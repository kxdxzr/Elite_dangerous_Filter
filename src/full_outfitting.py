"""Strict same-station inventory and public-discount checks."""
import copy
from dataclasses import dataclass, replace
import math
import time
import urllib.error

import filter_engine as eng
import outfitting_catalog as catalogue
import outfitting_identity as identity
from station_discounts import ALL_MODULE_PUBLIC_STATIONS, discount_info, key, public_surcharge


@dataclass(frozen=True)
class Criteria:
    reference: str
    radius: float
    other_discounts: bool = False
    neutral_ships: bool = False
    federal_ships: bool = False
    imperial_ships: bool = False
    guardian: bool = False
    special_equipment: bool = False
    require_discount: bool = False
    ax_weapons: bool = False
    universal_limpets: bool = False


def build_criteria(reference, radius, **options):
    reference = reference.strip()
    try:
        radius = float(radius)
    except (ValueError, TypeError):
        radius = 0
    if not reference or not math.isfinite(radius) or radius <= 0:
        raise ValueError('请填写参考星系和正数检索半径')
    if any(type(value) is not bool for value in options.values()):
        raise ValueError('条件开关须为布尔值')
    return Criteria(reference, radius, **options)


def ship_group(name):
    if name.startswith('Federal '):
        return 'federal_ships'
    if name.startswith('Imperial ') or name == 'Corsair':
        return 'imperial_ships'
    return 'neutral_ships'  # Alliance explicitly belongs here.


def has_guardian(row):
    broker = row.get('technology_broker')
    if isinstance(broker, str):
        return broker.casefold() == 'guardian'
    return False  # Generic Technology Broker service is not Guardian evidence.


def inventory_key(item):
    if item.get('identity_ambiguous'):
        return None
    ident = catalogue.variant(item)
    if ident and ident[0] == 'fdev_id':
        return ident
    cls, rating = item.get('class'), item.get('rating')
    if ident and isinstance(cls, int) and not isinstance(cls, bool) and isinstance(rating, str):
        return ident, cls, rating.upper()
    return None


def excluded_station(row):
    kind = str(row.get('type', '')).casefold()
    return (not kind or 'carrier' in kind or 'stronghold' in kind
            or 'stronghold carrier' in str(row.get('name', '')).casefold())


def complete_result_metadata(row, criteria, http, contexts=None, notes=None):
    """Fill presentation fields from exact Spansh identities; never merge stock.

    Metadata failure must not remove a stock-verified hit. Inventory timestamps
    remain attached to the inventory actually checked, not a newer response.
    """
    contexts = contexts if contexts is not None else {}
    notes = notes if notes is not None else []
    system = row.get('system_name')
    if not system:
        notes.append('结果缺少星系名称，无法补全资料')
        return
    try:
        if not contexts.get(system):
            response = http('https://spansh.co.uk/api/systems/search', dict(
                filters={'name': {'value': system}}, size=10, page=0,
                reference_system=criteria.reference))
            contexts[system] = next((item for item in response.get('results', [])
                                    if str(item.get('name', '')).strip().casefold() == str(system).strip().casefold()
                                    and (not row.get('system_id64') or
                                         str(item.get('id64') or item.get('id')) == str(row['system_id64']))), {})
        context = contexts[system]
        for target, source in (('needs_permit', 'needs_permit'),
                               ('system_controlling_power', 'controlling_power'),
                               ('system_power_state', 'power_state')):
            if row.get(target) in (None, '') and context.get(source) not in (None, ''):
                row[target] = context[source]
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        notes.append(f"{system} / 结果星系资料补全失败: {exc}")
    fields = ('distance', 'distance_to_arrival', 'technology_broker', 'services')
    if not any(row.get(field) in (None, '') for field in fields) and row.get('outfitting_updated_at'):
        return
    try:
        response = http('https://spansh.co.uk/api/stations/search', dict(
            filters={'name': {'value': row.get('name')}, 'system_name': {'value': system}},
            size=10, page=0, reference_system=criteria.reference))
        market = row.get('market_id') or row.get('id')
        station = next((item for item in response.get('results', [])
                        if str(item.get('name', '')).strip().casefold() == str(row.get('name', '')).strip().casefold()
                        and str(item.get('system_name', '')).strip().casefold() == str(system).strip().casefold()
                        and (not market or str(item.get('market_id') or item.get('id')) == str(market))), {})
        for field in fields:
            if row.get(field) in (None, '') and station.get(field) not in (None, ''):
                row[field] = copy.deepcopy(station[field])
        # A timestamp can be backfilled only if the associated stock snapshot
        # is exactly the same. Do not re-date old Spansh or EDSM evidence.
        if (not row.get('outfitting_updated_at') and row.get('modules')
                and row.get('modules') == station.get('modules')):
            row['outfitting_updated_at'] = station.get('outfitting_updated_at')
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        notes.append(f"{system} / {row.get('name')} / 结果站点资料补全失败: {exc}")


