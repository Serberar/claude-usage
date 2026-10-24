"""Las sesiones de Claude Code abiertas: los plugins nuevos solo se cargan al abrir una."""

import re
import time

from state import load_state, save_state
from system import StepError, run


def claude_sessions():
    """(PID, cuándo se abrió en segundos Unix) de cada sesión de Claude Code abierta.

    Si Windows no deja leer la hora de inicio, cuenta como 0 (abierta desde siempre).
    """
    script = ("Get-Process claude -ErrorAction SilentlyContinue | ForEach-Object { "
              "$t = try { [DateTimeOffset]::new($_.StartTime).ToUnixTimeSeconds() } catch { 0 }; "
              "\"$($_.Id) $t\" }")
    try:
        out = run(["powershell", "-NoProfile", "-Command", script], timeout=30)
    except StepError:
        return []
    return [tuple(map(int, line.split())) for line in out.splitlines()
            if re.fullmatch(r"\d+ \d+", line.strip())]


def mark_changed():
    """Apunta que se tocaron plugins: las sesiones abiertas antes no lo verán."""
    save_state(last_change=time.time())


def restart_needed():
    """Hay alguna sesión de Claude Code abierta desde antes del último cambio."""
    changed = load_state().get("last_change")
    return bool(changed) and any(start < changed for _pid, start in claude_sessions())


def close_claude(log):
    """Cierra Claude Code para que al abrirlo de nuevo cargue plugins, hooks y CLAUDE.md."""
    sessions = claude_sessions()
    if not sessions:
        log("No había ninguna sesión de Claude Code abierta.")
    for pid, _start in sessions:
        try:
            run(["taskkill", "/PID", str(pid), "/T", "/F"], log)
        except StepError:
            pass  # ya se había cerrado
    log("Vuelve a abrir Claude Code: en VS Code abre otra vez su panel y en la terminal "
        "escribe 'claude --continue' para seguir donde estabas.")
