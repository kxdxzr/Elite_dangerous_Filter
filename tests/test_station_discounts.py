import unittest
from unittest.mock import patch

import filter_engine as eng
from station_discounts import discount_info


class StationDiscountTests(unittest.TestCase):
    def test_max_rank_personal_weapon_bonus_is_opt_in_and_separate_from_public(self):
        laser = dict(name='Beam Laser', category='hardpoint', weapon_mode='Fixed')
        for power, percent in (('A. Lavigny-Duval', 30), ('Arissa Lavigny-Duval', 30),
                               ('Denton Patreus', 40), ('Jerome Archer', 30), ('Yuri Grom', 30)):
            for state in ('Exploited', 'Fortified', 'Stronghold'):
                row = dict(system_controlling_power=power, system_power_state=state)
                with self.subTest(power=power, state=state):
                    self.assertIsNone(discount_info(row, laser, 'modules')['percent'])
                    info = discount_info(row, laser, 'modules', power)
                    self.assertEqual(info['percent'], percent)
                    self.assertIn('assumed max-rank', info['source'])
                    for changes in (dict(type='Drake-Class Carrier'), dict(system_power_state=''),
                                    dict(system_controlling_power='Li Yong-Rui', system_power_state='Exploited')):
                        self.assertIsNone(discount_info(dict(row, **changes), laser, 'modules', power)['percent'])
                    for item in (dict(name='Cargo Rack'), dict(laser, name='Mining Laser'),
                                 dict(name='Beam Laser')):
                        self.assertIsNone(discount_info(row, item, 'modules', power)['percent'])
        row = dict(system_controlling_power='Arissa Lavigny-Duval', system_power_state='Fortified')
        self.assertEqual(discount_info(row, laser, 'modules', 'A. Lavigny-Duval')['percent'], 30)

    def test_lyr_requires_controlling_power_and_supported_state(self):
        item = dict(name='Anaconda')
        row = dict(system_controlling_power='Li Yong-Rui', system_power_state='Fortified')
        self.assertEqual(discount_info(row, item, 'ships')['percent'], 15)
        for state in ('Exploited', 'Unoccupied', ''):
            self.assertIsNone(discount_info(dict(row, system_power_state=state), item, 'ships')['discounted'])
        self.assertIsNone(discount_info(dict(system_power=['Li Yong-Rui'], system_power_state='Stronghold'),
                                        item, 'ships')['discounted'])
        self.assertIsNone(discount_info(dict(row, type='Drake-Class Carrier'), item, 'ships')['discounted'])

    def test_exact_station_and_product_rules(self):
        row = dict(name='Jameson Memorial', system_name='Shinrarta Dezhra')
        for field in ('ships', 'modules'):
            self.assertEqual(discount_info(row, dict(name='Product'), field)['percent'], 10)
        self.assertIsNone(discount_info(dict(row, system_name='Other'), dict(name='Product'), 'ships')['discounted'])
        irkutsk = dict(name='Irkutsk', system_name='Alioth')
        self.assertEqual(discount_info(irkutsk, dict(name='Asp Explorer'), 'ships')['percent'], 20)
        self.assertIsNone(discount_info(irkutsk, dict(name='Anaconda'), 'ships')['discounted'])

    def test_mahon_standard_goods_only_in_fortified_and_stronghold(self):
        for state in ('Exploited', 'Fortified', 'Stronghold', ''):
            row = dict(system_controlling_power='Edmund Mahon', system_power_state=state)
            for name in ('Cargo Rack', 'Hull Reinforcement Package',
                         'Guardian Hull Reinforcement Package', 'Guardian Shield Reinforcement Package'):
                with self.subTest(state=state, name=name):
                    info = discount_info(row, dict(name=name), 'modules')
                    expected = 20 if state in ('Fortified', 'Stronghold') and not name.startswith('Guardian') else None
                    self.assertEqual(info['percent'], expected)

    def test_product_discount_and_module_specs_must_match_same_item(self):
        row = dict(system_controlling_power='Edmund Mahon', system_power_state='Fortified', modules=[
            dict(name='Cargo Rack', **{'class': 4, 'rating': 'E'}),
            dict(name='Fuel Scoop', **{'class': 5, 'rating': 'A'})])
        condition = dict(field='modules', op='in', values=['Cargo Rack', 'Fuel Scoop'],
                         discounted=True, **{'class': [5]})
        self.assertFalse(eng.match_field('stations', row, condition))
        self.assertTrue(eng.match_field('stations', row, dict(condition, **{'class': [4]})))
        self.assertFalse(eng.match_field('stations', row, dict(condition, values=['Fuel Scoop'])))

    def test_archer_discount_is_inactive_but_independent_station_rules_apply(self):
        laser = dict(name='Beam Laser', category='hardpoint', weapon_mode='Fixed', **{'class': 2})
        for state in ('Exploited', 'Fortified', 'Stronghold'):
            row = dict(system_controlling_power='Jerome Archer', system_power_state=state, modules=[laser])
            with self.subTest(state=state):
                self.assertIsNone(discount_info(row, laser, 'modules')['discounted'])
                self.assertFalse(eng.match_field('stations', row,
                    dict(field='modules', op='in', values=['Beam Laser'], discounted=True)))
                station = dict(row, system_name='CD-43 11917', name='Attilius Orbital')
                info = discount_info(station, laser, 'modules')
                self.assertEqual((info['percent'], info['source']), (30, 'Attilius Orbital'))

    def test_attilius_size_mount_limits(self):
        laser = dict(name='Beam Laser', category='hardpoint', weapon_mode='Fixed', **{'class': 2})
        row = dict(system_name='CD-43 11917', name='Attilius Orbital')
        self.assertEqual(discount_info(row, laser, 'modules')['percent'], 30)
        self.assertIsNone(discount_info(row, dict(laser, **{'class': 3}), 'modules')['discounted'])
        self.assertIsNone(discount_info(row, dict(laser, weapon_mode='Turret'), 'modules')['discounted'])

    def test_missing_goods_cannot_trust_server_for_discount(self):
        condition = dict(field='ships', op='in', values=['Anaconda'], discounted=True)
        self.assertFalse(eng.match_candidate('stations', dict(name='Jameson Memorial', system_name='Shinrarta Dezhra'),
            [condition], {}, {'ships': [{'name': {'value': ['Anaconda']}}]}, set()))

    def test_wiki_expired_sales_and_personal_bonus_are_not_inferred(self):
        for system, station, field, name in (
                ('Lembava', 'Station', 'modules', 'Frame Shift Drive'),
                ('LFT 37', 'Onnes Gateway', 'modules', 'Fuel Scoop'),
                ('LTT 198', 'Torval Orbital', 'modules', 'Mining Laser'),
                ('Other', 'Other', 'ships', 'Anaconda')):
            with self.subTest(system=system, station=station):
                info = discount_info(dict(system_name=system, name=station), dict(name=name), field)
                self.assertIsNone(info['discounted'])

    def test_validation_payload_and_legacy_no_becomes_any(self):
        condition = dict(field='ships', op='=', text='Anaconda', discounted=True)
        payload = eng.build_server_payload('stations', [condition])
        self.assertEqual(payload['filters']['ships'], [{'name': {'value': ['Anaconda']}}])
        self.assertNotIn('discounted', eng.normalize_conditions('stations', [dict(condition, discounted=False)])[0])
        for changes in (dict(field='services'), dict(op='!='), dict(discounted='true')):
            with self.assertRaises(ValueError):
                eng.normalize_conditions('stations', [dict(condition, **changes)])

    def test_search_uses_rules_without_extra_network_or_price_data(self):
        response = dict(count=2, results=[
            dict(id=1, name='Jameson Memorial', system_name='Shinrarta Dezhra', ships=[dict(name='Anaconda')]),
            dict(id=2, name='Other', system_name='Other', ships=[dict(name='Anaconda', price=1)])])
        with patch.object(eng, 'resolve_option_cond'), patch.object(eng, '_http_json', return_value=response) as http:
            rows, _, _ = eng.search('stations', [dict(field='ships', op='=', text='Anaconda', discounted=True)],
                                     want=10, max_pages=1)
        self.assertEqual([r['name'] for r in rows], ['Jameson Memorial'])
        http.assert_called_once()

    def test_table_separates_name_discount_source_and_percent(self):
        from main_csv import export_table
        row = dict(name='Jameson Memorial', system_name='Shinrarta Dezhra', ships=[dict(name='Anaconda')])
        headers, records = export_table([row], 'stations', [dict(field='ships', op='=', text='Anaconda',
            discounted=True)], 'en', lambda x: x)
        self.assertEqual(headers[-3:], ['Matched ships (1)', 'Discount % (1)', 'Discount source (1)'])
        self.assertEqual(records[0][-3:], ['Anaconda', '10', 'Jameson Memorial'])
