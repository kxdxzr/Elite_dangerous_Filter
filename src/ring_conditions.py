"""Scope-aware ring evidence; absence requires explicit, complete records."""
import json

TYPES = ('Metallic', 'Metal Rich', 'Rocky', 'Icy')
MODES = {'any': '不限', 'present': '有星环', 'types': '指定类型', 'absent': '无星环'}


def validate(condition):
    c = dict(condition)
    mode = c.get('mode', 'any')
    values = c.get('values', [])
    if mode not in MODES or not isinstance(values, list) or any(v not in TYPES for v in values):
        raise ValueError('Invalid ring condition.')
    if mode == 'types' and not values:
        raise ValueError('Select at least one ring type.')
    return dict(type='rings', field='__rings__', op='matches', mode=mode,
                values=list(dict.fromkeys(values)) if mode == 'types' else [])


def legacy(condition):
    """Only migrate exact legacy booleans; preserve unusual old expressions."""
    if condition.get('field') == 'body_has_rings' and condition.get('op') in ('true', 'false'):
        return validate(dict(mode='present' if condition['op'] == 'true' else 'absent'))
    return condition


def key(condition):
    return json.dumps(validate(condition), sort_keys=True)


def outcome(row, condition):
    if condition.get('mode') == 'any':
        return True
    return row.get('_ring_outcomes', {}).get(key(condition))


def body_match(body, condition):
    rings = body.get('rings')
    flag = body.get('has_rings', body.get('body_has_rings'))
    if not isinstance(rings, list):
        if flag is False:
            rings = []
        elif flag is True and condition['mode'] != 'types':
            return condition['mode'] == 'present', []
        else:
            return None, []
    if condition['mode'] == 'absent':
        return not rings, []
    if condition['mode'] == 'present':
        return bool(rings), [r for r in rings if isinstance(r, dict)]
    hits = [r for r in rings if isinstance(r, dict) and r.get('type') in condition['values']]
    if hits:
        return True, hits
    unknown = any(not isinstance(r, dict) or not r.get('type') for r in rings)
    return (None if unknown else False), []


def evaluate(kind, row, records, condition):
    if condition['mode'] == 'any':
        return True, []
    if kind == 'stations' and condition['mode'] in ('present', 'absent'):
        flag = row.get('body_has_rings')
        if type(flag) is bool:
            hit = flag if condition['mode'] == 'present' else not flag
            return hit, [dict(body=row.get('body_name'), rings=[], present=flag)] if hit else []
    if not isinstance(records, list) or not records or any(not isinstance(b, dict) for b in records):
        return None, []
    if kind == 'stations':
        name = row.get('body_name')
        if not isinstance(name, str) or not name.strip():
            return None, []
        records = [b for b in records if b.get('name', '').casefold() == name.casefold()]
        if len(records) != 1:
            return None, []
    hits, evidence = [], []
    for body in records:
        hit, rings = body_match(body, condition)
        hits.append(hit)
        if hit is True:
            evidence.append(dict(body=body.get('name'), rings=rings))
    if condition['mode'] == 'absent':
        count = row.get('body_count')
        incomplete = kind == 'systems' and isinstance(count, (int, float)) and count > len(records)
        result = False if False in hits else None if incomplete or None in hits else True
    else:
        result = True if True in hits else None if None in hits else False
    return result, evidence if result is True else []


def prepare(kind, rows, conditions, *, stop=None, body_records=None):
    import colonisation_tool as bodies
    specs = [validate(c) for c in conditions if c.get('type') == 'rings']
    if not specs:
        return
    names = sorted({r.get('system_name') if kind == 'stations' else r.get('name') for r in rows} - {None, ''})
    records = dict(body_records or {})
    need_records = any(c['mode'] != 'any' and (
        kind != 'stations' or c['mode'] == 'types' or
        any(type(r.get('body_has_rings')) is not bool for r in rows)) for c in specs)
    if need_records:
        names = [name for name in names if name.casefold() not in records]
        for start in range(0, len(names), 8):
            bodies.check_stop(stop)
            records.update(bodies.load_bodies(names[start:start + 8], stop=stop))
    for row in rows:
        bodies.check_stop(stop)
        row['_ring_outcomes'], row['_ring_evidence'] = {}, {}
        name = row.get('system_name') if kind == 'stations' else row.get('name')
        for c in specs:
            result, evidence = evaluate(kind, row, records.get(str(name).casefold()), c)
            row['_ring_outcomes'][key(c)] = result
            row['_ring_evidence'][key(c)] = evidence


def evidence_text(row, condition):
    records = row.get('_ring_evidence', {}).get(key(condition))
    if records is None:
        return None
    return '; '.join(f"{r['body'] or '?'}: " + (', '.join(
        f"{ring.get('name', '?')} [{ring.get('type', '?')}]" for ring in r['rings']) or
        ('present (type unknown)' if r.get('present') else '[]')) for r in records)
