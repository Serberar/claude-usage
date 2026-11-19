"""La app de escritorio de Claude: qué cuenta tiene abierta, el consumo que apunta y
cambiarla de cuenta.

La app de escritorio guarda su sesión aparte de Claude Code (cswap no la ve): cookies,
almacenamiento del navegador y unos tokens en config.json, todo en %APPDATA%\\Claude.
Para cambiarla de cuenta se cierra, se guarda esa sesión en
%APPDATA%\\ClaudeUsage\\desktop\\<organización>, se pone la de la otra cuenta y se abre.
La primera vez que se pasa a una cuenta no hay sesión guardada: la app sale en la
pantalla de inicio de sesión y, a partir de ahí, ya se guarda sola.

Además apunta el consumo de la cuenta en plan-usage-history.json, así que se ve aunque
cswap no pueda leerlo (por ejemplo, si la sesión de Claude Code de esa cuenta caducó).
"""

import json
import os
import re
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

from applog import log as log_file
from state import STATE_FILE, load_state, save_state
from system import NO_WINDOW, StepError, run, write_atomic

DATA = Path(os.environ.get("APPDATA", Path.home())) / "Claude"
INSTALL = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "AnthropicClaude"
PROFILES = STATE_FILE.parent / "desktop"
LOG = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Claude" / "logs" / "main.log"
# lo que cambia de una cuenta a otra; el resto (ajustes, caché, sesiones de Code) se queda
SESSION_DIRS = ("Network", "Local Storage", "Session Storage", "IndexedDB", "WebStorage")
CONFIG_KEYS = ("lastKnownAccountUuid",)
CONFIG_PREFIXES = ("oauth:",)
ALLOWLIST = "dxt:allowlistLastUpdated:"  # lo escribe al entrar en cada organización
FILES_FREE_WAIT = 15  # segundos esperando a que Windows suelte los archivos de la app


def installed(data=DATA, install=INSTALL):
    return (install / "claude.exe").exists() and data.exists()


def _read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def usage_samples(data=DATA):
    """Lo que apunta la app de escritorio de su consumo: [{t (ms), org, u: {fh, sd}}]."""
    samples = _read_json(data / "plan-usage-history.json").get("samples")
    return [s for s in samples or [] if isinstance(s, dict) and s.get("org")
            and isinstance(s.get("t"), (int, float)) and isinstance(s.get("u"), dict)]


def latest_samples(samples):
    """El último dato de consumo de cada organización."""
    latest = {}
    for sample in samples:
        if sample["t"] >= latest.get(sample["org"], {}).get("t", -1):
            latest[sample["org"]] = sample
    return latest


def _ms(value):
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp() * 1000
    except (AttributeError, ValueError):
        return None


ORG_CHANGED = re.compile(
    r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)\S* .*Org changed from \S+ to ([0-9a-f-]{36})")
LOG_TAIL = 2_000_000  # bytes del final del registro que se leen (crece mucho)


def log_org_changes(log=LOG):
    """Cuándo entró la app de escritorio en cada organización, según su registro: lo
    apunta en el momento de entrar ("Org changed from … to …"). [(ms, organización)]."""
    try:
        with open(log, "rb") as handle:
            handle.seek(max(0, log.stat().st_size - LOG_TAIL))
            lines = handle.read().decode("utf-8", errors="replace").splitlines()
    except OSError:
        return []
    events = []
    for line in lines:
        match = ORG_CHANGED.match(line)
        if match:
            when = datetime.strptime(match.group(1), "%Y-%m-%d %H:%M:%S")  # hora local
            events.append((when.timestamp() * 1000, match.group(2)))
    return events


def current_org(data=DATA, switched=None, log=None):
    """La organización con la que está la app de escritorio: la última de la que apuntó
    algo (consumo, entrada en la organización, su lista de plugins) o a la que la
    cambiamos nosotros. Si tras cambiarla se entra con otra cuenta, gana esa."""
    events = [(s["t"], s["org"]) for s in usage_samples(data)]
    for key, value in _read_json(data / "config.json").items():
        when = _ms(value) if key.startswith(ALLOWLIST) else None
        if when:
            events.append((when, key[len(ALLOWLIST):]))
    # plugin-list/<cuenta>/<organización>/plugins.json: lo escribe al rato de entrar
    for plugins in (data / "plugin-list").glob("*/*/plugins.json"):
        try:
            events.append((plugins.stat().st_mtime * 1000, plugins.parent.name))
        except OSError:
            pass
    events += log_org_changes(LOG if log is None else log)
    switched = load_state().get("desktop_switch") if switched is None else switched
    if switched and switched.get("org"):
        events.append((switched.get("at", 0) * 1000, switched["org"]))
    return max(events)[1] if events else None


# ── la sesión guardada de cada cuenta ──

def _profile(org, profiles=PROFILES):
    return profiles / "".join(c for c in org if c.isalnum() or c == "-")


def has_profile(org, profiles=PROFILES):
    return bool(org) and (_profile(org, profiles) / "config.json").exists()


def _session_keys(config):
    return {k: v for k, v in config.items()
            if k in CONFIG_KEYS or k.startswith(CONFIG_PREFIXES)}


