"""Utilidades de texto, todas locales (sin LLM): limpieza de transcripción, tokenización, topes."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .rutas import sin_acentos

ETIQUETAS = {"yo": "M", "reunion": "R"}   # M = micrófono (puede recoger a varias personas); R = audio de la reunión

_RE_MULETILLA = re.compile(
    r"(?<!\w)(?:e+h+m*|m+h+m*|h+m+|a+h+|u+m+|ee+|o sea|digamos|pues nada)(?!\w)[,.]?\s*",
    re.I,
)
_RE_REPETICION = re.compile(r"\b(\w{1,12})(\s+\1\b)+", re.I)
_RE_ESPACIOS = re.compile(r"\s{2,}")

_STOP = set("""
para como pero porque cuando donde sobre entre desde hasta este esta estos estas esto ese esa eso esos esas
tiene tienen tener hacer hace hacen puede pueden poder todo toda todos todas algo mas menos muy bien aqui alli
vamos vale bueno entonces tambien ahora luego despues antes siempre nunca cada otro otra otros otras sido sera
seria seran estar estan estamos somos esta fue era eran habia hay habra donde quien quienes cual cuales
que con por una uno unos unas del los las les nos sus mis tus mas sin ser son soy
""".split())


def palabras(texto: str) -> int:
    return len(re.findall(r"\w+", texto or ""))


def tokens_utiles(texto: str) -> set[str]:
    t = sin_acentos(texto or "").lower()
    return {w for w in re.findall(r"[a-z0-9]{4,}", t) if w not in _STOP}


def mmss(segundos: float) -> str:
    s = max(0, int(segundos))
    return f"{s // 60:02d}:{s % 60:02d}"


def a_segundos(mmss_: str) -> int | None:
    m = re.fullmatch(r"\s*\[?(\d{1,3}):(\d{2})\]?\s*", mmss_ or "")
    return int(m.group(1)) * 60 + int(m.group(2)) if m else None


def recortar(texto: str, maximo: int) -> str:
    texto = texto or ""
    if len(texto) <= maximo:
        return texto
    corte = texto[:maximo]
    corte = corte[: max(corte.rfind(" "), int(maximo * 0.8))]
    return corte.rstrip(" ,;:.") + "…"


def limpiar_frase(texto: str) -> str:
    t = _RE_MULETILLA.sub(" ", texto or "")
    t = _RE_REPETICION.sub(r"\1", t)
    t = _RE_ESPACIOS.sub(" ", t).strip(" ,")
    if t and t[0].islower() and (texto or "").strip()[:1].isupper():
        t = t[0].upper() + t[1:]
    return t


@dataclass
class Linea:
    t: float
    fuente: str
    texto: str
    ids: list[int] = field(default_factory=list)   # ids de los segmentos que forman la línea (para saber qué leyó cada análisis)


def limpiar_transcripcion(segmentos, unir_si_hueco_s: float = 20.0) -> list[Linea]:
    """Quita muletillas y repeticiones, descarta duplicados exactos y une líneas contiguas de la
    misma fuente. `segmentos`: iterable de objetos/dicts con t, fuente y texto."""
    lineas: list[Linea] = []
    ultimo_texto = {}
    for s in segmentos:
        t, f, tx = (s["t"], s["fuente"], s["texto"]) if isinstance(s, dict) else (s.t, s.fuente, s.texto)
        sid = s.get("id") if isinstance(s, dict) else getattr(s, "id", None)
        tx = limpiar_frase(tx)
        if not tx or palabras(tx) < 2 and len(tx) < 4:
            continue
        clave = sin_acentos(tx).lower().strip(" .,!?")
        if ultimo_texto.get(f) == clave:
            continue
        ultimo_texto[f] = clave
        if lineas and lineas[-1].fuente == f and t - lineas[-1].t <= unir_si_hueco_s \
                and lineas and (len(lineas[-1].texto) < 600):
            lineas[-1].texto = f"{lineas[-1].texto} {tx}"
            if sid is not None:
                lineas[-1].ids.append(sid)
        else:
            lineas.append(Linea(t, f, tx, [sid] if sid is not None else []))
    return lineas


def formatear_lineas(lineas: list[Linea]) -> str:
    return "\n".join(f"[{mmss(l.t)}] {ETIQUETAS.get(l.fuente, 'R')}: {l.texto}" for l in lineas)


def escapar_delimitadores(texto: str) -> str:
    """Evita que el texto de la reunión imite los delimitadores del prompt."""
    return (texto or "").replace("<<<", "‹‹‹").replace(">>>", "›››")
