"""La ventana para iniciar sesión en Claude Code pegando el código.

Claude autoriza la cuenta que el navegador tenga abierta en claude.ai, aunque se le pida
otra. Por eso se enseña el enlace para abrirlo en una ventana privada (sin esa sesión), y
el código que da la página al acabar se pega aquí.
"""

import customtkinter as ctk

from theme import ACCENT, BG, GREEN, MUTED, RED
from widgets import button, entry, text

POLL_MS = 500  # cada cuánto se mira si el inicio de sesión ha terminado por su cuenta


class LoginDialog(ctk.CTkToplevel):
    """who: el email con el que hay que entrar (o una descripción). on_done(resultado):
    el código pegado, "" si el inicio de sesión terminó solo, o None si se cancela."""

    def __init__(self, master, url, who, finished, on_done):
        super().__init__(master, fg_color=BG)
        self.url, self.finished, self.on_done = url, finished, on_done
        self.answered = False
        self.title("Iniciar sesión en Claude")
        self.geometry("420x470")
        self.resizable(False, False)
        self.attributes("-topmost", True)
        self.protocol("WM_DELETE_WINDOW", self.cancel)

        box = ctk.CTkFrame(self, fg_color="transparent")
        box.pack(fill="both", expand=True, padx=20, pady=18)
        text(box, f"Iniciar sesión con {who}", 16, bold=True, wrap=True).pack(fill="x")
        steps = (
            "1. Copia el enlace y ábrelo en una ventana privada del navegador (Firefox: "
            "Ctrl+Mayús+P; Chrome y Edge: Ctrl+Mayús+N). Así no se cuela la cuenta que "
            "tengas abierta en claude.ai.",
            f"2. Entra con {who} y pulsa Autorizar.",
            "3. Copia el código que te enseña la página y pégalo abajo.",
        )
        for step in steps:
            text(box, step, 12, wrap=True).pack(fill="x", pady=(10, 0))
        text(box, "Si se abre una pestaña del navegador sola, ciérrala sin pulsar Autorizar.",
             11, MUTED, wrap=True).pack(fill="x", pady=(10, 0))

        self.copy = button(box, "Copiar enlace", self.copy_url, primary=True)
        self.copy.pack(fill="x", pady=(14, 0))
        text(box, "Código", 11, MUTED).pack(fill="x", pady=(14, 2))
        self.code = entry(box, placeholder="pégalo aquí")
        self.code.pack(fill="x")
        self.code.bind("<Return>", lambda _e: self.submit())
        self.error = text(box, "", 11, RED, wrap=True)
        self.error.pack(fill="x", pady=(4, 0))
        row = ctk.CTkFrame(box, fg_color="transparent")
        row.pack(fill="x", pady=(10, 0))
        button(row, "Continuar", self.submit, primary=True).pack(side="right")
        button(row, "Cancelar", self.cancel).pack(side="right", padx=(0, 8))

        self.after(100, self.lift)
        self.after(150, self.focus_force)
        self.after(POLL_MS, self.poll)

    def copy_url(self):
        self.clipboard_clear()
        self.clipboard_append(self.url)
        self.copy.configure(text="✓ Enlace copiado", fg_color=GREEN)
        self.after(2500, lambda: self.copy.configure(text="Copiar enlace", fg_color=ACCENT))

    def submit(self):
        code = self.code.get().strip()
        if not code:
            self.error.configure(text="Pega el código que te da la página al autorizar.")
            return
        self.finish(code)

    def cancel(self):
        self.finish(None)

    def poll(self):
        """Si se autorizó en la pestaña que abre Claude Code, ya no hace falta el código."""
        if self.answered:
            return
        if self.finished():
            self.finish("")
        else:
            self.after(POLL_MS, self.poll)

    def finish(self, result):
        if self.answered:
            return
        self.answered = True
        self.destroy()
        self.on_done(result)
