"""Medición de consumo por llamada a `claude -p`. El log local NO contiene contenido de reuniones."""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path


class Consumo:
    def __init__(self, ruta_log: Path | None):
        self.ruta = ruta_log
        self._lock = threading.Lock()
        self.por_modelo: dict[str, dict] = {}
        self.llamadas: list[dict] = []  # sin contenido: tarea, modelos, tokens, ms
        self.contexto = None  # () -> dict: cadencia de la sesión y motivo del análisis en curso (el Gestor lo pone al empezar); sin contenido de reuniones

    def reiniciar(self) -> None:
        with self._lock:
            self.por_modelo, self.llamadas = {}, []

    def registrar(self, sesion: str, tarea: str, uso_lista, ms: int, ok: bool, error: str = "") -> None:
        with self._lock:
            for u in uso_lista:
                m = self.por_modelo.setdefault(u.modelo, {"llamadas": 0, "entrada": 0, "salida": 0,
                                                          "cache_creacion": 0, "cache_lectura": 0})
                m["llamadas"] += 1
                m["entrada"] += u.entrada
                m["salida"] += u.salida
                m["cache_creacion"] += u.cache_creacion
                m["cache_lectura"] += u.cache_lectura
            reg = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "sesion": sesion, "tarea": tarea, "ok": ok, "ms": ms,
                   "error": error,
                   "uso": [{"modelo": u.modelo, "entrada": u.entrada, "salida": u.salida,
                            "cache_creacion": u.cache_creacion, "cache_lectura": u.cache_lectura,
                            "razonamiento": u.razonamiento, "coste_ref_usd": round(u.coste_ref_usd, 6)} for u in uso_lista]}
            if self.contexto:   # con qué cadencia y por qué se llamó: así un registro sin turnos se puede explicar (a petición, señales, rotación…)
                try:
                    reg.update({k: v for k, v in self.contexto().items() if v})
                except Exception:  # noqa: BLE001  (medir nunca rompe la llamada)
                    pass
            self.llamadas.append(reg)
            if self.ruta:
                try:
                    self.ruta.parent.mkdir(parents=True, exist_ok=True)
                    with open(self.ruta, "a", encoding="utf-8") as f:
                        f.write(json.dumps(reg, ensure_ascii=False) + "\n")
                except OSError:
                    pass

    def resumen(self) -> dict:
        with self._lock:
            tot = {"llamadas": 0, "entrada": 0, "salida": 0, "cache_creacion": 0, "cache_lectura": 0}
            for m in self.por_modelo.values():
                for k in tot:
                    tot[k] += m[k]
            return {"por_modelo": {k: dict(v) for k, v in self.por_modelo.items()}, "total": tot,
                    "llamadas": len(self.llamadas)}
