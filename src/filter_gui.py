"""Elite Dangerous GUI 筛选器: 可不停添加条件, 允许重复, 支持多参考点距离内外过滤.
第三格为下拉+联想: 选项少直接下拉选, 选项多边打边提示, 星系名有联想。
关闭时自动记住条件, 下次打开恢复。
"""
import csv
from export_metadata import PROJECT_VERSION, write_csv_provenance
import json
import os
import queue
import re
import sys
import threading
import tkinter as tk
from datetime import datetime, timezone
from tkinter import filedialog
from localized_tk import messagebox, ttk, Toplevel
from i18n import Localizer
from appearance import Appearance, MODES

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from spansh_filter import (STATION_FIELDS, SYSTEM_FIELDS, STATION_FIELDS_CN,
                             SYSTEM_FIELDS_CN, field_label, parse_field_label)
import filter_engine as eng
import field_options as fo
import session_store
from runtime_paths import data_file
from system_filter_fields import COUNT_FIELDS
from result_format import format_ly, format_ls, format_population
from search_progress import SearchProgress
from result_copy import copy_result

SYSTEM_FIELDS = dict(SYSTEM_FIELDS, **COUNT_FIELDS)
SYSTEM_FIELDS_CN.update(COUNT_FIELDS)

OP_LABELS = ["属于其一", "不属于", "等于", "不等于", "包含",
             "<", "<=", ">", ">=", "区间(内)", "范围外", "是", "否"]
OP_MAP = {"属于其一": "in", "不属于": "not in", "等于": "=",
          "不等于": "!=", "包含": "contains", "<": "<", "<=": "<=",
          ">": ">", ">=": ">=", "区间(内)": "between", "范围外": "outside",
          "是": "true", "否": "false"}
SESSION_FILE = data_file("last_session.json")
MULTI_OPS = {"属于其一", "不属于"}
SINGLE_CHOICE_OPS = {"属于其一", "不属于", "等于", "不等于", "包含"}
NUMERIC_OPS = {"<", "<=", ">", ">=", "区间(内)", "范围外"}
# 新鲜度快捷值 (时间字段区间条件用; 相对标记由引擎解析成绝对时间)
FRESH_QUICK = ["近1天", "近7天", "近30天", "近90天"]
FRESH_FIELDS = {"last_updated_at", "market_last_updated_at",
                "shipyard_last_updated_at", "outfitting_last_updated_at"}
# 船/模块名自动纠错字段
AUTOCORRECT_FIELDS = {"ships", "modules"}
# 船/模块行集成新鲜度 (卖X且数据N天内新, 只本地复核)
FRESH_OPTS = ["不限", "近1天", "近7天", "近30天", "近90天"]
FRESH_DAYS = {"近1天": 1, "近7天": 7, "近30天": 30, "近90天": 90}
FRESH_FIELDS_ROWS = {"ships", "modules"}
_FRESH_OPT_RE = re.compile(r"^近(\d+)天$")


def ui_dispatcher(widget):
    """主线程初始化；后台线程只入队，所有 Tk 调用由主线程执行。"""
    root = widget._root()
    if hasattr(root, "_ui_post"):
        return root._ui_post
    pending = queue.Queue()

    def post(owner, callback, *args):
        pending.put((owner, callback, args))

    def drain():
        for _ in range(100):
            try:
                owner, callback, args = pending.get_nowait()
            except queue.Empty:
                break
            if owner.winfo_exists():
                try:
                    callback(*args)
                except Exception:
                    root.report_callback_exception(*sys.exc_info())
        root.after(30, drain)

    root._ui_post = post
    root.after(30, drain)
    return post


def fresh_opt_days(label):
    """新鲜度选项 -> 天数 (不限/非法 -> None)。"""
    days = FRESH_DAYS.get((label or "").strip())
    if days is not None:
        return days
    m = _FRESH_OPT_RE.match((label or "").strip())
    return int(m.group(1)) if m else None


def data_age(ts):
    """更新时间 -> '3天前'/'5小时前'/'刚刚'/'未知'。"""
    if not ts:
        return "未知"
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return "未知"
    secs = (datetime.now(timezone.utc) - dt).total_seconds()
    if secs < 0:
        return "未知"
    if secs < 60:
        return "刚刚"
    if secs < 3600:
        return f"{int(secs // 60)}分钟前"
    if secs < 86400:
        return f"{int(secs // 3600)}小时前"
    return f"{int(secs // 86400)}天前"


def open_multi_select(parent, title, options, current):
    """多选弹窗, 返回选中的 list[str] 或 None(取消)."""
    win = Toplevel(parent)
    win.title(title)
    win.geometry("340x420")
    win.transient(parent)
    cur = [c.strip().lower() for c in current if c.strip()]
    ttk.Label(win, text="输入过滤, 勾选后确定 (多选用 ; 连接)").pack(fill="x", padx=6, pady=4)
    q = tk.StringVar()
    ttk.Entry(win, textvariable=q).pack(fill="x", padx=6)
    lb = tk.Listbox(win, selectmode="multiple", height=18)
    lb.pack(fill="both", expand=True, padx=6, pady=4)
    shown = list(options)

    def refill():
        s = q.get().strip().lower()
        shown.clear()
        shown.extend([o for o in options if not s or s in o.lower()])
        lb.delete(0, "end")
        for o in shown:
            lb.insert("end", o)
            if o.lower() in cur:
                lb.selection_set("end")

    def on_q(*a):
        refill()

    q.trace_add("write", on_q)
    refill()
    picked = {"vals": None}

    def ok():
        picked["vals"] = [shown[i] for i in lb.curselection()]
        win.destroy()

    ttk.Button(win, text="确定", command=ok).pack(pady=4)
    win.bind("<Return>", lambda e: ok())
    parent.wait_window(win)
    return picked["vals"]


class SuggestPopup:
    """单例: 在输入框下方弹出候选列表 (Inara式联想)。
    焦点始终留在输入框, 上下键移动高亮, 回车/Tab/点击选中, Esc关闭。"""
    _inst = None

    @classmethod
    def inst(cls):
        if cls._inst is None:
            cls._inst = SuggestPopup()
        return cls._inst

    def __init__(self):
        self.win = None
        self.lb = None
        self.on_pick = None
        self.anchor = None

    def visible_for(self, widget):
        return self.win is not None and self.anchor is widget

    def show(self, widget, items, on_pick):
        self.hide()
        items = [i for i in items if i][:8]
        if not items or not widget.winfo_exists():
            return
        try:
            x = widget.winfo_rootx()
            y = widget.winfo_rooty() + widget.winfo_height()
        except tk.TclError:
            return
        self.on_pick = on_pick
        self.anchor = widget
        self.win = tk.Toplevel(widget)
        self.win.wm_overrideredirect(True)
        self.win.wm_geometry(f"+{x}+{y}")
        self.win.lift()
        self.lb = tk.Listbox(self.win, height=len(items),
                             width=max(16, min(44, max(len(s) for s in items) + 2)))
        self.lb.pack()
        for it in items:
            self.lb.insert("end", it)
        self.lb.selection_set(0)
        self.lb.bind("<ButtonPress-1>", self._pick)

    def _pick(self, event):
        """Select the clicked row before class bindings can move focus."""
        if self.lb is not None:
            index = self.lb.nearest(event.y)
            self.lb.selection_clear(0, "end")
            self.lb.selection_set(index)
            self.pick_current()
        return "break"

    def move(self, delta):
        if not self.lb or not self.win:
            return False
        sel = self.lb.curselection()
        i = (sel[0] if sel else (-1 if delta > 0 else self.lb.size())) + delta
        i = max(0, min(self.lb.size() - 1, i))
        self.lb.selection_clear(0, "end")
        self.lb.selection_set(i)
        self.lb.see(i)
        return True

    def pick_current(self):
        if not self.lb or not self.win:
            return False
        sel = self.lb.curselection()
        vals = [self.lb.get(i) for i in (sel or (0,))]
        if not vals:
            return False
        cb, val = self.on_pick, vals[0]
        self.hide()
        if cb:
            cb(val)
        return True

    def hide(self, widget=None):
        if widget is not None and self.anchor is not widget:
            return
        if self.win is not None:
            try:
                self.win.destroy()
            except tk.TclError:
                pass
        self.win = None
        self.lb = None
        self.on_pick = None
        self.anchor = None


