"""Transcripción con faster-whisper (CPU, int8). Los buffers de audio se descartan al transcribir."""
from __future__ import annotations

import gc
import queue
import re
import threading
import time
from collections import deque
from difflib import SequenceMatcher

import numpy as np

from .config import APP_DIR
from .rutas import sin_acentos

MODELOS_DIR = APP_DIR / "modelos"

# Alucinaciones típicas de Whisper sobre silencio o música. «vale» y «ok» sueltos se CONSERVAN (suelen ser un acuerdo);
# «gracias» suelto se descarta (es la alucinación más común sobre silencio).
ALUCINACIONES = re.compile(
    r"amara\.org|subtítulos (realizados|por)|gracias por (ver|vuestra atención)|"
    r"^\W*gracias\W*$", re.I)
# Equivalentes catalanes de esos mismos créditos de vídeo (Whisper los emite con las mismas fórmulas en catalán: «Subtítols realitzats per…»,
# «Gràcies per veure», «Gràcies» solo sobre silencio). «Gràcies» suelto se descarta igual que «gracias»; «gràcies per l'ajuda» no.
ALUCINACIONES_CA = re.compile(
    r"subt[ií]tols (realitzats|fets|de la comunitat|per)|gr[àa]cies per (veure|mirar|la vostra atenci[óo])|"
    r"^\W*gr[àa]cies\W*$", re.I)

# Fórmulas de vídeo («suscríbete», «suscribíos», «suscríbanse», «suscribirse al canal»…). NO casa «hay que suscribir el contrato».
SUSCRIPCION = re.compile(
    r"\bsuscr[ií]b(?:ete|[ií]os|anse|ase)\b|"
    r"\bsuscribi(?:rte|rse|ros)\s+(?:al|a\s+(?:mi|nuestro|este|el))\s+canal\b|"
    r"\bno\s+(?:te\s+)?olvid\w*\s+(?:de\s+)?suscribi", re.I)

# «subscriu-te», «subscriviu-vos», «no oblidis subscriure't al canal»: la fórmula de vídeo en catalán. NO casa «cal subscriure el contracte».
SUSCRIPCION_CA = re.compile(
    r"\bsubscriu[- ]?(?:te|vos)\b|\bsubscriviu[- ]?vos\b|"
    r"\bsubscriure[- ]?(?:'?t|'?us)\s+(?:al|a\s+(?:el|aquest|aquesta|nostre|meu))\s+canal\b|"
    r"\bno\s+(?:t['’]?)?\s*oblid\w*\s+(?:de\s+)?subscriu", re.I)

URL = re.compile(r"(?:https?://|www\.)\S+", re.I)
MAX_PALABRAS_TRAS_URL = 3   # un tramo con URL y a lo sumo estas palabras más es un crédito/dirección, no una frase real

# Prompt de Whisper (initial_prompt): admite ~224 tokens; se usan ~200. Aproximación por caracteres (español con siglas,
# ~2,4 caracteres por token): 480 caracteres.
MAX_PROMPT_CHARS = 480
MAX_PALABRAS_CONTINUIDAD = 30
MIN_PALABRAS_CONTINUIDAD = 6    # si la última frase es muy corta («Vale.») se le suma la anterior hasta este mínimo
ETIQUETA_VOCABULARIO = "Términos:"
ETIQUETA_VOCABULARIO_CA = "Termes:"
ETIQUETA_VOCABULARIO_EN = "Terms:"
# initial_prompt del tema, coherente con el idioma que se transcribe: un prompt en español sesga a Whisper hacia el español.
PROMPT_TEMA = {"es": "Reunión de trabajo: {}.", "ca": "Reunió de treball: {}.", "en": "Work meeting: {}."}
ETIQUETAS = {"es": ETIQUETA_VOCABULARIO, "ca": ETIQUETA_VOCABULARIO_CA, "en": ETIQUETA_VOCABULARIO_EN}
IDIOMAS_TRANSCRIPCION = ("es", "ca", "en")


# hotwords de faster-whisper (≥1.0): los términos del proyecto también como pista de decodificación, aparte del initial_prompt.
# Presupuesto propio y corto (el prompt ya gasta sus 480): se recorta por el final, que es lo menos prioritario.
MAX_HOTWORDS_CHARS = 200


def construir_hotwords(vocabulario=(), tope: int = MAX_HOTWORDS_CHARS) -> str:
    """«a, b, c» con los primeros términos del vocabulario que caben en `tope` caracteres; vacío si no hay vocabulario."""
    elegidos, usado = [], 0
    for term in vocabulario or ():
        term = " ".join(str(term).split())
        if not term:
            continue
        coste = len(term) + (2 if elegidos else 0)
        if usado + coste > tope:
            break
        elegidos.append(term)
        usado += coste
    return ", ".join(elegidos)


_VOCALES = {"a": "aáàâä", "e": "eéèêë", "i": "iíìîï", "o": "oóòôö", "u": "uúùûü", "n": "nñ", "c": "cç"}


def _plegado(s: str) -> str:
    return " ".join(sin_acentos(s).lower().split())


