"""La pestaña Uso: una tarjeta por cuenta con sus dos límites."""

import customtkinter as ctk

import usage
from theme import ACCENT, AMBER, BORDER, MUTED
from widgets import Meter, Page, button, card, pill, text


class AccountCard:
    """Una cuenta: nombre, si está en uso (o botón para usarla) y sus límites.
    Lo que se enseña lo decide usage.account_view; aquí solo se dibuja."""

    def __init__(self, master, on_switch):
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
        self.meters = {}
        for key, title in usage.LIMITS:
            self.meters[key] = Meter(inner, title)
            self.meters[key].pack(fill="x", pady=(0, 10))
        self.warning = text(inner, "", 11, AMBER, wrap=True)

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
        for widget in (*self.meters.values(), self.warning):
            widget.pack_forget()
        for key, meter in self.meters.items():
            shown = view["meters"][key]
            if not shown["visible"]:
                continue
            meter.pack(fill="x", pady=(0, 10))
            meter.heading.configure(text=shown["title"])
            meter.show(shown["used"])
            meter.show_bar(shown["bar"])
            if not shown["value"]:
                meter.value.configure(text="")
            if not shown["left"] or not shown["value"]:
                meter.left.configure(text="")
            meter.note.configure(text=shown["note"])

        self.warning.configure(text=view["warning"])
        if view["warning"]:
            self.warning.pack(fill="x")

    def tick(self):
        """Las cuentas atrás («en 2h 30m») avanzan sin esperar a cswap."""
        for key, meter in self.meters.items():
            meter.note.configure(text=usage.window_note(usage.window(self.acc or {}, key)))

    def destroy(self):
        self.frame.destroy()


class UsagePage(Page):
    def __init__(self, master, on_switch):
        super().__init__(master)
        self.on_switch = on_switch
        self.cards = []

    def show(self, accounts):
        while len(self.cards) < len(accounts):
            self.cards.append(AccountCard(self.body, self.on_switch))
        while len(self.cards) > len(accounts):
            self.cards.pop().destroy()
        for account_card, acc in zip(self.cards, accounts):
            account_card.update(acc)

    def tick(self):
        for account_card in self.cards:
            account_card.tick()
