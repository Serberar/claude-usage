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
    "auto_switch": False,    # cambiar de cuenta solo al llegar al umbral (cswap auto)
    "auto_threshold": 90,    # % del límite que va peor
    "tray_shows": "five",    # qué marca el icono: "five", "week" o "worst"
}


def setting(name):
    return load_state().get("settings", {}).get(name, SETTINGS[name])


def set_setting(name, value):
    _update(lambda state: state.setdefault("settings", {}).update({name: value}))
