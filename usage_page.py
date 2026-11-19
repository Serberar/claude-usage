"""La pestaña Uso: arriba, cómo se usan las cuentas (automático o qué cuenta va en Claude
Code y en la app de escritorio); debajo, una tarjeta por cuenta con sus dos límites."""

from tkinter import messagebox

import customtkinter as ctk

import state
import usage
from theme import ACCENT, AMBER, BORDER, CARD, GREEN, MUTED, TEXT, TRACK, font
from widgets import Meter, Page, button, card, notice, pill, segmented, text

MODE_LABELS = {"auto": "Automático", "manual": "Manual"}
DARK_TEXT = ("#ffffff", "#0e1015")  # sobre el verde claro del tema oscuro


def dropdown(master, command):
    return ctk.CTkOptionMenu(
        master, values=["—"], command=command, width=170, height=30, corner_radius=8,
        font=font(12), dropdown_font=font(12), fg_color=TRACK, button_color=TRACK,
        button_hover_color=BORDER, text_color=TEXT, dropdown_fg_color=CARD,
        dropdown_hover_color=TRACK, dropdown_text_color=TEXT, dynamic_resizing=False)


class UseCard:
    """Cómo se usan las cuentas. Automático: Code y escritorio con la misma cuenta, pasan
    juntos a otra al agotarse. Manual: un desplegable para cada uno, sin cambios solos."""

    def __init__(self, master, actions):
        self.actions = actions
        self.accounts = []
        self.frame, inner = card(master)
        self.frame.pack(fill="x", pady=(0, 12))
        head = ctk.CTkFrame(inner, fg_color="transparent")
        head.pack(fill="x")
        text(head, "Cómo se usan", 15, bold=True).pack(side="left")
        self.mode = segmented(head, list(MODE_LABELS.values()), command=self.change_mode,
                              height=28)
        self.mode.pack(side="right")

        self.auto = ctk.CTkFrame(inner, fg_color="transparent")
        self.explain = text(self.auto, "", 12, MUTED, wrap=True)
        self.explain.pack(fill="x")
        self.now = text(self.auto, "", 12, wrap=True)
        self.now.pack(fill="x", pady=(6, 0))

        self.manual = ctk.CTkFrame(inner, fg_color="transparent")
        self.code_row, self.code_menu = self.row("Claude Code", self.pick_code)
        self.desk_row, self.desk_menu = self.row("Escritorio", self.pick_desktop)
        self.note = text(self.manual, "", 11, MUTED, wrap=True)
        self.note.pack(fill="x", pady=(8, 0))

    # lo que dice el modo automático según lo que esté instalado (Code, escritorio)
    EXPLAIN = {
        (True, True): "Claude Code y la app de escritorio van con la misma cuenta y, "
                      "cuando se agota, pasan solos a la otra.",
        (True, False): "Claude Code usa una cuenta y, cuando se agota, pasa solo a la otra.",
        (False, True): "La app de escritorio usa una cuenta y, cuando se agota, pasa sola a "
                       "la otra.",
    }

    def row(self, label, command):
        line = ctk.CTkFrame(self.manual, fg_color="transparent")
        line.pack(fill="x", pady=(8, 0))
        text(line, label, 13).pack(side="left")
        menu = dropdown(line, command)
        menu.pack(side="right")
        return line, menu

    # ── datos ──

    def labels(self, for_code=True):
        """El nombre de cada cuenta en un desplegable, diciendo si no se puede usar ahí (la
        sesión caducada es la de Claude Code: en el escritorio sí se puede usar)."""
        names = {}
        for acc in self.accounts:
            name = usage.display_name(acc)
            if name in names.values():
                name = f"{name} ({acc.get('number')})"
            if for_code and usage.needs_login(acc):
                name += " · sin sesión"
            elif usage.exhausted(acc, "sevenDay"):
                name += " · agotada"
            names[acc.get("number")] = name
        return names

    def update(self, accounts):
        self.accounts = accounts
        mode = state.mode()
        self.mode.set(MODE_LABELS[mode])
        names, desk_names = self.labels(), self.labels(for_code=False)
        code = next((acc for acc in accounts if acc.get("active")), None)
        desk = next((acc for acc in accounts if acc.get("desktop")), None)
        # solo lo que está instalado en este ordenador
        has_code = self.actions["code_installed"]()
        has_desktop = self.actions["desktop_installed"]()
        if not (has_code or has_desktop):
            has_code = True  # sin ninguno no hay cuentas que enseñar; por si acaso, Code
        self.code_menu.configure(values=list(names.values()) or ["—"])
        self.desk_menu.configure(values=list(desk_names.values()) or ["—"])
        self.code_menu.set(names.get(code.get("number")) if code else "—")
        self.desk_menu.set(desk_names.get(desk.get("number")) if desk else "—")

        self.explain.configure(text=self.EXPLAIN[(has_code, has_desktop)])
        parts = []
        if has_code:
            parts.append(f"Code: {usage.display_name(code) if code else '—'}")
        if has_desktop:
            parts.append(f"Escritorio: {usage.display_name(desk) if desk else '—'}")
        self.now.configure(text="Ahora  ·  " + "  ·  ".join(parts))
        both = has_code and has_desktop
        self.note.configure(text="Nada cambia solo." + (" Puedes poner la misma en los dos."
                                                        if both else ""))

        self.auto.pack_forget()
        self.manual.pack_forget()
        (self.auto if mode == "auto" else self.manual).pack(fill="x", pady=(10, 0))
        for row, shown in ((self.code_row, has_code), (self.desk_row, has_desktop)):
            row.pack_forget()
            if shown:
                row.pack(fill="x", pady=(8, 0), before=self.note)

    # ── elegir ──

    def account_named(self, label, for_code=True):
        names = self.labels(for_code)
        number = next((n for n, name in names.items() if name == label), None)
        return next((acc for acc in self.accounts if acc.get("number") == number), None)

    def change_mode(self, label):
        mode = next(key for key, shown in MODE_LABELS.items() if shown == label)
        state.set_setting("mode", mode)
        self.actions["mode_changed"]()

    def pick_code(self, label):
        acc = self.account_named(label)
        if not acc or acc.get("active"):
            return
        if self.confirm(f"¿Pasar Claude Code a {usage.display_name(acc)}?",
                        "Las sesiones abiertas siguen, ahora con esa cuenta."):
            self.actions["switch"](acc.get("number"))

    def pick_desktop(self, label):
        acc = self.account_named(label, for_code=False)
        if not acc or acc.get("desktop"):
            return
        if self.confirm(f"¿Pasar la app de escritorio a {usage.display_name(acc)}?",
                        "Se cerrará y se volverá a abrir con esa cuenta. La conversación "
                        "abierta se queda en la cuenta anterior."):
            self.actions["desktop"](acc)

    def confirm(self, question, detail):
        """Un desplegable se cambia sin querer con facilidad: se pregunta antes. Si se dice
        que no, vuelve a enseñar la cuenta que había."""
        if messagebox.askyesno("Cambiar de cuenta", f"{question}\n\n{detail}",
                               parent=self.frame):
            return True
        self.update(self.accounts)
        return False


