"""Registro de envíos y modo solo local (ola 4).

TODA llamada al modelo (`claude -p`) pasa por `ModeloVigilado`, que envuelve a la implementación real en el Gestor. Es el ÚNICO punto donde se hacen dos cosas:
- **Modo solo local**: si está activo (`modo_local` de la configuración, o el de la sesión en curso), la llamada NO se hace: se lanza `ErrorAnalisis("local")` y se
  anota el intento como bloqueado. Ningún agente, ni el cierre, ni «Pregúntale», ni «Profundizar» pueden saltárselo: no hay otro camino hasta el modelo.
- **Registro de envíos**: cada llamada que sí sale deja una línea en `envios.jsonl` (carpeta local de datos, solo vía Guardian) con fecha, sesión, agente/tarea,
  modelo, caracteres enviados, tokens de entrada y de salida y un extracto corto (≤120 caracteres) de lo que salió. Es lo que el usuario consulta para saber qué
  salió de su máquina. Esa carpeta está fuera de git.

La tarea la anota `Analista._llamar` (el punto único de las llamadas) con `marcar_tarea` justo antes de llamar al modelo.
"""
from __future__ import annotations

import json
import threading
import time

from .analisis import ErrorAnalisis, ModeloLLM, Respuesta
from .rutas import RutaProhibida

FICHERO = "envios.jsonl"
EXTRACTO_MAX = 120
MENSAJE_LOCAL = ("Modo solo local: no se envía nada a Claude. La transcripción y el Monitor siguen funcionando; "
                 "desactiva el modo solo local para usar los agentes.")

_ctx = threading.local()


def marcar_tarea(tarea: str) -> None:
    """La anota `Analista._llamar` antes de llamar al modelo (hilo propio de cada llamada)."""
    _ctx.tarea = tarea


def tarea_actual() -> str:
    return getattr(_ctx, "tarea", "") or ""


def agente_de(tarea: str) -> str:
    from .orquesta import AGENTES
    return AGENTES.get(tarea, ("", tarea or "Otra tarea"))[1]


def extracto(usuario: str) -> str:
    """Primeros caracteres de lo enviado (sin saltos ni marcas de datos), para reconocer la llamada sin guardar el contenido entero."""
    t = " ".join(str(usuario or "").replace("<<<", " ").replace(">>>", " ").split())
    return t[:EXTRACTO_MAX]


def tokens_de(uso_lista) -> tuple[int, int]:
    """(entrada con caché, salida) de las medidas de una respuesta."""
    entrada = sum(u.entrada + u.cache_creacion + u.cache_lectura for u in uso_lista)
    return entrada, sum(u.salida for u in uso_lista)


class RegistroEnvios:
    def __init__(self, guardian):
        self.g = guardian
        self._lock = threading.Lock()

    def registrar(self, reg: dict) -> None:
        if not self.g.hay_datos():
            return
        try:
            with self._lock:
                self.g.anadir_datos(FICHERO, json.dumps(reg, ensure_ascii=False))
        except (OSError, RutaProhibida):
            pass   # medir nunca rompe la llamada

    def listar(self, sesion: str | None = None, limite: int = 500) -> list[dict]:
        try:
            texto = self.g.leer_datos(FICHERO) or ""
        except (OSError, RutaProhibida):
            return []
        out = []
        for linea in texto.splitlines():
            try:
                r = json.loads(linea)
            except ValueError:
                continue
            if isinstance(r, dict) and (not sesion or r.get("sesion") == sesion):
                out.append(r)
        return out[-max(1, limite):]

    @staticmethod
    def resumir(envios: list[dict]) -> dict:
        """Totales y desglose por agente de una lista de envíos."""
        r = {"llamadas": 0, "enviadas": 0, "bloqueadas": 0, "errores": 0, "chars": 0, "entrada": 0, "salida": 0, "por_agente": {}}
        for e in envios:
            r["llamadas"] += 1
            if e.get("bloqueado"):
                r["bloqueadas"] += 1
                continue
            r["enviadas"] += 1
            if not e.get("ok", True):
                r["errores"] += 1
            for k in ("chars", "entrada", "salida"):
                r[k] += int(e.get(k) or 0)
            a = r["por_agente"].setdefault(e.get("agente") or e.get("tarea") or "?", {"llamadas": 0, "chars": 0, "entrada": 0, "salida": 0})
            a["llamadas"] += 1
            for k in ("chars", "entrada", "salida"):
                a[k] += int(e.get(k) or 0)
        return r

    def por_sesion(self) -> list[dict]:
        """Resumen de cada sesión con envíos, de la más reciente a la más antigua."""
        grupos: dict[str, list[dict]] = {}
        for e in self.listar(None, 100_000):
            grupos.setdefault(e.get("sesion") or "", []).append(e)
        out = []
        for sid, lista in grupos.items():
            out.append({"sesion": sid, "primera": lista[0].get("ts"), "ultima": lista[-1].get("ts"), **self.resumir(lista)})
        return sorted(out, key=lambda x: x["ultima"] or "", reverse=True)


class ModeloVigilado(ModeloLLM):
    """Envuelve al modelo real: impone el modo solo local y registra cada envío. `gestor` da `modo_local_activo()`, `sesion` y `emitir`."""

    def __init__(self, interno: ModeloLLM, gestor):
        self.interno, self.gestor = interno, gestor

    def __getattr__(self, nombre):   # lo que no es de esta capa (p. ej. `exe` de ClaudeCLI) es del modelo real
        return getattr(self.interno, nombre)

    def _reg(self, tarea: str, modelo: str, chars: int, usuario: str, **extra) -> dict:
        s = self.gestor.sesion
        return {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "sesion": s.id if s else "", "agente": agente_de(tarea), "tarea": tarea or "otra",
                "modelo": modelo, "chars": chars, "extracto": extracto(usuario), **extra}

    def _anotar(self, reg: dict) -> None:
        try:
            self.gestor.envios.registrar(reg)
            self.gestor.emitir("envio", **reg)
        except Exception:  # noqa: BLE001  (el registro nunca detiene el análisis)
            pass

    def completar(self, sistema: str, usuario: str, modelo: str, esfuerzo: str = "", timeout_s: int = 240,
                  sin_razonamiento: bool = False, **extra) -> Respuesta:
        tarea = tarea_actual()
        marcar_tarea("")   # la siguiente llamada que no pase por `Analista._llamar` no hereda esta tarea
        chars = len(sistema or "") + len(usuario or "")
        if self.gestor.modo_local_activo():
            self._anotar(self._reg(tarea, modelo, 0, "", bloqueado=True, ok=False, entrada=0, salida=0, error="local"))
            raise ErrorAnalisis("local", MENSAJE_LOCAL, transitorio=False)
        try:
            r = self.interno.completar(sistema, usuario, modelo, esfuerzo, timeout_s, sin_razonamiento, **extra)
        except ErrorAnalisis as e:
            self._anotar(self._reg(tarea, modelo, chars, usuario, bloqueado=False, ok=False, entrada=0, salida=0, error=e.tipo))
            raise
        entrada, salida = tokens_de(r.uso)
        self._anotar(self._reg(tarea, modelo, chars, usuario, bloqueado=False, ok=True, entrada=entrada, salida=salida, ms=r.ms))
        return r