def check_station(row, criteria, catalog):
    """Return evidence and all failures. Missing data never qualifies a station."""
    problems, missing, no_discount, unknown = [], [], [], []
    result = dict(matched=False, missing=missing, no_discount=no_discount, problems=problems,
                  surcharge=public_surcharge(row),
                  unknown=unknown, required=0, present=0, discount_min=None, discount_max=None, sources=[])
    if excluded_station(row):
        problems.append('排除航母或站点类型未知')
        return result
    lyr = (key(row.get('system_controlling_power')) == key('Li Yong-Rui')
           and str(row.get('system_power_state', '')).casefold() in ('fortified', 'stronghold'))
    if criteria.require_discount and not criteria.other_discounts and not lyr:
        problems.append('未确认 LYR 15%公共折扣')
    if criteria.require_discount and criteria.other_discounts and not lyr and not any(
            key(row.get('system_name')) == key(system) and key(row.get('name')) == key(station)
            for system, station, _ in ALL_MODULE_PUBLIC_STATIONS):
        problems.append('未确认全配件公共折扣')
    if criteria.guardian and not has_guardian(row):
        problems.append('未确认同站 Guardian 科技经纪人')
    if problems:
        return result  # Cheap evidence checks precede the large inventory walk.
    requirements = [item for item in catalog.get('items', [])
                    if not catalogue.excluded_hangar(item)
                    and (criteria.universal_limpets or not catalogue.is_universal_limpet(item))
                    and (criteria.ax_weapons or not catalogue.is_ax(item))]
    if criteria.universal_limpets and not {(7, 'A'), (7, 'C')}.issubset(
            {(item.get('class'), item.get('rating')) for item in requirements
             if catalogue.is_universal_limpet(item)}):
        problems.append('通用无人机控制器目录不完整，无法确认齐全')
    if criteria.ax_weapons and not catalog.get('release_engine') and not catalogue.AX_EQUIPMENT.issubset(
            {item.get('name') for item in requirements}):
        problems.append('AX装备目录不完整，无法确认齐全')
    if criteria.special_equipment:
        requirements.extend(item for item in catalog.get('special_items', [])
                            if not catalogue.excluded_merc_spec(item))
        if catalog.get('special_issues') or not catalog.get('special_items'):
            problems.append('特殊装备目录不完整，无法确认齐全')
    if not requirements or catalog.get('issues'):
        problems.append('配件规格目录不完整，无法确认齐全')
    selected = [name for name in catalog.get('ships', []) if getattr(criteria, ship_group(name))]
    if any((criteria.neutral_ships, criteria.federal_ships, criteria.imperial_ships)) and not selected:
        problems.append('舰船目录不完整')
    raw_ships = row.get('ships')
    ship_names = {key(item.get('name')) for item in raw_ships
                  if isinstance(item, dict) and item.get('name')} if isinstance(raw_ships, list) else set()
    missing_ships = [name for name in selected if key(name) not in ship_names]
    result['missing_ships'] = missing_ships
    if missing_ships:
        problems.append('舰船库存不齐或未知')
    for ship in selected:
        armour = [item for item in catalog.get('armours', []) if key(item.get('ship')) == key(ship)]
        names = {item.get('name') for item in armour}
        if not any(family.issubset(names) for family in (catalogue.ARMOURS, catalogue.MKII_ARMOURS)):
            problems.append(f'船体装甲目录不完整: {ship}')
        requirements.extend(armour)
    raw_modules = row.get('modules')
    stock, by_symbol = {}, {}
    if not isinstance(raw_modules, list) or not raw_modules:
        problems.append('配件库存未知')
    else:
        facts = catalog.get('module_facts')
        modules = identity.normalize_stock(raw_modules, facts) if facts else raw_modules
        modules = [*modules, *row.get('_edsm_modules', [])]
        for item in modules:
            if isinstance(item, dict):
                if inventory_key(item):
                    stock[inventory_key(item)] = item
                by_symbol.setdefault(catalogue.symbol(item), []).append(item)
    percentages, sources, sale_items = [], set(), []
    if result['surcharge']:
        sources.add('i Sola Prospect')
    for item in requirements:
        expected = inventory_key(item)
        actual = stock.get(expected) if expected is not None else None
        label = f"{item.get('name', '?')} {item.get('class', '?')}{item.get('rating', '?')} [{catalogue.symbol(item)}]"
        if actual is None or (item.get('ship') and key(actual.get('ship')) != key(item['ship'])):
            alternatives = by_symbol.get(catalogue.symbol(item), [])
            if alternatives and not item.get('ship'):
                observed = '; '.join(f"{value.get('name')} {value.get('class')}{value.get('rating')}"
                                     for value in alternatives)
                unknown.append(f'{label} → {observed}')
            else:
                missing.append(label)
            continue
        result['present'] += 1
        if catalogue.is_special(item):
            # The optional Merc Coins condition is stock-only. A credit discount
            # is not evidence that token costs are discounted.
            continue
        sale_items.append((actual, label))
    # Do not spend time pricing hundreds of items at clearly incomplete shops.
    # Nearly complete/complete stock is still checked item by item.
    if not problems and not missing:
        for actual, label in sale_items:
            discount = discount_info(row, actual, 'modules')  # No personal-rank bonuses.
            if discount['discounted'] is not True:
                no_discount.append(label)
            else:
                percentages.append(discount['percent'])
                sources.add(discount['source'])
    result.update(required=len(requirements), sources=sorted(sources),
                  discount_covered=len(percentages), discount_total=sum(not catalogue.is_special(item) for item in requirements),
                  discount_min=min(percentages) if percentages else None,
                  discount_max=max(percentages) if percentages else None)
    result['matched'] = not (problems or missing or unknown or (criteria.require_discount and no_discount))
    return result


