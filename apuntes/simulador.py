"""Modo --simular: alimenta una transcripción ficticia con tiempos acelerados, sin audio."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

# «Micro» (o «M»; «Yo»/«Y» siguen valiendo por compatibilidad) = micrófono; «Reunión»/«R» = audio de la reunión.
_RE = re.compile(r"^\s*(?:\[(\d{1,3}):(\d{2})\]\s*)?(Micro|M|Yo|Y|Reuni[oó]n|R)\s*:\s*(.+?)\s*$", re.I)


@dataclass
class LineaSim:
    t: float
    fuente: str
    texto: str


def parsear(texto: str) -> list[LineaSim]:
    """Formato por línea: `[MM:SS] Micro: texto` o `[MM:SS] Reunión: texto`. Una marca de tiempo manda: la línea sale
    en ese minuto (nunca antes que la anterior) aunque la anterior sea larga, así los minutos de la transcripción
    original no se desplazan. Solo las líneas SIN marca avanzan ~0,4 s por palabra respecto a la anterior. Las líneas
    que no encajan se ignoran (comentarios, vacías)."""
    out: list[LineaSim] = []
    t = 0.0
    for linea in texto.splitlines():
        m = _RE.match(linea)
        if not m:
            continue
        mm, ss, quien, tx = m.groups()
        if mm is not None:
            t = max(t, int(mm) * 60 + int(ss))
        elif out:
            t += max(2.0, len(out[-1].texto.split()) * 0.4)
        fuente = "reunion" if quien.lower().startswith(("reuni", "r")) else "yo"
        out.append(LineaSim(t, fuente, tx))
    return out


def cargar(ruta: str | Path) -> list[LineaSim]:
    return parsear(Path(ruta).read_text(encoding="utf-8"))
