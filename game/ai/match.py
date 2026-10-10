"""Партия между ИИ (и любыми «контроллерами»): кто когда думает и сколько команд может отдать.

Контроллер получает только Observation (game.core.observation) - ссылки на партию у него
нет. Думает раз в think_every тактов (стороны со сдвигом на половину, чтобы не ходить
«одновременно» всегда в один такт), а команды проходят через ограничитель APM: ведро
жетонов на apm команд в минуту игры. Лишние команды отбрасываются и считаются - честный ИИ
не может щёлкать быстрее, чем позволяет его уровень.
"""
from game.core import rules
from game.core.observation import observe
from game.core.record import Recorder

TICKS_PER_MINUTE = 60 * rules.TICKS_PER_SECOND


class Controller:
    """Основа ИИ. decide(obs) -> список команд от имени obs.player."""
    name = "controller"

    def reset(self, player, seed):
        self.player = player
        self.seed = seed

    def decide(self, obs):
        return []

    def thoughts(self):
        """Для «Мыслей ИИ»: короткий план и что он знает о сопернике."""
        return {}


class ApmLimiter:
    """Ведро жетонов: apm команд в минуту, в запасе не больше burst."""

    def __init__(self, apm, burst=None):
        self.apm = apm
        self.burst = burst if burst is not None else max(3, apm // 10)
        self.tokens = self.burst * TICKS_PER_MINUTE   # в долях: жетон = TICKS_PER_MINUTE
        self.dropped = 0
        self.passed = 0

    def tick(self):
        cap = self.burst * TICKS_PER_MINUTE
        self.tokens = min(cap, self.tokens + self.apm)

    def allow(self, commands):
        out = []
        for c in commands:
            if self.tokens >= TICKS_PER_MINUTE:
                self.tokens -= TICKS_PER_MINUTE
                out.append(c)
                self.passed += 1
            else:
                self.dropped += 1
        return out


def play(gmap, controllers, seed=0, fog=True, think_every=5, apm=(None, None),
         max_ticks=rules.MAX_TICKS, meta=None, on_tick=None, stop=None, **game_kw):
    """Сыграть партию до конца. controllers - по одному на игрока; apm - лимит команд в
    минуту на каждого (None - без лимита); think_every - число или по числу на игрока. Возвращает Recorder (партия и запись)."""
    rec = Recorder(gmap, seed=seed, fog=fog, max_ticks=max_ticks, meta=meta, **game_kw)
    g = rec.game
    for p, c in enumerate(controllers):
        c.reset(p, seed * 1009 + p)
    limiters = [ApmLimiter(a) if a else None for a in apm]
    every = list(think_every) if isinstance(think_every, (tuple, list)) else [think_every] * len(controllers)
    while not g.over:
        cmds = []
        for p, c in enumerate(controllers):
            lim = limiters[p]
            if lim is not None:
                lim.tick()
            if (g.tick + p * (every[p] // 2)) % every[p]:
                continue
            out = [x for x in c.decide(observe(g, p)) if x.player == p]
            if lim is not None:
                out = lim.allow(out)
            cmds.extend(out)
        rec.step(cmds)
        if on_tick is not None:
            on_tick(g)
        if stop is not None and stop():
            break
    rec.limiters = limiters
    return rec
