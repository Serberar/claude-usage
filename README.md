# Claude Usage

Pequeña app de escritorio para Windows que muestra el consumo de tus cuentas de Claude Code sin tener que abrir el navegador.

Lee las cuentas que gestionas con [claude-swap](https://github.com/realiti4/claude-swap) (`cswap`) y para cada una enseña:

- **Límite de 5 horas** y **límite semanal**: barras que se van llenando con el consumo (verde → amarillo → naranja → rojo).
- Cuándo se vacía cada límite y cuánto falta.
- Qué cuenta está activa y un botón para cambiar a otra.

Además deja un **icono junto al reloj** con el % consumido de la cuenta activa, del color que toque. Con doble clic se abre la ventana y con clic derecho puedes actualizar, cambiar de cuenta o salir.

Las cuentas se detectan solas: si añades o quitas una con `cswap`, aparece o desaparece en menos de un minuto.

Todo se maneja desde la propia ventana, sin terminal:

- **Cuentas**: si falta Claude Code o claude-swap, la app los descarga e instala. Desde ahí guardas la cuenta actual, añades otra (se abre el inicio de sesión de Claude) o quitas una. Con una sola cuenta funciona igual.
- **Plugins**: herramientas para gastar menos tokens ([Ponytail](https://github.com/DietrichGebert/ponytail), [Caveman](https://github.com/JuliusBrussee/caveman), [claude-token-efficient](https://github.com/drona23/claude-token-efficient), [Magic Compact](https://github.com/aerovato/magic-compact), [context-compress](https://github.com/Open330/context-compress), [RTK](https://github.com/rtk-ai/rtk)), cada una con lo bueno y lo malo según las pruebas publicadas. Todas se instalan, actualizan, desinstalan, activan y desactivan con un botón, y una barra estima cuánto gasto de tokens te ahorras con las que tienes activas; si alguna necesita algo más (Node, winget…), lo instala antes.
- **Actualizaciones**: al arrancar mira si hay una versión nueva en Releases y, con un clic, se descarga, se reemplaza y se vuelve a abrir.
- Solo se abre una vez: si ya está abierta, al pulsar el icono aparece la ventana que ya había.

## Requisitos

- Windows
- Nada más: si falta Claude Code o [claude-swap](https://github.com/realiti4/claude-swap), la app los instala desde la pestaña Cuentas.

## Uso

Descarga `ClaudeUsage.exe` desde [Releases](../../releases) y ábrelo. No hace falta instalar Python.

Para que se abra sola al encender el ordenador, marca **Abrir al iniciar Windows** abajo en la ventana: arrancará directamente en la bandeja.

## Ejecutarlo desde el código

```
pip install -r requirements.txt
pythonw claude_usage.pyw
```

Sin `pystray` y `Pillow` funciona igual, pero sin el icono de la bandeja.

## Compilar el .exe

```
pip install pyinstaller -r requirements.txt
python make_icon.py
pyinstaller --noconfirm --onefile --windowed --name ClaudeUsage --icon claude_usage.ico --add-data "claude_usage.ico;." --hidden-import pystray._win32 claude_usage.pyw
```

El ejecutable queda en `dist/ClaudeUsage.exe`. Para publicar una versión, sube `VERSION` en `claude_usage.pyw` y crea una release con la etiqueta `vX.Y.Z` y el `ClaudeUsage.exe` adjunto: las copias instaladas la verán y se actualizarán solas.

---

Creado por **Sergio Bernabé**.
