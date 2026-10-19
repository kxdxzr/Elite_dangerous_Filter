"""稀有商品目标查找器；后台仅使用普通Python数据，Tk更新交给App调度器。"""
import csv
from export_metadata import write_csv_provenance
from result_format import format_ls
from result_copy import copy_result
import threading
import tkinter as tk
from tkinter import filedialog
from localized_tk import messagebox, ttk, Toplevel

import powerplay_tool as tool
import rare_goods as sources


def open_window(app, data_age):
    win = Toplevel(app.root)
    win.title("稀有商品目标查找器")
    win.geometry("1200x760")
    controls = ttk.Frame(win, padding=8)
    controls.pack(fill="x")
    reference = tk.StringVar(value="Ngurii")
    minimum, maximum = tk.StringVar(value="200"), tk.StringVar(value="220")
    pages = tk.StringVar(value="20")
    ttk.Label(controls, text="商品来源星系").pack(side="left")
    cb_ref = ttk.Combobox(controls, textvariable=reference, width=36,
                          state="readonly", values=sources.SOURCE_SYSTEMS)
    cb_ref.pack(side="left", padx=4, fill='x', expand=True)
    distances = ttk.Frame(win, padding=(8, 0))
    distances.pack(fill='x')
    for label, variable in (("最小距离 ly", minimum), ("最大距离 ly", maximum),
                            ("每轮最多页数", pages)):
        ttk.Label(distances, text=label).pack(side="left", padx=(8, 0))
        ttk.Entry(distances, textvariable=variable, width=7).pack(side="left", padx=4)
    source_filter = ttk.Frame(win, padding=(8, 4))
    source_filter.pack(fill="x")
    ttk.Label(source_filter, text="筛选来源（星系／商品／站名）").pack(side="left")
    query = tk.StringVar()
    entry_filter = ttk.Entry(source_filter, textvariable=query, width=32)
    entry_filter.pack(side="left", padx=4)
    source_count = tk.StringVar()
    ttk.Label(source_filter, textvariable=source_count, style='Muted.TLabel').pack(side="left", padx=6)
    source_info = tk.StringVar()
    ttk.Label(win, textvariable=source_info, wraplength=1160).pack(fill="x", padx=8, pady=4)

    def filter_options(*args):
        candidates = sources.filter_sources(query.get())
        cb_ref.configure(values=candidates)
        source_count.set(f"{len(candidates)}/{len(sources.SOURCE_SYSTEMS)} 个星系；筛选后请从下拉选择")

    def describe_source(*args):
        source_info.set(sources.source_description(reference.get()))

    query.trace_add("write", filter_options)
    reference.trace_add("write", describe_source)
    filter_options()
    describe_source()
    options = ttk.Frame(win, padding=(8, 0))
    options.pack(fill="x")
    ttk.Label(options, text="Power（关联势力）").pack(side="left")
    power = tk.StringVar(value=tool.POWER_LABELS[tool.POWERS[0]])
    cb_power = ttk.Combobox(options, textvariable=power, state="readonly", width=36,
                            values=[tool.POWER_LABELS[p] for p in tool.POWERS])
    cb_power.pack(side="left", padx=4, fill='x', expand=True)
    all_powers = tk.BooleanVar(value=False)
    ttk.Checkbutton(options, text="全势力扫描（12个）", variable=all_powers,
                    command=lambda: cb_power.configure(state="disabled" if all_powers.get()
                                                        else "readonly")).pack(side="left", padx=8)
    neutron_only = tk.BooleanVar(win, value=False)
    # Fixed-range position estimates, independent of ship-specific exact routing.
    if tool.ENABLE_NEUTRON_FILTER:
        neutron_controls = ttk.Frame(win, padding=(8, 4))
        neutron_controls.pack(fill='x')
        ttk.Checkbutton(neutron_controls, text='仅显示顺路中子星辅助目标（实验性功能）', variable=neutron_only).pack(side='left')
        ttk.Label(neutron_controls, text='去程40 ly／返程50 ly；来源200 ly内中子星；到达距离≤100 Ls',
                  style='Muted.TLabel').pack(side='left', padx=8)
        ttk.Label(win, text='顺路条件逐势力放宽：30°／10% → 45°／25% → 60°／50%，有结果即停；40／50 ly仅作内部参考，不用于排除候选，不保证实际省跳。',
                  style='Muted.TLabel', wraplength=1160).pack(fill='x', padx=8)
    ttk.Label(win, text="固定条件：大型停机坪、非地面站、排除航母和殖民船、Unoccupied。每个势力先查 ≤100 Ls，确认无结果后查 ≤1000 Ls。",
              wraplength=1160).pack(fill="x", padx=8, pady=(8, 0))
    ttk.Label(win, text=tool.STATE_NOTE + " 使用 Power，不要求由该势力控制。",
              style='Muted.TLabel', wraplength=1160).pack(fill="x", padx=8, pady=4)
    status = tk.StringVar(value="每个势力最多显示5个星系，同星系只算一个结果；空间站仅供参考，保留最近的合格站点。双击明细复制星系名。")
    ttk.Label(win, textvariable=status, wraplength=1160).pack(fill="x", padx=8)
    progressbar = ttk.Progressbar(win, mode="indeterminate")
    progressbar.pack(fill="x", padx=8, pady=4)
    from search_progress import SearchProgress
    progress_text = tk.StringVar(win)
    ttk.Label(win, textvariable=progress_text).pack(fill='x', padx=8)
    tracker = SearchProgress(progressbar, progress_text, app.localizer)

    summary = ttk.Treeview(win, columns=("power", "systems", "limit", "status"),
                           show="headings", height=6, selectmode="browse")
    for key, width, title in (("power", 250, "关联势力"),
                              ("systems", 90, "命中星系数"), ("limit", 100, "到站上限 Ls"),
                              ("status", 230, "检索状态")):
        summary.heading(key, text=title)
        summary.column(key, width=width)
    summary.pack(fill="x", padx=8, pady=4)
    frame = ttk.Frame(win)
    frame.pack(fill="both", expand=True, padx=8, pady=4)
    columns = (("power", 170, "关联势力"), ("system", 150, "星系"),
               ("station", 180, "空间站"), ("ly", 70, "距离 ly"),
               ("ls", 90, "到站距离 Ls"), ("age", 100, "站点记录年龄"),
               ('out_anchors', 190, '去程参考中子星'),
               ('in_anchors', 190, '返程参考中子星'),
               ('direction_deg', 115, '方向夹角 °'), ('detour_ly', 130, '额外绕行 ly'),
               ('alignment_label', 120, '顺路筛选档位'))
    tree = ttk.Treeview(frame, columns=[c for c, _, _ in columns], show="headings")
    tree.configure(displaycolumns=[c for c, _, _ in columns[:6]])
    for key, width, title in columns:
        tree.heading(key, text=title)
        tree.column(key, width=width, stretch=False)
    vertical = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
    horizontal = ttk.Scrollbar(frame, orient="horizontal", command=tree.xview)
    tree.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
    tree.grid(row=0, column=0, sticky="nsew")
    vertical.grid(row=0, column=1, sticky="ns")
    horizontal.grid(row=1, column=0, sticky="ew")
    frame.rowconfigure(0, weight=1)
    frame.columnconfigure(0, weight=1)
    state = {"groups": {}, "info": None, "visible": None}
    stop = threading.Event()

    def values(p, row):
        from result_format import format_ly
        comparison = row.get('_neutron', {})
        return (tool.POWER_LABELS[p], row.get("system_name", ""), row.get("name", ""),
                format_ly(row.get("_powerplay_distance")), format_ls(row.get("distance_to_arrival")),
                data_age(row.get("updated_at")),
                ' → '.join(comparison.get('outbound_anchors') or ([comparison['route_anchor']] if comparison.get('route_anchor') else [])),
                ' → '.join(comparison.get('inbound_anchors') or ([comparison['route_anchor']] if comparison.get('route_anchor') else [])),
                *[f'{comparison[key]:,.2f}' if key in comparison else '' for key in ('direction_deg', 'detour_ly')],
                comparison.get('alignment_label', ''))

    def active_columns():
        return columns if state['info'] and state['info'].get('neutron_filter') else columns[:6]

    def show_details(p=None):
        state["visible"] = p
        tree.configure(displaycolumns=[c for c, _, _ in active_columns()])
        tree.delete(*tree.get_children())
        for name, group in state["groups"].items():
            if p is None or name == p:
                for row in group["rows"]:
                    tree.insert("", "end", values=values(name, row))

    def selected(event=None):
        selection = summary.selection()
        if selection:
            show_details(selection[0])

    summary.bind("<<TreeviewSelect>>", selected)

    def copy_system(event=None):
        copy_result(win, tree, 'system')

    tree.bind("<Double-1>", copy_system)

    def export():
        if not state["groups"]:
            messagebox.showinfo("提示", "请先查询", parent=win)
            return
        neutron_export = bool(state['info'] and state['info'].get('neutron_filter'))
        if neutron_export and not state['info']['complete'] and not messagebox.askyesno(
                '确认', '中子筛选未完成，仅导出已确认符合条件的部分结果？', parent=win):
            return
        path = filedialog.asksaveasfilename(parent=win, defaultextension=".csv",
                                            filetypes=[("CSV", "*.csv")])
        if not path:
            return
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            exported_columns = active_columns()
            write_csv_provenance(writer, len(exported_columns), app.localizer.language)
            writer.writerow([app.localizer.tr(title) for _, _, title in exported_columns])
            for name, group in state["groups"].items():
                for row in group["rows"]:
                    writer.writerow([app.localizer.tr(value) if index >= 5 else value
                                     for index, value in enumerate(values(name, row)[:len(exported_columns)])])
                if not group["rows"]:
                    writer.writerow([tool.POWER_LABELS[name]] + [""] * (len(exported_columns) - 1))

    def notes():
        if state["info"]:
            messagebox.showinfo("检索说明", tool.STATE_NOTE + "\n\n" +
                                "\n".join(state["info"]["notes"]), parent=win)

    def finish():
        button.configure(state="normal")
        cb_ref.configure(state="readonly")
        entry_filter.configure(state="normal")
        progressbar.stop()

    def run():
        try:
            name, lo, hi, limit = reference.get().strip(), float(minimum.get()), float(maximum.get()), int(pages.get())
            chosen, scan_all = tool.normalize_power(power.get()), all_powers.get()
            use_neutron = tool.ENABLE_NEUTRON_FILTER and neutron_only.get()
            if name not in sources.SOURCE_SYSTEMS or not 0 <= lo <= hi < float("inf") or hi <= 0 or limit < 1:
                raise ValueError()
        except ValueError:
            messagebox.showwarning("参数错误", "请从列表选择来源星系，并填写有效距离区间和正整数页数", parent=win)
            return
        stop.clear()
        state.update(groups={}, info=None, visible=None)
        summary.delete(*summary.get_children())
        tree.delete(*tree.get_children())
        button.configure(state="disabled")
        cb_ref.configure(state="disabled")
        entry_filter.configure(state="disabled")
        tracker.update()
        status.set("查询中...")

        def work():
            try:
                extra = {}
                if use_neutron:
                    from rare_neutron import SavingsFilter
                    extra['neutron_filter'] = SavingsFilter(stop=stop,
                        progress=lambda msg, detail=None: app._post(win, lambda: (status.set(msg), tracker.update(msg, detail))))
                info, groups = tool.search_powerplay(
                    name, chosen, scan_all, lo, hi, limit, stop=stop,
                    progress=lambda msg, detail=None: app._post(win, lambda: (status.set(msg), tracker.update(msg, detail))),
                    **extra)

                def show():
                    state.update(groups=groups, info=info)
                    for p, group in groups.items():
                        summary.insert("", "end", iid=p, values=(tool.POWER_LABELS[p],
                            f"{group['system_count']:,}", format_ls(group['arrival_limit']), group["status"]))
                    show_details()
                    count = len({str(r.get('system_name', '')).strip().casefold()
                                 for g in groups.values() for r in g['rows']})
                    shown = sum(len(g["rows"]) for g in groups.values())
                    text = "检索完成" if info["complete"] else "检索未完成（当前仅部分结果，不代表无命中）"
                    status.set(f"参考 {info['reference']}，{lo:,.2f}–{hi:,.2f} ly：{text}；{len(groups):,} 个势力，显示 {count:,} 个不同星系、{shown:,} 条分组结果（每势力最多5个星系）。")
                    if use_neutron:
                        status.set(status.get() + ' ' + app.localizer.tr('中子筛选已启用；失败或未评估详情见检索说明。'))
                    finish()
                    tracker.finish(info['complete'])

                app._post(win, show)
            except Exception as exc:
                def failed(error=str(exc)):
                    status.set("查询失败；不能解释为无结果")
                    finish()
                    tracker.finish(False)
                    messagebox.showerror("查询失败", error, parent=win)
                app._post(win, failed)

        threading.Thread(target=work, daemon=True).start()

    button = ttk.Button(options, text="开始查询", command=run)
    button.pack(side="left", padx=6)
    ttk.Button(options, text="停止", command=stop.set).pack(side="left")
    footer = ttk.Frame(win, padding=8)
    footer.pack(side='bottom', fill='x', before=summary)
    ttk.Button(footer, text="全部组明细", command=show_details).pack(side="left")
    ttk.Button(footer, text="复制星系名", command=copy_system).pack(side="left", padx=6)
    ttk.Button(footer, text='复制空间站名', command=lambda: copy_result(win, tree, 'station')).pack(side='left', padx=6)
    ttk.Button(footer, text="导出全部组 CSV", command=export).pack(side="left")
    ttk.Button(footer, text="检索说明", command=notes).pack(side="left", padx=6)

    app.bind_tool_state("rare_goods", win, dict(reference=reference, minimum=minimum,
                        maximum=maximum, pages=pages, query=query, power=power, all_powers=all_powers,
                        neutron_only=neutron_only))
    if reference.get() not in sources.SOURCE_SYSTEMS:
        reference.set("Ngurii")
    if not tool.ENABLE_NEUTRON_FILTER:
        neutron_only.set(False)
    cb_power.configure(state="disabled" if all_powers.get() else "readonly")

    def close():
        stop.set()
        win.destroy()

    win.protocol("WM_DELETE_WINDOW", close)
    win.rare_state, win.result_tree = state, tree
    return win
