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

import setup_tools

try:
    import pystray
    from PIL import Image, ImageDraw, ImageFont
except ImportError:  # sin icono en la bandeja, la ventana sigue funcionando
    pystray = None

VERSION = "1.1.2"
REPO = "Serberar/claude-usage"
RELEASES_URL = f"https://github.com/{REPO}/releases/latest"
INSTALLER_ID = "7F4AB592-8EFE-486C-AC71-466940D30782"  # AppId de installer.iss

REFRESH_MS = 60_000      # cada cuánto se vuelve a consultar cswap
TICK_MS = 30_000         # cada cuánto se recalculan las cuentas atrás
INSTANCE_PORT = 47821    # puerto local con el que la app detecta si ya está abierta
UPDATE_CHECK_MS = 6 * 3600_000  # cada cuánto se mira si hay versión nueva

BG = "#0f1115"
CARD = "#1a1d24"
CARD_ACTIVE = "#1d2230"
TRACK = "#2a2f3a"
TEXT = "#e8eaf0"
MUTED = "#8b93a5"
ACCENT = "#d97757"
GREEN = "#4ade80"
AMBER = "#fbbf24"
ORANGE = "#fb923c"
RED = "#f87171"
FONT = "Segoe UI"

DIAS = ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"]
MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


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


def exe_asset_url(release):
    for asset in release.get("assets", []):
        if asset.get("name", "").lower() == "claudeusage.exe":
            return asset.get("browser_download_url")
    return None


def can_self_update(release):
    """Solo el .exe compilado se puede reemplazar a sí mismo."""
    return getattr(sys, "frozen", False) and exe_asset_url(release) is not None


def download_update(release):
    """Descarga el .exe nuevo junto al actual (ClaudeUsage.new.exe)."""
    current = Path(sys.executable)
    new = current.with_name(current.stem + ".new.exe")
    with github_request(exe_asset_url(release), 300) as resp, open(new, "wb") as out:
        shutil.copyfileobj(resp, out)
    with open(new, "rb") as f:
        valid = f.read(2) == b"MZ"
    if not valid:
        new.unlink()
        raise RuntimeError("la descarga no es un ejecutable válido")
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
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key, 0, winreg.KEY_SET_VALUE) as handle:
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
    exe = setup_tools.find("cswap")
    if not exe:
        raise RuntimeError("Falta claude-swap: instálalo desde la pestaña Cuentas.")
    env = dict(os.environ, PYTHONIOENCODING="utf-8", NO_COLOR="1")
    proc = subprocess.run(
        [exe, *args], capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=60, creationflags=NO_WINDOW, env=env,
    )
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout).strip() or "cswap falló")
    return proc.stdout


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


class Meter(tk.Canvas):
    """Barra de consumo: se llena según se gasta y pasa de verde a rojo."""

    WIDTH = 400
    HEIGHT = 58
    BAR_Y = 34
    BAR_H = 16

    def __init__(self, master, title, bg):
        super().__init__(master, width=self.WIDTH, height=self.HEIGHT, bg=bg,
                         highlightthickness=0)
        self.title = title

    def pill(self, x1, x2, color):
        r = self.BAR_H / 2
        y1, y2 = self.BAR_Y, self.BAR_Y + self.BAR_H
        if x2 - x1 < 2 * r:
            x2 = x1 + 2 * r
        self.create_oval(x1, y1, x1 + 2 * r, y2, fill=color, outline="")
        self.create_oval(x2 - 2 * r, y1, x2, y2, fill=color, outline="")
        self.create_rectangle(x1 + r, y1, x2 - r, y2, fill=color, outline="")

    def draw(self, used):
        self.delete("all")
        self.create_text(0, 12, text=self.title, anchor="w", fill=TEXT, font=(FONT, 10))
        self.pill(0, self.WIDTH, TRACK)
        if used is None:
            self.create_text(self.WIDTH, 12, text="sin datos", anchor="e", fill=MUTED,
                             font=(FONT, 10))
            return
        color = color_for(used)
        right = self.create_text(self.WIDTH, 12, text=f"usado {used:.0f}%", anchor="e",
                                 fill=color, font=(FONT, 12, "bold"))
        left = self.bbox(right)[0]
        self.create_text(left - 8, 12, text=f"queda {100 - used:.0f}% ·", anchor="e",
                         fill=MUTED, font=(FONT, 9))
        if used > 0:
            self.pill(0, self.WIDTH * used / 100, color)


