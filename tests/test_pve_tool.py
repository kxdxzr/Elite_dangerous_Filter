import copy
from dataclasses import replace
from html import escape
import threading
import io
import urllib.error
import unittest
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

import pve_tool as pve


def candidate(source='Alpha', target='Target', distance=20, sites=('low',), cnb=False, rings=3):
    return dict(source=source, target=target, distance=distance, res_types=list(sites), cnb=cnb,
                site_record=','.join(sites) or ('CNB' if cnb else f'{rings} rings'),
                ring_count=0 if cnb else rings,
                federation=2, empire=1, factions=4, count_source='EDTools')


def page(*rows, radius=pve.GLOBAL_RADIUS, reference='Sol'):
    return dict(reference=reference, radius=radius, rows=list(rows))


def faction(name, allegiance='Federation', government='Democracy'):
    return dict(name=name, allegiance=allegiance, government=government)


DETAILS = {
    'Alpha': dict(controlling_minor_faction='Local Government', controlling_power='Yuri Grom',
                  power=['Ignored Power'], updated_at='2026-10-12T00:00:00Z',
                  minor_faction_presences=[faction('Fed One'), faction('Fed Two'),
                     faction('Imp One', 'Empire'), faction('Pirates', 'Independent', 'Anarchy')]),
    'Beta': dict(controlling_minor_faction='Other Government', controlling_power='Other Power',
                 minor_faction_presences=[faction('Fed One')]),
    'Target': dict(controlling_minor_faction='Target Pirates', controlling_power='Yuri Grom',
                   power=['Ignored Power'], updated_at='2026-10-11T00:00:00Z'),
}


def run(criteria=None, *rows, loader=None, **kw):
    kw.setdefault('ring_loader', lambda names: {})
    return pve.search(criteria or pve.Criteria(), page=page(*rows),
        details_loader=loader or (lambda name: copy.deepcopy(DETAILS[name])),
        resolver=lambda name: (name, (0, 0, 0), False), **kw)


def html_page(rows, radius=50, reference='Sol'):
    parts = [f'<div>Systems within {radius} ly from {escape(reference)}:</div>',
             '<table id="sys_tbl"><thead><tr>' + ''.join(f'<th>{h}</th>' for h in pve.HEADERS) + '</tr></thead>']
    for row in rows:
        source, target = (escape(row[key], quote=True) for key in ('source', 'target'))
        cells = [str(row['distance']), f'<a data-clipboard-text="{source}"></a>{source}',
                 '1,000', '', '', '2', '1', '', '1', f'<a data-clipboard-text="{target}"></a>{target} / [ 2 ]',
                 row['site_record']]
        parts.append('<tr>' + ''.join(f'<td>{cell}</td>' for cell in cells) + '</tr>')
    parts.append(f'</table><div>rows: {len(rows)}</div>')
    return ''.join(parts)


