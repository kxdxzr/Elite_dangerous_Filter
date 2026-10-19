"""Position-based rare-goods estimates; ordinary transfer stars are not verified."""
import math

import filter_engine as eng
import pve_cache


def check_stop(stop):
    if stop is not None and stop.is_set():
        raise InterruptedError('Neutron candidate search cancelled.')


OUTBOUND_RANGE = 40
RETURN_RANGE = 50
ANCHOR_RADIUS = 200
MAX_ARRIVAL_LS = 100
MAX_DIRECTION_DEG = 30
MAX_DETOUR_RATIO = .10
ALIGNMENT_TIERS = (
    ('优先顺路', 30, .10),
    ('适度绕行', 45, .25),
    ('宽松候选', 60, .50),
)
NOTE = '中子辅助目标查找为实验性功能。顺路几何条件决定命中：逐势力30°／10% → 45°／25% → 60°／50%，有结果即停，投影不越过目标。40／50 ly模型仅作内部参考，不因模型未省跳而排除候选。仅使用来源200 ly内、到达距离≤100 Ls的中子星；未验证实际中转星或燃油，不保证实际省跳或全势力有结果。'


def coordinates(values):
    if values is None or len(values) != 3 or any(isinstance(v, bool) for v in values):
        raise ValueError('Missing or invalid system coordinates.')
    result = tuple(float(v) for v in values)
    if not all(math.isfinite(v) for v in result):
        raise ValueError('Non-finite system coordinates.')
    return result


def lower_bound(distance, jump_range):
    return max(0, math.ceil(distance / jump_range - 1e-9))


def alignment(origin, target, anchor_coords, max_angle=MAX_DIRECTION_DEG, max_detour=MAX_DETOUR_RATIO):
    """Outbound alignment; reject reverse, overshooting or costly detours."""
    direct = math.dist(origin, target)
    if direct <= 1e-9:
        return None
    to_anchor = tuple(a - o for a, o in zip(anchor_coords, origin))
    to_target = tuple(t - o for t, o in zip(target, origin))
    first = math.dist(origin, anchor_coords)
    dot = sum(a * b for a, b in zip(to_anchor, to_target))
    projection = dot / (direct * direct)
    angle = (math.degrees(math.acos(max(-1., min(1., dot / (first * direct)))))
             if first > 1e-9 else 0.)
    detour = max(0., first + math.dist(anchor_coords, target) - direct)
    ratio = detour / direct
    if (projection < -1e-9 or projection > 1 + 1e-9
            or angle > max_angle + 1e-9 or ratio > max_detour + 1e-9):
        return None
    return dict(direction_deg=angle, detour_ly=detour, detour_ratio=ratio)


def load_anchors(source, origin, stop=None, http=None):
    """Cache only complete catalogues; never interpret failed queries as empty."""
    origin = coordinates(origin)
    http = http or eng._http_json

    def load():
        seen, anchors = set(), {}
        for page in range(100):
            check_stop(stop)
            data = http(eng.SPansh_BASE + '/bodies/search', {
                'filters': {'subtype': {'value': ['Neutron Star']},
                            'distance': {'max': ANCHOR_RADIUS}},
                'reference_coords': dict(zip(('x', 'y', 'z'), origin)),
                'size': 500, 'page': page}, compressed=True)
            rows = data.get('results') if isinstance(data, dict) else None
            if not isinstance(rows, list):
                raise ValueError('Invalid neutron catalogue response.')
            added = 0
            for row in rows:
                check_stop(stop)
                name = str(row.get('system_name') or '').strip()
                ident = (name.casefold(), str(row.get('id64', row.get('name', ''))))
                if not name or not ident[1] or row.get('subtype') != 'Neutron Star':
                    raise ValueError('Invalid neutron body identity/type.')
                if ident in seen:
                    continue
                seen.add(ident)
                added += 1
                raw = row.get('distance_to_arrival')
                if raw is None or isinstance(raw, bool):
                    raise ValueError('Unknown neutron arrival distance.')
                arrival = float(raw)
                if not math.isfinite(arrival) or arrival < 0:
                    raise ValueError('Invalid neutron arrival distance.')
                if arrival > MAX_ARRIVAL_LS:
                    continue
                key = name.casefold()
                if key in anchors:
                    continue
                # Body rows may not contain coordinates; resolve the system exactly.
                hit = eng._lookup_exact(name)
                check_stop(stop)
                if hit is None:
                    raise ValueError('Missing neutron system coordinates: ' + name)
                xyz = coordinates(hit[1])
                if math.dist(origin, xyz) <= ANCHOR_RADIUS + 1e-7:
                    anchors[key] = dict(name=name, coords=xyz, arrival_ls=arrival)
            if rows and not added:
                raise ValueError('Repeated neutron catalogue page.')
            if len(rows) < 500:
                total = data.get('count')
                if isinstance(total, (int, float)) and total > len(seen):
                    raise ValueError('Incomplete neutron catalogue.')
                check_stop(stop)
                return list(anchors.values())
        raise ValueError('Neutron catalogue page limit reached.')

    key = 'rare-neutron-anchors-v1:' + source.casefold() + ':' + repr(origin)
    return pve_cache.cached(key, load, 7 * 86400)[0]


