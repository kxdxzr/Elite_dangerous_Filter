"""Same-station existential groups and conservative station classification."""
import math

import filter_engine as eng
from spansh_filter import STATION_FIELDS_CN
from system_filter_fields import STATION_COUNT_FIELDS


FIELDS = {key: STATION_FIELDS_CN[key] for key in (
    'name', 'type', 'is_planetary', 'has_large_pad', 'distance_to_arrival',
    'services', 'has_market', 'has_shipyard', 'has_outfitting',
    'large_pads', 'medium_pads', 'small_pads', 'material_trader',
    'technology_broker', 'primary_economy', 'secondary_economy',
    'allegiance', 'government', 'controlling_faction')}
FIELDS['is_carrier'] = '是否航母（含强权航母）'
BOOL_FIELDS = {'is_planetary', 'is_carrier', 'has_large_pad', 'has_market', 'has_shipyard', 'has_outfitting'}
NUM_FIELDS = {'distance_to_arrival', 'large_pads', 'medium_pads', 'small_pads'}
OPERATORS = ['=', '!=', 'in', 'not in', 'contains', '<', '<=', '>', '>=', 'between', 'outside']
ORBITAL_TYPES = {'Asteroid base', 'Coriolis Starport', 'Dodec Starport', 'Mega ship',
                 'Ocellus Starport', 'Orbis Starport', 'Outpost', 'Space Construction Depot'}
PLANETARY_TYPES = {'Dockable Planet Station', 'Planetary Construction Depot', 'Planetary Outpost',
                   'Planetary Port', 'Settlement', 'Surface Settlement'}
VALUES = {
    **{key: ['true', 'false'] for key in BOOL_FIELDS},
    'type': sorted(ORBITAL_TYPES | PLANETARY_TYPES | {'Drake-Class Carrier', 'Stronghold Carrier'}),
    'services': ['Refuel', 'Repair', 'Restock', 'Market', 'Outfitting', 'Shipyard',
                 'Interstellar Factors Contact', 'Material Trader', 'Technology Broker',
                 'Universal Cartographics', 'Vista Genomics'],
    'material_trader': ['Raw', 'Manufactured', 'Encoded'],
    'technology_broker': ['Human', 'Guardian', 'Sirius'],
}


def carrier(station):
    kind = station.get('type')
    if not isinstance(kind, str) or not kind.strip():
        return None
    return 'carrier' in kind.casefold() or 'stronghold' in kind.casefold()


def planetary(station):
    if type(station.get('is_planetary')) is bool:
        return station['is_planetary']
    kind = station.get('type')
    if not isinstance(kind, str):
        return None
    if kind in PLANETARY_TYPES:
        return True
    if kind in ORBITAL_TYPES or carrier(station) is True:
        return False
    return None


def counts(records):
    result = dict.fromkeys(STATION_COUNT_FIELDS)
    if not isinstance(records, list) or any(not isinstance(s, dict) for s in records):
        return result
    result['station_count'] = len(records)
    carriers = [carrier(s) for s in records]
    if all(value is not None for value in carriers):
        result['carrier_count'] = sum(carriers)
        result['non_carrier_station_count'] = len(records) - sum(carriers)
    locations = [planetary(s) if is_carrier is False else False if is_carrier is True else None
                 for s, is_carrier in zip(records, carriers)]
    if all(value is not None for value in locations):
        result['planetary_station_count'] = sum(locations)
        result['orbital_station_count'] = sum(is_carrier is False and location is False
                                              for is_carrier, location in zip(carriers, locations))
    return result


def compile_condition(condition):
    if not isinstance(condition, dict):
        raise ValueError('站点组条件格式无效')
    field, op = condition.get('field'), condition.get('op')
    value = str(condition.get('value', '')).strip()
    if not isinstance(field, str) or field not in FIELDS or op not in OPERATORS or not value:
        raise ValueError('站点组字段、操作或比较值无效')
    compiled = dict(type='field', field=field, op=op)
    if field in BOOL_FIELDS:
        if op not in ('=', '!=') or value.casefold() not in ('true', 'false'):
            raise ValueError('站点布尔条件须使用 = 或 !=，值为 true / false')
        want = value.casefold() == 'true'
        compiled['op'] = 'true' if (want if op == '=' else not want) else 'false'
    elif op in ('between', 'outside'):
        if field not in NUM_FIELDS:
            raise ValueError('站点范围条件须使用数值字段')
        parts = value.split('|')
        if len(parts) != 2 or not any(p.strip() for p in parts):
            raise ValueError('站点范围须填写 最小值|最大值，至少保留一个边界')
        compiled.update(min=parts[0].strip(), max=parts[1].strip())
    elif op in ('in', 'not in'):
        compiled['values'] = [v.strip() for v in value.split('|') if v.strip()]
    else:
        if (op in ('<', '<=', '>', '>=') and field not in NUM_FIELDS
                or op == 'contains' and field in NUM_FIELDS):
            raise ValueError('此站点字段不支持所选比较操作')
        compiled['text'] = value
    try:
        return eng.normalize_conditions('stations', [compiled])[0]
    except eng.Contradiction as exc:
        raise ValueError(str(exc)) from exc


def validate(groups, mode):
    if not isinstance(groups, list) or mode not in ('AND', 'OR'):
        raise ValueError('站点条件组或组间关系无效')
    for group in groups:
        if not isinstance(group, list) or not group:
            raise ValueError('每个站点组至少需要一条条件；请补全或删除空组')
        for condition in group:
            compile_condition(condition)


def match_condition(station, condition):
    field = condition['field']
    row = dict(station)
    if field == 'is_carrier':
        row[field] = carrier(station)
    elif field == 'is_planetary':
        row[field] = planetary(station)
    raw = eng.field_raw('stations', row, field)
    # Missing fields never prove absence, including negative comparisons.
    if raw is None:
        return None
    if field in BOOL_FIELDS and type(raw) is not bool:
        return None
    if field in NUM_FIELDS and (type(raw) not in (int, float) or not math.isfinite(raw)):
        return None
    if field == 'services' and (not isinstance(raw, list) or any(
            not isinstance(item, str) and not (isinstance(item, dict) and isinstance(item.get('name'), str))
            for item in raw)):
        return None
    if field not in BOOL_FIELDS | NUM_FIELDS | {'services'} and (not isinstance(raw, str) or not raw.strip()):
        return None
    return eng.match_field('stations', row, condition)


def match_groups(records, groups, mode):
    from colonisation_tool import combine
    if not groups:
        return True, []
    if not isinstance(records, list) or any(not isinstance(s, dict) for s in records):
        return None, []
    outcomes, evidence = [], []
    for index, group in enumerate(groups, 1):
        compiled = [compile_condition(c) for c in group]
        hits = [combine([match_condition(station, c) for c in compiled]) for station in records]
        outcomes.append(combine(hits, 'OR') if hits else False)
        evidence.append({'group': index, 'names': [str(s.get('name', '?'))
                                                  for s, hit in zip(records, hits) if hit is True]})
    return combine(outcomes, mode), evidence