class PveParserTests(unittest.TestCase):
    def setUp(self):
        self.cache_folder = tempfile.TemporaryDirectory()
        self.cache_patch = patch.object(pve.pve_cache, 'data_file', side_effect=lambda name: Path(self.cache_folder.name) / name)
        self.cache_patch.start()
        pve.pve_cache.clear_memory()

    def tearDown(self):
        pve.pve_cache.clear_memory()
        self.cache_patch.stop()
        self.cache_folder.cleanup()

    def test_full_json_catalogue_join_has_no_250_ly_cap_and_labels_ring_inference(self):
        pairs = {
            'Far Source': dict(x=1000, y=0, z=0, target='Low Target', Federation=2),
            'Ring Source': dict(x=20, y=0, z=0, target='Ring Only', t_r=9),
            'Beacon Source': dict(x=30, y=0, z=0, target='Beacon'),
        }
        sites = {'Low Target': dict(haz='', high='', reg='', low='A1', beac=0),
                 'Beacon': dict(haz='', high='', reg='', low='', beac=1)}
        data = pve.dataset_page(pairs, sites, 'Sol', (0, 0, 0))
        self.assertEqual(data['radius'], float('inf'))
        self.assertEqual(data['rows'][0]['distance'], 1000)
        self.assertFalse(data['rows'][1]['res_types'])
        info, rows = pve.search(pve.Criteria(radius=0), page=data)
        self.assertTrue(info['complete'])
        self.assertEqual([(r['source'], r['site']) for r in rows],
                         [('Far Source', 'RES Low'), ('Ring Source', 'RES（星环推定）')])
        self.assertEqual(info['inferred_res'], 1)

    def test_unlimited_loader_uses_both_public_json_resources(self):
        pairs = {'Alpha': dict(x=1000, y=0, z=0, target='Target')}
        sites = {'Target': dict(haz='', high='', reg='', low='1', beac=0)}
        with patch.object(pve, 'fetch_dataset', side_effect=[pairs, sites]) as fetch, \
                patch.object(pve.eng, 'get_system_coords', return_value=(0, 0, 0)), \
                patch.object(pve.urllib.request, 'urlopen') as html:
            data = pve.fetch_page(pve.Criteria(radius=0), 'Sol')
        self.assertEqual([call.args[0] for call in fetch.call_args_list], [pve.PAIRS_URL, pve.SITES_URL])
        self.assertEqual(data['rows'][0]['distance'], 1000)
        html.assert_not_called()

    def test_bad_catalogue_is_not_reported_as_no_matches(self):
        sites = {'Target': dict(haz='', high='', reg='', low='1', beac=0)}
        for pairs in ({}, {'Alpha': dict(target='Target')},
                      {'Alpha': dict(target='Target', x=float('nan'), y=0, z=0)}):
            with self.assertRaises(ValueError):
                pve.dataset_page(pairs, sites, 'Sol', (0, 0, 0))

    def test_thousands_separated_row_counter_still_checks_all_rows(self):
        html = html_page([candidate()] * 1000).replace('rows: 1000', 'rows: 1,000')
        self.assertEqual(len(pve.parse_page(html)['rows']), 1000)
        for bad in ('999', '1,001', '1,00', '1,0000'):
            with self.subTest(counter=bad), self.assertRaises(ValueError):
                pve.parse_page(html.replace('rows: 1,000', 'rows: ' + bad))

    def test_download_uses_explicit_php_without_multiviews(self):
        with patch.object(pve.urllib.request, 'urlopen', return_value=io.BytesIO(html_page([candidate()]).encode())) as get:
            parsed = pve.fetch_page(pve.Criteria(), 'Sol')
        self.assertEqual(len(parsed['rows']), 1)
        self.assertTrue(get.call_args.args[0].full_url.startswith('https://edtools.cc/pve.php?'))

    def test_download_error_identifies_server_and_matching_url(self):
        error = urllib.error.HTTPError(pve.BASE, 406, 'Not Acceptable', {}, None)
        with patch.object(pve.urllib.request, 'urlopen', side_effect=error):
            with self.assertRaises(pve.PageDownloadError) as caught:
                pve.fetch_page(pve.Criteria(reference='slo'), 'Sol')
        self.assertEqual(caught.exception.code, 406)
        self.assertIn('s=Sol', caught.exception.url)
        self.assertIn('import', str(caught.exception))
    def test_public_sol_sample_and_imported_search_without_network(self):
        html = (Path(__file__).resolve().parents[1] / 'docs' / 'edtools-sol-30-sample.html').read_text(encoding='utf-8')
        parsed = pve.parse_page(html)
        self.assertEqual(len(parsed['rows']), 8)
        resolver, loader = Mock(), Mock()
        info, rows = pve.search(pve.Criteria(radius=30), page=parsed, resolver=resolver, details_loader=loader)
        self.assertTrue(info['complete'])
        self.assertEqual(info['mode'], 'RES')
        self.assertTrue(rows)
        self.assertTrue(all(r['site'] == 'RES（星环推定）' for r in rows))
        self.assertNotIn('CU Cancri', [r['source'] for r in rows])
        resolver.assert_not_called()
        loader.assert_not_called()

    def test_real_layout_names_counts_and_sites(self):
        parsed = pve.parse_page(html_page([candidate(source='Alpha & Co'),
            candidate('Beta', sites=(), cnb=True), candidate('Gamma', sites=())]))
        self.assertEqual(parsed['reference'], 'Sol')
        self.assertEqual(parsed['radius'], 50)
        self.assertEqual(parsed['rows'][0]['source'], 'Alpha & Co')
        self.assertEqual(parsed['rows'][0]['factions'], 4)
        self.assertEqual(parsed['rows'][0]['res_types'], ['low'])
        self.assertTrue(parsed['rows'][1]['cnb'])
        self.assertFalse(parsed['rows'][2]['res_types'])  # Not confirmed RES/Low.
        self.assertEqual(parsed['rows'][2]['ring_count'], 3)

    def test_empty_valid_dataset(self):
        self.assertEqual(pve.parse_page(html_page([]))['rows'], [])

    def test_invalid_schema_truncation_and_coverage(self):
        html = html_page([candidate()])
        for text in ('Access denied', html.replace('sys_tbl', 'other_table'),
                     html.replace('RES/rings', 'New Column'), html.replace('rows: 1', 'rows: 2'),
                     html.replace('</table>', ''), html.replace('Systems within', 'Unknown coverage'),
                     html[:html.index('</tr></thead>')]):
            with self.subTest(text=text[:60]), self.assertRaises(ValueError):
                pve.parse_page(text)

    def test_missing_or_negative_numeric_cell(self):
        html = html_page([candidate()])
        for text in (html.replace('<td>20</td>', '<td>nan</td>'),
                     html.replace('<td>2</td>', '<td>-1</td>'),
                     html.replace('<td>20</td>', '')):
            with self.assertRaises(ValueError):
                pve.parse_page(text)

    def test_html_entities_in_reference(self):
        self.assertEqual(pve.parse_page(html_page([], reference='Alpha & Beta'))['reference'], 'Alpha & Beta')


