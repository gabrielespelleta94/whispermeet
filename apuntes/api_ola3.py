"""Ola 3 (capa agéntica): endpoints nuevos en un router propio. `servidor.crear_app` solo lo incluye (`include_router`).

- Acciones propuestas de la reunión: `/api/acciones…` (aceptar, editar, descartar, reabrir, hecha).
- Autonomía por tipo: `/api/autonomia`.
- Brief de preparación: `/api/proyectos/{n}/brief`.
- Seguimiento de pendientes entre sesiones: `/api/proyectos/{n}/seguimiento…`.
- Borrador de correo para Outlook: `/api/correo/outlook` (un `.eml` con `X-Unsent: 1`; nunca se envía).

Todo local. La API entera cuelga de `/api/`, así que el middleware de `servidor.py` ya exige el token y el host.
"""
from __future__ import annotations

import asyncio
import functools

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from . import correo_outlook as CO
from .analisis.analista import Analista
from .brief import ServicioBrief
from .config import AUTONOMIA_POR_DEFECTO, HACER_ADMITIDO, NIVELES_AUTONOMIA, TIPOS_ACCION, TIPOS_AUTONOMIA, validar_autonomia
from .rutas import RutaProhibida
from .seguimiento import Seguimiento


class AccionIn(BaseModel):
    tipo: str
    texto: str
    origen: str = "Tú"
    cita: dict | None = None
    datos: dict | None = None
    prioridad: str = "normal"


class AccionEditarIn(BaseModel):
    texto: str | None = None
    datos: dict | None = None
    cita: dict | None = None
    quitar_cita: bool = False


class AccionAceptarIn(BaseModel):
    texto: str | None = None      # «Editar y aceptar» en un solo paso
    datos: dict | None = None


class AutonomiaIn(BaseModel):
    autonomia: dict[str, str]     # {tipo: avisar|proponer|hacer}; solo los tipos que cambian


class HechoIn(BaseModel):
    cita: dict | None = None      # opcional: la `cierre_propuesto` que el usuario acepta


class OutlookIn(BaseModel):
    asunto: str
    cuerpo: str
    para: str | list[str] | None = None


def crear_router(gestor, cfg, guardian, backlog, abridor=None, fabrica_analista=None) -> APIRouter:
    """`abridor`: sustituye a `os.startfile` (pruebas: no se abre nada). `fabrica_analista`: devuelve el `Analista` del brief (pruebas: un modelo falso)."""
    r = APIRouter()
    acc = gestor.acciones
    seg = Seguimiento(guardian, backlog, cfg)
    gestor.seguimiento = seg   # el Gestor lo usa en el cierre de la revisión

    def analista_brief():
        if fabrica_analista is not None:
            return fabrica_analista()
        if gestor.sesion is not None and gestor.analista is not None:
            return gestor.analista   # con una reunión en curso, la llamada pasa por el punto único (en serie con los turnos)
        return Analista(gestor.llm, cfg, gestor.consumo, guardian, "brief")

    brief = ServicioBrief(guardian, cfg, backlog, seg, analista_brief)

    def envolver(fn):
        @functools.wraps(fn)
        async def _w(*a, **k):
            try:
                return await fn(*a, **k)
            except LookupError as e:
                raise HTTPException(404, str(e))
            except ValueError as e:
                raise HTTPException(400, str(e))
            except RutaProhibida as e:
                if "no existe" in str(e):
                    raise HTTPException(404, "Ese proyecto no existe.")
                raise HTTPException(403, f"Operación no permitida: {e}")
        return _w

    # ------------------------------------------------------------ acciones propuestas
    def _estado() -> dict:
        return {"acciones": acc.listar(), "autonomia": dict(cfg["autonomia"]), "en_reunion": gestor.sesion is not None}

    @r.get("/api/acciones")
    @envolver
    async def acciones_listar():
        return _estado()

    @r.post("/api/acciones")
    @envolver
    async def acciones_crear(b: AccionIn):
        a = acc.crear(b.tipo, b.texto, b.origen, b.cita, b.datos, b.prioridad)
        if a is None:
            raise ValueError("Ya hay una acción igual.")
        return a

    @r.put("/api/acciones/{ident}")
    @envolver
    async def acciones_editar(ident: str, b: AccionEditarIn):
        return acc.editar(ident, b.texto, b.datos, None if b.quitar_cita else (b.cita if b.cita is not None else "__no__"))

    @r.post("/api/acciones/{ident}/aceptar")
    @envolver
    async def acciones_aceptar(ident: str, b: AccionAceptarIn | None = None):
        return acc.aceptar(ident, b.texto if b else None, b.datos if b else None)

    @r.post("/api/acciones/{ident}/descartar")
    @envolver
    async def acciones_descartar(ident: str):
        return acc.descartar(ident)

    @r.post("/api/acciones/{ident}/reabrir")
    @envolver
    async def acciones_reabrir(ident: str):
        return acc.reabrir(ident)

    @r.post("/api/acciones/{ident}/hecha")
    @envolver
    async def acciones_hecha(ident: str):
        return acc.hecha(ident)

    # ------------------------------------------------------------ autonomía por tipo
    def _autonomia() -> dict:
        return {"autonomia": dict(cfg["autonomia"]), "defecto": dict(AUTONOMIA_POR_DEFECTO), "tipos": list(TIPOS_AUTONOMIA), "tipos_accion": list(TIPOS_ACCION),
                "niveles": list(NIVELES_AUTONOMIA), "hacer_admitido": list(HACER_ADMITIDO)}

    @r.get("/api/autonomia")
    @envolver
    async def autonomia_leer():
        return _autonomia()

    @r.put("/api/autonomia")
    @envolver
    async def autonomia_poner(b: AutonomiaIn):
        nueva = validar_autonomia(b.autonomia, cfg["autonomia"])   # ValueError -> 400: «hacer» solo en lo local y reversible
        cfg.actualizar({"autonomia": nueva})
        return _autonomia()

    # ------------------------------------------------------------ brief de preparación
    @r.get("/api/proyectos/{nombre}/brief")
    @envolver
    async def proyecto_brief(nombre: str, refrescar: int = 0):
        return await asyncio.to_thread(brief.generar, nombre, bool(refrescar))

    # ------------------------------------------------------------ seguimiento de pendientes entre sesiones
    @r.get("/api/proyectos/{nombre}/seguimiento")
    @envolver
    async def seguimiento_listar(nombre: str, refrescar: int = 0):
        return await asyncio.to_thread(seg.lista, nombre, bool(refrescar), True)

    @r.post("/api/proyectos/{nombre}/seguimiento/{iid}/reabrir")
    @envolver
    async def seguimiento_reabrir(nombre: str, iid: str):
        return await asyncio.to_thread(seg.reabrir, nombre, iid)

    @r.post("/api/proyectos/{nombre}/seguimiento/{iid}/hecho")
    @envolver
    async def seguimiento_hecho(nombre: str, iid: str, b: HechoIn | None = None):
        return await asyncio.to_thread(seg.marcar_hecho, nombre, iid, b.cita if b else None)

    # ------------------------------------------------------------ Outlook: borrador, nunca envío
    @r.post("/api/correo/outlook")
    @envolver
    async def correo_outlook(b: OutlookIn):
        return await asyncio.to_thread(CO.abrir_borrador, guardian, b.asunto, b.cuerpo, b.para, abridor)

    r.servicio_acciones, r.seguimiento, r.brief = acc, seg, brief   # para las pruebas
    return r
