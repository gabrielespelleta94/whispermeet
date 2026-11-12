"""Clave de la transcripción en la nube. Nunca va a `config.json`, a `/api/info`, al registro, a las copias ni al repositorio.

Se busca primero en la variable de entorno `WHISPERMEET_CLAVE_NUBE` y, si no está, en `datos/secreto-nube.dpapi`: un JSON pequeño con el blob
cifrado con DPAPI del usuario de Windows (`CryptProtectData`, por ctypes: sin dependencias). Atado al usuario y al equipo: en otro perfil no se
puede leer y hay que volver a ponerla (intencionado: la copia de seguridad no la lleva). El fichero se lee y se escribe SOLO por el Guardián
(`leer_secreto_nube`, `escribir_secreto_nube`, `borrar_secreto_nube`).
"""
from __future__ import annotations

import base64
import json
import os
import re
import sys
import threading
import time

from .rutas import RutaProhibida

ENV_CLAVE = "WHISPERMEET_CLAVE_NUBE"
ENTROPIA = b"WhisperMeet/nube/v1"
DESCRIPCION = "WhisperMeet nube"
CRYPTPROTECT_UI_FORBIDDEN = 0x1
TEXTO_CLAVE_INVALIDA = "La clave tiene de 8 a 400 caracteres visibles, sin espacios."
TEXTO_ERROR_LECTURA = "La clave guardada no se puede leer con este usuario de Windows: vuelve a ponerla."
_RE_CLAVE = re.compile(r"^[\x21-\x7e]{8,400}$")


def _blob_dpapi():
    import ctypes
    from ctypes import wintypes

    class DATA_BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]
    return ctypes, DATA_BLOB


def _blob_de(DATA_BLOB, ctypes, datos: bytes):
    buf = ctypes.create_string_buffer(datos, len(datos))
    return DATA_BLOB(len(datos), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))), buf


def _llamar(funcion: str, datos: bytes) -> bytes:
    if sys.platform != "win32":
        raise OSError("DPAPI solo está disponible en Windows")
    ctypes, DATA_BLOB = _blob_dpapi()
    crypt32, kernel32 = ctypes.windll.crypt32, ctypes.windll.kernel32
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    entrada, _b1 = _blob_de(DATA_BLOB, ctypes, datos)
    entropia, _b2 = _blob_de(DATA_BLOB, ctypes, ENTROPIA)
    salida = DATA_BLOB()
    if funcion == "proteger":
        ok = crypt32.CryptProtectData(ctypes.byref(entrada), DESCRIPCION, ctypes.byref(entropia), None, None,
                                      CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(salida))
    else:
        ok = crypt32.CryptUnprotectData(ctypes.byref(entrada), None, ctypes.byref(entropia), None, None,
                                        CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(salida))
    if not ok:
        raise OSError(f"DPAPI falló ({ctypes.GetLastError()})")
    try:
        return ctypes.string_at(salida.pbData, salida.cbData)
    finally:
        kernel32.LocalFree(salida.pbData)


def proteger(datos: bytes) -> bytes:
    """Cifra con DPAPI del usuario actual (con entropía propia). OSError si falla o no es Windows."""
    return _llamar("proteger", datos)


def desproteger(blob: bytes) -> bytes:
    """Descifra con DPAPI. OSError si el blob es de otro usuario o está dañado."""
    return _llamar("desproteger", blob)


def validar_clave(v) -> str:
    """Quita los espacios de los extremos y exige 8-400 caracteres ASCII visibles. ValueError con el texto de la API."""
    if not isinstance(v, str):
        raise ValueError(TEXTO_CLAVE_INVALIDA)
    v = v.strip()
    if not _RE_CLAVE.match(v):
        raise ValueError(TEXTO_CLAVE_INVALIDA)
    return v


class ClaveNube:
    def __init__(self, guardian, entorno=os.environ, proteger=proteger, desproteger=desproteger):
        self.g, self.entorno = guardian, entorno
        self._proteger, self._desproteger = proteger, desproteger
        self._lock = threading.Lock()
        self._cache: tuple | None = None   # ((mtime_ns, tamaño), clave | None, error)

    # ---------------------------------------------------------------- lectura
    def _del_entorno(self) -> str | None:
        v = (self.entorno.get(ENV_CLAVE) or "").strip()
        return v or None

    def _del_fichero(self) -> tuple[str | None, str]:
        """(clave, error). Caché por (mtime, tamaño): DPAPI no se llama en cada trozo. Nunca lanza."""
        try:
            ruta = self.g.ruta_secreto_nube()
            st = ruta.stat()
        except RutaProhibida:
            return None, ""
        except OSError:
            self._cache = None
            return None, ""
        marca = (st.st_mtime_ns, st.st_size)
        with self._lock:
            if self._cache and self._cache[0] == marca:
                return self._cache[1], self._cache[2]
        clave, error = None, ""
        try:
            texto = self.g.leer_secreto_nube()
            if texto is not None:
                d = json.loads(texto)
                if not isinstance(d, dict) or d.get("v") != 1 or not isinstance(d.get("dpapi"), str):
                    raise ValueError("formato")
                clave = validar_clave(self._desproteger(base64.b64decode(d["dpapi"], validate=True)).decode("ascii"))
        except Exception:  # noqa: BLE001  (JSON roto, DPAPI de otro usuario, formato nuevo…: no puesta y con el texto de ayuda; sin detalle, que podría ser sensible)
            clave, error = None, TEXTO_ERROR_LECTURA
        with self._lock:
            self._cache = (marca, clave, error)
        return clave, error

    def obtener(self) -> str | None:
        """La clave (entorno > fichero), o None. Nunca lanza."""
        try:
            return self._del_entorno() or self._del_fichero()[0]
        except Exception:  # noqa: BLE001
            return None

    def estado(self) -> dict:
        """{puesta, origen: entorno|fichero|ninguna, error}. Nunca lleva la clave."""
        try:
            if self._del_entorno():
                return {"puesta": True, "origen": "entorno", "error": ""}
            clave, error = self._del_fichero()
        except Exception:  # noqa: BLE001
            return {"puesta": False, "origen": "ninguna", "error": ""}
        if clave:
            return {"puesta": True, "origen": "fichero", "error": ""}
        return {"puesta": False, "origen": "ninguna", "error": error}

    # ---------------------------------------------------------------- escritura
    def guardar(self, clave: str) -> None:
        """ValueError si la clave no es válida; RutaProhibida si no hay carpeta de datos; OSError si DPAPI falla."""
        clave = validar_clave(clave)
        self.g.ruta_secreto_nube()   # RutaProhibida antes de cifrar nada
        blob = self._proteger(clave.encode("ascii"))
        cuerpo = {"v": 1, "dpapi": base64.b64encode(blob).decode("ascii"), "guardada": time.strftime("%Y-%m-%dT%H:%M:%S")}
        self.g.escribir_secreto_nube(json.dumps(cuerpo))
        with self._lock:
            self._cache = None

    def borrar(self) -> None:
        try:
            self.g.borrar_secreto_nube()
        except RutaProhibida:
            pass
        with self._lock:
            self._cache = None
