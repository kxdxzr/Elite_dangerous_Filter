"""Versioned public outfitting facts, never prices or commander entitlements.

Spansh stock supplements the pinned Coriolis symbols (not a Cartesian product).
Coverage is relative to this known catalogue, not a promise about future releases.
Downloaded facts remain third-party data and are cached outside the installation.
"""
import io
import hashlib
import json
import tarfile
import urllib.request
import urllib.error
from datetime import datetime, timezone

import filter_engine as eng
from field_options import BUNDLED_OPTIONS
from module_spec_pairs import BUNDLED_MODULE_PAIRS
from runtime_paths import data_file
import session_store
import outfitting_identity as identity

REVISION = '0db9234b5b9ce8c939ea84133d7ce336eea88e27'
SCHEMA = 4
CACHE_NAME = 'full_outfitting_catalog_v4.json'
# Only audited spelling/renaming equivalents. Power variants are NOT aliases.
NAME_ALIASES = {'fighter hangar': 'vessel hangar',
                'mk ii business class passenger cabin': 'mkii business class passenger cabin',
                'mk ii economy class passenger cabin': 'mkii economy class passenger cabin'}
ARMOURS = {'Lightweight Alloy', 'Reinforced Alloy', 'Military Grade Composite',
           'Mirrored Surface Composite', 'Reactive Surface Composite'}
MKII_ARMOURS = {'Mk II Ablative Lightweight Alloys', 'Mk II Ablative Reinforced Alloys',
                'Mk II Ablative Military Grade Composite', 'Mk II Ablative Mirrored Surface Composite',
                'Mk II Ablative Reactive Surface Composite'}
# Broker/engineer-only products are not ordinary retail stock. Guardian is a
# station-service option, not an automatic demand for all broker unlocks.
EXCLUDED = {'Corrosion Resistant Cargo Rack', 'Enzyme Missile Rack', 'Shock Cannon',
            'Remote Release Flechette Launcher', 'Meta Alloy Hull Reinforcement',
            'Enhanced Performance Thrusters', 'Long Range Detailed Surface Scanner',
            'Long Range Mining Laser', 'Guardian Nanite Torpedo Pylon', 'Caustic Sink Launcher'}
POWER_MODULES = {
    'Advanced Plasma Accelerator', 'Cytoscrambler Burst Laser', 'Enforcer Cannon',
    'Imperial Hammer Rail Gun', 'Mining Lance', 'Pacifier Frag-Cannon',
    'Pack-Hound Missile Rack', 'Prismatic Shield Generator', 'Pulse Disruptor Laser',
    'Retributor Beam Laser', 'Rocket Propelled FSD Disruptor', 'Concord Cannon'}
AX_WEAPONS = {'AX Missile Rack', 'AX Multi-Cannon',
              'Enhanced AX Missile Rack', 'Enhanced AX Multi-Cannon'}
AX_EQUIPMENT = AX_WEAPONS | {
    'Sub-Surface Extraction Missile',
    'Advanced Missile Rack', 'Advanced Multi-Cannon', 'Remote Release Flak Launcher',
    'Xeno Scanner', 'Enhanced Xeno Scanner', 'Pulse Wave Xeno Scanner',
    'Experimental Weapon Stabiliser', 'Shutdown Field Neutraliser',
    'Thargoid Pulse Neutraliser', 'Decontamination Limpet Controller',
    'Xeno Multi Limpet Controller'}
# Operations / Merc Coins pre-engineered equipment is not Powerplay stock.
# https://cms.zaonce.net/en-GB/node/7931
# https://forums.frontier.co.uk/threads/new-modules-available-for-mercs.647907/
SPECIAL_MODULES = {
    'Double Screaming Fragment Cannon', 'Enduring Feedback Rail Gun', 'Exposing Missiles',
    'Force Impact Cannon', 'High-Yield Enzyme Missile Rack', 'Lockdown Seeker Missile Rack',
    'Overloaded Beam Laser', 'Rapid Phase Multi-Cannon', 'Regenerative Burst Laser',
    'Balanced Power Distributor', 'Heavy Duty Module Reinforcement Package',
    'Support Focused Power Distributor', 'Far-Reaching Abrasion Blaster', 'Long Range Mining Laser',
    'Extended Cargo Rack', 'Long Range Detailed Surface Scanner', 'Drag Seeker Missile Rack',
    'Lightweight Thermal Seeker Missile Rack'}
