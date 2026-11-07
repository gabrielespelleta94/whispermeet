"""Mide la velocidad de faster-whisper (CPU, int8) con voz SINTÉTICA (SAPI de Windows vía pyttsx3).

No graba nada del micro ni del sistema: el audio sintético se genera en un temporal, se carga a memoria y se borra.

    .venv\\Scripts\\python.exe pruebas\\medir_velocidad.py [modelo] [beam]
"""
import os
import sys
import tempfile
import time
import wave
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

TEXTO = ("Buenos días a todos. Empezamos el seguimiento del portal de reservas. Hoy toca revisar el piloto, el calendario "
         "de disponibilidad y las peticiones nuevas del cliente. Se mantiene el piloto con dos hoteles para el veinte de enero. "
         "Luis estimará la integración con el sistema de facturación y la enviará el viernes. El informe semanal de ocupación "
         "se publicará los lunes a las siete de la mañana. Queda pendiente definir quién validará los datos cada semana.")


def sintetizar() -> tuple[np.ndarray, str]:
    import pyttsx3
    e = pyttsx3.init()
    voces = e.getProperty("voices")
    es = [v for v in voces if any("es" in str(l).lower()[:6] for l in (v.languages or [])) or "spanish" in v.name.lower() or "helena" in v.name.lower()]
    if es:
        e.setProperty("voice", es[0].id)
    nombre = es[0].name if es else "voz por defecto (no hay voz en español)"
    ruta = os.path.join(tempfile.mkdtemp(), "sintetico.wav")
    e.save_to_file(TEXTO, ruta)
    e.runAndWait()
    with wave.open(ruta, "rb") as w:
        sr, n, ch = w.getframerate(), w.getnframes(), w.getnchannels()
        x = np.frombuffer(w.readframes(n), dtype=np.int16).astype(np.float32) / 32768.0
    if ch > 1:
        x = x.reshape(-1, ch).mean(axis=1)
    if sr != 16000:
        x = np.interp(np.linspace(0, x.size - 1, int(x.size * 16000 / sr)), np.arange(x.size), x).astype(np.float32)
    os.remove(ruta)
    return x, nombre


def main():
    modelo = sys.argv[1] if len(sys.argv) > 1 else "small"
    beam = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    from faster_whisper import WhisperModel
    from apuntes.transcripcion import MODELOS_DIR
    audio, voz = sintetizar()
    dur = audio.size / 16000
    print(f"audio sintético: {dur:.1f} s, voz: {voz}")
    t0 = time.perf_counter()
    m = WhisperModel(modelo, device="cpu", compute_type="int8", cpu_threads=6, download_root=str(MODELOS_DIR))
    print(f"carga del modelo {modelo}: {time.perf_counter() - t0:.1f} s")
    # repetimos el audio hasta ~60 s para una medición estable (por tramos de ~20 s, como los enunciados reales)
    tramo = audio
    tiempos, textos = [], []
    for i in range(4):
        t0 = time.perf_counter()
        segs, _ = m.transcribe(tramo, language="es", beam_size=beam, vad_filter=False, condition_on_previous_text=False)
        texto = " ".join(s.text.strip() for s in segs)
        tiempos.append(time.perf_counter() - t0)
        textos.append(texto)
    for i, (t, tx) in enumerate(zip(tiempos, textos)):
        print(f"pasada {i + 1}: {t:.1f} s para {dur:.1f} s de audio -> {dur / t:.2f}x tiempo real")
    print("texto reconocido:", textos[-1][:300])
    print(f"RESUMEN modelo={modelo} beam={beam}: mediana {dur / sorted(tiempos)[len(tiempos)//2]:.2f}x tiempo real (>1 = más rápido que el audio)")


main()
