"""El icono junto al reloj: el % de la cuenta en uso y un menú para cambiar de cuenta."""

import sys
import threading

from PIL import Image, ImageDraw, ImageFont

import usage
from theme import TRACK, color_for
from windows import pin_tray_icon

try:
    import pystray
except ImportError:  # sin icono en la bandeja, la ventana sigue funcionando
    pystray = None


def tray_image(used):
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    # la barra de tareas es oscura casi siempre: colores del tema oscuro
    d.rounded_rectangle((0, 0, size - 1, size - 1), radius=14,
                        fill=TRACK[1] if used is None else color_for(used)[1])
    label = "–" if used is None else f"{used:.0f}"
    try:
        font = ImageFont.truetype("segoeuib.ttf", 40 if len(label) < 3 else 30)
    except OSError:
        font = ImageFont.load_default()
    d.text((size / 2, size / 2), label, fill="#111111", font=font, anchor="mm")
    return img


class Tray:
    """app es la ventana: el menú le pide mostrarse, refrescar, cambiar de cuenta y salir."""

    def __init__(self, app):
        self.app = app
        self.accounts = []
        self.update_tag = None
        self.icon = pystray.Icon("ClaudeUsage", tray_image(None), "Claude Usage",
                                 menu=pystray.Menu(self.menu_items))
        self.icon.run_detached()
        if getattr(sys, "frozen", False):
            # Windows crea la entrada del icono al mostrarlo por primera vez
            threading.Timer(5, pin_tray_icon).start()

    def menu_items(self):
        post = self.app.post
        yield pystray.MenuItem("Mostrar", lambda: post(self.app.show_window), default=True)
        yield pystray.MenuItem("Actualizar", lambda: post(self.app.refresh_usage))
        if self.update_tag:
            yield pystray.MenuItem(f"Instalar versión {self.update_tag}",
                                   lambda: post(self.app.start_update))
        yield pystray.Menu.SEPARATOR
        for acc in self.accounts:
            yield pystray.MenuItem(
                f"Usar {usage.display_name(acc)}",
                (lambda n: lambda: post(lambda: self.app.switch_to(n)))(acc.get("number")),
                checked=(lambda a: lambda _item: bool(a.get("active")))(acc),
                radio=True,
            )
        yield pystray.Menu.SEPARATOR
        yield pystray.MenuItem("Salir", lambda: post(self.app.quit_app))

    def update(self, accounts):
        self.accounts = accounts
        active = next((a for a in accounts if a.get("active")), None)
        if active:
            self.icon.icon = tray_image(usage.tray_value(active))
            self.icon.title = usage.tray_tooltip(active)
        self.icon.update_menu()

    def update_available(self, tag):
        self.update_tag = tag
        self.icon.update_menu()
        try:
            self.icon.notify(f"Hay una versión nueva: {tag}", "Claude Usage")
        except Exception:  # no en todos los Windows salen los avisos
            pass

    def stop(self):
        self.icon.stop()
