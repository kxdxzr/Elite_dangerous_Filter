"""RES candidates independent of EDTools massacre-mission pair coverage."""
import math
import time
from concurrent.futures import ThreadPoolExecutor

import filter_engine as eng
import pve_access
import pve_cache
import pve_tool as pve


def annotate_source_controllers(rows, info, *, details_loader=pve.system_details,
                                stop=None, refresh=False, progress=None):
    """Display-only BGS lookup; never infer a controller from the RES target."""
    pending, names = [], {}
    for row in rows:
        if not row.get('_known_sources'):
            row['source_controller'] = '-'
            continue
        if row.get('source_controller') and row['source_controller'] not in ('-', '—'):
            continue
        sources = row.get('_source_names') or [row['source']]
        pending.append((row, sources))
        for name in sources:
            names.setdefault(name.casefold(), name)
    results = {}
    failures = []
    reporter = pve.ProgressReporter(progress)

    def load(name):
        try:
            details = (pve.system_details(name, refresh=refresh) if details_loader is pve.system_details
                       else details_loader(name))
            controller = details.get('controlling_minor_faction')
            if not isinstance(controller, str) or not controller.strip():
                raise ValueError('Controlling faction missing.')
            return controller, None
        except Exception as exc:
            return '情况未知', name + ': ' + str(exc)

    unique = list(names.items())
    if unique:
        reporter.emit(f'任务来源控制派系：0/{len(unique)}', True)
        with ThreadPoolExecutor(max_workers=4) as pool:
            for start in range(0, len(unique), 4):
                if stop is not None and stop.is_set():
                    info['complete'] = False
                    break
                batch = [(key, pool.submit(load, name)) for key, name in unique[start:start + 4]]
                for key, future in batch:
                    controller, error = future.result()
                    results[key] = controller
                    if error:
                        failures.append(error)
                    reporter.emit(f'任务来源控制派系：{len(results)}/{len(unique)}', len(results) == len(unique))
    for row, sources in pending:
        row['source_controller'] = (results.get(sources[0].casefold(), '情况未知') if len(sources) == 1 else
                                    '; '.join(name + ': ' + results.get(name.casefold(), '情况未知') for name in sources))
    if failures:
        info.setdefault('errors', []).extend('Source controller annotation: ' + error for error in failures)
    info.setdefault('diagnostics', {})['source_controller_lookups'] = len(results)


