"""Скриптовые боты: дерево правил с числовыми параметрами. Три характера - раш, оборона,
экономика - отличаются только числами в PRESETS. Те же правила с подобранными числами
станут стратегией ИИ (план, шаг 6: эволюция в лиге).

Бот видит только Observation. Он не знает, где база врага, пока не увидит её; до тех пор
идёт к месту старта соперника - места баз на карте известны всем заранее.

Как бот думает (раз в несколько тактов):
1. свободных рабочих - на кристаллы у своей базы, поровну на клетку;
2. рабочих до workers, потом казармы и башни по очереди, когда хватает денег;
3. казармы учат бойцов, доля лучников - archers;
4. враг у базы - вся армия защищает; армия >= attack_at - атака на ближайшее известное
   здание врага (или на место его старта); армия растаяла до retreat_at - отход к базе.
"""
from game.core import commands as C
from game.core import rules
from game.ai.match import Controller

BASE = rules.BUILDINGS["base"]["size"]

PRESETS = {
    # рабочих, казарм, башен, доля лучников, армия для атаки, отход при армии меньше,
    # с какой армии строить башни, разведка (такт, 0 - нет)
    "rush":    dict(workers=5,  barracks=1, towers=0, archers=0.25, attack_at=4,
                    retreat_at=1, tower_after=99, scout_at=0),
    "defense": dict(workers=8,  barracks=1, towers=2, archers=0.6,  attack_at=12,
                    retreat_at=5, tower_after=0, scout_at=600),
    "economy": dict(workers=12, barracks=2, towers=1, archers=0.5,  attack_at=14,
                    retreat_at=6, tower_after=4, scout_at=900),
}

PLAN_RU = {"economy": "развиваю экономику", "army": "коплю армию", "attack": "атакую",
           "defend": "защищаю базу", "retreat": "отступаю"}


