"""Modo reunión: cálculo puro (sin Win32) de la distribución de paneles y de la región de la ventana.

La ventana ocupa el área de trabajo del monitor y `SetWindowRgn` deja visibles solo los paneles; el resto (el hueco central)
no pertenece a la ventana: se ve lo de debajo y recibe los clics. Aquí vive la matemática, para poder probarla sin ventana:
medidas en píxeles CSS (las de la interfaz), región en píxeles físicos (las de Win32) y escala DPI entre ambas.
"""
from __future__ import annotations

UMBRAL_DOS_PANELES = 1280      # ancho de pantalla (px CSS) por debajo del cual no cabe el hueco: un único panel lateral
PROPORCION_LATERAL = 0.25      # panel lateral por defecto: 360 / 720 / 360 a 1440 px
MIN_LATERAL = 280              # ancho mínimo de cada panel lateral
MIN_HUECO = 320                # el hueco central nunca baja de esto (si no, Teams no se ve)
UNICO_MIN = 300                # panel único (pantalla estrecha)
UNICO_MAX_FRAC = 0.6           # ...y nunca más del 60 % del ancho
OPACIDAD_MIN, OPACIDAD_MAX = 60, 100


def _acotar(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def escala_dpi(dpi: float | None) -> float:
    """Factor de escala de Windows (96 ppp = 1,0; 120 = 1,25; 144 = 1,5)."""
    if not dpi or dpi <= 0:
        return 1.0
    return _acotar(dpi / 96.0, 0.5, 4.0)


def elegir_escala(dpi: float | None, dpr: float | None = None) -> float:
    """Escala píxeles CSS -> píxeles de ventana. La referencia es la de Windows (`GetDpiForWindow`); si la página informa de
    un `devicePixelRatio` sensato y distinto (>1 %), manda ese: es lo que WebView2 pinta de verdad."""
    base = escala_dpi(dpi)
    if dpr and 0.5 <= dpr <= 4.0 and abs(dpr - base) / base > 0.01:
        return float(dpr)
    return base


def a_fisicos(css: float, escala: float) -> int:
    return int(round(css * escala))


def a_css(fisicos: float, escala: float) -> float:
    return fisicos / escala if escala else float(fisicos)


def calcular_layout(ancho_css: float, izq: float | None = None, der: float | None = None, uno: float | None = None) -> dict:
    """Reparto en píxeles CSS para una ventana de `ancho_css`. `izq`, `der` y `uno` son las medidas recordadas (None = por defecto).

    Con ancho >= 1280: dos paneles (izquierdo y derecho) y hueco central de al menos 320 px.
    Con menos: un único panel a la derecha (`izq` = 0), sin hueco que gestionar.
    Devuelve {modo: "dos"|"uno", ancho, izq, der, hueco}.
    """
    ancho = float(ancho_css)
    if ancho < UMBRAL_DOS_PANELES:
        defecto = _acotar(round(ancho * 0.35), 320, 420)
        panel = round(_acotar(uno if uno else defecto, UNICO_MIN, max(UNICO_MIN, ancho * UNICO_MAX_FRAC)))
        panel = min(panel, int(ancho))
        return {"modo": "uno", "ancho": round(ancho), "izq": 0, "der": panel, "hueco": round(ancho) - panel}
    lateral = round(ancho * PROPORCION_LATERAL)
    i = round(_acotar(izq if izq else lateral, MIN_LATERAL, ancho - MIN_HUECO - MIN_LATERAL))
    d = round(_acotar(der if der else lateral, MIN_LATERAL, ancho - MIN_HUECO - i))
    return {"modo": "dos", "ancho": round(ancho), "izq": i, "der": d, "hueco": round(ancho) - i - d}


def rectangulos_region(ancho_px: int, alto_px: int, layout: dict, escala: float) -> list[tuple[int, int, int, int]]:
    """Rectángulos (izq, arriba, der, abajo) de la ventana que se conservan, en píxeles físicos y relativos a su esquina superior
    izquierda. El hueco queda fuera. Con escala 1,25 un panel de 360 px CSS son 450 px físicos."""
    rects: list[tuple[int, int, int, int]] = []
    if layout["izq"] > 0:
        rects.append((0, 0, min(ancho_px, a_fisicos(layout["izq"], escala)), alto_px))
    if layout["der"] > 0:
        rects.append((max(0, ancho_px - a_fisicos(layout["der"], escala)), 0, ancho_px, alto_px))
    return [r for r in rects if r[2] > r[0] and r[3] > r[1]]


def punto_en_region(rects: list[tuple[int, int, int, int]], x: int, y: int) -> bool:
    return any(a <= x < c and b <= y < d for a, b, c, d in rects)


def opacidad_valida(pct) -> int:
    try:
        return int(round(_acotar(float(pct), OPACIDAD_MIN, OPACIDAD_MAX)))
    except (TypeError, ValueError):
        return OPACIDAD_MAX


def opacidad_a_alfa(pct) -> int:
    """Porcentaje (60-100) -> alfa de `SetLayeredWindowAttributes` (0-255)."""
    return int(round(opacidad_valida(pct) * 255 / 100))
