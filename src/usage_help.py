"""On-demand, localized usage notes without crowding the search form."""
from localized_tk import ttk, Toplevel
from form_scroll import settings_form


def usage_help(parent, paragraphs, *, inline=False):
    """Return a help button; repeated clicks reuse its non-modal window."""
    holder = parent if inline else ttk.Frame(parent, padding=(8, 2))
    if not inline:
        holder.pack(fill='x')
    window = None

    def open_help():
        nonlocal window
        if window is not None and window.winfo_exists():
            window.deiconify()
            window.lift()
            return window
        window = Toplevel(parent)
        window.title('使用说明')
        window.geometry('820x520')
        window.transient(parent.winfo_toplevel())
        body = settings_form(window, height=440)
        labels = []
        for text in paragraphs:
            label = ttk.Label(body, text=text, wraplength=760, justify='left')
            label.pack(fill='x', padx=12, pady=8)
            labels.append(label)

        def resize(event):
            for label in labels:
                label.configure(wraplength=max(120, event.width - 24))

        body.bind('<Configure>', resize, add='+')
        ttk.Button(window, text='关闭', command=window.destroy).pack(pady=6)
        window.help_labels = labels
        return window

    button = ttk.Button(holder, text='使用说明', command=open_help)
    button.pack(side='right', padx=4)
    button.open_help = open_help
    return button
