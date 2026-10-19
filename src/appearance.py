"""Shared, presentation-only light/dark themes; no third-party runtime dependencies."""
import sys
import tkinter as tk
from tkinter import font, ttk
from ui_display import windows_ui_font


MODES = {'system': '跟随系统', 'light': '浅色', 'dark': '深色'}
PALETTES = {
    'light': dict(bg='#f3f5f9', surface='#ffffff', alternate='#edf2f8',
                  text='#202b3c', muted='#58677c', border='#cbd5e1',
                  accent='#205ecf', hover='#174dac', selected='#ffffff',
                  disabled='#65748a', warning='#895000'),
    'dark': dict(bg='#171e29', surface='#202a38', alternate='#263344',
                 text='#e7edf7', muted='#a8b7cd', border='#43536a',
                 accent='#3574dc', hover='#4484ec', selected='#ffffff',
                 disabled='#96a6bd', warning='#f2bf65'),
}


def normalize_mode(mode):
    return mode if isinstance(mode, str) and mode in MODES else 'system'


def system_mode():
    """Use Windows' *app* colour preference; unsupported/missing settings use light."""
    if sys.platform == 'win32':
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                r'Software\Microsoft\Windows\CurrentVersion\Themes\Personalize') as key:
                value, _ = winreg.QueryValueEx(key, 'AppsUseLightTheme')
            return 'dark' if value == 0 else 'light'
        except OSError:
            pass
    return 'light'


