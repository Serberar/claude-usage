"""La ventana: cabecera, pestañas y pie. Coordina el refresco del consumo, las tareas de
fondo, el icono de la bandeja y las actualizaciones de la app."""

import json
import queue
import sys
import threading
import time
import webbrowser
from datetime import datetime, timezone
from pathlib import Path

import customtkinter as ctk
from PIL import Image

import accounts
from applog import log
import desktop
import relay_mcp
import state
import updater
import usage
import windows
from login_dialog import LoginDialog
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
DESKTOP_AUTO_PAUSE = 15 * 60    # tras cambiar sola la app de escritorio, no repetir en tanto
SWITCH_RETRY_MS = 500           # cambiar de cuenta mientras se lee el consumo: se reintenta…
SWITCH_RETRIES = 120            # …durante un minuto como mucho
STATUS_HOLD = 180               # segundos que se queda a la vista un error al iniciar sesión
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
        self.busy = False          # leyendo el consumo o cambiando de cuenta (segundos)
        # iniciar sesión o cambiar la app de escritorio (minutos): mientras tanto el consumo
        # se sigue leyendo, pero no se cambia de cuenta solo
        self.account_task = None
        self.status_hold_until = 0  # hasta cuándo se deja un error a la vista
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
        self.after(2000, refresh_relay_entry)

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
        self.usage_page = UsagePage(pages, {
            "switch": self.switch_to, "desktop": self.use_on_desktop,
            "login": self.relogin, "desktop_installed": desktop.installed,
            "code_installed": lambda: bool(find("claude")),
            "mode_changed": self.mode_changed})
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
                log.exception("error en la ventana")
                self.status.configure(text=f"Error: {exc}", text_color=RED)

    def report_callback_exception(self, kind, value, trace):
        """Errores en botones y temporizadores de Tk: al registro y a la línea de estado."""
        log.error("error en la interfaz", exc_info=(kind, value, trace))
        try:
            self.status.configure(text=f"Error: {value}", text_color=RED)
        except Exception:
            pass

    def run_in_background(self, work, done):
        def target():
            try:
                result, error = work(), None
            except Exception as exc:  # se le pasa a done para que lo enseñe
                result, error = None, exc
                log.warning("tarea de fondo: %s", exc,
                            exc_info=not isinstance(exc, accounts.StepError))
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
        self.run_in_background(read_accounts, self.show_usage)

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
        # la línea de estado antes que los cambios automáticos, que pueden escribir en ella;
        # y no encima de lo que va contando un inicio de sesión o un cambio del escritorio
        if not self.account_task and time.time() >= self.status_hold_until:
            self.show_fetched(account_list)
        if self.tray and state.setting("notify"):
            for message in usage.alerts(before, account_list):
                log.info("aviso: %s", message)
                self.tray.notify(message)
        if desktop.installed():
            self.check_desktop_account(account_list)
        if relay_mcp.installed():
            self.update_relay_status(before, account_list)
        if len(account_list) > 1 and state.mode() == "auto":
            self.auto_switch()
            if desktop.installed():
                self.desktop_auto_switch(account_list)

    def show_fetched(self, account_list):
        if not account_list:
            self.status.configure(text="Aún no hay cuentas: guárdalas en la pestaña Ajustes.",
                                  text_color=MUTED)
            return
        # la hora en que cswap pidió el consumo de la cuenta en uso, no la de esta lectura
        line = f"Actualizado {usage.fetched_at(account_list):%H:%M}"
        if accounts.schema_too_new():
            line += (" · claude-swap es más nuevo que esta app: si algo se ve raro, "
                     "actualiza Claude Usage")
        self.status.configure(text=line, text_color=MUTED)

    def update_relay_status(self, before, account_list):
        """Apunta por cuánto va la cuenta de la app de escritorio: el relevo se guarda solo a
        partir del 90 %. Al cruzarlo, un aviso para saber que ya se está guardando."""
        current = next((acc for acc in account_list if acc.get("desktop")), None)
        known = [usage.used(current, key) for key, _t in usage.LIMITS] if current else []
        known = [value for value in known if value is not None]
        try:
            relay_mcp.write_status(max(known) if known else None)
        except OSError:
            pass
        near = usage.desktop_near_limit(before, account_list, relay_mcp.NEAR)
        if near and self.tray and state.setting("notify"):
            self.tray.notify(f"{usage.display_name(near)} va por el {relay_mcp.NEAR} %: desde "
                             "ahora Claude guarda solo el relevo. Si no lo hace, escribe "
                             "«relevo» en el chat")

    def check_desktop_account(self, account_list):
        """Tras pasar la app de escritorio a una cuenta sin sesión guardada, se entra a mano:
        si se entra con otra (Google elige la que tenga abierta el navegador), se avisa."""
        switched = state.load_state().get("desktop_switch") or {}
        wanted, now = switched.get("org"), desktop.current_org()
        if not wanted or not now or now == wanted:
            return
        if getattr(self, "desktop_mismatch_warned", None) == switched.get("at"):
            return  # una vez por cambio
        self.desktop_mismatch_warned = switched.get("at")
        names = {acc.get("organizationUuid"): acc.get("email") or usage.display_name(acc)
                 for acc in account_list}
        message = (f"La app de escritorio ha entrado con {names.get(now, 'otra cuenta')}, no "
                   f"con {names.get(wanted, 'la elegida')}. Cierra sesión en ella y entra con "
                   "esa: con Google, «Usar otra cuenta»; si no, «Continuar con email»")
        log.info("escritorio: %s", message)
        self.status_hold_until = time.time() + STATUS_HOLD
        self.status.configure(text=message, text_color=RED)
        if self.tray:
            self.tray.notify(message)

    def mode_changed(self):
        """Pestaña Uso: se ha pasado a automático o a manual."""
        log.info("modo: %s", state.mode())
        self.usage_page.show(self.accounts)
        self.refresh_usage()  # en automático, que mire ya si toca cambiar

    def update_tray(self):
        if self.tray:
            self.tray.update(self.accounts, state.setting("tray_shows"))

    def auto_switch(self):
        """Modo automático: si la cuenta de Code llega al umbral, cswap cambia a la de más
        margen. Una pasada tras cada lectura; así no queda nada de cswap en marcha al salir."""
        if self.busy or self.account_task:
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

    def switch_to(self, number, retries=SWITCH_RETRIES):
        if number is None:
            return
        if self.busy:  # se está leyendo el consumo: se cambia de cuenta en cuanto acabe
            if retries:
                self.after(SWITCH_RETRY_MS, lambda: self.switch_to(number, retries - 1))
            else:
                self.status.configure(text="No se pudo cambiar de cuenta: claude-swap no "
                                           "responde. Vuelve a intentarlo.", text_color=RED)
            return
        self.busy = True
        self.status.configure(text=f"Cambiando a la cuenta {number}…", text_color=MUTED)
        log.info("Claude Code: cambio a la cuenta %s", number)

        def done(_result, error):
            self.busy = False
            if error:
                self.status.configure(text=f"Error al cambiar: {error}", text_color=RED)
            else:
                self.refresh_usage()

        self.run_in_background(lambda: accounts.switch_account(number), done)

    def background_step(self, title, work, done_text):
        """Algo largo con cuentas (iniciar sesión, cambiar la app de escritorio): lo que va
        pasando sale arriba, en la línea de estado."""
        if self.account_task:
            self.status.configure(text=f"Espera: {self.account_task}", text_color=MUTED)
            return
        self.account_task = title
        self.status.configure(text=title, text_color=MUTED)
        log.info(title)

        def progress(line):
            if line.strip() and not line.startswith((">", "  ")):  # sin la salida de comandos
                self.post(lambda: self.status.configure(text=line.strip(), text_color=MUTED))

        def done(result, error):
            self.account_task = None
            if error:
                # que dé tiempo a leerlo: el refresco de cada minuto no lo pisa enseguida
                self.status_hold_until = time.time() + STATUS_HOLD
                self.status.configure(text=f"Error: {error}", text_color=RED)
                if self.tray:
                    self.tray.notify(f"No se pudo: {error}")
                return
            message = done_text(result)
            if message and self.tray and state.setting("notify"):
                self.tray.notify(message)
            self.refresh_usage()

        self.run_in_background(lambda: work(progress), done)

    def ask_login_code(self, url, finished, who):
        """Desde un hilo de fondo: enseña la ventana para iniciar sesión pegando el código y
        espera a que se conteste (ver login_dialog)."""
        answer, ready = {}, threading.Event()

        def done(result):
            answer["code"] = result
            ready.set()
        self.post(lambda: LoginDialog(self, url, who, finished, done))
        ready.wait()
        return answer.get("code")

    def relogin(self, acc):
        email = acc.get("email")
        if email:
            self.background_step(f"Iniciando sesión con {email}…",
                                 lambda log: accounts.relogin(
                                     email, log, lambda url, done: self.ask_login_code(
                                         url, done, email)),
                                 lambda _r: None)

    def use_on_desktop(self, acc, automatic=False):
        org, name = acc.get("organizationUuid"), usage.display_name(acc)
        if not org:
            return

        def done_text(saved):
            if not saved:
                return (f"Entra en la app de escritorio con {acc.get('email') or name}. Con "
                        "Google, elige esa cuenta (si no sale, «Usar otra cuenta»); si no, "
                        "«Continuar con email». Solo hace falta esta vez")
            if not automatic:
                return None
            message = f"La app de escritorio ha pasado a {name}: la anterior estaba agotada."
            if relay_mcp.read_relay():
                message += " Escribe «continúa» en un chat nuevo para seguir."
            return message
        self.background_step(f"Pasando la app de escritorio a {name}…",
                             lambda log: desktop.switch_desktop(org, log), done_text)

    def desktop_auto_switch(self, account_list):
        """Modo automático: si la cuenta de la app de escritorio se agota, la pasa a la de
        más margen que ya tenga su sesión guardada. Se cierra y se vuelve a abrir sola: la
        conversación sigue en la otra cuenta, así que se empieza una nueva."""
        last = state.load_state().get("desktop_switch") or {}
        if self.account_task or time.time() - last.get("at", 0) < DESKTOP_AUTO_PAUSE:
            return
        target, warning = usage.desktop_target(account_list, desktop.has_profile)
        if target:
            self.use_on_desktop(target, automatic=True)
        elif warning and warning != getattr(self, "desktop_warned", None):
            self.desktop_warned = warning  # una vez, no cada minuto
            self.status.configure(text=warning, text_color=RED)
            if self.tray:
                self.tray.notify(warning)

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


def refresh_relay_entry():
    """Si el relevo está activado y la app ha cambiado de sitio (versión portable movida),
    la app de escritorio tiene que arrancar el servidor desde el sitio nuevo."""
    try:
        config = json.loads(relay_mcp.config_path().read_text(encoding="utf-8"))
        entry = (config.get("mcpServers") or {}).get(relay_mcp.NAME)
        if entry and entry != relay_mcp.server_entry():
            relay_mcp.set_installed(True)
    except (OSError, ValueError):
        pass


def read_accounts():
    """Las cuentas de cswap con lo que sabe la app de escritorio (qué cuenta usa y su
    consumo, que se ve aunque cswap no pueda leerlo)."""
    account_list = accounts.list_accounts()
    if desktop.installed():
        latest = desktop.latest_samples(desktop.usage_samples())
        usage.add_desktop(account_list, latest, desktop.current_org())
    return account_list
