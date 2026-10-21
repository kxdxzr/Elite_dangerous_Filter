"""A main-window row for reusable planet/ring groups and verified proximity."""
import json
import tkinter as tk

from localized_tk import ttk, Toplevel, manager
from colonisation_gui import GroupEditor
import colonisation_tool as bodies
import system_filters


class DetailsRow:
    type = 'system_details'

    def __init__(self, master, kind, saved=None):
        self.kind, self.editor = kind, None
        self.frame = ttk.Frame(master, padding=4, relief='groove')
        self.frame.pack(fill='x', pady=2)
        self.variables = {key: tk.StringVar(self.frame, value=value) for key, value in {
            'body_groups': '[]', 'ring_groups': '[]', 'body_mode': 'AND', 'ring_mode': 'AND',
            'population_min': '1', 'nearest_min': '', 'nearest_max': ''}.items()}
        for key, value in (saved or {}).get('settings', {}).items():
            if key in self.variables and isinstance(value, str):
                self.variables[key].set(value)
        ttk.Label(self.frame, text='天体／最近有人条件').pack(side='left', padx=3)
        self.button = ttk.Button(self.frame, text='编辑详细条件…', command=self.open_editor)
        self.button.pack(side='left', padx=4)
        self.summary = tk.StringVar(self.frame)
        ttk.Label(self.frame, textvariable=self.summary).pack(side='left', padx=4)
        ttk.Button(self.frame, text='删除', command=self.destroy).pack(side='right')
        self.localizer = manager(self.frame)
        if self.localizer:
            self.localizer.register(self.refresh_options)
        self.traces = [(var, var.trace_add('write', self.refresh_options)) for var in self.variables.values()]
        self.frame.bind('<Destroy>', self.cleanup, add='+')
        self.set_fields(kind)

    def refresh_options(self, *args):
        if not self.frame.winfo_exists():
            return
        counts = []
        for key in ('body_groups', 'ring_groups'):
            try:
                counts.append(len(json.loads(self.variables[key].get())))
            except (ValueError, TypeError):
                counts.append('?')
        v = {key: var.get() for key, var in self.variables.items()}
        from i18n import translate, message, SOURCE_LANGUAGE
        language = self.localizer.language if self.localizer else SOURCE_LANGUAGE
        if self.kind != 'systems':
            self.summary.set(translate('仅用于星系查询', language))
        else:
            self.summary.set(message('details.summary', language, bodies=counts[0], rings=counts[1],
                                     body_mode=v['body_mode'], ring_mode=v['ring_mode'],
                                     minimum=v['nearest_min'] or '—', maximum=v['nearest_max'] or '—',
                                     population=v['population_min']))

    def set_fields(self, kind):
        self.kind = kind
        self.button.configure(state='normal' if kind == 'systems' else 'disabled')
        self.refresh_options()

    def editor_state(self):
        return dict(type=self.type, settings={key: var.get() for key, var in self.variables.items()})

    def apply_condition(self, condition):
        for key, var in self.variables.items():
            if key in condition:
                value = condition[key]
                var.set(json.dumps(value, ensure_ascii=False) if key.endswith('_groups')
                        else '' if value is None else str(value))

    def to_cond(self):
        if self.kind != 'systems':
            raise ValueError('天体／最近有人条件仅用于星系查询')
        values = {key: var.get() for key, var in self.variables.items()}
        for key in ('body_groups', 'ring_groups'):
            values[key] = json.loads(values[key])
        return system_filters.validate(dict(type=self.type, **values))

    def open_editor(self):
        if self.editor is not None and self.editor.winfo_exists():
            self.editor.lift()
            return self.editor
        win = self.editor = Toplevel(self.frame)
        win.title('主界面星系详细条件')
        win.geometry('1250x800')
        ttk.Label(win, text='详细条件与主界面其他行之间为 AND；此处不强制零人口、无站点或免许可。',
                  wraplength=1200).pack(fill='x', padx=8, pady=5)
        nearest = ttk.LabelFrame(win, text='最近有人星系距离（可选）', padding=8)
        nearest.pack(fill='x', padx=8)
        for index, (key, text) in enumerate((('population_min', '附近星系人口大于'),
                                             ('nearest_min', '最近有人星系最小 ly'),
                                             ('nearest_max', '最近有人星系最大 ly'))):
            ttk.Label(nearest, text=text).grid(row=0, column=index, sticky='w', padx=4)
            ttk.Entry(nearest, textvariable=self.variables[key], width=24).grid(row=1, column=index, sticky='ew', padx=4)
            nearest.columnconfigure(index, weight=1)
        from usage_help import usage_help
        win.usage_help = usage_help(win, (
            '距离上下限都留空则不启用；先查最近达标星系，再判断含边界的范围。普通距离行可同时限定搜索区域。',
            '站点、航母和派系数量通过主界面的普通条件字段设置；任务派系数量为非无政府派系估计。',
            'in 多选及 between 范围用 | 分隔；布尔值用 true / false。互绕按共同直接质心和相同周期推定，复杂／缺失关系为未知。',
        ))
        editors = {}

        def changed():
            for key, editor in editors.items():
                self.variables[key].set(json.dumps(editor.snapshot(), ensure_ascii=False))

        for key, title, fields, mode in (
                ('body_groups', '星球条件', bodies.BODY_FIELDS, 'body_mode'),
                ('ring_groups', '独立星环条件', bodies.RING_FIELDS, 'ring_mode')):
            section = ttk.LabelFrame(win, text=title, padding=5)
            section.pack(fill='both', expand=True, padx=8, pady=4)
            try:
                saved = json.loads(self.variables[key].get())
                saved = saved if isinstance(saved, list) else []
            except ValueError:
                saved = []
            editors[key] = GroupEditor(section, fields, self.variables[mode], saved, changed)
        ttk.Button(win, text='关闭', command=win.destroy).pack(pady=5)

        def closed(event):
            if event.widget is win:
                for editor in editors.values():
                    editor.dispose()
                editors.clear()
                self.editor = None
        win.bind('<Destroy>', closed, add='+')
        win.group_editors = editors
        return win

    def destroy(self):
        if self.editor is not None:
            self.editor.destroy()
        self.frame.destroy()

    def cleanup(self, event):
        if event.widget is self.frame:
            for var, trace in self.traces:
                var.trace_remove('write', trace)
            self.traces.clear()
            if self.localizer:
                self.localizer.callbacks.discard(self.refresh_options)
