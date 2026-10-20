"""Capture current Windows UI with clearly labelled, offline demonstration data.

Developer-only: requires Windows and Pillow 12 (not an application dependency).
Uses an isolated temporary session and blocks network access. No personal data,
live stock, actual routes or claimable systems are implied by these fixtures.
Example: python scripts/capture_screenshots.py --work-dir <temporary directory>
"""
import argparse
from contextlib import ExitStack
import copy
import ctypes
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from unittest.mock import patch


PROJECT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=PROJECT / 'docs' / 'images')
    parser.add_argument('--work-dir', type=Path)
    parser.add_argument('--appearance', choices=('light', 'dark', 'system'), default='light',
                        help='Use a deterministic light theme by default; dark previews are optional.')
    args = parser.parse_args()
    if sys.platform != 'win32':
        parser.error('Window screenshots require Windows.')
    sys.path.insert(0, str(PROJECT / 'src'))
    from ui_display import initialize_display
    initialize_display()
    from PIL import ImageGrab
    args.output.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix='elite-screenshots-', dir=args.work_dir) as folder, ExitStack() as stack:
        stack.enter_context(patch.dict(os.environ, ELITE_FILTER_DATA_DIR=folder))
        import filter_gui as gui
        import field_options as fo
        import engineer_shopping as shopping
        from export_metadata import PROJECT_VERSION
        stack.enter_context(patch.object(fo, 'prefetch_common', lambda *a, **k: None))
        stack.enter_context(patch.object(fo, 'get_options', lambda kind, field: list(fo.BUNDLED_OPTIONS.get(f'{kind}/{field}', []))))
        stack.enter_context(patch.object(gui.App, 'restore_session', lambda *a: None))
        stack.enter_context(patch('urllib.request.urlopen', side_effect=RuntimeError('Screenshot capture is offline.')))
        root = gui.tk.Tk()
        root.withdraw()
        errors = []
        root.report_callback_exception = lambda *a: errors.append(str(a[1]))
        app = gui.App(root)
        app._closing = True
        app.set_appearance(args.appearance)

        def pump(seconds=.25):
            deadline = time.monotonic() + seconds
            while time.monotonic() < deadline:
                root.update()
                time.sleep(.01)
            if errors:
                raise RuntimeError(errors)

        def descendants(parent):
            for child in parent.winfo_children():
                yield child
                yield from descendants(child)

        def trees(parent):
            return [w for w in descendants(parent) if isinstance(w, gui.ttk.Treeview)]

        def button(parent, title):
            return next(w for w in descendants(parent) if isinstance(w, gui.ttk.Button) and getattr(w, '_raw_text', '') == title)

        def open_named(method, title):
            method()
            return next(w for w in root.winfo_children() if getattr(w, '_raw_title', '') == title)

        banners, records = {}, []
        screen_w = ctypes.windll.user32.GetSystemMetrics(0)
        screen_h = ctypes.windll.user32.GetSystemMetrics(1)

        def capture(win, filename, language, width=1540, height=860):
            if win not in banners:
                packed = win.pack_slaves()
                label = gui.tk.Label(win, background='#fff1cc', foreground='#654600', font=('Segoe UI', 10))
                label.pack(side='top', fill='x', before=packed[0] if packed else None)
                banners[win] = label
            banners[win].configure(text=(
                'v' + PROJECT_VERSION + ' · 界面演示：示例数据，非实时库存、任务或已验证航线'
                if language == 'zh' else
                'v' + PROJECT_VERSION + ' · UI DEMONSTRATION: example data, not live stock, missions or verified routes'))
            width, height = min(width, screen_w - 40), min(height, screen_h - 70)
            win.geometry(f'{width}x{height}+20+20')
            win.deiconify()
            win.lift()
            win.focus_force()
            pump(.35)
            hwnd = ctypes.windll.user32.GetAncestor
            hwnd.argtypes = [ctypes.c_void_p, ctypes.c_uint]
            hwnd.restype = ctypes.c_void_p
            handle = hwnd(win.winfo_id(), 2)
            image = ImageGrab.grab(window=handle)
            path = args.output / filename
            image.save(path, optimize=True)
            records.append(dict(file=filename, language=language, title=win.title(),
                                width=image.width, height=image.height,
                                sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
            print(f'{filename}: {image.width}x{image.height}', flush=True)
            if win is not root:
                win.withdraw()

        try:
            # Main window: two independently specified products and dynamic evidence.
            app.kind.set('stations')
            for cond in (
                dict(field='modules', op='in', values=['Shield Booster'], **{'class': [0], 'rating': ['A']}, discounted=True, module_slot='通用插槽'),
                dict(field='modules', op='in', values=['Plasma Accelerator'], **{'class': [2], 'rating': ['C']}, discounted=True, module_slot='武器挂点'),
                dict(field='distance_to_arrival', op='<', text=1500),
                dict(type='distance', ref_system='Sol', min_ly=None, max_ly=500, mode='inside')):
                app._append_cond(cond)
            for row in app.rows[:2]:
                row.v_category.set('商品与舰船模组')
                row.set_fields('stations')
            stock = [dict(name='Shield Booster', **{'class': 0, 'rating': 'A'}),
                     dict(name='Plasma Accelerator', **{'class': 2, 'rating': 'C'})]
            shops = [dict(name=f'Demo Outfitting {letter}', system_name=f'Demo System {letter}',
                          type='Coriolis Starport', is_planetary=False, modules=copy.deepcopy(stock),
                          system_controlling_power='Li Yong-Rui', system_power_state='Fortified',
                          distance_to_arrival=arrival,
                          _distances={'Sol': 34.75 + index * 12, 'LHS 336': first, 'Leesti': second},
                          _shopping_route=shopping.route_metrics((0, 0, 0), (320, 0, 0), point, 80))
                     for index, (letter, arrival, first, second, point) in enumerate((
                         ('A', 90, 160, 160, (160, 0, 0)), ('B', 425, 80, 240, (80, 0, 0)),
                         ('C', 970, 123.693, 202.237, (120, 30, 0))))]
            app.results = copy.deepcopy(shops)
            app._result_kind = 'stations'
            app._result_conditions = gui.eng.normalize_conditions('stations', app.collect())
            app.render_main_results()
            app.tree.sort_by('name')

            engineer = app.engineer_shopping_window()
            for key, value in dict(origin='LHS 336', destination='Didi Vatermann — Leesti',
                                   jump_range='80', max_extra_jumps='1').items():
                engineer.session_variables[key].set(value)
            engineer.session_variables['ignore_planetary'].set(True)
            engineer.purchase_row.val.set('Shield Booster')
            engineer.purchase_row.v_slot.set('通用插槽')
            engineer.purchase_row.v_spec.set('0A')
            engineer.add_purchase(dict(value='Plasma Accelerator', module_spec='2C', module_slot='武器挂点', discount='是'))
            conditions = engineer.criteria()[0].conditions
            conditions += [dict(type='distance', ref_system=ref, min_ly=None, max_ly=500, mode='inside')
                           for ref in ('LHS 336', 'Leesti')]
            engineer.search_state['result'] = dict(rows=copy.deepcopy(shops), conditions=conditions,
                                                  total=3, scanned=3, notes=['UI demonstration dataset'], stopped=False)

            outfitting = app.full_outfitting_window()
            outfitting.search_state['result'] = dict(
                rows=[dict(name='Demo Fully Outfitted Station', system_name='Demo System A',
                           distance=42.5, distance_to_arrival=125, needs_permit=False,
                           technology_broker='Guardian', outfitting_updated_at='2026-10-20T00:00:00Z',
                           _full_outfitting=dict(present=792, required=792, discount_min=15, discount_max=15,
                                                discount_covered=792, discount_total=792, sources=['Li Yong-Rui']))],
                criteria=vars(outfitting.criteria()[0]), search_limits=dict(want=50, max_pages=25),
                snapshot_created_at='2026-10-20T00:00:00+00:00',
                snapshot_scope=dict(reference='Sol', radius=20000),
                catalog_revision='UI demonstration catalogue', notes=['UI demonstration dataset'])

            rare = app.rare_goods_window()
            if rare is None:
                rare = next(w for w in root.winfo_children() if getattr(w, '_raw_title', '') == '稀有商品目标查找器')
            rare.session_variables['neutron_only'].set(True)
            rare.rare_state['info'] = dict(neutron_filter=True, complete=False, notes=['UI demonstration dataset'])
            power = 'A. Lavigny-Duval'
            rare_rows = [dict(name=f'Demo Starport {letter}', system_name=f'Demo Target {letter}',
                              _powerplay_distance=distance, distance_to_arrival=arrival, updated_at='2026-10-17T00:00:00Z',
                              _neutron=dict(outbound_anchors=['Demo Neutron A'], inbound_anchors=['Demo Neutron A'],
                                            direction_deg=angle, detour_ly=detour, alignment_label='优先顺路'))
                         for letter, distance, arrival, angle, detour in (
                             ('A', 205.35, 48, 12.5, 8.3), ('B', 211.46, 67, 18.4, 12.2), ('C', 217.8, 92, 25.1, 18.7))]
            rare.rare_state['groups'] = {power: dict(rows=rare_rows, system_count=3, arrival_limit=100, status='标准范围')}
            summary = next(t for t in trees(rare) if 'systems' in t['columns'])
            summary.insert('', 'end', iid=power, values=('Arissa Lavigny-Duval', '3', '100.00', '标准范围'))
            button(rare, '全部组明细').invoke()
            rare.result_tree.sort_by('ly')

            carrier = open_named(app.carrier_parking_window, '航母车位查找')
            carrier.session_variables['reference'].set('Sol')
            carrier.session_variables['radius'].set('15')
            carrier.session_variables['max_carriers'].set('10')
            carrier_tree = trees(carrier)[0]
            for name, distance, count, total in (('Demo System A', 4.35, 0, 2), ('Demo System B', 7.8, 3, 7), ('Demo System C', 12.6, 8, 12)):
                carrier_tree.insert('', 'end', values=(name, f'{distance:.2f}', str(count), str(total), '按已收录航母统计', '免许可', '0.5 d'))
            carrier_tree.sort_by('carriers')

            midpoint = open_named(app.midpoint_window, '两系中点 - 离中点最近的星系')
            midpoint.session_variables['b'].set('Ngurii')
            midpoint_tree = trees(midpoint)[0]
            for letter, distance in (('A', 1.85), ('B', 3.7), ('C', 5.45)):
                midpoint_tree.insert('', 'end', values=(f'Demo Midpoint {letter}', f'{distance:.2f}', '64.30', '65.20', 'pop 1,234,567 | Federation | 免许可'))
            midpoint_tree.sort_by('dmid')

            pve = app.pve_window()
            for key, value in dict(reference='Sol', radius='50', source_pad='L', source_station_max_ls='500', target_ring_max_ls='1500').items():
                pve.session_variables[key].set(value)
            for index, letter in enumerate('ABC'):
                data = dict(source=f'Demo Source {letter}', target=f'Demo Target {letter}', distance=f'{12.5 + index * 5:.2f}',
                            site='RES Low', factions='4', federation='2', empire='1', source_controller='Demo Cooperative',
                            target_controller='Demo Pirates', source_power='Yuri Grom', target_power='Yuri Grom',
                            count_source='Spansh', site_record='Demo RES Low', source_updated='2026-10-17', target_updated='2026-10-17',
                            source_station=f'Demo Starport {letter}', source_station_pad='L', source_station_ls='125.00',
                            target_ring_body=f'Demo Target {letter} 1', target_ring_ls='640.00')
                pve.result_tree.insert('', 'end', values=[data.get(key, '') for key in pve.result_tree['columns']])
            pve.result_tree.sort_by('distance')

            colony = app.colonisation_window()
            colony.session_variables['reference'].set('Sol')
            colony.session_variables['radius'].set('100')
            colony.session_variables['populated_radius'].set('10')
            colony.group_editors['body_groups'].add_group([dict(field='subtype', op='=', value='Water world')])
            for index, letter in enumerate('ABC'):
                data = dict(name=f'Demo Frontier {letter}', scan1=f'Demo {letter} 1 | Water world | 55,000 Cr',
                            scan2=f'Demo {letter} 2 | High metal content world | 16,000 Cr', scan3='无更多星球',
                            neighbour=f'Demo Neighbour {letter}', near_distance=f'{4.5 + index:.2f}', neighbour_pad='L',
                            distance=f'{44.5 + index * 10:.2f}', value='1,234,567', body_matches=f'Demo {letter} 1',
                            ring_matches='', relations='', scan_status='已记录天体完整', updated='2026-10-17')
                colony.result_tree.insert('', 'end', values=[data.get(key, '') for key in colony.result_tree['columns']])
            colony.result_tree.sort_by('near_distance')

            windows = [root, rare, pve, carrier, midpoint, colony, engineer, outfitting]
            for win in windows[1:]:
                win.withdraw()
            for language in ('zh', 'en'):
                app.set_language(language)
                pump()
                suffix = '-en' if language == 'en' else ''
                app.tree.xview_moveto(0)
                capture(root, f'main-gui{suffix}.png', language, width=2400, height=920)
                capture(rare, f'rare-goods-target-finder{suffix}.png', language)
                pve.result_tree.xview_moveto(0)
                capture(pve, 'pirate-massacre-finder-summary-en.png' if language == 'en' else 'pirate-massacre-finder-zh.png', language)
                pve.result_tree.xview_moveto(1)
                capture(pve, 'pirate-massacre-finder-en.png' if language == 'en' else 'pirate-massacre-finder-details-zh.png', language)
                capture(carrier, f'carrier-parking-finder{suffix}.png', language, width=1300, height=690)
                capture(midpoint, f'system-midpoint-finder{suffix}.png', language, width=1100, height=650)
                colony.result_tree.xview_moveto(0)
                capture(colony, f'colonisation-finder{suffix}.png', language, width=1700, height=930)
                colony.result_tree.xview_moveto(1)
                capture(colony, f'colonisation-finder-details{suffix}.png', language, width=1700, height=930)
                engineer.result_tree.xview_moveto(0)
                engineer.result_tree.sort_by(f'value_{len(engineer.result_tree["columns"]) - 2}')
                capture(engineer, f'engineer-shopping{suffix}.png', language, width=1600, height=930)
                engineer.result_tree.xview_moveto(1)
                capture(engineer, f'engineer-shopping-route-details{suffix}.png', language, width=1600, height=930)
                capture(outfitting, f'full-outfitting-finder{suffix}.png', language, width=1600, height=1000)
            # The nested main-window system-condition editor is another new UI.
            from main_system_gui import DetailsRow
            app.kind.set('systems')
            detail_row = DetailsRow(app.inner, 'systems')
            detail_row.apply_condition(dict(nearest_max=10, population_min=1,
                                            body_groups=[[dict(field='subtype', op='=', value='Water world')]],
                                            ring_groups=[[dict(field='ring.type', op='=', value='Metal Rich')]]))
            detail = detail_row.open_editor()
            for language in ('zh', 'en'):
                app.set_language(language)
                capture(detail, f'main-system-details{"-en" if language == "en" else ""}.png', language, width=1500, height=1100)
            manifest = dict(version=PROJECT_VERSION, captured_at=datetime.now().astimezone().isoformat(timespec='seconds'),
                            data='Offline illustrative fixtures; not live game records or verified routes.', screenshots=records)
            (args.output / 'screenshots.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
            print(f'Captured {len(records)} screenshots; no network or personal sessions used.')
        finally:
            app._closing = True
            root.destroy()


if __name__ == '__main__':
    main()
