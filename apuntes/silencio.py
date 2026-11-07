"""«Esto está mal» (ola 4): reglas locales de silencio para el Monitor y las tarjetas.

Una regla es (tipo, clave): `tipo` dice de qué clase de aviso se trata y `clave` es el texto normalizado (minúsculas, sin acentos ni signos) que lo identifica.
Se guardan en `reglas-silencio.json` de la carpeta local de datos (solo vía Guardian). El Monitor las consulta antes de añadir una entrada al feed y el Gestor
antes de emitir una tarjeta: un aviso EQUIVALENTE (misma clave, o muy parecida) no vuelve a salir. Nada sale de la máquina y nada se borra de la reunión.

Tipos: `senal:<señal>` (la cita de la señal), `definicion` (el término), `toca` y `sin_tratar` (el texto del objetivo), `silencio` (el aviso de «nadie tiene turno»,
a nivel de tipo) y `tarjeta:<categoría>` (el texto de la tarjeta de un perfil).
"""
from __future__ import annotations

import json
import re
import threading
import uuid
from datetime import datetime

from .rutas import RutaProhibida, sin_acentos
from .texto import tokens_utiles

FICHERO = "reglas-silencio.json"
MAX_REGLAS = 500
UMBRAL_PARECIDA = 0.8     # solape de términos útiles para dar por equivalente un aviso con otro texto
MIN_COMPARTIDOS = 2
CLAVE_MAX = 120
TIPOS_BASE = ("senal", "definicion", "toca", "sin_tratar", "silencio", "tarjeta")


def normalizar_clave(texto: str) -> str:
    t = sin_acentos(str(texto or "")).lower()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", t)).strip()[:CLAVE_MAX]


def tipo_valido(tipo: str) -> bool:
    return isinstance(tipo, str) and tipo.split(":", 1)[0] in TIPOS_BASE and len(tipo) <= 40


def equivalentes(a: str, b: str) -> bool:
    """Misma clave normalizada, o textos con el mismo asunto (≥80 % de los términos útiles del más corto y al menos dos en común)."""
    if not a or not b:
        return False
    if a == b:
        return True
    ta, tb = tokens_utiles(a), tokens_utiles(b)
    n = len(ta & tb)
    return bool(ta and tb) and n >= MIN_COMPARTIDOS and n / min(len(ta), len(tb)) >= UMBRAL_PARECIDA


class ReglasSilencio:
    def __init__(self, guardian):
        self.g = guardian
        self._lock = threading.Lock()
        self._cache: list[dict] | None = None

    # ---- almacenamiento
    def _leer(self) -> list[dict]:
        if self._cache is not None:
            return self._cache
        try:
            crudo = json.loads(self.g.leer_datos(FICHERO) or "[]")
        except (ValueError, RutaProhibida):
            crudo = []
        lista = [r for r in crudo if isinstance(r, dict) and tipo_valido(r.get("tipo")) and isinstance(r.get("clave"), str) and r.get("id")] \
            if isinstance(crudo, list) else []
        self._cache = lista
        return lista

    def _guardar(self, lista: list[dict]) -> None:
        self.g.escribir_datos(FICHERO, json.dumps(lista, ensure_ascii=False, indent=2))
        self._cache = lista

    # ---- API
    def listar(self) -> list[dict]:
        with self._lock:
            return [dict(r) for r in self._leer()]

    def silenciado(self, tipo: str, texto: str) -> bool:
        """¿Hay una regla que cubra este aviso? Se consulta en cada pasada del Monitor: solo memoria."""
        clave = normalizar_clave(texto)
        tipo_base = tipo
        with self._lock:
            for r in self._leer():
                if r["tipo"] != tipo_base:
                    continue
                if r["tipo"] == "silencio" or equivalentes(r["clave"], clave):
                    r["veces"] = int(r.get("veces", 0)) + 1   # solo en memoria: se guarda con el siguiente cambio de reglas
                    return True
        return False

    def anadir(self, tipo: str, texto: str, ejemplo: str = "", sesion: str = "") -> dict:
        """Guarda la regla (si ya hay una equivalente, devuelve esa con `nueva: False`). ValueError si el tipo no vale o no hay dónde guardar."""
        if not tipo_valido(tipo):
            raise ValueError("Tipo de regla no válido.")
        clave = normalizar_clave(texto) if tipo != "silencio" else "silencio"
        if not clave:
            raise ValueError("Este aviso no tiene texto con el que reconocerlo.")
        if not self.g.hay_datos():
            raise ValueError("No hay carpeta local de datos donde guardar la regla.")
        with self._lock:
            lista = self._leer()
            for r in lista:
                if r["tipo"] == tipo and (tipo == "silencio" or equivalentes(r["clave"], clave)):
                    return {**r, "nueva": False}
            if len(lista) >= MAX_REGLAS:
                raise ValueError("Hay demasiadas reglas de silencio; borra alguna.")
            regla = {"id": uuid.uuid4().hex[:12], "tipo": tipo, "clave": clave, "ejemplo": " ".join(str(ejemplo or texto).split())[:140],
                     "creada": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"), "sesion": sesion or "", "veces": 0}
            self._guardar(lista + [regla])
            return {**regla, "nueva": True}

    def borrar(self, ident: str) -> bool:
        with self._lock:
            lista = self._leer()
            nueva = [r for r in lista if r["id"] != ident]
            if len(nueva) == len(lista):
                return False
            self._guardar(nueva)
            return True
