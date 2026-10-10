"""Симуляция партии: фиксированный такт, только целые числа, никакого времени и случайности
вне зерна. Одинаковые карта, зерно и команды по тактам дают одинаковую партию до бита -
на этом стоят запись и повтор (record.py) и честные турниры ИИ.

Как устроен такт (Game.step):
1. команды игроков проверяются по тому, что игрок видел в конце прошлого такта, и меняют
   приказы юнитов и очереди зданий;
2. здания: обучение, стрельба башен;
3. юниты по возрастанию номера (в нечётные такты - по убыванию, чтобы ни у кого не было
   постоянного права первого хода): движение, бой, добыча, стройка;
4. гибель: убитые убираются разом, поэтому удары одного такта не зависят от порядка;
5. туман войны, проверка победы.

Юнит стоит в одной клетке. Шаг занимает несколько тактов (rules.UNITS move), клетка
занимается сразу в начале шага - окно рисует движение плавно по px, py и busy.
"""
from game.core import path as pathing
from game.core import rules
from game.core.commands import Command
from game.core.fog import Fog
from game.core.maps import GameMap, passable_cells

UNIT_FIELDS = ("id", "owner", "kind", "x", "y", "hp", "px", "py", "busy", "move_total", "atk",
               "order", "o_pos", "o_target", "o_kind", "o_n", "o_anchor", "auto", "path",
               "path_goal", "repath_at", "blocked", "want", "carry", "work", "wait")
BUILDING_FIELDS = ("id", "owner", "kind", "x", "y", "hp", "built", "build_total", "hp0",
                   "queue", "train_left", "rally", "atk")

FORCE_SWAP = 8          # тактов в тупике, после которых свой юнит меняется местами всегда
REPATH_AT = (4, 12, 30)  # на этих тактах тупика - путь в обход юнитов рядом
GIVE_UP = 80            # тактов без шага: приказ «идти» снимается (дошли, насколько можно)
GIVE_UP_GROUP = 40      # то же для группы у цели: толпа плотная, ближе не протиснуться
FIELD_REFRESH = 30      # устаревшее потоковое поле живёт столько тактов
REPATH_MOVING = 5       # погоня: путь к движущейся цели пересчитывается не чаще


class Entity:
    """Юнит или здание. Поля юнита и здания общие, чтобы окно и ИИ читали их одинаково."""
    __slots__ = UNIT_FIELDS + ("building", "size", "max_hp", "sight", "built", "build_total",
                               "hp0", "queue", "train_left", "rally")

    def __init__(self, eid, owner, kind, x, y):
        self.id, self.owner, self.kind, self.x, self.y = eid, owner, kind, x, y
        st = rules.stats(kind)
        self.building = rules.is_building(kind)
        self.size = st["size"] if self.building else 1
        self.max_hp = self.hp = st["hp"]
        self.sight = st["sight"]
        self.px, self.py = x, y
        self.busy = self.move_total = self.atk = 0
        self.order = "idle"
        self.o_pos = self.o_target = self.o_kind = self.o_anchor = None
        self.o_n = 1
        self.auto = False
        self.path = []
        self.path_goal = None
        self.repath_at = 0
        self.blocked = 0
        self.want = -1
        self.carry = 0
        self.work = None
        self.wait = 0
        self.built = self.build_total = self.hp0 = 0
        self.queue = []
        self.train_left = 0
        self.rally = None

    def rect(self):
        s = self.size - 1
        return (self.x, self.y, self.x + s, self.y + s)

    def key(self):
        fields = BUILDING_FIELDS if self.building else UNIT_FIELDS
        out = []
        for f in fields:
            v = getattr(self, f)
            out.append(tuple(v) if isinstance(v, list) else v)
        return tuple(out)


class Player:
    __slots__ = ("index", "resources", "stats")

    def __init__(self, index, resources):
        self.index = index
        self.resources = resources
        self.stats = {"gathered": 0, "spent": 0, "made": 0, "lost": 0, "killed": 0,
                      "buildings_lost": 0, "buildings_killed": 0, "rejected": 0}

    def key(self):
        return (self.index, self.resources, tuple(sorted(self.stats.items())))


def _xorshift(s):
    s ^= (s << 13) & 0xFFFFFFFF
    s ^= s >> 17
    s ^= (s << 5) & 0xFFFFFFFF
    return s & 0xFFFFFFFF


def arrival_radius(n):
    """Сколько клеток вокруг цели хватает группе из n юнитов: квадрат (2r+1)^2 >= n."""
    r = 0
    while (2 * r + 1) ** 2 < n:
        r += 1
    return r


