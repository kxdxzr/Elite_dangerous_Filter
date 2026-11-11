"""Compare stock-first verification against an old git revision, without HTTP."""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import types
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
import full_outfitting


def baseline(revision):
    source = subprocess.check_output(['git', 'show', f'{revision}:src/full_outfitting.py'], cwd=ROOT)
    module = types.ModuleType('_outfitting_before_stock_first')
    sys.modules[module.__name__] = module
    exec(compile(source, f'{revision}:src/full_outfitting.py', 'exec'), module.__dict__)
    return module


def measure(module, count, all_pass=False, shared_system=False):
    items = [dict(name='Shield Booster', ed_symbol='booster', **{'class': 0, 'rating': 'A'}),
             dict(name='Cargo Rack', ed_symbol='cargo', **{'class': 1, 'rating': 'E'})]
    catalog = dict(items=items, ships=[], armours=[], issues=[])
    rows = [dict(id=i + 1, name=f'Port{i}', system_name='Shared' if shared_system else f'System{i}',
                 type='Coriolis Starport', modules=deepcopy(items if all_pass or i % 10 == 0 else items[:1]),
                 distance=10, distance_to_arrival=100, technology_broker='None', services=[],
                 outfitting_updated_at='stock-time') for i in range(count)]
    calls = []
    def http(url, payload=None, **kwargs):
        assert '/systems/' in url, url
        name = payload['filters']['name']['value']
        calls.append(name)
        return dict(results=[dict(name=name, controlling_power='Li Yong-Rui',
                                  power_state='Fortified', needs_permit=False)])
    def candidates(kind, conditions, **kwargs):
        hits = []
        for raw in rows:
            row = deepcopy(raw)
            if kwargs['row_filter'](row):
                hits.append(row)
        kwargs['notes'].append('候选分页已取完')
        return hits, len(rows), len(rows)
    with patch.object(module.eng, 'search', side_effect=candidates), \
            patch.object(module, 'request_json', side_effect=http):
        result = module.search(module.build_criteria('Sol', 100, require_discount=True),
                               catalog=catalog, want=count + 1)
    return dict(system_lookups=len(calls), hits=len(result['rows']), scanned=result['scanned']), result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', default='v0.1.5-beta')
    parser.add_argument('--count', type=int, default=100)
    args = parser.parse_args()
    if args.count < 1:
        parser.error('count must be positive')
    old = baseline(args.baseline)
    report = dict(baseline=args.baseline, offline=True, cases={})
    for name, all_pass, shared in [('90_percent_missing_stock', False, False),
                                   ('all_pass', True, False), ('shared_system', True, True)]:
        before, expected = measure(old, args.count, all_pass, shared)
        after, actual = measure(full_outfitting, args.count, all_pass, shared)
        assert expected['rows'] == actual['rows'], name + ': verified rows changed'
        assert expected['complete'] and actual['complete'], name + ': incomplete fixture scan'
        assert old.export_table(expected) == full_outfitting.export_table(actual), name + ': result CSV changed'
        assert before['scanned'] == after['scanned'] == args.count
        report['cases'][name] = dict(before=before, after=after, identical_verified_rows=True,
                                     identical_result_csv=True,
                                     saved_system_lookups=before['system_lookups'] - after['system_lookups'])
    print(json.dumps(report, indent=2))
