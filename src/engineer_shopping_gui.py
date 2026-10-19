"""Dedicated engineer-trip shopping window; all Tk access stays on the UI thread."""
import csv
import json
import queue
import threading
import tkinter as tk
from tkinter import filedialog

import engineer_shopping as tool
from engineer_destinations import CHOICES, destination_choice
from export_metadata import write_csv_provenance
from localized_tk import ttk, messagebox, Toplevel
from powerplay_tool import POWERS, POWER_LABELS, normalize_power


def open_window(app):
    from filter_gui import Row, attach_system_suggest, field_label

    win = Toplevel(app.root)
    win.title('工程师途中采购')
    win.geometry('1320x820')
    from form_scroll import settings_form
    form = settings_form(win)
    variables = {key: tk.StringVar(win, value=value) for key, value in dict(
        origin='', destination='', jump_range='80', max_extra_jumps='1', arrival_ls='1500', want='100',
        max_pages='25', landing_pad='不限', pledged_power='无').items()}
    variables['assume_max_rank'] = tk.BooleanVar(win, value=True)
    variables['ignore_carriers'] = tk.BooleanVar(win, value=True)
    variables['ignore_planetary'] = tk.BooleanVar(win, value=False)
    variables['purchases'] = tk.StringVar(win, value='')
    route = ttk.LabelFrame(form, text='行程与航程', padding=8)
    route.pack(fill='x', padx=8, pady=6)
    for index, (key, title) in enumerate((('origin', '出发星系'), ('destination', '目标工程师／星系'),
                                         ('jump_range', '单跳航程 ly'), ('arrival_ls', '到站距离小于 ls'),
                                         ('max_extra_jumps', '最多额外跳数（估算）'),
                                         ('want', '最多结果'), ('max_pages', '最多页数'),
                                         ('landing_pad', '采购站停机坪（可停靠船型）'),
                                         ('pledged_power', '效忠 Power（个人优惠）'))):
        grid_row, grid_column = divmod(index, 4)
        ttk.Label(route, text=title).grid(row=grid_row * 2, column=grid_column, sticky='w', padx=4)
        if key == 'destination':
            entry = ttk.Combobox(route, textvariable=variables[key], values=CHOICES, state='readonly', width=36)
            win.destination_box = entry
        elif key == 'origin':
            entry = ttk.Combobox(route, textvariable=variables[key], width=24)
            attach_system_suggest(entry, variables[key])
        elif key == 'pledged_power':
            entry = ttk.Combobox(route, textvariable=variables[key],
                                 values=['无'] + [POWER_LABELS[p] for p in POWERS], state='readonly', width=26)
            win.pledged_power_box = entry
        elif key == 'landing_pad':
            entry = ttk.Combobox(route, textvariable=variables[key], values=['不限', 'S', 'M', 'L'],
                                 state='readonly', width=12)
            win.landing_pad_box = entry
        else:
            entry = ttk.Entry(route, textvariable=variables[key], width=12)
        entry.grid(row=grid_row * 2 + 1, column=grid_column, sticky='ew', padx=4, pady=4)
        route.columnconfigure(grid_column, weight=1)

    purchase = ttk.LabelFrame(form, text='采购模组／舰载武器', padding=5)
    purchase.pack(fill='x', padx=8, pady=4)
    purchase_actions = ttk.Frame(purchase)
    purchase_actions.pack(fill='x')
    area = ttk.Frame(purchase)
    area.pack(fill='x')
    canvas = tk.Canvas(area, height=165, highlightthickness=0)
    purchase_scroll = ttk.Scrollbar(area, orient='vertical', command=canvas.yview)
    canvas.configure(yscrollcommand=purchase_scroll.set)
    canvas.pack(side='left', fill='x', expand=True)
    purchase_scroll.pack(side='right', fill='y')
    purchase_frame = ttk.Frame(canvas)
    purchase_item = canvas.create_window((0, 0), window=purchase_frame, anchor='nw')
    purchase_frame.bind('<Configure>', lambda e: canvas.configure(scrollregion=canvas.bbox('all')))
    canvas.bind('<Configure>', lambda e: canvas.itemconfigure(purchase_item, width=e.width))
    purchase_rows = []

    def bind_first_row():
        # Keep legacy single-item session keys readable; purchases is authoritative.
        win.purchase_row = purchase_rows[0] if purchase_rows else None
        if purchase_rows:
            first = purchase_rows[0]
            variables.update(module=first.val, module_class=first.v_class, module_rating=first.v_rating,
                             slot=first.v_slot, freshness=first.v_fresh, discount=first.v_discount,
                             module_spec=first.v_spec)

    def remove_purchase(row):
        if row in purchase_rows:
            purchase_rows.remove(row)
            row.destroy()
            bind_first_row()

    def apply_purchase(row, saved):
        for variable, key in ((row.val, 'value'), (row.v_class, 'class'), (row.v_rating, 'rating'),
                              (row.v_slot, 'module_slot'), (row.v_fresh, 'fresh'), (row.v_discount, 'discount')):
            if isinstance(saved.get(key), str):
                variable.set(saved[key])
        if row.v_discount.get() not in ('不限', '是'):
            row.v_discount.set('不限')
        row.refresh_options()
        if isinstance(saved.get('module_spec'), str):
            row.v_spec.set(saved['module_spec'])

    def add_purchase(saved=None):
        row = Row(purchase_frame, 'stations')
        row.field.set(field_label('stations', 'modules'))
        row.v_discount.set('是')
        # Each entry has independent name/specification/freshness/discount controls.
        for widget in row.controls.winfo_children():
            if widget in (row.cb_category, row.cb_field, row.cb_op) or (
                    isinstance(widget, ttk.Label) and widget is not row.lbl_slot and widget is not row.lbl_opt) or (
                    isinstance(widget, ttk.Button) and widget is not row.btn_pick):
                widget.pack_forget()
        ttk.Button(row.controls, text='删除采购项', command=lambda: remove_purchase(row)).pack(side='right', padx=4)
        purchase_rows.append(row)
        if isinstance(saved, dict):
            apply_purchase(row, saved)
        else:
            row.refresh_options()
        bind_first_row()
        return row

    def snapshot_purchases():
        variables['purchases'].set(json.dumps([row.editor_state() for row in purchase_rows], ensure_ascii=False))

    first = add_purchase()
    app.bind_tool_state('engineer_shopping', win, variables, before_collect=snapshot_purchases)
    variables['destination'].set(destination_choice(variables['destination'].get()))
    if variables['landing_pad'].get() not in ('不限', 'S', 'M', 'L'):
        variables['landing_pad'].set('不限')
    if variables['pledged_power'].get() != '无':
        try:
            variables['pledged_power'].set(POWER_LABELS[normalize_power(variables['pledged_power'].get())])
        except ValueError:
            variables['pledged_power'].set('无')
    # Restore the full list, or migrate the old single-entry parameter set.
    try:
        saved_purchases = json.loads(variables['purchases'].get())
    except (ValueError, TypeError):
        saved_purchases = None
    if isinstance(saved_purchases, list) and all(isinstance(item, dict) for item in saved_purchases):
        if saved_purchases:
            apply_purchase(first, saved_purchases[0])
            for saved in saved_purchases[1:]:
                add_purchase(saved)
        else:
            remove_purchase(first)
    else:
        first.refresh_options()
    ttk.Button(purchase_actions, text='添加采购项', command=add_purchase).pack(side='left', padx=4, pady=3)
    ttk.Label(purchase_actions, text='同一站点须同时满足全部采购项；同一行多选名称也要求全部有货。').pack(side='left', padx=6)
    ttk.Label(form, text='前往工程师途中，寻找少绕路的模组／舰载武器售卖点，可筛选已知折扣。',
              wraplength=1280).pack(fill='x', padx=12)
    ttk.Label(form, text='自动覆盖单跳和多跳；额外跳数相对直达估算。未验证实际航线，排序仅针对已取回的命中。',
              wraplength=1280, style='Muted.TLabel').pack(fill='x', padx=12)
    ttk.Label(form, text='每项独立选择规格、折扣和新鲜度；到站距离留空不限，不核实购买数量。',
               style='Muted.TLabel').pack(fill='x', padx=12)
    ttk.Checkbutton(form, text='按满级个人优惠计算（默认）',
                    variable=variables['assume_max_rank']).pack(anchor='w', padx=12)
    win.personal_discount_note = ttk.Label(form,
        text='选择效忠 Power 后假设已解锁最高等级奖励，未读取实际等级；仅限本势力领地内适用武器，不与公共优惠相加，航母不计入。',
        wraplength=1250, style='Muted.TLabel')
    win.personal_discount_note.pack(fill='x', padx=12)

    actions = ttk.Frame(win, padding=8)
    actions.pack(fill='x')
    ttk.Checkbutton(actions, text='忽略航母', variable=variables['ignore_carriers']).pack(side='right', padx=4)
    ttk.Checkbutton(actions, text='忽略地面站', variable=variables['ignore_planetary']).pack(side='right', padx=4)
    status = tk.StringVar(win, value='就绪')
    ttk.Label(win, textvariable=status, wraplength=1280).pack(fill='x', padx=8)
    bar = ttk.Progressbar(win, mode='indeterminate')
    bar.pack(fill='x', padx=8, pady=4)
    frame = ttk.Frame(win)
    frame.pack(fill='both', expand=True, padx=8, pady=4)
    tree = ttk.Treeview(frame, columns=(), show='headings')
    vertical = ttk.Scrollbar(frame, orient='vertical', command=tree.yview)
    horizontal = ttk.Scrollbar(frame, orient='horizontal', command=tree.xview)
    tree.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
    tree.grid(row=0, column=0, sticky='nsew')
    vertical.grid(row=0, column=1, sticky='ns')
    horizontal.grid(row=1, column=0, sticky='ew')
    frame.rowconfigure(0, weight=1)
    frame.columnconfigure(0, weight=1)
    events, stop = queue.Queue(), threading.Event()
    state = dict(busy=False, result=None)

    def criteria():
        conditions = tool.build_criteria(variables['origin'].get(), variables['destination'].get(),
                                           variables['jump_range'].get(), variables['arrival_ls'].get(),
                                           [row.to_cond() for row in purchase_rows],
                                           ignore_carriers=variables['ignore_carriers'].get(),
                                           max_extra_jumps=variables['max_extra_jumps'].get(),
                                           ignore_planetary=variables['ignore_planetary'].get(),
                                           landing_pad=variables['landing_pad'].get(),
                                           pledged_power=variables['pledged_power'].get(),
                                           assume_max_rank=variables['assume_max_rank'].get())
        want, pages = int(variables['want'].get()), int(variables['max_pages'].get())
        if want < 1 or pages < 1:
            raise ValueError('结果数和页数必须大于零，每页数量必须在 1~500 之间')
        return conditions, want, pages

    def table():
        return tool.export_table(state['result'], app.localizer.language, app.localizer.tr)

    def render():
        headers, records = table()
        columns = tuple(f'value_{index}' for index in range(len(headers)))
        tree.set_columns(columns)
        for key, title in zip(columns, headers):
            tree.heading(key, text=title)
            tree.column(key, width=190, minwidth=80, stretch=False)
        tree.delete(*tree.get_children())
        for index, values in enumerate(records):
            tree.insert('', 'end', iid=str(index), values=values)
        result = state['result']
        if result:
            if app.localizer.language == 'en':
                status.set(f"Scanned: {result['scanned']}; matches: {len(result['rows'])}. " +
                           ' | '.join(app.localizer.tr(note) for note in result['notes']))
            else:
                status.set(f"已扫描：{result['scanned']}；命中：{len(result['rows'])}。" + '；'.join(result['notes']))

    def run():
        if state['busy']:
            return
        try:
            conditions, want, pages = criteria()
        except (ValueError, TypeError) as exc:
            messagebox.showwarning('条件有误', str(exc), parent=win)
            return
        stop.clear()
        state.update(busy=True, result=None)
        render()
        status.set('正在查询…')
        search_button.configure(state='disabled')
        stop_button.configure(state='normal')
        bar.start()

        def worker():
            try:
                result = tool.search(conditions, want=want, max_pages=pages, stop=stop,
                                     progress=lambda text, detail=None: events.put(('progress', text)))
                events.put(('done', result))
            except Exception as exc:
                events.put(('error', str(exc)))
        threading.Thread(target=worker, daemon=True).start()

    def export():
        if not state['result']:
            return
        path = filedialog.asksaveasfilename(parent=win, defaultextension='.csv', filetypes=[('CSV', '*.csv')])
        if path:
            try:
                headers, records = table()
                with open(path, 'w', newline='', encoding='utf-8-sig') as file:
                    writer = csv.writer(file)
                    write_csv_provenance(writer, len(headers), app.localizer.language)
                    writer.writerow(headers)
                    writer.writerows(records)
            except OSError as exc:
                messagebox.showerror('导出失败', str(exc), parent=win)

    def copy(key):
        from result_copy import copy_result
        return copy_result(win, tree, getter=lambda item: state['result']['rows'][int(item)].get(key, ''))

    search_button = ttk.Button(actions, text='查询', command=run)
    search_button.pack(side='left', padx=4)
    stop_button = ttk.Button(actions, text='停止', command=stop.set, state='disabled')
    stop_button.pack(side='left', padx=4)
    ttk.Button(actions, text='复制星系名', command=lambda: copy('system_name')).pack(side='left', padx=4)
    ttk.Button(actions, text='复制站名', command=lambda: copy('name')).pack(side='left', padx=4)
    ttk.Button(actions, text='导出CSV', command=export).pack(side='left', padx=4)
    tree.bind('<Double-1>', lambda event: copy('system_name'))
    poll_id = None

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
            app.localizer.callbacks.discard(render)

    app.localizer.register(render)
    win.bind('<Destroy>', destroyed, add='+')
    win.criteria, win.run_search = criteria, run
    win.export_csv = export
    win.result_tree, win.search_state = tree, state
    win.purchase_rows, win.add_purchase, win.remove_purchase = purchase_rows, add_purchase, remove_purchase
    render()
    poll()
    return win
