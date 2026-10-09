"""Поиск пути: A*, потоковые поля и карты-ловушки, на которых юниты не должны застревать.

«Не застрял» здесь значит: каждый приказ кончается за ограниченное число тактов, юнит
стоит у цели (одиночка - в самой клетке, группа - в радиусе, которого хватает всем) или,
если цель недостижима, в ближайшей к ней достижимой клетке.
"""
import random

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from game.core import commands as C
from game.core import maps
from game.core import path as P
from game.core.sim import Game, arrival_radius
from tests.helpers import check_invariants


def world(rows):
    return Game(maps.parse(rows), fog=False, victory=False, start_workers=0)


def put(g, cells, kind="swordsman", owner=0):
    return [g._add_unit(owner, kind, x, y) for (x, y) in cells]


def run_until_idle(g, units, limit):
    for t in range(limit):
        if all(u.order == "idle" and u.busy == 0 for u in units):
            return t
        g.step()
        check_invariants(g)
    raise AssertionError(f"не дошли за {limit} тактов: " +
                         str([(u.x, u.y, u.order, u.blocked) for u in units if u.order != "idle"]))


def cells_of(rows, ch):
    return [(x, y) for y, r in enumerate(rows) for x, c in enumerate(r) if c == ch]


def clean(rows):
    return [r.replace("u", ".").replace("t", ".") for r in rows]


# ----- A* и поля сами по себе -----

def test_astar_finds_shortest_path_cost():
    rows = clean(U_TRAP)
    m = maps.parse(rows)
    blocked = maps.passable_cells(m)
    (s,) = cells_of(U_TRAP, "u")
    (t,) = cells_of(U_TRAP, "t")
    p = P.astar(m.w, m.h, blocked, s, (t[0], t[1], t[0], t[1]))
    assert p[-1] == t
    f = P.flow_field(m.w, m.h, blocked, [t])
    assert P.path_cost(p, s) == f[s[1] * m.w + s[0]]          # A* оптимален
    x, y = s
    for nx, ny in p:                                           # шаги соседние, без стен и углов
        assert P.can_step(m.w, m.h, blocked, x, y, nx - x, ny - y)
        x, y = nx, ny


def test_astar_to_unreachable_goal_stops_at_nearest_reachable_cell():
    rows = clean(BOXED)
    m = maps.parse(rows)
    blocked = maps.passable_cells(m)
    (s,) = cells_of(BOXED, "u")
    (t,) = cells_of(BOXED, "t")
    p = P.astar(m.w, m.h, blocked, s, (t[0], t[1], t[0], t[1]))
    end = p[-1]
    seen = maps.reachable(m, s, blocked)
    best = min((x - t[0]) ** 2 + (y - t[1]) ** 2 for y in range(m.h) for x in range(m.w)
               if seen[y * m.w + x])
    assert (end[0] - t[0]) ** 2 + (end[1] - t[1]) ** 2 == best


@settings(max_examples=60, deadline=None)
@given(seed=st.integers(0, 10 ** 6), density=st.floats(0, 0.4))
def test_lazy_field_and_adjacency_match_full_dijkstra(seed, density):
    rng = random.Random(seed)
    w, h = 14, 11
    blocked = bytearray(1 if rng.random() < density else 0 for _ in range(w * h))
    target = (rng.randrange(w), rng.randrange(h))
    full = P.flow_field(w, h, blocked, [target])
    adj = P.build_adj(w, h, blocked)
    assert P.flow_field_adj(adj, w, h, blocked, [target]) == full
    ff = P.FlowField(adj, w, h, blocked, target)
    order = list(range(w * h))
    rng.shuffle(order)
    for i in order:
        assert ff.value(i) == full[i]
    # карта поменялась в нескольких клетках: точечное обновление = полная пересборка
    changed = [(rng.randrange(w), rng.randrange(h)) for _ in range(5)]
    for (x, y) in changed:
        blocked[y * w + x] ^= 1
    P.update_adj(adj, w, h, blocked, changed)
    assert adj == P.build_adj(w, h, blocked)


@settings(max_examples=60, deadline=None)
@given(seed=st.integers(0, 10 ** 6), density=st.floats(0, 0.4), r2=st.sampled_from([0, 2, 16]))
def test_astar_matches_field_cost_to_any_goal_cell(seed, density, r2):
    """Длина пути A* равна кратчайшей по полю до ближайшей подходящей клетки цели."""
    rng = random.Random(seed)
    w, h = 13, 12
    blocked = bytearray(1 if rng.random() < density else 0 for _ in range(w * h))
    s = (rng.randrange(w), rng.randrange(h))
    blocked[s[1] * w + s[0]] = 0
    t = (rng.randrange(w), rng.randrange(h))
    rect = (t[0], t[1], t[0], t[1])
    goals = [(x, y) for y in range(h) for x in range(w)
             if not blocked[y * w + x] and P.rect_dist2(x, y, rect) <= r2]
    p = P.astar(w, h, blocked, s, rect, r2)
    if not goals:
        return
    f = P.flow_field(w, h, blocked, goals)
    best = f[s[1] * w + s[0]]
    if best >= P.INF:
        assert not p or P.rect_dist2(*p[-1], rect) > r2
    else:
        assert P.path_cost(p, s) == best


