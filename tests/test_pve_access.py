import copy
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import pve_access as access
import pve_cache
import pve_tool as pve
from test_pve_tool import candidate, page, DETAILS, run


def station(name='Port', size='L', distance=100, **kw):
    return dict(name=name, type='Coriolis Starport', services=['Missions'],
                small_pads=1 if size == 'S' else 0, medium_pads=1 if size == 'M' else 0,
                large_pads=1 if size == 'L' else 0, distance_to_arrival=distance, **kw)


class AccessTests(unittest.TestCase):
    def test_unknown_sites_checked_without_distance_limit_and_ring_free_allows_cnb(self):
        rings = Mock(return_value={'target': dict(seen=True, uncertain=False, has_rings=False,
                                                distance=None, body='')})
        info, rows = run(None, candidate(sites=(), rings=None),
                         candidate('Beta', target='CNB Target', sites=(), cnb=True), ring_loader=rings)
        rings.assert_called_once_with(['Target'])
        self.assertEqual(info['mode'], 'CNB')
        self.assertEqual([row['target'] for row in rows], ['CNB Target'])
        self.assertEqual(info['diagnostics']['target_no_rings'], 1)
        self.assertEqual(info['diagnostics']['unknown_sites'], 0)

    def test_unknown_site_with_rings_but_unknown_distance_is_inferred_not_low(self):
        info, rows = run(None, candidate(sites=(), rings=None), ring_loader=lambda names: {
            'target': dict(seen=True, uncertain=True, has_rings=True, distance=None, body='')})
        self.assertEqual(rows[0]['site'], 'RES（星环推定）')
        self.assertIn('Spansh: rings found', rows[0]['site_record'])
        self.assertEqual(info['inferred_res'], 1)

    def test_failed_or_incomplete_ring_lookup_preserves_unknown_and_blocks_cnb(self):
        for loader in (Mock(side_effect=ValueError('offline')), lambda names: {},
                       lambda names: {'target': dict(seen=False, uncertain=False, has_rings=False)},
                       lambda names: {'target': dict(seen=True, uncertain=True, has_rings=False)}):
            info, rows = run(None, candidate(sites=(), rings=None),
                             candidate('Beta', sites=(), cnb=True), ring_loader=loader)
            self.assertEqual([row['site'] for row in rows], ['情况未知'])
            self.assertEqual(info['mode'], 'Unknown')

    def test_body_ring_presence_does_not_require_known_arrival_distance(self):
        response = {'results': [dict(system_name='Target', name='Ringed', rings=[{}])]}
        with tempfile.TemporaryDirectory() as folder, \
                patch.object(pve_cache, 'data_file', side_effect=lambda name: Path(folder) / name), \
                patch.object(access.eng, '_http_json', return_value=response):
            pve_cache.clear_memory()
            try:
                record = access.ring_distances(['Target'])['target']
                self.assertTrue(record['has_rings'])
                self.assertTrue(record['uncertain'])
                self.assertIsNone(record['distance'])
            finally:
                pve_cache.clear_memory()

    def test_station_constraints_must_match_same_station(self):
        data = {'stations': [station('Far Large', 'L', 1000), station('Near Medium', 'M', 50)]}
        self.assertIsNone(access.station_match(data, 'L', 100))
        self.assertEqual(access.station_match(data, 'M', 100)['source_station'], 'Near Medium')
        self.assertEqual(access.station_match(data, 'S', 100)['source_station'], 'Near Medium')
        self.assertEqual(access.station_match(data, 'L', 1000)['source_station'], 'Far Large')

    def test_pad_alone_does_not_require_distance_and_zero_is_real_limit(self):
        data = {'stations': [station(distance=None)]}
        self.assertEqual(access.station_match(data, 'L')['source_station_ls'], '情况未知')
        with self.assertRaises(ValueError):
            access.station_match(data, 'L', 0)
        self.assertIsNone(access.station_match({'stations': [station(distance=1)]}, '', 0))
        self.assertIsNotNone(access.station_match({'stations': [station(distance=0)]}, '', 0))

    def test_carriers_non_mission_stations_and_colony_ships_excluded(self):
        stations = [dict(station(), type='Fleet Carrier'), dict(station(), type='Colonisation Ship'),
                    dict(station(), services=['Dock']), dict(station(), name='System Colonisation Ship', type='Planetary Outpost'),
                    dict(station(), real_name='$EXT_PANEL_ColonisationShip;', type='Planetary Outpost'),
                    dict(station(), name='Stronghold Carrier', type='Mega ship')]
        self.assertIsNone(access.station_match({'stations': stations}, 'L', 100))

    def test_missing_data_does_not_confirm_absence(self):
        for data in ({}, {'stations': None}, {'stations': [{'name': 'Unknown'}]}):
            with self.assertRaises(ValueError):
                access.station_match(data, 'L', 100)
        self.assertIsNone(access.station_match({'stations': []}, 'L', 100))
        # Missing unrelated fields do not make a provably too-far station an
        # unknown potential match, nor a known medium-only pad for a large ship.
        self.assertIsNone(access.station_match({'stations': [dict(name='Far', distance_to_arrival=1000)]}, 'L', 100))
        self.assertIsNone(access.station_match({'stations': [dict(name='Medium', has_large_pad=False)]}, 'L', 100))

    def test_search_station_and_ring_and_other_filters(self):
        source = copy.deepcopy(DETAILS['Alpha'])
        source['stations'] = [station()]
        loader = Mock(side_effect=lambda name: source)
        rings = Mock(return_value={'target': dict(seen=True, uncertain=False, distance=500, body='Target 2')})
        info, rows = run(pve.Criteria(source_pad='L', source_station_max_ls=100,
                                     target_ring_max_ls=500, min_factions=3), candidate(), loader=loader, ring_loader=rings)
        self.assertTrue(info['complete'])
        self.assertEqual(rows[0]['source_station'], 'Port')
        self.assertEqual(rows[0]['target_ring_ls'], 500)
        self.assertEqual(rows[0]['site'], 'RES Low')
        self.assertEqual(run(pve.Criteria(source_pad='L', source_station_max_ls=99), candidate(), loader=loader)[1], [])

    def test_unknown_rings_and_stop_never_return_unfiltered_hits(self):
        info, rows = run(pve.Criteria(target_ring_max_ls=500), candidate(), ring_loader=lambda names: {})
        self.assertFalse(info['complete'])
        self.assertEqual(rows, [])
        stop = threading.Event()
        def loader(name):
            stop.set()
            return DETAILS['Alpha']
        info, rows = run(pve.Criteria(min_factions=1, target_ring_max_ls=500), candidate(), loader=loader, stop=stop)
        self.assertFalse(info['complete'])
        self.assertEqual(rows, [])

    def test_ring_distance_rejects_known_far_and_promotes_unknown_when_verified(self):
        def rings(names):
            return {'target': dict(seen=True, uncertain=False, distance=200, body='Target 1')}
        info, rows = run(pve.Criteria(target_ring_max_ls=199), candidate(), ring_loader=rings)
        self.assertTrue(info['complete'])
        self.assertEqual(rows, [])
        self.assertEqual(info['diagnostics']['target_ring_rejected'], 1)
        info, rows = run(pve.Criteria(target_ring_max_ls=200), candidate(sites=(), rings=None), ring_loader=rings)
        self.assertEqual(rows[0]['site'], 'RES（星环推定）')

    def test_validation_before_network_and_off_by_default(self):
        for args in ({'source_pad': 'X'}, {'source_station_max_ls': -1}, {'target_ring_max_ls': float('nan')},
                     {'target_ring_max_ls': True}):
            resolver = Mock()
            with self.assertRaises(ValueError):
                pve.search(pve.Criteria(**args), resolver=resolver)
            resolver.assert_not_called()
        loader, rings = Mock(), Mock()
        info, rows = run(None, candidate(), loader=loader, ring_loader=rings)
        self.assertEqual(len(rows), 1)
        loader.assert_not_called()
        rings.assert_not_called()

    def test_full_body_endpoint_batch_nearest_and_cache(self):
        response = {'results': [dict(system_name='Target', name='Far', id64=1, rings=[{}], distance_to_arrival=500),
                                dict(system_name='Target', name='Near', id64=2, rings=[{}], distance_to_arrival=100),
                                dict(system_name='Other', name='Planet', id64=3)]}
        with tempfile.TemporaryDirectory() as folder, \
                patch.object(pve_cache, 'data_file', side_effect=lambda name: Path(folder) / name), \
                patch.object(access.eng, '_http_json', return_value=response) as http:
            pve_cache.clear_memory()
            try:
                result = access.ring_distances(['Target', 'Other'])
                self.assertEqual(result['target']['body'], 'Near')
                self.assertEqual(result['target']['distance'], 100)
                self.assertTrue(result['other']['seen'])
                self.assertIsNone(result['other']['distance'])
                self.assertEqual(access.ring_distances(['Other', 'Target']), result)
                http.assert_called_once()
                self.assertTrue(http.call_args.args[0].endswith('/bodies/search'))
                self.assertEqual(set(http.call_args.args[1]['filters']['system_name']['value']), {'Target', 'Other'})
            finally:
                pve_cache.clear_memory()

    def test_body_schema_error_and_repeated_pages_never_confirm_ring_absence(self):
        with tempfile.TemporaryDirectory() as folder, \
                patch.object(pve_cache, 'data_file', side_effect=lambda name: Path(folder) / name):
            pve_cache.clear_memory()
            try:
                with patch.object(access.eng, '_http_json', return_value={'results': [{'name': 'Missing system'}]}):
                    with self.assertRaises(ValueError):
                        access.ring_distances(['Target'])
                rows = [dict(system_name='Target', name=str(i), id64=i) for i in range(500)]
                with patch.object(access.eng, '_http_json', side_effect=[{'results': rows}, {'results': rows}]):
                    with self.assertRaisesRegex(ValueError, 'repeated'):
                        access.ring_distances(['Target'])
            finally:
                pve_cache.clear_memory()


if __name__ == '__main__':
    unittest.main()
