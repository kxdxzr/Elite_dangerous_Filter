"""Offline, fixed-input comparison with a pre-pipeline git revision; no HTTP."""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import threading
import time
import types

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
import pve_tool


def baseline(revision):
    source = subprocess.check_output(['git', 'show', f'{revision}:src/pve_tool.py'], cwd=ROOT)
    module = types.ModuleType('_pve_before_pipeline')
    sys.modules[module.__name__] = module
    exec(compile(source, f'{revision}:src/pve_tool.py', 'exec'), module.__dict__)
    return module


def measure(module, count, delay_ms, passing, dynamic):
    rows, records = [], {}
    for i in range(count):
        source, target = f'S{i:05}', f'T{i:05}'
        rows.append(dict(source=source, target=target, distance=100000 + i,
                         res_types=['low'], cnb=False, site_record='low', ring_count=1,
                         federation=3, empire=0, factions=3, count_source='EDTools'))
        good = passing or i % 10 == 0
        records[source] = dict(minor_faction_presences=[dict(name=f'F{j}', allegiance='Federation', government='Democracy')
                                                       for j in range(3 if good else 1)])
        records[target] = dict(controlling_minor_faction='Pirates')
    lock = threading.Lock()
    stats = dict(detail_calls=0, in_flight=0, peak_in_flight=0)
    def load(name):
        with lock:
            stats['detail_calls'] += 1
            stats['in_flight'] += 1
            stats['peak_in_flight'] = max(stats['peak_in_flight'], stats['in_flight'])
        try:
            if delay_ms:
                time.sleep(delay_ms / 1000)
            return deepcopy(records[name])
        finally:
            with lock:
                stats['in_flight'] -= 1
    start = time.monotonic()
    def receive(batch):
        if batch and 'first_result_seconds' not in stats:
            stats['first_result_seconds'] = time.monotonic() - start
            stats['detail_calls_at_first_result'] = stats['detail_calls']
    kwargs = dict(page=dict(reference='Sol', radius=module.GLOBAL_RADIUS, rows=rows),
                  details_loader=load, workers=4, ring_loader=lambda names: {})
    if module is pve_tool:
        kwargs['on_results'] = receive
    info, result = module.search(module.Criteria(radius=0, min_factions=3 if dynamic else 0,
                                                target_controller='Pirates' if dynamic else ''), **kwargs)
    receive(result)
    stats.update(seconds=time.monotonic() - start, hits=len(result), scanned=info['scanned'], complete=info['complete'])
    stats.pop('in_flight')
    return stats, result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', default='v0.1.5-beta')
    parser.add_argument('--count', type=int, default=100)
    parser.add_argument('--delay-ms', type=float, default=0)
    args = parser.parse_args()
    if args.count < 1 or args.delay_ms < 0:
        parser.error('count must be positive and delay-ms nonnegative')
    old = baseline(args.baseline)
    report = dict(baseline=args.baseline, offline=True, radius=0,
                  synthetic_delay_ms=args.delay_ms, cases={})
    for name, passing, dynamic in [('reject_90_percent', False, True),
                                    ('all_pass', True, True), ('local_only', True, False)]:
        before, expected = measure(old, args.count, args.delay_ms, passing, dynamic)
        after, actual = measure(pve_tool, args.count, args.delay_ms, passing, dynamic)
        assert expected == actual, name + ': feasible results changed'
        assert before['complete'] and after['complete'] and before['scanned'] == after['scanned'] == args.count
        report['cases'][name] = dict(before=before, after=after, identical_results=True,
                                     saved_detail_calls=before['detail_calls'] - after['detail_calls'])
    print(json.dumps(report, indent=2))
