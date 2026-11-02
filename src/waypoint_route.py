"""Bounded candidate routing: fewest station stops/extra systems, then distance.

This is geometric waypoint planning, not a navigable jump or fuel route.
Optimality is relative to the verified, capped candidate pool only.
"""
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
import heapq
import math

import filter_engine as eng


@dataclass(frozen=True)
class Criteria:
    origin: str
    destination: str
    max_extra_ly: float = 100
    candidates_per_group: int = 12
    max_pages: int = 5

    def validate(self):
        if not self.origin.strip() or not self.destination.strip():
            raise ValueError('请填写起点和终点星系')
        if (isinstance(self.max_extra_ly, bool) or not math.isfinite(self.max_extra_ly)
                or self.max_extra_ly < 0):
            raise ValueError('最大额外路程必须为非负有限数')
        if type(self.candidates_per_group) is not int or not 1 <= self.candidates_per_group <= 30:
            raise ValueError('每组候选数必须为 1~30 的整数')
        if type(self.max_pages) is not int or not 1 <= self.max_pages <= 100:
            raise ValueError('最多页数必须为 1~100 的整数')
        return self


def check_stop(stop):
    if stop is not None and stop.is_set():
        raise InterruptedError('Search cancelled; no complete route was produced.')


def validate_groups(groups):
    if not 1 <= len(groups) <= 6:
        raise ValueError('请添加 1~6 个要求组')
    groups = deepcopy(groups)
    for group in groups:
        if not isinstance(group, dict):
            raise ValueError('每个要求组必须包含星系或站点条件')
        if group.get('kind') not in ('systems', 'stations') or not group.get('conditions'):
            raise ValueError('每个要求组必须包含星系或站点条件')
        group['conditions'] = eng.normalize_conditions(group['kind'], group['conditions'])
    return groups


def cross_match(groups, pools, *, stop=None):
    """Reuse explicit returned evidence across groups, never missing fields.

    This can discover one-stop coverage even if a station fell outside another
    group's capped results. Server-only facts without local evidence stay unknown.
    """
    originals = [list(pool) for pool in pools]
    coords = {}
    for index, group in enumerate(groups):
        known = {item['key'] for item in pools[index]}
        for other, pool in zip(groups, originals):
            if other['kind'] != group['kind']:
                continue
            for item in pool:
                check_stop(stop)
                if item['key'] in known:
                    continue
                row = deepcopy(item['row'])
                if any(c.get('field') and eng.field_raw(group['kind'], row, c['field']) is None
                       for c in group['conditions']):
                    continue
                if eng.match_all(group['kind'], row, group['conditions'], coords):
                    pools[index].append(point(group['kind'], row))
                    known.add(item['key'])


def point(kind, row):
    coords = eng.result_coords(kind, row)
    system = row.get('system_name') if kind == 'stations' else row.get('name')
    if not system or not row.get('name') or coords is None or not all(map(math.isfinite, coords)):
        return None
    # Same names in different systems must never merge; conflicting identities
    # remain separate rather than falsely claiming one-stop coverage.
    key = (kind, system.strip().casefold(), str(row.get('name')).strip().casefold(),
           str(row.get('id', '')) if kind == 'stations' else '')
    return dict(key=key, system=system, name=row['name'], kind=kind, coords=coords,
                mask=0, evidence={}, row=deepcopy(row))