def _patron_termino(term: str) -> str:
    """Patrón (sin distinguir mayúsculas ni acentos) de un término del glosario; los espacios admiten cualquier hueco."""
    out = []
    for ch in " ".join(term.split()):
        if ch == " ":
            out.append(r"\s+")
        else:
            base = _plegado(ch)
            out.append(f"[{_VOCALES[base]}]" if base in _VOCALES else re.escape(ch))
    return "".join(out)


def _es_sigla_o_codigo(t: str) -> bool:
    """≥2 mayúsculas o algún dígito (SAP, TPV, PowerBI, TR2): un término así no es una palabra corriente."""
    return sum(c.isupper() for c in t) >= 2 or any(c.isdigit() for c in t)


def corregir_glosario(texto: str, terminos, curados=()) -> str:
    """Arregla mayúsculas y acentos de los términos del glosario en el texto («sap» → «SAP», «fiori» → «Fiori»). FUNCIÓN PURA.
    Solo palabras completas (nunca «sapo» ni «tpvs»), sin distinguir mayúsculas ni acentos, y solo toca lo que es un término: el resto
    del texto queda exactamente igual. Si hay dos términos que solo se diferencian en eso, manda el primero de la lista.
    `curados`: términos del vocabulario del usuario (config), que se corrigen siempre; del resto solo se corrigen siglas y códigos."""
    if not texto or not terminos:
        return texto
    fiables = {_plegado(c) for c in (curados or ()) if str(c).strip()}
    forma: dict[str, str] = {}
    for t in terminos:
        t = " ".join(str(t).split())
        # Solo se fuerza lo que no es una palabra corriente: siglas/códigos o lo que el usuario puso en su vocabulario. Un término
        # sacado del contexto con solo la inicial en mayúscula («Reserva») NO se impone («la reserva» sigue igual).
        if len(t) >= 2 and (_es_sigla_o_codigo(t) or _plegado(t) in fiables):
            forma.setdefault(_plegado(t), t)
    if not forma:
        return texto
    claves = sorted(forma, key=len, reverse=True)   # el más largo primero: «Power BI» antes que «Power»
    patron = re.compile(r"(?<!\w)(?:" + "|".join(_patron_termino(forma[k]) for k in claves) + r")(?!\w)", re.I)
    return patron.sub(lambda m: forma.get(_plegado(m.group(0)), m.group(0)), texto)


def prompt_tema(tema: str, idioma: str = "es") -> str:
    return PROMPT_TEMA.get(idioma, PROMPT_TEMA["es"]).format(tema)


# ---------------------------------------------------------------- idioma automático (español/catalán, por fragmento)
# Constantes con su porqué. No hay audio de voz real en catalán en esta máquina para calibrarlas: son valores prudentes y se pueden
# afinar con reuniones reales (config: no se exponen a propósito; son decisiones de ingeniería, no preferencias del usuario).
MIN_DURACION_DETECCION_S = 2.0   # Whisper detecta el idioma sobre los primeros 30 s con relleno de silencio: por debajo de ~2 s de voz
                                  # (una o dos palabras: «vale», «sí, sí») la señal es casi nula y el catalán se confunde con el español
MIN_CONFIANZA_AUTO = 0.75        # probabilidad del ganador RENORMALIZADA entre los idiomas permitidos (es+ca): el español y el catalán
                                  # son vecinos, un 60/40 es un empate práctico; con 75 % no se cambia de idioma por un fragmento dudoso
MIN_MASA_AUTO = 0.5              # es+ca deben sumar al menos la mitad de la probabilidad total: si no, el audio es ruido, música u otro
                                  # idioma y renormalizar entre dos candidatos daría una "confianza" falsa
MOTIVOS_IDIOMA = ("fijo", "detectado", "corto", "poca_masa", "poca_confianza", "sin_deteccion")


def decidir_idioma(probs, duracion_s: float, ultimo: str | None, idiomas_auto=("es", "ca", "en"),
                   min_duracion_s: float = MIN_DURACION_DETECCION_S, min_confianza: float = MIN_CONFIANZA_AUTO,
                   min_masa: float = MIN_MASA_AUTO) -> tuple[str, str]:
    """Idioma de un fragmento en modo automático. FUNCIÓN PURA. `probs`: {idioma: probabilidad} o [(idioma, p)] de `detect_language`
    (None si no se detectó: fragmento corto o fallo). Solo elige entre `idiomas_auto`.
    Devuelve (idioma, motivo): «detectado» si manda la detección; si no, se reutiliza `ultimo` (el último idioma de ESA fuente) o, sin
    ninguno, el primero de `idiomas_auto`; el motivo dice por qué («corto», «poca_masa», «poca_confianza», «sin_deteccion»).
    La reutilización nunca bloquea un cambio: basta UN fragmento con duración y confianza suficientes en el otro idioma."""
    permitidos = [i for i in dict.fromkeys(idiomas_auto or ()) if isinstance(i, str) and i] or ["es"]
    previo = ultimo if ultimo in permitidos else permitidos[0]
    if len(permitidos) == 1:
        return permitidos[0], "fijo"
    if duracion_s < min_duracion_s:
        return previo, "corto"
    if not probs:
        return previo, "sin_deteccion"
    p = dict(probs)
    cand = {i: max(0.0, float(p.get(i, 0.0))) for i in permitidos}
    masa = sum(cand.values())
    if masa < min_masa:
        return previo, "poca_masa"
    mejor = max(permitidos, key=lambda i: (cand[i], i == previo))
    if cand[mejor] / masa < min_confianza:
        return previo, "poca_confianza"
    return mejor, "detectado"


