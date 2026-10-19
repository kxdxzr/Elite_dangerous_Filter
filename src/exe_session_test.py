"""两个独立进程的真实GUI会话回归；调用者必须提供隔离数据目录。"""
import json
import os
import sys
import time


ROWS = [
    dict(type="distance", ref="Sol", min="", max="50", mode="范围内"),
    dict(type="field", field="modules", op="属于其一", value="Fuel Scoop",
         **{"class": "5", "rating": "B", "fresh": "近7天", 'discount': '不限',
            'module_slot': '不限', 'condition_category': '不限', 'module_spec': '5B'}),
    dict(type="distance", ref="", min="unfinished", max="", mode="范围外"),
]
TOOLS = {
    "rare_goods": dict(reference="Leesti", minimum="205", maximum="219", pages="9",
                        query="Azure", power="Yuri Grom", all_powers=True, neutron_only=False),
    "carrier_parking": dict(reference="Lave", radius="45", pages="7",
                            min_carriers="0", max_carriers="17", exclude_permit=False),
    "midpoint": dict(a="Sol", b="Ngurii", want="15", populated_only=True, exclude_permit=True),
    "pve": dict(reference="Sol", radius="0", min_factions="0", min_federation="2", min_empire="1",
                 site_type='仅 Low RES',
                source_faction="Mother Gaia", source_controller="Mother Gaia", target_controller="Test Pirates",
                power="Yuri Grom", power_scope="双方", prefer_low=True, cnb_fallback=False,
                source_pad="L", source_station_max_ls="500", target_ring_max_ls="1500"),
}
SHOPPING_ROWS = [
    dict(type='field', field='modules', op='属于其一', value='Shield Booster',
         **{'class': '0', 'rating': 'A', 'fresh': '不限', 'discount': '是',
            'module_slot': '通用插槽', 'condition_category': '不限', 'module_spec': '0A'}),
    dict(type='field', field='modules', op='属于其一', value='Plasma Accelerator',
         **{'class': '2', 'rating': 'C', 'fresh': '不限', 'discount': '不限',
            'module_slot': '武器挂点', 'condition_category': '不限', 'module_spec': '2C'}),
]
TOOLS['engineer_shopping'] = dict(
    pledged_power='Jerome Archer', assume_max_rank=True,
    landing_pad='L',
    origin='LHS 336', destination='Didi Vatermann — Leesti', jump_range='90', max_extra_jumps='2',
    arrival_ls='1200', want='20', max_pages='5', ignore_carriers=True, ignore_planetary=True,
    purchases=json.dumps(SHOPPING_ROWS, ensure_ascii=False), module='Shield Booster', module_class='0',
    module_rating='A', slot='通用插槽', freshness='不限', discount='是', module_spec='0A')


def run(gui, phase, report_path):
    report = dict(ok=False, phase=phase, frozen=bool(getattr(sys, "frozen", False)))
    root = None
    closed = False
    try:
        if not os.environ.get("ELITE_FILTER_DATA_DIR"):
            raise ValueError("Session tests require an isolated ELITE_FILTER_DATA_DIR")
        if phase not in ("write", "read"):
            raise ValueError("Phase must be write or read")
        import field_options as fo
        import powerplay_gui
        import session_store

        fo.prefetch_common = lambda *args, **kwargs: None
        fo.get_options = lambda kind, field: list(fo.BUNDLED_OPTIONS.get(f"{kind}/{field}", []))
        root = gui.tk.Tk()
        root.withdraw()
        errors = []
        root.report_callback_exception = lambda *args: errors.append(str(args[1]))
        app = gui.App(root)
        root.withdraw()
        if phase == "write":
            app._apply_state(dict(kind="stations", rows=ROWS, want="17", maxpages="6", language="en",
                                 appearance='dark', tools=TOOLS))
        else:
            restored = app._state_dict()
            assert restored["rows"] == ROWS, restored["rows"]
            assert restored["want"] == "17" and restored["maxpages"] == "6"
            assert restored["tools"] == TOOLS, restored["tools"]
            assert restored["language"] == "en"
            assert restored['appearance'] == 'dark'
            assert app.appearance_manager.effective == 'dark'

        rare = powerplay_gui.open_window(app, gui.data_age)
        app.carrier_parking_window()
        app.midpoint_window()
        windows = {"rare_goods": rare, "pve": app.pve_window(), 'engineer_shopping': app.engineer_shopping_window()}
        assert len(windows['engineer_shopping'].purchase_rows) == 2
        assert [c['values'] for c in windows['engineer_shopping'].criteria()[0].conditions[:2]] == [['Shield Booster'], ['Plasma Accelerator']]
        for window in root.winfo_children():
            if isinstance(window, gui.tk.Toplevel):
                if getattr(window, "_raw_title", "") == "航母车位查找":
                    windows["carrier_parking"] = window
                elif getattr(window, "_raw_title", "").startswith("两系中点"):
                    windows["midpoint"] = window
        for key, window in windows.items():
            for name, value in TOOLS[key].items():
                variable = window.session_variables[name]
                if phase == "write":
                    variable.set(value)
                else:
                    assert variable.get() == value, (key, name, variable.get(), value)
        if phase == "write":
            # 不调用手动保存，确认周期自动保存确实包含草稿行和所有活动工具。
            deadline = time.monotonic() + 1.8
            while time.monotonic() < deadline:
                root.update()
                time.sleep(0.02)
            automatic = session_store.load(gui.SESSION_FILE)
            assert automatic["rows"] == ROWS and automatic["tools"] == TOOLS, automatic
            # 实际执行子窗口关闭协议，再打开，确认设置不丢失。
            rare.tk.call(rare.protocol("WM_DELETE_WINDOW"))
            assert "rare_goods" not in app._tool_collectors
            rare = powerplay_gui.open_window(app, gui.data_age)
            assert {name: var.get() for name, var in rare.session_variables.items()} == TOOLS["rare_goods"]
            pve = windows["pve"]
            pve.tk.call(pve.protocol("WM_DELETE_WINDOW"))
            assert "pve" not in app._tool_collectors
            pve = app.pve_window()
            assert {name: var.get() for name, var in pve.session_variables.items()} == TOOLS["pve"]
        root.update()
        assert not errors, errors
        assert app._state_dict()["rows"] == ROWS
        app.on_close()
        closed = True
        persisted = session_store.load(gui.SESSION_FILE)
        assert persisted["rows"] == ROWS and persisted["tools"] == TOOLS, persisted
        assert persisted["language"] == "en"
        assert persisted['appearance'] == 'dark'
        report.update(ok=True, session_file=gui.SESSION_FILE, rows=persisted["rows"], tools=persisted["tools"],
                      language=persisted["language"], appearance=persisted['appearance'])
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        if root is not None and not closed:
            root.destroy()
        with open(report_path, "w", encoding="utf-8") as file:
            json.dump(report, file, ensure_ascii=False, indent=2)
    return 0 if report["ok"] else 1
