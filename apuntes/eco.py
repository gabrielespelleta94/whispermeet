"""Eco entre canales, todo local (sin modelo y sin audio a disco).

En una sala el micrófono vuelve a recoger lo que suena por los altavoces: lo mismo queda escrito dos veces, una en «Reunión» (la
versión buena, directa del sistema) y otra en «Micro» (con ruido de sala, otra segmentación y a menudo otras palabras: «pasú» frente
a «pago»). Aquí se decide, de forma PURA y determinista, qué parte de un fragmento de Micro es eco de lo que dijo Reunión en una
ventana de tiempo, con similitud difusa por palabras (español y catalán).

Reglas (en este orden de importancia):
1. Se conserva SIEMPRE la versión de Reunión; solo se toca Micro.
2. De un fragmento de Micro se elimina únicamente la parte que coincide. Lo que no tiene equivalente se queda: ahí está la voz de
   quien está en la sala. El micro puede recoger a VARIAS personas: nunca se supone que sea una sola (regla de Etiquetas).
3. Ante la duda, se conserva: perder voz real es peor que dejar un duplicado. Por eso un tramo solo es eco si coinciden de forma
   sostenida varias palabras con contenido (`MIN_PARES` palabras alineadas y `MIN_PESO` de contenido); un «vale» o un «sí, claro» que
   dicen los dos canales nunca se elimina.
4. El resultado no depende del orden de llegada: es una función del conjunto de fragmentos. Si Micro llega antes que Reunión, el texto
   se recalcula cuando llega su pareja (`Sesion`), y mientras tanto no se entrega a ningún análisis (`micro_listo`).

Todo son constantes con su porqué; no son preferencias del usuario (el único interruptor es `filtrar_eco` en la configuración).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from functools import lru_cache

from .rutas import sin_acentos
from .texto import _STOP

# Ventana temporal: la marca de un fragmento es el INICIO de su tramo de audio y los dos canales segmentan distinto (se han visto
# diferencias de 2 a 15 s entre el mismo texto en Micro y en Reunión, en cualquiera de los dos sentidos).
VENTANA_ANTES_S = 45.0     # Reunión que empieza hasta este tiempo ANTES del fragmento de Micro
VENTANA_DESPUES_S = 45.0   # …o hasta este tiempo DESPUÉS
ESPERA_S = 60.0            # tiempo máximo que un Micro espera a su pareja de Reunión antes de entregarse (llegada, reloj de la reunión)

UMBRAL_PALABRA = 0.75      # similitud (SequenceMatcher sobre la palabra plegada) para dar dos palabras por la misma: una letra de cuatro
MIN_PARES = 5              # palabras alineadas para que un tramo cuente como eco
MIN_PESO = 3.0             # …y al menos esto de contenido (una palabra con contenido pesa 1; un artículo o un «vale», 0,3)
PESO_FUNCION = 0.3
DENSIDAD_MIN = 0.5         # palabras alineadas / longitud del tramo en Micro: un tramo ralo de coincidencias sueltas no es eco
MAX_PALABRAS_REBABA = 3    # resto máximo, sin palabras con contenido, que se descarta al lado de un tramo eliminado
HUECO_MICRO = 2            # palabras de Micro sin pareja que no cortan un tramo (variantes de transcripción: «pago» frente a «pasú»)
HUECO_REUNION = 4          # lo mismo en el texto de Reunión
UNION_MICRO_MAX = 8        # entre dos tramos que SÍ son eco se absorbe un hueco de Micro de hasta tantas palabras…
MAX_TOKENS_MICRO = 400     # topes de cálculo (un fragmento más largo se trata por trozos; la ventana, por cercanía)
MAX_TOKENS_REUNION = 900

_RE_PALABRA = re.compile(r"\d+(?:[.,]\d+)*(?![^\W_])|[^\W_]+|€", re.UNICODE)
_CON_DIGITOS = re.compile(r"\d")

_STOP_CA = set("""amb per una uns unes aquest aquesta aquests aquestes aixo allo pero perque quan molt mes tambe aqui ara doncs llavors
sempre mai cada altre altra altres tot tota tots totes son esta hi ho els les dels del ens seva seu meu teu tinc tens tenim tenen
vaig vols vol volem poden pot puc hem heu han hauria haver fer fem feu fan estem esteu estan sera seran seria seriem
vale bueno claro exacto perfecto correcto cierto vaya hombre mira oye escucha escolta sabes saps entonces digamos
""".split())


def _plegar(palabra: str) -> str:
    """Forma comparable de una palabra: minúsculas, sin acentos y con las grafías que Whisper confunde en español y en catalán
    (b/v, s/z/ç, c/qu/k, h muda, ll, doble consonante)."""
    p = sin_acentos(palabra).lower()
    p = p.replace("ll", "l").replace("ny", "n").replace("qu", "k").replace("ç", "s")
    p = re.sub(r"c(?=[aou])", "k", p)
    p = re.sub(r"c(?=[ei])", "s", p)
    p = p.replace("v", "b").replace("z", "s").replace("h", "")
    return re.sub(r"(.)\1+", r"\1", p)


_FUNCION = {_plegar(w) for w in _STOP} | {_plegar(w) for w in _STOP_CA}


@dataclass(frozen=True)
class Palabra:
    clave: str       # forma plegada
    ini: int         # posición en el texto original
    fin: int
    peso: float      # 1 con contenido, PESO_FUNCION si es una palabra función o muy corta


def _peso(clave: str) -> float:
    if clave.isdigit():
        return 1.0 if len(clave) >= 2 and clave.strip("0") else PESO_FUNCION
    if len(clave) < 4 or clave in _FUNCION:
        return PESO_FUNCION
    return 1.0


# ---------------------------------------------------------------- cifras: una sola forma canónica
# «noventa y cinco euros» (Reunión) y «95 €» (Micro) son la MISMA cifra: sin esto el eco no casa y, peor, un Micro con la cifra dicha
# en letras se confundía con una frase parecida de Reunión sin ella y la perdía. Español y catalán, hasta los miles (y «millones» se
# deja como palabra: «dos millones» queda «2 millones» en los dos lados). Una palabra ambigua suelta («un», «u», «nou», «deu») no
# cuenta como número: solo dentro de una cifra más larga («treinta y uno», «vint-i-u», «nou mil»).
_UNIDADES = {
    "cero": 0, "uno": 1, "un": 1, "una": 1, "u": 1, "dos": 2, "dues": 2, "tres": 3, "cuatro": 4, "quatre": 4, "cinco": 5, "cinc": 5,
    "seis": 6, "sis": 6, "siete": 7, "set": 7, "ocho": 8, "vuit": 8, "nueve": 9, "nou": 9}
_DIECES = {
    "diez": 10, "deu": 10, "once": 11, "onze": 11, "doce": 12, "dotze": 12, "trece": 13, "tretze": 13, "catorce": 14, "catorze": 14,
    "quince": 15, "quinze": 15, "dieciseis": 16, "setze": 16, "diecisiete": 17, "disset": 17, "dieciocho": 18, "divuit": 18,
    "diecinueve": 19, "dinou": 19, "veinte": 20, "vint": 20, "veintiuno": 21, "veintiun": 21, "veintiuna": 21, "veintidos": 22,
    "veintitres": 23, "veinticuatro": 24, "veinticinco": 25, "veintiseis": 26, "veintisiete": 27, "veintiocho": 28, "veintinueve": 29}
_DECENAS = {
    "treinta": 30, "trenta": 30, "cuarenta": 40, "quaranta": 40, "cincuenta": 50, "cinquanta": 50, "sesenta": 60, "seixanta": 60,
    "setenta": 70, "setanta": 70, "ochenta": 80, "vuitanta": 80, "noventa": 90, "noranta": 90}
_CENTENAS = {
    "cien": 100, "ciento": 100, "cent": 100, "doscientos": 200, "doscientas": 200, "trescientos": 300, "trescientas": 300,
    "cuatrocientos": 400, "cuatrocientas": 400, "quinientos": 500, "quinientas": 500, "seiscientos": 600, "seiscientas": 600,
    "setecientos": 700, "setecientas": 700, "ochocientos": 800, "ochocientas": 800, "novecientos": 900, "novecientas": 900}
_CENTS_CA = {"cents", "centes"}   # «dos-cents»: multiplica la unidad anterior
_AMBIGUAS = {"un", "una", "u", "nou", "deu", "set"}
_CONECTORES = {"y", "i"}


def _suma(cur: int, w: str):
    """Nuevo valor parcial (<1000) al añadir la palabra numérica `w`, o None si no puede seguir a `cur` en la misma cifra."""
    if w in _UNIDADES:
        v = _UNIDADES[w]
        return cur + v if cur % 100 == 0 or (cur % 100 >= 20 and cur % 10 == 0) else None
    if w in _DIECES:
        return cur + _DIECES[w] if cur % 100 == 0 else None
    if w in _DECENAS:
        return cur + _DECENAS[w] if cur % 100 == 0 else None
    if w in _CENTENAS:
        return cur + _CENTENAS[w] if cur == 0 else None
    if w in _CENTS_CA:
        return cur * 100 if 2 <= cur <= 9 else None
    return None


def _es_numero(w: str) -> bool:
    return w in _UNIDADES or w in _DIECES or w in _DECENAS or w in _CENTENAS or w in _CENTS_CA or w == "mil"


def _cifras_en_letras(crudas: list[tuple[str, int, int]]) -> list[tuple[str, int, int]]:
    """[(texto sin acentos y en minúsculas, ini, fin)] → lo mismo con cada cifra escrita en letras reducida a UN elemento con sus dígitos."""
    out, i, n = [], 0, len(crudas)
    while i < n:
        w = crudas[i][0]
        if not _es_numero(w):
            out.append(crudas[i])
            i += 1
            continue
        total, cur, j, usadas, hubo_mil = 0, 0, i, 0, False
        while j < n:
            w = crudas[j][0]
            if w == "mil" and not hubo_mil:
                total, cur, hubo_mil = total + max(cur, 1) * 1000, 0, True
            elif w in _CONECTORES and usadas and j + 1 < n and _es_numero(crudas[j + 1][0]) and crudas[j + 1][0] != "mil"                     and _suma(cur, crudas[j + 1][0]) is not None and cur % 100 >= 20:
                j += 1
                continue
            else:
                nuevo = _suma(cur, w) if _es_numero(w) and w != "mil" else None
                if nuevo is None:
                    break
                cur = nuevo
            usadas += 1
            j += 1
        if usadas == 0:   # no avanzó (palabra numérica que no encaja): se deja tal cual
            out.append(crudas[i])
            i += 1
        elif usadas == 1 and crudas[i][0] in _AMBIGUAS:
            out.append(crudas[i])
            i += 1
        else:
            out.append((str(total + cur), crudas[i][1], crudas[j - 1][2]))
            i = j
    return out


def _clave_cifra(t: str) -> str:
    """«1.500» → «1500», «95,5» → «95.5»: la cifra escrita con dígitos, en su forma canónica."""
    if re.fullmatch(r"\d{1,3}(?:\.\d{3})+(?:,\d+)?", t):
        t = t.replace(".", "")
    return t.replace(",", ".")


def palabras(texto: str) -> list[Palabra]:
    crudas = []
    for m in _RE_PALABRA.finditer(texto or ""):
        g = m.group()
        crudas.append(("euros" if g == "€" else (g if g[0].isdigit() and not g.isalnum() else sin_acentos(g).lower()), m.start(), m.end()))
    out = []
    for g, ini, fin in _cifras_en_letras(crudas):
        k = _clave_cifra(g) if g[:1].isdigit() and not g.isalpha() and re.fullmatch(r"\d[\d.,]*", g) else _plegar(g)
        if k:
            out.append(Palabra(k, ini, fin, _peso(k)))
    return out


@lru_cache(maxsize=300_000)
def _iguales(a: str, b: str) -> bool:
    if a == b:
        return True
    if min(len(a), len(b)) < 4 or abs(len(a) - len(b)) > 3 or a in _FUNCION or b in _FUNCION or _CON_DIGITOS.search(a) or _CON_DIGITOS.search(b):
        return False   # cifras y códigos («52», «ov2», «termino3x1»): o son iguales o son otra cosa
    return SequenceMatcher(None, a, b).ratio() >= UMBRAL_PALABRA


def _alinear(m: list[Palabra], r: list[Palabra]) -> list[tuple[int, int]]:
    """Subsecuencia común de mayor peso entre las palabras de Micro y de Reunión, con igualdad difusa: pares (i, j) en orden."""
    n, k = len(m), len(r)
    if not n or not k:
        return []
    puntos = [[0.0] * (k + 1) for _ in range(n + 1)]
    for i in range(n - 1, -1, -1):
        fila, sig = puntos[i], puntos[i + 1]
        for j in range(k - 1, -1, -1):
            mejor = sig[j] if sig[j] >= fila[j + 1] else fila[j + 1]
            if _iguales(m[i].clave, r[j].clave):
                v = sig[j + 1] + min(m[i].peso, r[j].peso)
                if v > mejor:
                    mejor = v
            fila[j] = mejor
    pares, i, j = [], 0, 0
    while i < n and j < k:
        if _iguales(m[i].clave, r[j].clave) and abs(puntos[i][j] - (puntos[i + 1][j + 1] + min(m[i].peso, r[j].peso))) < 1e-9:
            pares.append((i, j))
            i += 1
            j += 1
        elif puntos[i + 1][j] >= puntos[i][j + 1]:
            i += 1
        else:
            j += 1
    return pares


@dataclass
class _Tramo:
    pares: list[tuple[int, int]]

    @property
    def i0(self) -> int:
        return self.pares[0][0]

    @property
    def i1(self) -> int:
        return self.pares[-1][0]

    @property
    def j0(self) -> int:
        return self.pares[0][1]

    @property
    def j1(self) -> int:
        return self.pares[-1][1]


def _hay_cifra(m: list[Palabra], desde: int, hasta: int) -> bool:
    """¿Hay una cifra o un código entre esas palabras de Micro (sin pareja)? Un número que no coincide NUNCA se absorbe: puede ser la diferencia que importa."""
    return any(_CON_DIGITOS.search(p.clave) for p in m[desde:hasta])


def _es_eco(t: _Tramo, m: list[Palabra]) -> bool:
    peso = sum(m[i].peso for i, _ in t.pares)
    longitud = t.i1 - t.i0 + 1
    return len(t.pares) >= MIN_PARES and peso >= MIN_PESO and len(t.pares) / longitud >= DENSIDAD_MIN


def tramos_eco(m: list[Palabra], r: list[Palabra]) -> list[tuple[int, int]]:
    """Intervalos (primera, última) de palabras de Micro que son eco de Reunión. Vacío si no hay coincidencia sostenida."""
    pares = _alinear(m, r)
    if not pares:
        return []
    tramos: list[_Tramo] = []
    for i, j in pares:
        if (tramos and i - tramos[-1].i1 - 1 <= HUECO_MICRO and j - tramos[-1].j1 - 1 <= HUECO_REUNION
                and not _hay_cifra(m, tramos[-1].i1 + 1, i)):
            tramos[-1].pares.append((i, j))
        else:
            tramos.append(_Tramo([(i, j)]))
    validos = [t for t in tramos if _es_eco(t, m)]
    if not validos:
        return []
    # entre dos tramos que SÍ son eco, una zona pequeña de Micro sin pareja con otra zona equivalente en Reunión es la misma frase mal
    # transcrita («serán así retentadas» frente a «será una cifra tancada»): se absorbe. Si en Reunión no hay nada en medio, es voz propia.
    unidos = [[validos[0].i0, validos[0].i1, validos[0].j1]]
    for t in validos[1:]:
        gm = t.i0 - unidos[-1][1] - 1
        gr = t.j0 - unidos[-1][2] - 1
        if gm <= UNION_MICRO_MAX and gr >= (gm + 1) // 2 and gm <= 2 * gr + 2 and not _hay_cifra(m, unidos[-1][1] + 1, t.i0):
            unidos[-1][1], unidos[-1][2] = t.i1, t.j1
        else:
            unidos.append([t.i0, t.i1, t.j1])
    return [(a, b) for a, b, _ in unidos]


def _sin_cifras_nuevas(quitar: list[tuple[int, int]], m: list[Palabra], r: list[Palabra]) -> list[tuple[int, int]]:
    """Red de seguridad: un tramo de Micro con una cifra que NO aparece en el texto de Reunión de la ventana nunca se elimina (es justo la
    diferencia que importa: «precio noventa y cinco euros» frente a «precio por pasajero»). Las cifras ya están en forma canónica."""
    en_reunion = {p.clave for p in r if _CON_DIGITOS.search(p.clave)}
    return [(a, b) for a, b in quitar
            if all(not _CON_DIGITOS.search(p.clave) or p.clave in en_reunion for p in m[a:b + 1])]


def quitar_eco(texto: str, t: float, reunion: list[tuple[float, str]],
               antes: float = VENTANA_ANTES_S, despues: float = VENTANA_DESPUES_S) -> str:
    """Texto de un fragmento de Micro (marca `t`) sin la parte que es eco de lo que dijo Reunión en la ventana. FUNCIÓN PURA.
    `reunion`: [(t, texto)] de los fragmentos de Reunión (se usan los de la ventana, ordenados por marca; el orden de llegada no importa).
    Devuelve el texto tal cual si no hay eco, el resto (trozos que no coinciden, unidos con «…») o «» si TODO era eco."""
    texto = texto or ""
    m = palabras(texto)[:MAX_TOKENS_MICRO]
    if len(m) < MIN_PARES:
        return texto
    pool = sorted((x for x in reunion if x[1] and t - antes <= x[0] <= t + despues), key=lambda x: (abs(x[0] - t), x[0]))
    r: list[Palabra] = []
    tope = 0
    elegidos = []
    for x in pool:   # los más cercanos primero hasta el tope de cálculo; luego, en orden de tiempo
        p = palabras(x[1])
        if tope + len(p) > MAX_TOKENS_REUNION and elegidos:
            break
        tope += len(p)
        elegidos.append((x[0], p))
    for _, p in sorted(elegidos, key=lambda x: x[0]):
        r.extend(p)
    if len(r) < MIN_PARES:
        return texto
    quitar = _sin_cifras_nuevas(tramos_eco(m, r), m, r)
    if not quitar:
        return texto
    return _rehacer(texto, m, quitar)


def _rehacer(texto: str, m: list[Palabra], quitar: list[tuple[int, int]]) -> str:
    """El texto sin las palabras `quitar` (intervalos de índices de `m`): los trozos que quedan, tal cual estaban escritos."""
    fuera = [False] * len(m)
    for a, b in quitar:
        for i in range(a, b + 1):
            fuera[i] = True
    trozos, i = [], 0
    while i < len(m):
        if fuera[i]:
            i += 1
            continue
        j = i
        while j + 1 < len(m) and not fuera[j + 1]:
            j += 1
        fin = m[j + 1].ini if j + 1 < len(m) else len(texto)
        ini = m[i].ini
        trozo = texto[ini:fin].strip().strip("¿¡").strip()
        # la puntuación que pega con lo eliminado («…, y»): se conserva solo la que cierra la frase
        trozo = re.sub(r"^[\s,;:\-–—]+", "", trozo)
        # un resto de ≤3 palabras sin ninguna con contenido pegado a un tramo eliminado («Si», «Vale. Y la») es la rebaba del corte, no voz
        sobrante = m[i:j + 1]
        if _RE_PALABRA.search(trozo) and not (len(sobrante) <= MAX_PALABRAS_REBABA and all(p.peso < 1.0 for p in sobrante)):
            trozos.append(trozo)
        i = j + 1
    return " … ".join(trozos)


def micro_listo(llegada: float, ahora: float, reunion: list[tuple[float, str]], t: float, final: bool = False) -> bool:
    """¿Ya se puede entregar este fragmento de Micro a un análisis? Sí si es el cierre, si ha esperado `ESPERA_S` desde que llegó, o si Reunión
    ya ha avanzado más allá de la ventana (su pareja, si existe, ya llegó: la cola de transcripción es una sola y sale por orden). FUNCIÓN PURA."""
    if final or ahora - llegada >= ESPERA_S:
        return True
    return any(x[0] > t + VENTANA_DESPUES_S for x in reunion)
