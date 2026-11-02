"""Manual EDTools catalogue snapshots with conditional, non-installing checks.

Both resources live in one atomically replaced file. Query scopes pin a single
generation, including recursive expanded PvE searches. Dynamic BGS caches are
deliberately unrelated to this module.
"""
from contextlib import contextmanager
from copy import deepcopy
from functools import wraps
import hashlib
import json
import math
from pathlib import Path
import sys
import threading
import time
import urllib.error
import urllib.request

from file_io import atomic_write
from runtime_paths import data_file


URLS = ('https://edtools.cc/pve.json', 'https://edtools.cc/res.json')
ACTIVE = 'edtools_catalogue_v1.json'
PENDING = 'edtools_catalogue_pending_v1.json'
CHECK = 'edtools_catalogue_check_v1.json'
INTERVAL = 24 * 3600
MAX_BYTES = 64 * 1024 * 1024
_lock = threading.RLock()
_context = threading.local()
_memory = {}


def bundled_path():
    root = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parents[1]))
    return root / 'assets' / 'edtools' / 'default.json'


def path_for(name):
    return bundled_path() if name == 'bundled' else Path(data_file(name))


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
        allow_nan=False, separators=(',', ':')).encode('utf-8')).hexdigest()


def validate_data(url, data):
    # Keep the existing parser as the single authority for catalogue records.
    from pve_tool import validate_dataset
    return validate_dataset(url, data)


def read(name=ACTIVE):
    path = path_for(name)
    try:
        stat = path.stat()
        stamp = (stat.st_mtime_ns, stat.st_size)
        key = str(path)
        cached = _memory.get(key)
        if cached and cached[0] == stamp:
            return cached[1]
        with path.open('rb') as stream:
            body = stream.read(2 * MAX_BYTES + 1024 * 1024 + 1)
        if len(body) > 2 * MAX_BYTES + 1024 * 1024:
            return None
        value = json.loads(body.decode('utf-8'))
        if not isinstance(value, dict) or value.get('schema') != 1:
            return None
        if name in (ACTIVE, PENDING, 'bundled'):
            records = value['resources']
            if set(records) != set(URLS):
                return None
            for url, record in records.items():
                validate_data(url, record['data'])
                if digest(record['data']) != record['digest']:
                    return None
                stamp_value = record['fetched_at']
                if type(stamp_value) not in (int, float) or not math.isfinite(stamp_value) or stamp_value < 0:
                    return None
            if value.get('generation') != generation(records):
                return None
        _memory[key] = (stamp, value)
        return value
    except (OSError, ValueError, TypeError, KeyError, AttributeError, OverflowError):
        return None


def write(name, value):
    content = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode('utf-8')
    atomic_write(path_for(name), content)
    _memory.pop(str(path_for(name)), None)


def active_snapshot():
    return read() or read('bundled')


def generation(records):
    return digest({url: record['digest'] for url, record in records.items()})


def download(url, previous=None):
    headers = {'User-Agent': 'EliteDangerousFilter/next-release', 'Accept': 'application/json',
               'Accept-Encoding': 'identity'}
    if previous:
        if previous.get('etag'):
            headers['If-None-Match'] = previous['etag']
        elif previous.get('last_modified'):
            headers['If-Modified-Since'] = previous['last_modified']
    request = urllib.request.Request(url, headers=headers)
    try:
        response = urllib.request.urlopen(request, timeout=30)
    except urllib.error.HTTPError as error:
        if error.code != 304 or previous is None:
            raise
        error.close()
        return deepcopy(previous)
    with response:
        body = response.read(MAX_BYTES + 1)
        response_headers = response.headers
        if len(body) > MAX_BYTES:
            raise ValueError('EDTools JSON exceeds 64 MiB.')
        length = response_headers.get('Content-Length')
        if length is not None and int(length) != len(body):
            raise ValueError('Incomplete EDTools download.')
        data = validate_data(url, json.loads(body.decode('utf-8-sig')))
        return dict(data=data, digest=digest(data), fetched_at=time.time(),
                    etag=response_headers.get('ETag'), last_modified=response_headers.get('Last-Modified'))


def bundle(records, **extra):
    return dict(schema=1, generation=generation(records), resources=records, **extra)


