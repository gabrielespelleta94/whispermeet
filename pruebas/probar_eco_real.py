"""Mide el detector de eco por niveles (`apuntes/eco_audio.py`) con eco ACÚSTICO REAL de esta máquina. Prueba manual: NO es automática.

Qué hace: sintetiza con la voz de Windows unos 60-90 s de habla ficticia en español (una reunión inventada sobre un proyecto de reservas
de salas; sin nombres reales) o carga un WAV mono propio (`--wav`), y la REPRODUCE POR LOS ALTAVOCES (la salida predeterminada de Windows).
A la vez captura con la propia `Captura` de la app, construida igual que `Gestor._iniciar_audio`, las dos fuentes: «Reunión» (loopback de lo
que suena) y «Micro» (lo que el micrófono recoge de los altavoces). Cada tramo de Micro se pasa a `EcoAudio.probable_eco` y se informa de su
decisión (eco sí/no, motivo, rho, exceso, desfase, ganancia, dispersión). Con auriculares, volumen a cero o cancelación de eco del propio
micrófono no hay eco que medir y el informe lo dice.

AVISO: SUENA POR LOS ALTAVOCES y abre el micrófono. Si otra aplicación ya lo está usando (una llamada) NO empieza y sale con código 2
(salvo `--forzar`): no hay que soltar una voz en mitad de una llamada.

Escucha previa: antes de sonar escucha 3 s. Si el equipo ya está reproduciendo otra cosa (música, un vídeo) o en la sala hay sonido (alguien
hablando, un teclado cerca del micro), la medida no valdría —el detector compara el Micro con TODO lo que suena, y la voz de la sala no es
eco— y sale con código 3 sin reproducir nada (salvo `--forzar`). El informe dice además cuánto eco llega de verdad al micrófono mientras
suena y si quedó sonido en la sala al parar.

Audio: NUNCA va a disco. La voz sintetizada pasa por un fichero temporal (lo exige la síntesis de Windows) que se borra en cuanto está cargada
en memoria; lo capturado solo vive dentro de los callbacks de la app y no se guarda. `--json` escribe SOLO las métricas.

    .venv\\Scripts\\python.exe pruebas\\probar_eco_real.py [--segundos 60] [--volumen 0.6] [--wav RUTA] [--forzar] [--json RUTA]

Códigos de salida: 0 midió, 2 no se ejecutó porque otra aplicación usa el micrófono, 3 no se ejecutó porque ya había sonido (en el equipo
o en la sala), 1 error."""
from __future__ import annotations

import os

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")

import argparse
import json
import math
import sys
import tempfile
import threading
import time
import wave
from collections import Counter
from pathlib import Path

import numpy as np

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

SR = 16000
CLAVE_MICROFONO = r"Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore\microphone"
# Motivos con los que `decidir_eco` NO llegó a medir nada fiable: sus rho/exceso/etc. no entran en las medianas.
SIN_MEDIDA = {"tramo corto", "sin audio", "sin datos de Reunión", "faltan datos de Reunión", "Reunión sin actividad", "error", ""}
pyaudio_wpatch = None   # se importa en main (solo si hay que capturar)
PREVIA_S = 3.0             # escucha previa, sin sonar nada
REUNION_SUENA_DB = -55.0   # un bloque de Reunión por encima de esto es que el equipo está reproduciendo algo
VOZ_DB = -42.0             # umbral con el que el `Segmentador` de la app abre un tramo: por debajo, el Micro no cuenta como voz
PREVIA_REUNION_MAX = 0.10  # fracción de la escucha previa con Reunión sonando a partir de la cual no se mide
PREVIA_MICRO_MAX = 0.20    # fracción de la escucha previa con sonido en el Micro a partir de la cual no se mide
COLA_SALA_S = 0.7          # tras parar la reproducción, lo que tarda en apagarse la sala: no cuenta como «sonido al parar»