def review_status(evidence, criteria):
    if evidence['matched']:
        return 'matched'
    if evidence['missing']:
        return 'incomplete'
    if evidence['problems']:
        return 'conditions_unconfirmed'
    if criteria.require_discount and evidence['no_discount']:
        return 'discount_unconfirmed'
    if evidence['unknown']:
        return 'identity_pending'
    return 'conditions_unconfirmed'


def anchor_conditions(catalog):
    """Mandatory, unambiguous variants used only as a server prefilter.

    Every anchor is itself a required catalogue item, so a station missing one
    could not pass the full check anyway. This keeps the expensive 853-item walk
    for plausible candidates instead of every outfitter in the radius.
    """
    anchors, seen = [], set()
    for item in catalog.get('items', []):
        name = item.get('name')
        if (not name or name in seen or item.get('class') != 8 or item.get('rating') != 'A'
                or item.get('ship') or catalogue.is_special(item)):
            continue
        seen.add(name)
        anchors.append(dict(type='field', field='modules', op='in', values=[name],
                            **{'class': [8], 'rating': ['A']}))
    return anchors


def request_json(url, payload=None, *, stop=None, progress=None):
    """At most one transient retry; never change the shared engine transport."""
    if payload and url.endswith('/stations/search') and payload.get('page', 0) * payload.get('size', 0) >= 10000:
        raise ValueError('达到单来源10000条安全分页上限，请缩小检索半径')
    for attempt in range(2):
        catalogue.check_stop(stop)
        try:
            return eng._http_json(url, payload)
        except (urllib.error.URLError, TimeoutError) as exc:
            transient = not isinstance(exc, urllib.error.HTTPError) or exc.code in (500, 502, 503, 504)
            if attempt or not transient:
                raise
            if progress:
                progress('请求暂时失败，重试一次…')
            if stop is not None:
                if stop.wait(.75):
                    raise InterruptedError('已手动停止') from exc
            else:
                time.sleep(.75)