def attach_system_suggest(cb, textvar, suggest=None, feedback=None):
    post = ui_dispatcher(cb)
    """给任意星系输入框接下方候选弹窗 (打字即弹, 上下选, 回车/点击确认)。"""
    state = {"seq": 0, "hits": [], "selecting": False, "last_text": textvar.get()}
    provider = suggest or fo.suggest_systems
    pop = SuggestPopup.inst()

    def pick(val):
        cancel_timer()
        state["seq"] += 1
        state["selecting"] = True
        try:
            textvar.set(val)
            state["last_text"] = val
        finally:
            state["selecting"] = False
        if feedback:
            feedback.set("已选择完整名称")

    def cancel_timer():
        if state.get("timer"):
            try:
                cb.after_cancel(state["timer"])
            except tk.TclError:
                pass
            state["timer"] = None

    def on_key(event):
        if event.keysym in ("Down", "Up"):
            if pop.visible_for(cb):
                pop.move(1 if event.keysym == "Down" else -1)
                return
            if state["hits"]:
                pop.show(cb, state["hits"], pick)
            else:
                schedule()
            return
        if event.keysym in ("Return", "Tab"):
            if pop.visible_for(cb) and pop.pick_current():
                return
            return
        if event.keysym == "Escape":
            state["seq"] += 1
            pop.hide(cb)
            cancel_timer()
            return
        if textvar.get() != state["last_text"]:
            changed()

    def schedule():
        cancel_timer()
        state["seq"] += 1
        state["hits"] = []
        cb["values"] = []
        pop.hide(cb)
        text = textvar.get()
        state["last_text"] = text
        seq = state["seq"]
        if len(text.strip()) < 2:
            if feedback:
                feedback.set("输入至少两个字符联想；选择候选后使用完整名称。")
            return
        if feedback:
            feedback.set("正在查询名称候选…")

        def fire():
            state["timer"] = None

            def work():
                error = None
                try:
                    sug = provider(text)
                except Exception as exc:
                    sug, error = [], str(exc)

                def apply():
                    if seq != state["seq"] or text != textvar.get() or not cb.winfo_exists():
                        return
                    state["hits"] = sug
                    if feedback:
                        feedback.set("名称联想失败；可继续手动输入完整名称。" if error else
                                     ("输入至少两个字符联想；选择候选后使用完整名称。" if len(text.strip()) < 2 else
                                      ("请选择候选完整名称；不自动改写输入。" if sug else
                                       "未找到名称候选；不代表该派系不存在。")))
                    cb["values"] = sug
                    if sug:
                        try:
                            focused = cb.focus_get() == cb
                        except tk.TclError:
                            focused = False
                        if focused:
                            pop.show(cb, sug, pick)
                    else:
                        pop.hide(cb)
                post(cb, apply)
            threading.Thread(target=work, daemon=True).start()

        try:
            state["timer"] = cb.after(250, fire)
        except tk.TclError:
            pass

    def changed(*args):
        if state["selecting"] or textvar.get() == state["last_text"]:
            return
        state["last_text"] = textvar.get()
        state["seq"] += 1
        state["hits"] = []
        cancel_timer()
        if cb.focus_get() == cb:
            schedule()
        else:
            cb["values"] = []
            pop.hide(cb)

    trace = textvar.trace_add("write", changed)
    cb.bind("<KeyRelease>", on_key)
    cb.bind("<<ComboboxSelected>>", lambda e: pick(textvar.get()))
    def blur(event):
        def check():
            state["blur_timer"] = None
            if not cb.winfo_exists():
                return
            focus = cb.focus_get()
            if focus != cb and focus != pop.lb:
                pop.hide(cb)
        if state.get("blur_timer"):
            cb.after_cancel(state["blur_timer"])
        state["blur_timer"] = cb.after(100, check)
    cb.bind("<FocusOut>", blur)

    def destroyed(event):
        if event.widget is cb:
            state["seq"] += 1
            cancel_timer()
            if state.get("blur_timer"):
                cb.after_cancel(state["blur_timer"])
            textvar.trace_remove("write", trace)
            pop.hide(cb)
    cb.bind("<Destroy>", destroyed, add="+")
    cb.configure(postcommand=schedule)
    return state


