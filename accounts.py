"""Las cuentas de Claude Code: las guarda y las cambia claude-swap (cswap)."""

import hashlib
import json
import os
import re
import subprocess
import threading
import time
import urllib.request
from pathlib import Path

from prerequisites import ensure
from system import NO_WINDOW, StepError, find, quiet, run


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


def switch_account(number, email=None):
    """Pasa Claude Code a la cuenta number y comprueba que el token que queda puesto es de
    esa cuenta (email). cswap decide qué cuenta hay por ~/.claude.json, y ese archivo puede
    decir una cuenta mientras el token es de otra: entonces gastas de la que no crees."""
    cswap("switch", str(number))
    if not email:
        return
    live = live_email()
    if live and live != email.lower():
        raise StepError(f"cswap dice que ha cambiado, pero Claude Code sigue gastando de "
                        f"{live}. Cierra las sesiones de Claude Code y vuelve a intentarlo")


# ── qué cuenta gasta de verdad Claude Code ──
#
# Claude Code gasta con el token de .credentials.json. Su ~/.claude.json dice qué cuenta
# hay, pero se puede quedar con otra (ver switch_account), y de él se fían cswap, `claude
# auth status` y /usage. El token se le pregunta a Anthropic: una vez por token.

CREDENTIALS = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude") \
    / ".credentials.json"
PROFILE_URL = "https://api.anthropic.com/api/oauth/profile"
PROFILE_RETRY = 300  # segundos sin volver a preguntar por un token que no se pudo leer
_identity = {}       # huella del token -> email (o el momento del fallo)
_identity_lock = threading.Lock()


def _profile_email(token):
    request = urllib.request.Request(PROFILE_URL, headers={
        "Authorization": f"Bearer {token}", "anthropic-beta": "oauth-2025-04-20"})
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            data = json.load(response)
    except (OSError, ValueError):
        return None
    account = data.get("account") if isinstance(data, dict) else None
    email = account.get("email") if isinstance(account, dict) else None
    return email.lower() if isinstance(email, str) and email else None


def live_email(path=None, fetch=_profile_email, now=time.time):
    """El email de la cuenta con la que Claude Code gasta ahora, o None si no se sabe (sin
    sesión, sin internet o con el token caducado hasta que Claude Code lo renueve)."""
    try:
        data = json.loads((path or CREDENTIALS).read_text(encoding="utf-8"))
        token = data["claudeAiOauth"]["accessToken"]
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if not isinstance(token, str) or not token:
        return None
    key = hashlib.sha256(token.encode()).hexdigest()
    with _identity_lock:
        known = _identity.get(key)
    if isinstance(known, str):
        return known
    if isinstance(known, float) and now() - known < PROFILE_RETRY:
        return None
    email = fetch(token)
    with _identity_lock:
        if email:
            _identity.clear()  # solo hace falta el del token de ahora
            _identity[key] = email
        else:
            _identity[key] = float(now())
    return email


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


LOGIN_WAIT = 600     # segundos para terminar el inicio de sesión
LOGIN_URL_WAIT = 30  # segundos para que Claude Code dé el enlace
LOGIN_URL = re.compile(r"https://\S+/oauth/authorize\?\S+")


