"""Persistent station shortlist; inventory is refreshed only on explicit request."""
import copy
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import threading

import catalog_updates
import full_outfitting as tool
import outfitting_catalog as catalogue
from runtime_paths import data_file

NAME = 'full_outfitting_snapshot_v1.json'
COORDINATES = 'full_outfitting_coordinates_v1.json'
SCHEMA = 2
DISCOVERY_REFERENCE = 'Sol'
DISCOVERY_RADIUS = 20000
LOCK = threading.RLock()
MAX_BYTES = 128 * 1024 * 1024


def read():
    path = Path(data_file(NAME))
    if not path.exists():
        return None
    if path.stat().st_size > MAX_BYTES:
        raise ValueError('库存快照过大，请手动更新数据')
    data = json.loads(path.read_text(encoding='utf-8'))
    if (not isinstance(data, dict) or data.get('schema') not in (1, SCHEMA) or not data.get('complete')
            or not isinstance(data.get('rows'), list) or not isinstance(data.get('catalog'), dict)
            or not isinstance(data.get('scope'), dict) or not data.get('created_at')):
        raise ValueError('库存快照无效，请手动更新数据')
    scope = data['scope']
    validated_scope = tool.build_criteria(scope.get('reference', ''), scope.get('radius'))
    if (validated_scope.reference.casefold() != DISCOVERY_REFERENCE.casefold()
            or validated_scope.radius != DISCOVERY_RADIUS):
        raise ValueError('库存快照不是Sol周围20,000 ly采集范围，请手动更新数据')
    if not data['catalog'].get('items') or data['catalog'].get('issues'):
        raise ValueError('库存快照目录不完整，请手动更新数据')
    if data['schema'] != SCHEMA:
        # Reuse a valid fixed-scope v1 snapshot without re-querying inventory.
        # Upgrade in place, retaining the original inventory time and records.
        data['schema'] = SCHEMA
        catalog_updates.atomic_write(path, json.dumps(data, ensure_ascii=False, allow_nan=False).encode('utf-8'))
    return data


def position(values):
    return (tuple(values) if isinstance(values, (list, tuple)) and len(values) == 3
            and all(isinstance(v, (float, int)) and not isinstance(v, bool) and math.isfinite(v)
                    for v in values) else None)


def row_position(row):
    return position([row.get('system_' + axis) for axis in ('x', 'y', 'z')])


def distance_context(snapshot, criteria, stop=None, progress=None):
    """Fetch only missing system coordinates, never station stock or a catalogue."""
    if snapshot['scope']['reference'].strip().casefold() == criteria.reference.strip().casefold():
        return None, {}
    path = Path(data_file(COORDINATES))
    cached = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    if not isinstance(cached, dict):
        raise ValueError('星系坐标缓存无效')
    coords = {name: pos for name, values in cached.items() if (pos := position(values)) is not None}
    for row in snapshot['rows']:
        point = row_position(row)
        if point and row.get('system_name'):
            coords[row['system_name'].strip().casefold()] = point

    def resolve(name):
        catalogue.check_stop(stop)
        key = name.strip().casefold()
        if key not in coords:
            if progress:
                progress(f'仅查询星系坐标… {name}')
            response = tool.request_json('https://spansh.co.uk/api/systems/search', dict(
                filters={'name': {'value': name}}, size=10, page=0), stop=stop, progress=progress)
            match = next((row for row in response.get('results', [])
                          if str(row.get('name', '')).strip().casefold() == key), {})
            point = position([match.get(axis) for axis in ('x', 'y', 'z')])
            if point is None:
                raise ValueError(f'无法确认星系坐标: {name}；原库存名单不变')
            coords[key] = point
        return coords[key]

    reference = resolve(criteria.reference)
    for row in snapshot['rows']:
        if not row_position(row):
            if not row.get('system_name'):
                raise ValueError('缓存站点缺少星系名称，无法重算距离')
            resolve(row['system_name'])
    if {name: list(point) for name, point in coords.items()} != cached:
        catalog_updates.atomic_write(path, json.dumps(coords, ensure_ascii=False).encode('utf-8'))
    return reference, coords


