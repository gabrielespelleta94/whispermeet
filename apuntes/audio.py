"""Captura de audio (micro = «Micro», audio del sistema = «Reunión») y segmentación por silencios.

El audio NUNCA se escribe en disco: solo buffers en memoria que se pasan al transcriptor y se
descartan. Este módulo no abre ningún fichero.
"""
from __future__ import annotations

import queue
import threading
import time
from typing import Callable

import numpy as np

SR = 16000
FRAME = int(SR * 0.03)  # 30 ms


def rms_db(x: np.ndarray) -> float:
    if x.size == 0:
        return -90.0
    r = float(np.sqrt(np.mean(np.square(x, dtype=np.float64))))
    return 20.0 * np.log10(r) if r > 1e-6 else -90.0


def a_16k_mono(x: np.ndarray, sr: int, canales: int) -> np.ndarray:
    """int16/float intercalado -> float32 mono 16 kHz."""
    entero = np.issubdtype(x.dtype, np.integer)
    x = x.astype(np.float32)
    # La captura entrega SIEMPRE int16: se escala siempre, también un audio casi mudo de ±1 LSB (el dither del
    # loopback), que con el criterio de amplitud quedaba en ≈0 dB y se tomaba por voz continua. En float se
    # conserva la heurística: valores fuera de ±1,5 se entienden como escala int16.
    if entero or x.max(initial=0) > 1.5 or x.min(initial=0) < -1.5:
        x = x / 32768.0
    if canales > 1:
        n = (x.size // canales) * canales
        x = x[:n].reshape(-1, canales).mean(axis=1)
    if sr == SR:
        return x
    if sr % SR == 0:
        k = sr // SR
        n = (x.size // k) * k
        return x[:n].reshape(-1, k).mean(axis=1)
    destino = int(x.size * SR / sr)
    if destino <= 0:
        return np.zeros(0, np.float32)
    return np.interp(np.linspace(0, x.size - 1, destino), np.arange(x.size), x).astype(np.float32)


# Silencio exigido para cerrar según lo que dura ya el tramo, como fracción de `silencio_s` (así un
# `silencio_s` distinto escala toda la tabla). Cada fila: (duración mínima del tramo en s, fracción).
# Un texto no sale en pantalla hasta que cierra su enunciado: cuanto más largo es el tramo, menos pausa
# basta para cortarlo (en un monólogo con pausas cortas las palabras esperaban 11 s de media). Con el
# `silencio_s` de 0,7 s los escalones son 0,7 / 0,45 / 0,3 / 0,2 s. El diálogo, con pausas de ≥1 s y
# turnos cortos, no llega a estos escalones y se corta igual que antes.
ESCALONES_SILENCIO = (
    (0.0, 1.0),        # < 6 s: pausa normal, para no partir frases con una respiración
    (6.0, 9 / 14),     # 6-10 s: 0,45 s
    (10.0, 3 / 7),     # 10-14 s: 0,30 s
    (14.0, 2 / 7),     # >= 14 s: 0,20 s (cualquier micropausa; el tope duro está cerca)
)
VENTANA_VALLE_S = 2.0   # al llegar al tope se corta en la trama más silenciosa de los últimos 2 s
_EPS = 1e-9


class Segmentador:
    """Corta el flujo en enunciados: cierra tras un silencio que se acorta con la duración del tramo
    (`ESCALONES_SILENCIO`) o al llegar a `max_s`, donde corta en el valle de los últimos 2 s y el resto
    sigue como principio del tramo siguiente."""

    def __init__(self, reloj: Callable[[], float], umbral_db: float = -42.0, silencio_s: float = 0.7,
                 max_s: float = 18.0, min_voz_s: float = 0.35, preroll_s: float = 0.25):
        self.reloj, self.umbral, self.silencio_s = reloj, umbral_db, silencio_s
        self.max_s, self.min_voz_s, self.preroll_s = max_s, min_voz_s, preroll_s
        self._resto = np.zeros(0, np.float32)
        self._pre: list[np.ndarray] = []
        self._buf: list[np.ndarray] = []
        self._db: list[float] = []   # energía de cada trama de `_buf`, en paralelo
        self._en_voz = False
        self._silencio = 0.0
        self._voz = 0.0
        self._t_inicio = 0.0

    def reiniciar(self) -> None:
        self.__init__(self.reloj, self.umbral, self.silencio_s, self.max_s, self.min_voz_s, self.preroll_s)

    def _cerrar(self, salida: list):
        if self._buf and self._voz >= self.min_voz_s:
            salida.append((np.concatenate(self._buf), self._t_inicio))
        self._buf, self._db, self._en_voz, self._silencio, self._voz = [], [], False, 0.0, 0.0

    def _silencio_exigido(self, dur: float) -> float:
        frac = 1.0
        for desde, f in ESCALONES_SILENCIO:
            if dur + _EPS >= desde:
                frac = f
        return self.silencio_s * frac

    def _cortar_en_valle(self, salida: list):
        """Tope duro: emite hasta la trama de menor energía de los últimos 2 s y deja el resto como tramo abierto."""
        n_ult = min(len(self._buf), int(VENTANA_VALLE_S / 0.03))
        desde = len(self._buf) - n_ult
        ventana = self._db[desde:]
        k = desde + (len(ventana) - 1 - int(np.argmin(ventana[::-1])))   # a igualdad, la última
        resto, resto_db = self._buf[k + 1:], self._db[k + 1:]
        t_resto = self._t_inicio + (k + 1) * 0.03
        if self._voz >= self.min_voz_s:
            salida.append((np.concatenate(self._buf[:k + 1]), self._t_inicio))
        self._buf, self._db, self._t_inicio = resto, resto_db, t_resto
        self._voz = sum(1 for d in resto_db if d > self.umbral) * 0.03
        sil = 0
        for d in reversed(resto_db):
            if d > self.umbral:
                break
            sil += 1
        self._silencio = sil * 0.03

    def alimentar(self, x: np.ndarray) -> list[tuple[np.ndarray, float]]:
        """Devuelve enunciados completos [(audio, t_inicio_s)]."""
        salida: list = []
        x = np.concatenate([self._resto, x]) if self._resto.size else x
        n = x.size // FRAME
        ahora = self.reloj()
        for i in range(n):
            f = x[i * FRAME:(i + 1) * FRAME]
            db = rms_db(f)
            voz = db > self.umbral
            if not self._en_voz:
                self._pre.append(f)
                self._pre = self._pre[-int(self.preroll_s / 0.03):]
                if voz:
                    self._en_voz = True
                    self._buf = list(self._pre)
                    self._db = [rms_db(g) for g in self._buf[:-1]] + [db]
                    self._pre = []
                    self._voz = 0.03
                    self._silencio = 0.0
                    self._t_inicio = max(0.0, ahora - (n - i) * 0.03 - len(self._buf) * 0.03 + 0.03)
            else:
                self._buf.append(f)
                self._db.append(db)
                if voz:
                    self._voz += 0.03
                    self._silencio = 0.0
                else:
                    self._silencio += 0.03
                dur = len(self._buf) * 0.03
                if self._silencio + _EPS >= self._silencio_exigido(dur):
                    self._cerrar(salida)
                elif dur + _EPS >= self.max_s:
                    self._cortar_en_valle(salida)
        self._resto = x[n * FRAME:]
        return salida

    def vaciar_si_inactivo(self) -> list[tuple[np.ndarray, float]]:
        """Llamar cuando no llegan datos: cierra un enunciado a medias."""
        salida: list = []
        if self._en_voz:
            self._cerrar(salida)
        return salida


def listar_dispositivos() -> dict:
    """Solo enumera; no abre ningún stream."""
    try:
        import pyaudiowpatch as pa
    except Exception as e:  # noqa: BLE001
        return {"error": f"pyaudiowpatch no disponible: {e}", "entradas": [], "salidas": [],
                "mic_defecto": None, "sistema_defecto": None}
    p = pa.PyAudio()
    try:
        wasapi = p.get_host_api_info_by_type(pa.paWASAPI)
        entradas, salidas = [], []
        for i in range(p.get_device_count()):
            d = p.get_device_info_by_index(i)
            if d["hostApi"] != wasapi["index"]:
                continue
            fila = {"indice": d["index"], "nombre": d["name"], "canales": d["maxInputChannels"],
                    "frecuencia": int(d["defaultSampleRate"])}
            if d.get("isLoopbackDevice"):
                salidas.append(fila)
            elif d["maxInputChannels"] > 0:
                entradas.append(fila)
        defecto_mic = wasapi.get("defaultInputDevice")
        defecto_sis = None
        try:
            sp = p.get_device_info_by_index(wasapi["defaultOutputDevice"])
            for lb in p.get_loopback_device_info_generator():
                if sp["name"] in lb["name"]:
                    defecto_sis = lb["index"]
                    break
        except Exception:  # noqa: BLE001
            pass
        return {"error": "", "entradas": entradas, "salidas": salidas,
                "mic_defecto": defecto_mic, "sistema_defecto": defecto_sis}
    finally:
        p.terminate()


def elegir_dispositivo(guardado, validos: list[dict], defecto):
    """Windows renumera al conectar unos cascos: un índice guardado que ya no captura pasa al de por defecto."""
    return guardado if guardado in {f["indice"] for f in validos} else defecto


class Captura:
    """Dos flujos independientes. `on_enunciado(fuente, audio, t_inicio)`, `on_nivel(fuente, db)`."""

    def __init__(self, reloj, on_enunciado, on_nivel, idx_mic=None, idx_sistema=None, fuentes=("yo", "reunion"), vaciar_al_parar=False):
        """`fuentes`: qué se captura (el dictado del contexto abre solo el micro: ("yo",)). `vaciar_al_parar`: al detener, el enunciado a
        medias se entrega en vez de perderse (el dictado lo usa para no comerse la última frase)."""
        self.fuentes, self.vaciar_al_parar = tuple(fuentes), vaciar_al_parar
        self.reloj, self.on_enunciado, self.on_nivel = reloj, on_enunciado, on_nivel
        self.idx = {"yo": idx_mic, "reunion": idx_sistema}
        self.pausada = False
        self._parar = threading.Event()
        self._hilos: list[threading.Thread] = []
        self._p = None
        self._streams = []
        self.errores: dict[str, str] = {}

    def iniciar(self) -> None:
        import pyaudiowpatch as pa
        self._pa = pa
        self._p = pa.PyAudio()
        info = listar_dispositivos()
        elegidos = {
            "yo": elegir_dispositivo(self.idx["yo"], info["entradas"], info["mic_defecto"]),
            "reunion": elegir_dispositivo(self.idx["reunion"], info["salidas"], info["sistema_defecto"]),
        }
        for fuente, indice in elegidos.items():
            if fuente not in self.fuentes:
                continue
            if indice is None:
                self.errores[fuente] = "no se encontró dispositivo"
                continue
            try:
                self._abrir(fuente, int(indice))
            except Exception as e:  # noqa: BLE001
                self.errores[fuente] = str(e)

    def _abrir(self, fuente: str, indice: int) -> None:
        pa = self._pa
        d = self._p.get_device_info_by_index(indice)
        sr, ch = int(d["defaultSampleRate"]), max(1, int(d["maxInputChannels"]))
        q: queue.Queue = queue.Queue(maxsize=200)

        def cb(datos, frames, tiempo, estado):  # hilo de audio: mínimo trabajo
            try:
                q.put_nowait(datos)
            except queue.Full:
                pass
            return (None, pa.paContinue)

        stream = self._p.open(format=pa.paInt16, channels=ch, rate=sr, input=True,
                              input_device_index=indice, frames_per_buffer=int(sr * 0.05), stream_callback=cb)
        self._streams.append(stream)
        h = threading.Thread(target=self._trabajo, args=(fuente, q, sr, ch), daemon=True, name=f"captura-{fuente}")
        h.start()
        self._hilos.append(h)

    def _trabajo(self, fuente: str, q: queue.Queue, sr: int, ch: int) -> None:
        seg = Segmentador(self.reloj)
        ultimo_nivel = 0.0
        en_pausa = False
        while not self._parar.is_set():
            try:
                datos = q.get(timeout=0.3)
            except queue.Empty:
                for audio, t in seg.vaciar_si_inactivo():
                    self.on_enunciado(fuente, audio, t)
                continue
            if self.pausada:
                if not en_pausa:   # al ENTRAR en pausa el enunciado a medias se entrega; luego el audio se descarta
                    en_pausa = True
                    for audio, t in seg.vaciar_si_inactivo():
                        self.on_enunciado(fuente, audio, t)
                seg.reiniciar()
                continue
            en_pausa = False
            x = a_16k_mono(np.frombuffer(datos, dtype=np.int16), sr, ch)
            ahora = time.monotonic()
            if ahora - ultimo_nivel > 0.1:
                self.on_nivel(fuente, rms_db(x))
                ultimo_nivel = ahora
            for audio, t in seg.alimentar(x):
                self.on_enunciado(fuente, audio, t)
            del x, datos
        if self.vaciar_al_parar:   # el hilo termina aquí: lo que quedaba a medias en el segmentador se entrega antes de salir
            for audio, t in seg.vaciar_si_inactivo():
                self.on_enunciado(fuente, audio, t)

    def detener(self) -> None:
        self._parar.set()
        for s in self._streams:
            try:
                s.stop_stream()
                s.close()
            except Exception:  # noqa: BLE001
                pass
        for h in self._hilos:
            h.join(timeout=2)
        if self._p:
            self._p.terminate()
