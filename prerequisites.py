"""Lo que necesitan la app y los plugins (Claude Code, claude-swap, uv, Node, winget) y cómo
instalarlo si falta."""

import re

from system import StepError, find, refresh_path, run


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
