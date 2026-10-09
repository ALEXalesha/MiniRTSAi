"""Карты: клетки, стены, кристаллы, места баз. Готовые карты и генератор симметричных.

Все карты для двоих симметричны поворотом на 180°: клетка (x, y) игрока 0 отвечает клетке
(w-1-x, h-1-y) игрока 1. Так ни одна сторона не получает выгоды от карты.

Карта в тексте (для проверок и записи партии):
    .  земля      #  стена      *  кристалл      A, B  левый верхний угол базы игрока 0, 1
"""
import random
from collections import deque

from game.core import rules

FREE, WALL = 0, 1
BASE = rules.BUILDINGS["base"]["size"]


class GameMap:
    __slots__ = ("name", "w", "h", "walls", "crystals", "starts")

    def __init__(self, name, w, h, walls, crystals, starts):
        self.name = name
        self.w, self.h = w, h
        self.walls = bytearray(walls)            # w*h, 1 - стена
        self.crystals = dict(crystals)           # (x, y) -> запас
        self.starts = [tuple(s) for s in starts]  # левый верхний угол базы каждого игрока

    def copy(self):
        return GameMap(self.name, self.w, self.h, self.walls, self.crystals, self.starts)

    def to_rows(self):
        rows = [["#" if self.walls[y * self.w + x] else "." for x in range(self.w)]
                for y in range(self.h)]
        for (x, y) in self.crystals:
            rows[y][x] = "*"
        for i, (x, y) in enumerate(self.starts):
            rows[y][x] = "AB"[i]
        return ["".join(r) for r in rows]

    def to_json(self):
        """Карта целиком: запись партии не зависит от того, как карта была сделана."""
        extra = {f"{x},{y}": a for (x, y), a in sorted(self.crystals.items())
                 if a != rules.CRYSTAL_AMOUNT}
        return {"name": self.name, "rows": self.to_rows(), "amounts": extra}

    @classmethod
    def from_json(cls, d):
        m = parse(d["rows"], d.get("name", "map"))
        for k, a in d.get("amounts", {}).items():
            x, y = map(int, k.split(","))
            m.crystals[(x, y)] = a
        return m


def parse(rows, name="map", amount=None):
    rows = [r for r in rows if r]
    h, w = len(rows), len(rows[0])
    walls = bytearray(w * h)
    crystals, starts = {}, {}
    for y, row in enumerate(rows):
        if len(row) != w:
            raise ValueError(f"строка {y}: длина {len(row)}, ждали {w}")
        for x, ch in enumerate(row):
            if ch == "#":
                walls[y * w + x] = WALL
            elif ch == "*":
                crystals[(x, y)] = amount or rules.CRYSTAL_AMOUNT
            elif ch in "AB":
                starts["AB".index(ch)] = (x, y)
            elif ch != ".":
                raise ValueError(f"неизвестный знак {ch!r}")
    return GameMap(name, w, h, walls, crystals, [starts[i] for i in sorted(starts)])


def mirror(m, x, y):
    return m.w - 1 - x, m.h - 1 - y


def mirror_base(w, h, x, y):
    return w - BASE - x, h - BASE - y


def passable_cells(m):
    """Клетки без стен и кристаллов (базы ещё не поставлены)."""
    out = bytearray(m.walls)
    for (x, y) in m.crystals:
        out[y * m.w + x] = 1
    return out


def reachable(m, start, blocked=None):
    """Множество клеток, куда можно дойти из start по восьми направлениям без срезания углов."""
    blocked = blocked if blocked is not None else passable_cells(m)
    w, h = m.w, m.h
    sx, sy = start
    seen = bytearray(w * h)
    seen[sy * w + sx] = 1
    q = deque([(sx, sy)])
    while q:
        x, y = q.popleft()
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                nx, ny = x + dx, y + dy
                if (dx or dy) and 0 <= nx < w and 0 <= ny < h:
                    i = ny * w + nx
                    if seen[i] or blocked[i]:
                        continue
                    if dx and dy and (blocked[y * w + nx] or blocked[ny * w + x]):
                        continue
                    seen[i] = 1
                    q.append((nx, ny))
    return seen


class _Builder:
    """Рисует половину карты, вторая получается поворотом на 180°."""

    def __init__(self, name, w, h):
        self.m = GameMap(name, w, h, bytearray(w * h), {}, [])

    def wall(self, x, y):
        m = self.m
        if 0 <= x < m.w and 0 <= y < m.h:
            for (cx, cy) in ((x, y), mirror(m, x, y)):
                m.walls[cy * m.w + cx] = WALL
                m.crystals.pop((cx, cy), None)

    def rect(self, x0, y0, x1, y1):
        for y in range(y0, y1 + 1):
            for x in range(x0, x1 + 1):
                self.wall(x, y)

    def crystal(self, x, y, amount=rules.CRYSTAL_AMOUNT):
        m = self.m
        if 0 <= x < m.w and 0 <= y < m.h:
            for (cx, cy) in ((x, y), mirror(m, x, y)):
                m.walls[cy * m.w + cx] = FREE
                m.crystals[(cx, cy)] = amount

    def patch(self, x, y, cells, amount=rules.CRYSTAL_AMOUNT):
        for dx, dy in cells:
            self.crystal(x + dx, y + dy, amount)

    def bases(self, x, y):
        m = self.m
        m.starts = [(x, y), mirror_base(m.w, m.h, x, y)]

    def clear_around_bases(self, r):
        m = self.m
        for bx, by in m.starts:
            cx, cy = bx + 1, by + 1
            for y in range(cy - r, cy + r + 1):
                for x in range(cx - r, cx + r + 1):
                    if 0 <= x < m.w and 0 <= y < m.h:
                        m.walls[y * m.w + x] = FREE
            for y in range(by, by + BASE):
                for x in range(bx, bx + BASE):
                    m.crystals.pop((x, y), None)


