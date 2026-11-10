"""Detector de eco acústico por ENVOLVENTES de nivel, todo local (sin modelo, sin audio guardado).

En una sala o con altavoces el micrófono vuelve a recoger lo que suena por Reunión: «Micro» duplica a «Reunión». `eco.py` lo quita
DESPUÉS de transcribir, comparando textos. Aquí se mira ANTES de transcribir, solo con niveles de audio: si un tramo de Micro es con
alta probabilidad solo eco de Reunión, el gestor lo deja al final de la cola de transcripción (se transcribe igualmente, más tarde).
Es solo PRIORIDAD: un falso positivo retrasa unos segundos una frase real; un falso negativo deja las cosas como hoy.

Reglas (en este orden de importancia):
1. Ante la duda, NO es eco (misma filosofía que `eco.py`): el micro puede llevar a varias personas reales y una voz propia encima del
   eco es justo lo que no se puede retrasar. Por eso eco exige a la vez correlación alta, casi nada de Micro sin explicar y evidencia
   suficiente; cualquier otra cosa (poco audio, Reunión muda, desajuste, un fallo) es False.
2. El audio NUNCA se guarda: de cada bloque solo se conserva su nivel en dB (una cifra por 50 ms) y la memoria es un anillo de
   tamaño fijo (`memoria_s`): el objeto no crece con la duración de la reunión.
3. Nada lanza: `bloque` y `probable_eco` capturan cualquier fallo (el segundo devuelve False).

Idea: el eco es Reunión + retardo + atenuación + cola de reverberación. Su envolvente de nivel es la de Reunión desplazada y
suavizada. Para cada desfase candidato se compara la envolvente del tramo de Micro con la de Reunión desplazada: una persona que
habla encima, o sola, deja tramas de Micro con voz que Reunión no explica (estaba en silencio, o Micro supera lo que el eco daría).

Todo son constantes con su porqué (se fijaron midiendo con voz sintética real); no son preferencias del usuario.
"""
from __future__ import annotations

import math
import threading

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view

HOP_S = 0.05               # resolución de la envolvente: los bloques de captura duran 50 ms (frames_per_buffer = sr * 0.05)
SUELO_DB = -90.0           # nivel de silencio digital (el mismo que `audio.rms_db`)
_EPS_POT = 1e-12           # potencia mínima (−120 dB) para no tomar el logaritmo de 0; por debajo, SUELO_DB

# --- Rango de desfases ---------------------------------------------------------------------------------------------------------------
# El micro oye el eco DESPUÉS de que el sistema lo emita: latencia de salida + camino acústico + latencia de entrada, y además los
# relojes de los dos canales no están sincronizados al milisegundo. Desfase positivo = Micro retrasado respecto a Reunión.
DESFASE_MIN_TRAMAS = -4    # −0,2 s: un poco de margen por si el reloj de Micro va adelantado al de Reunión
DESFASE_MAX_TRAMAS = 20    # +1,0 s: salida + sala + entrada de un equipo normal rara vez pasa de 0,5 s; con margen
PREVIAS_TRAMAS = 20        # 1 s de historia de Reunión ANTES del primer desfase, para que la cola de reverberación ya esté formada

# --- Referencia ----------------------------------------------------------------------------------------------------------------------
COLA_RAZON = 0.25           # cola de reverberación: de la energía de cada trama de Reunión, esta fracción sigue sonando en la trama
                            # siguiente (−6 dB por trama ≈ RT60 de 0,5 s) y se SUMA a la nueva. Mejor que «máximo con el nivel anterior
                            # menos N dB» (probado: da más dispersión en un eco puro y deja pasar más voz propia)
COLA_TRAMAS = 12            # la cola se trunca a 0,6 s (0,25^12 ≈ −72 dB)
REF_ACTIVA_DB = -50.0       # Reunión «suena» por encima de esto (la voz del sistema ronda −20 dB; el dither del loopback, por debajo)

# --- Decisión ------------------------------------------------------------------------------------------------------------------------
UMBRAL_VOZ_DB = -42.0       # trama de Micro «con voz»: el mismo umbral con el que el `Segmentador` abre un tramo
MARGEN_DB = 8.0             # Micro puede superar a (referencia + ganancia) hasta esto sin dar la trama por no explicada (jitter de
                            # envolvente entre canales); más allá es voz que Reunión no tiene
