<div align="center">

# MiniRts

**A small real-time strategy game against an honest AI: it only sees what the fog of war reveals. Human vs AI and AI vs AI.**

[Русская версия](README.ru.md)

[![License](https://img.shields.io/badge/license-MIT-blue)](LICENSE)

</div>

Work in progress: the simulation, pathfinding, fog of war with an honesty law and
scripted bots are done (plan steps 1-5 in `docs/spec.md`). No window yet; next come a
strategy tuned by league evolution, a tactical network and the interface.

## The game

A 48 × 48 grid, one resource (crystals). The base trains workers and takes deliveries,
the barracks trains swordsmen and archers, the tower shoots on its own. You win by
destroying every enemy building. Three ready maps and a generator; every map is
symmetric under a 180° rotation.

| Unit | HP | Cost | Ticks per cell | Range | Strong against |
|---|---|---|---|---|---|
| Worker | 30 | 50 | 5 | melee | mines and builds |
| Swordsman | 110 | 100 | 6 | melee | archers: 18 damage per hit |
| Archer | 50 | 80 | 5 | 4 cells | swordsmen, if it keeps distance |

## A simulation that replays bit for bit

Fixed 10 ticks per second, integers only, no randomness outside the seed. Same map, seed
and commands give the same game, so a replay file is the map, the seed and the commands
per tick, plus a state hash every 50 ticks; a replay fails at the first diverging tick.
This holds in another process with another `PYTHONHASHSEED` too.

Hits within one tick are simultaneous. Before that, two identical swordsmen never died
together: the one with the lower id won.

## Pathfinding

Single units use A* to the exact cell; groups share a flow field and stop within a radius
large enough for all of them. An unreachable target sends the unit to the nearest
reachable cell. Friendly units swap places with standing or oncoming friends, so two
groups pass each other in a one-cell corridor. Flow fields are lazy (Dijkstra stops once
the requested cell is final) and survive map changes for 30 ticks, with A* as the
fallback: a 1500-tick random game went from 26 to 8 seconds. Trap maps are in
`tests/test_pathing.py`.

## Honesty

The AI only gets `observe(game, player)`: own units, enemy units visible now, enemy
buildings as remembered, last seen crystal amounts, explored terrain. Unit ids are
random, so an id says nothing about how many units the enemy has trained.
`tests/test_honesty.py` scrambles everything hidden and requires the observation and every
bot's decisions to stay identical. The law found a leak in the simulation itself: a worker
sent to a crystal already mined out in the fog stopped at once, revealing that it was
gone. Now it walks there to look.

## Scripted bots

Rush, defense and economy are the same rules with different numbers. 12 games per pair,
sides and maps alternate:

| | vs random | vs defense | vs economy |
|---|---|---|---|
| Rush | 100% | 25% | 0% |
| Defense | 100% | - | 12.5% |
| Economy | 100% | 87.5% | - |

Economy is the strongest for now. Tuning the numbers is the next plan step (league
evolution).

## Tests

182 pytest checks, 91 of them game-specific (the rest belong to the shared aikit).
`tools/mutate.py` breaks the product in 18 places and every mutant is caught. PySide6 and
numpy only, no pygame. MIT license.
