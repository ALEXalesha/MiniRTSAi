"""Что видит игрок - единственное, что получает ИИ.

observe(game, player) собирает неизменяемый снимок: свои юниты и здания целиком, чужие
юниты - только видимые сейчас, чужие здания - как их запомнил игрок (последний увиденный
вид, даже если в тумане их уже снесли), кристаллы - последний увиденный запас, рельеф -
только разведанные клетки. Карта (размер и места баз) известна всем заранее, как в любой
стратегии.

Закон честности (tests/test_honesty.py): любые изменения скрытого от игрока - юниты врага в
тумане, его деньги и очереди, кристаллы и стены за пределами разведанного - не меняют
снимок ни на бит, а значит, и решения ИИ.
"""
from typing import NamedTuple, Optional, Tuple

import numpy as np

UNKNOWN = 2


class MyUnit(NamedTuple):
    id: int
    kind: str
    x: int
    y: int
    hp: int
    order: str
    target: Optional[int]
    pos: Optional[Tuple[int, int]]
    carry: int
    busy: int
    atk: int


class MyBuilding(NamedTuple):
    id: int
    kind: str
    x: int
    y: int
    hp: int
    built: int              # тактов стройки осталось, 0 - готово
    queue: Tuple[str, ...]
    train_left: int
    rally: Optional[Tuple[int, int]]


class EnemyUnit(NamedTuple):
    id: int
    owner: int
    kind: str
    x: int
    y: int
    hp: int
    px: int                 # откуда пришёл: движение видно глазом
    py: int


class EnemyBuilding(NamedTuple):
    id: int
    owner: int
    kind: str
    x: int
    y: int
    hp: int
    built: int
    seen: int               # такт, когда видели в последний раз
    visible: bool


class Observation(NamedTuple):
    player: int
    tick: int
    w: int
    h: int
    starts: Tuple[Tuple[int, int], ...]
    resources: int
    population: int
    my_units: Tuple[MyUnit, ...]
    my_buildings: Tuple[MyBuilding, ...]
    enemy_units: Tuple[EnemyUnit, ...]
    enemy_buildings: Tuple[EnemyBuilding, ...]
    crystals: Tuple[Tuple[Tuple[int, int], int], ...]
    terrain: bytes          # 0 земля, 1 стена, 2 не разведано (здания и кристаллы - отдельно)
    visible: bytes          # 1 - видно сейчас
    over: bool

    # --- удобства для ботов: только из того, что уже в снимке ---

    def known_blocked(self):
        """Клетки, занятые по сведениям игрока: стены, кристаллы, свои и запомненные чужие
        здания. Неразведанное считается свободным (так ходят в незнакомом месте)."""
        w = self.w
        out = bytearray(1 if t == 1 else 0 for t in self.terrain)
        for (x, y), _ in self.crystals:
            out[y * w + x] = 1
        for b in self.my_buildings:
            s = SIZES[b.kind]
            for yy in range(b.y, b.y + s):
                for xx in range(b.x, b.x + s):
                    out[yy * w + xx] = 1
        for b in self.enemy_buildings:
            s = SIZES[b.kind]
            for yy in range(b.y, b.y + s):
                for xx in range(b.x, b.x + s):
                    out[yy * w + xx] = 1
        return out

    def sees(self, x, y):
        return self.visible[y * self.w + x] == 1

    def explored(self, x, y):
        return self.terrain[y * self.w + x] != UNKNOWN


from game.core.rules import BUILDINGS  # noqa: E402

SIZES = {k: v["size"] for k, v in BUILDINGS.items()}


def observe(game, player):
    fog = game.fog
    my_units, my_buildings, enemy_units = [], [], []
    for eid in sorted(game.ents):
        e = game.ents[eid]
        if e.owner == player:
            if e.building:
                my_buildings.append(MyBuilding(e.id, e.kind, e.x, e.y, e.hp, e.built,
                                               tuple(e.queue), e.train_left, e.rally))
            else:
                my_units.append(MyUnit(e.id, e.kind, e.x, e.y, e.hp, e.order, e.o_target,
                                       e.o_pos, e.carry, e.busy, e.atk))
        elif not e.building and fog.sees_entity(player, e):
            enemy_units.append(EnemyUnit(e.id, e.owner, e.kind, e.x, e.y, e.hp, e.px, e.py))
    enemy_buildings = []
    for bid, (kind, owner, x, y, hp, built, seen) in sorted(fog.buildings[player].items()):
        vis = fog.sees_rect(player, x, y, SIZES[kind])
        enemy_buildings.append(EnemyBuilding(bid, owner, kind, x, y, hp, built, seen, vis))
    explored = fog.explored[player]
    walls = np.frombuffer(bytes(game.map.walls), dtype=np.uint8).reshape(game.h, game.w)
    terrain = np.where(explored, walls, UNKNOWN).astype(np.uint8).tobytes()
    return Observation(
        player=player, tick=game.tick, w=game.w, h=game.h,
        starts=tuple(game.map.starts),
        resources=game.players[player].resources,
        population=len(my_units),
        my_units=tuple(my_units), my_buildings=tuple(my_buildings),
        enemy_units=tuple(enemy_units), enemy_buildings=tuple(enemy_buildings),
        crystals=tuple(sorted(fog.crystals[player].items())),
        terrain=terrain, visible=fog.vis_bytes[player], over=game.over)
