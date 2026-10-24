"""Las opciones de Ponytail que se cambian desde la pestaña Plugins: con qué nivel empieza
cada sesión y si enseña su barra en Claude Code."""

import json
import os
from pathlib import Path

from plugins import CLAUDE_DIR
from system import write_atomic

LEVELS = ["off", "lite", "full", "ultra"]
CONFIG = Path(os.environ.get("APPDATA", Path.home())) / "ponytail" / "config.json"
BAND = CLAUDE_DIR / ".ponytail-band"  # con "off" dentro, Ponytail no enseña su barra


def level():
    """Nivel con el que Ponytail empieza cada sesión (defaultMode de su config.json)."""
    try:
        value = json.loads(CONFIG.read_text(encoding="utf-8")).get("defaultMode")
    except (OSError, ValueError):
        value = None
    return value if value in LEVELS else "full"


def set_level(value):
    try:
        config = json.loads(CONFIG.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        config = {}
    config["defaultMode"] = value
    write_atomic(CONFIG, json.dumps(config, indent=2))


def band_visible():
    try:
        return BAND.read_text(encoding="utf-8").strip() != "off"
    except OSError:
        return True


def set_band(visible):
    if visible:
        BAND.unlink(missing_ok=True)
    else:
        write_atomic(BAND, "off")
