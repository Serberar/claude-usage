"""Las herramientas para gastar menos tokens en Claude Code: qué tipos hay (plugin de Claude
Code, programa aparte, paquete de npm, reglas en CLAUDE.md), cómo se instalan, activan,
actualizan y quitan, y lo que dice Claude Code de las instaladas."""

import json
import urllib.request
from pathlib import Path

from prerequisites import ensure, winget_install, winget_uninstall
from system import StepError, find, refresh_path, run, write_atomic

CLAUDE_DIR = Path.home() / ".claude"
WINGET_NO_UPDATE = -1978335189  # winget upgrade cuando ya está en la última versión
QUALITY = {"no_afecta": "No afecta", "sin_probar": "Sin probar", "empeora": "Empeora"}


# ── lo que dice Claude Code ───────────────────────────────────────────────────

def catalog_version(folder, name):
    """La versión de un plugin según el catálogo local de su marketplace (o None)."""
    try:
        catalog = json.loads((folder / ".claude-plugin" / "marketplace.json")
                             .read_text(encoding="utf-8"))
        entry = next(p for p in catalog.get("plugins", []) if p.get("name") == name)
        if entry.get("version"):
            return entry["version"]
        source = entry.get("source")
        if isinstance(source, dict):  # paquete de npm u otro origen con su versión fijada
            return source.get("version")
        if isinstance(source, str):  # carpeta dentro del repositorio del marketplace
            manifest = folder / source / ".claude-plugin" / "plugin.json"
            return json.loads(manifest.read_text(encoding="utf-8")).get("version")
    except (OSError, ValueError, StopIteration, TypeError):
        pass
    return None


def plugin_list():
    """Los plugins instalados en Claude Code: {plugin_id: {"enabled", "version", "latest",
    "repo"}}. latest es la versión del catálogo local de su marketplace (lo pone al día
    refresh_marketplaces) y repo, el repositorio de GitHub de ese marketplace."""
    if not find("claude"):
        return {}
    try:
        data = json.loads(run(["claude", "plugin", "list", "--json"], timeout=60))
        markets = json.loads(run(["claude", "plugin", "marketplace", "list", "--json"],
                                 timeout=60))
    except (StepError, ValueError):
        return {}
    folders = {m.get("name"): m for m in markets if isinstance(m, dict)}
    items = data.get("installed", []) if isinstance(data, dict) else data
    result = {}
    for item in items:
        plugin_id = item.get("id") or item.get("pluginId") or item.get("name")
        if not plugin_id:
            continue
        name, _, market_name = plugin_id.partition("@")
        market = folders.get(market_name, {})
        folder = market.get("installLocation")
        result[plugin_id] = {
            "enabled": item.get("enabled", True),
            "version": item.get("version"),
            "latest": catalog_version(Path(folder), name) if folder else None,
            "repo": market.get("repo"),
        }
    return result


def refresh_marketplaces(log):
    """Trae de GitHub los catálogos de los marketplaces: así se ve si hay versiones nuevas."""
    run(["claude", "plugin", "marketplace", "update"], log, timeout=300)


# ── las herramientas ──────────────────────────────────────────────────────────

class Tool:
    """Una herramienta: se instala, se desinstala, se activa y se desactiva.

    status() devuelve "missing", "enabled" o "disabled". saving es la parte de tokens que
    ahorra según las pruebas publicadas (None si nadie lo ha medido) y quality, lo que se
    sabe de cómo afecta a la calidad del código (una clave de QUALITY).
    """

    custom = False
    edited = False  # ficha del catálogo cambiada en Ajustes

    def __init__(self, name, description, pros, cons, saving=None, quality="no_afecta",
                 has_options=False):
        self.name = name
        self.description = description
        self.pros = pros
        self.cons = cons
        self.saving = saving
        self.quality = quality
        self.has_options = has_options

    def versions(self, _plugins):
        """(instalada, publicada), o None si no hay forma de saberlo."""
        return None


class Plugin(Tool):
    """Plugin de Claude Code que se instala desde su marketplace de GitHub."""

    def __init__(self, plugin_id, repo, **info):
        super().__init__(**info)
        self.plugin_id = plugin_id
        self.repo = repo

    def status(self, plugins):
        if self.plugin_id not in plugins:
            return "missing"
        return "enabled" if plugins[self.plugin_id]["enabled"] else "disabled"

    def versions(self, plugins):
        info = plugins.get(self.plugin_id, {})
        return info.get("version"), info.get("latest")

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


class CustomPlugin(Plugin):
    """Plugin añadido desde Ajustes. Su id completo (nombre@marketplace) se sabe al instalarlo:
    el marketplace lo nombra su propio repositorio. Se reconoce por nombre y repositorio, para
    no confundirlo con otro que se llame igual."""

    custom = True

    def status(self, plugins):
        name = self.plugin_id.split("@")[0]
        for plugin_id, info in plugins.items():
            same_repo = (info.get("repo") or "").lower() == self.repo.lower()
            if plugin_id.split("@")[0] == name and same_repo:
                self.plugin_id = plugin_id
                return "enabled" if info["enabled"] else "disabled"
        return "missing"


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

    def claude_md(self):
        """(líneas de tu CLAUDE.md, el salto de línea que usa). Se lee sin descodificar del
        todo (surrogateescape) para no estropear un CLAUDE.md que no sea UTF-8."""
        try:
            raw = (CLAUDE_DIR / "CLAUDE.md").read_bytes()
        except FileNotFoundError:
            return [], "\n"
        eol = "\r\n" if b"\r\n" in raw else "\n"
        return raw.decode("utf-8", errors="surrogateescape").splitlines(), eol

    def status(self, _plugins):
        if not self.file.exists():
            return "missing"
        return "enabled" if self.line in self.claude_md()[0] else "disabled"

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
        write_atomic(self.file, text)

    def uninstall(self, log):
        self.set_enabled(False, log)
        self.file.unlink(missing_ok=True)
        log(f"> borrado {self.file}")

    def set_enabled(self, enabled, log):
        lines, eol = self.claude_md()
        lines = [line for line in lines if line != self.line]
        if enabled:
            lines.append(self.line)
        # es el CLAUDE.md del usuario: nunca a medias, y con sus saltos de línea
        write_atomic(CLAUDE_DIR / "CLAUDE.md", eol.join(lines) + eol, errors="surrogateescape")
        log(f"> {'añadido' if enabled else 'quitado'} {self.line} en CLAUDE.md")


# ── cuentas de lo que hay ─────────────────────────────────────────────────────

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
    status = tool.status(plugin_list())
    if (status != "missing") != expected:
        verb = "instalado" if expected else "desinstalado"
        raise StepError(f"{tool.name} no aparece como {verb}")
    return status
