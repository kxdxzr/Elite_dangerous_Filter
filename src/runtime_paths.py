"""Separate source data/cache; keep frozen/override paths backwards compatible."""
import os
import sys
import shutil
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
CACHE_NAMES = {'field_values_cache.json', 'module_specs_cache.json', 'route_module_cache.json',
               'full_outfitting_catalog_v1.json', 'full_outfitting_catalog_v2.json',
               'full_outfitting_catalog_v3.json', 'full_outfitting_catalog_v4.json',
               'full_outfitting_snapshot_v1.json',
               'full_outfitting_coordinates_v1.json'}
DATA_NAMES = {'last_session.json', 'route_ship_favorites.json'}


def is_cache(filename):
    return filename in CACHE_NAMES or filename.startswith('pve_cache_') and filename.endswith('.json')


def data_directory():
    override = os.environ.get("ELITE_FILTER_DATA_DIR")
    if override:
        return os.path.abspath(os.path.expanduser(override))
    if getattr(sys, "frozen", False):
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~/AppData/Local")
        return os.path.join(base, "EliteDangerousFilter")
    return str(PROJECT / 'data')


def cache_directory():
    if os.environ.get('ELITE_FILTER_DATA_DIR') or getattr(sys, 'frozen', False):
        return data_directory()
    return str(PROJECT / 'cache')


def _migrate_file(source, target):
    """Exclusive copy before removing the old file: never overwrite either version."""
    if not source.is_file():
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    # 'xb' also protects against another process creating the destination meanwhile.
    with target.open('xb') as output:
        try:
            with source.open('rb') as original:
                shutil.copyfileobj(original, output)
            output.flush()
            os.fsync(output.fileno())
        except BaseException:
            output.close()
            target.unlink()
            raise
    source.unlink()
    return True


def migrate_legacy_files():
    """Explicit bulk migration for source runs; conflicts are retained and reported."""
    report = dict(moved=0, conflicts=[])
    if os.environ.get('ELITE_FILTER_DATA_DIR') or getattr(sys, 'frozen', False):
        return report
    names = DATA_NAMES | CACHE_NAMES | {p.name for p in PROJECT.glob('pve_cache_*.json')}
    for name in sorted(names):
        source = PROJECT / name
        if not source.is_file():
            continue
        target = Path(cache_directory() if is_cache(name) else data_directory()) / name
        try:
            report['moved'] += int(_migrate_file(source, target))
        except FileExistsError:
            report['conflicts'].append(name)
    return report


def data_file(filename):
    directory = cache_directory() if is_cache(filename) else data_directory()
    os.makedirs(directory, exist_ok=True)
    target = Path(directory) / filename
    if not os.environ.get('ELITE_FILTER_DATA_DIR') and not getattr(sys, 'frozen', False):
        if filename in DATA_NAMES or is_cache(filename):
            try:
                _migrate_file(PROJECT / filename, target)
            except FileExistsError:
                pass  # Keep both copies; the new location is authoritative.
    return str(target)