# Texto INVENTADO (ninguna persona ni empresa reales). Unas 230 palabras: a ritmo normal son 70-90 s de habla.
TEXTO = (
    "Buenos días a todos. Empezamos el seguimiento del proyecto de reservas de salas. "
    "La pantalla de disponibilidad ya muestra las salas libres en tiempo real, aunque todavía falla cuando dos personas reservan a la vez. "
    "Propongo que esta semana cerremos ese problema antes de tocar nada más. "
    "Sobre el calendario compartido, la sincronización funciona bien con las reuniones periódicas, pero se pierden algunas cancelaciones. "
    "Necesitamos decidir si avisamos por correo a quien tenía la sala o si basta con una notificación en la aplicación. "
    "Yo creo que la notificación es suficiente, porque el correo se acumula y casi nadie lo mira. "
    "Por otro lado, el informe de ocupación por plantas está casi terminado. Falta validar las horas punta con datos de un mes completo. "
    "Si los datos confirman lo que vemos, podremos reducir dos salas pequeñas y ahorrar bastante en limpieza. "
    "Quedan tres tareas pendientes. La primera es corregir las reservas simultáneas. La segunda, probar las cancelaciones con un grupo reducido de usuarios. "
    "La tercera, preparar una demostración corta para la dirección, con capturas reales de la pantalla de disponibilidad. "
    "Una duda: ¿alguien tiene inconveniente en que hagamos la prueba con usuarios el próximo martes por la mañana? "
    "Si no hay objeciones, lo damos por acordado y enviaré hoy mismo el resumen con las tareas y las fechas. "
    "Gracias a todos, y quedamos pendientes de cerrar la lista de preguntas abiertas en la próxima sesión."
)


# ------------------------------------------------------------------------------------------------ micrófono en uso (registro, solo lectura)
def micro_en_uso() -> list[str]:
    """Nombres (solo ejecutable o paquete, nunca la ruta) de las aplicaciones que usan el micrófono AHORA según el registro de Windows:
    una subclave de ConsentStore\\microphone (o de su NonPackaged) con LastUsedTimeStop == 0 (y un inicio registrado) está en uso."""
    import winreg
    en_uso: list[str] = []

    def revisar(ruta: str, paquete: bool) -> None:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, ruta) as k:
                n = winreg.QueryInfoKey(k)[0]
                nombres = [winreg.EnumKey(k, i) for i in range(n)]
        except OSError:
            return
        for nombre in nombres:
            if paquete and nombre == "NonPackaged":
                continue
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, ruta + "\\" + nombre) as s:
                    inicio = winreg.QueryValueEx(s, "LastUsedTimeStart")[0]
                    fin = winreg.QueryValueEx(s, "LastUsedTimeStop")[0]
            except OSError:
                continue
            if fin == 0 and inicio != 0:
                corto = nombre.split("#")[-1] or nombre   # NonPackaged guarda la ruta con «#» en vez de «\»: solo el último trozo
                if corto not in en_uso:
                    en_uso.append(corto)

    revisar(CLAVE_MICROFONO, True)
    revisar(CLAVE_MICROFONO + "\\NonPackaged", False)
    return en_uso


# ------------------------------------------------------------------------------------------------ voz ficticia
def sintetizar_voz() -> tuple[np.ndarray, str]:
    """Voz de Windows (SAPI) -> float32 mono 16 kHz en memoria y nombre de la voz. La síntesis exige un fichero: temporal, borrado al cargarlo."""
    import win32com.client
    voz = win32com.client.Dispatch("SAPI.SpVoice")
    elegida = None
    for v in voz.GetVoices():
        d = v.GetDescription()
        if any(c in d for c in ("Spanish", "Español", "Helena", "Laura", "Pablo", "Sabina")):
            voz.Voice, elegida = v, d
            break
    if elegida is None:
        elegida = voz.Voice.GetDescription() + " (no hay voz en español: sonará con acento)"
    fd, ruta = tempfile.mkstemp(prefix="eco_voz_", suffix=".wav")
    os.close(fd)
    try:
        fmt = win32com.client.Dispatch("SAPI.SpAudioFormat")
        fmt.Type = 18   # SAFT16kHz16BitMono
        fs = win32com.client.Dispatch("SAPI.SpFileStream")
        fs.Format = fmt
        fs.Open(ruta, 3, False)
        voz.AudioOutputStream = fs
        voz.Speak(TEXTO)
        fs.Close()
        x = leer_wav(ruta)
    finally:
        try:
            os.remove(ruta)
        except OSError:
            pass
    return x, elegida


