"""Туман войны: что видит каждый игрок сейчас, что он разведал и что запомнил.

- видно сейчас - круги обзора своих юнитов и зданий (стены обзор не закрывают);
- разведано - всё, что было видно хоть раз; рельеф за пределами разведанного игрок не знает;
- память - последний увиденный вид чужих зданий и запас кристаллов. Здание, разрушенное в
  тумане, остаётся в памяти, пока игрок снова не увидит пустое место.

Всё считается каждый такт после хода симуляции, поэтому и команды, и наблюдение ИИ
проверяются по тому, что игрок видел на экране.
"""
import numpy as np

_DISCS = {}


def disc(r):
    """Маска круга радиуса r: dx^2+dy^2 <= r^2 + r (круг выглядит круглее, чем строго r^2)."""
    m = _DISCS.get(r)
    if m is None:
        yy, xx = np.mgrid[-r:r + 1, -r:r + 1]
        m = (xx * xx + yy * yy) <= r * r + r
        _DISCS[r] = m
    return m


class Fog:
    def __init__(self, w, h, players=2, enabled=True):
        self.w, self.h = w, h
        self.enabled = enabled
        self.visible = [np.zeros((h, w), bool) for _ in range(players)]
        self.explored = [np.zeros((h, w), bool) for _ in range(players)]
        self.vis_bytes = [bytes(w * h) for _ in range(players)]
        self.buildings = [dict() for _ in range(players)]   # id -> (kind, owner, x, y, hp, built, tick)
        self.crystals = [dict() for _ in range(players)]    # (x, y) -> запас
        if not enabled:
            for p in range(players):
                self.visible[p][:] = True
                self.explored[p][:] = True
                self.vis_bytes[p] = bytes([1]) * (w * h)

    def sees(self, player, x, y):
        return self.vis_bytes[player][y * self.w + x] == 1

    def sees_rect(self, player, x, y, size):
        vb, w = self.vis_bytes[player], self.w
        for yy in range(y, y + size):
            row = yy * w
            for xx in range(x, x + size):
                if vb[row + xx]:
                    return True
        return False

    def sees_entity(self, player, e):
        if e.building:
            return self.sees_rect(player, e.x, e.y, e.size)
        return self.vis_bytes[player][e.y * self.w + e.x] == 1

    def update(self, game):
        w, h = self.w, self.h
        for p in range(len(self.visible)):
            if self.enabled:
                grid = self.visible[p]
                grid[:] = False
                for e in game.ents.values():
                    if e.owner != p:
                        continue
                    r = e.sight
                    cx, cy = (e.x + e.size // 2, e.y + e.size // 2) if e.building else (e.x, e.y)
                    m = disc(r)
                    x0, y0, x1, y1 = cx - r, cy - r, cx + r + 1, cy + r + 1
                    mx0, my0 = max(0, -x0), max(0, -y0)
                    mx1, my1 = m.shape[1] - max(0, x1 - w), m.shape[0] - max(0, y1 - h)
                    grid[max(0, y0):min(h, y1), max(0, x0):min(w, x1)] |= m[my0:my1, mx0:mx1]
                self.explored[p] |= grid
                self.vis_bytes[p] = grid.tobytes()
            self._remember(game, p)

    def _remember(self, game, p):
        mem = self.buildings[p]
        for bid in list(mem):
            kind, owner, x, y, hp, built, t = mem[bid]
            size = game.size_of(kind)
            if self.sees_rect(p, x, y, size):
                e = game.ents.get(bid)
                if e is None or e.x != x or e.y != y:
                    del mem[bid]
        for e in game.buildings_list():
            if e.owner != p and self.sees_rect(p, e.x, e.y, e.size):
                mem[e.id] = (e.kind, e.owner, e.x, e.y, e.hp, e.built, game.tick)
        cmem = self.crystals[p]
        vb, w = self.vis_bytes[p], self.w
        for pos in list(cmem):
            if vb[pos[1] * w + pos[0]] and pos not in game.crystals:
                del cmem[pos]
        for pos, amount in game.crystals.items():
            if vb[pos[1] * w + pos[0]]:
                cmem[pos] = amount

    def state_key(self):
        return (tuple(e.tobytes() for e in self.explored),
                tuple(tuple(sorted(m.items())) for m in self.buildings),
                tuple(tuple(sorted(m.items())) for m in self.crystals))
