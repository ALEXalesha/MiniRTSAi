"""Паспорт стратегии: числа из лиги и проверка силы против характеров и случайного бота.

Партии паспорта идут с зерном PASSPORT_SEED, номер партии задаёт карту и сторону, поэтому
тесты пересчитывают первые партии и сверяют исходы с паспортом.
"""
import json
import os
import time

from aikit import tournament as T
from game.ai import tournament
from game.version import VERSION

MODEL_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "models")
STRATEGY = os.path.join(MODEL_DIR, "strategy.json")
PASSPORT_SEED = 777
OPPONENTS = ("rush", "defense", "economy", "random")


def check(params, games, pool=None, processes=1):
    out = {}
    for opp in OPPONENTS:
        n = games if opp != "random" else max(2, games // 5)
        res = tournament.run_jobs([(params, opp, i, PASSPORT_SEED, {}) for i in range(n)],
                                  processes, pool)
        s = T.summary("".join(r for r, _ in res))
        s["mean_minutes"] = round(sum(t for _, t in res) / max(1, len(res)) / 600, 2)
        out[opp] = s
    return out


def publish(league, games, pool=None, path=STRATEGY):
    params = league.center()
    t0 = time.time()
    passport = check(params, games, pool)
    data = {"version": VERSION, "params": params, "generation": league.gen,
            "training_minutes": round(league.elapsed / 60, 1),
            "history": league.history,
            "passport_seed": PASSPORT_SEED, "passport": passport,
            "passport_minutes": round((time.time() - t0) / 60, 1)}
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)
    return path


def load(path=STRATEGY):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None