def solve(origin, destination, pools, max_extra_ly, *, stop=None, endpoint_names=None):
    """Exact lexicographic search within pools; never silently use partial cover."""
    direct = eng.dist3(origin, destination)
    budget = direct + max_extra_ly
    points = {}
    for index, pool in enumerate(pools):
        for item in pool:
            key = item['key']
            if key in points and points[key]['coords'] != item['coords']:
                raise ValueError('Conflicting coordinates for the same destination.')
            target = points.setdefault(key, deepcopy(item))
            target['mask'] |= 1 << index
            target['evidence'][index] = deepcopy(item['row'])
    points = list(points.values())
    initial = 0
    for item in points:
        at_endpoint = (item['system'].strip().casefold() in {name.strip().casefold() for name in endpoint_names}
                       if endpoint_names is not None else item['coords'] in (origin, destination))
        if item['kind'] == 'systems' and at_endpoint:
            initial |= item['mask']
    # Visiting a station also visits its system. Never transfer station evidence
    # to another station, even when they share system coordinates.
    systems = {}
    for item in points:
        if item['kind'] == 'systems':
            systems.setdefault(item['system'].strip().casefold(), []).append(item)
    for item in points:
        if item['kind'] == 'stations':
            for system in systems.get(item['system'].strip().casefold(), []):
                if system['coords'] != item['coords']:
                    raise ValueError('Conflicting system and station coordinates.')
                item['mask'] |= system['mask']
                item['evidence'].update(system['evidence'])
    full = (1 << len(pools)) - 1
    # State includes stop count: fewer stops but a longer prefix must not
    # dominate a shorter prefix needed to stay within the distance budget.
    heap = [(0, 0.0, initial, -1, ())]
    best = {(initial, -1, 0): 0.0}
    answer = None
    while heap:
        check_stop(stop)
        count, length, mask, last, path = heapq.heappop(heap)
        if answer is not None and count > answer[0]:
            break
        if length > best.get((mask, last, count), math.inf):
            continue
        current = origin if last == -1 else points[last]['coords']
        total = length + eng.dist3(current, destination)
        if total > budget + 1e-8:
            continue
        if mask == full:
            if answer is None or (count, total) < answer[:2]:
                answer = (count, total, path)
            continue
        if answer is not None and count >= answer[0]:
            continue
        for index, item in enumerate(points):
            covered = mask | item['mask']
            if covered == mask:
                continue
            distance = length + eng.dist3(current, item['coords'])
            if distance + eng.dist3(item['coords'], destination) > budget + 1e-8:
                continue
            state = (covered, index, count + 1)
            if distance < best.get(state, math.inf):
                best[state] = distance
                heapq.heappush(heap, (count + 1, distance, covered, index, path + (index,)))
    if answer is None:
        return dict(route=None, direct_ly=direct, missing=[i for i, pool in enumerate(pools) if not pool])
    count, total, path = answer
    route, previous, covered = [], origin, initial
    for index in path:
        item = deepcopy(points[index])
        item['requirements'] = [i for i in range(len(pools)) if item['mask'] & (1 << i) and not covered & (1 << i)]
        item['leg_ly'] = eng.dist3(previous, item['coords'])
        route.append(item)
        previous, covered = item['coords'], covered | item['mask']
    return dict(route=route, stops=count, total_ly=total, direct_ly=direct,
                extra_ly=max(0, total - direct), final_leg_ly=eng.dist3(previous, destination),
                endpoint_requirements=[i for i in range(len(pools)) if initial & (1 << i)], missing=[])


def search(criteria, groups, *, stop=None, progress=None):
    criteria.validate()
    groups = validate_groups(groups)
    check_stop(stop)
    origin_name, origin, _ = eng.resolve_ref(criteria.origin.strip())
    destination_name, destination, _ = eng.resolve_ref(criteria.destination.strip())
    direct = eng.dist3(origin, destination)
    # Any feasible waypoint lies within this bound of BOTH endpoints.
    bound = direct + criteria.max_extra_ly
    pools, notes = [], []
    for index, group in enumerate(groups):
        check_stop(stop)
        eng._report(progress, f"{index + 1}/{len(groups)} · {group.get('name', '')}")
        conditions = deepcopy(group['conditions']) + [dict(type='distance', ref_system=ref,
            min_ly=None, max_ly=bound, mode='inside') for ref in (origin_name, destination_name)]
        def usable(row):
            item = point(group['kind'], row)
            return item is not None and (eng.dist3(origin, item['coords'])
                + eng.dist3(item['coords'], destination) <= bound + 1e-8)
        group_notes = []
        rows, _, _ = eng.search(group['kind'], conditions, want=criteria.candidates_per_group,
            max_pages=criteria.max_pages, row_filter=usable, stop=stop, progress=progress, notes=group_notes,
            route_bound=(origin, destination, bound))
        check_stop(stop)
        pools.append([point(group['kind'], row) for row in rows if usable(row)])
        notes.extend(f"{index + 1}: {note}" for note in group_notes)
    cross_match(groups, pools, stop=stop)
    result = solve(origin, destination, pools, criteria.max_extra_ly, stop=stop,
                   endpoint_names=(origin_name, destination_name))
    result.update(groups=groups, criteria=criteria, pools=pools, notes=notes,
                  origin=origin_name, destination=destination_name,
                  fetched_at=datetime.now(timezone.utc).isoformat())
    return result
