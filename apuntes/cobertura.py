"""Cobertura de la transcripción: qué leyó cada análisis, qué quedó fuera y qué recibe el resumen final. Todo local, sin modelo.

En el modo equipo cada turno lee solo una parte de lo nuevo (tope `equipo_chars_nuevo`) y marca TODO como analizado; el resumen del cierre
solo conocía los títulos de los tramos y un modelo puede leer «[05:36]» (el inicio de un tramo) como si fuera el final de lo cubierto.
Aquí se registra, por análisis, el tramo leído y el recortado (`registrar_lectura`); lo que ningún análisis leyó es «no cubierto». En el cierre,
la MISMA llamada final recibe además esa transcripción (sin eco, con inicio y fin de cada tramo) hasta un tope; si hay que recortar, el recorte se
reparte entre todos los tramos y lo que quede fuera se avisa con sus minutos. No hay llamadas nuevas, ni reintentos, ni bloqueo.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .rutas import sin_acentos
from .texto import formatear_lineas, limpiar_transcripcion, mmss

MIN_POR_HUECO = 300      # caracteres mínimos que conserva cada tramo no cubierto al repartir un recorte (si caben)
INSTRUCCION_TRAMOS = "minutos de la reunión; el inicio y el fin de cada tramo están incluidos"


def rango(desde: float, hasta: float) -> str:
    return f"{mmss(desde)}–{mmss(hasta)}"


# ------------------------------------------------------------------ registro por análisis
def registrar_lectura(s, n: int, perfil: str, lineas: list, posiciones=None) -> dict:
    """Anota en la sesión qué leyó un análisis. `lineas`: las líneas limpias de ese análisis; `posiciones`: las que viajaron al modelo (None = todas).
    Los segmentos de las líneas leídas pasan a `Sesion.cubiertos`; las no leídas (recortadas por el tope) siguen sin cubrir."""
    pos = sorted(set(range(len(lineas)) if posiciones is None else posiciones))
    leidas = set(pos)
    ids = {i for p in pos for i in lineas[p].ids}
    omitidas: list[list[float]] = []
    anterior_omitida = False
    for k, l in enumerate(lineas):
        if k in leidas:
            anterior_omitida = False
            continue
        if anterior_omitida:
            omitidas[-1][0], omitidas[-1][1] = min(omitidas[-1][0], l.t), max(omitidas[-1][1], l.t)
        else:
            omitidas.append([l.t, l.t])
        anterior_omitida = True
    entrada = {"n": n, "perfil": perfil, "desde_t": round(min((l.t for l in lineas), default=0.0), 1),
               "hasta_t": round(max((l.t for l in lineas), default=0.0), 1), "lineas": len(lineas), "leidas": len(pos),
               "omitidas": [[round(a, 1), round(b, 1)] for a, b in omitidas]}
    with s._lock:
        s.cubiertos |= ids
        s.cobertura.append(entrada)
    return entrada


# ------------------------------------------------------------------ lo que recibe el cierre
@dataclass
class Cierre:
    tramo: str = ""                                   # transcripción aún no analizada (como antes), con inicio y fin
    huecos: str = ""                                  # transcripción de lo que ningún análisis leyó, tramo a tramo
    no_cubierto: list = field(default_factory=list)   # [(desde, hasta)] de cada tramo que ningún análisis leyó (entre o no al cierre)
    omitidos: list = field(default_factory=list)      # [(desde, hasta)] de lo que NO llega ni al análisis ni al cierre (por el tope)
    lineas_huecos: int = 0
    chars_huecos: int = 0
    ids_entregados: set = field(default_factory=set)   # ids de segmentos que SÍ viajan al cierre (tramo pendiente y no cubiertos que caben)

    @property
    def hay(self) -> bool:
        return bool(self.tramo or self.huecos)


def _linea(l) -> str:
    return formatear_lineas([l])


def _repartir(tamanos: list[int], tope: int) -> list[int]:
    """Presupuesto de cada tramo: si todo cabe, su tamaño; si no, un mínimo a cada uno y el resto en proporción a lo que le falta (el recorte
    se reparte entre TODOS, no solo el último)."""
    if sum(tamanos) <= tope:
        return list(tamanos)
    base = [min(t, MIN_POR_HUECO) for t in tamanos]
    if sum(base) >= tope:
        return [int(tope * b / sum(base)) for b in base]
    resto = tope - sum(base)
    extra = sum(t - b for t, b in zip(tamanos, base))
    return [b + int(resto * (t - b) / extra) for t, b in zip(tamanos, base)]


def _recortar_tramo(lineas: list, presupuesto: int) -> tuple[list[str], list[tuple[float, float]], list]:
    """Líneas de un tramo que caben en `presupuesto` caracteres: se conservan el principio y el final (alternando) y se marca lo omitido del medio."""
    textos = [_linea(l) for l in lineas]
    if sum(len(t) + 1 for t in textos) <= presupuesto:
        return textos, [], list(lineas)
    n = len(textos)
    elegidas: set[int] = set()
    usado, i, j = 0, 0, n - 1
    lado_cabeza = True
    while i <= j:
        k = i if lado_cabeza else j
        coste = len(textos[k]) + 1
        if usado + coste > presupuesto:
            break
        elegidas.add(k)
        usado += coste
        if lado_cabeza:
            i += 1
        else:
            j -= 1
        lado_cabeza = not lado_cabeza
    if not elegidas:   # ni una línea cabe entera: la primera, acortada
        return [textos[0][:max(40, presupuesto)].rstrip() + " […]"] + ([] if n == 1 else [f"[… {n - 1} líneas más omitidas por falta de espacio …]"]), \
            [(min(l.t for l in lineas), max(l.t for l in lineas))], [lineas[0]]
    salida: list[str] = []
    omitidos: list[tuple[float, float]] = []
    previo = -1
    for k in sorted(elegidas) + [n]:
        if k - previo > 1:
            tramo = lineas[previo + 1:k]
            omitidos.append((min(l.t for l in tramo), max(l.t for l in tramo)))
            salida.append(f"[… {len(tramo)} líneas omitidas por falta de espacio, entre {mmss(omitidos[-1][0])} y {mmss(omitidos[-1][1])} …]")
        if k < n:
            salida.append(textos[k])
        previo = k
    return salida, omitidos, [lineas[k] for k in sorted(elegidas)]


def preparar_cierre(s, tope_tramo: int, tope_huecos: int) -> Cierre:
    """Entradas de transcripción de la llamada final. `tope_tramo`: caracteres del tramo pendiente (lo de siempre); `tope_huecos`: caracteres de
    la transcripción de lo no cubierto. Sin eco (el texto de la sesión ya viene filtrado). No llama a ningún modelo."""
    c = Cierre()
    # 1. lo pendiente (id posterior al último análisis): las últimas líneas completas que caben en el tope, como siempre
    pend = limpiar_transcripcion(s.nuevos_desde_ultimo_analisis(final=True))
    conservadas: list = []
    usado = 0
    for l in reversed(pend):
        coste = len(_linea(l)) + 1
        if conservadas and usado + coste > tope_tramo:
            break
        conservadas.insert(0, l)
        usado += coste
    ids_tramo = {i for l in conservadas for i in l.ids}
    c.ids_entregados |= ids_tramo
    if conservadas:
        c.tramo = (f"Tramo pendiente, desde {mmss(min(l.t for l in conservadas))} hasta {mmss(max(l.t for l in conservadas))} ({INSTRUCCION_TRAMOS}):\n"
                   + formatear_lineas(conservadas))
    # 2. lo que ningún análisis leyó (y no va ya en el tramo pendiente): grupos de segmentos contiguos
    grupos: list[list] = []
    actual: list = []
    for x in s.estables(0, final=True):
        if x.id in s.cubiertos or x.id in ids_tramo:
            if actual:
                grupos.append(actual)
                actual = []
        else:
            actual.append(x)
    if actual:
        grupos.append(actual)
    tramos = [(limpiar_transcripcion(g)) for g in grupos]
    tramos = [t for t in tramos if t]
    if not tramos:
        return c
    c.no_cubierto = [(min(l.t for l in t), max(l.t for l in t)) for t in tramos]
    tamanos = [sum(len(_linea(l)) + 1 for l in t) for t in tramos]
    presupuestos = _repartir(tamanos, tope_huecos)
    bloques: list[str] = []
    for k, (t, pres) in enumerate(zip(tramos, presupuestos), 1):
        cuerpo, omit, kept = _recortar_tramo(t, pres)
        c.omitidos += omit
        c.ids_entregados |= {i for l in kept for i in l.ids}
        c.lineas_huecos += sum(1 for x in cuerpo if not x.startswith("[…"))
        cab = f"Tramo {k} de {len(tramos)}, desde {mmss(c.no_cubierto[k - 1][0])} hasta {mmss(c.no_cubierto[k - 1][1])} ({INSTRUCCION_TRAMOS})"
        bloques.append(cab + (" · recortado por espacio" if omit else "") + ":\n" + "\n".join(cuerpo))
    c.huecos = "\n\n".join(bloques)
    c.chars_huecos = len(c.huecos)
    return c


# ------------------------------------------------------------------ comprobación local del resumen
_FALTA = [re.compile(p) for p in (
    r"\bno hay (?:ningun |mas )?contenido",
    r"\bno hay (?:transcripcion|informacion|registro|registros|datos) (?:registrad\w*|disponible\w*|entre|desde|a partir|del? (?:tramo|periodo|minuto)|"
    r"en (?:el|ese|este) (?:tramo|periodo|intervalo)|de la (?:reunion|transcripcion))",
    r"\bsin (?:contenido|transcripcion|informacion|datos) (?:registrad\w*|disponible\w*|que (?:resumir|analizar))",
    r"\bno (?:se )?(?:ha|han|hay|consta|constan|existe|existen)n? (?:registrado|recogido|anotado|constancia)\w* (?:contenido|transcripcion|informacion|nada|tramos?|actividad)",
    r"\bno (?:se )?(?:puede|pueden|pudo|podido|ha podido)\w* (?:resumir|resumirse|resumirlo|resumirlos)",
    r"\bno se dispone de (?:contenido|transcripcion|informacion|datos)",
    r"\b(?:resumen acumulado|insights?|analisis) solo (?:recoge|recogen|incluye|cubre|llega)",
    r"\bno constan? (?:contenido|transcripcion|informacion)",
)]
_RE_MINUTO = re.compile(r"\b(\d{1,3}):(\d{2})\b")


def afirmaciones_de_falta(texto: str) -> list[tuple[str, tuple[float, float] | None]]:
    """Frases del resumen que afirman que falta contenido (o que el análisis no llegó a un tramo): [(frase, (desde, hasta) | None)].
    El rango sale de los minutos que cita la propia frase (dos o más: el menor y el mayor; uno solo: ese minuto)."""
    out = []
    for frase in re.split(r"(?<=[.!?])\s+|\n+", texto or ""):
        norm = sin_acentos(frase).lower()
        if not any(p.search(norm) for p in _FALTA):
            continue
        mins = [int(a) * 60 + int(b) for a, b in _RE_MINUTO.findall(frase)]
        out.append((" ".join(frase.split())[:160], (float(min(mins)), float(max(mins))) if mins else None))
    return out


def avisos(resumen: str, cierre: Cierre | None, s) -> list[str]:
    """Avisos para el .md y la revisión, con los minutos afectados. No borra ni corrige nada. Vacío si el resumen no afirma falta de contenido
    y todo lo no cubierto llegó al cierre."""
    out: list[str] = []
    if cierre is not None and cierre.omitidos:
        tramos = ", ".join(rango(a, b) for a, b in cierre.omitidos)
        out.append(f"Cobertura incompleta: ningún análisis leyó ni el resumen final recibió por el tope de tamaño la transcripción de {tramos}. "
                   "Lo dicho en esos minutos puede faltar en el resumen.")
    lineas = limpiar_transcripcion(s.estables(0, final=True))
    for frase, r in afirmaciones_de_falta(resumen):
        if r is None:
            out.append(f"El resumen afirma que falta contenido («{frase}») sin indicar minutos. Comprueba la transcripción.")
            continue
        n = sum(1 for l in lineas if r[0] - 1 <= l.t <= r[1] + 1)
        donde = f"entre {mmss(r[0])} y {mmss(r[1])}" if r[1] > r[0] else f"en el minuto {mmss(r[0])}"
        out.append(f"El resumen afirma que falta contenido («{frase}»). La transcripción tiene {n} líneas {donde}"
                   + (": ese tramo SÍ se habló." if n else "."))
    return out
