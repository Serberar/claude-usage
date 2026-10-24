"""Comprueba lo delicado: lo que escribe en tus archivos, el estado guardado, los plugins,
qué se enseña del consumo y la descarga de versiones nuevas.

Se ejecuta con: python tests.py
"""

import hashlib
import io
import json
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import catalog
import plugins
import state
import system
import updater
import usage

NOW = datetime(2026, 10, 24, 12, 0, tzinfo=timezone.utc)


def iso(dt):
    return dt.isoformat()


def test_versions():
    # 1.10 es más nueva que 1.9 (no se comparan como texto)
    assert updater.version_tuple("v1.10.0") > updater.version_tuple("v1.9.0")
    assert updater.version_tuple("v1.1.2") > updater.version_tuple("1.1.1")
    assert not updater.version_tuple("v1.1.2") > updater.version_tuple("v1.1.2")


def test_write_atomic(tmp):
    target = tmp / "sub" / "a.txt"
    system.write_atomic(target, "uno\r\ndos\r\n")
    assert target.read_bytes() == b"uno\r\ndos\r\n"  # los saltos de línea, tal cual
    system.write_atomic(target, "otro")
    assert target.read_text(encoding="utf-8") == "otro"
    assert [p.name for p in target.parent.iterdir()] == ["a.txt"]  # sin temporales sueltos


def test_state(tmp):
    state.STATE_FILE = tmp / "state.json"
    state.save_state(a=1)
    state.save_state(b=2)
    assert state.load_state() == {"a": 1, "b": 2}
    # roto: se aparta (no se pierde) y la app sigue con lo que hay
    state.STATE_FILE.write_text("{a medias", encoding="utf-8")
    assert state.load_state() == {}
    assert (tmp / "state.json.roto").read_text(encoding="utf-8") == "{a medias"


def test_claude_md_rules(tmp):
    # activar y desactivar las reglas no toca el resto, ni los saltos de línea de Windows,
    # ni las líneas que no son UTF-8
    plugins.CLAUDE_DIR = tmp
    claude_md = tmp / "CLAUDE.md"
    original = "# Mis reglas\r\nHabla en espa\xf1ol\r\n@RTK.md\r\n".encode("latin-1")
    claude_md.write_bytes(original)
    rules = plugins.ClaudeMdRules("https://example.invalid", "reglas.md", name="x",
                                  description="", pros="", cons="")
    rules.file.write_text("regla", encoding="utf-8")
    rules.set_enabled(True, print)
    assert rules.status({}) == "enabled"
    rules.set_enabled(True, print)  # dos veces no la duplica
    assert claude_md.read_bytes().count(b"@reglas.md") == 1
    rules.set_enabled(False, print)
    assert rules.status({}) == "disabled"
    assert claude_md.read_bytes() == original


def test_custom_plugins(tmp):
    # se guardan, salen tras el catálogo y se reconocen ya instalados por nombre Y
    # repositorio: otro "cosa" de otro repositorio no es el nuestro
    state.STATE_FILE = tmp / "state.json"
    catalog.save_custom_plugin({"repo": "alguien/cosa", "plugin": "cosa", "name": "Cosa",
                                "saving": 0.05, "quality": "empeora"})
    custom = catalog.all_tools()[-1]
    assert custom.custom and custom.name == "Cosa" and custom.quality == "empeora"
    assert len(catalog.all_tools()) == len(catalog.TOOLS) + 1
    other = {"cosa@otro": {"enabled": True, "repo": "otra-persona/cosa"}}
    assert custom.status(other) == "missing"
    ours = {"cosa@su-marketplace": {"enabled": False, "repo": "Alguien/Cosa"}}
    assert custom.status(ours) == "disabled"
    assert custom.plugin_id == "cosa@su-marketplace"  # para desinstalarlo o activarlo
    catalog.save_custom_plugin(dict(catalog.custom_plugins()[0], name="Cosa 2"), replaces="Cosa")
    assert [p["name"] for p in catalog.custom_plugins()] == ["Cosa 2"]
    catalog.remove_custom_plugin("Cosa 2")
    assert catalog.custom_plugins() == []


def test_plugin_edits(tmp):
    # una ficha del catálogo cambiada se aplica sin tocar el catálogo y se puede deshacer
    state.STATE_FILE = tmp / "state.json"
    original = catalog.TOOLS[0]
    catalog.save_plugin_edit(original.name, {"description": "mía", "pros": "", "cons": "",
                                             "saving": None, "quality": "empeora"})
    edited = catalog.all_tools()[0]
    assert edited.edited and edited.description == "mía" and edited.quality == "empeora"
    assert not original.edited and original.description != "mía"
    catalog.save_plugin_edit(original.name, None)
    assert not catalog.all_tools()[0].edited


def test_plugin_form():
    base = {"description": "d", "pros": "", "cons": "", "quality": "sin_probar"}
    item = catalog.plugin_from_form(dict(base, repo="JuliusBrussee/caveman", plugin="",
                                         name=""), "8,5 %", set(), custom=True)
    assert item["plugin"] == "caveman" and item["name"] == "caveman" and item["saving"] == 0.085
    assert catalog.plugin_from_form(base, "", set(), custom=False)["saving"] is None
    for repo, plugin, saving, taken in (("sin-barra", "", "", set()),
                                        ("a/b", "--scope", "", set()),  # parecería una opción
                                        ("a/b", "", "150", set()),
                                        ("a/b", "", "mucho", set()),
                                        ("a/b", "", "", {"b"})):
        try:
            catalog.plugin_from_form(dict(base, repo=repo, plugin=plugin, name=""), saving,
                                     taken, custom=True)
        except ValueError:
            continue
        raise AssertionError(f"debía rechazar {repo} {plugin} {saving} {taken}")


