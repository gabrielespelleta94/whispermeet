"""Servidor FastAPI + WebSocket. Solo escucha en 127.0.0.1 y exige un token por ejecución."""
from __future__ import annotations

import asyncio
import contextlib
import functools
import json
import re
import secrets
from datetime import datetime
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import __version__
from . import contexto as CX
from . import aviso as AV
from . import backlog as BL
from . import llamadas as LL
from . import planes as PL
from .audio import listar_dispositivos
from .config import APP_DIR, WEB_DIR
from .rutas import RutaProhibida, raiz_onedrive, sugerir_compartida

HOST = "127.0.0.1"


class Difusor:
    def __init__(self):
        self.loop: asyncio.AbstractEventLoop | None = None
        self.colas: set[asyncio.Queue] = set()

    def emitir(self, ev: dict) -> None:
        """Seguro desde cualquier hilo."""
        if self.loop is None:
            return
        try:
            self.loop.call_soon_threadsafe(self._publicar, ev)
        except RuntimeError:
            pass

    def _publicar(self, ev: dict) -> None:
        for q in list(self.colas):
            if q.qsize() > 2000:  # cliente atascado: se descarta
                self.colas.discard(q)
                continue
            q.put_nowait(ev)


class Inicio(BaseModel):
    proyecto: str | None = None  # None = Bandeja
    tema: str = ""
    cadencia: int | str | None = None  # adaptativo (por defecto) | 5 | 10 | manual
    sesion_plan: str | None = None  # id de la sesión del plan del proyecto (None = sin plan)
    objetivos: list[str] = []       # objetivos propios escritos antes de empezar (sin plan o «Otra reunión»)
    contexto_reunion: str = ""      # «Contexto de la reunión» aceptado por el usuario (vacío = todo como siempre)
    idioma: str | None = None       # «Idioma de la reunión»: auto | es | ca (None = el de la configuración); se valida en el gestor


class DictadoIn(BaseModel):
    idioma: str | None = None       # el mismo «Idioma de la reunión» del inicio


class EntradaIn(BaseModel):
    tipo: str | None = None    # comentario | pregunta | idea
    texto: str = ""


class ObjetivoIn(BaseModel):
    operacion: str             # anadir | editar | borrar | confirmar | descartar
    n: int | None = None
    texto: str = ""


class ConsultaIn(BaseModel):
    pregunta: str
    modelo: str = "haiku"      # haiku | sonnet (solo para esta pregunta)


class ProfundizarIn(BaseModel):
    web: bool = False          # «Buscar también en la web»: desmarcada por defecto; solo con la casilla marcada y si `claude -p` lo permite


class MarcaIn(BaseModel):
    valor: bool = True


class ExtraIn(BaseModel):
    nombre: str
    ruta: str
    compartido: bool = False


class CarpetaNuevaIn(BaseModel):
    nombre: str
    ubicacion: str | None = None   # None = la raíz de proyectos
    compartido: bool = False


class ContextoGenerarIn(BaseModel):
    texto: str
    tema: str = ""


class ContextoGuardarIn(BaseModel):
    proyecto: str | None = None
    tema: str = ""
    texto: str
    objetivos: list[str] = []


class Nota(BaseModel):
    texto: str = ""


class Aplicar(BaseModel):
    aceptados: list[str] = []


class Publicacion(BaseModel):
    publicar: bool = True


class Version(BaseModel):
    version: str


class Cierre(BaseModel):
    publicar: bool | None = None  # None = lo que haya elegido el usuario en la revisión


class ModoReunionIn(BaseModel):
    activo: bool
    izq: float | None = None      # medidas de los paneles en px CSS (None = por defecto)
    der: float | None = None
    uno: float | None = None
    dpr: float | None = None      # devicePixelRatio de la página (escala real de WebView2)
    guardar: bool = False         # recordar estas medidas (al soltar un divisor)
    solo_actualizar: bool = False  # recalcular si el modo ya está activo; nunca entrar (una petición tardía no puede reabrirlo tras salir)


