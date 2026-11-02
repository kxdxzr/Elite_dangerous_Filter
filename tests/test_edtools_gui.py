import gc
import os
import sys
import time
import unittest
from unittest.mock import patch

import edtools_snapshot as store


@unittest.skipUnless(sys.platform == 'win32' or os.environ.get('DISPLAY'), 'Requires a GUI display')
class EDToolsGuiTests(unittest.TestCase):
    def setUp(self):
        import filter_gui as gui
        self.gui = gui
        self.patches = [patch.object(gui.fo, 'prefetch_common', lambda *a: None),
                        patch.object(gui.fo, 'get_options', return_value=[]),
                        patch.object(gui.App, 'restore_session', lambda *a: None),
                        patch.object(store, 'active_snapshot', return_value=dict(
                            installed_at=1000, bundled_at=1000, generation='old'))]
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

    def wait(self, win):
        deadline = time.monotonic() + 4
        while win.catalog_state['busy'] and time.monotonic() < deadline:
            self.root.update()
            time.sleep(.01)
        self.assertFalse(win.catalog_state['busy'])

    def test_auto_check_decline_preserves_snapshot_and_language(self):
        import pve_gui as ui
        with patch.object(store, 'check', return_value=dict(status='available', generation='new')) as check, \
                patch.object(store, 'update') as update, \
                patch.object(ui.messagebox, 'askyesno', return_value=False) as ask:
            win = self.app.pve_window()
            self.wait(win)
        check.assert_called_once_with(force=False)
        ask.assert_called_once()
        update.assert_not_called()
        self.assertEqual(win.catalog_state['result']['status'], 'available')
        self.app.set_language('en')
        self.assertEqual(win.title(), 'Pirate massacre finder')

    def test_auto_check_confirmation_installs_only_staged_generation(self):
        import pve_gui as ui
        with patch.object(store, 'check', return_value=dict(status='available', generation='new')), \
                patch.object(store, 'update') as update, \
                patch.object(ui.messagebox, 'askyesno', return_value=True):
            win = self.app.pve_window()
            self.wait(win)
        update.assert_called_once_with('new')
        self.assertEqual(win.catalog_state['result']['status'], 'installed')

    def test_automatic_failure_is_nonblocking_manual_check_reports_error(self):
        import pve_gui as ui
        with patch.object(store, 'check', return_value=dict(status='failed', error='offline')) as check, \
                patch.object(ui.messagebox, 'showerror') as error:
            win = self.app.pve_window()
            self.wait(win)
            error.assert_not_called()
            win.catalog_action(force=True)
            self.wait(win)
        error.assert_called_once()
        self.assertEqual([call.kwargs['force'] for call in check.call_args_list], [False, True])

    def test_unchanged_does_not_prompt_or_update(self):
        import pve_gui as ui
        with patch.object(store, 'check', return_value=dict(status='unchanged')), \
                patch.object(store, 'update') as update, \
                patch.object(ui.messagebox, 'askyesno') as ask:
            win = self.app.pve_window()
            self.wait(win)
        ask.assert_not_called()
        update.assert_not_called()
