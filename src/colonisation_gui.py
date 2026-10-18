"""Editable existential body/ring groups; worker threads never call Tk."""
import csv
from export_metadata import write_csv_provenance
import json
import queue
import re
import threading
import tkinter as tk
from tkinter import filedialog

from localized_tk import ttk, messagebox, Toplevel
import colonisation_tool as tool


class GroupEditor:
    def __init__(self, parent, fields, mode, saved, changed):
        self.fields, self.groups, self.changed = fields, [], changed
        header = ttk.Frame(parent)
        header.pack(fill='x')
        ttk.Label(header, text='条件组之间').pack(side='left', padx=4)
        ttk.Combobox(header, textvariable=mode, values=['AND', 'OR'], state='readonly', width=8).pack(side='left')
        ttk.Label(header, text='AND：全部存在；OR：任一存在。组内条件由同一天体／星环同时满足。').pack(side='left', padx=8)
        ttk.Button(header, text='添加条件组', command=self.add_group).pack(side='right', padx=4)
        area = ttk.Frame(parent)
        area.pack(fill='both', expand=True)
        self.canvas = tk.Canvas(area, height=220, highlightthickness=0)
        scrollbar = ttk.Scrollbar(area, orient='vertical', command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=scrollbar.set)
        self.canvas.pack(side='left', fill='both', expand=True)
        scrollbar.pack(side='right', fill='y')
        self.frame = ttk.Frame(self.canvas)
        item = self.canvas.create_window((0, 0), window=self.frame, anchor='nw')
        self.frame.bind('<Configure>', lambda e: self.canvas.configure(scrollregion=self.canvas.bbox('all')))
        self.canvas.bind('<Configure>', lambda e: self.canvas.itemconfigure(item, width=e.width))
        for group in saved:
            if isinstance(group, list):
                self.add_group(group)

    def snapshot(self):
        return [[{'field': next((k for k, label in self.fields.items() if label == row['field'].get()), row['field'].get()),
                  'op': row['op'].get(), 'value': row['value'].get()} for row in group['rows']]
                for group in self.groups]

    def dispose(self):
        for group in self.groups:
            for row in group['rows']:
                for var, trace in row.get('traces', []):
                    var.trace_remove('write', trace)
                row['traces'] = []
        self.groups.clear()

    def add_group(self, saved=None):
        frame = ttk.LabelFrame(self.frame, text='条件组', padding=5)
        frame.pack(fill='x', padx=4, pady=4)
        group = {'frame': frame, 'rows': []}
        self.groups.append(group)
        buttons = ttk.Frame(frame)
        buttons.pack(fill='x')
        ttk.Button(buttons, text='添加条件', command=lambda: self.add_row(group)).pack(side='left')
        ttk.Button(buttons, text='删除组', command=lambda: self.delete_group(group)).pack(side='right')
        for condition in saved or [{}]:
            if isinstance(condition, dict):
                self.add_row(group, condition)
        self.changed()

    def delete_group(self, group):
        self.groups.remove(group)
        for row in group['rows']:
            for var, trace in row.get('traces', []):
                var.trace_remove('write', trace)
            row['traces'] = []
        group['rows'].clear()
        group['frame'].destroy()
        self.changed()

    def add_row(self, group, saved=None):
        saved = saved or {}
        frame = ttk.Frame(group['frame'])
        frame.pack(fill='x', pady=2)
        default = next(iter(self.fields))
        row = {'frame': frame,
               'field': tk.StringVar(frame, value=self.fields.get(saved.get('field', default), saved.get('field', default))),
               'op': tk.StringVar(frame, value=saved.get('op', '=')),
               'value': tk.StringVar(frame, value=saved.get('value', ''))}
        group['rows'].append(row)
        field_box = ttk.Combobox(frame, textvariable=row['field'], values=list(self.fields.values()), state='readonly', width=30)
        field_box.pack(side='left', padx=3)
        ttk.Combobox(frame, textvariable=row['op'], values=tool.OPERATORS, state='readonly', width=10).pack(side='left', padx=3)
        value_box = ttk.Combobox(frame, textvariable=row['value'], width=50)
        value_box.pack(side='left', fill='x', expand=True, padx=3)

        def update_choices(*args):
            key = next((k for k, label in self.fields.items() if label == row['field'].get()), '')
            value_box.configure(values=tool.VALUES.get(key, []))
            self.changed()

        row['traces'] = [(row['field'], row['field'].trace_add('write', update_choices))]
        for key in ('op', 'value'):
            row['traces'].append((row[key], row[key].trace_add('write', lambda *args: self.changed())))
        update_choices()

        def delete():
            group['rows'].remove(row)
            for var, trace in row['traces']:
                var.trace_remove('write', trace)
            row['traces'] = []
            frame.destroy()
            self.changed()

        ttk.Button(frame, text='删除条件', command=delete).pack(side='right', padx=3)
        self.changed()


