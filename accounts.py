"""Las cuentas de Claude Code: las guarda y las cambia claude-swap (cswap)."""

import json
import subprocess

from prerequisites import ensure
from system import NEW_CONSOLE, StepError, find, quiet, run


def cswap(*args, log=quiet, answer=None, timeout=60):
    if not find("cswap"):
        raise StepError("Falta claude-swap: instálalo desde la pestaña Ajustes.")
    return run(["cswap", *args], log, timeout=timeout, answer=answer)


def list_accounts():
    """Las cuentas con su consumo, como las da `cswap list --json`."""
    return json.loads(cswap("list", "--json")).get("accounts", [])


def switch_account(number):
    cswap("switch", str(number))


def set_alias(number, alias, log):
    """alias vacío lo quita. cswap lo guarda en minúsculas."""
    cswap("alias", str(number), alias or "--unset", log=log)


def remove_account(number, log):
    cswap("remove", str(number), log=log, answer="y\n")  # el CLI pide confirmar


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
    cswap("add", log=log, timeout=120)


def add_another_account(log):
    """Guarda la cuenta actual, abre el inicio de sesión de Claude y guarda la nueva."""
    ensure("claude", log)
    ensure("cswap", log)
    before = (claude_login_status() or {}).get("email")
    if before:
        log(f"Guardando la cuenta actual ({before})…")
        try:
            cswap("add", log=log, timeout=120)
        except StepError:
            pass  # ya estaba guardada
    log("Se abre una ventana para iniciar sesión con la otra cuenta. Sigue los pasos del navegador.")
    subprocess.Popen([find("claude"), "auth", "login"], creationflags=NEW_CONSOLE).wait()
    after = (claude_login_status() or {}).get("email")
    if not after:
        raise StepError("no se inició sesión")
    if after == before:
        raise StepError(f"sigues con la misma cuenta ({after}); inicia sesión con otra")
    log(f"Guardando la cuenta nueva ({after})…")
    cswap("add", log=log, timeout=120)
    log(f"✔ {after} añadida")
