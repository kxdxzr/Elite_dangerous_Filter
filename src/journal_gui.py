"""Shared click-to-fill control. Worker threads only handle files/plain data."""
from pathlib import Path
import queue
import threading
from tkinter import filedialog

from localized_tk import ttk, messagebox, manager, Toplevel
import journal_location


def current_system_button(parent, variable, *, allowed_systems=None, on_filled=None):
    root = parent._root()
    results = queue.Queue()
    state = dict(busy=False, timer=None, tooltip=None, location=None)

    def tr(text):
        localizer = manager(button)
        return localizer.tr(text) if localizer else text

    def choose():
        if state['busy']:
            return
        folder = filedialog.askdirectory(parent=button.winfo_toplevel(),
            title=tr('选择 Journal 日志文件夹'),
            initialdir=getattr(root, '_journal_directory', journal_location.default_directory()))
        if folder:
            root._journal_directory = folder
            start()

    def poll():
        state['timer'] = None
        try:
            location, error = results.get_nowait()
        except queue.Empty:
            state['timer'] = button.after(40, poll)
            return
        state['busy'] = False
        button.configure(state='normal')
        if error:
            messagebox.showerror('无法读取当前星系', tr(error), parent=button.winfo_toplevel())
            return
        if variable.get() != state['original']:
            # Do not overwrite edits made while disk I/O was in progress.
            return
        if allowed_systems is not None:
            canonical = next((name for name in allowed_systems if name.casefold() == location.system.casefold()), None)
            if canonical is None:
                messagebox.showwarning('提示', tr('当前星系不在此工具支持的来源清单中，已保留原选择。'),
                                       parent=button.winfo_toplevel())
                return
            variable.set(canonical)
        else:
            variable.set(location.system)
        state['location'] = location
        if on_filled is not None:
            on_filled(location)

    def start():
        if state['busy']:
            return
        folder = getattr(root, '_journal_directory', journal_location.default_directory())
        if not Path(folder).is_dir():
            choose()
            return
        state.update(busy=True, original=variable.get(), location=None)
        button.configure(state='disabled')

        def work():
            try:
                results.put((journal_location.read_current_system(folder), None))
            except (OSError, ValueError) as exc:
                results.put((None, str(exc)))
        threading.Thread(target=work, daemon=True).start()
        state['timer'] = button.after(40, poll)

    button = ttk.Button(parent, text='使用当前星系', command=start)
    button.journal_variable = variable
    button.journal_state = state
    button.choose_journal_directory = choose

    def hide(event=None):
        if state['tooltip'] is not None:
            state['tooltip'].destroy()
            state['tooltip'] = None

    def show(event=None):
        hide()
        text = tr('读取日志最近确认的位置；非实时定位。右键可选择 Journal 文件夹。')
        location = state['location']
        if location:
            text = tr('日志最近确认位置：{system}\n记录时间：{timestamp}\n文件：{filename}').format(
                system=location.system, timestamp=location.timestamp, filename=location.filename) + '\n' + text
        tip = state['tooltip'] = Toplevel(button)
        tip.overrideredirect(True)
        tip.geometry(f'+{button.winfo_rootx()}+{button.winfo_rooty() + button.winfo_height() + 4}')
        ttk.Label(tip, text=text, padding=6, wraplength=460).pack()

    def destroyed(event):
        if event.widget is button:
            hide()
            if state['timer'] is not None:
                button.after_cancel(state['timer'])
                state['timer'] = None
            # This convenience hook closes over the widget; release it on Tk's
            # thread instead of leaving a self-cycle for worker-thread GC.
            del button.choose_journal_directory

    button.bind('<Enter>', show)
    button.bind('<Leave>', hide)
    button.bind('<Button-3>', lambda event: choose())
    button.bind('<Destroy>', destroyed, add='+')
    return button


def system_label(parent, text, variable):
    """A drop-in grid/pack label with an adjacent Journal fill button."""
    frame = ttk.Frame(parent)
    ttk.Label(frame, text=text).pack(side='left')
    current_system_button(frame, variable).pack(side='left', padx=4)
    return frame
