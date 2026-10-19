"""Bounded-height settings form: keep search actions and results visible."""
import tkinter as tk
from localized_tk import ttk


def settings_form(window, height=360):
    outer = ttk.Frame(window)
    outer.pack(fill='x')
    canvas = tk.Canvas(outer, height=height, highlightthickness=0)
    scroll = ttk.Scrollbar(outer, orient='vertical', command=canvas.yview)
    scroll.pack(side='right', fill='y')
    canvas.pack(side='left', fill='x', expand=True)
    body = ttk.Frame(canvas)
    item = canvas.create_window((0, 0), window=body, anchor='nw')
    body.bind('<Configure>', lambda event: canvas.configure(scrollregion=canvas.bbox('all')))
    canvas.bind('<Configure>', lambda event: canvas.itemconfigure(item, width=event.width))

    def wheel(event):
        if isinstance(event.widget, (ttk.Combobox, ttk.Treeview)) or not event.delta:
            return
        if (canvas.winfo_rootx() <= event.x_root < canvas.winfo_rootx() + canvas.winfo_width()
                and canvas.winfo_rooty() <= event.y_root < canvas.winfo_rooty() + canvas.winfo_height()):
            canvas.yview_scroll(-1 if event.delta > 0 else 1, 'units')
            return 'break'
    binding = window.bind('<MouseWheel>', wheel, add='+')

    def dispose(event):
        if event.widget is outer:
            try:
                window.unbind('<MouseWheel>', binding)
            except tk.TclError:
                pass
    outer.bind('<Destroy>', dispose, add='+')
    window.settings_canvas = canvas
    return body
