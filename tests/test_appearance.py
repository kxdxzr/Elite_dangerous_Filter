import os
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

import appearance
import filter_gui as gui
import session_store


class AppearanceModeTests(unittest.TestCase):
    def test_only_canonical_modes_are_accepted(self):
        for mode in appearance.MODES:
            self.assertEqual(appearance.normalize_mode(mode), mode)
        for mode in ('Dark', '深色', '', None, [], {}):
            self.assertEqual(appearance.normalize_mode(mode), 'system')

    def test_windows_reads_app_not_shell_preference_and_missing_key_is_safe(self):
        key = MagicMock()
        registry = SimpleNamespace(HKEY_CURRENT_USER='HKCU',
                                   OpenKey=MagicMock(return_value=key), QueryValueEx=MagicMock())
        with patch.object(appearance.sys, 'platform', 'win32'), patch.dict(sys.modules, winreg=registry):
            for value, expected in ((0, 'dark'), (1, 'light')):
                registry.QueryValueEx.return_value = (value, 4)
                self.assertEqual(appearance.system_mode(), expected)
                registry.QueryValueEx.assert_called_with(key.__enter__.return_value, 'AppsUseLightTheme')
            registry.OpenKey.side_effect = OSError('No registry preference')
            self.assertEqual(appearance.system_mode(), 'light')
        with patch.object(appearance.sys, 'platform', 'linux'):
            self.assertEqual(appearance.system_mode(), 'light')


