import copy
import re
import threading
import unittest
from unittest.mock import patch

import filter_engine as eng
import station_groups as stations
import system_filters as details
from main_csv import export_table
from system_filter_fields import STATION_COUNT_FIELDS
from i18n import translate


def condition(field, value, op='='):
    return dict(field=field, value=str(value), op=op)


def spec(groups, mode='AND'):
    return eng.normalize_conditions('systems', [dict(type='system_details', station_groups=groups,
                                                     station_mode=mode)])[0]


class StationGroupTests(unittest.TestCase):
    def test_all_station_editor_labels_have_english_translations(self):
        for label in stations.FIELDS.values():
            with self.subTest(label=label):
                self.assertIsNone(re.search(r'[\u3400-\u9fff]', translate(label, 'en')))

    def test_same_station_not_combined_across_stations(self):
        groups = [[condition('has_large_pad', 'true'), condition('services', 'Repair'),
                   condition('services', 'Restock'), condition('distance_to_arrival', 1000, '<=')]]
        records = [dict(name='Large', has_large_pad=True, services=['Restock'], distance_to_arrival=10),
                   dict(name='Repair', has_large_pad=False, services=['Repair'], distance_to_arrival=10)]
        self.assertIs(stations.match_groups(records, groups, 'AND')[0], False)
        records.append(dict(name='Both', has_large_pad=True,
                            services=[dict(name='Repair'), dict(name='Restock')], distance_to_arrival=1000))
        hit, evidence = stations.match_groups(records, groups, 'AND')
        self.assertIs(hit, True)
        self.assertEqual(evidence[0]['names'], ['Both'])

    def test_group_modes_different_stations_and_no_groups(self):
        records = [dict(name='A', services=['Repair']), dict(name='B', services=['Restock'])]
        groups = [[condition('services', 'Repair')], [condition('services', 'Restock')]]
        self.assertIs(stations.match_groups(records, groups, 'AND')[0], True)
        groups.append([condition('services', 'Shipyard')])
        self.assertIs(stations.match_groups(records, groups, 'AND')[0], False)
        self.assertIs(stations.match_groups(records, groups, 'OR')[0], True)
        self.assertEqual(stations.match_groups(None, [], 'AND'), (True, []))
        self.assertIs(stations.match_groups([], groups, 'OR')[0], False)

    def test_unknown_never_proves_negative_or_numeric_match(self):
        for c in (condition('services', 'Repair', '!='), condition('type', 'Carrier', 'not in'),
                  condition('has_large_pad', 'true', '!='), condition('distance_to_arrival', 5, 'outside')):
            if c['op'] == 'outside':
                c['value'] = '0|5'
            with self.subTest(c=c):
                self.assertIsNone(stations.match_groups([dict(name='Unknown')], [[c]], 'AND')[0])
        for raw in (float('nan'), float('inf'), True, '10'):
            self.assertIsNone(stations.match_groups([dict(distance_to_arrival=raw)],
                              [[condition('distance_to_arrival', 50, '<')]], 'AND')[0])
        self.assertIsNone(stations.match_groups(None, [[condition('name', 'A')]], 'AND')[0])

    def test_classification_keeps_total_and_excludes_all_carriers(self):
        records = [dict(type='Orbis Starport'), dict(type='Outpost'), dict(type='Planetary Port'),
                   dict(type='Settlement'), dict(type='Drake-Class Carrier'), dict(type='Stronghold Carrier')]
        values = stations.counts(records)
        self.assertEqual(values, dict(station_count=6, carrier_count=2, non_carrier_station_count=4,
                                      orbital_station_count=2, planetary_station_count=2))
        self.assertEqual(stations.counts([]), dict.fromkeys(STATION_COUNT_FIELDS, 0))
        values = stations.counts([{}])
        self.assertEqual(values['station_count'], 1)
        self.assertIsNone(values['non_carrier_station_count'])
        self.assertIsNone(values['orbital_station_count'])
        values = stations.counts([dict(type='Future unknown type')])
        self.assertEqual(values['non_carrier_station_count'], 1)
        self.assertIsNone(values['planetary_station_count'])
        for kind in (None, '', [], {}):
            with self.subTest(kind=kind):
                values = stations.counts([dict(type=kind)])
                self.assertEqual(values['station_count'], 1)
                self.assertIsNone(values['orbital_station_count'])
        values = stations.counts([dict(type='Planetary Outpost', is_planetary=False)])
        self.assertEqual(values['orbital_station_count'], 1)
        self.assertEqual(values['planetary_station_count'], 0)

    def test_carrier_and_planetary_conditions(self):
        groups = [[condition('is_carrier', 'false'), condition('is_planetary', 'false')]]
        records = [dict(name='Carrier', type='Stronghold Carrier'), dict(name='Ground', type='Settlement'),
                   dict(name='Orbital', type='Orbis Starport'), dict(name='Unknown')]
        self.assertEqual(stations.match_groups(records, groups, 'AND')[1][0]['names'], ['Orbital'])

    def test_numeric_ranges_and_in_semantics(self):
        records = [dict(name='A', distance_to_arrival=0, services=['Repair'])]
        for c in (condition('distance_to_arrival', '0|1000', 'between'),
                  condition('distance_to_arrival', '0|10', 'in'),
                  condition('services', 'Repair|Restock', 'in')):
            self.assertIs(stations.match_groups(records, [[c]], 'AND')[0], True)

    def test_invalid_conditions_fail_before_network(self):
        invalid = [dict(station_groups='bad'), dict(station_groups=[[]]),
                   dict(station_groups=[[condition('unknown', 'x')]]),
                   dict(station_groups=[[condition('has_large_pad', 'yes')]]),
                   dict(station_groups=[[condition('distance_to_arrival', 'nan', '<')]]),
                   dict(station_groups=[[condition('distance_to_arrival', '5|2', 'between')]]),
                   dict(station_groups=[[condition('distance_to_arrival', '|', 'outside')]]),
                   dict(station_groups=[[condition('services', 'Repair', '<')]]),
                   dict(station_mode='X')]
        for kw in invalid:
            with self.subTest(kw=kw), patch.object(eng, '_http_json') as fetch, self.assertRaises(ValueError):
                eng.search('systems', [dict(type='system_details', **kw)])
            fetch.assert_not_called()

    def test_full_station_records_used_only_after_cheap_and_count_checks(self):
        c = spec([[condition('is_planetary', 'false'), condition('services', 'Repair')]])
        row = dict(name='A', population=10, stations=[dict(name='Embedded', type='Outpost')])
        original = copy.deepcopy(row)
        with patch.object(eng, '_http_json', return_value={'count': 1, 'results': [row]}), \
                patch.object(details.bodies, 'confirm_station_absence', return_value={
                    'a': [dict(name='Full', is_planetary=False, services=['Repair'])]}) as load:
            rows, _, _ = eng.search('systems', [c])
        load.assert_called_once()
        self.assertEqual(rows[0]['_system_details']['stations'][0]['groups'][0]['names'], ['Full'])
        self.assertEqual(row, original)
        self.assertEqual(eng.build_server_payload('systems', [c])['filters'], {})
        for cheap in (dict(field='population', op='=', text=0), dict(field='station_count', op='=', text=0)):
            with patch.object(eng, '_http_json', return_value={'count': 1, 'results': [row]}), \
                    patch.object(details.bodies, 'confirm_station_absence') as load:
                self.assertEqual(eng.search('systems', [c, cheap])[0], [])
                load.assert_not_called()

    def test_new_counts_use_station_path_not_faction_counts(self):
        conditions = [dict(field=key, op='>=', text=0) for key in STATION_COUNT_FIELDS]
        rows = [dict(name='A', stations=[dict(type='Outpost')])]
        details.prepare(rows, conditions)
        self.assertEqual(rows[0]['station_count'], 1)
        self.assertEqual(rows[0]['non_carrier_station_count'], 1)
        self.assertEqual(rows[0]['planetary_station_count'], 0)

    def test_result_limit_diagnostics_csv_and_cancellation(self):
        c = spec([[condition('services', 'Repair')]])
        candidates = [dict(name='A'), dict(name='B')]
        records = {'a': [dict(name='No', services=[])], 'b': [dict(name='Yes', services=['Repair'])]}
        with patch.object(eng, '_http_json', return_value={'count': 2, 'results': candidates}), \
                patch.object(details.bodies, 'confirm_station_absence', return_value=records):
            rows, _, _ = eng.search('systems', [c], want=1)
            stats, _ = eng.diagnose('systems', [c], pages=1)
        self.assertEqual([r['name'] for r in rows], ['B'])
        self.assertEqual(stats[0][1], 1)
        headers, values = export_table(rows, 'systems', [c], 'en', lambda t: translate(t, 'en'))
        self.assertEqual(headers, ['Name', 'Matched stations (1, by group)'])
        self.assertEqual(values, [['B', '1: Yes']])
        with patch.object(eng, '_http_json', return_value={'count': 2, 'results': candidates}), \
                patch.object(details.bodies, 'confirm_station_absence', side_effect=InterruptedError):
            rows, _, _ = eng.search('systems', [c], stop=threading.Event())
        self.assertEqual(rows, [])


if __name__ == '__main__':
    unittest.main()
