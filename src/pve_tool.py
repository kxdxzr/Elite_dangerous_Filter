"""Pirate massacre candidates, not a live mission-board API.

EDTools supplies source/target pairs and explicit RES/CNB records. Spansh
supplies current minor-faction/control data when additional filters need it.
Rings imply a candidate RES by user preference, not a confirmed/Low RES.
"""
import math
import json
import re
import urllib.parse
import urllib.request
import urllib.error
import time
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from dataclasses import dataclass, replace
from html.parser import HTMLParser
from html import unescape

import filter_engine as eng
import pve_cache
import pve_access

# Explicit resource avoids Apache MultiViews negotiating pve.json vs pve.php.
BASE = 'https://edtools.cc/pve.php'
GLOBAL_RADIUS = 1_000_000_000  # Covers the galaxy; local radius=0 has NO distance filter.
PAIRS_URL = 'https://edtools.cc/pve.json'
SITES_URL = 'https://edtools.cc/res.json'
HEADERS = ['Distance', 'Source System', 'L-Pad', 'M-pad', 'P-pad',
           'Fed', 'Imp', 'All', 'Ind', 'Target/Sources', 'RES/rings']
NOTE = ('Candidates, not guaranteed live missions. EDTools pairs/site records may be stale; '
        'Spansh non-Anarchy faction counts estimate potential issuers, not actual mission availability. '
        'Verify BGS state, reputation and missions in game. Rings are treated as inferred RES by user preference; missing data remains Unknown.')


class _Cancelled(Exception):
    pass


class PageDownloadError(OSError):
    def __init__(self, code, url):
        self.code, self.url = code, url
        super().__init__(f'EDTools HTTP {code}: {url}. Open this page in a browser and import the saved HTML if the server remains unavailable.')


@dataclass(frozen=True)
class Criteria:
    reference: str = 'Sol'
    radius: float = 50
    min_factions: int = 0
    min_federation: int = 0
    min_empire: int = 0
    source_faction: str = ''
    source_controller: str = ''
    target_controller: str = ''
    power: str = ''
    power_scope: str = 'source'
    prefer_low: bool = True
    cnb_fallback: bool = True
    source_pad: str = ''
    source_station_max_ls: float | None = None
    target_ring_max_ls: float | None = None
    search_mode: str = 'missions'
    site_type: str = 'any'

    def validate(self):
        if self.search_mode not in ('missions', 'res_systems', 'expanded'):
            raise ValueError('Unknown PvE search mode.')
        if self.site_type not in ('any', 'confirmed', 'low', 'reg', 'high', 'haz'):
            raise ValueError('Unknown RES site type.')
        if not isinstance(self.reference, str) or not self.reference.strip():
            raise ValueError('Enter a reference system (also used to sort unlimited searches).')
        if isinstance(self.radius, bool) or not isinstance(self.radius, (int, float)) or not math.isfinite(self.radius) or self.radius < 0:
            raise ValueError('Radius must be finite and >= 0; 0 means unlimited.')
        for value in (self.min_factions, self.min_federation, self.min_empire):
            if type(value) is not int or not 0 <= value <= 8:
                raise ValueError('Faction minima must be integers from 0 to 8.')
        if self.power_scope not in ('source', 'target', 'both'):
            raise ValueError('Power scope must be source, target or both.')
        for value in (self.source_faction, self.source_controller, self.target_controller, self.power):
            if not isinstance(value, str):
                raise ValueError('Faction/Power filters must be strings.')
        if type(self.prefer_low) is not bool or type(self.cnb_fallback) is not bool:
            raise ValueError('Site preferences must be booleans.')
        if self.source_pad not in ('', 'S', 'M', 'L'):
            raise ValueError('Source landing pad must be S, M, L or unrestricted.')
        for value in (self.source_station_max_ls, self.target_ring_max_ls):
            if value is not None and (type(value) not in (int, float) or not math.isfinite(value) or value < 0):
                raise ValueError('Station/ring distance must be finite and >= 0; leave blank for unrestricted.')
        return self


