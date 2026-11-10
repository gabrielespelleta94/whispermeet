"""Que Windows no frene el proceso cuando su ventana queda tapada.

Windows 11 puede bajar la calidad de servicio (EcoQoS, «regulación de energía») de los procesos cuya ventana no está visible, y es justo lo que
pasa en una reunión (Teams delante, WhisperMeet detrás): la transcripción se frena. `sin_freno_de_energia` le pide a Windows que NO regule la
velocidad de ejecución de ESTE proceso (`PROCESS_POWER_THROTTLING_EXECUTION_SPEED` con el estado en «apagado»). No cambia prioridad, afinidad
ni ningún otro ajuste, y no toca el sistema: solo el propio proceso. Fuera de Windows o ante cualquier error no hace nada y devuelve False."""
from __future__ import annotations

import ctypes
import sys

PROCESS_POWER_THROTTLING = 4            # ProcessPowerThrottling: clase de PROCESS_INFORMATION_CLASS
PROCESS_POWER_THROTTLING_CURRENT_VERSION = 1
PROCESS_POWER_THROTTLING_EXECUTION_SPEED = 0x1


class PROCESS_POWER_THROTTLING_STATE(ctypes.Structure):
    _fields_ = [("Version", ctypes.c_ulong), ("ControlMask", ctypes.c_ulong), ("StateMask", ctypes.c_ulong)]


def _declarar(kernel32) -> None:
    """Tipos de la API (el manejador es de 64 bits: sin `restype` Python lo truncaría a int de 32). Un doble de pruebas puede no admitirlos."""
    try:
        kernel32.GetCurrentProcess.restype = ctypes.c_void_p
        kernel32.GetCurrentProcess.argtypes = []
        kernel32.SetProcessInformation.restype = ctypes.c_int
        kernel32.SetProcessInformation.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_ulong]
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
