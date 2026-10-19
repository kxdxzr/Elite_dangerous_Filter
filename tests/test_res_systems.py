import copy
from dataclasses import replace
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

import pve_tool as pve
import pve_cache
import res_systems as res


def system(name, x=10, **extra):
    return dict(name=name, x=x, y=0, z=0, controlling_minor_faction='Test Faction',
                controlling_power='Yuri Grom', **extra)


def site(*levels):
    return dict(haz='Ring' if 'haz' in levels else '', high='Ring' if 'high' in levels else '',
                reg='Ring' if 'reg' in levels else '', low='Ring' if 'low' in levels else '', beac=0)


def ring(has=True, **extra):
    return dict(seen=True, uncertain=False, has_rings=has, distance=100 if has else None,
                body='Planet' if has else '', **extra)


def run(systems, pairs=None, sites=None, rings=None, criteria=None, **kw):
    criteria = criteria or pve.Criteria(search_mode='res_systems', target_controller='Test Faction')
    return pve.search(criteria, resolver=lambda name: (name, (0, 0, 0), False),
                      systems_loader=lambda criteria, reference: copy.deepcopy(systems),
                      dataset_loader=lambda url: (pairs or {}) if url == pve.PAIRS_URL else (sites or {}),
                      ring_loader=lambda names: rings if rings is not None else {name.casefold(): ring() for name in names}, **kw)


