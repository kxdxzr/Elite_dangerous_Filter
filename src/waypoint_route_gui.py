"""Condition groups captured from the main editor; all network work is threaded."""
from copy import deepcopy
from dataclasses import asdict
import json
import queue
import threading
import tkinter as tk

from localized_tk import ttk, messagebox, Toplevel
from result_copy import copy_result
import waypoint_route as tool


WARNING = '优先最少额外停靠，其次最短直线路程；仅在已查询候选中优化，不是逐跳导航，不检查燃料或许可。站点按实际站点计数，同星系不同站分别计数。'


def open_window(app):
    from filter_gui import attach_system_suggest

    win = Toplevel(app.root)
    win.title('多目标途经规划')
    win.geometry('1180x780')
    win.minsize(900, 600)
    variables = {key: tk.StringVar(win, value=value) for key, value in dict(
        origin='Sol', destination='', max_extra_ly='100', candidates_per_group='12',
        max_pages='5', groups='[]').items()}
    app.bind_tool_state('waypoint_route', win, variables)
    try:
        groups = json.loads(variables['groups'].get())
        if not isinstance(groups, list) or len(groups) > 6:
            raise ValueError()
        if groups:
            groups = tool.validate_groups(groups)
    except (ValueError, TypeError, KeyError, AttributeError):
        groups = []
    variables['groups'].set(json.dumps(groups, ensure_ascii=False))
    form = ttk.Frame(win, padding=8)
    form.pack(fill='x')
    for index, (key, title) in enumerate((('origin', '起点星系'), ('destination', '终点星系'),
            ('max_extra_ly', '最大额外路程 ly'), ('candidates_per_group', '每组候选数'),
            ('max_pages', '每组最多页数'))):
        row, column = index // 3, index % 3 * 2
        ttk.Label(form, text=title).grid(row=row, column=column, sticky='w', padx=4, pady=4)
        if key in ('origin', 'destination'):
            box = ttk.Combobox(form, textvariable=variables[key], width=24)
            attach_system_suggest(box, variables[key])
        else:
            box = ttk.Entry(form, textvariable=variables[key], width=12)
        box.grid(row=row, column=column + 1, sticky='ew', padx=4)
        form.columnconfigure(column + 1, weight=1)
    warning = ttk.Label(win, text=WARNING, wraplength=1100)
    warning.pack(fill='x', padx=12, pady=4)
    warning.bind('<Configure>', lambda e: warning.configure(wraplength=max(300, e.width)))
    ttk.Label(win, text='在主界面编辑条件，再添加为独立要求组。组内全部满足；最多六组。修改主界面不会改变已添加的组。',
              wraplength=1100).pack(fill='x', padx=12, pady=4)
    group_tree = ttk.Treeview(win, columns=('number', 'kind', 'conditions'), show='headings', height=6)
    for key, label, width in (('number', '要求组', 80), ('kind', '目标类型', 100), ('conditions', '条件', 850)):
        group_tree.heading(key, text=label)
        group_tree.column(key, width=width)
    group_tree.pack(fill='x', padx=12)
    state = dict(busy=False, result=None)
    events, stop = queue.Queue(), threading.Event()
    poll_id = None
    status = tk.StringVar(win, value='就绪')

    def tr(text):
        return app.localizer.tr(text)

    def persist():
        variables['groups'].set(json.dumps(groups, ensure_ascii=False))

    def render_groups():
        group_tree.delete(*group_tree.get_children())
        for index, group in enumerate(groups):
            group_tree.insert('', 'end', iid=str(index), values=(index + 1,
                tr('空间站' if group['kind'] == 'stations' else '星系'),
                json.dumps(group['conditions'], ensure_ascii=False)))

    def capture():
        if state['busy']:
            return
        try:
            if len(groups) >= 6:
                raise ValueError(tr('请添加 1~6 个要求组'))
            conditions = [row.to_cond() for row in app.rows if row.frame.winfo_exists()]
            draft = dict(kind=app.kind.get(), conditions=conditions, name=str(len(groups) + 1))
            tool.validate_groups([draft])
            groups.append(deepcopy(draft))
            state['result'] = None
            tree.delete(*tree.get_children())
            status.set(tr('就绪'))
            persist()
            render_groups()
        except (ValueError, TypeError, KeyError) as exc:
            messagebox.showerror('参数错误', str(exc), parent=win)

    def remove():
        if state['busy']:
            return
        for index in sorted((int(i) for i in group_tree.selection()), reverse=True):
            del groups[index]
        state['result'] = None
        tree.delete(*tree.get_children())
        status.set(tr('就绪'))
        persist()
        render_groups()

    group_actions = ttk.Frame(win, padding=8)
    group_actions.pack(fill='x')
    ttk.Button(group_actions, text='从主界面添加要求组', command=capture).pack(side='left', padx=4)
    ttk.Button(group_actions, text='删除选中要求组', command=remove).pack(side='left', padx=4)
    ttk.Label(win, textvariable=status, wraplength=1100).pack(fill='x', padx=12)
    bar = ttk.Progressbar(win, mode='indeterminate')
    bar.pack(fill='x', padx=12, pady=4)
    frame = ttk.Frame(win)
    frame.pack(fill='both', expand=True, padx=12, pady=8)
    columns = ('step', 'system', 'station', 'requirements', 'leg', 'updated')
    tree = ttk.Treeview(frame, columns=columns, show='headings')
    for key, label, width in zip(columns,
            ('顺序', '星系', '站点／途经', '完成要求组', '本段距离 ly', '记录更新时间'),
            (60, 220, 260, 140, 140, 200)):
        tree.heading(key, text=label)
        tree.column(key, width=width, stretch=False)
    tree.grid(row=0, column=0, sticky='nsew')
    ybar = ttk.Scrollbar(frame, orient='vertical', command=tree.yview)
    ybar.grid(row=0, column=1, sticky='ns')
    xbar = ttk.Scrollbar(frame, orient='horizontal', command=tree.xview)
    xbar.grid(row=1, column=0, sticky='ew')
    tree.configure(yscrollcommand=ybar.set, xscrollcommand=xbar.set)
    frame.rowconfigure(0, weight=1)
    frame.columnconfigure(0, weight=1)

    def render_result():
        render_groups()
        tree.delete(*tree.get_children())
        result = state['result']
        if result is None:
            return
        counts = ' / '.join(str(len(pool)) for pool in result['pools'])
        text = tr('仅对本次候选集优化；候选截断可能遗漏更好的路线。') + '\n'
        text += tr('每组候选数') + ': ' + counts + ' · ' + result['fetched_at']
        if result['route'] is None:
            text += '\n' + tr('本次候选中没有满足绕路上限的完整路线；不代表游戏中不存在。')
            if result['missing']:
                text += '\n' + tr('缺少候选的要求组') + ': ' + ', '.join(str(i + 1) for i in result['missing'])
        else:
            text += f"\n{tr('额外停靠')}: {result['stops']} · {tr('总路程 ly')}: {result['total_ly']:.2f} · {tr('额外路程 ly')}: {result['extra_ly']:.2f}"
            tree.insert('', 'end', iid='origin', values=(0, result['origin'], tr('起点'), '', '0', ''))
            for index, item in enumerate(result['route']):
                tree.insert('', 'end', iid=str(index), values=(index + 1, item['system'],
                    item['name'] if item['kind'] == 'stations' else tr('途经星系'),
                    ', '.join(str(i + 1) for i in item['requirements']), f"{item['leg_ly']:.2f}",
                    item['row'].get('updated_at', tr('情况未知'))))
            tree.insert('', 'end', iid='destination', values=(len(result['route']) + 1,
                result['destination'], tr('终点'), '', f"{result['final_leg_ly']:.2f}", ''))
            if result['endpoint_requirements']:
                text += '\n' + tr('起终点已满足的星系要求组') + ': ' + ', '.join(str(i + 1) for i in result['endpoint_requirements'])
        status.set(text + '\n' + '\n'.join(result['notes']))

    def run():
        if state['busy']:
            return
        try:
            criteria = tool.Criteria(origin=variables['origin'].get(), destination=variables['destination'].get(),
                max_extra_ly=float(variables['max_extra_ly'].get()),
                candidates_per_group=int(variables['candidates_per_group'].get()),
                max_pages=int(variables['max_pages'].get())).validate()
            selected = tool.validate_groups(groups)
        except (ValueError, TypeError, KeyError) as exc:
            messagebox.showerror('参数错误', str(exc), parent=win)
            return
        state['busy'], state['result'] = True, None
        tree.delete(*tree.get_children())
        search_button.configure(state='disabled')
        stop_button.configure(state='normal')
        stop.clear()
        bar.start()
        status.set(tr('正在查找途经候选…'))

        def work():
            try:
                result = tool.search(criteria, selected, stop=stop,
                    progress=lambda text, detail=None: events.put(('progress', text)))
                events.put(('result', result))
            except Exception as exc:
                events.put(('error', str(exc)))
        threading.Thread(target=work, daemon=True).start()

    def system_name(item):
        result = state['result']
        if item in ('origin', 'destination'):
            return result[item]
        return result['route'][int(item)]['system']

    def evidence():
        result = state['result']
        if result is None:
            return
        popup = Toplevel(win)
        popup.title('匹配依据')
        text = tk.Text(popup, width=100, height=32, wrap='word')
        text.pack(fill='both', expand=True)
        selected = tree.selection()
        item = result['route'][int(selected[0])] if selected and selected[0].isdigit() else None
        text.insert('1.0', json.dumps(dict(groups=result['groups'], waypoint=item,
            criteria=asdict(result['criteria']),
            endpoint_evidence=[dict(requirement=i + 1, candidates=[p['row'] for p in result['pools'][i]
                if p['kind'] == 'systems' and p['system'].casefold() in
                (result['origin'].casefold(), result['destination'].casefold())])
                for i in result.get('endpoint_requirements', [])],
            queried_at=result['fetched_at'], notes=result['notes']), ensure_ascii=False, indent=2))
        text.configure(state='disabled')

    actions = ttk.Frame(win, padding=8)
    actions.pack(fill='x')
    search_button = ttk.Button(actions, text='规划路线', command=run)
    search_button.pack(side='left', padx=4)
    stop_button = ttk.Button(actions, text='停止', command=stop.set, state='disabled')
    stop_button.pack(side='left', padx=4)
    ttk.Button(actions, text='复制星系名', command=lambda: copy_result(win, tree, getter=system_name)).pack(side='left', padx=4)
    ttk.Button(actions, text='匹配依据', command=evidence).pack(side='left', padx=4)

    def poll():
        nonlocal poll_id
        try:
            while True:
                event, data = events.get_nowait()
                if event == 'progress':
                    status.set(tr(data))
                    continue
                state['busy'] = False
                search_button.configure(state='normal')
                stop_button.configure(state='disabled')
                bar.stop()
                if event == 'result':
                    state['result'] = data
                    render_result()
                else:
                    status.set(data)
                    if not stop.is_set():
                        messagebox.showerror('查询失败', data, parent=win)
        except queue.Empty:
            pass
        poll_id = win.after(100, poll)

    def destroyed(event):
        if event.widget is win:
            stop.set()
            if poll_id is not None:
                win.after_cancel(poll_id)
            app.localizer.callbacks.discard(render_result)

    win.bind('<Destroy>', destroyed, add='+')
    app.localizer.register(render_result)
    win.route_controls = dict(variables=variables, groups=groups, group_tree=group_tree,
        tree=tree, state=state, capture=capture, remove=remove, run=run, stop=stop)
    render_groups()
    poll()
    return win
