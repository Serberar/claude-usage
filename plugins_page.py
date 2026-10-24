"""La pestaña Plugins: los instalados, con su ficha, activar o desactivar y actualizar.
Instalarlos, quitarlos, añadir otros y cambiar sus fichas se hace en Ajustes."""

import tkinter as tk
import tkinter.messagebox as messagebox

import customtkinter as ctk

import claude_session
import catalog
import plugins
import ponytail
from theme import AMBER, GREEN, MUTED, ORANGE, RED, TRACK
from widgets import (Fold, LogBox, Meter, Page, auto_wrap, button, card, flat_button, notice,
                     segmented, switch, text)

QUALITY_LINES = {
    "sin_probar": ("⚠", "No se ha probado si afecta a la calidad del código.", ORANGE),
    "empeora": ("⚠", "Puede empeorar la calidad del código.", RED),
    "no_afecta": ("✓", "No afecta a la calidad del código.", GREEN),
}


def plugin_details(master, tool):
    """La ficha de un plugin: qué hace, lo bueno y lo malo, la calidad del código y el ahorro."""
    text(master, tool.description, 12, wrap=True).pack(fill="x", pady=(6, 2))
    mark, quality, quality_color = QUALITY_LINES[tool.quality]
    lines = [("Bueno", tool.pros, GREEN, MUTED), ("Malo", tool.cons, AMBER, MUTED),
             (mark, quality, quality_color, quality_color)]
    for tag, value, tag_color, text_color in lines:
        if not value:
            continue
        row = ctk.CTkFrame(master, fg_color="transparent")
        row.pack(fill="x", pady=(4, 0))
        text(row, tag, 12, tag_color, bold=True, width=56).pack(side="left", anchor="n")
        text(row, value, 12, text_color, wrap=True).pack(side="left", fill="x", expand=True)
    if tool.saving is None:
        saving, color = "Ahorro sin medir", MUTED
    elif tool.saving > 0:
        saving, color = f"Ahorra ≈{tool.saving * 100:g} %".replace(".", ","), GREEN
    else:
        saving, color = "No ahorra", MUTED
    text(master, saving, 12, color, bold=True).pack(fill="x", pady=(10, 0))


