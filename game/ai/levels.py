"""Уровни и характеры ИИ.

Характер - какие числа стратегии: раш, оборона, экономика или обученный в лиге
(game/models/strategy.json; если файла нет - экономика). Уровень - как быстро ИИ думает и
сколько команд в минуту может отдать: новичок медлит и щёлкает редко, сильный - почти
как опытный игрок. Числа не дают ИИ знать больше: видит он одинаково на всех уровнях.
"""
from game.ai.scripted import PRESETS, ScriptedBot

LEVELS = {
    #          думает раз в N тактов, команд в минуту
    "novice": dict(think_every=25, apm=20),
    "medium": dict(think_every=10, apm=50),
    "strong": dict(think_every=5, apm=120),
}
CHARACTERS = ("rush", "defense", "economy", "league")


def league_params():
    from game.train.passport import load
    data = load()
    return data["params"] if data else None


def make_ai(level="medium", character="league"):
    """(контроллер, think_every, apm) для game.ai.match.play."""
    lv = LEVELS[level]
    if character == "league":
        params = league_params()
        bot = ScriptedBot(params=params) if params else ScriptedBot("economy")
        bot.character = bot.name = "league"
    else:
        if character not in PRESETS:
            raise ValueError(f"неизвестный характер {character!r}")
        bot = ScriptedBot(character)
    return bot, lv["think_every"], lv["apm"]
