"""Ejecutar programas de fuera y escribir archivos sin dejarlos a medias."""

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
NEW_CONSOLE = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
LOCAL_BIN = Path.home() / ".local" / "bin"


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
    # abierta desde PowerShell 7 hereda sus rutas de módulos: el PowerShell de Windows no
    # carga los suyos y comandos como Get-FileHash (los usa el instalador de Claude) no existen
    if Path(exe).stem.lower() == "powershell":
        env = {k: v for k, v in env.items() if k.upper() != "PSMODULEPATH"}
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
        detail = (proc.stderr or proc.stdout).strip().splitlines()
        raise StepError(detail[-1] if detail else f"{args[0]} falló (código {proc.returncode})")
    return proc.stdout


def write_atomic(path, text, encoding="utf-8", errors="strict"):
    """Escribe en un archivo temporal al lado y lo pone en su sitio de golpe: si algo se corta
    a mitad, queda el archivo de antes entero, nunca uno a medias. Los saltos de línea van
    tal cual vienen en text."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, tmp = tempfile.mkstemp(dir=path.parent, prefix=f"{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding=encoding, errors=errors, newline="") as out:
            out.write(text)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