def leer_wav(ruta: str) -> np.ndarray:
    """WAV mono PCM de 16 bits -> float32 a 16 kHz."""
    with wave.open(str(ruta), "rb") as w:
        if w.getnchannels() != 1:
            raise ValueError("el WAV debe ser mono")
        if w.getsampwidth() != 2:
            raise ValueError("el WAV debe ser PCM de 16 bits")
        sr, datos = w.getframerate(), w.readframes(w.getnframes())
    x = np.frombuffer(datos, dtype=np.int16).astype(np.float32) / 32768.0
    return remuestrear(x, sr, SR)


def remuestrear(x: np.ndarray, sr_in: int, sr_out: int) -> np.ndarray:
    if sr_in == sr_out or x.size == 0:
        return x.astype(np.float32)
    n = max(1, int(round(x.size * sr_out / sr_in)))
    return np.interp(np.linspace(0, x.size - 1, n), np.arange(x.size), x).astype(np.float32)


def cubrir(voz: np.ndarray, segundos: float) -> np.ndarray:
    """Repite la voz (con 1,5 s de silencio entre repeticiones) hasta cubrir `segundos`, y corta justo ahí."""
    unidad = np.concatenate([voz, np.zeros(int(1.5 * SR), np.float32)])
    total = int(segundos * SR)
    veces = max(1, math.ceil(total / unidad.size))
    return np.tile(unidad, veces)[:total]


# ------------------------------------------------------------------------------------------------ reproducción
def preparar_salida(pa, voz16k: np.ndarray, volumen: float):
    """(índice del dispositivo, nombre, frecuencia, canales, bytes int16 intercalados) para la salida predeterminada WASAPI."""
    wasapi = pa.get_host_api_info_by_type(pyaudio_wpatch.paWASAPI)
    d = pa.get_device_info_by_index(wasapi["defaultOutputDevice"])
    sr, ch = int(d["defaultSampleRate"]), max(1, int(d["maxOutputChannels"]))
    pico = float(np.max(np.abs(voz16k))) if voz16k.size else 0.0
    x = voz16k / pico * 0.9 if pico > 1e-4 else voz16k      # se normaliza al 0,9 y `--volumen` escala sobre eso
    x = np.clip(remuestrear(x, SR, sr) * volumen, -1.0, 1.0)
    pcm = (np.repeat(x[:, None], ch, axis=1) * 32767.0).astype(np.int16)
    return int(d["index"]), d["name"], sr, ch, pcm.tobytes()


def reproducir(pa, indice: int, sr: int, ch: int, datos: bytes, parar: threading.Event, fallo: list) -> None:
    """Hilo: escribe por bloques de 50 ms en la salida predeterminada hasta acabar o hasta `parar`."""
    stream = None
    try:
        stream = pa.open(format=pyaudio_wpatch.paInt16, channels=ch, rate=sr, output=True, output_device_index=indice,
                         frames_per_buffer=int(sr * 0.05))
        paso = int(sr * 0.05) * ch * 2
        for i in range(0, len(datos), paso):
            if parar.is_set():
                break
            stream.write(datos[i:i + paso])
    except Exception as e:  # noqa: BLE001
        fallo.append(str(e))
    finally:
        if stream is not None:
            try:
                stream.stop_stream()
                stream.close()
            except Exception:  # noqa: BLE001
                pass


# ------------------------------------------------------------------------------------------------ informe
def db_pico(p: float) -> float:
    return 20.0 * math.log10(p) if p > 1e-6 else -120.0


def mediana(valores: list[float]) -> float | None:
    return float(np.median(valores)) if valores else None


def nivel_db(x) -> float:
    """Nivel RMS de un bloque en dBFS (−120 si está vacío o en silencio digital)."""
    if x is None or len(x) == 0:
        return -120.0
    rms = float(np.sqrt(np.mean(np.square(np.asarray(x, dtype=np.float64)))))
    return 20.0 * math.log10(rms) if rms > 1e-6 else -120.0


