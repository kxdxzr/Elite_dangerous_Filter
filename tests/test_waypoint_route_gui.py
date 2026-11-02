import gc
import json
import os
import sys
import time
import unittest
from unittest.mock import patch

import waypoint_route as tool
from test_waypoint_route import station


@unittest.skipUnless(sys.platform == 'win32' or os.environ.get('DISPLAY'), 'Requires a GUI display')
class WaypointRouteGuiTests(unittest.TestCase):
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

    def capture_group(self, controls):
        self.app.clear()
        self.app.kind.set('stations')
        self.app._append_cond(dict(field='name', op='=', text='Port'))
        controls['capture']()

    def test_capture_is_independent_session_roundtrip_and_language(self):
        win = self.app.waypoint_route_window()
        controls = win.route_controls
        self.capture_group(controls)
        self.assertEqual(len(controls['groups']), 1)
        self.app.rows[0].val.set('Changed')
        self.assertEqual(controls['groups'][0]['conditions'][0]['text'], 'Port')
        controls['variables']['destination'].set('Achenar')
        saved = self.app._state_dict()['tools']['waypoint_route']
        self.assertEqual(json.loads(saved['groups'])[0]['conditions'][0]['text'], 'Port')
        self.app.set_language('en')
        self.assertEqual(win.title(), 'Multi-objective waypoint planner')
        self.assertEqual(controls['group_tree'].set('0', 'kind'), 'Station')
        win.destroy()
        self.app._tool_states['waypoint_route'] = saved
        restored = self.app.waypoint_route_window()
        self.assertEqual(restored.route_controls['groups'], controls['groups'])
        self.assertEqual(restored.session_variables['destination'].get(), 'Achenar')

    def test_worker_renders_snapshot_and_invalid_input_keeps_result(self):
        import waypoint_route_gui as ui
        win = self.app.waypoint_route_window()
        controls = win.route_controls
        self.capture_group(controls)
        controls['variables']['destination'].set('B')
        pools = [[station('Port', 5)]]
        result = tool.solve((0, 0, 0), (10, 0, 0), pools, 100)
        result.update(origin='Sol', destination='B', pools=pools, groups=controls['groups'],
                      fetched_at='2026-11-02T00:00:00Z', notes=[])
        with patch.object(tool, 'search', return_value=result) as search:
            controls['run']()
            deadline = time.monotonic() + 4
            while controls['state']['busy'] and time.monotonic() < deadline:
                self.root.update()
                time.sleep(.01)
        self.assertFalse(controls['state']['busy'])
        search.assert_called_once()
        self.assertEqual(controls['tree'].set('0', 'station'), 'Port')
        controls['variables']['max_extra_ly'].set('nan')
        with patch.object(ui.messagebox, 'showerror') as error:
            controls['run']()
        error.assert_called_once()
        self.assertIs(controls['state']['result'], result)

    def test_empty_capture_rejected_and_corrupt_session_is_safe(self):
        import waypoint_route_gui as ui
        self.app._tool_states['waypoint_route'] = dict(groups='[1]')
        win = self.app.waypoint_route_window()
        controls = win.route_controls
        self.assertEqual(controls['groups'], [])
        self.app.clear()
        with patch.object(ui.messagebox, 'showerror') as error:
            controls['capture']()
        error.assert_called_once()
        self.assertEqual(controls['groups'], [])
