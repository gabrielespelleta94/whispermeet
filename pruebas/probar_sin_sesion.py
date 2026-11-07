"""Comprueba con el `claude` real que, sin sesión iniciada, el error sale clasificado y con mensaje claro.

Usa un CLAUDE_CONFIG_DIR vacío y temporal (no toca la configuración real). Prompt ficticio.
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from apuntes.analisis import ErrorAnalisis  # noqa: E402
from apuntes.analisis.claude_cli import ClaudeCLI  # noqa: E402

os.environ["CLAUDE_CONFIG_DIR"] = tempfile.mkdtemp(prefix="apuntes-sin-sesion-")
try:
    ClaudeCLI().completar("Responde solo JSON.", "Devuelve {\"ok\": true}", "haiku", "low", 90)
    print("RESULTADO: la llamada funcionó (¿hay otra credencial en el entorno?)")
except ErrorAnalisis as e:
    print("RESULTADO tipo=%s bloqueante=%s" % (e.tipo, e.bloqueante))
    print("MENSAJE:", e.mensaje)
