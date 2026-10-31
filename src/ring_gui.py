"""One main-window ring entry for both search scopes."""
import tkinter as tk
from localized_tk import ttk
import ring_conditions as rings


class RingRow:
    type = 'rings'

    def __init__(self, master, kind, saved=None):
        self.frame = ttk.Frame(master, padding=4, relief='groove')
        self.frame.pack(fill='x', pady=2)
        self.mode = tk.StringVar(self.frame, '不限')
        self.types = {value: tk.BooleanVar(self.frame) for value in rings.TYPES}
        self.scope = ttk.Label(self.frame)
        self.scope.pack(side='left', padx=4)
        ttk.Combobox(self.frame, textvariable=self.mode, values=list(rings.MODES.values()),
                     state='readonly', width=15).pack(side='left', padx=4)
        self.buttons = []
        for value, variable in self.types.items():
            button = ttk.Checkbutton(self.frame, text=value, variable=variable)
            button.pack(side='left', padx=3)
            self.buttons.append(button)
        ttk.Button(self.frame, text='删除', command=self.destroy).pack(side='right')
        self.trace = self.mode.trace_add('write', self.refresh_options)
        self.set_fields(kind)
        if saved:
            self.apply_condition(saved)
        self.refresh_options()

    def set_fields(self, kind):
        self.kind = kind
        self.scope.configure(text='星环条件：站点所在天体' if kind == 'stations' else '星环条件：星系内任一天体')

    def refresh_options(self, *args):
        for button in self.buttons:
            button.configure(state='normal' if self.mode.get() == '指定类型' else 'disabled')

    def apply_condition(self, condition):
        self.mode.set(rings.MODES.get(condition.get('mode'), '不限'))
        for value, variable in self.types.items():
            variable.set(value in condition.get('values', []))

    def editor_state(self):
        return dict(type=self.type, mode=next((k for k, v in rings.MODES.items() if v == self.mode.get()), 'any'),
                    values=[k for k, v in self.types.items() if v.get()])

    def to_cond(self):
        return rings.validate(self.editor_state())

    def destroy(self):
        self.mode.trace_remove('write', self.trace)
        self.frame.destroy()
