"""Las piezas de la interfaz que se repiten: textos, botones, tarjetas, barras y plegables."""

import tkinter as tk

import customtkinter as ctk

from theme import (ACCENT, ACCENT_HOVER, BORDER, CARD, CARD_ALT, GREEN, MONO, MUTED,
                   ON_ACCENT, RED, TEXT, TRACK, color_for, font, pick)


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


def big_button(master, label, command, primary=False):
    """El botón ancho de añadir (una cuenta, un plugin)."""
    return ctk.CTkButton(master, text=label, command=command, height=42, corner_radius=10,
                         font=font(13, True), fg_color=ACCENT if primary else TRACK,
                         hover_color=ACCENT_HOVER if primary else BORDER,
                         text_color=ON_ACCENT if primary else TEXT)


def flat_button(master, label, command, color=MUTED, size=11, height=24, **kw):
    """Botón que parece texto: enlaces del pie, quitar, volver a lo de antes…"""
    return ctk.CTkButton(master, text=label, command=command, width=0, height=height,
                         corner_radius=6, font=font(size), fg_color="transparent",
                         hover_color=TRACK, text_color=color, **kw)


def link(master, label, command, color=MUTED):
    """Acción secundaria escrita como texto, ya colocada debajo de lo anterior."""
    flat_button(master, label, command, color, height=30, size=12,
                anchor="w").pack(fill="x", pady=(8, 0))


def pill(master, label, fg, color=ON_ACCENT):
    return ctk.CTkLabel(master, text=f"  {label}  ", font=font(10, True), fg_color=fg,
                        text_color=color, corner_radius=8, height=22)


def switch(master, label, variable, command):
    widget = ctk.CTkSwitch(master, text=label, variable=variable, command=command,
                           font=font(12), text_color=TEXT, progress_color=ACCENT,
                           fg_color=TRACK)
    widget.pack(anchor="w", pady=(10, 0))
    return widget


def segmented(master, values, command=None, height=30, size=12, background=TRACK):
    return ctk.CTkSegmentedButton(
        master, values=values, command=command, height=height, corner_radius=8,
        font=font(size, size > 12), fg_color=background, unselected_color=background,
        unselected_hover_color=BORDER if background == TRACK else TRACK,
        selected_color=ACCENT, selected_hover_color=ACCENT_HOVER, text_color=TEXT)


def entry(master, value="", placeholder=""):
    widget = ctk.CTkEntry(master, height=32, corner_radius=8, font=font(12), fg_color=CARD,
                          border_color=BORDER, text_color=TEXT, placeholder_text=placeholder)
    if value:
        widget.insert(0, value)
    return widget


def textbox(master, value=""):
    widget = ctk.CTkTextbox(master, height=56, corner_radius=8, font=font(12), fg_color=CARD,
                            border_color=BORDER, border_width=1, text_color=TEXT, wrap="word")
    widget.insert("1.0", value)
    return widget


def card(master, accent=False, compact=False):
    """Tarjeta con borde: (marco que se coloca, interior donde va el contenido).
    accent: borde de color, para avisos. compact: más baja, para avisos de una línea."""
    frame = ctk.CTkFrame(master, fg_color=CARD, corner_radius=14 if compact else 16,
                         border_width=1, border_color=ACCENT if accent else BORDER)
    inner = ctk.CTkFrame(frame, fg_color="transparent")
    inner.pack(fill="x", padx=14 if compact else 18, pady=10 if compact else 16)
    return frame, inner


def notice(master, message, action, command):
    """Aviso de una línea con su botón: versión nueva, reiniciar Claude Code…
    Devuelve (marco sin colocar, etiqueta del texto, botón)."""
    frame, row = card(master, accent=True, compact=True)
    action_button = button(row, action, command, primary=True)
    action_button.pack(side="right", padx=(10, 0))
    label = text(row, message, 12, wrap=True)
    label.pack(side="left", fill="x", expand=True)
    return frame, label, action_button


