"""Public FDev item IDs and independent, same-market stock evidence.

Names/classes can change without becoming a new product. A shared symbol can,
conversely, represent different numeric IDs (ordinary and Merc equipment).
Never infer both products from one symbol-only report.
"""
import csv
import io
import re
import urllib.parse
import urllib.request

REVISION = 'c35612952dd6a547d1a7ac4cffab9c7051e86579'
URL = f'https://raw.githubusercontent.com/EDCD/FDevIDs/{REVISION}/outfitting.csv'


def download_facts():
    with urllib.request.urlopen(URL, timeout=60) as response:
        body = response.read(2 * 1024 * 1024 + 1)
    if len(body) > 2 * 1024 * 1024:
        raise ValueError('配件身份目录响应过大')
    facts = []
    for row in csv.DictReader(io.StringIO(body.decode('utf-8-sig'))):
        try:
            ident, cls = int(row['id']), int(row['class'])
        except (KeyError, ValueError, TypeError):
            continue
        if not row.get('symbol') or not row.get('name') or row.get('rating') not in set('ABCDEFGHI'):
            continue
        item = dict(ed_id=ident, ed_symbol=row['symbol'], name=row['name'],
                    category=row['category'], ship=row.get('ship', ''),
                    **{'class': cls, 'rating': row['rating']})
        if row.get('mount'):
            item['weapon_mode'] = row['mount']
        facts.append(item)
    if not facts:
        raise ValueError('配件身份目录无效')
    return facts


def symbol(item):
    return str(item.get('ed_symbol') or item.get('symbol') or '').casefold()


def numeric_id(item):
    for name in ('ed_id', 'edID', 'fdev_id', 'id'):
        value = item.get(name)
        if type(value) is int and value > 0:
            return value
        if isinstance(value, str) and value.isascii() and value.isdigit() and int(value) > 0:
            return int(value)
    return None


def name_key(name):
    name = re.sub(r'^\d+[A-I]\s+', '', str(name), flags=re.IGNORECASE)
    guidance = re.search(r'\s*\((Seeker|Dumbfire),\s*(?:Fixed|Gimbal(?:led)?|Turret(?:ed)?)\)\s*$',
                         name, flags=re.IGNORECASE)
    if guidance:
        name = name[:guidance.start()]
        if guidance.group(1).casefold() == 'seeker':
            name = 'Seeker ' + name
    name = re.sub(r'\s*\((?:Fixed|Gimbal(?:led)?|Turret(?:ed)?)\)\s*$', '', name, flags=re.IGNORECASE)
    key = re.sub(r'[^a-z0-9]', '', name.casefold())
    return {'fighterhangar': 'vesselhangar'}.get(key, key)


def indexes(facts):
    by_id, by_symbol = {}, {}
    for item in facts:
        # Older v4 caches predate the explicit mount field. The stable asset
        # token supplies the same fact, without modifying the persisted cache.
        if not item.get('weapon_mode'):
            mode = next((part for part in str(item.get('ed_symbol', '')).split('_')
                         if part.casefold() in ('fixed', 'gimbal', 'turret')), None)
            if mode:
                item = dict(item, weapon_mode=mode)
        by_id[item['ed_id']] = item
        by_symbol.setdefault(symbol(item), []).append(item)
    return by_id, by_symbol


def canonical_catalog(catalog, facts, ordinary, restricted):
    """Use numeric IDs, not a union of stale class/rating descriptions."""
    result = dict(catalog)
    _, by_symbol = indexes(facts)
    regular, unresolved = {}, []
    for old in catalog['items']:
        choices = [item for item in by_symbol.get(symbol(old), []) if item['category'] != 'mercgear']
        if len(choices) != 1:
            unresolved.append((old.get('name'), old.get('class'), old.get('rating')))
            continue
        item = choices[0]
        if ordinary(item['name']) and not restricted(item['name'], item['class']):
            regular[item['ed_id']] = dict(item)
    result.update(items=list(regular.values()), module_facts=facts, identity_revision=REVISION,
                  special_items=[dict(item) for item in facts if item['category'] == 'mercgear'],
                  special_issues=[], special_errors=[], special_checked=True)
    result['issues'] = [*catalog.get('issues', []), *unresolved]
    return result


def normalize_stock(items, facts):
    by_id, by_symbol = indexes(facts)
    output = []
    for raw in items:
        if not isinstance(raw, dict):
            continue
        sym, ident = symbol(raw), numeric_id(raw)
        fact = by_id.get(ident)
        if fact and (not sym or symbol(fact) == sym):
            output.append(dict(raw, **fact, identity_source='numeric_id'))
            continue
        if ident is not None:
            output.append(dict(raw, identity_ambiguous=True))
            continue
        choices = by_symbol.get(sym, [])
        regular = [item for item in choices if item['category'] != 'mercgear']
        special = [item for item in choices if item['category'] == 'mercgear']
        # Spansh may label a symbol with the last Merc entry in the identity
        # table. Without a numeric ID this does NOT establish either offer.
        merc_label = raw.get('category') == 'mercgear' or any(
            name_key(raw.get('name')) == name_key(item['name']) for item in special)
        if regular and special and merc_label:
            output.append(dict(raw, identity_ambiguous=True))
        elif len(regular) == 1 and not merc_label:
            output.append(dict(raw, **regular[0], identity_source='unique_regular_symbol'))
        elif len(choices) == 1:
            output.append(dict(raw, **choices[0], identity_source='unique_symbol'))
        else:
            output.append(dict(raw, identity_ambiguous=True))
    return output


def edsm_stock(row, facts, http):
    """Only use an exact market/system/station match; never merge nearby shops."""
    market = row.get('market_id') or row.get('marketId') or row.get('id')
    if isinstance(market, bool) or not str(market or '').isascii() or not str(market).isdigit():
        raise ValueError('缺少可复核的站点市场编号')
    response = http('https://www.edsm.net/api-system-v1/stations/outfitting?' +
                    urllib.parse.urlencode({'marketId': str(market)}))
    if (not isinstance(response, dict) or str(response.get('marketId')) != str(market)
            or str(response.get('sName', '')).casefold() != str(row.get('name', '')).casefold()
            or str(response.get('name', '')).casefold() != str(row.get('system_name', '')).casefold()
            or not isinstance(response.get('outfitting'), list)):
        raise ValueError('第二来源站点身份不匹配')
    _, by_symbol = indexes(facts)
    output = {}
    for raw in response['outfitting']:
        sym = str(raw.get('id', '')).casefold()
        choices = [item for item in by_symbol.get(sym, []) if item['category'] != 'mercgear'
                   and name_key(item['name']) == name_key(raw.get('name'))]
        if len(choices) == 1:
            item = choices[0]
            output[item['ed_id']] = dict(item, identity_source='EDSM named stock',
                                         source_label=raw['name'])
    return list(output.values())