def test_catalog_version(tmp):
    market = tmp / "market"
    (market / ".claude-plugin").mkdir(parents=True)
    (market / "sub" / ".claude-plugin").mkdir(parents=True)
    (market / "sub" / ".claude-plugin" / "plugin.json").write_text('{"version": "2.0"}')
    (market / ".claude-plugin" / "marketplace.json").write_text(json.dumps({"plugins": [
        {"name": "fija", "version": "1.0"},
        {"name": "npm", "source": {"source": "npm", "version": "3.0"}},
        {"name": "carpeta", "source": "./sub"},
    ]}))
    assert plugins.catalog_version(market, "fija") == "1.0"
    assert plugins.catalog_version(market, "npm") == "3.0"
    assert plugins.catalog_version(market, "carpeta") == "2.0"
    assert plugins.catalog_version(market, "no-existe") is None
    assert plugins.catalog_version(tmp / "sin-catalogo", "fija") is None


def test_usage_view():
    week = {"pct": 40.0, "resetsAt": iso(NOW + timedelta(days=3))}
    acc = {"email": "a@b.c", "active": True,
           "usage": {"fiveHour": {"pct": 100.0, "resetsAt": iso(NOW + timedelta(hours=1))},
                     "sevenDay": week}}
    view = usage.account_view(acc)
    five = view["meters"]["fiveHour"]
    assert view["name"] == "a@b.c" and view["email"] is None  # sin alias ya es el nombre
    assert five["title"] == "Límite de 5 horas agotado" and not five["left"] and five["bar"]
    assert view["active"] and not view["can_switch"]

    # semanal agotado: no se puede usar, solo se dice cuándo se recarga
    out = {"email": "x@y.z", "alias": "trabajo",
           "usage": {"fiveHour": {"pct": 0.0}, "sevenDay": {"pct": 100.0}}}
    view = usage.account_view(out)
    assert view["name"] == "trabajo" and view["email"] == "x@y.z"
    assert not view["meters"]["fiveHour"]["visible"]
    week_view = view["meters"]["sevenDay"]
    assert week_view["title"] == "Límite semanal agotado" and not week_view["bar"]
    assert not view["can_switch"]

    # sin datos de un límite (la API puede no darlo): no rompe nada
    view = usage.account_view({"email": "q", "usage": {"fiveHour": {"pct": None}}})
    assert view["meters"]["fiveHour"]["used"] is None and view["can_switch"]


def test_tray_value():
    # con el semanal agotado el icono no puede decir 0 en verde
    assert usage.tray_value({"usage": {"fiveHour": {"pct": 0}, "sevenDay": {"pct": 100}}}) == 100
    assert usage.tray_value({"usage": {"fiveHour": {"pct": 30}, "sevenDay": {"pct": 50}}}) == 30
    assert usage.tray_value({"usage": {}}) is None


def test_forget_past_windows():
    # un límite cuya recarga ya pasó sale recargado aunque cswap aún no haya vuelto a preguntar
    accounts = [{"usage": {"fiveHour": {"pct": 100.0, "resetsAt": iso(NOW - timedelta(hours=2))},
                           "sevenDay": {"pct": 40.0, "resetsAt": iso(NOW + timedelta(days=6))}}}]
    usage.forget_past_windows(accounts, NOW)
    assert accounts[0]["usage"]["fiveHour"] == {"pct": 0.0, "reloaded": True}
    assert accounts[0]["usage"]["sevenDay"]["pct"] == 40.0
    assert usage.window_note(accounts[0]["usage"]["fiveHour"]) == usage.RELOADED_NOTE


def test_download_update(tmp):
    # solo se acepta el .exe publicado: con otra huella se borra y no se instala
    body = b"MZ" + b"x" * 100
    real_request, real_executable = updater.github_request, sys.executable
    updater.github_request = lambda url, timeout: io.BytesIO(body)
    sys.executable = str(tmp / "ClaudeUsage.exe")
    try:
        good = {"assets": [{"name": "ClaudeUsage.exe", "browser_download_url": "u",
                            "digest": "sha256:" + hashlib.sha256(body).hexdigest()}]}
        assert updater.download_update(good).read_bytes() == body
        bad = {"assets": [dict(good["assets"][0], digest="sha256:" + "0" * 64)]}
        try:
            updater.download_update(bad)
            raise AssertionError("aceptó un .exe con otra huella")
        except RuntimeError:
            pass
        assert not (tmp / "ClaudeUsage.new.exe").exists()
        # sin huella publicada no se ofrece instalarla
        assert updater.exe_asset({"assets": [{"name": "ClaudeUsage.exe"}]}) is None
    finally:
        updater.github_request, sys.executable = real_request, real_executable


def main():
    tests = [(name, fn) for name, fn in globals().items() if name.startswith("test_")]
    for name, fn in tests:
        if fn.__code__.co_argcount:
            with tempfile.TemporaryDirectory() as tmp:
                fn(Path(tmp))
        else:
            fn()
        print(f"✔ {name}")
    print("ok")


if __name__ == "__main__":
    main()
