"""Instala lo que necesita la app y las herramientas para ahorrar tokens en Claude Code."""

import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
NEW_CONSOLE = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
LOCAL_BIN = Path.home() / ".local" / "bin"
CLAUDE_DIR = Path.home() / ".claude"
STATE_FILE = Path(os.environ.get("APPDATA", Path.home())) / "ClaudeUsage" / "state.json"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
WINGET_NO_UPDATE = -1978335189  # winget upgrade cuando ya está en la última versión


class StepError(RuntimeError):
    pass


def refresh_path():
    """Relee el PATH del registro: lo recién instalado no está en el PATH de este proceso."""
    try:
        import winreg
    except ImportError:
        return
    parts = []
    keys = ((winreg.HKEY_LOCAL_MACHINE,
             r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"),
            (winreg.HKEY_CURRENT_USER, "Environment"))
    for root, key in keys:
        try:
            with winreg.OpenKey(root, key) as handle:
                value, _type = winreg.QueryValueEx(handle, "Path")
        except OSError:
            continue
        parts.extend(os.path.expandvars(value).split(os.pathsep))
    parts.append(str(LOCAL_BIN))
    current = os.environ.get("PATH", "").split(os.pathsep)
    os.environ["PATH"] = os.pathsep.join(dict.fromkeys(p for p in parts + current if p))


def find(name):
    found = shutil.which(name)
    if not found:  # quizá se instaló después de abrir la app
        refresh_path()
        found = shutil.which(name)
    if found:
        return found
    candidate = LOCAL_BIN / f"{name}.exe"
    return str(candidate) if candidate.exists() else None


def quiet(_line):
    pass


def run(args, log=quiet, timeout=900, answer=None, ok_codes=(0,)):
    """Ejecuta un comando, apunta su salida en el registro y falla si no acaba bien.

    answer es lo que se le escribe al comando si pregunta algo.
    """
    exe = find(args[0]) or args[0]
    log(f"> {' '.join(args)}")
    env = dict(os.environ, PYTHONIOENCODING="utf-8", NO_COLOR="1")
    try:
        proc = subprocess.run(
            [exe, *args[1:]], capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=timeout, creationflags=NO_WINDOW, env=env,
            input=answer, stdin=None if answer else subprocess.DEVNULL,
        )
    except FileNotFoundError:
        raise StepError(f"no encuentro {args[0]}") from None
    except subprocess.TimeoutExpired:
        raise StepError(f"{args[0]} tardó demasiado") from None
    for line in (proc.stdout + proc.stderr).strip().splitlines()[-12:]:
        log("  " + line)
    if proc.returncode not in ok_codes:
        raise StepError(f"{args[0]} falló (código {proc.returncode})")
    return proc.stdout


def run_installer_script(url, log):
    run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command",
         f"irm {url} | iex"], log)


def winget_install(package, log):
    ensure("winget", log)
    run(["winget", "install", "-e", "--id", package, "--silent", "--disable-interactivity",
         "--accept-package-agreements", "--accept-source-agreements"], log)


def winget_uninstall(package, log):
    run(["winget", "uninstall", "-e", "--id", package, "--silent",
         "--disable-interactivity"], log)


def node_ok():
    exe = find("node")
    if not exe:
        return False
    try:
        version = run([exe, "--version"])
    except StepError:
        return False
    match = re.search(r"(\d+)", version)
    return bool(match) and int(match.group(1)) >= 22


def install_cswap(log):
    ensure("uv", log)
    run(["uv", "tool", "install", "claude-swap"], log)


# clave: (nombre, cómo saber si está, cómo instalarlo; None si no se puede instalar solo)
REQUIREMENTS = {
    "claude": ("Claude Code", lambda: bool(find("claude")),
               lambda log: run_installer_script("https://claude.ai/install.ps1", log)),
    "uv": ("uv", lambda: bool(find("uv")),
           lambda log: run_installer_script("https://astral.sh/uv/install.ps1", log)),
    "winget": ("winget", lambda: bool(find("winget")), None),
    "node": ("Node.js 22 o más nuevo", node_ok,
             lambda log: winget_install("OpenJS.NodeJS.LTS", log)),
    "cswap": ("claude-swap", lambda: bool(find("cswap")), install_cswap),
}


def is_ready(key):
    return REQUIREMENTS[key][1]()