class AccountCard(tk.Frame):
    def __init__(self, master, app):
        super().__init__(master, bg=CARD, padx=18, pady=14)
        self.app = app
        self.number = None

        head = tk.Frame(self, bg=CARD)
        head.pack(fill="x")
        self.name = tk.Label(head, bg=CARD, fg=TEXT, font=(FONT, 13, "bold"), anchor="w")
        self.name.pack(side="left")
        self.badge = tk.Label(head, text=" ACTIVA ", bg=ACCENT, fg="#1a1a1a",
                              font=(FONT, 8, "bold"))
        self.empty = tk.Label(head, text=" AGOTADA ", bg=RED, fg="#1a1a1a",
                              font=(FONT, 8, "bold"))
        self.button = tk.Label(head, text="Usar esta", bg=TRACK, fg=TEXT,
                               font=(FONT, 9), padx=10, pady=2, cursor="hand2")
        self.button.bind("<Button-1>", lambda _e: self.app.switch_to(self.number))
        self.email = tk.Label(self, bg=CARD, fg=MUTED, font=(FONT, 9), anchor="w")
        self.email.pack(fill="x", pady=(0, 10))

        self.meters = {}
        self.resets = {}
        for key, title in (("fiveHour", "Límite de 5 horas"), ("sevenDay", "Límite semanal")):
            meter = Meter(self, title, CARD)
            meter.pack(anchor="w", pady=(4, 0))
            label = tk.Label(self, bg=CARD, fg=MUTED, font=(FONT, 9), anchor="w")
            label.pack(fill="x", pady=(2, 6))
            self.meters[key] = meter
            self.resets[key] = label
        self.warning = tk.Label(self, bg=CARD, fg=AMBER, font=(FONT, 9), anchor="w")

    def set_bg(self, color):
        stack = [self]
        while stack:
            widget = stack.pop()
            if widget not in (self.badge, self.button, self.empty):
                widget.configure(bg=color)
            stack.extend(widget.winfo_children())

    def update_account(self, acc):
        self.number = acc.get("number")
        self.acc = acc
        self.name.configure(text=acc.get("alias") or acc.get("email", "?"))
        self.email.configure(text=acc.get("email", ""))
        self.badge.pack_forget()
        self.button.pack_forget()
        self.empty.pack_forget()
        usage = acc.get("usage") or {}
        if any((usage.get(k) or {}).get("pct", 0) >= 100 for k in ("fiveHour", "sevenDay")):
            self.empty.pack(side="right", padx=(6, 0))
        if acc.get("active"):
            self.badge.pack(side="right")
            self.set_bg(CARD_ACTIVE)
        else:
            self.button.pack(side="right")
            self.set_bg(CARD)

        for key, meter in self.meters.items():
            pct = (usage.get(key) or {}).get("pct")
            meter.draw(None if pct is None else min(100.0, max(0.0, pct)))

        week = usage.get("sevenDay") or {}
        note = ""
        if acc.get("usageStatus") not in (None, "ok"):
            note = f"⚠ {acc.get('usageStatus')}"
        elif week.get("willLastToReset") is False and week.get("pct", 0) < 100:
            note = "⚠ a este ritmo no llega al reinicio semanal"
        self.warning.configure(text=note)
        if note:
            self.warning.pack(fill="x", pady=(10, 0))
        else:
            self.warning.pack_forget()
        self.tick()

    def tick(self):
        usage = (getattr(self, "acc", None) or {}).get("usage") or {}
        for key, label in self.resets.items():
            label.configure(text=reset_label(parse_time((usage.get(key) or {}).get("resetsAt"))))


