"""Команды игрока - единственный способ влиять на партию. И человек, и ИИ отдают одни и те же
команды; симуляция проверяет каждую и молча отбрасывает недопустимые (чужие юниты, цель в
тумане, здание за пределами разведанного).

    move         units, pos             идти; группа идёт потоковым полем
    attack_move  units, pos             идти, по пути нападая на всех, кого видно
    attack       units, target          напасть на видимую цель
    harvest      units, pos             рабочие добывают кристалл в клетке pos
    build        units, pos, arg=вид    рабочие строят здание, pos - левый верхний угол
    train        units=(здание,), arg   обучить юнита (цена списывается сразу)
    cancel       units=(здание,)        снять последний в очереди, цена возвращается
    rally        units=(здание,), pos   куда идти обученным
    stop         units                  остановиться
"""
from typing import NamedTuple, Optional, Tuple

KINDS = ("move", "attack_move", "attack", "harvest", "build", "train", "cancel", "rally", "stop")


class Command(NamedTuple):
    player: int
    kind: str
    units: Tuple[int, ...] = ()
    pos: Optional[Tuple[int, int]] = None
    target: Optional[int] = None
    arg: Optional[str] = None

    def to_json(self):
        return [self.player, self.kind, list(self.units),
                list(self.pos) if self.pos is not None else None, self.target, self.arg]

    @classmethod
    def from_json(cls, a):
        player, kind, units, pos, target, arg = a
        return cls(int(player), str(kind), tuple(int(u) for u in units),
                   tuple(int(v) for v in pos) if pos is not None else None,
                   int(target) if target is not None else None, arg)


def move(player, units, pos):
    return Command(player, "move", tuple(units), tuple(pos))


def attack_move(player, units, pos):
    return Command(player, "attack_move", tuple(units), tuple(pos))


def attack(player, units, target):
    return Command(player, "attack", tuple(units), None, target)


def harvest(player, units, pos):
    return Command(player, "harvest", tuple(units), tuple(pos))


def build(player, units, kind, pos):
    return Command(player, "build", tuple(units), tuple(pos), None, kind)


def train(player, building, kind):
    return Command(player, "train", (building,), None, None, kind)


def cancel(player, building):
    return Command(player, "cancel", (building,))


def rally(player, building, pos):
    return Command(player, "rally", (building,), tuple(pos))


def stop(player, units):
    return Command(player, "stop", tuple(units))