class Row:
    def __init__(self, master, kind, rowtype="field"):
        self._post = ui_dispatcher(master)
        self.type = rowtype
        self.kind = kind
        self._options = []      # 全量候选
        self._seq = 0           # 异步刷新序号, 防旧结果覆盖新字段
        self.frame = ttk.Frame(master, padding=(8, 6), style='Condition.TFrame')
        self.frame.pack(fill="x", pady=4)
        if rowtype == "distance":
            ttk.Label(self.frame, text="到星系距离", width=10).pack(side="left")
            self.ref = tk.StringVar(value="Sol")
            self.cb_ref = ttk.Combobox(self.frame, textvariable=self.ref, width=16)
            self.cb_ref.pack(side="left", padx=2)
            self.cb_ref.bind("<KeyRelease>", self._on_ref_key)
            self._ref_seq = 0
            self.cb_ref.bind("<<ComboboxSelected>>",
                             lambda e: SuggestPopup.inst().hide(self.cb_ref))
            ttk.Label(self.frame, text="最小LY").pack(side="left")
            self.vmin = tk.StringVar()
            ttk.Entry(self.frame, textvariable=self.vmin, width=8).pack(side="left")
            ttk.Label(self.frame, text="最大LY").pack(side="left")
            self.vmax = tk.StringVar(value="50")
            ttk.Entry(self.frame, textvariable=self.vmax, width=8).pack(side="left")
            self.mode = tk.StringVar(value="范围内")
            ttk.Combobox(self.frame, textvariable=self.mode, width=8,
                         values=["范围内", "范围外"], state="readonly").pack(side="left", padx=4)
            self.ref_info = tk.StringVar(value="")
            self.lbl_ref = ttk.Label(self.frame, textvariable=self.ref_info,
                                     style='Muted.TLabel')
            self.lbl_ref.pack(side="left", padx=4)
            self.cb_ref.bind("<FocusOut>", lambda e: (SuggestPopup.inst().hide(self.cb_ref),
                                                          self.validate_ref()))
        else:
            bar = self.controls = ttk.Frame(self.frame)
            bar.pack(fill='x')
            self.subcontrols = ttk.Frame(self.frame)
            ttk.Label(bar, text='条件分类').pack(side='left')
            self.v_category = tk.StringVar(value='不限')
            self.cb_category = ttk.Combobox(bar, textvariable=self.v_category, width=16,
                                           state='readonly')
            self.cb_category.pack(side='left', padx=2)
            self.cb_category.bind('<<ComboboxSelected>>', lambda e: self.change_category())
            self.field = tk.StringVar()
            self.op = tk.StringVar(value="属于其一")
            self.val = tk.StringVar()
            self.cb_field = ttk.Combobox(bar, textvariable=self.field,
                                         width=30, state="readonly")
            self.cb_field.pack(side="left", padx=2)
            self.cb_field.bind("<<ComboboxSelected>>", lambda e: self.refresh_options())
            self.cb_op = ttk.Combobox(bar, textvariable=self.op, width=10,
                                      values=OP_LABELS, state="readonly")
            self.cb_op.pack(side="left")
            self.cb_op.bind("<<ComboboxSelected>>", lambda e: self.refresh_options())
            self.cb_val = ttk.Combobox(bar, textvariable=self.val, width=24)
            self.cb_val.pack(side="left", padx=4, fill="x", expand=True)
            self.cb_val.bind("<KeyRelease>", self._on_val_key)
            self.cb_val.bind("<<ComboboxSelected>>",
                             lambda e: (SuggestPopup.inst().hide(self.cb_val),
                                        self.validate_val()))
            self.cb_val.bind("<FocusOut>", lambda e: (SuggestPopup.inst().hide(self.cb_val),
                                                      self.validate_val()))
            self.btn_pick = ttk.Button(bar, text="选值…", width=6,
                                        command=self.pick_values)
            self.btn_pick.pack(side="left")
            from module_slots import SLOT_GROUPS
            self.lbl_slot = ttk.Label(bar, text='槽位类型')
            self.v_slot = tk.StringVar(value='不限')
            self.cb_slot = ttk.Combobox(bar, textvariable=self.v_slot, width=12,
                                       values=SLOT_GROUPS, state='readonly')
            self.cb_slot.bind('<<ComboboxSelected>>', lambda e: self.refresh_options())
            # One paired specification selector; legacy filters retain their model variables.
            self.v_class = tk.StringVar()
            self.v_rating = tk.StringVar()
            self.lbl_spec = ttk.Label(self.subcontrols, text='规格')
            self.v_spec = tk.StringVar(value='不限')
            self._spec_display = '不限'
            self.cb_spec = ttk.Combobox(self.subcontrols, textvariable=self.v_spec, width=28,
                                        postcommand=self._refresh_spec_options)
            self.cb_spec.bind('<<ComboboxSelected>>', lambda e: self._commit_spec())
            self.cb_spec.bind('<FocusOut>', lambda e: self.validate_val())
            # 集成新鲜度: 仅 ships/modules + 属于/等于/包含时显示
            self.lbl_fresh = ttk.Label(self.subcontrols, text="新鲜度")
            self.v_fresh = tk.StringVar(value="不限")
            self.cb_fresh = ttk.Combobox(self.subcontrols, textvariable=self.v_fresh, width=8,
                                         values=FRESH_OPTS, state="readonly")
            self.lbl_discount = ttk.Label(self.subcontrols, text='是否打折')
            self.v_discount = tk.StringVar(value='不限')
            self.cb_discount = ttk.Combobox(self.subcontrols, textvariable=self.v_discount, width=6,
                                           values=['不限', '是'], state='readonly')
            self.opt_info = tk.StringVar(value="")
            self.lbl_opt = ttk.Label(bar, textvariable=self.opt_info, width=10,
                                     style='Muted.TLabel')
            self.lbl_opt.pack(side="left")
            self._opt_base = ""
            self.set_fields(kind)
            self.refresh_options()
        ttk.Button(self.controls if self.type == 'field' else self.frame, text="删除", width=6,
                   command=self.destroy).pack(side="right")

    # ---- 距离参考点联想 (Inara式): 打字即在下方弹候选 ----
    def _on_ref_key(self, event):
        pop = SuggestPopup.inst()
        if event.keysym in ("Down", "Up"):
            if pop.visible_for(self.cb_ref):
                pop.move(1 if event.keysym == "Down" else -1)
                return
            # 没弹窗时按↓: 用上次结果直接弹
            if getattr(self, "_ref_hits", None):
                pop.show(self.cb_ref, self._ref_hits, self._pick_ref)
            return
        if event.keysym in ("Return", "Tab"):
            if pop.visible_for(self.cb_ref) and pop.pick_current():
                return
            return
        if event.keysym == "Escape":
            pop.hide(self.cb_ref)
            return
        if getattr(self, "_ref_timer", None):
            try:
                self.frame.after_cancel(self._ref_timer)
            except tk.TclError:
                pass
            self._ref_timer = None

        def fire():
            self._ref_timer = None
            self._ref_seq += 1
            seq = self._ref_seq
            text = self.ref.get()

            def work():
                sug = fo.suggest_systems(text)

                def apply():
                    if seq != self._ref_seq or not self.cb_ref.winfo_exists():
                        return
                    self._ref_hits = sug
                    if sug:
                        self.cb_ref["values"] = sug
                        if self.cb_ref.focus_get() == self.cb_ref:
                            pop.show(self.cb_ref, sug, self._pick_ref)
                    else:
                        pop.hide(self.cb_ref)
                self._post(self.frame, apply)
            threading.Thread(target=work, daemon=True).start()

        try:
            self._ref_timer = self.frame.after(250, fire)
        except tk.TclError:
            pass
    def _pick_ref(self, val):
        self.ref.set(val)
        self.validate_ref()

    # ---- 参考星系失焦即校验: 存在打勾, 打错自动纠, 不存在报错+建议 ----
    def validate_ref(self):
        if self.type != "distance":
            return
        name = self.ref.get().strip()
        if not name:
            self.ref_info.set("请填星系")
            self.lbl_ref["foreground"] = "red"
            return
        self._ref_vseq = getattr(self, "_ref_vseq", 0) + 1
        seq = self._ref_vseq

        def work():
            try:
                canon, _, fixed = eng.resolve_ref(name)
            except ValueError as e:
                msg = str(e)
                def apply_err():
                    if seq != self._ref_vseq or not self.frame.winfo_exists():
                        return
                    self.ref_info.set(msg[:70])
                    self.lbl_ref["foreground"] = "red"
                self._post(self.frame, apply_err)
                return

            def apply_ok():
                if seq != self._ref_vseq or not self.frame.winfo_exists():
                    return
                if fixed:
                    self.ref.set(canon)
                    self.ref_info.set(f"已纠正为 {canon}")
                else:
                    self.ref_info.set(f"✓ {canon}")
                self.lbl_ref["foreground"] = "green"
            self._post(self.frame, apply_ok)
        threading.Thread(target=work, daemon=True).start()

    # ---- 第三格: 下拉 + 联想 ----
    def set_fields(self, kind):
        if self.type != "field":
            return
        self.kind = kind
        from field_categories import available_groups, fields_for
        fields = STATION_FIELDS if kind == 'stations' else SYSTEM_FIELDS
        groups = available_groups(fields)
        self.cb_category['values'] = groups
        if self.v_category.get() not in groups:
            self.v_category.set('不限')
        keys = fields_for(fields, self.v_category.get())
        labels = [field_label(kind, k) for k in keys]
        self.cb_field["values"] = labels
        cur_en = parse_field_label(self.field.get())
        if cur_en not in keys:
            first = keys[0] if keys else ""
            self.field.set(field_label(kind, first) if first else "")

    def change_category(self):
        self.set_fields(self.kind)
        self.refresh_options()

    def _toggle_module_sub(self):
        """模块规格输入显隐: 仅 stations.modules + 属于/等于/包含时显示。"""
        show = (self.type == "field" and self.kind == "stations"
                and parse_field_label(self.field.get().strip()) == "modules"
                and self.op.get() in ("属于其一", "等于", "包含"))
        browse = (self.kind == 'stations' and parse_field_label(self.field.get().strip()) == 'modules'
                  and self.op.get() not in NUMERIC_OPS and self.op.get() not in ('是', '否'))
        for widget in (self.lbl_slot, self.cb_slot):
            if browse:
                widget.pack(side='left', before=self.cb_val, padx=(4, 0))
            else:
                widget.pack_forget()
        for w in (self.lbl_spec, self.cb_spec):
            if show:
                w.pack(side="left", padx=(4, 0))
            else:
                w.pack_forget()
        if show:
            self._refresh_spec_options()
        self._toggle_fresh()
        return show

    def _single_module_name(self):
        """当前模块值是单个确切模块名时返回其标准名，否则 None（多值不联动）。"""
        if self.type != "field" or self.kind != "stations":
            return None
        if parse_field_label(self.field.get().strip()) != "modules":
            return None
        segs = [s.strip() for s in self.val.get().replace("，", ";").replace(",", ";").split(";")
                if s.strip()]
        if len(segs) != 1:
            return None
        low = segs[0].casefold()
        for o in self._options or fo.get_options("stations", "modules"):
            if str(o).casefold() == low:
                return str(o)
        return None

    def _refresh_spec_options(self):
        """One specification dropdown; no class/rating cross product."""
        names = [s.strip() for s in self.val.get().replace('，', ';').replace(',', ';').split(';') if s.strip()]
        self.cb_spec['values'] = ['不限'] + fo.get_module_variants(names)
        if self.v_spec.get() == self._spec_display:
            self._sync_spec_display()

    def _spec_text(self):
        classes = [s.strip() for s in self.v_class.get().split(';') if s.strip()]
        ratings = [s.strip() for s in self.v_rating.get().split(';') if s.strip()]
        if not classes and not ratings:
            display = '不限'
        elif len(classes) == len(ratings) == 1:
            display = classes[0] + ratings[0]
        else:
            # Preserve old partial/multiple filters without inventing paired variants.
            display = f"class={';'.join(classes) or '*'} / rating={';'.join(ratings) or '*'}"
        return display

    def _sync_spec_display(self):
        if not hasattr(self, 'v_spec'):
            return
        self._spec_display = self._spec_text()
        self.v_spec.set(self._spec_display)

    def _commit_spec(self):
        if not hasattr(self, 'v_spec') or self.v_spec.get() == self._spec_display:
            return
        if self.v_spec.get() == self._spec_text():
            self._spec_display = self.v_spec.get()
            return
        raw = self.v_spec.get().strip().upper()
        if not raw or raw == '不限':
            self.v_class.set('')
            self.v_rating.set('')
        elif re.fullmatch(r'[0-8][A-I]', raw):
            self.v_class.set(raw[0])
            self.v_rating.set(raw[1])
        else:
            raise ValueError('规格请填写如 2C、5A，或选择不限')
        self._sync_spec_display()

    def _toggle_fresh(self):
        """集成新鲜度显隐: ships/modules + 属于/等于/包含时显示。"""
        show = (self.type == "field" and self.kind == "stations"
                and parse_field_label(self.field.get().strip()) in FRESH_FIELDS_ROWS
                and self.op.get() in ("属于其一", "等于", "包含"))
        if show:
            self.subcontrols.pack(fill='x', pady=(3, 0))
        else:
            self.subcontrols.pack_forget()
        for w in (self.lbl_fresh, self.cb_fresh, self.lbl_discount, self.cb_discount):
            if show:
                w.pack(side="left", padx=(4, 0))
            else:
                w.pack_forget()
        return show

    def refresh_options(self):
        if self.type != "field":
            return
        self._toggle_module_sub()
        op = self.op.get()
        if op in ("是", "否"):
            self.cb_val.set("")
            self.cb_val["state"] = "disabled"
            self.btn_pick["state"] = "disabled"
            self.opt_info.set("无需填写")
            return
        self.cb_val["state"] = "normal"
        field = parse_field_label(self.field.get().strip())
        if self.kind == 'systems' and field in COUNT_FIELDS:
            self._seq += 1
            self._options = []
            self.cb_val['values'] = []
            self.btn_pick['state'] = 'disabled'
            self.opt_info.set('填数字/min~max')
            return
        if field in FRESH_FIELDS and op in ("区间(内)", "范围外"):
            # 新鲜度快捷: 可选近N天, 也可手填日期区间
            self.cb_val["values"] = list(FRESH_QUICK)
            self._options = list(FRESH_QUICK)
            self.btn_pick["state"] = "normal"
            self.opt_info.set("快捷或手填日期")
            self._opt_base = self.opt_info.get()
            self.lbl_opt["foreground"] = "gray"
            return
        if op in NUMERIC_OPS:
            self.cb_val["values"] = []
            self.btn_pick["state"] = "disabled"
            if field in FRESH_FIELDS:
                self.opt_info.set("填日期或近N天")
            else:
                self.opt_info.set("填数字/min~max")
            return
        # 枚举/文本类: 异步取候选
        kind = self.kind
        slot = self.v_slot.get()
        self._seq += 1
        seq = self._seq
        self.opt_info.set("加载中…")
        self.btn_pick["state"] = "normal"

        def work():
            opts = fo.get_options(kind, field)
            if kind == 'stations' and field == 'modules':
                from module_slots import options_for
                opts = options_for(opts, slot)
            def apply():
                if seq != self._seq or not self.frame.winfo_exists():
                    return
                self._options = opts
                if opts:
                    self.cb_val["values"] = opts[:50] if len(opts) > 50 else opts
                    if len(opts) <= 30:
                        self.opt_info.set(f"{len(opts)}个可下拉")
                    else:
                        self.opt_info.set(f"{len(opts)}个打字筛")
                else:
                    self.cb_val["values"] = []
                    self.opt_info.set("自由输入")
                self._opt_base = self.opt_info.get()
                self.lbl_opt["foreground"] = "gray"
            self._post(self.frame, apply)
        threading.Thread(target=work, daemon=True).start()

    def _on_val_key(self, event):
        pop = SuggestPopup.inst()
        if event.keysym in ("Down", "Up"):
            if pop.visible_for(self.cb_val):
                pop.move(1 if event.keysym == "Down" else -1)
                return
            if getattr(self, "_val_hits", None):
                pop.show(self.cb_val, self._val_hits, self._pick_val)
            return
        if event.keysym in ("Return", "Tab"):
            if pop.visible_for(self.cb_val) and pop.pick_current():
                return
            return
        if event.keysym == "Escape":
            pop.hide(self.cb_val)
            return
        if not self._options or self.op.get() in NUMERIC_OPS:
            pop.hide(self.cb_val)
            return
        # 只对当前正在输入的一段(按 ; 分)做过滤, 并在下方弹出
        text = self.val.get()
        seg = text.replace("，", ";").split(";")[-1].strip().lower()
        if not seg:
            hit = self._options[:50]
        else:
            hit = [o for o in self._options if seg in o.lower()][:30]
        self._val_hits = hit
        self.cb_val["values"] = hit
        if hit and self.cb_val.focus_get() == self.cb_val:
            pop.show(self.cb_val, hit, self._pick_val)
        else:
            pop.hide(self.cb_val)

    def _pick_val(self, val):
        if self.op.get() in MULTI_OPS:
            # 多选: 只替换正在输入的最后一段
            parts = self.val.get().replace("，", ";").split(";")
            parts[-1] = val
            self.val.set("; ".join(p.strip() for p in parts if p.strip()))
        else:
            self.val.set(val)
        self._refresh_spec_options()

    def validate_val(self):
        """船/模块名失焦即校验: 未知标红+建议, 可纠正提示将自动纠 (实际纠正在运行时)。"""
        if self.type != "field" or not self.frame.winfo_exists():
            return
        f = parse_field_label(self.field.get().strip())
        if self.kind != "stations" or f not in AUTOCORRECT_FIELDS:
            return
        if self.op.get() in NUMERIC_OPS:
            return
        segs = [s.strip() for s in self.val.get().replace("，", ";").replace(",", ";").split(";")
                if s.strip()]
        if not segs:
            self.opt_info.set(self._opt_base)
            self.lbl_opt["foreground"] = "gray"
            return
        bad, fixes = [], []
        for s in segs:
            try:
                canon, fixed = eng.resolve_option("stations", f, s)
                if fixed:
                    fixes.append((s, canon))
            except ValueError:
                sims = (fo.similar_modules(s) if f == "modules"
                        else fo.similar_ships(s))
                bad.append((s, sims[0][0] if sims else "无"))
        if bad:
            s, sug = bad[0]
            self.opt_info.set(f"未知:{s}→{sug}?"[:24])
            self.lbl_opt["foreground"] = "red"
            return
        if fixes:
            self.opt_info.set("、".join(f"{a}→{b}" for a, b in fixes)[:24])
            self.lbl_opt["foreground"] = "orange"
            return
        self._refresh_spec_options()
        if self.op.get() in ("属于其一", "等于", "包含"):
            try:
                if f == 'modules':
                    self._commit_spec()
                for seg in [x.strip() for x in self.v_class.get().replace("，", ";").replace(",", ";").split(";") if x.strip()]:
                    eng.parse_module_class(seg, "等级")
                for seg in [x.strip() for x in self.v_rating.get().replace("，", ";").replace(",", ";").split(";") if x.strip()]:
                    eng.parse_module_rating(seg, "级别")
            except ValueError as e:
                self.opt_info.set(str(e)[:24])
                self.lbl_opt["foreground"] = "red"
                return
            if f == 'modules' and re.fullmatch(r'[0-8][A-I]', self.v_spec.get()):
                variants = fo.get_module_variants(segs)
                if self.v_spec.get() not in variants:
                    self.opt_info.set('未确认此规格，可手填查询')
                    self.lbl_opt['foreground'] = 'orange'
                    return
        self.opt_info.set(self._opt_base)
        self.lbl_opt["foreground"] = "gray"

    def pick_values(self):
        if not self._options:
            messagebox.showinfo("提示", "该字段无预置选项, 直接输入即可 (星系/派系名支持模糊)。")
            return
        cur = self.val.get().replace("，", ";").replace(",", ";").split(";")
        cur = [c.strip() for c in cur if c.strip()]
        if self.op.get() in MULTI_OPS:
            picked = open_multi_select(self.frame, f"多选 {self.field.get()}",
                                       self._options, cur)
            if picked is not None:
                if not picked:
                    messagebox.showwarning("提示", "未勾选任何值")
                    return
                self.val.set("; ".join(picked))
        else:
            picked = open_multi_select(self.frame, f"单选 {self.field.get()}",
                                       self._options, cur[:1])
            if picked:
                self.val.set(picked[0])

    def destroy(self):
        pop = SuggestPopup.inst()
        if pop.anchor in (getattr(self, "cb_ref", None), getattr(self, "cb_val", None)):
            pop.hide()
        self.frame.destroy()

    def editor_state(self):
        """保存原始输入，未填完整或暂时非法的条件也能继续编辑。"""
        if self.type == "distance":
            return dict(type="distance", ref=self.ref.get(), min=self.vmin.get(),
                        max=self.vmax.get(), mode=self.mode.get())
        if hasattr(self, 'v_spec') and self.v_spec.get() == self._spec_display:
            self._sync_spec_display()
        return dict(type="field", field=parse_field_label(self.field.get()), op=self.op.get(),
                    value=self.val.get(), **{"class": self.v_class.get(),
                    "rating": self.v_rating.get(), "fresh": self.v_fresh.get(),
                    "discount": self.v_discount.get(), 'module_slot': self.v_slot.get(),
                    'condition_category': self.v_category.get(),
                    'module_spec': self.v_spec.get() if hasattr(self, 'v_spec') else ''})

    def to_cond(self):
        if self.type == "distance":
            def num(s):
                s = s.strip()
                return float(s) if s else None
            if not self.ref.get().strip():
                raise ValueError("距离条件请填写参考星系")
            return {"type": "distance", "ref_system": self.ref.get().strip(),
                    "min_ly": num(self.vmin.get()), "max_ly": num(self.vmax.get()),
                    "mode": "inside" if self.mode.get() == "范围内" else "outside"}
        f = parse_field_label(self.field.get().strip())
        if f == 'modules':
            self._commit_spec()
        op_label = self.op.get()
        op = OP_MAP[op_label]
        raw = self.val.get().strip().replace("，", ";").replace(",", ";")

        def split_list(s):
            return [x.strip() for x in s.replace("，", ";").replace(",", ";").split(";")
                    if x.strip()]

        def module_spec(d):
            if f == 'modules' and self.v_slot.get() != '不限':
                d['module_slot'] = self.v_slot.get()
            # 模块规格原文透传 (等级如 5/5级, 级别如 A), 引擎统一校验
            if f == "modules" and op in ("in", "=", "contains"):
                rc = split_list(self.v_class.get())
                rr = split_list(self.v_rating.get())
                if rc:
                    d["class"] = rc
                if rr:
                    d["rating"] = rr
            # 船/模块集成新鲜度 (卖X且数据N天内新)
            if f in FRESH_FIELDS_ROWS and op in ("in", "=", "contains"):
                days = fresh_opt_days(self.v_fresh.get())
                if days:
                    d["fresh_days"] = days
                if self.kind == 'stations' and self.v_discount.get() == '是':
                    d['discounted'] = True
            return d

        if op in ("true", "false"):
            return {"type": "field", "field": f, "op": op}
        if op in ("in", "not in"):
            vals = [v.strip() for v in raw.split(";") if v.strip()]
            if not vals:
                raise ValueError(f"{f}: 请下拉选择或输入至少一个值, 多个用 ; 分隔")
            return module_spec({"type": "field", "field": f, "op": op, "values": vals})
        if op in ("=", "!=", "contains"):
            if not raw:
                raise ValueError(f"{f}: 请下拉选择或输入内容")
            return module_spec({"type": "field", "field": f, "op": op,
                                "text": raw.split(";")[0].strip()})
        if op in ("<", "<=", ">", ">="):
            if not raw:
                raise ValueError(f"{f}: 请填写数字")
            value = raw.split(";")[0]
            return {"type": "field", "field": f, "op": op,
                    "text": value if f in eng.TIMESTAMP_KEYS else float(value)}
        if op in ("between", "outside"):
            s = raw.replace("～", "~")
            if "~" not in s and "-" in s and f not in eng.TIMESTAMP_KEYS:
                s = s.replace("-", "~", 1)
            if "~" not in s:
                if f in eng.TIMESTAMP_KEYS and "-" not in s:
                    a, b = s, ""  # 时间快捷值 (如近7天) 默认只封下限
                else:
                    raise ValueError(f"{f}: 区间格式为 最小~最大, 如 0~1000, 空一边表示不封口")
            else:
                a, b = s.split("~", 1)
            def num(x):
                x = x.strip()
                return (x if f in eng.TIMESTAMP_KEYS else float(x)) if x else None
            return {"type": "field", "field": f, "op": op,
                    "min": num(a), "max": num(b)}
        raise ValueError(f"未知操作: {op_label}")


