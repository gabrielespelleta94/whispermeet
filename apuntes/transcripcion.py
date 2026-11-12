"""Transcripción con faster-whisper (CPU, int8). Los buffers de audio se descartan al transcribir."""
from __future__ import annotations

import gc
import os
import re
import threading
import time
from collections import deque
from difflib import SequenceMatcher

import numpy as np

from .config import APP_DIR, dialecto_efectivo
from .motor_nube import VOZ_MIN_S, MotorNube
from .nube import wav_pcm16
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

# Prompt de Whisper (initial_prompt): admite ~224 tokens. Aproximación por caracteres (español con siglas, ~2,4 caracteres por token).
# El prompt se paga en CADA tramo (medido con `small`, 6 s por tramo, 3 pasadas: 480 caracteres → 3,7×; 240 → 4,3× (+17 %, parecido del texto 98,7 %,
# ningún término hablado perdido); 120 → 5,4×; sin prompt, 5,9×), así que se recorta: 240 en modo normal y 120 en modo rápido.
MAX_PROMPT_CHARS = 240
MAX_PROMPT_CHARS_RAPIDO = 120   # modo rápido: solo tema y primeros términos, sin continuidad
MAX_PALABRAS_CONTINUIDAD = 30
MIN_PALABRAS_HUECO = 6          # una continuidad que hay que acortar solo entra si en el hueco que deja el vocabulario caben al menos estas palabras
RESERVA_CONTINUIDAD = 60         # caracteres que el vocabulario deja siempre libres para la continuidad (si la hay)
MIN_PALABRAS_CONTINUIDAD = 6    # si la última frase es muy corta («Vale.») se le suma la anterior hasta este mínimo
ETIQUETA_VOCABULARIO = "Términos:"
ETIQUETA_VOCABULARIO_CA = "Termes:"
ETIQUETA_VOCABULARIO_EN = "Terms:"
# initial_prompt del tema, coherente con el idioma que se transcribe: un prompt en español sesga a Whisper hacia el español.
PROMPT_TEMA = {"es": "Reunión de trabajo: {}.", "ca": "Reunió de treball: {}.", "en": "Work meeting: {}."}
ETIQUETAS = {"es": ETIQUETA_VOCABULARIO, "ca": ETIQUETA_VOCABULARIO_CA, "en": ETIQUETA_VOCABULARIO_EN}
IDIOMAS_TRANSCRIPCION = ("es", "ca", "en")


# Sin `hotwords` de faster-whisper: cada tramo es una sola ventana y el vocabulario ya va en el initial_prompt, así que duplicaban el
# prompt y costaban cálculo en cada tramo (medido: ver CLAUDE.md).


