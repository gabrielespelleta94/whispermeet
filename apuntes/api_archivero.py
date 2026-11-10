"""Ola B: endpoints del Agente Archivero, en un router propio (`servidor.crear_app` solo lo incluye).

- `GET  /api/proyectos/{n}/archivero`: `{plan, resultado}`. Sin tokens y sin abrir ficheros: el plan sale del mapa de documentos (solo metadatos) y el resultado es
  solo lo cacheado (o null).
- `POST /api/proyectos/{n}/archivero` (`?refrescar=1`): lee los documentos del plan, hace UNA llamada y devuelve el resultado.
- `POST /api/proyectos/{n}/archivero/guardar`: con `{"confirmar": false}` (por defecto) devuelve la vista previa del Markdown; con `{"confirmar": true, "huella": …}` (la `huella` de la vista previa)
  lo escribe en `00. CONTEXTO (IA)` y anota el cambio en `10-registro-de-cambios.md`; si lo que se escribiría ya no coincide con esa huella responde 409 con
  la vista previa nueva (`previa`) y no escribe.

Ninguna respuesta lleva rutas absolutas. La API entera cuelga de `/api/`, así que el middleware de `servidor.py` ya exige el token y el host.
"""
from __future__ import annotations

import asyncio
import functools
import threading

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from .analisis.analista import Analista
from .archivero import ResultadoCambiado, ServicioArchivero
from .rutas import RutaProhibida

ESTADOS_OCUPADOS = ("preparando", "grabando", "pausada", "terminando")


class GuardarIn(BaseModel):
    confirmar: bool = False
    huella: str | None = None   # la `huella` de la vista previa que se enseñó; con `confirmar` es obligatoria


def _proyecto_inexistente(fn):
    """Un proyecto que no existe es un 404 (el `envolver` del servidor convierte el resto de `RutaProhibida` en un 403)."""
    @functools.wraps(fn)
    async def _w(*a, **k):
        try:
            return await fn(*a, **k)
        except RutaProhibida as e:
            if "no existe" in str(e):
                raise HTTPException(404, "No existe ese proyecto.")
            raise
    return _w


def crear_router(gestor, cfg, guardian, envolver, fabrica_analista=None) -> APIRouter:
    """`fabrica_analista`: devuelve el `Analista` del Archivero (pruebas: un modelo falso); por defecto, uno propio sobre el modelo del gestor."""
    r = APIRouter()

    def analista_archivero():
        if fabrica_analista is not None:
            return fabrica_analista()
        analista = Analista(gestor.llm, cfg, gestor.consumo, guardian, "archivero")
        gestor.sonda.instrumentar(analista)   # mismo punto único: traza real, medición en consumo y un solo cerrojo para todas las llamadas
        return analista

    servicio = ServicioArchivero(guardian, cfg, analista_archivero)
    en_curso: set[str] = set()
    cerrojo = threading.Lock()

    @r.get("/api/proyectos/{nombre}/archivero")
    @envolver
    @_proyecto_inexistente
    async def archivero_estado(nombre: str):
        return await asyncio.to_thread(servicio.estado, nombre)

    @r.post("/api/proyectos/{nombre}/archivero")
    @envolver
    @_proyecto_inexistente
    async def archivero_analizar(nombre: str, refrescar: int = 0):
        if gestor.estado in ESTADOS_OCUPADOS:
            raise ValueError("Hay una reunión en curso: lanza el Archivero cuando termine, para no retrasar las llamadas del equipo.")
        clave = nombre.lower()
        with cerrojo:
            if clave in en_curso:
                raise ValueError("El Archivero ya está analizando este proyecto: espera a que termine.")
            en_curso.add(clave)
        try:
            return await asyncio.to_thread(servicio.analizar, nombre, bool(refrescar))
        finally:
            with cerrojo:
                en_curso.discard(clave)

    @r.post("/api/proyectos/{nombre}/archivero/guardar")
    @envolver
    @_proyecto_inexistente
    async def archivero_guardar(nombre: str, b: GuardarIn | None = None):
        try:
            return await asyncio.to_thread(servicio.guardar, nombre, bool(b and b.confirmar), b.huella if b else None)
        except ResultadoCambiado as e:   # lo que se guardaría ya no es lo que se enseñó: no se escribe y se devuelve la vista previa nueva
            return JSONResponse(status_code=409, content={"detail": str(e), "previa": e.vista})

    r.servicio = servicio   # para las pruebas
    return r