class AccountCard:
    """Una cuenta: nombre, dónde se está usando (CODE, ESCRITORIO) y sus límites.
    Lo que se enseña lo decide usage.account_view; aquí solo se dibuja."""

    def __init__(self, master, actions):
        """actions: login(acc)."""
        self.frame, inner = card(master)
        self.frame.pack(fill="x", pady=(0, 12))
        self.acc = None
        head = ctk.CTkFrame(inner, fg_color="transparent")
        head.pack(fill="x", pady=(0, 12))
        # las etiquetas se colocan antes que el nombre: si no cabe, salta de línea el nombre.
        # Solo se coloca con alguna dentro: un marco vacío ocupa 200x200 y lo descoloca todo
        self.tags = ctk.CTkFrame(head, fg_color="transparent", width=0, height=0)
        self.code_tag = pill(self.tags, "CODE", ACCENT)
        self.desk_tag = pill(self.tags, "ESCRITORIO", GREEN, color=DARK_TEXT)
        self.names = ctk.CTkFrame(head, fg_color="transparent")
        self.names.pack(side="left", fill="x", expand=True)
        self.name = text(self.names, "", 16, bold=True, wrap=True)
        self.name.pack(fill="x")
        self.email = text(self.names, "", 11, MUTED, wrap=True)
        self.meters = {}
        for key, title in usage.LIMITS:
            self.meters[key] = Meter(inner, title)
            self.meters[key].pack(fill="x", pady=(0, 10))
        self.warning = text(inner, "", 11, AMBER, wrap=True)
        self.login = button(inner, "Iniciar sesión", lambda: actions["login"](self.acc),
                            primary=True)

    def update(self, acc):
        self.acc = acc
        view = usage.account_view(acc)
        self.name.configure(text=view["name"])
        if view["email"]:
            self.email.configure(text=view["email"])
            self.email.pack(fill="x")
        else:
            self.email.pack_forget()
        self.code_tag.pack_forget()
        self.desk_tag.pack_forget()
        self.tags.pack_forget()
        if view["active"]:
            self.code_tag.pack(side="left", padx=(6, 0))
        if view["desktop"]:
            self.desk_tag.pack(side="left", padx=(6, 0))
        in_use = view["active"] or view["desktop"]
        if in_use:
            self.tags.pack(side="right", anchor="n", before=self.names)
        self.frame.configure(border_color=ACCENT if in_use else BORDER,
                             border_width=2 if in_use else 1)

        # se quitan y se vuelven a poner en orden: así un límite oculto vuelve a su sitio
        for widget in (*self.meters.values(), self.warning, self.login):
            widget.pack_forget()
        for key, meter in self.meters.items():
            shown = view["meters"][key]
            if not shown["visible"]:
                continue
            meter.pack(fill="x", pady=(0, 10))
            meter.heading.configure(text=shown["title"])
            meter.show(shown["used"])
            meter.show_bar(shown["bar"])
            meter.show_pace(shown["pace"])
            if not shown["value"]:
                meter.value.configure(text="")
            if not shown["left"] or not shown["value"]:
                meter.left.configure(text="")
            meter.note.configure(text=shown["note"])

        self.warning.configure(text=view["warning"])
        if view["warning"]:
            self.warning.pack(fill="x")
        if view["login"]:
            self.login.pack(anchor="w", pady=(8, 0))

    def tick(self):
        """Las cuentas atrás («en 2h 30m») avanzan sin esperar a cswap."""
        for key, meter in self.meters.items():
            meter.note.configure(text=usage.window_note(usage.window(self.acc or {}, key)))

    def destroy(self):
        self.frame.destroy()