class App:
    def __init__(self, root):
        self._post = ui_dispatcher(root)
        self.root = root
        self.localizer = Localizer(root)
        self.appearance_manager = Appearance(root)
        self.localizer.register(lambda: root.title(
            f'{self.localizer.tr("Elite 星系/空间站全条件筛选器")} — v{PROJECT_VERSION}'))
        root.geometry("1320x840")
        self.rows = []
        self.results = []
        self._tool_states = {}
        self._tool_collectors = {}
        self._last_session_state = None
        self._closing = False

        header = ttk.Frame(root, padding=(12, 12, 12, 10))
        header.pack(fill='x')
        brand = ttk.Frame(header)
        brand.pack(side='left')
        ttk.Label(brand, text='Elite Dangerous Filter', style='Title.TLabel').pack(anchor='w')
        ttk.Label(brand, text='星系、空间站与顺路工具', style='Muted.TLabel').pack(anchor='w')
        preferences = ttk.Frame(header)
        preferences.pack(side='right')
        ttk.Label(preferences, text='外观').pack(side='left', padx=(0, 6))
        self.appearance = tk.StringVar(value=MODES['system'])
        self.appearance_box = ttk.Combobox(preferences, textvariable=self.appearance,
                                          values=list(MODES.values()), state='readonly', width=12)
        self.appearance_box.pack(side='left', padx=(0, 12))
        self.appearance_box.bind('<<ComboboxSelected>>', self._appearance_selected)
        ttk.Label(preferences, text='语言 / Language').pack(side='left', padx=(0, 6))
        self.language = tk.StringVar(value='中文')
        language_box = ttk.Combobox(preferences, textvariable=self.language,
                                    values=['中文', 'English'], state='readonly', width=10)
        language_box.pack(side='left')
        language_box.bind('<<ComboboxSelected>>', lambda e: self.set_language(
            'en' if self.language.get() == 'English' else 'zh'))

        top = ttk.Frame(root, padding=(12, 6, 12, 4))
        top.pack(fill="x")
        ttk.Label(top, text="类型").pack(side="left")
        self.kind = tk.StringVar(value="stations")
        self.cb_kind = ttk.Combobox(top, textvariable=self.kind, width=10,
                                    values=["stations", "systems"], state="readonly")
        self.cb_kind.pack(side="left", padx=4)
        self.cb_kind.bind("<<ComboboxSelected>>", lambda e: self.refresh_fields())
        ttk.Label(top, text="要几条").pack(side="left", padx=(8, 0))
        self.want = tk.StringVar(value="200")
        ttk.Entry(top, textvariable=self.want, width=6).pack(side="left")
        ttk.Label(top, text="最多翻页").pack(side="left", padx=(8, 0))
        self.maxpages = tk.StringVar(value="25")
        ttk.Entry(top, textvariable=self.maxpages, width=4).pack(side="left")
        top = ttk.Frame(root, padding=(6, 2))
        top.pack(fill="x")
        ttk.Button(top, text="+ 普通条件", command=self.add_field).pack(side="left", padx=4)
        ttk.Button(top, text="+ 距离条件", command=self.add_distance).pack(side="left")
        ttk.Button(top, text="清空条件", command=self.clear).pack(side="left", padx=4)
        ttk.Button(top, text="保存条件", command=self.save).pack(side="left")
        ttk.Button(top, text="读取条件", command=self.load).pack(side="left", padx=4)
        self.btn_run = ttk.Button(top, text="运行搜索", command=self.run, style='Accent.TButton')
        self.btn_run.pack(side="left")
        self.btn_stop = ttk.Button(top, text="停止", command=self.stop_search,
                                   state="disabled")
        self.btn_stop.pack(side="left", padx=4)
        ttk.Button(top, text="诊断", command=self.diagnose).pack(side="left")
        ttk.Button(top, text="导出CSV", command=self.export).pack(side="left", padx=4)

        details_bar = ttk.Frame(root, padding=(6, 2))
        details_bar.pack(fill='x')
        ttk.Button(details_bar, text='+ 天体／最近有人条件', command=self.add_system_details).pack(side='left', padx=4)
        ttk.Label(details_bar, text='星系模式：数量用普通条件；天体组和最近有人距离用详细条件。',
                  style='Muted.TLabel').pack(side='left', padx=4)

        extra = ttk.Frame(root, padding=(6, 0, 6, 6))
        extra.pack(fill="x")
        ttk.Label(extra, text="额外功能：", style='Muted.TLabel').pack(side="left")
        ttk.Button(extra, text="两系中点", command=self.midpoint_window).pack(side="left")
        ttk.Button(extra, text="航母车位", command=self.carrier_parking_window).pack(side="left", padx=4)
        ttk.Button(extra, text="稀有商品目标查找器", command=self.rare_goods_window).pack(side="left", padx=4)
        ttk.Button(extra, text="海盗任务查找器", command=self.pve_window).pack(side="left", padx=4)
        ttk.Button(extra, text="殖民候选星系查找器", command=self.colonisation_window).pack(side="left", padx=4)
        route_bar = ttk.Frame(root, padding=(6, 0, 6, 4))
        route_bar.pack(fill='x')
        ttk.Button(route_bar, text='中子星规划器（独立项目）', command=self.neutron_planner_project).pack(side='left', padx=4)
        ttk.Button(route_bar, text='工程师途中采购', command=self.engineer_shopping_window).pack(side='left', padx=4)

        self.hint_var = tk.StringVar(
            value="第三格可下拉/打字联想/点“选值…”多选 (选项≤30个直接下拉)。船/模块名打字联想+自动纠错，行内自带新鲜度选择。")
        ttk.Label(root, textvariable=self.hint_var, style='Muted.TLabel').pack(fill="x", padx=6)

        body = ttk.Frame(root)
        body.pack(fill="both", expand=True, padx=6)
        self.canvas = tk.Canvas(body, height=220)
        vsb = ttk.Scrollbar(body, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=vsb.set)
        self.inner = ttk.Frame(self.canvas)
        self.inner.bind("<Configure>", lambda e: self.canvas.configure(
            scrollregion=self.canvas.bbox("all")))
        self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        self.status = tk.StringVar(value="就绪")
        ttk.Label(root, textvariable=self.status).pack(fill="x", padx=6)
        progfrm = ttk.Frame(root)
        progfrm.pack(fill="x", padx=6, pady=(0, 2))
        self.prog = ttk.Progressbar(progfrm, mode="determinate", maximum=100, value=0)
        self.prog.pack(side="left", fill="x", expand=True)
        self.prog_pct = tk.StringVar(value="")
        ttk.Label(progfrm, textvariable=self.prog_pct, width=8).pack(side="left", padx=(4, 0))

        result_frame = ttk.Frame(root)
        result_frame.pack(fill='both', expand=True, padx=6, pady=4)
        self.tree = ttk.Treeview(result_frame, columns=('name', 'system'), show="headings", height=16)
        for c, w, t in [("name", 220, "名称"), ("system", 180, "星系")]:
            self.tree.heading(c, text=t)
            self.tree.column(c, width=w)
        self.tree.grid(row=0, column=0, sticky='nsew')
        vertical = ttk.Scrollbar(result_frame, orient='vertical', command=self.tree.yview)
        vertical.grid(row=0, column=1, sticky='ns')
        horizontal = ttk.Scrollbar(result_frame, orient='horizontal', command=self.tree.xview)
        horizontal.grid(row=1, column=0, sticky='ew')
        self.tree.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        result_frame.rowconfigure(0, weight=1)
        result_frame.columnconfigure(0, weight=1)
        self.localizer.register(self.render_main_results)
        copy_bar = ttk.Frame(root, padding=(6, 0, 6, 4))
        copy_bar.pack(side='bottom', fill='x', before=body)
        ttk.Button(copy_bar, text='复制名称', command=lambda: copy_result(root, self.tree, 'name')).pack(side='left')
        ttk.Button(copy_bar, text='复制星系名', command=self.copy_result_system).pack(side='left', padx=6)

        # 后台预热常见字段候选值
        fo.prefetch_common("stations", ["allegiance", "government", "primary_economy",
                                        "type", "services", "material_trader",
                                        "system_power_state"])
        fo.prefetch_common("systems", ["allegiance", "primary_economy", "security", "power"])
        # 恢复上次关闭时的条件; 没有则从空开始
        self.restore_session()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.root.after(1500, self._autosave_session)

    def copy_result_system(self):
        def system_name(item):
            # View order can change independently of self.results.
            column = 'system' if 'system' in self.tree['columns'] else 'name'
            return self.tree.set(item, column)
        return copy_result(self.root, self.tree, getter=system_name)

    def refresh_fields(self):
        self.rows = [r for r in self.rows if r.frame.winfo_exists()]
        for r in self.rows:
            r.set_fields(self.kind.get())
            r.refresh_options()

    def add_field(self):
        self.rows.append(Row(self.inner, self.kind.get(), "field"))
        self.rows[-1].frame.winfo_toplevel().update_idletasks()

    def add_distance(self):
        self.rows.append(Row(self.inner, self.kind.get(), "distance"))

    def add_system_details(self):
        if self.kind.get() != 'systems':
            messagebox.showinfo('提示', '请先切换为星系查询', parent=self.root)
            return
        from main_system_gui import DetailsRow
        row = DetailsRow(self.inner, self.kind.get())
        self.rows.append(row)
        return row.open_editor()

    def clear(self):
        for r in self.rows:
            r.destroy()
        self.rows = []

    def collect(self):
        conds = []
        for r in self.rows:
            if r.frame.winfo_exists():
                conds.append(r.to_cond())
        self.rows = [r for r in self.rows if r.frame.winfo_exists()]
        if not conds:
            raise ValueError("请先添加至少一个条件")
        return conds

    def save(self):
        try:
            conds = self.collect()
        except ValueError as e:
            messagebox.showwarning("提示", str(e))
            return
        p = filedialog.asksaveasfilename(defaultextension=".json",
                                         filetypes=[("JSON", "*.json")])
        if p:
            with open(p, "w", encoding="utf-8") as f:
                json.dump({"kind": self.kind.get(), "conditions": conds},
                          f, ensure_ascii=False, indent=1)
            self.status.set(f"已保存 {p}")

    def _append_cond(self, c):
        """按一条条件字典建行 (读取文件/恢复会话共用), 条目损坏则跳过。"""
        if c.get('type') == 'system_details':
            from main_system_gui import DetailsRow
            row = DetailsRow(self.inner, self.kind.get())
            row.apply_condition(c)
            self.rows.append(row)
            return
        if c.get("type") == "distance":
            r = Row(self.inner, self.kind.get(), "distance")
            r.ref.set(str(c.get("ref_system") or "Sol"))
            r.vmin.set("" if c.get("min_ly") is None else str(c["min_ly"]))
            r.vmax.set("" if c.get("max_ly") is None else str(c["max_ly"]))
            r.mode.set("范围内" if c.get("mode", "inside") == "inside" else "范围外")
            self.rows.append(r)
            return
        if not c.get("field") or not c.get("op"):
            return
        r = Row(self.inner, self.kind.get(), "field")
        r.field.set(field_label(self.kind.get(), c["field"]))
        inv = {v: k for k, v in OP_MAP.items()}
        r.op.set(inv.get(c["op"], "属于其一"))
        if c["op"] in ("in", "not in"):
            r.val.set("; ".join(str(v) for v in c.get("values", [])))
        elif c["op"] in ("between", "outside"):
            a = "" if c.get("min") is None else str(c["min"])
            b = "" if c.get("max") is None else str(c["max"])
            r.val.set(f"{a}~{b}")
        elif c["op"] not in ("true", "false"):
            r.val.set(str(c.get("text", "")))
        if c.get("field") == "modules":
            r.v_class.set("; ".join(str(v) for v in c.get("class", [])))
            r.v_rating.set("; ".join(str(v) for v in c.get("rating", [])))
            from module_slots import SLOT_GROUPS
            r.v_slot.set(c.get('module_slot') if c.get('module_slot') in SLOT_GROUPS else '不限')
        if c.get("field") in FRESH_FIELDS_ROWS and c.get("fresh_days"):
            try:
                fd = int(c["fresh_days"])
            except (TypeError, ValueError):
                fd = None
            inv_fresh = {v: k for k, v in FRESH_DAYS.items()}
            r.v_fresh.set(inv_fresh.get(fd, f"近{fd}天" if fd else "不限"))
        if c.get('field') in FRESH_FIELDS_ROWS and isinstance(c.get('discounted'), bool):
            r.v_discount.set('是' if c['discounted'] else '不限')
        r.refresh_options()
        self.rows.append(r)

    def _apply_state(self, d):
        if hasattr(self, "localizer"):
            self.set_language(d.get("language", self.localizer.language))
        if hasattr(self, 'appearance_manager') and 'appearance' in d:
            self.set_appearance(d['appearance'])
        self.clear()
        if d.get("kind") in ("stations", "systems"):
            self.kind.set(d["kind"])
        if isinstance(d.get("rows"), list):
            for saved in d["rows"]:
                if not isinstance(saved, dict) or saved.get("type") not in ("field", "distance", 'system_details'):
                    continue
                if saved['type'] == 'system_details':
                    from main_system_gui import DetailsRow
                    self.rows.append(DetailsRow(self.inner, self.kind.get(), saved))
                    continue
                r = Row(self.inner, self.kind.get(), saved["type"])
                if saved["type"] == "distance":
                    for variable, key in ((r.ref, "ref"), (r.vmin, "min"),
                                          (r.vmax, "max"), (r.mode, "mode")):
                        if isinstance(saved.get(key), str):
                            variable.set(saved[key])
                else:
                    from field_categories import available_groups
                    fields = STATION_FIELDS if self.kind.get() == 'stations' else SYSTEM_FIELDS
                    category = saved.get('condition_category', '不限')
                    if category in available_groups(fields):
                        r.v_category.set(category)
                        r.set_fields(self.kind.get())
                    r.field.set(field_label(self.kind.get(), str(saved.get("field") or "name")))
                    for variable, key in ((r.op, "op"), (r.val, "value"), (r.v_class, "class"),
                                          (r.v_rating, "rating"), (r.v_fresh, "fresh"),
                                          (r.v_discount, 'discount'), (r.v_slot, 'module_slot')):
                        if isinstance(saved.get(key), str):
                            variable.set(saved[key])
                    r.refresh_options()
                    if isinstance(saved.get('module_spec'), str) and hasattr(r, 'v_spec'):
                        r.v_spec.set(saved['module_spec'])
                    if r.v_discount.get() not in ('不限', '是'):
                        r.v_discount.set('不限')
                self.rows.append(r)
        else:
            for c in d.get("conditions", []):
                if isinstance(c, dict):
                    self._append_cond(c)
        if isinstance(d.get("tools"), dict):
            self._tool_states.update({key: value for key, value in d["tools"].items()
                                      if isinstance(value, dict)})
        if d.get("want") is not None:
            self.want.set(str(d["want"]))
        if d.get("maxpages") is not None:
            self.maxpages.set(str(d["maxpages"]))

    def _state_dict(self):
        try:
            conds = self.collect()
        except (ValueError, KeyError):
            # conditions保留旧格式；完整编辑状态另存rows，不丢弃草稿行。
            conds = [c for r in self.rows if r.frame.winfo_exists()
                     for c in [self._try_cond(r)] if c is not None]
        for key, collector in self._tool_collectors.items():
            self._tool_states[key] = collector()
        return {"kind": self.kind.get(), "conditions": conds,
                "want": self.want.get(), "maxpages": self.maxpages.get(),
                "rows": [r.editor_state() for r in self.rows if r.frame.winfo_exists()],
                "tools": dict(self._tool_states),
                "language": self.localizer.language if hasattr(self, "localizer") else "zh",
                "appearance": self.appearance_manager.mode if hasattr(self, 'appearance_manager') else 'system'}

    def set_appearance(self, mode):
        self.appearance_manager.set_mode(mode)
        self.appearance.set(MODES[self.appearance_manager.mode])

    def _appearance_selected(self, event=None):
        mode = next((key for key, label in MODES.items() if label == self.appearance.get()), 'system')
        self.set_appearance(mode)
        self.save_session()

    def set_language(self, language):
        if language not in ("zh", "en"):
            language = "zh"
        self.language.set("English" if language == "en" else "中文")
        self.localizer.set_language(language)

    def main_result_table(self):
        from main_csv import export_table
        return export_table(self.results, getattr(self, '_result_kind', self.kind.get()),
                            getattr(self, '_result_conditions', []),
                            self.localizer.language, self.localizer.tr)

    def render_main_results(self):
        if not hasattr(self, '_result_conditions') or not hasattr(self, 'tree'):
            return
        headers, records = self.main_result_table()
        self.tree.delete(*self.tree.get_children())
        keys = ['name'] + [f'value_{i}' for i in range(1, len(headers))]
        if getattr(self, '_result_kind', '') == 'stations' and len(keys) > 1:
            keys[1] = 'system'
        self.tree.set_columns(keys)
        for column, title in zip(keys, headers):
            self.tree.heading(column, text=title)
            self.tree.column(column, width=220 if column in ('name', 'system') else 180,
                             minwidth=80, stretch=False)
        for values in records:
            self.tree.insert('', 'end', values=values)

    def bind_tool_state(self, key, window, variables, before_collect=None):
        """统一保存辅助窗口；关子窗口和关主窗口都能保存当前参数。"""
        saved = self._tool_states.get(key, {})
        for name, variable in variables.items():
            value = saved.get(name)
            if isinstance(variable, tk.BooleanVar):
                if isinstance(value, bool):
                    variable.set(value)
            elif isinstance(value, str):
                variable.set(value)
        def collector():
            if before_collect is not None:
                before_collect()
            return {name: variable.get() for name, variable in variables.items()}
        self._tool_collectors[key] = collector
        window.session_variables = variables

        def destroyed(event):
            if event.widget is not window or self._closing:
                return
            self._tool_states[key] = collector()
            if self._tool_collectors.get(key) is collector:
                del self._tool_collectors[key]
            self.save_session()

        window.bind("<Destroy>", destroyed, add="+")

    @staticmethod
    def _try_cond(r):
        try:
            return r.to_cond()
        except (ValueError, AttributeError, TypeError, KeyError, tk.TclError):
            return None

    def save_session(self):
        try:
            state = self._state_dict()
            if state != self._last_session_state or not os.path.exists(SESSION_FILE):
                session_store.save(SESSION_FILE, state)
                self._last_session_state = state
            return True
        except (OSError, ValueError, tk.TclError) as exc:
            self.status.set(f"会话保存失败：{exc}")
            return False

    def _autosave_session(self):
        if not self._closing:
            self.save_session()
            self.root.after(1500, self._autosave_session)

    def restore_session(self):
        d = session_store.load(SESSION_FILE)
        if d:
            self._apply_state(d)

    def on_close(self):
        if not self.save_session():
            messagebox.showerror("会话保存失败", f"未关闭程序，请检查目录权限后重试。\n{SESSION_FILE}", parent=self.root)
            return
        self._closing = True
        fo.save_module_specs()
        self.root.destroy()

    def load(self):
        p = filedialog.askopenfilename(filetypes=[("JSON", "*.json")])
        if not p:
            return
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
        self._apply_state(d)

    def run(self):
        try:
            conds = self.collect()
            want = max(1, min(2000, int(self.want.get())))
            maxpages = max(1, min(50, int(self.maxpages.get())))
        except ValueError as e:
            messagebox.showwarning("条件有误", str(e))
            return
        kind = self.kind.get()
        try:
            p0 = eng.build_server_payload(kind, conds)
            blind = not p0["filters"] and "reference_system" not in p0
        except eng.Contradiction as ce:
            messagebox.showinfo("无需检索", str(ce) + "\n(条件自相矛盾，一次请求都没发)")
            return
        except ValueError as exc:
            messagebox.showwarning("条件有误", str(exc))
            return
        if blind and not messagebox.askyesno(
                "确认", "没有任何条件能推给服务器，将逐页硬扫全库\n(慢，且翻页上限内未必扫全)，继续吗？"):
            return
        self._stop = threading.Event()
        self.btn_run["state"] = "disabled"
        self.btn_stop["state"] = "normal"
        self.status.set("查询中...")
        self.prog.stop()
        self.prog["mode"] = "indeterminate"
        self.prog.start(80)
        self.prog_pct.set("准备中")
        self.results = []
        self.tree.delete(*self.tree.get_children())
        self._result_conditions = conds
        self._result_kind = kind

        def work():
            try:
                corr = []
                notes = []
                rows, total, scanned = eng.search(
                    kind, conds, want=want, max_pages=maxpages,
                    progress=lambda msg, info=None: self._post(
                        self.root, self._apply_progress, msg, info or {}),
                    corrections=corr,
                    stop=self._stop, notes=notes)
                self.results = rows
                # 反哺规格学习库: 结果行里的在售条目自带 (name, class, rating)
                for r in rows:
                    fo.learn_module_specs(r.get("modules"))
                fo.save_module_specs()
                # 把纠正应用回界面条件 (距离参考点 + 船/模块值段落), 展示用纠正后的值
                for old, new in corr:
                    for c in conds:
                        if c.get("type") == "distance":
                            if c.get("ref_system") == old:
                                c["ref_system"] = new
                        elif c.get("op") in ("in", "not in") and "values" in c:
                            c["values"] = [new if str(v).casefold() == old.casefold() else v
                                           for v in c["values"]]
                        elif isinstance(c.get("text"), str) and c["text"].casefold() == old.casefold():
                            c["text"] = new
                # 展示用归一化副本 (规格解析为整数/大写, 与引擎口径一致)
                try:
                    dconds = eng.normalize_conditions(kind, conds)
                except (ValueError, eng.Contradiction):
                    dconds = conds

                def show():
                    for old, new in corr:
                        for rr in self.rows:
                            if not rr.frame.winfo_exists():
                                continue
                            if (getattr(rr, "type", "") == "distance"
                                    and rr.ref.get().strip() == old):
                                rr.ref.set(new)
                                rr.ref_info.set(f"已纠正为 {new}")
                                rr.lbl_ref["foreground"] = "green"
                            elif (getattr(rr, "type", "") == "field"
                                    and parse_field_label(rr.field.get()) in AUTOCORRECT_FIELDS):
                                parts = rr.val.get().replace("，", ";").split(";")
                                if any(p.strip().casefold() == old.casefold() for p in parts):
                                    rr.val.set("; ".join(
                                        new if p.strip().casefold() == old.casefold() else p.strip()
                                        for p in parts if p.strip()))
                    self._result_conditions = dconds
                    self.render_main_results()
                    msg = f"服务器候选计数 {total:,}, 已复核 {scanned:,} 条, 命中 {len(rows):,} 条"
                    if corr:
                        msg += "；" + "、".join(f"'{a}'→'{b}'" for a, b in corr) + "已自动纠正"
                    if notes:
                        msg += "；" + "、".join(notes)
                    self.status.set(msg)
                    self.btn_run["state"] = "normal"
                    self.btn_stop["state"] = "disabled"
                    self.prog.stop()
                    self.prog["mode"] = "determinate"
                    if any("已达到所需结果数" in n or "候选分页已取完" in n for n in notes):
                        self.prog["value"] = 100
                        self.prog_pct.set("完成")
                    elif any("已手动停止" in n for n in notes):
                        self.prog_pct.set("已停止")
                    else:
                        self.prog_pct.set("未完成")
                    if hasattr(self, '_search_progress'):
                        self._search_progress.finish(any('候选分页已取完' in n or '已达到所需结果数' in n for n in notes))
                self._post(self.root, show)
            except Exception as e:
                self._post(self.root, lambda error=str(e): (
                    messagebox.showerror("查询失败", error),
                    self.status.set("失败"),
                    self.prog.stop(),
                    self.prog.configure(mode="determinate"),
                    self.prog_pct.set("失败"),
                    self._search_progress.finish(False) if hasattr(self, '_search_progress') else None,
                    self.btn_run.__setitem__("state", "normal"),
                    self.btn_stop.__setitem__("state", "disabled")))

        threading.Thread(target=work, daemon=True).start()

    def _apply_progress(self, msg, info):
        if not hasattr(self, '_search_progress'):
            self._search_progress = SearchProgress(self.prog, self.prog_pct, self.localizer)
        self.status.set(msg)
        self._search_progress.update(msg, info)

    def stop_search(self):
        if getattr(self, "_stop", None):
            self._stop.set()
            self.status.set("正在停止...")
            self.prog_pct.set("停止中")

    def diagnose(self):
        try:
            conds = self.collect()
        except ValueError as e:
            messagebox.showwarning("条件有误", str(e))
            return
        kind = self.kind.get()
        self.status.set("诊断中: 取前3页样本统计各条件通过率...")
        self.prog.stop()
        self.prog["mode"] = "indeterminate"
        self.prog.start(80)
        self.prog_pct.set("诊断中")

        def work():
            try:
                stats, n = eng.diagnose(kind, conds, pages=3)
                lines = [f"样本 {n} 条 (服务器前3页候选):"]
                for desc, hit, _ in stats:
                    pct = hit * 100.0 / n if n else 0
                    flag = "  <-- 最严, 优先放宽它" if hit == 0 else ""
                    lines.append(f"{pct:5.1f}% 通过 ({hit}/{n})  {desc}{flag}")
                lines.append("")
                lines.append("通过率仅针对这些候选样本；0% 不代表全库无结果。多距离组合注意两圈是否有交集。")
                self._post(self.root, lambda: (
                    messagebox.showinfo("诊断", "\n".join(lines)),
                    self.status.set("诊断完成"),
                    self.prog.stop(),
                    self.prog.configure(mode="determinate"),
                    self.prog_pct.set("")))
            except eng.Contradiction as ce:
                self._post(self.root, lambda error=str(ce): (
                    messagebox.showinfo("诊断", error),
                    self.status.set("诊断完成"),
                    self.prog.stop(),
                    self.prog.configure(mode="determinate"),
                    self.prog_pct.set("")))
            except Exception as e:
                self._post(self.root, lambda error=str(e): (
                    messagebox.showerror("诊断失败", error),
                    self.status.set("失败"),
                    self.prog.stop(),
                    self.prog.configure(mode="determinate"),
                    self.prog_pct.set("失败")))

        threading.Thread(target=work, daemon=True).start()

    def neutron_planner_project(self):
        import webbrowser
        return webbrowser.open('https://github.com/kxdxzr/Elite_dangerous_Neutron_Planner')

    def rare_goods_window(self):
        from powerplay_gui import open_window
        open_window(self, data_age)

    def pve_window(self):
        from pve_gui import open_window
        return open_window(self)

    def colonisation_window(self):
        from colonisation_gui import open_window
        return open_window(self)

    def engineer_shopping_window(self):
        from engineer_shopping_gui import open_window
        return open_window(self)

    def carrier_parking_window(self):
        win = Toplevel(self.root)
        win.title("航母车位查找")
        win.geometry("1060x580")
        controls = ttk.Frame(win, padding=8)
        controls.pack(fill="x")
        ttk.Label(controls, text="参考星系").pack(side="left")
        reference = tk.StringVar(value="Sol")
        cb = ttk.Combobox(controls, textvariable=reference, width=24)
        cb.pack(side="left", padx=4)
        attach_system_suggest(cb, reference)
        radius = tk.StringVar(value="30")
        pages = tk.StringVar(value="20")
        for label, variable in (("半径 ly (≤50)", radius), ("最多页数", pages)):
            ttk.Label(controls, text=label).pack(side="left", padx=(8, 0))
            ttk.Entry(controls, textvariable=variable, width=7).pack(side="left", padx=4)
        options = ttk.Frame(win, padding=(8, 0))
        options.pack(fill="x")
        minimum = tk.StringVar(value="")
        maximum = tk.StringVar(value="")
        no_permit = tk.BooleanVar(value=True)
        for label, variable in (("最少航母数", minimum), ("最多航母数", maximum)):
            ttk.Label(options, text=label).pack(side="left", padx=(8, 0))
            ttk.Entry(options, textvariable=variable, width=7).pack(side="left", padx=4)
        ttk.Label(options, text="留空不限，包含边界").pack(side="left")
        ttk.Checkbutton(options, text="只显示确认免许可的星系", variable=no_permit).pack(side="left", padx=8)
        ttk.Label(win, text="按站点类型统计 Spansh 已收录航母，不是实时数量或车位预测。类型数据不完整显示未知；数量筛选不包含未知结果。",
                  wraplength=1020, style='Muted.TLabel').pack(fill="x", padx=8, pady=6)
        status = tk.StringVar(value="输入参考星系后查询；双击结果复制星系名。")
        ttk.Label(win, textvariable=status, wraplength=1020).pack(fill="x", padx=8)
        progressbar = ttk.Progressbar(win, mode='determinate')
        progressbar.pack(fill='x', padx=8)
        progress_text = tk.StringVar(win)
        ttk.Label(win, textvariable=progress_text).pack(fill='x', padx=8)
        tracker = SearchProgress(progressbar, progress_text, self.localizer)
        columns = [("name", 210, "星系"), ("distance", 90, "距离 ly"),
                   ("carriers", 80, "航母数"), ("stations", 90, "站点总数"),
                   ("parking", 250, "统计状态"), ("permit", 80, "许可"),
                   ("age", 110, "星系记录年龄")]
        results_frame = ttk.Frame(win)
        results_frame.pack(fill="both", expand=True, padx=8, pady=6)
        tree = ttk.Treeview(results_frame, columns=[c for c, _, _ in columns], show="headings")
        for column, width, title in columns:
            tree.heading(column, text=title)
            tree.column(column, width=width)
        tree.pack(side="left", fill="both", expand=True)
        scrollbar = ttk.Scrollbar(results_frame, orient="vertical", command=tree.yview)
        scrollbar.pack(side="right", fill="y")
        tree.configure(yscrollcommand=scrollbar.set)
        stop = threading.Event()

        def copy_name(event=None):
            copy_result(win, tree, 'name')

        tree.bind("<Double-1>", copy_name)
        copy_bar = ttk.Frame(win, padding=(8, 0, 8, 6))
        copy_bar.pack(side='bottom', fill='x', before=results_frame)
        ttk.Button(copy_bar, text='复制星系名', command=copy_name).pack(side='left')

        def export_rows():
            if not tree.get_children():
                messagebox.showinfo("提示", "暂无结果", parent=win)
                return
            path = filedialog.asksaveasfilename(parent=win, defaultextension=".csv",
                                                filetypes=[("CSV", "*.csv")])
            if path:
                with open(path, "w", newline="", encoding="utf-8-sig") as f:
                    writer = csv.writer(f)
                    write_csv_provenance(writer, len(columns), self.localizer.language)
                    writer.writerow([self.localizer.tr(title) for _, _, title in columns])
                    writer.writerows([self.localizer.tr(value) for value in tree.item(i, "values")]
                                     for i in tree.get_children())

        def run():
            try:
                name, distance, limit = reference.get().strip(), float(radius.get()), int(pages.get())
                low = int(minimum.get()) if minimum.get().strip() else None
                high = int(maximum.get()) if maximum.get().strip() else None
                if not name or not 0 < distance <= 50 or limit < 1:
                    raise ValueError()
                if any(v is not None and v < 0 for v in (low, high)) or (low is not None and high is not None and low > high):
                    raise ValueError()
            except ValueError:
                messagebox.showwarning("参数错误", "请填参考星系、有效半径和页数；航母数量为非负整数或留空，最少不能大于最多", parent=win)
                return
            exclude = no_permit.get()
            stop.clear()
            button["state"] = "disabled"
            tracker.update()
            tree.delete(*tree.get_children())
            status.set("查询中...")

            def work():
                try:
                    info, rows = eng.carrier_parking_search(
                        name, distance, min_carriers=low, max_carriers=high, exclude_permit=exclude,
                        max_pages=limit, stop=stop,
                        progress=lambda msg, detail=None: self._post(win, lambda: (status.set(msg), tracker.update(msg, detail))))

                    def show():
                        reference.set(info["reference"])
                        tracker.finish(info['complete'])
                        for row in rows:
                            permit = row.get("needs_permit")
                            tree.insert("", "end", tags=(row["_parking_category"],), values=(
                                row.get("name"), format_ly(row["_parking_distance"]),
                                format_population(row["_carrier_count"], "未知"),
                                format_population(row["_station_count"], "未知"),
                                row["_parking_label"], "需许可" if permit else ("免许可" if permit is False else "未知"),
                                data_age(row.get("updated_at"))))
                        state = "范围内分页已取完" if info["complete"] else "检索未完成，当前为部分结果"
                        status.set(f"{info['reference']} 周围 {format_ly(info['radius'])} ly：扫描 {info['scanned']:,} 个星系，显示 {len(rows):,} 个；{state}。航母数量未知 {info['unknown']:,} 个。")
                        button["state"] = "normal"

                    self._post(win, show)
                except Exception as exc:
                    def failed(error=str(exc)):
                        status.set("查询失败")
                        tracker.finish(False)
                        button["state"] = "normal"
                        messagebox.showerror("查询失败", error, parent=win)
                    self._post(win, failed)

            threading.Thread(target=work, daemon=True).start()

        button = ttk.Button(controls, text="查找车位", command=run)
        button.pack(side="left", padx=6)
        ttk.Button(controls, text="停止", command=stop.set).pack(side="left")
        ttk.Button(controls, text="导出 CSV", command=export_rows).pack(side="left", padx=6)
        self.bind_tool_state("carrier_parking", win, dict(reference=reference, radius=radius,
                             pages=pages, min_carriers=minimum, max_carriers=maximum, exclude_permit=no_permit))
        def close():
            stop.set()
            win.destroy()
        win.protocol("WM_DELETE_WINDOW", close)

    def midpoint_window(self):
        """两系中点工具: 输入 A、B, 找离中点最近的星系。"""
        win = Toplevel(self.root)
        win.title("两系中点 - 离中点最近的星系")
        win.geometry("780x560")
        frm = ttk.Frame(win, padding=8)
        frm.pack(fill="x")
        ttk.Label(frm, text="A星系").grid(row=0, column=0, sticky="e")
        va = tk.StringVar(value="Sol")
        cba = ttk.Combobox(frm, textvariable=va, width=26)
        cba.grid(row=0, column=1, padx=4, pady=2)
        attach_system_suggest(cba, va)
        ttk.Label(frm, text="B星系").grid(row=0, column=2, sticky="e")
        vb = tk.StringVar(value="Shinrarta Dezhra")
        cbb = ttk.Combobox(frm, textvariable=vb, width=26)
        cbb.grid(row=0, column=3, padx=4, pady=2)
        attach_system_suggest(cbb, vb)
        ttk.Label(frm, text="要几条").grid(row=1, column=0, sticky="e")
        want = tk.StringVar(value="20")
        ttk.Entry(frm, textvariable=want, width=8).grid(row=1, column=1, sticky="w", padx=4)
        pop_only = tk.BooleanVar(value=False)
        no_permit = tk.BooleanVar(value=False)
        ttk.Checkbutton(frm, text="仅有人星系", variable=pop_only).grid(row=1, column=2)
        ttk.Checkbutton(frm, text="排除需许可", variable=no_permit).grid(row=1, column=3, sticky="w")
        btn = ttk.Button(frm, text="查找")
        btn.grid(row=1, column=4, padx=8)
        status = tk.StringVar(value="输入两星系名后点查找 (支持联想, 打错自动纠)。")
        ttk.Label(win, textvariable=status, style='Muted.TLabel').pack(fill="x", padx=8)
        progressbar = ttk.Progressbar(win, mode='determinate')
        progressbar.pack(fill='x', padx=8)
        progress_text = tk.StringVar(win)
        ttk.Label(win, textvariable=progress_text).pack(fill='x', padx=8)
        tracker = SearchProgress(progressbar, progress_text, self.localizer)
        cols = ("name", "dmid", "da", "db", "info")
        tree = ttk.Treeview(win, columns=cols, show="headings", height=18)
        for c, w, t in [("name", 200, "星系"), ("dmid", 90, "距中点ly"),
                        ("da", 90, "距A ly"), ("db", 90, "距B ly"),
                        ("info", 280, "人口/阵营/许可")]:
            tree.heading(c, text=t)
            tree.column(c, width=w)
        tree.pack(fill="both", expand=True, padx=8, pady=4)
        copy_bar = ttk.Frame(win, padding=(8, 0, 8, 6))
        copy_bar.pack(side='bottom', fill='x', before=tree)
        ttk.Button(copy_bar, text='复制星系名', command=lambda: copy_result(win, tree, 'name')).pack(side='left')
        tree.bind('<Double-1>', lambda event: copy_result(win, tree, 'name'))

        def run():
            try:
                n = max(1, min(200, int(want.get())))
            except ValueError:
                messagebox.showwarning("提示", "要几条请填数字", parent=win)
                return
            if not va.get().strip() or not vb.get().strip():
                messagebox.showwarning("提示", "请填写 A、B 星系", parent=win)
                return
            btn["state"] = "disabled"
            tracker.update()
            status.set("查询中...")
            tree.delete(*tree.get_children())
            a, b = va.get(), vb.get()
            populated, exclude = pop_only.get(), no_permit.get()

            def work():
                try:
                    corr = []
                    info, rows = eng.midpoint_search(
                        a, b, want=n,
                        populated_only=populated,
                        exclude_permit=exclude, corrections=corr,
                        progress=lambda msg, detail=None: self._post(win, lambda: (status.set(msg), tracker.update(msg, detail))))

                    def show():
                        for r in rows:
                            permit = "需许可" if r.get("needs_permit") else "免许可"
                            tree.insert("", "end", values=(
                                r.get("name"), format_ly(r.get("_d_mid")),
                                format_ly(r.get("_d_a")), format_ly(r.get("_d_b")),
                                f"pop {format_population(r.get('population'), '?')} | "
                                f"{r.get('allegiance')} | {permit}"))
                        va.set(info["a"])
                        tracker.finish(info.get('complete', False))
                        vb.set(info["b"])
                        msg = (f"{info['a']} ↔ {info['b']} 相距 {format_ly(info['ab'])}ly, "
                                f"中点({', '.join(format_ly(v) for v in info['mid'])}), 找到 {len(rows):,} 条")
                        if corr:
                            msg += "；" + "、".join(f"'{a}'→'{b}'" for a, b in corr) + "已自动纠正"
                        status.set(msg)
                        btn["state"] = "normal"
                    self._post(win, show)
                except Exception as e:
                    self._post(win, lambda error=str(e): (
                        messagebox.showerror("查找失败", error, parent=win),
                        tracker.finish(False),
                        status.set("失败"),
                        btn.__setitem__("state", "normal")))

            threading.Thread(target=work, daemon=True).start()

        btn["command"] = run
        self.bind_tool_state("midpoint", win, dict(a=va, b=vb, want=want,
                             populated_only=pop_only, exclude_permit=no_permit))

    def export(self):
        if not self.results:
            messagebox.showinfo("提示", "暂无结果, 先运行搜索")
            return
        p = filedialog.asksaveasfilename(defaultextension=".csv",
                                         filetypes=[("CSV", "*.csv")])
        if not p:
            return
        headers, records = self.main_result_table()
        with open(p, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            write_csv_provenance(w, len(headers), self.localizer.language)
            w.writerow(headers)
            w.writerows(records)
        self.status.set(f"已导出 {p}")


if __name__ == "__main__":
    if "--session-test" in sys.argv:
        from exe_session_test import run
        index = sys.argv.index("--session-test")
        if index + 2 >= len(sys.argv):
            raise SystemExit("--session-test requires write/read and a JSON report path")
        raise SystemExit(run(sys.modules[__name__], sys.argv[index + 1], sys.argv[index + 2]))
    if "--smoke-test" in sys.argv:
        from exe_smoke_test import run
        index = sys.argv.index("--smoke-test")
        if index + 1 >= len(sys.argv):
            raise SystemExit("--smoke-test requires a JSON report path")
        raise SystemExit(run(sys.modules[__name__], sys.argv[index + 1]))
    root = tk.Tk()
    App(root)
    root.mainloop()