def ensure(key, log):
    """Si falta el requisito, lo descarga e instala."""
    name, check, install = REQUIREMENTS[key]
    if check():
        return
    if install is None:
        raise StepError(f"falta {name} y no se puede instalar automáticamente")
    log(f"Falta {name}: instalándolo…")
    install(log)
    refresh_path()
    if not check():
        raise StepError(f"{name} se instaló pero no aparece; cierra y vuelve a abrir la app")
    log(f"✔ {name} listo")


# ── cuentas ────────────────────────────────────────────────────────────────

def claude_login_status():
    """El estado de la sesión de Claude Code, o None si no está instalado."""
    if not find("claude"):
        return None
    try:
        return json.loads(run(["claude", "auth", "status", "--json"], timeout=30))
    except (StepError, ValueError):
        return {"loggedIn": False}


def save_current_account(log):
    ensure("cswap", log)
    run(["cswap", "add"], log)


def add_another_account(log):
    """Guarda la cuenta actual, abre el inicio de sesión de Claude y guarda la nueva."""
    ensure("claude", log)
    ensure("cswap", log)
    before = (claude_login_status() or {}).get("email")
    if before:
        log(f"Guardando la cuenta actual ({before})…")
        try:
            run(["cswap", "add"], log)
        except StepError:
            pass  # ya estaba guardada
    log("Se abre una ventana para iniciar sesión con la otra cuenta. Sigue los pasos del navegador.")
    proc = subprocess.Popen([find("claude"), "auth", "login"], creationflags=NEW_CONSOLE)
    proc.wait()
    after = (claude_login_status() or {}).get("email")
    if not after:
        raise StepError("no se inició sesión")
    if after == before:
        raise StepError(f"sigues con la misma cuenta ({after}); inicia sesión con otra")
    log(f"Guardando la cuenta nueva ({after})…")
    run(["cswap", "add"], log)
    log(f"✔ {after} añadida")


def remove_account(number, log):
    run(["cswap", "remove", str(number)], log, answer="y\n")  # el CLI pide confirmar


def load_state():
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_state(**changes):
    state = load_state()
    state.update(changes)
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state), encoding="utf-8")


def mark_changed():
    """Apunta que se tocaron plugins: las sesiones abiertas antes no lo verán."""
    save_state(last_change=time.time())


def claude_start_times():
    """Cuándo se abrió cada sesión de Claude Code que sigue abierta (segundos Unix)."""
    script = ("Get-Process claude -ErrorAction SilentlyContinue | ForEach-Object { "
              "try { [DateTimeOffset]::new($_.StartTime).ToUnixTimeSeconds() } catch {} }")
    try:
        out = run(["powershell", "-NoProfile", "-Command", script], timeout=30)
    except StepError:
        return []
    return [int(line) for line in out.split() if line.strip().isdigit()]


def restart_needed():
    """Hay alguna sesión de Claude Code abierta desde antes del último cambio."""
    changed = load_state().get("last_change")
    return bool(changed) and any(start < changed for start in claude_start_times())


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


def claude_processes():
    """PIDs de las sesiones de Claude Code abiertas (terminal o VS Code)."""
    try:
        out = run(["tasklist", "/FI", "IMAGENAME eq claude.exe", "/FO", "CSV", "/NH"],
                  timeout=15)
    except StepError:
        return []
    return [line.split('","')[1] for line in out.splitlines() if line.startswith('"claude')]


def close_claude(log):
    """Cierra Claude Code para que al abrirlo de nuevo cargue plugins, hooks y CLAUDE.md."""
    pids = claude_processes()
    if not pids:
        log("No había ninguna sesión de Claude Code abierta.")
    for pid in pids:
        try:
            run(["taskkill", "/PID", pid, "/T", "/F"], log)
        except StepError:
            pass  # ya se había cerrado
    log("Vuelve a abrir Claude Code: en VS Code abre otra vez su panel y en la terminal "
        "escribe 'claude --continue' para seguir donde estabas.")


# ── herramientas para ahorrar tokens ───────────────────────────────────────

def installed_plugins():
    """{plugin_id: activo} de los plugins de Claude Code instalados."""
    if not find("claude"):
        return {}
    try:
        data = json.loads(run(["claude", "plugin", "list", "--json"], timeout=60))
    except (StepError, ValueError):
        return {}
    items = data.get("installed", []) if isinstance(data, dict) else data
    result = {}
    for item in items:
        plugin_id = item.get("pluginId") or item.get("id") or item.get("name")
        if plugin_id:
            result[plugin_id] = item.get("enabled", True)
    return result


