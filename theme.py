"""Colores y letra. Cada color es (claro, oscuro): CustomTkinter usa el que toque según el
tema de Windows."""

import customtkinter as ctk

ctk.set_appearance_mode("system")

BG = ("#f3f4f7", "#0e1015")
CARD = ("#ffffff", "#171a21")
CARD_ALT = ("#f5f6f8", "#1d2129")
BORDER = ("#e2e5ea", "#262b35")
TRACK = ("#e7e9ee", "#272c36")
TEXT = ("#14171c", "#eef0f5")
MUTED = ("#6b7280", "#8d95a6")
ACCENT = ("#c96442", "#e07b56")
ACCENT_HOVER = ("#b35838", "#c96a47")
ON_ACCENT = "#ffffff"
GREEN = ("#15803d", "#4ade80")
AMBER = ("#b45309", "#fbbf24")
ORANGE = ("#c2410c", "#fb923c")
RED = ("#dc2626", "#f87171")
FONT = "Segoe UI Variable Text"  # Windows 11; en Windows 10 Tk usa la de por defecto
MONO = "Cascadia Mono"


def font(size, bold=False):
    return (FONT, size, "bold") if bold else (FONT, size)


def pick(color):
    """El color del tema actual, para lo que no entiende las parejas (claro, oscuro)."""
    return color[1] if ctk.get_appearance_mode() == "Dark" else color[0]


def color_for(used):
    """Verde → amarillo → naranja → rojo según el % usado."""
    if used < 50:
        return GREEN
    if used < 75:
        return AMBER
    if used < 90:
        return ORANGE
    return RED