class UsagePage(Page):
    """actions: switch(number), desktop(acc), login(acc), code_installed(),
    desktop_installed() y mode_changed()."""

    def __init__(self, master, actions):
        super().__init__(master)
        self.actions = actions
        self.cards = []
        self.best = None
        self.use = UseCard(self.body, actions)
        self.use.frame.pack_forget()  # hasta que haya más de una cuenta
        # en manual, si otra cuenta tiene claramente más margen que la de Claude Code
        self.best_note, self.best_text, _button = notice(
            self.body, "", "Usar en Code",
            lambda: self.best and actions["switch"](self.best.get("number")))

    def show(self, accounts):
        while len(self.cards) < len(accounts):
            self.cards.append(AccountCard(self.body, self.actions))
        while len(self.cards) > len(accounts):
            self.cards.pop().destroy()
        for account_card, acc in zip(self.cards, accounts):
            account_card.update(acc)
        first = self.cards[0].frame if self.cards else None
        self.use.frame.pack_forget()
        if len(accounts) > 1:
            self.use.update(accounts)
            self.use.frame.pack(fill="x", pady=(0, 12), before=first)
        self.best = usage.best_account(accounts) if state.mode() == "manual" else None
        self.best_note.pack_forget()
        if self.best and first:
            self.best_text.configure(
                text=f"{usage.display_name(self.best)} tiene más margen "
                     f"(le queda un {usage.headroom(self.best):.0f} %).")
            self.best_note.pack(fill="x", pady=(0, 12), before=first)

    def tick(self):
        for account_card in self.cards:
            account_card.tick()
