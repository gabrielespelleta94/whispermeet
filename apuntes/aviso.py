"""Aviso flotante de llamada de Teams (sin tokens ni modelos).

Cuando `llamadas.vigilar_llamadas` da «inicio», se abre una ventana pequeña, siempre encima y sin tomar el foco (`ventana.VentanaAviso`),
con el logo, el tema de la reunión, la casilla «He avisado a los asistentes», «Empezar a transcribir» y un desplegable (proyecto, idioma,
tema). La app solo PROPONE grabar: la grabación empieza SOLO con el clic de la persona en «Empezar a transcribir» y el servidor exige la
casilla marcada (`AvisoLlamada.empezar`). «Ahora no», `AVISO_CADUCA_S` sin tocarlo (lo cuenta la página; el ratón encima lo pausa), colgar o
empezar a grabar por otro lado lo cierran, y no vuelve a salir en ESA llamada (el detector solo da un «inicio» por llamada).

El título de la reunión se lee localmente de la ventana de Teams (Win32, `ventana.titulos_ventanas_de`) y solo viaja, si la persona empieza,
como el tema normal de la sesión. Si la ventana flotante falla, `vigilar_llamadas` cae al banner y al parpadeo de siempre.
"""
from __future__ import annotations

import re
import threading
from datetime import datetime

from .config import APP_DIR, AVISO_CADUCA_S, validar_idioma
from .registro import registrar_error

MAX_TEMA = 120    # el mismo tope que el campo «Tema de la reunión» de la pantalla de inicio
ESPERA_PAGINA_S = 12.0   # si la página del aviso no se ha cargado a los N s, se cierra y se cae al banner

# ---------------------------------------------------------------------------------------------- título de la ventana de Teams
_INVISIBLES = dict.fromkeys(map(ord, "​‌‍⁠﻿‎‏"))
_CORREO = re.compile(r"^[^\s@|]+@[^\s@|]+\.[^\s@|]+$")
_SUFIJO_TEAMS = re.compile(r"\s*[-–—]\s*microsoft teams\s*$", re.I)
_CONTADOR = re.compile(r"^\s*\(\d+\)\s*")
# Fragmentos que Teams añade al título y que no son el tema («Unión a la reunión | …», «Reunión | …»)
_RUIDO = {
    "unión a la reunión", "unirse a la reunión", "unión a una reunión", "unirte a la reunión", "unió a la reunió", "unir-se a la reunió",
    "join meeting", "joining meeting", "join the meeting", "joining the meeting", "join a meeting", "join now",
    "reunión", "reunión en curso", "reunió", "meeting", "call", "llamada", "trucada", "en curso", "microsoft teams", "teams",
}
# Pantallas de Teams que NO son una reunión (la primera parte del título es una sección o una barra auxiliar): no dan tema
_SECCIONES = {
    "chat", "chats", "calendario", "calendar", "calendari", "equipos", "equips", "actividad", "activity", "activitat", "llamadas", "calls", "trucades",
    "archivos", "files", "fitxers", "aplicaciones", "apps", "aplicacions", "ayuda", "help", "ajuda", "inicio", "home", "inici", "buscar", "search", "cercar",
    "comunidades", "communities", "comunitats", "onedrive", "copilot", "notificaciones", "notifications", "notificacions", "novedades", "what's new",
    "barra de control de uso compartido", "sharing control bar", "barra de control de compartició", "configuración", "settings", "configuració",
    "tareas", "tasks", "tasques", "viva engage", "mensajes", "messages", "missatges", "mentions", "menciones", "mencions",
}


def limpiar_titulo(texto: str | None) -> str:
    """Tema a partir del título de una ventana de Teams, o «» si no parece una reunión.

    «Unión a la reunión | NORDIA - Seguimiento Interno (EPM) | Microsoft Teams» -> «NORDIA - Seguimiento Interno (EPM)». Quita el sufijo de
    Teams, los fragmentos de ruido («Unión a la reunión», «Reunión»), el correo y la organización que Teams añade tras el tema, los caracteres
    invisibles y los contadores «(2)»; una sección de Teams («Chat | …», «Calendario | …») no es una reunión. Función pura (con tests)."""
    if not isinstance(texto, str):
        return ""
    t = _SUFIJO_TEAMS.sub("", " ".join(texto.translate(_INVISIBLES).split()))
    partes = [p.strip() for p in t.split("|")]
    partes = [p for p in partes if p]
    limpias: list[str] = []
    for i, p in enumerate(partes):
        if _CORREO.match(p):
            if len(limpias) > 1:
                limpias.pop()      # la organización que Teams pone justo antes del correo («… | STRATESYS … | correo | Microsoft Teams»)
            continue
        if p.casefold() in _RUIDO:
            continue
        limpias.append(p)
    if not limpias:
        return ""
    primero = _CONTADOR.sub("", limpias[0]).strip()
    if not primero or primero.casefold() in _SECCIONES:
        return ""
    primero = primero.rstrip(" -–—:").strip()
    return primero[:MAX_TEMA].rstrip()


