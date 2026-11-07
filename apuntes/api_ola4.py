"""Endpoints de la ola 4 (confianza y escala). Un `APIRouter` que `servidor.crear_app` monta con una sola línea.

Contrato completo (rutas, cuerpos, respuestas y eventos del WebSocket) en `demo/api-ola4.md`.
"""
from __future__ import annotations

import asyncio
import re

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from . import cartera as CA
from . import correccion as CORR
from . import metricas as MT
from .glosario import limpiar_termino

RE_MONITOR = re.compile(r"m\d{1,6}")
RE_TARJETA = re.compile(r"t\d{1,5}-[0-9a-f]{4}")


class GlosarioIn(BaseModel):
    termino: str
    proyecto: str | None = None     # None = vocabulario global; con proyecto, el de ese proyecto


class CorregirIn(BaseModel):
    texto: str
    glosario: str | None = None     # None | "global" | "proyecto": añade al glosario lo que el usuario cambió (o `termino`)
    termino: str | None = None      # si se da, es lo que se añade al glosario en vez de las palabras cambiadas


class MalIn(BaseModel):
    motivo: str = ""


class ModoLocalIn(BaseModel):
    activo: bool


def crear_router(gestor, cfg, guardian, bl, envolver) -> APIRouter:
    r = APIRouter()

    def _sesion():
        if gestor.sesion is None:
            raise ValueError("No hay reunión en curso.")
        return gestor.sesion

    # ------------------------------------------------------------ 1. confianza de Whisper y glosario
    @r.post("/api/glosario")
    @envolver
    async def glosario_anadir(b: GlosarioIn):
        res = await asyncio.to_thread(gestor.glosario.anadir, b.termino, b.proyecto)
        if gestor.transcriptor is not None:
            gestor._actualizar_vocabulario()   # vale ya para lo que queda de la reunión en curso
        gestor.emitir("glosario", **res)
        return res

    @r.post("/api/sesion/segmento/{ident}/corregir")
    @envolver
    async def segmento_corregir(ident: int, b: CorregirIn):
        s = _sesion()
        res = CORR.corregir_segmento(s, gestor.equipo, ident, b.texto)
        glosario = []
        if b.glosario:
            if b.glosario not in ("global", "proyecto"):
                raise ValueError("El glosario debe ser «global» o «proyecto».")
            if b.glosario == "proyecto" and not s.proyecto:
                raise ValueError("Esta reunión no tiene proyecto: usa el glosario global.")
            candidatos = [b.termino] if b.termino else [n for _v, n in res["sustituciones"]]
            for t in candidatos:
                try:
                    limpiar_termino(t)
                except ValueError:
                    continue   # una frase larga no es un término del glosario
                glosario.append(await asyncio.to_thread(gestor.glosario.anadir, t, s.proyecto if b.glosario == "proyecto" else None))
            if glosario and gestor.transcriptor is not None:
                gestor._actualizar_vocabulario()
        await asyncio.to_thread(s.guardar)
        gestor.emitir("segmento_corregido", segmento=res["segmento"], sustituciones=res["sustituciones"], propagado=res["propagado"])
        cambios = s.recoger_cambios_eco()
        if cambios:
            gestor.emitir("segmento_eco", cambios=cambios)
        p = res["propagado"]
        if p["tarjetas"] or p["resumen"]:
            gestor.emitir("tarjetas", nuevas=[], todas=[dict(t) for t in s.tarjetas], resumen=s.resumen_acumulado)
        if p["definiciones"]:
            gestor.emitir("definiciones", definiciones=gestor.equipo.definiciones.publico())
        return {**res, "glosario": glosario}

    # ------------------------------------------------------------ 2. «Esto está mal»
    @r.post("/api/avisos/{ident}/mal")
    @envolver
    async def aviso_mal(ident: str, b: MalIn | None = None):
        s = _sesion()
        reglas = gestor.reglas_silencio
        if RE_MONITOR.fullmatch(ident):
            e = next((x for x in gestor.equipo.monitor.feed if x.get("id") == ident), None)
            if e is None:
                raise HTTPException(404, "Ese aviso ya no está.")
            if not e.get("regla_tipo"):
                raise ValueError("Este aviso no se puede silenciar.")
            regla = await asyncio.to_thread(reglas.anadir, e["regla_tipo"], e["regla_texto"], e["texto"], s.id)
            e["silenciado"] = True
            gestor.emitir("aviso_silenciado", id=ident, origen="monitor", regla=regla)
            return {"id": ident, "origen": "monitor", "regla": regla}
        if RE_TARJETA.fullmatch(ident):
            t = next((x for x in s.tarjetas if x.get("id") == ident), None)
            if t is None:
                raise HTTPException(404, "Esa tarjeta ya no está.")
            regla = await asyncio.to_thread(reglas.anadir, "tarjeta:" + t["categoria"], t["texto"], t["texto"], s.id)
            t["mal"] = True
            await asyncio.to_thread(s.guardar)
            gestor.emitir("aviso_silenciado", id=ident, origen="tarjeta", regla=regla)
            gestor.emitir("tarjetas", nuevas=[], todas=[dict(x) for x in s.tarjetas], resumen=s.resumen_acumulado)
            return {"id": ident, "origen": "tarjeta", "regla": regla}
        raise ValueError("Solo se pueden marcar como «mal» los avisos del Monitor (m…) y las tarjetas de los perfiles (t…).")

    @r.get("/api/reglas-silencio")
    @envolver
    async def reglas_listar():
        lista = await asyncio.to_thread(gestor.reglas_silencio.listar)
        return {"reglas": lista, "total": len(lista)}

    @r.delete("/api/reglas-silencio/{ident}")
    @envolver
    async def regla_borrar(ident: str):
        if not re.fullmatch(r"[0-9a-f]{12}", ident):
            raise ValueError("Identificador no válido.")
        if not await asyncio.to_thread(gestor.reglas_silencio.borrar, ident):
            raise HTTPException(404, "Esa regla no existe.")
        gestor.emitir("regla_silencio_borrada", id=ident)
        return {"ok": True, "id": ident}

    # ------------------------------------------------------------ 3. registro de envíos y modo solo local
    @r.get("/api/envios")
    @envolver
    async def envios_listar(sesion: str | None = None, limite: int = 500):
        limite = max(1, min(int(limite), 5000))
        lista = await asyncio.to_thread(gestor.envios.listar, sesion, limite)
        return {"sesion": sesion, "envios": lista, "resumen": gestor.envios.resumir(lista),
                "sesiones": [] if sesion else await asyncio.to_thread(gestor.envios.por_sesion)}

    @r.get("/api/envios/resumen")
    @envolver
    async def envios_resumen():
        return {"sesiones": await asyncio.to_thread(gestor.envios.por_sesion)}

    @r.get("/api/modo-local")
    @envolver
    async def modo_local_estado():
        return gestor.modo_local_publico()

    @r.post("/api/modo-local")
    @envolver
    async def modo_local_poner(b: ModoLocalIn):
        """Sin reunión, cambia el valor por defecto (`modo_local` de la configuración); con reunión, el de ESA reunión."""
        return gestor.poner_modo_local(b.activo)

    @r.post("/api/revision/agentes")
    @envolver
    async def revision_agentes():
        """Confirma lanzar los agentes del cierre en una reunión en modo solo local (resumen final y cambios al contexto)."""
        return await gestor.lanzar_agentes_cierre()

    # ------------------------------------------------------------ 4. plantillas de reunión
    @r.get("/api/plantillas")
    @envolver
    async def plantillas_listar():
        return {"plantillas": await asyncio.to_thread(gestor.plantillas.listar)}

    @r.post("/api/plantillas")
    @envolver
    async def plantilla_anadir(b: dict):
        return {"plantilla": await asyncio.to_thread(gestor.plantillas.anadir, b)}

    @r.delete("/api/plantillas/{ident}")
    @envolver
    async def plantilla_borrar(ident: str):
        if not await asyncio.to_thread(gestor.plantillas.borrar, ident):
            raise HTTPException(404, "No hay una plantilla propia con ese identificador (las de base no se borran).")
        return {"ok": True, "id": ident}

    # ------------------------------------------------------------ 5. cartera
    @r.get("/api/cartera")
    @envolver
    async def cartera(refrescar: bool = False):
        return await asyncio.to_thread(CA.cartera, bl, cfg["cartera_ventana_dias"], cfg["cartera_pendiente_antiguo_dias"], refrescar, gestor.metricas)

    # ------------------------------------------------------------ 6. métricas de valor
    @r.get("/api/proyectos/{nombre}/metricas")
    @envolver
    async def proyecto_metricas(nombre: str):
        regs = await asyncio.to_thread(gestor.metricas.de_proyecto, nombre)
        return {"proyecto": nombre, **MT.agregar(regs)}

    @r.get("/api/sesion/metricas")
    @envolver
    async def sesion_metricas():
        s = _sesion()
        envios = gestor.envios.resumir(gestor.envios.listar(s.id, 100_000)) if gestor.g.hay_datos() else None
        return MT.de_sesion(s, gestor.equipo, list(gestor.consumo.llamadas), envios, modo_local=bool(gestor.modo_local_sesion))

    return r