def filter_snapshot(snapshot, criteria, want=50, max_pages=25, stop=None, progress=None,
                    reference_coords=None, system_coords=None):
    """No network calls, including metadata and identity lookups."""
    changed_reference = snapshot['scope']['reference'].strip().casefold() != criteria.reference.strip().casefold()
    if changed_reference and position(reference_coords) is None:
        raise ValueError('缺少新参考星系坐标，不能沿用旧距离')
    catalog = snapshot['catalog']
    result = dict(rows=[], diagnostics=[], identity_candidates=[], notes=list(snapshot.get('notes', [])),
                  scanned=0, total=len(snapshot['rows']), rejected=0, uncertain=0, incomplete=0,
                  condition_failures=0, stopped=False, complete=True, partial=False, errors=[], sources=[],
                  criteria=vars(criteria).copy(), search_limits=dict(want=want, max_pages=max_pages),
                  catalog_revision=catalog.get('release_version', catalogue.REVISION),
                  catalog_built_at=catalog.get('built_at', ''), catalog_size=len(catalog['items']),
                  identity_revision=catalog.get('identity_revision', ''),
                  catalog_sources=catalog.get('release_sources', []),
                  catalog_rules_version=catalog.get('release_engine', 'bundled'),
                  catalog_conflicts=catalog.get('conflicts', []),
                  catalog_shared_symbols=len(catalog.get('shared_symbols', [])),
                  catalog_special_size=sum(not catalogue.excluded_merc_spec(item)
                                           for item in catalog.get('special_items', [])) if criteria.special_equipment else 0,
                  snapshot_created_at=snapshot['created_at'], snapshot_scope=snapshot['scope'],
                  snapshot_update_pages=snapshot.get('max_pages'),
                  snapshot_scanned=snapshot.get('scanned', 0), snapshot_local=True)
    result['notes'].append('仅筛选已有站点名单，换星系只重算距离；扩大半径不代表发现新范围内全部站点。')
    candidates = []
    for raw in snapshot['rows']:
        distance = raw.get('distance')
        if changed_reference:
            point = row_position(raw) or (system_coords or {}).get(str(raw.get('system_name', '')).strip().casefold())
            if position(point) is None:
                raise ValueError('缓存站点缺少坐标，无法重算距离')
            distance = math.dist(reference_coords, point)
        if isinstance(distance, (int, float)) and not isinstance(distance, bool) and math.isfinite(distance):
            candidates.append((distance, raw))
    candidates.sort(key=lambda pair: pair[0])
    for distance, raw in candidates:
        if stop is not None and stop.is_set():
            result.update(stopped=True, complete=False, partial=True)
            break
        result['scanned'] += 1
        if not 0 <= distance <= criteria.radius:
            continue
        row = copy.deepcopy(raw)
        row['distance'] = distance
        evidence = tool.check_station(row, criteria, catalog)
        status = tool.review_status(evidence, criteria)
        evidence['review_status'] = status
        row['_full_outfitting'] = evidence
        if evidence['matched']:
            if len(result['rows']) < want:
                result['rows'].append(row)
        else:
            result['rejected'] += 1
            field = 'uncertain' if status == 'identity_pending' else 'incomplete' if status == 'incomplete' else 'condition_failures'
            result[field] += 1
            summary = {k: v for k, v in row.items() if k in ('name', 'system_name', 'type', 'distance', '_full_outfitting')}
            if len(result['diagnostics']) < 100:
                result['diagnostics'].append(summary)
            if status == 'identity_pending' and len(result['identity_candidates']) < 100:
                result['identity_candidates'].append(summary)
    if progress:
        progress('本地快照筛选完成', dict(done=result['scanned'], work_total=result['total'], stage='本地库存筛选'))
    return result


def search(criteria, want=50, max_pages=25, stop=None, progress=None, refresh=False):
    if type(want) is not int or want < 1 or type(max_pages) is not int or max_pages < 1:
        raise ValueError('结果数和页数必须大于零')
    with LOCK:
        snapshot = None if refresh else read()
        if snapshot is None:
            catalogue.check_stop(stop)
            # Load a fixed catalogue once; do not change it during subsequent
            # local filtering, even if another window installs an update.
            catalog = catalogue.prepare(catalogue.load(stop, progress, include_special=True))
            base = tool.build_criteria(DISCOVERY_REFERENCE, DISCOVERY_RADIUS)
            if progress:
                progress('正在建立最宽松库存快照…')
            fetched = tool.search(base, want=10001, max_pages=max_pages, stop=stop,
                                  progress=progress, catalog=catalog)
            if not fetched.get('complete'):
                raise ValueError('库存快照未完整更新（停止、网络失败或页数不足），原快照未替换；请手动更新数据')
            snapshot = dict(schema=SCHEMA, complete=True, created_at=datetime.now(timezone.utc).isoformat(),
                            scope=vars(base).copy(), catalog=catalog, rows=fetched['rows'],
                            scanned=fetched['scanned'], notes=fetched['notes'], max_pages=max_pages)
            content = json.dumps(snapshot, ensure_ascii=False, allow_nan=False).encode('utf-8')
            if len(content) > MAX_BYTES:
                raise ValueError('库存快照过大，原快照未替换')
            catalogue.check_stop(stop)
            catalog_updates.atomic_write(data_file(NAME), content)
        reference, coords = distance_context(snapshot, criteria, stop, progress)
        return filter_snapshot(snapshot, criteria, want, max_pages, stop, progress,
                               reference_coords=reference, system_coords=coords)