def load():
    """Read forever until explicitly updated; initialize both resources once."""
    if getattr(_context, 'active', False) and getattr(_context, 'snapshot', None) is not None:
        return _context.snapshot
    snapshot = active_snapshot()
    if snapshot is None:
        with _lock:
            snapshot = active_snapshot()
            if snapshot is None:
                records = {url: download(url) for url in URLS}
                snapshot = bundle(records, installed_at=time.time())
                write(ACTIVE, snapshot)
    if getattr(_context, 'active', False):
        _context.snapshot = snapshot
    return snapshot


@contextmanager
def scope():
    if getattr(_context, 'active', False):
        yield
        return
    _context.active, _context.snapshot = True, None
    try:
        yield
    finally:
        _context.active, _context.snapshot = False, None


def query_scope(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        with scope():
            return function(*args, **kwargs)
    return wrapped


def get(url):
    if url not in URLS:
        raise ValueError('Unknown EDTools dataset URL.')
    snapshot = load()
    record = snapshot['resources'][url]
    return deepcopy(record['data']), dict(url=url, hit=True, manual_snapshot=True,
        generation=snapshot['generation'], fetched_at=record['fetched_at'],
        source='bundled' if snapshot.get('bundled_at') else 'user',
        age_seconds=max(0, time.time() - record['fetched_at']),
        last_modified=record.get('last_modified'))


def pending(active=None):
    active = active or active_snapshot()
    candidate = read(PENDING)
    return (candidate if active and candidate and candidate.get('base_generation') == active['generation']
            and candidate['generation'] != active['generation'] else None)


def check(force=False):
    """Never installs data. Failures are explicit and do not affect active data."""
    with _lock:
        active = active_snapshot()
        if active is None:
            return dict(status='missing')
        candidate = pending(active)
        if candidate is not None and not force:
            return dict(status='available', generation=candidate['generation'])
        previous_check = read(CHECK) or {}
        now = time.time()
        checked_at = previous_check.get('checked_at', active.get('installed_at', 0))
        valid_time = type(checked_at) in (int, float) and math.isfinite(checked_at)
        if (not force and previous_check.get('base_generation', active['generation']) == active['generation']
                and valid_time and 0 <= now - checked_at < INTERVAL):
            return dict(status='failed' if previous_check.get('error') else 'recent',
                        error=previous_check.get('error', ''))
        try:
            records = {}
            for url in URLS:
                previous = deepcopy(active['resources'][url])
                if previous_check.get('base_generation') == active['generation']:
                    previous.update(previous_check.get('validators', {}).get(url, {}))
                records[url] = download(url, previous)
            candidate = bundle(records, base_generation=active['generation'], checked_at=now)
            changed = candidate['generation'] != active['generation']
            if changed:
                write(PENDING, candidate)
            elif path_for(PENDING).exists():
                path_for(PENDING).unlink()
                _memory.pop(str(path_for(PENDING)), None)
            write(CHECK, dict(schema=1, base_generation=active['generation'], checked_at=now,
                validators={url: {key: record.get(key) for key in ('etag', 'last_modified')}
                            for url, record in records.items()} if not changed else {}))
            return dict(status='available' if changed else 'unchanged', generation=candidate['generation'])
        except Exception as error:
            try:
                write(CHECK, dict(schema=1, base_generation=active['generation'], checked_at=now, error=str(error)))
            except OSError:
                pass
            return dict(status='failed', error=str(error))


def update(expected_generation=None):
    """Explicit user-authorized install; a failed download/write preserves active."""
    with _lock:
        candidate = pending()
        if expected_generation is not None:
            if candidate is None or candidate['generation'] != expected_generation:
                raise ValueError('EDTools staged update changed; check again before installing.')
        if candidate is None:
            candidate = bundle({url: download(url) for url in URLS})
        installed = bundle(candidate['resources'], installed_at=time.time())
        write(ACTIVE, installed)
        # Stale pending/check files are ignored by generation; cleanup failures
        # must not turn a successful atomic installation into a reported failure.
        for name in (PENDING, CHECK):
            try:
                path_for(name).unlink(missing_ok=True)
                _memory.pop(str(path_for(name)), None)
            except OSError:
                pass
        return installed
