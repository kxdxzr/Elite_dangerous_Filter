"""TTL cache for public PvE data. No stale-on-error fallback or failed entries."""
import hashlib
import threading
import time
import math
from collections import OrderedDict

from runtime_paths import data_file
import session_store

_memory = OrderedDict()
_locks = [threading.Lock() for _ in range(32)]
_guard = threading.Lock()


def peek(key, ttl):
    """Read a fresh successful entry without invoking a loader."""
    with _guard:
        record = _memory.get(key)
    if record is None:
        record = session_store.load(data_file('pve_cache_' + hashlib.sha256(key.encode()).hexdigest()[:24] + '.json'))
    stamp = record.get('fetched_at') if isinstance(record, dict) else None
    age = time.time() - stamp if type(stamp) in (int, float) and math.isfinite(stamp) else ttl + 1
    if isinstance(record, dict) and record.get('version') == 1 and 0 <= age < ttl and 'value' in record:
        _remember(key, record)
        return True, record['value']
    return False, None


def put(key, value, fetched_at=None):
    """Publish only fully verified successful responses; persistence is best effort."""
    record = dict(version=1, fetched_at=time.time() if fetched_at is None else fetched_at, value=value)
    try:
        session_store.save(data_file('pve_cache_' + hashlib.sha256(key.encode()).hexdigest()[:24] + '.json'), record)
    except OSError:
        pass
    _remember(key, record)


def cached(key, loader, ttl, force=False):
    lock = _locks[hash(key) % len(_locks)]
    with lock:
        with _guard:
            record = _memory.get(key)
        path = data_file('pve_cache_' + hashlib.sha256(key.encode()).hexdigest()[:24] + '.json')
        if record is None:
            record = session_store.load(path)
        stamp = record.get('fetched_at') if isinstance(record, dict) else None
        age = time.time() - stamp if type(stamp) in (int, float) and math.isfinite(stamp) else ttl + 1
        if not force and isinstance(record, dict) and record.get('version') == 1 and 0 <= age < ttl and 'value' in record:
            _remember(key, record)
            return record['value'], dict(hit=True, fetched_at=record['fetched_at'], age_seconds=age)
        value = loader()
        record = dict(version=1, fetched_at=time.time(), value=value)
        # A cache write failure must not discard a successful network query.
        try:
            session_store.save(path, record)
        except OSError:
            pass
        _remember(key, record)
        return value, dict(hit=False, fetched_at=record['fetched_at'], age_seconds=0)


def clear_memory():
    with _guard:
        _memory.clear()


def _remember(key, record):
    with _guard:
        _memory[key] = record
        _memory.move_to_end(key)
        while len(_memory) > 256:
            _memory.popitem(last=False)
