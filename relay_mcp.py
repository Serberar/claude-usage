"""El relevo de conversaciones de la app de escritorio: un servidor MCP (lo arranca la
propia app de escritorio) con dos herramientas para Claude.

- guardar_relevo: Claude escribe un resumen de la conversación en un archivo.
- leer_relevo: en la otra cuenta, Claude lo lee al empezar un chat nuevo y sigue.

Por debajo del 90 % Claude no hace nada por su cuenta (no gasta): solo guarda si el usuario
escribe «relevo». Al pasar del 90 % (lo apunta Claude Usage cada minuto) cambia la
descripción de guardar_relevo para que lo guarde solo al terminar cada respuesta, y se
avisa a la app de escritorio de que las herramientas han cambiado (tools/list_changed).

Los servidores MCP se configuran en el ordenador, no en la cuenta: valen en las dos. La
conversación nunca sale de claude.ai por otro camino; el resumen lo hace Claude dentro del
chat. Aquí solo se habla MCP por stdio (JSON por líneas), sin dependencias.
"""

import json
import os
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

from system import write_atomic

NAME = "claude-usage-relevo"
RELAY_DIR = Path(os.environ.get("APPDATA", Path.home())) / "ClaudeUsage" / "relevo"
RELAY_FILE = RELAY_DIR / "relevo.md"
STATUS_FILE = RELAY_DIR / "estado.json"  # lo escribe Claude Usage cada minuto
STATUS_MAX_AGE = 15 * 60  # más viejo, la app no está abierta: se mira la app de escritorio
NEAR = 90                 # % a partir del cual Claude guarda el relevo solo
WATCH_SECONDS = 30        # cada cuánto mira el servidor si se ha cruzado el 90 %
KEEP = 20                 # relevos anteriores que se guardan por si acaso

INSTRUCTIONS = (
    "Relevo entre cuentas de Claude. Cuando el usuario escriba «relevo», llama a "
    "guardar_relevo. Cuando escriba «continúa» o «sigue» al empezar un chat nuevo, llama a "
    "leer_relevo y continúa la tarea desde donde se quedó, sin volver a preguntar lo que ya "
    "está decidido. Sigue lo que diga la descripción de guardar_relevo: cambia cuando la "
    "cuenta está cerca del límite.")

CONTENT = (
    "El relevo se reescribe entero cada vez, conciso pero suficiente para seguir sin el chat "
    "original: objetivo, contexto y decisiones tomadas, lo que ya está hecho, lo que falta y "
    "el siguiente paso exacto, datos y textos clave al pie de la letra (código, cifras, "
    "nombres), y el tono o formato que pidió el usuario.")


def save_tool(pct):
    """guardar_relevo: a mano por debajo del 90 %; sola por encima."""
    if pct is not None and pct >= NEAR:
        when = (f"AHORA la cuenta va por el {pct:.0f} % y está a punto de agotarse: al "
                "terminar cada respuesta en la que la conversación avance, llama a "
                "guardar_relevo sin que el usuario lo pida y sin mencionarlo (no en "
                "respuestas triviales). También si el usuario escribe «relevo».")
    else:
        when = ("Úsala solo cuando el usuario escriba «relevo» o pida guardar la "
                "conversación para seguirla en otro chat. No la llames por tu cuenta.")
    return {
        "name": "guardar_relevo",
        "description": ("Guarda el relevo de esta conversación para continuarla en otro chat "
                        "(otra cuenta) si esta se agota. " + when + " " + CONTENT),
        "inputSchema": {
            "type": "object",
            "properties": {
                "titulo": {"type": "string", "description": "De qué va, en pocas palabras"},
                "resumen": {"type": "string", "description": "El relevo completo, en Markdown"},
            },
            "required": ["resumen"],
        },
    }


READ_TOOL = {
    "name": "leer_relevo",
    "description": (
        "Lee el último relevo guardado para continuar una conversación de otro chat. Úsala "
        "cuando el usuario escriba «continúa» o «sigue» al empezar un chat nuevo, y después "
        "sigue con la tarea desde el siguiente paso que indique."),
    "inputSchema": {"type": "object", "properties": {}},
    "annotations": {"readOnlyHint": True},
}


def tools(pct):
    return [save_tool(pct), READ_TOOL]


def is_near(pct):
    return pct is not None and pct >= NEAR


# ── el estado de la cuenta y los relevos ──

