"""El registro de la app: %APPDATA%\\ClaudeUsage\\logs\\claude-usage.log.

Abierta con pythonw o como .exe no hay consola: sin esto, un error en casa de alguien no
deja rastro. Se guardan los errores con su traza, los comandos que fallan y los cambios de
cuenta; nunca tokens ni el contenido de las conversaciones. Rota a 1 MB (3 archivos).
"""

import logging
import os
import sys
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_DIR = Path(os.environ.get("APPDATA", Path.home())) / "ClaudeUsage" / "logs"
LOG_FILE = LOG_DIR / "claude-usage.log"

log = logging.getLogger("claude_usage")


def setup(name="app"):
    """Prepara el registro y engancha los errores que no recoge nadie. name distingue los
    procesos que escriben en el mismo archivo (la ventana, el servidor del relevo)."""
    if log.handlers:
        return log
    log.setLevel(logging.INFO)
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(LOG_FILE, maxBytes=1_000_000, backupCount=3,
                                      encoding="utf-8", delay=True)
    except OSError:
        handler = logging.NullHandler()  # sin registro, pero la app funciona igual
    handler.setFormatter(logging.Formatter(
        f"%(asctime)s %(levelname)s [{name}:%(threadName)s] %(message)s"))
    log.addHandler(handler)

    def unhandled(kind, value, trace):
        log.critical("error sin recoger", exc_info=(kind, value, trace))

    def unhandled_thread(args):
        if args.exc_type is not SystemExit:
            log.error("error en un hilo", exc_info=(args.exc_type, args.exc_value,
                                                    args.exc_traceback))

    sys.excepthook = unhandled
    threading.excepthook = unhandled_thread
    return log
