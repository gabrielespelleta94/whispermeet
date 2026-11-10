"""Ola C: endpoints del plan de sesiones, en un router propio (`servidor.crear_app` solo lo incluye).

- `GET  /api/proyectos/{n}/plan`: el plan editable (`{plan, version, ficheros_contexto, limites, descartadas}`; `plan` es null si el proyecto no tiene) y la marca `version`.
- `PUT  /api/proyectos/{n}/plan` con `{version, sesiones}`: valida y guarda (`plan_editor.guardar`, vía `Guardian.escribir_plan`) y devuelve lo mismo que el GET. Errores de validación:
  422 con `{detail, errores: [{indice, campo, mensaje}]}` y no se escribe nada; si el fichero cambió desde que se leyó (`version` distinta), 409 y no se escribe.
- `GET  /api/proyectos/{n}/plan/proponer`: lo que leería «Proponer plan» (solo metadatos; no gasta tokens ni abre ficheros).
- `POST /api/proyectos/{n}/plan/proponer` con `{nombres?}`: UNA llamada a `claude -p`; devuelve el borrador y NO guarda nada.

Ninguna respuesta lleva rutas absolutas. La API entera cuelga de `/api/`, así que el middleware de `servidor.py` ya exige el token y el host.
"""
from __future__ import annotations

import asyncio
import threading

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from . import plan_editor as PE
from .analisis.analista import Analista
from .api_archivero import ESTADOS_OCUPADOS, _proyecto_inexistente
from .plan_propuesto import ServicioPlanPropuesto


class SesionIn(BaseModel):
    id: str | None = None
    nombre: str = ""
    fecha: str = ""
    fecha_iso: str = ""
    hora: str = ""
    objetivos: list[str] = []
    checks: list[str] = []
    fichero_prioritario: str = ""
    depende_de: list[str] = []


class PlanIn(BaseModel):
    version: str | None = None   # la marca que recibió el cliente en el GET
    sesiones: list[SesionIn]


class ProponerIn(BaseModel):
    nombres: list[str] = []      # nombres de las sesiones que ya hay en el editor (también las no guardadas): no se repiten


def crear_router(gestor, cfg, guardian, envolver, fabrica_analista=None) -> APIRouter:
    """`fabrica_analista`: devuelve el `Analista` de «Proponer plan» (pruebas: un modelo falso); por defecto, uno propio sobre el modelo del gestor."""
    r = APIRouter()

    def analista_plan():
        if fabrica_analista is not None:
            return fabrica_analista()
        analista = Analista(gestor.llm, cfg, gestor.consumo, guardian, "plan_propuesto")
        gestor.sonda.instrumentar(analista)   # mismo punto único: traza real, medición en consumo y un solo cerrojo para todas las llamadas
        return analista

    servicio = ServicioPlanPropuesto(guardian, cfg, analista_plan)
    en_curso: set[str] = set()
    cerrojo = threading.Lock()
    cerrojo_plan = threading.Lock()   # un guardado a la vez: la comparación de la versión y la escritura no se pisan entre dos peticiones

    def _guardar(nombre: str, b: PlanIn):
        with cerrojo_plan:
            return PE.guardar(guardian, nombre, b.version, [s.model_dump() for s in b.sesiones])

    @r.get("/api/proyectos/{nombre}/plan")
    @envolver
    @_proyecto_inexistente
    async def plan_leer(nombre: str):
        return await asyncio.to_thread(PE.leer, guardian, nombre)

    @r.put("/api/proyectos/{nombre}/plan")
    @envolver
    @_proyecto_inexistente
    async def plan_guardar(nombre: str, b: PlanIn):
        try:
            return await asyncio.to_thread(_guardar, nombre, b)
        except PE.PlanInvalido as e:
            return JSONResponse(status_code=422, content={"detail": str(e), "errores": e.errores})
        except PE.ConflictoPlan as e:
            return JSONResponse(status_code=409, content={"detail": str(e)})

    @r.get("/api/proyectos/{nombre}/plan/proponer")
    @envolver
    @_proyecto_inexistente
    async def proponer_estado(nombre: str):
        return await asyncio.to_thread(servicio.estado, nombre)

    @r.post("/api/proyectos/{nombre}/plan/proponer")
    @envolver
    @_proyecto_inexistente
    async def proponer(nombre: str, b: ProponerIn | None = None):
        if gestor.estado in ESTADOS_OCUPADOS:
            raise ValueError("Hay una reunión en curso: propón el plan cuando termine, para no retrasar las llamadas del equipo.")
        clave = nombre.lower()
        with cerrojo:
            if clave in en_curso:
                raise ValueError("Ya se está proponiendo un plan para este proyecto: espera a que termine.")
            en_curso.add(clave)
        try:
            def _todo():
                guardados = [s["nombre"] for s in ((PE.leer(guardian, nombre)["plan"] or {}).get("sesiones") or [])]
                return servicio.proponer(nombre, guardados + list(b.nombres if b else []))
            return await asyncio.to_thread(_todo)
        finally:
            with cerrojo:
                en_curso.discard(clave)

    r.servicio = servicio   # para las pruebas
    return r
