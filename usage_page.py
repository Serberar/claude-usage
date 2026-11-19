"""La pestaña Uso: una tarjeta por cuenta con sus dos límites."""

import customtkinter as ctk

import usage
from theme import ACCENT, AMBER, BORDER, GREEN, MUTED
from widgets import Meter, Page, button, card, flat_button, notice, pill, text


class AccountCard:
    """Una cuenta: nombre, si está en uso (o botón para usarla) y sus límites.
    Lo que se enseña lo decide usage.account_view; aquí solo se dibuja."""

    def __init__(self, master, actions):
        """actions: switch(number), desktop(acc), login(acc) y desktop_installed()."""
        self.actions = actions
        on_switch = actions["switch"]
        self.frame, inner = card(master)
        self.frame.pack(fill="x", pady=(0, 12))
        self.acc = None
        head = ctk.CTkFrame(inner, fg_color="transparent")
        head.pack(fill="x", pady=(0, 12))
        self.names = ctk.CTkFrame(head, fg_color="transparent")
        self.names.pack(side="left", fill="x", expand=True)
        # salta de línea si no cabe junto a EN USO o Usar (ventana de 360 px)
        self.name = text(self.names, "", 16, bold=True, wrap=True)
        self.name.pack(fill="x")
        self.email = text(self.names, "", 11, MUTED)
        self.badge = pill(head, "EN USO", ACCENT)
        self.switch = button(head, "Usar", lambda: on_switch(self.acc.get("number")))
        # la app de escritorio lleva su propia cuenta, aparte de Claude Code
        self.desk = ctk.CTkFrame(inner, fg_color="transparent")
        text(self.desk, "App de escritorio", 11, MUTED).pack(side="left")
        self.desk_badge = pill(self.desk, "EN USO", GREEN, color=("#ffffff", "#0e1015"))
        self.desk_use = flat_button(self.desk, "Usar ahí", lambda: actions["desktop"](self.acc),
                                    color=ACCENT, size=11)
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
        # before=names: las etiquetas se colocan antes que el nombre, que se ajusta al hueco
        self.badge.pack_forget()
        self.switch.pack_forget()
        if view["active"]:
            self.badge.pack(side="right", before=self.names)
        elif view["can_switch"]:
            self.switch.pack(side="right", before=self.names)
        self.frame.configure(border_color=ACCENT if view["active"] else BORDER,
                             border_width=2 if view["active"] else 1)

        # se quitan y se vuelven a poner en orden: así un límite oculto vuelve a su sitio
        for widget in (self.desk, *self.meters.values(), self.warning, self.login):
            widget.pack_forget()
        if self.actions["desktop_installed"]():
            self.desk.pack(fill="x", pady=(0, 10))
            self.desk_badge.pack_forget()
            self.desk_use.pack_forget()
            if view["desktop"]:
                self.desk_badge.pack(side="right")
            elif view["can_use_on_desktop"]:
                self.desk_use.pack(side="right")
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
    def __init__(self, master, actions):
        super().__init__(master)
        self.actions = actions
        on_switch = actions["switch"]
        self.cards = []
        self.best = None
        # arriba, solo si otra cuenta tiene claramente más margen que la que está en uso
        self.best_note, self.best_text, _button = notice(
            self.body, "", "Usar", lambda: self.best and on_switch(self.best.get("number")))

    def show(self, accounts):
        while len(self.cards) < len(accounts):
            self.cards.append(AccountCard(self.body, self.actions))
        while len(self.cards) > len(accounts):
            self.cards.pop().destroy()
        for account_card, acc in zip(self.cards, accounts):
            account_card.update(acc)
        self.best = usage.best_account(accounts)
        self.best_note.pack_forget()
        if self.best and self.cards:
            self.best_text.configure(
                text=f"{usage.display_name(self.best)} tiene más margen "
                     f"(le queda un {usage.headroom(self.best):.0f} %).")
            self.best_note.pack(fill="x", pady=(0, 12), before=self.cards[0].frame)

    def tick(self):
        for account_card in self.cards:
            account_card.tick()
