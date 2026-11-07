"""Montaje común de los tests de la ola 4: gestor con modelo falso (cuenta las llamadas), datos temporales y cliente HTTP. Sin red, sin audio, sin datos reales."""
from __future__ import annotations

import asyncio
import json
import shutil
import time
from pathlib import Path

from fastapi.testclient import TestClient

from apuntes.analisis import ErrorAnalisis, ModeloLLM, Respuesta, Uso
from apuntes.backlog import Backlog
from apuntes.config import Config
from apuntes.consumo import Consumo
from apuntes.gestor import Gestor
from apuntes.rutas import Guardian
from apuntes.servidor import Difusor, crear_app
from apuntes.simulador import LineaSim

PRUEBAS = Path(__file__).resolve().parent.parent / "pruebas" / "proyectos"
PROYECTO = "Proyecto Ficticio Alfa"
PUERTO, TOKEN = 8147, "t0k3n-ola4"


class Falso(ModeloLLM):
    """Responde a los prompts de siempre con JSON válido y registra cada llamada (`llamadas`: sistema, usuario, modelo)."""

    def __init__(self):
        self.llamadas = []
        self.error = None

    def completar(self, sistema, usuario, modelo, esfuerzo="", timeout_s=240, sin_razonamiento=False, **extra):
        self.llamadas.append((sistema, usuario, modelo))
        if self.error:
            raise self.error
        uso = [Uso(modelo, 100, 20)]
        if "compactar el contexto" in sistema:
            return Respuesta(json.dumps({"digest": "[02-alcance.md] SAP fuera de alcance."}), uso)
        if "análisis incremental" in sistema:
            return Respuesta(json.dumps({
                "resumen": "Se habló de SAP.",
                "t": [{"k": "decision", "x": "El piloto sigue el 20 de enero", "m": "01:55"},
                      {"k": "pendiente", "x": "Estimar SAP", "m": "04:05", "r": "Luis"}],
                "c": [{"x": "Meter SAP en fase 1", "m": "02:10", "q": "Integración con SAP fuera de alcance"}]}), uso)
        if "verificar candidatas" in sistema:
            return Respuesta(json.dumps({"v": [{"i": 0, "ok": True, "x": "Contradice el alcance"}]}), uso)
        if "cierre de la reunión" in sistema:
            return Respuesta(json.dumps({"resumen": "Resumen final.", "cambios": []}), uso)
        return Respuesta(json.dumps({"tarjetas": [], "t": [], "e": "tema"}), uso)


def lineas(n=60, texto=None):
    """Cada línea con palabras distintas (si no, el filtro de eco quitaría de Micro lo que Reunión ya dijo)."""
    return [LineaSim(i * 5.0, "reunion" if i % 2 else "yo", texto or " ".join(f"palabra{i}x{j}" for j in range(12))) for i in range(n)]


def montar(tmp_path, llm=None, simulacion=None, velocidad=200, cfg_extra=None, datos=True, con_proyecto=True):
    """-> (gestor, llm, eventos, g, cfg). `datos=False`: sin carpeta local de datos (para comprobar que nada se rompe)."""
    raiz = tmp_path / "proyectos"
    if con_proyecto:
        shutil.copytree(PRUEBAS, raiz)
    else:
        raiz.mkdir()
    g = Guardian(raiz, tmp_path / "bandeja", tmp_path / "cache", sesiones_locales=tmp_path / "sesiones", backlog=tmp_path / "backlog",
                 datos=(tmp_path / "datos-app") if datos else None)
    cfg = Config(tmp_path / "config.json")
    cfg.actualizar({"raiz_proyectos": str(raiz), "knowledge": "", "proyectos_extra": [], **(cfg_extra or {})}, guardar=False)
    eventos = []
    dif = Difusor()
    llm = llm or Falso()
    gestor = Gestor(cfg, g, Consumo(None), llm, lambda ev: (eventos.append(ev), dif.emitir(ev)),
                    simulacion=simulacion if simulacion is not None else lineas(), velocidad=velocidad)
    gestor._dif = dif
    return gestor, llm, eventos, g, cfg


def cliente(gestor, cfg, g, ahora=None):
    bl = Backlog(g, cfg, ahora=ahora)
    app = crear_app(gestor, gestor._dif, cfg, g, TOKEN, PUERTO, backlog=bl)
    return TestClient(app, base_url=f"http://127.0.0.1:{PUERTO}", headers={"X-Token": TOKEN})


def esperar(cond, t=15):
    for _ in range(int(t / 0.05)):
        if cond():
            return
        time.sleep(0.05)
    raise AssertionError("tiempo agotado")


async def esperar_async(cond, t=15):
    for _ in range(int(t / 0.05)):
        if cond():
            return
        await asyncio.sleep(0.05)
    raise AssertionError("tiempo agotado")