def write_status(pct, folder=RELAY_DIR, now=None):
    """Claude Usage apunta por cuánto va la cuenta de la app de escritorio (el límite que va
    peor), para que el servidor sepa cuándo toca guardar el relevo."""
    write_atomic(folder / STATUS_FILE.name, json.dumps({"pct": pct, "at": now or time.time()}))


def desktop_pct(folder=RELAY_DIR, now=None):
    """% del límite que va peor de la cuenta de la app de escritorio, o None si no se sabe."""
    now = now or time.time()
    try:
        status = json.loads((folder / STATUS_FILE.name).read_text(encoding="utf-8"))
        if now - status["at"] < STATUS_MAX_AGE:
            return status["pct"]
    except (OSError, ValueError, KeyError, TypeError):
        pass
    try:  # Claude Usage no está abierta: lo último que apuntó la app de escritorio
        import desktop
        sample = desktop.latest_samples(desktop.usage_samples()).get(desktop.current_org())
        values = [v for v in (sample or {}).get("u", {}).values() if isinstance(v, (int, float))]
        return max(values) if values else None
    except Exception:
        return None


def save_relay(summary, title="", folder=RELAY_DIR, now=None):
    now = now or datetime.now()
    text = (f"# Relevo: {title or 'conversación'}\n\n"
            f"Guardado el {now:%d/%m/%Y a las %H:%M}.\n\n{summary.strip()}\n")
    write_atomic(folder / RELAY_FILE.name, text)
    history = folder / "anteriores"
    write_atomic(history / f"{now:%Y%m%d-%H%M%S}.md", text)
    for old in sorted(history.glob("*.md"))[:-KEEP]:
        old.unlink(missing_ok=True)
    return folder / RELAY_FILE.name


def relay_time(folder=RELAY_DIR):
    """Cuándo se guardó el último relevo (datetime local) o None."""
    try:
        return datetime.fromtimestamp((folder / RELAY_FILE.name).stat().st_mtime)
    except OSError:
        return None


def read_relay(folder=RELAY_DIR):
    try:
        return (folder / RELAY_FILE.name).read_text(encoding="utf-8")
    except OSError:
        return None


def call_tool(name, args, folder=RELAY_DIR):
    """(texto de respuesta, es un error)."""
    if name == "guardar_relevo":
        summary = str(args.get("resumen") or "").strip()
        if not summary:
            return "Falta el resumen.", True
        save_relay(summary, str(args.get("titulo") or "").strip(), folder)
        return "Relevo guardado. No hace falta decírselo al usuario.", False
    if name == "leer_relevo":
        relay = read_relay(folder)
        if not relay:
            return "No hay ningún relevo guardado.", False
        return ("Este es el relevo de la conversación anterior. Continúa la tarea desde el "
                "siguiente paso que indica, sin repetir lo que ya está hecho.\n\n" + relay), False
    return f"No existe la herramienta {name}.", True


# ── el servidor ──