def candidate_sources(criteria):
    """Optional discount scope; ordinary searches use mandatory stock anchors."""
    if not criteria.require_discount:
        return [('全部配件商店', [])]
    sources = []
    if criteria.other_discounts:
        for system, station, _ in ALL_MODULE_PUBLIC_STATIONS:
            sources.append((station, [dict(type='field', field='system_name', op='=', text=system),
                                      dict(type='field', field='name', op='=', text=station)]))
    sources.append(('LYR 15%', [dict(type='field', field='system_controlling_power', op='=', text='Li Yong-Rui'),
                               dict(type='field', field='system_power_state', op='in', values=['Fortified', 'Stronghold'])]))
    return sources


def reference_station(criteria, catalog, stop=None, progress=None):
    """A visible benchmark, never an unconditional qualifying search result."""
    reference = dict(name='Jameson Memorial', system_name='Shinrarta Dezhra',
                     counted_as_hit=False, within_radius=None, scope_eligible=False)
    try:
        response = request_json('https://spansh.co.uk/api/stations/search',
                                dict(filters={'system_name': {'value': 'Shinrarta Dezhra'},
                                              'name': {'value': 'Jameson Memorial'}},
                                     reference_system=criteria.reference, size=3, page=0),
                                stop=stop, progress=progress)
        if not isinstance(response, dict) or not isinstance(response.get('results'), list):
            raise ValueError('参照站数据未返回')
        rows = [row for row in response.get('results', [])
                if str(row.get('name', '')).casefold() == 'jameson memorial'
                and str(row.get('system_name', '')).casefold() == 'shinrarta dezhra'
                and not excluded_station(row)]
        if not rows:
            reference['error'] = '参照站数据未返回'
            return reference
        row = max(rows, key=lambda value: str(value.get('outfitting_updated_at') or value.get('updated_at') or ''))
        reference['evidence'] = check_station(row, replace(criteria, other_discounts=True), catalog)
        reference['outfitting_updated_at'] = row.get('outfitting_updated_at')
        distance = row.get('distance')
        if isinstance(distance, (int, float)) and not isinstance(distance, bool) and math.isfinite(distance):
            reference.update(distance=distance, within_radius=distance <= criteria.radius)
        reference['scope_eligible'] = (not criteria.require_discount or criteria.other_discounts) and reference['within_radius'] is True
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        reference['error'] = str(exc)
    return reference


