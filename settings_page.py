"""La pestaña Ajustes: preparar lo que falta, las cuentas, los plugins y las opciones
generales. La página solo coloca las secciones; cada una es su propia clase."""

import tkinter as tk
import tkinter.messagebox as messagebox

import customtkinter as ctk

import accounts
import autostart
import catalog
import plugins
import prerequisites
import state
from plugins_page import plugin_details
from theme import ACCENT, AMBER, GREEN, MUTED, ON_ACCENT, RED, TEXT, TRACK, font
from widgets import (LogBox, Page, big_button, button, card, entry, fold_card, fold_row, link,
                     notice, segmented, switch, text, textbox)
from windows import set_tray_icon_visible, tray_icon_entries


class SettingsPage(Page):
    """app da run_task, run_in_background, refresh_usage y la pestaña de plugins."""

    def __init__(self, master, app):
        super().__init__(master)
        self.app = app
        self.status = None     # lo que hay instalado y con qué cuenta se ha iniciado sesión
        self.accounts = None   # las cuentas guardadas, según la última lectura de cswap
        self.plugins = None    # [(herramienta, estado)], según la última comprobación
        self.open_sections = set()  # tarjetas desplegadas: empiezan plegadas
        self.log = LogBox(self, self.anchor)
        self.account_section = AccountsSection(self)
        self.plugin_section = PluginsSection(self)
        self.general_section = GeneralSection(self)
        text(self.body, "Comprobando…", 12, MUTED).pack(anchor="w")

    # ── datos que llegan ──

    def refresh(self):
        def work():
            return {"login": accounts.claude_login_status(),
                    "cswap": prerequisites.is_ready("cswap")}
        self.app.run_in_background(work, self.show_status)

    def show_status(self, status, error):
        if not error:
            self.status = status
            self.render()

    def show_accounts(self, account_list):
        # llega cada minuto con el consumo: redibujar borraría lo que se esté escribiendo
        def ids(accs):
            return [(a.get("number"), a.get("email"), a.get("alias")) for a in accs or []]
        changed = self.accounts is None or ids(self.accounts) != ids(account_list)
        self.accounts = account_list
        if changed:
            self.render()

    def show_plugins(self, tools, statuses):
        self.plugins = list(zip(tools, statuses))
        self.render()

    # ── dibujar ──

    def render(self):
        if self.status is None:
            return
        self.clear()
        login = self.status["login"]
        email = (login or {}).get("email") if (login or {}).get("loggedIn") else None
        account_list = self.accounts or []
        steps = [
            ("Instalar Claude Code", login is not None, "Instalar",
             self.account_section.install_claude),
            ("Iniciar sesión en Claude", bool(email), "Iniciar sesión",
             self.account_section.add_account),
            ("Activar el cambio de cuentas", self.status["cswap"] and bool(account_list),
             "Activar", self.account_section.save_current),
        ]
        ready = all(done for _t, done, _b, _c in steps)
        if not ready:
            self.render_steps(steps)
        elif email not in [acc.get("email") for acc in account_list]:
            frame, _label, _button = notice(
                self.body, f"Claude Code está usando {email}, pero no la tienes guardada aquí.",
                "Guardarla", self.account_section.save_current)
            frame.pack(fill="x", pady=(0, 12))
        if ready:
            self.account_section.render(self.section("Tus cuentas"), account_list)
        if self.plugins is not None:
            self.plugin_section.render(self.section("Plugins"), self.plugins)
        self.general_section.render(self.section("General"))
        info = self.section("Información")
        for line in ("El consumo se actualiza solo cada minuto; con ⟳ al momento.",
                     "La raya de la barra semanal marca lo que deberías llevar gastado "
                     "para llegar justo al reinicio: si la barra la pasa, vas rápido.",
                     "Los avisos de Windows saltan cuando la cuenta en uso pasa del 90 % del "
                     "límite de 5 horas y cuando una cuenta agotada vuelve a estar disponible.",
                     "El cambio automático usa claude-swap: cambia a la cuenta con más margen "
                     "cuando la que usas llega al límite elegido."):
            text(info, line, 12, MUTED, wrap=True).pack(fill="x", pady=(8, 0))

    def section(self, title):
        return fold_card(self.body, title, self.open_sections)

    def render_steps(self, steps):
        frame, box = card(self.body)
        frame.pack(fill="x", pady=(0, 12))
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

    # ── tareas de las secciones ──

    def task(self, title, work):
        """Cambios en las cuentas: al acabar se vuelve a mirar todo."""
        def after():
            self.refresh()
            self.app.refresh_usage()
        self.app.run_task(self.log, title, work, after=after)


