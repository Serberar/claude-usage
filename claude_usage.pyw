"""Claude Usage: consumo de las cuentas de Claude Code, gestión de cuentas y plugins."""

import json
import os
import queue
import re
import shutil
import socket
import subprocess
import sys
import threading
import tkinter as tk
import tkinter.messagebox as messagebox
import urllib.request
import webbrowser
from datetime import datetime, timezone
from pathlib import Path

import customtkinter as ctk
from PIL import Image, ImageDraw, ImageFont

import setup_tools

try:
    import pystray
except ImportError:  # sin icono en la bandeja, la ventana sigue funcionando
    pystray = None

VERSION = "1.2.0"
REPO = "Serberar/claude-usage"
RELEASES_URL = f"https://github.com/{REPO}/releases/latest"
INSTALLER_ID = "7F4AB592-8EFE-486C-AC71-466940D30782"  # AppId de installer.iss

REFRESH_MS = 60_000      # cada cuánto se vuelve a consultar cswap
TICK_MS = 30_000         # cada cuánto se recalculan las cuentas atrás
INSTANCE_PORT = 47821    # puerto local con el que la app detecta si ya está abierta
UPDATE_CHECK_MS = 6 * 3600_000  # cada cuánto se mira si hay versión nueva

# la ventana y su barra de título siguen el tema de Windows (claro u oscuro)
ctk.set_appearance_mode("system")

# (claro, oscuro): CustomTkinter usa el que toque según el tema
BG = ("#f3f4f7", "#0e1015")
CARD = ("#ffffff", "#171a21")
CARD_ALT = ("#f5f6f8", "#1d2129")
BORDER = ("#e2e5ea", "#262b35")
TRACK = ("#e7e9ee", "#272c36")
TEXT = ("#14171c", "#eef0f5")
MUTED = ("#6b7280", "#8d95a6")
ACCENT = ("#c96442", "#e07b56")
ACCENT_HOVER = ("#b35838", "#c96a47")
ON_ACCENT = "#ffffff"
GREEN = ("#15803d", "#4ade80")
AMBER = ("#b45309", "#fbbf24")
ORANGE = ("#c2410c", "#fb923c")
RED = ("#dc2626", "#f87171")
FONT = "Segoe UI Variable Text"  # Windows 11; en Windows 10 Tk usa la de por defecto
MONO = "Cascadia Mono"

DIAS = ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"]
MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]

def font(size, bold=False):
    return (FONT, size, "bold") if bold else (FONT, size)


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
    """Avisa a la instancia abierta; True si respondió (y esta debe cerrarse)."""
    try:
        with socket.create_connection(("127.0.0.1", INSTANCE_PORT), timeout=2) as conn:
            conn.sendall(b"show" if show else b"ping")
        return True
    except OSError:
        return False


def version_tuple(tag):
    return tuple(int(n) for n in re.findall(r"\d+", tag)[:3])


def github_request(url, timeout):
    req = urllib.request.Request(url, headers={"User-Agent": f"ClaudeUsage/{VERSION}"})
    return urllib.request.urlopen(req, timeout=timeout)


def fetch_newer_release():
    """La última release de GitHub si es más nueva que esta versión; si no, None."""
    with github_request(f"https://api.github.com/repos/{REPO}/releases/latest", 15) as resp:
        release = json.load(resp)
    if version_tuple(release.get("tag_name", "")) <= version_tuple(VERSION):
        return None
    return release


def exe_asset(release):
    for asset in release.get("assets", []):
        if asset.get("name", "").lower() == "claudeusage.exe":
            return asset
    return None


def can_self_update(release):
    """Solo el .exe compilado se puede reemplazar a sí mismo."""
    return getattr(sys, "frozen", False) and exe_asset(release) is not None


def download_update(release):
    """Descarga el .exe nuevo junto al actual (ClaudeUsage.new.exe)."""
    current = Path(sys.executable)
    new = current.with_name(current.stem + ".new.exe")
    asset = exe_asset(release)
    with github_request(asset["browser_download_url"], 300) as resp, open(new, "wb") as out:
        shutil.copyfileobj(resp, out)
    # urllib no avisa si la conexión se corta a mitad: se comprueba el tamaño
    with open(new, "rb") as f:
        valid = f.read(2) == b"MZ" and new.stat().st_size == asset.get("size")
    if not valid:
        new.unlink()
        raise RuntimeError("la descarga llegó incompleta; vuelve a intentarlo")
    return new


def install_update(new):
    """Pone el .exe nuevo en el sitio del actual; el viejo queda como .old.exe."""
    current = Path(sys.executable)
    old = current.with_name(current.stem + ".old.exe")
    old.unlink(missing_ok=True)
    current.rename(old)  # Windows deja renombrar un .exe que está en marcha
    try:
        new.rename(current)
    except OSError:
        old.rename(current)
        raise
    return current


def sync_installed_version():
    """Si se instaló con el instalador, que Windows muestre la versión tras actualizarse sola."""
    try:
        import winreg
        key = rf"Software\Microsoft\Windows\CurrentVersion\Uninstall\{{{INSTALLER_ID}}}_is1"
        access = winreg.KEY_READ | winreg.KEY_SET_VALUE
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key, 0, access) as handle:
            folder = winreg.QueryValueEx(handle, "InstallLocation")[0]
            if Path(sys.executable).parent == Path(folder):  # no un .exe portable suelto
                winreg.SetValueEx(handle, "DisplayVersion", 0, winreg.REG_SZ, VERSION)
    except OSError:  # no está instalada (o no es Windows)
        pass


def remove_update_leftovers():
    sync_installed_version()
    if not getattr(sys, "frozen", False):
        return
    current = Path(sys.executable)
    for suffix in (".old.exe", ".new.exe"):
        try:
            current.with_name(current.stem + suffix).unlink(missing_ok=True)
        except OSError:  # la versión vieja aún se está cerrando; ya se borrará la próxima vez
            pass


