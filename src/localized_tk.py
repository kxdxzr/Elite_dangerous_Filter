"""Localized ttk adapters: display strings are separate from canonical model variables.

No tkinter monkey patches. Only this application's imported widgets are adapted.
"""
import tkinter as tk
from tkinter import ttk as base, messagebox as dialogs
from types import SimpleNamespace


def manager(widget):
    return getattr(widget._root(), '_localizer', None)


class TextMixin:
    def __init__(self, master=None, **kw):
        self._value_labels = kw.pop('value_labels', {})
        self._raw_text = kw.get('text')
        self._raw_values = tuple(kw.get('values', ()))
        self._raw_width = kw.get('width')
        self._model = kw.get('textvariable')
        self._display = None
        self._busy = False
        super().__init__(master, **kw)
        self._manager = manager(self)
        if self._manager:
            if isinstance(self._model, tk.StringVar):
                self._display = tk.StringVar(self)
                super().configure(textvariable=self._display)
                self._model_trace = self._model.trace_add('write', self._model_changed)
                self._display_trace = self._display.trace_add('write', self._display_changed)
            self._manager.register(self._render)
            self.bind('<Destroy>', self._cleanup, add='+')

    def _cleanup(self, event):
        if event.widget is self:
            self._manager.callbacks.discard(self._render)
            if self._display is not None:
                self._model.trace_remove('write', self._model_trace)
                self._display.trace_remove('write', self._display_trace)

    def _model_changed(self, *args):
        if not self._busy:
            self._render()

    def _display_changed(self, *args):
        if self._busy or not isinstance(self, base.Combobox):
            return
        value = self._display.get()
        inverse = {self._manager.tr(self._value_labels.get(v, v)): v for v in self._raw_values}
        self._busy = True
        try:
            self._model.set(inverse.get(value, value))
        finally:
            self._busy = False

    def _render(self):
        if not self.winfo_exists():
            return
        if self._raw_text is not None:
            super().configure(text=self._manager.tr(self._raw_text))
        if isinstance(self, base.Combobox):
            values = [self._manager.tr(self._value_labels.get(v, v)) for v in self._raw_values]
            super().configure(values=values)
            if self._raw_width is not None:
                changed = any(str(a) != str(b) for a, b in zip(self._raw_values, values))
                width = max(self._raw_width, min(42, max((len(str(v)) + 2 for v in values), default=0))) if changed else self._raw_width
                super().configure(width=width)
        if self._display is not None:
            self._busy = True
            try:
                value = self._model.get()
                self._display.set(self._manager.tr(self._value_labels.get(value, value)))
            finally:
                self._busy = False

    def configure(self, cnf=None, **kw):
        if isinstance(cnf, dict):
            kw = dict(cnf, **kw)
            cnf = None
        if 'text' in kw:
            self._raw_text = kw['text']
            if getattr(self, '_manager', None):
                kw['text'] = self._manager.tr(kw['text'])
        if 'values' in kw:
            self._raw_values = tuple(kw['values'])
            if getattr(self, '_manager', None):
                kw['values'] = [self._manager.tr(self._value_labels.get(v, v)) for v in self._raw_values]
        result = super().configure(cnf, **kw)
        return result

    config = configure


class Combobox(TextMixin, base.Combobox):
    def set(self, value):
        if self._display is not None:
            self._model.set(value)
        else:
            super().set(value)

    def get(self):
        return self._model.get() if self._display is not None else super().get()