ALIASES = {'auto_field_maintenance_unit': 'Auto Field-Maintenance Unit',
           'pristmatic_shield_generator': 'Prismatic Shield Generator',
           'internal_fuel_tank': 'Fuel Tank', 'fuel_tank': 'Fuel Tank',
           'planetary_vehicle_hanger': 'Planetary Vehicle Hangar',
           'experemental_weapon_stabilizer': 'Experimental Weapon Stabiliser',
           'business_passenger_cabin': 'Business Class Passenger Cabin',
           'economy_passenger_cabin': 'Economy Class Passenger Cabin',
           'first_passenger_cabin': 'First Class Passenger Cabin',
           'luxury_passenger_cabin': 'Luxury Class Passenger Cabin',
           'collector_limpet_controllers': 'Collector Limpet Controller',
           'fuel_transfer_limpet_controllers': 'Fuel Transfer Limpet Controller',
           'prospector_limpet_controllers': 'Prospector Limpet Controller',
           'recon_limpet_controllers': 'Recon Limpet Controller'}


def ordinary(name):
    return (name not in EXCLUDED and name not in SPECIAL_MODULES and name not in ARMOURS
            and not name.startswith('Guardian ')
            and 'Alloy' not in name and 'Composite' not in name)


def restricted_spec(name, cls):
    # These are engineering-workshop sizes, not general outfitting stock.
    # Audit 2026-10-20: all 14 reported ordinary 8C FSD suppliers and all
    # three reported 1A shield suppliers expose the Workshop service.
    return (name == 'Shield Generator' and cls == 1) or (name == 'Frame Shift Drive' and cls == 8)


def is_special(item):
    return item.get('catalog_group') == 'merc' or item.get('category') == 'mercgear' or item.get('name') in SPECIAL_MODULES


def is_ax(item):
    group = item.get('catalog_group')
    return group == 'ax' if group is not None else item.get('name') in AX_EQUIPMENT


def is_free_hangar(item):
    """Claimable hangars are not separate required retail stock."""
    sym = symbol(item)
    return sym.endswith('_free') and any(token in sym for token in ('buggybay', 'fighterbay'))


def excluded_hangar(item):
    sym = symbol(item)
    return (is_free_hangar(item) or item.get('name') == 'Mk II Vessel Hangar'
            or sym.startswith('int_fighterbaymk2_')
            or item.get('name') in ('Large Planetary Vehicle Hangar', 'Mk II Large Planetary Vehicle Hangar')
            or sym.startswith(('int_largebuggybay_', 'int_mkiilargebuggybay_')))


def is_universal_limpet(item):
    return (item.get('name') == 'Universal Multi Limpet Controller'
            or symbol(item).startswith('int_multidronecontrol_universal_'))


def excluded_merc_spec(item):
    # Explicitly excluded requirement, not proof of absence or an ID alias.
    # Keep the item in identity facts so it cannot masquerade as a base module.
    return (item.get('name') == 'High-Yield Enzyme Missile Rack'
            and item.get('class') == 2 and item.get('rating') == 'B')


def check_stop(stop):
    if stop is not None and stop.is_set():
        raise InterruptedError('已手动停止')


def symbol(item):
    return str(item.get('ed_symbol') or item.get('symbol') or '').casefold()


def variant(item):
    """Symbol identifies real mount and special version; no fuzzy fallback."""
    ident = identity.numeric_id(item)
    if ident is not None and not item.get('identity_ambiguous'):
        return ('fdev_id', ident)
    value = symbol(item)
    return (canonical_name(item['name']), value, item.get('class'), item.get('rating')) if (
        value and isinstance(item.get('name'), str)) else None


def canonical_name(name):
    name = str(name).strip().casefold()
    return NAME_ALIASES.get(name, name)


def prepare(catalog):
    """Deduplicate proven aliases, but retain and expose identity conflicts.

    A shared symbol is not permission to invent stock for a second product.
    Conflicts are resolved against station evidence, not by arbitrary precedence.
    """
    result = dict(catalog)
    if catalog.get('release_engine') == 1:
        # Validated release packages already classify every numeric ID. Do not
        # run the old bundled name allowlist over newly released equipment.
        return result
    combined = [*catalog.get('items', []), *catalog.get('special_items', [])]
    items = {variant(item): item for item in combined if variant(item) and not is_special(item) and ordinary(item.get('name', ''))
             and not restricted_spec(item.get('name'), item.get('class'))}
    special = {variant(item): item for item in combined if variant(item) and is_special(item)}
    result['items'] = list(items.values())
    result['special_items'] = list(special.values())
    if not result.get('module_facts'):
        result['special_issues'] = special_issues(result['special_items'])
    groups = {}
    for item in [*result['items'], *result['special_items']]:
        groups.setdefault(symbol(item), []).append(item)
    conflicts, shared = [], []
    for sym, values in groups.items():
        if len(values) < 2:
            continue
        entry = dict(symbol=sym, variants=[clean(item) for item in values])
        ids = [identity.numeric_id(item) for item in values]
        if all(value is not None for value in ids) and len(set(ids)) == len(ids):
            shared.append(entry)  # Known different products, not an identity error.
        else:
            conflicts.append(entry)
    result['conflicts'], result['shared_symbols'] = conflicts, shared
    return result


