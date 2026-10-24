"""Claude Usage: consumo de las cuentas de Claude Code, gestión de cuentas y plugins.

Punto de entrada: si ya hay una copia abierta, le pide que enseñe su ventana y se cierra.
"""

import sys

from windows import listen_for_other_instances, notify_running_instance

if __name__ == "__main__":
    start_hidden = "--tray" in sys.argv
    listener = listen_for_other_instances()
    if listener is None and notify_running_instance(show=not start_hidden):
        sys.exit(0)
    from app import App  # después: si ya hay otra abierta, ni se carga la interfaz
    App(start_hidden=start_hidden, listener=listener).mainloop()
