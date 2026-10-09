"""Турнир ИИ: N партий с зёрнами, стороны меняются (чётные - проверяемый играет за 0),
карты по кругу. Исход с точки зрения проверяемого: W, D, L (aikit.tournament).

    python -m game.ai.tournament rush economy 20     # быстрый замер из командной строки
"""
import sys
import time

from aikit import tournament as T
from game.ai.match import play
from game.core import maps

MAPS = ("plains", "crossroads", "twin_passes")


def make(name):
    from game.ai.bots import RandomBot
    from game.ai.scripted import PRESETS, ScriptedBot
    if name == "random":
        return RandomBot()
    if name in PRESETS:
        return ScriptedBot(name)
    raise ValueError(f"неизвестный бот {name!r}")


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


def match(subject, opponent, games, seed=0, **kw):
    results, ticks = [], []
    for i in range(games):
        r, t, _ = one_game(subject, opponent, i, seed, **kw)
        results.append(r)
        ticks.append(t)
    s = T.summary("".join(results))
    s["mean_ticks"] = sum(ticks) / max(1, len(ticks))
    return s


def main(argv):
    a, b = argv[1], argv[2]
    n = int(argv[3]) if len(argv) > 3 else 10
    t0 = time.time()
    s = match(a, b, n)
    print(f"{a} против {b}: {s['results']} доля {s['score']:.3f}, "
          f"средняя партия {s['mean_ticks'] / 600:.1f} мин игры, {time.time() - t0:.0f} с")


if __name__ == "__main__":
    main(sys.argv)
