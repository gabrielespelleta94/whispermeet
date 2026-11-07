"""Ola 3: «Abrir en Outlook». Escribe un borrador `.eml` con la cabecera `X-Unsent: 1` en la carpeta temporal PROPIA de la app
(`Guardian.borradores`, nunca datos del usuario ni el repo) y lo abre con el programa del sistema para que Outlook lo muestre como borrador sin enviar.
NUNCA envía nada: no hay SMTP, ni Graph, ni red.
"""
from __future__ import annotations

import re
import secrets
from email.message import EmailMessage
from email.policy import SMTP

from .rutas import RutaProhibida

MAX_ASUNTO = 200
MAX_CUERPO = 20_000
MAX_DESTINATARIOS = 20
_RE_CORREO = re.compile(r"^[^\s@<>,;\"]{1,64}@[^\s@<>,;\"]{1,190}\.[^\s@<>,;\"]{2,20}$")


def limpiar_destinatarios(para) -> list[str]:
    """Acepta una cadena («a@x.com; b@y.com») o una lista; descarta lo que no parece una dirección. Sin saltos de línea (nada de inyección de cabeceras)."""
    if para is None:
        return []
    trozos = re.split(r"[;,\s]+", para) if isinstance(para, str) else [str(x) for x in para]
    out: list[str] = []
    for t in trozos:
        t = t.strip()
        if t and _RE_CORREO.match(t) and t.lower() not in [o.lower() for o in out]:
            out.append(t)
    return out[:MAX_DESTINATARIOS]


def construir_eml(asunto: str, cuerpo: str, para=None) -> bytes:
    """El mensaje como bytes `.eml` (UTF-8, CRLF) con `X-Unsent: 1`. FUNCIÓN PURA. Lanza ValueError si falta el asunto o el cuerpo."""
    asunto = " ".join(str(asunto or "").split())[:MAX_ASUNTO]
    cuerpo = str(cuerpo or "").replace("\r\n", "\n").replace("\r", "\n").strip("\n")[:MAX_CUERPO]
    if not asunto:
        raise ValueError("El correo necesita un asunto.")
    if not cuerpo.strip():
        raise ValueError("El correo necesita un cuerpo.")
    m = EmailMessage(policy=SMTP)
    destinatarios = limpiar_destinatarios(para)
    if destinatarios:
        m["To"] = ", ".join(destinatarios)
    m["Subject"] = asunto
    m["X-Unsent"] = "1"
    m.set_content(cuerpo, charset="utf-8", cte="8bit")
    return m.as_bytes()


def abrir_borrador(guardian, asunto: str, cuerpo: str, para=None, abridor=None) -> dict:
    """Crea el `.eml` y lo abre. -> {ok: True} o {ok: False, error}. `abridor(ruta)` sustituye a `os.startfile` (pruebas: no se abre nada)."""
    try:
        datos = construir_eml(asunto, cuerpo, para)
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    try:
        ruta = guardian.escribir_borrador(f"borrador-{secrets.token_hex(8)}.eml", datos)
        guardian.abrir_borrador(ruta, abridor)
    except RutaProhibida as e:
        return {"ok": False, "error": f"No se pudo preparar el borrador: {e}"}
    except OSError as e:
        return {"ok": False, "error": f"No se pudo abrir el borrador: {e}"}
    return {"ok": True}
