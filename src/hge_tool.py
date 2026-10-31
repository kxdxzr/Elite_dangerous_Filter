"""HGE candidates using user-supplied rules, never a live signal/spawn claim.

Allegiance and current states must belong to the named controlling faction in
the same system record. Pending/recovering and unrelated factions do not count.
Freshness is system-record updated_at, NOT an independently dated faction fact.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import math

import filter_engine as eng


RULES = {
    'federal': (('Core Dynamics Composites', 'Proprietary Composites'),
                ('Federation',), ('Election', 'None')),
    'military': (('Military Grade Alloys', 'Military Supercapacitors'),
                 ('Independent', 'Alliance'), ('War', 'Civil War')),
    'improvised': (('Improvised Components',), ('Independent', 'Alliance'), ('Civil Unrest',)),
    'imperial': (('Imperial Shielding',), ('Empire',), ('Election', 'None')),
    'pharmaceutical': (('Pharmaceutical Isolators',), ('Independent', 'Alliance'), ('Outbreak',)),
    'proto_heat': (('Proto Heat Radiators', 'Proto Light Alloys'), ('Independent', 'Alliance'), ('Boom',)),
    'proto_radiolic': (('Proto Radiolic Alloys',), ('Independent', 'Alliance'), ('Boom',)),
}
MATERIAL_LABELS = {'all': '全部材料', **{key: ' / '.join(rule[0]) for key, rule in RULES.items()}}
POPULATION_OPTIONS = {
    '不限': None, '人口大于 0': 0, '至少 100 万': 1_000_000,
    '至少 1000 万': 10_000_000, '至少 1 亿': 100_000_000,
    '至少 10 亿': 1_000_000_000, '至少 100 亿': 10_000_000_000,
}
FRESHNESS_OPTIONS = {
    '近 1 小时': 1, '近 3 小时': 3, '近 6 小时': 6, '近 12 小时': 12,
    '近 24 小时': 24, '近 48 小时': 48, '近 72 小时': 72,
    '近 7 天': 168, '不限': None,
}


@dataclass(frozen=True)
class Criteria:
    reference: str = 'Sol'
    radius: float = 50
    material: str = 'federal'
    population: str = '人口大于 0'
    freshness: str = '近 24 小时'
    want: int = 100
    max_pages: int = 25
    require_manufactured_trader: bool = False

    def validate(self):
        if not isinstance(self.reference, str) or not self.reference.strip():
            raise ValueError('请填写参考星系')
        if isinstance(self.radius, bool) or not math.isfinite(float(self.radius)) or float(self.radius) <= 0:
            raise ValueError('HGE 搜索半径必须大于零')
        if self.material not in MATERIAL_LABELS:
            raise ValueError('请选择 HGE 材料')
        if self.population not in POPULATION_OPTIONS or self.freshness not in FRESHNESS_OPTIONS:
            raise ValueError('请选择有效的人口和时效档位')
        if any(type(v) is not int or not 1 <= v <= 10000 for v in (self.want, self.max_pages)):
            raise ValueError('结果数和页数必须为 1~10000 的整数')
        if type(self.require_manufactured_trader) is not bool:
            raise ValueError('人造材料商人选项必须为布尔值')
        return self


def timestamp(value):
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        value = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
    except ValueError:
        return None


def current_states(record):
    """An empty/missing list is not evidence of None; explicit None is required."""
    states = set()
    state = record.get('state')
    if isinstance(state, str) and state.strip():
        states.add(state.strip())
    if 'active_states' in record:
        if not isinstance(record['active_states'], list):
            return None
        for value in record['active_states']:
            value = value.get('name') if isinstance(value, dict) else value
            if not isinstance(value, str) or not value.strip():
                return None
            states.add(value.strip())
    states = {s.casefold() for s in states}
    if states - {'none'}:
        states.discard('none')
    return frozenset(states) or None


def controller_evidence(row):
    name = row.get('controlling_minor_faction')
    records = row.get('minor_faction_presences')
    if not isinstance(name, str) or not name.strip() or not isinstance(records, list):
        return None
    evidence = set()
    for record in records:
        if not isinstance(record, dict) or str(record.get('name', '')).strip().casefold() != name.strip().casefold():
            continue
        allegiance = record.get('allegiance')
        states = current_states(record)
        if not isinstance(allegiance, str) or not allegiance.strip() or not states:
            return None
        evidence.add((allegiance.strip().casefold(), states))
    # Conflicting duplicate records are unknown, not an opportunity to cherry-pick.
    if len(evidence) != 1:
        return None
    allegiance, states = next(iter(evidence))
    return name.strip(), allegiance, states


def candidate(row, criteria, now):
    population = row.get('population')
    minimum = POPULATION_OPTIONS[criteria.population]
    if minimum is not None:
        if (type(population) not in (int, float) or not math.isfinite(population)
                or population < minimum or minimum == 0 and population == 0):
            return None
    stamp = timestamp(row.get('updated_at'))
    hours = FRESHNESS_OPTIONS[criteria.freshness]
    age = (now - stamp).total_seconds() if stamp is not None else None
    if hours is not None and (age is None or not 0 <= age <= hours * 3600):
        return None
    controller = controller_evidence(row)
    if controller is None:
        return None
    name, allegiance, states = controller
    matched, matched_states = [], set()
    for key, (materials, allegiances, required_states) in RULES.items():
        if criteria.material not in ('all', key):
            continue
        matching = {s for s in required_states if s.casefold() in states}
        if allegiance in {a.casefold() for a in allegiances} and matching:
            matched.extend(materials)
            matched_states.update(matching)
    if not matched:
        return None
    return dict(materials=matched, controller=name, allegiance=allegiance.title(),
                states=sorted(matched_states), updated_at=row.get('updated_at'),
                age_hours=age / 3600 if age is not None and age >= 0 else None)


def find_manufactured_trader(system, *, max_pages=25, stop=None, page_size=100):
    """Fresh station evidence in this exact system; unknown is never a hit."""
    name = system.get('name')
    if not isinstance(name, str) or not name.strip():
        return None
    seen = set()
    for page in range(max_pages):
        if stop is not None and stop.is_set():
            raise InterruptedError('Search cancelled; results are incomplete.')
        data = eng._http_json(eng.SPansh_BASE + '/stations/search', {
            'filters': {'system_name': {'value': [name]},
                        'material_trader': {'value': ['Manufactured']}},
            'size': page_size, 'page': page}, compressed=True)
        if stop is not None and stop.is_set():
            raise InterruptedError('Search cancelled; results are incomplete.')
        rows = data.get('results') if isinstance(data, dict) else None
        if not isinstance(rows, list):
            raise ValueError('Invalid material-trader station response.')
        added = 0
        for station in rows:
            if not isinstance(station, dict):
                continue
            ident = tuple(str(station.get(key, '')) for key in ('system_name', 'name', 'id'))
            if ident in seen:
                continue
            seen.add(ident)
            added += 1
            if (not isinstance(station.get('name'), str) or not station['name'].strip()
                    or str(station.get('system_name', '')).strip().casefold() != name.strip().casefold()
                    or str(station.get('material_trader', '')).strip().casefold() != 'manufactured'):
                continue
            if (system.get('id64') is not None and station.get('system_id64') is not None
                    and str(system['id64']) != str(station['system_id64'])):
                continue
            if stop is not None and stop.is_set():
                raise InterruptedError('Search cancelled; results are incomplete.')
            return dict(name=station['name'], system_name=station['system_name'],
                        material_trader='Manufactured', updated_at=station.get('updated_at'))
        if rows and not added:
            raise ValueError('Repeated material-trader station page.')
        if len(rows) < page_size:
            return None
    raise ValueError('Material-trader station page limit reached; evidence incomplete.')


def search(criteria, *, stop=None, progress=None, now=None):
    criteria.validate()
    now = now or datetime.now(timezone.utc)
    conditions = [dict(type='distance', ref_system=criteria.reference.strip(),
                       min_ly=None, max_ly=float(criteria.radius), mode='inside')]
    minimum = POPULATION_OPTIONS[criteria.population]
    if minimum is not None:
        conditions.append(dict(field='population', op='>' if minimum == 0 else '>=', text=minimum))
    hours = FRESHNESS_OPTIONS[criteria.freshness]
    if hours is not None:
        conditions.append(dict(field='last_updated_at', op='>=', text=(now - timedelta(hours=hours)).isoformat()))
    # No allegiance/state push-down: system allegiance can differ from the
    # controller, and a singular top-level state can omit a second active state.
    def verify(row):
        evidence = candidate(row, criteria, now)
        if evidence is None:
            return False
        if criteria.require_manufactured_trader:
            eng._report(progress, '正在核实人造材料商人…')
            try:
                trader = find_manufactured_trader(row, max_pages=criteria.max_pages, stop=stop)
            except ValueError:
                note = '部分候选的人造材料商人资料无法核实，未计入结果'
                if note not in notes:
                    notes.append(note)
                return False
            if trader is None:
                return False
            evidence['manufactured_trader'] = trader
        row['_hge'] = evidence
        return True

    checkpoint, notes = {}, []
    rows, total, scanned = eng.search('systems', conditions, want=criteria.want,
                                     max_pages=criteria.max_pages, row_filter=verify,
                                     stop=stop, progress=progress, notes=notes, resume=checkpoint)
    if checkpoint.get('error'):
        notes = [n for n in notes if n != '网络暂时异常，已保留核实结果；可继续检索']
        notes.append('网络暂时异常，已保留核实结果；重新查询获取最新候选')
    return dict(rows=rows, total=total, scanned=scanned, notes=notes,
                fetched_at=now.isoformat(), criteria=criteria,
                paused=bool(checkpoint.get('paused')), error=checkpoint.get('error', ''),
                stopped=bool(stop is not None and stop.is_set()))