def wait_login(args, ask_code, wait=LOGIN_WAIT):
    """Inicia sesión en Claude Code sin terminal, pegando el código a mano.

    Claude Code da un enlace para autorizar; ask_code(enlace, terminado) lo enseña (para
    abrirlo en una ventana privada, donde no se cuela la cuenta que el navegador tenga
    abierta en claude.ai) y devuelve el código que da la página al acabar, "" si terminó
    solo (se autorizó en la pestaña que abre Claude Code) o None si se cancela."""
    proc = subprocess.Popen(args, creationflags=NO_WINDOW, stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                            encoding="utf-8", errors="replace")
    lines, found = [], threading.Event()

    def read():
        for line in proc.stdout:
            lines.append(line.strip())
            if LOGIN_URL.search(line):
                found.set()
        found.set()  # se acabó sin dar enlace

    threading.Thread(target=read, daemon=True).start()
    try:
        url = None
        if found.wait(LOGIN_URL_WAIT):
            url = next((m.group() for line in lines if (m := LOGIN_URL.search(line))), None)
        if not url:
            raise StepError(_last(lines) or "Claude Code no ha dado el enlace para iniciar sesión")
        code = ask_code(url, lambda: proc.poll() is not None)
        if code is None:
            raise StepError("cancelado")
        if code and proc.poll() is None:
            proc.stdin.write(code.strip() + "\n")
            proc.stdin.flush()
        proc.wait(timeout=60 if code else wait)
    except subprocess.TimeoutExpired:
        raise StepError("no se terminó de iniciar sesión a tiempo; vuelve a intentarlo") from None
    finally:
        if proc.poll() is None:
            proc.kill()
    if proc.returncode != 0:
        detail = _last(lines)
        if "400" in detail:
            detail = "el código no vale (¿copiado entero y del último intento?)"
        raise StepError(detail or "no se pudo iniciar sesión")


def _last(lines):
    """La última línea con algo que decir de lo que escribió Claude Code."""
    useful = [line.split(">")[-1].strip() for line in lines if line.strip()]
    useful = [line for line in useful if line and not LOGIN_URL.search(line)]
    return useful[-1] if useful else ""


def wrong_browser_account(got, wanted):
    """Claude autoriza la cuenta que el navegador tiene abierta en claude.ai, aunque el
    inicio de sesión lleve otro email puesto: hay que cambiarla allí antes."""
    if not got:
        return "no se terminó de iniciar sesión; vuelve a intentarlo"
    return (f"se ha autorizado {got}, no {wanted}: vuelve a intentarlo abriendo el enlace "
            f"en una ventana privada y entrando con {wanted}")


def save_current_account(log):
    ensure("cswap", log)
    cswap("add", log=log, timeout=120)


def add_another_account(log, ask_code):
    """Guarda la cuenta actual, inicia sesión con otra (ver wait_login) y la guarda."""
    ensure("claude", log)
    ensure("cswap", log)
    before = (claude_login_status() or {}).get("email")
    if before:
        log(f"Guardando la cuenta actual ({before})…")
        try:
            cswap("add", log=log, timeout=120)
        except StepError:
            pass  # ya estaba guardada
    log("Sigue los pasos de la ventana que se ha abierto.")
    wait_login([find("claude"), "auth", "login"], ask_code)
    after = (claude_login_status() or {}).get("email")
    if not after:
        raise StepError("no se inició sesión")
    if after == before:
        raise StepError(wrong_browser_account(after, "la otra cuenta"))
    log(f"Guardando la cuenta nueva ({after})…")
    cswap("add", log=log, timeout=120)
    log(f"✔ {after} añadida")


def relogin(email, log, ask_code, wait=LOGIN_WAIT):
    """Vuelve a iniciar la sesión de Claude Code de una cuenta guardada cuya sesión caducó
    (ver wait_login), guarda la sesión nueva en cswap y deja Claude Code con la cuenta que
    tenía antes."""
    ensure("claude", log)
    ensure("cswap", log)
    previous = next((acc for acc in list_accounts() if acc.get("active")), None)
    log("Sigue los pasos de la ventana que se ha abierto.")
    wait_login([find("claude"), "auth", "login", "--email", email], ask_code, wait)
    got = (claude_login_status() or {}).get("email")
    try:
        if got != email:
            raise StepError(wrong_browser_account(got, email))
        log(f"Guardando la sesión nueva de {email}…")
        cswap("add", log=log, timeout=120)  # con la cuenta ya guardada, la renueva
    finally:
        # Claude Code vuelve a la cuenta que tenía, haya ido bien o no
        if previous and previous.get("email") != got:
            log(f"Claude Code vuelve a {previous.get('email')}…")
            switch_account(previous["number"])
    log(f"✔ Sesión de {email} renovada")