def search(criteria, want=100, max_pages=25, stop=None, progress=None, catalog=None, refresh=False,
           include_reference=False):
    if type(want) is not int or want < 1 or type(max_pages) is not int or max_pages < 1:
        raise ValueError('结果数和页数必须大于零')
    notes = ['按已知规格目录逐项核验，不保证实时库存；默认已有全部 Power 配件购买资格。']
    result = dict(rows=[], diagnostics=[], notes=notes, scanned=0, total=0, rejected=0,
                  uncertain=0, identity_candidates=[], incomplete=0, condition_failures=0,
                  stopped=False, complete=False, partial=False, errors=[], sources=[],
                  catalog_revision=catalogue.REVISION, criteria=vars(criteria).copy(),
                  search_limits=dict(want=want, max_pages=max_pages))
    stage, page = '配件目录', 1
    exhausted = True

    def announce(text, detail=None):
        if progress:
            progress(text, detail)

    def http(url, payload=None):
        return request_json(url, payload, stop=stop, progress=announce)

    def failure(exc):
        error = dict(source=stage, page=page, message=str(exc), status=getattr(exc, 'code', None))
        result['errors'].append(error)
        notes.append(f"{stage} / 第{page}页: {exc}")

    try:
        catalogue.check_stop(stop)
        catalog = catalog if catalog is not None else catalogue.load(
            stop, announce, refresh, http=http, include_special=criteria.special_equipment)
        catalog = catalogue.prepare(catalog)
        if include_reference:
            announce('正在核验创世参照站…')
            result['reference'] = reference_station(criteria, catalog, stop=stop, progress=announce)
        if catalog.get('issues') or not catalog.get('items'):
            notes.append('配件规格目录不完整，无法确认齐全')
            result['catalog_issues'] = catalog.get('issues', [])
            result['partial'] = True
            return result
        result.update(catalog_size=len(catalog['items']), catalog_built_at=catalog.get('built_at', ''),
                      catalog_revision=catalog.get('release_version', catalogue.REVISION),
                      catalog_sources=catalog.get('release_sources', []),
                      catalog_rules_version=catalog.get('release_engine', 'bundled'),
                      identity_revision=catalog.get('identity_revision', ''),
                      catalog_special_size=sum(not catalogue.excluded_merc_spec(item)
                                               for item in catalog.get('special_items', [])) if criteria.special_equipment else 0,
                      catalog_conflicts=catalog.get('conflicts', []),
                      catalog_shared_symbols=len(catalog.get('shared_symbols', [])),
                      special_issues=catalog.get('special_issues', []) if criteria.special_equipment else [],
                      special_errors=catalog.get('special_errors', []) if criteria.special_equipment else [])
        if catalog.get('module_facts'):
            notes.append('目录按数字物品ID去重，不要求工程师专售规格及限定科技配件。')
        contexts, seen = {}, set()
        anchors = anchor_conditions(dict(catalog, items=[item for item in catalog['items']
                                    if (criteria.ax_weapons or not catalogue.is_ax(item))
                                    and (criteria.universal_limpets or not catalogue.is_universal_limpet(item))
                                    and not catalogue.excluded_hangar(item)]))

        def enrich_power(row):
            name = row.get('system_name')
            named = any(key(name) == key(system) and key(row.get('name')) == key(station)
                        for system, station, _ in ALL_MODULE_PUBLIC_STATIONS)
            if (excluded_station(row) or named or not name
                    or row.get('system_controlling_power') and row.get('system_power_state')):
                return
            if name not in contexts:
                try:
                    announce(f"正在补查折扣背景… {row.get('name', '')}",
                             dict(done=0, work_total=None, stage='优惠资料复核'))
                    response = http('https://spansh.co.uk/api/systems/search',
                                    dict(filters={'name': {'value': name}}, size=1, page=0))
                    contexts[name] = next((item for item in response.get('results', [])
                                          if str(item.get('name', '')).casefold() == name.casefold()), {})
                except (urllib.error.URLError, TimeoutError, ValueError) as exc:
                    contexts[name] = {}
                    notes.append(f'{name}: {exc}')
            for target, source in (('system_controlling_power', 'controlling_power'),
                                   ('system_power_state', 'power_state'), ('needs_permit', 'needs_permit')):
                if row.get(target) in (None, '') and source in contexts[name]:
                    row[target] = contexts[name][source]

        remaining = max_pages
        for stage, source_conditions in candidate_sources(criteria):
            catalogue.check_stop(stop)
            if remaining <= 0 or len(result['rows']) >= want:
                exhausted = False
                break
            base_scanned = result['scanned']
            base_hits = len(result['rows'])
            page, inspected, reported_scanned, pages_used = 1, 0, 0, 0
            source_notes = []
            source_info = dict(name=stage, complete=False, scanned=0, pages=0, total=0)
            result['sources'].append(source_info)

            def update(text, detail=None):
                nonlocal page, pages_used, reported_scanned
                if detail:
                    reported_scanned = max(reported_scanned, detail.get('scanned', 0))
                    if isinstance(detail.get('total'), int):
                        source_info['total'] = max(source_info['total'], detail['total'])
                    if detail.get('phase') == 'fetch':
                        page = detail.get('page', 0) + 1
                        pages_used = max(pages_used, page)
                    result['scanned'] = base_scanned + max(reported_scanned, inspected)
                    total = detail.get('total', 0)
                    detail = dict(detail, scanned=result['scanned'], hits=len(result['rows']),
                                  done=reported_scanned,
                                  work_total=total if isinstance(total, int) and 0 < total < 10000 else None,
                                  stage=f'{stage}: 候选核查')
                else:
                    # Keep the known candidate progress while a second source is
                    # checked; otherwise the bar appears to jump back to zero at
                    # the exact moment the last candidates need the most work.
                    total = source_info['total']
                    detail = dict(done=reported_scanned,
                                  work_total=total if isinstance(total, int) and 0 < total < 10000 else None,
                                  stage=f'{stage}: 库存复核')
                announce(f'{stage}: {text}', detail)

            def inspect(row):
                nonlocal inspected
                if stop is not None and stop.is_set():
                    return False
                inspected += 1
                result['scanned'] = base_scanned + max(reported_scanned, inspected)
                ident = row.get('id') or (row.get('system_name'), row.get('name'))
                if ident in seen:
                    return False
                seen.add(ident)
                if criteria.require_discount:
                    enrich_power(row)
                evidence = check_station(row, criteria, catalog)
                # Resolve nearly complete inventories through independent,
                # explicitly named same-market records. No station whitelist.
                if (catalog.get('module_facts') and evidence['unknown'] and not evidence['missing']
                        and not evidence['problems'] and (not criteria.require_discount or not evidence['no_discount'])):
                    try:
                        update(f"正在用第二来源复核库存… {row.get('name', '')}")
                        row['_edsm_modules'] = identity.edsm_stock(row, catalog['module_facts'], http)
                        if row['_edsm_modules']:
                            row['_stock_sources'] = ['Spansh', 'EDSM（未提供库存时间）']
                            note = '第二来源未提供库存时间，合并核验不代表现场实时库存。'
                            if note not in notes:
                                notes.append(note)
                            evidence = check_station(row, criteria, catalog)
                    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
                        notes.append(f"{row.get('name')}: {exc}")
                if evidence['matched']:
                    update(f"正在补全结果资料… {row.get('name', '')}")
                    complete_result_metadata(row, criteria, http, contexts, notes)
                    evidence = check_station(row, criteria, catalog)
                status = review_status(evidence, criteria)
                evidence['review_status'] = status
                row['_full_outfitting'] = evidence
                if evidence['matched']:
                    # Capture before the engine can fail on a later page.
                    result['rows'].append(copy.deepcopy(row))
                else:
                    result['rejected'] += 1
                    if status == 'identity_pending':
                        result['uncertain'] += 1
                    elif status == 'incomplete':
                        result['incomplete'] += 1
                    else:
                        result['condition_failures'] += 1
                    summary = {key: value for key, value in row.items() if key in
                               ('name', 'system_name', 'type', 'distance', '_full_outfitting')}
                    result['diagnostics'].append(summary)
                    if status == 'identity_pending' and len(result['identity_candidates']) < 100:
                        result['identity_candidates'].append(summary)
                    result['diagnostics'].sort(key=lambda item: (
                        item['_full_outfitting'].get('review_status') == 'identity_pending',
                        item['_full_outfitting']['required'] > 0,
                        item['_full_outfitting']['present'] / max(1, item['_full_outfitting']['required'])), reverse=True)
                    del result['diagnostics'][100:]
                return evidence['matched']

            try:
                _, total, scanned = eng.search(
                    'stations', [dict(type='distance', ref_system=criteria.reference, max_ly=criteria.radius),
                                 dict(type='field', field='has_outfitting', op='true'), *source_conditions, *anchors],
                    want=want - base_hits, max_pages=remaining, stop=stop, progress=update,
                    notes=source_notes, row_filter=inspect, http=http)
                source_info['total'] = total
                result['scanned'] = base_scanned + scanned
                source_info['complete'] = bool(source_notes and source_notes[-1] == '候选分页已取完')
                exhausted = exhausted and source_info['complete']
            except (urllib.error.URLError, TimeoutError, ValueError) as exc:
                failure(exc)
                exhausted = False
            finally:
                remaining -= pages_used
                source_info.update(scanned=result['scanned'] - base_scanned, pages=pages_used)
                result['total'] += source_info['total']
                notes.extend(f'{stage}: {note}' for note in source_notes)
    except InterruptedError:
        result['stopped'] = True
        notes.append('已手动停止')
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        failure(exc)
        exhausted = False
    result['stopped'] = result['stopped'] or (stop is not None and stop.is_set())
    result['complete'] = exhausted and not result['errors'] and not result['stopped']
    result['partial'] = not result['complete']
    if result['partial']:
        notes.append('检索未完成，已保留通过核验的部分结果')
    return result