def clean(item):
    return {key: item[key] for key in ('name', 'class', 'rating', 'ed_symbol', 'category',
                                      'weapon_mode', 'ship', 'ed_id') if key in item}


def download_archive():
    url = f'https://codeload.github.com/EDCD/coriolis-data/tar.gz/{REVISION}'
    with urllib.request.urlopen(url, timeout=60) as response:
        content = response.read(16 * 1024 * 1024 + 1)
    if len(content) > 16 * 1024 * 1024:
        raise ValueError('配件目录响应过大')
    return content


def supplement(content, items):
    """Add real mount variants from facts; exclude engineered duplicate symbols."""
    names = {}
    for row in items.values():
        names.setdefault(symbol(row), set()).add(row['name'])
    by_name = {name.replace('-', '').replace(' ', '').lower(): name for name in BUNDLED_MODULE_PAIRS}
    with tarfile.open(fileobj=io.BytesIO(content), mode='r:gz') as archive:
        for member in archive:
            if not member.isfile() or '/modules/' not in member.name or not member.name.endswith('.json'):
                continue
            if member.size > 2 * 1024 * 1024:
                raise ValueError('配件目录响应过大')
            stem = member.name.rsplit('/', 1)[-1][:-5]
            default = ALIASES.get(stem) or by_name.get(stem.replace('_', ''))
            data = json.load(archive.extractfile(member))
            for values in data.values():
                if not isinstance(values, list):
                    continue
                for entry in values:
                    if not isinstance(entry, dict) or not entry.get('symbol') or entry.get('edID') == 0:
                        continue
                    sym = symbol(entry)
                    candidates = names.get(sym, set())
                    power = str(entry.get('powerplay', '')).casefold() == 'true'
                    candidates = sorted(name for name in candidates if ordinary(name) and (name in POWER_MODULES) == power)
                    name = candidates[0] if candidates else None
                    if name is None:
                        # Named/special records need their real retail name from
                        # stock; never mistake a Guardian/Power item for the base.
                        if entry.get('special') or entry.get('name') or 'guardian' in sym:
                            continue
                        name = default
                    if not name or not ordinary(name) or restricted_spec(name, entry.get('class')):
                        continue
                    if not isinstance(entry.get('class'), int) or entry.get('rating') not in 'ABCDEFGHI':
                        continue
                    item = dict(name=name, ed_symbol=entry['symbol'],
                                **{'class': entry['class'], 'rating': entry['rating']})
                    items.setdefault(variant(item), item)


def required_pairs():
    return {(name, cls, rating) for name, pairs in BUNDLED_MODULE_PAIRS.items()
            if ordinary(name) for cls, rating in pairs if not restricted_spec(name, cls)}


def catalogue_issues(items):
    covered = {(canonical_name(item.get('name')), item.get('class'), item.get('rating')) for item in items
               if isinstance(item, dict) and isinstance(item.get('class'), int)
               and isinstance(item.get('rating'), str) and isinstance(item.get('name'), str)}
    return sorted((name, cls, rating) for name, cls, rating in required_pairs()
                  if (canonical_name(name), cls, rating) not in covered)


def fingerprint(catalog):
    facts = {name: catalog.get(name) for name in ('items', 'special_items', 'armours', 'ships', 'module_facts')}
    return hashlib.sha256(json.dumps(facts, sort_keys=True, ensure_ascii=True).encode()).hexdigest()


def special_issues(items):
    covered = {(item.get('name'), item.get('class'), item.get('rating')) for item in items}
    issues = []
    for name in sorted(SPECIAL_MODULES):
        pairs = BUNDLED_MODULE_PAIRS.get(name, ())
        if pairs:
            issues.extend((name, cls, rating) for cls, rating in pairs
                          if not excluded_merc_spec(dict(name=name, **{'class': cls, 'rating': rating}))
                          and (name, cls, rating) not in covered)
        elif name == 'High-Yield Enzyme Missile Rack':
            # The known 2B variant is not a required Merc purchase.
            continue
        elif not any(item.get('name') == name for item in items):
            issues.append((name, None, None))
    return issues


