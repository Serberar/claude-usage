"""Claude Usage: ventana con el uso restante de cada cuenta gestionada por claude-swap."""

import json
import os
import queue
import shutil
import subprocess
import sys
import threading
import tkinter as tk
from datetime import datetime, timezone
from pathlib import Path

try:
    import pystray
    from PIL import Image, ImageDraw, ImageFont
except ImportError:  # sin icono en la bandeja, la ventana sigue funcionando
    pystray = None

REFRESH_MS = 60_000      # cada cuánto se vuelve a consultar cswap
TICK_MS = 30_000         # cada cuánto se recalculan las cuentas atrás

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


def find_cswap():
    found = shutil.which("cswap")
    if found:
        return found
    candidate = Path.home() / ".local" / "bin" / "cswap.exe"
    return str(candidate) if candidate.exists() else None


def run_cswap(*args):
    exe = find_cswap()
    if not exe:
        raise RuntimeError("No encuentro cswap. ¿Está instalado claude-swap?")
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
        self.icon = pystray.Icon("ClaudeUsage", tray_image(None), "Claude Usage",
                                 menu=pystray.Menu(self.menu_items))
        self.icon.run_detached()

    def menu_items(self):
        post = self.app.post
        yield pystray.MenuItem("Mostrar", lambda: post(self.app.show_window), default=True)
        yield pystray.MenuItem("Actualizar", lambda: post(lambda: self.app.refresh(schedule=False)))
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

    def stop(self):
        self.icon.stop()


class App(tk.Tk):
    def __init__(self, start_hidden=False):
        super().__init__()
        self.queue = queue.Queue()
        self.poll_queue()
        self.title("Claude Usage")
        self.configure(bg=BG, padx=16, pady=14)
        self.resizable(False, False)
        icon = Path(getattr(sys, "_MEIPASS", Path(__file__).parent)) / "claude_usage.ico"
        if icon.exists():
            self.iconbitmap(str(icon))
        self.cards = []
        self.busy = False

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
        refresh.bind("<Button-1>", lambda _e: self.refresh())

        self.body = tk.Frame(self, bg=BG)
        self.body.pack(fill="both")
        self.status = tk.Label(self, text="Cargando…", bg=BG, fg=MUTED, font=(FONT, 9),
                               anchor="w")
        self.status.pack(fill="x", pady=(10, 0))
        tk.Frame(self, bg=TRACK, height=1).pack(fill="x", pady=(10, 8))
        footer = tk.Frame(self, bg=BG)
        footer.pack(fill="x")
        tk.Label(footer, text="Creado por ", bg=BG, fg=MUTED,
                 font=(FONT, 9)).pack(side="left")
        tk.Label(footer, text="Sergio Bernabé", bg=BG, fg=ACCENT,
                 font=(FONT, 9, "bold")).pack(side="left")

        self.tray = Tray(self) if pystray else None
        if self.tray:
            self.protocol("WM_DELETE_WINDOW", self.withdraw)
            if start_hidden:
                self.withdraw()
                self.after(500, self.withdraw)  # a veces Windows la vuelve a mostrar al arrancar
        self.refresh()
        self.after(TICK_MS, self.tick)

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

    def show_window(self):
        self.deiconify()
        self.lift()
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
            return
        accounts = data.get("accounts", [])
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
            self.status.configure(text="No hay cuentas en cswap.", fg=MUTED)
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


if __name__ == "__main__":
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
    App(start_hidden="--tray" in sys.argv).mainloop()