# La transcripción no puede quedarse atrás. Whisper codifica SIEMPRE una ventana de 30 s: un «vale» de un segundo costaba casi lo mismo que
# una frase de 25 (≈2-3 s de cálculo) y, con dos canales hablando, la cola crecía sin techo (visto en una reunión real: 180 s de retraso;
# la transcripción ya no servía en directo). Cuatro medidas, todas medidas con el modelo `small` (int8, 6 hilos):
# 1. VENTANA AJUSTADA: el codificador solo procesa lo que dura el tramo más un margen (`ventana_frames`), no 30 s. Un tramo de 2 s pasa de
#    1,9 s de cálculo a 0,4 s; uno de 6,5 s, de 2,6 s a 1,1 s; la detección de idioma, de 1,5 s a 0,3 s. Mismo texto con 5 s de margen (con
#    3 s se perdió una frase en un tramo de 12 s). Se hace recortando las características a la entrada de `WhisperModel.encode`
#    (`Transcriptor._instalar_ventana`): es un método público y no toca el interior de faster-whisper.
# 2. MODO RÁPIDO con cola (≥ COLA_ALCANCE_S esperando): beam 3, un solo reintento de temperatura, sin probabilidad por palabra y sin volver a
#    detectar el idioma si se detectó hace poco (≈20-25 % menos de cálculo por tramo). NUNCA beam 1: en voraz Whisper entra en bucle («es lo
#    que es lo que es…») o se salta frases enteras cuando el tramo empieza a media frase (medido: 70-95 % del texto perdido). Medido sobre 47
#    tramos frente a la ventana de 30 s con beam 5: con beam 2 aún se pierde un 4,8 % en tramos largos; con beam 3, nada, y cuesta lo mismo.
# 3. TOPE DE TOKENS proporcional a la duración (`tope_tokens`): corta los bucles antes de que llenen la ventana.
# 4. UN REINTENTO, en rápido, si una pasada falla (p. ej. sin memoria): el tramo no se pierde a la primera.
# Los tramos se transcriben de uno en uno y en orden de llegada: cada texto es de SU tramo y la sesión los recibe en el orden de siempre.
# (Se probó juntar varios tramos en una pasada: con la ventana ajustada ya no ahorra nada y reparte mal el texto entre los tramos.)
# Constantes, no preferencias: el usuario no tiene que elegir entre directo y calidad.
COLA_ALCANCE_S = 6.0      # audio esperando en la cola (sin contar el tramo que se toma) a partir del cual se pasa al modo rápido
BEAM_RAPIDO = 3
TEMPERATURAS = (0.0, 0.2, 0.4)   # faster-whisper reintenta con la siguiente si un tramo falla por compresión (>2,4) o log-prob (<-1,0)
TEMPERATURAS_RAPIDO = (0.0, 0.2)
IDIOMA_VIGENTE_S = 20.0   # en modo rápido, el idioma detectado hace menos de esto para esa fuente se reutiliza sin volver a detectar
SR_WHISPER = 16000
FRAMES_POR_S = 100        # características de Whisper: una cada 10 ms
VENTANAS_S = (8, 10, 15, 20, 25, 30)   # ventanas del codificador: se usa la menor que cubre el tramo más el margen
MARGEN_VENTANA_S = 5.0
TOKENS_POR_S = 10         # holgura sobre el habla rápida (medido con el tokenizador de `small`: ≈7 tokens/s a 5 palabras/s, y las marcas
                          # de tiempo también cuentan); si se alcanzara, faster-whisper sigue desde la última marca completa
TOKENS_MARGEN = 24        # suelo para tramos muy cortos («sí, vale, de acuerdo, lo vemos el lunes»)
MAX_TOKENS_WHISPER = 448  # faster-whisper rechaza la llamada si prompt + max_new_tokens pasa de aquí
TOPE_TOKENS_SEGURO = 120  # sin tokenizador para contar el prompt (peor caso ≈330 tokens), por encima de esto no se pasa tope


def ventana_frames(duracion_s: float, margen_s: float = MARGEN_VENTANA_S) -> int:
    """Características (10 ms cada una) que debe ver el codificador para un tramo de `duracion_s` segundos: la menor ventana de `VENTANAS_S`
    que cubre el tramo más el margen (como mucho, los 30 s de Whisper). FUNCIÓN PURA."""
    necesita = min(max(0.0, duracion_s) + margen_s, VENTANAS_S[-1])
    return next(v for v in VENTANAS_S if v >= necesita) * FRAMES_POR_S


def tope_tokens(duracion_s: float, tokens_prompt: int | None = None) -> int | None:
    """max_new_tokens para un fragmento de `duracion_s` segundos. FUNCIÓN PURA. Con el tamaño real del prompt (`tokens_prompt`) el tope nunca
    hace que faster-whisper rechace la llamada; sin él, solo se pasa tope cuando cabe con seguridad. None = sin tope (el límite propio de
    Whisper ya acota)."""
    n = int(max(0.0, duracion_s) * TOKENS_POR_S) + TOKENS_MARGEN
    if tokens_prompt is None:
        return n if n <= TOPE_TOKENS_SEGURO else None
    libre = MAX_TOKENS_WHISPER - int(tokens_prompt) - 2
    return min(n, libre) if libre > 0 else None