PATCH = [(0, 0), (1, 0), (2, 0), (0, 1), (1, 1), (2, 1), (1, 2), (3, 1)]


def plains():
    """Открытое поле: редкие скалы, кристаллы у баз и два поля в середине."""
    b = _Builder("plains", 48, 48)
    b.bases(5, 5)
    b.patch(11, 3, PATCH)
    b.patch(3, 11, [(0, 0), (1, 0), (0, 1), (1, 1), (0, 2), (1, 2), (0, 3)])
    b.patch(21, 14, PATCH, 200)
    b.rect(16, 6, 17, 9)
    b.rect(6, 17, 9, 18)
    b.rect(28, 20, 30, 21)
    b.rect(13, 30, 14, 33)
    b.clear_around_bases(4)
    return b.m


def crossroads():
    """Крест из стен с четырьмя проходами по три клетки, кристаллы в каждой четверти."""
    b = _Builder("crossroads", 48, 48)
    b.bases(4, 4)
    for y in range(48):
        if not (10 <= y <= 12 or 35 <= y <= 37):
            b.wall(23, y)
    for x in range(48):
        if not (10 <= x <= 12 or 35 <= x <= 37):
            b.wall(x, 23)
    b.patch(10, 4, PATCH)
    b.patch(4, 11, [(0, 0), (1, 0), (0, 1), (1, 1), (0, 2), (1, 2)])
    b.patch(30, 15, PATCH, 200)
    b.clear_around_bases(4)
    return b.m


def twin_passes():
    """Диагональная гряда через всю карту и два узких прохода: бой за узкие места."""
    b = _Builder("twin_passes", 48, 48)
    b.bases(4, 4)
    for i in range(48):
        x, y = i, 47 - i
        if 10 <= i <= 11 or 36 <= i <= 37:
            continue
        b.wall(x, y)
        if x + 1 < 48:
            b.wall(x + 1, y)
    b.patch(11, 3, PATCH)
    b.patch(3, 10, [(0, 0), (1, 0), (0, 1), (1, 1), (0, 2), (1, 2), (0, 3)])
    b.patch(17, 17, PATCH, 250)
    b.clear_around_bases(4)
    return b.m


READY = {"plains": plains, "crossroads": crossroads, "twin_passes": twin_passes}


def generate(seed, size=48):
    """Симметричная карта по зерну. Базы связаны проходом, у каждой рядом кристаллы.
    Если случайные стены разрезали карту, берутся следующие числа того же зерна."""
    rng = random.Random(seed)
    for _ in range(50):
        b = _Builder(f"random-{seed}", size, size)
        bx = by = rng.randint(3, 6)
        b.bases(bx, by)
        for _ in range(rng.randint(6, 12)):
            x, y = rng.randrange(size), rng.randrange(size // 2 + 4)
            if rng.random() < 0.5:
                b.rect(x, y, x + rng.randint(0, 6), y + rng.randint(0, 1))
            else:
                b.rect(x, y, x + rng.randint(0, 1), y + rng.randint(0, 6))
        # кристаллы у базы - справа или снизу, плюс 1-2 поля ближе к середине
        if rng.random() < 0.5:
            b.patch(bx + 6, by - 1 if by > 1 else by, PATCH)
        else:
            b.patch(bx - 1 if bx > 1 else bx, by + 6, [(dy, dx) for dx, dy in PATCH])
        for _ in range(rng.randint(1, 2)):
            px, py = rng.randint(10, size - 14), rng.randint(10, size // 2 - 2)
            b.patch(px, py, PATCH, 200)
        b.clear_around_bases(4)
        m = b.m
        if _fair(m):
            return m
    b = _Builder(f"random-{seed}", size, size)
    b.bases(4, 4)
    b.patch(11, 3, PATCH)
    b.clear_around_bases(4)
    return b.m


def _fair(m):
    """Базы связаны, и к каждому кристаллу можно подойти (сосед-клетка достижима)."""
    blocked = passable_cells(m)
    ax, ay = m.starts[0]
    seen = reachable(m, (ax + 1, ay + 1), blocked)
    bx, by = m.starts[1]
    if not seen[(by + 1) * m.w + bx + 1]:
        return False
    for (x, y) in m.crystals:
        if not any(0 <= x + dx < m.w and 0 <= y + dy < m.h and seen[(y + dy) * m.w + x + dx]
                   for dx in (-1, 0, 1) for dy in (-1, 0, 1)):
            return False
    return True


def get(name_or_seed):
    """Готовая карта по имени или случайная по числу."""
    if isinstance(name_or_seed, int):
        return generate(name_or_seed)
    if isinstance(name_or_seed, str) and name_or_seed.startswith("random-"):
        return generate(int(name_or_seed.split("-", 1)[1]))
    return READY[name_or_seed]()
