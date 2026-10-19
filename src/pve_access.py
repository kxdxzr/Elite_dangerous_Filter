"""PvE station access and ringed-body arrival distances (Ls, not ring radius)."""
import math
from concurrent.futures import ThreadPoolExecutor

import filter_engine as eng
import pve_cache
from powerplay_tool import _is_colonisation_ship


def arrival(value):
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number >= 0 else None


def station_match(system, pad='', maximum=None):
    stations = system.get('stations')
    if not isinstance(stations, list):
        raise ValueError('Source station data is unknown.')
    matches, uncertain = [], False
    for station in stations:
        if not isinstance(station, dict):
            uncertain = True
            continue
        kind = str(station.get('type', '')).casefold()
        name = str(station.get('name', ''))
        if 'carrier' in kind or name.casefold().startswith('stronghold carrier') or _is_colonisation_ship(station):
            continue
        distance = arrival(station.get('distance_to_arrival'))
        if maximum is not None and distance is not None and distance > maximum:
            continue
        services = station.get('services')
        if isinstance(services, list) and not any(str(service).casefold() == 'missions' for service in services):
            continue
        capability = []
        for size in ('S', 'M', 'L'):
            key = {'S': 'small_pads', 'M': 'medium_pads', 'L': 'large_pads'}[size]
            count = arrival(station.get(key))
            flag = count > 0 if count is not None else None
            if size == 'L' and type(station.get('has_large_pad')) is bool:
                flag = station['has_large_pad'] or flag is True
            capability.append(flag)
        usable = capability[('S', 'M', 'L').index(pad):] if pad else [True]
        if True not in usable and None not in usable:
            continue
        if (not kind or not isinstance(services, list) or maximum is not None and distance is None
                or True not in usable):
            uncertain = True
            continue
        if not name:
            uncertain = True
            continue
        largest = next((size for size, flag in reversed(list(zip(('S', 'M', 'L'), capability))) if flag is True), '情况未知')
        matches.append(dict(source_station=name, source_station_pad=largest,
                            source_station_ls=distance if distance is not None else '情况未知'))
    if matches:
        return min(matches, key=lambda item: (arrival(item['source_station_ls']) if arrival(item['source_station_ls']) is not None else math.inf,
                                             item['source_station'].casefold()))
    if uncertain:
        raise ValueError('Source station services, pad or arrival distance is unknown; cannot confirm no matching station.')
    return None


def ring_distances(names, refresh=False, stop=None, progress=None):
    """Batch full body records: system summaries omit rings and cannot prove absence."""
    names = sorted(set(names), key=str.casefold)
    chunks = [names[index:index + 8] for index in range(0, len(names), 8)]

    def chunk_load(chunk):
        def load():
            targets = {name.casefold(): dict(seen=False, uncertain=False, has_rings=False,
                                             distance=None, body='') for name in chunk}
            seen = set()
            for page in range(100):
                if stop is not None and stop.is_set():
                    raise InterruptedError('Stopped during ring-distance lookup.')
                data = eng._http_json(eng.SPansh_BASE + '/bodies/search', {
                    'filters': {'system_name': {'value': chunk}}, 'size': 500, 'page': page}, timeout=30, compressed=True)
                rows = data.get('results') if isinstance(data, dict) else None
                if not isinstance(rows, list):
                    raise ValueError('Invalid body response; ring distances unknown.')
                added = 0
                for row in rows:
                    if not isinstance(row, dict) or not row.get('system_name') or not row.get('name'):
                        raise ValueError('Body system/name fields missing; coverage unknown.')
                    key = (row['system_name'].casefold(), str(row.get('id64', row['name'])))
                    if key in seen:
                        continue
                    seen.add(key)
                    added += 1
                    target = targets.get(key[0])
                    if target is None:
                        continue
                    target['seen'] = True
                    rings = row.get('rings', [])
                    if not isinstance(rings, list):
                        target['uncertain'] = True
                    elif rings:
                        target['has_rings'] = True
                        if not target['body']:
                            target['body'] = row['name']
                        distance = arrival(row.get('distance_to_arrival'))
                        if distance is None:
                            target['uncertain'] = True
                        elif target['distance'] is None or distance < target['distance']:
                            target.update(distance=distance, body=row['name'])
                if rows and not added:
                    raise ValueError('Body pages repeated; ring-distance coverage incomplete.')
                if len(rows) < 500:
                    return targets
            raise ValueError('Body page limit reached; ring-distance coverage incomplete.')
        key = 'ring-arrival-v2:' + '\n'.join(name.casefold() for name in chunk)
        return pve_cache.cached(key, load, 300, refresh)[0]

    result = {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        # Submit only one bounded wave; cancellation never queues the catalogue.
        for start in range(0, len(chunks), 4):
            if stop is not None and stop.is_set():
                raise InterruptedError('Stopped during ring-distance lookup.')
            futures = [pool.submit(chunk_load, chunk) for chunk in chunks[start:start + 4]]
            try:
                for future in futures:
                    result.update(future.result())
                if progress:
                    progress(f'查询目标星环距离：{min(start + 4, len(chunks))}/{len(chunks)}')
            finally:
                for future in futures:
                    future.cancel()
    return result