def alinear_palabras(palabras_whisper, texto: str, umbral: float = 0.5) -> list[dict]:
    """Palabras con su probabilidad (ola 4). FUNCIÓN PURA. `palabras_whisper`: [(palabra, probabilidad)] de `word_timestamps`; `texto`: el texto FINAL del
    fragmento (ya filtrado y con el glosario aplicado). Se alinean palabra a palabra (el texto se parte por espacios, como Whisper): si el número no coincide
    (el filtro quitó algo, un bucle repetido…) no se adivina nada y la lista queda vacía. -> [{w, p, d}] con `d` = dudosa (probabilidad < `umbral`)."""
    tokens = (texto or "").split()
    if not palabras_whisper or len(tokens) != len(palabras_whisper):
        return []
    out = []
    for tok, (_w, p) in zip(tokens, palabras_whisper):
        p = max(0.0, min(1.0, float(p or 0.0)))
        out.append({"w": tok, "p": round(p, 2), "d": p < umbral})
    return out


def _solo_credito_o_url(t: str) -> bool:
    if not URL.search(t):
        return False
    resto = re.findall(r"\w+", URL.sub(" ", t))
    return len(resto) <= MAX_PALABRAS_TRAS_URL


def filtrar_texto(texto: str) -> str:
    t = re.sub(r"\s+", " ", texto or "").strip()
    if (not t or ALUCINACIONES.search(t) or SUSCRIPCION.search(t) or ALUCINACIONES_CA.search(t) or SUSCRIPCION_CA.search(t)
            or _solo_credito_o_url(t)):
        return ""
    # bucles típicos de whisper: la misma palabra/frase repetida muchas veces
    t = re.sub(r"\b(\w+(?:\s+\w+){0,3}?)(?:[\s,.]+\1\b){3,}", r"\1", t, flags=re.I)
    return _sin_frases_repetidas(t)


MIN_PALABRAS_FRASE_REPETIDA = 3   # «Sí. Sí.» o «Vale, vale.» son habla normal y se quedan; una frase entera dicha dos veces seguidas es el tic de Whisper


def _sin_frases_repetidas(t: str) -> str:
    """Deja una sola copia de una frase de ≥3 palabras repetida seguida («¿Alguien tiene alguna duda? ¿Alguien tiene alguna duda?»): lo emite
    Whisper cuando el tramo acaba cortado (el tope de tokens acota el bucle pero deja dos o tres copias). FUNCIÓN PURA."""
    frases = [f for f in re.split(r"(?<=[.!?…])\s+", t) if f]
    if len(frases) < 2:
        return t
    out: list[str] = []
    for f in frases:
        # idéntica CON su puntuación: «¿Lo tenemos el lunes? Lo tenemos el lunes.» es una pregunta y su respuesta, y se queda
        if out and len(_tokens(f)) >= MIN_PALABRAS_FRASE_REPETIDA and f.strip().casefold() == out[-1].strip().casefold():
            continue
        out.append(f)
    return " ".join(out)


def ultima_frase(texto: str, max_palabras: int = MAX_PALABRAS_CONTINUIDAD, min_palabras: int = MIN_PALABRAS_CONTINUIDAD) -> str:
    """La última frase del texto (tope de palabras); si es muy corta se le suma la anterior. Para el prompt de continuidad."""
    frases = [f for f in re.split(r"(?<=[.!?…])\s+", re.sub(r"\s+", " ", texto or "").strip()) if f.strip()]
    elegidas: list[str] = []
    n = 0
    for f in reversed(frases):
        elegidas.insert(0, f)
        n += len(f.split())
        if n >= min_palabras:
            break
    palabras = " ".join(elegidas).split()
    return " ".join(palabras[-max_palabras:])


def construir_prompt(base: str, vocabulario=(), continuidad: str = "", tope: int = MAX_PROMPT_CHARS,
                     etiqueta: str = ETIQUETA_VOCABULARIO) -> str:
    """`base` (tema) + «Términos: a, b.» + continuidad. Si no cabe, se conservan tema y continuidad y se recorta el vocabulario;
    solo si ni siquiera ellos caben se acorta la continuidad por el principio. Sin vocabulario ni continuidad, es `base`."""
    base, cont = (base or "").strip(), " ".join((continuidad or "").split())
    if cont and len(base) + len(cont) + 1 > tope:
        libre = max(0, tope - len(base) - 1)
        palabras = cont.split()
        while palabras and len(" ".join(palabras)) > libre:
            palabras.pop(0)
        cont = " ".join(palabras)
    fijo = " ".join(x for x in (base, cont) if x)
    libre = tope - len(fijo) - (1 if fijo else 0) - len(etiqueta) - 1   # -1: el punto final
    elegidos: list[str] = []
    usado = 0
    for term in vocabulario or ():
        term = " ".join(str(term).split())
        if not term:
            continue
        coste = len(term) + (2 if elegidos else 1)   # «, » o el espacio tras la etiqueta
        if usado + coste > libre:
            break   # los siguientes son menos prioritarios: no se salta a uno más corto para respetar la prioridad
        elegidos.append(term)
        usado += coste
    partes = [base]
    if elegidos:
        partes.append(f"{etiqueta} {', '.join(elegidos)}.")
    if cont:
        partes.append(cont)
    return " ".join(p for p in partes if p)