def fraccion(valores: list[float], umbral_db: float) -> float:
    """Fracción de bloques por encima de `umbral_db` (0 si no hay bloques)."""
    return float(np.mean(np.asarray(valores) > umbral_db)) if valores else 0.0


def ambiente(niveles: dict, t_suena: float, t_calla: float) -> dict:
    """Qué había alrededor de la medida, a partir del nivel de cada bloque de 50 ms (`niveles[fuente]` = [(t, dB)]): cuánto sonaba antes
    de reproducir, cuánto eco llega al micrófono mientras suena y si quedó sonido en la sala al parar. FUNCIÓN PURA."""
    def tramo(fuente: str, a: float, b: float) -> list[float]:
        return [db for t, db in niveles.get(fuente, ()) if a < t <= b]
    antes_r, antes_m = tramo("reunion", 0.0, t_suena), tramo("yo", 0.0, t_suena)
    suena_r = [db for db in tramo("reunion", t_suena, t_calla) if db > REUNION_SUENA_DB]
    suena_m = tramo("yo", t_suena, t_calla)
    despues_m = tramo("yo", t_calla + COLA_SALA_S, float("inf"))
    med_r, med_m = mediana(suena_r), mediana(suena_m)
    return {
        "previa": {"reunion_sonando": round(fraccion(antes_r, REUNION_SUENA_DB), 3), "micro_con_sonido": round(fraccion(antes_m, VOZ_DB), 3)},
        "sonando": {"reunion_db": None if med_r is None else round(med_r, 1), "micro_db": None if med_m is None else round(med_m, 1),
                    "micro_sobre_umbral": round(fraccion(suena_m, VOZ_DB), 3)},
        "al_parar": {"micro_con_sonido": round(fraccion(despues_m, VOZ_DB), 3)},
    }


def calcular(reunion: list[float], micro: list[dict], picos_db: dict, alrededor: dict | None = None) -> dict:
    """Métricas del informe a partir de las duraciones de los tramos de Reunión y las decisiones de los tramos de Micro."""
    dur_micro = sum(t["dur"] for t in micro)
    ecos = [t for t in micro if t["eco"]]
    medidos = [t for t in micro if t["motivo"] not in SIN_MEDIDA]
    no_marcados = Counter(t["motivo"] or "sin motivo" for t in micro if not t["eco"])

    def med(clave: str):
        m = mediana([t[clave] for t in medidos])
        return None if m is None else round(m, 3)
    return {
        "reunion": {"tramos": len(reunion), "segundos": round(sum(reunion), 1), "pico_dbfs": round(picos_db["reunion"], 1)},
        "micro": {"tramos": len(micro), "segundos": round(dur_micro, 1), "pico_dbfs": round(picos_db["yo"], 1)},
        "eco": {"tramos": len(ecos), "segundos": round(sum(t["dur"] for t in ecos), 1),
                "porcentaje_tiempo": round(100.0 * sum(t["dur"] for t in ecos) / dur_micro, 1) if dur_micro > 0 else 0.0},
        "tramos_medidos": len(medidos),
        "medianas": {"rho": med("rho"), "exceso": med("exceso"), "dispersion_db": med("dispersion_db"),
                     "ganancia_db": med("ganancia_db"), "desfase_s": med("desfase_s")},
        "no_marcados_por_motivo": dict(no_marcados.most_common()),
        "ambiente": alrededor or {},
    }


def f(v, formato: str) -> str:
    return "-" if v is None else format(v, formato)


