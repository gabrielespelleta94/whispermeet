"""Que Windows no frene el proceso cuando su ventana queda tapada.

Windows 11 puede bajar la calidad de servicio (EcoQoS, «regulación de energía») de los procesos cuya ventana no está visible, y es justo lo que
pasa en una reunión (Teams delante, WhisperMeet detrás): la transcripción se frena. `sin_freno_de_energia` le pide a Windows que NO regule la
velocidad de ejecución de ESTE proceso (`PROCESS_POWER_THROTTLING_EXECUTION_SPEED` con el estado en «apagado»). No cambia prioridad, afinidad
ni ningún otro ajuste, y no toca el sistema: solo el propio proceso. Fuera de Windows o ante cualquier error no hace nada y devuelve False.
`prioridad_de_reunion` sube la clase de prioridad del proceso mientras se captura (con Teams abierto Whisper compite con la videollamada y sin esto
iba a 1,1× del tiempo real), y `tiempos_del_equipo`/`uso_de_cpu` miden cuánta CPU gasta TODO el equipo, solo como diagnóstico para el registro."""
from __future__ import annotations

import ctypes
import os
import sys

PROCESS_POWER_THROTTLING = 4            # ProcessPowerThrottling: clase de PROCESS_INFORMATION_CLASS
PROCESS_POWER_THROTTLING_CURRENT_VERSION = 1
PROCESS_POWER_THROTTLING_EXECUTION_SPEED = 0x1
ABOVE_NORMAL_PRIORITY_CLASS = 0x00008000
NORMAL_PRIORITY_CLASS = 0x00000020
HIGH_PRIORITY_CLASS = 0x00000080
REALTIME_PRIORITY_CLASS = 0x00000100
CLASES_ALTAS = (ABOVE_NORMAL_PRIORITY_CLASS, HIGH_PRIORITY_CLASS, REALTIME_PRIORITY_CLASS)   # si el proceso ya corre con una de estas, no se toca
VARIABLE_SIN_PRIORIDAD = "WHISPERMEET_SIN_PRIORIDAD"   # si existe, la prioridad no se toca (los tests no pueden cambiar la de pytest ni la de sus servidores)


class PROCESS_POWER_THROTTLING_STATE(ctypes.Structure):
    _fields_ = [("Version", ctypes.c_ulong), ("ControlMask", ctypes.c_ulong), ("StateMask", ctypes.c_ulong)]


class FILETIME(ctypes.Structure):
    _fields_ = [("Bajo", ctypes.c_ulong), ("Alto", ctypes.c_ulong)]   # intervalos de 100 ns


def _declarar(kernel32) -> None:
    """Tipos de la API (el manejador es de 64 bits: sin `restype` Python lo truncaría a int de 32). Un doble de pruebas puede no admitirlos."""
    try:
        kernel32.GetCurrentProcess.restype = ctypes.c_void_p
        kernel32.GetCurrentProcess.argtypes = []
        kernel32.SetProcessInformation.restype = ctypes.c_int
        kernel32.SetProcessInformation.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_ulong]
        kernel32.GetPriorityClass.restype = ctypes.c_ulong
        kernel32.GetPriorityClass.argtypes = [ctypes.c_void_p]
        kernel32.SetPriorityClass.restype = ctypes.c_int
        kernel32.SetPriorityClass.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        kernel32.GetSystemTimes.restype = ctypes.c_int
        kernel32.GetSystemTimes.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
    except Exception:  # noqa: BLE001
        pass


def sin_freno_de_energia(kernel32=None) -> bool:
    """Pide a Windows que no regule la velocidad de este proceso. True si la llamada dice que sí. Nunca lanza.
    `kernel32` permite inyectar un doble (pruebas): con él no se comprueba la plataforma."""
    try:
        if kernel32 is None:
            if sys.platform != "win32":
                return False
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            _declarar(kernel32)
        estado = PROCESS_POWER_THROTTLING_STATE(PROCESS_POWER_THROTTLING_CURRENT_VERSION, PROCESS_POWER_THROTTLING_EXECUTION_SPEED, 0)
        manejador = kernel32.GetCurrentProcess()
        return bool(kernel32.SetProcessInformation(manejador, PROCESS_POWER_THROTTLING, ctypes.pointer(estado), ctypes.sizeof(estado)))
    except Exception:  # noqa: BLE001 — esto es un favor al rendimiento: nunca debe impedir arrancar
        return False