def save_profile(org, data=DATA, profiles=PROFILES):
    """Copia la sesión de la app de escritorio (cerrada) a la carpeta de esa cuenta. Se
    copia a una carpeta nueva y luego se cambia por la vieja: nunca queda una a medias."""
    target = _profile(org, profiles)
    tmp = target.with_name(target.name + ".nuevo")
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    for name in SESSION_DIRS:
        if (data / name).exists():
            _copy_when_free(data / name, tmp / name)
    keys = _session_keys(_read_json(data / "config.json"))
    write_atomic(tmp / "config.json", json.dumps(keys, ensure_ascii=False, indent=2))
    old = target.with_name(target.name + ".viejo")
    shutil.rmtree(old, ignore_errors=True)
    if target.exists():
        target.rename(old)
    tmp.rename(target)
    shutil.rmtree(old, ignore_errors=True)


def _copy_when_free(source, target, wait=FILES_FREE_WAIT):
    """Copia una carpeta. Recién cerrada la app, Windows puede tardar unos segundos en
    soltar sus archivos (las cookies): se reintenta en vez de fallar a la primera."""
    deadline = time.time() + wait
    while True:
        try:
            shutil.copytree(source, target, dirs_exist_ok=True)
            return
        except (shutil.Error, PermissionError):
            if time.time() > deadline:
                raise StepError("la app de escritorio sigue usando sus archivos; ciérrala del "
                                "todo (también del icono junto al reloj) y vuelve a "
                                "intentarlo") from None
            time.sleep(1)


def restore_profile(org, data=DATA, profiles=PROFILES):
    """Pone la sesión guardada de esa cuenta; sin sesión guardada, la deja sin sesión para
    que la app pida iniciarla. Devuelve si había una guardada."""
    source = _profile(org, profiles) if org else None
    saved = bool(source) and (source / "config.json").exists()
    for name in SESSION_DIRS:
        shutil.rmtree(data / name, ignore_errors=True)
        if (data / name).exists():
            raise StepError(f"no se pudo quitar {name}: ¿sigue abierta la app de escritorio?")
        if saved and (source / name).exists():
            shutil.copytree(source / name, data / name)
    config = _read_json(data / "config.json")
    config = {k: v for k, v in config.items() if k not in _session_keys(config)}
    if saved:
        config.update(_session_keys(_read_json(source / "config.json")))
    write_atomic(data / "config.json", json.dumps(config, ensure_ascii=False, indent=2))
    return saved


# ── abrir y cerrar la app de escritorio ──

def _is_desktop(path):
    """Los claude.exe de la app de escritorio (y los Claude Code que lanza ella), no los
    de Claude Code de la terminal o de VS Code, que se llaman igual."""
    path = str(path or "").lower()
    return path.startswith((str(INSTALL).lower(), str(DATA).lower()))


def desktop_pids():
    script = ("Get-Process claude -ErrorAction SilentlyContinue | "
              "ForEach-Object { \"$($_.Id)|$($_.Path)\" }")
    try:
        out = run(["powershell", "-NoProfile", "-Command", script], timeout=30)
    except StepError:
        return []
    pids = []
    for line in out.splitlines():
        pid, _sep, path = line.strip().partition("|")
        if pid.isdigit() and _is_desktop(path):
            pids.append(int(pid))
    return pids


def close_desktop(log, wait=15):
    """Cierra la app de escritorio. Devuelve si estaba abierta. Directamente a la fuerza:
    cerrarla como el botón de cerrar no funciona (Windows contesta que solo se puede de
    forma forzada) y solo hacía esperar."""
    pids = desktop_pids()
    if not pids:
        return False
    log("Cerrando la app de escritorio…")
    deadline = time.time() + wait
    while pids:
        args = ["taskkill", "/F", "/T"] + [part for pid in pids for part in ("/PID", str(pid))]
        try:
            run(args, ok_codes=(0, 128, 255))  # 128: alguno ya se había cerrado
        except StepError:
            pass
        time.sleep(1)
        pids = desktop_pids()
        if pids and time.time() > deadline:
            raise StepError("la app de escritorio no se cierra")
    time.sleep(1)  # que Windows suelte sus archivos
    return True


def open_desktop():
    exe = INSTALL / "claude.exe"
    if exe.exists():
        subprocess.Popen([str(exe)], creationflags=NO_WINDOW, close_fds=True,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)


def switch_desktop(target_org, log):
    """Cierra la app de escritorio, guarda la sesión de la cuenta que tenía, pone la de
    target_org y la vuelve a abrir. Devuelve si target_org tenía sesión guardada (si no,
    la app pedirá iniciar sesión con esa cuenta)."""
    if not installed():
        raise StepError("no está instalada la app de escritorio de Claude")
    current = current_org()
    log_file.info("escritorio: de %s a %s", current, target_org)
    close_desktop(log)
    try:
        if current:
            log("Guardando la sesión de la cuenta que tenía…")
            save_profile(current)
        elif any((DATA / name).exists() for name in SESSION_DIRS):
            save_profile("sin-identificar")  # por si acaso: no se pierde nada
        if current == target_org:
            return True  # ya estaba en esa cuenta: se deja como estaba (y ya se ha guardado)
        saved = restore_profile(target_org)
        save_state(desktop_switch={"org": target_org, "at": time.time()})
        log("Sesión puesta." if saved else
            "Esta cuenta aún no tenía sesión guardada: inicia sesión en la app con ella.")
        return saved
    finally:
        open_desktop()


def sample_time(sample):
    return datetime.fromtimestamp(sample["t"] / 1000, timezone.utc)