class Server:
    """MCP por stdio. pct: de dónde sale el % de la cuenta (se cambia en las pruebas)."""

    def __init__(self, stdout, folder=RELAY_DIR, pct=None):
        self.stdout, self.folder = stdout, folder
        self.pct = pct or (lambda: desktop_pct(folder))
        self.lock = threading.Lock()  # el hilo que vigila y el que contesta escriben a la vez
        self.listed_near = None       # cómo estaba al dar la lista de herramientas

    def send(self, message):
        with self.lock:
            self.stdout.write(json.dumps(message, ensure_ascii=False).encode("utf-8") + b"\n")
            self.stdout.flush()

    def handle(self, message):
        """La respuesta a un mensaje JSON-RPC, o None si es una notificación."""
        method, msg_id = message.get("method"), message.get("id")
        if msg_id is None:
            return None
        if method == "initialize":
            version = (message.get("params") or {}).get("protocolVersion") or "2025-06-18"
            result = {"protocolVersion": version,
                      "capabilities": {"tools": {"listChanged": True}},
                      "serverInfo": {"name": NAME, "version": "1.1.0"},
                      "instructions": INSTRUCTIONS}
        elif method == "tools/list":
            pct = self.pct()
            self.listed_near = is_near(pct)
            result = {"tools": tools(pct)}
        elif method == "tools/call":
            params = message.get("params") or {}
            text, error = call_tool(params.get("name"), params.get("arguments") or {},
                                    self.folder)
            result = {"content": [{"type": "text", "text": text}], "isError": error}
        elif method == "ping":
            result = {}
        else:
            return {"jsonrpc": "2.0", "id": msg_id,
                    "error": {"code": -32601, "message": f"método desconocido: {method}"}}
        return {"jsonrpc": "2.0", "id": msg_id, "result": result}

    def check(self):
        """Si la cuenta ha cruzado el 90 % (en un sentido u otro) desde la última lista, avisa
        a la app de escritorio para que la pida otra vez. Devuelve si avisó."""
        if self.listed_near is None:
            return False  # aún no ha pedido la lista
        near = is_near(self.pct())
        if near == self.listed_near:
            return False
        self.listed_near = near  # no repetir el aviso cada medio minuto
        self.send({"jsonrpc": "2.0", "method": "notifications/tools/list_changed"})
        return True

    def watch(self, stop):
        while not stop.wait(WATCH_SECONDS):
            try:
                self.check()
            except Exception:
                pass  # vigilar no puede tumbar el servidor

    def serve(self, stdin):
        stop = threading.Event()
        threading.Thread(target=self.watch, args=(stop,), daemon=True).start()
        try:
            for line in stdin:
                try:
                    message = json.loads(line)
                except ValueError:
                    continue
                try:
                    reply = self.handle(message)
                except Exception as exc:  # una herramienta que falla no tumba el servidor
                    reply = {"jsonrpc": "2.0", "id": message.get("id"),
                             "error": {"code": -32603, "message": str(exc)}}
                if reply is not None:
                    self.send(reply)
        finally:
            stop.set()


def std_streams():
    """La entrada y salida que le da la app de escritorio. El .exe es de ventana (sin
    consola): si Python no las ha preparado, se abren desde los handles de Windows."""
    if sys.stdin is not None and sys.stdout is not None:
        return sys.stdin.buffer, sys.stdout.buffer
    import ctypes
    import msvcrt
    kernel32 = ctypes.windll.kernel32
    kernel32.GetStdHandle.restype = ctypes.c_void_p
    streams = []
    for handle_id, mode in ((-10, "rb"), (-11, "wb")):  # STD_INPUT_HANDLE, STD_OUTPUT_HANDLE
        handle = kernel32.GetStdHandle(handle_id)
        if not handle or handle == ctypes.c_void_p(-1).value:
            raise OSError("la app de escritorio no ha dado entrada y salida al servidor")
        streams.append(os.fdopen(msvcrt.open_osfhandle(handle, 0), mode))
    return tuple(streams)


def serve(stdin=None, stdout=None):
    from applog import log
    try:
        if stdin is None or stdout is None:
            stdin, stdout = std_streams()
        log.info("servidor del relevo en marcha")
        Server(stdout).serve(stdin)
    except Exception:
        log.exception("el servidor del relevo se ha parado")
        raise


# ── darlo de alta en la app de escritorio ──

def server_entry():
    """Cómo arranca la app de escritorio este servidor: con el .exe, o con Python si se
    ejecuta desde el código."""
    if getattr(sys, "frozen", False):
        return {"command": sys.executable, "args": ["--relevo"]}
    python = Path(sys.executable)
    console = python.with_name("python.exe")  # pythonw no tiene stdio
    return {"command": str(console if console.exists() else python),
            "args": [str(Path(__file__).resolve())]}


def config_path():
    from desktop import DATA
    return DATA / "claude_desktop_config.json"


def installed(path=None):
    path = path or config_path()
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return NAME in (config.get("mcpServers") or {})


def set_installed(on, path=None, entry=None):
    """Lo añade o lo quita de claude_desktop_config.json sin tocar lo demás. La app de
    escritorio lo carga al volver a abrirse."""
    path = path or config_path()
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        config = {}
    except ValueError:
        raise OSError(f"{path.name} no es JSON válido; no lo toco") from None
    servers = config.setdefault("mcpServers", {})
    if on:
        servers[NAME] = entry or server_entry()
    else:
        servers.pop(NAME, None)
        if not servers:
            config.pop("mcpServers")
    write_atomic(path, json.dumps(config, ensure_ascii=False, indent=2))


if __name__ == "__main__":  # desde el código; el .exe entra por claude_usage.pyw --relevo
    import applog
    applog.setup("relevo")
    serve()