MIN_TRAMAS_VOZ = 14         # 0,7 s de voz en Micro: con menos, una correlación de unas pocas tramas no demuestra nada
MIN_TRAMAS_ACTIVAS = 10     # tramas con Micro y referencia activas a la vez, para medir la ganancia del camino de eco con base
RHO_MIN = 0.75              # correlación de Pearson mínima entre las dos envolventes con el mejor desfase
DISPERSION_MAX_DB = 4.5     # desviación típica máxima de (micro - referencia) donde las dos suenan: el camino de eco tiene UNA ganancia
                            # casi constante (laxa: la reverberación de la sala se modela solo aproximadamente; lo fino lo hace la coherencia entre tramos)
EXCESO_MAX = 0.05           # fracción máxima de tramas con voz de Micro que Reunión no explica: casi ninguna
SUELO_CORR_DB = -60.0       # para correlacionar se recortan ambas envolventes aquí: el ruido de fondo no debe pesar como si fuera señal

# --- Coherencia de la ganancia entre tramos ------------------------------------------------------------------------------------------
# El camino de eco de una sala es UNO (altavoz, sala, micro): su ganancia se repite tramo tras tramo (medido: ±1,5 dB), mientras que una
# persona que habla encima de un eco infla la ganancia medida 3-6 dB. Se recuerda la ganancia de los tramos muy claros y un tramo
# dudoso solo es eco si coincide con ella; sin esa referencia (principio de la reunión) solo vale un tramo muy claro.
FUERTE_RHO = 0.8            # «tramo muy claro»: correlación alta…
FUERTE_EXCESO = 0.05        # …casi nada sin explicar…
FUERTE_DISPERSION_DB = 3.0  # …ganancia casi constante…
FUERTE_TRAMAS_VOZ = 20      # …y 1 s de voz como mínimo
HISTORIAL_MAX = 8           # ganancias recordadas (la mediana resiste a un tramo «muy claro» equivocado)
HISTORIAL_MIN = 3           # con menos, no hay referencia de ganancia
HISTORIAL_CADUCA_S = 300.0  # un volumen o una sala que cambian no deben quedar fijados: se olvida lo de hace más de 5 minutos
GANANCIA_TOL_DB = 3.0       # un eco dudoso debe estar a menos de esto de la ganancia recordada (el eco real varía ±1,5 dB)

# --- Diagnóstico (solo contadores; no cambia ninguna decisión) ---------------------------------------------------------------------------
# Cubos fijos: límites superiores (exclusivos salvo el último, abierto) de la correlación, la dispersión y el exceso. Sirven para ver, en una
# reunión real, POR QUÉ umbral se cae casi todo (RHO_MIN, DISPERSION_MAX_DB y EXCESO_MAX son los de arriba).
CUBOS_RHO = (0.3, 0.5, 0.65, 0.75)
CUBOS_DISPERSION_DB = (2.0, 3.0, 4.5, 7.0)
CUBOS_EXCESO = (0.02, 0.05, 0.1, 0.2)
RHO_PARA_DETALLE = 0.5      # la dispersión y el exceso solo se cuentan donde ya hay algo parecido a un eco
CLAVES_MOTIVO = {"sin audio": "sin_audio", "sin datos de Reunión": "sin_datos_reunion", "faltan datos de Reunión": "faltan_datos_reunion",
                 "tramo corto": "tramo_corto", "Reunión sin actividad": "reunion_sin_actividad", "correlación baja": "correlacion_baja",
                 "voz no explicada": "voz_no_explicada", "ganancia inestable": "ganancia_inestable",
                 "ganancia distinta a la de los ecos anteriores": "ganancia_distinta", "sin ganancia de referencia": "sin_ganancia_ref",
                 "error": "error"}
MOTIVOS_SIN_REFERENCIA = ("sin datos de Reunión", "faltan datos de Reunión", "Reunión sin actividad")   # Reunión no dio base suficiente
MOTIVOS_SIN_MEDIDA = ("sin audio", "sin datos de Reunión", "faltan datos de Reunión", "tramo corto", "error")   # no llegó a medirse la correlación


def _cubo(valor: float, limites: tuple) -> int:
    """Índice del cubo (0..len(limites)) de `valor`: el primero cuyo límite no alcanza. Un valor no finito cae en el primero."""
    if not math.isfinite(valor):
        return 0
    for i, lim in enumerate(limites):
        if valor < lim:
            return i
    return len(limites)


