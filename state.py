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


def save_state(**changes):
    with _lock:
        state = load_state()
        state.update(changes)
        write_atomic(STATE_FILE, json.dumps(state, ensure_ascii=False))
