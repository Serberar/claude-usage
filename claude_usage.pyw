"""Claude Usage: consumo de las cuentas de Claude Code, gestión de cuentas y plugins.

Punto de entrada: si ya hay una copia abierta, le pide que enseñe su ventana y se cierra.

Otras formas de arrancarla (no abren la ventana):
  --relevo       el servidor MCP del relevo de conversaciones (lo arranca la app de escritorio)
  --desinstalar  deshace lo que la app cambia fuera de su carpeta (lo llama el desinstalador)
"""

import sys

import applog

if __name__ == "__main__":
    if "--relevo" in sys.argv:
        applog.setup("relevo")
        import relay_mcp
        relay_mcp.serve()
        sys.exit(0)
    if "--desinstalar" in sys.argv:
        applog.setup("desinstalar")
        import relay_mcp
        try:
            if relay_mcp.installed():
                relay_mcp.set_installed(False)
        except OSError:
            applog.log.exception("no se pudo quitar el relevo de la app de escritorio")
        sys.exit(0)

    log = applog.setup()
    from version import VERSION
    from windows import listen_for_other_instances, notify_running_instance

    start_hidden = "--tray" in sys.argv
    listener = listen_for_other_instances()
    if listener is None and notify_running_instance(show=not start_hidden):
        sys.exit(0)
    log.info("Claude Usage %s arranca", VERSION)
    from app import App  # después: si ya hay otra abierta, ni se carga la interfaz
    App(start_hidden=start_hidden, listener=listener).mainloop()
