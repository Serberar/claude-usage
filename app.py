"""La ventana: cabecera, pestañas y pie. Coordina el refresco del consumo, las tareas de
fondo, el icono de la bandeja y las actualizaciones de la app."""

import queue
import sys
import threading
import traceback
import webbrowser
from datetime import datetime, timezone
from pathlib import Path

import customtkinter as ctk
from PIL import Image

import accounts
import state
import updater
import usage
import windows
from plugins_page import PluginsPage
from settings_page import SettingsPage
from system import find
from theme import ACCENT, BG, BORDER, CARD, MUTED, RED, TRACK, font
from tray import Tray, pystray
from usage_page import UsagePage
from version import VERSION
from widgets import flat_button, notice, segmented, text

REFRESH_MS = 60_000      # cada cuánto se vuelve a leer el consumo de cswap
TICK_MS = 30_000         # cada cuánto avanzan las cuentas atrás
POLL_MS = 150            # cada cuánto se recoge lo que dejan los hilos de fondo
UPDATE_CHECK_MS = 6 * 3600_000  # cada cuánto se mira si hay versión nueva
WIDTH = 360


class App(ctk.CTk):
    def __init__(self, start_hidden=False, listener=None):
        super().__init__(fg_color=BG)
        self.queue = queue.Queue()
        self.poll_queue()
        self.listener = listener
        if listener:
            threading.Thread(target=windows.serve_other_instances,
                             args=(listener, lambda: self.post(self.show_window)),
                             daemon=True).start()
        self.busy = False          # leyendo el consumo o cambiando de cuenta
        self.accounts = []         # la última lectura, para los avisos y el icono
        self.task_running = False  # instalando o cambiando algo (de uno en uno)
        self.pinned = False
        self.release = None
        self.downloading = False

        self.title("Claude Usage")
        self.icon_path = Path(getattr(sys, "_MEIPASS", Path(__file__).parent)) / "claude_usage.ico"
        if self.icon_path.exists():
            self.iconbitmap(str(self.icon_path))
            # CustomTkinter pone el suyo al poco de abrir
            self.after(250, lambda: self.iconbitmap(str(self.icon_path)))
        # tamaño fijo al cambiar de pestaña; se puede redimensionar a mano
        scale = ctk.ScalingTracker.get_window_scaling(self)
        height = min(860, int(self.winfo_screenheight() / scale * 0.85))
        self.geometry(f"{WIDTH}x{height}")
        self.minsize(WIDTH, 520)

        shell = ctk.CTkFrame(self, fg_color="transparent")
        shell.pack(fill="both", expand=True, padx=18, pady=(16, 12))
        self.build_header(shell)
        self.update_bar, self.update_text, self.update_button = notice(
            shell, "", "Actualizar", self.start_update)
        self.build_pages(shell)
        self.build_footer(shell)

        self.tray = Tray(self) if pystray else None
        if self.tray:
            self.protocol("WM_DELETE_WINDOW", self.withdraw)
            if start_hidden:
                self.withdraw()
                self.after(500, self.withdraw)  # a veces Windows la vuelve a mostrar al arrancar
        self.refresh()
        self.settings_page.refresh()
        self.plugins_page.refresh()
        self.after(TICK_MS, self.tick)
        self.after(5000, updater.remove_update_leftovers)
        self.after(3000, self.check_for_update)

    # ── construir ──

    def build_header(self, shell):
        top = ctk.CTkFrame(shell, fg_color="transparent")
        top.pack(fill="x", pady=(0, 14))
        if self.icon_path.exists():
            logo = Image.open(self.icon_path)
            ctk.CTkLabel(top, text="", image=ctk.CTkImage(logo, logo, size=(34, 34))
                         ).pack(side="left", padx=(0, 12))
        # los botones van antes que los títulos: si la ventana es estrecha, se recorta el texto
        self.pin = self.icon_button(top, "📌", self.toggle_pin)
        self.pin.pack(side="right", padx=(4, 0))
        self.icon_button(top, "⟳", self.refresh_all).pack(side="right")
        titles = ctk.CTkFrame(top, fg_color="transparent")
        titles.pack(side="left", fill="x", expand=True)
        text(titles, "Claude Usage", 20, bold=True).pack(fill="x")
        self.status = text(titles, "Cargando…", 12, MUTED, wrap=True)
        self.status.pack(fill="x")

    def build_pages(self, shell):
        self.tabs = segmented(shell, ["Uso", "Plugins", "Ajustes"], command=self.show_tab,
                              height=36, size=13, background=CARD)
        self.tabs.pack(fill="x", pady=(0, 14))
        pages = ctk.CTkFrame(shell, fg_color="transparent")
        pages.pack(fill="both", expand=True)
        self.usage_page = UsagePage(pages, self.switch_to)
        self.settings_page = SettingsPage(pages, self)
        self.plugins_page = PluginsPage(pages, self, on_status=self.settings_page.show_plugins)
        self.tab_pages = {"Uso": self.usage_page, "Plugins": self.plugins_page,
                          "Ajustes": self.settings_page}
        self.show_tab("Uso")

    def build_footer(self, shell):
        ctk.CTkFrame(shell, fg_color=BORDER, height=1).pack(fill="x", pady=(12, 10))
        credit = ctk.CTkFrame(shell, fg_color="transparent")
        credit.pack(fill="x")
        text(credit, "Creado por Sergio Bernabé", 11, MUTED).pack(side="left")
        text(credit, f"Versión {VERSION}", 11, MUTED).pack(side="right")
        self.check_link = flat_button(credit, "Buscar actualizaciones", self.check_now)
        self.check_link.pack(side="right", padx=(0, 2))

    def icon_button(self, master, label, command):
        return ctk.CTkButton(master, text=label, command=command, width=36, height=36,
                             corner_radius=10, font=font(16), fg_color="transparent",
                             hover_color=TRACK, text_color=MUTED)

    # ── ventana ──

    def show_tab(self, name):
        for page in self.tab_pages.values():
            page.pack_forget()
        self.tab_pages[name].pack(fill="both", expand=True)
        self.tabs.set(name)

    def show_window(self):
        self.deiconify()
        self.lift()
        # Windows no deja que un proceso en segundo plano se ponga delante sin más
        self.attributes("-topmost", True)
        self.attributes("-topmost", self.pinned)
        self.focus_force()

    def toggle_pin(self):
        self.pinned = not self.pinned
        self.attributes("-topmost", self.pinned)
        self.pin.configure(text_color=ACCENT if self.pinned else MUTED)

    def quit_app(self):
        if self.tray:
            self.tray.stop()
        self.destroy()

    # ── hilos de fondo ──

    def post(self, fn):
        """Ejecuta fn en el hilo de la ventana (desde la bandeja o hilos de trabajo)."""
        self.queue.put(fn)

    def poll_queue(self):
        # se programa la siguiente vuelta antes de nada: un error en una tarea no puede
        # dejar la cola sin leer (la app se quedaba congelada para siempre)
        self.after(POLL_MS, self.poll_queue)
        while True:
            try:
                fn = self.queue.get_nowait()
            except queue.Empty:
                return
            try:
                fn()
            except Exception as exc:
                traceback.print_exc()
                self.status.configure(text=f"Error: {exc}", text_color=RED)

    def run_in_background(self, work, done):
        def target():
            try:
                result, error = work(), None
            except Exception as exc:  # se le pasa a done para que lo enseñe
                result, error = None, exc
            self.post(lambda: done(result, error))
        threading.Thread(target=target, daemon=True).start()

    def run_task(self, log, title, work, after=None):
        """Instalaciones y cambios, de uno en uno, contando lo que pasa en log."""
        if self.task_running:
            log.write("Espera a que termine lo que se está haciendo.", "error")
            return
        self.task_running = True
        log.clear()
        log.write(title)

        def done(_result, error):
            self.task_running = False
            log.write(f"✖ {error}" if error else "✔ Hecho", "error" if error else "ok")
            if after:
                after()

        self.run_in_background(lambda: work(lambda line: self.post(lambda: log.write(line))),
                               done)

    # ── consumo ──

    def refresh(self, schedule=True):
        if schedule:
            self.after(REFRESH_MS, self.refresh)
        if self.busy:
            return
        self.busy = True
        self.status.configure(text="Actualizando…")
        self.run_in_background(accounts.list_accounts, self.show_usage)

    def refresh_usage(self):
        self.refresh(schedule=False)

    def refresh_all(self):
        self.refresh_usage()
        self.settings_page.refresh()
        self.plugins_page.refresh()

    def show_usage(self, account_list, error):
        self.busy = False
        if error:
            self.status.configure(text=f"Error: {error}", text_color=RED)
            if not find("cswap") and not getattr(self, "sent_to_setup", False):
                self.sent_to_setup = True  # solo la primera vez, para no secuestrar la ventana
                self.show_tab("Ajustes")
            return
        usage.forget_past_windows(account_list, datetime.now(timezone.utc))
        before, self.accounts = self.accounts, account_list
        self.settings_page.show_accounts(account_list)
        self.usage_page.show(account_list)
        self.update_tray()
        if self.tray and state.setting("notify"):
            for message in usage.alerts(before, account_list):
                self.tray.notify(message)
        if state.setting("auto_switch") and len(account_list) > 1:
            self.auto_switch()
        if not account_list:
            self.status.configure(text="Aún no hay cuentas: guárdalas en la pestaña Ajustes.",
                                  text_color=MUTED)
            return
        # la hora en que cswap pidió el consumo de la cuenta en uso, no la de esta lectura
        self.status.configure(text=f"Actualizado {usage.fetched_at(account_list):%H:%M}",
                              text_color=MUTED)

    def update_tray(self):
        if self.tray:
            self.tray.update(self.accounts, state.setting("tray_shows"))

    def auto_switch(self):
        """Ajustes > General: si la cuenta en uso llega al umbral, cswap cambia a la de más
        margen. Una pasada tras cada lectura; así no queda nada de cswap en marcha al salir."""
        if self.busy:
            return
        self.busy = True

        def done(switched, error):
            self.busy = False
            if error:
                self.status.configure(text=f"Cambio automático: {error}", text_color=RED)
            elif switched:
                if self.tray:
                    self.tray.notify(f"Cambiado a {switched.get('email', 'otra cuenta')}: "
                                     "la anterior estaba cerca del límite")
                self.refresh_usage()

        threshold = state.setting("auto_threshold")
        self.run_in_background(lambda: accounts.auto_switch(threshold), done)

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
                self.refresh_usage()

        self.run_in_background(lambda: accounts.switch_account(number), done)

    def tick(self):
        self.usage_page.tick()
        self.after(TICK_MS, self.tick)

    # ── actualizar la app ──

    def check_for_update(self):
        self.after(UPDATE_CHECK_MS, self.check_for_update)
        self.run_in_background(updater.fetch_newer_release, self.on_release)

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

        self.run_in_background(updater.fetch_newer_release, done)

    def on_release(self, release, error):
        if error or not release or self.release:
            return  # sin internet o sin novedades: no molestamos
        self.release = release
        tag = release.get("tag_name", "")
        self.update_text.configure(text=f"Hay una versión nueva: {tag}")
        self.update_button.configure(
            text="Actualizar" if updater.can_self_update(release) else "Descargar")
        self.update_bar.pack(fill="x", pady=(0, 14), before=self.tabs)
        if self.tray:
            self.tray.update_available(tag)

    def start_update(self):
        if not self.release or self.downloading:
            return
        if not updater.can_self_update(self.release):
            webbrowser.open(self.release.get("html_url") or updater.RELEASES_URL)
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

        self.run_in_background(lambda: updater.download_update(self.release), done)

    def apply_update(self, new):
        try:
            exe = updater.install_update(new)
        except OSError as exc:
            self.release = dict(self.release, assets=[])  # a partir de aquí el botón abre la web
            self.update_button.configure(text="Descargar")
            self.update_text.configure(text=f"No se pudo reemplazar el .exe: {exc}")
            return
        if self.listener:  # liberamos el puerto para que la versión nueva no crea que ya hay otra
            self.listener.close()
        updater.restart(exe)
        self.quit_app()
