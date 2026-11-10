"""Orquestación visible: eventos REALES de cada tarea (agente, modelo, tramo, duración, tokens, resultado).

La interfaz pinta los agentes a partir de estos eventos y nada más: no hay temporizadores que simulen actividad.
- `instrumentar` envuelve el punto único por el que pasan las llamadas al LLM (`Analista._llamar`) sin tocar su lógica
  ni el reparto de modelos y sin llamadas nuevas.
- `Sonda.transcripcion` recibe el inicio y el fin de cada tramo que procesa el transcriptor (Whisper, local).
- `Sonda.observar` lee los eventos que el gestor ya emite (`analisis`, `tarjetas`) para construir la traza por análisis.
Nada de esto guarda contenido de reuniones: solo tiempos, modelos, tokens y contadores.
"""
from __future__ import annotations

import heapq
import threading
import time
from collections import deque
from datetime import datetime

from .texto import mmss

# tarea del Analista -> (clave de agente, nombre visible)
AGENTES = {
    "digest": ("contexto", "Contexto"),
    "contexto_reunion": ("contexto", "Contexto de la reunión"),   # «Generar con Claude» en el inicio (antes de empezar la reunión)
    "periodico": ("analista", "Analista"),
    "contradicciones_confirmar": ("verificador", "Verificador de contradicciones"),
    "final": ("redactor", "Redactor del resumen final"),
    "pulido": ("pulidor", "Pulidor"),
    "brief": ("brief", "Brief de preparación"),          # ola 3: al abrir la ficha de un proyecto (cacheado)
    "pregunta_capitan": ("coordinador", "Capitán"),      # ola 3: la pregunta que cerraría un objetivo sin tratar
    "archivero": ("archivero", "Archivero"),             # ola B: lectura manual de los documentos clave de un proyecto (desde la ficha)
    "consulta": ("consultas", "Consultas"),            # «Pregúntale»: una llamada por pregunta, solo si el usuario la lanza
    "consulta_sonnet": ("consultas", "Consultas"),
    # el asesor en directo: respuestas sugeridas, consejos del Estratega y «Profundizar»
    "asesor_respuesta": ("asesor", "Asesor"),
    "asesor_respuesta_sonnet": ("asesor", "Asesor"),
    "asesor_consejo": ("estratega", "Estratega"),
    "asesor_consejo_sonnet": ("estratega", "Estratega"),
    "asesor_profundizar": ("asesor", "Asesor"),
    # los cuatro perfiles del equipo: un turno = una llamada real a haiku
    "equipo_coordinador": ("coordinador", "Coordinador"),
    "equipo_funcional": ("funcional", "Analista funcional"),
    "equipo_constructor": ("constructor", "Constructor"),
    "equipo_revisor": ("revisor", "Revisor"),
}
PERFILES_AGENTE = ("coordinador", "funcional", "constructor", "revisor")
# Prioridad en la cola de llamadas (menor = antes). Las llamadas siguen EN SERIE; solo cambia quién entra cuando el cerrojo queda libre:
# la respuesta a una pregunta del cliente y «Profundizar» (lo pide el usuario) se adelantan a los turnos del equipo; la afinación con sonnet va después de ellas.
PRIORIDAD_TAREA = {"asesor_respuesta": 0, "asesor_profundizar": 0, "asesor_respuesta_sonnet": 1}
PRIORIDAD_DEFECTO = 2
TOPE_TAREAS = 400
TOPE_TRANSCRIPCION = 60
TOPE_TRAZA = 200


def _tokens(llamadas: list[dict]) -> int:
    """Entrada (con caché) + salida de las llamadas medidas por `Consumo` para esa tarea."""
    t = 0
    for reg in llamadas:
        for u in reg.get("uso", []):
            t += u.get("entrada", 0) + u.get("cache_creacion", 0) + u.get("cache_lectura", 0) + u.get("salida", 0)
    return t


