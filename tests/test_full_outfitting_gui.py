import gc
import csv
from datetime import datetime, timezone
import os
import sys
import time
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

import full_outfitting as tool
import outfitting_snapshot


class CacheAgeTextTests(unittest.TestCase):
    def test_days_are_elapsed_24_hour_periods_not_file_modification_time(self):
        from full_outfitting_gui import cache_age_text
        now = datetime(2026, 10, 20, 12, tzinfo=timezone.utc)
        self.assertEqual(cache_age_text('2026-10-17T12:00:00Z', now=now), '缓存于（3）天之前')
        self.assertEqual(cache_age_text('2026-10-20T08:00:00+00:00', now=now), '缓存于（0）天之前')
        self.assertEqual(cache_age_text('2026-10-18T20:00:00+08:00', now=now), '缓存于（2）天之前')
        self.assertEqual(cache_age_text(None, now=now), '暂无缓存')
        self.assertEqual(cache_age_text('bad', now=now), '缓存时间无效，请更新数据')
        self.assertEqual(cache_age_text('2026-10-17T12:00:00', now=now), '缓存时间无效，请更新数据')


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
        self.assertFalse(criteria.ax_weapons)
        self.assertFalse(criteria.universal_limpets)
        self.assertEqual(win.cache_notice_font.actual('weight'), 'bold')
        self.assertIsNot(win.cache_age_label.master, win)
        self.assertIn('首次扫描需要建立缓存', str(win.cache_notice['text']))
        self.assertEqual(str(win.other_discount_box['state']), 'disabled')
        win.session_variables['neutral_ships'].set(True)
        win.session_variables['guardian'].set(True)
        win.session_variables['special_equipment'].set(True)
        win.session_variables['universal_limpets'].set(True)
        before = win.criteria()
        self.app.set_language('en')
        self.assertIn('The first scan builds the cache', str(win.cache_notice['text']))
        self.assertEqual(win.title(), 'Find fully outfitted stations')
        self.assertEqual(win.criteria(), before)
        self.app._tool_states['full_outfitting'] = self.app._state_dict()['tools']['full_outfitting']
        win.destroy()
        restored = self.app.full_outfitting_window()
        self.assertEqual(restored.criteria(), before)

    def test_english_controls_have_space_and_preserve_values(self):
        win = self.app.full_outfitting_window()
        before = win.criteria()
        self.app.set_language('en')
        win.geometry('1100x820')
        self.root.update()
        for entry in win.criteria_entries.values():
            self.assertEqual(int(entry.grid_info()['row']), 1)
            self.assertGreaterEqual(int(entry.cget('width')), 12)
        self.assertEqual({(int(c.grid_info()['row']), int(c.grid_info()['column']))
                          for c in win.ship_choices}, {(0, 0), (0, 1), (1, 0), (1, 1)})
        for choice in win.ship_choices:
            self.assertGreaterEqual(choice.winfo_width(), choice.winfo_reqwidth())
        self.assertEqual(win.criteria(), before)

    def test_worker_result_snapshot_and_result_table_survives_small_window(self):
        win = self.app.full_outfitting_window()
        row = dict(name='Jameson Memorial', system_name='Shinrarta Dezhra', distance=10,
                   _full_outfitting=dict(present=10, required=10, discount_min=10,
                                         discount_max=10, sources=['Jameson Memorial']))
        result = dict(rows=[row], diagnostics=[], notes=[], scanned=1, stopped=False,
                      catalog_revision='test')
        with patch.object(outfitting_snapshot, 'search', return_value=result):
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

    def test_catalog_update_confirmation_does_not_mutate_existing_results(self):
        win = self.app.full_outfitting_window()
        snapshot = dict(rows=[], diagnostics=[], notes=[], scanned=0, catalog_revision='old')
        win.search_state['result'] = snapshot
        with patch('catalog_updates.check', return_value=dict(version='2026.10.20.1', summary='test')), \
                patch('catalog_updates.read_package', return_value=None), \
                patch('full_outfitting_gui.messagebox.askyesno', return_value=False) as confirm, \
                patch('catalog_updates.install') as install:
            win.update_catalog()
            until = time.monotonic() + 3
            while win.search_state['updating'] and time.monotonic() < until:
                self.root.update()
                time.sleep(.01)
            confirm.assert_called_once()
            install.assert_not_called()
        self.assertIs(win.search_state['result'], snapshot)
        self.assertFalse(win.search_state['updating'])

    def test_csv_preamble_uses_search_snapshot_not_edited_form(self):
        win = self.app.full_outfitting_window()
        row = dict(name='Station', system_name='Sol', _full_outfitting=dict(
            present=1, required=1, discount_min=15, discount_max=15, sources=['Li Yong-Rui']))
        win.search_state['result'] = dict(rows=[row], criteria=vars(tool.build_criteria('Sol', 500)),
                                          search_limits=dict(want=50, max_pages=25))
        win.session_variables['reference'].set('Achenar')
        win.session_variables['radius'].set('100')
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'result.csv'
            with patch('full_outfitting_gui.filedialog.asksaveasfilename', return_value=str(path)):
                win.export_csv()
            with path.open(encoding='utf-8-sig', newline='') as file:
                rows = list(csv.reader(file))
        separator = rows.index([])
        conditions = rows[separator - 1]
        self.assertEqual(conditions[0], '# 检索条件')
        self.assertIn('参考星系: Sol', conditions[1])
        self.assertIn('检索半径 ly: 500', conditions[1])
        self.assertNotIn('Achenar', conditions[1])
        self.assertEqual(rows[separator + 1][0], '星系')
        metadata = {row[0]: row[1] for row in rows[:separator]}
        for label in ('特殊装备条件', '库存核验来源', '物品ID目录版本', '折扣要求', 'AX装备条件'):
            self.assertIn('# ' + label, metadata)
            self.assertNotIn(label, rows[separator + 1])

    def test_failed_data_update_keeps_previous_displayed_result(self):
        win = self.app.full_outfitting_window()
        previous = dict(rows=[], catalog_revision='previous')
        win.search_state['result'] = previous
        with patch.object(outfitting_snapshot, 'search', side_effect=ValueError('Update incomplete')), \
                patch('full_outfitting_gui.messagebox.showerror') as error:
            win.run_search(True)
            until = time.monotonic() + 3
            while win.search_state['busy'] and time.monotonic() < until:
                self.root.update()
                time.sleep(.01)
            error.assert_called_once()
        self.assertIs(win.search_state['result'], previous)

    def test_partial_http_failure_keeps_rows_and_export_requires_confirmation(self):
        win = self.app.full_outfitting_window()
        row = dict(name='Station', system_name='Sol', _full_outfitting=dict(
            present=1, required=1, discount_min=15, discount_max=15, sources=['Li Yong-Rui']))
        result = dict(rows=[row], diagnostics=[], notes=[], scanned=1, partial=True,
                      complete=False, errors=[dict(source='LYR 15%', page=2, message='HTTP Error 500')],
                      catalog_revision='test')
        with patch.object(outfitting_snapshot, 'search', return_value=result), \
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
        with patch.object(outfitting_snapshot, 'search', return_value=result):
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
