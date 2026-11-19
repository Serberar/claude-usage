"""Las cuentas de Claude Code: las guarda y las cambia claude-swap (cswap)."""

import json
import subprocess

from prerequisites import ensure
from system import NEW_CONSOLE, StepError, find, quiet, run


def cswap(*args, log=quiet, answer=None, timeout=60, ok_codes=(0,)):
    if not find("cswap"):
        raise StepError("Falta claude-swap: instálalo desde la pestaña Ajustes.")
    return run(["cswap", *args], log, timeout=timeout, answer=answer, ok_codes=ok_codes)


SCHEMA_VERSION = 1  # el formato de `cswap list --json` que conoce esta versión de la app
_schema_seen = None


def list_accounts():
    """Las cuentas con su consumo, como las da `cswap list --json`."""
    global _schema_seen
    try:
        data = json.loads(cswap("list", "--json"))
    except ValueError:
        raise StepError("claude-swap ha devuelto algo que no se entiende; "
                        "prueba a actualizarlo") from None
    if not isinstance(data, dict) or not isinstance(data.get("accounts", []), list):
        raise StepError("claude-swap ha devuelto algo que no se entiende; "
                        "prueba a actualizarlo")
    _schema_seen = data.get("schemaVersion")
    return [acc for acc in data.get("accounts", []) if isinstance(acc, dict)]


def schema_too_new():
    """claude-swap usa un formato más nuevo del que conoce la app (se lee lo que se puede)."""
    return isinstance(_schema_seen, int) and _schema_seen > SCHEMA_VERSION


def switch_account(number):
    cswap("switch", str(number))


def auto_switch(threshold):
    """Una pasada del cambio automático de cswap (`cswap auto --once`): si la cuenta en uso
    llega al umbral en el límite que va peor, cambia a la que tiene más margen. Devuelve la
    cuenta a la que ha cambiado ({number, email}) o None."""
    out = cswap("auto", "--once", "--json", "--threshold", str(threshold),
                ok_codes=(0, 2, 3))  # 2: no hacía falta; 3: no había otra cuenta con margen
    for line in out.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if event.get("event") == "switch" and not event.get("dryRun"):
            return event.get("to")
    return None


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


LOGIN_WAIT = 600  # segundos para terminar el inicio de sesión en el navegador


def wait_login(args, wait=LOGIN_WAIT):
    """Abre el inicio de sesión de Claude en su ventana y espera a que acabe (como mucho
    wait segundos: si se deja a medias, la app no se queda esperando para siempre)."""
    proc = subprocess.Popen(args, creationflags=NEW_CONSOLE)
    try:
        proc.wait(timeout=wait)
    except subprocess.TimeoutExpired:
        proc.kill()
        raise StepError("no se terminó de iniciar sesión a tiempo; vuelve a intentarlo") from None


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
    wait_login([find("claude"), "auth", "login"])
    after = (claude_login_status() or {}).get("email")
    if not after:
        raise StepError("no se inició sesión")
    if after == before:
        raise StepError(f"sigues con la misma cuenta ({after}); inicia sesión con otra")
    log(f"Guardando la cuenta nueva ({after})…")
    cswap("add", log=log, timeout=120)
    log(f"✔ {after} añadida")


def relogin(email, log, wait=LOGIN_WAIT):
    """Vuelve a iniciar la sesión de Claude Code de una cuenta guardada cuya sesión caducó.

    Abre el inicio de sesión de Claude con su email ya puesto (en el navegador basta con
    pulsar Autorizar si ya estás dentro de claude.ai con esa cuenta), guarda la sesión
    nueva en cswap y deja Claude Code con la cuenta que tenía antes."""
    ensure("claude", log)
    ensure("cswap", log)
    previous = next((acc for acc in list_accounts() if acc.get("active")), None)
    log(f"Se abre el navegador para iniciar sesión con {email}: pulsa Autorizar.")
    wait_login([find("claude"), "auth", "login", "--email", email], wait)
    got = (claude_login_status() or {}).get("email")
    try:
        if got != email:
            raise StepError(f"se inició sesión con {got or 'ninguna cuenta'}, no con {email}")
        log(f"Guardando la sesión nueva de {email}…")
        cswap("add", log=log, timeout=120)  # con la cuenta ya guardada, la renueva
    finally:
        # Claude Code vuelve a la cuenta que tenía, haya ido bien o no
        if previous and previous.get("email") != got:
            log(f"Claude Code vuelve a {previous.get('email')}…")
            switch_account(previous["number"])
    log(f"✔ Sesión de {email} renovada")
