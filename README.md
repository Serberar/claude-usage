# Claude Usage

Pequeña app de escritorio para Windows que muestra el consumo de tus cuentas de Claude Code sin tener que abrir el navegador.

Lee las cuentas que gestionas con [claude-swap](https://github.com/realiti4/claude-swap) (`cswap`) y para cada una enseña:

- **Límite de 5 horas** y **límite semanal**: barras que se van llenando con el consumo (verde → amarillo → naranja → rojo).
- Cuándo se vacía cada límite y cuánto falta.
- Qué cuenta está activa y un botón para cambiar a otra.

Además deja un **icono junto al reloj** con el % consumido de la cuenta activa, del color que toque. Con doble clic se abre la ventana y con clic derecho puedes actualizar, cambiar de cuenta o salir.

Las cuentas se detectan solas: si añades o quitas una con `cswap`, aparece o desaparece en menos de un minuto.

## Requisitos

- Windows
- [claude-swap](https://github.com/realiti4/claude-swap) instalado y con tus cuentas añadidas (`cswap add`)

## Uso

Descarga `ClaudeUsage.exe` desde [Releases](../../releases) y ábrelo. No hace falta instalar Python.

Para que se abra solo al encender el ordenador, directamente en la bandeja:

1. Pulsa `Win + R`, escribe `shell:startup` y pulsa Enter.
2. Crea ahí un acceso directo a `ClaudeUsage.exe` y añade ` --tray` al final del destino.

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

El ejecutable queda en `dist/ClaudeUsage.exe`.

---

Creado por **Sergio Bernabé**.