def imprimir(m: dict, micro: list[dict]) -> None:
    print("\n=== Tramos de Micro ===")
    if not micro:
        print("  (ninguno)")
    for t in micro:
        print(f"  {t['t0']:7.1f} s  {t['dur']:5.1f} s  eco={'SI' if t['eco'] else 'no'}  {t['motivo'] or '-':<42} rho={t['rho']:5.2f}  exceso={t['exceso']:4.2f}  "
              f"desfase={t['desfase_s']:+5.2f} s  ganancia={t['ganancia_db']:+6.1f} dB  dispersion={t['dispersion_db']:4.1f} dB")
    r, mi, e, md = m["reunion"], m["micro"], m["eco"], m["medianas"]
    print("\n=== Resumen ===")
    print(f"  Reunión (audio del sistema): {r['tramos']} tramos, {r['segundos']} s, pico {r['pico_dbfs']} dBFS")
    print(f"  Micro:                       {mi['tramos']} tramos, {mi['segundos']} s, pico {mi['pico_dbfs']} dBFS")
    amb = m.get("ambiente") or {}
    if amb:
        pr, so, de = amb["previa"], amb["sonando"], amb["al_parar"]
        print(f"  Antes de sonar: el equipo reproducía algo el {pr['reunion_sonando'] * 100:.0f} % del tiempo; sonido en el Micro el {pr['micro_con_sonido'] * 100:.0f} %")
        if so["reunion_db"] is not None and so["micro_db"] is not None:
            print(f"  Mientras suena: Reunión {so['reunion_db']:.0f} dB, Micro {so['micro_db']:.0f} dB ({so['micro_db'] - so['reunion_db']:+.0f} dB); "
                  f"el Micro pasa del umbral de voz ({VOZ_DB:.0f} dB) el {so['micro_sobre_umbral'] * 100:.0f} % del tiempo")
        print(f"  Al parar: sonido en el Micro el {de['micro_con_sonido'] * 100:.0f} % del tiempo")
        if pr["reunion_sonando"] > PREVIA_REUNION_MAX or pr["micro_con_sonido"] > PREVIA_MICRO_MAX or de["micro_con_sonido"] > PREVIA_MICRO_MAX:
            print("  MEDIDA CONTAMINADA: había otro sonido (en el equipo o en la sala) además de la voz de prueba; lo que no se marca como eco "
                  "puede ser ese sonido y no un fallo del detector. Repítela en silencio.")
        elif so["micro_sobre_umbral"] < 0.15:
            print("  El eco apenas llega al micrófono a este volumen (cancelación de eco del propio equipo o altavoces bajos): casi no abre "
                  "tramos de Micro, así que en una reunión así hay poco eco que aplazar. Prueba con más --volumen para medir el detector.")
    if r["tramos"] == 0:
        print("  No se capturó el audio del sistema: ¿la salida predeterminada es otra?")
    if mi["tramos"] == 0:
        print("  El micro no recogió los altavoces: auriculares, volumen a cero o cancelación de eco del propio micro; no hay eco que medir.")
        return
    print(f"  Marcados como eco: {e['tramos']} de {mi['tramos']} tramos; {e['segundos']} s = {e['porcentaje_tiempo']} % del tiempo de Micro")
    print(f"  Medianas sobre {m['tramos_medidos']} tramos medidos: rho {f(md['rho'], '.2f')}, exceso {f(md['exceso'], '.2f')}, "
          f"dispersion {f(md['dispersion_db'], '.1f')} dB, ganancia {f(md['ganancia_db'], '+.1f')} dB, desfase {f(md['desfase_s'], '+.2f')} s")
    if m["no_marcados_por_motivo"]:
        print("  No marcados, por motivo: " + "; ".join(f"{k}: {v}" for k, v in m["no_marcados_por_motivo"].items()))
    else:
        print("  No marcados: ninguno")


