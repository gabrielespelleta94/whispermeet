"""Corrección de un segmento de la reunión en curso (ola 4). Todo local, sin modelo.

Qué hace al corregir el texto de un segmento:
1. Sustituye el texto del segmento (`original` y `texto`) y quita las palabras con probabilidad (ya no casan).
2. Calcula las SUSTITUCIONES palabra a palabra (lo que el usuario cambió: «sap» -> «SAP», «Nordia» -> «Nórdia») y las propaga a lo que ya se derivó
   de esa frase: tarjetas (texto, referencia, línea citada, nota), resumen acumulado/completo/final, definiciones y el feed del Monitor.
3. Opcionalmente añade las palabras nuevas al glosario (global o del proyecto).

LÍMITES (documentados en el contrato): solo se propagan sustituciones cortas (≤4 palabras) de al menos 3 caracteres y por coincidencia exacta de palabra completa;
lo que el modelo parafraseó, lo que ya viajó al modelo (digest en caché, llamadas pasadas) y los consejos/respuestas del asesor NO se reescriben. No se vuelve a
llamar a ningún agente.
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher

from .rutas import sin_acentos

MAX_PALABRAS_SUSTITUCION = 4
MIN_CHARS_SUSTITUCION = 3
CAMPOS_TARJETA = ("texto", "referencia", "linea", "nota")
CAMPOS_RESUMEN = ("resumen_acumulado", "resumen_completo", "resumen_final", "resumen_modelo")


def _plano(p: str) -> str:
    return sin_acentos(p.strip(" .,;:¿?¡!\"'«»()")).lower()


def _limpia(p: str) -> str:
    return p.strip(" .,;:¿?¡!\"'«»()")


def sustituciones(viejo: str, nuevo: str) -> list[tuple[str, str]]:
    """Pares (palabra(s) vieja(s), palabra(s) nueva(s)) donde el usuario CAMBIÓ palabras (ni inserciones ni borrados). FUNCIÓN PURA.
    Se comparan sin signos de los extremos; «sap» -> «SAP» cuenta (cambia la forma)."""
    a, b = (viejo or "").split(), (nuevo or "").split()
    sm = SequenceMatcher(None, a, b, autojunk=False)
    out: list[tuple[str, str]] = []
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op != "replace":
            continue
        v, n = _limpia(" ".join(a[i1:i2])), _limpia(" ".join(b[j1:j2]))
        if v and n and v != n:
            out.append((v, n))
    return out


def _sustituir(texto: str, viejo: str, nuevo: str) -> tuple[str, int]:
    patron = re.compile(r"(?<!\w)" + re.escape(viejo) + r"(?!\w)")
    return patron.subn(lambda _m: nuevo, texto)


def _propagables(pares: list[tuple[str, str]]) -> list[tuple[str, str]]:
    return [(v, n) for v, n in pares
            if len(v) >= MIN_CHARS_SUSTITUCION and len(v.split()) <= MAX_PALABRAS_SUSTITUCION and len(n.split()) <= MAX_PALABRAS_SUSTITUCION]


def propagar(sesion, equipo, pares: list[tuple[str, str]]) -> dict:
    """Aplica las sustituciones a lo derivado de la reunión. Devuelve cuántos sitios cambió: {tarjetas, resumen, definiciones, feed}."""
    r = {"tarjetas": 0, "resumen": 0, "definiciones": 0, "feed": 0}
    pares = _propagables(pares)
    if not pares:
        return r
    with sesion._lock:
        for viejo, nuevo in pares:
            for t in sesion.tarjetas:
                cambiada = False
                for c in CAMPOS_TARJETA:
                    if isinstance(t.get(c), str) and t[c]:
                        t[c], n = _sustituir(t[c], viejo, nuevo)
                        cambiada = cambiada or n > 0
                r["tarjetas"] += 1 if cambiada else 0
            for c in CAMPOS_RESUMEN:
                valor = getattr(sesion, c, "")
                if valor:
                    nuevo_valor, n = _sustituir(valor, viejo, nuevo)
                    if n:
                        setattr(sesion, c, nuevo_valor)
                        r["resumen"] += n
            fuentes_def = [sesion.definiciones] + ([equipo.definiciones.lista] if equipo is not None else [])
            for lista in fuentes_def:
                for d in lista:
                    for c in ("termino", "definicion"):
                        if isinstance(d.get(c), str):
                            d[c], n = _sustituir(d[c], viejo, nuevo)
                            r["definiciones"] += n if lista is sesion.definiciones else 0
            if equipo is not None:
                for e in equipo.monitor.feed:
                    if isinstance(e.get("texto"), str):
                        e["texto"], n = _sustituir(e["texto"], viejo, nuevo)
                        r["feed"] += n
        if equipo is not None:
            sesion.definiciones = equipo.definiciones.publico()
    return r


def corregir_segmento(sesion, equipo, seg_id: int, texto: str) -> dict:
    """Corrige el segmento `seg_id`. -> {segmento (público), sustituciones [[viejo, nuevo]], propagado {…}}. ValueError si no existe o el texto está vacío."""
    texto = " ".join((texto or "").split())
    if not texto:
        raise ValueError("El texto corregido no puede quedar vacío.")
    if len(texto) > 4000:
        raise ValueError("El texto corregido es demasiado largo.")
    with sesion._lock:
        seg = next((x for x in sesion.segmentos if x.id == seg_id), None)
        if seg is None:
            raise ValueError("Ese segmento no existe.")
        antes = seg.texto if seg.texto.strip() else seg.original   # lo que el usuario veía (sin eco); si todo era eco, lo de Whisper
        pares = sustituciones(antes, texto)
        seg.original = texto
        seg.texto = texto
        seg.palabras = []
        seg.corregido = True
        if sesion.filtrar_eco:
            sesion._recalcular_eco(seg)   # una corrección que repite a Reunión se vuelve a filtrar como cualquier otro Micro
    propagado = propagar(sesion, equipo, pares)
    return {"segmento": seg.publico(), "sustituciones": [[v, n] for v, n in pares], "propagado": propagado}
