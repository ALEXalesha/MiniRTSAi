"""Уровни и характеры: как собирается ИИ, паспорт стратегии и сила уровней."""
import pytest

from game.ai import tournament
from game.ai.levels import CHARACTERS, LEVELS, make_ai
from game.ai.match import play
from game.ai.scripted import SPACE
from game.core import maps
from game.train import passport


@pytest.mark.parametrize("character", CHARACTERS)
@pytest.mark.parametrize("level", sorted(LEVELS))
def test_make_ai_gives_bot_and_limits(level, character):
    bot, every, apm = make_ai(level, character)
    assert every == LEVELS[level]["think_every"] and apm == LEVELS[level]["apm"]
    assert set(bot.params) >= set(SPACE)
    assert bot.character == character


def test_levels_think_slower_and_click_less_going_down():
    order = ["novice", "medium", "strong"]
    for a, b in zip(order, order[1:]):
        assert LEVELS[a]["think_every"] > LEVELS[b]["think_every"]
        assert LEVELS[a]["apm"] < LEVELS[b]["apm"]


def test_unknown_character_rejected():
    with pytest.raises(ValueError):
        make_ai("medium", "chaos")


def test_published_strategy_has_passport_and_valid_params():
    data = passport.load()
    if data is None:
        pytest.skip("стратегия ещё не обучена")
    for k, (lo, hi, kind) in SPACE.items():
        assert lo <= data["params"][k] <= hi
    for opp in passport.OPPONENTS:
        s = data["passport"][opp]
        assert len(s["results"]) == s["games"] and 0 <= s["score"] <= 1


@pytest.mark.slow
def test_passport_first_games_replay():
    """Первые партии паспорта с теми же зёрнами дают те же исходы."""
    data = passport.load()
    if data is None:
        pytest.skip("стратегия ещё не обучена")
    for opp in ("rush", "economy"):
        for i in range(2):
            r, _, _ = tournament.one_game(data["params"], opp, i, passport.PASSPORT_SEED)
            assert r == data["passport"][opp]["results"][i], (opp, i)


@pytest.mark.slow
def test_strong_level_beats_novice_of_same_character():
    wins = 0
    for i in range(4):
        a, ea, pa = make_ai("strong", "economy")
        b, eb, pb = make_ai("novice", "economy")
        first = i % 2 == 0
        ctrls, every, apm = ([a, b], (ea, eb), (pa, pb)) if first else ([b, a], (eb, ea), (pb, pa))
        rec = play(maps.get(tournament.MAPS[i % 3]), ctrls, seed=50 + i, think_every=every, apm=apm)
        wins += rec.game.winner == (0 if first else 1)
    assert wins >= 3