class Tool:
    """Una herramienta del catálogo: se instala, se desinstala, se activa y se desactiva.

    status() devuelve "missing", "enabled" o "disabled". saving es la parte de tokens que
    ahorra según las pruebas publicadas (None si nadie lo ha medido) y quality_risk indica
    que nadie ha comprobado si empeora el código.
    """

    def __init__(self, name, description, priority, pros, cons, saving=None,
                 quality_risk=False):
        self.name = name
        self.description = description
        self.priority = priority
        self.pros = pros
        self.cons = cons
        self.saving = saving
        self.quality_risk = quality_risk


class Plugin(Tool):
    """Plugin de Claude Code que se instala desde su marketplace de GitHub."""

    def __init__(self, plugin_id, repo, **info):
        super().__init__(**info)
        self.plugin_id = plugin_id
        self.repo = repo

    def status(self, plugins):
        if self.plugin_id not in plugins:
            return "missing"
        return "enabled" if plugins[self.plugin_id] else "disabled"

    def install(self, log):
        ensure("claude", log)
        run(["claude", "plugin", "install", self.plugin_id.split("@")[0],
             "--marketplace", self.repo], log)

    def uninstall(self, log):
        run(["claude", "plugin", "uninstall", self.plugin_id], log)

    def set_enabled(self, enabled, log):
        run(["claude", "plugin", "enable" if enabled else "disable", self.plugin_id], log)

    def update(self, log):
        run(["claude", "plugin", "update", self.plugin_id], log)


class Rtk(Tool):
    """Programa aparte; activarlo es engancharlo a Claude Code con rtk init."""

    package = "rtk-ai.rtk"

    def status(self, _plugins):
        if not find("rtk"):
            return "missing"
        return "enabled" if (CLAUDE_DIR / "RTK.md").exists() else "disabled"

    def install(self, log):
        if not find("rtk"):
            winget_install(self.package, log)
            refresh_path()
        self.set_enabled(True, log)

    def uninstall(self, log):
        if find("rtk"):
            self.set_enabled(False, log)
        winget_uninstall(self.package, log)

    def set_enabled(self, enabled, log):
        run(["rtk", "init", "-g", "--auto-patch" if enabled else "--uninstall"], log)

    def update(self, log):
        ensure("winget", log)
        run(["winget", "upgrade", "-e", "--id", self.package, "--silent",
             "--disable-interactivity", "--accept-package-agreements",
             "--accept-source-agreements"], log, ok_codes=(0, WINGET_NO_UPDATE))


class ContextCompress(Tool):
    """Paquete de npm; activarlo es registrar su servidor y sus hooks en Claude Code."""

    def status(self, _plugins):
        if not find("context-compress"):
            return "missing"
        try:
            settings = (CLAUDE_DIR / "settings.json").read_text(encoding="utf-8")
        except OSError:
            settings = ""
        return "enabled" if "context-compress" in settings else "disabled"

    def install(self, log):
        ensure("node", log)
        run(["npm", "install", "-g", "context-compress"], log)
        refresh_path()
        self.set_enabled(True, log)

    def uninstall(self, log):
        if find("context-compress"):
            self.set_enabled(False, log)
        run(["npm", "uninstall", "-g", "context-compress"], log)

    def set_enabled(self, enabled, log):
        run(["context-compress", "setup", "--auto"] if enabled
            else ["context-compress", "uninstall"], log)

    def update(self, log):
        run(["npm", "install", "-g", "context-compress@latest"], log)


