"""Full-outfitting finder; worker threads communicate through a Tk queue."""
import csv
from datetime import datetime, timezone
import queue
import threading
import tkinter as tk
from tkinter import filedialog, font as tkfont

import full_outfitting as tool
import catalog_updates
import outfitting_snapshot
from export_metadata import write_csv_provenance
from localized_tk import ttk, Toplevel, messagebox
from result_copy import copy_result
from search_progress import SearchProgress


def cache_age_text(stamp, tr=lambda text: text, now=None):
    if stamp is None:
        return tr('暂无缓存')
    try:
        created = datetime.fromisoformat(stamp.replace('Z', '+00:00'))
        if created.tzinfo is None:
            raise ValueError('Missing timezone')
        days = max(0, int(((now or datetime.now(timezone.utc)) - created).total_seconds() // 86400))
    except (ValueError, TypeError, AttributeError, OverflowError):
        return tr('缓存时间无效，请更新数据')
    return tr('缓存于（{days}）天之前').format(days=days)


def open_window(app):
    from filter_gui import attach_system_suggest

    win = Toplevel(app.root)
    win.title('查找满配件空间站')
    win.geometry('1320x820')
    variables = {name: tk.StringVar(win, value=value) for name, value in
                 dict(reference='Sol', radius='200', want='50', max_pages='25').items()}
    for name in ('other_discounts', 'neutral_ships', 'federal_ships', 'imperial_ships', 'guardian', 'special_equipment', 'require_discount', 'ax_weapons', 'universal_limpets'):
        variables[name] = tk.BooleanVar(win, value=False)
    app.bind_tool_state('full_outfitting', win, variables)
    controls = ttk.Frame(win, padding=8)
    controls.pack(fill='x')
    for index, (name, label) in enumerate((('reference', '参考星系'), ('radius', '半径 ly'),
                                          ('want', '最多结果'), ('max_pages', '最多页数'))):
        ttk.Label(controls, text=label).grid(row=0, column=index * 2, padx=4)
        if name == 'reference':
            entry = ttk.Combobox(controls, textvariable=variables[name], width=24)
            attach_system_suggest(entry, variables[name])
        else:
            entry = ttk.Entry(controls, textvariable=variables[name], width=9)
        entry.grid(row=0, column=index * 2 + 1, sticky='ew', padx=4)
    controls.columnconfigure(1, weight=1)
    choices = ttk.LabelFrame(win, text='附加条件', padding=6)
    choices.pack(fill='x', padx=8, pady=4)
    for name, label in (('neutral_ships', '全部非势力船（含联盟）'), ('federal_ships', '全部联邦船'),
                         ('imperial_ships', '全部帝国船'), ('guardian', '同站 Guardian 科技经纪人')):
        ttk.Checkbutton(choices, text=label, variable=variables[name]).pack(side='left', padx=5)
    discount_box = ttk.Checkbutton(win, text='必须全部已选必需配件都有公共折扣（默认关闭）',
                                   variable=variables['require_discount'])
    discount_box.pack(anchor='w', padx=12)
    other_discount_box = ttk.Checkbutton(win, text='包含其他全配件公共折扣站（如 Jameson Memorial）',
                                         variable=variables['other_discounts'])
    other_discount_box.pack(anchor='w', padx=28)

    def discount_state(*args):
        other_discount_box.configure(state='normal' if variables['require_discount'].get() else 'disabled')

    discount_trace = variables['require_discount'].trace_add('write', discount_state)
    discount_state()
    ttk.Checkbutton(win, text='同站AX装备规格齐全（含武器及支援设备，默认关闭）',
                    variable=variables['ax_weapons']).pack(anchor='w', padx=12)
    ttk.Checkbutton(win, text='同站通用无人机控制器7A及7C齐全（默认关闭）',
                    variable=variables['universal_limpets']).pack(anchor='w', padx=12)
    ttk.Checkbutton(win, text='额外要求 Merc Coins 特殊装备齐全（默认不要求）',
                    variable=variables['special_equipment']).pack(anchor='w', padx=12)
    ttk.Label(win, text='默认不要求折扣；启用后默认LYR 15%，可包含其他公共优惠。始终排除航母及要塞航母。',
              wraplength=1260).pack(fill='x', padx=8)
    ttk.Label(win, text='普通／Power须全实际规格，AX装备单独可选；默认已有购买资格。Merc装备不推定代币折扣。',
              wraplength=1260, style='Muted.TLabel').pack(fill='x', padx=8)
    ttk.Label(win, text='舰船勾选同时检查对应船体装甲，不要求舰船折扣。库存及目录非实时，缺失数据不能证明齐全。',
               wraplength=1260, style='Muted.TLabel').pack(fill='x', padx=8)
    cache_notice = ttk.Label(win, text='首次扫描需要建立缓存，因此会很慢；缓存完成后，后续查询会更快。',
                             wraplength=1260)
    cache_notice_font = tkfont.nametofont('TkDefaultFont').copy()
    cache_notice_font.configure(weight='bold')
    cache_notice.configure(font=cache_notice_font)
    cache_notice.pack(fill='x', padx=8)
    win.cache_notice, win.cache_notice_font = cache_notice, cache_notice_font
    ttk.Label(win, text='首次及手动更新固定扫描Sol周围20,000 ly的最宽松站点名单；再按表单筛选。换星系只查询坐标并重算距离，不重扫库存。',
              wraplength=1260, style='Muted.TLabel').pack(fill='x', padx=8)
    ttk.Label(win, text='主要适用于Bubble（人类核心居住区）；远离Bubble后，现有站点名单可能不再适用或没有结果。换参考星系只重算距离，不会自动发现当地站点。',
              wraplength=1260, style='Muted.TLabel').pack(fill='x', padx=8)
    actions = ttk.Frame(win, padding=8)
    actions.pack(fill='x')
    status = tk.StringVar(win, value='就绪')
    ttk.Label(win, textvariable=status, wraplength=1260).pack(fill='x', padx=8)
    bar = ttk.Progressbar(win, mode='determinate')
    bar.pack(fill='x', padx=8)
    progress_text = tk.StringVar(win)
    ttk.Label(win, textvariable=progress_text).pack(fill='x', padx=8)
    tracker = SearchProgress(bar, progress_text, app.localizer)
    frame = ttk.Frame(win)
    frame.pack(fill='both', expand=True, padx=8, pady=2)
    keys = [field for field, _ in tool.COLUMNS]
    tree = ttk.Treeview(frame, columns=keys, show='headings')
    tree.grid(row=0, column=0, sticky='nsew')
    vertical = ttk.Scrollbar(frame, orient='vertical', command=tree.yview)
    vertical.grid(row=0, column=1, sticky='ns')
    horizontal = ttk.Scrollbar(frame, orient='horizontal', command=tree.xview)
    horizontal.grid(row=1, column=0, sticky='ew')
    tree.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
    frame.rowconfigure(0, weight=1)
    frame.columnconfigure(0, weight=1)
    stop, events = threading.Event(), queue.Queue()
    state = dict(busy=False, result=None, updating=False)
    catalog_version = tk.StringVar(win)
    cache_age = tk.StringVar(win, value=app.localizer.tr('正在读取缓存时间…'))
    cache_info = dict(stamp=None, loaded=False)

    def render_cache_age():
        text = (cache_age_text(cache_info['stamp'], app.localizer.tr) if cache_info['loaded']
                else app.localizer.tr('正在读取缓存时间…'))
        if cache_age.get() != text:
            cache_age.set(text)

    cache_age_label = ttk.Label(actions, textvariable=cache_age, style='Muted.TLabel')
    cache_age_label.pack(side='right', padx=4)

    def read_cache_age():
        try:
            snapshot = outfitting_snapshot.read()
            events.put(('cache_age', snapshot['created_at'] if snapshot else None))
        except (ValueError, OSError):
            events.put(('cache_age', ''))

    threading.Thread(target=read_cache_age, daemon=True).start()

    def show_catalog_version():
        try:
            package = catalog_updates.read_package()
            value = package['version'] if package else app.localizer.tr('内置目录')
        except (ValueError, OSError):
            value = app.localizer.tr('本地更新清单无效，查询时回退原目录')
        catalog_version.set(app.localizer.tr('已安装装备清单（更新数据后应用）') + ': ' + value)

    show_catalog_version()
    poll_id = None

    def criteria():
        options = {name: variables[name].get() for name in
                   ('other_discounts', 'neutral_ships', 'federal_ships', 'imperial_ships', 'guardian', 'special_equipment', 'require_discount', 'ax_weapons', 'universal_limpets')}
        value = tool.build_criteria(variables['reference'].get(), variables['radius'].get(), **options)
        want, pages = int(variables['want'].get()), int(variables['max_pages'].get())
        if want < 1 or pages < 1:
            raise ValueError('结果数和页数必须大于零')
        return value, want, pages

    def render():
        headers, records = tool.export_table(state['result'], app.localizer.tr)
        tree.delete(*tree.get_children())
        for field, header in zip(keys, headers):
            tree.heading(field, text=header)
            tree.column(field, width=190 if field in ('name', 'system_name', 'sources') else 140,
                        minwidth=80, stretch=False)
        for index, values in enumerate(records):
            tree.insert('', 'end', iid=str(index), values=values)

    def run(refresh=False):
        if state['busy'] or state['updating']:
            return
        try:
            value, want, pages = criteria()
        except (ValueError, TypeError) as exc:
            messagebox.showwarning('条件有误', str(exc), parent=win)
            return
        stop.clear()
        state.update(busy=True)
        status.set(app.localizer.tr('正在查询…'))
        tracker.update()
        search_button.configure(state='disabled')
        refresh_button.configure(state='disabled')
        update_button.configure(state='disabled')
        rollback_button.configure(state='disabled')

        def worker():
            try:
                result = outfitting_snapshot.search(value, want=want, max_pages=pages, stop=stop, refresh=refresh,
                                     progress=lambda text, detail=None: events.put(('progress', (text, detail))))
                events.put(('done', result))
            except Exception as exc:
                events.put(('error', str(exc)))
        threading.Thread(target=worker, daemon=True).start()

    def export():
        result = state['result']
        if not result or not result['rows']:
            messagebox.showinfo('提示', '暂无结果', parent=win)
            return
        if (result.get('partial') or result.get('stopped')) and not messagebox.askyesno(
                '确认', '检索未完成，仅导出已核验的部分结果？', parent=win):
            return
        path = filedialog.asksaveasfilename(parent=win, defaultextension='.csv', filetypes=[('CSV', '*.csv')])
        if path:
            try:
                headers, records = tool.export_table(result, app.localizer.tr)
                with open(path, 'w', newline='', encoding='utf-8-sig') as file:
                    writer = csv.writer(file)
                    write_csv_provenance(writer, len(headers), app.localizer.language,
                                         search_conditions=tool.export_search_conditions(result, app.localizer.tr))
                    writer.writerow(headers)
                    for values in records:
                        writer.writerow(["'" + value if isinstance(value, str) and value != '-' and
                                         value.lstrip().startswith(('=', '+', '-', '@')) else value for value in values])
            except OSError as exc:
                messagebox.showerror('导出失败', str(exc), parent=win)

    def diagnostics():
        result = state['result']
        if result is None:
            return
        dialog = Toplevel(win)
        dialog.title('检索说明')
        dialog.geometry('1000x650')
        text = tk.Text(dialog, wrap='word')
        scroll = ttk.Scrollbar(dialog, command=text.yview)
        scroll.pack(side='right', fill='y')
        text.pack(fill='both', expand=True)
        text.configure(yscrollcommand=scroll.set)
        lines = [f"{result['catalog_revision']} / {result.get('catalog_size', 0)}",
                 app.localizer.tr('仅待身份复核（其他要求均满足）') + f": {result.get('uncertain', 0)}",
                 app.localizer.tr('库存未齐或未收录') + f": {result.get('incomplete', 0)}",
                 app.localizer.tr('其他条件未满足或无法确认') + f": {result.get('condition_failures', 0)}",
                 *result['notes']]
        lines.extend(str(issue) for issue in result.get('catalog_issues', []))
        lines.extend(str(issue) for issue in result.get('special_issues', []))
        lines.extend(str(error) for error in result.get('special_errors', []))
        if result.get('reference'):
            lines.append(app.localizer.tr('创世参照（独立于筛选结果）'))
            lines.append(str(result['reference']))
        lines.append(app.localizer.tr('同编号身份冲突不等于缺货，也不能证明齐全'))
        lines.append(app.localizer.tr('已按数字ID区分的共享符号组') + f": {result.get('catalog_shared_symbols', 0)}")
        lines.extend(str(conflict) for conflict in result.get('catalog_conflicts', []))
        for row in result['diagnostics']:
            evidence = row['_full_outfitting']
            lines.extend(['', f"{row.get('system_name')} / {row.get('name')}",
                          app.localizer.tr('仅待身份复核（其他要求均满足）' if evidence.get('review_status') == 'identity_pending'
                                           else '库存未齐或未收录' if evidence.get('review_status') == 'incomplete'
                                           else '其他条件未满足或无法确认'),
                          *evidence['problems'], *evidence.get('missing_ships', []),
                          app.localizer.tr('未收录规格（不代表确认缺货）') + ':', *evidence['missing'],
                          app.localizer.tr('名称或规格冲突，无法确认') + ':', *evidence.get('unknown', [])])
            if result.get('criteria', {}).get('require_discount'):
                lines.extend([app.localizer.tr('未确认折扣') + ':', *evidence['no_discount']])
            else:
                lines.append(app.localizer.tr('未启用折扣筛选'))
        text.insert('1.0', '\n'.join(app.localizer.tr(line) for line in lines))
        text.configure(state='disabled')

    def update_catalog(action='check', manifest=None):
        if state['busy'] or state['updating']:
            return
        state['updating'] = True
        for button in (search_button, refresh_button, update_button, rollback_button):
            button.configure(state='disabled')
        status.set(app.localizer.tr('正在更新装备清单…'))

        def worker():
            try:
                value = (catalog_updates.check() if action == 'check' else
                         catalog_updates.install(manifest) if action == 'install' else catalog_updates.rollback())
                events.put(('catalog_' + action, value))
            except Exception as exc:
                events.put(('catalog_error', str(exc)))
        threading.Thread(target=worker, daemon=True).start()

    search_button = ttk.Button(actions, text='查询', command=run)
    search_button.pack(side='left', padx=4)
    ttk.Button(actions, text='停止', command=stop.set).pack(side='left', padx=4)
    refresh_button = ttk.Button(actions, text='更新数据并查询', command=lambda: run(True))
    refresh_button.pack(side='left', padx=4)
    ttk.Button(actions, text='复制星系名', command=lambda: copy_result(win, tree, 'system_name')).pack(side='left', padx=4)
    ttk.Button(actions, text='复制站名', command=lambda: copy_result(win, tree, 'name')).pack(side='left', padx=4)
    ttk.Button(actions, text='导出CSV', command=export).pack(side='left', padx=4)
    ttk.Button(actions, text='检索说明', command=diagnostics).pack(side='left', padx=4)
    catalog_actions = ttk.Frame(win, padding=(8, 0))
    catalog_actions.pack(fill='x', before=frame)
    catalog_version_label = ttk.Label(catalog_actions, textvariable=catalog_version)
    catalog_version_label.pack(side='right', padx=4)
    update_button = ttk.Button(catalog_actions, text='检查装备清单更新', command=update_catalog)
    update_button.pack(side='left', padx=4)
    rollback_button = ttk.Button(catalog_actions, text='回退装备清单', command=lambda: update_catalog('rollback'))
    rollback_button.pack(side='left', padx=4)
    tree.bind('<Double-1>', lambda event: copy_result(win, tree, 'system_name'))

    def poll():
        nonlocal poll_id
        try:
            while True:
                kind, data = events.get_nowait()
                if kind == 'cache_age':
                    stamp = (state['result'] or {}).get('snapshot_created_at', data)
                    cache_info.update(stamp=stamp, loaded=True)
                    continue
                if kind.startswith('catalog_'):
                    state['updating'] = False
                    for button in (search_button, refresh_button, update_button, rollback_button):
                        button.configure(state='normal')
                    if kind == 'catalog_error':
                        status.set(app.localizer.tr('装备清单更新失败，保留原版本'))
                        messagebox.showerror('装备清单', data, parent=win)
                    elif kind == 'catalog_check':
                        try:
                            current = catalog_updates.read_package()
                        except (ValueError, OSError):
                            current = None
                        if data is None:
                            status.set(app.localizer.tr('GitHub尚未发布装备清单'))
                        elif current and catalog_updates.version(data['version']) <= catalog_updates.version(current['version']):
                            status.set(app.localizer.tr('装备清单已是最新版本'))
                        elif messagebox.askyesno('装备清单',
                                app.localizer.tr('下载并应用装备清单？') + '\n' + data['version'] + '\n' + data['summary'], parent=win):
                            update_catalog('install', data)
                        else:
                            status.set(app.localizer.tr('已取消清单更新'))
                    else:
                        show_catalog_version()
                        status.set(app.localizer.tr('装备清单已更新，下次查询生效') + ': ' + str(data))
                    continue
                if kind == 'progress':
                    text, detail = data
                    status.set(app.localizer.tr(text))
                    tracker.update(text, detail)
                    continue
                state['busy'] = False
                search_button.configure(state='normal')
                refresh_button.configure(state='normal')
                update_button.configure(state='normal')
                rollback_button.configure(state='normal')
                tracker.finish(kind == 'done' and data.get('complete', False))
                if kind == 'error':
                    status.set(data)
                    messagebox.showerror('查询失败', data, parent=win)
                else:
                    state['result'] = data
                    if data.get('snapshot_created_at'):
                        cache_info.update(stamp=data['snapshot_created_at'], loaded=True)
                    render()
                    summary = app.localizer.tr(f"已扫描：{data['scanned']}；命中：{len(data['rows'])}。")
                    summary += ' ' + app.localizer.tr('仅待身份复核') + f": {data.get('uncertain', 0)}；"
                    summary += app.localizer.tr('库存未齐或未收录') + f": {data.get('incomplete', 0)}。"
                    if data.get('snapshot_created_at'):
                        summary += ' ' + app.localizer.tr('库存快照时间') + ': ' + data['snapshot_created_at']
                    if data.get('partial'):
                        summary += ' ' + app.localizer.tr('检索未完成，已保留通过核验的部分结果')
                    if data.get('errors'):
                        error = data['errors'][0]
                        summary += f" [{error['source']} / {error['page']}: {error['message'][:180]}]"
                    status.set(summary)
        except queue.Empty:
            pass
        render_cache_age()
        poll_id = win.after(100, poll)

    def destroy(event):
        if event.widget is win:
            stop.set()
            variables['require_discount'].trace_remove('write', discount_trace)
            if poll_id is not None:
                win.after_cancel(poll_id)
            app.localizer.callbacks.discard(render)
            app.localizer.callbacks.discard(render_cache_age)

    app.localizer.register(render)
    app.localizer.register(render_cache_age)
    win.bind('<Destroy>', destroy, add='+')
    win.criteria, win.run_search, win.export_csv = criteria, run, export
    win.result_tree, win.search_state = tree, state
    win.discount_requirement_box, win.other_discount_box = discount_box, other_discount_box
    win.update_catalog, win.catalog_version = update_catalog, catalog_version
    win.cache_age = cache_age
    win.cache_age_label = cache_age_label
    poll()
    return win