# ----- карты-ловушки -----

U_TRAP = [
    "....................",
    "..........t.........",
    "....................",
    "....############....",
    "....#..........#....",
    "....#..........#....",
    "....#....u.....#....",
    "....#..........#....",
    "....#..........#....",
    "....#####..#####....",
    "....................",
    "....................",
]

BOXED = [
    "..............",
    "..u...........",
    "..............",
    ".......#####..",
    ".......#...#..",
    ".......#.t.#..",
    ".......#...#..",
    ".......#####..",
    "..............",
]

def corridor_rows():
    """Два поля 5x7 и между ними коридор шириной 1 и длиной 14 (строка 3)."""
    wall = "....." + "#" * 14 + "....."
    rows = ["." * 24] * 7
    return [wall if i in (0, 1, 2, 4, 5, 6) else r for i, r in enumerate(rows)]


def spiral(n=21):
    g = [["." for _ in range(n)] for _ in range(n)]
    lo, hi = 1, n - 2
    side = 0
    while hi - lo >= 2:
        for i in range(lo, hi + 1):
            g[lo][i] = g[hi][i] = g[i][lo] = g[i][hi] = "#"
        # проход: по очереди на разных сторонах
        mid = (lo + hi) // 2
        if side % 4 == 0:
            g[lo][mid] = "."
        elif side % 4 == 1:
            g[mid][hi] = "."
        elif side % 4 == 2:
            g[hi][mid] = "."
        else:
            g[mid][lo] = "."
        side += 1
        lo, hi = lo + 2, hi - 2
    return ["".join(r) for r in g]


def test_unit_escapes_u_trap_to_exact_cell():
    g = world(clean(U_TRAP))
    (s,) = cells_of(U_TRAP, "u")
    (t,) = cells_of(U_TRAP, "t")
    (u,) = put(g, [s])
    g.apply_command(C.move(0, [u.id], t))
    run_until_idle(g, [u], 300)
    assert (u.x, u.y) == t


def test_unit_walks_out_of_spiral_and_back_in():
    rows = spiral()
    g = world(rows)
    (u,) = put(g, [(10, 10)])
    g.apply_command(C.move(0, [u.id], (0, 0)))
    run_until_idle(g, [u], 1500)
    assert (u.x, u.y) == (0, 0)
    g.apply_command(C.move(0, [u.id], (10, 10)))
    run_until_idle(g, [u], 1500)
    assert (u.x, u.y) == (10, 10)


def test_head_on_traffic_in_one_wide_corridor():
    """Две группы навстречу друг другу в коридоре шириной в одну клетку: без обмена местами
    это вечная пробка."""
    rows = corridor_rows()
    g = world(rows)
    left = put(g, [(0, 2), (1, 2), (2, 2), (0, 3), (1, 3)])
    right = put(g, [(23, 4), (22, 4), (21, 4), (23, 3), (22, 3)])
    g.apply_command(C.move(0, [u.id for u in left], (22, 5)))
    g.apply_command(C.move(0, [u.id for u in right], (1, 1)))
    run_until_idle(g, left + right, 1200)
    assert all(u.x >= 19 for u in left), [(u.x, u.y) for u in left]
    assert all(u.x <= 4 for u in right), [(u.x, u.y) for u in right]


def test_single_units_head_on_in_corridor():
    rows = corridor_rows()
    g = world(rows)
    a, b = put(g, [(6, 3), (17, 3)])
    g.apply_command(C.move(0, [a.id], (23, 3)))
    g.apply_command(C.move(0, [b.id], (0, 3)))
    run_until_idle(g, [a, b], 600)
    assert (a.x, a.y) == (23, 3) and (b.x, b.y) == (0, 3)


def test_crowd_squeezes_through_one_cell_gap():
    rows = ["." * 24] * 20
    rows = [r[:12] + "#" + r[13:] if y != 10 else r for y, r in enumerate(rows)]
    g = world(rows)
    crowd = put(g, [(x, y) for y in range(5, 15) for x in range(2, 4)])
    g.apply_command(C.move(0, [u.id for u in crowd], (20, 10)))
    run_until_idle(g, crowd, 1500)
    assert all(u.x > 12 for u in crowd), [(u.x, u.y) for u in crowd if u.x <= 12]
    r = arrival_radius(len(crowd))
    near = sum(1 for u in crowd if max(abs(u.x - 20), abs(u.y - 10)) <= r + 1)
    assert near >= len(crowd) * 3 // 4


