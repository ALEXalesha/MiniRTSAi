"""Числа игры: юниты, здания, урон. Всё в тактах (TICKS_PER_SECOND в секунду) и клетках.

Камень-ножницы-бумага через урон и скорость:
- мечник догоняет лучника (лучник почти не бронирован) и рубит его втрое сильнее, чем тот
  стреляет в ответ;
- лучник бьёт мечника издалека и быстрее бегает, поэтому выигрывает, если держит дистанцию;
- башня бьёт дальше лучника и сильнее всего по лучникам, но мечник сносит её быстрее;
- рабочий дешёвый и слабый, его дело - кристаллы и стройка.

Числа подбираются турнирами скриптовых ботов (план, шаги 5-6); меняя их, проверять
доли побед.
"""

TICKS_PER_SECOND = 10

START_RESOURCES = 150
START_WORKERS = 4
MAX_UNITS = 50            # юнитов у игрока одновременно; дальше обучение ждёт
QUEUE_MAX = 5
MAX_TICKS = 20 * 60 * TICKS_PER_SECOND   # 20 минут - ничья

CARRY = 8                 # кристаллов за ходку
HARVEST_TICKS = 12        # такты добычи у кристалла
CRYSTAL_AMOUNT = 150      # в одной клетке кристалла по умолчанию

MELEE_R2 = 2              # квадрат дальности ближнего боя: соседние клетки и диагональ

# hp, цена, такты обучения, такты на клетку (по диагонали x1.4), обзор, квадрат дальности,
# перезарядка удара
UNITS = {
    "worker":    dict(hp=30,  cost=50,  train=50, move=5, sight=6, r2=MELEE_R2, cooldown=10),
    "swordsman": dict(hp=110, cost=100, train=80, move=6, sight=6, r2=MELEE_R2, cooldown=10),
    "archer":    dict(hp=50,  cost=80,  train=70, move=5, sight=7, r2=16,       cooldown=12),
}

# размер стороны, hp, цена, такты стройки, обзор, что обучает
BUILDINGS = {
    "base":     dict(size=3, hp=500, cost=300, build=200, sight=7, trains=("worker",)),
    "barracks": dict(size=2, hp=300, cost=150, build=120, sight=5, trains=("swordsman", "archer")),
    "tower":    dict(size=1, hp=220, cost=120, build=100, sight=8, trains=(),
                     r2=25, cooldown=12),
}

# урон за удар: DAMAGE[кто][по кому]; "building" - любое здание
DAMAGE = {
    "worker":    {"worker": 3,  "swordsman": 2,  "archer": 3,  "building": 2},
    "swordsman": {"worker": 12, "swordsman": 10, "archer": 18, "building": 9},
    "archer":    {"worker": 8,  "swordsman": 7,  "archer": 6,  "building": 3},
    "tower":     {"worker": 10, "swordsman": 8,  "archer": 14, "building": 0},
}

COMBAT = ("swordsman", "archer")


def damage(attacker, target_kind):
    table = DAMAGE[attacker]
    return table[target_kind] if target_kind in table else table["building"]


def move_ticks(kind, diagonal):
    t = UNITS[kind]["move"]
    return t * 14 // 10 if diagonal else t


def stats(kind):
    return UNITS[kind] if kind in UNITS else BUILDINGS[kind]


def is_building(kind):
    return kind in BUILDINGS
