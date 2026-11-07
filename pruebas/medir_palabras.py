"""Mide el sobrecoste de `word_timestamps` (probabilidad por palabra, ola 4) en CPU con el modelo de Whisper YA descargado (nunca descarga nada).

Uso:
    .venv\\Scripts\\python.exe pruebas\\medir_palabras.py [--audio FICHERO.wav] [--repeticiones 3] [--modelo small]

Sin `--audio` sintetiza ~40 s de voz española ficticia con la voz de Windows (pyttsx3, SAPI) en una carpeta temporal que se borra al terminar (esto es solo la
prueba: la app nunca escribe audio a disco). Transcribe el mismo audio con y sin `word_timestamps` con los mismos parámetros que `transcripcion.py`
(beam, VAD, temperaturas, hilos de la configuración) y da el tiempo medio de cada una, el factor de tiempo real y el sobrecoste.
"""
from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
import time
import wave
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from apuntes.config import Config  # noqa: E402
from apuntes.transcripcion import MODELOS_DIR  # noqa: E402

TEXTO = ("Buenos días a todos. Empezamos el seguimiento del proyecto de reservas. Hoy toca revisar el calendario del piloto, "
         "las peticiones nuevas del cliente y los riesgos que quedaron abiertos. Ana se encarga de enviar la tarifa nueva antes del viernes. "
         "Luis propone adelantar el piloto al dos de diciembre, pero Marta dice que el calendario de disponibilidad no estará terminado. "
         "Quedamos en que el piloto sigue el veinte de enero y que revisamos el presupuesto en la próxima reunión. "
         "La integración con el sistema de pagos queda fuera de la primera fase.")


def sintetizar(carpeta: Path) -> Path:
    import pyttsx3
    motor = pyttsx3.init()
    for v in motor.getProperty("voices"):
        if "es-ES" in (v.languages or []) or "Spanish" in v.name:
            motor.setProperty("voice", v.id)
            break
    motor.setProperty("rate", 170)
    ruta = carpeta / "voz.wav"
    motor.save_to_file(TEXTO, str(ruta))
    motor.runAndWait()
    return ruta


def cargar(ruta: Path) -> np.ndarray:
    with wave.open(str(ruta), "rb") as w:
        sr, canales, ancho = w.getframerate(), w.getnchannels(), w.getsampwidth()
        crudo = w.readframes(w.getnframes())
    x = np.frombuffer(crudo, dtype={1: np.int8, 2: np.int16, 4: np.int32}[ancho]).astype(np.float32)
    x /= float(2 ** (8 * ancho - 1))
    if canales > 1:
        x = x.reshape(-1, canales).mean(axis=1)
    if sr != 16000:
        n = int(len(x) * 16000 / sr)
        x = np.interp(np.linspace(0, len(x) - 1, n), np.arange(len(x)), x).astype(np.float32)
    return x


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--audio")
    ap.add_argument("--repeticiones", type=int, default=3)
    ap.add_argument("--modelo", default=None)
    ap.add_argument("--hilos", type=int, default=None, help="por defecto, los de la configuración")
    a = ap.parse_args()
    cfg = Config()
    tmp = Path(tempfile.mkdtemp(prefix="medir_palabras_"))
    try:
        ruta = Path(a.audio) if a.audio else sintetizar(tmp)
        audio = cargar(ruta)
        dur = len(audio) / 16000
        from faster_whisper import WhisperModel
        modelo = WhisperModel(a.modelo or cfg["whisper_modelo"], device="cpu", compute_type="int8", cpu_threads=a.hilos or int(cfg["whisper_hilos"]),
                              download_root=str(MODELOS_DIR), local_files_only=True)

        def pasada(palabras: bool):
            kw = dict(language="es", beam_size=int(cfg["whisper_beam"]), condition_on_previous_text=False, temperature=(0.0, 0.2, 0.4), no_speech_threshold=0.6,
                      vad_filter=True, vad_parameters=dict(min_silence_duration_ms=int(cfg["whisper_vad_min_silencio_ms"])))
            if palabras:
                kw["word_timestamps"] = True
            t0 = time.perf_counter()
            segs = list(modelo.transcribe(audio, **kw)[0])
            return time.perf_counter() - t0, segs
        pasada(False)   # calentamiento
        res = {False: [], True: []}
        for i in range(a.repeticiones):
            for p in ((False, True) if i % 2 == 0 else (True, False)):   # se alterna el orden: la carga de la máquina no favorece siempre a la misma
                res[p].append(pasada(p))
        sin, con = (min(t for t, _ in res[p]) for p in (False, True))   # el mínimo es lo menos contaminado por otros procesos
        medios = [sum(t for t, _ in res[p]) / a.repeticiones for p in (False, True)]
        print("tiempos sin: " + ", ".join(f"{t:.1f}" for t, _ in res[False]) + " · con: " + ", ".join(f"{t:.1f}" for t, _ in res[True]))
        pal = [w for s in res[True][-1][1] for w in (s.words or [])]
        dud = [w for w in pal if w.probability < cfg["palabra_dudosa_umbral"]]
        print(f"audio: {dur:.1f} s · modelo {a.modelo or cfg['whisper_modelo']} · hilos {a.hilos or cfg['whisper_hilos']} · {a.repeticiones} repeticiones")
        print(f"sin word_timestamps: {sin:.2f} s (mínimo; media {medios[0]:.2f}) ({dur / sin:.1f}x tiempo real)")
        print(f"con word_timestamps: {con:.2f} s (mínimo; media {medios[1]:.2f}) ({dur / con:.1f}x tiempo real)")
        print(f"sobrecoste: +{con - sin:.2f} s ({(con / sin - 1) * 100:+.0f} %) · palabras {len(pal)} · dudosas (p < {cfg['palabra_dudosa_umbral']}): {len(dud)}")
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
