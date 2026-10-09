"""Симуляция: старт, добыча, обучение, стройка, бой, победа, проверка команд."""
import pytest

from game.core import commands as C
from game.core import maps, rules
from tests.helpers import DUEL, building, check_invariants, game, run, unit


def test_start_has_bases_workers_and_money():
    g = game(workers=4, resources=150)
    for p in range(2):
        bases = [b for b in g.buildings_list(p) if b.kind == "base"]
        assert len(bases) == 1 and bases[0].built == 0 and bases[0].hp == bases[0].max_hp
        assert len(g.units_list(p)) == 4
        assert g.players[p].resources == 150
    check_invariants(g)


@pytest.mark.parametrize("name", sorted(maps.READY))
def test_ready_maps_are_symmetric_and_fair(name):
    m = maps.get(name)
    assert (m.w, m.h) == (48, 48)
    assert m.starts[1] == maps.mirror_base(m.w, m.h, *m.starts[0])
    for y in range(m.h):
        for x in range(m.w):
            mx, my = maps.mirror(m, x, y)
            assert m.walls[y * m.w + x] == m.walls[my * m.w + mx]
            assert ((x, y) in m.crystals) == ((mx, my) in m.crystals)
    assert maps._fair(m)
    assert maps.parse(m.to_rows()).to_rows() == m.to_rows()


@pytest.mark.parametrize("seed", range(12))
def test_generated_maps_are_symmetric_fair_and_repeatable(seed):
    m = maps.generate(seed)
    assert maps._fair(m)
    assert m.to_rows() == maps.generate(seed).to_rows()
    for (x, y), a in m.crystals.items():
        assert m.crystals[maps.mirror(m, x, y)] == a


def test_worker_harvests_and_delivers():
    g = game()
    u = unit(g, 0, "worker", 7, 3)
    before = g.crystals[(8, 2)]
    assert g.apply_command(C.harvest(0, [u.id], (8, 2)))
    run(g, 200)
    assert g.players[0].resources > 1000
    assert g.players[0].stats["gathered"] == g.players[0].resources - 1000
    assert g.crystals[(8, 2)] < before
    check_invariants(g)


def test_depleted_crystal_frees_the_cell_and_worker_moves_on():
    g = game()
    g.crystals[(8, 2)] = rules.CARRY        # одна ходка
    u = unit(g, 0, "worker", 7, 3)
    g.apply_command(C.harvest(0, [u.id], (8, 2)))
    run(g, 120)
    assert (8, 2) not in g.crystals
    assert not g.blocked[2 * g.w + 8]
    assert u.order == "harvest" and u.o_pos in g.crystals      # взял соседний
    check_invariants(g)


def test_train_costs_waits_and_spawns_next_to_building():
    g = game(resources=60)
    base = g.buildings_list(0)[0]
    assert g.apply_command(C.train(0, base.id, "worker"))
    assert g.players[0].resources == 10
    assert not g.apply_command(C.train(0, base.id, "worker"))        # денег нет
    assert not g.apply_command(C.train(0, base.id, "swordsman"))     # база мечников не учит
    run(g, rules.UNITS["worker"]["train"] - 1)
    assert not g.units_list(0)
    run(g, 2)
    (w,) = g.units_list(0)
    assert w.kind == "worker"
    assert max(abs(w.x - 2), abs(w.y - 2)) == 2      # вплотную к базе 3x3 с центром (2, 2)
    check_invariants(g)


def test_queue_limit_and_cancel_refunds():
    g = game(resources=10000)
    base = g.buildings_list(0)[0]
    for _ in range(rules.QUEUE_MAX):
        assert g.apply_command(C.train(0, base.id, "worker"))
    assert not g.apply_command(C.train(0, base.id, "worker"))
    money = g.players[0].resources
    assert g.apply_command(C.cancel(0, base.id))
    assert g.players[0].resources == money + rules.UNITS["worker"]["cost"]
    assert len(base.queue) == rules.QUEUE_MAX - 1


def test_rally_point_sends_new_units():
    g = game(resources=1000)
    base = g.buildings_list(0)[0]
    g.apply_command(C.rally(0, base.id, (8, 6)))
    g.apply_command(C.train(0, base.id, "worker"))
    run(g, rules.UNITS["worker"]["train"] + 60)
    (w,) = g.units_list(0)
    assert (w.x, w.y) == (8, 6)