def _tokens(texto: str) -> list[str]:
    return re.findall(r"\w+", sin_acentos(texto or "").lower())


def es_copia_del_prompt(texto: str, prompt: str, vocabulario=(), continuidad: str = "") -> bool:
    """True si el resultado de un tramo es sustancialmente una copia del prompt: Whisper lo repite cuando el audio es silencio,
    ruido o muy corto. Casos: (1) un tramo contiguo de ≥4 palabras del prompt cubre ≥70 % del resultado; (2) el resultado es
    (casi) solo términos del vocabulario, sin frase; (3) repite entera la frase de continuidad."""
    r = _tokens(texto)
    if not r:
        return False
    p = _tokens(prompt)
    if p:
        m = SequenceMatcher(None, r, p, autojunk=False).find_longest_match(0, len(r), 0, len(p))
        if m.size >= 4 and m.size >= 0.7 * len(r):
            return True
    voc = {w for t in (vocabulario or ()) for w in _tokens(str(t))}
    if voc and len(r) >= 3 and sum(1 for w in r if w in voc) >= 0.9 * len(r):
        return True
    c = _tokens(continuidad)
    return len(c) >= 3 and r == c


class Transcriptor:
    def __init__(self, config, on_texto):
        """`on_texto(fuente, t_inicio, texto)` se llama desde el hilo del transcriptor."""
        self.config, self.on_texto = config, on_texto
        self.estado = "sin_cargar"  # sin_cargar | cargando | listo | error
        self.error = ""
        self._modelo = None
        self._cola: queue.Queue = queue.Queue()
        self._pendiente_s = 0.0
        self._lock = threading.Lock()
        self._parar = threading.Event()
        self._hilo: threading.Thread | None = None
        self.prompt = ""            # tema de la reunión («Reunión de trabajo: X.»); con vocabulario y continuidad forma el initial_prompt
        self.prompt_ca = ""         # el mismo tema en catalán («Reunió de treball: X.»); vacío = se usa `prompt` también en catalán
        self.prompt_en = ""         # el mismo tema en inglés («Work meeting: X.»); vacío = se usa `prompt`
        self.idioma: str | None = None   # idioma de ESTA reunión: auto | es | ca. None = el de la configuración (`idioma`)
        self.vocabulario_curado: list[str] = []   # subconjunto del vocabulario puesto por el usuario (config): único que corrige mayúsculas siempre
        self.vocabulario: list[str] = []   # términos distintivos del proyecto (locales, sin LLM); los primeros mandan al recortar
        self._ultima: dict[str, str] = {}  # última frase TRANSCRITA Y CONSERVADA por fuente (yo / reunion): nunca se mezclan
        self._ultimo_idioma: dict[str, str] = {}   # último idioma DETECTADO con confianza por fuente (también sin mezclar)
        self._idioma_usado: dict[str, str] = {}    # idioma con el que se transcribió el último tramo de cada fuente (es | ca)
        self.ultima_deteccion_ms = None            # coste de la última detección de idioma (None si no hubo)
        self.velocidad_x = None  # tiempo de audio / tiempo de cálculo, última medición
        self.entrega_palabras = False   # ola 4: el Gestor lo activa; solo entonces se piden word_timestamps y `on_texto` recibe `palabras=` (el dictado no)
        self._palabras: list[tuple[str, float]] = []   # (palabra, probabilidad) del último fragmento transcrito
        self.on_tarea = None     # on_tarea(fase, ident, **datos): inicio y fin REALES de cada tramo (panel de orquestación)
        self._n_tarea = 0
        self.alcance = False     # modo rápido en marcha: hay cola y el último tramo se decodificó en rápido (vuelve a False al vaciarse)
        self.tramos_rapidos = 0  # tramos decodificados en modo rápido en esta ejecución (diagnóstico)
        self.reintentos = 0      # pasadas que fallaron y se repitieron en rápido
        self.perdidos_s = 0.0    # segundos de audio que no se pudieron transcribir (fallo también en el reintento, o modelo sin cargar)
        self.ultimo_fallo = ""   # tipo de la última excepción que hizo perder un tramo (sin mensaje: puede llevar texto)
        self.latencia_s = None   # del último tramo: segundos entre que se cerró (se encoló) y que su texto quedó entregado
        self._espera: deque = deque()               # instante en que se encoló cada tramo pendiente, en orden (para `retraso_s`)
        self._t_deteccion: dict[str, float] = {}    # cuándo se detectó por última vez el idioma de cada fuente
        self._frames_ventana = 0                    # ventana del codificador para la llamada en curso (0 = los 30 s de Whisper)

    def _avisar(self, fase: str, ident: int, **datos) -> None:
        if self.on_tarea:
            try:
                self.on_tarea(fase, ident, **datos)
            except Exception:  # noqa: BLE001  (la telemetría nunca detiene la transcripción)
                pass

    @property
    def pendiente_s(self) -> float:
        return max(0.0, self._pendiente_s)

    @property
    def retraso_s(self) -> float:
        """Cuánto lleva esperando el tramo pendiente más antiguo (0 si no hay ninguno): lo que va la transcripción por detrás del directo.
        `pendiente_s` suma el audio de los dos canales; esto es tiempo de reloj."""
        with self._lock:
            return max(0.0, time.monotonic() - self._espera[0]) if self._espera else 0.0

    def iniciar(self) -> None:
        self._parar.clear()
        self._hilo = threading.Thread(target=self._bucle, daemon=True, name="transcriptor")
        self._hilo.start()

    def cargar_modelo(self):
        from faster_whisper import WhisperModel
        MODELOS_DIR.mkdir(parents=True, exist_ok=True)
        return WhisperModel(self.config["whisper_modelo"], device="cpu", compute_type="int8",
                            cpu_threads=int(self.config["whisper_hilos"]), download_root=str(MODELOS_DIR))

    def _instalar_ventana(self, modelo) -> None:
        """Hace que el codificador vea solo `_frames_ventana` características en vez de los 30 s que faster-whisper rellena siempre. Se envuelve
        `encode` (método público de `WhisperModel`; lo usan `transcribe` y `detect_language`): si la librería cambia y deja de pasar por ahí,
        simplemente no se recorta y todo sigue funcionando a la velocidad de antes. Los dobles de test sin `encode` quedan como están."""
        original = getattr(modelo, "encode", None)
        if not callable(original) or getattr(original, "_ventana_ajustada", False):
            return   # ya envuelto: un modelo compartido entre dictados (`dictado.py`) lleva su ventana consigo, una por hilo

        ventana = threading.local()   # del modelo y por hilo: dos transcriptores que compartan modelo no se pisan la ventana

        def encode(features, *args, **kw):
            n = getattr(ventana, "frames", 0)
            try:
                if n and features.shape[-1] > n:
                    features = np.ascontiguousarray(features[..., :n])
            except Exception:  # noqa: BLE001  (una forma inesperada: se codifica entera)
                pass
            return original(features, *args, **kw)

        encode._ventana_ajustada = True
        encode._ventana = ventana
        try:
            modelo.encode = encode
        except Exception:  # noqa: BLE001
            pass

    def _fijar_ventana(self, frames: int) -> None:
        """Ventana del codificador para las llamadas que haga ESTE hilo a partir de ahora (0 = los 30 s de Whisper)."""
        self._frames_ventana = frames
        ventana = getattr(getattr(self._modelo, "encode", None), "_ventana", None)
        if ventana is not None:
            ventana.frames = frames

    def encolar(self, fuente: str, audio: np.ndarray, t_inicio: float) -> None:
        dur = audio.size / SR_WHISPER
        if self.estado == "error":   # sin modelo no hay quien vacíe la cola: no se acumula audio en memoria, se cuenta como perdido
            self.perdidos_s += dur
            return
        with self._lock:   # la cola y `_espera` se llenan juntas: con dos hilos de captura, el mismo orden en las dos
            self._pendiente_s += dur
            self._espera.append(time.monotonic())
            self._cola.put((fuente, audio, t_inicio))

    def vacio(self) -> bool:
        return self._cola.empty() and self._pendiente_s <= 0.01

    def _bucle(self) -> None:
        self.estado = "cargando"
        self._n_tarea += 1
        carga = self._n_tarea
        self._avisar("inicio", carga, etiqueta="carga del modelo")
        ini_carga = time.perf_counter()
        try:
            self._modelo = self.cargar_modelo()
            self.estado = "listo"
            self._avisar("fin", carga, ok=True, ms=int((time.perf_counter() - ini_carga) * 1000))
        except Exception as e:  # noqa: BLE001
            self.estado, self.error = "error", f"No se pudo cargar el modelo de transcripción: {e}"
            self._avisar("fin", carga, ok=False, error=self.error, ms=int((time.perf_counter() - ini_carga) * 1000))
            return
        self._instalar_ventana(self._modelo)
        while not self._parar.is_set():
            try:
                fuente, audio, t0 = self._cola.get(timeout=0.3)
            except queue.Empty:
                self.alcance = False
                continue
            dur = audio.size / SR_WHISPER
            with self._lock:
                en_cola_s = self._pendiente_s - dur   # lo que espera DETRÁS del tramo que se toma
            rapido = en_cola_s >= COLA_ALCANCE_S
            self.alcance = rapido
            if rapido:
                self.tramos_rapidos += 1
            self._procesar(fuente, audio, t0, rapido)
            del audio
            if self._cola.empty():
                self.alcance = False

    def _procesar(self, fuente: str, audio: np.ndarray, t0: float, rapido: bool) -> None:
        """Transcribe un tramo y entrega su texto. Si la pasada falla se repite UNA vez en rápido; si vuelve a fallar, el tramo cuenta como perdido."""
        dur = audio.size / SR_WHISPER
        self._n_tarea += 1
        ident = self._n_tarea
        self._avisar("inicio", ident, fuente=fuente, audio_s=dur, **({"etiqueta": "tramo · rápido"} if rapido else {}))
        ini = time.perf_counter()
        try:
            try:
                segmentos = self._segmentos(audio, fuente, rapido=rapido)
            except Exception:  # noqa: BLE001  (sin memoria, un tramo que el modelo no digiere…): un reintento más barato antes de darlo por perdido
                if self._parar.is_set():
                    raise
                self.reintentos += 1
                gc.collect()
                segmentos = self._segmentos(audio, fuente, rapido=True)
            calc = time.perf_counter() - ini
            if calc > 0:
                self.velocidad_x = dur / calc
            texto = self._entregar(fuente, t0, " ".join(t for _i, t, _p in segmentos), [w for _i, _t, p in segmentos for w in p])
            self._avisar("fin", ident, ok=True, ms=int(calc * 1000), palabras=len(texto.split()))
        except Exception as e:  # noqa: BLE001
            self.error = f"Fallo al transcribir un tramo: {e}"
            self.perdidos_s += dur
            self.ultimo_fallo = type(e).__name__
            self._avisar("fin", ident, ok=False, error=self.error, ms=int((time.perf_counter() - ini) * 1000))
        finally:
            with self._lock:   # el buffer lo descarta quien llama
                self._pendiente_s -= dur
                if self._espera:
                    self.latencia_s = round(time.monotonic() - self._espera.popleft(), 2)

    def _entregar(self, fuente: str, t0: float, texto: str, palabras_whisper: list) -> str:
        """Filtra, corrige y entrega el texto de un tramo. Devuelve el texto entregado ("" si se descartó)."""
        texto = filtrar_texto(texto)
        if texto and es_copia_del_prompt(texto, self.prompt_para(fuente), self.vocabulario, self._ultima.get(fuente, "")):
            texto = ""   # el prompt se ha colado en el resultado: ni se emite ni sirve de continuidad
        if not texto or self._parar.is_set():   # tras `detener` no se entrega nada: la sesión ya está cerrada (o es otra)
            return ""
        texto = corregir_glosario(texto, self.vocabulario, self.vocabulario_curado)   # mayúsculas y acentos del glosario, antes de entrar en la sesión
        self._ultima[fuente] = ultima_frase(texto)
        pal = alinear_palabras(palabras_whisper, texto, self._umbral_dudosa()) if (self.entrega_palabras and palabras_whisper) else []
        if pal:
            self.on_texto(fuente, t0, texto, palabras=pal)
        else:
            self.on_texto(fuente, t0, texto)
        return texto

    def _cfg(self, clave: str, defecto):
        try:
            return self.config[clave]
        except (KeyError, TypeError):
            return defecto

    @property
    def modo_idioma(self) -> str:
        """auto | es | ca: el de esta reunión o, si no se fijó, el de la configuración (un valor desconocido cuenta como es)."""
        v = self.idioma if self.idioma is not None else self._cfg("idioma", "es")
        return v if v == "auto" or v in IDIOMAS_TRANSCRIPCION else "es"

    def idiomas_auto(self) -> list[str]:
        v = [i for i in (self._cfg("idiomas_auto", ["es", "ca", "en"]) or []) if i in IDIOMAS_TRANSCRIPCION]
        return v or ["es", "ca", "en"]

    def _idioma_prompt(self, fuente: str) -> str:
        """Idioma del prompt de esta fuente: el fijo, o el del último tramo transcrito (en automático, el primero de la lista al empezar)."""
        m = self.modo_idioma
        if m in IDIOMAS_TRANSCRIPCION:
            return m
        return self._idioma_usado.get(fuente) or self.idiomas_auto()[0]

    def prompt_para(self, fuente: str, idioma: str | None = None) -> str:
        """initial_prompt de esta fuente: tema (en el idioma del tramo) + vocabulario + última frase conservada de ESA fuente."""
        idioma = idioma or self._idioma_prompt(fuente)
        base = {"ca": self.prompt_ca, "en": self.prompt_en}.get(idioma) or self.prompt
        return construir_prompt(base, self.vocabulario, self._ultima.get(fuente, ""), etiqueta=ETIQUETAS.get(idioma, ETIQUETA_VOCABULARIO))

    def detectar_idioma(self, audio: np.ndarray):
        """[(idioma, probabilidad)] de `WhisperModel.detect_language` (faster-whisper ≥1.0: devuelve (idioma, p, todas)), o None si falla."""
        try:
            _, _, todas = self._modelo.detect_language(audio=audio)
            return list(todas)
        except Exception:  # noqa: BLE001  (sin detección se reutiliza el último idioma: nunca se pierde el tramo)
            return None

    def elegir_idioma(self, audio: np.ndarray, fuente: str, rapido: bool = False) -> str:
        """Idioma concreto (es | ca | en) con el que se transcribe este tramo. Fijo: sin detectar. Automático: `decidir_idioma` sobre
        `detect_language`, que se omite en fragmentos cortos (no aporta y cuesta CPU) y, en modo rápido, si el idioma de esa fuente se detectó
        hace menos de `IDIOMA_VIGENTE_S` (con cola, una detección por tramo es buena parte del cálculo)."""
        modo = self.modo_idioma
        self.ultima_deteccion_ms = None
        if modo in IDIOMAS_TRANSCRIPCION:
            self._idioma_usado[fuente] = modo
            return modo
        permitidos = self.idiomas_auto()
        dur = audio.size / 16000
        vigente = self._ultimo_idioma.get(fuente)
        if rapido and vigente in permitidos and time.monotonic() - self._t_deteccion.get(fuente, -1e9) < IDIOMA_VIGENTE_S:
            self._idioma_usado[fuente] = vigente
            return vigente
        probs = None
        if len(permitidos) > 1 and dur >= MIN_DURACION_DETECCION_S:
            ini = time.perf_counter()
            probs = self.detectar_idioma(audio)
            self.ultima_deteccion_ms = (time.perf_counter() - ini) * 1000
        idioma, motivo = decidir_idioma(probs, dur, self._ultimo_idioma.get(fuente), permitidos)
        if motivo == "detectado":
            self._ultimo_idioma[fuente] = idioma
            self._t_deteccion[fuente] = time.monotonic()
        self._idioma_usado[fuente] = idioma
        return idioma

    def _opciones_vad(self) -> dict:
        """Silero VAD de faster-whisper sobre cada fragmento (además de la segmentación por energía de audio.py): recorta silencios y
        ruido de sala antes de decodificar, que es lo que más alucinaciones evita."""
        if not self._cfg("whisper_vad", True):
            return {"vad_filter": False}
        ms = self._cfg("whisper_vad_min_silencio_ms", 500)
        return {"vad_filter": True, "vad_parameters": dict(min_silence_duration_ms=int(ms))}

    def _quiere_palabras(self) -> bool:
        return bool(self.entrega_palabras and self._cfg("whisper_palabras", True))

    def _umbral_dudosa(self) -> float:
        try:
            return float(self._cfg("palabra_dudosa_umbral", 0.5))
        except (TypeError, ValueError):
            return 0.5

    def transcribir(self, audio: np.ndarray, fuente: str, rapido: bool = False) -> str:
        """Texto de un fragmento (todo junto). Deja en `self._palabras` las palabras con su probabilidad si se pidieron."""
        segmentos = self._segmentos(audio, fuente, rapido=rapido)
        self._palabras = [w for _i, _t, p in segmentos for w in p]
        return " ".join(t for _i, t, _p in segmentos)

    def _tokens_prompt(self, prompt: str | None, hotwords: str | None) -> int | None:
        """Tokens que ocupa el prompt de la llamada (marcas de inicio + hotwords + initial_prompt, cada uno con el tope de faster-whisper), o
        None si el modelo no expone su tokenizador (dobles de test)."""
        tok = getattr(self._modelo, "hf_tokenizer", None)
        if tok is None:
            return None
        try:
            n = 5
            for texto in (hotwords, prompt):
                if texto:
                    n += min(len(tok.encode(" " + texto.strip(), add_special_tokens=False).ids), MAX_TOKENS_WHISPER // 2 - 1)
            return n
        except Exception:  # noqa: BLE001
            return None

    def _segmentos(self, audio: np.ndarray, fuente: str, rapido: bool = False) -> list[tuple[float, str, list]]:
        """[(inicio_s, texto, [(palabra, probabilidad)])] de los segmentos que pasan el filtro de calidad.
        `rapido` (hay cola): beam `BEAM_RAPIDO`, un solo reintento de temperatura, sin probabilidad por palabra y con el idioma vigente de la fuente."""
        dur = audio.size / SR_WHISPER
        self._fijar_ventana(ventana_frames(dur))   # vale para la detección de idioma y para la transcripción de este tramo
        try:
            idioma = self.elegir_idioma(audio, fuente, rapido=rapido)
            palabras = self._quiere_palabras() and not rapido
            beam = max(1, int(self.config["whisper_beam"]))
            if rapido:
                decodificacion = {"beam_size": min(beam, BEAM_RAPIDO), "temperature": TEMPERATURAS_RAPIDO}
            else:
                decodificacion = {"beam_size": beam, "temperature": TEMPERATURAS}
            prompt = self.prompt_para(fuente, idioma) or None
            hotwords = construir_hotwords(self.vocabulario) or None
            tope = tope_tokens(dur, self._tokens_prompt(prompt, hotwords))
            if tope is not None:
                decodificacion["max_new_tokens"] = tope   # corta los bucles de Whisper antes de que llenen la ventana
            resto = dict(condition_on_previous_text=False, no_speech_threshold=0.6, initial_prompt=prompt, hotwords=hotwords,
                         **self._opciones_vad(), **({"word_timestamps": True} if palabras else {}))   # ola 4: probabilidad por palabra
            try:
                segs = list(self._modelo.transcribe(audio, language=idioma, **decodificacion, **resto)[0])   # faster-whisper genera al iterar
            except ValueError as e:
                if "max_new_tokens" not in decodificacion or "max_length" not in str(e):
                    raise
                decodificacion.pop("max_new_tokens")   # prompt más largo de lo contado: sin tope, con el límite propio de Whisper
                segs = list(self._modelo.transcribe(audio, language=idioma, **decodificacion, **resto)[0])
        finally:
            self._fijar_ventana(0)
        salida = []
        for s in segs:
            if not (s.no_speech_prob < 0.7 and s.avg_logprob > -1.3):
                continue
            pal = [(w.word.strip(), w.probability) for w in (getattr(s, "words", None) or []) if w.word.strip()] if palabras else []
            salida.append((float(getattr(s, "start", 0.0) or 0.0), s.text.strip(), pal))
        return salida

    def detener(self) -> None:
        self._parar.set()
        if self._hilo:
            self._hilo.join(timeout=3)
