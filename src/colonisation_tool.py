"""Colonisation candidates, with existential body/ring groups and strict eligibility."""
import math
from itertools import count
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

import filter_engine as eng
import pve_cache


BODY_FIELDS = {
    'type': '天体类别', 'star_subtype': '恒星类型', 'is_main_star': '是否主星',
    'subtype': '星球类型', 'is_landable': '可着陆',
    'terraforming_state': '地球化状态', 'gravity': '重力 G',
    'distance_to_arrival': '到达距离 Ls', 'surface_temperature': '表面温度 K',
    'surface_pressure': '表面气压 atm', 'atmosphere': '大气类型',
    'volcanism_type': '火山活动类型', 'radius': '半径 km',
    'earth_masses': '地球质量', 'is_rotational_period_tidally_locked': '潮汐锁定',
    'rotational_period': '自转周期 天', 'orbital_period': '公转周期 天',
    'orbital_eccentricity': '轨道偏心率', 'orbital_inclination': '轨道倾角 度',
    'semi_major_axis': '轨道半长轴 AU', 'reserve_level': '储量等级',
    'materials': '地表材料', 'signals': '信号类型', 'signal_count': '信号数量',
    'estimated_mapping_value': '天体估算测绘价值',
    'estimated_scan_value': '天体估算扫描价值',
    '_is_moon': '是卫星', '_has_moons': '拥有卫星', '_is_binary': '互绕成员（关系推定）',
    'ring.type': '星环类型', 'ring.inner_radius': '星环内半径 m',
    'ring.outer_radius': '星环外半径 m', 'ring.mass': '星环质量（源数据单位）',
}
RING_FIELDS = {key: value for key, value in BODY_FIELDS.items()
               if key.startswith('ring.') or key in ('distance_to_arrival', 'reserve_level', 'subtype')}
NUMERIC_FIELDS = set(BODY_FIELDS) - {
    'type', 'star_subtype',
    'subtype', 'is_landable', 'terraforming_state', 'atmosphere', 'volcanism_type',
    'is_rotational_period_tidally_locked', 'reserve_level', 'materials', 'signals', 'ring.type'}
BOOL_FIELDS = {'is_main_star', 'is_landable', 'is_rotational_period_tidally_locked', '_is_moon', '_has_moons', '_is_binary'}
NUMERIC_FIELDS -= BOOL_FIELDS
OPERATORS = ('=', '!=', 'in', '>', '>=', '<', '<=', 'between')
VALUES = {
    'type': ['Planet', 'Star'],
    # Spansh /bodies/field_values/subtype, verified 2026-10-25. Display-only
    # suggestions; unknown future types remain usable through manual entry.
    'star_subtype': [
        'O (Blue-White) Star', 'B (Blue-White) Star', 'A (Blue-White) Star',
        'F (White) Star', 'G (White-Yellow) Star', 'K (Yellow-Orange) Star',
        'M (Red dwarf) Star', 'L (Brown dwarf) Star', 'T (Brown dwarf) Star',
        'Y (Brown dwarf) Star', 'Neutron Star', 'Black Hole', 'Supermassive Black Hole',
        'A (Blue-White super giant) Star', 'B (Blue-White super giant) Star',
        'F (White super giant) Star', 'G (White-Yellow super giant) Star',
        'K (Yellow-Orange giant) Star', 'M (Red giant) Star', 'M (Red super giant) Star',
        'C Star', 'CJ Star', 'CN Star', 'MS-type Star', 'S-type Star',
        'Herbig Ae/Be Star', 'T Tauri Star',
        'White Dwarf (D) Star', 'White Dwarf (DA) Star', 'White Dwarf (DAB) Star',
        'White Dwarf (DAV) Star', 'White Dwarf (DAZ) Star', 'White Dwarf (DB) Star',
        'White Dwarf (DBV) Star', 'White Dwarf (DBZ) Star', 'White Dwarf (DC) Star',
        'White Dwarf (DCV) Star', 'White Dwarf (DQ) Star',
        'Wolf-Rayet Star', 'Wolf-Rayet C Star', 'Wolf-Rayet N Star',
        'Wolf-Rayet NC Star', 'Wolf-Rayet O Star'],
    'subtype': ['Earth-like world', 'Water world', 'Ammonia world', 'High metal content world',
                'Metal-rich body', 'Rocky body', 'Rocky Ice world', 'Icy body',
                'Class I gas giant', 'Class II gas giant', 'Class III gas giant',
                'Class IV gas giant', 'Class V gas giant', 'Gas giant with water-based life',
                'Gas giant with ammonia-based life', 'Helium-rich gas giant', 'Water giant'],
    'ring.type': ['Metallic', 'Metal Rich', 'Rocky', 'Icy'],
    'terraforming_state': ['Terraformable', 'Terraformed', 'Not terraformable', 'Terraforming'],
    'reserve_level': ['Pristine', 'Major', 'Common', 'Low', 'Depleted'],
    'is_landable': ['true', 'false'], 'is_rotational_period_tidally_locked': ['true', 'false'],
    'signals': ['Biological', 'Geological', 'Human', 'Guardian', 'Thargoid', 'Other'],
    'atmosphere': ['No atmosphere'],
}
VALUES.update({key: ['true', 'false'] for key in BOOL_FIELDS})