def test_worker_builds_barracks_and_more_workers_build_faster():
    times = []
    for n in (1, 2):
        g = game(resources=1000)
        ws = [unit(g, 0, "worker", 6 + i, 5) for i in range(n)]
        assert g.apply_command(C.build(0, [w.id for w in ws], "barracks", (6, 6)))
        t = 0
        while True:
            g.step()
            t += 1
            bs = [b for b in g.buildings_list(0) if b.kind == "barracks"]
            if bs and bs[0].built == 0:
                break
            assert t < 500
        b = bs[0]
        assert b.hp == b.max_hp
        assert g.players[0].resources == 1000 - rules.BUILDINGS["barracks"]["cost"]
        assert all(w.order == "idle" for w in ws)
        check_invariants(g)
        times.append(t)
    assert times[1] < times[0] * 0.7


def test_building_waits_for_money_and_rejects_bad_places():
    g = game(resources=0)
    w = unit(g, 0, "worker", 6, 5)
    g.apply_command(C.build(0, [w.id], "tower", (7, 6)))
    run(g, 30)
    assert not [b for b in g.buildings_list(0) if b.kind == "tower"]
    g.players[0].resources = 500
    run(g, 5)
    assert [b for b in g.buildings_list(0) if b.kind == "tower"]
    # на кристалле, вне карты, в неразведанном - отказ
    assert not g.apply_command(C.build(0, [w.id], "tower", (99, 0)))
    assert not g.apply_command(C.build(0, [w.id], "base", (14, 0)))     # не влезает
    assert not g.apply_command(C.build(0, [w.id], "tower", (15, 11)))   # туман


def test_build_on_crystal_cancels_order():
    g = game(resources=1000, fog=False)
    w = unit(g, 0, "worker", 6, 5)
    assert g.apply_command(C.build(0, [w.id], "barracks", (8, 1)))
    run(g, 60)
    assert w.order == "idle"
    assert not [b for b in g.buildings_list(0) if b.kind == "barracks"]


def test_swordsman_beats_archer_in_melee_and_archer_shoots_from_range():
    g = game(fog=False)
    s = unit(g, 0, "swordsman", 6, 5)
    a = unit(g, 1, "archer", 7, 5)
    g.apply_command(C.attack(0, [s.id], a.id))
    run(g, 60)
    assert a.id not in g.ents and s.id in g.ents
    g2 = game(fog=False)
    a2 = unit(g2, 0, "archer", 4, 5)
    t = unit(g2, 1, "swordsman", 8, 5)
    g2.apply_command(C.attack(0, [a2.id], t.id))
    g2.step()
    assert t.hp == t.max_hp - rules.damage("archer", "swordsman")
    assert (a2.x, a2.y) == (4, 5)        # дальность 4 - стреляет с места


def test_attack_rate_is_cooldown():
    g = game(fog=False)
    s = unit(g, 0, "swordsman", 6, 5)
    t = unit(g, 1, "swordsman", 7, 5)
    g.apply_command(C.attack(0, [s.id], t.id))
    g.apply_command(C.stop(1, [t.id]))
    t.order = "move"   # не отвечает: стоит в своём приказе
    t.o_pos, t.o_n = (7, 5), 1
    hits = []
    for _ in range(31):
        hp = t.hp
        g.step()
        if t.hp < hp:
            hits.append(g.tick)
    assert len(hits) == 4 and hits[1] - hits[0] == rules.UNITS["swordsman"]["cooldown"]


def test_tower_shoots_enemies_in_range():
    g = game(fog=True)
    tw = building(g, 0, "tower", 8, 6)
    e = unit(g, 1, "archer", 8, 10)        # 4 клетки - в дальности 5
    far = unit(g, 1, "archer", 14, 6)      # 6 клеток - нет
    g.step()
    assert e.hp < e.max_hp and far.hp == far.max_hp
    assert tw.atk == rules.BUILDINGS["tower"]["cooldown"]


