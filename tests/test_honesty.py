"""Закон честности: ИИ знает только то, что видно игроку.

Главная проверка: берётся позиция из случайной партии, и всё, что скрыто от игрока,
перетряхивается - вражеские юниты в тумане переезжают, меняют вид и hp, исчезают и
появляются, у врага меняются деньги и очереди, кристаллы в тумане и стены за пределами
разведанного меняются. Снимок игрока observe(game, p) обязан остаться тем же до бита, а
значит, и решения любого ИИ (он получает только снимок).
"""
import copy
import random

from hypothesis import given, settings
from hypothesis import strategies as st

from game.ai.bots import RandomBot
from game.ai.match import play
from game.core import commands as C
from game.core import maps, rules
from game.core.observation import Observation, observe
from tests.helpers import building, game, run, unit


def midgame(seed, ticks=500, name="plains"):
    rec = play(maps.get(name), [RandomBot(4), RandomBot(4)], seed=seed, max_ticks=ticks,
               start_resources=900)
    return rec.game


def hidden_cells(g, p):
    vb = g.fog.vis_bytes[p]
    return [(i % g.w, i // g.w) for i in range(g.w * g.h)
            if not vb[i] and not g.blocked[i] and not g.unit_at[i]]


def scramble_hidden(g, p, rng):
    """Поменять всё, чего игрок p не видит. Возвращает число изменений."""
    changes = 0
    hidden = hidden_cells(g, p)
    rng.shuffle(hidden)
    fog = g.fog
    for e in list(g.ents.values()):
        if e.owner == p or fog.sees_entity(p, e):
            continue
        if e.building:
            e.hp = max(1, e.hp - rng.randint(0, e.hp // 2))
            e.queue = rng.choice([[], ["worker"], list(rules.BUILDINGS[e.kind]["trains"])])
            e.train_left = rng.randint(0, 50)
            changes += 1
            continue
        roll = rng.random()
        if roll < 0.3:
            del g.ents[e.id]
            g.unit_at[e.y * g.w + e.x] = 0
        elif roll < 0.7 and hidden:
            x, y = hidden.pop()
            g.unit_at[e.y * g.w + e.x] = 0
            e.x, e.y, e.px, e.py = x, y, x, y
            g.unit_at[y * g.w + x] = e.id
            e.hp = rng.randint(1, e.max_hp)
            e.carry = rng.choice([0, rules.CARRY])
        else:
            e.order = "move"
            e.o_pos = (rng.randrange(g.w), rng.randrange(g.h))
        changes += 1
    enemy = 1 - p
    for _ in range(rng.randint(0, 4)):
        if hidden:
            x, y = hidden.pop()
            g._add_unit(enemy, rng.choice(sorted(rules.UNITS)), x, y)
            changes += 1
    g.players[enemy].resources = rng.randint(0, 5000)
    g.players[enemy].stats["made"] += 7
    vb = fog.vis_bytes[p]
    for pos in list(g.crystals):
        if not vb[pos[1] * g.w + pos[0]]:
            g.crystals[pos] = rng.randint(1, 400)
            changes += 1
    explored = fog.explored[p]
    for i in range(g.w * g.h):
        x, y = i % g.w, i // g.w
        if not explored[y, x] and not g.blocked[i] and not g.unit_at[i] and rng.random() < 0.05:
            g.map.walls[i] = 1 - g.map.walls[i]
            changes += 1
    g._ids = rng.randrange(1, 2 ** 32)
    return changes


@settings(max_examples=25, deadline=None)
@given(seed=st.integers(0, 10 ** 6), ticks=st.integers(1, 600), p=st.sampled_from([0, 1]))
def test_hidden_changes_do_not_change_observation_or_decisions(seed, ticks, p):
    g = midgame(seed % 50, ticks)
    before = observe(g, p)
    g2 = copy.deepcopy(g)
    n = scramble_hidden(g2, p, random.Random(seed))
    g2.fog.update(g2)
    after = observe(g2, p)
    assert after == before, f"изменений скрыто: {n}"
    bot = RandomBot(6)
    bot.reset(p, seed)
    bot2 = copy.deepcopy(bot)
    assert bot.decide(before) == bot2.decide(after)


def test_scramble_really_changes_hidden_things():
    """Проверка самой проверки: перетряска меняет состояние партии, иначе закон пуст."""
    g = midgame(3, 400)
    g2 = copy.deepcopy(g)
    assert scramble_hidden(g2, 0, random.Random(1)) > 10
    assert g2.state_hash() != g.state_hash()


def test_visible_enemy_changes_do_change_observation():
    """Обратная сторона: видимое должно доходить до ИИ."""
    g = game(fog=True)
    unit(g, 0, "swordsman", 5, 5)
    e = unit(g, 1, "archer", 8, 5)
    before = observe(g, 0)
    assert [x.id for x in before.enemy_units] == [e.id]
    e.hp -= 5
    assert observe(g, 0) != before


def test_observation_lists_exactly_visible_enemy_units():
    g = midgame(7, 600)
    for p in (0, 1):
        obs = observe(g, p)
        seen = {e.id for e in obs.enemy_units}
        for e in g.ents.values():
            if e.owner != p and not e.building:
                assert (e.id in seen) == g.fog.sees_entity(p, e)


def test_observation_holds_only_plain_data():
    """В снимке нет ссылок на партию: только числа, строки, байты и кортежи из них."""
    obs = observe(midgame(9, 300), 0)

    def walk(v):
        if v is None or isinstance(v, (bool, int, str, bytes)):
            return
        assert isinstance(v, tuple), type(v)
        for x in v:
            walk(x)
    assert isinstance(obs, Observation)
    walk(tuple(obs))


def test_unexplored_terrain_is_unknown_and_explored_is_true():
    g = game(fog=True)
    obs = observe(g, 0)
    w = g.w
    for i in range(g.w * g.h):
        x, y = i % w, i // w
        if g.fog.explored[0][y, x]:
            assert obs.terrain[i] == g.map.walls[i]
        else:
            assert obs.terrain[i] == 2


def test_building_destroyed_in_fog_stays_remembered_until_seen():
    g = game(fog=True)
    scout = unit(g, 0, "archer", 9, 6)
    tw = building(g, 1, "tower", 12, 6)
    g.apply_command(C.move(0, [scout.id], (2, 6)))      # уходит, башня остаётся в памяти
    run(g, 60)
    assert not g.fog.sees_entity(0, tw)
    remembered = [b for b in observe(g, 0).enemy_buildings if b.id == tw.id]
    assert remembered and not remembered[0].visible
    del g.ents[tw.id]                                   # снесли в тумане
    g.bld_at[6 * g.w + 12] = 0
    g.blocked[6 * g.w + 12] = 0
    g.fog.update(g)
    assert tw.id in [b.id for b in observe(g, 0).enemy_buildings]
    g.apply_command(C.move(0, [scout.id], (10, 6)))
    run(g, 80)
    assert tw.id not in [b.id for b in observe(g, 0).enemy_buildings]


def test_remembered_building_keeps_last_seen_hp():
    g = game(fog=True)
    scout = unit(g, 0, "archer", 9, 6)
    tw = building(g, 1, "tower", 12, 6)
    seen_hp = tw.hp
    g.apply_command(C.move(0, [scout.id], (2, 6)))
    run(g, 60)
    tw.hp = 7
    g.fog.update(g)
    (b,) = [b for b in observe(g, 0).enemy_buildings if b.id == tw.id]
    assert b.hp == seen_hp


def test_attack_on_hidden_target_rejected_and_chase_stops_in_fog():
    g = game(fog=True)
    s = unit(g, 0, "swordsman", 3, 6)
    e = unit(g, 1, "worker", 8, 6)
    assert g.apply_command(C.attack(0, [s.id], e.id))
    # цель телепортируется в туман: погоня обрывается, юнит не идёт к ней «знанием»
    g.unit_at[6 * g.w + 8] = 0
    e.x, e.y = 15, 0
    g.unit_at[0 * g.w + 15] = e.id
    g.fog.update(g)
    run(g, 5)
    assert s.order == "idle" or (s.order == "move" and s.o_pos == (3, 6))
    assert not g.apply_command(C.attack(0, [s.id], e.id))


def test_worker_does_not_pick_crystal_it_cannot_see():
    """Поле кончилось - рабочий ищет соседний кристалл только среди видимых. (2, 8) в
    пределах поиска (8 клеток от старого), но вне обзора рабочего (6)."""
    rows = [
        "..*.........A.......",
        "....................",
        "....................",
        "....................",
        "....................",
        "....................",
        "....................",
        "....................",
        "..*.................",
        "....................",
    ]
    g = game(rows=rows, fog=True, victory=False)
    w = unit(g, 0, "worker", 3, 1)
    g.crystals[(2, 0)] = rules.CARRY
    assert not g.fog.sees(0, 2, 8)
    g.apply_command(C.harvest(0, [w.id], (2, 0)))
    run(g, 150)
    assert (2, 0) not in g.crystals and g.players[0].stats["gathered"] == rules.CARRY
    assert not g.fog.sees(0, 2, 8)
    assert w.order == "idle"


def test_ai_receives_nothing_but_observation():
    """Контроллер в партии получает только Observation: подсунем бота, который проверяет
    тип каждого аргумента."""
    seen = []

    class Spy(RandomBot):
        def decide(self, obs):
            seen.append(type(obs))
            return super().decide(obs)
    play(maps.get("plains"), [Spy(), Spy()], seed=1, max_ticks=50)
    assert seen and set(seen) == {Observation}


def test_apm_limiter_caps_commands_per_minute():
    from game.ai.match import ApmLimiter, TICKS_PER_MINUTE
    lim = ApmLimiter(60, burst=5)
    passed = 0
    for t in range(TICKS_PER_MINUTE * 3):
        lim.tick()
        passed += len(lim.allow([C.stop(0, [1])] * 4))
    assert 60 * 3 <= passed <= 60 * 3 + 5
    rec = play(maps.get("plains"), [RandomBot(10), RandomBot(10)], seed=2, max_ticks=600,
               apm=(30, None))
    n0 = sum(1 for row in rec.commands if row[1] == 0)
    n1 = sum(1 for row in rec.commands if row[1] == 1)
    assert n0 <= 30 + 3 and n1 > 5 * n0


def test_worker_walks_to_remembered_crystal_even_if_it_is_gone_in_fog():
    """Кристалл выбрали в тумане. Хозяин помнит его - рабочий обязан дойти и увидеть, а не
    встать сразу: мгновенная остановка выдала бы, что кристалла уже нет."""
    rows = ["." * 20] * 6
    g = game(rows=rows, fog=True, victory=False)
    w = unit(g, 0, "worker", 1, 2)
    g.fog.crystals[0][(15, 2)] = 100      # видели раньше
    assert not g.fog.sees(0, 15, 2) and (15, 2) not in g.crystals
    assert g.apply_command(C.harvest(0, [w.id], (15, 2)))
    run(g, 20)
    assert w.order == "harvest" and w.x > 2
    run(g, 120)
    assert w.order == "idle" and (15, 2) not in g.fog.crystals[0]