class Game:
    def __init__(self, gmap: GameMap, seed=0, fog=True, max_ticks=rules.MAX_TICKS,
                 start_resources=rules.START_RESOURCES, start_workers=rules.START_WORKERS,
                 victory=True):
        self.map = gmap.copy()
        self.victory = victory      # False - партия без конца (проверки поиска пути)
        self.w, self.h = gmap.w, gmap.h
        self.seed = seed
        self.max_ticks = max_ticks
        self.tick = 0
        self.over = False
        self.winner = None
        self.end_reason = None     # destroyed, points_buildings, points_army, draw
        self.crystals = dict(gmap.crystals)
        self.blocked = passable_cells(gmap)          # стены, кристаллы, здания
        self.unit_at = [0] * (self.w * self.h)
        self.bld_at = [0] * (self.w * self.h)
        self.ents = {}
        self.players = [Player(i, start_resources) for i in range(max(2, len(gmap.starts)))]
        self.static_version = 0
        self._fields = {}
        self.adj = pathing.build_adj(self.w, self.h, self.blocked)
        self._ids = (seed * 2654435761 + 0x9E3779B9) & 0xFFFFFFFF or 1
        self.fog = Fog(self.w, self.h, len(self.players), enabled=fog)
        self.events = []       # (такт, вид, ...) для окна и «Мыслей ИИ»; в хэш не входит
        for p, (bx, by) in enumerate(gmap.starts):
            base = self._add_building(p, "base", bx, by)
            base.built = 0
            base.hp = base.max_hp
            for _ in range(start_workers):
                cell = self._spawn_cell(base)
                if cell is not None:
                    self._add_unit(p, "worker", *cell)
        self.fog.update(self)

    # ----- служебное -----

    def _new_id(self):
        while True:
            self._ids = _xorshift(self._ids)
            eid = self._ids & 0x7FFFFFFF
            if eid and eid not in self.ents:
                return eid

    def size_of(self, kind):
        return rules.BUILDINGS[kind]["size"] if kind in rules.BUILDINGS else 1

    def units_list(self, owner=None):
        return [e for e in self.ents.values() if not e.building and (owner is None or e.owner == owner)]

    def buildings_list(self, owner=None):
        return [e for e in self.ents.values() if e.building and (owner is None or e.owner == owner)]

    def population(self, owner):
        return sum(1 for e in self.ents.values() if e.owner == owner and not e.building)

    def entity_at(self, x, y):
        i = y * self.w + x
        eid = self.unit_at[i] or self.bld_at[i]
        return self.ents.get(eid) if eid else None

    def _add_unit(self, owner, kind, x, y):
        u = Entity(self._new_id(), owner, kind, x, y)
        self.ents[u.id] = u
        self.unit_at[y * self.w + x] = u.id
        return u

    def _add_building(self, owner, kind, x, y):
        b = Entity(self._new_id(), owner, kind, x, y)
        st = rules.BUILDINGS[kind]
        b.build_total = b.built = st["build"]
        b.hp0 = b.hp = max(1, st["hp"] // 10)
        self.ents[b.id] = b
        for yy in range(y, y + b.size):
            for xx in range(x, x + b.size):
                i = yy * self.w + xx
                self.bld_at[i] = b.id
                self.blocked[i] = 1
        self._static_changed([(xx, yy) for yy in range(y, y + b.size) for xx in range(x, x + b.size)])
        return b

    def _finish_building(self, b):
        b.built = 0          # урон, полученный при стройке, остаётся: hp рос по ходу работы
        self.events.append((self.tick, "built", b.id))

    def _static_changed(self, cells):
        self.static_version += 1
        pathing.update_adj(self.adj, self.w, self.h, self.blocked, cells)

    def field(self, owner, target):
        """Потоковое поле к клетке target: одно на все группы игрока с этой целью.

        После изменения карты поле не выбрасывается сразу: новые здания и стены всё равно
        не пройти (can_step), а освободившиеся клетки поле просто не знает. Устаревшее поле
        пересчитывается не чаще раза в FIELD_REFRESH тактов - кристаллы кончаются часто, а
        поле на 48x48 стоит миллисекунды. Кэш у каждого игрока свой: движение его юнитов
        не зависит от того, куда враг посылал своих."""
        key = (owner, target)
        entry = self._fields.get(key)
        if entry is not None:
            version, made, f = entry
            if version == self.static_version or self.tick - made < FIELD_REFRESH:
                return f
        if entry is None and len(self._fields) >= 64:
            self._fields.clear()
        f = pathing.FlowField(self.adj, self.w, self.h, self.blocked, target)
        self._fields[key] = (self.static_version, self.tick, f)
        return f

    def footprint_free(self, kind, x, y):
        s = self.size_of(kind)
        if x < 0 or y < 0 or x + s > self.w or y + s > self.h:
            return False
        return all(not self.blocked[yy * self.w + xx]
                   for yy in range(y, y + s) for xx in range(x, x + s))

    def _spawn_cell(self, b, toward=None):
        """Свободная клетка у здания: ближайшая к центру (или к точке сбора), порядок задан."""
        x0, y0, x1, y1 = b.rect()
        cx2, cy2 = x0 + x1, y0 + y1
        for r in range(1, 6):
            cells = []
            for y in range(y0 - r, y1 + r + 1):
                for x in range(x0 - r, x1 + r + 1):
                    if max(x0 - x, x - x1, y0 - y, y - y1) != r:
                        continue
                    if 0 <= x < self.w and 0 <= y < self.h:
                        i = y * self.w + x
                        if not self.blocked[i] and not self.unit_at[i]:
                            if toward is not None:
                                k = (toward[0] - x) ** 2 + (toward[1] - y) ** 2
                            else:
                                k = (2 * x - cx2) ** 2 + (2 * y - cy2) ** 2
                            cells.append((k, y, x))
            if cells:
                _, y, x = min(cells)
                return x, y
        return None

    def visible_to(self, player, e):
        return self.fog.sees_entity(player, e)

    # ----- команды -----

    def apply_command(self, c: Command):
        """Проверить и применить команду. Возвращает True, если принята."""
        ok = self._command(c)
        if not ok and 0 <= c.player < len(self.players):
            self.players[c.player].stats["rejected"] += 1
        return ok

    def _own_units(self, c, workers=False):
        out = []
        seen = set()
        for uid in c.units:
            e = self.ents.get(uid)
            if e is None or e.owner != c.player or e.building or uid in seen:
                continue
            if workers and e.kind != "worker":
                continue
            seen.add(uid)
            out.append(e)
        return out

    def _in_map(self, pos):
        return (pos is not None and len(pos) == 2 and 0 <= pos[0] < self.w
                and 0 <= pos[1] < self.h)

    def _command(self, c):
        if self.over or not (0 <= c.player < len(self.players)):
            return False
        k = c.kind
        if k in ("train", "cancel", "rally"):
            if len(c.units) != 1:
                return False
            b = self.ents.get(c.units[0])
            if b is None or not b.building or b.owner != c.player or b.built:
                return False
            pl = self.players[c.player]
            if k == "train":
                if c.arg not in rules.BUILDINGS[b.kind]["trains"] or len(b.queue) >= rules.QUEUE_MAX:
                    return False
                cost = rules.UNITS[c.arg]["cost"]
                if pl.resources < cost:
                    return False
                pl.resources -= cost
                pl.stats["spent"] += cost
                if not b.queue:
                    b.train_left = rules.UNITS[c.arg]["train"]
                b.queue.append(c.arg)
                return True
            if k == "cancel":
                if not b.queue:
                    return False
                kind = b.queue.pop()
                pl.resources += rules.UNITS[kind]["cost"]
                pl.stats["spent"] -= rules.UNITS[kind]["cost"]
                if not b.queue:
                    b.train_left = 0
                return True
            if not self._in_map(c.pos):
                return False
            b.rally = tuple(c.pos)
            return True
        units = self._own_units(c, workers=k in ("harvest", "build"))
        if not units:
            return False
        if k == "stop":
            for u in units:
                self._set_order(u, "idle")
            return True
        if k in ("move", "attack_move"):
            if not self._in_map(c.pos):
                return False
            order = "move" if k == "move" else "amove"
            for u in units:
                self._set_order(u, order, pos=tuple(c.pos), n=len(units))
            return True
        if k == "attack":
            t = self.ents.get(c.target)
            if t is None or t.owner == c.player or not self.visible_to(c.player, t):
                return False
            for u in units:
                self._set_order(u, "attack", target=t.id)
            return True
        if k == "harvest":
            pos = tuple(c.pos) if self._in_map(c.pos) else None
            if pos is None or pos not in self.fog.crystals[c.player]:
                return False
            for u in units:
                self._set_order(u, "harvest", pos=pos)
            return True
        if k == "build":
            if c.arg not in rules.BUILDINGS or not self._in_map(c.pos):
                return False
            x, y = c.pos
            s = self.size_of(c.arg)
            if x + s > self.w or y + s > self.h:
                return False
            if not self.fog.explored[c.player][y:y + s, x:x + s].all():
                return False
            existing = self.ents.get(self.bld_at[y * self.w + x])
            target = None
            if existing is not None:
                if (existing.owner == c.player and existing.kind == c.arg and existing.built
                        and (existing.x, existing.y) == (x, y)):
                    target = existing.id
                else:
                    return False
            for u in units:
                self._set_order(u, "build", pos=(x, y), kind=c.arg, target=target)
            return True
        return False

    def _set_order(self, u, order, pos=None, target=None, kind=None, n=1, auto=False):
        if u.work == "harvest":
            u.work = None
            u.busy = 0
        u.order = order
        u.o_pos, u.o_target, u.o_kind, u.o_n = pos, target, kind, n
        u.o_anchor = (u.x, u.y) if auto else None
        u.auto = auto
        u.path = []
        u.path_goal = None
        u.blocked = 0
        u.wait = 0
        u.want = -1

    # ----- такт -----

    def step(self, commands=()):
        if self.over:
            return
        for c in commands:
            self.apply_command(c)
        ids = sorted(self.ents)
        if self.tick % 2:
            ids.reverse()
        for eid in ids:
            e = self.ents.get(eid)
            if e is not None and e.building:     # убитый в этом такте тоже бьёт: удары
                self._act_building(e)            # одного такта одновременны
        for eid in ids:
            e = self.ents.get(eid)
            if e is not None and not e.building:
                self._act_unit(e)
        self._deaths()
        if len(self.events) > 2000:
            del self.events[:1000]
        self.tick += 1
        self.fog.update(self)
        self._check_over()

    def _deaths(self):
        dead = [e for e in self.ents.values() if e.hp <= 0]
        dead.sort(key=lambda e: e.id)
        for e in dead:
            del self.ents[e.id]
            pl = self.players[e.owner]
            if e.building:
                for yy in range(e.y, e.y + e.size):
                    for xx in range(e.x, e.x + e.size):
                        i = yy * self.w + xx
                        self.bld_at[i] = 0
                        self.blocked[i] = 0
                self._static_changed([(xx, yy) for yy in range(e.y, e.y + e.size)
                                      for xx in range(e.x, e.x + e.size)])
                pl.stats["buildings_lost"] += 1   # очередь сгорает без возврата цены
            else:
                self.unit_at[e.y * self.w + e.x] = 0
                pl.stats["lost"] += 1
            for other in self.players:
                if other.index != e.owner:
                    other.stats["buildings_killed" if e.building else "killed"] += 1
            self.events.append((self.tick, "died", e.id, e.kind, e.owner, e.x, e.y))

    def _check_over(self):
        if not self.victory:
            return
        alive = [any(e.building and e.owner == p.index for e in self.ents.values())
                 for p in self.players]
        if sum(alive) <= 1:
            self.over = True
            self.winner = alive.index(True) if any(alive) else None
            self.end_reason = "destroyed" if any(alive) else "draw"
        elif self.tick >= self.max_ticks:
            # время вышло: победа по очкам (решение Алексея 10.10.2026)
            self.over = True
            self.winner, self.end_reason = self.points_winner()

    def points(self, owner):
        """Очки на случай конца времени: (цена уцелевших зданий, цена армии). Здание считается
        по полной цене, даже недостроенное: деньги за него уже отданы. Армия - мечники и
        лучники, рабочие не в счёт."""
        bld = sum(rules.BUILDINGS[e.kind]["cost"] for e in self.ents.values()
                  if e.owner == owner and e.building)
        army = sum(rules.UNITS[e.kind]["cost"] for e in self.ents.values()
                   if e.owner == owner and not e.building and e.kind in rules.COMBAT)
        return bld, army

    def points_winner(self):
        """(победитель или None, причина): сначала здания, при равенстве - армия, иначе ничья."""
        a, b = self.points(0), self.points(1)
        if a[0] != b[0]:
            return (0 if a[0] > b[0] else 1), "points_buildings"
        if a[1] != b[1]:
            return (0 if a[1] > b[1] else 1), "points_army"
        return None, "draw"

    # ----- здания -----

    def _act_building(self, b):
        if b.built:
            return
        if b.atk:
            b.atk -= 1
        st = rules.BUILDINGS[b.kind]
        if b.queue:
            if b.train_left > 0:
                b.train_left -= 1
            if b.train_left == 0 and self.population(b.owner) < rules.MAX_UNITS:
                cell = self._spawn_cell(b, b.rally)
                if cell is not None:
                    kind = b.queue.pop(0)
                    u = self._add_unit(b.owner, kind, *cell)
                    self.players[b.owner].stats["made"] += 1
                    if b.rally is not None:
                        self._set_order(u, "move", pos=b.rally)
                    if b.queue:
                        b.train_left = rules.UNITS[b.queue[0]]["train"]
        if "r2" in st and b.atk == 0:
            t = self._nearest_enemy(b, st["r2"], cx=b.x, cy=b.y)
            if t is not None:
                self._hit(b, t)
                b.atk = st["cooldown"]

    # ----- юниты -----

    def _nearest_enemy(self, e, r2, cx=None, cy=None, units_first=True):
        """Ближайший видимый хозяину враг в квадрате дальности r2: сначала юниты, потом здания."""
        cx = e.x if cx is None else cx
        cy = e.y if cy is None else cy
        best, best_key = None, None
        sees = self.fog.sees_entity
        for t in self.ents.values():
            if t.owner == e.owner or t.hp <= 0:
                continue
            d2 = pathing.rect_dist2(cx, cy, t.rect()) if t.building else (t.x - cx) ** 2 + (t.y - cy) ** 2
            if d2 > r2:
                continue
            if not sees(e.owner, t):
                continue
            k = (t.building if units_first else 0, d2, t.id)
            if best_key is None or k < best_key:
                best, best_key = t, k
        return best

    def in_range(self, u, t):
        r2 = rules.UNITS[u.kind]["r2"]
        if t.building:
            return pathing.rect_dist2(u.x, u.y, t.rect()) <= r2
        return (t.x - u.x) ** 2 + (t.y - u.y) ** 2 <= r2

    def _hit(self, a, t):
        t.hp -= rules.damage(a.kind, t.kind)
        if (not t.building and t.order == "idle" and t.kind in rules.COMBAT and t.hp > 0
                and self.fog.sees_entity(t.owner, a)):
            self._set_order(t, "attack", target=a.id, auto=True)

    def _act_unit(self, u):
        if u.atk:
            u.atk -= 1
        if u.busy:
            u.busy -= 1
            if u.busy:
                return
            if u.work == "harvest":
                self._finish_harvest(u)
                return
        o = u.order
        if o == "idle":
            u.want = -1
            if u.kind in rules.COMBAT and (self.tick + u.id) % 3 == 0:
                t = self._nearest_enemy(u, u.sight * u.sight)
                if t is not None:
                    self._set_order(u, "attack", target=t.id, auto=True)
                    self._do_attack(u)
        elif o == "move":
            st = self._advance_to(u, u.o_pos, u.o_n)
            if st != "moving":
                self._set_order(u, "idle")
        elif o == "amove":
            self._do_amove(u)
        elif o == "attack":
            self._do_attack(u)
        elif o == "harvest":
            self._do_harvest(u)
        elif o == "build":
            self._do_build(u)

    def _do_amove(self, u):
        if u.o_target is not None:
            t = self.ents.get(u.o_target)
            if t is None or not self.fog.sees_entity(u.owner, t):
                u.o_target = None
                u.path = []
            else:
                self._engage(u, t)
                return
        if u.kind != "worker":
            t = self._nearest_enemy(u, u.sight * u.sight)
            if t is not None:
                u.o_target = t.id
                u.path = []
                self._engage(u, t)
                return
        if self._advance_to(u, u.o_pos, u.o_n) != "moving":
            self._set_order(u, "idle")

    def _do_attack(self, u):
        t = self.ents.get(u.o_target)
        if t is None or t.hp <= 0 or not self.fog.sees_entity(u.owner, t):
            if u.auto and u.o_anchor is not None and u.o_anchor != (u.x, u.y):
                self._set_order(u, "move", pos=u.o_anchor)
            else:
                self._set_order(u, "idle")
            return
        if u.auto and u.o_anchor is not None:
            ax, ay = u.o_anchor
            if max(abs(u.x - ax), abs(u.y - ay)) > u.sight + 2:
                self._set_order(u, "move", pos=(ax, ay))
                return
        if self._engage(u, t) == "stuck":
            self._set_order(u, "idle")

    def _engage(self, u, t):
        """Бить, если цель в дальности, иначе подходить. Возвращает 'hit', 'moving', 'stuck'."""
        if self.in_range(u, t):
            u.want = -1
            u.blocked = 0
            if u.atk == 0:
                self._hit(u, t)
                u.atk = rules.UNITS[u.kind]["cooldown"]
            return "hit"
        st = self._advance_rect(u, t.rect(), rules.UNITS[u.kind]["r2"], moving=not t.building)
        return "moving" if st == "moving" else "stuck"

    # ----- добыча и стройка -----

    def _nearest_base(self, u):
        best, best_key = None, None
        for b in self.ents.values():
            if b.owner == u.owner and b.kind == "base" and not b.built:
                k = (pathing.rect_dist2(u.x, u.y, b.rect()), b.id)
                if best_key is None or k < best_key:
                    best, best_key = b, k
        return best

    def _crystal_near(self, u, pos):
        """Видимый хозяину кристалл рядом с pos (поле кончилось - рабочий берёт соседний)."""
        best, best_key = None, None
        sees = self.fog.sees
        for (x, y) in self.crystals:
            d2 = (x - pos[0]) ** 2 + (y - pos[1]) ** 2
            if d2 > 64 or not sees(u.owner, x, y):
                continue
            k = ((x - u.x) ** 2 + (y - u.y) ** 2, y, x)
            if best_key is None or k < best_key:
                best, best_key = (x, y), k
        return best

    def _do_harvest(self, u):
        if u.carry >= rules.CARRY:
            self._deliver(u)
            return
        pos = u.o_pos
        if pos not in self.crystals and not self.fog.sees(u.owner, *pos):
            # хозяин помнит кристалл, но не видит клетку: рабочий идёт проверить. Встать
            # сразу значило бы выдать, что кристалл в тумане уже выбран.
            if u.carry:
                self._deliver(u)
            elif self._advance_rect(u, (pos[0], pos[1], pos[0], pos[1]), rules.MELEE_R2) != "moving":
                self._set_order(u, "idle")
            return
        if pos not in self.crystals:
            nxt = self._crystal_near(u, pos)
            if nxt is None:
                if u.carry:
                    self._deliver(u)
                else:
                    self._set_order(u, "idle")
                return
            u.o_pos = pos = nxt
            u.path = []
        if (pos[0] - u.x) ** 2 + (pos[1] - u.y) ** 2 <= rules.MELEE_R2:
            u.busy = rules.HARVEST_TICKS
            u.work = "harvest"
            u.want = -1
            u.blocked = 0
            return
        if self._advance_rect(u, (pos[0], pos[1], pos[0], pos[1]), rules.MELEE_R2) != "moving":
            self._set_order(u, "idle")

    def _finish_harvest(self, u):
        u.work = None
        pos = u.o_pos
        amount = self.crystals.get(pos, 0)
        if amount <= 0:
            return
        take = min(rules.CARRY - u.carry, amount)
        u.carry += take
        if amount - take > 0:
            self.crystals[pos] = amount - take
        else:
            del self.crystals[pos]
            self.blocked[pos[1] * self.w + pos[0]] = 0
            self._static_changed([pos])

    def _deliver(self, u):
        b = self._nearest_base(u)
        if b is None:
            self._set_order(u, "idle")
            return
        if pathing.rect_dist2(u.x, u.y, b.rect()) <= rules.MELEE_R2:
            pl = self.players[u.owner]
            pl.resources += u.carry
            pl.stats["gathered"] += u.carry
            u.carry = 0
            u.path = []
            u.want = -1
            return
        if self._advance_rect(u, b.rect(), rules.MELEE_R2) != "moving":
            self._set_order(u, "idle")

    def _do_build(self, u):
        kind, (x, y) = u.o_kind, u.o_pos
        s = self.size_of(kind)
        rect = (x, y, x + s - 1, y + s - 1)
        b = self.ents.get(u.o_target) if u.o_target is not None else None
        if b is not None and (not b.built or b.owner != u.owner):
            self._set_order(u, "idle")
            return
        inside = x <= u.x < x + s and y <= u.y < y + s
        if b is None and inside:
            self._step_out(u, rect)
            return
        if pathing.rect_dist2(u.x, u.y, rect) > rules.MELEE_R2:
            if self._advance_rect(u, rect, rules.MELEE_R2) != "moving":
                self._set_order(u, "idle")
            return
        u.want = -1
        if b is None:
            # здание ещё не заложено: место, кристаллы, юниты на месте
            if not self.footprint_free(kind, x, y):
                own = self.ents.get(self.bld_at[y * self.w + x])
                if own is not None and own.owner == u.owner and own.kind == kind and own.built \
                        and (own.x, own.y) == (x, y):
                    u.o_target = own.id
                    return
                self._set_order(u, "idle")
                return
            occupants = [self.ents[self.unit_at[yy * self.w + xx]]
                         for yy in range(y, y + s) for xx in range(x, x + s)
                         if self.unit_at[yy * self.w + xx]]
            pl = self.players[u.owner]
            cost = rules.BUILDINGS[kind]["cost"]
            if occupants or pl.resources < cost:
                for o in occupants:
                    if o.owner == u.owner and o.order == "idle" and o.busy == 0:
                        self._step_out(o, rect)
                u.wait += 1
                if u.wait > 100:
                    self._set_order(u, "idle")
                return
            pl.resources -= cost
            pl.stats["spent"] += cost
            b = self._add_building(u.owner, kind, x, y)
            u.o_target = b.id
            self.events.append((self.tick, "placed", b.id))
        # стройка: каждый рабочий рядом - такт работы
        done = b.build_total - b.built
        gain = b.max_hp - b.hp0
        b.hp += gain * (done + 1) // b.build_total - gain * done // b.build_total
        b.built -= 1
        if b.built == 0:
            self._finish_building(b)
            self._set_order(u, "idle")

    def _step_out(self, u, rect):
        """Выйти с места будущего здания в ближайшую свободную клетку рядом."""
        x0, y0, x1, y1 = rect
        best, best_key = None, None
        for y in range(y0 - 1, y1 + 2):
            for x in range(x0 - 1, x1 + 2):
                if x0 <= x <= x1 and y0 <= y <= y1:
                    continue
                if 0 <= x < self.w and 0 <= y < self.h:
                    i = y * self.w + x
                    if not self.blocked[i] and not self.unit_at[i]:
                        k = ((x - u.x) ** 2 + (y - u.y) ** 2, y, x)
                        if best_key is None or k < best_key:
                            best, best_key = (x, y), k
        if best is None or u.busy:
            return
        if max(abs(best[0] - u.x), abs(best[1] - u.y)) == 1 and pathing.can_step(
                self.w, self.h, self.blocked, u.x, u.y, best[0] - u.x, best[1] - u.y):
            self._move(u, *best)
        else:
            path = pathing.astar(self.w, self.h, self.blocked, (u.x, u.y),
                                 (best[0], best[1], best[0], best[1]))
            if path and not self.unit_at[path[0][1] * self.w + path[0][0]]:
                self._move(u, *path[0])

    # ----- движение -----

    def _advance_to(self, u, pos, n):
        """Шаг к точке. Группа (n > 1) идёт по общему потоковому полю и останавливается в
        радиусе, которого хватает всем; одиночка - по A* в саму клетку."""
        if n > 1:
            return self._advance_field(u, pos, n)
        return self._advance_rect(u, (pos[0], pos[1], pos[0], pos[1]), 0)

    def _advance_field(self, u, pos, n):
        ff = self.field(u.owner, pos)
        w = self.w
        cur = u.y * w + u.x
        d = ff.value(cur)
        f = ff.dist
        if d >= pathing.INF:
            return self._advance_rect(u, (pos[0], pos[1], pos[0], pos[1]), 0)
        if d <= 14 * arrival_radius(n):
            return "arrived"
        best = None
        free = None
        for dx, dy in pathing.DIRS:
            nx, ny = u.x + dx, u.y + dy
            if not (0 <= nx < w and 0 <= ny < self.h):
                continue
            i = ny * w + nx
            if f[i] >= d or not pathing.can_step(w, self.h, self.blocked, u.x, u.y, dx, dy):
                continue
            k = (f[i], i)
            if best is None or k < best[0]:
                best = (k, nx, ny)
            if not self.unit_at[i] and (free is None or k < free[0]):
                free = (k, nx, ny)
        if free is not None:
            self._move(u, free[1], free[2])
            return "moving"
        if best is None:
            # яма устаревшего поля (новое здание перекрыло спуск) - дальше по A*
            return self._advance_rect(u, (pos[0], pos[1], pos[0], pos[1]), 0)
        if self._swap_or_wait(u, best[1], best[2]):
            return "moving"
        if u.blocked >= GIVE_UP_GROUP:
            return "arrived"
        return "moving"

    def _advance_rect(self, u, rect, r2, moving=False):
        """Шаг по A* к прямоугольнику rect на квадрат дальности r2. Возвращает 'arrived',
        'moving' (шагнул или ждёт) или 'stuck' (ближе не подойти)."""
        if pathing.rect_dist2(u.x, u.y, rect) <= r2:
            u.blocked = 0
            return "arrived"
        goal = (rect, r2)
        need = not u.path or u.path_goal != goal
        if need and moving and u.path and self.tick < u.repath_at:
            need = False      # цель движется: старый путь ещё годен, пересчёт реже
        if not need:
            nx, ny = u.path[0]
            if not pathing.can_step(self.w, self.h, self.blocked, u.x, u.y, nx - u.x, ny - u.y) \
                    or max(abs(nx - u.x), abs(ny - u.y)) != 1:
                need = True
        if need:
            u.path = pathing.astar(self.w, self.h, self.blocked, (u.x, u.y), rect, r2)
            u.path_goal = goal
            u.repath_at = self.tick + REPATH_MOVING
            if not u.path:
                return "stuck"
        nx, ny = u.path[0]
        i = ny * self.w + nx
        if not self.unit_at[i]:
            self._move(u, nx, ny)
            return "moving"
        # обход соседней клеткой, если она тоже ведёт к следующей точке пути
        if len(u.path) >= 2:
            ax, ay = u.path[1]
            for dx, dy in pathing.DIRS:
                cx, cy = u.x + dx, u.y + dy
                if (cx, cy) == (nx, ny) or max(abs(ax - cx), abs(ay - cy)) != 1:
                    continue
                if not (0 <= cx < self.w and 0 <= cy < self.h) or self.unit_at[cy * self.w + cx]:
                    continue
                if pathing.can_step(self.w, self.h, self.blocked, u.x, u.y, dx, dy) and \
                        pathing.can_step(self.w, self.h, self.blocked, cx, cy, ax - cx, ay - cy):
                    u.path[0] = (cx, cy)
                    self._move(u, cx, cy)
                    return "moving"
        if self._swap_or_wait(u, nx, ny):
            return "moving"
        if u.blocked in REPATH_AT:
            extra = self._units_near(u, 5)
            p = pathing.astar(self.w, self.h, self.blocked, (u.x, u.y), rect, r2, extra=extra)
            if p and p[0] != (nx, ny) and not self.unit_at[p[0][1] * self.w + p[0][0]]:
                u.path = p
                u.path_goal = goal
        if u.blocked >= GIVE_UP:
            return "stuck"
        return "moving"

    def _units_near(self, u, r):
        out = set()
        w = self.w
        for y in range(max(0, u.y - r), min(self.h, u.y + r + 1)):
            for x in range(max(0, u.x - r), min(w, u.x + r + 1)):
                i = y * w + x
                if self.unit_at[i] and self.unit_at[i] != u.id:
                    out.add(i)
        return out

    def _swap_or_wait(self, u, nx, ny):
        """Клетка занята юнитом B. Свой B, который стоит (или идёт навстречу, или мы ждём
        слишком долго), меняется с нами местами - так в узком проходе нет вечных пробок.
        Чужой - ждём."""
        i = ny * self.w + nx
        b = self.ents[self.unit_at[i]]
        mine = u.y * self.w + u.x
        if (b.owner == u.owner and b.busy == 0 and b.hp > 0 and not b.work
                and (b.want in (-1, mine) or u.blocked >= FORCE_SWAP)
                and pathing.can_step(self.w, self.h, self.blocked, nx, ny, u.x - nx, u.y - ny)):
            self._swap(u, b)
            return True
        u.blocked += 1
        u.want = i
        return False

    def _move(self, u, nx, ny):
        w = self.w
        self.unit_at[u.y * w + u.x] = 0
        self.unit_at[ny * w + nx] = u.id
        diag = nx != u.x and ny != u.y
        u.px, u.py = u.x, u.y
        u.x, u.y = nx, ny
        u.busy = u.move_total = rules.move_ticks(u.kind, diag)
        u.blocked = 0
        u.want = -1
        if u.path and u.path[0] == (nx, ny):
            u.path.pop(0)

    def _swap(self, u, b):
        w = self.w
        ux, uy, bx, by = u.x, u.y, b.x, b.y
        diag = ux != bx and uy != by
        for e, (fx, fy), (tx, ty) in ((u, (ux, uy), (bx, by)), (b, (bx, by), (ux, uy))):
            e.px, e.py = fx, fy
            e.x, e.y = tx, ty
            e.busy = e.move_total = rules.move_ticks(e.kind, diag)
            e.blocked = 0
            e.want = -1
        self.unit_at[uy * w + ux] = b.id
        self.unit_at[by * w + bx] = u.id
        if u.path and u.path[0] == (bx, by):
            u.path.pop(0)
        if b.path and b.path[0] == (ux, uy):
            b.path.pop(0)
        else:
            b.path = []

    # ----- хэш состояния -----

    def state_key(self):
        ents = tuple(self.ents[k].key() for k in sorted(self.ents))
        return (self.tick, self.over, self.winner, self.end_reason, self._ids, self.static_version,
                tuple(p.key() for p in self.players), ents,
                tuple(sorted(self.crystals.items())), bytes(self.blocked), self.fog.state_key())

    def state_hash(self):
        import hashlib
        return hashlib.blake2b(repr(self.state_key()).encode(), digest_size=16).hexdigest()
