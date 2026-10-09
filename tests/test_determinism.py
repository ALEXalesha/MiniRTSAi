"""Детерминированность: одинаковые карта, зерно и команды дают одинаковую партию; запись
проигрывается до бита; любая подмена в записи ловится на ближайшей контрольной точке."""
import copy
import json
import os
import subprocess
import sys

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from game.ai.bots import RandomBot
from game.ai.match import play
from game.core import maps
from game.core import record as R
from tests.helpers import DUEL, check_invariants

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def random_match(seed, rows=DUEL, ticks=600, fog=True):
    m = maps.parse(rows) if isinstance(rows, list) else rows
    return play(m, [RandomBot(), RandomBot()], seed=seed, fog=fog, max_ticks=ticks,
                start_resources=600)


def hashes_each_tick(seed):
    out = []
    play(maps.parse(DUEL), [RandomBot(), RandomBot()], seed=seed, max_ticks=300,
         start_resources=600, on_tick=lambda g: out.append(g.state_hash()))
    return out


def test_same_seed_same_game_every_tick():
    a, b = hashes_each_tick(5), hashes_each_tick(5)
    assert len(a) == 300 and a == b


def test_different_seed_different_game():
    assert hashes_each_tick(5)[-1] != hashes_each_tick(6)[-1]


def test_replay_reproduces_game_exactly():
    rec = random_match(11)
    g = rec.game
    assert len(rec.commands) > 100
    r = R.replay(rec.to_json())
    assert r.state_hash() == g.state_hash()
    assert (r.tick, r.over, r.winner) == (g.tick, g.over, g.winner)


def test_record_survives_json_file(tmp_path):
    rec = random_match(12, ticks=300)
    p = tmp_path / "game.json"
    rec.save(str(p))
    data = R.load(str(p))
    assert R.replay(data).state_hash() == rec.game.state_hash()


def test_replay_until_stops_midway():
    rec = random_match(13, ticks=400)
    g = R.replay(rec.to_json(), until=200)
    assert g.tick == 200 and g.state_hash() == R.replay(rec.to_json(), until=200).state_hash()


def test_tampered_record_is_caught():
    rec = random_match(14, ticks=400).to_json()
    bad = copy.deepcopy(rec)
    # убрать команды игрока 0 после такта 100: партия обязана разойтись
    bad["commands"] = [row for row in bad["commands"] if row[0] <= 100 or row[1] != 0]
    assert len(bad["commands"]) < len(rec["commands"])
    with pytest.raises(R.ReplayMismatch) as e:
        R.replay(bad)
    assert int(str(e.value).split()[1].rstrip(":")) > 100     # расхождение найдено после 100
    bad2 = copy.deepcopy(rec)
    bad2["config"]["seed"] += 1
    with pytest.raises(R.ReplayMismatch):
        R.replay(bad2)


def test_copy_midgame_continues_identically():
    rec = random_match(15, ticks=200)
    g1 = rec.game
    g2 = copy.deepcopy(g1)
    for _ in range(150):
        g1.step()
        g2.step()
    assert g1.state_hash() == g2.state_hash()


def test_replay_is_independent_of_python_hash_seed(tmp_path):
    """Порядок обхода множеств в Python зависит от PYTHONHASHSEED. Симуляция не должна от
    него зависеть: запись, сделанная здесь, проигрывается в другом процессе с другим зерном."""
    rec = random_match(16, ticks=300)
    p = tmp_path / "rec.json"
    rec.save(str(p))
    code = ("import sys; sys.path.insert(0, %r)\n"
            "from game.core import record as R\n"
            "print(R.replay(R.load(%r)).state_hash())") % (ROOT, str(p))
    env = dict(os.environ, PYTHONHASHSEED="12345")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                         env=env, timeout=120, cwd=ROOT)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == rec.game.state_hash()


@settings(max_examples=12, deadline=None)
@given(seed=st.integers(0, 10 ** 6), fog=st.booleans())
def test_random_games_keep_invariants(seed, fog):
    """Случайные команды не ломают состояние: юнит и клетка всегда согласованы, никто не
    стоит в стене, деньги не уходят в минус, hp не выше максимума."""
    play(maps.parse(DUEL), [RandomBot(5), RandomBot(5)], seed=seed, fog=fog, max_ticks=250,
         start_resources=800, on_tick=check_invariants)


@pytest.mark.slow
def test_full_random_game_on_real_map_replays():
    rec = play(maps.get("crossroads"), [RandomBot(4), RandomBot(4)], seed=3, max_ticks=1500)
    data = json.loads(json.dumps(rec.to_json()))
    assert R.replay(data).state_hash() == rec.game.state_hash()
