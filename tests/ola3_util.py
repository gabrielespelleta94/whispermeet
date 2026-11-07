"""Material común de las pruebas de la ola 3: proyecto sintético en carpeta temporal, sesiones .md ficticias, modelo falso y cliente de la API."""
import json
import threading
from datetime import datetime
from pathlib import Path

from fastapi.testclient import TestClient

from apuntes.analisis import ModeloLLM, Respuesta, Uso
from apuntes.backlog import Backlog
from apuntes.config import Config
from apuntes.consumo import Consumo
from apuntes.gestor import Gestor
from apuntes.rutas import CARPETA_SESIONES, Guardian
from apuntes.servidor import Difusor, crear_app

PUERTO, TOKEN = 8197, "t0k3n"
PROYECTO = "Proyecto Ola Tres"
AHORA = datetime(2026, 11, 5, 15, 0)


def sesion_md(tema, fecha, resumen="", insights=(), inicio="10:00", estado="finalizada", transcripcion=("[00:05] **Reunión:** Hola a todos.",)):
    partes = ["---", f'tema: "{tema}"', f'proyecto: "{PROYECTO}"', f"fecha: {fecha}", f"inicio: {inicio}", "duracion: 20:00", f"estado: {estado}", "---", "", f"# {tema}", ""]
    if resumen:
        partes += ["## Resumen", "", resumen, ""]
    if insights:
        partes += ["## Insights", "", *insights, ""]
    partes += ["## Transcripción", "", *transcripcion, ""]
    return "\n".join(partes) + "\n"


class ModeloFalso(ModeloLLM):
    """Responde según la tarea (por el prompt de sistema). `respuestas`: lista de (fragmento del sistema, texto); `fallar`: lanza ErrorAnalisis."""

    def __init__(self, respuestas=None, fallar=False):
        self.respuestas = respuestas or []
        self.fallar = fallar
        self.llamadas = []
        self._l = threading.Lock()

    def completar(self, sistema, usuario, modelo, esfuerzo="", timeout_s=240, sin_razonamiento=False, web=False):
        from apuntes.analisis import ErrorAnalisis
        with self._l:
            self.llamadas.append((sistema, usuario, modelo))
        if self.fallar:
            raise ErrorAnalisis("otro", "sin modelo de prueba", False)
        for frag, texto in self.respuestas:
            if frag in sistema:
                return Respuesta(texto if isinstance(texto, str) else json.dumps(texto), [Uso(modelo, 50, 10)])
        raise AssertionError("prompt inesperado: " + sistema[:80])


def montaje(tmp_path, modelo=None, sesiones=(), abridor=None, config=None):
    """-> (cliente, gestor, cfg, guardian, backlog, modelo, eventos). `sesiones`: [(nombre fichero, texto .md)] en `02. Sesiones` del proyecto."""
    raiz = tmp_path / "proyectos"
    carpeta = raiz / PROYECTO / CARPETA_SESIONES
    carpeta.mkdir(parents=True)
    (raiz / PROYECTO / "00. CONTEXTO (IA)").mkdir()
    for nombre, texto in sesiones:
        (carpeta / nombre).write_text(texto, encoding="utf-8", newline="\n")
    g = Guardian(raiz, tmp_path / "bandeja", tmp_path / "cache", sesiones_locales=tmp_path / "sesiones", backlog=tmp_path / "backlog", planes=tmp_path / "planes")
    g.borradores = tmp_path / "borradores"   # los .eml de prueba, en la carpeta temporal del test
    cfg = Config(tmp_path / "config.json")
    cfg.actualizar({"raiz_proyectos": str(raiz), "knowledge": "", **(config or {})}, guardar=False)
    modelo = modelo or ModeloFalso(fallar=True)
    eventos = []
    dif = Difusor()
    gestor = Gestor(cfg, g, Consumo(None), modelo, eventos.append)
    bl = Backlog(g, cfg, ahora=lambda: AHORA)
    app = crear_app(gestor, dif, cfg, g, TOKEN, PUERTO, backlog=bl, abridor_ola3=abridor)
    cli = TestClient(app, base_url=f"http://127.0.0.1:{PUERTO}", headers={"X-Token": TOKEN})
    return cli, gestor, cfg, g, bl, modelo, eventos


def sesion_directa(gestor, g, objetivos=(), tema="Reunión de prueba", t=0.0):
    """Pone una sesión en curso SIN arrancar audio, bucle ni modelo: lo justo para probar acciones, tarjetas y cierre. -> la Sesión."""
    from apuntes import planes as PL
    from apuntes.sesion import Sesion
    ruta = g.ruta_sesion(PROYECTO, "2026-11-06", tema)
    s = Sesion(PROYECTO, tema, 5, ruta)
    s.modo_cadencia = "equipo"
    s.objetivos = [PL.objetivo_nuevo(i, txt) for i, txt in enumerate(objetivos, 1)]
    s.vincular(g)
    gestor.sesion, gestor.estado = s, "grabando"
    gestor.acciones.reiniciar()
    gestor.reloj.fijar(t)
    return s
