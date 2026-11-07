"""Tarjetas de insights: prioridad, tope por análisis, duplicados entre categorías y forma compacta para el resumen final.

Todo local (sin LLM). El modelo propone; aquí se decide cuántas y cuáles se muestran.
"""
from __future__ import annotations

import re

from .texto import a_segundos, mmss, tokens_utiles

# Orden de prioridad cuando un análisis propone más del tope: lo accionable antes que lo que solo conviene preguntar.
PRIORIDAD = {"decisión": 0, "contradicción": 1, "pendiente": 2, "riesgo": 3, "regla": 3, "pregunta": 4, "idea": 5}
MAX_POR_ANALISIS = 3
VENTANA_CRUZADA_S = 150     # una pregunta y una decisión sobre lo mismo en este margen son la misma tarjeta
UMBRAL_MISMA = 0.6          # solapamiento de términos útiles dentro de la misma categoría
UMBRAL_CRUZADA = 0.5        # entre categorías distintas y cercanas en el tiempo
MIN_COMPARTIDOS = 3


_RE_FIJO = re.compile(r"alcance|importe|presupuesto|precio|tarifa|coste|cuant[ií]a|honorario|€|\beuros?\b|\b\d[\d.,]*\s?(?:k|mil)\b", re.I)


def prioridad_de(t: dict) -> str:
    """ola 3: `fijo` (se queda en pantalla hasta que se atienda), `normal` o `discreto`. Una contradicción de ALCANCE o IMPORTE (la que ve el Auditor,
    o el análisis generalista) sale fija; una idea, discreta; el resto, normal. Solo etiqueta: no cambia qué tarjetas se muestran."""
    cat = t.get("categoria")
    if cat == "contradicción":
        texto = " ".join(str(t.get(k) or "") for k in ("texto", "referencia", "linea", "nota"))
        if _RE_FIJO.search(texto) and t.get("perfil") in (None, "", "revisor"):
            return "fijo"
        return "normal"
    return "discreto" if cat == "idea" else "normal"


def solapamiento(a: str, b: str) -> tuple[float, int]:
    """(|A∩B| / min(|A|,|B|), |A∩B|) sobre términos útiles (sin acentos, sin palabras vacías)."""
    ta, tb = tokens_utiles(a), tokens_utiles(b)
    if not ta or not tb:
        return 0.0, 0
    n = len(ta & tb)
    return n / min(len(ta), len(tb)), n


def son_duplicadas(a: dict, b: dict) -> bool:
    """Misma categoría y texto muy parecido, o distinta categoría pero casi el mismo minuto y el mismo asunto."""
    coef, n = solapamiento(a["texto"], b["texto"])
    if n < MIN_COMPARTIDOS:
        return False
    if a["categoria"] == b["categoria"]:
        return coef >= UMBRAL_MISMA
    ta, tb = a.get("t_seg"), b.get("t_seg")
    if ta is None or tb is None:
        return False
    return abs(ta - tb) <= VENTANA_CRUZADA_S and coef >= UMBRAL_CRUZADA


def seleccionar(candidatas: list[dict], emitidas: list[dict], maximo: int = MAX_POR_ANALISIS) -> list[dict]:
    """De las candidatas del análisis (con `categoria`, `texto`, `t_seg`) devuelve las que se muestran: como mucho
    `maximo`, por prioridad de categoría (a igual prioridad, el orden del modelo) y sin duplicar nada de lo ya
    emitido ni de lo ya elegido, tampoco entre categorías."""
    orden = sorted(range(len(candidatas)), key=lambda i: (PRIORIDAD.get(candidatas[i]["categoria"], 9), i))
    elegidas: list[int] = []
    for i in orden:
        c = candidatas[i]
        if len(elegidas) >= maximo:
            break
        if any(son_duplicadas(c, e) for e in emitidas) or any(son_duplicadas(c, candidatas[j]) for j in elegidas):
            continue
        elegidas.append(i)
    return [candidatas[i] for i in sorted(elegidas)]


def _segundos(t: dict) -> float:
    s = t.get("t_seg")
    if s is None:
        s = a_segundos(t.get("minuto") or "")
    return s if s is not None else 10 ** 9


def lineas_compactas(tarjetas: list[dict], tope_chars: int = 24_000, largo_texto: int = 130) -> list[str]:
    """TODAS las tarjetas, de la primera a la última, una línea cada una: `[mm:ss] categoría: texto (responsable)`.
    Es lo que usa el resumen final: no se recorta por antigüedad. Solo si se pasa de `tope_chars` se descartan
    primero preguntas y luego riesgos (las menos accionables), nunca decisiones, pendientes ni contradicciones."""
    def linea(t: dict) -> str:
        texto = (t.get("texto") or "").strip()
        if len(texto) > largo_texto:
            texto = texto[:largo_texto].rstrip() + "…"
        resp = f" ({t['responsable']})" if t.get("responsable") else ""
        marca = " [posible, sin verificar]" if t.get("estado") == "posible" else ""
        return f"[{t.get('minuto') or '--:--'}] {t['categoria']}: {texto}{resp}{marca}"

    orden = sorted(range(len(tarjetas)), key=lambda i: (_segundos(tarjetas[i]), i))
    lineas = {i: linea(tarjetas[i]) for i in orden}
    total = sum(len(l) + 1 for l in lineas.values())
    for cat in ("idea", "pregunta", "riesgo"):
        for i in orden:
            if total <= tope_chars:
                break
            if tarjetas[i]["categoria"] == cat and i in lineas:
                total -= len(lineas.pop(i)) + 1
    return [lineas[i] for i in orden if i in lineas]


def rango_minutos(tarjetas: list[dict]) -> tuple[str, str]:
    """(primer minuto, último minuto) de las tarjetas con minuto, para comprobar que cubren toda la reunión."""
    segs = [s for s in (_segundos(t) for t in tarjetas) if s < 10 ** 9]
    return (mmss(min(segs)), mmss(max(segs))) if segs else ("", "")
