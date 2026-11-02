"""Safe bounds for waypoints with |A-P| + |P-B| <= total distance budget.

The feasible region is a prolate ellipsoid (a line segment when budget=|AB|).
Its enclosing midpoint sphere has radius budget/2; the exact axis-aligned box
is also safe for system coordinate filters. Final tool semantics stay separate.
"""
from copy import deepcopy
import math


class Envelope:
    def __init__(self, origin, destination, budget):
        self.origin, self.destination = tuple(origin), tuple(destination)
        values = self.origin + self.destination + (budget,)
        if (len(self.origin) != 3 or len(self.destination) != 3
                or any(isinstance(value, bool) or not math.isfinite(value) for value in values)
                or budget < 0):
            raise ValueError('Invalid route geometry or distance budget.')
        direct = math.dist(self.origin, self.destination)
        self.epsilon = max(1e-7, max(math.ulp(float(value)) for value in values) * 16)
        if not math.isfinite(direct) or budget + self.epsilon < direct:
            raise ValueError('Route distance budget is shorter than the direct distance.')
        self.budget = max(budget, direct)
        self.center = tuple(a / 2 + b / 2 for a, b in zip(self.origin, self.destination))
        self.radius = self.budget / 2
        # sqrt((L-D)*(L+D))/2 without subtracting nearly equal squares,
        # rounding D/L to one, or overflowing the intermediate product.
        minor = math.sqrt(max(0, self.budget - direct)) * math.sqrt(self.budget / 4 + direct / 4)
        unit = tuple((b - a) / direct for a, b in zip(self.origin, self.destination)) if direct else (0, 0, 0)
        self.box = []
        for center, component in zip(self.center, unit):
            span = math.hypot(self.radius * component, minor * math.sqrt(max(0, 1 - component ** 2)))
            self.box.append((center - span - self.epsilon, center + span + self.epsilon))

    def contains(self, point):
        return (point is not None and all(math.isfinite(v) for v in point)
                and math.dist(self.origin, point) + math.dist(point, self.destination)
                <= self.budget + self.epsilon)

    def tighten(self, kind, payload, conditions, notes):
        payload = deepcopy(payload)
        filters = payload['filters']
        if kind == 'systems':
            for axis, (lo, hi) in zip(('x', 'y', 'z'), self.box):
                previous = filters.get(axis)
                if previous is not None:
                    # Do not reinterpret unsupported filter shapes or loosen a
                    # user's coordinate condition. Local checks remain intact.
                    values = previous.get('value')
                    if previous.get('comparison') != '<=>' or not isinstance(values, list) or len(values) != 2:
                        continue
                    lo, hi = max(lo, values[0]), min(hi, values[1])
                    if lo > hi:
                        from filter_engine import Contradiction
                        raise Contradiction('Route bounds do not intersect the coordinate conditions.')
                filters[axis] = dict(comparison='<=>', value=[lo, hi])
            notes.append('路线椭球坐标包围盒已下推')
        # An ordinary distance field is relative to the existing API reference;
        # replacing that reference would change its meaning.
        ordinary_distance = any(c.get('type') != 'distance' and c.get('field') == 'distance' for c in conditions)
        radius = self.radius + self.epsilon
        if not ordinary_distance and radius < filters.get('distance', {}).get('max', math.inf):
            payload.pop('reference_system', None)
            payload['reference_coords'] = dict(zip(('x', 'y', 'z'), self.center))
            filters['distance'] = dict(max=radius)
            notes.append('路线中点包围球已下推；仍逐项核对原始条件')
        return payload
