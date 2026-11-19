"""Lo que la app guarda: %APPDATA%\\ClaudeUsage\\state.json (plugins añadidos, fichas
cambiadas y cuándo se tocaron los plugins por última vez)."""

import json
import os
import threading
from pathlib import Path

from system import write_atomic

STATE_FILE = Path(os.environ.get("APPDATA", Path.home())) / "ClaudeUsage" / "state.json"
_lock = threading.Lock()  # guardan a la vez la ventana y los hilos de fondo


def load_state():
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError):
        # roto o ilegible: se aparta para no pisarlo con el próximo guardado
        try:
            STATE_FILE.replace(STATE_FILE.with_name(STATE_FILE.name + ".roto"))
        except OSError:
            pass
        return {}


def _update(change):
    """Lee, cambia y guarda de una vez: dos hilos a la vez no se pisan los cambios."""
    with _lock:
        state = load_state()
        change(state)
        write_atomic(STATE_FILE, json.dumps(state, ensure_ascii=False))


def save_state(**changes):
    _update(lambda state: state.update(changes))


# opciones de Ajustes > General y su valor si nunca se han tocado
SETTINGS = {
    "notify": True,          # avisos de Windows (cerca del límite, cuenta disponible otra vez)
    "mode": None,            # "auto" o "manual" (ver mode())
    "auto_threshold": 90,    # en automático, % del límite que va peor al que cambia Code
    # de versiones anteriores, solo para elegir el modo la primera vez
    "auto_switch": False,
    "desktop_auto": False,
    "tray_shows": "five",    # qué marca el icono: "five", "week" o "worst"
}


def setting(name):
    return load_state().get("settings", {}).get(name, SETTINGS[name])


MODES = ("auto", "manual")


def mode():
    """Cómo se usan las cuentas (pestaña Uso). "auto": Claude Code y la app de escritorio
    van con la misma cuenta y pasan juntos a otra cuando se agota. "manual": cada uno con
    la que se elija, sin cambios solos. Sin elegir aún, lo que dijeran los interruptores de
    cambio automático de versiones anteriores."""
    value = load_state().get("settings", {}).get("mode")
    if value in MODES:
        return value
    return "auto" if setting("auto_switch") or setting("desktop_auto") else "manual"


def set_setting(name, value):
    _update(lambda state: state.setdefault("settings", {}).update({name: value}))
