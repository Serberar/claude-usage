"""Abrir la app al iniciar Windows: un valor en HKCU\\...\\Run (el mismo que crea el
instalador, que también lo borra al desinstalar)."""

import sys
from pathlib import Path

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def autostart_command():
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}" --tray'
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    script = Path(__file__).with_name("claude_usage.pyw")
    return f'"{pythonw}" "{script}" --tray'


def autostart_enabled():
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.QueryValueEx(key, "ClaudeUsage")
        return True
    except OSError:
        return False


def set_autostart(enabled):
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        if enabled:
            winreg.SetValueEx(key, "ClaudeUsage", 0, winreg.REG_SZ, autostart_command())
        else:
            try:
                winreg.DeleteValue(key, "ClaudeUsage")
            except FileNotFoundError:
                pass