class CerrojoPrioritario:
    """Cerrojo de las llamadas al modelo: una a la vez (como un `threading.Lock`), pero al quedar libre entra primero la de MENOR prioridad que espera
    y, a igual prioridad, la que llegó antes. No expulsa a la que ya está llamando: la respuesta al cliente espera, como mucho, a que termine la llamada en curso."""

    def __init__(self):
        self._c = threading.Condition()
        self._ocupado = False
        self._cola: list[tuple[int, int]] = []
        self._n = 0

    def adquirir(self, prioridad: int = PRIORIDAD_DEFECTO) -> None:
        with self._c:
            self._n += 1
            ticket = (prioridad, self._n)
            heapq.heappush(self._cola, ticket)
            while self._ocupado or self._cola[0] != ticket:
                self._c.wait()
            heapq.heappop(self._cola)
            self._ocupado = True

    def liberar(self) -> None:
        with self._c:
            self._ocupado = False
            self._c.notify_all()

    def locked(self) -> bool:
        return self._ocupado

    def esperando(self) -> int:
        with self._c:
            return len(self._cola)

    def turno(self, prioridad: int = PRIORIDAD_DEFECTO):
        cerrojo = self

        class _Turno:
            def __enter__(self_):
                cerrojo.adquirir(prioridad)

            def __exit__(self_, *a):
                cerrojo.liberar()
        return _Turno()

    def __enter__(self):   # `with cerrojo:` como un Lock normal (prioridad por defecto)
        self.adquirir(PRIORIDAD_DEFECTO)
        return self

    def __exit__(self, *a):
        self.liberar()


