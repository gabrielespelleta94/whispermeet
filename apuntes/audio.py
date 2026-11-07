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
    x = x.astype(np.float32)
    if x.max(initial=0) > 1.5 or x.min(initial=0) < -1.5:
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


class Segmentador:
    """Corta el flujo en enunciados: cierra tras `silencio_s` de silencio o a `max_s`."""

    def __init__(self, reloj: Callable[[], float], umbral_db: float = -42.0, silencio_s: float = 0.7,
                 max_s: float = 25.0, min_voz_s: float = 0.35, preroll_s: float = 0.25):
        self.reloj, self.umbral, self.silencio_s = reloj, umbral_db, silencio_s
        self.max_s, self.min_voz_s, self.preroll_s = max_s, min_voz_s, preroll_s
        self._resto = np.zeros(0, np.float32)
        self._pre: list[np.ndarray] = []
        self._buf: list[np.ndarray] = []
        self._en_voz = False
        self._silencio = 0.0
        self._voz = 0.0
        self._t_inicio = 0.0

    def reiniciar(self) -> None:
        self.__init__(self.reloj, self.umbral, self.silencio_s, self.max_s, self.min_voz_s, self.preroll_s)

    def _cerrar(self, salida: list):
        if self._buf and self._voz >= self.min_voz_s:
            salida.append((np.concatenate(self._buf), self._t_inicio))
        self._buf, self._en_voz, self._silencio, self._voz = [], False, 0.0, 0.0

    def alimentar(self, x: np.ndarray) -> list[tuple[np.ndarray, float]]:
        """Devuelve enunciados completos [(audio, t_inicio_s)]."""
        salida: list = []
        x = np.concatenate([self._resto, x]) if self._resto.size else x
        n = x.size // FRAME
        ahora = self.reloj()
        for i in range(n):
            f = x[i * FRAME:(i + 1) * FRAME]
            voz = rms_db(f) > self.umbral
            if not self._en_voz:
                self._pre.append(f)
                self._pre = self._pre[-int(self.preroll_s / 0.03):]
                if voz:
                    self._en_voz = True
                    self._buf = list(self._pre)
                    self._pre = []
                    self._voz = 0.03
                    self._silencio = 0.0
                    self._t_inicio = max(0.0, ahora - (n - i) * 0.03 - len(self._buf) * 0.03 + 0.03)
            else:
                self._buf.append(f)
                if voz:
                    self._voz += 0.03
                    self._silencio = 0.0
                else:
                    self._silencio += 0.03
                dur = len(self._buf) * 0.03
                if self._silencio >= self.silencio_s or dur >= self.max_s:
                    self._cerrar(salida)
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
        while not self._parar.is_set():
            try:
                datos = q.get(timeout=0.3)
            except queue.Empty:
                for audio, t in seg.vaciar_si_inactivo():
                    self.on_enunciado(fuente, audio, t)
                continue
            if self.pausada:
                seg.reiniciar()
                continue
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