class Meter(ctk.CTkFrame):
    """Un límite: título, % usado, barra que pasa de verde a rojo y cuándo se recarga."""

    def __init__(self, master, title):
        super().__init__(master, fg_color="transparent")
        head = ctk.CTkFrame(self, fg_color="transparent")
        head.pack(fill="x")
        self.heading = text(head, title, 13)
        self.heading.pack(side="left")
        self.value = text(head, "", 16, bold=True)
        self.value.pack(side="right")
        self.left = text(head, "", 11, MUTED)
        self.left.pack(side="right", padx=(0, 8))
        self.bar = ctk.CTkProgressBar(self, height=10, corner_radius=5, fg_color=TRACK,
                                      progress_color=TRACK)
        self.bar.pack(fill="x", pady=(6, 0))
        self.bar.set(0)
        # raya sobre la barra: lo que deberías llevar gastado para llegar justo al reinicio
        self.pace = ctk.CTkFrame(self, width=3, height=16, corner_radius=1, fg_color=TEXT)
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

    def show_bar(self, visible):
        if visible:
            self.bar.pack(fill="x", pady=(6, 0), before=self.note)
        else:
            self.bar.pack_forget()

    def show_pace(self, expected):
        if expected is None or not self.bar.winfo_manager():
            self.pace.place_forget()
        else:
            self.pace.place(in_=self.bar, relx=min(max(expected, 0), 100) / 100, rely=0.5,
                            anchor="center")


class Fold:
    """Flecha en una cabecera que muestra u oculta content sin redibujar nada más.
    opened es el set de claves abiertas: así se recuerda si se vuelve a dibujar la página.
    Se crea antes que lo demás de la cabecera, para que la flecha quede a la derecha del todo."""

    def __init__(self, head, content, key, opened):
        self.content, self.key, self.opened = content, key, opened
        self.chevron = ctk.CTkButton(head, text="▸", width=28, height=28, corner_radius=6,
                                     font=font(18), fg_color="transparent", hover_color=TRACK,
                                     text_color=MUTED, command=self.toggle)
        self.chevron.pack(side="right", padx=(6, 0))
        self.show()

    def clickable(self, *widgets):
        for widget in widgets:
            widget.bind("<Button-1>", lambda _e: self.toggle())
            widget.configure(cursor="hand2")

    def toggle(self):
        self.opened ^= {self.key}
        self.show()

    def show(self):
        if self.key in self.opened:
            self.content.pack(fill="x")
        else:
            self.content.pack_forget()
        self.chevron.configure(text="▾" if self.key in self.opened else "▸")


def fold_row(master, key, opened):
    """Fila plegable dentro de una tarjeta (una cuenta, un plugin en Ajustes).
    Devuelve (cabecera, interior del desplegable, Fold)."""
    row = ctk.CTkFrame(master, fg_color=CARD_ALT, corner_radius=12)
    row.pack(fill="x", pady=(10, 0))
    head = ctk.CTkFrame(row, fg_color="transparent")
    head.pack(fill="x", padx=12, pady=10)
    panel = ctk.CTkFrame(row, fg_color="transparent")
    fold = Fold(head, panel, key, opened)
    inner = ctk.CTkFrame(panel, fg_color="transparent")
    inner.pack(fill="x", padx=12, pady=(0, 12))
    ctk.CTkFrame(inner, fg_color=BORDER, height=1).pack(fill="x", pady=(0, 6))
    return head, inner, fold


def fold_card(master, title, opened):
    """Tarjeta que se pliega por su cabecera (las de Ajustes). Devuelve dónde va su contenido."""
    frame, box = card(master)
    frame.pack(fill="x", pady=(0, 12))
    head = ctk.CTkFrame(box, fg_color="transparent")
    head.pack(fill="x")
    content = ctk.CTkFrame(box, fg_color="transparent")
    fold = Fold(head, content, title, opened)
    label = text(head, title, 17, bold=True)
    label.pack(side="left")
    fold.clickable(head, label)
    return content


class LogBox(ctk.CTkTextbox):
    """Registro de lo que se va haciendo al instalar, para ver dónde falla.

    Aparece abajo de su pestaña (antes de anchor) la primera vez que se escribe algo.
    """

    def __init__(self, master, anchor):
        super().__init__(master, height=120, corner_radius=12, fg_color=CARD,
                         border_width=1, border_color=BORDER, text_color=MUTED,
                         font=(MONO, 11), wrap="word")
        self.anchor = anchor
        self.configure(state="disabled")

    def write(self, line, tag=None):
        if not self.winfo_ismapped():
            self.pack(side="bottom", fill="x", pady=(10, 0), before=self.anchor)
        # aquí y no al crearlo: el tema de Windows puede haber cambiado mientras tanto
        self.tag_config("error", foreground=pick(RED))
        self.tag_config("ok", foreground=pick(GREEN))
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

    def clear(self):
        for child in self.body.winfo_children():
            child.destroy()