def tema_por_defecto(titulo: str, ahora: datetime) -> str:
    """El título limpio de la reunión o, si no se pudo leer, «Llamada de Teams HH:MM»."""
    return titulo or f"Llamada de Teams {ahora:%H:%M}"


def titulo_reunion_teams() -> str:
    """Título limpio de la ventana de reunión de Teams (la de más arriba que lo tenga), o «» si no se lee. Nunca lanza."""
    try:
        from . import ventana as V
        for crudo in V.titulos_ventanas_de():
            limpio = limpiar_titulo(crudo)
            if limpio:
                return limpio
    except Exception:  # noqa: BLE001
        pass
    return ""


# ---------------------------------------------------------------------------------------------- el aviso
def _nombres_proyectos(guardian) -> list[str]:
    from . import contexto as CX
    return [p["nombre"] for p in CX.listar_proyectos(guardian, "", (APP_DIR,), {})]


class AvisoLlamada:
    """Ciclo de vida del aviso flotante. `fabrica()` devuelve la ventana (`ventana.VentanaAviso` o una falsa en los tests) con
    `abrir(url)`, `cerrar()`, `redimensionar(alto)`, `pedir_teclado(bool)` y `medir()`."""

    def __init__(self, gestor, cfg, guardian, fabrica, url: str, leer_titulo=titulo_reunion_teams, ahora=datetime.now,
                 al_fallar=None, espera_pagina_s: float = ESPERA_PAGINA_S, caduca_s: float = AVISO_CADUCA_S, proyectos=_nombres_proyectos):
        self.gestor, self.cfg, self.guardian = gestor, cfg, guardian
        self.fabrica, self.url = fabrica, url
        self.leer_titulo, self.ahora, self.al_fallar = leer_titulo, ahora, al_fallar
        self.espera_pagina_s, self.caduca_s, self._proyectos = espera_pagina_s, caduca_s, proyectos
        self.ventana = None
        self.activo = False        # hay un aviso en pantalla
        self.atendida = False      # en ESTA llamada ya se enseñó (y se resolvió): no vuelve hasta que cuelgue
        self.pagina_cargada = False
        self._datos: dict = {}
        self._lock = threading.RLock()
        self._vigia: threading.Timer | None = None

    # ------------------------------------------------------------ datos de la página
    def _preparar_datos(self) -> dict:
        titulo = ""
        try:
            titulo = self.leer_titulo() or ""
        except Exception as e:  # noqa: BLE001 — sin título se usa «Llamada de Teams HH:MM»
            registrar_error("aviso.leer_titulo", e)
        try:
            nombres = self._proyectos(self.guardian)
        except Exception as e:  # noqa: BLE001
            registrar_error("aviso.proyectos", e)
            nombres = []
        ultimo = (self.cfg.datos.get("ultimo_proyecto") or "").strip()
        proyecto = next((n for n in nombres if n.lower() == ultimo.lower()), "") if ultimo else ""   # «» = Bandeja (nunca o ya no existe)
        return {"titulo": titulo, "tema": tema_por_defecto(titulo, self.ahora()), "proyectos": nombres, "proyecto": proyecto,
                "idioma": validar_idioma(self.cfg.datos.get("ultimo_idioma"), defecto="auto"), "caduca_s": self.caduca_s}

    def datos_publicos(self) -> dict:
        """Lo que la página del aviso pide al abrirse. Marca la página como cargada (el vigía deja de esperar)."""
        with self._lock:
            self.pagina_cargada = True
            return {**self._datos, "activo": self.activo}

    # ------------------------------------------------------------ ciclo de vida
    def mostrar(self) -> bool:
        """Abre el aviso. True si está en pantalla (o ya se resolvió en esta llamada: no hay que caer al banner); False si no se pudo abrir.
        Se llama desde un hilo (crear la ventana espera a la interfaz nativa)."""
        with self._lock:
            if self.atendida or self.activo:
                return True
            if not self.cfg.datos.get("detectar_llamadas", True) or self.gestor.estado != "inactivo":
                return True          # nada que avisar (y nada que reemplazar con el banner)
            self._datos = self._preparar_datos()
            self.pagina_cargada = False
            self.ventana = self.fabrica()
            self.activo = True
        try:
            self.ventana.abrir(self.url)
        except Exception as e:  # noqa: BLE001 — cualquier fallo: se cierra lo que hubiera y el llamador usa el banner
            registrar_error("aviso.abrir", e)
            with self._lock:
                self.activo = False
            self._cerrar_ventana()
            return False
        with self._lock:
            if not self.activo:      # se cerró mientras se abría
                return True
            self._vigia = threading.Timer(self.espera_pagina_s, self._vigilar_carga)
            self._vigia.daemon = True
            self._vigia.start()
        return True

    def _vigilar_carga(self) -> None:
        """Si la página no llegó a pedir sus datos, el aviso está muerto: se cierra y se vuelve al banner y al parpadeo."""
        with self._lock:
            if not self.activo or self.pagina_cargada:
                return
        registrar_error("aviso.pagina", RuntimeError(f"La página del aviso no cargó en {self.espera_pagina_s:g} s."))
        self.cerrar("fallo")
        g = self.gestor
        if getattr(g, "llamada", False):
            g.llamada_flotante = False
            g.emitir("llamada", activa=True, flotante=False)
            if self.al_fallar:
                try:
                    self.al_fallar()
                except Exception:  # noqa: BLE001
                    pass

    def _cerrar_ventana(self) -> None:
        v, self.ventana = self.ventana, None
        if v is not None:
            try:
                v.cerrar()
            except Exception as e:  # noqa: BLE001
                registrar_error("aviso.cerrar", e)

    def cerrar(self, motivo: str = "") -> None:
        """Quita el aviso. `motivo` «fin» (la llamada ha terminado) deja listo el aviso para la llamada siguiente. Idempotente."""
        with self._lock:
            self.activo = False
            if motivo == "fin":
                self.atendida = False
            if self._vigia is not None:
                self._vigia.cancel()
                self._vigia = None
        self._cerrar_ventana()

    def descartar(self) -> None:
        """«Ahora no» o caducidad: se cierra y no vuelve en esta llamada."""
        with self._lock:
            self.atendida = True
        self.cerrar("descartar")

    def ventana_cerrada(self) -> None:
        """La ventana desapareció por su cuenta (cerrada desde fuera): cuenta como «Ahora no»."""
        with self._lock:
            if self.activo:
                self.atendida = True
            self.activo = False
            self.ventana = None
            if self._vigia is not None:
                self._vigia.cancel()
                self._vigia = None

    def redimensionar(self, alto_css: float) -> None:
        v = self.ventana
        if v is not None:
            v.redimensionar(alto_css)

    def pedir_teclado(self, si: bool) -> None:
        v = self.ventana
        if v is not None:
            v.pedir_teclado(bool(si))

    # ------------------------------------------------------------ empezar
    async def empezar(self, proyecto: str | None, tema: str, idioma: str | None, avisado: bool) -> dict:
        """El clic de la persona en «Empezar a transcribir»: inicia la sesión por el flujo normal (`Gestor.iniciar`) y cierra el aviso.
        Sin la casilla de aviso a los asistentes marcada no hace nada."""
        if not self.activo:
            raise ValueError("Este aviso ya no está activo.")
        if avisado is not True:
            raise ValueError("Confirma que has avisado a los asistentes.")
        nombre = (proyecto or "").strip() or None
        if nombre is not None:
            conocidos = {n.lower(): n for n in self._datos.get("proyectos", [])}
            if nombre.lower() not in conocidos:
                raise ValueError("Ese proyecto no está en la lista.")
            nombre = conocidos[nombre.lower()]
        idioma_ok = validar_idioma(idioma if idioma is not None else self.cfg.datos.get("ultimo_idioma"), defecto="auto")
        texto = " ".join((tema or "").split())[:MAX_TEMA] or self._datos.get("tema") or tema_por_defecto("", self.ahora())
        resultado = await self.gestor.iniciar(nombre, texto, None, None, [], "", idioma_ok)
        recordar_ultimo(self.cfg, nombre, idioma_ok)
        with self._lock:
            self.atendida = True
        self.cerrar("empezar")
        return resultado


def recordar_ultimo(cfg, proyecto: str | None, idioma: str | None) -> None:
    """Guarda el último proyecto e idioma con que se empezó a grabar (el aviso de llamada los propone). Nunca lanza."""
    try:
        cambios = {}
        p = (proyecto or "").strip()
        if p != (cfg.datos.get("ultimo_proyecto") or ""):
            cambios["ultimo_proyecto"] = p
        if idioma and idioma != cfg.datos.get("ultimo_idioma"):
            cambios["ultimo_idioma"] = idioma
        if cambios:
            cfg.actualizar(cambios)
    except Exception as e:  # noqa: BLE001
        registrar_error("aviso.recordar_ultimo", e)
