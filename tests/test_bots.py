"""Скриптовые боты: играют по правилам, честно, детерминированно и сильнее случайного."""
import copy
import random

import pytest

from game.ai import tournament
from game.ai.match import play
from game.ai.scripted import PRESETS, ScriptedBot
from game.core import maps
from game.core.observation import observe
from tests.test_honesty import midgame, scramble_hidden


@pytest.mark.parametrize("character", sorted(PRESETS))
def test_bot_builds_economy_and_army_alone(character):
    """Против пустого соперника (он ничего не делает) бот за 5 минут игры добывает,
    строит казарму и учит бойцов."""
    from game.ai.match import Controller
    rec = play(maps.get("plains"), [ScriptedBot(character), Controller()], seed=1,
               max_ticks=3000)
    g = rec.game
    st = g.players[0].stats
    assert st["gathered"] >= 600
    assert any(b.kind == "barracks" and not b.built for b in g.buildings_list(0))
    assert sum(1 for u in g.units_list(0) if u.kind != "worker") >= 3
    assert st["rejected"] <= st["made"] + 20       # почти все команды осмысленны


@pytest.mark.parametrize("character", sorted(PRESETS))
def test_bot_decisions_ignore_hidden_state(character):
    """Закон честности для каждого характера: перетряска скрытого не меняет решений."""
    for seed in range(4):
        g = midgame(seed, 300 + 150 * seed)
        bot = ScriptedBot(character)
        bot.reset(0, seed)
        bot.decide(observe(g, 0))           # бот запомнил что-то о партии
        g2 = copy.deepcopy(g)
        scramble_hidden(g2, 0, random.Random(seed))
        g2.fog.update(g2)
        b1, b2 = copy.deepcopy(bot), copy.deepcopy(bot)
        assert b1.decide(observe(g, 0)) == b2.decide(observe(g2, 0))
        assert b1.thoughts() == b2.thoughts()


def test_bot_game_is_deterministic():
    a = tournament.one_game("rush", "economy", 0, seed=3, max_ticks=1500)
    b = tournament.one_game("rush", "economy", 0, seed=3, max_ticks=1500)
    assert a[2].game.state_hash() == b[2].game.state_hash()


@pytest.mark.slow
@pytest.mark.parametrize("character", sorted(PRESETS))
def test_scripted_bots_beat_random(character):
    s = tournament.match(character, "random", 6, seed=1)
    assert s["wins"] >= 5, s


@pytest.mark.slow
def test_bot_vs_bot_games_end_with_a_winner():
    s = tournament.match("rush", "defense", 4, seed=2)
    assert s["draws"] <= 1, s
