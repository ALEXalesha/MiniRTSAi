# Мутанты MiniRts для tools/mutate.py: (имя, файл, было, стало, проверки).
# Каждый ломает одно правило; проверки из последнего поля обязаны упасть.

SIM, PATH = "game/core/sim.py", "game/core/path.py"
OBS, FOG = "game/core/observation.py", "game/core/fog.py"
T_SIM, T_PATH = "tests/test_sim.py", "tests/test_pathing.py"
T_HON, T_DET = "tests/test_honesty.py", "tests/test_determinism.py"
T_BOTS = "tests/test_bots.py"

# Не мутант: проверка видимости в _nearest_enemy. Ищут только в своём обзоре (d2 <= sight^2),
# а круг обзора шире (r^2 + r) - враг там всегда виден, мутант был бы равнозначен коду.

MUTANTS = [
    # симуляция
    ("sim: убитый в такте не бьёт", SIM,
     "            if e is not None and not e.building:\n",
     "            if e is not None and not e.building and e.hp > 0:\n", T_SIM),
    ("sim: обучение без денег", SIM,
     "                if pl.resources < cost:\n                    return False",
     "                if False:\n                    return False", T_SIM),
    ("sim: команда чужому юниту", SIM,
     "if e is None or e.owner != c.player or e.building or uid in seen:",
     "if e is None or e.building or uid in seen:", T_SIM),
    ("sim: атака цели в тумане", SIM,
     "if t is None or t.owner == c.player or not self.visible_to(c.player, t):",
     "if t is None or t.owner == c.player:", T_SIM + " " + T_HON),
    ("sim: соседний кристалл из тумана", SIM,
     "if d2 > 64 or not sees(u.owner, x, y):", "if d2 > 64:", T_HON),
    ("sim: свои не меняются местами", SIM,
     "if (b.owner == u.owner and b.busy == 0",
     "if (False and b.owner == u.owner and b.busy == 0", T_PATH),
    ("sim: яма поля - остановка вместо A*", SIM,
     "            return self._advance_rect(u, (pos[0], pos[1], pos[0], pos[1]), 0)\n"
     "        if self._swap_or_wait",
     "            return \"arrived\"\n        if self._swap_or_wait", T_PATH),
    # поиск пути
    ("path: срезание углов", PATH,
     "        if dx and dy and (blocked[y * w + nx] or blocked[ny * w + x]):\n"
     "            continue\n        out.append",
     "        out.append", T_PATH),
    ("path: недостижимая цель - стоять", PATH,
     "end = found if found >= 0 else best", "end = found if found >= 0 else s", T_PATH),
    ("path: ленивое поле не досчитывает", PATH,
     "        while not done[i] and heap:", "        while False:", T_PATH),
    ("path: обновление соседей только в строке", PATH,
     "        for yy in range(max(0, y - 1), min(h, y + 2)):",
     "        for yy in range(y, y + 1):", T_PATH),
    # туман и наблюдение
    ("obs: все враги в снимке", OBS,
     "elif not e.building and fog.sees_entity(player, e):", "elif not e.building:", T_HON),
    ("obs: рельеф без тумана", OBS,
     "terrain = np.where(explored, walls, UNKNOWN)",
     "terrain = np.where(True, walls, UNKNOWN)", T_HON),
    ("fog: память зданий без взгляда", FOG,
     "            if e.owner != p and self.sees_rect(p, e.x, e.y, e.size):",
     "            if e.owner != p:", T_HON),
    ("fog: кристаллы без взгляда", FOG,
     "            if vb[pos[1] * w + pos[0]]:\n                cmem[pos] = amount",
     "            if True:\n                cmem[pos] = amount", T_HON),
    # запись и ИИ
    ("record: хэши не сверяются", "game/core/record.py",
     "if verify and g.tick in hashes and hashes[g.tick] != g.state_hash():",
     "if False:", T_DET),
    ("match: APM без лимита", "game/ai/match.py",
     "            if self.tokens >= TICKS_PER_MINUTE:", "            if True:", T_HON),
]
MUTANTS.append(
    ("sim: выбранный в тумане кристалл виден сразу", SIM,
     "        if pos not in self.crystals and not self.fog.sees(u.owner, *pos):",
     "        if False:", T_HON))
MUTANTS += [
    ("sim: очки без зданий", SIM,
     "        if a[0] != b[0]:\n", "        if False:\n", "tests/test_victory.py"),
    ("sim: рабочие в цене армии", SIM,
     "if e.owner == owner and not e.building and e.kind in rules.COMBAT)",
     "if e.owner == owner and not e.building)", "tests/test_victory.py"),
    ("sim: по времени всегда ничья", SIM,
     "            self.winner, self.end_reason = self.points_winner()",
     "            self.winner, self.end_reason = None, \"draw\"", "tests/test_victory.py"),
]
