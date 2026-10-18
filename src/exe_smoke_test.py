"""离线验证实际打包程序能创建主界面、加载辅助窗口和内置候选。"""
import json
import os
import sys
import time


def run(gui, report_path):
    report = {"ok": False, "frozen": bool(getattr(sys, "frozen", False))}
    root = None
    app = None
    try:
        import field_options as fo
        import powerplay_gui
        import rare_goods
        from runtime_paths import data_directory

        # 只验证加载和控件，不发起网络查询。
        fo.prefetch_common = lambda *args, **kwargs: None
        fo.get_options = lambda kind, field: list(fo.BUNDLED_OPTIONS.get(f"{kind}/{field}", []))
        root = gui.tk.Tk()
        root.withdraw()
        callback_errors = []
        root.report_callback_exception = lambda *args: callback_errors.append(str(args[1]))
        app = gui.App(root)
        app._closing = True  # 禁用自动保存，避免加载验证覆盖正常会话。
        for mode in ('dark', 'light', 'system'):
            app.set_appearance(mode)
            assert app.appearance_manager.mode == mode
        app.set_language("zh")
        root.withdraw()
        app.clear()
        row = gui.Row(app.inner, "stations")
        row.field.set(gui.field_label("stations", "modules"))
        row.val.set("Fuel Scoop")
        row.refresh_options()
        assert '5A' in row.cb_spec['values'] and '5E' in row.cb_spec['values']
        assert fo.get_module_variants('Plasma Accelerator') == ['2C', '3B', '4A']
        assert fo.get_module_variants('Rail Gun') == ['1D', '2B']
        window = powerplay_gui.open_window(app, gui.data_age)
        assert window.title() == "稀有商品目标查找器"
        app.carrier_parking_window()
        app.midpoint_window()
        pve = app.pve_window()
        assert pve.title() == "海盗任务查找器"
        colony = app.colonisation_window()
        route = app.route_window()
        shopping = app.engineer_shopping_window()
        app.set_appearance('dark')
        root.update_idletasks()
        assert shopping.cget('background') == app.appearance_manager.palette['bg']
        assert app.canvas.cget('background') == app.appearance_manager.palette['bg']
        app.set_appearance('light')

        def button(parent, raw):
            stack, found = [parent], None
            while stack:
                for child in stack.pop().winfo_children():
                    if isinstance(child, gui.ttk.Button) and getattr(child, '_raw_text', '') == raw:
                        found = found or child
                    stack.append(child)
            assert found is not None, f'missing button {raw}'
            return found

        # 发布后修复的三个标签必须随界面语言切换。
        assert button(colony, '查询').cget('text') == '查询'
        assert button(shopping, '查询').cget('text') == '查询'
        assert button(shopping, '复制站名').cget('text') == '复制站名'
        shopping.session_variables['origin'].set('LHS 336')
        shopping.session_variables['destination'].set('Didi Vatermann — Leesti')
        shopping.purchase_row.val.set('Shield Booster')
        shopping.purchase_row.v_spec.set('0A')
        shopping.add_purchase(dict(value='Plasma Accelerator', module_spec='2C'))
        assert [c['values'] for c in shopping.criteria()[0].conditions[:2]] == [['Shield Booster'], ['Plasma Accelerator']]
        assert 'ignore_planetary' in shopping.session_variables
        assert len(shopping.destination_box['values']) == 25
        app.results = [dict(name='Shop 10', system_name='Sol', distance_to_arrival=10),
                       dict(name='Shop 2', system_name='Sol', distance_to_arrival=2)]
        app._result_kind = 'stations'
        app._result_conditions = [dict(field='distance_to_arrival', op='<', text=100)]
        app.render_main_results()
        app.tree.sort_by('value_2')
        assert app.tree.set(app.tree.get_children()[0], 'name') == 'Shop 2'
        assert app.results[0]['name'] == 'Shop 10'
        assert route.title() == '中子星跳跃规划器'
        assert route.route_state['points'] == []
        assert 'population' not in colony.result_tree['columns']
        assert all(key in colony.result_tree['columns'] for key in ('scan1', 'scan2', 'scan3', 'neighbour_pad'))
        assert 'max_pages' not in colony.session_variables
        from result_format import format_ls, format_ly, format_population
        assert format_ls(1279.406775) == '1,279.41'
        assert format_ly(1234.567) == '1,234.57'
        assert format_population(1234567.0) == '1,234,567'
        colony.group_editors['body_groups'].add_group([
            {'field': '_is_binary', 'op': '=', 'value': 'true'}])
        assert colony.criteria().body_groups[0][0]['field'] == '_is_binary'
        app.set_language("en")
        assert shopping.title() == 'Engineer trip shopping'
        assert route.title() == 'Neutron jump planner'
        assert colony.title() == "Colonisation candidate finder"
        assert button(colony, '查询').cget('text') == 'Search'
        assert button(shopping, '查询').cget('text') == 'Search'
        assert button(shopping, '复制站名').cget('text') == 'Copy station name'
        from main_system_gui import DetailsRow
        app.kind.set('systems')
        detailed_row = DetailsRow(app.inner, 'systems')
        app.rows.append(detailed_row)
        detailed_row.apply_condition(dict(nearest_max=10, population_min=1))
        detailed_editor = detailed_row.open_editor()
        assert detailed_editor.title() == 'Main-window system details'
        assert button(detailed_editor, '关闭').cget('text') == 'Close'
        assert detailed_row.to_cond()['nearest_max'] == 10
        detailed_editor.destroy()
        assert pve.title() == "Pirate massacre finder"
        assert window.title() == "Rare goods target finder"
        end = time.monotonic() + 0.3
        while time.monotonic() < end:
            root.update()
            time.sleep(0.01)
        assert not callback_errors, callback_errors
        assert len(rare_goods.GOODS) == 142
        assert len(rare_goods.SOURCE_SYSTEMS) == 138
        assert len(fo.BUNDLED_OPTIONS["stations/modules"]) == 153
        from export_metadata import PROJECT_VERSION
        assert PROJECT_VERSION in root.title()
        if getattr(sys, 'frozen', False):
            from pathlib import Path
            licence = Path(sys._MEIPASS) / 'LICENSE'
            assert 'GNU GENERAL PUBLIC LICENSE' in licence.read_text(encoding='utf-8')
        report.update(ok=True, version=PROJECT_VERSION, shopping_items=len(shopping.purchase_rows),
                      appearance_modes=['system', 'light', 'dark'],
                      sortable_results=True, paired_specs=len(fo.BUNDLED_MODULE_PAIRS),
                      data_directory=data_directory(), session_file=gui.SESSION_FILE,
                      cache_file=fo.CACHE_FILE, specs_file=fo.SPECS_FILE,
                      goods=142, sources=138, modules=153, languages=["zh", "en"],
                      windows=[w.title() for w in root.winfo_children() if isinstance(w, gui.tk.Toplevel)])
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        if root is not None:
            if app is not None:
                app._closing = True  # 加载冒烟不写回用户会话。
            root.destroy()
        # 调用者提供已存在的报告目录；不向单文件解包目录写入用户数据。
        with open(os.path.abspath(report_path), "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
    return 0 if report["ok"] else 1