def annotate_relationships(bodies):
    """Derive relationships only from immediate parents, never shared stellar ancestry."""
    children = {}
    uncertain = False
    for body in bodies:
        parents = body.get('parents')
        if not isinstance(parents, list) or not parents or not isinstance(parents[0], dict):
            uncertain = uncertain or body.get('type') == 'Planet'
            continue
        parent = parents[0]
        if parent.get('id64') is not None:
            children.setdefault(str(parent['id64']), []).append(body)
    for body in bodies:
        if body.get('type') != 'Planet':
            continue
        body.update(_is_moon=None, _is_binary=None, _relations='')
        own_children = children.get(str(body.get('id64')), []) if body.get('id64') is not None else []
        moons = [child for child in own_children if child.get('type') == 'Planet']
        body['_has_moons'] = True if moons else None if uncertain or body.get('id64') is None else False
        parents = body.get('parents')
        if not isinstance(parents, list) or not parents or not isinstance(parents[0], dict):
            continue
        parent = parents[0]
        body['_is_moon'] = parent.get('type') == 'Planet' if parent.get('type') in ('Planet', 'Star', 'Null') else None
        if parent.get('type') != 'Null':
            body['_is_binary'] = False if parent.get('type') in ('Planet', 'Star') else None
        elif parent.get('id64') is not None:
            siblings = children.get(str(parent['id64']), [])
            if not uncertain and len(siblings) == 2 and all(s.get('type') == 'Planet' for s in siblings):
                periods = [number(s.get('orbital_period')) for s in siblings]
                if None not in periods and all(periods):
                    body['_is_binary'] = math.isclose(abs(periods[0]), abs(periods[1]), rel_tol=1e-6)
                    if body['_is_binary']:
                        body['_relations'] = 'Binary (inferred): ' + ', '.join(s['name'] for s in siblings if s is not body)
        if moons:
            body['_relations'] += ('; ' if body['_relations'] else '') + 'Moons: ' + ', '.join(m['name'] for m in moons)


def number(value):
    if isinstance(value, bool):
        return None
    try:
        n = float(value)
        return n if math.isfinite(n) else None
    except (ValueError, TypeError):
        return None


def optional_number(value):
    if value is None or isinstance(value, str) and not value.strip():
        return None
    n = number(value)
    if n is None or n < 0:
        raise ValueError('Enter a finite non-negative number, or leave blank.')
    return n