def estimate_leg(start, end, anchors, jump_range, stop=None):
    """Directed shortest path with optimistic, unverified ordinary transfer legs.

    A charged departure covers up to 4R once; any remainder is estimated at R.
    Such edges are NOT actual jump-by-jump itineraries, even if savings are positive.
    """
    nodes = [start] + [coordinates(a['coords']) for a in anchors] + [end]
    charged = {coordinates(a['coords']) for a in anchors}
    costs, paths, visited = [math.inf] * len(nodes), [[] for _ in nodes], set()
    costs[0] = 0
    for _ in nodes:
        check_stop(stop)
        u = min((i for i in range(len(nodes)) if i not in visited), key=lambda i: costs[i])
        if u == len(nodes) - 1:
            break
        visited.add(u)
        for v in range(len(nodes)):
            if v in visited:
                continue
            distance = math.dist(nodes[u], nodes[v])
            cost = lower_bound(distance, jump_range)
            boosted = False
            if nodes[u] in charged and distance > 0:
                boosted_cost = 1 + lower_bound(max(0, distance - 4 * jump_range), jump_range)
                if boosted_cost < cost:
                    cost, boosted = boosted_cost, True
            if costs[u] + cost < costs[v]:
                costs[v] = costs[u] + cost
                names = [a['name'] for a in anchors if coordinates(a['coords']) == nodes[u]] if boosted else []
                paths[v] = paths[u] + names
    return int(costs[-1]), paths[-1]


class SavingsFilter:
    def __init__(self, stop=None, progress=None, anchor_loader=load_anchors):
        self.stop, self.progress, self.anchor_loader = stop, progress, anchor_loader
        self.cache, self.catalogues = {}, {}
        self.evaluated = 0

    def evaluate(self, source, destination, origin, target):
        check_stop(self.stop)
        key = (source.casefold(), destination.casefold())
        if key in self.cache:
            return dict(self.cache[key])
        self.evaluated += 1
        try:
            origin, target = coordinates(origin), coordinates(target)
            source_key = (source.casefold(), origin)
            if source_key not in self.catalogues:
                if self.progress:
                    self.progress('加载来源200 ly内中子星')
                try:
                    self.catalogues[source_key] = self.anchor_loader(source, origin, stop=self.stop)
                except InterruptedError:
                    raise
                except Exception as exc:
                    self.catalogues[source_key] = exc
            anchors = self.catalogues[source_key]
            if isinstance(anchors, Exception):
                raise anchors
            distance = math.dist(origin, target)
            normal_out = lower_bound(distance, OUTBOUND_RANGE)
            normal_in = lower_bound(distance, RETURN_RANGE)
            ordinary = normal_out + normal_in
            answer = dict(status='not_proven', outbound=normal_out, inbound=normal_in,
                          ordinary_min=ordinary, neutron_total=ordinary, saved=0,
                          outbound_anchors=[], inbound_anchors=[], anchor_count=len(anchors))
            candidates = []
            for anchor in anchors:
                check_stop(self.stop)
                geometry, tier_index = None, None
                for index, (_, max_angle, max_detour) in enumerate(ALIGNMENT_TIERS):
                    geometry = alignment(origin, target, coordinates(anchor['coords']), max_angle, max_detour)
                    if geometry is not None:
                        tier_index = index
                        break
                if tier_index is None:
                    continue
                # Optional model hint, never an eligibility gate. Failure of the
                # hint must not discard an otherwise aligned neutron candidate.
                model_error = ''
                try:
                    outbound, out_names = estimate_leg(origin, target, [anchor], OUTBOUND_RANGE, self.stop)
                    inbound, in_names = estimate_leg(target, origin, [anchor], RETURN_RANGE, self.stop)
                except InterruptedError:
                    raise
                except Exception as exc:
                    outbound, inbound, out_names, in_names = normal_out, normal_in, [], []
                    model_error = str(exc)
                saved = ordinary - outbound - inbound
                candidate = dict(answer, status='candidate', outbound=outbound, inbound=inbound,
                                 neutron_total=outbound + inbound, saved=saved,
                                 outbound_anchors=out_names, inbound_anchors=in_names,
                                 model_available=not model_error, model_error=model_error,
                                 route_anchor=anchor['name'], alignment_tier=tier_index,
                                 alignment_label=ALIGNMENT_TIERS[tier_index][0], **geometry)
                candidates.append(candidate)
            if candidates:
                # Earliest successful tier, then least detour. Per-Power tier
                # selection is handled over the whole scanned batch by the caller.
                answer = min(candidates, key=lambda c: (c['alignment_tier'], c['detour_ly'], c['direction_deg'],
                                                        c['neutron_total'], c['route_anchor']))
        except InterruptedError:
            raise
        except Exception as exc:
            answer = dict(status='unknown', reason=str(exc))
        self.cache[key] = answer
        return dict(answer)

    def __call__(self, source, destination):
        return self.evaluate(source, destination, eng.get_system_coords(source), eng.get_system_coords(destination))
