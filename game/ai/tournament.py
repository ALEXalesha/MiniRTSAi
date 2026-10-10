"""Турнир ИИ: N партий с зёрнами, стороны меняются (чётные - проверяемый играет за 0),
карты по кругу. Исход с точки зрения проверяемого: W, D, L (aikit.tournament).

Игрок - имя ("rush", "defense", "economy", "random") или словарь параметров стратегии.

    python -m game.ai.tournament rush economy 20          # быстрый замер
    python -m game.ai.tournament --round 12 --processes 2  # круговой турнир характеров
"""
import argparse
import os
import time

from aikit import tournament as T
from game.ai.match import play
from game.core import maps

MAPS = ("plains", "crossroads", "twin_passes")


def make(who):
    from game.ai.bots import RandomBot
    from game.ai.scripted import PRESETS, ScriptedBot
    if isinstance(who, dict):
        return ScriptedBot(params=who)
    if who == "random":
        return RandomBot()
    if who in PRESETS:
        return ScriptedBot(who)
    raise ValueError(f"неизвестный бот {who!r}")


def one_game(subject, opponent, i, seed, map_names=MAPS, max_ticks=None, apm=(None, None)):
    """Партия i: карта и стороны по номеру. Возвращает (исход, такты, рекордер)."""
    first = i % 2 == 0
    m = maps.get(map_names[(i // 2) % len(map_names)])
    a, b = make(subject), make(opponent)
    ctrls = [a, b] if first else [b, a]
    kw = {} if max_ticks is None else {"max_ticks": max_ticks}
    rec = play(m, ctrls, seed=seed * 7919 + i, apm=apm if first else apm[::-1], **kw)
    g = rec.game
    me = 0 if first else 1
    res = "D" if g.winner is None else ("W" if g.winner == me else "L")
    return res, g.tick, rec


def _job(args):
    subject, opponent, i, seed, kw = args
    r, t, _ = one_game(subject, opponent, i, seed, **kw)
    return r, t


def run_jobs(jobs, processes=1, pool=None):
    """jobs - [(subject, opponent, i, seed, kw)] -> [(исход, такты)]. Процессы - spawn, у
    каждого один поток BLAS (OPENBLAS_NUM_THREADS ставит вызывающий)."""
    if pool is not None:
        return pool.map(_job, jobs, chunksize=1)
    if processes > 1:
        import multiprocessing as mp
        with mp.get_context("spawn").Pool(processes) as p:
            return p.map(_job, jobs, chunksize=1)
    return [_job(j) for j in jobs]


def match(subject, opponent, games, seed=0, processes=1, pool=None, **kw):
    out = run_jobs([(subject, opponent, i, seed, kw) for i in range(games)], processes, pool)
    s = T.summary("".join(r for r, _ in out))
    s["mean_ticks"] = sum(t for _, t in out) / max(1, len(out))
    return s


def round_robin(names, games, seed=0, processes=1, pool=None):
    """Каждый с каждым: {(a, b): summary} для a < b по порядку names."""
    pairs = [(a, b) for i, a in enumerate(names) for b in names[i + 1:]]
    jobs = [(a, b, i, seed, {}) for a, b in pairs for i in range(games)]
    out = run_jobs(jobs, processes, pool)
    res = {}
    for k, (a, b) in enumerate(pairs):
        part = out[k * games:(k + 1) * games]
        s = T.summary("".join(r for r, _ in part))
        s["mean_ticks"] = sum(t for _, t in part) / max(1, len(part))
        res[(a, b)] = s
    return res


def main(argv=None):
    for var in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
        os.environ[var] = "1"
    ap = argparse.ArgumentParser(prog="python -m game.ai.tournament")
    ap.add_argument("pair", nargs="*")
    ap.add_argument("--round", type=int, default=0, help="круговой турнир, партий на пару")
    ap.add_argument("--processes", type=int, default=1)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args(argv)
    t0 = time.time()
    if args.round:
        res = round_robin(["rush", "defense", "economy"], args.round, args.seed, args.processes)
        for (a, b), s in res.items():
            print(f"{a:8} {b:8} {s['results']} доля {s['score']:.3f} "
                  f"средняя {s['mean_ticks'] / 600:.1f} мин")
    else:
        a, b = args.pair[0], args.pair[1]
        n = int(args.pair[2]) if len(args.pair) > 2 else 10
        s = match(a, b, n, args.seed, args.processes)
        print(f"{a} против {b}: {s['results']} доля {s['score']:.3f}, "
              f"средняя партия {s['mean_ticks'] / 600:.1f} мин игры")
    print(f"{time.time() - t0:.0f} с")


if __name__ == "__main__":
    main()