_DESFASES = np.arange(DESFASE_MIN_TRAMAS, DESFASE_MAX_TRAMAS + 1)
_N_DESFASES = int(_DESFASES.size)
_PAD = DESFASE_MAX_TRAMAS + PREVIAS_TRAMAS   # tramas de Reunión anteriores al inicio del tramo de Micro que pide `decidir_eco`


def _pot_a_db(pot: np.ndarray) -> np.ndarray:
    """FUNCIÓN PURA. Potencia media -> dB (10·log10); lo no finito o por debajo de _EPS_POT es silencio (SUELO_DB)."""
    pot = np.nan_to_num(np.asarray(pot, dtype=np.float32), nan=0.0, posinf=1.0, neginf=0.0)
    db = 10.0 * np.log10(np.maximum(pot, np.float32(_EPS_POT)))
    return np.where(pot > _EPS_POT, db, np.float32(SUELO_DB)).astype(np.float32)


def envolvente_db(x: np.ndarray, sr: int = 16000, hop_s: float = HOP_S) -> np.ndarray:
    """Nivel RMS en dB de cada trama de `hop_s` de un audio float32 mono. FUNCIÓN PURA. Audio vacío -> array vacío; silencio -> -90.
    La cola que no completa una trama se descarta."""
    x = np.asarray(x, dtype=np.float32).ravel()
    n = max(1, int(round(sr * hop_s)))
    k = x.size // n
    if k == 0:
        return np.zeros(0, np.float32)
    m = x[:k * n].reshape(k, n)
    return _pot_a_db(np.einsum("ij,ij->i", m, m) / np.float32(n))


def _con_cola(db: np.ndarray) -> np.ndarray:
    """FUNCIÓN PURA. Envolvente de referencia con la cola de reverberación: la energía de cada trama más COLA_RAZON^k de la de k tramas
    antes (convolución con una exponencial truncada), otra vez en dB."""
    if db.size == 0:
        return db
    pot = np.power(10.0, db.astype(np.float64) / 10.0)
    nucleo = COLA_RAZON ** np.arange(COLA_TRAMAS)
    con_cola = np.convolve(pot, nucleo)[:db.size]
    return np.maximum(10.0 * np.log10(np.maximum(con_cola, 1e-12)), SUELO_DB).astype(np.float32)


def longitud_reunion_necesaria(n_tramas_micro: int) -> int:
    """FUNCIÓN PURA. Tramas de Reunión que necesita `decidir_eco` para un tramo de Micro de `n_tramas_micro` tramas."""
    return n_tramas_micro + _PAD - DESFASE_MIN_TRAMAS