class AccountsSection:
    """Las cuentas guardadas: alias y quitar. Cuál está en uso y cambiar se ve en Uso."""

    def __init__(self, page):
        self.page = page
        self.opened = set()  # números de las cuentas desplegadas

    def render(self, box, account_list):
        for acc in account_list:
            self.row(box, acc)
        big_button(box, "+   Añadir una cuenta", self.add_account,
                   primary=True).pack(fill="x", pady=(16, 0))
        text(box, "Se abre el navegador para que entres con la otra cuenta y se guarda sola. "
                  "No cierres sesión antes en Claude Code.", 11, MUTED,
             wrap=True).pack(fill="x", pady=(10, 0))

    def row(self, master, acc):
        head, inner, fold = fold_row(master, acc.get("number"), self.opened)
        names = ctk.CTkFrame(head, fg_color="transparent")
        names.pack(side="left", fill="x", expand=True)
        name = text(names, acc.get("alias") or acc.get("email", "?"), 13, bold=True, wrap=True)
        name.pack(fill="x")
        fold.clickable(head, names, name)
        if acc.get("alias"):
            text(names, acc.get("email", ""), 11, MUTED, wrap=True).pack(fill="x")

        text(inner, "Alias (vacío para quitarlo)", 11, MUTED).pack(fill="x", pady=(4, 0))
        line = ctk.CTkFrame(inner, fg_color="transparent")
        line.pack(fill="x", pady=(4, 0))
        alias = entry(line, acc.get("alias", ""), acc.get("email", ""))
        button(line, "Guardar", lambda: self.save_alias(acc, alias.get()),
               primary=True).pack(side="right", padx=(8, 0))
        alias.pack(side="left", fill="x", expand=True)
        alias.bind("<Return>", lambda _e: self.save_alias(acc, alias.get()))
        link(inner, "Quitar esta cuenta", lambda: self.remove(acc), RED)

    def save_alias(self, acc, alias):
        self.opened.discard(acc.get("number"))
        self.page.task("Cambiando el alias…",
                       lambda log: accounts.set_alias(acc.get("number"), alias.strip(), log))

    def install_claude(self):
        self.page.task("Instalando Claude Code…",
                       lambda log: prerequisites.ensure("claude", log))

    def save_current(self):
        self.page.task("Guardando la cuenta con la que has iniciado sesión…",
                       accounts.save_current_account)

    def add_account(self):
        self.page.task("Abriendo el inicio de sesión…", accounts.add_another_account)

    def remove(self, acc):
        name = acc.get("alias") or acc.get("email", "?")
        if not messagebox.askyesno(
                "Quitar cuenta", f"¿Quitar {name} de la lista?\n\nPodrás volver a añadirla "
                "cuando quieras.", parent=self.page):
            return
        self.page.task(f"Quitando {name}…",
                       lambda log: accounts.remove_account(acc.get("number"), log))


