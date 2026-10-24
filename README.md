# Claude Usage

Pequeña app de escritorio para Windows que muestra el consumo de tus cuentas de Claude Code sin tener que abrir el navegador.

Lee las cuentas que gestionas con [claude-swap](https://github.com/realiti4/claude-swap) (`cswap`) y para cada una enseña:

- **Límite de 5 horas** y **límite semanal**: barras que se van llenando con el consumo (verde → amarillo → naranja → rojo).
- Cuándo se recarga cada límite y cuánto falta.
- En la barra semanal, una raya con lo que deberías llevar gastado para llegar justo al reinicio.
- Qué cuenta está activa y un botón para cambiar a otra. Si otra tiene claramente más margen, un aviso arriba para pasarte a ella.

Además deja un **icono junto al reloj** con el % consumido de la cuenta activa, del color que toque. Con doble clic se abre la ventana y con clic derecho puedes actualizar, cambiar de cuenta o salir.

Las cuentas se detectan solas: si añades o quitas una con `cswap`, aparece o desaparece en menos de un minuto.

Todo se maneja desde la propia ventana, sin terminal:

- **Plugins**: las herramientas para gastar menos tokens que tienes instaladas ([Ponytail](https://github.com/DietrichGebert/ponytail), [Caveman](https://github.com/JuliusBrussee/caveman), [claude-token-efficient](https://github.com/drona23/claude-token-efficient), [Magic Compact](https://github.com/aerovato/magic-compact), [context-compress](https://github.com/Open330/context-compress), [RTK](https://github.com/rtk-ai/rtk)), cada una con lo bueno y lo malo según las pruebas publicadas, si afecta a la calidad del código y cuánto ahorra. Se activan y desactivan con un botón, y se actualizan cuando hay una versión nueva. Una barra estima cuánto te ahorras con las que tienes activas.
- **Ajustes** (cada parte se despliega por separado):
  - **Tus cuentas**: si falta Claude Code o claude-swap, la app los descarga e instala. Desde ahí guardas la cuenta actual, añades otra (se abre el inicio de sesión de Claude), le pones un alias o la quitas. Con una sola cuenta funciona igual.
  - **Plugins**: instalar y desinstalar cada herramienta, cambiar su ficha y añadir otros plugins de Claude Code desde su repositorio de GitHub. Si alguna necesita algo más (Node, winget…), lo instala antes.
  - **General**: abrir al iniciar Windows; que el icono se vea siempre junto al reloj y qué marca (5 horas, semanal o el que vaya peor); avisos de Windows cuando la cuenta en uso pasa del 90 % del límite de 5 horas o una cuenta agotada vuelve a estar disponible; y cambiar de cuenta sola al llegar al 80, 90 o 95 % (con `cswap auto`).
- **Actualizaciones**: al arrancar mira si hay una versión nueva en Releases y, con un clic, se descarga, se comprueba que es la publicada (su huella SHA-256), se reemplaza y se vuelve a abrir.
- Solo se abre una vez: si ya está abierta, al pulsar el icono aparece la ventana que ya había.

## Requisitos

- Windows
- Nada más: si falta Claude Code o [claude-swap](https://github.com/realiti4/claude-swap), la app los instala desde la pestaña Ajustes.

## Uso

Descarga `ClaudeUsage-Setup.exe` desde [Releases](../../releases) y ábrelo. Se instala solo para tu usuario, sin permisos de administrador, y queda en el menú Inicio. No hace falta instalar Python. Se desinstala desde Configuración de Windows.

Si prefieres no instalarla, `ClaudeUsage.exe` es la versión portable: se abre tal cual.

Para que se abra sola al encender el ordenador, marca **Abrir al iniciar Windows** en la pestaña Ajustes: arrancará directamente en la bandeja.

## Ejecutarlo desde el código

```
pip install -r requirements.txt
pythonw claude_usage.pyw
```

Sin `pystray` funciona igual, pero sin el icono de la bandeja.

El consumo lo pide claude-swap a Claude cada 3-10 minutos por cuenta (más a menudo, Claude corta las consultas); la app lo lee cada minuto y arriba pone la hora en que se pidió.

## Código

| Archivo | Qué hace |
|---|---|
| `claude_usage.pyw` | Punto de entrada: una sola copia abierta |
| `app.py` | La ventana: pestañas, refresco del consumo, tareas de fondo, actualizarse |
| `usage_page.py`, `plugins_page.py`, `settings_page.py` | Las tres pestañas |
| `widgets.py`, `theme.py` | Piezas de la interfaz y colores |
| `tray.py` | El icono junto al reloj |
| `usage.py` | Qué se enseña del consumo de cada cuenta (sin interfaz) |
| `accounts.py` | Cuentas, a través de claude-swap |
| `plugins.py`, `catalog.py`, `ponytail.py` | Tipos de herramienta, el catálogo y lo que se cambia en Ajustes, opciones de Ponytail |
| `prerequisites.py` | Instalar lo que falte (Claude Code, claude-swap, uv, Node) |
| `claude_session.py` | Sesiones de Claude Code abiertas y reiniciarlas |
| `updater.py`, `version.py` | Actualizarse sola desde GitHub y la versión |
| `windows.py`, `autostart.py` | Una sola instancia, icono junto al reloj, abrir al iniciar Windows |
| `state.py`, `system.py` | Lo que se guarda (`state.json`) y ejecutar comandos o escribir sin dejar archivos a medias |

## Pruebas

```
python tests.py
```

## Compilar el .exe y el instalador

Hace falta [Inno Setup 6](https://jrsoftware.org/isinfo.php) (`winget install JRSoftware.InnoSetup`).

```
pip install pyinstaller -r requirements.txt
.\build.ps1
```

Deja `dist/ClaudeUsage.exe` y `dist/ClaudeUsage-Setup.exe` con la versión que pone `VERSION` en `version.py`.

Para publicar una versión: sube `VERSION`, ejecuta `.\build.ps1` y crea una release con la etiqueta `vX.Y.Z` y **los dos archivos** adjuntos. Las copias instaladas la verán y se actualizarán solas (usan `ClaudeUsage.exe`; el instalador es para quien la instala por primera vez).

---

Creado por **Sergio Bernabé**.