def test_unreachable_target_unit_stops_nearest_and_order_ends():
    rows = clean(BOXED)
    g = world(rows)
    (s,) = cells_of(BOXED, "u")
    (t,) = cells_of(BOXED, "t")
    (u,) = put(g, [s])
    g.apply_command(C.move(0, [u.id], t))
    run_until_idle(g, [u], 200)
    assert (u.x - t[0]) ** 2 + (u.y - t[1]) ** 2 == 9     # вплотную к коробке напротив цели


def test_unreachable_target_group_stops_and_orders_end():
    rows = clean(BOXED)
    g = world(rows)
    grp = put(g, [(1, 1), (2, 1), (3, 1), (1, 2), (2, 2), (3, 2)])
    g.apply_command(C.move(0, [u.id for u in grp], cells_of(BOXED, "t")[0]))
    run_until_idle(g, grp, 400)
    assert all(abs(u.x - 9) + abs(u.y - 5) <= 8 for u in grp)


def test_target_inside_wall():
    rows = ["." * 12, "." * 12, "....####....", "....####....", "." * 12, "." * 12]
    g = world(rows)
    (u,) = put(g, [(0, 0)])
    g.apply_command(C.move(0, [u.id], (5, 3)))
    run_until_idle(g, [u], 200)
    assert P.rect_dist2(u.x, u.y, (5, 3, 5, 3)) <= 2
    grp = put(g, [(11, 0), (11, 1), (10, 0)])
    g.apply_command(C.move(0, [x.id for x in grp], (6, 2)))
    run_until_idle(g, grp, 300)
    assert all(P.rect_dist2(x.x, x.y, (6, 2, 6, 2)) <= 8 for x in grp)


def test_unit_passes_through_corridor_full_of_idle_friends():
    rows = corridor_rows()
    g = world(rows)
    idle = put(g, [(x, 3) for x in range(6, 18)])
    (u,) = put(g, [(1, 3)])
    g.apply_command(C.move(0, [u.id], (22, 3)))
    run_until_idle(g, [u] + idle, 900)
    assert (u.x, u.y) == (22, 3)


def test_group_into_pocket_smaller_than_group_ends():
    rows = [
        "..............",
        "..............",
        "......###.....",
        "......#.#.....",
        "......#.#.....",
        "..............",
        "..............",
    ]
    g = world(rows)
    grp = put(g, [(x, y) for x in range(0, 3) for y in range(0, 3)])
    g.apply_command(C.move(0, [u.id for u in grp], (7, 3)))
    run_until_idle(g, grp, 400)


def test_building_placed_on_the_route_does_not_strand_the_group():
    """Устаревшее потоковое поле: здание встало поперёк пути, юниты всё равно доходят."""
    rows = ["." * 20] * 12
    g = world(rows)
    grp = put(g, [(0, y) for y in range(4, 8)])
    g.apply_command(C.move(0, [u.id for u in grp], (19, 6)))
    for _ in range(3):
        g.step()
    b = g._add_building(1, "base", 8, 4)
    b.built = 0
    g._add_building(1, "base", 8, 7)
    g._add_building(1, "base", 8, 1)
    run_until_idle(g, grp, 600)
    assert all(u.x > 10 for u in grp)


@settings(max_examples=40, deadline=None)
@given(seed=st.integers(0, 10 ** 6), density=st.floats(0, 0.3), n=st.integers(1, 7))
def test_random_maps_every_order_ends(seed, density, n):
    rng = random.Random(seed)
    w, h = 16, 14
    rows = ["".join("#" if rng.random() < density else "." for _ in range(w)) for _ in range(h)]
    g = world(rows)
    free = [(x, y) for y in range(h) for x in range(w) if rows[y][x] == "."]
    if len(free) < n + 1:
        return
    starts = rng.sample(free, n)
    grp = put(g, starts)
    target = (rng.randrange(w), rng.randrange(h))
    g.apply_command(C.move(0, [u.id for u in grp], target))
    run_until_idle(g, grp, 900)
    if n == 1:
        # одиночка встаёт в ближайшую к цели достижимую клетку
        m = maps.parse(rows)
        seen = maps.reachable(m, starts[0])
        best = min((x - target[0]) ** 2 + (y - target[1]) ** 2
                   for y in range(h) for x in range(w) if seen[y * w + x])
        u = grp[0]
        assert (u.x - target[0]) ** 2 + (u.y - target[1]) ** 2 == best


@pytest.mark.parametrize("name", sorted(maps.READY))
def test_armies_cross_ready_maps(name):
    m = maps.get(name)
    g = Game(m, fog=False, victory=False, start_workers=0)
    (bx, by), (ex, ey) = m.starts
    cells = []
    for y in range(by + 4, by + 9):
        for x in range(bx, bx + 4):
            if not g.blocked[y * g.w + x]:
                cells.append((x, y))
    grp = put(g, cells[:12])
    g.apply_command(C.move(0, [u.id for u in grp], (ex - 2, ey + 1)))
    run_until_idle(g, grp, 2500)
    assert all(abs(u.x - (ex - 2)) + abs(u.y - (ey + 1)) <= 8 for u in grp)
