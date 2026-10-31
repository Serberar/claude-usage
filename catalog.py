"""El catálogo de herramientas con sus fichas, y lo que se cambia en Ajustes: fichas
editadas y plugins añadidos desde GitHub."""

import copy
import re

from plugins import CustomPlugin, Plugin, Rtk
from state import load_state, save_state

FICHA = ("description", "pros", "cons", "saving", "quality")  # lo que se edita en Ajustes
NAME = re.compile(r"\w[\w.-]*")  # sin guion delante: el comando lo tomaría por una opción

TOOLS = [
    Plugin(
        "token-diet@token-diet", "Serberar/token-diet", name="token-diet",
        description="Ahorra tokens: reglas compactas, capturas reducidas, botones de /clear y "
                    "/compact, y auditoría de tokens.",
        pros="Sustituye a Caveman y Ponytail con un solo bloque de reglas por sesión. Reduce "
             "las capturas antes de que Claude las lea y su banda deja compactar al acabar "
             "una tarea sin cortarla. Medido por su autor: entre un 45 % y un 53 % menos, "
             "con el ajuste que recomienda (CLAUDE_CODE_AUTO_COMPACT_WINDOW a 200K).",
        cons="Sin pruebas independientes. Reducir capturas solo funciona en Windows. No "
             "comprime la salida de los comandos: para eso va RTK. Limpiar con /clear "
             "pierde la conversación actual.",
        saving=(0.45, 0.53), quality="sin_probar", recommended=True,
    ),
    Rtk(
        name="RTK",
        description="Quita el ruido de lo que la terminal le devuelve a Claude Code.",
        pros="Resume la salida de git, tests y similares antes de que la lea Claude. En un "
             "uso real quitó ≈29 % de esa salida. Complementa a token-diet, que no la toca.",
        cons="La salida de los comandos es poca parte del coste, así que en total ahorra "
             "poco. JetBrains no vio ahorro con esfuerzo bajo (≈7,6 % más caro). En Windows "
             "su enganche funciona peor que en Linux o WSL.",
        saving=0.01, recommended=True,
    ),
]


# ── lo que se cambia en Ajustes ───────────────────────────────────────────────

def custom_plugins():
    """Los plugins añadidos desde Ajustes, como se guardan: dicts con repo, plugin, name,
    description, pros, cons, saving (0-1 o None) y quality."""
    return load_state().get("custom_plugins", [])


def save_custom_plugin(item, replaces=None):
    """Guarda un plugin propio; replaces es el nombre que tenía si se está editando."""
    items = [p for p in custom_plugins() if p["name"] != (replaces or item["name"])]
    save_state(custom_plugins=items + [item])


def remove_custom_plugin(name):
    save_state(custom_plugins=[p for p in custom_plugins() if p["name"] != name])


def plugin_edits():
    """Las fichas del catálogo cambiadas en Ajustes: {nombre: {campo de FICHA: valor}}."""
    return load_state().get("plugin_edits", {})


def save_plugin_edit(name, values):
    """values None vuelve a la ficha original."""
    edits = plugin_edits()
    if values is None:
        edits.pop(name, None)
    else:
        edits[name] = {key: values[key] for key in FICHA}
    save_state(plugin_edits=edits)


def all_tools():
    """El catálogo, con las fichas cambiadas en Ajustes, y los plugins añadidos allí."""
    edits = plugin_edits()
    tools = []
    for tool in TOOLS:
        if tool.name in edits:
            tool = copy.copy(tool)
            vars(tool).update(edits[tool.name], edited=True)
        tools.append(tool)
    return tools + [
        CustomPlugin(item["plugin"], item["repo"], name=item["name"],
                     description=item.get("description", ""), pros=item.get("pros", ""),
                     cons=item.get("cons", ""), saving=item.get("saving"),
                     quality=item.get("quality", "sin_probar"))
        for item in custom_plugins()]


def detected_plugins(installed, tools):
    """Los plugins de Claude Code instalados por fuera de la app, para verlos como uno más.
    Llamar después de status() en tools: así los añadidos en Ajustes ya saben su id completo."""
    known = {getattr(tool, "plugin_id", None) for tool in tools}
    names = {tool.name for tool in tools}
    found = []
    for plugin_id, info in installed.items():
        if plugin_id in known:
            continue
        name = plugin_id.split("@")[0]
        tool = Plugin(plugin_id, info.get("repo") or "", name=plugin_id if name in names else name,
                      description="Instalado fuera de la app.", pros="", cons="",
                      quality="sin_probar")
        tool.detected = True
        found.append(tool)
    return found


def plugin_from_form(values, saving_text, taken, custom):
    """Comprueba lo escrito en el formulario de Ajustes y lo deja como se guarda.

    values trae description, pros, cons y quality, y si custom, también repo, plugin y name.
    taken son los nombres de los demás plugins. Lanza ValueError con el mensaje que se le
    enseña al usuario.
    """
    item = dict(values)
    saving = saving_text.replace(",", ".").replace("%", "").strip()
    try:
        # un número (8,5) o un rango (3-17)
        parts = [float(part) / 100 for part in saving.split("-")] if saving else []
    except ValueError:
        parts = [-1]
    if len(parts) > 2 or not all(0 <= part <= 1 for part in parts) or parts != sorted(parts):
        raise ValueError("El ahorro es un número entre 0 y 100, un rango como 3-17, o vacío "
                         "si no se sabe.")
    item["saving"] = None if not parts else parts[0] if len(parts) == 1 else parts
    if not custom:
        return {key: item[key] for key in FICHA}
    parts = item["repo"].split("/")
    if len(parts) != 2 or not all(NAME.fullmatch(part) for part in parts):
        raise ValueError("El repositorio va como usuario/repositorio, por ejemplo "
                         "JuliusBrussee/caveman.")
    item["plugin"] = item["plugin"] or parts[1]
    if not NAME.fullmatch(item["plugin"]):
        raise ValueError("El nombre del plugin solo lleva letras, números, punto, guion y "
                         "guion bajo, y no empieza por guion.")
    item["name"] = item["name"] or item["plugin"]
    if item["name"] in taken:
        raise ValueError(f"Ya hay un plugin que se llama {item['name']}.")
    return item
