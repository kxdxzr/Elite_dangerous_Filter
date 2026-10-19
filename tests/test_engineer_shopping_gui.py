import csv
import gc
import io
import os
import sys
import time
import unittest
from unittest.mock import patch, mock_open


@unittest.skipUnless(sys.platform == 'win32' or os.environ.get('DISPLAY'), 'Requires a GUI display')
class EngineerShoppingGuiTests(unittest.TestCase):
    def setUp(self):
        import filter_gui as gui
        self.gui = gui
        self.patches = [patch.object(gui.fo, 'prefetch_common', lambda *a: None),
                        patch.object(gui.fo, 'get_options', return_value=[]),
                        patch.object(gui.App, 'restore_session', lambda *a: None)]
        for item in self.patches:
            item.start()
        self.root = gui.tk.Tk()
        self.root.withdraw()
        self.app = gui.App(self.root)
        self.app._closing = True
        self.errors = []
        self.root.report_callback_exception = lambda *args: self.errors.append(str(args[1]))

    def tearDown(self):
        for callback in self.root.tk.splitlist(self.root.tk.call('after', 'info')):
            self.root.tk.call('after', 'cancel', callback)
        self.root.destroy()
        gc.collect()
        for item in reversed(self.patches):
            item.stop()
        self.assertEqual(self.errors, [])

    def populate(self, win):
        for key, value in dict(origin='LHS 336', destination='Didi Vatermann — Leesti', jump_range='95',
                               max_extra_jumps='2', module='Shield Booster', module_class='0', module_rating='A').items():
            win.session_variables[key].set(value)

    def test_separate_window_carrier_toggle_localization_and_session(self):
        win = self.app.engineer_shopping_window()
        self.populate(win)
        self.assertTrue(win.session_variables['ignore_carriers'].get())
        self.assertFalse(win.session_variables['ignore_planetary'].get())
        conditions, want, pages = win.criteria()
        self.assertEqual((conditions.jump_range, conditions.max_extra_jumps), (95, 2))
        win.session_variables['ignore_carriers'].set(False)
        self.assertFalse(any(c.get('field') == 'type' for c in win.criteria()[0].conditions))
        win.session_variables['ignore_planetary'].set(True)
        self.assertTrue(any(c.get('field') == 'is_planetary' and c['op'] == 'false'
                            for c in win.criteria()[0].conditions))
        before = win.criteria()
        self.app.set_language('en')
        self.assertEqual(win.title(), 'Engineer trip shopping')
        self.assertEqual(before, win.criteria())
        self.app._tool_states['engineer_shopping'] = self.app._state_dict()['tools']['engineer_shopping']
        win.destroy()
        restored = self.app.engineer_shopping_window()
        self.assertFalse(restored.session_variables['ignore_carriers'].get())
        self.assertTrue(restored.session_variables['ignore_planetary'].get())
        self.assertEqual(before, restored.criteria())
        self.assertEqual(self.app.rows, [])

    def test_destination_is_readonly_engineer_list_and_legacy_sessions_are_checked(self):
        from engineer_destinations import CHOICES
        self.app._tool_states['engineer_shopping'] = {'destination': 'Leesti'}
        win = self.app.engineer_shopping_window()
        self.assertEqual(str(win.destination_box['state']), 'readonly')
        self.assertFalse(win.session_variables['ignore_planetary'].get())
        self.assertEqual(tuple(win.destination_box['values']), CHOICES)
        self.assertEqual(win.session_variables['destination'].get(), 'Didi Vatermann — Leesti')
        self.populate(win)
        win.session_variables['destination'].set('Felicity Farseer — Deciat')
        self.assertEqual(win.criteria()[0].destination, 'Deciat')
        self.app.set_language('en')
        self.assertEqual(win.session_variables['destination'].get(), 'Felicity Farseer — Deciat')
        win.session_variables['destination'].set('LHS 336')
        with self.assertRaises(ValueError):
            win.criteria()
        win.destroy()
        self.app._tool_states['engineer_shopping'] = {'destination': 'LHS 336'}
        restored = self.app.engineer_shopping_window()
        self.assertEqual(restored.session_variables['destination'].get(), '')

    def test_pad_selector_is_localized_readonly_and_survives_reopen(self):
        win = self.app.engineer_shopping_window()
        self.populate(win)
        self.assertEqual(str(win.landing_pad_box['state']), 'readonly')
        self.assertEqual(tuple(win.landing_pad_box['values']), ('不限', 'S', 'M', 'L'))
        self.assertEqual(win.criteria()[0].landing_pad, '')
        win.session_variables['landing_pad'].set('M')
        before = win.criteria()
        self.app.set_language('en')
        self.assertEqual(tuple(win.landing_pad_box['values']), ('Any', 'S', 'M', 'L'))
        self.assertEqual(win.landing_pad_box.get(), 'M')
        self.assertEqual(win.criteria(), before)
        self.app._tool_states['engineer_shopping'] = self.app._state_dict()['tools']['engineer_shopping']
        win.destroy()
        restored = self.app.engineer_shopping_window()
        self.assertEqual(restored.session_variables['landing_pad'].get(), 'M')
        self.assertEqual(restored.criteria(), before)

    def test_old_or_invalid_saved_pad_defaults_to_any(self):
        for state in ({}, {'landing_pad': 'XL'}, {'landing_pad': ''}):
            self.app._tool_states['engineer_shopping'] = state
            win = self.app.engineer_shopping_window()
            self.assertEqual(win.session_variables['landing_pad'].get(), '不限')
            win.destroy()

    def test_pledged_power_defaults_max_rank_and_survives_language_and_reopen(self):
        win = self.app.engineer_shopping_window()
        self.populate(win)
        self.assertEqual(win.session_variables['pledged_power'].get(), '无')
        self.assertTrue(win.session_variables['assume_max_rank'].get())
        self.app.set_language('en')
        self.assertEqual(win.pledged_power_box._display.get(), 'None')
        self.app.set_language('zh')
        self.assertEqual(str(win.pledged_power_box['state']), 'readonly')
        win.session_variables['pledged_power'].set('Jerome Archer')
        criteria = win.criteria()[0]
        self.assertEqual(criteria.pledged_power, 'Jerome Archer')
        self.assertEqual(criteria.conditions[0]['personal_power'], 'Jerome Archer')
        self.app.set_language('en')
        self.assertIn('maximum-rank', win.personal_discount_note.cget('text'))
        self.assertEqual(win.criteria()[0], criteria)
        win.session_variables['assume_max_rank'].set(False)
        self.assertNotIn('personal_power', win.criteria()[0].conditions[0])
        self.app._tool_states['engineer_shopping'] = self.app._state_dict()['tools']['engineer_shopping']
        win.destroy()
        restored = self.app.engineer_shopping_window()
        self.assertEqual(restored.session_variables['pledged_power'].get(), 'Jerome Archer')
        self.assertFalse(restored.session_variables['assume_max_rank'].get())

    def test_single_spec_selector_and_saved_raw_spec_draft(self):
        win = self.app.engineer_shopping_window()
        self.populate(win)
        row = win.purchase_row
        row.val.set('Plasma Accelerator')
        row.v_class.set('')
        row.v_rating.set('')
        row._refresh_spec_options()
        self.assertEqual(tuple(row.cb_spec['values']), ('不限', '2C', '3B', '4A'))
        row.v_spec.set('2C')
        module = win.criteria()[0].conditions[0]
        self.assertEqual((module['class'], module['rating']), ([2], ['C']))
        row.v_spec.set('2 unfinished')
        saved = self.app._state_dict()['tools']['engineer_shopping']
        win.destroy()
        self.app._tool_states['engineer_shopping'] = saved
        restored = self.app.engineer_shopping_window()
        self.assertEqual(restored.purchase_row.v_spec.get(), '2 unfinished')
        with self.assertRaises(ValueError):
            restored.criteria()

    def test_search_separate_columns_csv_and_edited_form_keeps_result_snapshot(self):
        import engineer_shopping as tool
        import engineer_shopping_gui as ui
        win = self.app.engineer_shopping_window()
        self.populate(win)
        win.session_variables['landing_pad'].set('L')
        win.add_purchase(dict(value='Plasma Accelerator', module_spec='2C', discount='是'))
        conditions = win.criteria()[0].conditions
        conditions += [dict(type='distance', ref_system=ref, min_ly=None, max_ly=1000, mode='inside')
                       for ref in ('LHS 336', 'Leesti')]
        result = dict(rows=[dict(name='Shop', system_name='Shopping', type='Coriolis Starport',
                                 distance_to_arrival=1234.56, has_large_pad=True,
                                 _distances={'Leesti': 40, 'LHS 336': 60},
                                _shopping_route=dict(direct_jumps=2, origin_jumps=1, destination_jumps=1,
                                                     total_jumps=2, extra_jumps=0, detour_ly=0),
                                system_controlling_power='Li Yong-Rui', system_power_state='Fortified',
                                modules=[dict(name='Shield Booster', **{'class': 0, 'rating': 'A'}),
                                         dict(name='Plasma Accelerator', **{'class': 2, 'rating': 'C'})])],
                      conditions=conditions, landing_pad='L', scanned=10, total=10, notes=['候选分页已取完'], stopped=False)
        with patch.object(tool, 'search', return_value=result) as search:
            win.run_search()
            deadline = time.monotonic() + 3
            while win.search_state['busy'] and time.monotonic() < deadline:
                self.root.update()
                time.sleep(.01)
        search.assert_called_once()
        self.assertFalse(win.search_state['busy'])
        tree = win.result_tree
        values = tree.item(tree.get_children()[0], 'values')
        self.assertEqual(values[2:7], ('Shield Booster', '0', 'A', '15', 'Li Yong-Rui'))
        self.assertEqual(values[7:12], ('Plasma Accelerator', '2', 'C', '15', 'Li Yong-Rui'))
        self.assertEqual(values[-6:], ('2', '1', '1', '2', '0', '0.00'))
        win.session_variables['origin'].set('Edited')
        win.session_variables['max_extra_jumps'].set('99')
        win.session_variables['ignore_carriers'].set(False)
        win.session_variables['landing_pad'].set('S')
        self.app.set_language('en')
        headers = [tree.heading(key, 'text') for key in tree['columns']]
        self.assertIn('Arrival distance ls', headers)
        self.assertIn('Distance to Leesti (ly)', headers)
        self.assertIn('Estimated extra jumps', headers)
        self.assertIn('Matched modules (2)', headers)
        self.assertIn('Confirmed landing pad', headers)
        self.assertEqual(win.search_state['result']['landing_pad'], 'L')
        self.assertNotIn('Distance to Edited (ly)', headers)
        output = mock_open()
        with patch.object(ui.filedialog, 'asksaveasfilename', return_value='shopping.csv'), \
                patch('builtins.open', output):
            win.export_csv()
        contents = ''.join(call.args[0] for call in output().write.call_args_list)
        self.assertFalse(any('\u3400' <= ch <= '\u9fff' for ch in contents))
        exported = list(csv.reader(io.StringIO(contents)))[6:]
        self.assertEqual(exported[0], headers)
        self.assertEqual(exported[1], list(tree.item(tree.get_children()[0], 'values')))

    def test_shopping_list_add_remove_and_session_roundtrip_with_independent_drafts(self):
        win = self.app.engineer_shopping_window()
        self.populate(win)
        second = win.add_purchase(dict(value='Plasma Accelerator', module_spec='2C', discount='不限'))
        self.assertEqual(len(win.purchase_rows), 2)
        conditions = win.criteria()[0].conditions
        self.assertEqual([c['values'] for c in conditions[:2]], [['Shield Booster'], ['Plasma Accelerator']])
        self.assertEqual([c['class'] for c in conditions[:2]], [[0], [2]])
        self.assertTrue(conditions[0]['discounted'])
        self.assertNotIn('discounted', conditions[1])
        before = win.criteria()
        self.app.set_language('en')
        self.assertEqual(before, win.criteria())
        # Drafts are saved without forcing validation or applying another row's spec.
        second.v_spec.set('unfinished')
        saved = self.app._state_dict()['tools']['engineer_shopping']
        win.destroy()
        self.app._tool_states['engineer_shopping'] = saved
        restored = self.app.engineer_shopping_window()
        self.assertEqual(len(restored.purchase_rows), 2)
        self.assertEqual(restored.purchase_rows[1].v_spec.get(), 'unfinished')
        self.assertEqual(restored.purchase_rows[1].v_discount.get(), '不限')
        restored.purchase_rows[1].v_spec.set('2C')
        self.assertEqual(before, restored.criteria())
        restored.remove_purchase(restored.purchase_rows[0])
        self.assertEqual(len(restored.purchase_rows), 1)
        self.assertIs(restored.purchase_row, restored.purchase_rows[0])
        self.assertEqual(restored.criteria()[0].conditions[0]['values'], ['Plasma Accelerator'])
        restored.remove_purchase(restored.purchase_rows[0])
        with self.assertRaises(ValueError):
            restored.criteria()

    def test_shopping_list_is_saved_when_window_is_closed(self):
        win = self.app.engineer_shopping_window()
        self.populate(win)
        win.add_purchase(dict(value='Plasma Accelerator', module_spec='2C'))
        self.app._closing = False
        with patch.object(self.app, 'save_session', return_value=True):
            win.destroy()
        self.app._closing = True
        self.assertNotIn('engineer_shopping', self.app._tool_collectors)
        restored = self.app.engineer_shopping_window()
        self.assertEqual(len(restored.purchase_rows), 2)
        self.assertEqual(restored.criteria()[0].conditions[1]['values'], ['Plasma Accelerator'])