class PluginsPage(Page):
    """app da run_task y run_in_background; on_status avisa a Ajustes de lo que hay."""

    LABELS = {"enabled": ("● Activo", GREEN), "disabled": ("Desactivado", AMBER)}

    def __init__(self, master, app, on_status):
        super().__init__(master)
        self.app = app
        self.on_status = on_status
        self.tools, self.statuses, self.plugins = [], [], {}
        self.expanded = set()  # nombres de los plugins desplegados

        frame, summary = card(self.body)
        frame.pack(fill="x", pady=(0, 12))
        self.spend = Meter(summary, "Ahorro estimado")
        self.spend.pack(fill="x")
        auto_wrap(self.spend.note)
        self.show_spend(1.0)
        flat_button(summary, "Buscar actualizaciones", self.check_updates).pack(anchor="e",
                                                                              pady=(6, 0))
        self.list = ctk.CTkFrame(self.body, fg_color="transparent")
        self.list.pack(fill="x")
        text(self.list, "Comprobando…", 12, MUTED).pack(anchor="w")

        # solo se enseña cuando hay cambios que Claude Code aún no ha cargado
        self.restart_note, _label, _button = notice(
            self, "Has hecho cambios. Reinicia Claude Code para que se apliquen.",
            "Reiniciar Claude Code", self.restart_claude)
        self.log = LogBox(self, self.anchor)

    def show_spend(self, spend):
        saved = round((1 - spend) * 100)
        self.spend.value.configure(text=f"≈{saved} %" if saved > 0 else "sin ahorro",
                                   text_color=GREEN if saved > 0 else MUTED)
        # cuenta solo lo medido en las pruebas publicadas de cada plugin
        self.spend.note.configure(text="Orientativo, según las pruebas publicadas.")
        # la barra es el ahorro, como dice el título
        self.spend.bar.configure(progress_color=GREEN if saved > 0 else TRACK)
        self.spend.bar.set(max(0, saved) / 100)

    # ── comprobar ──

    def refresh(self):
        tools = catalog.all_tools()  # con lo añadido o cambiado en Ajustes

        def work():
            installed = plugins.plugin_list()
            statuses = [tool.status(installed) for tool in tools]
            return tools, statuses, installed, claude_session.restart_needed()
        self.app.run_in_background(work, self.show_status)

    def show_status(self, result, error):
        if error:
            self.log.write(f"✖ No pude comprobar los plugins: {error}", "error")
            return
        self.tools, self.statuses, self.plugins, restart = result
        if not restart:
            self.restart_note.pack_forget()
        elif not self.restart_note.winfo_ismapped():
            self.pin_bottom(self.restart_note, pady=(10, 0))
        self.show_spend(plugins.estimated_spend(
            tool for tool, status in zip(self.tools, self.statuses) if status == "enabled"))
        self.render()
        self.on_status(self.tools, self.statuses)

    # ── dibujar ──

    def render(self):
        for child in self.list.winfo_children():
            child.destroy()
        installed = [(t, s) for t, s in zip(self.tools, self.statuses) if s != "missing"]
        if not installed:
            text(self.list, "No tienes plugins instalados: se instalan en Ajustes.", 12, MUTED,
                 wrap=True).pack(fill="x")
        for tool, status in installed:
            self.plugin_card(tool, status)

    def plugin_card(self, tool, status):
        frame, box = card(self.list)
        frame.pack(fill="x", pady=(0, 12))
        head = ctk.CTkFrame(box, fg_color="transparent")
        head.pack(fill="x")
        content = ctk.CTkFrame(box, fg_color="transparent")
        fold = Fold(head, content, tool.name, self.expanded)
        # el estado antes que el nombre: si no cabe, se recorta el nombre, no el estado
        label, color = self.LABELS[status]
        state = text(head, label, 12, color)
        state.pack(side="right")
        name = text(head, tool.name, 15, bold=True)
        name.pack(side="left")
        fold.clickable(head, name, state)

        plugin_details(content, tool)
        if tool.has_options:
            options = ctk.CTkFrame(content, fg_color="transparent")
            options.pack(fill="x", pady=(12, 0))
            self.ponytail_options(options)
        row = ctk.CTkFrame(content, fg_color="transparent")
        row.pack(fill="x", pady=(12, 0))
        enable = status == "disabled"
        button(row, "Activar" if enable else "Desactivar", lambda: self.toggle(tool, enable),
               primary=enable).pack(side="left")
        self.version_info(row, tool)

    def version_info(self, row, tool):
        """«Actualizar a X» solo si hay versión nueva; si no, la versión instalada."""
        versions = tool.versions(self.plugins)
        if versions is None:
            # no es un plugin de Claude Code: no hay forma de saber si tiene versión nueva
            button(row, "Actualizar", lambda: self.update(tool)).pack(side="left", padx=(6, 0))
            return
        installed, latest = versions
        if installed and latest and latest != installed:
            button(row, f"Actualizar a {latest}", lambda: self.update(tool),
                   primary=True).pack(side="right")
        elif installed:
            text(row, f"Versión {installed}", 11, MUTED).pack(side="right")

    def ponytail_options(self, frame):
        """Nivel con el que empieza cada sesión y si se ve su barra en Claude Code."""
        row = ctk.CTkFrame(frame, fg_color="transparent")
        row.pack(fill="x")
        text(row, "Nivel", 12, MUTED, bold=True, width=56).pack(side="left")
        levels = segmented(row, ponytail.LEVELS,
                           command=lambda level: self.set_ponytail(level=level))
        levels.set(ponytail.level())
        levels.pack(side="left")
        band = tk.BooleanVar(value=ponytail.band_visible())
        switch(frame, "Mostrar su barra en Claude Code", band,
               lambda: self.set_ponytail(band=band.get()))

    # ── acciones ──

    def task(self, title, work, changes=True, log=None):
        """log: el registro donde se cuenta (el de Ajustes para instalar y desinstalar)."""
        def run(line):
            work(line)
            if changes:
                claude_session.mark_changed()
        self.app.run_task(log or self.log, title, run, after=self.refresh)

    def check_updates(self):
        self.task("Buscando actualizaciones de los plugins…", plugins.refresh_marketplaces,
                  changes=False)

    def set_ponytail(self, level=None, band=None):
        def work(log):
            if level is not None:
                ponytail.set_level(level)
                log(f"> nivel de Ponytail: {level}")
            if band is not None:
                ponytail.set_band(band)
                log(f"> barra de Ponytail: {'visible' if band else 'oculta'}")
        self.task("Cambiando las opciones de Ponytail…", work)

    def toggle(self, tool, enabled):
        verb = "Activando" if enabled else "Desactivando"
        self.task(f"{verb} {tool.name}…", lambda log: tool.set_enabled(enabled, log))

    def update(self, tool, log=None):
        self.task(f"Actualizando {tool.name}…", tool.update, log=log)

    def install(self, tool, log=None):
        def work(line):
            tool.install(line)
            plugins.check_tool(tool, expected=True)
        self.task(f"Instalando {tool.name}…", work, log=log)

    def uninstall(self, tool, log=None):
        if not messagebox.askyesno("Desinstalar", f"¿Desinstalar {tool.name}?", parent=self):
            return

        def work(line):
            tool.uninstall(line)
            plugins.check_tool(tool, expected=False)
        self.task(f"Desinstalando {tool.name}…", work, log=log)

    def restart_claude(self):
        count = len(claude_session.claude_sessions())
        sessions = "la sesión" if count == 1 else f"las {count} sesiones"
        if count and not messagebox.askyesno(
                "Reiniciar Claude Code",
                f"Se cerrará {sessions} de Claude Code abierta{'s' if count > 1 else ''} "
                "(terminal y VS Code). Las conversaciones no se pierden: puedes seguirlas con "
                "'claude --continue' o /resume.\n\n¿Cerrarlas ahora?", parent=self):
            return
        self.task("Cerrando Claude Code…", claude_session.close_claude, changes=False)