class PveTable(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.active = False
        self.found = False
        self.rows, self.header = [], []
        self.row, self.cell = None, None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'table' and attrs.get('id') == 'sys_tbl':
            self.active = self.found = True
        if not self.active:
            return
        if tag == 'tr':
            self.row = []
        elif tag in ('th', 'td'):
            self.cell = {'text': [], 'names': [], 'heading': tag == 'th'}
        elif self.cell is not None and 'data-clipboard-text' in attrs:
            self.cell['names'].append(attrs['data-clipboard-text'])

    def handle_data(self, data):
        if self.active and self.cell is not None:
            self.cell['text'].append(data)

    def handle_endtag(self, tag):
        if not self.active:
            return
        if tag in ('th', 'td') and self.cell is not None:
            if self.row is None:
                raise ValueError('PvE cell outside a table row.')
            self.cell['text'] = ''.join(self.cell['text']).strip()
            self.row.append(self.cell)
            self.cell = None
        elif tag == 'tr' and self.row is not None:
            if self.row and self.row[0]['heading']:
                self.header = [c['text'] for c in self.row]
            elif self.row:
                self.rows.append(self.row)
            self.row = None
        elif tag == 'table':
            self.active = False


def parse_page(html):
    parser = PveTable()
    parser.feed(html)
    if not parser.found or parser.header != HEADERS or parser.active or parser.cell is not None or parser.row is not None:
        raise ValueError('EDTools PvE table missing or schema changed; cannot treat this as no matches.')
    declared = re.search(r'rows:\s*((?:\d{1,3}(?:,\d{3})+|\d+))(?![\d,])', html)
    if not declared or int(declared.group(1).replace(',', '')) != len(parser.rows):
        raise ValueError('Missing/mismatched page row count; truncated data cannot confirm no RES matches.')
    coverage = re.search(r'Systems within ([\d.,eE+\-]+) ly from ([^<]+):\s*</', html)
    if not coverage:
        raise ValueError('Missing reference/radius metadata; page coverage cannot be verified.')
    radius = float(coverage.group(1).replace(',', ''))
    if not math.isfinite(radius) or radius < 0:
        raise ValueError('Invalid page radius.')
    rows = []
    for cells in parser.rows:
        if len(cells) != len(HEADERS):
            raise ValueError('Unexpected PvE row width; partial rows are not silently skipped.')
        source = (cells[1]['names'] or [cells[1]['text']])[0].strip()
        target = (cells[9]['names'] or [cells[9]['text'].split(' / ')[0]])[0].strip()
        distance = float(cells[0]['text'].replace(',', ''))
        counts = [int(cells[i]['text'].replace(',', '') or '0') for i in (5, 6, 7, 8)]
        if not source or not target or not math.isfinite(distance) or distance < 0 or min(counts) < 0:
            raise ValueError('Invalid PvE row.')
        tokens = set(re.split(r'[,;/\s]+', cells[10]['text'].casefold()))
        ring_match = re.fullmatch(r'(\d+)\s+rings?', cells[10]['text'].strip(), re.I)
        rings = int(ring_match.group(1)) if ring_match else (0 if cells[10]['text'].strip().casefold() == 'no rings' else None)
        sites = tokens & {'haz', 'high', 'reg', 'low', 'res'}
        rows.append(dict(source=source, target=target, distance=distance,
                         federation=counts[0], empire=counts[1], factions=sum(counts),
                         res_types=sorted(sites), cnb='cnb' in tokens,
                          site_record=cells[10]['text'], ring_count=rings, count_source='EDTools',
                         source_controller='', target_controller='', source_power='', target_power='',
                         source_updated='', target_updated=''))
    return {'reference': unescape(coverage.group(2)).strip(), 'radius': radius, 'rows': rows}


def page_url(criteria, reference=None):
    criteria.validate()
    return BASE + '?' + urllib.parse.urlencode(dict(
        s=reference or criteria.reference.strip(), md=GLOBAL_RADIUS if criteria.radius == 0 else max(30, criteria.radius)))


def fetch_page(criteria, reference, refresh=False):
    if criteria.radius == 0 or criteria.radius > 250:
        with ThreadPoolExecutor(max_workers=2) as pool:
            if refresh:
                pairs = pool.submit(fetch_dataset, PAIRS_URL, True)
                sites = pool.submit(fetch_dataset, SITES_URL, True)
            else:
                pairs = pool.submit(fetch_dataset, PAIRS_URL)
                sites = pool.submit(fetch_dataset, SITES_URL)
            page = dataset_page(pairs.result(), sites.result(), reference, eng.get_system_coords(reference))
        page['cache'] = [dataset_cache_info(url) for url in (PAIRS_URL, SITES_URL)]
        return page
    url = page_url(criteria, reference)
    parsed, metadata = pve_cache.cached('page:' + url, lambda: _download_page(url), 3600, refresh)
    return dict(parsed, cache=[dict(metadata, url=url)])


def _download_page(url):
    request = urllib.request.Request(url, headers={
        'User-Agent': 'EliteDangerousFilter/next-release', 'Accept': 'text/html'})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            body = response.read(64 * 1024 * 1024 + 1)
    except urllib.error.HTTPError as exc:
        raise PageDownloadError(exc.code, request.full_url) from exc
    if len(body) > 64 * 1024 * 1024:
        raise ValueError('PvE page exceeds 64 MiB; coverage is unverified, not an empty result.')
    return parse_page(body.decode('utf-8-sig'))


_dataset_metadata = {}


def dataset_cache_info(url):
    return dict(_dataset_metadata.get(url, {}), url=url)


def fetch_dataset(url, refresh=False):
    value, metadata = pve_cache.cached('dataset:' + url, lambda: _download_dataset(url), 3600, refresh)
    _dataset_metadata[url] = metadata
    return value


def _download_dataset(url):
    request = urllib.request.Request(url, headers={
        'User-Agent': 'EliteDangerousFilter/next-release', 'Accept': 'application/json'})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            body = response.read(64 * 1024 * 1024 + 1)
    except urllib.error.HTTPError as exc:
        raise PageDownloadError(exc.code, request.full_url) from exc
    if len(body) > 64 * 1024 * 1024:
        raise ValueError('EDTools JSON exceeds 64 MiB; dataset completeness is unverified.')
    data = json.loads(body.decode('utf-8-sig'))
    if not isinstance(data, dict) or not data:
        raise ValueError('EDTools catalogue missing or invalid; not cached.')
    for name, record in data.items():
        if url == PAIRS_URL:
            _pair_fields(name, record)
        elif url == SITES_URL:
            if not isinstance(name, str) or not name.strip():
                raise ValueError('Invalid site name; not cached.')
            _site_fields(record)
    return data


def _pair_fields(source, record):
    if not isinstance(source, str) or not source.strip() or not isinstance(record, dict):
        raise ValueError('Invalid source catalogue record.')
    target = record.get('target')
    if not isinstance(target, str) or not target.strip():
        raise ValueError('Missing target in source catalogue.')
    try:
        xyz = tuple(float(record[key]) for key in ('x', 'y', 'z'))
    except (TypeError, ValueError, KeyError) as exc:
        raise ValueError('Missing/invalid source coordinates; cannot verify coverage.') from exc
    if not all(math.isfinite(v) for v in xyz):
        raise ValueError('Non-finite source coordinates.')
    counts = [record.get(key, 0) for key in ('Federation', 'Empire', 'Alliance', 'Independent')]
    if any(type(value) is not int or value < 0 for value in counts):
        raise ValueError('Invalid source faction count.')
    return target, xyz, counts


def _site_fields(known):
    if not isinstance(known, dict) or any(not isinstance(known.get(key), str) for key in ('haz', 'high', 'reg', 'low')):
        raise ValueError('Invalid RES record; cannot verify site availability.')
    if type(known.get('beac')) is not int or known['beac'] not in (0, 1):
        raise ValueError('Invalid CNB record.')
    levels = [key for key in ('haz', 'high', 'reg', 'low') if known[key].strip()]
    cnb = known['beac'] == 1
    return levels, cnb, [f'{key}: {known[key]}' for key in levels] + (['CNB'] if cnb else [])


def dataset_page(pairs, sites, reference, coordinates):
    """Join explicit site records to the full public source/target catalogue.

    Ring count t_r is an inferred RES, never a confirmed Low. Infinite coverage
    means all records in this catalogue, not all actual systems in the galaxy.
    """
    if not isinstance(pairs, dict) or not pairs or not isinstance(sites, dict) or not sites:
        raise ValueError('EDTools pair/site catalogue missing or invalid.')
    coordinates = tuple(float(value) for value in coordinates)
    if len(coordinates) != 3 or not all(math.isfinite(v) for v in coordinates):
        raise ValueError('Reference coordinates invalid.')
    sites_by_name = {name.casefold(): record for name, record in sites.items()}
    rows = []
    for source, record in pairs.items():
        target, xyz, counts = _pair_fields(source, record)
        known = sites_by_name.get(target.casefold())
        levels, cnb, evidence = [], False, []
        if known is not None:
            levels, cnb, evidence = _site_fields(known)
        rows.append(dict(source=source, target=target, distance=eng.dist3(xyz, coordinates),
                         federation=counts[0], empire=counts[1], factions=sum(counts),
                          res_types=levels, cnb=cnb,
                          ring_count=record.get('t_r') if type(record.get('t_r')) is int and record['t_r'] >= 0 else None,
                          site_record='; '.join(evidence) or (str(record['t_r']) + ' rings' if type(record.get('t_r')) is int and record['t_r'] >= 0 else 'Unknown'),
                         count_source='EDTools JSON', source_controller='', target_controller='',
                         source_power='', target_power='', source_updated='', target_updated=''))
    return dict(reference=reference, radius=math.inf, rows=rows,
                dataset_source='EDTools pve.json + res.json')


def system_details(name, refresh=False):
    return pve_cache.cached('system-access-v3:' + name.casefold(), lambda: _system_details(name), 300, refresh)[0]


def _system_details(name):
    data = eng._http_json(eng.SPansh_BASE + '/systems/search', {
        'filters': {'name': {'value': name}}, 'size': 100, 'page': 0}, compressed=True)
    for row in data.get('results') or []:
        if str(row.get('name', '')).casefold() == name.casefold():
            return _detail_fields(row)
    raise ValueError(f'No exact Spansh system record for {name!r}; control data is unknown.')


def _detail_fields(row):
    result = {key: row[key] for key in ('name', 'controlling_minor_faction', 'controlling_power',
                                      'minor_faction_presences', 'updated_at') if key in row}
    if isinstance(row.get('stations'), list):
        result['station_schema'] = 2
        result['stations'] = [{key: station[key] for key in ('name', 'real_name', 'type', 'services', 'distance_to_arrival',
                               'has_large_pad', 'small_pads', 'medium_pads', 'large_pads') if key in station}
                              if isinstance(station, dict) else station for station in row['stations']]
    return result


_controller_metadata = {}
_power_metadata = {}


def _canonical_controller_name(name):
    # Spansh's controller filter is case-sensitive. Only repair casing of an
    # exact full name, never accept fuzzy suggestions or rewrite Criteria/UI.
    import faction_options
    return next((value for value in faction_options._fetch(name)
                 if equal(value, name)), None)


def controller_systems(name, refresh=False, stop=None):
    """Complete paginated controller query; count may be capped, never used to stop."""
    def load():
        systems, seen = {}, set()
        requested = name.strip()
        def fetch_rows(page):
            if stop is not None and stop.is_set():
                raise _Cancelled()
            data = eng._http_json(eng.SPansh_BASE + '/systems/search', {
                'filters': {'controlling_minor_faction': {'value': [requested]}}, 'size': 500, 'page': page}, timeout=30)
            rows = data.get('results') if isinstance(data, dict) else None
            if not isinstance(rows, list):
                raise ValueError('Invalid controller-system response; coverage is unknown.')
            return rows
        for page in range(100):
            if stop is not None and stop.is_set():
                raise _Cancelled()
            rows = fetch_rows(page)
            if not rows and page == 0:
                if stop is not None and stop.is_set():
                    raise _Cancelled()
                formal = _canonical_controller_name(requested)
                if formal and formal != requested:
                    requested = formal
                    rows = fetch_rows(page)
            if not rows:
                return systems
            added = 0
            for row in rows:
                if not isinstance(row, dict) or not row.get('name') or 'controlling_minor_faction' not in row:
                    raise ValueError('Controller-system fields missing; cannot prefilter.')
                key = row['name'].casefold()
                if key not in seen:
                    seen.add(key)
                    added += 1
                if equal(row['controlling_minor_faction'], name):
                    systems[key] = _detail_fields(row)
            if not added:
                raise ValueError('Controller-system pages repeated; coverage incomplete.')
            if len(rows) < 500:
                return systems
        raise ValueError('Controller-system page limit reached; coverage incomplete.')
    value, metadata = pve_cache.cached('controller:' + name.casefold(), load, 300, refresh)
    _controller_metadata[name.casefold()] = dict(metadata, faction=name)
    return value


def power_systems(name, refresh=False, stop=None, progress=None, workers=4):
    """Fetch controlling Power records in pages, never per catalogue system.

    The associated `power` list is deliberately not used. Only a complete,
    validated result is persisted; cancellation and repeated pages fail closed.
    """
    from powerplay_tool import normalize_power
    requested = normalize_power(name)
    reporter = ProgressReporter(progress)
    def load():
        systems, seen = {}, set()
        worker_count = max(1, min(4, workers))
        def fetch(page):
            if stop is not None and stop.is_set():
                raise _Cancelled()
            return eng._http_json(eng.SPansh_BASE + '/systems/search', {
                'filters': {'controlling_power': {'value': [requested]}},
                'size': 500, 'page': page}, timeout=30, compressed=True)
        # Read pages in order, with at most four in flight. A short/empty page
        # ends coverage, not the potentially capped `count`. Speculative pages
        # beyond that boundary are ignored; no unbounded task submission.
        with ThreadPoolExecutor(max_workers=worker_count) as pool:
            for start in range(0, 100, worker_count):
                futures = []
                try:
                    for page in range(start, min(start + worker_count, 100)):
                        if stop is not None and stop.is_set():
                            raise _Cancelled()
                        futures.append((page, pool.submit(fetch, page)))
                    for page, future in futures:
                        if stop is not None and stop.is_set():
                            raise _Cancelled()
                        data = future.result()
                        rows = data.get('results') if isinstance(data, dict) else None
                        if not isinstance(rows, list):
                            raise ValueError('Invalid controlling-Power response; coverage is unknown.')
                        if not rows:
                            return systems
                        added = 0
                        for row in rows:
                            if not isinstance(row, dict) or not isinstance(row.get('name'), str) or not row['name'] or 'controlling_power' not in row:
                                raise ValueError('Controlling-Power fields missing; cannot prefilter.')
                            key = row['name'].casefold()
                            if key not in seen:
                                seen.add(key)
                                added += 1
                            if equal(row['controlling_power'], requested):
                                systems[key] = _detail_fields(row)
                        if not added:
                            raise ValueError('Controlling-Power pages repeated; coverage incomplete.')
                        reporter.emit(f'控制 Power 分页：{requested}；第 {page + 1} 页；已读取 {len(seen)} 个星系', page == 0)
                        if len(rows) < 500:
                            return systems
                finally:
                    for _, future in futures:
                        future.cancel()
        raise ValueError('Controlling-Power page limit reached; coverage incomplete.')
    value, metadata = pve_cache.cached('controlling-power:' + requested.casefold(), load, 300, refresh)
    _power_metadata[name.casefold()] = dict(metadata, power=requested)
    return value


def site_kind(row):
    rings = row.get('ring_count')
    # Confirmed absence of rings rules out RES, even in stale site records.
    # CNB does not depend on rings and remains independently eligible.
    if type(rings) is int and rings == 0:
        return 'cnb' if row.get('cnb') else 'none'
    if row.get('res_types'):
        return 'res'
    if type(rings) is int and rings > 0:
        return 'rings'
    if row.get('cnb'):
        return 'cnb'
    return 'unknown' if rings is None else 'none'


class ProgressReporter:
    def __init__(self, callback, interval=0.15):
        self.callback, self.interval, self.last = callback, interval, 0

    def emit(self, text, force=False):
        now = time.monotonic()
        if self.callback and (force or now - self.last >= self.interval):
            self.last = now
            self.callback(text)


def eligible_factions(system):
    factions = system.get('minor_faction_presences')
    if not isinstance(factions, list):
        raise ValueError('Minor-faction data is missing; availability cannot be inferred.')
    names, eligible = set(), []
    for faction in factions:
        if not isinstance(faction, dict) or not faction.get('name'):
            raise ValueError('Incomplete minor-faction record.')
        key = faction['name'].casefold()
        if key in names:
            continue
        names.add(key)
        if not faction.get('government') or not faction.get('allegiance'):
            raise ValueError('Missing faction government/allegiance; counts are unknown.')
        if faction['government'].casefold() != 'anarchy':
            eligible.append(faction)
    return eligible


def equal(actual, requested):
    return str(actual or '').strip().casefold() == requested.strip().casefold()


def search(criteria, *, page=None, page_loader=fetch_page, details_loader=system_details,
            resolver=eng.resolve_ref, stop=None, progress=None, refresh=False, workers=None,
            controller_loader=None, power_loader=None, ring_loader=None,
            systems_loader=None, dataset_loader=None, include_cnb_candidates=False):
    criteria.validate()  # Invalid inputs cause zero network requests.
    if criteria.search_mode == 'expanded':
        from res_systems import merge_results, annotate_source_controllers
        try:
            legacy_info, legacy_rows = search(replace(criteria, search_mode='missions'),
                page=page, page_loader=page_loader, details_loader=details_loader, resolver=resolver,
                stop=stop, progress=progress, refresh=refresh, workers=workers,
                controller_loader=controller_loader, power_loader=power_loader, ring_loader=ring_loader,
                include_cnb_candidates=criteria.cnb_fallback)
        except Exception as exc:
            legacy_info, legacy_rows = dict(complete=False, errors=[str(exc)], notes=[]), []
        extra_info, extra_rows = search(replace(criteria, search_mode='res_systems'), resolver=resolver,
            stop=stop, progress=progress, refresh=refresh, ring_loader=ring_loader,
            systems_loader=systems_loader, dataset_loader=dataset_loader)
        info, rows = merge_results(criteria, legacy_info, legacy_rows, extra_info, extra_rows)
        annotation_started = time.monotonic()
        annotate_source_controllers(rows, info, details_loader=details_loader, stop=stop,
                                    refresh=refresh, progress=progress)
        info['timings']['total'] += time.monotonic() - annotation_started
        return info, rows
    if criteria.search_mode == 'res_systems':
        from res_systems import search as search_res_systems
        return search_res_systems(criteria, resolver=resolver, stop=stop, progress=progress,
                                  refresh=refresh, ring_loader=ring_loader,
                                  systems_loader=systems_loader, dataset_loader=dataset_loader)
    started = time.monotonic()
    reporter = ProgressReporter(progress)
    timings = {}
    worker_count = max(1, min(4, workers if workers is not None else (4 if details_loader is system_details else 1)))
    if stop is not None and stop.is_set():
        return {'complete': False, 'scanned': 0, 'errors': [], 'mode': 'stopped', 'notes': [NOTE]}, []
    if page is not None and equal(page['reference'], criteria.reference):
        # Imported distances already refer to this exact name; no coordinate lookup
        # is needed. Site-only imported searches can therefore work offline.
        reference = page['reference']
    else:
        reporter.emit('解析参考星系…', True)
        reference, _, _ = resolver(criteria.reference)
    if stop is not None and stop.is_set():
        return {'complete': False, 'scanned': 0, 'errors': [], 'mode': 'stopped', 'notes': [NOTE]}, []
    timings['resolve'] = time.monotonic() - started
    stage = time.monotonic()
    reporter.emit('获取配对与地点数据（优先有效缓存）…', True)
    if page is None:
        page = page_loader(criteria, reference, refresh=refresh) if page_loader is fetch_page else page_loader(criteria, reference)
    timings['dataset'] = time.monotonic() - stage
    if not equal(page['reference'], reference):
        raise ValueError('Imported page reference differs from the selected reference system.')
    required = GLOBAL_RADIUS if criteria.radius == 0 else criteria.radius
    if page['radius'] < required:
        raise ValueError('PvE page covers a smaller radius. Import/query a larger page; do not infer no RES matches.')
    info = dict(reference=reference, radius=criteria.radius, complete=True, scanned=0,
                errors=[], mode='RES', notes=[NOTE], candidates=len(page['rows']),
                timings=timings, dataset_cache=page.get('cache', []), controller_cache=[], power_cache=[],
                diagnostics=dict(catalogue_pairs=len(page['rows']), radius_rejected=0, no_site=0,
                                 controller_rejected=0, power_rejected=0, other_filters_rejected=0, unknown_sites=0))
    cache, seen, res, cnb, unknown = {}, set(), [], [], []
    diagnostics = info['diagnostics']
    station_filter = bool(criteria.source_pad or criteria.source_station_max_ls is not None)
    needs_source = bool(station_filter or criteria.source_faction or criteria.source_controller or
                        criteria.min_factions or criteria.min_federation or criteria.min_empire or
                        criteria.power and criteria.power_scope in ('source', 'both'))
    needs_target = bool(criteria.target_controller or criteria.power and criteria.power_scope in ('target', 'both'))
    stage = time.monotonic()
    controller_maps = {}
    power_maps = {}
    requested_power = criteria.power
    bulk = controller_loader or (controller_systems if details_loader is system_details else None)
    if bulk:
        for side, faction in (('source', criteria.source_controller), ('target', criteria.target_controller)):
            if faction:
                if stop is not None and stop.is_set():
                    info['complete'] = False
                    break
                reporter.emit('按控制派系批量预筛选：' + faction, True)
                try:
                    mapping = bulk(faction, refresh=refresh, stop=stop) if bulk is controller_systems else bulk(faction)
                except _Cancelled:
                    info['complete'] = False
                    break
                if bulk is controller_systems:
                    info['controller_cache'].append(_controller_metadata[faction.casefold()].copy())
                controller_maps[side] = mapping
                cache.update(mapping)
                diagnostics[side + '_controller_systems'] = len(mapping)
                diagnostics[side + '_catalogue_overlap'] = sum(row[side].casefold() in mapping for row in page['rows'])
                if side == 'source':
                    covered = {row['source'].casefold() for row in page['rows']}
                    diagnostics['controlled_sources_not_in_catalogue'] = sum(key not in covered for key in mapping)
    power_bulk = power_loader or (power_systems if details_loader is system_details else None)
    if criteria.power and power_bulk and (stop is None or not stop.is_set()):
        reporter.emit('按控制 Power 批量预筛选：' + criteria.power, True)
        try:
            mapping = (power_bulk(criteria.power, refresh=refresh, stop=stop, progress=reporter.emit)
                       if power_bulk is power_systems else power_bulk(criteria.power))
        except _Cancelled:
            info['complete'] = False
        else:
            if power_bulk is power_systems:
                metadata = _power_metadata[criteria.power.casefold()].copy()
                info['power_cache'].append(metadata)
                requested_power = metadata['power']
            cache.update(mapping)
            diagnostics['power_controlled_systems'] = len(mapping)
            for side in ('source', 'target'):
                if criteria.power_scope in (side, 'both'):
                    power_maps[side] = mapping
                    diagnostics[side + '_power_catalogue_overlap'] = sum(row[side].casefold() in mapping for row in page['rows'])
    candidates = []
    for original in page['rows']:
        key = (original['source'].casefold(), original['target'].casefold())
        if key in seen:
            continue
        seen.add(key)
        if criteria.radius > 0 and original['distance'] > criteria.radius:
            diagnostics['radius_rejected'] += 1
            continue
        if any(original[side].casefold() not in mapping for side, mapping in controller_maps.items()):
            diagnostics['controller_rejected'] += 1
            continue
        if any(original[side].casefold() not in mapping for side, mapping in power_maps.items()):
            diagnostics['power_rejected'] += 1
            continue
        kind = site_kind(original)
        if kind == 'none' or kind == 'cnb' and not criteria.cnb_fallback:
            diagnostics['no_site'] += 1
            continue
        candidates.append(original)
    timings['prefilter'] = time.monotonic() - stage
    diagnostics['details_candidates'] = len(candidates)
    if station_filter:
        # Old cached bulk records contain only BGS fields. Upgrade only matching
        # sources, never mistake omitted station data for an empty station list.
        for row in candidates:
            key = row['source'].casefold()
            if key in cache and ('stations' not in cache[key] or details_loader is system_details and cache[key].get('station_schema') != 2):
                del cache[key]

    # Bounded in-flight requests. Workers never access Tk; failures are per-query
    # only, never written into the persistent success cache.
    stage = time.monotonic()
    if worker_count > 1 and (needs_source or needs_target):
        names = dict.fromkeys(row[side] for row in candidates
                             for side, needed in (('source', needs_source), ('target', needs_target))
                             if needed and row[side].casefold() not in cache)
        iterator = iter(names)
        def load(name):
            return system_details(name, refresh=refresh) if details_loader is system_details else details_loader(name)
        reporter.emit(f'查询派系详情：{len(names)} 个星系，最多 {worker_count} 并发…', True)
        pool = ThreadPoolExecutor(max_workers=worker_count)
        pending = {}
        completed = 0
        try:
            def submit_next():
                name = next(iterator, None)
                if name is not None:
                    pending[pool.submit(load, name)] = name
            for _ in range(worker_count):
                if stop is None or not stop.is_set():
                    submit_next()
            while pending:
                if stop is not None and stop.is_set():
                    info['complete'] = False
                    break
                ready, _ = wait(pending, timeout=0.1, return_when=FIRST_COMPLETED)
                for future in ready:
                    name = pending.pop(future)
                    try:
                        cache[name.casefold()] = future.result()
                    except Exception as exc:
                        cache[name.casefold()] = exc
                    completed += 1
                    reporter.emit(f'查询派系详情：{completed}/{len(names)} 个星系')
                    if stop is None or not stop.is_set():
                        submit_next()
        finally:
            for future in pending:
                future.cancel()
            pool.shutdown(wait=True, cancel_futures=True)
        info['detail_requests'] = completed
    timings['details'] = time.monotonic() - stage

    def details(name):
        if stop is not None and stop.is_set():
            raise _Cancelled()
        key = name.casefold()
        if key not in cache:
            try:
                cache[key] = system_details(name, refresh=refresh) if details_loader is system_details else details_loader(name)
            except Exception as exc:
                cache[key] = exc
        if isinstance(cache[key], Exception):
            raise cache[key]
        return cache[key]

    def rejected(reason):
        diagnostics['other_filters_rejected'] += 1
        diagnostics[reason] = diagnostics.get(reason, 0) + 1

    stage = time.monotonic()
    reporter.emit(f'本地复核：{len(candidates)} 条候选…', True)
    for original in candidates:
        if stop is not None and stop.is_set():
            info['complete'] = False
            info['notes'].append('Stopped; CNB fallback suppressed because RES absence is unconfirmed.')
            break
        info['scanned'] += 1
        reporter.emit(f"Checking {info['scanned']}/{len(candidates)}: {original['source']} → {original['target']}")
        if stop is not None and stop.is_set():
            info['complete'] = False
            break
        row = dict(original)
        if criteria.radius > 0 and row['distance'] > criteria.radius:
            continue
        try:
            if needs_source:
                source = details(row['source'])
                row.update(source_controller=source.get('controlling_minor_faction', ''),
                           source_power=source.get('controlling_power', ''), source_updated=source.get('updated_at', ''))
                if criteria.source_faction:
                    presences = source.get('minor_faction_presences')
                    if not isinstance(presences, list):
                        raise ValueError('Source faction presence data missing.')
                    if not any(equal(f.get('name'), criteria.source_faction) for f in presences if isinstance(f, dict)):
                        rejected('source_presence_rejected')
                        continue
                if criteria.source_controller:
                    if not row['source_controller']:
                        raise ValueError('Source controlling faction unknown.')
                    if not equal(row['source_controller'], criteria.source_controller):
                        rejected('source_controller_rejected')
                        continue
                if criteria.min_factions or criteria.min_federation or criteria.min_empire:
                    eligible = eligible_factions(source)
                    row.update(factions=len(eligible),
                               federation=sum(equal(f['allegiance'], 'Federation') for f in eligible),
                               empire=sum(equal(f['allegiance'], 'Empire') for f in eligible), count_source='Spansh estimate')
                if criteria.power and criteria.power_scope in ('source', 'both'):
                    if 'controlling_power' not in source:
                        raise ValueError('Source controlling Power data missing.')
                    if not equal(row['source_power'], requested_power):
                        rejected('source_power_rejected')
                        continue
                if station_filter:
                    station = pve_access.station_match(source, criteria.source_pad, criteria.source_station_max_ls)
                    if station is None:
                        rejected('source_station_rejected')
                        continue
                    row.update(station)
            if needs_target:
                target = details(row['target'])
                row.update(target_controller=target.get('controlling_minor_faction', ''),
                           target_power=target.get('controlling_power', ''), target_updated=target.get('updated_at', ''))
                if criteria.target_controller:
                    if not row['target_controller']:
                        raise ValueError('Target controlling faction unknown.')
                    if not equal(row['target_controller'], criteria.target_controller):
                        rejected('target_controller_rejected')
                        continue
                if criteria.power and criteria.power_scope in ('target', 'both'):
                    if 'controlling_power' not in target:
                        raise ValueError('Target controlling Power data missing.')
                    if not equal(row['target_power'], requested_power):
                        rejected('target_power_rejected')
                        continue
        except _Cancelled:
            info['complete'] = False
            break
        except Exception as exc:
            info['complete'] = False
            info['errors'].append(f"{row['source']} → {row['target']}: {exc}")
            continue
        if (row['factions'] < criteria.min_factions or row['federation'] < criteria.min_federation
                or row['empire'] < criteria.min_empire):
            rejected('faction_minima_rejected')
            continue
        kind = site_kind(row)
        row['site'] = ('RES Low' if 'low' in row['res_types'] else 'RES') if kind == 'res' else {
            'rings': 'RES（星环推定）', 'cnb': 'CNB', 'unknown': '情况未知'}[kind]
        row['site_evidence'] = kind
        (res if kind in ('res', 'rings') else cnb if kind == 'cnb' else unknown).append(row)
    if stop is not None and stop.is_set():
        info['complete'] = False
        info['notes'].append('Stopped; partial results only, no CNB fallback.')
    timings['scan'] = time.monotonic() - stage
    stage = time.monotonic()
    # Unknown EDTools sites are checked even without an arrival-distance limit.
    # Do not infer absence from failed requests, empty system coverage or bad data.
    if criteria.target_ring_max_ls is None and unknown and (stop is None or not stop.is_set()):
        reporter.emit('用 Spansh 复核未知目标星环…', True)
        try:
            ring_data = (pve_access.ring_distances([row['target'] for row in unknown], refresh=refresh,
                         stop=stop, progress=reporter.emit) if ring_loader is None else
                         ring_loader([row['target'] for row in unknown]))
        except Exception as exc:
            info['complete'] = False
            info['errors'].append('Spansh ring verification: ' + str(exc))
            ring_data = {}
        remaining = []
        for row in unknown:
            record = ring_data.get(row['target'].casefold(), {})
            distance = pve_access.arrival(record.get('distance'))
            if record.get('has_rings') is True or distance is not None:
                row.update(site='RES（星环推定）', site_evidence='rings',
                           target_ring_body=record.get('body', ''),
                           site_record=row.get('site_record', '') + '; Spansh: rings found')
                if distance is not None:
                    row['target_ring_ls'] = distance
                res.append(row)
            elif record.get('seen') and not record.get('uncertain'):
                rejected('target_no_rings')
            else:
                remaining.append(row)
        unknown = remaining
    if criteria.target_ring_max_ls is not None and stop is not None and stop.is_set():
        res, unknown, cnb = [], [], []
        info['complete'] = False
    if criteria.target_ring_max_ls is not None and (stop is None or not stop.is_set()):
        matched = res + unknown + cnb
        if matched:
            reporter.emit('查询目标星环距离…', True)
            try:
                ring_data = (pve_access.ring_distances([row['target'] for row in matched], refresh=refresh,
                             stop=stop, progress=reporter.emit) if ring_loader is None else
                             ring_loader([row['target'] for row in matched]))
            except InterruptedError:
                info['complete'] = False
                ring_data = {}
            # Network/schema errors propagate; they must not produce an empty
            # "complete" query or incorrectly permit CNB fallback.
            res, unknown, cnb = [], [], []
            for row in matched:
                record = ring_data.get(row['target'].casefold(), {})
                distance = pve_access.arrival(record.get('distance'))
                if distance is not None and distance <= criteria.target_ring_max_ls:
                    row.update(target_ring_ls=distance, target_ring_body=record.get('body', ''))
                    if row['site_evidence'] not in ('res', 'rings'):
                        row.update(site='RES（星环推定）', site_evidence='rings')
                    res.append(row)
                elif not record.get('seen') or record.get('uncertain'):
                    info['complete'] = False
                    info['errors'].append(row['target'] + ': Ring arrival distance unknown; cannot confirm this filter.')
                else:
                    rejected('target_ring_rejected')
    timings['rings'] = time.monotonic() - stage
    if stop is not None and stop.is_set():
        info['complete'] = False
    result = res + unknown
    if unknown:
        info['mode'] = 'RES + Unknown' if res else 'Unknown'
    if not res and not unknown and criteria.cnb_fallback and info['complete']:
        result, info['mode'] = cnb, 'CNB'
    elif not res and not info['complete']:
        info['notes'].append('Data incomplete; CNB fallback suppressed, no confirmed absence of RES matches.')
    if unknown:
        info['notes'].append('Unknown site data is shown, not treated as confirmed RES absence; CNB fallback suppressed if no RES matches.')
    if include_cnb_candidates:
        result = res + unknown + cnb
    diagnostics['unknown_sites'] = len(unknown)
    diagnostics['data_errors'] = len(info['errors'])
    info['notes'].append('Coverage/filter diagnostics: ' + json.dumps(diagnostics, ensure_ascii=False))
    info['confirmed_res'] = sum(row['site_evidence'] == 'res' for row in res)
    info['inferred_res'] = sum(row['site_evidence'] == 'rings' for row in res)
    timings['total'] = time.monotonic() - started
    result.sort(key=lambda r: (2 if r['site_evidence'] == 'unknown' else 0 if criteria.prefer_low and r['site'] == 'RES Low' else 1,
                               r['distance'], r['source'].casefold(), r['target'].casefold()))
    info['hits'] = len(result)
    reporter.emit(f"检索完成：{len(result)} 条结果；耗时 {timings['total']:.2f} 秒", True)
    return info, result