def binding_used(acc):
    """El % del límite más gastado de la cuenta (el que te va a cortar antes)."""
    usage = acc.get("usage") or {}
    values = [(usage.get(k) or {}).get("pct") for k in ("fiveHour", "sevenDay")]
    values = [v for v in values if v is not None]
    return max(values) if values else None


def tray_image(used):
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((0, 0, size - 1, size - 1), radius=14,
                        fill=TRACK if used is None else color_for(used))
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
            self.icon.icon = tray_image(binding_used(active))
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


def make_button(master, text, command, primary=False):
    button = tk.Label(master, text=text, bg=ACCENT if primary else TRACK,
                      fg="#1a1a1a" if primary else TEXT,
                      font=(FONT, 9, "bold" if primary else "normal"), padx=10, pady=2,
                      cursor="hand2")
    button.bind("<Button-1>", lambda _e: command())
    return button


class LogBox(tk.Text):
    """Registro de lo que se va haciendo al instalar, para ver dónde falla."""

    def __init__(self, master):
        super().__init__(master, width=1, height=5, bg=CARD, fg=MUTED, font=("Consolas", 8),
                         relief="flat", padx=10, pady=8, wrap="word", state="disabled",
                         highlightthickness=0)
        self.tag_configure("error", foreground=RED)
        self.tag_configure("ok", foreground=GREEN)

    def write(self, line, tag=None):
        if not self.winfo_ismapped():
            self.pack(fill="x")
        self.configure(state="normal")
        self.insert("end", line + "\n", tag or ())
        self.see("end")
        self.configure(state="disabled")

    def clear(self):
        self.configure(state="normal")
        self.delete("1.0", "end")
        self.configure(state="disabled")


