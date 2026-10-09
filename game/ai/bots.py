"""Простые боты. RandomBot - случайные, но осмысленные команды: им проверяется, что
симуляция выдерживает что угодно (инварианты, повтор из записи, честность).

Скриптовые боты (раш, оборона, экономика) - scripted.py.
"""
import random

from game.core import commands as C
from game.core import rules
from game.ai.match import Controller


class RandomBot(Controller):
    name = "random"

    def __init__(self, n_commands=3):
        self.n_commands = n_commands

    def reset(self, player, seed):
        super().reset(player, seed)
        self.rng = random.Random(seed)

    def _cell(self, obs, near=None, r=6):
        rng = self.rng
        if near is None:
            return rng.randrange(obs.w), rng.randrange(obs.h)
        x = min(obs.w - 1, max(0, near[0] + rng.randint(-r, r)))
        y = min(obs.h - 1, max(0, near[1] + rng.randint(-r, r)))
        return x, y

    def decide(self, obs):
        rng = self.rng
        p = obs.player
        out = []
        units = list(obs.my_units)
        workers = [u for u in units if u.kind == "worker"]
        for _ in range(self.n_commands):
            roll = rng.random()
            if roll < 0.25 and units:
                grp = rng.sample(units, rng.randint(1, min(6, len(units))))
                out.append(C.move(p, [u.id for u in grp], self._cell(obs, (grp[0].x, grp[0].y), 10)))
            elif roll < 0.4 and workers and obs.crystals:
                (pos, _) = rng.choice(obs.crystals)
                grp = rng.sample(workers, rng.randint(1, min(3, len(workers))))
                out.append(C.harvest(p, [u.id for u in grp], pos))
            elif roll < 0.55 and obs.my_buildings:
                b = rng.choice(obs.my_buildings)
                if rules.BUILDINGS[b.kind]["trains"]:
                    out.append(C.train(p, b.id, rng.choice(rules.BUILDINGS[b.kind]["trains"])))
            elif roll < 0.65 and workers:
                w = rng.choice(workers)
                kind = rng.choice(sorted(rules.BUILDINGS))
                out.append(C.build(p, [w.id], kind, self._cell(obs, (w.x, w.y), 5)))
            elif roll < 0.8 and units and (obs.enemy_units or obs.enemy_buildings):
                targets = [e.id for e in obs.enemy_units] + [b.id for b in obs.enemy_buildings if b.visible]
                if targets:
                    grp = rng.sample(units, rng.randint(1, min(5, len(units))))
                    out.append(C.attack(p, [u.id for u in grp], rng.choice(targets)))
            elif roll < 0.9 and units:
                grp = rng.sample(units, rng.randint(1, min(8, len(units))))
                out.append(C.attack_move(p, [u.id for u in grp], self._cell(obs)))
            elif roll < 0.95 and units:
                out.append(C.stop(p, [rng.choice(units).id]))
            elif obs.my_buildings:
                b = rng.choice(obs.my_buildings)
                if rng.random() < 0.5:
                    out.append(C.cancel(p, b.id))
                else:
                    out.append(C.rally(p, b.id, self._cell(obs, (b.x, b.y), 6)))
        return out