COLUMNS = [('system_name', '星系'), ('name', '站点'), ('distance', '距离 ly'),
           ('distance_to_arrival', '到站距离 Ls'), ('coverage', '已知规格覆盖'),
            ('discount', '公共折扣'), ('discount_scope', '已知优惠范围'), ('sources', '优惠来源'),
           ('guardian', 'Guardian 科技经纪人'), ('permit', '许可'),
           ('outfitting_updated_at', '配件库存更新时间'), ('catalog_revision', '目录事实版本'),
           ('catalog_built_at', '目录核验时间'), ('eligibility', '购买资格假设'), ('ship_requirements', '舰船条件'),
           ('search_status', '检索完整性'), ('special_requirements', '特殊装备条件'), ('stock_sources', '库存核验来源'),
            ('identity_revision', '物品ID目录版本'), ('discount_requirement', '折扣要求'),
            ('ax_requirements', 'AX装备条件'), ('catalog_rules_version', '目录规则版本'),
            ('catalog_sources', '目录事实来源'), ('universal_requirements', '通用无人机控制器条件'),
            ('snapshot_created_at', '库存快照时间'), ('snapshot_scope_text', '库存快照范围')]


def export_search_conditions(result, tr=lambda text: text):
    """Describe the completed query, never the current editable GUI form."""
    criteria = (result or {}).get('criteria')
    if not criteria:
        return tr('未记录检索条件')
    limits = result.get('search_limits', {})
    fields = [('参考星系', criteria.get('reference')), ('检索半径 ly', criteria.get('radius')),
              ('最多结果', limits.get('want')), ('最多页数', limits.get('max_pages'))]
    if result.get('snapshot_created_at'):
        scope = result.get('snapshot_scope', {})
        fields.extend([('库存快照时间', result['snapshot_created_at']),
                       ('库存快照范围', f"{scope.get('reference', '')} / {scope.get('radius', '')} ly"),
                       ('快照更新页数上限', result.get('snapshot_update_pages'))])
    for field, label in (
            ('require_discount', '必须全配件公共折扣'),
            ('other_discounts', '包含其他全配件公共折扣站'),
            ('ax_weapons', 'AX装备规格齐全'),
            ('universal_limpets', '要求通用无人机控制器7A及7C'),
            ('special_equipment', 'Merc Coins 特殊装备齐全（仅库存）'),
            ('neutral_ships', '全部非势力船（含联盟）'),
            ('federal_ships', '全部联邦船'), ('imperial_ships', '全部帝国船'),
            ('guardian', '同站Guardian科技经纪人')):
        value = tr('是' if criteria.get(field, False) else '否')
        if field == 'other_discounts' and not criteria.get('require_discount'):
            value = tr('不适用（未要求折扣）')
        fields.append((label, value))
    return '; '.join(f"{tr(label)}: {value if value is not None else tr('未记录')}" for label, value in fields)


