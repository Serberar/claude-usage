"""Qué se enseña del consumo de cada cuenta. Sin interfaz, para poder probarlo."""

from datetime import datetime, timezone

DIAS = ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"]
MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]
LIMITS = (("fiveHour", "Límite de 5 horas"), ("sevenDay", "Límite semanal"))
RELOADED_NOTE = "recargado · el uso nuevo sale en unos minutos"
# usageStatus de cswap cuando la sesión de Claude Code de la cuenta ya no vale
RELOGIN = ("relogin_required", "token_expired", "no_credentials")
EXPIRES_SOON_DAYS = 3
# cswap pregunta cada 3-10 min; más que esto es que Anthropic no le deja (http 429)
STALE_MINUTES = 20


def parse_time(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def countdown(target, now=None):
    if not target:
        return ""
    secs = int((target - (now or datetime.now(timezone.utc))).total_seconds())
    if secs <= 0:
        return "ya"
    d, rem = divmod(secs, 86400)
    h, rem = divmod(rem, 3600)
    m = rem // 60
    if d:
        return f"{d}d {h}h"
    if h:
        return f"{h}h {m}m"
    return f"{m}m"


def countdown_minutes(minutes):
    h, m = divmod(minutes, 60)
    return f"{h} h {m} min" if h else f"{m} min"


def reset_label(target):
    if not target:
        return "sin uso reciente"
    local = target.astimezone()
    now = datetime.now().astimezone()
    when = f"a las {local:%H:%M}"
    if local.date() != now.date():
        when = f"el {DIAS[local.weekday()]} {local.day} {MESES[local.month - 1]} {when}"
    return f"se recarga {when} · en {countdown(target)}"


def window_note(window):
    """Debajo de cada barra: cuándo se recarga ese límite."""
    if window.get("reloaded"):
        return RELOADED_NOTE
    reset = parse_time(window.get("resetsAt"))
    desktop_at = parse_time(window.get("desktopAt"))
    if desktop_at and not reset:
        return f"según la app de escritorio, a las {desktop_at.astimezone():%H:%M}"
    return reset_label(reset)


def add_desktop(accounts, latest, desktop_org):
    """Lo que sabe la app de escritorio. latest: el último dato de consumo que apuntó de
    cada organización ({org: {t, u: {fh, sd}}}); desktop_org: con la que está abierta.

    Marca la cuenta que usa la app de escritorio y, si su dato es más nuevo que el de
    cswap (o cswap no tiene ninguno, por ejemplo porque su sesión de Claude Code caducó),
    pone el de la app de escritorio. Los límites son de la cuenta, no del programa: el %
    es el mismo en los dos. La app de escritorio lo apunta en cuanto se agota y cswap
    tarda hasta 10 minutos: así el cambio automático no se queda esperando."""
    for acc in accounts:
        org = acc.get("organizationUuid")
        acc["desktop"] = bool(org) and org == desktop_org
        sample = latest.get(org) if org else None
        if not sample:
            continue
        at = datetime.fromtimestamp(sample["t"] / 1000, timezone.utc)
        fetched = parse_time(acc.get("usageFetchedAt"))
        current = acc.get("usage") if isinstance(acc.get("usage"), dict) else None
        if current and fetched and fetched >= at:
            continue
        old = current or acc.get("lastGoodUsage") or {}
        merged = {}
        for key, short in (("fiveHour", "fh"), ("sevenDay", "sd")):
            pct = sample["u"].get(short)
            if not isinstance(pct, (int, float)):
                continue
            merged[key] = {"pct": float(pct), "desktopAt": at.isoformat()}
            # la hora de recarga no la apunta; vale la última que vio cswap si es posterior
            reset = (old.get(key) or {}).get("resetsAt")
            if parse_time(reset) and parse_time(reset) > at:
                merged[key]["resetsAt"] = reset
        if merged:
            acc["usage"] = merged
            acc["usageFetchedAt"] = at.isoformat()
            acc["usageSource"] = "desktop"


def apply_live(accounts, email):
    """Claude Code gasta de la cuenta de su token (email), que puede no ser la que cree cswap
    (lo saca de ~/.claude.json). Marca como en uso la del token y apunta en cswapActive la
    que decía cswap. Devuelve el email del token si es de una cuenta que no está guardada
    (entonces ninguna sale en uso), o None."""
    if not email:
        return None
    email = email.lower()
    live = next((acc for acc in accounts if (acc.get("email") or "").lower() == email), None)
    for acc in accounts:
        acc["cswapActive"] = bool(acc.get("active"))
        acc["active"] = acc is live
    return None if live else email


def code_repair(accounts, wanted_email):
    """Tras apply_live: la cuenta a la que hay que volver a poner Claude Code (con cswap),
    o None si no hace falta.

    Solo cuando el token y ~/.claude.json no dicen la misma cuenta: eso no lo hace nadie a
    propósito. Cambiar con cswap o con /login cambia los dos a la vez, y eso se respeta.
    Va a la última que se eligió (wanted_email) o, si no se sabe, a la que decía cswap."""
    if not any("cswapActive" in acc for acc in accounts):
        return None  # no se ha podido leer el token: no se toca nada a ciegas
    live = next((acc for acc in accounts if acc.get("active")), None)
    claimed = next((acc for acc in accounts if acc.get("cswapActive")), None)
    if live is claimed:
        return None
    wanted = next((acc for acc in accounts
                   if wanted_email and (acc.get("email") or "").lower() == wanted_email), None)
    target = wanted or claimed
    if target is None or needs_login(target):
        return None
    return target


def stale_minutes(acc, now=None, limit=STALE_MINUTES):
    """Minutos que tiene el dato de consumo si pasa de limit (None si es reciente)."""
    fetched = parse_time(acc.get("usageFetchedAt"))
    if not fetched:
        return None
    minutes = int(((now or datetime.now(timezone.utc)) - fetched).total_seconds() // 60)
    return minutes if minutes >= limit else None


def forget_past_windows(accounts, now):
    """cswap pide el consumo a Claude cada 3-10 min por cuenta (más a menudo, la API corta):
    si la recarga de un límite ya pasó, su dato es de antes y queda recargado (0 %) hasta
    el siguiente. Antes se quedaba en 100 % hasta que cswap volvía a preguntar."""
    for acc in accounts:
        usage = acc.get("usage") or {}
        for key, window in usage.items():
            reset = parse_time(window.get("resetsAt")) if isinstance(window, dict) else None
            if reset and reset <= now:
                usage[key] = {"pct": 0.0, "reloaded": True}


def window(acc, key):
    value = (acc.get("usage") or {}).get(key)
    return value if isinstance(value, dict) else {}


def used(acc, key):
    """% usado de un límite, entre 0 y 100, o None si cswap no lo sabe."""
    pct = window(acc, key).get("pct")
    return None if pct is None else min(100.0, max(0.0, float(pct)))


def exhausted(acc, key):
    return (used(acc, key) or 0) >= 100


def display_name(acc):
    return acc.get("alias") or acc.get("email", "?")


def needs_login(acc):
    """La sesión de Claude Code de esta cuenta caducó: cswap no puede leer su consumo ni
    pasarse a ella hasta que se vuelva a iniciar."""
    return acc.get("usageStatus") in RELOGIN


def login_expires_soon(acc, now=None, days=EXPIRES_SOON_DAYS):
    """Cuándo caduca la sesión si es en menos de days días (None si no)."""
    expires = parse_time(acc.get("loginExpiresAt"))
    now = now or datetime.now(timezone.utc)
    if expires and (expires - now).total_seconds() < days * 86400:
        return expires
    return None


def account_view(acc, now=None):
    """Lo que enseña la tarjeta de una cuenta en la pestaña Uso.

    Con el semanal agotado no se puede usar hasta que se recargue: basta con decirlo y
    cuándo. Un límite agotado lo dice su título; el «queda 0 %» sobra.
    """
    weekly_out = exhausted(acc, "sevenDay")
    meters = {}
    for key, title in LIMITS:
        out = exhausted(acc, key)
        meters[key] = {
            "visible": not (weekly_out and key == "fiveHour"),
            "title": f"{title} agotado" if out else title,
            "used": used(acc, key),
            "bar": not (weekly_out and key == "sevenDay"),
            "value": not (weekly_out and key == "sevenDay"),
            "left": not out,
            "note": window_note(window(acc, key)),
            # cuánto deberías llevar gastado para llegar justo al reinicio (lo calcula cswap)
            "pace": None if out else window(acc, key).get("expectedPct"),
        }
    week = window(acc, "sevenDay")
    warning = ""
    relogin = needs_login(acc)
    expires = None if relogin else login_expires_soon(acc, now)
    if relogin:
        warning = "⚠ La sesión de Claude Code de esta cuenta caducó."
        if acc.get("usageSource") == "desktop":
            warning += " El consumo es el que apunta la app de escritorio."
    elif expires:
        when = expires.astimezone()
        warning = (f"⚠ La sesión de Claude Code de esta cuenta caduca el "
                   f"{DIAS[when.weekday()]} {when.day} {MESES[when.month - 1]} a las {when:%H:%M}.")
    elif acc.get("usageStatus") not in (None, "ok"):
        warning = f"⚠ cswap no puede leer el consumo ({acc.get('usageStatus')})"
    elif stale_minutes(acc, now) is not None:
        warning = (f"⚠ Dato de hace {countdown_minutes(stale_minutes(acc, now))}: Anthropic "
                   "no deja preguntar más ahora. Puede ir más alto; se reintenta solo")
    elif week.get("willLastToReset") is False and not weekly_out:
        warning = "⚠ a este ritmo no llega al reinicio semanal"
    return {
        "name": display_name(acc),
        "email": acc.get("email", "") if acc.get("alias") else None,  # sin alias ya es el nombre
        "active": bool(acc.get("active")),
        "can_switch": not acc.get("active") and not weekly_out and not relogin,
        "desktop": bool(acc.get("desktop")),
        "can_use_on_desktop": not acc.get("desktop") and not weekly_out
                              and bool(acc.get("organizationUuid")),
        "login": relogin or bool(expires),
        "meters": meters,
        "warning": warning,
    }


def tray_value(acc, shows="five"):
    """El número del icono junto al reloj. shows (Ajustes > General): "five", el límite de 5
    horas, o 100 si el semanal está agotado (si no, enseñaría un 0 verde de una cuenta que
    no se puede usar); "week", el semanal; "worst", el que va peor de los dos."""
    five, week = used(acc, "fiveHour"), used(acc, "sevenDay")
    if shows == "week":
        return week
    if shows == "worst":
        known = [value for value in (five, week) if value is not None]
        return max(known) if known else None
    return 100.0 if exhausted(acc, "sevenDay") else five


def blocked(acc):
    """No se puede usar: tiene algún límite agotado."""
    return any(exhausted(acc, key) for key, _title in LIMITS)


def headroom(acc):
    """Lo que le queda al límite que va peor (None si cswap no sabe nada de la cuenta)."""
    known = [value for value in (used(acc, key) for key, _t in LIMITS) if value is not None]
    return 100.0 - max(known) if known else None


def best_account(accounts, margin=10.0):
    """La cuenta con más margen si es otra que la que está en uso y le saca al menos margin
    puntos (por menos no compensa cambiar); si no, None."""
    # con la sesión caducada cswap no puede pasarse a ella: primero hay que iniciarla
    known = [acc for acc in accounts if (headroom(acc) or 0) > 0 and not needs_login(acc)]
    if not known:
        return None
    best = max(known, key=headroom)
    active = next((acc for acc in accounts if acc.get("active")), None)
    if best is active:
        return None
    if active is not None and headroom(best) - (headroom(active) or 0) < margin:
        return None
    return best


def alerts(before, after, near=90.0):
    """Avisos entre dos lecturas del consumo: la cuenta en uso llega a near en el límite de
    5 horas, o una cuenta que estaba agotada vuelve a poder usarse."""
    previous = {acc.get("number"): acc for acc in before}
    messages = []
    for acc in after:
        prev = previous.get(acc.get("number"))
        if prev is None:
            continue
        name = display_name(acc)
        was, now = used(prev, "fiveHour") or 0, used(acc, "fiveHour") or 0
        if acc.get("active") and was < near <= now:
            messages.append(f"{name} ha agotado el límite de 5 horas" if now >= 100
                            else f"{name} lleva un {now:.0f} % del límite de 5 horas")
        if blocked(prev) and not blocked(acc):
            messages.append(f"{name} vuelve a estar disponible")
        if needs_login(acc) and not needs_login(prev):
            messages.append(f"La sesión de {name} caducó: pulsa «Iniciar sesión» en su tarjeta")
        elif login_expires_soon(acc) and not login_expires_soon(prev) and not needs_login(acc):
            messages.append(f"La sesión de {name} caduca en menos de {EXPIRES_SOON_DAYS} días: "
                            "pulsa «Iniciar sesión» en su tarjeta para que no se pare")
    return messages


def desktop_near_limit(before, after, near=90.0):
    """La cuenta de la app de escritorio acaba de pasar de near en algún límite (es el
    momento de guardar el relevo de la conversación), o None."""
    previous = {acc.get("number"): acc for acc in before}
    for acc in after:
        prev = previous.get(acc.get("number"))
        if not acc.get("desktop") or prev is None:
            continue
        for key, _title in LIMITS:
            if (used(prev, key) or 0) < near <= (used(acc, key) or 0) < 100:
                return acc
    return None


def desktop_target(accounts, has_profile):
    """Cambio automático de la app de escritorio: si su cuenta está agotada, la cuenta con
    más margen que ya tenga sesión guardada para la app (si no, saldría la pantalla de
    inicio de sesión en vez de poder seguir).

    Va a la misma cuenta que Claude Code si puede (en automático van juntas); si no, a la
    de más margen.

    Devuelve (cuenta, None) si toca cambiar; (None, aviso) si toca pero a las cuentas con
    margen les falta la sesión guardada; y (None, None) si no toca."""
    current = next((acc for acc in accounts if acc.get("desktop")), None)
    if current is None or not blocked(current):
        return None, None
    free = [acc for acc in accounts if acc is not current and not blocked(acc)
            and (headroom(acc) or 0) > 0]
    ready = [acc for acc in free if has_profile(acc.get("organizationUuid"))]
    code = next((acc for acc in ready if acc.get("active")), None)
    if code or ready:
        return code or max(ready, key=headroom), None
    if free:
        best = max(free, key=headroom)
        return None, (f"La app de escritorio se ha agotado y {display_name(best)} tiene "
                      "margen, pero aún no la has usado ahí. Pasa a Manual, elígela en "
                      "«Escritorio» e inicia sesión (solo la primera vez)")
    return None, None


def tray_tooltip(acc):
    parts = [f"{label} {'?' if used(acc, key) is None else f'{used(acc, key):.0f}%'}"
             for key, label in (("fiveHour", "5h"), ("sevenDay", "semana"))]
    return f"{display_name(acc)} · usado {' · '.join(parts)}"


def fetched_at(accounts):
    """Cuándo pidió cswap el consumo de la cuenta en uso (la hora que se enseña arriba)."""
    active = next((acc for acc in accounts if acc.get("active")), accounts[0])
    fetched = parse_time(active.get("usageFetchedAt"))
    return fetched.astimezone() if fetched else datetime.now()
