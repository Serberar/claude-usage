"""Cosas de Windows: que la app se abra una sola vez y el icono de junto al reloj."""

import socket
import sys
from pathlib import Path

INSTANCE_PORT = 47821  # puerto local con el que la app detecta si ya está abierta
NOTIFY_ROOT = r"Control Panel\NotifyIconSettings"


# ── una sola instancia ────────────────────────────────────────────────────────

def listen_for_other_instances():
    """Ocupa el puerto de la app; devuelve None si ya lo tiene otra instancia."""
    sock = socket.socket()
    if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
    try:
        sock.bind(("127.0.0.1", INSTANCE_PORT))
    except OSError:
        sock.close()
        return None
    sock.listen()
    return sock


def notify_running_instance(show):
    """Avisa a la instancia abierta; True si contestó (y esta debe cerrarse). Si el puerto
    lo tiene otro programa no contesta "ok", y la app se abre igual."""
    try:
        with socket.create_connection(("127.0.0.1", INSTANCE_PORT), timeout=2) as conn:
            conn.sendall(b"show" if show else b"ping")
            return conn.recv(2) == b"ok"
    except OSError:
        return False


def serve_other_instances(listener, on_show):
    """Atiende a las copias que se abren después; on_show se llama al pedir la ventana."""
    while True:
        try:
            conn, _addr = listener.accept()
        except OSError:  # se cerró el socket porque la app se está actualizando
            return
        with conn:
            conn.settimeout(2)
            try:
                message = conn.recv(16)
                conn.sendall(b"ok")
            except OSError:
                continue
        if message == b"show":
            on_show()


# ── el icono junto al reloj (Windows 11) ──────────────────────────────────────

def tray_icon_entries():
    """Las entradas de Windows 11 del icono de este .exe junto al reloj: {clave: IsPromoted}.
    IsPromoted es None si nadie lo ha decidido aún en Configuración. Vacío en Windows 10."""
    entries = {}
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, NOTIFY_ROOT) as settings:
            for i in range(winreg.QueryInfoKey(settings)[0]):
                name = winreg.EnumKey(settings, i)
                with winreg.OpenKey(settings, name) as handle:
                    try:
                        path = winreg.QueryValueEx(handle, "ExecutablePath")[0]
                    except OSError:
                        continue
                    if Path(path) != Path(sys.executable):
                        continue
                    key = rf"{NOTIFY_ROOT}\{name}"
                    try:
                        entries[key] = bool(winreg.QueryValueEx(handle, "IsPromoted")[0])
                    except OSError:
                        entries[key] = None
    except OSError:  # Windows 10 (no tiene esta clave) u otro sistema
        pass
    return entries


def set_tray_icon_visible(visible, keys=None):
    import winreg
    for key in keys or tray_icon_entries():
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key, 0, winreg.KEY_SET_VALUE) as handle:
            winreg.SetValueEx(handle, "IsPromoted", 0, winreg.REG_DWORD, int(visible))


def pin_tray_icon():
    """Windows 11 esconde los iconos nuevos tras la flecha: el % se ve siempre junto al reloj.
    Solo si el usuario no lo ha decidido ya (en Configuración o en Ajustes)."""
    undecided = [key for key, value in tray_icon_entries().items() if value is None]
    if undecided:
        try:
            set_tray_icon_visible(True, undecided)
        except OSError:
            pass