class PveSearchTests(unittest.TestCase):
    def test_confirmed_ring_free_overrides_stale_res_records(self):
        for sites in ((), ('low',), ('haz', 'high', 'reg', 'low')):
            with self.subTest(sites=sites):
                info, rows = run(None, candidate(sites=sites, rings=0))
                self.assertEqual(rows, [])
                self.assertTrue(info['complete'])
                self.assertEqual(info['confirmed_res'], 0)
                self.assertEqual(info['diagnostics']['no_site'], 1)

    def test_ring_free_res_record_does_not_block_independent_cnb_fallback(self):
        info, rows = run(None, candidate(sites=('low',), rings=0),
                         candidate('Beta', sites=('high',), cnb=True))
        self.assertEqual(info['mode'], 'CNB')
        self.assertEqual([row['source'] for row in rows], ['Beta'])
        self.assertEqual(rows[0]['site'], 'CNB')
        self.assertEqual(run(pve.Criteria(cnb_fallback=False), candidate(cnb=True))[1], [])

    def test_missing_ring_count_is_not_evidence_of_ring_free_system(self):
        self.assertEqual(run(None, candidate(rings=None))[1][0]['site'], 'RES Low')
        self.assertEqual(run(None, candidate(sites=(), rings=None))[1][0]['site'], '情况未知')

    def test_validation_zero_requests(self):
        resolver = Mock()
        for args in ({'radius': -1}, {'radius': float('nan')}, {'radius': float('inf')}, {'radius': True},
                     {'radius': '50'}, {'min_factions': 9}, {'min_federation': -1}, {'min_empire': 1.5},
                     {'min_factions': True}, {'reference': ''}, {'power_scope': 'association'},
                     {'source_faction': 42}, {'prefer_low': 'yes'}):
            with self.subTest(args=args), self.assertRaises(ValueError):
                pve.search(pve.Criteria(**args), resolver=resolver)
        resolver.assert_not_called()

    def test_zero_radius_unlimited_and_url(self):
        info, rows = run(pve.Criteria(radius=0), candidate(distance=100000))
        self.assertEqual(len(rows), 1)
        self.assertTrue(info['complete'])
        self.assertIn('md=1000000000', pve.page_url(pve.Criteria(radius=0)))
        self.assertEqual(run(pve.Criteria(radius=5), candidate(distance=6))[1], [])

    def test_reference_and_radius_coverage_required(self):
        for data, criteria in [(page(candidate(), radius=30), pve.Criteria(radius=50)),
                               (page(candidate(), reference='Lave'), pve.Criteria()),
                               (page(candidate(), radius=250), pve.Criteria(radius=0))]:
            with self.assertRaises(ValueError):
                pve.search(criteria, page=data, resolver=lambda name: (name, (0, 0, 0), False))

    def test_low_preferred_but_not_required(self):
        low, high = candidate(), candidate('Beta', distance=1, sites=('high',))
        self.assertEqual([r['source'] for r in run(None, high, low)[1]], ['Alpha', 'Beta'])
        self.assertEqual([r['source'] for r in run(pve.Criteria(prefer_low=False), high, low)[1]], ['Beta', 'Alpha'])
        self.assertEqual(run(None, high)[1][0]['site'], 'RES')

    def test_cnb_fallback_only_after_all_other_filters(self):
        criteria = pve.Criteria(source_controller='Local Government')
        info, rows = run(criteria, candidate('Beta'), candidate('Alpha', sites=(), cnb=True))
        self.assertEqual(info['mode'], 'CNB')
        self.assertEqual(rows[0]['source'], 'Alpha')
        info, rows = run(None, candidate(), candidate('Beta', sites=(), cnb=True))
        self.assertEqual(info['mode'], 'RES')
        self.assertEqual([r['source'] for r in rows], ['Alpha'])

    def test_no_cnb_if_disabled_and_rings_inferred_not_low(self):
        self.assertEqual(run(pve.Criteria(cnb_fallback=False), candidate(sites=(), cnb=True))[1], [])
        self.assertEqual(run(None, candidate(sites=()))[1][0]['site'], 'RES（星环推定）')
        self.assertEqual(run(None, candidate(sites=(), rings=0))[1], [])

    def test_unknown_sites_shown_separately_and_do_not_confirm_cnb_fallback(self):
        info, rows = run(None, candidate(sites=(), rings=None), candidate('Beta', sites=(), cnb=True))
        self.assertEqual([r['site'] for r in rows], ['情况未知'])
        self.assertEqual(info['diagnostics']['unknown_sites'], 1)
        self.assertEqual(info['mode'], 'Unknown')
        self.assertEqual(info['confirmed_res'], 0)
        self.assertTrue(info['complete'])

    def test_unknown_rows_obey_all_other_filters(self):
        info, rows = run(pve.Criteria(min_factions=4), candidate(sites=(), rings=None))
        self.assertEqual(rows, [])
        self.assertEqual(info['diagnostics']['faction_minima_rejected'], 1)

    def test_bulk_controller_coverage_and_reuse_prevent_per_source_requests(self):
        mapping = {'alpha': copy.deepcopy(DETAILS['Alpha']), 'outside catalogue': {}}
        loader = Mock(side_effect=AssertionError('unnecessary detail lookup'))
        info, rows = run(pve.Criteria(source_controller='Local Government', min_factions=3),
                         candidate(sites=()), candidate('Beta'), loader=loader,
                         controller_loader=lambda name: mapping)
        self.assertEqual(len(rows), 1)
        self.assertEqual(info['diagnostics']['controlled_sources_not_in_catalogue'], 1)
        self.assertEqual(info['diagnostics']['source_catalogue_overlap'], 1)
        self.assertEqual(info['diagnostics']['controller_rejected'], 1)
        loader.assert_not_called()

    def test_progress_is_throttled_for_large_local_search(self):
        callback = Mock()
        rows = [candidate(str(n)) for n in range(28075)]
        info, result = run(None, *rows, progress=callback)
        self.assertEqual(len(result), 28075)
        self.assertEqual(info['scanned'], 28075)
        self.assertLess(callback.call_count, 50)
        self.assertIn('total', info['timings'])

    def test_presence_source_controller_target_controller_and(self):
        criteria = pve.Criteria(source_faction='fed one', source_controller='Local Government',
                                target_controller='Target Pirates')
        rows = run(criteria, candidate())[1]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['target_controller'], 'Target Pirates')
        for key in ('source_faction', 'source_controller', 'target_controller'):
            self.assertEqual(run(replace(criteria, **{key: 'No such faction'}), candidate())[1], [])
        # Presence does not require the faction to control the source.
        self.assertEqual(len(run(pve.Criteria(source_faction='Pirates'), candidate())[1]), 1)

    def test_live_faction_minima_independent_and_anarchy_excluded(self):
        good = pve.Criteria(min_factions=3, min_federation=2, min_empire=1)
        row = run(good, candidate())[1][0]
        self.assertEqual((row['factions'], row['federation'], row['empire']), (3, 2, 1))
        self.assertEqual(row['count_source'], 'Spansh estimate')
        for args in ({'min_factions': 4}, {'min_federation': 3}, {'min_empire': 2}):
            self.assertEqual(run(replace(good, **args), candidate())[1], [])

    def test_count_duplicate_factions_once(self):
        source = copy.deepcopy(DETAILS['Alpha'])
        source['minor_faction_presences'].append(source['minor_faction_presences'][0])
        self.assertEqual(len(pve.eligible_factions(source)), 3)

    def test_power_scope_uses_controlling_not_associated_power(self):
        for scope in ('source', 'target', 'both'):
            good = pve.Criteria(power='Yuri Grom', power_scope=scope)
            self.assertEqual(len(run(good, candidate())[1]), 1)
            self.assertEqual(run(replace(good, power='Ignored Power'), candidate())[1], [])
        self.assertEqual(len(run(pve.Criteria(power='Yuri Grom', power_scope='target'), candidate('Beta'))[1]), 1)
        self.assertEqual(run(pve.Criteria(power='Yuri Grom', power_scope='both'), candidate('Beta'))[1], [])

    def test_bulk_power_scopes_share_one_query_and_reuse_all_details(self):
        mapping = {name.casefold(): copy.deepcopy(DETAILS[name]) for name in ('Alpha', 'Target')}
        for scope, expected in (('source', ['Alpha']), ('target', ['Alpha', 'Beta']), ('both', ['Alpha'])):
            with self.subTest(scope=scope):
                bulk = Mock(return_value=mapping)
                loader = Mock(side_effect=AssertionError('Power records already contain details'))
                info, rows = run(pve.Criteria(power='Yuri Grom', power_scope=scope),
                                 candidate(), candidate('Beta'), loader=loader, power_loader=bulk)
                self.assertEqual([row['source'] for row in rows], expected)
                self.assertTrue(info['complete'])
                self.assertEqual(info['diagnostics']['power_rejected'], 0 if scope == 'target' else 1)
                bulk.assert_called_once_with('Yuri Grom')
                loader.assert_not_called()

    def test_bulk_power_and_controller_and_quantity_remain_and(self):
        mapping = {'alpha': copy.deepcopy(DETAILS['Alpha']), 'target': copy.deepcopy(DETAILS['Target'])}
        controller = lambda name: {'alpha': copy.deepcopy(DETAILS['Alpha'])}
        for minimum, count in ((3, 1), (4, 0)):
            info, rows = run(pve.Criteria(power='Yuri Grom', power_scope='both',
                                         source_controller='Local Government', min_factions=minimum),
                             candidate(), candidate('Beta'), power_loader=lambda name: mapping,
                             controller_loader=controller, loader=Mock(side_effect=AssertionError('no per-system calls')))
            self.assertEqual(len(rows), count)
            self.assertTrue(info['complete'])
            self.assertEqual(info['diagnostics']['controller_rejected'], 1)
        # Target Power does not imply source Power: fetch only the remaining
        # source's live faction count, instead of applying Power to both sides.
        loader = Mock(side_effect=lambda name: copy.deepcopy(DETAILS[name]))
        info, rows = run(pve.Criteria(power='Yuri Grom', power_scope='target', min_factions=3),
                         candidate(), power_loader=lambda name: {'target': mapping['target']}, loader=loader)
        self.assertTrue(info['complete'])
        self.assertEqual(rows[0]['factions'], 3)
        loader.assert_called_once_with('Alpha')

    def test_bulk_power_error_does_not_return_empty_or_cnb_fallback(self):
        with self.assertRaises(OSError):
            run(pve.Criteria(power='Yuri Grom'), candidate(sites=(), cnb=True),
                power_loader=Mock(side_effect=OSError('network failure')))

    def test_cached_details_and_pair_deduplication(self):
        loader = Mock(side_effect=lambda name: copy.deepcopy(DETAILS[name]))
        info, rows = run(pve.Criteria(source_controller='Local Government', target_controller='Target Pirates'),
                         candidate(), candidate(), loader=loader)
        self.assertEqual(len(rows), 1)
        self.assertEqual(info['scanned'], 1)
        self.assertEqual(loader.call_count, 2)

    def test_missing_data_does_not_confirm_empty_or_trigger_cnb(self):
        for source in ({}, {'minor_faction_presences': None},
                       {'minor_faction_presences': [dict(name='Unknown')]}):
            info, rows = run(pve.Criteria(min_factions=1), candidate(),
                             candidate('Beta', sites=(), cnb=True),
                             loader=lambda name: source if name == 'Alpha' else copy.deepcopy(DETAILS[name]))
            self.assertFalse(info['complete'])
            self.assertTrue(info['errors'])
            self.assertEqual(rows, [])

    def test_network_errors_not_empty_results(self):
        loader = Mock(side_effect=OSError('HTTP 406'))
        with self.assertRaises(OSError):
            pve.search(pve.Criteria(), page_loader=loader, resolver=lambda name: (name, (0, 0, 0), False))

    def test_stop_prevents_false_fallback_and_zero_requests_if_pre_stopped(self):
        stop = threading.Event()
        stop.set()
        resolver = Mock()
        info, rows = pve.search(pve.Criteria(), stop=stop, resolver=resolver)
        self.assertFalse(info['complete'])
        self.assertEqual(rows, [])
        resolver.assert_not_called()
        stop.clear()
        info, rows = run(None, candidate(sites=(), cnb=True), candidate('Beta'), stop=stop,
                         progress=lambda text: stop.set())
        self.assertFalse(info['complete'])
        self.assertEqual(rows, [])

    def test_stop_during_last_record_does_not_trigger_fallback_or_request_target(self):
        stop = threading.Event()
        def loader(name):
            stop.set()
            return copy.deepcopy(DETAILS[name])
        mocked = Mock(side_effect=loader)
        info, rows = run(pve.Criteria(source_controller='Local Government', target_controller='Target Pirates'),
                         candidate(sites=(), cnb=True), loader=mocked, stop=stop)
        self.assertFalse(info['complete'])
        self.assertEqual(rows, [])
        self.assertEqual(info['errors'], [])
        mocked.assert_called_once_with('Alpha')


if __name__ == '__main__':
    unittest.main()