def merge_results(criteria, legacy_info, legacy_rows, extra_info, extra_rows):
    """Preserve task-pair rows; only append targets not already represented."""
    def eligible(row):
        levels = row.get('res_types', [])
        return (criteria.site_type == 'any' or
                criteria.site_type == 'confirmed' and bool(levels) or
                criteria.site_type in levels)
    extra_by_target = {row['target'].casefold(): row for row in extra_rows}
    ring_free = {name.casefold() for name in extra_info.get('ring_free_targets', [])}
    rows = []
    for original in legacy_rows:
        if original['target'].casefold() in ring_free and original.get('site_evidence') != 'cnb':
            continue
        row = dict(original, _known_sources=True)
        verified = extra_by_target.get(row['target'].casefold())
        if verified and row.get('site_evidence') != 'cnb':
            preserve_explicit = row.get('site_evidence') == 'res' and verified.get('site_evidence') != 'res'
            for key in ('site', 'site_evidence', 'res_types', 'target_ring_ls', 'target_ring_body',
                        'target_controller', 'target_power', 'target_updated', 'site_record'):
                if preserve_explicit and key in ('site', 'site_evidence', 'res_types', 'site_record'):
                    continue
                if key in verified:
                    row[key] = verified[key]
        if eligible(row) or row.get('site_evidence') == 'cnb':
            rows.append(row)
    targets = {row['target'].casefold() for row in rows if row.get('site_evidence') != 'cnb'}
    for row in extra_rows:
        if row['target'].casefold() not in targets:
            rows.append(row)
            targets.add(row['target'].casefold())
    complete = bool(legacy_info.get('complete') and extra_info.get('complete'))
    res_rows = [row for row in rows if row.get('site_evidence') != 'cnb']
    cnb_rows = [row for row in rows if row.get('site_evidence') == 'cnb']
    has_unknown = (any(row.get('site_evidence') == 'unknown' for row in res_rows)
                   or legacy_info.get('diagnostics', {}).get('unknown_sites', 0) > 0
                   or extra_info.get('diagnostics', {}).get('unknown_sites', 0) > 0)
    # CNB is independent of rings, but is only a fallback after the whole
    # expanded candidate set has been checked, not just the mission catalogue.
    if res_rows:
        rows = res_rows
    elif criteria.cnb_fallback and complete and not has_unknown:
        rows = cnb_rows
    else:
        rows = []
    rows.sort(key=lambda row: (not row.get('_known_sources', False),
                              row.get('site_evidence') != 'res',
                              not (criteria.prefer_low and 'low' in row.get('res_types', [])),
                              row['distance'], row['target'].casefold(), row['source'].casefold()))
    info = dict(extra_info)
    info.update(mode='CNB' if rows and not res_rows else 'Missions + RES systems',
                complete=complete,
                errors=legacy_info.get('errors', []) + extra_info.get('errors', []),
                notes=legacy_info.get('notes', []) + extra_info.get('notes', []),
                scanned=legacy_info.get('scanned', 0) + extra_info.get('scanned', 0), hits=len(rows),
                confirmed_res=sum(row.get('site_evidence') == 'res' for row in rows),
                inferred_res=sum(row.get('site_evidence') == 'rings' for row in rows))
    info['diagnostics'] = dict(info.get('diagnostics', {}),
                               unknown_sites=sum(row.get('site_evidence') == 'unknown' for row in rows))
    info['timings'] = dict(total=legacy_info.get('timings', {}).get('total', 0)
                          + extra_info.get('timings', {}).get('total', 0))
    return info, rows


def candidate_systems(criteria, reference, stop=None, refresh=False, progress=None):
    """Complete bounded pagination; never trust the backend's capped count."""
    filters = {}
    if criteria.target_controller.strip():
        filters['controlling_minor_faction'] = {'value': [criteria.target_controller.strip()]}
    if criteria.power.strip():
        filters['controlling_power'] = {'value': [criteria.power.strip()]}
    if criteria.radius:
        filters['distance'] = {'max': criteria.radius}
    payload = dict(filters=filters, reference_system=reference, size=500,
                   sort=[{'distance': {'direction': 'asc'}}])

    def load():
        rows, seen = [], set()
        for page in range(100):
            if stop is not None and stop.is_set():
                raise pve._Cancelled()
            data = eng._http_json(eng.SPansh_BASE + '/systems/search', dict(payload, page=page),
                                  timeout=30, compressed=True)
            batch = data.get('results') if isinstance(data, dict) else None
            if not isinstance(batch, list):
                raise ValueError('Invalid RES system response; coverage unknown.')
            if not batch and not page and criteria.target_controller.strip():
                formal = pve._canonical_controller_name(criteria.target_controller.strip())
                if formal and formal != payload['filters']['controlling_minor_faction']['value'][0]:
                    payload['filters']['controlling_minor_faction'] = {'value': [formal]}
                    data = eng._http_json(eng.SPansh_BASE + '/systems/search', dict(payload, page=page),
                                          timeout=30, compressed=True)
                    batch = data.get('results') if isinstance(data, dict) else None
                    if not isinstance(batch, list):
                        raise ValueError('Invalid RES system response; coverage unknown.')
            added = 0
            for row in batch:
                if not isinstance(row, dict) or not isinstance(row.get('name'), str) or not row['name']:
                    raise ValueError('RES system name missing; coverage unknown.')
                key = row['name'].casefold()
                if key not in seen:
                    seen.add(key)
                    rows.append(row)
                    added += 1
            if progress:
                progress(f'RES 星系分页：{page + 1}；已读取 {len(rows)} 个星系')
            if len(batch) < 500:
                return rows
            if not added:
                raise ValueError('RES system pages repeated; coverage incomplete.')
        raise ValueError('RES system page limit reached; coverage incomplete.')

    import json
    key = 'res-systems-v1:' + json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return pve_cache.cached(key, load, 300, refresh)[0]


