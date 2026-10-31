import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import filter_gui as gui
import session_store
import file_io


class Value:
    def __init__(self, value=""):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class EditorRow(gui.Row):
    def __init__(self, master, kind, rowtype="field"):
        self.type, self.kind = rowtype, kind
        self.frame = Mock()
        self.frame.winfo_exists.return_value = True
        for name, value in dict(ref="Sol", vmin="", vmax="50", mode="范围内", field="name",
                                op="属于其一", val="", v_class="", v_rating="", v_fresh="不限",
                                v_discount='不限', v_slot='不限', v_category='不限').items():
            setattr(self, name, Value(value))

    def refresh_options(self):
        pass

    def set_fields(self, kind):
        self.kind = kind


def app_fixture():
    app = gui.App.__new__(gui.App)
    app.rows, app.inner = [], None
    app.kind, app.want, app.maxpages = Value("stations"), Value("200"), Value("25")
    app._tool_states, app._tool_collectors = {}, {}
    app.clear = lambda: app.rows.clear()
    return app


class SessionStoreTests(unittest.TestCase):
    def test_atomic_unicode_and_boolean_roundtrip(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "last_session.json"
            state = dict(rows=[dict(value="未完成的条件")], tools=dict(rare_goods=dict(all_powers=True)))
            session_store.save(path, state)
            self.assertEqual(session_store.load(path), state)
            self.assertEqual(list(Path(folder).iterdir()), [path])

    def test_replace_failure_keeps_previous_session(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "last_session.json"
            session_store.save(path, dict(want="17"))
            with patch.object(file_io.os, "replace", side_effect=OSError("disk failure")):
                with self.assertRaises(OSError):
                    session_store.save(path, dict(want="99"))
            self.assertEqual(session_store.load(path), dict(want="17"))
            self.assertEqual(list(Path(folder).iterdir()), [path])

    def test_missing_or_invalid_file_is_safe(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "last_session.json"
            self.assertEqual(session_store.load(path), {})
            for text in ("{broken", "[]", "null"):
                path.write_text(text, encoding="utf-8")
                self.assertEqual(session_store.load(path), {})

    def test_draft_rows_restore_without_validation_loss(self):
        app = app_fixture()
        draft = EditorRow(None, "stations", "distance")
        draft.ref.set("")
        draft.vmin.set("unfinished")
        module = EditorRow(None, "stations")
        module.field.set("modules")
        module.val.set("Fuel Scoop")
        module.v_class.set("5; 3")
        module.v_rating.set("B")
        module.v_fresh.set("近7天")
        app.rows = [draft, module]
        saved = app._state_dict()
        self.assertEqual(len(saved["rows"]), 2)
        self.assertEqual(len(saved["conditions"]), 1)
        restored = app_fixture()
        with patch.object(gui, "Row", EditorRow):
            restored._apply_state(saved)
        self.assertEqual([r.editor_state() for r in restored.rows], saved["rows"])

    def test_legacy_session_remains_supported(self):
        app = app_fixture()
        saved = dict(kind="stations", conditions=[dict(type="distance", ref_system="Sol",
                     min_ly=None, max_ly=50, mode="inside")], want="17", maxpages="6")
        with patch.object(gui, "Row", EditorRow):
            app._apply_state(saved)
        self.assertEqual(app.rows[0].ref.get(), "Sol")
        self.assertEqual(app.rows[0].vmax.get(), "50")
        self.assertEqual((app.want.get(), app.maxpages.get()), ("17", "6"))

    def test_closed_and_live_tool_settings_are_preserved(self):
        app = app_fixture()
        app._tool_states = dict(rare_goods=dict(reference="Leesti", all_powers=True))
        app._tool_collectors = dict(carrier_parking=lambda: dict(radius="45", candidates_only=False))
        state = app._state_dict()
        self.assertEqual(state["tools"]["rare_goods"], dict(reference="Leesti", all_powers=True))
        self.assertEqual(state["tools"]["carrier_parking"], dict(radius="45", candidates_only=False))

    def test_save_failure_is_reported_and_close_keeps_window_open(self):
        app = app_fixture()
        app._last_session_state, app._closing = None, False
        app.status, app.root = Value(), Mock()
        with patch.object(session_store, "save", side_effect=OSError("permission denied")), \
                patch.object(gui.messagebox, "showerror") as error:
            app.on_close()
        self.assertIn("permission denied", app.status.get())
        error.assert_called_once()
        app.root.destroy.assert_not_called()
        self.assertFalse(app._closing)


if __name__ == "__main__":
    unittest.main()