@unittest.skipUnless(sys.platform == 'win32' or os.environ.get('DISPLAY'), 'Requires a GUI display')
class AppearanceGuiTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.session = Path(self.directory.name) / 'last_session.json'
        self.system = ['light']
        patches = (
            patch.dict(os.environ, ELITE_FILTER_DATA_DIR=self.directory.name),
            patch.object(gui, 'SESSION_FILE', str(self.session)),
            patch.object(gui.fo, 'prefetch_common', lambda *a, **k: None),
            patch.object(gui.fo, 'get_options', lambda *a, **k: []),
            patch.object(appearance, 'system_mode', lambda: self.system[0]),
            patch('urllib.request.urlopen', side_effect=AssertionError('Appearance tests must be offline')),
        )
        for item in patches:
            item.start()
            self.addCleanup(item.stop)
        self.root = gui.tk.Tk()
        self.root.withdraw()
        self.errors = []
        self.root.report_callback_exception = lambda *args: self.errors.append(str(args[1]))
        self.app = gui.App(self.root)
        self.app._closing = True
        self.addCleanup(self._destroy)

    def _destroy(self):
        if self.root is not None:
            for timer in self.root.tk.splitlist(self.root.tk.call('after', 'info')):
                self.root.tk.call('after', 'cancel', timer)
            self.root.destroy()

    def tearDown(self):
        if self.root is not None:
            self.root.update_idletasks()
        self.assertEqual(self.errors, [])

    def test_default_translation_and_model_preserved_when_switching(self):
        self.assertEqual(self.app.appearance_manager.mode, 'system')
        self.app.add_distance()
        before = self.app._state_dict()
        for mode in ('dark', 'light', 'system'):
            self.app.set_appearance(mode)
            self.app.set_language('en')
            self.root.update_idletasks()
            self.assertEqual(tuple(self.app.appearance_box['values']), ('Follow system', 'Light', 'Dark'))
            self.assertEqual(self.app.appearance_box.get(), appearance.MODES[mode])
            self.assertEqual(self.app.appearance_box._display.get(),
                             {'system': 'Follow system', 'light': 'Light', 'dark': 'Dark'}[mode])
            self.app.set_language('zh')
            self.assertEqual(self.app.appearance_box._display.get(), appearance.MODES[mode])
            after = self.app._state_dict()
            self.assertEqual(before['rows'], after['rows'])
            self.assertEqual(before['conditions'], after['conditions'])
            self.assertEqual(before['tools'], after['tools'])

    def test_actual_selector_saves_canonical_value_and_restart_restores_it(self):
        self.app.set_language('en')
        self.app.appearance_box._display.set('Dark')
        self.app.appearance_box.event_generate('<<ComboboxSelected>>')
        self.assertEqual(self.app.appearance_manager.mode, 'dark')
        saved = session_store.load(self.session)
        self.assertEqual(saved['appearance'], 'dark')
        self._destroy()
        self.root = gui.tk.Tk()
        self.root.withdraw()
        self.root.report_callback_exception = lambda *args: self.errors.append(str(args[1]))
        self.app = gui.App(self.root)
        self.app._closing = True
        self.assertEqual(self.app.appearance_manager.mode, 'dark')
        self.assertEqual(self.app.appearance_manager.effective, 'dark')
        self.assertEqual(self.app.appearance_box._display.get(), 'Dark')

    def test_legacy_sessions_preserve_choice_and_invalid_modes_fall_back(self):
        self.app.set_appearance('dark')
        self.app._apply_state(dict(kind='stations', conditions=[]))
        self.assertEqual(self.app.appearance_manager.mode, 'dark')
        for value in (None, [], 'not-a-theme'):
            self.app._apply_state(dict(appearance=value))
            self.assertEqual(self.app.appearance_manager.mode, 'system')

    def test_follow_system_polls_but_manual_mode_does_not_follow(self):
        manager = self.app.appearance_manager
        self.root.after_cancel(manager._poll_id)
        manager._poll_ms = 10
        manager._poll_id = self.root.after(1, manager._poll)

        def pump():
            deadline = time.monotonic() + .08
            while time.monotonic() < deadline:
                self.root.update()
                time.sleep(.005)

        self.system[0] = 'dark'
        pump()
        self.assertEqual(manager.effective, 'dark')
        self.assertEqual(manager.mode, 'system')
        self.app.set_appearance('light')
        pump()
        self.assertEqual(manager.effective, 'light')
        self.assertEqual(manager.mode, 'light')
        self.app.set_appearance('system')
        self.assertEqual(manager.effective, 'dark')
        self.system[0] = 'light'
        pump()
        self.assertEqual(manager.effective, 'light')
        manager._system_reader = lambda: (_ for _ in ()).throw(OSError('Unavailable'))
        manager.refresh()
        self.assertEqual(manager.effective, 'light')

    def test_existing_and_new_classic_widgets_and_ttk_states_have_matching_colors(self):
        window = gui.Toplevel(self.root)
        canvas = gui.tk.Canvas(window)
        text = gui.tk.Text(window)
        listing = gui.tk.Listbox(window)
        label = gui.tk.Label(window, text='Rename')
        entry = gui.tk.Entry(window)
        button = gui.tk.Button(window, text='OK')
        banner = gui.tk.Label(window, text='Example data', background='#fff1cc')
        for mode in ('dark', 'light'):
            self.app.set_appearance(mode)
            p = appearance.PALETTES[mode]
            self.assertEqual(window.cget('background'), p['bg'])
            self.assertEqual(canvas.cget('background'), p['bg'])
            self.assertEqual(text.cget('background'), p['surface'])
            self.assertEqual(text.cget('insertbackground'), p['text'])
            self.assertEqual(listing.cget('foreground'), p['text'])
            self.assertEqual(listing.cget('selectbackground'), p['accent'])
            self.assertEqual(label.cget('foreground'), p['text'])
            self.assertEqual(entry.cget('background'), p['surface'])
            self.assertEqual(button.cget('foreground'), p['text'])
            self.assertEqual(banner.cget('background'), '#fff1cc')
            new_text = gui.tk.Text(window)
            self.assertEqual(new_text.cget('background'), p['surface'])
            new_text.destroy()
            style = self.app.appearance_manager.style
            self.assertEqual(style.lookup('TCombobox', 'fieldbackground', ('readonly',)), p['surface'])
            self.assertEqual(style.lookup('TEntry', 'foreground', ('disabled',)), p['disabled'])
            self.assertEqual(style.lookup('Treeview', 'background', ('selected',)), p['accent'])
            self.assertEqual(style.lookup('Muted.TLabel', 'foreground'), p['muted'])
            self.assertEqual(style.lookup('Warning.TLabel', 'foreground'), p['warning'])
        window.destroy()

    def test_tcl_owned_combobox_popdown_updates_while_open(self):
        self.root.deiconify()
        self.root.update()
        box = self.app.appearance_box
        path = str(box) + '.popdown.f.l'
        try:
            box.tk.call('ttk::combobox::Post', str(box))
            self.root.update()
            for mode in ('dark', 'light'):
                self.app.set_appearance(mode)
                self.root.update()
                self.assertEqual(box.tk.call(path, 'cget', '-background'),
                                 appearance.PALETTES[mode]['surface'])
                self.assertEqual(box.tk.call(path, 'cget', '-foreground'),
                                 appearance.PALETTES[mode]['text'])
        finally:
            box.tk.call('ttk::combobox::Unpost', str(box))

    def test_striping_sorting_and_theme_preserve_identity_selection_and_evidence_tags(self):
        tree = self.app.tree
        first = tree.insert('', 'end', values=('Station 10', 'Sol'), tags=('evidence',))
        second = tree.insert('', 'end', values=('Station 2', 'Sol'))
        tree.selection_set(first)
        for mode in ('dark', 'light'):
            self.app.set_appearance(mode)
            tree.sort_by('name')
            self.root.update_idletasks()
            ordered = tree.get_children()
            self.assertEqual(tree.selection(), (first,))
            self.assertEqual(tree.item(first, 'values'), ('Station 10', 'Sol'))
            self.assertIn('evidence', tree.item(first, 'tags'))
            self.assertIn('_stripe_even', tree.item(ordered[0], 'tags'))
            self.assertIn('_stripe_odd', tree.item(ordered[1], 'tags'))
            self.assertEqual(str(tree.tag_configure('_stripe_odd', 'background')),
                             appearance.PALETTES[mode]['alternate'])
        tree.delete(second)
        self.root.update_idletasks()
        self.assertIn('_stripe_even', tree.item(first, 'tags'))

    def test_all_tools_open_in_current_theme_and_follow_switches(self):
        self.app.set_appearance('dark')
        for method in ('rare_goods_window', 'pve_window', 'colonisation_window',
                       'carrier_parking_window', 'midpoint_window',
                       'engineer_shopping_window'):
            getattr(self.app, method)()
        windows = [child for child in self.root.winfo_children() if isinstance(child, gui.tk.Toplevel)]
        self.assertGreaterEqual(len(windows), 6)
        self.root.update_idletasks()
        for mode in ('dark', 'light'):
            self.app.set_appearance(mode)
            for window in windows:
                self.assertEqual(window.cget('background'), appearance.PALETTES[mode]['bg'])
        self.assertEqual(session_store.load(self.session), {})

    def test_pve_and_shopping_forms_scroll_without_hiding_results(self):
        for method in ('pve_window', 'engineer_shopping_window'):
            window = getattr(self.app, method)()
            for size in ('1400x820', '1100x700'):
                with self.subTest(method=method, size=size):
                    window.geometry(size)
                    window.deiconify()
                    self.root.update()
                    self.assertTrue(window.result_tree.winfo_ismapped())
                    self.assertGreater(window.result_tree.winfo_height(), 100)
                    window.settings_canvas.yview_moveto(1)
                    self.assertGreater(window.settings_canvas.yview()[0], 0)
                    window.settings_canvas.yview_moveto(0)
            window.destroy()

    def test_copy_and_export_footers_remain_visible(self):
        self.root.deiconify()
        for method in ('pve_window', 'rare_goods_window', 'carrier_parking_window', 'midpoint_window'):
            getattr(self.app, method)()
        self.root.update()
        expected = {'复制名称', '复制目标星系', '复制来源空间站', '导出全部组 CSV', '复制星系名'}
        found = set()

        def scan(parent):
            for child in parent.winfo_children():
                raw = getattr(child, '_raw_text', '')
                if isinstance(child, gui.ttk.Button) and raw in expected:
                    window = child.winfo_toplevel()
                    with self.subTest(action=raw, window=window.title()):
                        self.assertTrue(child.winfo_ismapped())
                        self.assertLessEqual(child.winfo_rooty() + child.winfo_height(),
                                             window.winfo_rooty() + window.winfo_height())
                    found.add(raw)
                scan(child)
        scan(self.root)
        self.assertEqual(found, expected)


if __name__ == '__main__':
    unittest.main()