def search(criteria, *, resolver=eng.resolve_ref, stop=None, progress=None, refresh=False,
           ring_loader=None, systems_loader=None, dataset_loader=None):
    criteria.validate()
    started = time.monotonic()
    reporter = pve.ProgressReporter(progress)
    cancelled = lambda: stop is not None and stop.is_set()
    info = dict(reference=criteria.reference, radius=criteria.radius, complete=True, scanned=0,
                errors=[], mode='RES systems', notes=[
                    'RES 星系模式：不要求任务来源；有已知任务来源的优先，无记录显示无数据。',
                    '有环仅推定 RES；Low／普通／High／Haz 必须有明确地点记录。'],
                timings={}, dataset_cache=[], controller_cache=[], power_cache=[],
                confirmed_res=0, inferred_res=0, diagnostics=dict(unknown_sites=0))
    info['ring_free_targets'] = []
    if cancelled():
        info['complete'] = False
        return info, []
    reference, origin, _ = resolver(criteria.reference)
    if not all(math.isfinite(v) for v in origin):
        raise ValueError('Reference coordinates invalid.')
    info['reference'] = reference
    if cancelled():
        info['complete'] = False
        return info, []
    reporter.emit('查询符合条件的 RES 候选星系…', True)
    try:
        systems = (candidate_systems(criteria, reference, stop=stop, refresh=refresh, progress=reporter.emit)
                   if systems_loader is None else systems_loader(criteria, reference))
    except pve._Cancelled:
        info['complete'] = False
        return info, []
    info['candidates'] = len(systems)
    targets, seen = [], set()
    for index, system in enumerate(systems):
        if cancelled():
            info['complete'] = False
            break
        if not isinstance(system, dict) or not system.get('name'):
            raise ValueError('RES system name missing.')
        name = system['name']
        reporter.emit(f'Checking {index + 1}/{len(systems)}: {name}')
        if name.casefold() in seen:
            continue
        seen.add(name.casefold())
        coords = eng.result_coords('systems', system)
        if coords is None or not all(math.isfinite(v) for v in coords):
            info['complete'] = False
            info['errors'].append(name + ': System coordinates unknown.')
            continue
        distance = eng.dist3(origin, coords)
        if criteria.radius and distance > criteria.radius:
            continue
        if criteria.target_controller.strip():
            if 'controlling_minor_faction' not in system:
                info['complete'] = False
                info['errors'].append(name + ': Controlling faction unknown.')
                continue
            if not pve.equal(system['controlling_minor_faction'], criteria.target_controller):
                continue
        if criteria.power.strip():
            if 'controlling_power' not in system:
                info['complete'] = False
                info['errors'].append(name + ': Controlling Power unknown.')
                continue
            if not pve.equal(system['controlling_power'], criteria.power):
                continue
        targets.append((system, distance))
    # Supplementary catalogues never gate the Spansh candidate universe.
    sources, sites = {}, {}
    if targets and not cancelled():
        for url in (pve.PAIRS_URL, pve.SITES_URL):
            try:
                data = (pve.fetch_dataset(url, refresh=refresh) if dataset_loader is None else dataset_loader(url))
                if not isinstance(data, dict):
                    raise ValueError('Invalid supplementary catalogue.')
                if url == pve.PAIRS_URL:
                    for source, record in data.items():
                        target, _, _ = pve._pair_fields(source, record)
                        sources.setdefault(target.casefold(), []).append(source)
                else:
                    for target, record in data.items():
                        sites[target.casefold()] = pve._site_fields(record)[0]
                if dataset_loader is None:
                    info['dataset_cache'].append(pve.dataset_cache_info(url))
            except Exception as exc:
                info['errors'].append('EDTools supplementary data: ' + str(exc))
                info['complete'] = False
        reporter.emit('复核 RES 候选星系的星环…', True)
    if criteria.site_type != 'any':
        before = len(targets)
        targets = [(system, distance) for system, distance in targets
                   if (bool(sites.get(system['name'].casefold())) if criteria.site_type == 'confirmed'
                       else criteria.site_type in sites.get(system['name'].casefold(), []))]
        info['diagnostics']['site_type_rejected'] = before - len(targets)
    if cancelled():
        info['complete'] = False
        return info, []
    rings = {}
    if targets:
        names = [system['name'] for system, _ in targets]
        reporter.emit(f'查询目标星环距离：0/{math.ceil(len(names) / 8)}', True)
        try:
            rings = (pve_access.ring_distances(names, stop=stop, refresh=refresh, progress=reporter.emit)
                     if ring_loader is None else ring_loader(names))
        except Exception as exc:
            info['complete'] = False
            info['errors'].append('Spansh ring verification: ' + str(exc))
    rows = []
    for index, (system, distance) in enumerate(targets):
        if cancelled():
            info['complete'] = False
            break
        info['scanned'] += 1
        name = system['name']
        reporter.emit(f'Checking {index + 1}/{len(targets)}: {name}', index + 1 == len(targets))
        record = rings.get(name.casefold(), {})
        ring_ls = pve_access.arrival(record.get('distance'))
        has_rings = record.get('has_rings') is True or ring_ls is not None
        no_rings = record.get('seen') and not record.get('uncertain') and not has_rings
        if no_rings:
            info['ring_free_targets'].append(name)
            continue
        levels = sites.get(name.casefold(), [])
        if criteria.site_type in ('low', 'reg', 'high', 'haz') and criteria.site_type not in levels:
            continue
        if criteria.site_type == 'confirmed' and not levels:
            continue
        if not levels and not has_rings:
            info['diagnostics']['unknown_sites'] += 1
            info['complete'] = False
            continue
        if criteria.target_ring_max_ls is not None:
            if ring_ls is None:
                info['diagnostics']['unknown_sites'] += 1
                info['complete'] = False
                continue
            if ring_ls > criteria.target_ring_max_ls:
                continue
        known_sources = sorted(set(sources.get(name.casefold(), [])), key=str.casefold)
        kind = 'res' if levels else 'rings'
        labels = {'low': 'RES Low', 'reg': 'RES', 'high': 'RES High', 'haz': 'RES Haz'}
        site = ' / '.join(labels[level] for level in levels) if levels else 'RES（星环推定）'
        rows.append(dict(source='; '.join(known_sources) if known_sources else '无数据', target=name,
                         distance=distance, site=site, site_evidence=kind, res_types=levels,
                         target_controller=system.get('controlling_minor_faction', ''),
                         target_power=system.get('controlling_power', ''), target_updated=system.get('updated_at', ''),
                         target_ring_ls=ring_ls if ring_ls is not None else '', target_ring_body=record.get('body', ''),
                         site_record='EDTools: ' + ', '.join(levels) if levels else 'Spansh: rings found',
                         _known_sources=bool(known_sources), _source_names=known_sources))
    rows.sort(key=lambda row: (not row['_known_sources'], row['site_evidence'] != 'res',
                              not (criteria.prefer_low and 'low' in row['res_types']),
                              row['distance'], row['target'].casefold()))
    info['confirmed_res'] = sum(row['site_evidence'] == 'res' for row in rows)
    info['inferred_res'] = sum(row['site_evidence'] == 'rings' for row in rows)
    info['hits'] = len(rows)
    info['timings']['total'] = time.monotonic() - started
    return info, rows
