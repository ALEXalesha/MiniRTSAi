"""MiniRts: маленькая стратегия в реальном времени против честного ИИ.

Вход игры по контракту PythonAiGames: GAME_INFO и create_widget(ctx). Qt загружается
только в create_widget - симуляция, ИИ и обучение работают без него.
"""
from game.version import VERSION

GAME_INFO = {
    "id": "minirts",
    "title": {"ru": "Мини-стратегия", "en": "MiniRts"},
    "summary": {"ru": "Маленькая стратегия в реальном времени против ИИ, который видит только то, что открыто в тумане",
                "en": "A small real-time strategy game against an AI that only sees what the fog of war reveals"},
    "preview": "docs/preview.png",
    "version": VERSION,
}

APP_NAME = "MiniRts"


def create_widget(ctx):
    """ctx: aikit.Context. Виджет с картой, меню и панелями (план, шаг 8)."""
    from game.ui.widget import GameWidget
    return GameWidget(ctx)