@dataclass
class Criteria:
    reference: str = ''
    radius: object = None
    populated_radius: object = None
    populated_min_distance: object = None
    minimum_value: object = None
    value_field: str = 'estimated_mapping_value'
    body_mode: str = 'AND'
    ring_mode: str = 'AND'
    body_groups: list = field(default_factory=list)
    ring_groups: list = field(default_factory=list)
    max_pages: object = None  # Legacy saved/API setting; colonisation now pages automatically.
    want: int = 100

    def validate(self):
        self.reference = self.reference.strip()
        for key in ('radius', 'populated_radius', 'populated_min_distance', 'minimum_value'):
            setattr(self, key, optional_number(getattr(self, key)))
        if (self.populated_min_distance is not None and self.populated_radius is not None
                and self.populated_min_distance > self.populated_radius):
            raise ValueError('The nearest-populated distance minimum exceeds the maximum.')
        if self.radius is not None and not self.reference:
            raise ValueError('A reference system is required for the regional radius.')
        if self.value_field not in ('estimated_mapping_value', 'estimated_scan_value', 'landmark_value'):
            raise ValueError('Invalid system value field.')
        if self.body_mode not in ('AND', 'OR') or self.ring_mode not in ('AND', 'OR'):
            raise ValueError('Group combination must be AND or OR.')
        for key in ('want',):
            value = getattr(self, key)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError('Result limit must be a positive integer.')
        for groups, fields in ((self.body_groups, BODY_FIELDS), (self.ring_groups, RING_FIELDS)):
            for group in groups:
                if not isinstance(group, list) or not group:
                    raise ValueError('Each group needs at least one condition.')
                for condition in group:
                    if condition.get('field') not in fields or condition.get('op') not in OPERATORS:
                        raise ValueError('Invalid body/ring condition.')
                    value = str(condition.get('value', '')).strip()
                    key, op = condition['field'], condition['op']
                    if not value:
                        raise ValueError('Each condition needs a value.')
                    if key in NUMERIC_FIELDS:
                        bounds = value.split('|') if op == 'between' else [value]
                        if op == 'in' or len(bounds) != (2 if op == 'between' else 1) or any(number(v) is None for v in bounds):
                            raise ValueError('Numeric conditions need a number; between uses min|max.')
                        if op == 'between' and float(bounds[0]) > float(bounds[1]):
                            raise ValueError('The lower bound exceeds the upper bound.')
                    elif op not in ('=', '!=', 'in'):
                        raise ValueError('Text and boolean fields use =, != or in.')
                    elif key in BOOL_FIELDS and (op == 'in' or value.casefold() not in ('true', 'false')):
                        raise ValueError('Boolean values must be true or false.')
                    elif op == 'in' and any(not v.strip() for v in value.split('|')):
                        raise ValueError('Separate non-empty choices with |.')
        return self


def combine(values, mode='AND'):
    """Three-valued logic: unknown is never converted to a positive match."""
    if not values:
        return True
    if mode == 'AND':
        return False if False in values else None if None in values else True
    return True if True in values else None if None in values else False


def condition_match(record, condition):
    key, op, expected = condition['field'], condition['op'], str(condition['value']).strip()
    if key in ('star_subtype', 'is_main_star', 'subtype'):
        required_type = 'Planet' if key == 'subtype' else 'Star'
        if record.get('type') != required_type:
            return False if record.get('type') else None
        if key == 'star_subtype':
            key = 'subtype'
    key = key.removeprefix('ring.')
    actual = record.get(key)
    if actual is None:
        return None
    if condition['field'] in NUMERIC_FIELDS:
        actual = number(actual)
        if actual is None:
            return None
        if op == 'between':
            lo, hi = map(float, expected.split('|'))
            return lo <= actual <= hi
        target = float(expected)
        return {'=': actual == target, '!=': actual != target, '>': actual > target,
                '>=': actual >= target, '<': actual < target, '<=': actual <= target}[op]
    if condition['field'] in BOOL_FIELDS:
        if type(actual) is not bool:
            return None
        return (actual == (expected.casefold() == 'true')) != (op == '!=')
    if isinstance(actual, list):
        if any(not isinstance(v, dict) or not isinstance(v.get('name'), str) for v in actual):
            return None
        actual = [v['name'].casefold() for v in actual]
    elif isinstance(actual, str):
        actual = [actual.casefold()]
    else:
        return None
    choices = expected.split('|') if op == 'in' else [expected]
    hit = any(v.strip().casefold() in actual for v in choices)
    return not hit if op == '!=' else hit


def match_body_group(body, group):
    # Old groups remain planet-only, including radius/temperature-only groups.
    # Selecting category or a star-specific field explicitly opts into stars.
    explicit = any(c['field'] in ('type', 'star_subtype', 'is_main_star') for c in group)
    if body.get('type') not in (('Planet', 'Star') if explicit else ('Planet',)):
        return False if body.get('type') else None
    basic = [c for c in group if not c['field'].startswith('ring.')]
    rings = [c for c in group if c['field'].startswith('ring.')]
    values = [condition_match(body, c) for c in basic]
    if rings:
        records = body.get('rings')
        values.append(None if not isinstance(records, list) else combine([
            combine([condition_match(ring, c) for c in rings]) if isinstance(ring, dict) else None
            for ring in records], 'OR') if records else False)
    return combine(values)