class PluginsSection:
    """Todos los plugins: su ficha guardada, editarla, instalar, desinstalar y añadir otros.
    Las tareas las hace la pestaña Plugins, pero se cuentan en el registro de Ajustes."""

    def __init__(self, page):
        self.page = page
        self.opened = set()  # nombres de los plugins desplegados

    @property
    def actions(self):
        return self.page.app.plugins_page

    def render(self, box, plugin_states):
        for tool, status in plugin_states:
            self.row(box, tool, status != "missing")
        adder = ctk.CTkFrame(box, fg_color="transparent")
        adder.pack(fill="x", pady=(16, 0))
        self.show_adder(adder)

    def show_adder(self, adder):
        for child in adder.winfo_children():
            child.destroy()
        big_button(adder, "+   Añadir un plugin",
                   lambda: PluginForm(self, adder, None, lambda: self.show_adder(adder))
                   ).pack(fill="x")

    def row(self, master, tool, installed):
        head, inner, fold = fold_row(master, tool.name, self.opened)
        state = text(head, "Instalado" if installed else "No instalado", 12,
                     GREEN if installed else MUTED)
        state.pack(side="right")
        name = text(head, tool.name, 13, bold=True, wrap=True)
        name.pack(side="left", fill="x", expand=True)
        fold.clickable(head, name, state)
        self.panel(inner, tool, installed)

    def panel(self, inner, tool, installed):
        """La ficha guardada y lo que se puede hacer con el plugin."""
        for child in inner.winfo_children()[1:]:  # el primero es la raya de arriba
            child.destroy()
        plugin_details(inner, tool)
        buttons = ctk.CTkFrame(inner, fg_color="transparent")
        buttons.pack(fill="x", pady=(12, 0))
        log = self.page.log
        if installed:
            button(buttons, "Desinstalar", lambda: self.actions.uninstall(tool, log)
                   ).pack(side="left", padx=(0, 6))
        else:
            button(buttons, "Instalar", lambda: self.actions.install(tool, log),
                   primary=True).pack(side="left", padx=(0, 6))

        def edit():
            for child in inner.winfo_children()[1:]:
                child.destroy()
            PluginForm(self, inner, tool, lambda: self.panel(inner, tool, installed))
        button(buttons, "Editar", edit).pack(side="left", padx=(0, 6))
        if tool.edited:
            link(inner, "Volver a la ficha original", lambda: self.restore(tool))
        if tool.custom and not installed:
            link(inner, "Quitar de la lista", lambda: self.remove(tool), RED)

    def saved(self, name=None):
        if name:
            self.opened.add(name)
        self.actions.refresh()

    def restore(self, tool):
        catalog.save_plugin_edit(tool.name, None)
        self.saved()

    def remove(self, tool):
        if not messagebox.askyesno("Quitar de la lista", f"¿Quitar {tool.name} de la lista?",
                                   parent=self.page):
            return
        catalog.remove_custom_plugin(tool.name)
        self.saved()

    def taken_names(self, tool):
        names = {t.name for t, _s in self.page.plugins or []}
        return names - ({tool.name} if tool else set())


class PluginForm:
    """Editar la ficha de un plugin (tool) o añadir uno desde su repositorio de GitHub
    (tool None). Los del catálogo no cambian de repositorio ni de nombre."""

    def __init__(self, section, master, tool, on_cancel):
        self.section, self.tool = section, tool
        self.form = ctk.CTkFrame(master, fg_color="transparent")
        self.form.pack(fill="x", pady=(6, 0))
        for child in master.winfo_children():
            if child is not self.form and tool is None:
                child.destroy()  # el botón de añadir se cambia por el formulario
        if tool is None:
            text(self.form, "Añadir un plugin", 15, bold=True).pack(fill="x")
            text(self.form, "Un plugin es código que Claude Code ejecuta con tus permisos: "
                            "añade solo repositorios de los que te fíes.", 11, AMBER,
                 wrap=True).pack(fill="x", pady=(4, 0))
        self.source = {}
        if tool is None or tool.custom:
            item = next((p for p in catalog.custom_plugins()
                         if tool and p["name"] == tool.name), {})
            self.source = {
                "repo": self.field(entry, "Repositorio de GitHub", item.get("repo", ""),
                                   "usuario/repositorio"),
                "plugin": self.field(entry, "Nombre del plugin en ese repositorio",
                                     item.get("plugin", ""),
                                     "si se deja vacío, el del repositorio"),
                "name": self.field(entry, "Nombre que se ve", item.get("name", "")),
            }
        self.description = self.field(entry, "Qué hace", tool.description if tool else "")
        self.pros = self.field(textbox, "Lo bueno", tool.pros if tool else "")
        self.cons = self.field(textbox, "Lo malo", tool.cons if tool else "")
        saving = tool.saving if tool else None
        self.saving = self.field(entry, "Ahorro aproximado en %",
                                 "" if saving is None else f"{saving * 100:g}",
                                 "vacío si no se sabe")
        text(self.form, "Calidad del código", 11, MUTED).pack(fill="x", pady=(8, 2))
        self.quality = segmented(self.form, list(plugins.QUALITY.values()))
        self.quality.set(plugins.QUALITY[tool.quality if tool else "sin_probar"])
        self.quality.pack(anchor="w")
        buttons = ctk.CTkFrame(self.form, fg_color="transparent")
        buttons.pack(fill="x", pady=(14, 0))
        button(buttons, "Guardar", self.save, primary=True).pack(side="left")
        button(buttons, "Cancelar", lambda: (self.form.destroy(), on_cancel())
               ).pack(side="left", padx=(6, 0))

    def field(self, make, label, *args):
        text(self.form, label, 11, MUTED).pack(fill="x", pady=(8, 2))
        widget = make(self.form, *args)
        widget.pack(fill="x")
        return widget

    def save(self):
        values = {key: widget.get().strip() for key, widget in self.source.items()}
        values.update(description=self.description.get().strip(),
                      pros=self.pros.get("1.0", "end").strip(),
                      cons=self.cons.get("1.0", "end").strip(),
                      quality=next(k for k, v in plugins.QUALITY.items()
                                   if v == self.quality.get()))
        custom = self.tool is None or self.tool.custom
        try:
            item = catalog.plugin_from_form(values, self.saving.get(),
                                            self.section.taken_names(self.tool), custom)
        except ValueError as exc:
            messagebox.showerror("Plugin", str(exc), parent=self.section.page)
            return
        if custom:
            catalog.save_custom_plugin(item, replaces=self.tool.name if self.tool else None)
            self.section.saved(item["name"])
        else:
            catalog.save_plugin_edit(self.tool.name, item)
            self.section.saved()


