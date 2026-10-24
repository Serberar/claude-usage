"""El catálogo de herramientas con sus fichas, y lo que se cambia en Ajustes: fichas
editadas y plugins añadidos desde GitHub."""

import copy
import re

from plugins import ClaudeMdRules, ContextCompress, CustomPlugin, Plugin, Rtk
from state import load_state, save_state

FICHA = ("description", "pros", "cons", "saving", "quality")  # lo que se edita en Ajustes
NAME = re.compile(r"\w[\w.-]*")  # sin guion delante: el comando lo tomaría por una opción

TOOLS = [
    Plugin(
        "ponytail@ponytail", "DietrichGebert/ponytail", name="Ponytail",
        description="Hace que Claude escriba solo el código necesario, sin complicarlo.",
        pros="El que mejor sale en pruebas independientes (JetBrains): ≈10 % menos de "
             "coste por tarea. Menos código que revisar.",
        cons="En Windows hay un fallo conocido que puede dejar cada mensaje parado unos "
             "segundos. Ahorra menos de lo que anuncia (20 %).",
        saving=0.10, quality="sin_probar", has_options=True,
    ),
    Plugin(
        "caveman@caveman", "JuliusBrussee/caveman", name="Caveman",
        description="Hace que las respuestas de Claude sean mucho más cortas.",
        pros="JetBrains midió ≈8,5 % menos tokens sin perder calidad en el código.",
        cons="Respuestas telegráficas, a veces difíciles de leer. Añade instrucciones a "
             "cada mensaje: en tareas cortas puede no ahorrar nada. Anuncia 65 %.",
        saving=0.085,
    ),
    ClaudeMdRules(
        "https://raw.githubusercontent.com/drona23/claude-token-efficient/main/CLAUDE.md",
        "claude-token-efficient.md", name="claude-token-efficient",
        description="Unas reglas en tu CLAUDE.md para que Claude sea más directo.",
        pros="Sin programas ni riesgos: es solo texto y se quita al momento. En una "
             "prueba bajó ≈40 % los tokens.",
        cons="Esa prueba es una sola y en un proyecto pequeño: aquí contamos solo un 10 % "
             "por prudencia. Se solapa con Caveman y puede chocar con tu CLAUDE.md.",
        saving=0.10, quality="sin_probar",
    ),
    Plugin(
        "claude-magic-compact@magic-compact", "aerovato/magic-compact",
        name="Magic Compact",
        description="Conserva el contexto útil en sesiones largas al compactar.",
        pros="En sesiones largas, al compactar se pierde menos de lo que estabas haciendo.",
        cons="Sin pruebas independientes. Si resume mal, Claude puede olvidar parte de lo "
             "que estabais haciendo. En sesiones cortas no aporta nada.",
        quality="sin_probar",
    ),
    ContextCompress(
        name="context-compress",
        description="Comprime lo que devuelven las herramientas para gastar menos contexto.",
        pros="Las salidas largas (logs, JSON, webs) entran comprimidas y lo completo se "
             "puede buscar después.",
        cons="Bloquea WebFetch y obliga a usar sus herramientas, que a veces no están "
             "cargadas. Necesita Node. Sin pruebas independientes.",
        quality="sin_probar",
    ),
    Rtk(
        name="RTK",
        description="Quita el ruido de lo que la terminal le devuelve a Claude Code.",
        pros="Resume la salida de git, tests y similares antes de que la lea Claude.",
        cons="JetBrains midió que no ahorra: con esfuerzo bajo sale ≈7,6 % más caro. "
             "En Windows su enganche funciona peor que en Linux o WSL.",
        saving=0.0,
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


def plugin_from_form(values, saving_text, taken, custom):
    """Comprueba lo escrito en el formulario de Ajustes y lo deja como se guarda.

    values trae description, pros, cons y quality, y si custom, también repo, plugin y name.
    taken son los nombres de los demás plugins. Lanza ValueError con el mensaje que se le
    enseña al usuario.
    """
    item = dict(values)
    try:
        saving = saving_text.replace(",", ".").rstrip("%").strip()
        item["saving"] = float(saving) / 100 if saving else None
    except ValueError:
        item["saving"] = -1
    if item["saving"] is not None and not 0 <= item["saving"] <= 1:
        raise ValueError("El ahorro es un número entre 0 y 100, o vacío si no se sabe.")
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