def test_dead_units_and_buildings_free_cells():
    g = game(fog=False)
    s = unit(g, 0, "swordsman", 9, 6)
    tw = building(g, 1, "tower", 10, 6)
    tw.hp = 5
    g.apply_command(C.attack(0, [s.id], tw.id))
    run(g, 3)
    assert tw.id not in g.ents
    assert not g.blocked[6 * g.w + 10] and not g.bld_at[6 * g.w + 10]
    assert g.players[1].stats["buildings_lost"] == 1
    check_invariants(g)


def test_victory_when_all_enemy_buildings_fall():
    g = game(fog=False)
    base1 = [b for b in g.buildings_list(1)][0]
    base1.hp = 1
    s = unit(g, 0, "swordsman", 11, 8)
    g.apply_command(C.attack(0, [s.id], base1.id))
    run(g, 5)
    assert g.over and g.winner == 0
    n = g.tick
    g.step()
    assert g.tick == n          # после конца такты не идут


def test_draw_at_tick_limit():
    g = game(max_ticks=30)
    run(g, 100)
    assert g.over and g.winner is None and g.tick == 30


def test_commands_are_validated():
    g = game(fog=True)
    mine = unit(g, 0, "swordsman", 4, 4)
    theirs = unit(g, 1, "swordsman", 13, 4)   # в тумане у игрока 0
    assert not g.apply_command(C.move(1, [mine.id], (5, 5)))      # чужой юнит
    assert not g.apply_command(C.attack(0, [mine.id], theirs.id))  # цель в тумане
    assert not g.apply_command(C.move(0, [mine.id], (-1, 5)))
    assert not g.apply_command(C.move(0, [mine.id], (16, 5)))
    assert not g.apply_command(C.harvest(0, [mine.id], (8, 2)))    # не рабочий
    assert not g.apply_command(C.train(0, mine.id, "worker"))     # не здание
    assert not g.apply_command(C.Command(0, "dance", (mine.id,)))
    assert g.players[0].stats["rejected"] == 6
    assert g.players[1].stats["rejected"] == 1
    assert g.apply_command(C.move(0, [mine.id], (5, 5)))


def test_idle_soldier_engages_enemy_in_sight_but_not_through_fog():
    g = game(fog=True)
    s = unit(g, 0, "swordsman", 4, 6)
    e = unit(g, 1, "archer", 9, 6)          # 5 клеток: в обзоре 6
    run(g, 40)
    assert e.id not in g.ents or e.hp < e.max_hp
    g2 = game(fog=True)
    s2 = unit(g2, 0, "swordsman", 2, 6)
    e2 = unit(g2, 1, "worker", 14, 6)       # 12 клеток: не видно
    run(g2, 40)
    assert (s2.x, s2.y) == (2, 6) and s2.order == "idle"


def test_unit_processing_order_alternates_so_mirror_fights_are_even():
    """Два одинаковых мечника бьют друг друга: умирают в один такт (удары до уборки убитых)."""
    g = game(fog=False)
    a = unit(g, 0, "swordsman", 6, 5)
    b = unit(g, 1, "swordsman", 7, 5)
    g.apply_command(C.attack(0, [a.id], b.id))
    g.apply_command(C.attack(1, [b.id], a.id))
    run(g, 200)
    assert a.id not in g.ents and b.id not in g.ents


def test_ids_reveal_nothing_about_counts():
    """Номера юнитов случайны (зерно), а не 1, 2, 3...: по номеру увиденного врага нельзя
    узнать, сколько он уже обучил."""
    g = game(resources=10000)
    ids = [u.id for u in (unit(g, 0, "worker", 5 + i, 6) for i in range(6))]
    assert ids != sorted(ids)
    assert len(set(ids)) == 6 and all(0 < i < 2 ** 31 for i in ids)


def test_population_cap_holds_training():
    g = game(resources=100000)
    base = g.buildings_list(0)[0]
    for i in range(rules.MAX_UNITS):
        unit(g, 0, "worker", i % 16, 4 + i // 16)
    g.apply_command(C.train(0, base.id, "worker"))
    run(g, 80)
    assert g.population(0) == rules.MAX_UNITS and base.queue == ["worker"]


def test_duel_map_parses():
    m = maps.parse(DUEL)
    assert m.starts == [(1, 1), (12, 8)]