class Appearance:
    def __init__(self, root, mode='system', system_reader=None, poll_ms=1500):
        self.root = root
        self.mode, self.effective = normalize_mode(mode), None
        self._system_reader = system_reader or system_mode
        self._poll_ms, self._poll_id, self._closed = poll_ms, None, False
        root._appearance = self
        self.style = ttk.Style(root)
        self.style.theme_create('elite', parent='clam')
        self.style.theme_use('elite')
        self._fonts()
        # Map also sees Tcl-owned combobox dropdowns and unadapted Tk popups.
        root.bind_all('<Map>', self._on_map, add='+')
        root.bind('<Destroy>', self._on_destroy, add='+')
        self.refresh()
        self._poll_id = root.after(self._poll_ms, self._poll)

    def _fonts(self):
        default = font.nametofont('TkDefaultFont', root=self.root)
        if sys.platform == 'win32':
            family = windows_ui_font(font.families(self.root), default.actual('family'))
            default.configure(family=family, size=10, weight='normal')
        for name in ('TkTextFont', 'TkMenuFont', 'TkHeadingFont'):
            target = font.nametofont(name, root=self.root)
            target.configure(family=default.actual('family'), size=default.actual('size'))
        font.nametofont('TkHeadingFont', root=self.root).configure(weight='bold')
        self._title_font = default.copy()
        self._title_font.configure(size=16, weight='bold')

    @property
    def palette(self):
        return PALETTES[self.effective]

    def set_mode(self, mode):
        self.mode = normalize_mode(mode)
        self.refresh()

    def refresh(self):
        if self._closed:
            return
        effective = self.mode
        if effective == 'system':
            try:
                effective = self._system_reader()
            except (OSError, ValueError):
                effective = 'light'
        if effective not in ('light', 'dark'):
            effective = 'light'
        if effective == self.effective:
            return
        self.effective = effective
        self._styles()
        self._defaults()
        self._walk(str(self.root))

    def _styles(self):
        p, s = self.palette, self.style
        s.configure('.', background=p['bg'], foreground=p['text'],
                    font='TkDefaultFont', bordercolor=p['border'],
                    lightcolor=p['border'], darkcolor=p['border'],
                    troughcolor=p['alternate'], selectbackground=p['accent'],
                    selectforeground=p['selected'])
        s.configure('TFrame', background=p['bg'])
        s.configure('Condition.TFrame', borderwidth=1, relief='solid')
        s.configure('TLabel', background=p['bg'], foreground=p['text'])
        s.configure('Muted.TLabel', foreground=p['muted'])
        s.configure('Warning.TLabel', foreground=p['warning'])
        s.configure('Title.TLabel', font=self._title_font)
        s.configure('TLabelframe', borderwidth=1, relief='solid')
        s.configure('TLabelframe.Label', foreground=p['muted'], font='TkHeadingFont')
        s.configure('TButton', padding=(10, 6), background=p['surface'],
                    foreground=p['text'], borderwidth=1, relief='flat')
        s.map('TButton', background=[('disabled', p['bg']), ('pressed', p['border']),
                                     ('active', p['alternate'])],
              foreground=[('disabled', p['disabled'])],
              bordercolor=[('focus', p['accent'])])
        s.configure('Accent.TButton', background=p['accent'], foreground=p['selected'])
        s.map('Accent.TButton', background=[('disabled', p['alternate']),
                                            ('pressed', p['hover']), ('active', p['hover'])],
              foreground=[('disabled', p['disabled']), ('!disabled', p['selected'])])
        for name in ('TEntry', 'TCombobox', 'TSpinbox'):
            s.configure(name, padding=5, foreground=p['text'], fieldbackground=p['surface'],
                        background=p['surface'], insertcolor=p['text'],
                        arrowcolor=p['text'], borderwidth=1)
            s.map(name, fieldbackground=[('disabled', p['alternate']),
                                         ('readonly', p['surface'])],
                  foreground=[('disabled', p['disabled']), ('readonly', p['text'])],
                  background=[('disabled', p['alternate']), ('active', p['alternate'])],
                  bordercolor=[('focus', p['accent'])],
                  selectbackground=[('!disabled', p['accent'])],
                  selectforeground=[('!disabled', p['selected'])])
        for name in ('TCheckbutton', 'TRadiobutton'):
            s.configure(name, padding=(2, 4), background=p['bg'], foreground=p['text'])
            s.map(name, background=[('active', p['bg'])],
                  foreground=[('disabled', p['disabled'])],
                  indicatorbackground=[('disabled', p['alternate']),
                                       ('selected', p['accent']), ('!selected', p['surface'])],
                  indicatorforeground=[('selected', p['selected']), ('!selected', p['text'])])
        rowheight = max(28, font.nametofont('TkDefaultFont', root=self.root).metrics('linespace') + 10)
        s.configure('Treeview', background=p['surface'], fieldbackground=p['surface'],
                    foreground=p['text'], rowheight=rowheight, borderwidth=1)
        s.map('Treeview', background=[('selected', p['accent'])],
              foreground=[('selected', p['selected'])])
        s.configure('Treeview.Heading', background=p['alternate'], foreground=p['text'],
                    font='TkHeadingFont', padding=(8, 7), relief='flat')
        s.map('Treeview.Heading', background=[('active', p['border'])])
        for name in ('Vertical.TScrollbar', 'Horizontal.TScrollbar'):
            s.configure(name, background=p['border'], troughcolor=p['bg'],
                        arrowcolor=p['text'], borderwidth=0, arrowsize=14)
            s.map(name, background=[('pressed', p['muted']), ('active', p['muted'])])
        for name in ('Horizontal.TProgressbar', 'Vertical.TProgressbar'):
            s.configure(name, background=p['accent'], troughcolor=p['alternate'], borderwidth=0)
        s.configure('TNotebook', background=p['bg'], borderwidth=0)
        s.configure('TNotebook.Tab', padding=(12, 7))
        s.map('TNotebook.Tab', background=[('selected', p['surface']), ('!selected', p['alternate'])],
              foreground=[('selected', p['text']), ('!selected', p['muted'])])

    def _classic_options(self, widget_class):
        p = self.palette
        if widget_class in ('Tk', 'Toplevel', 'Frame'):
            return dict(background=p['bg'])
        if widget_class == 'Canvas':
            return dict(background=p['bg'], highlightbackground=p['border'], highlightthickness=0)
        if widget_class == 'Label':
            return dict(background=p['bg'], foreground=p['text'])
        if widget_class == 'Button':
            return dict(background=p['surface'], foreground=p['text'],
                        activebackground=p['alternate'], activeforeground=p['text'],
                        disabledforeground=p['disabled'], highlightbackground=p['border'],
                        relief='flat', borderwidth=1, padx=10, pady=5)
        if widget_class == 'Entry':
            return dict(background=p['surface'], foreground=p['text'],
                        insertbackground=p['text'], selectbackground=p['accent'],
                        selectforeground=p['selected'], disabledbackground=p['alternate'],
                        disabledforeground=p['disabled'], readonlybackground=p['surface'],
                        highlightbackground=p['border'], highlightcolor=p['accent'],
                        relief='flat', borderwidth=1)
        if widget_class in ('Text', 'Listbox'):
            options = dict(background=p['surface'], foreground=p['text'],
                           selectbackground=p['accent'], selectforeground=p['selected'],
                           highlightbackground=p['border'], highlightcolor=p['accent'],
                           relief='flat', borderwidth=1)
            if widget_class == 'Text':
                options.update(insertbackground=p['text'], inactiveselectbackground=p['alternate'])
            else:
                options.update(disabledforeground=p['disabled'])
            return options
        if widget_class == 'Menu':
            return dict(background=p['surface'], foreground=p['text'],
                        activebackground=p['accent'], activeforeground=p['selected'])
        return {}

    def _defaults(self):
        # Options apply at construction, even to hidden/new windows and Tcl-owned popdowns.
        resource_names = dict(selectbackground='selectBackground', selectforeground='selectForeground',
                              insertbackground='insertBackground', highlightbackground='highlightBackground',
                              highlightcolor='highlightColor', highlightthickness='highlightThickness',
                              borderwidth='borderWidth', disabledforeground='disabledForeground',
                              disabledbackground='disabledBackground', readonlybackground='readonlyBackground',
                              inactiveselectbackground='inactiveSelectBackground',
                              activebackground='activeBackground', activeforeground='activeForeground')
        for cls in ('Toplevel', 'Frame', 'Canvas', 'Text', 'Listbox', 'Menu', 'Label', 'Entry', 'Button'):
            for option, value in self._classic_options(cls).items():
                resource = resource_names.get(option, option)
                self.root.option_add(f'*{cls}.{resource}', value, 'interactive')
        self.root.option_add('*Listbox.font', 'TkDefaultFont', 'interactive')

    def style_widget(self, path):
        try:
            cls = self.root.tk.call('winfo', 'class', path)
            options = self._classic_options(cls)
            if cls == 'Label':
                background = self.root.tk.call(path, 'cget', '-background')
                if str(background) not in {p['bg'] for p in PALETTES.values()}:
                    options = {}  # Preserve explicitly coloured banners / semantic notices.
            if options:
                args = [arg for key, value in options.items() for arg in (f'-{key}', value)]
                self.root.tk.call(path, 'configure', *args)
            if cls in ('Tk', 'Toplevel'):
                self._titlebar(path)
            if cls == 'Treeview':
                for tag, color in (('_stripe_even', self.palette['surface']),
                                   ('_stripe_odd', self.palette['alternate'])):
                    self.root.tk.call(path, 'tag', 'configure', tag, '-background', color)
        except tk.TclError:
            pass  # A window can close between a Map notification and repaint.

    def _titlebar(self, path):
        """Best-effort native frame colours on Windows 11; older systems keep their frame."""
        if sys.platform != 'win32':
            return
        try:
            import ctypes
            from ctypes import wintypes
            if self.root.tk.getboolean(self.root.tk.call('wm', 'overrideredirect', path)):
                return
            user32, dwm = ctypes.WinDLL('user32'), ctypes.WinDLL('dwmapi')
            user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
            user32.GetAncestor.restype = wintypes.HWND
            dwm.DwmSetWindowAttribute.argtypes = [wintypes.HWND, wintypes.DWORD,
                                                  ctypes.c_void_p, wintypes.DWORD]
            dwm.DwmSetWindowAttribute.restype = ctypes.c_long
            window_id = self.root.tk.getint(self.root.tk.call('winfo', 'id', path))
            handle = user32.GetAncestor(window_id, 2)
            if not handle:
                return
            dark = wintypes.BOOL(self.effective == 'dark')
            dwm.DwmSetWindowAttribute(handle, 20, ctypes.byref(dark), ctypes.sizeof(dark))
            # Explicit caption/text colours also honour manual mode when Windows differs.
            for attribute, color in ((35, self.palette['bg']), (36, self.palette['text'])):
                red, green, blue = (int(color[i:i + 2], 16) for i in (1, 3, 5))
                value = wintypes.DWORD(red | green << 8 | blue << 16)
                dwm.DwmSetWindowAttribute(handle, attribute, ctypes.byref(value), ctypes.sizeof(value))
        except (OSError, AttributeError, tk.TclError):
            pass  # Unsupported DWM attributes are cosmetic, never a startup failure.

    def _walk(self, path):
        self.style_widget(path)
        try:
            children = self.root.tk.splitlist(self.root.tk.call('winfo', 'children', path))
        except tk.TclError:
            return
        for child in children:
            self._walk(child)

    def _on_map(self, event):
        if not self._closed:
            self.style_widget(str(event.widget))

    def _poll(self):
        self._poll_id = None
        if not self._closed:
            if self.mode == 'system':
                self.refresh()
            self._poll_id = self.root.after(self._poll_ms, self._poll)

    def _on_destroy(self, event):
        if event.widget is self.root:
            self._closed = True
            if self._poll_id is not None:
                self.root.after_cancel(self._poll_id)
                self._poll_id = None