class AccountsPage(tk.Frame):
    """Preparar todo y añadir, usar o quitar cuentas sin tocar la terminal."""

    def __init__(self, master, app):
        super().__init__(master, bg=BG)
        self.app = app
        self.status = None     # lo que hay instalado y con qué cuenta se ha iniciado sesión
        self.accounts = None   # las cuentas guardadas, según la última lectura de cswap
        self.content = tk.Frame(self, bg=BG)
        self.content.pack(fill="x")
        tk.Label(self.content, text="Comprobando…", bg=BG, fg=MUTED,
                 font=(FONT, 9)).pack(anchor="w")
        self.log = LogBox(self)

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

    def card(self, title):
        frame = tk.Frame(self.content, bg=CARD, padx=18, pady=14)
        frame.pack(fill="x", pady=(0, 10))
        tk.Label(frame, text=title, bg=CARD, fg=TEXT, font=(FONT, 12, "bold"),
                 anchor="w").pack(fill="x")
        return frame

    def hint(self, master, text, bg=CARD):
        tk.Label(master, text=text, bg=bg, fg=MUTED, font=(FONT, 9), justify="left",
                 anchor="w", wraplength=400).pack(fill="x", pady=(8, 0))

    def render(self):
        if self.status is None:
            return
        for child in self.content.winfo_children():
            child.destroy()
        login = self.status["login"]
        installed = login is not None
        email = (login or {}).get("email") if (login or {}).get("loggedIn") else None
        accounts = self.accounts or []
        saved = [acc.get("email") for acc in accounts]
        steps = [
            ("Instalar Claude Code", installed, "Instalar", self.install_claude),
            ("Iniciar sesión en Claude", bool(email), "Iniciar sesión",
             self.add_account),
            ("Activar el cambio de cuentas", self.status["cswap"] and bool(accounts),
             "Activar", self.save_current),
        ]
        if not all(done for _t, done, _b, _c in steps):
            self.render_steps(steps)
            return

        if email not in saved:
            banner = tk.Frame(self.content, bg=CARD_ACTIVE, padx=14, pady=10)
            banner.pack(fill="x", pady=(0, 10))
            make_button(banner, "Guardarla", self.save_current,
                        primary=True).pack(side="right", padx=(10, 0))
            tk.Label(banner, bg=CARD_ACTIVE, fg=TEXT, font=(FONT, 9), justify="left",
                     anchor="w", wraplength=300,
                     text=f"Claude Code está usando {email}, pero no la tienes guardada "
                          "aquí.").pack(side="left", fill="x")

        box = self.card("Tus cuentas")
        for acc in accounts:
            self.account_row(box, acc)
        add = make_button(box, "+  Añadir una cuenta", self.add_account, primary=True)
        add.configure(pady=6)
        add.pack(fill="x", pady=(14, 0))
        self.hint(box, "Se abre el navegador para que entres con la otra cuenta y se guarda "
                       "sola. No cierres sesión antes en Claude Code.")

    def render_steps(self, steps):
        box = self.card("Vamos a prepararlo")
        self.hint(box, "Son tres pasos y solo hay que hacerlos una vez.")
        current = next(i for i, (_t, done, _b, _c) in enumerate(steps) if not done)
        for i, (title, done, button, command) in enumerate(steps):
            row = tk.Frame(box, bg=CARD)
            row.pack(fill="x", pady=(12, 0))
            mark = "✔" if done else str(i + 1)
            tk.Label(row, text=mark, width=2, font=(FONT, 10, "bold"),
                     bg=GREEN if done else (ACCENT if i == current else TRACK),
                     fg="#1a1a1a" if done or i == current else MUTED).pack(side="left")
            tk.Label(row, text=title, bg=CARD, font=(FONT, 10),
                     fg=TEXT if i == current else MUTED).pack(side="left", padx=(10, 0))
            if i == current:
                make_button(row, button, command, primary=True).pack(side="right")

    def account_row(self, master, acc):
        active = acc.get("active")
        row = tk.Frame(master, bg=CARD_ACTIVE if active else CARD, padx=10, pady=8)
        row.pack(fill="x", pady=(8, 0))
        bg = row.cget("bg")
        names = tk.Frame(row, bg=bg)
        names.pack(side="left", fill="x")
        tk.Label(names, text=acc.get("alias") or acc.get("email", "?"), bg=bg, fg=TEXT,
                 font=(FONT, 10, "bold"), anchor="w").pack(fill="x")
        tk.Label(names, text=acc.get("email", ""), bg=bg, fg=MUTED, font=(FONT, 8),
                 anchor="w").pack(fill="x")
        remove = tk.Label(row, text="✕", bg=bg, fg=MUTED, font=(FONT, 11), cursor="hand2")
        remove.pack(side="right", padx=(8, 0))
        remove.bind("<Button-1>", lambda _e: self.remove(acc))
        if active:
            tk.Label(row, text=" EN USO ", bg=ACCENT, fg="#1a1a1a",
                     font=(FONT, 8, "bold")).pack(side="right")
        else:
            make_button(row, "Usar", lambda: self.app.switch_to(acc.get("number"))
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


class SpendMeter(Meter):
    """Barra con el gasto de tokens estimado: 100 % es usar Claude Code sin plugins."""

    def draw(self, spend):
        self.delete("all")
        self.create_text(0, 12, text=self.title, anchor="w", fill=TEXT, font=(FONT, 10))
        self.pill(0, self.WIDTH, TRACK)
        saved = round((1 - spend) * 100)
        text, color = (f"≈{saved} % menos", GREEN) if saved > 0 else ("sin ahorro", MUTED)
        right = self.create_text(self.WIDTH, 12, text=text, anchor="e", fill=color,
                                 font=(FONT, 12, "bold"))
        left = self.bbox(right)[0]
        self.create_text(left - 8, 12, text=f"{spend * 100:.0f} % del normal ·", anchor="e",
                         fill=MUTED, font=(FONT, 9))
        self.pill(0, self.WIDTH * spend, ACCENT)


class PluginsPage(tk.Frame):
    """Catálogo de herramientas para gastar menos tokens en Claude Code."""

    LABELS = {"missing": ("No instalado", MUTED), "enabled": ("✔ Activo", GREEN),
              "disabled": ("Desactivado", AMBER)}

    LIST_HEIGHT = 420

    def __init__(self, master, app):
        super().__init__(master, bg=BG)
        self.app = app
        self.cards = []

        summary = tk.Frame(self, bg=CARD, padx=18, pady=12)
        summary.pack(fill="x", pady=(0, 10))
        self.spend = SpendMeter(summary, "Gasto estimado", CARD)
        self.spend.pack(anchor="w")
        self.spend.draw(1.0)
        tk.Label(summary, bg=CARD, fg=MUTED, font=(FONT, 8), anchor="w", justify="left",
                 wraplength=400,
                 text="Orientativo, según las pruebas publicadas de cada plugin. Los que "
                      "nadie ha medido no cuentan. Los plugins valen para todas las "
                      "cuentas.").pack(fill="x", pady=(4, 0))

        # el catálogo no cabe entero: va dentro de un canvas con scroll
        holder = tk.Frame(self, bg=BG)
        holder.pack(fill="x", pady=(0, 8))
        canvas = tk.Canvas(holder, bg=BG, height=self.LIST_HEIGHT, highlightthickness=0,
                           width=1)
        canvas.pack(side="left", fill="x", expand=True)
        inner = tk.Frame(canvas, bg=BG)
        window = canvas.create_window(0, 0, window=inner, anchor="nw")
        inner.bind("<Configure>",
                   lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(window, width=e.width))

        def wheel(event):
            canvas.yview_scroll(-1 if event.delta > 0 else 1, "units")
        holder.bind("<Enter>", lambda _e: canvas.bind_all("<MouseWheel>", wheel))
        holder.bind("<Leave>", lambda _e: canvas.unbind_all("<MouseWheel>"))

        for tool in setup_tools.TOOLS:
            card = tk.Frame(inner, bg=CARD, padx=18, pady=12)
            card.pack(fill="x", pady=(0, 8))
            head = tk.Frame(card, bg=CARD)
            head.pack(fill="x")
            tk.Label(head, text=tool.name, bg=CARD, fg=TEXT,
                     font=(FONT, 11, "bold")).pack(side="left")
            tk.Label(head, text=f" {tool.priority.upper()} ", font=(FONT, 7, "bold"),
                     bg=ACCENT if tool.priority == "Alta" else TRACK,
                     fg="#1a1a1a" if tool.priority == "Alta" else TEXT,
                     ).pack(side="left", padx=(8, 0))
            state = tk.Label(head, text="comprobando…", bg=CARD, fg=MUTED, font=(FONT, 9))
            state.pack(side="left", padx=(8, 0))
            if tool.saving is None:
                saving, color = "ahorro sin medir", MUTED
            elif tool.saving > 0:
                saving, color = f"ahorra ≈{tool.saving * 100:g} %".replace(".", ","), GREEN
            else:
                saving, color = "no ahorra", MUTED
            tk.Label(card, text=tool.description, bg=CARD, fg=TEXT, font=(FONT, 9),
                     anchor="w", justify="left", wraplength=360).pack(fill="x", pady=(4, 0))
            lines = [("Bueno", tool.pros, GREEN, MUTED), ("Malo", tool.cons, AMBER, MUTED)]
            if tool.quality_risk:
                lines.append(("  ⚠", "No se ha probado si puede afectar a la calidad del "
                                     "código.", ORANGE, ORANGE))
            for tag, text, tag_color, text_color in lines:
                row = tk.Frame(card, bg=CARD)
                row.pack(fill="x", pady=(3, 0))
                tk.Label(row, text=tag, bg=CARD, fg=tag_color, font=(FONT, 9, "bold"),
                         width=6, anchor="nw").pack(side="left", anchor="n")
                tk.Label(row, text=text, bg=CARD, fg=text_color, font=(FONT, 9),
                         anchor="w", justify="left", wraplength=320).pack(side="left",
                                                                          fill="x")
            bottom = tk.Frame(card, bg=CARD)
            bottom.pack(fill="x", pady=(8, 0))
            tk.Label(bottom, text=saving, bg=CARD, fg=color,
                     font=(FONT, 9, "bold")).pack(side="right")
            buttons = tk.Frame(bottom, bg=CARD)
            buttons.pack(side="left")
            self.cards.append((tool, state, buttons))
        # solo se enseña cuando hay cambios que Claude Code aún no ha cargado
        self.restart_note = tk.Frame(self, bg=CARD_ACTIVE, padx=14, pady=10)
        make_button(self.restart_note, "Reiniciar Claude Code", self.restart_claude,
                    primary=True).pack(side="right", padx=(10, 0))
        tk.Label(self.restart_note, bg=CARD_ACTIVE, fg=TEXT, font=(FONT, 9), anchor="w",
                 justify="left", wraplength=250,
                 text="Has hecho cambios. Reinicia Claude Code para que se apliquen.",
                 ).pack(side="left", fill="x")
        self.log = LogBox(self)

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
            where = {"before": self.log} if self.log.winfo_manager() else {}
            self.restart_note.pack(fill="x", pady=(0, 8), **where)
        self.spend.draw(setup_tools.estimated_spend(
            tool for (tool, _s, _b), status in zip(self.cards, statuses)
            if status == "enabled"))
        for (tool, state, buttons), status in zip(self.cards, statuses):
            text, color = self.LABELS[status]
            state.configure(text=text, fg=color)
            for child in buttons.winfo_children():
                child.destroy()
            if status == "missing":
                make_button(buttons, "Instalar", lambda t=tool: self.install(t),
                            primary=True).pack(side="left")
                continue
            enable = status == "disabled"
            make_button(buttons, "Activar" if enable else "Desactivar",
                        lambda t=tool, e=enable: self.toggle(t, e),
                        primary=enable).pack(side="left")
            make_button(buttons, "Actualizar",
                        lambda t=tool: self.update(t)).pack(side="left", padx=(6, 0))
            make_button(buttons, "Desinstalar",
                        lambda t=tool: self.uninstall(t)).pack(side="left", padx=(6, 0))

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
        count = len(setup_tools.claude_processes())
        sessions = "la sesión" if count == 1 else f"las {count} sesiones"
        if count and not messagebox.askyesno(
                "Reiniciar Claude Code",
                f"Se cerrará {sessions} de Claude Code abierta{'s' if count > 1 else ''} "
                "(terminal y VS Code). Las conversaciones no se pierden: puedes seguirlas con "
                "'claude --continue' o /resume.\n\n¿Cerrarlas ahora?", parent=self):
            return
        self.task("Cerrando Claude Code…", setup_tools.close_claude, changes=False)


class App(tk.Tk):
    def __init__(self, start_hidden=False, listener=None):
        super().__init__()
        self.queue = queue.Queue()
        self.poll_queue()
        self.listener = listener
        if listener:
            threading.Thread(target=self.serve_other_instances, args=(listener,),
                             daemon=True).start()
        self.title("Claude Usage")
        self.configure(bg=BG, padx=16, pady=14)
        self.resizable(False, False)
        icon = Path(getattr(sys, "_MEIPASS", Path(__file__).parent)) / "claude_usage.ico"
        if icon.exists():
            self.iconbitmap(str(icon))
        self.cards = []
        self.busy = False
        self.task_running = False

        top = tk.Frame(self, bg=BG)
        top.pack(fill="x", pady=(0, 10))
        titles = tk.Frame(top, bg=BG)
        titles.pack(side="left")
        tk.Label(titles, text="✳ Uso de Claude", bg=BG, fg=TEXT,
                 font=(FONT, 15, "bold")).pack(anchor="w")
        tk.Label(titles, text="Consumo de cada cuenta", bg=BG, fg=MUTED,
                 font=(FONT, 9)).pack(anchor="w")
        self.pin_var = tk.BooleanVar(value=False)
        pin = tk.Label(top, text="📌", bg=BG, fg=MUTED, font=(FONT, 11), cursor="hand2")
        pin.pack(side="right", padx=(8, 0))
        pin.bind("<Button-1>", lambda _e: self.toggle_pin(pin))
        refresh = tk.Label(top, text="⟳", bg=BG, fg=MUTED, font=(FONT, 15), cursor="hand2")
        refresh.pack(side="right")
        refresh.bind("<Button-1>", lambda _e: self.refresh_all())

        self.update_bar = tk.Frame(self, bg=CARD_ACTIVE, padx=12, pady=8)
        self.update_text = tk.Label(self.update_bar, bg=CARD_ACTIVE, fg=TEXT, font=(FONT, 9),
                                    anchor="w")
        self.update_text.pack(side="left")
        self.update_button = tk.Label(self.update_bar, bg=ACCENT, fg="#1a1a1a",
                                      font=(FONT, 9, "bold"), padx=10, pady=2, cursor="hand2")
        self.update_button.pack(side="right", padx=(10, 0))
        self.update_button.bind("<Button-1>", lambda _e: self.start_update())
        self.release = None
        self.downloading = False

        tabs = tk.Frame(self, bg=BG)
        tabs.pack(fill="x", pady=(0, 10))
        self.pages = tk.Frame(self, bg=BG)
        self.pages.pack(fill="both")
        usage = tk.Frame(self.pages, bg=BG)
        self.body = tk.Frame(usage, bg=BG)
        self.body.pack(fill="both")
        self.status = tk.Label(usage, text="Cargando…", bg=BG, fg=MUTED, font=(FONT, 9),
                               anchor="w")
        self.status.pack(fill="x")
        self.accounts_page = AccountsPage(self.pages, self)
        self.plugins_page = PluginsPage(self.pages, self)
        self.tab_pages = {"Uso": usage, "Cuentas": self.accounts_page,
                          "Plugins": self.plugins_page}
        self.tab_labels = {}
        for name in self.tab_pages:
            label = tk.Label(tabs, text=name, bg=BG, fg=MUTED, font=(FONT, 10, "bold"),
                             padx=10, pady=3, cursor="hand2")
            label.pack(side="left", padx=(0, 4))
            label.bind("<Button-1>", lambda _e, n=name: self.show_tab(n))
            self.tab_labels[name] = label
        self.show_tab("Uso")
        self.autostart = tk.BooleanVar(value=setup_tools.autostart_enabled())
        tk.Checkbutton(self, text="Abrir al iniciar Windows", variable=self.autostart,
                       command=self.toggle_autostart, bg=BG, fg=MUTED, selectcolor=CARD,
                       activebackground=BG, activeforeground=TEXT, font=(FONT, 9),
                       highlightthickness=0, bd=0, cursor="hand2").pack(anchor="w",
                                                                         pady=(8, 0))
        tk.Frame(self, bg=TRACK, height=1).pack(fill="x", pady=(8, 8))
        footer = tk.Frame(self, bg=BG)
        footer.pack(fill="x")
        tk.Label(footer, text="Creado por ", bg=BG, fg=MUTED,
                 font=(FONT, 9)).pack(side="left")
        tk.Label(footer, text="Sergio Bernabé", bg=BG, fg=ACCENT,
                 font=(FONT, 9, "bold")).pack(side="left")
        tk.Label(footer, text=f"v{VERSION}", bg=BG, fg=MUTED,
                 font=(FONT, 9)).pack(side="right")
        self.check_link = tk.Label(footer, text="Buscar actualizaciones ·", bg=BG, fg=MUTED,
                                   font=(FONT, 9, "underline"), cursor="hand2")
        self.check_link.pack(side="right", padx=(0, 4))
        self.check_link.bind("<Button-1>", lambda _e: self.check_now())

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
        for tab, page in self.tab_pages.items():
            page.pack_forget()
            selected = tab == name
            self.tab_labels[tab].configure(bg=TRACK if selected else BG,
                                           fg=TEXT if selected else MUTED)
        self.tab_pages[name].pack(fill="both")

    def run_task(self, log, title, work, after=None):
        """Instalaciones y cambios, de uno en uno, contando lo que pasa en log."""
        if self.task_running:
            log.write("Espera a que termine lo que se está haciendo.", "error")
            return
        self.task_running = True
        log.clear()
        log.write(title)

        def line(text):
            self.post(lambda: log.write(text))

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
        self.attributes("-topmost", self.pin_var.get())
        self.focus_force()

    def quit_app(self):
        if self.tray:
            self.tray.stop()
        self.destroy()

    def toggle_pin(self, label):
        self.pin_var.set(not self.pin_var.get())
        self.attributes("-topmost", self.pin_var.get())
        label.configure(fg=ACCENT if self.pin_var.get() else MUTED)

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
            self.status.configure(text=f"Error: {error}", fg=RED)
            if not setup_tools.find("cswap") and not getattr(self, "sent_to_setup", False):
                self.sent_to_setup = True  # solo la primera vez, para no secuestrar la ventana
                self.show_tab("Cuentas")
            return
        accounts = data.get("accounts", [])
        self.accounts_page.show_accounts(accounts)
        while len(self.cards) < len(accounts):
            card = AccountCard(self.body, self)
            card.pack(fill="x", pady=(0, 10))
            self.cards.append(card)
        while len(self.cards) > len(accounts):
            self.cards.pop().destroy()
        for card, acc in zip(self.cards, accounts):
            card.update_account(acc)
        if self.tray:
            self.tray.update(accounts)
        if not accounts:
            self.status.configure(
                text="Aún no hay cuentas: guárdalas en la pestaña Cuentas.", fg=MUTED)
            return
        self.status.configure(
            text=f"Actualizado {datetime.now():%H:%M} · se refresca cada minuto", fg=MUTED)

    def switch_to(self, number):
        if number is None or self.busy:
            return
        self.busy = True
        self.status.configure(text=f"Cambiando a la cuenta {number}…", fg=MUTED)

        def done(_result, error):
            self.busy = False
            if error:
                self.status.configure(text=f"Error al cambiar: {error}", fg=RED)
            else:
                self.refresh(schedule=False)

        self.run_in_background(lambda: run_cswap("switch", str(number)), done)

    def tick(self):
        for card in self.cards:
            card.tick()
        self.after(TICK_MS, self.tick)

    def check_for_update(self):
        self.after(UPDATE_CHECK_MS, self.check_for_update)
        self.run_in_background(fetch_newer_release, self.on_release)

    def check_now(self):
        if self.check_link.cget("text") == "Buscando… ·":
            return
        self.check_link.configure(text="Buscando… ·")

        def done(release, error):
            if error:
                text = "Sin conexión ·"
            elif release or self.release:
                text = "Hay versión nueva ·"
            else:
                text = "✔ Estás al día ·"
            self.check_link.configure(text=text)
            self.after(5000, lambda: self.check_link.configure(text="Buscar actualizaciones ·"))
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
        self.update_bar.pack(fill="x", pady=(0, 10), before=self.pages)
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
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
    start_hidden = "--tray" in sys.argv
    listener = listen_for_other_instances()
    if listener is None and notify_running_instance(show=not start_hidden):
        sys.exit(0)
    App(start_hidden=start_hidden, listener=listener).mainloop()