class ClaudeMdRules(Tool):
    """Unas reglas en un .md que se cargan desde ~/.claude/CLAUDE.md con @archivo."""

    def __init__(self, url, filename, **info):
        super().__init__(**info)
        self.url = url
        self.file = CLAUDE_DIR / filename
        self.line = f"@{filename}"

    def claude_md_lines(self):
        try:
            return (CLAUDE_DIR / "CLAUDE.md").read_text(encoding="utf-8").splitlines()
        except FileNotFoundError:
            return []

    def status(self, _plugins):
        if not self.file.exists():
            return "missing"
        return "enabled" if self.line in self.claude_md_lines() else "disabled"

    def install(self, log):
        self.download(log)
        self.set_enabled(True, log)

    def update(self, log):
        self.download(log)  # si estaba desactivado, sigue desactivado

    def download(self, log):
        log(f"> descargando {self.url}")
        req = urllib.request.Request(self.url, headers={"User-Agent": "ClaudeUsage"})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                text = resp.read().decode("utf-8")
        except OSError as exc:
            raise StepError(f"no se pudo descargar: {exc}") from None
        CLAUDE_DIR.mkdir(exist_ok=True)
        self.file.write_text(text, encoding="utf-8")

    def uninstall(self, log):
        self.set_enabled(False, log)
        self.file.unlink(missing_ok=True)
        log(f"> borrado {self.file}")

    def set_enabled(self, enabled, log):
        lines = [line for line in self.claude_md_lines() if line != self.line]
        if enabled:
            lines.append(self.line)
        CLAUDE_DIR.mkdir(exist_ok=True)
        (CLAUDE_DIR / "CLAUDE.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
        log(f"> {'añadido' if enabled else 'quitado'} {self.line} en CLAUDE.md")


TOOLS = [
    Plugin(
        "ponytail@ponytail", "DietrichGebert/ponytail", name="Ponytail", priority="Alta",
        description="Hace que Claude escriba solo el código necesario, sin complicarlo.",
        pros="El que mejor sale en pruebas independientes (JetBrains): ≈10 % menos de "
             "coste por tarea. Menos código que revisar.",
        cons="En Windows hay un fallo conocido que puede dejar cada mensaje parado unos "
             "segundos. Ahorra menos de lo que anuncia (20 %).",
        saving=0.10, quality_risk=True,
    ),
    Plugin(
        "caveman@caveman", "JuliusBrussee/caveman", name="Caveman", priority="Alta",
        description="Hace que las respuestas de Claude sean mucho más cortas.",
        pros="JetBrains midió ≈8,5 % menos tokens sin perder calidad en el código.",
        cons="Respuestas telegráficas, a veces difíciles de leer. Añade instrucciones a "
             "cada mensaje: en tareas cortas puede no ahorrar nada. Anuncia 65 %.",
        saving=0.085,
    ),
    ClaudeMdRules(
        "https://raw.githubusercontent.com/drona23/claude-token-efficient/main/CLAUDE.md",
        "claude-token-efficient.md", name="claude-token-efficient", priority="Media",
        description="Unas reglas en tu CLAUDE.md para que Claude sea más directo.",
        pros="Sin programas ni riesgos: es solo texto y se quita al momento. En una "
             "prueba bajó ≈40 % los tokens.",
        cons="Esa prueba es una sola y en un proyecto pequeño: aquí contamos solo un 10 % "
             "por prudencia. Se solapa con Caveman y puede chocar con tu CLAUDE.md.",
        saving=0.10, quality_risk=True,
    ),
    Plugin(
        "claude-magic-compact@magic-compact", "aerovato/magic-compact",
        name="Magic Compact", priority="Media",
        description="Conserva el contexto útil en sesiones largas al compactar.",
        pros="En sesiones largas, al compactar se pierde menos de lo que estabas haciendo.",
        cons="Sin pruebas independientes. Si resume mal, Claude puede olvidar parte de lo "
             "que estabais haciendo. En sesiones cortas no aporta nada.",
        quality_risk=True,
    ),
    ContextCompress(
        name="context-compress", priority="Media",
        description="Comprime lo que devuelven las herramientas para gastar menos contexto.",
        pros="Las salidas largas (logs, JSON, webs) entran comprimidas y lo completo se "
             "puede buscar después.",
        cons="Bloquea WebFetch y obliga a usar sus herramientas, que a veces no están "
             "cargadas. Necesita Node. Sin pruebas independientes.",
        quality_risk=True,
    ),
    Rtk(
        name="RTK", priority="Baja",
        description="Quita el ruido de lo que la terminal le devuelve a Claude Code.",
        pros="Resume la salida de git, tests y similares antes de que la lea Claude.",
        cons="JetBrains midió que no ahorra: con esfuerzo bajo sale ≈7,6 % más caro. "
             "En Windows su enganche funciona peor que en Linux o WSL.",
        saving=0.0,
    ),
]


def estimated_spend(tools_enabled):
    """Gasto de tokens que queda (1.0 = sin plugins) con las herramientas activas.

    Los ahorros se multiplican, no se suman: dos del 10 % dejan un 81 %, no un 80 %.
    """
    spend = 1.0
    for tool in tools_enabled:
        spend *= 1 - (tool.saving or 0)
    return spend


def check_tool(tool, expected):
    """Comprueba después de instalar o desinstalar que de verdad quedó así."""
    status = tool.status(installed_plugins())
    if (status != "missing") != expected:
        verb = "instalado" if expected else "desinstalado"
        raise StepError(f"{tool.name} no aparece como {verb}")
    return status