def load(stop=None, progress=None, refresh=False, http=None, archive_fetch=None, include_special=False, facts_fetch=None):
    """Build/cache public facts. Cancellation/failed audits never replace a cache."""
    check_stop(stop)
    import catalog_updates
    try:
        package = catalog_updates.read_package()
        if package:
            return catalog_updates.as_catalog(package)
    except (ValueError, OSError) as exc:
        if progress:
            progress(f'本地更新清单无效，使用原目录：{exc}')
    http = http or eng._http_json
    archive_fetch = archive_fetch or download_archive
    path = data_file(CACHE_NAME)
    cached = session_store.load(path)
    valid = (not refresh and isinstance(cached, dict) and cached.get('schema') == SCHEMA
            and cached.get('revision') == REVISION and isinstance(cached.get('items'), list)
            and cached['items'] and cached.get('fingerprint') == fingerprint(cached)
            and cached.get('identity_revision') == identity.REVISION and cached.get('module_facts')
            and not cached.get('issues'))
    if valid:
        return cached
    items = {variant(item): item for item in cached['items']} if valid else {}
    armour = {(item['ship'], variant(item)): item for item in cached.get('armours', [])} if valid else {}
    special = {variant(item): item for item in cached.get('special_items', [])} if valid else {}

    def collect(rows):
        for station in rows:
            for item in station.get('modules', []):
                ident = variant(item)
                if not ident:
                    continue
                name = item['name']
                if name in SPECIAL_MODULES:
                    special[ident] = clean(item)
                elif item.get('ship') and (name in ARMOURS or 'Alloy' in name or 'Composite' in name):
                    armour[(item['ship'], ident)] = clean(item)
                elif name in BUNDLED_MODULE_PAIRS and ordinary(name) and not restricted_spec(name, item.get('class')):
                    items[ident] = clean(item)

    def fetch(filters):
        check_stop(stop)
        response = http('https://spansh.co.uk/api/stations/search',
                        dict(filters=filters, size=3, page=0))
        if not isinstance(response, dict) or not isinstance(response.get('results'), list):
            raise ValueError('服务器响应无效')
        collect(response['results'])

    if progress:
        progress('正在核验配件规格目录…')
    # These are catalogue observations only, not automatic search results.
    if not valid:
        for station in ('Jameson Memorial', 'I Sola Prospect'):
            fetch({'name': {'value': station}})
        check_stop(stop)
        supplement(archive_fetch(), items)
    missing_names = sorted({name for name, _, _ in catalogue_issues(list(items.values()))})
    for index, name in enumerate(missing_names):
        if progress:
            progress(f'正在核验配件规格目录… {index + 1}/{len(missing_names)}: {name}')
        fetch({'modules': [{'name': {'value': [name]}}]})
    # Broad name queries may return stations without a rare class/rating. Ask
    # for that exact real pair, never infer it from independent marginals.
    for name, cls, rating in catalogue_issues(list(items.values())):
        if progress:
            progress(f'正在核验配件规格目录… {name} {cls}{rating}')
        fetch({'modules': [{'name': {'value': [name]}, 'class': {'value': [cls]},
                            'rating': {'value': [rating]}}]})
    check_stop(stop)
    issues = catalogue_issues(list(items.values()))
    result = prepare(dict(schema=SCHEMA, revision=REVISION, built_at=datetime.now(timezone.utc).isoformat(),
                  items=list(items.values()),
                  special_items=list(special.values()), special_checked=include_special,
                  special_issues=special_issues(list(special.values())),
                  special_errors=[],
                  armours=list(armour.values()), ships=list(BUNDLED_OPTIONS['stations/ships']),
                  issues=issues))
    facts = (facts_fetch or identity.download_facts)()
    result = prepare(identity.canonical_catalog(result, facts, ordinary, restricted_spec))
    # Hull armour also has a stable ID, while keeping the observed ship label.
    _, fact_symbols = identity.indexes(facts)
    for item in result['armours']:
        choices = fact_symbols.get(symbol(item), [])
        if len(choices) == 1:
            item['ed_id'] = choices[0]['ed_id']
    check_stop(stop)
    if not result['issues']:
        result['fingerprint'] = fingerprint(result)
        session_store.save(path, result)
    return result
