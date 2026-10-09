"""Общее для проверок: маленькие карты и быстрые способы расставить юнитов."""
from game.core import maps
from game.core.sim import Game

# 16x12: базы в углах, кристаллы у каждой
DUEL = [
    "................",
    ".A..............",
    "........***.....",
    "................",
    "................",
    "................",
    "................",
    "................",
    "............B...",
    ".....***........",
    "................",
    "................",
]

EMPTY_20 = ["." * 20] * 20


def game(rows=DUEL, seed=0, fog=True, workers=0, resources=1000, **kw):
    """Партия на карте из строк. Если баз нет (A, B), ставится только то, что добавят."""
    m = maps.parse(rows)
    return Game(m, seed=seed, fog=fog, start_workers=workers, start_resources=resources, **kw)


def unit(g, owner, kind, x, y):
    u = g._add_unit(owner, kind, x, y)
    g.fog.update(g)
    return u


def building(g, owner, kind, x, y, done=True):
    b = g._add_building(owner, kind, x, y)
    if done:
        b.built = 0
        b.hp = b.max_hp
    g.fog.update(g)
    return b


def run(g, ticks, commands=None):
    """ticks тактов; commands - список команд на первый такт."""
    for i in range(ticks):
        if g.over:
            break
        g.step(commands if (i == 0 and commands) else ())


def check_invariants(g):
    """Согласованность состояния: каждая клетка и каждый юнит смотрят друг на друга."""
    w = g.w
    seen = {}
    for e in g.ents.values():
        assert e.hp > 0
        assert e.hp <= e.max_hp
        if e.building:
            for yy in range(e.y, e.y + e.size):
                for xx in range(e.x, e.x + e.size):
                    assert g.bld_at[yy * w + xx] == e.id
                    assert g.blocked[yy * w + xx]
        else:
            i = e.y * w + e.x
            assert g.unit_at[i] == e.id, (e.id, e.x, e.y)
            assert not g.blocked[i], ("юнит в стене", e.kind, e.x, e.y)
            assert i not in seen
            seen[i] = e.id
            assert 0 <= e.carry <= 8
            assert max(abs(e.x - e.px), abs(e.y - e.py)) <= 1
    assert sum(1 for v in g.unit_at if v) == len(seen)
    for i, v in enumerate(g.bld_at):
        if v:
            assert v in g.ents and g.ents[v].building
    for pos, a in g.crystals.items():
        assert a > 0 and g.blocked[pos[1] * w + pos[0]]
    for p in g.players:
        assert p.resources >= 0
