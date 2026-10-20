import unittest
import urllib.parse
from unittest.mock import patch

import full_outfitting as tool
import outfitting_catalog as catalog
import outfitting_identity as identity
import filter_engine as engine


class OutfittingIdentityTests(unittest.TestCase):
    def setUp(self):
        self.base = dict(ed_id=128049456, ed_symbol='Hpt_MultiCannon_Fixed_Medium',
                         name='Multi-Cannon', category='hardpoint', **{'class': 2, 'rating': 'E'})
        self.special = dict(self.base, ed_id=129045433, category='mercgear', name='Rapid Phase Multi-Cannon')
        self.facts = [self.base, self.special]

    def test_two_numeric_ids_are_not_two_aliases_of_one_product(self):
        self.assertNotEqual(catalog.variant(self.base), catalog.variant(self.special))
        normalized = identity.normalize_stock([dict(self.special)], self.facts)
        self.assertEqual(tool.inventory_key(normalized[0]), ('fdev_id', 129045433))
        prepared = catalog.prepare(dict(items=[self.base], special_items=[self.special], module_facts=self.facts))
        self.assertEqual(prepared['conflicts'], [])
        self.assertEqual(len(prepared['shared_symbols']), 1)

    def test_edsm_seeker_label_is_an_audited_name_format_not_a_merc_alias(self):
        self.assertEqual(identity.name_key('3A Missile Rack (Seeker, Fixed)'),
                         identity.name_key('Seeker Missile Rack'))
        self.assertNotEqual(identity.name_key('2B Lockdown Seeker Missile Rack'),
                            identity.name_key('Seeker Missile Rack'))
        seeker = dict(ed_id=10, ed_symbol='Hpt_BasicMissileRack_Fixed_Large',
                      name='Seeker Missile Rack', category='hardpoint', **{'class': 3, 'rating': 'A'})
        merc = dict(seeker, ed_id=11, category='mercgear', name='Exposing Missiles')
        response = dict(marketId=1, name='System', sName='Station', outfitting=[dict(
            id='hpt_basicmissilerack_fixed_large', name='3A Missile Rack (Seeker, Fixed)')])
        stock = identity.edsm_stock(dict(market_id=1, name='Station', system_name='System'),
                                    [seeker, merc], lambda *args: response)
        self.assertEqual([item['ed_id'] for item in stock], [10])
        self.assertEqual(stock[0]['weapon_mode'], 'Fixed')

    def test_symbol_only_merc_label_does_not_prove_base_or_special_stock(self):
        raw = {key: value for key, value in self.special.items() if key != 'ed_id'}
        item = identity.normalize_stock([raw], self.facts)[0]
        self.assertTrue(item['identity_ambiguous'])
        self.assertIsNone(tool.inventory_key(item))

    def test_stale_class_rating_descriptions_do_not_create_duplicate_products(self):
        raw = dict(self.base, **{'rating': 'F'})
        prepared = identity.canonical_catalog(dict(items=[raw, self.base], issues=[]), self.facts,
                                               catalog.ordinary, catalog.restricted_spec)
        self.assertEqual(len(prepared['items']), 1)
        self.assertEqual(prepared['items'][0]['rating'], 'E')

    def test_engineer_only_sizes_are_not_general_retail_requirements(self):
        self.assertTrue(catalog.restricted_spec('Shield Generator', 1))
        self.assertTrue(catalog.restricted_spec('Frame Shift Drive', 8))
        self.assertFalse(catalog.restricted_spec('Frame Shift Drive (SCO)', 8))
        self.assertFalse(catalog.ordinary('Caustic Sink Launcher'))

    def test_second_source_must_match_market_system_and_station(self):
        row = dict(market_id=123, system_name='System', name='Station')
        response = dict(marketId=123, name='System', sName='Station',
                        outfitting=[dict(id=self.base['ed_symbol'].lower(), name='2E Multi-Cannon (Fixed)')])
        result = identity.edsm_stock(row, self.facts, lambda *args: response)
        self.assertEqual([item['ed_id'] for item in result], [self.base['ed_id']])
        self.assertNotIn(self.special['ed_id'], [item['ed_id'] for item in result])
        response['marketId'] = 456
        with self.assertRaises(ValueError):
            identity.edsm_stock(row, self.facts, lambda *args: response)

    def test_same_rule_qualifies_jameson_and_other_public_discount_stations(self):
        raw = {key: value for key, value in self.special.items() if key != 'ed_id'}
        data = dict(items=[self.base], special_items=[self.special], module_facts=self.facts,
                    issues=[], ships=[], armours=[], special_issues=[])
        for name, system, power in [('Jameson Memorial', 'Shinrarta Dezhra', ''),
                                     ('Independent test station', 'Other system', 'Li Yong-Rui')]:
            row = dict(name=name, system_name=system, type='Orbis Starport', modules=[raw],
                       system_controlling_power=power, system_power_state='Fortified')
            criteria = tool.build_criteria('Sol', 500, other_discounts=True)
            before = tool.check_station(row, criteria, data)
            self.assertFalse(before['matched'])
            row['_edsm_modules'] = [dict(self.base, identity_source='EDSM named stock')]
            after = tool.check_station(row, criteria, data)
            self.assertTrue(after['matched'])
            self.assertFalse(tool.check_station(row, tool.build_criteria('Sol', 500,
                             other_discounts=True, special_equipment=True), data)['matched'])

    def test_normal_search_automatically_cross_checks_any_nearly_complete_station(self):
        raw = {key: value for key, value in self.special.items() if key != 'ed_id'}
        data = dict(items=[self.base], special_items=[self.special], module_facts=self.facts,
                    issues=[], ships=[], armours=[], special_issues=[])
        stations = {
            '123': dict(name='Jameson Memorial', system_name='Shinrarta Dezhra', type='Orbis Starport',
                        id='123', market_id=123, modules=[raw]),
            '456': dict(name='Other station', system_name='Other system', type='Orbis Starport',
                        id='456', market_id=456, modules=[raw], system_controlling_power='Li Yong-Rui',
                        system_power_state='Fortified')}

        def http(url, payload=None):
            if 'spansh.co.uk' in url:
                return dict(results=[])
            market = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)['marketId'][0]
            row = stations[market]
            return dict(marketId=int(market), name=row['system_name'], sName=row['name'],
                        outfitting=[dict(id=self.base['ed_symbol'], name='2E Multi-Cannon (Fixed)')])

        def search(kind, conditions, **kwargs):
            named = any(item.get('field') == 'name' for item in conditions)
            row = dict(stations['123' if named else '456'])
            self.assertTrue(kwargs['row_filter'](row))
            kwargs['notes'].append('候选分页已取完')
            return [row], 1, 1

        with patch.object(engine, 'search', side_effect=search), patch.object(engine, '_http_json', side_effect=http) as fetch:
            result = tool.search(tool.build_criteria('Sol', 500, other_discounts=True, require_discount=True), catalog=data)
        self.assertEqual(len(result['rows']), 2)
        self.assertEqual(sum('edsm.net' in call.args[0] for call in fetch.call_args_list), 2)
        self.assertTrue(all(row['_full_outfitting']['matched'] for row in result['rows']))
        self.assertTrue(all('EDSM（未提供库存时间）' in row['_stock_sources'] for row in result['rows']))