class ResSystemTests(unittest.TestCase):
    def test_expanded_cnb_fallback_applies_only_after_combining_res_candidates(self):
        from test_pve_tool import candidate, page
        for has_res in (True, False):
            for enabled in (True, False):
                with self.subTest(has_res=has_res, enabled=enabled):
                    info, rows = pve.search(pve.Criteria(search_mode='expanded', cnb_fallback=enabled),
                        page=page(candidate(source='CNB source', target='CNB target', sites=(), cnb=True)),
                        resolver=lambda name: (name, (0, 0, 0), False),
                        systems_loader=lambda *args: [system('Extra RES')] if has_res else [],
                        dataset_loader=lambda url: {},
                        details_loader=lambda name: dict(controlling_minor_faction='Controller'),
                        ring_loader=lambda names: {name.casefold(): ring() for name in names})
                    expected = ['Extra RES'] if has_res else ['CNB target'] if enabled else []
                    self.assertEqual([row['target'] for row in rows], expected)

    def test_expanded_ring_free_system_can_still_be_cnb(self):
        from test_pve_tool import candidate, page
        info, rows = pve.search(pve.Criteria(search_mode='expanded'),
            page=page(candidate(target='Target', sites=(), cnb=True)),
            resolver=lambda name: (name, (0, 0, 0), False),
            systems_loader=lambda *args: [system('Target')], dataset_loader=lambda url: {},
            details_loader=lambda name: dict(controlling_minor_faction='Controller'),
            ring_loader=lambda names: {'target': ring(False)})
        self.assertEqual([row['site'] for row in rows], ['CNB'])
        self.assertEqual(info['mode'], 'CNB')

    def test_expanded_cnb_suppressed_when_ring_data_incomplete(self):
        from test_pve_tool import candidate, page
        info, rows = pve.search(pve.Criteria(search_mode='expanded'),
            page=page(candidate(target='CNB Target', sites=(), cnb=True)),
            resolver=lambda name: (name, (0, 0, 0), False),
            systems_loader=lambda *args: [system('Unknown')], dataset_loader=lambda url: {},
            ring_loader=lambda names: {})
        self.assertEqual(rows, [])
        self.assertFalse(info['complete'])
    def test_source_annotation_only_queries_known_sources_and_deduplicates(self):
        rows = [dict(source='A; B', _source_names=['A', 'B'], _known_sources=True),
                dict(source='A', _known_sources=True),
                dict(source='无数据', _known_sources=False)]
        info = dict(complete=True, errors=[])
        loader = Mock(side_effect=lambda name: dict(controlling_minor_faction=name + ' Faction'))
        res.annotate_source_controllers(rows, info, details_loader=loader)
        self.assertEqual(loader.call_count, 2)
        self.assertEqual(rows[0]['source_controller'], 'A: A Faction; B: B Faction')
        self.assertEqual(rows[1]['source_controller'], 'A Faction')
        self.assertEqual(rows[2]['source_controller'], '-')

    def test_source_annotation_failures_preserve_results_and_do_not_guess(self):
        rows = [dict(source='A', _known_sources=True)]
        info = dict(complete=True, errors=[])
        res.annotate_source_controllers(rows, info, details_loader=Mock(side_effect=OSError('offline')))
        self.assertEqual(rows[0]['source_controller'], '情况未知')
        self.assertTrue(info['complete'])
        self.assertEqual(len(info['errors']), 1)
    def test_expansion_retains_original_task_rows_and_appends_new_targets(self):
        from test_pve_tool import candidate, page
        criteria = pve.Criteria(search_mode='expanded')
        original = candidate(source='Original Source', target='Known')
        info, rows = pve.search(criteria, page=page(original),
            details_loader=lambda name: dict(controlling_minor_faction='Source Controller'),
            resolver=lambda name: (name, (0, 0, 0), False),
            systems_loader=lambda *args: [system('Known'), system('New', 1)],
            dataset_loader=lambda url: {},
            ring_loader=lambda names: {name.casefold(): ring() for name in names})
        self.assertEqual([row['target'] for row in rows], ['Known', 'New'])
        self.assertEqual(rows[0]['source'], 'Original Source')
        self.assertEqual(rows[0]['factions'], original['factions'])
        self.assertEqual(rows[1]['source'], '无数据')
        self.assertEqual(rows[0]['source_controller'], 'Source Controller')
        self.assertEqual(rows[1]['source_controller'], '-')
        self.assertEqual(info['mode'], 'Missions + RES systems')

    def test_expansion_removes_legacy_target_proven_ring_free(self):
        from test_pve_tool import candidate, page
        info, rows = pve.search(pve.Criteria(search_mode='expanded'), page=page(candidate(target='No rings')),
            resolver=lambda name: (name, (0, 0, 0), False),
            systems_loader=lambda *args: [system('No rings')], dataset_loader=lambda url: {},
            ring_loader=lambda names: {'no rings': ring(False)})
        self.assertEqual(rows, [])

    def test_not_limited_to_task_catalogue_and_known_sources_rank_first(self):
        pairs = {'Source B': dict(target='Far Known', x=0, y=0, z=0),
                 'Source A': dict(target='Far Known', x=0, y=0, z=0)}
        info, rows = run([system('Near Unlisted', 1), system('Far Known', 40)], pairs=pairs)
        self.assertEqual([row['target'] for row in rows], ['Far Known', 'Near Unlisted'])
        self.assertEqual(rows[0]['source'], 'Source A; Source B')
        self.assertEqual(rows[1]['source'], '无数据')
        self.assertEqual(rows[1]['site'], 'RES（星环推定）')
        self.assertNotIn('factions', rows[1])
        self.assertTrue(info['complete'])

    def test_target_radius_controller_power_and_no_task_requirements(self):
        criteria = pve.Criteria(search_mode='res_systems', target_controller='Test Faction', power='Yuri Grom',
                                min_factions=8, source_faction='Ignored', source_pad='L')
        wrong_faction = dict(system('Wrong faction'), controlling_minor_faction='Other')
        wrong_power = dict(system('Wrong power'), controlling_power='Other')
        info, rows = run([system('Match'), wrong_faction, wrong_power, system('Far', 60)], criteria=criteria)
        self.assertEqual([row['target'] for row in rows], ['Match'])
        self.assertTrue(info['complete'])

    def test_only_low_requires_explicit_record_and_rings_never_infer_low(self):
        criteria = pve.Criteria(search_mode='res_systems', site_type='low')
        sites = {'Low': site('low'), 'High': site('high')}
        systems = [system('Low'), system('High'), system('Unlisted')]
        self.assertEqual([row['target'] for row in run(systems, sites=sites, criteria=criteria)[1]], ['Low'])
        confirmed = replace(criteria, site_type='confirmed')
        self.assertEqual({row['target'] for row in run(systems, sites=sites, criteria=confirmed)[1]}, {'Low', 'High'})
        self.assertEqual(len(run(systems, sites=sites)[1]), 3)

    def test_known_res_rank_before_inferred_then_distance(self):
        _, rows = run([system('Near', 1), system('Known', 30), system('Middle', 10)], sites={'Known': site('haz')})
        self.assertEqual([row['target'] for row in rows], ['Known', 'Near', 'Middle'])
        self.assertEqual(rows[0]['site'], 'RES Haz')

    def test_no_rings_excluded_even_with_stale_low_record(self):
        info, rows = run([system('No rings')], sites={'No rings': site('low')}, rings={'no rings': ring(False)})
        self.assertEqual(rows, [])
        self.assertTrue(info['complete'])

    def test_ring_distance_missing_coverage_and_duplicates(self):
        systems = [system('Found'), system('Found'), system('Unknown'), system('Far')]
        rings = {'found': ring(), 'far': dict(ring(), distance=1000)}
        criteria = pve.Criteria(search_mode='res_systems', target_ring_max_ls=200)
        info, rows = run(systems, rings=rings, criteria=criteria)
        self.assertEqual([row['target'] for row in rows], ['Found'])
        self.assertFalse(info['complete'])
        self.assertEqual(info['diagnostics']['unknown_sites'], 1)

    def test_ring_lookup_failure_never_produces_inferred_hits(self):
        with patch.object(res.pve_access, 'ring_distances', side_effect=OSError('offline')):
            info, rows = res.search(pve.Criteria(search_mode='res_systems'),
                resolver=lambda name: (name, (0, 0, 0), False), systems_loader=lambda *args: [system('Target')],
                dataset_loader=lambda url: {})
        self.assertEqual(rows, [])
        self.assertFalse(info['complete'])

    def test_supplementary_edtools_failure_does_not_gate_spansh_results(self):
        info, rows = res.search(pve.Criteria(search_mode='res_systems'),
            resolver=lambda name: (name, (0, 0, 0), False), systems_loader=lambda *args: [system('Target')],
            dataset_loader=Mock(side_effect=OSError('offline')),
            ring_loader=lambda names: {'target': ring()})
        self.assertEqual(rows[0]['source'], '无数据')
        self.assertFalse(info['complete'])
        self.assertEqual(len(info['errors']), 2)

    def test_stop_and_bad_mode_make_no_requests(self):
        stop = threading.Event()
        stop.set()
        resolver = Mock()
        info, rows = pve.search(pve.Criteria(search_mode='res_systems'), stop=stop, resolver=resolver)
        resolver.assert_not_called()
        self.assertFalse(info['complete'])
        for criteria in (pve.Criteria(search_mode='bad'), pve.Criteria(site_type='bad')):
            with self.assertRaises(ValueError):
                pve.search(criteria, resolver=resolver)
        resolver.assert_not_called()

    def test_paginated_system_search_ignores_capped_count_and_caches(self):
        batches = [dict(count=1, results=[system(str(i)) for i in range(500)]),
                   dict(count=1, results=[system('Last')])]
        with tempfile.TemporaryDirectory() as folder, \
                patch.object(pve_cache, 'data_file', side_effect=lambda name: Path(folder) / name), \
                patch.object(res.eng, '_http_json', side_effect=batches) as http:
            pve_cache.clear_memory()
            try:
                criteria = pve.Criteria(search_mode='res_systems', target_controller='Test Faction', power='Yuri Grom')
                rows = res.candidate_systems(criteria, 'Sol')
                self.assertEqual(len(rows), 501)
                self.assertEqual(res.candidate_systems(criteria, 'Sol'), rows)
                self.assertEqual(http.call_count, 2)
                filters = http.call_args.args[1]['filters']
                self.assertEqual(filters['controlling_minor_faction']['value'], ['Test Faction'])
                self.assertEqual(filters['controlling_power']['value'], ['Yuri Grom'])
                self.assertEqual(filters['distance']['max'], 50)
            finally:
                pve_cache.clear_memory()

    def test_repeated_full_pages_fail_instead_of_confirming_completion(self):
        batch = dict(results=[system(str(i)) for i in range(500)])
        with tempfile.TemporaryDirectory() as folder, \
                patch.object(pve_cache, 'data_file', side_effect=lambda name: Path(folder) / name), \
                patch.object(res.eng, '_http_json', return_value=batch):
            pve_cache.clear_memory()
            try:
                with self.assertRaisesRegex(ValueError, 'repeated'):
                    res.candidate_systems(pve.Criteria(search_mode='res_systems'), 'Sol')
            finally:
                pve_cache.clear_memory()