def d2(a, b):
    return (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2


class ScriptedBot(Controller):
    def __init__(self, character="rush", **overrides):
        self.character = character
        self.params = dict(PRESETS[character])
        self.params.update(overrides)
        self.name = character

    def reset(self, player, seed):
        super().reset(player, seed)
        self.mode = "economy"
        self.target = None
        self.scouted = False
        self.explore = 0
        self.home = None
        self.enemy_start = None
        self.last = {}

    # ----- что известно -----

    def _setup(self, obs):
        if self.home is None:
            sx, sy = obs.starts[obs.player]
            self.home = (sx + 1, sy + 1)
            ex, ey = obs.starts[1 - obs.player] if len(obs.starts) > 1 else (obs.w // 2, obs.h // 2)
            self.enemy_start = (ex + 1, ey + 1)

    def _base_center(self, obs):
        bases = [b for b in obs.my_buildings if b.kind == "base"]
        if bases:
            b = min(bases, key=lambda b: (d2((b.x, b.y), self.home), b.id))
            return (b.x + 1, b.y + 1)
        return self.home

    def _sites(self, obs, kind, near, toward=None):
        """Место под здание: всё разведано и свободно, вокруг кольцо свободных клеток (не
        запираем проходы), не вплотную к кристаллам. Ближе к near, при равенстве - к toward."""
        size = rules.BUILDINGS[kind]["size"]
        blocked = obs.known_blocked()
        w, h = obs.w, obs.h
        units = {(u.x, u.y) for u in obs.my_units}
        crystals = [p for p, _ in obs.crystals]
        cx, cy = near
        best = None
        for r in range(3, 11):
            for y in range(cy - r, cy + r + 1):
                for x in range(cx - r, cx + r + 1):
                    if max(abs(x - cx), abs(y - cy)) != r:
                        continue
                    if x < 1 or y < 1 or x + size >= w or y + size >= h:
                        continue
                    ok = True
                    for yy in range(y - 1, y + size + 1):
                        for xx in range(x - 1, x + size + 1):
                            i = yy * w + xx
                            if blocked[i] or obs.terrain[i] == 2:
                                ok = False
                                break
                            if x <= xx < x + size and y <= yy < y + size and (xx, yy) in units:
                                ok = False
                                break
                        if not ok:
                            break
                    if not ok:
                        continue
                    if any(abs(px - x - size // 2) <= 2 and abs(py - y - size // 2) <= 2
                           for px, py in crystals):
                        continue
                    k = (d2((x, y), near), d2((x, y), toward) if toward else 0, y, x)
                    if best is None or k < best[0]:
                        best = (k, (x, y))
            if best is not None:
                return best[1]
        return None

    # ----- решение -----

    def decide(self, obs):
        self._setup(obs)
        p = obs.player
        P = self.params
        out = []
        base = self._base_center(obs)
        workers = [u for u in obs.my_units if u.kind == "worker"]
        army = [u for u in obs.my_units if u.kind in rules.COMBAT]
        bases = [b for b in obs.my_buildings if b.kind == "base" and not b.built]
        barracks = [b for b in obs.my_buildings if b.kind == "barracks"]
        towers = [b for b in obs.my_buildings if b.kind == "tower"]
        money = obs.resources

        # 1. экономика: свободные рабочие на кристаллы у базы
        near_crystals = [(pos, a) for pos, a in obs.crystals if d2(pos, base) <= 14 ** 2]
        if not near_crystals and obs.crystals:
            # у базы всё выбрано - ближайшее известное поле, носить дальше
            far = min(obs.crystals, key=lambda c: (d2(c[0], base), c[0]))[0]
            near_crystals = [(pos, a) for pos, a in obs.crystals if d2(pos, far) <= 6 ** 2]
        idle_workers = [u for u in workers if u.order == "idle"]
        if not obs.crystals and idle_workers:
            # кристаллов не знаем: один рабочий идёт смотреть карту (центр, потом сторона врага)
            spots = [(obs.w // 2, obs.h // 2), (obs.w // 4, obs.h * 3 // 4),
                     (obs.w * 3 // 4, obs.h // 4), self.enemy_start]
            spot = spots[self.explore % len(spots)]
            self.explore += 1
            out.append(C.move(p, [idle_workers[0].id], spot))
        load = {}
        for u in workers:
            if u.order == "harvest" and u.pos is not None:
                load[u.pos] = load.get(u.pos, 0) + 1
        for u in workers:
            if u.order == "idle" and near_crystals:
                pos = min(near_crystals, key=lambda c: (load.get(c[0], 0), d2(c[0], (u.x, u.y)), c[0]))[0]
                load[pos] = load.get(pos, 0) + 1
                out.append(C.harvest(p, [u.id], pos))

        # 2. рабочие
        queued_workers = sum(b.queue.count("worker") for b in bases)
        if bases and len(workers) + queued_workers < P["workers"] and money >= rules.UNITS["worker"]["cost"]:
            b = min(bases, key=lambda b: (len(b.queue), b.id))
            if len(b.queue) < 1:
                out.append(C.train(p, b.id, "worker"))
                money -= rules.UNITS["worker"]["cost"]

        # 3. стройка: одна закладка за раз
        building_now = any(u.order == "build" for u in workers)
        want = None
        enough_workers = len(workers) >= min(P["workers"], 4)
        if not building_now and enough_workers and workers:
            if len(barracks) < P["barracks"]:
                want = "barracks"
            elif len(towers) < P["towers"] and len(army) >= P["tower_after"]:
                want = "tower"
        if want and money >= rules.BUILDINGS[want]["cost"]:
            site = self._sites(obs, want, base, self.enemy_start)
            if site is not None:
                builder = min(workers, key=lambda u: (u.carry > 0, d2((u.x, u.y), site), u.id))
                out.append(C.build(p, [builder.id], want, site))
                money -= rules.BUILDINGS[want]["cost"]

        # 4. армия
        n_arch = sum(1 for u in army if u.kind == "archer")
        for b in barracks:
            if b.built or b.queue:
                continue
            total = len(army) + 1
            kind = "archer" if n_arch < P["archers"] * total else "swordsman"
            if money >= rules.UNITS[kind]["cost"]:
                out.append(C.train(p, b.id, kind))
                money -= rules.UNITS[kind]["cost"]
                n_arch += kind == "archer"
            if b.rally is None:
                # сбор в двух клетках от казармы в сторону врага
                rx = b.x + (3 if self.enemy_start[0] > b.x else -2)
                ry = b.y + (3 if self.enemy_start[1] > b.y else -2)
                out.append(C.rally(p, b.id, (max(0, min(obs.w - 1, rx)), max(0, min(obs.h - 1, ry)))))

        # 5. разведка: один рабочий к месту старта врага
        if P["scout_at"] and not self.scouted and obs.tick >= P["scout_at"] and len(workers) > 3:
            scout = max(workers, key=lambda u: (u.carry == 0, u.id))
            out.append(C.move(p, [scout.id], self.enemy_start))
            self.scouted = True

        # 6. бой
        # денег нет и взять негде: копить больше нечего, армия идёт в бой
        broke = ((not obs.crystals or not workers)
                 and money < min(u["cost"] for u in rules.UNITS.values()))
        threats = [e for e in obs.enemy_units if d2((e.x, e.y), base) <= 12 ** 2]
        known = [b for b in obs.enemy_buildings]
        if broke and not army and workers and not obs.crystals:
            # карта выработана, армии нет: рабочие - последняя сила
            self.mode = "attack"
            self._order_army(out, p, workers, self._attack_target(known))
            return out
        if threats and army:
            self.mode = "defend"
            t = min(threats, key=lambda e: (d2((e.x, e.y), base), e.id))
            self._order_army(out, p, army, (t.x, t.y))
        elif self.mode == "attack":
            if len(army) <= P["retreat_at"] and not broke:      # без денег - до конца
                self.mode = "retreat"
                self._order_army(out, p, army, base, kind="move")
            else:
                tgt = self._attack_target(known)
                self._order_army(out, p, army, tgt)
        elif len(army) >= P["attack_at"] or (army and broke):
            self.mode = "attack"
            self._order_army(out, p, army, self._attack_target(known))
        else:
            self.mode = "army" if barracks else "economy"
            idle_far = [u for u in army if u.order == "idle" and d2((u.x, u.y), base) > 10 ** 2]
            if idle_far:
                out.append(C.move(p, [u.id for u in idle_far], base))
        return out

    def _attack_target(self, known):
        if known:
            # ближе к своей базе - сначала то, что по пути
            b = min(known, key=lambda b: (b.kind != "tower" and b.kind != "barracks",
                                         d2((b.x, b.y), self.home), b.id))
            return (b.x, b.y)
        return self.enemy_start

    def _order_army(self, out, p, army, pos, kind="attack_move"):
        """Команда только тем, у кого другой приказ: не тратить действия впустую."""
        order = "amove" if kind == "attack_move" else "move"
        need = [u for u in army if not (u.order == order and u.pos == tuple(pos))
                and not (order == "amove" and u.order == "attack")]
        if need:
            self.target = tuple(pos)
            make = C.attack_move if kind == "attack_move" else C.move
            out.append(make(p, [u.id for u in need], pos))

    def thoughts(self):
        return {"plan": PLAN_RU.get(self.mode, self.mode), "mode": self.mode,
                "target": self.target, "character": self.character}
