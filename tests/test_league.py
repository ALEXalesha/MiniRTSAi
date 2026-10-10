"""Эволюция в лиге: перевод чисел, сам CEM на поддельной оценке, продолжение с места."""
import numpy as np
from hypothesis import given, settings
from hypothesis import strategies as st

from game.ai.scripted import PRESETS, SPACE, clip_params
from game.train.league import KEYS, League, from_unit, to_unit

TARGET = {"workers": 12, "barracks_at": 6, "barracks": 2, "towers": 1, "tower_at": 10,
          "archers": 0.3, "attack_at": 10, "retreat_at": 3, "scout_at": 400}


def fake_evaluate(jobs):
    """Чем ближе кандидат к TARGET, тем больше побед; без игр, мгновенно."""
    t = to_unit(TARGET)
    out = []
    per = {}
    for c, opp, i, seed, kw in jobs:
        key = tuple(sorted(c.items()))
        per.setdefault(key, 0)
        d = float(np.abs(to_unit(c) - t).mean())
        n = per[key]
        per[key] += 1
        out.append(("W" if (n % 10) / 10 < 1 - 2 * d else "L", 3000))
    return out


@given(vec=st.lists(st.floats(-3, 3, allow_nan=False), min_size=len(KEYS), max_size=len(KEYS)))
@settings(max_examples=200, deadline=None)
def test_any_vector_gives_valid_params(vec):
    p = from_unit(np.array(vec))
    for k, (lo, hi, kind) in SPACE.items():
        assert lo <= p[k] <= hi
        assert isinstance(p[k], kind)


def test_presets_survive_round_trip_after_clipping():
    for name, p in PRESETS.items():
        clipped = clip_params(p)
        assert from_unit(to_unit(clipped)) == clipped


def test_all_candidates_play_the_same_games():
    lg = League("unused", population=3, games_per_opponent=2)
    cands, _ = lg.candidates()
    jobs = lg.jobs(cands)
    per = {}
    for ci, oi, (c, opp, i, seed, kw) in jobs:
        per.setdefault(ci, []).append((str(opp), i, seed))
    assert per[0] == per[1] == per[2]
    assert len(per[0]) == 3 * 2
    lg.hall = [cands[0]]
    assert len(lg.jobs(cands)) == 3 * (3 * 2 + lg.hall_games)


def test_cem_moves_toward_better_region(tmp_path):
    lg = League(str(tmp_path), population=12, games_per_opponent=4, seed=1)
    d0 = np.abs(lg.mu - to_unit(TARGET)).mean()
    first = lg.step(fake_evaluate)
    for _ in range(14):
        last = lg.step(fake_evaluate)
    d1 = np.abs(lg.mu - to_unit(TARGET)).mean()
    assert d1 < d0 * 0.5
    assert last["mean"] > first["mean"]
    assert len(lg.hall) == lg.hall_size


def test_resume_continues_exactly(tmp_path):
    a = League(str(tmp_path / "a"), population=6, games_per_opponent=2, seed=3)
    for _ in range(3):
        a.step(fake_evaluate)
    b = League(str(tmp_path / "b"), population=6, games_per_opponent=2, seed=3)
    for _ in range(2):
        b.step(fake_evaluate)
        b.save()
    c = League(str(tmp_path / "b")).load()
    c.step(fake_evaluate)
    assert c.gen == a.gen == 3
    assert np.allclose(c.mu, a.mu) and np.allclose(c.sigma, a.sigma)
    assert c.hall == a.hall