def export_table(result, tr=lambda text: text):
    from result_format import format_ly, format_ls
    headers = [tr(title) for _, title in COLUMNS]
    records = []
    for row in (result or {}).get('rows', []):
        evidence = row['_full_outfitting']
        low, high = evidence['discount_min'], evidence['discount_max']
        discount = tr('未确认公共折扣') if low is None else f'{low}%' if low == high else f'{low}–{high}%'
        covered = evidence.get('discount_covered', evidence.get('required', 0) if not evidence.get('no_discount') else 0)
        total = evidence.get('discount_total', evidence.get('required', 0))
        discount_scope = tr('未确认公共折扣' if low is None else
                            '全配件有已知优惠' if covered == total else '部分配件有已知优惠')
        if evidence.get('surcharge'):
            discount = tr('公共加价') + f" {evidence['surcharge']}%"
            discount_scope = tr('全配件公共加价')
        criteria = (result or {}).get('criteria', {})
        groups = [tr(label) for name, label in (('neutral_ships', '全部非势力船（含联盟）'),
                  ('federal_ships', '全部联邦船'), ('imperial_ships', '全部帝国船')) if criteria.get(name)]
        values = dict(row, distance=format_ly(row.get('distance')), coverage=f"{evidence['present']}/{evidence['required']}",
                      distance_to_arrival=format_ls(row.get('distance_to_arrival')),
                      discount=discount, discount_scope=discount_scope,
                      sources='; '.join(evidence['sources']),
                       guardian=tr('是' if has_guardian(row) else '否' if row.get('technology_broker') == 'Human'
                                   or isinstance(row.get('services'), list) and row['services']
                                   and not any(key(item.get('name') if isinstance(item, dict) else item) == key('Technology Broker')
                                               for item in row['services']) else 'Spansh未提供'),
                      ship_requirements='; '.join(groups) or '-',
                       catalog_revision=(result or {}).get('catalog_revision', ''),
                       catalog_rules_version=(result or {}).get('catalog_rules_version', 'bundled'),
                       catalog_sources='; '.join((result or {}).get('catalog_sources', [])),
                       snapshot_created_at=(result or {}).get('snapshot_created_at', ''),
                       snapshot_scope_text=(f"{result['snapshot_scope'].get('reference', '')} / "
                                            f"{result['snapshot_scope'].get('radius', '')} ly"
                                            if result.get('snapshot_scope') else ''),
                      identity_revision=(result or {}).get('identity_revision', ''),
                      catalog_built_at=(result or {}).get('catalog_built_at', ''),
                      eligibility=tr('默认已有全部 Power 配件购买资格'),
                      discount_requirement=tr('必须全配件公共折扣' if criteria.get('require_discount') else '不要求折扣'),
                      stock_sources='; '.join(tr(source) for source in row.get('_stock_sources', ['Spansh'])),
                       special_requirements=tr('Merc Coins 特殊装备齐全（仅库存）' if criteria.get('special_equipment') else '不要求特殊装备'),
                       ax_requirements=tr('AX装备规格齐全' if criteria.get('ax_weapons') else '不要求AX装备'),
                       universal_requirements=tr('要求通用无人机控制器7A及7C' if criteria.get('universal_limpets')
                                                 else '不要求通用无人机控制器7A及7C'),
                       search_status=tr('部分结果' if result.get('partial') else
                                        '已有站点名单筛选完成' if result.get('snapshot_local') else '候选分页已取完'),
                      permit=tr('需许可' if row.get('needs_permit') is True else
                                 '免许可' if row.get('needs_permit') is False else 'Spansh未提供'))
        for field in ('distance', 'distance_to_arrival', 'outfitting_updated_at'):
            if values.get(field) in (None, '', '-'):
                values[field] = tr('Spansh未提供')
        records.append([values.get(field) if values.get(field) not in (None, '') else '-' for field, _ in COLUMNS])
    return headers, records
