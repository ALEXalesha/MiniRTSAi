"""Проверки симуляции для самопроверки (main.py --selftest)."""
import time


def run_checks():
    from game.ai.bots import RandomBot
    from game.ai.match import play
    from game.core import maps
    from game.core import record as R
    out = []
    t0 = time.time()
    rec = play(maps.get("plains"), [RandomBot(), RandomBot()], seed=1, max_ticks=300)
    g = R.replay(rec.to_json())
    if g.state_hash() != rec.game.state_hash():
        raise AssertionError("повтор из записи разошёлся с партией")
    out.append(f"симуляция: 300 тактов случайных команд и повтор из записи совпали, "
               f"{time.time() - t0:.1f} с")
    return out
