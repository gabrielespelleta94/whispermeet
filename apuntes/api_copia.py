"""Ola F: endpoints de la copia de seguridad de los datos de la app, en un router propio (`servidor.crear_app` solo lo incluye).

- `GET  /api/copia`: `{copias: [{nombre, bytes, fecha}], carpeta}`, las más recientes primero (`carpeta` es solo el nombre de la carpeta, nunca la ruta).
- `POST /api/copia`: crea una copia (`copia.crear_copia`, en un hilo: el disco no corre en el bucle de asyncio) y devuelve su resultado. Durante una reunión, 409
  «Haz la copia fuera de una reunión.» (no se compite con la transcripción por el disco); con otra copia en marcha, 409 «Ya hay una copia en curso.». Un fallo inesperado
  sale como «No se pudo crear la copia.» (sin traza; el detalle queda en `datos/apuntes.log`). El cerrojo se coge y se suelta DENTRO de la función del hilo: si la petición se
  cancela con la copia en marcha, el cerrojo sigue cogido hasta que el hilo acaba.
- `POST /api/copia/abrir`: abre la carpeta de copias con el explorador (la crea si falta); sirve también durante una reunión, porque no escribe nada más.

La API cuelga de `/api/`: el middleware de `servidor.py` ya exige el token y el host.
"""
from __future__ import annotations

import asyncio
import threading

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from . import copia as C
from .api_archivero import ESTADOS_OCUPADOS
from .registro import registrar_error
from .rutas import RutaProhibida


class CopiaEnCurso(Exception):
    """Ya hay otra copia escribiendo (la lanza la función del hilo si no puede coger el cerrojo)."""


def crear_router(gestor, cfg, guardian, envolver, abridor=None) -> APIRouter:
    """`abridor` sustituye a `os.startfile` (pruebas: no se abre nada de verdad)."""
    r = APIRouter()
    cerrojo = threading.Lock()   # una copia a la vez

    def copiar_en_hilo():
        if not cerrojo.acquire(blocking=False):
            raise CopiaEnCurso()
        try:
            return C.crear_copia(guardian)
        finally:
            cerrojo.release()
    r.copiar_en_hilo, r.cerrojo = copiar_en_hilo, cerrojo   # (pruebas)

    @r.get("/api/copia")
    @envolver
    async def copia_listar():
        copias = await asyncio.to_thread(guardian.listar_copias)
        return {"copias": copias, "carpeta": guardian.copias.name}

    @r.post("/api/copia")
    @envolver
    async def copia_crear():
        if gestor.estado in ESTADOS_OCUPADOS:
            return JSONResponse(status_code=409, content={"detail": "Haz la copia fuera de una reunión."})
        try:
            return await asyncio.to_thread(copiar_en_hilo)
        except CopiaEnCurso:
            return JSONResponse(status_code=409, content={"detail": "Ya hay una copia en curso."})
        except RutaProhibida:
            raise   # lo traduce `envolver` (403)
        except OSError as e:
            raise ValueError(f"No se pudo crear la copia: {e.strerror or e}")
        except Exception as e:   # noqa: BLE001  (nada inesperado llega al cliente con traza)
            registrar_error("api_copia.copia_crear", e)
            raise ValueError("No se pudo crear la copia. El detalle queda en el registro de la app.")

    @r.post("/api/copia/abrir")
    @envolver
    async def copia_abrir():
        try:
            await asyncio.to_thread(guardian.abrir_carpeta_copias, abridor)
        except OSError as e:
            raise ValueError(f"No se pudo abrir la carpeta: {e.strerror or e}")
        return {"ok": True}

    return r