class Treeview(base.Treeview):
    def __init__(self, master=None, **kw):
        self._sortable = kw.pop('sortable', True)
        self._sort_column, self._sort_descending, self._sort_after = None, False, None
        self._sort_commands, self._custom_headings = {}, set()
        self._stripe_after = None
        super().__init__(master, **kw)
        self._manager = manager(self)
        self._headings, self._items = {}, {}
        appearance = getattr(self._root(), '_appearance', None)
        if appearance:
            appearance.style_widget(str(self))
        self.bind('<Destroy>', self._cleanup_sort, add='+')
        if self._manager:
            self._manager.register(self._render)
            self.bind('<Destroy>', lambda e: self._manager.callbacks.discard(self._render)
                      if e.widget is self else None, add='+')

    def heading(self, column, option=None, **kw):
        column = str(column)
        if 'command' in kw:
            self._custom_headings.add(column)
        elif kw and self._sortable and column not in self._custom_headings:
            if column not in self._sort_commands:
                self._sort_commands[column] = self.register(lambda column=column: self.sort_by(column))
            kw['command'] = self._sort_commands[column]
        if 'text' in kw:
            self._headings[column] = kw['text']
            kw['text'] = self._heading_title(column, kw['text'])
        return super().heading(column, option, **kw)

    def _heading_title(self, column, text):
        title = self._manager.tr(text) if self._manager else text
        if column == self._sort_column:
            title = f'{title} {"▼" if self._sort_descending else "▲"}'
        return title

    def sort_by(self, column):
        """Toggle view order, preserving item identities, selection and model order."""
        column = str(column)
        if not self._sortable or column not in (*self.cget('columns'), '#0'):
            return
        self._sort_descending = not self._sort_descending if column == self._sort_column else False
        self._sort_column = column
        if self._sort_after is not None:
            self.after_cancel(self._sort_after)
            self._sort_after = None
        self._apply_sort()

    def _apply_sort(self):
        from result_sort import sorted_cells
        self._sort_after = None
        if self._sort_column is None:
            return
        parents = ['']
        while parents:
            parent = parents.pop()
            children = self.get_children(parent)
            values = ((item, self.item(item, 'text') if self._sort_column == '#0' else
                       self.set(item, self._sort_column)) for item in children)
            for index, item in enumerate(sorted_cells(values, self._sort_descending)):
                self.move(item, parent, index)
            parents.extend(children)
        for key, text in self._headings.items():
            super().heading(key, text=self._heading_title(key, text))

    def _queue_sort(self):
        if self._sort_column is not None and self._sort_after is None:
            self._sort_after = self.after_idle(self._apply_sort)

    def _cleanup_sort(self, event):
        if event.widget is self:
            for name in ('_sort_after', '_stripe_after'):
                pending = getattr(self, name)
                if pending is not None:
                    self.after_cancel(pending)
                    setattr(self, name, None)

    def _queue_stripes(self):
        if getattr(self._root(), '_appearance', None) and self._stripe_after is None:
            self._stripe_after = self.after_idle(self._stripe_rows)

    def _stripe_rows(self):
        self._stripe_after = None
        parents = ['']
        while parents:
            children = self.get_children(parents.pop())
            for index, item in enumerate(children):
                tags = tuple(tag for tag in self.item(item, 'tags')
                             if tag not in ('_stripe_even', '_stripe_odd'))
                super().item(item, tags=tags + (('_stripe_odd' if index % 2 else '_stripe_even'),))
            parents.extend(children)

    def move(self, item, parent, index):
        super().move(item, parent, index)
        self._queue_stripes()

    def set_columns(self, columns):
        """Replace a dynamic schema without retaining obsolete localized headers."""
        self._headings.clear()
        self.configure(columns=columns, displaycolumns=columns)
        if self._sort_column not in (*self.cget('columns'), '#0'):
            self._sort_column, self._sort_descending = None, False
        for column in set(self._sort_commands) - set(self.cget('columns')) - {'#0'}:
            self.deletecommand(self._sort_commands.pop(column))
        self._custom_headings.intersection_update((*self.cget('columns'), '#0'))
        self._queue_sort()

    def insert(self, parent, index, iid=None, **kw):
        raw = kw.get('values', ())
        if self._manager:
            kw['values'] = self._display_values(raw)
        item = super().insert(parent, index, iid, **kw)
        self._items[item] = tuple(raw)
        self._queue_sort()
        self._queue_stripes()
        return item

    def _display_values(self, values):
        identifiers = {'name', 'source', 'target', 'system', 'station', 'power',
                       'source_controller', 'target_controller', 'source_power', 'target_power',
                       'neighbour', 'body_matches', 'ring_matches', 'relations'}
        columns = self.cget('columns')
        return [value if (index < len(columns) and columns[index] in identifiers
                          and not (columns[index] == 'source' and value == '无数据')
                          and not (columns[index] in ('source_controller', 'target_controller')
                                   and value == '情况未知')) else self._manager.tr(value)
                for index, value in enumerate(values)]

    def delete(self, *items):
        for item in items:
            self._items.pop(item, None)
        super().delete(*items)
        self._queue_stripes()

    def _render(self):
        for key, text in self._headings.items():
            super().heading(key, text=self._heading_title(key, text))
        for key, values in self._items.items():
            if self.exists(key):
                super().item(key, values=self._display_values(values))
        self._queue_sort()


class Toplevel(tk.Toplevel):
    def __init__(self, master=None, **kw):
        super().__init__(master, **kw)
        self._raw_title = ''
        self._manager = manager(self)
        if self._manager:
            self._manager.register(self._render_title)
            self.bind('<Destroy>', lambda e: self._manager.callbacks.discard(self._render_title)
                      if e.widget is self else None, add='+')

    def _render_title(self):
        super().title(self._manager.tr(self._raw_title))

    def title(self, string=None):
        if string is not None:
            self._raw_title = string
            loc = getattr(self, '_manager', None)
            return super().title(loc.tr(string) if loc else string)
        return super().title()


ttk = SimpleNamespace(**{name: getattr(base, name) for name in dir(base) if not name.startswith('_')})
for _name in ('Label', 'Button', 'Checkbutton', 'Radiobutton', 'LabelFrame'):
    setattr(ttk, _name, type(_name, (TextMixin, getattr(base, _name)), {}))
ttk.Combobox, ttk.Treeview = Combobox, Treeview


def _dialog(name):
    def show(title=None, message=None, **kw):
        root = kw.get('parent') or tk._default_root
        loc = manager(root) if root is not None else None
        return getattr(dialogs, name)(loc.tr(title) if loc else title,
                                    loc.tr(message) if loc else message, **kw)
    return show


messagebox = SimpleNamespace(**{name: _dialog(name) for name in
    ('showinfo', 'showwarning', 'showerror', 'askyesno', 'askokcancel')})
