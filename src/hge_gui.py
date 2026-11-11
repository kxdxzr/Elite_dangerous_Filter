"""Read-only, uncached HGE candidate finder; no CSV or live signal claims."""
import queue
import threading
import tkinter as tk

import hge_tool as tool
from localized_tk import ttk, messagebox, Toplevel
from result_copy import copy_result
from result_format import format_ly, format_population


WARNING = '仅按控制派系的阵营和当前状态推测；不是 HGE 信号点阵营，也不保证信号或掉落。时效依据星系记录更新时间，不是派系状态的独立时间。'


def open_window(app):
    from filter_gui import attach_system_suggest

    win = Toplevel(app.root)
    win.title('HGE 可能星系查找器')
    win.geometry('1280x720')
    win.minsize(1000, 580)
    variables = {key: tk.StringVar(win, value=value) for key, value in dict(
        reference='Sol', radius='50', material='federal', population='人口大于 0',
        freshness='近 24 小时', want='100', max_pages='25').items()}
    variables['require_manufactured_trader'] = tk.BooleanVar(win, value=False)
    form = ttk.Frame(win, padding=8)
    form.pack(fill='x')
    ttk.Label(form, text='HGE 材料').grid(row=0, column=0, sticky='w', padx=4)
    material = ttk.Combobox(form, textvariable=variables['material'], values=list(tool.MATERIAL_LABELS),
                            value_labels=tool.MATERIAL_LABELS, width=72, state='readonly')
    material.grid(row=0, column=1, columnspan=5, sticky='ew', padx=4, pady=4)
    boxes = {'material': material}
    for index, (key, title) in enumerate((('reference', '参考星系'), ('radius', '搜索半径 ly'),
                                         ('want', '最多结果'), ('population', '人口下限'),
                                         ('freshness', '星系记录时效'), ('max_pages', '最多页数'))):
        row, column = 1 + index // 3, (index % 3) * 2
        from journal_gui import system_label
        heading = system_label(form, title, variables[key]) if key == 'reference' else ttk.Label(form, text=title)
        heading.grid(row=row, column=column, sticky='w', padx=4, pady=4)
        if key in ('population', 'freshness'):
            values = tool.POPULATION_OPTIONS if key == 'population' else tool.FRESHNESS_OPTIONS
            box = ttk.Combobox(form, textvariable=variables[key], values=list(values), state='readonly', width=20)
        elif key == 'reference':
            box = ttk.Combobox(form, textvariable=variables[key], width=24)
            attach_system_suggest(box, variables[key])
        else:
            box = ttk.Entry(form, textvariable=variables[key], width=12)
        box.grid(row=row, column=column + 1, sticky='ew', padx=4, pady=4)
        boxes[key] = box
        form.columnconfigure(column + 1, weight=1)
    trader_box = ttk.Checkbutton(form, text='目标星系存在人造材料商人',
                                 variable=variables['require_manufactured_trader'])
    trader_box.grid(row=3, column=0, columnspan=6, sticky='w', padx=4, pady=4)
    boxes['require_manufactured_trader'] = trader_box
    app.bind_tool_state('hge', win, variables)
    # Readonly controls must not retain invalid selections from hand-edited sessions.
    for key, choices, default in (('material', tool.MATERIAL_LABELS, 'federal'),
                                  ('population', tool.POPULATION_OPTIONS, '人口大于 0'),
                                  ('freshness', tool.FRESHNESS_OPTIONS, '近 24 小时')):
        if variables[key].get() not in choices:
            variables[key].set(default)
    warning = ttk.Label(win, text=WARNING, wraplength=1200, justify='left')
    warning.pack(fill='x', padx=12, pady=4)
    warning.bind('<Configure>', lambda e: warning.configure(wraplength=max(300, e.width)))
    rule_text = tk.StringVar(win)
    ttk.Label(win, textvariable=rule_text, wraplength=1200).pack(fill='x', padx=12, pady=4)
    actions = ttk.Frame(win, padding=8)
    actions.pack(fill='x')
    status = tk.StringVar(win, value='就绪')
    status_label = ttk.Label(win, textvariable=status, wraplength=1200)
    status_label.pack(fill='x', padx=12)
    bar = ttk.Progressbar(win, mode='indeterminate')
    bar.pack(fill='x', padx=12, pady=4)
    frame = ttk.Frame(win)
    frame.pack(fill='both', expand=True, padx=8, pady=8)
    columns = ('name', 'distance', 'materials', 'controller', 'allegiance', 'states', 'population',
               'updated_at', 'age', 'permit', 'trader')
    tree = ttk.Treeview(frame, columns=columns, show='headings')
    for key, label, width in zip(columns,
            ('星系', '距离 ly', '可能材料', '控制派系', '控制派系阵营', '匹配当前状态', '人口',
             '星系记录更新时间 UTC', '查询时记录年龄（小时）', '需要许可', '人造材料商人站点'),
            (180, 110, 360, 220, 140, 150, 140, 190, 150, 100, 220)):
        tree.heading(key, text=label)
        tree.column(key, width=width, minwidth=60, stretch=False)
    tree.configure(displaycolumns=columns[:-1])
    tree.grid(row=0, column=0, sticky='nsew')
    ybar = ttk.Scrollbar(frame, orient='vertical', command=tree.yview)
    ybar.grid(row=0, column=1, sticky='ns')
    xbar = ttk.Scrollbar(frame, orient='horizontal', command=tree.xview)
    xbar.grid(row=1, column=0, sticky='ew')
    tree.configure(yscrollcommand=ybar.set, xscrollcommand=xbar.set)
    frame.columnconfigure(0, weight=1)
    frame.rowconfigure(0, weight=1)
    events, stop = queue.Queue(), threading.Event()
    state = dict(busy=False, result=None)
    poll_id = None

    def criteria():
        return tool.Criteria(reference=variables['reference'].get(), radius=float(variables['radius'].get()),
                             material=variables['material'].get(), population=variables['population'].get(),
                             freshness=variables['freshness'].get(), want=int(variables['want'].get()),
                             max_pages=int(variables['max_pages'].get()),
                             require_manufactured_trader=variables['require_manufactured_trader'].get()).validate()

    def render():
        key = variables['material'].get()
        if key == 'all':
            rule_text.set(app.localizer.tr('按所列材料规则逐项匹配；待处理或恢复中的状态不计入。'))
        elif key in tool.RULES:
            _, allegiances, states = tool.RULES[key]
            rule_text.set(app.localizer.tr('匹配规则：') + ' / '.join(allegiances) + ' · ' + ' / '.join(states))
        result = state['result']
        tree.delete(*tree.get_children())
        if not result:
            return
        tree.configure(displaycolumns=columns if result['criteria'].require_manufactured_trader else columns[:-1])
        for index, row in enumerate(result['rows']):
            evidence = row['_hge']
            distances = row.get('_distances', {})
            distance = next(iter(distances.values()), row.get('distance'))
            permit = row.get('needs_permit')
            stamp = tool.timestamp(evidence['updated_at'])
            tree.insert('', 'end', iid=str(index), values=(
                row['name'], format_ly(distance), ' / '.join(evidence['materials']), evidence['controller'],
                evidence['allegiance'], ' / '.join(evidence['states']), format_population(row.get('population')),
                stamp.isoformat(timespec='seconds') if stamp else '情况未知',
                f"{evidence['age_hours']:.2f}" if evidence['age_hours'] is not None else '情况未知',
                '是' if permit is True else '否' if permit is False else '情况未知',
                evidence.get('manufactured_trader', {}).get('name', '')))
        summary = f"{app.localizer.tr('已核实候选')}: {len(result['rows'])} · {app.localizer.tr('已扫描')}: {result['scanned']}"
        summary += '\n' + app.localizer.tr('本次查询时间：') + result['fetched_at']
        summary += '\n' + ' / '.join(app.localizer.tr(n) for n in result['notes'])
        status.set(summary)

    def run():
        if state['busy']:
            return
        try:
            selected = criteria()
        except (ValueError, TypeError, OverflowError) as exc:
            messagebox.showerror('参数错误', str(exc), parent=win)
            return
        stop.clear()
        state['busy'] = True
        search_button.configure(state='disabled')
        stop_button.configure(state='normal')
        status.set('正在重新查询 HGE 候选…')
        bar.start()

        def work():
            try:
                result = tool.search(selected, stop=stop,
                                     progress=lambda text, detail=None: events.put(('progress', text)))
                events.put(('result', result))
            except Exception as exc:
                events.put(('error', str(exc)))
        threading.Thread(target=work, daemon=True).start()

    def copy_system():
        return copy_result(win, tree, getter=lambda item: state['result']['rows'][int(item)]['name'])

    search_button = ttk.Button(actions, text='查询', command=run)
    search_button.pack(side='left', padx=4)
    stop_button = ttk.Button(actions, text='停止', command=stop.set, state='disabled')
    stop_button.pack(side='left', padx=4)
    copy_button = ttk.Button(actions, text='复制星系名', command=copy_system)
    copy_button.pack(side='left', padx=4)
    tree.bind('<Double-1>', lambda event: copy_system())

    def poll():
        nonlocal poll_id
        try:
            while True:
                event, data = events.get_nowait()
                if event == 'progress':
                    status.set(app.localizer.tr(data))
                    continue
                state['busy'] = False
                search_button.configure(state='normal')
                stop_button.configure(state='disabled')
                bar.stop()
                if event == 'error':
                    status.set(data)
                    messagebox.showerror('查询失败', data, parent=win)
                else:
                    state['result'] = data
                    render()
        except queue.Empty:
            pass
        poll_id = win.after(100, poll)

    def destroyed(event):
        if event.widget is win:
            stop.set()
            if poll_id is not None:
                win.after_cancel(poll_id)
            variables['material'].trace_remove('write', material_trace)
            app.localizer.callbacks.discard(render)

    material_trace = variables['material'].trace_add('write', lambda *args: render())
    app.localizer.register(render)
    win.bind('<Destroy>', destroyed, add='+')
    win.criteria, win.run_search, win.copy_system = criteria, run, copy_system
    win.result_tree, win.search_state, win.control_widgets = tree, state, boxes
    win.search_button, win.copy_button = search_button, copy_button
    win.status_variable = status
    poll()
    return win
