"""Guarda para la batería de tests: que no compita con una reunión que se está transcribiendo en directo.

Las funciones son pequeñas y reciben lo que necesitan (entorno, lector del registro, reloj, carpeta de datos)
para probarse sin tocar el registro real de Windows ni la carpeta de datos real."""
import os
import sys

BELOW_NORMAL_PRIORITY_CLASS = 0x00004000
UMBRAL_ESCRITURA_S = 120
FICHEROS_DE_LA_APP = ("apuntes.log", "consumo.jsonl")
CLAVE_MICROFONO = r"Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore\microphone"


def _bajar_prioridad_real(clase):
    import ctypes
    k32 = ctypes.windll.kernel32
    k32.GetCurrentProcess.restype = ctypes.c_void_p
    k32.SetPriorityClass.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    return bool(k32.SetPriorityClass(k32.GetCurrentProcess(), clase))


def bajar_prioridad(entorno=None, plataforma=None, llamar=None):
    """Baja el proceso a «por debajo de lo normal» (los hijos la heredan). Nunca lanza. Devuelve si lo ha conseguido."""
    entorno = os.environ if entorno is None else entorno
    plataforma = sys.platform if plataforma is None else plataforma
    if plataforma != "win32" or entorno.get("WHISPERMEET_TESTS_PRIORIDAD_NORMAL") == "1":
        return False
    try:
        return bool((llamar or _bajar_prioridad_real)(BELOW_NORMAL_PRIORITY_CLASS))
    except Exception:
        return False


def leer_microfono_registro():
    """[(subclave, LastUsedTimeStop)] del consentimiento de micrófono de Windows (incluye NonPackaged). Solo lectura."""
    import winreg
    salida = []

    def recorrer(raiz, ruta, prefijo=""):
        with winreg.OpenKey(raiz, ruta) as clave:
            i = 0
            while True:
                try:
                    nombre = winreg.EnumKey(clave, i)
                except OSError:
                    break
                i += 1
                if nombre == "NonPackaged" and not prefijo:
                    recorrer(raiz, ruta + "\\" + nombre, "NonPackaged\\")
                    continue
                try:
                    with winreg.OpenKey(clave, nombre) as sub:
                        valor, _ = winreg.QueryValueEx(sub, "LastUsedTimeStop")
                    salida.append((prefijo + nombre, valor))
                except OSError:
                    continue
    recorrer(winreg.HKEY_CURRENT_USER, CLAVE_MICROFONO)
    return salida


def _nombre_app(subclave):
    return subclave.replace("#", "\\").replace("/", "\\").rsplit("\\", 1)[-1] or subclave


def motivo_reunion(lector_registro, reloj, datos_dir, umbral_s=UMBRAL_ESCRITURA_S):
    """Texto con la señal que indica reunión en marcha, o None. Cualquier fallo propio cuenta como «no hay reunión»."""
    try:
        for subclave, parada in lector_registro():
            if parada == 0:
                return f"micrófono en uso por {_nombre_app(subclave)}"
        ahora = reloj()
        for nombre in FICHEROS_DE_LA_APP:
            try:
                mtime = os.stat(os.path.join(datos_dir, nombre)).st_mtime
            except OSError:
                continue
            if ahora - mtime < umbral_s:
                return f"la app real ha escrito en {nombre} hace menos de {umbral_s} s"
    except Exception:
        return None
    return None


def comprobar_reunion(entorno, lector_registro, reloj, datos_dir):
    """Mensaje completo para el usuario si hay reunión y no se ha forzado; si no, None."""
    if entorno.get("WHISPERMEET_TESTS_EN_REUNION") == "1":
        return None
    motivo = motivo_reunion(lector_registro, reloj, datos_dir)
    if motivo is None:
        return None
    return (f"Hay una reunión en marcha ({motivo}). Los tests consumen mucha CPU y retrasan la transcripción en directo: "
            "espera a que termine o define WHISPERMEET_TESTS_EN_REUNION=1.")


def exigir_sin_reunion(entorno, lector_registro, reloj, datos_dir):
    import pytest
    mensaje = comprobar_reunion(entorno, lector_registro, reloj, datos_dir)
    if mensaje:
        pytest.exit(mensaje, returncode=3)
