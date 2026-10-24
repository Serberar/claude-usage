"""Actualizarse sola desde las Releases de GitHub: el .exe nuevo se descarga, se comprueba
su huella SHA-256 (la publica GitHub) y sustituye al que está en marcha."""

import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

from system import NO_WINDOW
from version import VERSION

REPO = "Serberar/claude-usage"
RELEASES_URL = f"https://github.com/{REPO}/releases/latest"
INSTALLER_ID = "7F4AB592-8EFE-486C-AC71-466940D30782"  # AppId de installer.iss


def version_tuple(tag):
    return tuple(int(n) for n in re.findall(r"\d+", tag)[:3])


def github_request(url, timeout):
    req = urllib.request.Request(url, headers={"User-Agent": f"ClaudeUsage/{VERSION}"})
    return urllib.request.urlopen(req, timeout=timeout)


def fetch_newer_release():
    """La última release de GitHub si es más nueva que esta versión; si no, None."""
    with github_request(f"https://api.github.com/repos/{REPO}/releases/latest", 15) as resp:
        release = json.load(resp)
    if version_tuple(release.get("tag_name", "")) <= version_tuple(VERSION):
        return None
    return release


def exe_asset(release):
    """El ClaudeUsage.exe de la release, solo si GitHub da su huella (sin ella no se instala)."""
    for asset in release.get("assets", []):
        if asset.get("name", "").lower() == "claudeusage.exe" and asset.get("digest"):
            return asset
    return None


def can_self_update(release):
    """Solo el .exe compilado se puede reemplazar a sí mismo."""
    return getattr(sys, "frozen", False) and exe_asset(release) is not None


def download_update(release):
    """Descarga el .exe nuevo junto al actual (ClaudeUsage.new.exe) y comprueba que es el
    publicado: un archivo cortado o cambiado por el camino no se instala."""
    current = Path(sys.executable)
    new = current.with_name(current.stem + ".new.exe")
    asset = exe_asset(release)
    expected = asset["digest"].lower().removeprefix("sha256:")
    digest = hashlib.sha256()
    try:
        with github_request(asset["browser_download_url"], 300) as resp, open(new, "wb") as out:
            while chunk := resp.read(1 << 20):
                out.write(chunk)
                digest.update(chunk)
        if digest.hexdigest() != expected:
            raise RuntimeError("la descarga no coincide con la publicada; vuelve a intentarlo")
    except BaseException:
        new.unlink(missing_ok=True)
        raise
    return new


def install_update(new):
    """Pone el .exe nuevo en el sitio del actual; el viejo queda como .old.exe."""
    current = Path(sys.executable)
    old = current.with_name(current.stem + ".old.exe")
    old.unlink(missing_ok=True)
    current.rename(old)  # Windows deja renombrar un .exe que está en marcha
    try:
        new.rename(current)
    except OSError:
        old.rename(current)
        raise
    return current


def restart(exe):
    # sin esto el .exe nuevo reutilizaría la carpeta temporal de este, que se borra al salir
    env = dict(os.environ, PYINSTALLER_RESET_ENVIRONMENT="1")
    subprocess.Popen([str(exe)], env=env, close_fds=True)


def sync_installed_version():
    """Si se instaló con el instalador, que Windows muestre la versión tras actualizarse sola."""
    try:
        import winreg
        key = rf"Software\Microsoft\Windows\CurrentVersion\Uninstall\{{{INSTALLER_ID}}}_is1"
        access = winreg.KEY_READ | winreg.KEY_SET_VALUE
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key, 0, access) as handle:
            folder = winreg.QueryValueEx(handle, "InstallLocation")[0]
            if Path(sys.executable).parent == Path(folder):  # no un .exe portable suelto
                winreg.SetValueEx(handle, "DisplayVersion", 0, winreg.REG_SZ, VERSION)
    except OSError:  # no está instalada (o no es Windows)
        pass


def remove_update_leftovers():
    sync_installed_version()
    if not getattr(sys, "frozen", False):
        return
    current = Path(sys.executable)
    if current.with_name(current.stem + ".old.exe").exists():
        # recién actualizada: Windows guarda el icono del .exe viejo para esta ruta
        subprocess.Popen([Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" /
                          "ie4uinit.exe", "-show"], creationflags=NO_WINDOW)
    for suffix in (".old.exe", ".new.exe"):
        try:
            current.with_name(current.stem + suffix).unlink(missing_ok=True)
        except OSError:  # la versión vieja aún se está cerrando; ya se borrará la próxima vez
            pass
