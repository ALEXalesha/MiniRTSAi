"""Запись партии и повтор из записи.

Запись - карта целиком, зерно, настройки и команды по тактам (и принятые, и отброшенные:
при повторе симуляция отбросит их так же). Каждые CHECKPOINT тактов в запись кладётся
хэш состояния; повтор сверяет их и падает на первом расхождении с номером такта - так
сразу видно, где симуляция перестала быть детерминированной.
"""
import json

from game.core import rules
from game.core.commands import Command
from game.core.maps import GameMap
from game.core.sim import Game

FORMAT = 1
CHECKPOINT = 50


class ReplayMismatch(Exception):
    pass


class Recorder:
    """Партия с записью: вместо game.step(cmds) зовут recorder.step(cmds)."""

    def __init__(self, gmap, seed=0, fog=True, max_ticks=rules.MAX_TICKS,
                 start_resources=rules.START_RESOURCES, start_workers=rules.START_WORKERS,
                 meta=None):
        self.config = {"seed": seed, "fog": fog, "max_ticks": max_ticks,
                       "start_resources": start_resources, "start_workers": start_workers}
        self.map_json = gmap.to_json()
        self.game = Game(gmap, **self.config)
        self.commands = []
        self.hashes = {0: self.game.state_hash()}
        self.meta = dict(meta or {})

    def step(self, commands=()):
        t = self.game.tick
        for c in commands:
            self.commands.append([t] + c.to_json())
        self.game.step(commands)
        if self.game.tick % CHECKPOINT == 0 or self.game.over:
            self.hashes[self.game.tick] = self.game.state_hash()

    def to_json(self):
        g = self.game
        return {"format": FORMAT, "map": self.map_json, "config": self.config,
                "commands": self.commands,
                "hashes": {str(k): v for k, v in sorted(self.hashes.items())},
                "result": {"tick": g.tick, "over": g.over, "winner": g.winner,
                           "reason": g.end_reason},
                "meta": self.meta}

    def save(self, path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_json(), f, ensure_ascii=False, separators=(",", ":"))


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def commands_by_tick(rec):
    out = {}
    for row in rec["commands"]:
        out.setdefault(int(row[0]), []).append(Command.from_json(row[1:]))
    return out


def start(rec):
    """Новая партия с картой и настройками записи (такт 0)."""
    if rec.get("format") != FORMAT:
        raise ValueError(f"формат записи {rec.get('format')}, ждали {FORMAT}")
    return Game(GameMap.from_json(rec["map"]), **rec["config"])


def replay(rec, until=None, verify=True, on_tick=None):
    """Проиграть запись. until - остановиться на этом такте (для перемотки в окне).
    verify - сверять хэши; on_tick(game) - после каждого такта (окно рисует повтор)."""
    g = start(rec)
    cmds = commands_by_tick(rec)
    hashes = {int(k): v for k, v in rec.get("hashes", {}).items()}
    end = rec["result"]["tick"] if until is None else min(until, rec["result"]["tick"])
    if verify and 0 in hashes and hashes[0] != g.state_hash():
        raise ReplayMismatch("такт 0: начальное состояние другое")
    while g.tick < end and not g.over:
        g.step(cmds.get(g.tick, ()))
        if verify and g.tick in hashes and hashes[g.tick] != g.state_hash():
            raise ReplayMismatch(f"такт {g.tick}: состояние разошлось с записью")
        if on_tick is not None:
            on_tick(g)
    if verify and until is None:
        r = rec["result"]
        if (g.tick, g.over, g.winner) != (r["tick"], r["over"], r["winner"]):
            raise ReplayMismatch(f"итог другой: {(g.tick, g.over, g.winner)} против {r}")
    return g