class OpacidadIn(BaseModel):
    pct: int = 100
    guardar: bool = False


class AvisoEmpezarIn(BaseModel):
    proyecto: str | None = None   # None o vacío = Bandeja
    tema: str = ""
    idioma: str | None = None     # auto | es | ca
    avisado: bool = False         # la casilla «He avisado a los asistentes»: sin ella no empieza nada


class AvisoTamanoIn(BaseModel):
    alto: float                   # alto del contenido en px CSS (el desplegable crece o se recoge)


class AvisoTecladoIn(BaseModel):
    activo: bool


class EstadoItemIn(BaseModel):
    estado: str                   # pendiente: abierto | hecho | descartado; idea: nueva | aprovechada | descartada


class TemaIn(BaseModel):
    tema: str = ""                # vacío = volver al tema original del .md


class CheckIn(BaseModel):
    proyecto: str | None = None   # None = Bandeja
    sesion: str | None = None     # id de la sesión del plan (None = lista general del proyecto)
    texto: str = ""
    hecho: bool | None = None


def crear_app(gestor, difusor: Difusor, cfg, guardian, token: str, puerto: int,
              al_cambiar_captura=None, ventana=None, al_avisar_llamada=None, vigilar_llamadas_activo=False, aviso=None,
              leer_micro=None, intervalo_llamadas: float = 5.0, backlog=None) -> FastAPI:
    """`ventana`: función sin argumentos que devuelve la `Ventana` nativa (o None con `--sin-ventana`).
    `backlog`: el `Backlog` (pruebas: con tiempos, reloj y abridor propios); por defecto uno sobre el Guardian.
    `vigilar_llamadas_activo`: solo la app real vigila el micro de Teams (los tests no leen el registro).
    `aviso`: el `AvisoLlamada` flotante (None con `--sin-ventana`: entonces solo banner y parpadeo). `leer_micro` e `intervalo_llamadas`
    sustituyen la lectura del registro y el intervalo (pruebas con una llamada simulada)."""
    hosts_ok = {f"{HOST}:{puerto}", f"localhost:{puerto}"}
    bl = backlog if backlog is not None else BL.Backlog(guardian, cfg)
    gestor.fuentes.backlog = bl   # las sesiones anteriores del mismo proyecto entran en las fuentes del asesor por backlog.py
    re_id = re.compile(r"[0-9a-f]{16}")
    re_asesor = re.compile(r"[rc]\d{1,4}")

    @asynccontextmanager
    async def vida(app):
        difusor.loop = asyncio.get_running_loop()
        tarea_llamadas = None
        if vigilar_llamadas_activo:
            extra = {"leer": leer_micro} if leer_micro else {}
            tarea_llamadas = asyncio.create_task(LL.vigilar_llamadas(gestor, cfg, al_avisar_llamada, intervalo_llamadas, aviso=aviso, **extra))
        yield
        if aviso is not None:
            with contextlib.suppress(Exception):
                aviso.cerrar("fin")
        if tarea_llamadas:
            tarea_llamadas.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await tarea_llamadas
        gestor.apagar()

    app = FastAPI(title="WhisperMeet", version=__version__, lifespan=vida, docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware("http")
    async def seguridad(request: Request, call_next):
        if request.headers.get("host", "") not in hosts_ok:
            return JSONResponse({"error": "host no permitido"}, status_code=403)
        if request.url.path.startswith("/api/") and not secrets.compare_digest(request.headers.get("x-token", ""), token):
            return JSONResponse({"error": "token no válido"}, status_code=401)
        resp = await call_next(request)
        resp.headers["Cache-Control"] = "no-store"
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["Content-Security-Policy"] = ("default-src 'self'; style-src 'self' 'unsafe-inline'; "
                                                   "connect-src 'self' ws://127.0.0.1:%d ws://localhost:%d; img-src 'self' data:" % (puerto, puerto))
        return resp

    def envolver(fn):
        @functools.wraps(fn)
        async def _w(*a, **k):
            try:
                return await fn(*a, **k)
            except ValueError as e:
                raise HTTPException(400, str(e))
            except RutaProhibida as e:
                raise HTTPException(403, f"Operación no permitida: {e}")
        return _w

    # ------------------------------------------------------------ páginas
    @app.get("/")
    async def index():
        return FileResponse(WEB_DIR / "index.html")

    @app.get("/aviso")
    async def pagina_aviso():
        """La página de la ventana flotante del aviso de llamada (como «/», sin token en la ruta: la API sí lo exige)."""
        return FileResponse(WEB_DIR / "aviso.html")

    app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")

    # ------------------------------------------------------------ API
    @app.get("/api/info")
    async def info():
        return {"version": __version__, "simulacion": gestor.sim is not None, "config": cfg.publico(),
                "raiz_existe": Path(cfg["raiz_proyectos"]).is_dir()}

    @app.put("/api/config")
    @envolver
    async def poner_config(cambios: dict):
        antes = cfg["excluir_captura"]
        if "raiz_proyectos" in cambios:
            r = Path(str(cambios["raiz_proyectos"]))
            if not r.is_dir():
                raise ValueError("La carpeta raíz de proyectos no existe.")
        if "whisper_modelo" in cambios and not re.fullmatch(r"[A-Za-z0-9._\-/]{1,80}", str(cambios["whisper_modelo"])):
            raise ValueError("Nombre de modelo no válido.")
        if gestor.estado != "inactivo" and ("raiz_proyectos" in cambios or "whisper_modelo" in cambios):
            raise ValueError("Cambia la raíz o el modelo de transcripción fuera de una reunión.")
        cfg.actualizar(cambios)
        guardian.raiz = Path(cfg["raiz_proyectos"])
        guardian.fijar_extras(cfg["proyectos_extra"])
        if cfg["excluir_captura"] != antes and al_cambiar_captura:
            al_cambiar_captura(cfg["excluir_captura"])
        return {"config": cfg.publico()}

    @app.get("/api/proyectos")
    async def proyectos(q: str = ""):
        excluir = (APP_DIR,)
        planes = await asyncio.to_thread(PL.cargar_planes, guardian)
        ahora = datetime.now()
        planes = {k: PL.enriquecer(v, ahora) for k, v in planes.items()}  # estados del Gantt: sin llamar a ningún modelo
        return {"raiz": str(guardian.raiz),
                "proyectos": CX.listar_proyectos(guardian, q, excluir, planes)}

    @app.get("/api/dispositivos")
    async def dispositivos():
        return await asyncio.to_thread(listar_dispositivos)

    @app.get("/api/sesion")
    async def sesion():
        return gestor.snapshot()

    @app.get("/api/consumo")
    async def consumo():
        return gestor.consumo.resumen()

    @app.post("/api/sesion/iniciar")
    @envolver
    async def iniciar(b: Inicio):
        r = await gestor.iniciar(b.proyecto, b.tema, b.cadencia, b.sesion_plan, b.objetivos, b.contexto_reunion, b.idioma)
        AV.recordar_ultimo(cfg, b.proyecto, b.idioma)   # el aviso de llamada propondrá este proyecto e idioma
        if aviso is not None:
            aviso.cerrar("empezar")                      # si había un aviso flotante abierto, ya no hace falta
        return r

    # ------------------------------------------------------------ aviso flotante de llamada de Teams (solo con ventana nativa)
    def _aviso():
        if aviso is None:
            raise ValueError("El aviso flotante necesita la ventana nativa de WhisperMeet (no existe con --sin-ventana).")
        return aviso

    @app.get("/api/aviso")
    @envolver
    async def aviso_datos():
        return _aviso().datos_publicos()

    @app.post("/api/aviso/empezar")
    @envolver
    async def aviso_empezar(b: AvisoEmpezarIn):
        """El clic en «Empezar a transcribir»: la grabación empieza SOLO aquí y solo con la casilla de aviso a los asistentes marcada."""
        return await _aviso().empezar(b.proyecto, b.tema, b.idioma, b.avisado)

    @app.post("/api/aviso/descartar")
    @envolver
    async def aviso_descartar():
        _aviso().descartar()
        return {"ok": True}

    @app.post("/api/aviso/tamano")
    @envolver
    async def aviso_tamano(b: AvisoTamanoIn):
        await asyncio.to_thread(_aviso().redimensionar, b.alto)
        return {"ok": True}

    @app.post("/api/aviso/teclado")
    @envolver
    async def aviso_teclado(b: AvisoTecladoIn):
        await asyncio.to_thread(_aviso().pedir_teclado, b.activo)
        return {"ok": True}

    # ------------------------------------------------------------ anotaciones del usuario, objetivos propios y «Pregúntale»
    @app.post("/api/sesion/entradas")
    @envolver
    async def entrada_anadir(b: EntradaIn):
        return gestor.entrada_anadir(b.tipo or "", b.texto)

    @app.put("/api/sesion/entradas/{ident}")
    @envolver
    async def entrada_editar(ident: str, b: EntradaIn):
        return gestor.entrada_editar(ident, b.texto, b.tipo)

    @app.delete("/api/sesion/entradas/{ident}")
    @envolver
    async def entrada_borrar(ident: str):
        return gestor.entrada_borrar(ident)

    @app.post("/api/sesion/objetivos")
    @envolver
    async def objetivo_operar(b: ObjetivoIn):
        return {"objetivos": gestor.objetivo_operar(b.operacion, b.n, b.texto)}

    @app.post("/api/sesion/consultar")
    @envolver
    async def consultar(b: ConsultaIn):
        return await gestor.consultar(b.pregunta, b.modelo)

    # ------------------------------------------------------------ asesor en directo: «Profundizar», fijar y descartar (las respuestas y los consejos llegan por el WebSocket)
    def _id_asesor(ident: str) -> str:
        if not re_asesor.fullmatch(ident):
            raise HTTPException(404, "No existe ese elemento del asesor.")
        return ident

    @app.get("/api/asesor")
    async def asesor_estado():
        return gestor.asesor.publico()

    @app.post("/api/asesor/{ident}/profundizar")
    @envolver
    async def asesor_profundizar(ident: str, b: ProfundizarIn):
        return await gestor.asesor.profundizar(_id_asesor(ident), b.web)

    @app.post("/api/asesor/{ident}/fijar")
    @envolver
    async def asesor_fijar(ident: str, b: MarcaIn):
        return gestor.asesor.marcar(_id_asesor(ident), "fijar", b.valor)

    @app.post("/api/asesor/{ident}/descartar")
    @envolver
    async def asesor_descartar(ident: str, b: MarcaIn):
        return gestor.asesor.marcar(_id_asesor(ident), "descartar", b.valor)

    # ------------------------------------------------------------ añadir carpeta de proyecto (Ajustes e inicio)
    @app.post("/api/proyectos/extra")
    @envolver
    async def anadir_extra(b: ExtraIn):
        nuevo = guardian.validar_extra(b.nombre, b.ruta, b.compartido)   # RutaProhibida -> 403 con el motivo
        cfg.actualizar({"proyectos_extra": [*cfg["proyectos_extra"], nuevo]})
        guardian.fijar_extras(cfg["proyectos_extra"])
        return {"proyecto": nuevo, "proyectos_extra": cfg["proyectos_extra"]}

    @app.delete("/api/proyectos/extra/{nombre}")
    @envolver
    async def quitar_extra(nombre: str):
        if gestor.estado != "inactivo":
            raise ValueError("Quita la carpeta fuera de una reunión.")
        cfg.actualizar({"proyectos_extra": [e for e in cfg["proyectos_extra"] if e["nombre"].lower() != nombre.lower()]})
        guardian.fijar_extras(cfg["proyectos_extra"])
        return {"proyectos_extra": cfg["proyectos_extra"]}

    @app.post("/api/proyectos/carpeta")
    @envolver
    async def crear_carpeta(b: CarpetaNuevaIn):
        """«Nueva carpeta»: crea una carpeta vacía (sin sobrescribir ni reutilizar una existente) y, si no cuelga directamente de la raíz
        de proyectos, la registra como proyecto extra por el mismo camino que «Añadir carpeta» (`validar_extra`)."""
        creada = guardian.crear_carpeta_proyecto(b.nombre, b.ubicacion)   # RutaProhibida -> 403 con el motivo
        extra = not creada["en_raiz"]
        if extra:
            try:
                nuevo = guardian.validar_extra(creada["nombre"], creada["ruta"], b.compartido)
                cfg.actualizar({"proyectos_extra": [*cfg["proyectos_extra"], nuevo]})
                guardian.fijar_extras(cfg["proyectos_extra"])
            except RutaProhibida:
                guardian.deshacer_carpeta_nueva(creada["ruta"])   # no queda una carpeta huérfana sin proyecto
                raise
        return {"proyecto": {"nombre": creada["nombre"], "ruta": creada["ruta"], "compartido": bool(extra and b.compartido)},
                "registrada_como_extra": extra, "proyectos_extra": cfg["proyectos_extra"]}

    @app.post("/api/sesion/pausa")
    @envolver
    async def pausa():
        await gestor.pausar()
        return {"ok": True}

    @app.post("/api/sesion/reanudar")
    @envolver
    async def reanudar():
        await gestor.reanudar()
        return {"ok": True}

    @app.put("/api/sesion/notas")
    @envolver
    async def notas(b: Nota):
        gestor.nota(b.texto)
        return {"ok": True}

    @app.post("/api/sesion/analizar")
    @envolver
    async def analizar():
        return await gestor.analizar(manual=True)

    @app.post("/api/sesion/terminar")
    @envolver
    async def terminar():
        return await gestor.terminar()

    @app.post("/api/revision/reintentar")
    @envolver
    async def reintentar():
        await gestor.reintentar_revision()
        return {"ok": True}

    @app.post("/api/revision/aplicar")
    @envolver
    async def aplicar(b: Aplicar):
        return await gestor.aplicar_revision(b.aceptados)

    @app.post("/api/revision/pulir")
    @envolver
    async def pulir():
        return await gestor.pulir()

    @app.post("/api/revision/resumen")
    @envolver
    async def elegir_resumen(b: Version):
        return await gestor.elegir_resumen(b.version)

    @app.post("/api/revision/publicacion")
    @envolver
    async def elegir_publicacion(b: Publicacion):
        return await gestor.elegir_publicacion(b.publicar)

    @app.post("/api/revision/publicar")
    @envolver
    async def publicar():
        return await gestor.publicar()

    @app.post("/api/revision/cerrar")
    @envolver
    async def cerrar(b: Cierre | None = None):
        return await gestor.cerrar_revision(b.publicar if b else None)

    # ------------------------------------------------------------ Modo reunión (solo con ventana nativa)
    def _ventana():
        v = ventana() if ventana else None
        if v is None:
            raise ValueError("El Modo reunión necesita la ventana nativa de WhisperMeet (no funciona con --sin-ventana).")
        return v

    def _prefs(b: ModoReunionIn | None = None) -> dict:
        p = dict(cfg["modo_reunion"])
        if b is not None:
            for k in ("izq", "der", "uno"):
                if getattr(b, k) is not None:
                    p[k] = getattr(b, k)
        return p

    @app.get("/api/ventana")
    async def ventana_estado():
        v = ventana() if ventana else None
        if v is None:
            return {"nativa": False}
        return {"nativa": True, "prefs": dict(cfg["modo_reunion"]), **await asyncio.to_thread(v.estado_modo)}

    @app.post("/api/ventana/elegir-carpeta")
    @envolver
    async def elegir_carpeta():
        """Selector de carpetas nativo de Windows (solo con ventana nativa). Devuelve la carpeta elegida y una propuesta de «Carpeta
        compartida»; no registra nada: el alta sigue pasando por /api/proyectos/extra. Solo carpetas visibles en disco (OneDrive o Google
        Drive sincronizados); no hay integración con ninguna nube."""
        v = _ventana()
        ruta = await asyncio.to_thread(v.elegir_carpeta, raiz_onedrive() or "")   # empieza en el OneDrive del usuario, si existe   # el diálogo lo muestra el hilo de la interfaz de pywebview
        if not ruta:
            return {"cancelado": True}
        p = Path(ruta)
        return {"cancelado": False, "ruta": str(p), "nombre": p.name, "compartida_sugerida": sugerir_compartida(p)}

    @app.post("/api/ventana/modo-reunion")
    @envolver
    async def modo_reunion(b: ModoReunionIn):
        v = _ventana()
        if b.guardar:
            cfg.actualizar({"modo_reunion": {k: getattr(b, k) for k in ("izq", "der", "uno") if getattr(b, k) is not None}})
        if not b.activo:
            return await asyncio.to_thread(v.salir)
        if gestor.estado not in ("grabando", "pausada") and not v.modo_activo and not b.solo_actualizar:
            raise ValueError("El Modo reunión solo se activa con una reunión en curso.")
        prefs = _prefs(b)
        if v.modo_activo or b.solo_actualizar:
            return await asyncio.to_thread(v.actualizar, prefs, b.dpr)
        return await asyncio.to_thread(v.entrar, prefs, b.dpr)

    @app.post("/api/ventana/opacidad")
    @envolver
    async def modo_opacidad(b: OpacidadIn):
        v = _ventana()
        cfg.actualizar({"modo_reunion": {"opacidad": b.pct}}, guardar=b.guardar)
        ok = await asyncio.to_thread(v.fijar_opacidad, b.pct)
        return {"ok": ok, **await asyncio.to_thread(v.estado_modo)}

    # ------------------------------------------------------------ Contexto de la reunión (inicio): dictado, Claude y guardado
    @app.get("/api/contexto-reunion/dictado")
    async def dictado_estado():
        return gestor.dictado.publico()

    @app.post("/api/contexto-reunion/dictado/iniciar")
    @envolver
    async def dictado_iniciar(b: DictadoIn | None = None):
        return await asyncio.to_thread(gestor.dictado.iniciar, b.idioma if b else None)   # abre el micro y carga el modelo: en un hilo aparte

    @app.post("/api/contexto-reunion/dictado/parar")
    @envolver
    async def dictado_parar():
        return await asyncio.to_thread(gestor.dictado.detener)

    @app.post("/api/contexto-reunion/generar")
    @envolver
    async def contexto_generar(b: ContextoGenerarIn):
        return await gestor.generar_contexto_reunion(b.texto, b.tema)

    @app.post("/api/contexto-reunion/guardar")
    @envolver
    async def contexto_guardar(b: ContextoGuardarIn):
        return await asyncio.to_thread(gestor.guardar_contexto_reunion, b.proyecto, b.tema, b.texto, b.objetivos)

    # ------------------------------------------------------------ checks de preparación
    @app.get("/api/checks")
    @envolver
    async def checks_listar(proyecto: str | None = None, sesion: str | None = None):
        return {"checks": gestor.checks_listar(proyecto, sesion)}

    @app.post("/api/checks")
    @envolver
    async def checks_anadir(b: CheckIn):
        return {"checks": gestor.checks_operar(b.proyecto, b.sesion, "anadir", texto=b.texto)}

    @app.put("/api/checks/{ident}")
    @envolver
    async def checks_cambiar(ident: str, b: CheckIn):
        if b.hecho is not None:
            return {"checks": gestor.checks_operar(b.proyecto, b.sesion, "marcar", ident, hecho=b.hecho)}
        return {"checks": gestor.checks_operar(b.proyecto, b.sesion, "editar", ident, texto=b.texto)}

    @app.post("/api/checks/{ident}/deshacer")
    @envolver
    async def checks_deshacer(ident: str, b: CheckIn):
        return {"checks": gestor.checks_operar(b.proyecto, b.sesion, "deshacer", ident)}

    @app.delete("/api/checks/{ident}")
    @envolver
    async def checks_borrar(ident: str, proyecto: str | None = None, sesion: str | None = None):
        return {"checks": gestor.checks_operar(proyecto, sesion, "borrar", ident)}

    # ------------------------------------------------------------ backlog: sesiones pasadas y lista conjunta (sin llamadas al modelo)
    def _id(valor: str) -> str:
        if not re_id.fullmatch(valor or ""):   # solo ids que da la propia API: nunca una ruta
            raise ValueError("Identificador no válido.")
        return valor

    @app.get("/api/backlog/sesiones")
    @envolver
    async def backlog_sesiones(refrescar: bool = True):
        return await asyncio.to_thread(bl.sesiones, refrescar)

    @app.get("/api/backlog/items")
    @envolver
    async def backlog_items(refrescar: bool = False):
        return await asyncio.to_thread(bl.items, refrescar)

    @app.get("/api/backlog/sesiones/{sid}")
    @envolver
    async def backlog_sesion(sid: str):
        s = await asyncio.to_thread(bl.sesion, _id(sid))
        if s is None:
            raise HTTPException(404, "No existe esa sesión.")
        return s

    @app.put("/api/backlog/items/{iid}")
    @envolver
    async def backlog_estado(iid: str, b: EstadoItemIn):
        it = await asyncio.to_thread(bl.fijar_estado, _id(iid), b.estado)
        if it is None:
            raise HTTPException(404, "No existe ese elemento.")
        return it

    @app.put("/api/backlog/sesiones/{sid}/tema")
    @envolver
    async def backlog_tema(sid: str, b: TemaIn):
        s = await asyncio.to_thread(bl.fijar_tema, _id(sid), b.tema)
        if s is None:
            raise HTTPException(404, "No existe esa sesión.")
        return s

    @app.post("/api/backlog/sesiones/{sid}/abrir")
    @envolver
    async def backlog_abrir(sid: str):
        try:
            r = await asyncio.to_thread(bl.abrir, _id(sid))
        except OSError as e:
            raise ValueError(f"No se pudo abrir el fichero: {e}")
        if r is None:
            raise HTTPException(404, "No existe esa sesión.")
        return r

    # ------------------------------------------------------------ WebSocket
    @app.websocket("/ws")
    async def ws(sock: WebSocket):
        origen = sock.headers.get("origin", "")
        if sock.headers.get("host", "") not in hosts_ok or not secrets.compare_digest(sock.query_params.get("t", ""), token) \
                or (origen and origen not in {f"http://{h}" for h in hosts_ok}):
            await sock.close(code=4403)
            return
        await sock.accept()
        q: asyncio.Queue = asyncio.Queue()
        difusor.colas.add(q)
        await sock.send_text(json.dumps({"tipo": "snapshot", **gestor.snapshot()}, ensure_ascii=False))

        async def enviar():
            while True:
                ev = await q.get()
                await sock.send_text(json.dumps(ev, ensure_ascii=False))

        tarea = asyncio.create_task(enviar())
        try:
            while True:
                await sock.receive_text()  # solo para detectar la desconexión
        except WebSocketDisconnect:
            pass
        finally:
            tarea.cancel()
            difusor.colas.discard(q)

    return app
