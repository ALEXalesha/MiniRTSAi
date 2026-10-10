"""Эволюция стратегии в лиге - только по команде:

    python -m game.train --trial                     # пробное поколение и прогноз времени
    python -m game.train --gens 20                   # с нуля (runs/league)
    python -m game.train --gens 30 --resume          # продолжить со снимка до 30 поколений
    python -m game.train --publish                   # середина облака -> game/models + паспорт

Процессов --processes (по умолчанию 2), в каждом один поток BLAS. Журнал - train.log
рядом со снимком, строка на поколение.
"""
import os

for _var in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ[_var] = "1"

import argparse  # noqa: E402
import multiprocessing as mp  # noqa: E402
import tempfile  # noqa: E402
import time  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m game.train")
    ap.add_argument("--run", default=os.path.join("runs", "league2"))
    ap.add_argument("--gens", type=int, default=20, help="до какого поколения учить")
    ap.add_argument("--population", type=int, default=12)
    ap.add_argument("--games", type=int, default=4, help="партий против каждого характера")
    ap.add_argument("--processes", type=int, default=2)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--trial", action="store_true")
    ap.add_argument("--publish", action="store_true")
    ap.add_argument("--passport-games", type=int, default=30)
    args = ap.parse_args(argv)

    from aikit.trainlog import TrainLog
    from game.ai import tournament
    from game.train.league import League

    with mp.get_context("spawn").Pool(args.processes) as pool:
        def evaluate(jobs):
            return tournament.run_jobs(jobs, pool=pool)

        if args.publish:
            from game.train.passport import publish
            lg = League(args.run).load()
            path = publish(lg, args.passport_games, pool)
            print(f"стратегия поколения {lg.gen} -> {path}")
            return 0

        if args.trial:
            run = tempfile.mkdtemp(prefix="minirts-trial-")
            lg = League(run, population=4, games_per_opponent=1, seed=args.seed)
            rec = lg.step(evaluate)
            per_game = rec["seconds"] / rec["games"]
            # в полном поколении: характеры по --games партий, два чемпиона по 2
            games = args.population * (args.games * 3 + 2 * 2)
            total = per_game * games * args.gens
            print(f"пробное поколение: {rec['games']} партий за {rec['seconds']:.0f} с "
                  f"({per_game:.1f} с на партию при {args.processes} процессах)")
            print(f"прогноз: {games} партий на поколение, {args.gens} поколений - "
                  f"около {total / 60:.0f} мин")
            return 0

        log = TrainLog(os.path.join(args.run, "train.log"))
        if args.resume:
            lg = League(args.run).load()
            log(f"продолжение с поколения {lg.gen}")
        else:
            lg = League(args.run, population=args.population, games_per_opponent=args.games,
                        seed=args.seed)
            log(f"старт: {args.population} кандидатов, {args.games} партии на соперника, "
                f"{args.processes} процесса")
        t0 = time.time()
        while lg.gen < args.gens:
            lg.step(evaluate, log)
            lg.save()
        log(f"готово: {lg.gen} поколений, {time.time() - t0:.0f} с в этом запуске, "
            f"всего {lg.elapsed / 60:.1f} мин; середина {lg.center()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