def run_cswap(*args):
    if not setup_tools.find("cswap"):
        raise RuntimeError("Falta claude-swap: instálalo desde la pestaña Cuentas.")
    return setup_tools.run(["cswap", *args], timeout=60)


def color_for(used):
    if used < 50:
        return GREEN
    if used < 75:
        return AMBER
    if used < 90:
        return ORANGE
    return RED


def parse_time(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def countdown(target):
    if not target:
        return ""
    secs = int((target - datetime.now(timezone.utc)).total_seconds())
    if secs <= 0:
        return "ya"
    d, rem = divmod(secs, 86400)
    h, rem = divmod(rem, 3600)
    m = rem // 60
    if d:
        return f"{d}d {h}h"
    if h:
        return f"{h}h {m}m"
    return f"{m}m"


def reset_label(target):
    if not target:
        return "sin uso reciente"
    local = target.astimezone()
    now = datetime.now().astimezone()
    when = f"a las {local:%H:%M}"
    if local.date() != now.date():
        when = f"el {DIAS[local.weekday()]} {local.day} {MESES[local.month - 1]} {when}"
    return f"se vacía {when} · en {countdown(target)}"


def tray_image(used):
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    # la barra de tareas es oscura casi siempre: colores del tema oscuro
    d.rounded_rectangle((0, 0, size - 1, size - 1), radius=14,
                        fill=TRACK[1] if used is None else color_for(used)[1])
    text = "–" if used is None else f"{used:.0f}"
    try:
        font = ImageFont.truetype("segoeuib.ttf", 40 if len(text) < 3 else 30)
    except OSError:
        font = ImageFont.load_default()
    d.text((size / 2, size / 2), text, fill="#111111", font=font, anchor="mm")
    return img


class Tray:
    """Icono junto al reloj con el consumo de la cuenta activa."""

    def __init__(self, app):
        self.app = app
        self.accounts = []
        self.update_tag = None
        self.icon = pystray.Icon("ClaudeUsage", tray_image(None), "Claude Usage",
                                 menu=pystray.Menu(self.menu_items))
        self.icon.run_detached()

    def menu_items(self):
        post = self.app.post
        yield pystray.MenuItem("Mostrar", lambda: post(self.app.show_window), default=True)
        yield pystray.MenuItem("Actualizar", lambda: post(lambda: self.app.refresh(schedule=False)))
        if self.update_tag:
            yield pystray.MenuItem(f"Instalar versión {self.update_tag}",
                                   lambda: post(self.app.start_update))
        yield pystray.Menu.SEPARATOR
        for acc in self.accounts:
            number = acc.get("number")
            name = acc.get("alias") or acc.get("email", "?")
            yield pystray.MenuItem(
                f"Usar {name}",
                (lambda n: lambda: post(lambda: self.app.switch_to(n)))(number),
                checked=(lambda a: lambda _item: bool(a.get("active")))(acc),
                radio=True,
            )
        yield pystray.Menu.SEPARATOR
        yield pystray.MenuItem("Salir", lambda: post(self.app.quit_app))

    def update(self, accounts):
        self.accounts = accounts
        active = next((a for a in accounts if a.get("active")), None)
        if active:
            usage = active.get("usage") or {}
            parts = [f"{label} {(usage.get(k) or {}).get('pct', 0):.0f}%"
                     for k, label in (("fiveHour", "5h"), ("sevenDay", "semana"))]
            name = active.get("alias") or active.get("email", "?")
            self.icon.icon = tray_image((usage.get("fiveHour") or {}).get("pct"))
            self.icon.title = f"{name} · usado {' · '.join(parts)}"
        self.icon.update_menu()

    def update_available(self, tag):
        self.update_tag = tag
        self.icon.update_menu()
        try:
            self.icon.notify(f"Hay una versión nueva: {tag}", "Claude Usage")
        except Exception:  # no en todos los Windows salen los avisos
            pass

    def stop(self):
        self.icon.stop()


def pick(color):
    """El color del tema actual, para lo que no entiende las parejas (claro, oscuro)."""
    return color[1] if ctk.get_appearance_mode() == "Dark" else color[0]


def auto_wrap(label):
    """Reparte el texto en líneas según el ancho que tenga: la ventana cambia de tamaño."""
    def resize(event):
        scale = ctk.ScalingTracker.get_widget_scaling(label)
        label.configure(wraplength=max(int(event.width / scale) - 4, 40))
    # en el marco del CTkLabel, no en su texto: ese mide lo que ocupa ya repartido
    tk.Frame.bind(label, "<Configure>", resize, add="+")
    return label


def text(master, value="", size=12, color=TEXT, bold=False, wrap=False, **kw):
    label = ctk.CTkLabel(master, text=value, font=font(size, bold), text_color=color,
                         anchor="w", justify="left", **kw)
    return auto_wrap(label) if wrap else label


def button(master, label, command, primary=False, **kw):
    return ctk.CTkButton(master, text=label, command=command, height=30, width=72,
                         corner_radius=8, font=font(12, primary),
                         fg_color=ACCENT if primary else TRACK,
                         hover_color=ACCENT_HOVER if primary else BORDER,
                         text_color=ON_ACCENT if primary else TEXT, **kw)


def pill(master, label, fg, color=ON_ACCENT):
    return ctk.CTkLabel(master, text=f"  {label}  ", font=font(10, True), fg_color=fg,
                        text_color=color, corner_radius=8, height=22)


def card(master, **kw):
    frame = ctk.CTkFrame(master, fg_color=CARD, corner_radius=16, border_width=1,
                         border_color=BORDER, **kw)
    inner = ctk.CTkFrame(frame, fg_color="transparent")
    inner.pack(fill="x", padx=18, pady=16)
    return frame, inner


class Meter(ctk.CTkFrame):
    """Un límite: título, % usado, barra que pasa de verde a rojo y cuándo se vacía."""

    def __init__(self, master, title):
        super().__init__(master, fg_color="transparent")
        head = ctk.CTkFrame(self, fg_color="transparent")
        head.pack(fill="x")
        text(head, title, 13).pack(side="left")
        self.value = text(head, "", 16, bold=True)
        self.value.pack(side="right")
        self.left = text(head, "", 11, MUTED)
        self.left.pack(side="right", padx=(0, 8))
        self.bar = ctk.CTkProgressBar(self, height=10, corner_radius=5, fg_color=TRACK,
                                      progress_color=TRACK)
        self.bar.pack(fill="x", pady=(6, 0))
        self.bar.set(0)
        self.note = text(self, "", 11, MUTED)
        self.note.pack(fill="x", pady=(4, 0))

    def show(self, used):
        if used is None:
            self.value.configure(text="sin datos", text_color=MUTED)
            self.left.configure(text="")
            self.bar.configure(progress_color=TRACK)
            self.bar.set(0)
            return
        color = color_for(used)
        self.value.configure(text=f"{used:.0f}%", text_color=color)
        self.left.configure(text=f"queda {100 - used:.0f}% ·")
        # la barra redondeada siempre pinta un trocito: a 0 se pinta del color del fondo
        self.bar.configure(progress_color=color if used > 0 else TRACK)
        self.bar.set(used / 100)


class AccountCard(ctk.CTkFrame):
    """Una cuenta en la pestaña Uso: sus dos límites y si es la que está en uso."""

    def __init__(self, master, app):
        super().__init__(master, fg_color=CARD, corner_radius=16, border_width=1,
                         border_color=BORDER)
        self.app = app
        self.number = None
        self.acc = None
        inner = ctk.CTkFrame(self, fg_color="transparent")
        inner.pack(fill="x", padx=18, pady=16)

        head = ctk.CTkFrame(inner, fg_color="transparent")
        head.pack(fill="x", pady=(0, 12))
        names = ctk.CTkFrame(head, fg_color="transparent")
        names.pack(side="left", fill="x", expand=True)
        self.name = text(names, "", 16, bold=True)
        self.name.pack(fill="x")
        self.email = text(names, "", 11, MUTED)
        self.email.pack(fill="x")
        self.badge = pill(head, "EN USO", ACCENT)
        self.empty = pill(head, "AGOTADA", RED)
        self.button = button(head, "Usar", lambda: self.app.switch_to(self.number))

        self.meters = {key: Meter(inner, title) for key, title in
                       (("fiveHour", "Límite de 5 horas"), ("sevenDay", "Límite semanal"))}
        for meter in self.meters.values():
            meter.pack(fill="x", pady=(0, 10))
        self.warning = text(inner, "", 11, AMBER, wrap=True)

    def update_account(self, acc):
        self.number = acc.get("number")
        self.acc = acc
        self.name.configure(text=acc.get("alias") or acc.get("email", "?"))
        self.email.configure(text=acc.get("email", ""))
        for widget in (self.badge, self.button, self.empty):
            widget.pack_forget()
        usage = acc.get("usage") or {}
        if acc.get("active"):
            self.badge.pack(side="right")
            self.configure(border_color=ACCENT, border_width=2)
        else:
            self.button.pack(side="right")
            self.configure(border_color=BORDER, border_width=1)
        if any((usage.get(k) or {}).get("pct", 0) >= 100 for k in ("fiveHour", "sevenDay")):
            self.empty.pack(side="right", padx=(0, 6))

        for key, meter in self.meters.items():
            pct = (usage.get(key) or {}).get("pct")
            meter.show(None if pct is None else min(100.0, max(0.0, pct)))

        week = usage.get("sevenDay") or {}
        note = ""
        if acc.get("usageStatus") not in (None, "ok"):
            note = f"⚠ {acc.get('usageStatus')}"
        elif week.get("willLastToReset") is False and week.get("pct", 0) < 100:
            note = "⚠ a este ritmo no llega al reinicio semanal"
        self.warning.configure(text=note)
        if note:
            self.warning.pack(fill="x")
        else:
            self.warning.pack_forget()
        self.tick()

    def tick(self):
        usage = (self.acc or {}).get("usage") or {}
        for key, meter in self.meters.items():
            meter.note.configure(
                text=reset_label(parse_time((usage.get(key) or {}).get("resetsAt"))))


class LogBox(ctk.CTkTextbox):
    """Registro de lo que se va haciendo al instalar, para ver dónde falla.

    Aparece abajo de su pestaña (antes de anchor) la primera vez que se escribe algo.
    """

    def __init__(self, master, anchor):
        super().__init__(master, height=120, corner_radius=12, fg_color=CARD,
                         border_width=1, border_color=BORDER, text_color=MUTED,
                         font=(MONO, 11), wrap="word")
        self.anchor = anchor
        self.tag_config("error", foreground=pick(RED))
        self.tag_config("ok", foreground=pick(GREEN))
        self.configure(state="disabled")

    def write(self, line, tag=None):
        if not self.winfo_ismapped():
            self.pack(side="bottom", fill="x", pady=(10, 0), before=self.anchor)
        self.configure(state="normal")
        self.insert("end", line + "\n", tag)
        self.see("end")
        self.configure(state="disabled")

    def clear(self):
        self.configure(state="normal")
        self.delete("1.0", "end")
        self.configure(state="disabled")


class Page(ctk.CTkFrame):
    """Una pestaña: su contenido se desplaza y lo de abajo (registro, avisos) queda fijo."""

    def __init__(self, master):
        super().__init__(master, fg_color="transparent")
        self.body = ctk.CTkScrollableFrame(self, fg_color="transparent", corner_radius=0,
                                           scrollbar_button_color=TRACK,
                                           scrollbar_button_hover_color=BORDER)
        self.body.pack(fill="both", expand=True)
        # lo que se coloca en la ventana es el marco que envuelve la zona con scroll
        self.anchor = self.body._parent_frame

    def pin_bottom(self, widget, **pack):
        """Coloca widget abajo del todo, fuera de la zona que se desplaza."""
        widget.pack(side="bottom", fill="x", before=self.anchor, **pack)


class AccountsPage(Page):
    """Preparar todo y añadir, usar o quitar cuentas sin tocar la terminal."""

    def __init__(self, master, app):
        super().__init__(master)
        self.app = app
        self.status = None     # lo que hay instalado y con qué cuenta se ha iniciado sesión
        self.accounts = None   # las cuentas guardadas, según la última lectura de cswap
        text(self.body, "Comprobando…", 12, MUTED).pack(anchor="w")
        self.log = LogBox(self, self.anchor)

    def refresh(self):
        def work():
            return {"login": setup_tools.claude_login_status(),
                    "cswap": setup_tools.is_ready("cswap")}
        self.app.run_in_background(work, self.show_status)

    def show_status(self, status, error):
        if not error:
            self.status = status
            self.render()

    def show_accounts(self, accounts):
        self.accounts = accounts
        self.render()

    def render(self):
        if self.status is None:
            return
        for child in self.body.winfo_children():
            child.destroy()
        login = self.status["login"]
        installed = login is not None
        email = (login or {}).get("email") if (login or {}).get("loggedIn") else None
        accounts = self.accounts or []
        saved = [acc.get("email") for acc in accounts]
        steps = [
            ("Instalar Claude Code", installed, "Instalar", self.install_claude),
            ("Iniciar sesión en Claude", bool(email), "Iniciar sesión", self.add_account),
            ("Activar el cambio de cuentas", self.status["cswap"] and bool(accounts),
             "Activar", self.save_current),
        ]
        if not all(done for _t, done, _b, _c in steps):
            self.render_steps(steps)
            return

        if email not in saved:
            banner = ctk.CTkFrame(self.body, fg_color=CARD, corner_radius=14, border_width=1,
                                  border_color=ACCENT)
            banner.pack(fill="x", pady=(0, 12))
            row = ctk.CTkFrame(banner, fg_color="transparent")
            row.pack(fill="x", padx=14, pady=12)
            button(row, "Guardarla", self.save_current, primary=True).pack(side="right",
                                                                           padx=(10, 0))
            text(row, f"Claude Code está usando {email}, pero no la tienes guardada aquí.",
                 12, wrap=True).pack(side="left", fill="x", expand=True)

        frame, box = card(self.body)
        frame.pack(fill="x")
        text(box, "Tus cuentas", 17, bold=True).pack(fill="x")
        for acc in accounts:
            self.account_row(box, acc)
        ctk.CTkButton(box, text="+   Añadir una cuenta", command=self.add_account, height=42,
                      corner_radius=10, font=font(13, True), fg_color=ACCENT,
                      hover_color=ACCENT_HOVER, text_color=ON_ACCENT).pack(fill="x",
                                                                           pady=(16, 0))
        text(box, "Se abre el navegador para que entres con la otra cuenta y se guarda sola. "
                  "No cierres sesión antes en Claude Code.", 11, MUTED,
             wrap=True).pack(fill="x", pady=(10, 0))

    def render_steps(self, steps):
        frame, box = card(self.body)
        frame.pack(fill="x")
        text(box, "Vamos a prepararlo", 17, bold=True).pack(fill="x")
        text(box, "Son tres pasos y solo hay que hacerlos una vez.", 12, MUTED,
             wrap=True).pack(fill="x", pady=(4, 6))
        current = next(i for i, (_t, done, _b, _c) in enumerate(steps) if not done)
        for i, (title, done, label, command) in enumerate(steps):
            row = ctk.CTkFrame(box, fg_color="transparent")
            row.pack(fill="x", pady=(10, 0))
            ctk.CTkLabel(row, text="✓" if done else str(i + 1), width=28, height=28,
                         corner_radius=14, font=font(12, True),
                         fg_color=GREEN if done else (ACCENT if i == current else TRACK),
                         text_color=ON_ACCENT if done or i == current else MUTED,
                         ).pack(side="left")
            text(row, title, 13, TEXT if i == current else MUTED).pack(side="left",
                                                                      padx=(12, 0))
            if i == current:
                button(row, label, command, primary=True).pack(side="right")

    def account_row(self, master, acc):
        active = acc.get("active")
        row = ctk.CTkFrame(master, fg_color=CARD_ALT, corner_radius=12,
                           border_width=2 if active else 0, border_color=ACCENT)
        row.pack(fill="x", pady=(10, 0))
        inner = ctk.CTkFrame(row, fg_color="transparent")
        inner.pack(fill="x", padx=12, pady=10)
        names = ctk.CTkFrame(inner, fg_color="transparent")
        names.pack(side="left", fill="x", expand=True)
        text(names, acc.get("alias") or acc.get("email", "?"), 13, bold=True).pack(fill="x")
        text(names, acc.get("email", ""), 11, MUTED).pack(fill="x")
        ctk.CTkButton(inner, text="✕", width=30, height=30, corner_radius=8,
                      fg_color="transparent", hover_color=TRACK, text_color=MUTED,
                      font=font(13), command=lambda: self.remove(acc)).pack(side="right",
                                                                           padx=(6, 0))
        if active:
            pill(inner, "EN USO", ACCENT).pack(side="right")
        else:
            button(inner, "Usar", lambda: self.app.switch_to(acc.get("number"))
                   ).pack(side="right")

    def task(self, title, work):
        self.app.run_task(self.log, title, work, after=self.after_change)

    def after_change(self):
        self.refresh()
        self.app.refresh(schedule=False)

    def install_claude(self):
        self.task("Instalando Claude Code…", lambda log: setup_tools.ensure("claude", log))

    def save_current(self):
        self.task("Guardando la cuenta con la que has iniciado sesión…",
                  setup_tools.save_current_account)

    def add_account(self):
        self.task("Abriendo el inicio de sesión…", setup_tools.add_another_account)

    def remove(self, acc):
        name = acc.get("alias") or acc.get("email", "?")
        if not messagebox.askyesno(
                "Quitar cuenta", f"¿Quitar {name} de la lista?\n\nPodrás volver a añadirla "
                "cuando quieras.", parent=self):
            return
        self.task(f"Quitando {name}…",
                  lambda log: setup_tools.remove_account(acc.get("number"), log))


class PluginsPage(Page):
    """Catálogo de herramientas para gastar menos tokens en Claude Code."""

    LABELS = {"missing": ("No instalado", MUTED), "enabled": ("● Activo", GREEN),
              "disabled": ("Desactivado", AMBER)}

    def __init__(self, master, app):
        super().__init__(master)
        self.app = app
        self.cards = []

        frame, summary = card(self.body)
        frame.pack(fill="x", pady=(0, 12))
        self.spend = Meter(summary, "Gasto estimado de tokens")
        self.spend.pack(fill="x")
        self.show_spend(1.0)
        self.spend.note.configure(
            text="Orientativo, según las pruebas publicadas de cada plugin. Los que nadie ha "
                 "medido no cuentan. Los plugins valen para todas las cuentas.")
        auto_wrap(self.spend.note)

        for tool in setup_tools.TOOLS:
            frame, box = card(self.body)
            frame.pack(fill="x", pady=(0, 12))
            head = ctk.CTkFrame(box, fg_color="transparent")
            head.pack(fill="x")
            text(head, tool.name, 15, bold=True).pack(side="left")
            high = tool.priority == "Alta"
            pill(head, tool.priority.upper(), ACCENT if high else TRACK,
                 ON_ACCENT if high else TEXT).pack(side="left", padx=(10, 0))
            state = text(head, "comprobando…", 12, MUTED)
            state.pack(side="right")
            text(box, tool.description, 12, wrap=True).pack(fill="x", pady=(8, 4))

            lines = [("Bueno", tool.pros, GREEN, MUTED), ("Malo", tool.cons, AMBER, MUTED)]
            if tool.quality_risk:
                lines.append(("⚠", "No se ha probado si puede afectar a la calidad del "
                                   "código.", ORANGE, ORANGE))
            for tag, value, tag_color, text_color in lines:
                row = ctk.CTkFrame(box, fg_color="transparent")
                row.pack(fill="x", pady=(4, 0))
                text(row, tag, 12, tag_color, bold=True, width=56).pack(side="left", anchor="n")
                text(row, value, 12, text_color, wrap=True).pack(side="left", fill="x",
                                                                  expand=True)

            bottom = ctk.CTkFrame(box, fg_color="transparent")
            bottom.pack(fill="x", pady=(12, 0))
            if tool.saving is None:
                saving, color = "ahorro sin medir", MUTED
            elif tool.saving > 0:
                saving, color = f"ahorra ≈{tool.saving * 100:g} %".replace(".", ","), GREEN
            else:
                saving, color = "no ahorra", MUTED
            text(bottom, saving, 12, color, bold=True).pack(side="right")
            buttons = ctk.CTkFrame(bottom, fg_color="transparent")
            buttons.pack(side="left")
            options = ctk.CTkFrame(box, fg_color="transparent")
            self.cards.append((tool, state, buttons, options))

        # solo se enseña cuando hay cambios que Claude Code aún no ha cargado
        self.restart_note = ctk.CTkFrame(self, fg_color=CARD, corner_radius=14,
                                         border_width=1, border_color=ACCENT)
        row = ctk.CTkFrame(self.restart_note, fg_color="transparent")
        row.pack(fill="x", padx=14, pady=10)
        button(row, "Reiniciar Claude Code", self.restart_claude,
               primary=True).pack(side="right", padx=(10, 0))
        text(row, "Has hecho cambios. Reinicia Claude Code para que se apliquen.", 12,
             wrap=True).pack(side="left", fill="x", expand=True)
        self.log = LogBox(self, self.anchor)

    def show_spend(self, spend):
        saved = round((1 - spend) * 100)
        self.spend.value.configure(text=f"≈{saved} % menos" if saved > 0 else "sin ahorro",
                                   text_color=GREEN if saved > 0 else MUTED)
        self.spend.left.configure(text=f"{spend * 100:.0f} % del normal ·")
        self.spend.bar.configure(progress_color=ACCENT)
        self.spend.bar.set(spend)

    def refresh(self):
        def work():
            plugins = setup_tools.installed_plugins()
            return ([tool.status(plugins) for tool in setup_tools.TOOLS],
                    setup_tools.restart_needed())
        self.app.run_in_background(work, self.show_status)

    def show_status(self, result, error):
        if error:
            self.log.write(f"✖ No pude comprobar los plugins: {error}", "error")
            return
        statuses, restart = result
        if not restart:
            self.restart_note.pack_forget()
        elif not self.restart_note.winfo_ismapped():
            self.pin_bottom(self.restart_note, pady=(10, 0))
        self.show_spend(setup_tools.estimated_spend(
            tool for (tool, _s, _b, _o), status in zip(self.cards, statuses)
            if status == "enabled"))
        for (tool, state, buttons, options), status in zip(self.cards, statuses):
            label, color = self.LABELS[status]
            state.configure(text=label, text_color=color)
            for child in buttons.winfo_children() + options.winfo_children():
                child.destroy()
            options.pack_forget()
            if tool.has_options and status != "missing":
                self.ponytail_options(options)
                options.pack(fill="x", pady=(14, 0))
            if status == "missing":
                button(buttons, "Instalar", lambda t=tool: self.install(t),
                       primary=True).pack(side="left")
                continue
            enable = status == "disabled"
            button(buttons, "Activar" if enable else "Desactivar",
                   lambda t=tool, e=enable: self.toggle(t, e), primary=enable).pack(side="left")
            button(buttons, "Actualizar", lambda t=tool: self.update(t)).pack(side="left",
                                                                              padx=(6, 0))
            button(buttons, "Desinstalar", lambda t=tool: self.uninstall(t)).pack(side="left",
                                                                                  padx=(6, 0))

    def ponytail_options(self, frame):
        """Nivel con el que empieza cada sesión y si se ve su barra en Claude Code."""
        row = ctk.CTkFrame(frame, fg_color="transparent")
        row.pack(fill="x")
        text(row, "Nivel", 12, MUTED, bold=True, width=56).pack(side="left")
        levels = ctk.CTkSegmentedButton(
            row, values=setup_tools.PONYTAIL_LEVELS, height=30, corner_radius=8,
            font=font(12), fg_color=TRACK, unselected_color=TRACK,
            unselected_hover_color=BORDER, selected_color=ACCENT,
            selected_hover_color=ACCENT_HOVER, text_color=TEXT,
            command=lambda level: self.set_ponytail(level=level))
        levels.set(setup_tools.ponytail_level())
        levels.pack(side="left")
        band = tk.BooleanVar(value=setup_tools.ponytail_band_visible())
        ctk.CTkSwitch(frame, text="Mostrar su barra en Claude Code", variable=band,
                      font=font(12), text_color=TEXT, progress_color=ACCENT,
                      fg_color=TRACK, command=lambda: self.set_ponytail(band=band.get()),
                      ).pack(anchor="w", pady=(10, 0))

    def set_ponytail(self, level=None, band=None):
        def work(log):
            if level is not None:
                setup_tools.set_ponytail_level(level)
                log(f"> nivel de Ponytail: {level}")
            if band is not None:
                setup_tools.set_ponytail_band(band)
                log(f"> barra de Ponytail: {'visible' if band else 'oculta'}")
        self.task("Cambiando las opciones de Ponytail…", work)

    def task(self, title, work, changes=True):
        def run(log):
            work(log)
            if changes:
                setup_tools.mark_changed()
        self.app.run_task(self.log, title, run, after=self.refresh)

    def update(self, tool):
        self.task(f"Actualizando {tool.name}…", tool.update)

    def install(self, tool):
        def work(log):
            tool.install(log)
            setup_tools.check_tool(tool, expected=True)
        self.task(f"Instalando {tool.name}…", work)

    def uninstall(self, tool):
        if not messagebox.askyesno("Desinstalar", f"¿Desinstalar {tool.name}?", parent=self):
            return

        def work(log):
            tool.uninstall(log)
            setup_tools.check_tool(tool, expected=False)
        self.task(f"Desinstalando {tool.name}…", work)

    def toggle(self, tool, enabled):
        verb = "Activando" if enabled else "Desactivando"
        self.task(f"{verb} {tool.name}…", lambda log: tool.set_enabled(enabled, log))

    def restart_claude(self):
        count = len(setup_tools.claude_sessions())
        sessions = "la sesión" if count == 1 else f"las {count} sesiones"
        if count and not messagebox.askyesno(
                "Reiniciar Claude Code",
                f"Se cerrará {sessions} de Claude Code abierta{'s' if count > 1 else ''} "
                "(terminal y VS Code). Las conversaciones no se pierden: puedes seguirlas con "
                "'claude --continue' o /resume.\n\n¿Cerrarlas ahora?", parent=self):
            return
        self.task("Cerrando Claude Code…", setup_tools.close_claude, changes=False)


class App(ctk.CTk):
    def __init__(self, start_hidden=False, listener=None):
        super().__init__(fg_color=BG)
        self.queue = queue.Queue()
        self.poll_queue()
        self.listener = listener
        if listener:
            threading.Thread(target=self.serve_other_instances, args=(listener,),
                             daemon=True).start()
        self.title("Claude Usage")
        icon = Path(getattr(sys, "_MEIPASS", Path(__file__).parent)) / "claude_usage.ico"
        if icon.exists():
            self.iconbitmap(str(icon))
            self.after(250, lambda: self.iconbitmap(str(icon)))  # CustomTkinter pone el suyo
        # tamaño fijo al cambiar de pestaña; se puede redimensionar a mano
        scale = ctk.ScalingTracker.get_window_scaling(self)
        height = min(860, int(self.winfo_screenheight() / scale * 0.85))
        self.geometry(f"520x{height}")
        self.minsize(440, 560)
        self.cards = []
        self.busy = False
        self.task_running = False
        self.pinned = False

        shell = ctk.CTkFrame(self, fg_color="transparent")
        shell.pack(fill="both", expand=True, padx=18, pady=(16, 12))

        top = ctk.CTkFrame(shell, fg_color="transparent")
        top.pack(fill="x", pady=(0, 14))
        if icon.exists():
            logo = Image.open(icon)
            ctk.CTkLabel(top, text="", image=ctk.CTkImage(logo, logo, size=(34, 34))
                         ).pack(side="left", padx=(0, 12))
        titles = ctk.CTkFrame(top, fg_color="transparent")
        titles.pack(side="left")
        text(titles, "Claude Usage", 20, bold=True).pack(anchor="w")
        text(titles, "Consumo de tus cuentas de Claude Code", 12, MUTED).pack(anchor="w")
        self.pin = self.icon_button(top, "📌", self.toggle_pin)
        self.pin.pack(side="right", padx=(4, 0))
        self.icon_button(top, "⟳", self.refresh_all).pack(side="right")

        self.update_bar = ctk.CTkFrame(shell, fg_color=CARD, corner_radius=14, border_width=1,
                                       border_color=ACCENT)
        row = ctk.CTkFrame(self.update_bar, fg_color="transparent")
        row.pack(fill="x", padx=14, pady=10)
        self.update_button = button(row, "Actualizar", self.start_update, primary=True)
        self.update_button.pack(side="right", padx=(10, 0))
        self.update_text = text(row, "", 12, wrap=True)
        self.update_text.pack(side="left", fill="x", expand=True)
        self.release = None
        self.downloading = False

        self.tabs = ctk.CTkSegmentedButton(
            shell, values=["Uso", "Cuentas", "Plugins"], command=self.show_tab, height=36,
            corner_radius=10, font=font(13, True), fg_color=CARD, unselected_color=CARD,
            unselected_hover_color=TRACK, selected_color=ACCENT,
            selected_hover_color=ACCENT_HOVER, text_color=TEXT)
        self.tabs.pack(fill="x", pady=(0, 14))
        self.pages = ctk.CTkFrame(shell, fg_color="transparent")
        self.pages.pack(fill="both", expand=True)
        usage = Page(self.pages)
        self.body = usage.body
        self.status = text(usage, "Cargando…", 11, MUTED)
        usage.pin_bottom(self.status, pady=(8, 0))
        self.accounts_page = AccountsPage(self.pages, self)
        self.plugins_page = PluginsPage(self.pages, self)
        self.tab_pages = {"Uso": usage, "Cuentas": self.accounts_page,
                          "Plugins": self.plugins_page}
        self.show_tab("Uso")

        ctk.CTkFrame(shell, fg_color=BORDER, height=1).pack(fill="x", pady=(12, 10))
        footer = ctk.CTkFrame(shell, fg_color="transparent")
        footer.pack(fill="x")
        self.autostart = tk.BooleanVar(value=setup_tools.autostart_enabled())
        ctk.CTkSwitch(footer, text="Abrir al iniciar Windows", variable=self.autostart,
                      command=self.toggle_autostart, font=font(12), text_color=TEXT,
                      progress_color=ACCENT, fg_color=TRACK).pack(side="left")
        text(footer, f"v{VERSION}", 11, MUTED).pack(side="right")
        self.check_link = ctk.CTkButton(
            footer, text="Buscar actualizaciones", command=self.check_now, width=0, height=26,
            corner_radius=6, font=font(11), fg_color="transparent", hover_color=TRACK,
            text_color=MUTED)
        self.check_link.pack(side="right", padx=(0, 4))
        credit = ctk.CTkFrame(shell, fg_color="transparent")
        credit.pack(fill="x", pady=(6, 0))
        text(credit, "Creado por ", 11, MUTED).pack(side="left")
        text(credit, "Sergio Bernabé", 11, ACCENT, bold=True).pack(side="left")

        self.tray = Tray(self) if pystray else None
        if self.tray:
            self.protocol("WM_DELETE_WINDOW", self.withdraw)
            if start_hidden:
                self.withdraw()
                self.after(500, self.withdraw)  # a veces Windows la vuelve a mostrar al arrancar
        self.refresh()
        self.accounts_page.refresh()
        self.plugins_page.refresh()
        self.after(TICK_MS, self.tick)
        self.after(5000, remove_update_leftovers)
        self.after(3000, self.check_for_update)

    def icon_button(self, master, label, command):
        return ctk.CTkButton(master, text=label, command=command, width=36, height=36,
                             corner_radius=10, font=font(16), fg_color="transparent",
                             hover_color=TRACK, text_color=MUTED)

    def toggle_autostart(self):
        try:
            setup_tools.set_autostart(self.autostart.get())
        except OSError as exc:
            self.autostart.set(not self.autostart.get())
            messagebox.showerror("Abrir al iniciar Windows", f"No se pudo cambiar: {exc}",
                                 parent=self)

    def refresh_all(self):
        self.refresh(schedule=False)
        self.accounts_page.refresh()
        self.plugins_page.refresh()

    def show_tab(self, name):
        for page in self.tab_pages.values():
            page.pack_forget()
        self.tab_pages[name].pack(fill="both", expand=True)
        self.tabs.set(name)

    def run_task(self, log, title, work, after=None):
        """Instalaciones y cambios, de uno en uno, contando lo que pasa en log."""
        if self.task_running:
            log.write("Espera a que termine lo que se está haciendo.", "error")
            return
        self.task_running = True
        log.clear()
        log.write(title)

        def line(value):
            self.post(lambda: log.write(value))

        def done(_result, error):
            self.task_running = False
            if error:
                log.write(f"✖ {error}", "error")
            else:
                log.write("✔ Hecho", "ok")
            if after:
                after()

        self.run_in_background(lambda: work(line), done)

    def post(self, fn):
        """Ejecuta fn en el hilo de tkinter (desde la bandeja o hilos de trabajo)."""
        self.queue.put(fn)

    def poll_queue(self):
        while True:
            try:
                fn = self.queue.get_nowait()
            except queue.Empty:
                break
            fn()
        self.after(150, self.poll_queue)

    def serve_other_instances(self, listener):
        """Si se vuelve a abrir la app, la otra instancia nos pide mostrar la ventana."""
        while True:
            try:
                conn, _addr = listener.accept()
            except OSError:  # se cerró el socket porque la app se está actualizando
                return
            with conn:
                conn.settimeout(2)
                try:
                    message = conn.recv(16)
                except OSError:
                    continue
            if message == b"show":
                self.post(self.show_window)

    def show_window(self):
        self.deiconify()
        self.lift()
        # Windows no deja que un proceso en segundo plano se ponga delante sin más
        self.attributes("-topmost", True)
        self.attributes("-topmost", self.pinned)
        self.focus_force()

    def quit_app(self):
        if self.tray:
            self.tray.stop()
        self.destroy()

    def toggle_pin(self):
        self.pinned = not self.pinned
        self.attributes("-topmost", self.pinned)
        self.pin.configure(text_color=ACCENT if self.pinned else MUTED)

    def run_in_background(self, work, done):
        def target():
            try:
                result, error = work(), None
            except Exception as exc:  # se muestra en la barra de estado
                result, error = None, exc
            self.post(lambda: done(result, error))
        threading.Thread(target=target, daemon=True).start()

    def refresh(self, schedule=True):
        if schedule:
            self.after(REFRESH_MS, self.refresh)
        if self.busy:
            return
        self.busy = True
        self.status.configure(text="Actualizando…")
        self.run_in_background(lambda: json.loads(run_cswap("list", "--json")), self.show)

    def show(self, data, error):
        self.busy = False
        if error:
            self.status.configure(text=f"Error: {error}", text_color=RED)
            if not setup_tools.find("cswap") and not getattr(self, "sent_to_setup", False):
                self.sent_to_setup = True  # solo la primera vez, para no secuestrar la ventana
                self.show_tab("Cuentas")
            return
        accounts = data.get("accounts", [])
        self.accounts_page.show_accounts(accounts)
        while len(self.cards) < len(accounts):
            account = AccountCard(self.body, self)
            account.pack(fill="x", pady=(0, 12))
            self.cards.append(account)
        while len(self.cards) > len(accounts):
            self.cards.pop().destroy()
        for account, acc in zip(self.cards, accounts):
            account.update_account(acc)
        if self.tray:
            self.tray.update(accounts)
        if not accounts:
            self.status.configure(
                text="Aún no hay cuentas: guárdalas en la pestaña Cuentas.", text_color=MUTED)
            return
        self.status.configure(
            text=f"Actualizado {datetime.now():%H:%M} · se refresca cada minuto",
            text_color=MUTED)

    def switch_to(self, number):
        if number is None:
            return
        if self.busy:  # se está refrescando: se cambia de cuenta en cuanto acabe
            self.after(500, lambda: self.switch_to(number))
            return
        self.busy = True
        self.status.configure(text=f"Cambiando a la cuenta {number}…", text_color=MUTED)

        def done(_result, error):
            self.busy = False
            if error:
                self.status.configure(text=f"Error al cambiar: {error}", text_color=RED)
            else:
                self.refresh(schedule=False)

        self.run_in_background(lambda: run_cswap("switch", str(number)), done)

    def tick(self):
        for account in self.cards:
            account.tick()
        self.after(TICK_MS, self.tick)

    def check_for_update(self):
        self.after(UPDATE_CHECK_MS, self.check_for_update)
        self.run_in_background(fetch_newer_release, self.on_release)

    def check_now(self):
        if self.check_link.cget("text") == "Buscando…":
            return
        self.check_link.configure(text="Buscando…")

        def done(release, error):
            if error:
                label = "Sin conexión"
            elif release or self.release:
                label = "Hay versión nueva"
            else:
                label = "✓ Estás al día"
            self.check_link.configure(text=label)
            self.after(5000, lambda: self.check_link.configure(text="Buscar actualizaciones"))
            self.on_release(release, error)

        self.run_in_background(fetch_newer_release, done)

    def on_release(self, release, error):
        if error or not release or self.release:
            return  # sin internet o sin novedades: no molestamos
        self.release = release
        tag = release.get("tag_name", "")
        self.update_text.configure(text=f"Hay una versión nueva: {tag}")
        self.update_button.configure(
            text="Actualizar" if can_self_update(release) else "Descargar")
        self.update_bar.pack(fill="x", pady=(0, 14), before=self.tabs)
        if self.tray:
            self.tray.update_available(tag)

    def start_update(self):
        if not self.release or self.downloading:
            return
        if not can_self_update(self.release):
            webbrowser.open(self.release.get("html_url") or RELEASES_URL)
            return
        self.downloading = True
        self.update_button.configure(text="Descargando…")
        self.update_text.configure(text=f"Descargando {self.release.get('tag_name', '')}…")

        def done(new, error):
            self.downloading = False
            if error:
                self.update_button.configure(text="Reintentar")
                self.update_text.configure(text=f"No se pudo descargar: {error}")
                return
            self.apply_update(new)

        self.run_in_background(lambda: download_update(self.release), done)

    def apply_update(self, new):
        try:
            exe = install_update(new)
        except OSError as exc:
            self.release = dict(self.release, assets=[])  # a partir de aquí el botón abre la web
            self.update_button.configure(text="Descargar")
            self.update_text.configure(text=f"No se pudo reemplazar el .exe: {exc}")
            return
        if self.listener:  # liberamos el puerto para que la versión nueva no crea que ya hay otra
            self.listener.close()
        # sin esto el .exe nuevo reutilizaría la carpeta temporal de este, que se borra al salir
        env = dict(os.environ, PYINSTALLER_RESET_ENVIRONMENT="1")
        subprocess.Popen([str(exe)], env=env, close_fds=True)
        self.quit_app()


if __name__ == "__main__":
    start_hidden = "--tray" in sys.argv
    listener = listen_for_other_instances()
    if listener is None and notify_running_instance(show=not start_hidden):
        sys.exit(0)
    App(start_hidden=start_hidden, listener=listener).mainloop()
