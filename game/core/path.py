"""Поиск пути по клеткам: A* для одного юнита и потоковое поле для группы.

Ходы - восемь направлений, прямой шаг стоит 10, диагональный 14. Срезать угол нельзя:
диагональ открыта, только если обе соседние прямые клетки свободны, - иначе юнит прошёл бы
сквозь угол стены или здания.

Цель A* - прямоугольник (точка, здание) и квадрат дальности: «встать в клетку», «подойти
вплотную к зданию», «подойти на выстрел». Если до цели не дойти (она в стене, за стеной,
закрыта зданиями), A* возвращает путь к ближайшей достижимой клетке - юнит не бьётся о
стену вечно, а встаёт как можно ближе.

Порядок соседей и разбор равных вершин в куче фиксированы - путь зависит только от карты,
так партия повторяется из записи.
"""
import heapq

INF = 1 << 30
# прямые, затем диагонали; порядок участвует в выборе между равными путями
DIRS = ((1, 0), (0, 1), (-1, 0), (0, -1), (1, 1), (-1, 1), (-1, -1), (1, -1))


def octile(dx, dy):
    dx, dy = abs(dx), abs(dy)
    return 10 * (dx + dy) - 6 * min(dx, dy)


def rect_delta(x, y, rect):
    x0, y0, x1, y1 = rect
    dx = x0 - x if x < x0 else (x - x1 if x > x1 else 0)
    dy = y0 - y if y < y0 else (y - y1 if y > y1 else 0)
    return dx, dy


def rect_dist2(x, y, rect):
    dx, dy = rect_delta(x, y, rect)
    return dx * dx + dy * dy


def isqrt_ceil(n):
    r = int(n ** 0.5)
    while r * r < n:
        r += 1
    while r > 0 and (r - 1) * (r - 1) >= n:
        r -= 1
    return r


def can_step(w, h, blocked, x, y, dx, dy):
    """Можно ли шагнуть из (x, y) в (x+dx, y+dy) по стенам и зданиям (юниты не учитываются)."""
    nx, ny = x + dx, y + dy
    if not (0 <= nx < w and 0 <= ny < h) or blocked[ny * w + nx]:
        return False
    if dx and dy and (blocked[y * w + nx] or blocked[ny * w + x]):
        return False
    return True


def astar(w, h, blocked, start, rect, r2=0, extra=None, max_nodes=None):
    """Путь из start к клеткам на расстоянии^2 <= r2 от прямоугольника rect (x0, y0, x1, y1).

    extra - множество индексов клеток, временно занятых (юниты рядом). Возвращает список
    клеток без стартовой; [] - уже на месте или ближе не подойти. Если цель недостижима,
    путь ведёт к достижимой клетке, ближайшей к цели (по прямой, при равенстве - короче путь).
    """
    sx, sy = start
    reach = isqrt_ceil(r2) * 14 if r2 else 0
    s = sy * w + sx
    if rect_dist2(sx, sy, rect) <= r2:
        return []
    g = {s: 0}
    parent = {s: -1}
    dx, dy = rect_delta(sx, sy, rect)
    best, best_key = s, (dx * dx + dy * dy, 0)
    heap = [(max(0, octile(dx, dy) - reach), 0, s)]
    counter = 0
    closed = set()
    found = -1
    limit = max_nodes or w * h
    while heap:
        _, _, cur = heapq.heappop(heap)
        if cur in closed:
            continue
        closed.add(cur)
        if len(closed) > limit:
            break
        cx, cy = cur % w, cur // w
        gc = g[cur]
        d2 = rect_dist2(cx, cy, rect)
        if d2 <= r2:
            found = cur
            break
        key = (d2, gc)
        if key < best_key:
            best, best_key = cur, key
        for ddx, ddy in DIRS:
            nx, ny = cx + ddx, cy + ddy
            if not (0 <= nx < w and 0 <= ny < h):
                continue
            n = ny * w + nx
            if blocked[n] or n in closed or (extra is not None and n in extra):
                continue
            if ddx and ddy and (blocked[cy * w + nx] or blocked[ny * w + cx]):
                continue
            ng = gc + (14 if ddx and ddy else 10)
            if ng < g.get(n, INF):
                g[n] = ng
                parent[n] = cur
                hx, hy = rect_delta(nx, ny, rect)
                counter += 1
                heapq.heappush(heap, (ng + max(0, octile(hx, hy) - reach), counter, n))
    end = found if found >= 0 else best
    out = []
    while end != s and end >= 0:
        out.append((end % w, end // w))
        end = parent[end]
    out.reverse()
    return out


def flow_field(w, h, blocked, targets):
    """Расстояние (10 за прямой шаг, 14 за диагональ) от каждой клетки до ближайшей из
    targets. Цель может стоять в стене - поле идёт от неё в свободные соседние клетки.
    Недостижимые клетки - INF."""
    dist = [INF] * (w * h)
    heap = []
    for (x, y) in targets:
        i = y * w + x
        if dist[i]:
            dist[i] = 0
            heap.append((0, i))
    heapq.heapify(heap)
    while heap:
        d, cur = heapq.heappop(heap)
        if d > dist[cur]:
            continue
        cx, cy = cur % w, cur // w
        for ddx, ddy in DIRS:
            nx, ny = cx + ddx, cy + ddy
            if not (0 <= nx < w and 0 <= ny < h):
                continue
            n = ny * w + nx
            if blocked[n]:
                continue
            # шаг n -> cur: углы проверяются у пары (n, cur), без учёта того, что цель - стена
            if ddx and ddy and (blocked[cy * w + nx] or blocked[ny * w + cx]):
                continue
            nd = d + (14 if ddx and ddy else 10)
            if nd < dist[n]:
                dist[n] = nd
                heapq.heappush(heap, (nd, n))
    return dist


def path_cost(path, start):
    x, y = start
    total = 0
    for nx, ny in path:
        total += 14 if (nx != x and ny != y) else 10
        x, y = nx, ny
    return total
