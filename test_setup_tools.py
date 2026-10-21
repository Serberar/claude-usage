"""Comprueba lo delicado: lo que escribe en tu CLAUDE.md y cómo compara versiones.

Se ejecuta con: python test_setup_tools.py
"""

import tempfile
from importlib.machinery import SourceFileLoader
from pathlib import Path

import setup_tools

app = SourceFileLoader("claude_usage", str(Path(__file__).with_name("claude_usage.pyw"))).load_module()

# versiones: 1.10 es más nueva que 1.9 (no se comparan como texto)
assert app.version_tuple("v1.10.0") > app.version_tuple("v1.9.0")
assert app.version_tuple("v1.1.2") > app.version_tuple("1.1.1")
assert not app.version_tuple("v1.1.2") > app.version_tuple("v1.1.2")

# CLAUDE.md: activar y desactivar las reglas no toca el resto de líneas, ni las que no son UTF-8
with tempfile.TemporaryDirectory() as tmp:
    setup_tools.CLAUDE_DIR = Path(tmp)
    claude_md = Path(tmp) / "CLAUDE.md"
    original = "# Mis reglas\r\nHabla en espa\xf1ol\r\n@RTK.md\r\n".encode("latin-1")
    claude_md.write_bytes(original)
    rules = setup_tools.ClaudeMdRules("https://example.invalid", "reglas.md", name="x",
                                      description="", priority="", pros="", cons="")
    rules.file.write_text("regla", encoding="utf-8")

    rules.set_enabled(True, print)
    assert rules.status({}) == "enabled"
    rules.set_enabled(True, print)  # dos veces no la duplica
    assert claude_md.read_bytes().count(b"@reglas.md") == 1

    rules.set_enabled(False, print)
    assert rules.status({}) == "disabled"
    assert claude_md.read_bytes().splitlines() == original.splitlines()

print("ok")
