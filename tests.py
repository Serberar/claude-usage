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
import desktop
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


def test_detected_plugins(tmp):
    # lo instalado por fuera sale como uno más; lo del catálogo no se repite
    state.STATE_FILE = tmp / "state.json"
    tools = catalog.all_tools()
    installed = {"token-diet@token-diet": {"enabled": True, "repo": "Serberar/token-diet"},
                 "caveman@caveman": {"enabled": False, "repo": None},
                 "token-diet@otro": {"enabled": True, "repo": "x/token-diet"}}
    for tool in tools:
        tool.status(installed)
    found = catalog.detected_plugins(installed, tools)
    assert [t.name for t in found] == ["caveman", "token-diet@otro"]  # sin chocar de nombre
    assert all(t.detected for t in found) and found[0].status(installed) == "disabled"


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
    # un rango se guarda como rango, se escribe igual y la barra cuenta su punto medio
    ranged = catalog.plugin_from_form(base, "45-53 %", set(), custom=False)["saving"]
    assert ranged == [0.45, 0.53] and plugins.saving_text(ranged) == "45-53"
    assert plugins.saving_text(0.085) == "8,5" and plugins.saving_text(None) == ""
    tool = plugins.Tool("x", "", "", "", saving=ranged)
    assert abs(plugins.estimated_spend([tool]) - 0.51) < 1e-9
    for repo, plugin, saving, taken in (("sin-barra", "", "", set()),
                                        ("a/b", "--scope", "", set()),  # parecería una opción
                                        ("a/b", "", "150", set()),
                                        ("a/b", "", "53-45", set()),
                                        ("a/b", "", "1-2-3", set()),
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


def acc_with(number, five, week, active=False, email=None):
    return {"number": number, "email": email or f"c{number}@x", "active": active,
            "usage": {"fiveHour": {"pct": five}, "sevenDay": {"pct": week}}}


def test_tray_shows():
    acc = acc_with(1, 30, 60)
    assert usage.tray_value(acc, "five") == 30
    assert usage.tray_value(acc, "week") == 60
    assert usage.tray_value(acc, "worst") == 60


def test_best_account():
    # la de más margen, solo si es otra y le saca al menos 10 puntos
    accounts = [acc_with(1, 80, 20, active=True), acc_with(2, 10, 30), acc_with(3, 0, 100)]
    assert usage.best_account(accounts)["number"] == 2
    accounts[0] = acc_with(1, 25, 20, active=True)  # 75 de margen contra 70: no compensa
    assert usage.best_account(accounts) is None
    assert usage.best_account([acc_with(1, 0, 100, active=True), acc_with(2, 0, 100)]) is None


def test_alerts():
    before = [acc_with(1, 85, 20, active=True), acc_with(2, 0, 100)]
    after = [acc_with(1, 92, 21, active=True), acc_with(2, 0, 3)]
    messages = usage.alerts(before, after)
    assert messages == ["c1@x lleva un 92 % del límite de 5 horas", "c2@x vuelve a estar disponible"]
    assert usage.alerts(after, after) == []  # sin cambios, sin avisos repetidos
    assert usage.alerts([], after) == []      # la primera lectura no avisa de nada
    assert usage.alerts(before, [acc_with(1, 100, 20, active=True)]) == [
        "c1@x ha agotado el límite de 5 horas"]


def test_settings(tmp):
    state.STATE_FILE = tmp / "state.json"
    assert state.setting("auto_threshold") == 90  # sin tocar: el valor por defecto
    state.set_setting("auto_threshold", 80)
    state.save_state(otra="cosa")  # guardar otra cosa no borra las opciones
    assert state.setting("auto_threshold") == 80 and state.load_state()["otra"] == "cosa"


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


def test_desktop_usage():
    org1, org2 = "org-1", "org-2"
    t = NOW - timedelta(minutes=5)
    latest = {org1: {"t": t.timestamp() * 1000, "org": org1, "u": {"fh": 40, "sd": 70}}}
    old_reset = iso(NOW + timedelta(days=2))
    accs = [
        # sesión de Claude Code caducada: cswap no sabe el consumo, la app de escritorio sí
        {"number": 1, "organizationUuid": org1, "usageStatus": "relogin_required",
         "usage": None, "lastGoodUsage": {"sevenDay": {"pct": 10, "resetsAt": old_reset},
                                           "fiveHour": {"pct": 99, "resetsAt": iso(t - timedelta(hours=1))}}},
        {"number": 2, "organizationUuid": org2, "active": True, "usageStatus": "ok",
         "usage": {"fiveHour": {"pct": 5}}},
    ]
    usage.add_desktop(accs, latest, org1)
    assert accs[0]["desktop"] and not accs[1]["desktop"]
    assert usage.used(accs[0], "fiveHour") == 40 and usage.used(accs[0], "sevenDay") == 70
    assert accs[0]["usage"]["sevenDay"]["resetsAt"] == old_reset   # la recarga posterior vale
    assert "resetsAt" not in accs[0]["usage"]["fiveHour"]          # la de antes del dato, no
    assert "app de escritorio" in usage.window_note(accs[0]["usage"]["fiveHour"])
    assert usage.used(accs[1], "fiveHour") == 5                     # sin dato del escritorio
    # el escritorio apunta que se agotó después de la última lectura de cswap: manda él
    fresh = {"number": 3, "organizationUuid": org1, "usageStatus": "ok",
             "usageFetchedAt": iso(t - timedelta(minutes=8)),
             "usage": {"fiveHour": {"pct": 93, "resetsAt": iso(NOW + timedelta(hours=1))}}}
    newer = dict(fresh, usageFetchedAt=iso(t + timedelta(minutes=1)),
                 usage={"fiveHour": {"pct": 93}})
    usage.add_desktop([fresh, newer], latest, org1)
    assert usage.used(fresh, "fiveHour") == 40 and fresh["usage"]["fiveHour"]["resetsAt"]
    assert usage.used(newer, "fiveHour") == 93                      # el de cswap es más nuevo
    view = usage.account_view(accs[0])
    assert view["login"] and not view["can_switch"] and view["desktop"]
    assert "caducó" in view["warning"]
    assert usage.best_account(accs) is None  # no propone una cuenta que no se puede usar


def test_login_expires_soon():
    soon = {"usageStatus": "ok", "loginExpiresAt": iso(NOW + timedelta(days=1))}
    later = {"usageStatus": "ok", "loginExpiresAt": iso(NOW + timedelta(days=20))}
    assert usage.login_expires_soon(soon, NOW) and not usage.login_expires_soon(later, NOW)
    assert usage.account_view(soon, NOW)["login"]
    assert not usage.account_view(later, NOW)["login"]
    before = [{"number": 1, "usageStatus": "ok"}]
    after = [{"number": 1, "usageStatus": "relogin_required"}]
    assert any("caducó" in m for m in usage.alerts(before, after))
    soon_now = [{"number": 1, "usageStatus": "ok",
                 "loginExpiresAt": iso(datetime.now(timezone.utc) + timedelta(days=1))}]
    assert any("caduca" in m for m in usage.alerts(before, soon_now))
    assert not usage.alerts(soon_now, soon_now)                     # solo una vez


def test_desktop_target():
    def acc(org, five, desk=False):
        return {"organizationUuid": org, "desktop": desk, "usage": {"fiveHour": {"pct": five}}}
    full, free, other = acc("a", 100, True), acc("b", 20), acc("c", 50)
    assert usage.desktop_target([full, free, other], lambda org: True) == (free, None)
    assert usage.desktop_target([full, free, other], lambda org: org == "c") == (other, None)
    target, warning = usage.desktop_target([full, free], lambda org: False)  # sin sesión
    assert target is None and "Usar ahí" in warning
    assert usage.desktop_target([acc("a", 50, True), free], lambda org: True) == (None, None)
    assert usage.desktop_target([full, acc("b", 100)], lambda org: True) == (None, None)


def test_desktop_profiles(tmp):
    data, profiles = tmp / "Claude", tmp / "perfiles"
    (data / "Network").mkdir(parents=True)
    (data / "Network" / "Cookies").write_text("cuenta1")
    (data / "IndexedDB").mkdir()
    (data / "config.json").write_text(json.dumps(
        {"locale": "es-ES", "oauth:tokenCache": "t1", "lastKnownAccountUuid": "u1"}))
    desktop.save_profile("org-1", data, profiles)
    assert desktop.has_profile("org-1", profiles) and not desktop.has_profile("org-2", profiles)
    # a una cuenta sin sesión guardada: se queda sin sesión, pero los ajustes siguen
    assert not desktop.restore_profile("org-2", data, profiles)
    config = json.loads((data / "config.json").read_text())
    assert config == {"locale": "es-ES"} and not (data / "Network").exists()
    # la otra cuenta inicia sesión, se guarda y se vuelve a la primera
    (data / "Network").mkdir()
    (data / "Network" / "Cookies").write_text("cuenta2")
    config["oauth:tokenCache"] = "t2"
    (data / "config.json").write_text(json.dumps(config))
    desktop.save_profile("org-2", data, profiles)
    assert desktop.restore_profile("org-1", data, profiles)
    assert (data / "Network" / "Cookies").read_text() == "cuenta1"
    config = json.loads((data / "config.json").read_text())
    assert config["oauth:tokenCache"] == "t1" and config["locale"] == "es-ES"
    assert desktop.restore_profile("org-2", data, profiles)
    assert (data / "Network" / "Cookies").read_text() == "cuenta2"
    # al guardar otra vez no quedan carpetas a medias
    desktop.save_profile("org-2", data, profiles)
    assert sorted(p.name for p in profiles.iterdir()) == ["org-1", "org-2"]


def test_desktop_current_org(tmp):
    data = tmp / "Claude"
    data.mkdir()
    (data / "plan-usage-history.json").write_text(json.dumps({"samples": [
        {"t": 1000, "org": "a", "u": {"fh": 1}}, {"t": 3000, "org": "b", "u": {"fh": 2}},
        {"t": 2000, "org": "a", "u": {"fh": 3}}]}))
    assert desktop.latest_samples(desktop.usage_samples(data))["a"]["t"] == 2000
    assert desktop.current_org(data, switched={}) == "b"
    # entrar en otra organización después cuenta, y que la cambiemos nosotros también
    (data / "config.json").write_text(json.dumps(
        {desktop.ALLOWLIST + "c": "1970-01-01T00:00:04Z"}))
    assert desktop.current_org(data, switched={}) == "c"
    assert desktop.current_org(data, switched={"org": "d", "at": 5}) == "d"


def test_desktop_near_limit():
    def acc(five, desk=True):
        return {"number": 1, "desktop": desk, "usage": {"fiveHour": {"pct": five}}}
    assert usage.desktop_near_limit([acc(85)], [acc(91)])["number"] == 1
    assert usage.desktop_near_limit([acc(91)], [acc(93)]) is None       # solo al cruzar
    assert usage.desktop_near_limit([acc(85)], [acc(100)]) is None      # ya es tarde
    assert usage.desktop_near_limit([acc(85, False)], [acc(91, False)]) is None


def test_relay(tmp):
    import relay_mcp
    out = io.BytesIO()
    pct = {"value": 50}
    server = relay_mcp.Server(out, tmp, pct=lambda: pct["value"])
    reply = server.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                           "params": {"protocolVersion": "2025-03-26"}})
    assert reply["result"]["protocolVersion"] == "2025-03-26"
    assert reply["result"]["capabilities"]["tools"]["listChanged"]
    assert server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
    # por debajo del 90 %: Claude solo guarda si se lo piden, y no se avisa de nada
    listed = server.handle({"id": 2, "method": "tools/list"})["result"]["tools"]
    assert [t["name"] for t in listed] == ["guardar_relevo", "leer_relevo"]
    assert "No la llames por tu cuenta" in listed[0]["description"]
    assert not server.check() and out.getvalue() == b""
    # al cruzar el 90 %: un aviso (uno solo) y la lista nueva le dice que guarde solo
    pct["value"] = 93
    assert server.check() and not server.check()
    assert b"notifications/tools/list_changed" in out.getvalue()
    listed = server.handle({"id": 3, "method": "tools/list"})["result"]["tools"]
    assert "93 %" in listed[0]["description"] and "sin que el usuario" in listed[0]["description"]
    pct["value"] = 0  # recargada: vuelve a avisar para dejar de gastar
    assert server.check()
    # de dónde sale el %: lo que apunta Claude Usage, mientras sea reciente
    relay_mcp.write_status(50, tmp, now=1000)
    assert relay_mcp.desktop_pct(tmp, now=1060) == 50
    text, error = relay_mcp.call_tool("leer_relevo", {}, tmp)
    assert not error and "No hay" in text
    assert relay_mcp.call_tool("guardar_relevo", {"resumen": " "}, tmp)[1]
    for i in range(relay_mcp.KEEP + 3):
        relay_mcp.save_relay(f"paso {i}", "prueba", tmp, NOW + timedelta(seconds=i))
    text, error = relay_mcp.call_tool("leer_relevo", {}, tmp)
    assert not error and f"paso {relay_mcp.KEEP + 2}" in text and "Relevo: prueba" in text
    assert len(list((tmp / "anteriores").glob("*.md"))) == relay_mcp.KEEP
    # darlo de alta sin tocar lo demás de la configuración, y quitarlo
    config = tmp / "claude_desktop_config.json"
    config.write_text(json.dumps({"preferences": {"a": 1}}))
    relay_mcp.set_installed(True, config, {"command": "x", "args": []})
    assert relay_mcp.installed(config)
    assert json.loads(config.read_text())["preferences"] == {"a": 1}
    relay_mcp.set_installed(False, config)
    assert json.loads(config.read_text()) == {"preferences": {"a": 1}}
    config.write_text("{roto")
    try:
        relay_mcp.set_installed(True, config)
        raise AssertionError("pisó una configuración rota")
    except OSError:
        pass


