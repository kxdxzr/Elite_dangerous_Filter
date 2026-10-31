"""PvE search GUI; all Tk work stays on the main thread."""
import csv
from export_metadata import write_csv_provenance
from result_format import format_ly, format_ls, format_number
from result_copy import copy_result
import threading
import tkinter as tk
import webbrowser
import json
from datetime import datetime
from tkinter import filedialog

from localized_tk import ttk, messagebox, Toplevel
import pve_tool as tool
import faction_options
from powerplay_tool import POWERS, POWER_LABELS, normalize_power

NOTE_CN = '候选地点不保证实时任务。配对与 RES/CNB 数据来自 EDTools；非无政府小派系数量仅估计可能发任务的派系。星环视为推定 RES，不推定 Low；明确无环视为无 RES，CNB 独立判断；数据缺失仍为情况未知。请在游戏中确认 BGS、声望和任务。'


def open_window(app):
    win = Toplevel(app.root)
    win.title('海盗任务查找器')
    win.geometry('1400x820')
    from form_scroll import settings_form
    form = settings_form(win)
    controls = ttk.Frame(form, padding=8)
    controls.pack(fill='x')
    variables = {key: tk.StringVar(win, value=value) for key, value in {
        'reference': 'Sol', 'radius': '50', 'min_factions': '0', 'min_federation': '0', 'min_empire': '0',
        'source_faction': '', 'source_controller': '', 'target_controller': '', 'power': '',
        'power_scope': '任务来源', 'source_pad': '', 'source_station_max_ls': '', 'target_ring_max_ls': '',
         'site_type': '任意 RES（允许星环推定）'}.items()}
    variables.update(prefer_low=tk.BooleanVar(win, value=True), cnb_fallback=tk.BooleanVar(win, value=True))
    faction_feedback = tk.StringVar(win, value='输入至少两个字符联想；选择候选后使用完整名称。')
    faction_boxes = {}
    from filter_gui import attach_system_suggest
    site_values = {'任意 RES（允许星环推定）': 'any', '仅明确 RES': 'confirmed',
                   '仅 Low RES': 'low', '仅普通 RES': 'reg', '仅 High RES': 'high', '仅 Haz RES': 'haz'}
    control_widgets, action_widgets = {}, {}
    specs = [('site_type', 'RES 类型（任务派系数为0时）'),
             ('reference', '参考星系'), ('radius', '半径 ly（0=无限）'),
             ('min_factions', '最少任务派系（0–8）'), ('min_federation', '最少联邦派系（0–8）'),
             ('min_empire', '最少帝国派系（0–8）'), ('source_faction', '来源存在派系'),
             ('source_controller', '来源控制小派系'), ('target_controller', '目标控制小派系'),
             ('power', '控制 Power'), ('power_scope', 'Power 筛选对象'),
             ('source_pad', '来源停机坪（可停靠船型）'), ('source_station_max_ls', '来源空间站最大距离 Ls'),
             ('target_ring_max_ls', '目标星环最大距离 Ls')]
    for index, (key, label) in enumerate(specs):
        row, column = divmod(index, 5)
        ttk.Label(controls, text=label, wraplength=250).grid(row=row * 2, column=column, sticky='w', padx=5)
        var = variables[key]
        if key == 'site_type':
            entry = ttk.Combobox(controls, textvariable=var,
                                 values=list(site_values),
                                 state='readonly', width=26)
        elif key.startswith('min_'):
            entry = ttk.Combobox(controls, textvariable=var, values=list(range(9)), state='readonly', width=18)
        elif key == 'source_pad':
            entry = ttk.Combobox(controls, textvariable=var, values=['', 'S', 'M', 'L'], state='readonly', width=22)
        elif key == 'power_scope':
            entry = ttk.Combobox(controls, textvariable=var, values=['任务来源', '击杀目标', '双方'], state='readonly', width=22)
        elif key == 'power':
            entry = ttk.Combobox(controls, textvariable=var, values=[''] + [POWER_LABELS[p] for p in POWERS], width=24)
        elif key in ('source_faction', 'source_controller', 'target_controller'):
            entry = ttk.Combobox(controls, textvariable=var, width=26)
            attach_system_suggest(entry, var, faction_options.suggest_factions, faction_feedback)
            faction_boxes[key] = entry
        else:
            entry = ttk.Entry(controls, textvariable=var, width=26)
        entry.grid(row=row * 2 + 1, column=column, sticky='ew', padx=5, pady=(2, 8))
        control_widgets[key] = entry
        controls.columnconfigure(column, weight=1)
    actions = ttk.Frame(win, padding=8)
    actions.pack(fill='x')
    for key, text in [('prefer_low', '优先 RES Low'), ('cnb_fallback', '无 RES 命中时回退 CNB')]:
        button = ttk.Checkbutton(actions, text=text, variable=variables[key])
        button.pack(side='left', padx=4)
        action_widgets[key] = button
    from usage_help import usage_help
    win.usage_help = usage_help(form, (
        NOTE_CN,
        '距离留空不限；来源停机坪与距离须同站满足。星环距离为最近已知有环天体的到达 Ls，不是具体 RES 位置。',
        '未知目标自动用 Spansh 天体数据复核星环（距离留空也复核）；未查到星环则排除，查询失败或数据不完整仍为未知。',
        '补充的 RES 星系按目标距离、目标控制小派系筛选；有已知任务来源的优先，未收录显示无数据。',
        '最少任务派系数为0：保留任务结果并补充 RES 星系；1–8：仅检索海盗任务。0时来源条件停用但保留。',
    ))
    ttk.Label(form, textvariable=faction_feedback, style='Muted.TLabel').pack(fill='x', padx=8)
    status = tk.StringVar(win, value='半径针对任务来源星系；0 不限制距离。有环推定 RES；情况未知单独标注，不作为无 RES 的证据。')
    ttk.Label(win, textvariable=status, wraplength=1360).pack(fill='x', padx=8, pady=4)
    progress = ttk.Progressbar(win, mode='indeterminate')
    progress.pack(fill='x', padx=8)
    from search_progress import SearchProgress
    progress_text = tk.StringVar(win)
    ttk.Label(win, textvariable=progress_text).pack(fill='x', padx=8)
    tracker = SearchProgress(progress, progress_text, app.localizer)
    columns = [('source', '任务来源'), ('target', '目标星系'), ('distance', '距离 ly'), ('site', '战斗地点'),
               ('factions', '任务派系数'), ('federation', '联邦派系数'), ('empire', '帝国派系数'),
               ('source_controller', '来源控制派系'), ('target_controller', '目标控制派系'),
               ('source_power', '来源 Power'), ('target_power', '目标 Power'), ('count_source', '派系计数数据源'),
               ('site_record', '地点原始记录'), ('source_updated', '来源更新时间'), ('target_updated', '目标更新时间'),
               ('source_station', '匹配来源空间站'), ('source_station_pad', '来源站最大停机坪'),
               ('source_station_ls', '来源站距离 Ls'), ('target_ring_body', '目标有环天体'), ('target_ring_ls', '星环距离 Ls')]
    frame = ttk.Frame(win)
    frame.pack(fill='both', expand=True, padx=8, pady=6)
    tree = ttk.Treeview(frame, columns=[key for key, _ in columns], show='headings')
    for key, title in columns:
        tree.heading(key, text=title)
        tree.column(key, width=170 if key in ('source', 'target') or 'controller' in key else 120, stretch=False)
    vertical = ttk.Scrollbar(frame, orient='vertical', command=tree.yview)
    horizontal = ttk.Scrollbar(frame, orient='horizontal', command=tree.xview)
    tree.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
    tree.grid(row=0, column=0, sticky='nsew')
    vertical.grid(row=0, column=1, sticky='ns')
    horizontal.grid(row=1, column=0, sticky='ew')
    frame.rowconfigure(0, weight=1)
    frame.columnconfigure(0, weight=1)
    state = {'page': None, 'rows': [], 'info': None}

    def result_value(row, key):
        value = row.get(key, '')
        if value is None or value == '':
            return '-'
        if key == 'distance':
            return format_ly(value)
        if key in ('source_station_ls', 'target_ring_ls'):
            return format_ls(value, value if isinstance(value, str) else '')
        if key in ('factions', 'federation', 'empire'):
            return format_number(value, value)
        return value
    stop = threading.Event()

    def criteria():
        args = {key: variable.get() for key, variable in variables.items()}
        args['search_mode'] = 'expanded' if int(args['min_factions']) == 0 else 'missions'
        args['site_type'] = site_values[args['site_type']]
        if args['search_mode'] == 'expanded':
            # Preserve disabled editor drafts but never apply mission-only filters.
            args.update(min_factions='0', min_federation='0', min_empire='0', source_faction='',
                        source_controller='', source_pad='', source_station_max_ls='',
                        power_scope='击杀目标')
        args['radius'] = float(args['radius'])
        for key in ('source_station_max_ls', 'target_ring_max_ls'):
            args[key] = float(args[key]) if args[key].strip() else None
        for key in ('min_factions', 'min_federation', 'min_empire'):
            args[key] = int(args[key])
        args['power_scope'] = {'任务来源': 'source', '击杀目标': 'target', '双方': 'both'}[args['power_scope']]
        if args['power'].strip():
            args['power'] = normalize_power(args['power'])
        return tool.Criteria(**args).validate()

    def import_page():
        path = filedialog.askopenfilename(parent=win, filetypes=[('HTML', '*.html *.htm')])
        if path:
            search_button.configure(state='disabled')
            import_button.configure(state='disabled')
            online_button.configure(state='disabled')
            refresh_button.configure(state='disabled')
            tracker.update('正在导入网页...')
            status.set('正在导入网页...')
            def work():
                try:
                    with open(path, 'rb') as file:
                        body = file.read(64 * 1024 * 1024 + 1)
                    if len(body) > 64 * 1024 * 1024:
                        raise ValueError('Imported HTML exceeds 64 MiB.')
                    parsed = tool.parse_page(body.decode('utf-8-sig'))
                    def show():
                        state['page'] = parsed
                        status.set('已导入网页；点击开始查询应用条件。')
                        finish()
                        tracker.finish(True)
                    app._post(win, show)
                except (OSError, ValueError) as exc:
                    def failed(error=str(exc)):
                        status.set('导入失败；保留之前导入的数据。')
                        tracker.finish(False)
                        finish()
                        messagebox.showerror('数据错误', error, parent=win)
                    app._post(win, failed)
            threading.Thread(target=work, daemon=True).start()

    def use_online():
        state.update(page=None, rows=[], info=None)
        tree.delete(*tree.get_children())
        status.set('已切换在线数据；点击开始查询。')

    def open_page():
        try:
            webbrowser.open(tool.page_url(criteria()))
        except (ValueError, KeyError) as exc:
            messagebox.showwarning('参数错误', str(exc), parent=win)

    def finish():
        control_widgets['min_factions'].configure(state='readonly')
        search_button.configure(state='normal')
        import_button.configure(state='normal')
        online_button.configure(state='normal')
        refresh_button.configure(state='normal')
        progress.stop()
        sync_mode()

    def run(refresh=False):
        try:
            query = criteria()
        except (ValueError, KeyError) as exc:
            messagebox.showwarning('参数错误', str(exc), parent=win)
            return
        if refresh:
            state['page'] = None
        snapshot = state['page']
        control_widgets['min_factions'].configure(state='disabled')
        stop.clear()
        search_button.configure(state='disabled')
        import_button.configure(state='disabled')
        online_button.configure(state='disabled')
        refresh_button.configure(state='disabled')
        tracker.update()
        state.update(rows=[], info=None)
        tree.delete(*tree.get_children())
        status.set('查询中...')

        def work():
            try:
                info, rows = tool.search(query, page=snapshot, stop=stop, refresh=refresh,
                    progress=lambda text: app._post(win, lambda: (status.set(text), tracker.update(text))))

                def show():
                    state.update(rows=rows, info=info)
                    faction_options.remember(row.get(key, '') for row in rows
                                             for key in ('source_controller', 'target_controller'))
                    summary = (f"参考 {info.get('reference', query.reference)}，半径 {query.radius:,.2f} ly；{info['mode']}：命中 {len(rows):,} 条；已复核 {info['scanned']:,} 条。"
                               + ('已完成当前数据集检索。' if info['complete'] else '检索未完成；不能确认不存在 RES 命中。')
                               + (f" 数据错误 {len(info['errors'])} 条，详见检索说明。" if info['errors'] else '')
                               + f" 明确 RES：{info.get('confirmed_res', 0)}；星环推定：{info.get('inferred_res', 0)}；情况未知：{info.get('diagnostics', {}).get('unknown_sites', 0)}；用时 {info.get('timings', {}).get('total', 0):.2f} s。")
                    stamps = [item['fetched_at'] for item in info.get('dataset_cache', []) if item.get('fetched_at')]
                    if stamps:
                        summary += ' 数据获取时间：' + datetime.fromtimestamp(min(stamps)).isoformat(sep=' ', timespec='seconds')
                        summary += f"；缓存命中 {sum(bool(item.get('hit')) for item in info['dataset_cache'])}/{len(info['dataset_cache'])}。"
                    def render(start=0):
                        for row in rows[start:start + 200]:
                            tree.insert('', 'end', values=[result_value(row, key) for key, _ in columns])
                        if start + 200 < len(rows):
                            status.set(f'显示结果：{start + 200}/{len(rows)}')
                            app.root.after(1, lambda: app._post(win, render, start + 200))
                        else:
                            status.set(summary)
                            finish()
                            tracker.finish(info['complete'])
                    render()
                app._post(win, show)
            except Exception as exc:
                download_error = isinstance(exc, tool.PageDownloadError)
                def failed(error=str(exc), is_download=download_error,
                           url=exc.url if download_error else None):
                    status.set('查询失败，不能判断有无命中。可导入浏览器保存的 EDTools PvE 网页。')
                    finish()
                    if is_download:
                        prompt = ('完整数据下载失败。网页最多覆盖 250 ly，保存的 HTML 只能用于对应有限半径。是否打开网页？'
                                  if url in (tool.PAIRS_URL, tool.SITES_URL) else
                                  'EDTools 页面下载失败。是否打开对应网页？在浏览器保存 HTML 后，点击“导入 PvE 网页”继续查询。')
                        if messagebox.askyesno('EDTools 下载失败',
                            app.localizer.tr(prompt)
                            + '\n\n' + error, parent=win):
                            webbrowser.open(tool.page_url(query) if url in (tool.PAIRS_URL, tool.SITES_URL) else url)
                    else:
                        messagebox.showerror('查询失败', error, parent=win)
                    tracker.finish(False)
                app._post(win, failed)
        threading.Thread(target=work, daemon=True).start()

    def export():
        if not state['rows']:
            messagebox.showinfo('提示', '暂无结果', parent=win)
            return
        path = filedialog.asksaveasfilename(parent=win, defaultextension='.csv', filetypes=[('CSV', '*.csv')])
        if path:
            with open(path, 'w', encoding='utf-8-sig', newline='') as file:
                writer = csv.writer(file)
                write_csv_provenance(writer, len(columns), app.localizer.language)
                writer.writerow([app.localizer.tr(label) for _, label in columns])
                writer.writerows([app.localizer.tr(result_value(row, key))
                                   for key, _ in columns] for row in state['rows'])

    def copy_target(event=None):
        copy_system(1)

    def copy_system(column):
        copy_result(win, tree, columns[column][0])

    tree.bind('<Double-1>', copy_target)
    search_button = ttk.Button(actions, text='开始查询', command=run)
    search_button.pack(side='left', padx=8)
    ttk.Button(actions, text='停止', command=stop.set).pack(side='left')
    import_button = ttk.Button(actions, text='导入 PvE 网页', command=import_page)
    import_button.pack(side='left', padx=8)
    page_button = ttk.Button(actions, text='打开 PvE 网页', command=open_page)
    page_button.pack(side='left')
    online_button = ttk.Button(actions, text='使用在线数据', command=use_online)
    online_button.pack(side='left', padx=8)
    footer = ttk.Frame(win, padding=8)
    footer.pack(side='bottom', fill='x', before=frame)
    ttk.Button(footer, text='导出 CSV', command=export).pack(side='left')
    ttk.Button(footer, text='复制目标星系', command=copy_target).pack(side='left', padx=8)
    ttk.Button(footer, text='复制任务来源星系', command=lambda: copy_system(0)).pack(side='left', padx=8)
    ttk.Button(footer, text='复制来源空间站', command=lambda: copy_result(win, tree, 'source_station')).pack(side='left', padx=8)
    refresh_button = ttk.Button(footer, text='刷新数据并查询', command=lambda: run(refresh=True))
    refresh_button.pack(side='left', padx=8)
    ttk.Button(footer, text='检索说明', command=lambda: messagebox.showinfo('检索说明',
        NOTE_CN + '\n\n' + '\n'.join((state['info'] or {}).get('notes', [])) + '\n\n'
        + '\n'.join((state['info'] or {}).get('errors', []))
        + '\n\n' + app.localizer.tr('分阶段耗时：') + json.dumps((state['info'] or {}).get('timings', {}), indent=2)
        + '\n\n' + app.localizer.tr('缓存信息：') + json.dumps({key: (state['info'] or {}).get(key, [])
            for key in ('dataset_cache', 'controller_cache', 'power_cache')}, ensure_ascii=False, indent=2), parent=win)).pack(side='left')
    app.bind_tool_state('pve', win, variables)
    if variables['site_type'].get() not in site_values:
        variables['site_type'].set('任意 RES（允许星环推定）')

    def sync_mode(*args):
        res_mode = variables['min_factions'].get() == '0'
        mission_only = ('min_federation', 'min_empire', 'source_faction',
                        'source_controller', 'power_scope', 'source_pad', 'source_station_max_ls')
        readonly = ('min_factions', 'min_federation', 'min_empire', 'power_scope', 'source_pad')
        for key in mission_only:
            control_widgets[key].configure(state='disabled' if res_mode else 'readonly' if key in readonly else 'normal')
        control_widgets['site_type'].configure(state='readonly' if res_mode else 'disabled')
        action_widgets['cnb_fallback'].configure(state='normal')
        for button in (import_button, page_button):
            button.configure(state='disabled' if res_mode else 'normal')
    variables['min_factions'].trace_add('write', sync_mode)
    sync_mode()
    win.protocol('WM_DELETE_WINDOW', lambda: (stop.set(), win.destroy()))
    # Source smoke tests can exercise the real UI without invoking network queries.
    win.result_tree, win.search_state = tree, state
    win.faction_boxes, win.faction_feedback = faction_boxes, faction_feedback
    win.criteria, win.control_widgets = criteria, control_widgets
    def dispose(event):
        if event.widget is win:
            # Debug/accessor attributes must not leave window -> child -> window
            # cycles whose Tk variables might be collected by a worker thread.
            faction_boxes.clear()
            control_widgets.clear()
            action_widgets.clear()
            win.criteria = win.control_widgets = None
            win.result_tree = win.search_state = win.faction_feedback = None
            win.session_variables = {}
    win.bind('<Destroy>', dispose, add='+')
    return win