def match_groups(bodies, groups, mode, rings=False):
    matches, outcomes = [], []
    for index, group in enumerate(groups, 1):
        names, values = [], []
        for body in bodies:
            if rings:
                records = body.get('rings')
                if not isinstance(records, list):
                    values.append(None)
                    continue
                for ring in records:
                    hit = combine([condition_match(ring if c['field'].startswith('ring.') else body, c)
                                   for c in group]) if isinstance(ring, dict) else None
                    values.append(hit)
                    if hit is True:
                        names.append(f"{body['name']} / {ring.get('name', '?')}")
            else:
                hit = match_body_group(body, group)
                values.append(hit)
                if hit is True:
                    names.append(body['name'])
        outcomes.append(combine(values, 'OR') if values else None)
        if names:
            matches.append(f"{index}: " + ', '.join(names))
    return combine(outcomes, mode), '; '.join(matches)


def top_scan_planets(records, expected_count=None):
    """Rank recorded planets only; missing prices never become zero or mapping values."""
    if not isinstance(records, list):
        return [], False
    complete = expected_count is None or len(records) == expected_count
    ranked, seen = [], set()
    for body in records:
        if not isinstance(body, dict) or not body.get('type'):
            complete = False
            continue
        if body['type'] != 'Planet':
            continue
        value = number(body.get('estimated_scan_value'))
        if not body.get('name') or value is None or value < 0:
            complete = False
            continue
        ident = str(body.get('id64', body['name'].casefold()))
        if ident in seen:
            continue
        seen.add(ident)
        ranked.append(dict(name=body['name'], subtype=body.get('subtype') or 'Unknown',
                           estimated_scan_value=value))
    ranked.sort(key=lambda b: (-b['estimated_scan_value'], b['name'].casefold()))
    return ranked[:3], complete


def eligible(system):
    population, stations, permit = system.get('population'), system.get('stations'), system.get('needs_permit')
    if eng.is_excluded_system('systems', system):
        return False
    if number(population) is not None and number(population) != 0 or isinstance(stations, list) and stations or permit is True:
        return False
    if number(population) is None or not isinstance(stations, list) or type(permit) is not bool:
        return None
    return True


def check_stop(stop):
    if stop is not None and stop.is_set():
        raise InterruptedError('Search cancelled; results are incomplete.')


def confirm_station_absence(names, refresh=False, stop=None):
    def load():
        targets = {name.casefold(): [] for name in names}
        seen = set()
        for page in range(100):
            check_stop(stop)
            data = eng._http_json(eng.SPansh_BASE + '/stations/search', {
                'filters': {'system_name': {'value': names}}, 'size': 500, 'page': page}, compressed=True)
            rows = data.get('results') if isinstance(data, dict) else None
            if not isinstance(rows, list):
                raise ValueError('Invalid station response; absence cannot be confirmed.')
            added = 0
            for row in rows:
                if not isinstance(row, dict) or not row.get('system_name') or not row.get('name'):
                    raise ValueError('Missing station identity; coverage unknown.')
                key = row['system_name'].casefold()
                if key not in targets:
                    raise ValueError('Unexpected system in station response.')
                ident = str(row.get('id', (key, row['name'])))
                if ident not in seen:
                    seen.add(ident)
                    added += 1
                    targets[key].append(row)
            if rows and not added:
                raise ValueError('Repeated station page; coverage incomplete.')
            if len(rows) < 500:
                count = data.get('count')
                if isinstance(count, (int, float)) and count < 10000 and count > len(seen):
                    raise ValueError('Station count exceeds returned coverage.')
                return targets
        raise ValueError('Station page limit reached; coverage incomplete.')
    key = 'colonisation-stations-v1:' + '\n'.join(sorted(n.casefold() for n in names))
    return pve_cache.cached(key, load, 300, refresh)[0]


def load_bodies(names, refresh=False, stop=None):
    """Reuse complete per-system records even when callers change their batches."""
    import copy
    result, missing = {}, []
    unique = {name.casefold(): name for name in names}
    for key, name in unique.items():
        check_stop(stop)
        hit, records = pve_cache.peek('body-system-v1:' + key, 300) if not refresh else (False, None)
        if hit and isinstance(records, list):
            result[key] = copy.deepcopy(records)
        else:
            missing.append(name)
    if missing:
        metadata = {}
        with eng.request_control.context(stop):
            loaded = _load_bodies_batch(missing, refresh, stop, metadata=metadata)
        for name in missing:
            key = name.casefold()
            records = loaded.get(key)
            if not isinstance(records, list):
                raise ValueError('Missing system body coverage.')
        for name in missing:
            key = name.casefold()
            pve_cache.put('body-system-v1:' + key, loaded[key], fetched_at=metadata.get('fetched_at'))
            result[key] = copy.deepcopy(loaded[key])
    return result


