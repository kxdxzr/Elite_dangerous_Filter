import gc
import os
import sys
import time
import unittest
from unittest.mock import patch

import full_outfitting as tool


@unittest.skipUnless(sys.platform == 'win32' or os.environ.get('DISPLAY'), 'Requires a GUI display')
class FullOutfittingGuiTests(unittest.TestCase):
    def setUp(self):
        import filter_gui as gui
        self.patches = [patch.object(gui.fo, 'prefetch_common'),
                        patch.object(gui.fo, 'get_options', return_value=[]),
                        patch.object(gui.App, 'restore_session')]
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

    def test_defaults_localization_and_session_restore(self):
        with patch('outfitting_catalog.load', side_effect=AssertionError('network on open')):
            win = self.app.full_outfitting_window()
        criteria, _, _ = win.criteria()
        self.assertFalse(criteria.other_discounts)
        self.assertFalse(criteria.neutral_ships)
        self.assertFalse(criteria.special_equipment)
        self.assertFalse(criteria.require_discount)
        self.assertEqual(str(win.other_discount_box['state']), 'disabled')
        win.session_variables['neutral_ships'].set(True)
        win.session_variables['guardian'].set(True)
        win.session_variables['special_equipment'].set(True)
        before = win.criteria()
        self.app.set_language('en')
        self.assertEqual(win.title(), 'Full-outfitting discount station finder')
        self.assertEqual(win.criteria(), before)
        self.app._tool_states['full_outfitting'] = self.app._state_dict()['tools']['full_outfitting']
        win.destroy()
        restored = self.app.full_outfitting_window()
        self.assertEqual(restored.criteria(), before)

    def test_worker_result_snapshot_and_result_table_survives_small_window(self):
        win = self.app.full_outfitting_window()
        row = dict(name='Jameson Memorial', system_name='Shinrarta Dezhra', distance=10,
                   _full_outfitting=dict(present=10, required=10, discount_min=10,
                                         discount_max=10, sources=['Jameson Memorial']))
        result = dict(rows=[row], diagnostics=[], notes=[], scanned=1, stopped=False,
                      catalog_revision='test')
        with patch.object(tool, 'search', return_value=result):
            win.run_search()
            until = time.monotonic() + 3
            while win.search_state['busy'] and time.monotonic() < until:
                self.root.update()
                time.sleep(.01)
        self.assertFalse(win.search_state['busy'])
        self.assertEqual(len(win.result_tree.get_children()), 1)
        win.session_variables['reference'].set('Achenar')
        self.app.set_language('en')
        self.assertEqual(win.result_tree.item('0', 'values')[0], 'Shinrarta Dezhra')
        win.geometry('1100x700')
        self.root.update()
        self.assertGreater(win.result_tree.winfo_height(), 100)

    def test_partial_http_failure_keeps_rows_and_export_requires_confirmation(self):
        win = self.app.full_outfitting_window()
        row = dict(name='Station', system_name='Sol', _full_outfitting=dict(
            present=1, required=1, discount_min=15, discount_max=15, sources=['Li Yong-Rui']))
        result = dict(rows=[row], diagnostics=[], notes=[], scanned=1, partial=True,
                      complete=False, errors=[dict(source='LYR 15%', page=2, message='HTTP Error 500')],
                      catalog_revision='test')
        with patch.object(tool, 'search', return_value=result), \
                patch('full_outfitting_gui.messagebox.showerror') as error:
            win.run_search()
            until = time.monotonic() + 3
            while win.search_state['busy'] and time.monotonic() < until:
                self.root.update()
                time.sleep(.01)
        self.assertEqual(len(win.result_tree.get_children()), 1)
        self.assertEqual(win.search_state['result']['errors'][0]['page'], 2)
        error.assert_not_called()
        with patch('full_outfitting_gui.messagebox.askyesno', return_value=False) as confirm, \
                patch('full_outfitting_gui.filedialog.asksaveasfilename') as path:
            win.export_csv()
        confirm.assert_called_once()
        path.assert_not_called()

    def test_jameson_must_be_a_real_search_hit_not_a_fixed_reference(self):
        win = self.app.full_outfitting_window()
        row = dict(name='Jameson Memorial', system_name='Shinrarta Dezhra',
                   _full_outfitting=dict(present=1, required=1, discount_min=10,
                                         discount_max=10, sources=['Jameson Memorial']))
        result = dict(rows=[row], diagnostics=[], notes=[], scanned=1, partial=False,
                      complete=True, errors=[], catalog_revision='test')
        with patch.object(tool, 'search', return_value=result):
            win.run_search()
            until = time.monotonic() + 3
            while win.search_state['busy'] and time.monotonic() < until:
                self.root.update()
                time.sleep(.01)
        self.assertEqual(len(win.result_tree.get_children()), 1)
        self.assertEqual(win.result_tree.set('0', 'name'), 'Jameson Memorial')
        self.assertFalse(hasattr(win, 'reference_text'))

    def test_discount_toggle_retains_other_discount_draft(self):
        win = self.app.full_outfitting_window()
        win.session_variables['other_discounts'].set(True)
        self.assertFalse(win.criteria()[0].require_discount)
        self.assertEqual(str(win.other_discount_box['state']), 'disabled')
        win.session_variables['require_discount'].set(True)
        self.assertEqual(str(win.other_discount_box['state']), 'normal')
        self.assertTrue(win.criteria()[0].other_discounts)
        win.session_variables['require_discount'].set(False)
        self.assertEqual(str(win.other_discount_box['state']), 'disabled')
        self.assertTrue(win.session_variables['other_discounts'].get())
