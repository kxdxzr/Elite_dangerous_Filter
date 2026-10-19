"""Display bootstrap, called before Tk creates any windows.

Frozen builds declare system DPI awareness in their embedded manifest. Source
launches opt in via Win32 before Tk starts. Do not force per-monitor awareness
until geometry and monitor-transition handling are supported and tested.
"""
import ctypes
import sys


def process_dpi_awareness():
    """Return 0 (unaware), 1 (system), 2 (per-monitor), or None if unsupported."""
    if sys.platform != 'win32':
        return None
    try:
        query = ctypes.WinDLL('shcore').GetProcessDpiAwareness
        query.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_int)]
        query.restype = ctypes.c_long
        value = ctypes.c_int()
        if query(None, ctypes.byref(value)) == 0:
            return value.value
    except (OSError, AttributeError):
        pass
    return None


def initialize_display():
    """Source-only fallback; frozen mode must be configured by its manifest."""
    awareness = process_dpi_awareness()
    if sys.platform != 'win32' or getattr(sys, 'frozen', False) or awareness in (1, 2):
        return awareness
    try:
        enable = ctypes.WinDLL('user32').SetProcessDPIAware
        enable.argtypes = []
        enable.restype = ctypes.c_int
        enable()
    except (OSError, AttributeError):
        pass
    return process_dpi_awareness()


def windows_ui_font(families, native):
    """Use a real CJK UI font instead of forcing Chinese glyphs through Segoe UI."""
    available = set(families)
    return next((name for name in ('Microsoft YaHei UI', 'Microsoft YaHei', 'Segoe UI')
                 if name in available), native)