# ------------------------------------------------------------------------------------------------ principal
def main() -> int:
    global pyaudio_wpatch
    ap = argparse.ArgumentParser(description="Mide el detector de eco por niveles con eco acústico real (suena por los altavoces, abre el micrófono, no guarda audio).")
    ap.add_argument("--segundos", type=float, default=60.0, help="duración de la reproducción (60 por defecto; la voz se repite si es más corta)")
    ap.add_argument("--volumen", type=float, default=0.6, help="escala de la señal reproducida, 0-1 (0,6 por defecto)")
    ap.add_argument("--wav", help="WAV mono PCM 16 bits propio, en vez de la voz sintetizada")
    ap.add_argument("--forzar", action="store_true", help="seguir aunque otra aplicación esté usando el micrófono o ya haya sonido antes de empezar")
    ap.add_argument("--json", help="escribe SOLO las métricas (nunca audio) en esta ruta")
    a = ap.parse_args()
    if not (a.segundos > 0) or not (0.0 <= a.volumen <= 1.0):
        print("Error: --segundos debe ser mayor que 0 y --volumen estar entre 0 y 1.")
        return 1

    # 1. ¿otra aplicación usa el micrófono? (solo lectura del registro)
    try:
        usan = micro_en_uso()
    except Exception as e:  # noqa: BLE001
        usan = []
        print(f"(no se pudo leer el registro del micrófono: {e}; se sigue sin esa comprobación)")
    if usan and not a.forzar:
        print("El micrófono lo está usando ahora: " + ", ".join(usan))
        print("No se reproduce nada para no soltar una voz por los altavoces en mitad de una llamada. Para seguir igualmente, usa --forzar.")
        return 2
    if usan:
        print("Aviso: el micrófono lo usa " + ", ".join(usan) + " (se sigue por --forzar).")

    # 2. señal a reproducir
    try:
        if a.wav:
            voz, nombre_voz = leer_wav(a.wav), "WAV propio"
        else:
            print("Sintetizando la voz ficticia con Windows (no suena)...")
            voz, nombre_voz = sintetizar_voz()
    except Exception as e:  # noqa: BLE001
        print(f"Error al preparar la voz: {e}")
        return 1
    if voz.size < SR:
        print("Error: la voz obtenida dura menos de 1 s.")
        return 1
    print(f"Voz: {nombre_voz}, {voz.size / SR:.1f} s" + (f"; se repite hasta cubrir {a.segundos:g} s" if voz.size / SR < a.segundos else ""))
    senal = cubrir(voz, a.segundos)
    del voz

    # 3. captura con la clase de la app, igual que Gestor._iniciar_audio
    try:
        import pyaudiowpatch
        pyaudio_wpatch = pyaudiowpatch
        from apuntes.audio import Captura
        from apuntes.eco_audio import EcoAudio
    except Exception as e:  # noqa: BLE001
        print(f"Error: no se pudo cargar la captura ({e}).")
        return 1

    detector = EcoAudio()
    cerrojo = threading.Lock()
    reunion: list[float] = []          # duración de cada tramo de Reunión
    micro: list[dict] = []             # decisión de cada tramo de Micro (solo números y texto)
    picos = {"yo": 0.0, "reunion": 0.0}   # pico absoluto visto por fuente
    niveles: dict[str, list] = {"yo": [], "reunion": []}   # (instante, dB) de cada bloque de 50 ms: solo números
    suena = {"ini": float("inf"), "fin": float("inf")}     # reloj de la captura al empezar y al acabar la reproducción

    def on_bloque(fuente: str, x, t: float) -> None:
        try:
            p = float(np.max(np.abs(x))) if len(x) else 0.0
            if p > picos.get(fuente, 0.0):
                picos[fuente] = p
            niveles[fuente].append((float(t), nivel_db(x)))   # list.append es atómico: cada fuente escribe solo en la suya
        except Exception:  # noqa: BLE001
            pass
        detector.bloque(fuente, x, t)

    def on_enunciado(fuente: str, audio, t0: float) -> None:   # el audio no se guarda: solo se miden duración y decisión
        dur = len(audio) / SR
        with cerrojo:
            if fuente == "yo":
                eco = detector.probable_eco(audio, t0)
                u = dict(detector.ultimo)
                micro.append({"t0": float(t0), "dur": dur, "eco": bool(eco), "motivo": u.get("motivo", ""), "rho": float(u.get("rho", 0.0)),
                              "exceso": float(u.get("exceso", 1.0)), "desfase_s": float(u.get("desfase_s", 0.0)),
                              "ganancia_db": float(u.get("ganancia_db", 0.0)), "dispersion_db": float(u.get("dispersion_db", 0.0)),
                              "fuerte": bool(u.get("fuerte", False))})
            elif fuente == "reunion":
                reunion.append(dur)

    t_ini = time.monotonic()
    captura = Captura(lambda: time.monotonic() - t_ini, on_enunciado, lambda fuente, db: None, None, None,
                      vaciar_al_parar=True, on_bloque=on_bloque)
    pa = None
    parar = threading.Event()
    fallo: list[str] = []
    try:
        pa = pyaudiowpatch.PyAudio()
        indice, nombre_sal, sr_sal, ch_sal, datos = preparar_salida(pa, senal, a.volumen)
        del senal
        print(f"Salida predeterminada: «{nombre_sal}» ({sr_sal} Hz, {ch_sal} canales), volumen {a.volumen:g}. Capturando Reunión y Micro...")
        captura.iniciar()
        for fuente, err in captura.errores.items():
            print(f"Aviso: sin captura de {'el micrófono' if fuente == 'yo' else 'el audio del sistema'}: {err}")
        if len(captura.errores) >= 2:
            print("Error: no se pudo abrir ninguna de las dos fuentes de audio.")
            return 1
        try:
            time.sleep(PREVIA_S)   # escucha previa: ¿ya suena algo en el equipo o en la sala?
            ahora = time.monotonic() - t_ini
            ya_suena = fraccion([db for t, db in list(niveles["reunion"]) if t <= ahora], REUNION_SUENA_DB)
            sala = fraccion([db for t, db in list(niveles["yo"]) if t <= ahora], VOZ_DB)
            if ya_suena > PREVIA_REUNION_MAX or sala > PREVIA_MICRO_MAX:
                que = []
                if ya_suena > PREVIA_REUNION_MAX:
                    que.append(f"el equipo ya está reproduciendo otro audio (el {ya_suena * 100:.0f} % de la escucha previa)")
                if sala > PREVIA_MICRO_MAX:
                    que.append(f"hay sonido en la sala (el micrófono lo recoge el {sala * 100:.0f} % de la escucha previa)")
                if not a.forzar:
                    print("No se mide: " + " y ".join(que) + ". La medida no sería fiable; repítela en silencio o usa --forzar.")
                    return 3
                print("Aviso: " + " y ".join(que) + " (se sigue por --forzar; la medida saldrá contaminada).")
            suena["ini"] = time.monotonic() - t_ini
            hilo = threading.Thread(target=reproducir, args=(pa, indice, sr_sal, ch_sal, datos, parar, fallo), daemon=True, name="reproduccion")
            hilo.start()
            print("Suena ahora por los altavoces (Ctrl+C para cortar y ver lo medido)...")
            while hilo.is_alive():
                hilo.join(0.5)
            suena["fin"] = time.monotonic() - t_ini
            time.sleep(2.0)
        except KeyboardInterrupt:
            print("\nInterrumpido: se cierra la captura con lo medido hasta ahora.")
            parar.set()
    except Exception as e:  # noqa: BLE001
        print(f"Error: {e}")
        return 1
    finally:
        parar.set()
        try:
            captura.detener()
        except Exception:  # noqa: BLE001
            pass
        if pa is not None:
            try:
                pa.terminate()
            except Exception:  # noqa: BLE001
                pass
    time.sleep(0.5)   # los hilos de captura entregan el tramo a medias (vaciar_al_parar) justo al salir
    if fallo:
        print(f"Error en la reproducción: {fallo[0]}")
        return 1

    # 4. informe
    with cerrojo:
        tramos_micro, tramos_reunion = list(micro), list(reunion)
    alrededor = ambiente({k: list(v) for k, v in niveles.items()}, suena["ini"], suena["fin"]) if suena["ini"] != float("inf") else None
    m = calcular(tramos_reunion, tramos_micro, {k: db_pico(v) for k, v in picos.items()}, alrededor)
    imprimir(m, tramos_micro)
    if a.json:
        try:
            salida = {"parametros": {"segundos": a.segundos, "volumen": a.volumen, "wav_propio": bool(a.wav), "forzar": bool(a.forzar)},
                      **m, "tramos_micro": [{k: (round(v, 3) if isinstance(v, float) else v) for k, v in t.items()} for t in tramos_micro]}
            Path(a.json).write_text(json.dumps(salida, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"\nMétricas escritas en {a.json} (sin audio).")
        except Exception as e:  # noqa: BLE001
            print(f"Error al escribir el JSON: {e}")
            return 1
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # noqa: BLE001
        print(f"Error inesperado: {e}")
        sys.exit(1)
