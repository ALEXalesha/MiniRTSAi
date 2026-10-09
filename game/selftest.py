"""Самопроверка без экрана: python main.py --selftest итог.txt.

Нужна собранному exe (он без консоли, итог пишется в файл) и CI. Пока окна нет, она
проверяет симуляцию: партия с записью и повтор записи должны совпасть.
"""
import time
import traceback


def selftest(out_path):
    lines = []
    code = 0
    try:
        from game.version import VERSION
        lines.append(f"MiniRts {VERSION} самопроверка")
        started = time.time()
        from game.core.selfcheck import run_checks
        lines.extend(run_checks())
        lines.append(f"время {time.time() - started:.1f} с")
        lines.append("итог: OK")
    except Exception:  # noqa: BLE001 - самопроверка пишет любую ошибку в файл
        lines.append(traceback.format_exc())
        lines.append("итог: ОШИБКА")
        code = 1
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return code
