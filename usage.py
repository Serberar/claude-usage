"""Qué se enseña del consumo de cada cuenta. Sin interfaz, para poder probarlo."""

from datetime import datetime, timezone

DIAS = ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"]
MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]
LIMITS = (("fiveHour", "Límite de 5 horas"), ("sevenDay", "Límite semanal"))
RELOADED_NOTE = "recargado · el uso nuevo sale en unos minutos"


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
    return reset_label(parse_time(window.get("resetsAt")))


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


def account_view(acc):
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
        }
    week = window(acc, "sevenDay")
    warning = ""
    if acc.get("usageStatus") not in (None, "ok"):
        warning = f"⚠ {acc.get('usageStatus')}"
    elif week.get("willLastToReset") is False and not weekly_out:
        warning = "⚠ a este ritmo no llega al reinicio semanal"
    return {
        "name": display_name(acc),
        "email": acc.get("email", "") if acc.get("alias") else None,  # sin alias ya es el nombre
        "active": bool(acc.get("active")),
        "can_switch": not acc.get("active") and not weekly_out,
        "meters": meters,
        "warning": warning,
    }


def tray_value(acc):
    """El número del icono junto al reloj: el límite de 5 horas, o 100 si el semanal está
    agotado (si no, enseñaría un 0 verde de una cuenta que no se puede usar)."""
    return 100.0 if exhausted(acc, "sevenDay") else used(acc, "fiveHour")


def tray_tooltip(acc):
    parts = [f"{label} {'?' if used(acc, key) is None else f'{used(acc, key):.0f}%'}"
             for key, label in (("fiveHour", "5h"), ("sevenDay", "semana"))]
    return f"{display_name(acc)} · usado {' · '.join(parts)}"


def fetched_at(accounts):
    """Cuándo pidió cswap el consumo de la cuenta en uso (la hora que se enseña arriba)."""
    active = next((acc for acc in accounts if acc.get("active")), accounts[0])
    fetched = parse_time(active.get("usageFetchedAt"))
    return fetched.astimezone() if fetched else datetime.now()
