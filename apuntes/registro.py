"""Registro de errores de fondo en datos\apuntes.log (el mismo fichero al que va la salida de pythonw.exe).

Para los bucles que no pueden morir en silencio: se anota el fallo con su traza y el bucle sigue. Nunca lanza, y un mismo
error repetido no inunda el fichero (como mucho una línea por minuto y mensaje)."""
from __future__ import annotations

import threading
import time
import traceback
from datetime import datetime
from pathlib import Path

from .config import DATOS_DIR

RUTA_LOG = DATOS_DIR / "apuntes.log"
REPETIDO_S = 60.0          # el mismo error (lugar + tipo + mensaje) no se vuelve a anotar antes de este tiempo
_vistos: dict[str, float] = {}
_lock = threading.Lock()


def registrar_error(donde: str, exc: BaseException, ruta: Path | None = None) -> bool:
    """Anota `exc` (con la traza) bajo la etiqueta `donde`. Devuelve True si escribió; False si era un repetido reciente o no pudo."""
    try:
        clave = f"{donde}|{type(exc).__name__}|{exc}"
        ahora = time.monotonic()
        with _lock:
            if ahora - _vistos.get(clave, -1e9) < REPETIDO_S:
                return False
            _vistos[clave] = ahora
            if len(_vistos) > 200:
                _vistos.clear()
        destino = Path(ruta) if ruta else RUTA_LOG
        destino.parent.mkdir(parents=True, exist_ok=True)
        # Solo tipo y pila: el mensaje de una excepción puede llevar texto de la reunión y no debe acabar en el log.
        traza = "".join(traceback.format_tb(exc.__traceback__)).rstrip()
        with open(destino, "a", encoding="utf-8", errors="replace") as f:
            f.write(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] ERROR en {donde}: {type(exc).__name__}\n{traza}\n")
        return True
    except Exception:  # noqa: BLE001 — registrar nunca debe romper a quien registra
        return False