def hilos_efectivos(config, nucleos: int | None = None) -> int:
    """Hilos de cálculo que usa Whisper. FUNCIÓN PURA (salvo contar los núcleos si no se dan). Con `whisper_hilos_auto` (por defecto):
    min(whisper_hilos, max(2, núcleos // 2)). Motivo: con prioridad alta hay que dejar la mitad de los núcleos a la videollamada. Con False,
    `whisper_hilos` tal cual."""
    def cfg(clave, defecto):
        try:
            return config[clave]
        except (KeyError, TypeError):
            return defecto
    pedidos = int(cfg("whisper_hilos", 6))
    if not cfg("whisper_hilos_auto", True) or pedidos <= 0:
        return pedidos
    nucleos = int(nucleos) if nucleos else (os.cpu_count() or 2)
    return min(pedidos, max(2, nucleos // 2))


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
# Los tramos se transcriben de uno en uno: cada texto es de SU tramo y lleva su minuto (`t_inicio`). Cuál se toma después lo decide la cola
# con prioridades de más abajo; por eso el texto puede llegar a la sesión fuera de orden, y quien lo enseña lo ordena por su minuto.
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
TOPE_TOKENS_SEGURO = 120  # sin tokenizador para contar el prompt (peor caso ≈100 tokens), por encima de esto no se pasa tope
# COLA CON PRIORIDADES. Un solo hilo y un solo modelo atienden los dos canales y un tramo no se interrumpe a medias: lo único que se decide
# es cuál se toma después. La regla busca que lo que se lee en directo sea lo último que se ha dicho, aunque la máquina no dé para todo:
#   1. NORMALES: lo que acaba de llegar. Primero Reunión (lo que dicen los demás) y después el Micro (lo que ha dicho uno mismo es lo que
#      menos urge leer); dentro de cada canal, en orden de llegada.
#   2. REZAGADOS: un normal que lleva más de RETRASO_TOPE_S esperando ya no sirve en directo: deja de frenar a los que vienen detrás y se
#      transcribe en los huecos (pausas, final de la reunión), del más reciente al más antiguo y siempre en modo rápido.
#   3. APLAZADOS: los tramos que `encolar(..., aplazar=True)` marca (un Micro que probablemente solo es eco de Reunión). Solo cuando no
#      queda nada de lo anterior. NUNCA se adelantan a un normal: una versión anterior los atendía antes que los normales al cumplir 20 s
#      de espera y, con eco continuo, el hilo solo transcribía ecos mientras Reunión se retrasaba un segundo por cada segundo de reunión.
# Las dos colas de baja prioridad tienen un presupuesto de audio. Lo que no cabe se descarta empezando por lo más antiguo y SE CUENTA, con
# su minuto (`tomar_descartes`): un rezagado descartado es audio perdido (`perdidos_s`); un aplazado descartado, eco sin transcribir.
RETRASO_TOPE_S = 30.0     # espera a partir de la cual un tramo normal pasa a rezagado: el retraso que se ve en directo no crece más allá
REZAGADO_TOPE_S = 480.0   # audio rezagado que se guarda para después; a la velocidad habitual cabe en la espera del cierre (600 s)
APLAZADO_TOPE_S = 120.0   # audio aplazado (eco probable) que se guarda; lo que pase de aquí se descarta, el más antiguo primero
ESPERA_HILO_S = 0.3       # sin nada que transcribir, cada cuánto mira el hilo si debe parar
NORMAL, REZAGADO, APLAZADO = "normal", "rezagado", "aplazado"   # clase de un tramo en el momento de tomarlo
FUENTE_PRIORITARIA = "reunion"


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
    """`base` (tema) + «Términos: a, b.» + continuidad, en `tope` caracteres y por este orden de prioridad: el tema, los términos del vocabulario
    (los primeros mandan: no se salta a uno más corto) y la continuidad con el hueco que quede (se acorta por el principio: queda lo último
    dicho; si hay que acortarla y quedan menos de `MIN_PALABRAS_HUECO` palabras, no entra). Si hay continuidad, el vocabulario deja libres
    `RESERVA_CONTINUIDAD` caracteres (o lo que ella mida, si es menos) para que entre siempre algo de ella; sin continuidad (modo rápido) los
    términos usan todo el hueco. Sin vocabulario ni continuidad, es `base`."""
    base, cont = (base or "").strip(), " ".join((continuidad or "").split())
    if len(base) > tope:
        base = base[:tope].rsplit(" ", 1)[0] if " " in base[:tope] else base[:tope]
    libre = tope - len(base) - (1 if base else 0) - len(etiqueta) - 1   # -1: el punto final
    if cont:
        libre -= min(len(cont) + 1, RESERVA_CONTINUIDAD)   # hueco garantizado para la continuidad: el vocabulario no lo ocupa
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
        hueco = tope - len(" ".join(p for p in partes if p)) - 1
        entera = cont.split()
        palabras = list(entera)
        while palabras and len(" ".join(palabras)) > hueco:
            palabras.pop(0)
        if palabras and (len(palabras) == len(entera) or len(palabras) >= MIN_PALABRAS_HUECO):   # un cabo suelto de 2-3 palabras no sirve; la frase entera, sí
            partes.append(" ".join(palabras))
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


# Transcripción en la nube (apuntes/motor_nube.py, apuntes/nube.py). En la nube «rápido» solo acorta las pistas: no hay beam ni probabilidad por palabra.
MAX_KEYWORDS = 30           # términos del vocabulario que viajan como `keywords[]` (gpt-transcribe)
MAX_KEYWORDS_RAPIDO = 10
REINTENTO_CARGA_LOCAL_S = 60.0   # si falla la carga perezosa del modelo de respaldo, no se vuelve a intentar antes de esto


def timestamps_voz(audio: np.ndarray, min_silencio_ms: int) -> list[dict] | None:
    """Tramos con voz del Silero VAD de faster-whisper ([{start, end}] en muestras), sin cargar Whisper. None si el VAD no se puede usar:
    entonces se sube el trozo entero."""
    try:
        from faster_whisper.vad import VadOptions, get_speech_timestamps
        return list(get_speech_timestamps(audio, VadOptions(min_silence_duration_ms=int(min_silencio_ms)), sampling_rate=SR_WHISPER))
    except Exception:  # noqa: BLE001  (sin VAD, o un fallo suyo: el trozo entero)
        return None


class Transcriptor:
    tope_retraso_s: float | None = RETRASO_TOPE_S   # None = orden de llegada estricto, sin prioridad entre fuentes ni rezagados (el dictado)
    forzar_local = False                            # True = nunca la nube (el dictado del contexto, que se hace antes de la reunión)

    def __init__(self, config, on_texto, *, clave_nube=None, permitir_nube=None):
        """`on_texto(fuente, t_inicio, texto)` se llama desde el hilo del transcriptor. `clave_nube()`: la clave de la nube o None;
        `permitir_nube()`: False si la nube está vetada ahora (modo solo local)."""
        self.config, self.on_texto = config, on_texto
        self.nube = None if self.forzar_local else MotorNube(config, clave_nube or (lambda: None), permitir_nube or (lambda: True))
        self._ultimo_motor: str | None = None   # quién transcribió el último trozo: local | nube
        self._resuelto_por: str | None = None   # lo mismo, pero solo del trozo en curso (lo pone `_segmentos`)
        self.error_respaldo = ""                # no se pudo cargar el modelo local de respaldo
        self._carga_local_fallida_en: float | None = None
        self.tramos_nube = 0
        self.tramos_local = 0
        self.estado = "sin_cargar"  # sin_cargar | cargando | listo | error
        self.error = ""
        self._modelo = None
        self._solo_en_disco = False                 # True mientras `_cargar_solo_en_disco` llama a `cargar_modelo` (`local_files_only=True`)
        self._cerrojo_modelo = threading.Lock()     # una sola carga del modelo a la vez (precarga del respaldo y carga perezosa)
        # Las tres colas guardan (fuente, audio, t_inicio, instante de encolado) en orden de llegada y solo se tocan con `_lock` cogido.
        self._normales: deque = deque()    # lo que toca transcribir ya
        self._rezagados: deque = deque()   # normales que superaron `tope_retraso_s`: se atienden del final (el más reciente) al principio
        self._aplazados: deque = deque()   # baja prioridad (eco probable)
        self._pendiente_s = 0.0     # TODO el audio pendiente o en curso: normal + rezagado + aplazado
        self._rezagado_s = 0.0      # la parte rezagada de `_pendiente_s`
        self._aplazado_s = 0.0      # la parte aplazada de `_pendiente_s`
        self._en_curso = None       # (clase, fuente, instante de encolado, segundos de audio) del tramo que se está transcribiendo
        self._descartes: deque = deque(maxlen=1000)   # (fuente, t_inicio, segundos, motivo) de lo descartado por presupuesto
        self.tramos_aplazados = 0   # tramos encolados como aplazados en esta ejecución (diagnóstico)
        self.tramos_rezagados = 0   # tramos normales que pasaron a rezagados (diagnóstico)
        self.rezagado_total_s = 0.0   # audio que pasó a rezagado en esta ejecución, se transcribiera después o no
        self.eco_descartado_s = 0.0   # audio aplazado descartado sin transcribir por no caber en su presupuesto
        self._lock = threading.Lock()
        self._hay = threading.Condition(self._lock)   # despierta al hilo cuando entra un tramo o hay que parar
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
        self.latencia_s = None   # del último tramo normal: segundos entre que se cerró (se encoló) y que su texto quedó entregado
        self.latencias: dict[str, float] = {}       # lo mismo, por fuente (yo / reunion)
        self.latencia_max: dict[str, float] = {}    # la mayor de esta ejecución, por fuente
        self.audio_total_s = 0.0     # audio transcrito en esta ejecución y lo que costó calcularlo: la velocidad media, sin el ruido
        self.calculo_total_s = 0.0   # de un tramo suelto
        self.cpu_total_s = 0.0       # CPU del proceso (`process_time`) durante esos mismos cálculos: cpu_total_s / calculo_total_s = núcleos que consiguió Whisper
        self.audio_recibido_s = 0.0  # audio que ha entrado en la cola en esta ejecución (la demanda; `audio_total_s` es lo ya calculado)
        self.prompt_chars_total = 0  # caracteres del initial_prompt de todas las llamadas y cuántas fueron: el prompt medio
        self.prompt_llamadas = 0
        self.hilos: int | None = None   # hilos con los que se cargó el modelo (`hilos_efectivos`); None = aún sin cargar
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
    def aplazado_s(self) -> float:
        """Audio aplazado (de baja prioridad) pendiente o en curso; `pendiente_s` lo incluye."""
        return max(0.0, self._aplazado_s)

    @property
    def rezagado_s(self) -> float:
        """Audio que no llegó a tiempo para el directo y espera un hueco (o está en curso); `pendiente_s` lo incluye."""
        with self._lock:
            self._ordenar(time.monotonic())   # un normal que ya pasó del tope cuenta aquí aunque nadie haya encolado ni preguntado el retraso
            return max(0.0, self._rezagado_s)

    @property
    def retraso_s(self) -> float:
        """Cuánto lleva esperando el tramo normal más antiguo, contando el que está en curso (0 si no hay ninguno): lo que va la transcripción
        por detrás del directo. `pendiente_s` suma el audio de los dos canales; esto es tiempo de reloj. No cuentan los rezagados (ya se dan
        por tardíos: `rezagado_s`) ni los aplazados (un eco no es retraso)."""
        return self.retraso_de(None)

    @property
    def retraso_reunion_s(self) -> float:
        """`retraso_s` solo de Reunión: lo que van por detrás del directo las palabras de los demás."""
        return self.retraso_de(FUENTE_PRIORITARIA)

    def retraso_de(self, fuente: str | None) -> float:
        """`retraso_s` de una sola fuente (yo / reunion); None = la que más retraso lleve."""
        with self._lock:
            ahora = time.monotonic()
            self._ordenar(ahora)   # lo que ya pasa del tope deja de contar aquí y pasa a `rezagado_s`: la cifra y la cola dicen lo mismo
            viejo = next((x[3] for x in self._normales if fuente is None or x[0] == fuente), None)
            c = self._en_curso
            if c and c[0] == NORMAL and c[2] is not None and (fuente is None or c[1] == fuente):
                viejo = c[2] if viejo is None else min(viejo, c[2])
            return max(0.0, ahora - viejo) if viejo is not None else 0.0

    def tomar_descartes(self) -> list[tuple[str, float, float, str]]:
        """Lo descartado por presupuesto desde la última llamada: (fuente, t_inicio, segundos, motivo), motivo `saturacion` (un rezagado:
        audio perdido) o `eco` (un aplazado). Quien lo recoge lo deja escrito con su minuto: nada se pierde en silencio."""
        with self._lock:
            d = list(self._descartes)
            self._descartes.clear()
        return d

    def iniciar(self) -> None:
        self._parar.clear()
        self._hilo = threading.Thread(target=self._bucle, daemon=True, name="transcriptor")
        self._hilo.start()

    def cargar_modelo(self):
        from faster_whisper import WhisperModel
        MODELOS_DIR.mkdir(parents=True, exist_ok=True)
        self.hilos = hilos_efectivos(self.config)   # num_workers se queda en 1 (el valor por defecto): un solo tramo a la vez
        extra = {"local_files_only": True} if self._solo_en_disco else {}   # el respaldo de la nube NUNCA descarga el modelo en plena reunión
        return WhisperModel(self.config["whisper_modelo"], device="cpu", compute_type="int8",
                            cpu_threads=self.hilos, download_root=str(MODELOS_DIR), **extra)

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

    def encolar(self, fuente: str, audio: np.ndarray, t_inicio: float, aplazar: bool = False) -> None:
        """`aplazar`: tramo de baja prioridad (probable eco): se transcribe solo cuando no queda ningún otro esperando."""
        dur = audio.size / SR_WHISPER
        if self.estado == "error":   # sin modelo no hay quien vacíe la cola: no se acumula audio en memoria, se cuenta como perdido
            self.perdidos_s += dur
            return
        with self._hay:   # las colas y los contadores cambian juntos: con dos hilos de captura, el mismo orden en todos
            ahora = time.monotonic()
            self._pendiente_s += dur
            self.audio_recibido_s += dur
            if aplazar:
                self._aplazado_s += dur
                self.tramos_aplazados += 1
                self._aplazados.append((fuente, audio, t_inicio, ahora))
            else:
                self._normales.append((fuente, audio, t_inicio, ahora))
            self._ordenar(ahora)   # también aquí: si el hilo se queda atascado en un tramo, las colas no crecen sin límite en memoria
            self._hay.notify()

    def vacio(self) -> bool:
        with self._lock:
            return not (self._normales or self._rezagados or self._aplazados) and self._pendiente_s <= 0.01

    def _ordenar(self, ahora: float) -> None:
        """Con `_lock` cogido: pasa a rezagados los normales que ya no llegan a tiempo y recorta las colas de baja prioridad a su presupuesto."""
        tope = self.tope_retraso_s
        if tope is not None:
            while self._normales and ahora - self._normales[0][3] > tope:
                item = self._normales.popleft()
                dur = item[1].size / SR_WHISPER
                self._rezagados.append(item)
                self._rezagado_s += dur
                self.rezagado_total_s += dur
                self.tramos_rezagados += 1
        # el tramo en curso ya no está en su cola: cuenta en `_rezagado_s`/`_aplazado_s` pero no contra el presupuesto (no se puede descartar)
        while self._rezagados and self._rezagado_s - self._en_vuelo_s(REZAGADO) > REZAGADO_TOPE_S:
            self._descartar(self._rezagados.popleft(), "saturacion")
        while self._aplazados and self._aplazado_s - self._en_vuelo_s(APLAZADO) > APLAZADO_TOPE_S:
            self._descartar(self._aplazados.popleft(), "eco")

    def _en_vuelo_s(self, clase: str) -> float:
        """Con `_lock` cogido: segundos del tramo en curso si es de esa clase, 0 si no."""
        c = self._en_curso
        return c[3] if c is not None and c[0] == clase else 0.0

    def _descartar(self, item, motivo: str) -> None:
        """Con `_lock` cogido: un tramo que no cabe en su presupuesto deja la cola sin transcribirse, y queda apuntado."""
        fuente, audio, t0, _instante = item
        dur = audio.size / SR_WHISPER
        self._pendiente_s -= dur
        if motivo == "eco":
            self._aplazado_s -= dur
            self.eco_descartado_s += dur
        else:
            self._rezagado_s -= dur
            self.perdidos_s += dur
            if self.estado != "error":   # con el modelo caído el fallo real (el que se muestra) no se tapa con la saturación
                self.ultimo_fallo = "saturación"
        self._descartes.append((fuente, t0, dur, motivo))

    def _tomar(self):
        """Con `_lock` cogido: saca de las colas el próximo tramo, (fuente, audio, t0, clase, instante), o devuelve None si no hay.
        El orden es el de COLA CON PRIORIDADES: normales (Reunión antes que Micro), rezagados del más reciente al más antiguo y aplazados."""
        self._ordenar(time.monotonic())
        if self._normales:
            i = 0
            if self.tope_retraso_s is not None:
                i = next((k for k, x in enumerate(self._normales) if x[0] == FUENTE_PRIORITARIA), 0)
            item, clase = self._normales[i], NORMAL
            del self._normales[i]
        elif self._rezagados:
            item, clase = self._rezagados.pop(), REZAGADO
        elif self._aplazados:
            item, clase = self._aplazados.popleft(), APLAZADO
        else:
            return None
        fuente, audio, t0, instante = item
        self._en_curso = (clase, fuente, instante, audio.size / SR_WHISPER)
        return fuente, audio, t0, clase, instante

    def _siguiente(self):
        """Próximo tramo a transcribir, (fuente, audio, t0, clase, instante), o None si no hay (tras esperar un poco a que entre alguno)."""
        with self._hay:
            tramo = None   # tras `detener()` no se toma nada: nadie usaría el texto y el tramo seguiría ocupando el hilo
            if not self._parar.is_set():
                tramo = self._tomar()
                if tramo is None:
                    self._hay.wait(ESPERA_HILO_S)
                    if not self._parar.is_set():
                        tramo = self._tomar()
            if tramo is None:
                self.alcance = False
            return tramo

    def _cargas(self, clase: str, dur: float) -> tuple[float, float]:
        """Con `_lock` cogido y el tramo de `clase` y `dur` s ya tomado: (en_cola_s, normal_detras_s). `en_cola_s` es lo que espera detrás y decide
        el modo rápido: a un normal no le cuenta el audio aplazado (los ecos no bajan la calidad del útil), pero el rezagado sí cuenta (es texto
        útil que falta, y mientras lo haya se trabaja en rápido para recuperarlo antes). `normal_detras_s` es solo el audio NORMAL que espera:
        el tramo en curso ya sale de las cuentas de su clase al acabar, así que solo se resta si es normal; nunca negativo."""
        en_cola_s = self._pendiente_s - dur - (0.0 if clase == APLAZADO else self._aplazado_s)
        normal_detras_s = self._pendiente_s - self._aplazado_s - self._rezagado_s - (dur if clase == NORMAL else 0.0)
        return en_cola_s, max(0.0, normal_detras_s)

    def _motor_previsto(self) -> str:
        """local | nube: el motor que se usaría ahora mismo (la `decidir()` de este momento)."""
        return "local" if self.nube is None else self.nube.decidir().motor

    @property
    def motor_activo(self) -> str:
        """Quién transcribió el último trozo; antes del primero, el que se usaría."""
        return self._ultimo_motor or self._motor_previsto()

    def _asegurar_local(self) -> None:
        """Carga perezosa de Whisper cuando el motor local hace falta y aún no está (respaldo de la nube, o cambio de motor a mitad de reunión).
        Si falla no pone `estado = "error"`: la nube puede seguir. Reintenta como mucho cada `REINTENTO_CARGA_LOCAL_S` y relanza."""
        if self._modelo is not None:
            return
        with self._cerrojo_modelo:   # la precarga y la carga perezosa no duplican el modelo
            if self._modelo is not None:
                return
            ahora = time.monotonic()
            if self._carga_local_fallida_en is not None and ahora - self._carga_local_fallida_en < REINTENTO_CARGA_LOCAL_S:
                raise RuntimeError(self.error_respaldo)
            self._n_tarea += 1
            ident = self._n_tarea
            self._avisar("inicio", ident, etiqueta="carga del modelo (respaldo)")
            ini = time.perf_counter()
            try:
                self._modelo = self._cargar_solo_en_disco()
                self._instalar_ventana(self._modelo)
                self.error_respaldo, self._carga_local_fallida_en = "", None
                self._avisar("fin", ident, ok=True, ms=int((time.perf_counter() - ini) * 1000))
            except Exception:  # noqa: BLE001
                self._modelo = None
                self.error_respaldo, self._carga_local_fallida_en = "No se pudo cargar el modelo local de respaldo.", ahora
                self._avisar("fin", ident, ok=False, error=self.error_respaldo, ms=int((time.perf_counter() - ini) * 1000))
                if self.nube is not None:
                    self.nube.anotar_sin_modelo()
                raise

    def _cargar_solo_en_disco(self):
        """`cargar_modelo()` con `local_files_only=True`: si el modelo no está en disco falla en vez de descargarlo (cientos de MB en plena reunión)."""
        self._solo_en_disco = True
        try:
            return self.cargar_modelo()
        finally:
            self._solo_en_disco = False

    def _precargar_respaldo(self) -> None:
        """Con el motor en la nube: carga el modelo local en un hilo aparte para que el respaldo esté listo sin parar el transcriptor. Solo desde disco
        y sin avisos si no está (la pantalla de requisitos ya lo dice). Nunca lanza."""
        try:
            with self._cerrojo_modelo:
                if self._modelo is not None or self._parar.is_set():
                    return
                self._modelo = self._cargar_solo_en_disco()
                self._instalar_ventana(self._modelo)
                self.error_respaldo, self._carga_local_fallida_en = "", None
        except Exception:  # noqa: BLE001  (sin modelo en disco: el aviso llegará si de verdad hace falta el respaldo)
            self._modelo = None

    def _bucle(self) -> None:
        if self._motor_previsto() == "nube":   # con la nube no se carga Whisper al empezar: el hilo no espera; el respaldo se precarga aparte (o en `_asegurar_local`)
            self.estado = "listo"
            threading.Thread(target=self._precargar_respaldo, daemon=True, name="precarga-whisper").start()
        else:
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
            tramo = self._siguiente()
            if tramo is None:
                continue
            fuente, audio, t0, clase, instante = tramo
            dur = audio.size / SR_WHISPER
            with self._lock:
                en_cola_s, normal_detras_s = self._cargas(clase, dur)
            rapido = clase == REZAGADO or en_cola_s >= COLA_ALCANCE_S
            self.alcance = normal_detras_s >= COLA_ALCANCE_S   # «alcanzando el directo» habla del texto en directo: ni un eco ni un atraso ya aceptado lo encienden
            if rapido:
                self.tramos_rapidos += 1
            self._procesar(fuente, audio, t0, rapido, clase, instante)
            del audio
            if self.vacio():
                self.alcance = False

    def _procesar(self, fuente: str, audio: np.ndarray, t0: float, rapido: bool, clase: str = NORMAL, instante: float | None = None) -> None:
        """Transcribe un tramo y entrega su texto. Si la pasada falla se repite UNA vez en rápido; si vuelve a fallar, el tramo cuenta como perdido.
        `clase` e `instante` (cuándo se encoló) vienen de `_siguiente`: deciden qué contadores se tocan al acabar."""
        dur = audio.size / SR_WHISPER
        self._n_tarea += 1
        ident = self._n_tarea
        etiqueta = {(NORMAL, True): "tramo · rápido", (APLAZADO, False): "eco probable", (APLAZADO, True): "eco probable · rápido",
                    (REZAGADO, False): "tramo atrasado", (REZAGADO, True): "tramo atrasado · rápido"}.get((clase, rapido))
        self._avisar("inicio", ident, fuente=fuente, audio_s=dur, **({"etiqueta": etiqueta} if etiqueta else {}))
        cpu0, ini = time.process_time(), time.perf_counter()
        self._resuelto_por = None
        try:
            try:
                segmentos = self._segmentos(audio, fuente, rapido=rapido)
            except Exception:  # noqa: BLE001  (sin memoria, un tramo que el modelo no digiere…): un reintento más barato antes de darlo por perdido
                if self._parar.is_set():
                    raise
                self.reintentos += 1
                gc.collect()
                segmentos = self._segmentos(audio, fuente, rapido=True, solo_local=True)   # la nube ya tuvo su turno: este reintento es de Whisper
            calc = time.perf_counter() - ini
            cpu = time.process_time() - cpu0   # de todo el proceso (también hilos ajenos al cálculo): una cota alta de lo que consiguió Whisper
            if calc > 0 and self._resuelto_por != "nube":   # la velocidad habla de Whisper local: un trozo de la nube no cuenta
                self.velocidad_x = dur / calc
            if self._resuelto_por != "nube":   # la velocidad media y los núcleos hablan de Whisper: un trozo de la nube no cuenta
                self.audio_total_s += dur
                self.calculo_total_s += calc
                self.cpu_total_s += cpu
            # un rezagado se transcribe fuera de su sitio: su última frase no sirve de continuidad al tramo que venga después
            texto = self._entregar(fuente, t0, " ".join(t for _i, t, _p in segmentos), [w for _i, _t, p in segmentos for w in p],
                                   continuidad=clase != REZAGADO)
            self._avisar("fin", ident, ok=True, ms=int(calc * 1000), palabras=len(texto.split()), motor=self._resuelto_por)
        except Exception as e:  # noqa: BLE001
            self.error = f"Fallo al transcribir un tramo: {e}"
            with self._lock:   # `perdidos_s` también lo sube `_descartar`, desde los hilos de captura
                self.perdidos_s += dur
                self.ultimo_fallo = type(e).__name__
            self._avisar("fin", ident, ok=False, error=self.error, ms=int((time.perf_counter() - ini) * 1000))
        finally:
            with self._lock:   # el buffer lo descarta quien llama
                self._pendiente_s -= dur
                self._en_curso = None
                if clase == APLAZADO:
                    self._aplazado_s -= dur   # la latencia mide solo los tramos normales: ni un eco ni un rezagado son «el directo»
                elif clase == REZAGADO:
                    self._rezagado_s -= dur
                elif instante is not None:
                    lat = round(max(0.0, time.monotonic() - instante), 2)
                    self.latencia_s = self.latencias[fuente] = lat
                    self.latencia_max[fuente] = max(lat, self.latencia_max.get(fuente, 0.0))

    def _entregar(self, fuente: str, t0: float, texto: str, palabras_whisper: list, continuidad: bool = True) -> str:
        """Filtra, corrige y entrega el texto de un tramo. Devuelve el texto entregado ("" si se descartó)."""
        texto = filtrar_texto(texto)
        if texto and es_copia_del_prompt(texto, self.prompt_para(fuente), self.vocabulario, self._ultima.get(fuente, "")):
            texto = ""   # el prompt se ha colado en el resultado: ni se emite ni sirve de continuidad
        if not texto or self._parar.is_set():   # tras `detener` no se entrega nada: la sesión ya está cerrada (o es otra)
            return ""
        texto = corregir_glosario(texto, self.vocabulario, self.vocabulario_curado)   # mayúsculas y acentos del glosario, antes de entrar en la sesión
        if continuidad:
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

    def prompt_para(self, fuente: str, idioma: str | None = None, rapido: bool = False) -> str:
        """initial_prompt de esta fuente: tema (en el idioma del tramo) + vocabulario + última frase conservada de ESA fuente, en este orden y con el
        hueco que quede. En modo rápido, solo tema y primeros términos (`MAX_PROMPT_CHARS_RAPIDO`, sin continuidad)."""
        idioma = idioma or self._idioma_prompt(fuente)
        base = {"ca": self.prompt_ca, "en": self.prompt_en}.get(idioma) or self.prompt
        return construir_prompt(base, self.vocabulario, "" if rapido else self._ultima.get(fuente, ""),
                                tope=MAX_PROMPT_CHARS_RAPIDO if rapido else MAX_PROMPT_CHARS,
                                etiqueta=ETIQUETAS.get(idioma, ETIQUETA_VOCABULARIO))

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

    def _tokens_prompt(self, prompt: str | None) -> int | None:
        """Tokens que ocupa el prompt de la llamada (marcas de inicio + initial_prompt, con el tope de faster-whisper), o
        None si el modelo no expone su tokenizador (dobles de test)."""
        tok = getattr(self._modelo, "hf_tokenizer", None)
        if tok is None:
            return None
        try:
            n = 5
            if prompt:
                n += min(len(tok.encode(" " + prompt.strip(), add_special_tokens=False).ids), MAX_TOKENS_WHISPER // 2 - 1)
            return n
        except Exception:  # noqa: BLE001
            return None

    def _segmentos(self, audio: np.ndarray, fuente: str, rapido: bool = False, solo_local: bool = False) -> list[tuple[float, str, list]]:
        """[(inicio_s, texto, [(palabra, probabilidad)])] de los segmentos que pasan el filtro de calidad. Aquí se decide el motor DE ESTE TROZO
        (no al empezar la reunión): la nube si `MotorNube.decidir()` lo permite y, ante cualquier fallo suyo, Whisper local para ese mismo trozo.
        `solo_local`: sin nube (el reintento de `_procesar`)."""
        if solo_local or self.forzar_local or self.nube is None:
            return self._resolver_local(audio, fuente, rapido)
        d = self.nube.decidir()
        if d.motor == "nube":
            try:
                segs = self._segmentos_nube(audio, fuente, rapido, d.sonda)
                self._ultimo_motor = self._resuelto_por = "nube"
                self.tramos_nube += 1
                return segs
            except Exception:  # noqa: BLE001  (NubeFallo o cualquier otra cosa: el texto del trozo no se pierde, lo hace Whisper local)
                if self._parar.is_set():
                    raise
        if d.motivo != "config":   # motor configurado en la nube y trozo resuelto en local: respaldo
            self.nube.anotar_respaldo(audio.size / SR_WHISPER)
        return self._resolver_local(audio, fuente, rapido)

    def _resolver_local(self, audio: np.ndarray, fuente: str, rapido: bool) -> list[tuple[float, str, list]]:
        segs = self._segmentos_local(audio, fuente, rapido=rapido)
        self._ultimo_motor = self._resuelto_por = "local"
        self.tramos_local += 1
        return segs

    def _voz_para_nube(self, audio: np.ndarray) -> np.ndarray:
        """Solo se sube la voz: el trozo con los silencios quitados (Silero VAD de faster-whisper; `whisper_vad` y `whisper_vad_min_silencio_ms`).
        Si el VAD no está o falla, el trozo entero."""
        if not self._cfg("whisper_vad", True):
            return audio
        tramos = timestamps_voz(audio, int(self._cfg("whisper_vad_min_silencio_ms", 500)))
        if tramos is None:
            return audio
        if not tramos:
            return audio[:0]
        return np.concatenate([audio[int(t["start"]):int(t["end"])] for t in tramos])

    def _idiomas_de_partida(self, fuente: str) -> list[str]:
        """Idiomas que se ofrecen a la nube: el fijo, o `idiomas_auto` empezando por el último usado en esa fuente."""
        m = self.modo_idioma
        if m in IDIOMAS_TRANSCRIPCION:
            return [m]
        lista = self.idiomas_auto()
        ultimo = self._ultimo_idioma.get(fuente) or self._idioma_usado.get(fuente)
        return ([ultimo] + [i for i in lista if i != ultimo]) if ultimo in lista else list(lista)

    def _segmentos_nube(self, audio: np.ndarray, fuente: str, rapido: bool, sonda: bool) -> list[tuple[float, str, list]]:
        """El trozo por la nube. Lanza `NubeFallo` (o cualquier excepción) si hay que caer a local; quien llama lo resuelve.
        El plazo total del trozo (`PLAZO_TROZO_S`) nace aquí y lo comparten todos sus intentos."""
        hasta = self.nube.nuevo_plazo()
        voz = self._voz_para_nube(audio)
        voz_s = voz.size / SR_WHISPER
        if voz_s < VOZ_MIN_S:   # sin voz suficiente no se envía nada: texto vacío
            self.nube.anotar_silencio()
            return []
        auto = self.modo_idioma not in IDIOMAS_TRANSCRIPCION
        idiomas = self._idiomas_de_partida(fuente)
        idioma_p = self._idioma_prompt(fuente)
        base = {"ca": self.prompt_ca, "en": self.prompt_en}.get(idioma_p) or self.prompt
        dialecto = dialecto_efectivo(str(self._cfg("nube_modelo", "gpt-transcribe")), str(self._cfg("nube_dialecto", "auto")))
        if dialecto == "gpt-transcribe":
            tope = MAX_PROMPT_CHARS_RAPIDO if rapido else MAX_PROMPT_CHARS
            prompt = construir_prompt(base, (), "" if rapido else self._ultima.get(fuente, ""), tope=tope)
            claves = list(self.vocabulario)[:MAX_KEYWORDS_RAPIDO if rapido else MAX_KEYWORDS]
        else:
            prompt = self.prompt_para(fuente, idioma_p, rapido=rapido)
            claves = []
        self.prompt_chars_total += len(prompt)
        self.prompt_llamadas += 1
        wav = wav_pcm16(voz)
        res = self.nube.transcribir(wav, voz_s, idiomas=idiomas, prompt=prompt, palabras_clave=claves, rapido=rapido, sonda=sonda, hasta=hasta)
        codigo = (res.idioma or "").split("-")[0]
        if auto and codigo:
            if codigo not in self.idiomas_auto():
                # Un idioma fuera de la lista nunca se acepta: se repite UNA vez con el de partida de la fuente (la regla de siempre: no se acaba en otro idioma)
                partida = idiomas[0]
                self.nube.anotar_idioma_repetido()
                # Sin permiso o sin plazo, `transcribir` lanza `NubeFallo`: lo ya obtenido tiene un idioma NO admisible (por eso se repite), así que el trozo va a local
                res = self.nube.transcribir(wav, voz_s, idiomas=[partida], prompt=prompt, palabras_clave=claves, rapido=rapido, sonda=False,
                                            hasta=hasta, repeticion=True)
                codigo = partida
            self._idioma_usado[fuente] = self._ultimo_idioma[fuente] = codigo
        if res.segmentos is not None:   # dialecto clásico: el mismo filtro de calidad que el local
            return [(float(s.get("start", 0.0) or 0.0), s["text"], []) for s in res.segmentos
                    if s.get("text") and s.get("no_speech_prob", 0.0) < 0.7 and s.get("avg_logprob", 0.0) > -1.3]
        return [(0.0, res.texto, [])] if res.texto else []

    def _segmentos_local(self, audio: np.ndarray, fuente: str, rapido: bool = False) -> list[tuple[float, str, list]]:
        """El cuerpo de siempre: Whisper local. `rapido` (hay cola): beam `BEAM_RAPIDO`, un solo reintento de temperatura, sin probabilidad por
        palabra y con el idioma vigente de la fuente."""
        self._asegurar_local()
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
            prompt = self.prompt_para(fuente, idioma, rapido=rapido) or None
            self.prompt_chars_total += len(prompt or "")
            self.prompt_llamadas += 1
            tope = tope_tokens(dur, self._tokens_prompt(prompt))
            if tope is not None:
                decodificacion["max_new_tokens"] = tope   # corta los bucles de Whisper antes de que llenen la ventana
            resto = dict(condition_on_previous_text=False, no_speech_threshold=0.6, initial_prompt=prompt,
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
        with self._hay:
            self._hay.notify_all()   # si el hilo espera un tramo, que vea ya que debe parar
        if self._hilo:
            self._hilo.join(timeout=3)
