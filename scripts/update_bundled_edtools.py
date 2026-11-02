"""Explicit maintainer download of the bundled, validated EDTools baseline."""
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
import edtools_snapshot as snapshot
from file_io import atomic_write
import json


if __name__ == '__main__':
    records = {url: snapshot.download(url) for url in snapshot.URLS}
    now = time.time()
    value = snapshot.bundle(records, installed_at=now, bundled_at=now)
    content = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode('utf-8')
    path = ROOT / 'assets' / 'edtools' / 'default.json'
    atomic_write(path, content)
    print(f'{path}: {len(content)} bytes')
    for url, record in records.items():
        print(url, len(record['data']), record.get('last_modified'), record['digest'])