def decidir_eco(micro_db: np.ndarray, reunion_db: np.ndarray) -> dict:
    """FUNCIÓN PURA. Decide si el tramo de Micro es solo eco de Reunión a partir de dos envolventes (dB, paso HOP_S).

    `micro_db`: envolvente del tramo de Micro, n tramas; la trama j empieza en t0 + j·HOP_S.
    `reunion_db`: envolvente de Reunión (silencio donde no hubo bloques) con `longitud_reunion_necesaria(n)` tramas; el elemento i es el
    nivel en el instante t0 + (i - PREVIAS_TRAMAS - DESFASE_MAX_TRAMAS)·HOP_S. Si trae más, se usan las primeras.
    Devuelve {"eco", "motivo", "rho", "exceso", "desfase_s", "ganancia_db", "dispersion_db", "fuerte"}: «eco» es la regla sobre este
    tramo SOLO; `EcoAudio` la completa con la coherencia de la ganancia entre tramos (`_resolver`)."""
    res = {"eco": False, "motivo": "", "rho": 0.0, "exceso": 1.0, "desfase_s": 0.0, "ganancia_db": 0.0, "dispersion_db": 0.0, "fuerte": False}
    micro = np.nan_to_num(np.asarray(micro_db, dtype=np.float32).ravel(), nan=SUELO_DB, posinf=0.0, neginf=SUELO_DB)
    n = micro.size
    voz = micro > UMBRAL_VOZ_DB
    n_voz = int(voz.sum())
    if n_voz < MIN_TRAMAS_VOZ:
        res["motivo"] = "tramo corto"
        return res
    largo = longitud_reunion_necesaria(n)
    reunion = np.nan_to_num(np.asarray(reunion_db, dtype=np.float32).ravel(), nan=SUELO_DB, posinf=0.0, neginf=SUELO_DB)
    if reunion.size < largo:
        res["motivo"] = "faltan datos de Reunión"
        return res
    ref_total = _con_cola(reunion[:largo])
    # referencia para el desfase d: ref[j] = ref_total[j - d + _PAD]; una vista por ventanas y un índice, sin bucle por desfase
    ref = sliding_window_view(ref_total, n)[_PAD - _DESFASES]            # (desfases, n)
    activa = ref > REF_ACTIVA_DB
    ambas = activa & voz[None, :]
    n_amb = ambas.sum(axis=1)
    # ganancia del camino de eco = mediana de (micro - referencia) donde las dos suenan
    dif = np.where(ambas, micro[None, :] - ref, np.inf)
    dif.sort(axis=1)
    pos = np.clip((n_amb - 1) // 2, 0, n - 1)
    gan = np.where(n_amb > 0, dif[np.arange(_N_DESFASES), pos], 0.0)
    # exceso: fracción de tramas con voz de Micro que la referencia no explica
    no_explicada = voz[None, :] & (~activa | (micro[None, :] > ref + gan[:, None] + MARGEN_DB))
    exceso = no_explicada.sum(axis=1) / n_voz
    # dispersión de (micro - referencia) donde las dos suenan
    dd = np.where(ambas, micro[None, :] - ref, 0.0)
    nn = np.maximum(n_amb, 1)
    media = dd.sum(axis=1) / nn
    disp = np.sqrt(np.maximum((np.where(ambas, (dd - media[:, None]) ** 2, 0.0)).sum(axis=1) / nn, 0.0))
    # correlación de Pearson entre las envolventes recortadas
    a = np.maximum(micro, SUELO_CORR_DB)[None, :]
    b = np.maximum(ref, SUELO_CORR_DB)
    a = a - a.mean(axis=1, keepdims=True)
    b = b - b.mean(axis=1, keepdims=True)
    den = np.sqrt((a * a).sum(axis=1) * (b * b).sum(axis=1))
    rho = np.where(den > 1e-6, (a * b).sum(axis=1) / np.maximum(den, 1e-6), 0.0)
    rho = np.where(n_amb >= MIN_TRAMAS_ACTIVAS, rho, -1.0)
    k = int(np.argmax(rho))
    res.update(rho=float(rho[k]), exceso=float(exceso[k]), desfase_s=float(_DESFASES[k] * HOP_S), ganancia_db=float(gan[k]), dispersion_db=float(disp[k]))
    if n_amb[k] < MIN_TRAMAS_ACTIVAS:
        res["motivo"] = "Reunión sin actividad"
    elif rho[k] < RHO_MIN:
        res["motivo"] = "correlación baja"
    elif exceso[k] > EXCESO_MAX:
        res["motivo"] = "voz no explicada"
    elif disp[k] > DISPERSION_MAX_DB:
        res["motivo"] = "ganancia inestable"
    else:
        res["eco"] = True
        res["motivo"] = "eco"
        res["fuerte"] = bool(rho[k] >= FUERTE_RHO and exceso[k] <= FUERTE_EXCESO and disp[k] <= FUERTE_DISPERSION_DB
                             and n_voz >= FUERTE_TRAMAS_VOZ)
    return res


class EcoAudio:
    """Solo guarda NIVELES (dB) de los últimos `memoria_s` segundos de Reunión: nunca audio.

    Anillo de tamaño fijo indexado por el número de trama absoluto (instante / HOP_S). Lo que no llegó (el loopback no entrega nada
    cuando no suena nada) o ya caducó vale silencio."""

    HUECO_TOLERADO = 2     # tramas que se rellenan si faltan entre dos bloques (jitter de reloj, no silencio real); más es silencio
    MEMORIA_MIN_S = 5.0    # por debajo no cabría ni un tramo con sus desfases

    def __init__(self, memoria_s: float = 90.0):
        try:
            memoria_s = float(memoria_s)
        except (TypeError, ValueError):
            memoria_s = 90.0
        if not math.isfinite(memoria_s):
            memoria_s = 90.0
        self.memoria_s = max(memoria_s, self.MEMORIA_MIN_S)
        self._n = int(math.ceil(self.memoria_s / HOP_S)) + 1
        self._cerrojo = threading.Lock()
        self.ultimo: dict = {}
        self._anillo = np.full(self._n, SUELO_DB, np.float32)
        self._cabeza = None   # número de la última trama escrita (None = ninguna)
        self._ganancias: list = []   # [(t0, ganancia_db)] de los tramos «muy claros»; solo números
        self._poner_a_cero()

    def _poner_a_cero(self) -> None:
        """Contadores de diagnóstico de la reunión (solo enteros)."""
        self._diag = {"eval": 0, "eco": 0, "fuertes": 0, "sin_ref": 0, "motivos": {},
                      "rho": [0] * (len(CUBOS_RHO) + 1), "disp": [0] * (len(CUBOS_DISPERSION_DB) + 1), "exceso": [0] * (len(CUBOS_EXCESO) + 1)}

    def reiniciar(self) -> None:
        with self._cerrojo:
            self._anillo.fill(SUELO_DB)
            self._cabeza = None
            self._ganancias = []
            self.ultimo = {}
            self._poner_a_cero()

    def diagnostico(self) -> dict:
        """Contadores acumulados desde `reiniciar` (una reunión): tramos evaluados, marcados como eco, «fuertes», sin referencia suficiente de
        Reunión, motivos por los que se descartó cada tramo no marcado (clave → tramos) e histogramas de la correlación máxima (`rho`), y, con
        rho ≥ 0,5, de la dispersión en dB (`disp`) y del exceso. Solo enteros: una copia, sin audio ni texto. Nunca lanza."""
        try:
            with self._cerrojo:
                d = self._diag
                return {"eval": int(d["eval"]), "eco": int(d["eco"]), "fuertes": int(d["fuertes"]), "sin_ref": int(d["sin_ref"]),
                        "motivos": {k: int(v) for k, v in d["motivos"].items()}, "rho": [int(v) for v in d["rho"]],
                        "disp": [int(v) for v in d["disp"]], "exceso": [int(v) for v in d["exceso"]]}
        except Exception:  # noqa: BLE001
            return {"eval": 0, "eco": 0, "fuertes": 0, "sin_ref": 0, "motivos": {}, "rho": [0] * 5, "disp": [0] * 5, "exceso": [0] * 5}

    def _contar(self, res: dict) -> None:
        """Suma un tramo evaluado a los contadores. Nunca lanza ni cambia `res`."""
        try:
            with self._cerrojo:
                d = self._diag
                d["eval"] += 1
                motivo = str(res.get("motivo", ""))
                if res.get("eco"):
                    d["eco"] += 1
                else:
                    clave = CLAVES_MOTIVO.get(motivo, "otro")
                    d["motivos"][clave] = d["motivos"].get(clave, 0) + 1
                if res.get("fuerte"):
                    d["fuertes"] += 1
                if motivo in MOTIVOS_SIN_REFERENCIA:
                    d["sin_ref"] += 1
                if motivo in MOTIVOS_SIN_MEDIDA:
                    return
                rho = float(res.get("rho", 0.0))
                d["rho"][_cubo(rho, CUBOS_RHO)] += 1
                if rho >= RHO_PARA_DETALLE:
                    d["disp"][_cubo(float(res.get("dispersion_db", 0.0)), CUBOS_DISPERSION_DB)] += 1
                    d["exceso"][_cubo(float(res.get("exceso", 0.0)), CUBOS_EXCESO)] += 1
        except Exception:  # noqa: BLE001
            return

    # -- escritura (hilo de captura de cada canal) --------------------------------------------------------------------------------
    def bloque(self, fuente: str, x: np.ndarray, t: float) -> None:
        """Lo llama el hilo de captura de CADA canal con cada bloque (float32 mono 16 kHz) y `t` = instante en que TERMINA. Solo cuenta
        fuente == "reunion". Nunca lanza."""
        try:
            if fuente != "reunion":
                return
            x = np.asarray(x, dtype=np.float32).ravel()
            if x.size == 0 or not math.isfinite(t):
                return
            if x.size >= int(round(16000 * HOP_S)):
                niveles = envolvente_db(x)
            else:   # bloque más corto que una trama: una sola cifra con lo que hay
                niveles = _pot_a_db(np.array([float(np.dot(x, x)) / x.size], np.float32))
            fin = int(round(t / HOP_S)) - 1                       # número de la trama que termina en t
            ini = fin - niveles.size + 1
            if fin < 0:
                return
            with self._cerrojo:
                self._escribir(ini, niveles)
        except Exception:  # noqa: BLE001
            return

    def _poner(self, desde: int, hasta: int, valor: float) -> None:
        if hasta < desde:
            return
        if hasta - desde + 1 >= self._n:
            self._anillo.fill(valor)
        else:
            self._anillo[np.arange(desde, hasta + 1) % self._n] = valor

    def _escribir(self, ini: int, niveles: np.ndarray) -> None:
        """Escribe `niveles` desde la trama `ini`. Llamar con el cerrojo tomado."""
        if ini < 0:
            niveles, ini = niveles[-ini:], 0
        cab = self._cabeza
        if cab is not None and ini <= cab - self._n:                # lo anterior a la memoria no se guarda
            recorte = cab - self._n + 1 - ini
            niveles, ini = niveles[recorte:], ini + recorte
        if niveles.size == 0:
            return
        if niveles.size > self._n:
            niveles, ini = niveles[-self._n:], ini + niveles.size - self._n
        fin = ini + niveles.size - 1
        if cab is None:
            self._anillo.fill(SUELO_DB)
        elif ini > cab + 1:
            falta = ini - cab - 1
            # hueco pequeño: jitter de reloj, se rellena con el primer nivel nuevo; grande: el loopback no entregó nada = silencio
            self._poner(cab + 1, ini - 1, float(niveles[0]) if falta <= self.HUECO_TOLERADO else SUELO_DB)
        idx = np.arange(ini, fin + 1) % self._n
        if cab is not None and ini <= cab:                           # solapa con lo ya escrito (jitter): se queda el mayor
            niveles = np.where(np.arange(ini, fin + 1) <= cab, np.maximum(self._anillo[idx], niveles), niveles)
        self._anillo[idx] = niveles
        if cab is None or fin > cab:
            self._cabeza = fin

    # -- lectura (hilo de captura del micro) --------------------------------------------------------------------------------------
    def _niveles_reunion(self, primera: int, cuantas: int) -> np.ndarray:
        """Niveles de las tramas [primera, primera+cuantas), silencio donde no hay dato. Llamar con el cerrojo tomado."""
        out = np.full(cuantas, SUELO_DB, np.float32)
        if self._cabeza is None:
            return out
        absolutas = np.arange(primera, primera + cuantas)
        validas = (absolutas <= self._cabeza) & (absolutas > self._cabeza - self._n) & (absolutas >= 0)
        if validas.any():
            out[validas] = self._anillo[absolutas[validas] % self._n]
        return out

    def _anotar(self, eco: bool, motivo: str) -> None:
        self.ultimo = {"eco": eco, "motivo": motivo, "rho": 0.0, "exceso": 1.0, "desfase_s": 0.0}
        self._contar(self.ultimo)

    def _resolver(self, res: dict, t0: float) -> dict:
        """Completa la decisión de un tramo con la ganancia recordada de los tramos muy claros (ver HISTORIAL_*)."""
        with self._cerrojo:
            recientes = sorted(g for t, g in self._ganancias if abs(t0 - t) <= HISTORIAL_CADUCA_S)
            if res.get("eco"):
                if len(recientes) >= HISTORIAL_MIN:
                    if abs(res["ganancia_db"] - recientes[len(recientes) // 2]) > GANANCIA_TOL_DB:
                        res.update(eco=False, motivo="ganancia distinta a la de los ecos anteriores")
                elif not res.get("fuerte"):
                    res.update(eco=False, motivo="sin ganancia de referencia")
            if res.get("fuerte"):
                self._ganancias.append((t0, res["ganancia_db"]))
                del self._ganancias[:-HISTORIAL_MAX]
        return res

    def probable_eco(self, audio: np.ndarray, t0: float) -> bool:
        """True si el tramo de Micro `audio` (float32 mono 16 kHz), cuya primera muestra es del instante `t0`, es con alta probabilidad
        SOLO eco de lo que sonó por Reunión. Nunca lanza (ante cualquier fallo, False). Deja el diagnóstico en `ultimo`."""
        try:
            micro = envolvente_db(audio)
            if micro.size == 0 or not math.isfinite(t0):
                self._anotar(False, "sin audio")
                return False
            base = int(round(t0 / HOP_S))
            with self._cerrojo:
                sin_datos = self._cabeza is None
                reunion = self._niveles_reunion(base - _PAD, longitud_reunion_necesaria(micro.size))
            if sin_datos:
                self._anotar(False, "sin datos de Reunión")
                return False
            self.ultimo = self._resolver(decidir_eco(micro, reunion), t0)
            self._contar(self.ultimo)
            return bool(self.ultimo["eco"])
        except Exception:  # noqa: BLE001
            self._anotar(False, "error")
            return False