def _load_bodies_batch(names, refresh=False, stop=None, metadata=None):
    """Fetch complete full-record pages; cache only successful reads."""
    def load():
        result = {name.casefold(): [] for name in names}
        seen = set()
        for page in range(100):
            check_stop(stop)
            data = eng._http_json(eng.SPansh_BASE + '/bodies/search', {
                'filters': {'system_name': {'value': names}}, 'size': 500, 'page': page}, compressed=True)
            rows = data.get('results') if isinstance(data, dict) else None
            if not isinstance(rows, list):
                raise ValueError('Invalid body response; coverage unknown.')
            added = 0
            for body in rows:
                if not isinstance(body, dict) or not body.get('system_name') or not body.get('name'):
                    raise ValueError('Missing body identity; coverage unknown.')
                key = body['system_name'].casefold()
                if key not in result:
                    raise ValueError('Unexpected system in body response.')
                ident = (key, str(body.get('id64', body['name'])))
                if ident not in seen:
                    seen.add(ident)
                    added += 1
                    result[key].append(body)
            if rows and not added:
                raise ValueError('Repeated body page; coverage incomplete.')
            if len(rows) < 500:
                count = data.get('count')
                if isinstance(count, (int, float)) and count < 10000 and count > len(seen):
                    raise ValueError('Body count exceeds returned coverage.')
                return result
        raise ValueError('Body page limit reached; coverage incomplete.')
    key = 'colonisation-bodies-v1:' + '\n'.join(sorted(name.casefold() for name in names))
    records, info = pve_cache.cached(key, load, 300, refresh)
    if metadata is not None:
        metadata.update(info)
    return records


def largest_fixed_pad(system):
    """Maximum confirmed pad at fixed stations; carriers/construction ships do not count."""
    from powerplay_tool import _is_colonisation_ship
    stations = system.get('stations')
    if not isinstance(stations, list):
        return '情况未知'
    best, uncertain = '', False
    for station in stations:
        if not isinstance(station, dict) or not isinstance(station.get('type'), str) or not station['type'].strip():
            uncertain = True
            continue
        if 'carrier' in station['type'].casefold() or _is_colonisation_ship(station):
            continue
        station_pad = ''
        for size, key in (('L', 'large_pads'), ('M', 'medium_pads'), ('S', 'small_pads')):
            value = number(station.get(key))
            present = value > 0 if value is not None and value >= 0 else None
            if size == 'L' and type(station.get('has_large_pad')) is bool:
                present = station['has_large_pad'] or present is True
            if present is True:
                station_pad = size
                break
            if present is None:
                uncertain = True
                break
        if station_pad and (not best or 'SML'.index(station_pad) > 'SML'.index(best)):
            best = station_pad
    if best == 'L':
        return best
    return '情况未知' if uncertain else best or '无固定停机坪'


def populated_neighbour(system, radius, max_pages, stop=None, population_min=1, evidence=None):
    """Find the nearest system above the population threshold, not an annulus.

    The server sorts from the candidate's coordinates. Verify that order using
    actual coordinates before accepting the nearest hit; uncertain records or
    incomplete pages without a hit cannot establish a nearest neighbour.
    """
    coords = tuple(number(system.get(axis)) for axis in ('x', 'y', 'z'))
    if None in coords:
        return None, '', None, None
    seen, uncertain, previous_distance = set(), False, None
    for page in count() if max_pages is None else range(max_pages):
        check_stop(stop)
        filters = eng.build_server_payload('systems', [
            {'field': 'population', 'op': 'between', 'min': math.floor(population_min) + 1, 'max': eng.BIG}])['filters']
        if radius is not None:
            filters['distance'] = {'max': radius}
        data = eng._http_json(eng.SPansh_BASE + '/systems/search', {
            'filters': filters,
            'reference_coords': dict(zip(('x', 'y', 'z'), coords)),
            'sort': [{'distance': {'direction': 'asc'}}], 'size': 50, 'page': page}, compressed=True)
        rows = data.get('results') if isinstance(data, dict) else None
        if not isinstance(rows, list):
            raise ValueError('Invalid populated-system response.')
        added, hits = 0, []
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError('Invalid populated-system record.')
            ident = row.get('id64', row.get('name'))
            if ident in seen:
                continue
            seen.add(ident)
            added += 1
            if eng.is_excluded_system('systems', row):
                continue
            population = number(row.get('population'))
            xyz = tuple(number(row.get(axis)) for axis in ('x', 'y', 'z'))
            if population is None or None in xyz or not row.get('name'):
                uncertain = True
                continue
            distance = eng.dist3(coords, xyz)
            if previous_distance is not None and distance < previous_distance - 1e-7:
                raise ValueError('Populated systems are not sorted by coordinate distance; nearest is unknown.')
            previous_distance = distance
            if population > population_min and (radius is None or distance <= radius):
                hits.append((distance, row['name'], population))
        if hits:
            if uncertain:
                return None, '', None, None
            distance, name, population = min(hits)
            if evidence is not None:
                nearest = next(row for row in rows if row.get('name') == name)
                evidence['pad'] = largest_fixed_pad(nearest)
            return True, name, population, distance
        if len(rows) < 50:
            return (None if uncertain else False), '', None, None
        if not added:
            break
    return None, '', None, None


