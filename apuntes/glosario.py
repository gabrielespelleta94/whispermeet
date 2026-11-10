"""Vocabulario curado por el usuario (ola 4): el global vive en `vocabulario_transcripcion` (config) y el de cada proyecto en `glosario.json`,
dentro de la carpeta local de datos de la app (solo vía Guardian). Lo que se añade aquí entra en el `initial_prompt` y en `corregir_glosario`
de las reuniones siguientes y, si hay una en curso, de la actual (el Gestor recalcula el vocabulario del transcriptor)."""
from __future__ import annotations

import json
import threading

from .rutas import RutaProhibida

FICHERO = "glosario.json"
MAX_TERMINO = 40
MAX_POR_PROYECTO = 60


def limpiar_termino(termino) -> str:
    t = " ".join(str(termino or "").split())
    if len(t) < 2:
        raise ValueError("El término es demasiado corto.")
    if len(t) > MAX_TERMINO:
        raise ValueError(f"El término no puede pasar de {MAX_TERMINO} caracteres.")
    return t


class Glosario:
    def __init__(self, guardian, config):
        self.g, self.cfg = guardian, config
        self._lock = threading.Lock()

    def _leer(self) -> dict[str, list[str]]:
        try:
            crudo = json.loads(self.g.leer_datos(FICHERO) or "{}")
        except (ValueError, RutaProhibida):
            return {}
        if not isinstance(crudo, dict):
            return {}
        return {str(k): [str(x) for x in v if isinstance(x, str)] for k, v in crudo.items() if isinstance(v, list)}

    def de_proyecto(self, proyecto: str | None) -> list[str]:
        if not proyecto:
            return []
        return list(self._leer().get(proyecto.strip().lower(), []))

    def anadir(self, termino: str, proyecto: str | None = None) -> dict:
        """Añade `termino` al vocabulario global (sin proyecto) o al del proyecto. -> {termino, ambito, nuevo, total}. ValueError si no cabe o no se puede guardar."""
        t = limpiar_termino(termino)
        with self._lock:
            if not proyecto:
                actual = list(self.cfg["vocabulario_transcripcion"])
                if any(x.lower() == t.lower() for x in actual):
                    return {"termino": t, "ambito": "global", "proyecto": None, "nuevo": False, "total": len(actual)}
                if len(actual) >= MAX_POR_PROYECTO:
                    raise ValueError("El vocabulario global ya tiene el máximo de términos (60).")
                self.cfg.actualizar({"vocabulario_transcripcion": actual + [t]})
                return {"termino": t, "ambito": "global", "proyecto": None, "nuevo": True, "total": len(actual) + 1}
            if not self.g.hay_datos():
                raise ValueError("No hay carpeta local de datos para guardar el glosario del proyecto.")
            todo = self._leer()
            clave = proyecto.strip().lower()
            lista = todo.get(clave, [])
            if any(x.lower() == t.lower() for x in lista):
                return {"termino": t, "ambito": "proyecto", "proyecto": proyecto, "nuevo": False, "total": len(lista)}
            if len(lista) >= MAX_POR_PROYECTO:
                raise ValueError("El glosario de este proyecto ya tiene el máximo de términos (60).")
            todo[clave] = lista + [t]
            self.g.escribir_datos(FICHERO, json.dumps(todo, ensure_ascii=False, indent=2))
            return {"termino": t, "ambito": "proyecto", "proyecto": proyecto, "nuevo": True, "total": len(lista) + 1}