class Sonda:
    def __init__(self, emitir, gestor=None):
        self._emitir = emitir          # emitir(dict): seguro desde cualquier hilo (Difusor.emitir)
        self.gestor = gestor
        self._lock = threading.Lock()
        self._id = 0
        self._zid = 0
        self.tareas: list[dict] = []
        self.transcripcion_tareas: deque = deque(maxlen=TOPE_TRANSCRIPCION)
        self.traza: list[dict] = []
        self._pendiente: dict | None = None        # análisis en curso (para la traza)
        self._obj_prev: dict[int, tuple] = {}
        self._chk_auto_prev: set[str] = set()
        self._ultima_periodica: dict | None = None
        self._turno = CerrojoPrioritario()   # todas las llamadas al modelo van EN SERIE: el fin de una es anterior al inicio de la siguiente
        self.tramo_actual = ""           # tramo del turno de un perfil en curso (lo fija el director antes de llamar)
        self.al_terminar = None          # callback(reg, llamadas) tras cada llamada (el presupuesto cuenta los tokens)

    # ------------------------------------------------------------ ciclo de vida
    def reiniciar(self) -> None:
        with self._lock:
            self.tareas, self.traza = [], []
            self.transcripcion_tareas.clear()
            self._pendiente, self._ultima_periodica = None, None
            self._obj_prev, self._chk_auto_prev = {}, set()

    def publico(self) -> dict:
        with self._lock:
            return {"tareas": [dict(t) for t in self.tareas] + [dict(t) for t in self.transcripcion_tareas],
                    "traza": [dict(t) for t in self.traza]}

    def _nuevo_id(self) -> int:
        with self._lock:
            self._id += 1
            return self._id

    def _t(self) -> float:
        g = self.gestor
        return round(g.reloj.ahora(), 1) if g is not None else 0.0

    # ------------------------------------------------------------ tareas del LLM
    def _tramo(self, tarea: str) -> str:
        """Tramo de reunión al que se refiere la tarea; vacío si no aplica (un dato ausente no se pinta)."""
        g = self.gestor
        s = g.sesion if g is not None else None
        if s is None:
            return ""
        try:
            if tarea == "periodico":
                nuevos = s.nuevos_desde_ultimo_analisis()
                if nuevos:
                    return f"{mmss(nuevos[0].t)}–{mmss(nuevos[-1].t)}"
            elif tarea == "final":
                return f"00:00–{mmss(s.duracion_s)}"
            elif tarea.startswith("equipo_") or tarea.startswith("asesor_consejo"):
                return self.tramo_actual
        except Exception:  # noqa: BLE001
            pass
        return ""

    def inicio(self, tarea: str, modelo: str) -> dict:
        agente, nombre = AGENTES.get(tarea, (tarea, tarea))
        reg = {"id": self._nuevo_id(), "agente": agente, "nombre": nombre, "tarea": tarea, "modelo": modelo,
               "tramo": self._tramo(tarea), "t": self._t(), "hora": datetime.now().strftime("%H:%M:%S"),
               "estado": "en_curso", "ms": None, "tokens": None, "ok": None, "error": ""}
        reg = {k: v for k, v in reg.items() if v not in ("",)} | {"error": ""}
        with self._lock:
            self.tareas.append(reg)
            del self.tareas[:-TOPE_TAREAS]
        self._emitir({"tipo": "tarea", "fase": "inicio", **reg})
        return reg

    def fin(self, reg: dict, ok: bool, ms: int, llamadas: list[dict], error: str = "", clase: str = "") -> None:
        with self._lock:
            reg.update(estado="ok" if ok else "error", ok=ok, ms=ms, error=error, clase=clase,
                       tokens=_tokens(llamadas) if llamadas else None)
            if (reg.get("tarea") == "periodico" or str(reg.get("tarea", "")).startswith("equipo_")) and ok:
                self._ultima_periodica = reg
            copia = dict(reg)
        self._emitir({"tipo": "tarea", "fase": "fin", **copia})
        if self.al_terminar:
            try:
                self.al_terminar(copia, llamadas)
            except Exception:  # noqa: BLE001
                pass

    def instrumentar(self, analista) -> None:
        """Envuelve `analista._llamar` (punto único de las llamadas al LLM). La lógica original no cambia."""
        original = analista._llamar
        sonda = self

        def _llamar(tarea, sistema, usuario, parsear, intentos=2, web=False):
            extra = {"web": True} if web else {}   # solo «Profundizar» con la casilla marcada; los modelos de prueba antiguos no lo conocen
            with sonda._turno.turno(PRIORIDAD_TAREA.get(tarea, PRIORIDAD_DEFECTO)):   # en serie: nunca dos llamadas al modelo a la vez (digest, turnos, Pregúntale, cierre)
                reg = sonda.inicio(tarea, analista.config.modelo(tarea))
                n0 = len(analista.consumo.llamadas)
                t0 = time.perf_counter()

                def medidas():
                    return [r for r in analista.consumo.llamadas[n0:] if r.get("tarea") == tarea]
                try:
                    r = original(tarea, sistema, usuario, parsear, intentos, **extra)
                except Exception as e:  # noqa: BLE001
                    msg = getattr(e, "mensaje", None) or str(e)
                    sonda.fin(reg, False, int((time.perf_counter() - t0) * 1000), medidas(), msg, getattr(e, "tipo", "otro"))
                    raise
                sonda.fin(reg, True, int((time.perf_counter() - t0) * 1000), medidas())
                return r
        analista._llamar = _llamar

    # ------------------------------------------------------------ transcriptor (Whisper, local)
    def transcripcion(self, fase: str, ident: int, **datos) -> None:
        """`fase` inicio|fin. `ident` identifica el tramo. Datos: fuente, audio_s, palabras, ms, ok, error, etiqueta."""
        hora = datetime.now().strftime("%H:%M:%S")
        with self._lock:
            reg = next((t for t in self.transcripcion_tareas if t["id"] == f"w{ident}"), None)
            if reg is None:
                reg = {"id": f"w{ident}", "agente": "transcriptor", "nombre": "Transcriptor", "tarea": datos.get("etiqueta", "tramo"),
                       "modelo": "local", "t": self._t(), "hora": hora, "estado": "en_curso", "ms": None, "tokens": None,
                       "ok": None, "error": ""}
                if datos.get("fuente"):
                    reg["fuente"] = datos["fuente"]
                if datos.get("audio_s") is not None:
                    reg["audio_s"] = round(datos["audio_s"], 1)
                if datos.get("etiqueta"):
                    reg["tramo"] = datos["etiqueta"]
                self.transcripcion_tareas.append(reg)
            if fase == "fin":
                ok = datos.get("ok", True)
                reg.update(estado="ok" if ok else "error", ok=ok, ms=datos.get("ms"), error=datos.get("error", ""))
                if datos.get("palabras") is not None:
                    reg["palabras"] = datos["palabras"]
            copia = dict(reg)
        self._emitir({"tipo": "tarea", "fase": fase, **copia})

    # ------------------------------------------------------------ traza por análisis (a partir de los eventos del gestor)
    def observar(self, tipo: str, d: dict) -> None:
        g = self.gestor
        if g is None or g.sesion is None:
            return
        s = g.sesion
        if tipo == "analisis":
            fase = d.get("fase")
            if fase == "inicio":
                nuevos = s.nuevos_desde_ultimo_analisis()
                desde, hasta = (d["desde_t"], d["hasta_t"]) if d.get("desde_t") is not None else ((nuevos[0].t, nuevos[-1].t) if nuevos else (None, None))
                self._pendiente = {"n": g.n_analisis + 1, "desde_t": desde, "hasta_t": hasta, "perfil": d.get("perfil", ""),
                                   "insights": 0, "objetivos": 0, "checks": 0, "definiciones": 0, "motivo": d.get("motivo", "")}
            elif fase == "ok":
                self._cerrar_analisis(s)
            elif fase == "omitido":
                self._anadir({"fila": "omitido", "n": g.n_analisis, "t": self._t(), "palabras": d.get("palabras"),
                              "minimo": d.get("minimo")})
            elif fase == "error":
                self._pendiente = None
                self._anadir({"fila": "fallo", "n": g.n_analisis + 1, "t": self._t(), "clase": d.get("clase", ""),
                              "mensaje": d.get("mensaje", ""), "bloqueante": d.get("clase") in ("sesion", "limite")})
        elif tipo == "tarjetas" and self._pendiente is not None and "nuevas" in d and not d.get("todas"):
            p = self._pendiente
            p["insights"] = len(d.get("nuevas") or [])
            p["definiciones"] = int(d.get("definiciones") or 0)
            if d.get("hasta_id"):
                p["hasta_id"] = d["hasta_id"]
            cambios = 0
            nuevos_obj = {}
            for o in d.get("objetivos") or []:
                clave = (o.get("estado"), o.get("minuto"))
                nuevos_obj[o.get("n")] = clave
                if o.get("estado") != "sin_tratar" and self._obj_prev.get(o.get("n"), ("sin_tratar", "")) != clave:
                    cambios += 1
            self._obj_prev.update(nuevos_obj)
            p["objetivos"] = cambios
            autos = {c.get("id") for c in d.get("checks") or [] if c.get("auto")}
            p["checks"] = len(autos - self._chk_auto_prev)
            self._chk_auto_prev = autos

    def _cerrar_analisis(self, s) -> None:
        p, self._pendiente = self._pendiente, None
        if p is None:
            return
        reg = self._ultima_periodica or {}
        e = {"fila": "analisis", "n": p["n"], "t": self._t(), "insights": p["insights"], "objetivos": p["objetivos"], "checks": p["checks"]}
        if p.get("perfil"):
            e["perfil"] = p["perfil"]
        if p.get("definiciones"):
            e["definiciones"] = p["definiciones"]
        if p.get("desde_t") is not None:
            e["tramo"] = f"{mmss(p['desde_t'])}–{mmss(p['hasta_t'])}"
            e["hasta_t"] = round(p["hasta_t"], 1)
        e["hasta_id"] = p.get("hasta_id") or s.ultimo_analizado_id
        if p.get("motivo"):
            e["motivo"] = p["motivo"]
        for k_dst, k_src in (("modelo", "modelo"), ("ms", "ms"), ("tokens", "tokens")):
            if reg.get(k_src) is not None:
                e[k_dst] = reg[k_src]
        self._anadir(e)

    def _anadir(self, e: dict) -> None:
        with self._lock:
            self._zid += 1
            e["id"] = f"z{self._zid}"
            self.traza.append(e)
            del self.traza[:-TOPE_TRAZA]
        self._emitir({"tipo": "traza", **e})