def _neighbours_batch(systems, criteria, stop):
    """At most four requests in flight; preserve candidate order and exceptions."""
    def lookup(system):
        check_stop(stop)
        evidence = {}
        with eng.request_control.context(stop):
            result = populated_neighbour(system, criteria.populated_radius, None, stop, evidence=evidence)
        return result, evidence
    results = {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [(system['name'].casefold(), pool.submit(lookup, system)) for system in systems]
        for key, future in futures:
            try:
                results[key] = future.result()
            except Exception as error:
                results[key] = error
    return results


def search(criteria, progress=None, stop=None, refresh=False, resume=None):
    import json
    import search_recovery
    if resume is not None:
        search_recovery.bind(resume, json.dumps(vars(criteria.validate()), sort_keys=True))
    try:
        with eng.request_control.context(stop, lambda text: eng._report(progress, text, stage='网络冷却', done=0, work_total=None)):
            result = _search(criteria, progress, stop, refresh, resume)
    except Exception as error:
        if isinstance(error, InterruptedError) and resume is not None and stop is not None and stop.is_set():
            result = (dict(scanned=resume.get('display_scanned', 0), total=resume.get('total', 0),
                           unknown=resume.get('display_unknown', 0), complete=False,
                           reason='Search cancelled; results are incomplete.', value_field=criteria.value_field),
                      list(resume.get('rows', [])))
        elif resume is None or not search_recovery.transient(error):
            raise
        else:
            search_recovery.pause(resume, error)
            return dict(scanned=resume.get('display_scanned', 0), total=resume.get('total', 0),
                        unknown=resume.get('display_unknown', 0), complete=False,
                        reason='Network interrupted; verified results retained. Continue to retry.',
                        value_field=criteria.value_field, error=str(error)), list(resume.get('rows', []))
    if resume is not None and stop is not None and stop.is_set() and resume.get('rows'):
        info, _ = result
        info.update(scanned=max(info['scanned'], resume.get('display_scanned', 0)),
                    unknown=max(info['unknown'], resume.get('display_unknown', 0)),
                    total=resume.get('total', info['total']))
        result = info, list(resume['rows'])
    search_recovery.finished(resume, stopped=bool(stop is not None and stop.is_set() and not result[0]['complete'] and len(result[1]) < criteria.want))
    return result


def _search(criteria, progress=None, stop=None, refresh=False, resume=None):
    c = criteria.validate()
    if stop is not None and stop.is_set():
        return dict(scanned=0, total=0, complete=False, unknown=0,
                    reason='Search cancelled; results are incomplete.', value_field=c.value_field), []
    conditions = [{'field': 'population', 'op': 'between', 'min': 0, 'max': 0},
                  {'field': 'needs_permit', 'op': 'false'}]
    if c.minimum_value is not None:
        conditions.append({'field': c.value_field, 'op': '>', 'text': c.minimum_value})
    if c.reference:
        conditions.append({'type': 'distance', 'ref_system': c.reference,
                           'min_ly': None, 'max_ly': c.radius, 'mode': 'inside'})
    payload = eng.build_server_payload('systems', conditions, size=500)
    reference_coords = None
    if c.reference:
        canonical, reference_coords, _ = eng.resolve_ref(c.reference)
        payload['reference_system'] = canonical
    rows = resume.setdefault('rows', []) if resume is not None else []
    seen = set(resume.get('seen', ())) if resume is not None else set()
    scanned, unknown = (resume.get('scanned', 0), resume.get('unknown', 0)) if resume is not None else (0, 0)
    emitted = {r.get('id64', r['name'].casefold()) for r in rows}
    complete, reason = False, 'Search incomplete.'
    total = resume.get('total', 0) if resume is not None else 0
    verified = scanned
    caller_progress = progress
    plan = ['候选分页', '站点复核']
    if c.body_groups or c.ring_groups:
        plan.append('天体批次')
    if c.populated_radius is not None or c.populated_min_distance is not None:
        plan.append('最近有人星系核验')
    plan.append('本页候选核查')
    page = resume.get('page', 0) if resume is not None else 0
    def progress(message, detail=None):
        info = dict(detail or {})
        stage = info.get('stage', '候选分页')
        info['overall'] = dict(scanned=verified, total=total, hits=len(rows), want=c.want,
                               page=page + 1, step=plan.index(stage) + 1 if stage in plan else 1,
                               steps=len(plan), plan=plan, per=500)
        eng._report(caller_progress, message, **info)
    try:
        for page in count(resume.get('page', 0) if resume is not None else 0):
            check_stop(stop)
            if resume is not None:
                resume.update(page=page, seen=set(seen), scanned=scanned, unknown=unknown,
                              display_scanned=scanned, display_unknown=unknown, total=total)
            if progress:
                eng._report(progress, f'Page {page + 1}; scanned {scanned}; matches {len(rows)}',
                            scanned=scanned, total=total)
            import copy
            data = resume.get('batch') if resume is not None else None
            if data is None:
                data = eng._http_json(eng.SPansh_BASE + '/systems/search', dict(payload, page=page), compressed=True)
                if resume is not None:
                    resume['batch'] = copy.deepcopy(data)
            else:
                data = copy.deepcopy(data)
            check_stop(stop)
            candidates = data.get('results') if isinstance(data, dict) else None
            if not isinstance(candidates, list):
                raise ValueError('Invalid system response.')
            if page == 0:
                total = data.get('count', 0)
            if resume is not None:
                resume['total'] = total
            missing_stations = [s['name'] for s in candidates if isinstance(s, dict) and s.get('name')
                                and number(s.get('population')) == 0 and s.get('needs_permit') is False
                                and 'stations' not in s and not eng.is_excluded_system('systems', s)]
            confirmed = {}
            for start in range(0, len(missing_stations), 16):
                eng._report(progress, 'Verifying station records', stage='站点复核',
                            done=start, work_total=len(missing_stations))
                confirmed.update(confirm_station_absence(missing_stations[start:start + 16], refresh, stop))
                eng._report(progress, 'Verifying station records', stage='站点复核',
                            done=min(start + 16, len(missing_stations)), work_total=len(missing_stations))
            accepted, added = [], 0
            for system in candidates:
                if not isinstance(system, dict) or not system.get('name'):
                    raise ValueError('Missing system identity.')
                ident = system.get('id64', system['name'].casefold())
                if ident in seen:
                    continue
                seen.add(ident)
                scanned += 1
                if resume is not None:
                    resume['display_scanned'] = scanned
                added += 1
                if system['name'].casefold() in confirmed:
                    system = dict(system, stations=confirmed[system['name'].casefold()])
                hit = eligible(system)
                if hit is None:
                    unknown += 1
                if hit is not True:
                    continue
                if c.minimum_value is not None:
                    value = number(system.get(c.value_field))
                    if value is None:
                        unknown += 1
                        continue
                    if value <= c.minimum_value:
                        continue
                if c.radius is not None:
                    xyz = tuple(number(system.get(axis)) for axis in ('x', 'y', 'z'))
                    if None in xyz:
                        unknown += 1
                        continue
                    distance = eng.dist3(xyz, reference_coords)
                    if distance > c.radius:
                        continue
                    system = dict(system, distance=distance)
                accepted.append(system)
            bodies = {}
            verified = scanned - len(accepted)
            if resume is not None:
                resume['display_unknown'] = unknown
            block_end, neighbours = 0, {}
            for index, system in enumerate(accepted):
                verified = scanned - len(accepted) + index
                eng._report(progress, f'Checking candidate {index + 1}/{len(accepted)}',
                            stage='本页候选核查', done=index, work_total=len(accepted))
                check_stop(stop)
                if index >= block_end:
                    near_enabled = c.populated_radius is not None or c.populated_min_distance is not None
                    limit = 8 if near_enabled else 32
                    block_end = min(len(accepted), index + min(limit, max(1, c.want - len(rows))))
                    block = accepted[index:block_end]
                    bodies = {}
                    if c.body_groups or c.ring_groups:
                        eng._report(progress, 'Loading body records', stage='天体批次', done=index,
                                    work_total=len(accepted))
                        chunks = [[row['name'] for row in block[start:start + 8]] for start in range(0, len(block), 8)]
                        with ThreadPoolExecutor(max_workers=min(4, len(chunks))) as pool:
                            futures = [pool.submit(load_bodies, chunk, refresh, stop) for chunk in chunks]
                            for future in futures:
                                bodies.update(future.result())
                    neighbours = {}
                    if c.populated_radius is not None or c.populated_min_distance is not None:
                        eligible_neighbours = []
                        for row in block:
                            records = bodies.get(row['name'].casefold(), [])
                            annotate_relationships(records)
                            if combine([match_groups(records, c.body_groups, c.body_mode)[0],
                                        match_groups(records, c.ring_groups, c.ring_mode, rings=True)[0]]) is True:
                                eligible_neighbours.append(row)
                        eng._report(progress, 'Verifying nearby systems', stage='最近有人星系核验',
                                    done=index, work_total=len(accepted))
                        neighbours = _neighbours_batch(eligible_neighbours, c, stop)
                records = bodies.get(system['name'].casefold(), [])
                annotate_relationships(records)
                body_hit, body_names = match_groups(records, c.body_groups, c.body_mode)
                ring_hit, ring_names = match_groups(records, c.ring_groups, c.ring_mode, rings=True)
                hit = combine([body_hit, ring_hit])
                if hit is None:
                    unknown += 1
                if hit is not True:
                    continue
                neighbour, population, distance = '', None, None
                neighbour_evidence = {}
                if c.populated_radius is not None or c.populated_min_distance is not None:
                    if resume is not None:
                        resume['display_unknown'] = unknown
                    result = neighbours[system['name'].casefold()]
                    if isinstance(result, Exception):
                        raise result
                    (hit, neighbour, population, distance), neighbour_evidence = result
                    if hit is None:
                        unknown += 1
                    if hit is not True:
                        continue
                    if c.populated_min_distance is not None and distance < c.populated_min_distance:
                        continue
                # System summaries already contain per-body scan values: no extra network
                # requests just to display prices. Reuse full records if fetched for groups.
                prices, prices_complete = top_scan_planets(
                    bodies.get(system['name'].casefold(), system.get('bodies')),
                    system.get('body_count'))
                row = dict(system, _top_scan_planets=prices, _top_scan_complete=prices_complete,
                           _body_matches=body_names, _ring_matches=ring_names,
                           _relations='; '.join(f"{b['name']}: {b['_relations']}" for b in records if b.get('_relations')),
                            _neighbour=neighbour, _neighbour_population=population,
                            _neighbour_pad=neighbour_evidence.get('pad', '情况未知') if neighbour else '',
                           _neighbour_distance=distance)
                row_ident = row.get('id64', row['name'].casefold())
                if row_ident not in emitted:
                    rows.append(row)
                    emitted.add(row_ident)
                verified = scanned - len(accepted) + index + 1
                if len(rows) >= c.want:
                    reason = 'Result limit reached; results are incomplete.'
                    break
            if len(rows) >= c.want:
                break
            verified = scanned
            eng._report(progress, f'Page {page + 1}; scanned {scanned}; matches {len(rows)}',
                        scanned=scanned, total=total)
            if candidates and not added:
                reason = 'Repeated system page; results are incomplete.'
                break
            if len(candidates) < 500:
                complete = True
                reason = 'All supplied candidate pages fetched.'
                break
            if resume is not None:
                resume.pop('batch', None)
    except InterruptedError as exc:
        reason = str(exc)
    eng._report(progress, reason, stage='本页候选核查', done=verified, work_total=total if 0 < total < 10000 else None)
    return dict(scanned=scanned, total=total, complete=complete, unknown=unknown,
                reason=reason, value_field=c.value_field), rows