class GeneralSection:
    """Abrir al iniciar Windows, el icono junto al reloj, los avisos y el cambio automático."""

    TRAY_SHOWS = {"five": "5 horas", "week": "Semanal", "worst": "El peor"}
    THRESHOLDS = (80, 90, 95)

    def __init__(self, page):
        self.page = page
        self.autostart = tk.BooleanVar(value=autostart.autostart_enabled())

    def render(self, box):
        switch(box, "Abrir al iniciar Windows", self.autostart, self.toggle_autostart)
        entries = tray_icon_entries()
        if entries:  # Windows 11 y el icono ya creado
            tray = tk.BooleanVar(value=any(entries.values()))
            switch(box, "Icono siempre visible junto al reloj", tray,
                   lambda: self.toggle_tray_icon(tray))
        self.choice(box, "El icono marca", self.TRAY_SHOWS, "tray_shows",
                    after=self.page.app.update_tray)
        self.setting_switch(box, "Avisos de Windows", "notify")

        auto = self.setting_switch(box, "Cambiar de cuenta sola al llegar al límite",
                                   "auto_switch", after=lambda: show_threshold())
        threshold = self.choice(box, "Al llegar al", {n: f"{n} %" for n in self.THRESHOLDS},
                                "auto_threshold")

        def show_threshold():
            if auto.get():
                threshold.pack(fill="x", pady=(8, 0))
            else:
                threshold.pack_forget()
        show_threshold()

    def setting_switch(self, box, label, name, after=None):
        """Interruptor de una opción guardada (state.SETTINGS)."""
        var = tk.BooleanVar(value=state.setting(name))

        def changed():
            state.set_setting(name, var.get())
            if after:
                after()
        switch(box, label, var, changed)
        return var

    def choice(self, box, label, options, name, after=None):
        """Fila con una etiqueta y un selector de una opción guardada; devuelve la fila."""
        row = ctk.CTkFrame(box, fg_color="transparent")
        row.pack(fill="x", pady=(10, 0))
        text(row, label, 12).pack(side="left")
        by_label = {shown: value for value, shown in options.items()}

        def changed(shown):
            state.set_setting(name, by_label[shown])
            if after:
                after()
        selector = segmented(row, list(options.values()), command=changed, height=28)
        selector.set(options.get(state.setting(name), next(iter(options.values()))))
        selector.pack(side="right")
        return row

    def toggle_autostart(self):
        self.flip(self.autostart, autostart.set_autostart, "Abrir al iniciar Windows")

    def toggle_tray_icon(self, var):
        self.flip(var, set_tray_icon_visible, "Icono junto al reloj")

    def flip(self, var, apply, title):
        try:
            apply(var.get())
        except OSError as exc:
            var.set(not var.get())
            messagebox.showerror(title, f"No se pudo cambiar: {exc}", parent=self.page)