def prioridad_compatible(hilos: int, nucleos: int) -> bool:
    """True si subir la prioridad es seguro: Whisper deja la mitad de los núcleos a la videollamada (1 <= hilos <= max(1, núcleos // 2)). FUNCIÓN PURA."""
    return 1 <= hilos <= max(1, nucleos // 2)


def clase_de_prioridad(kernel32=None) -> int | None:
    """Clase de prioridad actual de ESTE proceso (`GetPriorityClass`), o None si no se puede leer (falla, devuelve 0, no es Windows o la variable
    `WHISPERMEET_SIN_PRIORIDAD`, sin llamar a la API). Nunca lanza. `kernel32` permite inyectar un doble (pruebas)."""
    try:
        if os.environ.get(VARIABLE_SIN_PRIORIDAD):
            return None
        if kernel32 is None:
            if sys.platform != "win32":
                return None
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            _declarar(kernel32)
        clase = int(kernel32.GetPriorityClass(kernel32.GetCurrentProcess()))
        return clase or None
    except Exception:  # noqa: BLE001
        return None


def prioridad_de_reunion(activa: bool, kernel32=None, clase_normal: int | None = None) -> bool:
    """Prioridad de ESTE proceso mientras se captura: `ABOVE_NORMAL` con `activa`; sin ella, `clase_normal` (la que tenía antes) o `NORMAL`.
    True si la llamada dice que sí. Nunca lanza.
    Los hijos (`claude -p`) no heredan ABOVE_NORMAL en Windows y siguen arrancando con su propia prioridad baja: aquí no se hace nada con ellos.
    Con la variable `WHISPERMEET_SIN_PRIORIDAD` no se llama a la API y devuelve False. `kernel32` permite inyectar un doble (pruebas)."""
    try:
        if os.environ.get(VARIABLE_SIN_PRIORIDAD):
            return False
        if kernel32 is None:
            if sys.platform != "win32":
                return False
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            _declarar(kernel32)
        clase = ABOVE_NORMAL_PRIORITY_CLASS if activa else (clase_normal or NORMAL_PRIORITY_CLASS)
        return bool(kernel32.SetPriorityClass(kernel32.GetCurrentProcess(), clase))
    except Exception:  # noqa: BLE001 — un favor al rendimiento: nunca debe impedir capturar
        return False


def tiempos_del_equipo(kernel32=None) -> tuple[float, float] | None:
    """(ocupado_s, total_s) acumulados de TODOS los núcleos del equipo, de `GetSystemTimes` (el tiempo de kernel incluye el ocioso). None si no se
    puede (fuera de Windows o ante cualquier error). Nunca lanza. Es una lectura sin dependencias: dos lecturas y `uso_de_cpu` dan el % del intervalo."""
    try:
        if kernel32 is None:
            if sys.platform != "win32":
                return None
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            _declarar(kernel32)
        ocioso, kernel, usuario = FILETIME(), FILETIME(), FILETIME()
        if not kernel32.GetSystemTimes(ctypes.pointer(ocioso), ctypes.pointer(kernel), ctypes.pointer(usuario)):
            return None

        def segundos(t: FILETIME) -> float:
            return ((int(t.Alto) << 32) | int(t.Bajo)) / 1e7
        total = segundos(kernel) + segundos(usuario)
        return max(0.0, total - segundos(ocioso)), total
    except Exception:  # noqa: BLE001
        return None


def uso_de_cpu(antes: tuple[float, float] | None, despues: tuple[float, float] | None) -> int | None:
    """% de CPU (0-100) de todo el equipo entre dos lecturas de `tiempos_del_equipo`; None si falta alguna o no pasó tiempo. FUNCIÓN PURA."""
    if not antes or not despues:
        return None
    total = despues[1] - antes[1]
    if total <= 0:
        return None
    return int(round(max(0.0, min(100.0, 100.0 * (despues[0] - antes[0]) / total))))