def test_list_accounts_format():
    import accounts
    real = accounts.cswap
    try:
        accounts.cswap = lambda *a, **k: json.dumps(
            {"schemaVersion": 1, "accounts": [{"number": 1}, "basura"]})
        assert accounts.list_accounts() == [{"number": 1}] and not accounts.schema_too_new()
        accounts.cswap = lambda *a, **k: json.dumps({"schemaVersion": 2, "accounts": []})
        assert accounts.list_accounts() == [] and accounts.schema_too_new()
        for broken in ("no es json", "[1, 2]", json.dumps({"accounts": "x"})):
            accounts.cswap = lambda *a, b=broken, **k: b
            try:
                accounts.list_accounts()
                raise AssertionError(f"aceptó {broken!r}")
            except accounts.StepError:
                pass
    finally:
        accounts.cswap = real


def test_cannot_switch_to_dead_login():
    dead = {"number": 1, "usageStatus": "relogin_required", "usage": None}
    full = {"number": 2, "usage": {"sevenDay": {"pct": 100}}}
    ok = {"number": 3, "usage": {"fiveHour": {"pct": 10}}}
    assert not usage.account_view(dead)["can_switch"]
    assert not usage.account_view(full)["can_switch"]
    assert usage.account_view(ok)["can_switch"]



def test_wrong_browser_account():
    import accounts
    text = accounts.wrong_browser_account("b@x.com", "a@x.com")
    assert "b@x.com" in text and "a@x.com" in text and "cierra sesión" in text
    assert "no se terminó" in accounts.wrong_browser_account(None, "a@x.com")

def main():
    sys.stdout.reconfigure(encoding="utf-8")  # la consola de Windows no es UTF-8 (✔)
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
