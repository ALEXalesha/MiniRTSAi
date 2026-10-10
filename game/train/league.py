"""Эволюция стратегии в лиге (CEM - метод перекрёстной энтропии).

Стратегия - числа ScriptedBot (game.ai.scripted.SPACE). В эволюции каждое число живёт в
отрезке [0, 1] (0 - нижняя граница, 1 - верхняя), там же гауссово облако кандидатов:
середина mu и разброс sigma по каждому числу.

Поколение:
1. из облака берутся population кандидатов;
2. каждый играет одни и те же партии (одинаковые зёрна, карты и стороны - сравнение
   честное): против трёх характеров (раш, оборона, экономика) и против чемпионов прошлых
   поколений (зал славы);
3. оценка кандидата - половина средней доли очков и половина доли против худшего
   соперника; лучшая четверть (элита) задаёт новые mu и sigma; к sigma добавляется шум, который
   убывает, чтобы облако не схлопнулось раньше времени;
4. лучший кандидат поколения - в зал славы (не больше hall_size последних).

После каждого поколения строка в журнал и снимок (atomic): обучение продолжается с места
(--resume). Потоки: процессов --processes (по умолчанию 2), в каждом один поток BLAS.
"""
import json
import os
import time

import numpy as np

from game.ai.scripted import PRESETS, SPACE, clip_params  # noqa: F401

KEYS = tuple(SPACE)
CHARACTERS = ("rush", "defense", "economy")


def to_unit(params):
    """Параметры -> вектор в [0, 1]."""
    out = []
    for k in KEYS:
        lo, hi, _ = SPACE[k]
        out.append((min(hi, max(lo, params[k])) - lo) / (hi - lo))
    return np.array(out, dtype=np.float64)


def from_unit(vec):
    """Вектор (любой) -> допустимые параметры: обрезка в [0, 1], округление целых."""
    raw = {}
    for k, v in zip(KEYS, vec):
        lo, hi, _ = SPACE[k]
        raw[k] = lo + float(min(1.0, max(0.0, v))) * (hi - lo)
    return clip_params(raw)


class League:
    def __init__(self, run_dir, population=12, games_per_opponent=4, hall_size=2,
                 elite_frac=0.25, sigma0=0.25, noise0=0.08, noise_decay=0.9, seed=0,
                 start="mix", hall_games=2):
        self.run_dir = run_dir
        self.population = population
        self.games_per_opponent = games_per_opponent   # против каждого характера
        self.hall_games = hall_games                   # против каждого чемпиона
        self.hall_size = hall_size
        self.elite_frac = elite_frac
        self.noise0 = noise0
        self.noise_decay = noise_decay
        self.seed = seed
        self.gen = 0
        if start == "mix":
            # середина между тремя характерами: поиск не начинает с одной крайности
            self.mu = np.mean([to_unit(clip_params(p)) for p in PRESETS.values()], axis=0)
        else:
            self.mu = to_unit(clip_params(PRESETS[start]))
        self.sigma = np.full(len(KEYS), sigma0)
        self.hall = []              # параметры чемпионов (словари)
        self.history = []           # по поколению: лучшая и средняя доля, время
        self.elapsed = 0.0

    # ----- снимок -----

    @property
    def snap_path(self):
        return os.path.join(self.run_dir, "league.json")

    def state(self):
        return {"gen": self.gen, "mu": self.mu.tolist(), "sigma": self.sigma.tolist(),
                "hall": self.hall, "history": self.history, "elapsed": self.elapsed,
                "config": {"population": self.population,
                           "games_per_opponent": self.games_per_opponent,
                           "hall_games": self.hall_games,
                           "hall_size": self.hall_size, "elite_frac": self.elite_frac,
                           "noise0": self.noise0, "noise_decay": self.noise_decay,
                           "seed": self.seed}}

    def save(self):
        os.makedirs(self.run_dir, exist_ok=True)
        tmp = self.snap_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.state(), f, ensure_ascii=False, indent=1)
        os.replace(tmp, self.snap_path)

    def load(self):
        with open(self.snap_path, encoding="utf-8") as f:
            s = json.load(f)
        self.gen = s["gen"]
        self.mu = np.array(s["mu"])
        self.sigma = np.array(s["sigma"])
        self.hall = s["hall"]
        self.history = s["history"]
        self.elapsed = s["elapsed"]
        for k, v in s["config"].items():
            setattr(self, k, v)
        return self

    # ----- поколение -----

    def opponents(self):
        return list(CHARACTERS) + [dict(h) for h in self.hall]

    def candidates(self):
        """Кандидаты поколения: зерно (seed, gen) - повтор с места даёт тех же."""
        rng = np.random.default_rng([self.seed, self.gen])
        vecs = self.mu + self.sigma * rng.standard_normal((self.population, len(KEYS)))
        vecs[0] = self.mu                          # середина облака играет всегда
        return [from_unit(v) for v in vecs], vecs

    def jobs(self, cands):
        """Одинаковые партии для всех кандидатов: номер партии задаёт карту и сторону."""
        out = []
        for ci, c in enumerate(cands):
            i = 0
            for oi, opp in enumerate(self.opponents()):
                n = self.games_per_opponent if oi < len(CHARACTERS) else self.hall_games
                for _ in range(n):
                    out.append((ci, oi, (c, opp, i, self.seed * 100003 + self.gen, {})))
                    i += 1
        return out

    def step(self, evaluate, log=None):
        """Одно поколение. evaluate(список jobs) -> [(исход, такты)]."""
        t0 = time.time()
        cands, vecs = self.candidates()
        jobs = self.jobs(cands)
        results = evaluate([j for _, _, j in jobs])
        n_opp = len(self.opponents())
        got = np.zeros((len(cands), n_opp))
        cnt = np.zeros((len(cands), n_opp))
        ticks = []
        for (ci, oi, _), (r, t) in zip(jobs, results):
            got[ci, oi] += {"W": 1.0, "D": 0.5, "L": 0.0}[r]
            cnt[ci, oi] += 1
            ticks.append(t)
        per_opp = got / np.maximum(cnt, 1)
        # сила - не только в среднем: половина оценки - худший соперник. Иначе лига
        # находит «сверхэкономику», которая бьёт всех, кроме раша (первый запуск: 13%)
        scores = 0.5 * per_opp.mean(axis=1) + 0.5 * per_opp.min(axis=1)
        order = np.argsort(-scores, kind="stable")
        n_elite = max(2, int(round(self.population * self.elite_frac)))
        elite = vecs[order[:n_elite]]
        noise = self.noise0 * (self.noise_decay ** self.gen)
        self.mu = np.clip(elite.mean(axis=0), 0.0, 1.0)
        self.sigma = elite.std(axis=0) + noise
        best = cands[order[0]]
        self.hall = (self.hall + [best])[-self.hall_size:]
        dt = time.time() - t0
        self.elapsed += dt
        rec = {"gen": self.gen, "best": float(scores[order[0]]), "mean": float(scores.mean()),
               "best_vs": [round(float(x), 3) for x in per_opp[order[0]]],
               "games": len(jobs), "seconds": round(dt, 1),
               "mean_minutes": round(float(np.mean(ticks)) / 600, 2) if ticks else 0.0}
        self.history.append(rec)
        self.gen += 1
        if log is not None:
            log(f"поколение {rec['gen']}: лучший {rec['best']:.3f} {rec['best_vs']}, средний {rec['mean']:.3f}, "
                f"{rec['games']} партий за {dt:.0f} с; середина {self.center()}")
        return rec

    def center(self):
        return from_unit(self.mu)