def open_window(app):
    win = Toplevel(app.root)
    win.title('殖民候选星系查找器')
    win.geometry('1400x900')
    variables = {key: tk.StringVar(win, value=value) for key, value in {
        'reference': '', 'radius': '', 'populated_min_distance': '', 'populated_radius': '', 'minimum_value': '',
        'value_field': 'estimated_mapping_value', 'body_mode': 'AND', 'ring_mode': 'AND',
        'body_groups': '[]', 'ring_groups': '[]', 'want': '100'}.items()}
    app.bind_tool_state('colonisation', win, variables)
    controls = ttk.Frame(win, padding=8)
    controls.pack(fill='x')
    sections = [
        ('区域距离（可选）', [('reference', '区域参考星系（可选）'), ('radius', '区域半径 ly（留空不限）')]),
        ('最近有人星系距离（可选）', [('populated_min_distance', '最近有人星系最小 ly'),
                                      ('populated_radius', '最近有人星系最大 ly')]),
        ('价值与查询数量', [('minimum_value', '星系价值大于（可选）'), ('value_field', '星系价值字段'),
                         ('want', '最多结果')]),
    ]
    for section_index, (title, specs) in enumerate(sections):
        section = ttk.LabelFrame(controls, text=title, padding=5)
        section.grid(row=0 if section_index < 2 else 1, column=section_index if section_index < 2 else 0,
                     columnspan=1 if section_index < 2 else 2, sticky='ew', padx=3, pady=3)
        for index, (key, text) in enumerate(specs):
            ttk.Label(section, text=text).grid(row=0, column=index, sticky='w', padx=3)
            if key == 'value_field':
                entry = ttk.Combobox(section, textvariable=variables[key], state='readonly',
                                     values=['estimated_mapping_value', 'estimated_scan_value', 'landmark_value'], width=25)
            elif key == 'reference':
                from filter_gui import attach_system_suggest
                entry = ttk.Combobox(section, textvariable=variables[key], width=21)
                attach_system_suggest(entry, variables[key])
            else:
                entry = ttk.Entry(section, textvariable=variables[key], width=16)
            entry.grid(row=1, column=index, sticky='ew', padx=3, pady=4)
            section.columnconfigure(index, weight=1)
    controls.columnconfigure(0, weight=1)
    controls.columnconfigure(1, weight=1)
    ttk.Label(win, text='两套距离独立且同时启用时为 AND；最近距离先找最近人口达标星系，再判断上下限，包含边界。',
              wraplength=1360, style='Muted.TLabel').pack(fill='x', padx=8)
    ttk.Label(win, text='强制：零人口、无任何站点（含航母）、明确无需许可。可选数值留空不限，0 是实际阈值。',
              wraplength=1360).pack(fill='x', padx=8)
    ttk.Label(win, text='in 多选及 between 范围用 | 分隔；布尔值用 true / false。互绕按共同直接质心和相同周期推定，复杂／缺失关系为未知。',
              wraplength=1360, style='Muted.TLabel').pack(fill='x', padx=8)
    tabs = ttk.Notebook(win)
    tabs.pack(fill='x', padx=8, pady=5)
    body_tab, ring_tab = ttk.Frame(tabs), ttk.Frame(tabs)
    tabs.add(body_tab, text='星球条件')
    tabs.add(ring_tab, text='独立星环条件')
    # ttk.Notebook does not use TextMixin; translate its titles explicitly.
    def localize_tabs():
        tabs.tab(body_tab, text=app.localizer.tr('星球条件'))
        tabs.tab(ring_tab, text=app.localizer.tr('独立星环条件'))
    app.localizer.register(localize_tabs)
    editors = {}

    def changed():
        for key, editor in editors.items():
            variables[key].set(json.dumps(editor.snapshot(), ensure_ascii=False))

    for key, parent, fields, mode in (
            ('body_groups', body_tab, tool.BODY_FIELDS, 'body_mode'),
            ('ring_groups', ring_tab, tool.RING_FIELDS, 'ring_mode')):
        try:
            saved = json.loads(variables[key].get())
            saved = saved if isinstance(saved, list) else []
        except ValueError:
            saved = []
        editors[key] = GroupEditor(parent, fields, variables[mode], saved, changed)
    changed()
    actions = ttk.Frame(win, padding=8)
    actions.pack(fill='x')
    status = tk.StringVar(win, value='可选条件留空不限；查询只覆盖第三方已记录数据。')
    ttk.Label(win, textvariable=status, wraplength=1360).pack(fill='x', padx=8)
    bar = ttk.Progressbar(win, mode='indeterminate')
    bar.pack(fill='x', padx=8, pady=4)
    from search_progress import SearchProgress
    progress_text = tk.StringVar(win)
    ttk.Label(win, textvariable=progress_text).pack(fill='x', padx=8)
    tracker = SearchProgress(bar, progress_text, app.localizer)
    frame = ttk.Frame(win)
    frame.pack(fill='both', expand=True, padx=8)
    columns = [('name', '候选星系'), ('scan1', '扫描价值第1（星球／类型／Cr）'),
                ('scan2', '扫描价值第2（星球／类型／Cr）'),
                ('scan3', '扫描价值第3（星球／类型／Cr）'),
                ('neighbour', '最近有人星系'), ('near_distance', '最近有人星系距离 ly'),
                ('neighbour_pad', '最近有人星系最大停机坪'),
                ('distance', '区域距离 ly'), ('value', '星系价值'),
                ('body_matches', '匹配星球（按组）'), ('ring_matches', '匹配星环（按组）'),
                ('relations', '天体关系（推定）'),
                ('scan_status', '扫描价值数据完整性'), ('updated', '记录更新时间')]
    tree = ttk.Treeview(frame, columns=[key for key, _ in columns], show='headings')
    for key, title in columns:
        tree.heading(key, text=title)
        tree.column(key, width=300 if key in ('body_matches', 'ring_matches', 'relations', 'scan1', 'scan2', 'scan3') else 165, stretch=False)
    vertical = ttk.Scrollbar(frame, orient='vertical', command=tree.yview)
    horizontal = ttk.Scrollbar(frame, orient='horizontal', command=tree.xview)
    tree.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
    tree.grid(row=0, column=0, sticky='nsew')
    vertical.grid(row=0, column=1, sticky='ns')
    horizontal.grid(row=1, column=0, sticky='ew')
    frame.rowconfigure(0, weight=1)
    frame.columnconfigure(0, weight=1)
    events, stop = queue.Queue(), threading.Event()
    state = {'rows': [], 'info': None, 'busy': False, 'progress': ''}

    def render_status():
        en = app.localizer.language == 'en'
        info = state['info']
        if info:
            reasons = {
                'All supplied candidate pages fetched.': '已取完数据源候选分页。',
                'Page limit reached; results are incomplete.': '达到翻页上限，结果不完整。',
                'Result limit reached; results are incomplete.': '达到结果数量上限，结果不完整。',
                'Repeated system page; results are incomplete.': '服务器返回重复分页，结果不完整。',
                'Search cancelled; results are incomplete.': '已停止，结果不完整。',
            }
            if en:
                text = f"Scanned: {info['scanned']:,}; matches: {len(state['rows']):,}; unknown: {info['unknown']:,}. {info['reason']}"
            else:
                text = f"扫描 {info['scanned']:,}；匹配 {len(state['rows']):,}；数据未知 {info['unknown']:,}。" + reasons.get(info['reason'], info['reason'])
            status.set(text)
        elif state['busy']:
            text = state['progress']
            page = re.fullmatch(r'Page (\d+); scanned (\d+); matches (\d+)', text)
            batch = re.fullmatch(r'Body batches (\d+)/(\d+); matches (\d+)', text)
            if page:
                a, scanned, hits = map(int, page.groups())
                text = (f'Page {a:,}; scanned {scanned:,}; matches {hits:,}' if en else
                        f'分页 {a:,}；已扫描 {scanned:,}；匹配 {hits:,}')
            elif not en and batch:
                a, b, hits = batch.groups()
                text = f'天体批次 {a}/{b}；匹配 {hits}'
            status.set(text or ('Searching...' if en else '查询中...'))
    app.localizer.register(render_status)

    def criteria():
        changed()
        args = {key: value.get() for key, value in variables.items()}
        for key in ('body_groups', 'ring_groups'):
            args[key] = json.loads(args[key])
        for key in ('want',):
            args[key] = int(args[key])
        return tool.Criteria(**args).validate()

    def values(row):
        from result_format import format_ly, format_number
        prices = row.get('_top_scan_planets', [])
        top = [f"{b['name']} | {b['subtype']} | {b['estimated_scan_value']:,.0f} Cr" for b in prices]
        complete = row.get('_top_scan_complete', False)
        top += [app.localizer.tr('无更多星球' if complete else '情况未知')] * (3 - len(top))
        return (row['name'], *top,
                row['_neighbour'], format_ly(row['_neighbour_distance']),
                app.localizer.tr(row.get('_neighbour_pad', '情况未知') if row['_neighbour'] else ''),
                format_ly(row.get('distance')),
                format_number(row.get(state['info']['value_field']), app.localizer.tr('情况未知')),
                row['_body_matches'], row['_ring_matches'], row['_relations'],
                app.localizer.tr('已记录天体完整' if complete else '数据不完整，仅列已知估值'),
                row.get('updated_at', ''))

    def run(refresh=False):
        if state['busy']:
            return
        try:
            c = criteria()
        except (ValueError, TypeError, KeyError) as exc:
            messagebox.showwarning('条件有误', str(exc), parent=win)
            return
        stop.clear()
        state['busy'] = True
        state['progress'] = ''
        state['info'], state['rows'] = None, []
        tree.delete(*tree.get_children())
        search_button.configure(state='disabled')
        refresh_button.configure(state='disabled')
        stop_button.configure(state='normal')
        render_status()
        tracker.update()

        def worker():
            try:
                info, rows = tool.search(c, progress=lambda text, detail=None: events.put(('progress', (text, detail))), stop=stop, refresh=refresh)
                events.put(('done', (info, rows)))
            except Exception as exc:
                events.put(('error', str(exc)))
        threading.Thread(target=worker, daemon=True).start()

    def copy(key='name'):
        from result_copy import copy_result
        return copy_result(win, tree, getter=lambda item: state['rows'][int(item)].get(key, ''))

    def export():
        if not state['info']:
            return
        path = filedialog.asksaveasfilename(parent=win, defaultextension='.csv', filetypes=[('CSV', '*.csv')])
        if path:
            try:
                with open(path, 'w', newline='', encoding='utf-8-sig') as file:
                    writer = csv.writer(file)
                    write_csv_provenance(writer, len(columns), app.localizer.language)
                    writer.writerow([state['info']['value_field'] if key == 'value' else key for key, _ in columns])
                    writer.writerows(values(row) for row in state['rows'])
            except OSError as exc:
                messagebox.showerror('导出失败', str(exc), parent=win)

    search_button = ttk.Button(actions, text='查询', command=run)
    search_button.pack(side='left', padx=4)
    refresh_button = ttk.Button(actions, text='刷新数据并查询', command=lambda: run(True))
    refresh_button.pack(side='left', padx=4)
    stop_button = ttk.Button(actions, text='停止', command=stop.set, state='disabled')
    stop_button.pack(side='left', padx=4)
    ttk.Button(actions, text='复制星系名', command=copy).pack(side='left', padx=4)
    ttk.Button(actions, text='复制最近有人星系', command=lambda: copy('_neighbour')).pack(side='left', padx=4)
    ttk.Button(actions, text='导出CSV', command=export).pack(side='left', padx=4)
    tree.bind('<Double-1>', lambda e: copy())

    poll_id = None

    def poll():
        nonlocal poll_id
        if not win.winfo_exists():
            return
        try:
            while True:
                event, data = events.get_nowait()
                if event == 'progress':
                    text, detail = data
                    state['progress'] = text
                    tracker.update(text, detail)
                    render_status()
                    continue
                state['busy'] = False
                search_button.configure(state='normal')
                refresh_button.configure(state='normal')
                stop_button.configure(state='disabled')
                bar.stop()
                if event == 'error':
                    tracker.finish(False)
                    status.set(data)
                    messagebox.showerror('查询失败', data, parent=win)
                    continue
                info, rows = data
                state.update(info=info, rows=rows)
                tracker.finish(info['complete'])
                render_status()
                for index, row in enumerate(rows):
                    tree.insert('', 'end', iid=str(index), values=values(row))
        except queue.Empty:
            pass
        poll_id = win.after(100, poll)

    def destroyed(event):
        if event.widget is win:
            stop.set()
            for editor in editors.values():
                editor.dispose()
            editors.clear()
            if poll_id is not None:
                win.after_cancel(poll_id)
            app.localizer.callbacks.discard(localize_tabs)
            app.localizer.callbacks.discard(render_status)
    win.bind('<Destroy>', destroyed, add='+')
    win.group_editors, win.result_tree, win.search_state = editors, tree, state
    win.criteria = criteria
    localize_tabs()
    poll()
    return win
