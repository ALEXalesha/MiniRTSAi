"""Победа по очкам, когда вышло время (решение Алексея 10.10.2026): сначала цена уцелевших
зданий, при равенстве - цена армии, иначе ничья. Закон: зеркальная позиция - ничья,
у кого больше - тот и победил."""
from hypothesis import given, settings
from hypothesis import strategies as st

from game.core import maps, rules
from game.core.sim import Game

KINDS = ("barracks", "tower")


def mirrored(seed_cells, extra=None):
    """Карта-поле, у обоих одинаковые здания и армии по зеркалу; extra - что добавить игроку."""
    m = maps.get("plains")
    g = Game(m, start_workers=0, max_ticks=1)
    for kind, x, y in seed_cells:
        s = g.size_of(kind)
        mx, my = m.w - s - x, m.h - s - y
        for owner, (cx, cy) in ((0, (x, y)), (1, (mx, my))):
            if kind in rules.BUILDINGS:
                if g.footprint_free(kind, cx, cy):
                    g._add_building(owner, kind, cx, cy)
            elif not g.blocked[cy * g.w + cx] and not g.unit_at[cy * g.w + cx]:
                g._add_unit(owner, kind, cx, cy)
    for owner, kind, x, y in extra or ():
        if kind in rules.BUILDINGS:
            assert g.footprint_free(kind, x, y)
            g._add_building(owner, kind, x, y)
        else:
            g._add_unit(owner, kind, x, y)
    return g


def finish(g):
    g.step()
    assert g.over
    return g.winner, g.end_reason


cells = st.lists(st.tuples(st.sampled_from(KINDS + tuple(rules.UNITS)),
                           st.integers(8, 20), st.integers(8, 20)), max_size=8)


@settings(max_examples=60, deadline=None)
@given(c=cells)
def test_mirror_position_is_a_draw(c):
    g = mirrored(c)
    assert g.points(0) == g.points(1)
    assert finish(g) == (None, "draw")


@settings(max_examples=60, deadline=None)
@given(c=cells, side=st.sampled_from([0, 1]), kind=st.sampled_from(KINDS))
def test_extra_building_wins_on_points(c, side, kind):
    x, y = (30, 4) if side == 0 else (4, 30)
    g = mirrored(c, [(side, kind, x, y)])
    assert finish(g) == (side, "points_buildings")


@settings(max_examples=60, deadline=None)
@given(c=cells, side=st.sampled_from([0, 1]), kind=st.sampled_from(rules.COMBAT))
def test_equal_buildings_extra_soldier_wins_on_army(c, side, kind):
    x, y = (30, 4) if side == 0 else (4, 30)
    g = mirrored(c, [(side, kind, x, y)])
    assert finish(g) == (side, "points_army")


def test_buildings_outweigh_army_and_workers_do_not_count():
    g = mirrored([], [(0, "tower", 30, 4)] +
                 [(1, "swordsman", 4 + i, 30) for i in range(10)])
    assert finish(g) == (0, "points_buildings")
    g = mirrored([], [(1, "worker", 4 + i, 30) for i in range(10)])
    assert finish(g) == (None, "draw")


def test_base_is_worth_more_than_barracks_and_tower():
    b = rules.BUILDINGS
    assert b["base"]["cost"] > b["barracks"]["cost"] and b["base"]["cost"] > b["tower"]["cost"]


def test_destroying_all_buildings_still_wins_before_time():
    g = mirrored([])
    g.max_ticks = 100
    for e in list(g.ents.values()):
        if e.owner == 1:
            e.hp = 0
    g.step()
    assert g.over and g.winner == 0 and g.end_reason == "destroyed"
