"""Gestor: orquesta sesión, captura/simulación, transcripción, análisis y revisión."""
from __future__ import annotations

import asyncio
import contextlib
import hashlib
import random
import threading
import time
from datetime import date, datetime
from pathlib import Path

from . import asesor as AS
from . import cambios as CB
from . import checks as CK
from . import cobertura as COB
from . import correo_cierre as CC
from . import disparo as DP
from . import contexto as CX
from . import planes as PL
from . import tarjetas as TJ
from .analisis import ErrorAnalisis, ModeloLLM
from .analisis import prompts as P
from .analisis.analista import Analista
from .asesor_directo import Asesor
from .config import validar_idioma
from .dictado import Dictado
from .consumo import Consumo
from .equipo.director import MODOS_CON_EQUIPO, Director
from .fuentes import ServicioFuentes
from .orquesta import Sonda
from .registro import registrar_error
from .rutas import CARPETA_CONTEXTO, CARPETA_SESIONES, Guardian, RutaProhibida, slug
from .sesion import Sesion
from .transcripcion import prompt_tema
from .simulador import LineaSim
from .texto import a_segundos, formatear_lineas, limpiar_transcripcion, mmss, palabras, recortar


class Reloj:
    """Tiempo activo de la reunión (se detiene en pausa). `factor` > 1 acelera la simulación."""

    def __init__(self, factor: float = 1.0):
        self.factor, self.base, self.t0 = factor, 0.0, None

    def iniciar(self):
        if self.t0 is None:
            self.t0 = time.monotonic()

    def pausar(self):
        if self.t0 is not None:
            self.base += (time.monotonic() - self.t0) * self.factor
            self.t0 = None

    def fijar(self, segundos: float) -> None:
        """Detiene el reloj en `segundos` (solo simulación: al acabar la transcripción simulada, la reunión «termina» ahí)."""
        self.t0, self.base = None, float(segundos)

    def ahora(self) -> float:
        return self.base + ((time.monotonic() - self.t0) * self.factor if self.t0 is not None else 0.0)


def acumular_resumen(previo: str, nuevo: str, tope: int) -> str:
    """El modelo solo devuelve lo nuevo; aquí se acumula y, si pasa del tope, se descarta lo más antiguo."""
    texto = f"{previo}\n{nuevo}".strip() if nuevo else previo
    if len(texto) <= tope:
        return texto
    corte = texto[len(texto) - tope:]
    return corte[corte.find("\n") + 1:] if "\n" in corte else corte


FALLOS_SEGUIDOS_GRAVE = 10      # pasadas seguidas fallando de un mismo tipo: el aviso pasa a decirlo claramente
AVISO_FALLO_CADA_S = 300.0      # como máximo un aviso por tipo de fallo cada 5 min
TEXTO_FALLO = "El análisis automático ha fallado. La grabación sigue."
TEXTO_FALLO_GRAVE = ("El análisis automático lleva varias pasadas seguidas fallando. La grabación sigue y se sigue intentando; "
                     "usa «Analizar ahora» y revisa datos\\apuntes.log.")
TEXTO_RECUPERADO = "El análisis automático se ha recuperado."
TOPE_RESUMEN_COMPLETO = 30_000  # seguridad: para reuniones de horas; las tarjetas del final nunca se recortan por antigüedad


class Gestor:
    def __init__(self, config, guardian: Guardian, consumo: Consumo, modelo_llm: ModeloLLM, emitir,
                 simulacion: list[LineaSim] | None = None, velocidad: float = 30.0):
        self.cfg, self.g, self.consumo, self.llm = config, guardian, consumo, modelo_llm
        self._emitir = emitir
        self.sonda = Sonda(emitir, self)   # eventos reales de cada tarea para el panel de orquestación (sin llamadas nuevas)
        self.sim = simulacion
        self.velocidad = velocidad
        self.estado = "inactivo"  # inactivo | preparando | grabando | pausada | terminando | revision
        self.llamada = False      # Teams está usando el micro (apuntes/llamadas.py): solo propone grabar, nunca graba
        self.llamada_flotante = False   # el aviso flotante (apuntes/aviso.py) está atendiendo esta llamada: el banner de inicio no sale
        self.sesion: Sesion | None = None
        self.reloj = Reloj()
        self.analista: Analista | None = None
        self.transcriptor = None
        self._vocabulario_contexto: list[str] = []
        self.captura = None
        self.digest = ""
        self.digest_origen = ""
        self.digest_solo_lectura = False        # el contexto sale de CLAUDE.md, README.md o docs/ (proyecto sin «00. CONTEXTO (IA)»)
        self.digest_ficheros: list[str] = []   # nombres de los ficheros que alimentan el contexto (pie de la reunión)
        self._digest_tarea: asyncio.Task | None = None
        self._tareas: list[asyncio.Task] = []
        self.analizando = False
        self.proximo_analisis = 0.0
        self.bloqueo: ErrorAnalisis | None = None
        self.ultimo_error: dict | None = None
        self.ultimo_omitido: dict | None = None
        self.n_analisis = 0
        self.avisos: list[str] = []
        self.revision: dict | None = None
        self.niveles = {"yo": -90.0, "reunion": -90.0}
        self._sim_fin = False
        self._plan_sesion: dict | None = None
        self._plan_con_objetivos = False
        self.ultimo_analisis_t = 0.0          # reloj de la reunión en el último análisis (disparo adaptativo y enfriamiento)
        self._ultima_comprobacion = 0.0
        self.motivo_ultimo = ""
        self._consulta_en_curso = False
        self.checks = CK.AlmacenChecks(guardian)
        self.idioma = validar_idioma(config["idioma"], defecto="auto")   # idioma de la reunión en curso (auto | es | ca)
        self.contexto_reunion = ""             # lo que el usuario aceptó en «Contexto de la reunión» (vacío = todo como siempre)
        self._contexto_en_curso = False
        self.dictado = Dictado(config, emitir, bloqueo=self._bloqueo_dictado)   # dictado del contexto por micro: solo en memoria
        self._cierre: COB.Cierre | None = None   # lo que recibió la llamada final (para avisar de lo que quedó fuera)
        self._salud: dict[str, dict] = {}      # por tipo de fallo del bucle: {seguidas, ultimo_aviso, avisado, texto}
        self.fuentes = ServicioFuentes(guardian, config)   # índice local de fuentes (BM25) para el asesor: se construye en segundo plano, nunca bloquea
        self.asesor = Asesor(self)             # respuestas sugeridas a las preguntas del cliente y «Profundizar» (presupuesto propio)
        self.equipo = Director(self)           # el Monitor local, el presupuesto, las definiciones y los turnos de los perfiles (con el Estratega)

    # ------------------------------------------------------------------ utilidades
    def emitir(self, tipo: str, **datos) -> None:
        try:
            self.sonda.observar(tipo, datos)   # traza por análisis a partir de los eventos reales; nunca debe romper el flujo
        except Exception:  # noqa: BLE001
            pass
        self._emitir({"tipo": tipo, **datos})

    def _palabras_nuevas(self) -> int | None:
        """Palabras nuevas desde el último análisis (las que cuentan para el mínimo); None si no hay sesión."""
        s = self.sesion
        if not s:
            return None
        return sum(palabras(x.texto) for x in s.nuevos_desde_ultimo_analisis()) + palabras(s.notas_para_modelo())

    def _texto_nuevo(self) -> str:
        """Lo nuevo desde el último análisis (transcripción, notas y anotaciones del usuario), para buscar señales locales."""
        s = self.sesion
        if not s:
            return ""
        return " ".join([x.texto for x in s.nuevos_desde_ultimo_analisis()] + [s.notas_para_modelo()])

    def estado_ligero(self) -> dict:
        s = self.sesion
        tr = self.transcriptor
        return {
            "estado": self.estado, "simulacion": self.sim is not None, "velocidad": self.velocidad if self.sim else 1,
            "sesion": None if not s else {
                "id": s.id, "proyecto": s.proyecto, "tema": s.tema, "cadencia_min": s.cadencia_min,
                "cadencia": s.modo_cadencia or str(s.cadencia_min),
                "fichero": s.ruta.name, "compartido": s.compartido,
                "carpeta": ("sesiones\\" + s.ruta.parent.name) if s.compartido else CARPETA_SESIONES if s.proyecto else "bandeja",
                "plan": {"id": s.plan_id, "nombre": s.plan_nombre} if s.plan_id else None},
            "objetivos": [dict(o) for o in s.objetivos] if s else [],
            "checks": [dict(c) for c in s.checks] if s else [],
            "entradas": [dict(e) for e in s.entradas] if s else [],
            "temas": [dict(t) for t in s.temas] if s else [],
            "consultas": [dict(c) for c in s.consultas] if s else [],
            "t": round(self.reloj.ahora(), 1),
            "analisis": {"en_curso": self.analizando, "n": self.n_analisis,
                         "proximo_en": max(0, round(self.proximo_analisis - self.reloj.ahora()))
                         if self.estado in ("grabando", "pausada") and s and s.modo_cadencia in ("5", "10", "") else None,
                         "modo": s.modo_cadencia if s else "", "adaptativo": None,
                         "motivo_ultimo": self.motivo_ultimo,
                         "bloqueo": None if not self.bloqueo else {"tipo": self.bloqueo.tipo, "mensaje": self.bloqueo.mensaje},
                         "ultimo_error": self.ultimo_error, "ultimo_omitido": self.ultimo_omitido,
                         "min_palabras": self.cfg["min_palabras_analisis"], "palabras": self._palabras_nuevas()},
            "equipo": self.equipo.publico() if s else None,
            "asesor": self.asesor.estado_publico() if s else None,
            "digest": {"origen": self.digest_origen, "chars": len(self.digest), "ficheros": list(self.digest_ficheros),
                       "solo_lectura": self.digest_solo_lectura},
            "transcripcion": None if tr is None else {"estado": tr.estado, "error": tr.error,
                                                      "pendiente_s": round(tr.pendiente_s, 1),
                                                      "velocidad_x": None if tr.velocidad_x is None else round(tr.velocidad_x, 2)},
            "captura": None if self.captura is None else {"errores": {k: str(v) for k, v in dict(self.captura.errores).items()}},
            "avisos": list(self.avisos), "consumo": self.consumo.resumen(),
            "revision": self.revision_publica(),
        }

    def snapshot(self) -> dict:
        d = self.estado_ligero()
        d["llamada"] = self.llamada
        d["llamada_flotante"] = self.llamada_flotante
        s = self.sesion
        d["segmentos"] = [x.publico() for x in s.segmentos if x.texto.strip()] if s else []
        d["notas"] = s.notas if s else ""
        d["tarjetas"] = list(s.tarjetas) if s else []
        d["resumen_acumulado"] = s.resumen_acumulado if s else ""
        d["niveles"] = dict(self.niveles)
        d.update(self.sonda.publico())   # tareas (agente, modelo, tramo, duración, tokens, resultado) y traza por análisis
        d["monitor"] = self.equipo.snapshot() if s else {"feed": [], "definiciones": [], "pasadas": []}
        d["asesor"] = self.asesor.publico() if s else {"respuestas": [], "consejos": [], **self.asesor.estado_publico()}
        return d

    def _emitir_estado(self) -> None:
        self.emitir("estado", **self.estado_ligero())

    # ------------------------------------------------------------------ inicio
    async def iniciar(self, proyecto: str | None, tema: str, cadencia=None, sesion_plan: str | None = None,
                      objetivos: list[str] | None = None, contexto_reunion: str = "", idioma: str | None = None) -> dict:
        """`cadencia`: adaptativo (por defecto) | 5 | 10 | manual. `objetivos`: los que el usuario escribe antes de empezar
        (solo sin plan o en «Otra reunión»; con la sesión de un plan mandan los del plan). `contexto_reunion`: el texto que el usuario
        aceptó en «Contexto de la reunión»; entra en el digest y en su clave de caché (vacío: nada cambia)."""
        if self.estado != "inactivo":
            raise ValueError("Ya hay una reunión en curso o pendiente de revisar.")
        # «Idioma de la reunión» (auto | es | ca), validado en servidor; sin valor, el de la configuración (un «es» guardado sigue valiendo)
        self.idioma = validar_idioma(self.cfg["idioma"] if idioma is None else idioma)
        if self.dictado.activo:   # el micro y el modelo de transcripción pasan a la reunión
            await asyncio.to_thread(self.dictado.cancelar)
        modo = DP.normalizar_modo(self.cfg["cadencia_defecto"] if cadencia is None else cadencia)
        plan = PL.plan_de(self.g, proyecto)
        if sesion_plan and not plan:
            raise ValueError("Este proyecto no tiene plan de sesiones.")
        ses = PL.sesion_de(plan, sesion_plan)  # ValueError si no existe en el plan
        tema = (tema or "").strip()[:120] or (ses["nombre"] if ses else "Reunión sin título")
        ruta = self.g.ruta_sesion(proyecto, date.today().isoformat(), tema)  # valida proyecto y ruta
        minutos = DP.minutos_de(modo)
        s = Sesion(proyecto, tema, minutos, ruta)
        s.modo_cadencia = modo
        s.compartido = self.g.es_compartido(proyecto)
        s.filtrar_eco = bool(self.cfg["filtrar_eco"])   # se lee al empezar: un cambio en Ajustes vale para la reunión siguiente
        s.vincular_reloj(lambda: self.reloj.ahora())
        if ses:
            s.plan_id, s.plan_nombre, s.objetivos = ses["id"], ses["nombre"], PL.objetivos_iniciales(ses)
        if not s.objetivos:   # sin plan, «Otra reunión» o sesión sin objetivos: los propios del usuario
            propios = [" ".join(str(t).split())[:200] for t in (objetivos or []) if isinstance(t, str) and t.strip()][:12]
            s.objetivos = [PL.objetivo_nuevo(i, t, "usuario") for i, t in enumerate(propios, 1)]
        self._plan_sesion = ses
        self.contexto_reunion = P.limpiar_texto_usuario(contexto_reunion)
        self._plan_con_objetivos = bool(ses and ses["objetivos"])
        s.checks = self.checks.listar(proyecto, s.plan_id or None, ses["checks"] if ses else [])
        s.vincular(self.g)
        await asyncio.to_thread(s.guardar)
        self.sesion = s
        self.consumo.reiniciar()
        self.consumo.contexto = lambda: {"cadencia": s.modo_cadencia or str(s.cadencia_min), "motivo": self.motivo_ultimo if self.analizando else ""}
        self.analista = Analista(self.llm, self.cfg, self.consumo, self.g, s.id)
        self.sonda.reiniciar()
        self.equipo.reiniciar()
        self.asesor.reiniciar()
        self.fuentes.preparar_proyecto(proyecto, s.ruta.name, self.contexto_reunion)   # hilo demonio: contexto del proyecto y sesiones anteriores
        self.sonda.instrumentar(self.analista)   # punto único de las llamadas al LLM: inicio y fin reales de cada tarea
        self.reloj = Reloj(self.velocidad if self.sim is not None else 1.0)
        self.reloj.iniciar()
        self.digest, self.digest_origen, self.avisos = "", "", []
        self._salud = {}
        self._cierre = None
        self.digest_ficheros = []
        self.bloqueo = self.ultimo_error = self.ultimo_omitido = None
        self.n_analisis, self.analizando, self._sim_fin, self.revision = 0, False, False, None
        self.proximo_analisis = minutos * 60 if minutos else 0.0
        self.ultimo_analisis_t = self._ultima_comprobacion = 0.0
        self.motivo_ultimo, self._consulta_en_curso = "", False
        self.estado = "grabando"
        loop = asyncio.get_running_loop()
        self._loop = loop

        if self.sim is None:
            await self._iniciar_audio(tema)
        else:
            self._tareas.append(loop.create_task(self._sim_bucle()))
        self._digest_tarea = loop.create_task(self._preparar_digest())
        self._tareas.append(self._digest_tarea)
        self._tareas.append(loop.create_task(self._bucle()))
        self._emitir_estado()
        return self.estado_ligero()

    async def _iniciar_audio(self, tema: str) -> None:
        from .audio import Captura
        from .transcripcion import Transcriptor
        self.transcriptor = Transcriptor(self.cfg, self._on_texto)
        self.transcriptor.idioma = self.idioma
        self.transcriptor.prompt = prompt_tema(recortar(tema, 80), "es")       # initial_prompt coherente con el idioma de cada tramo
        self.transcriptor.prompt_ca = prompt_tema(recortar(tema, 80), "ca")
        self.transcriptor.prompt_en = prompt_tema(recortar(tema, 80), "en")
        self._vocabulario_contexto = []
        self._actualizar_vocabulario()
        self.transcriptor.on_tarea = self.sonda.transcripcion
        self.transcriptor.iniciar()
        self.captura = Captura(self.reloj.ahora, self._on_enunciado, self._on_nivel,
                               self.cfg["dispositivo_mic"], self.cfg["dispositivo_sistema"])
        try:
            await asyncio.to_thread(self.captura.iniciar)
        except Exception as e:  # noqa: BLE001
            self.avisos.append(f"No se pudo abrir el audio: {e}")
        for fuente, err in self.captura.errores.items():
            nombre = "el micrófono" if fuente == "yo" else "el audio del sistema"
            self.avisos.append(f"Sin captura de {nombre}: {err}")

    def _actualizar_vocabulario(self) -> None:
        """Vocabulario del prompt de Whisper: primero el de `vocabulario_transcripcion` (config), luego las siglas y términos
        distintivos extraídos en local de los ficheros de contexto ya cargados (sin LLM, sin leer nada nuevo)."""
        if not self.transcriptor:
            return
        vistos, lista = set(), []
        for t in list(self.cfg["vocabulario_transcripcion"]) + list(self._vocabulario_contexto):
            if t.lower() not in vistos:
                vistos.add(t.lower())
                lista.append(t)
        self.transcriptor.vocabulario = lista
        self.transcriptor.vocabulario_curado = list(self.cfg["vocabulario_transcripcion"])

    # ------------------------------------------------------------------ audio -> texto
    def _on_enunciado(self, fuente: str, audio, t0: float) -> None:
        if self.transcriptor:
            self.transcriptor.encolar(fuente, audio, t0)

    def _on_nivel(self, fuente: str, db: float) -> None:
        self.niveles[fuente] = db
        self.emitir("nivel", fuente=fuente, db=round(db, 1))

    def _on_texto(self, fuente: str, t0: float, texto: str) -> None:
        self._agregar(t0, fuente, texto)

    def _agregar(self, t: float, fuente: str, texto: str) -> None:
        s = self.sesion
        if not s:
            return
        seg = s.agregar_segmento(t, fuente, texto)
        s.duracion_s = max(s.duracion_s, self.reloj.ahora())
        try:
            s.guardar()  # guardado incremental: sobrevive a un cierre inesperado
        except Exception as e:  # noqa: BLE001
            self.avisos.append(f"No se pudo guardar la transcripción: {e}")
        if seg.texto.strip():   # un Micro que era todo eco de Reunión no se muestra
            self.emitir("segmento", **seg.publico())
        cambios = s.recoger_cambios_eco()   # Micro anteriores a los que la llegada de este fragmento les quita (más) eco
        if cambios:
            self.emitir("segmento_eco", cambios=cambios)

    # ------------------------------------------------------------------ simulación
    async def _sim_bucle(self) -> None:
        lineas = self.sim or []
        i = 0
        while i < len(lineas):
            if self.estado == "pausada":
                await asyncio.sleep(0.1)
                continue
            if self.estado not in ("grabando",):
                return
            ahora = self.reloj.ahora()
            if lineas[i].t <= ahora:
                l = lineas[i]
                self._agregar(l.t, l.fuente, l.texto)
                asyncio.get_running_loop().create_task(self._pulso(l.fuente))
                i += 1
            else:
                await asyncio.sleep(min(0.2, max(0.01, (lineas[i].t - ahora) / self.velocidad)))
        if lineas:
            self.reloj.fijar(lineas[-1].t)  # la reunión simulada acaba en su último minuto, no cuando acaban los análisis
        self._sim_fin = True
        self.emitir("sim_fin")

    async def _pulso(self, fuente: str) -> None:
        for _ in range(6):
            self._on_nivel(fuente, random.uniform(-38, -14))
            await asyncio.sleep(0.12)
        self._on_nivel(fuente, -90)

    # ------------------------------------------------------------------ control
    async def pausar(self) -> None:
        if self.estado != "grabando":
            return
        self.estado = "pausada"
        self.reloj.pausar()
        if self.captura:
            self.captura.pausada = True
        self._emitir_estado()

    async def reanudar(self) -> None:
        if self.estado != "pausada":
            return
        self.estado = "grabando"
        self.reloj.iniciar()
        if self.captura:
            self.captura.pausada = False
        self._emitir_estado()

    def nota(self, texto: str) -> None:
        if self.sesion and self.estado in ("grabando", "pausada"):
            self.sesion.notas = (texto or "")[:20000]
            try:
                self.sesion.guardar()
            except Exception:  # noqa: BLE001
                pass

    def _toca_analizar(self) -> str:
        """Motivo por el que el reloj dispara el análisis generalista ahora (cadencias fijas de 5 y 10 min), o «» si no toca.
        Sin llamadas al modelo. En modo equipo decide el Monitor (`apuntes/equipo`); en «solo cuando lo pida» nunca."""
        s = self.sesion
        ahora = self.reloj.ahora()
        if s and s.modo_cadencia in ("5", "10", "") and ahora >= self.proximo_analisis > 0:
            return f"cada {s.cadencia_min} min"
        return ""

    async def _bucle(self) -> None:
        """Una pasada por segundo. Cada parte de la pasada (Monitor, turno, tick, análisis periódico) está protegida por separado: si una falla,
        queda en datos\\apuntes.log y en el .md de la sesión, se avisa en la interfaz y la pasada siguiente sigue. La parada (estado, cancelación)
        no se captura: el hilo termina al acabar la reunión."""
        while self.estado in ("grabando", "pausada"):
            await asyncio.sleep(1.0)
            if self.estado == "grabando" and self.sesion:
                await self._protegida("reloj", self._actualizar_duracion)
                await self._vigilar()
                await self._protegida("asesor", self._asesor_paso)
                await self._protegida("analisis", self._disparar_periodico)
            await self._protegida("tick", self._emitir_tick)

    def _actualizar_duracion(self) -> None:
        self.sesion.duracion_s = self.reloj.ahora()

    def _emitir_tick(self) -> None:
        self.emitir("tick", **{k: v for k, v in self.estado_ligero().items() if k in ("t", "analisis", "transcripcion", "consumo", "avisos", "equipo", "asesor")})

    def _disparar_periodico(self) -> bool:
        if self.analizando or self.bloqueo:
            return False
        motivo = self._toca_analizar()
        if not motivo:
            return False
        self._lanzar("analisis", self.analizar(manual=False, motivo=motivo))
        return True

    def _asesor_paso(self):
        """Una pasada del asesor (cada segundo, local): detecta preguntas del cliente en lo nuevo y, si toca (límite de 20 s, la más reciente, presupuesto), lanza UNA
        respuesta sugerida. False = nada que hacer. Un fallo queda en datos\\apuntes.log y la reunión sigue."""
        a = self.asesor
        a.observar()
        p = a.siguiente()
        if p is None:
            return False
        self._lanzar("asesor", a.responder(p))
        return True

    def _lanzar(self, tipo: str, corrutina) -> None:
        """Lanza una tarea de fondo cuyo fallo inesperado no se pierde (antes quedaba como «Task exception was never retrieved», invisible en pythonw)."""
        tarea = asyncio.get_running_loop().create_task(corrutina)

        def fin(t: asyncio.Task) -> None:
            if t.cancelled():
                return
            e = t.exception()
            if e is not None:
                self._fallo(tipo, e)
            else:
                self._ok(tipo)
        tarea.add_done_callback(fin)

    async def _protegida(self, tipo: str, f):
        """Ejecuta una parte de la pasada. Devuelve su resultado; None si falló. `f` puede ser síncrona o async; si devuelve False
        es que no tocaba hacer nada (no cuenta como éxito ni como fallo). No captura CancelledError ni lo que no sea Exception."""
        try:
            r = f()
            if asyncio.iscoroutine(r):
                r = await r
        except Exception as e:  # noqa: BLE001
            self._fallo(tipo, e)
            return None
        if r is not False:
            self._ok(tipo)
        return r

    def _fallo(self, tipo: str, e: BaseException) -> None:
        """Registra el fallo de una parte del bucle y, sin spam, avisa. Nunca lanza ni detiene la grabación."""
        try:
            registrar_error(f"Gestor._bucle.{tipo}", e)
            if self.estado not in ("grabando", "pausada") or not self.sesion:
                return
            h = self._salud.setdefault(tipo, {"seguidas": 0, "ultimo_aviso": None, "avisado": False, "texto": ""})
            h["seguidas"] += 1
            ahora = time.monotonic()
            if h["ultimo_aviso"] is not None and ahora - h["ultimo_aviso"] < AVISO_FALLO_CADA_S:
                return
            h["ultimo_aviso"], h["avisado"] = ahora, True
            grave = h["seguidas"] >= FALLOS_SEGUIDOS_GRAVE
            self.sesion.incidencias.append(f"[{mmss(self.reloj.ahora())}] {tipo}: {type(e).__name__}"
                                           + (f" ({h['seguidas']} pasadas seguidas)" if grave else ""))
            self._poner_aviso(h, TEXTO_FALLO_GRAVE if grave else TEXTO_FALLO)
            self.emitir("aviso", mensaje=h["texto"], componente=tipo, grave=grave)
            self._emitir_estado()
            with contextlib.suppress(Exception):
                self.sesion.guardar()
        except Exception:  # noqa: BLE001 — avisar nunca debe romper el bucle
            pass

    def _ok(self, tipo: str) -> None:
        h = self._salud.get(tipo)
        if not h or not h["seguidas"]:
            return
        try:
            avisado = h["avisado"]
            h["seguidas"], h["avisado"] = 0, False   # `ultimo_aviso` se conserva: un fallo que vuelve enseguida no salta el límite de 5 min
            if not avisado or not self.sesion:
                return
            self.sesion.incidencias.append(f"[{mmss(self.reloj.ahora())}] {tipo}: recuperado")
            self._poner_aviso(h, TEXTO_RECUPERADO)
            self.emitir("aviso", mensaje=TEXTO_RECUPERADO, componente=tipo, grave=False, recuperado=True)
            self._emitir_estado()
            with contextlib.suppress(Exception):
                self.sesion.guardar()
        except Exception:  # noqa: BLE001
            pass

    def _poner_aviso(self, h: dict, texto: str) -> None:
        """Un solo aviso de fallo por tipo en `avisos` (lo que ven el snapshot y el tick): el nuevo sustituye al anterior."""
        for viejo in (h["texto"], TEXTO_RECUPERADO):
            while viejo and viejo in self.avisos:
                self.avisos.remove(viejo)
        self.avisos.append(texto)
        h["texto"] = texto

    async def _vigilar(self) -> None:
        """Una pasada del Monitor protegida por partes (comprobar, publicar lo detectado, arrancar el turno): un fallo queda en datos\\apuntes.log
        y la reunión sigue (el bucle no muere en silencio, que fue lo que dejó una sesión de 33 min sin turnos del equipo)."""
        r = await self._protegida("monitor", self._monitor_comprobar)
        if not r:
            return
        await self._protegida("monitor_eventos", lambda: self._monitor_publicar(r))
        await self._protegida("turno", lambda: self._monitor_turno(r))

    async def _monitor_comprobar(self):
        """Una pasada del Monitor (local, regex y aritmética, sin modelo) cada `adaptativo_comprobar_s`. False si aún no toca."""
        s, eq = self.sesion, self.equipo
        ahora = self.reloj.ahora()
        if ahora - eq._ultima_comprobacion < max(1, self.cfg["adaptativo_comprobar_s"]):
            return False
        try:
            return await asyncio.to_thread(eq.comprobar, ahora, s.modo_cadencia == "equipo") or False
        except Exception:
            with contextlib.suppress(Exception):
                eq._ultima_comprobacion = ahora   # sin esto, un fallo fijo se repetiría cada segundo
            raise

    def _monitor_publicar(self, r: dict) -> None:
        s, eq = self.sesion, self.equipo
        pas = r["pasada"]
        self.emitir("monitor", entradas=[dict(e) for e in pas.entradas], pasada=pas.publico())
        if pas.definiciones:
            s.definiciones = eq.definiciones.publico()
            self.emitir("definiciones", definiciones=s.definiciones)

    def _monitor_turno(self, r: dict) -> None:
        eq = self.equipo
        try:
            if r["turno"]:
                perfil, motivo = r["turno"]
                eq.eligiendo = perfil
                self._lanzar("turno", eq.turno(perfil, motivo))
        finally:
            eq.emitir_estado()

    # ------------------------------------------------------------------ digest
    async def _preparar_digest(self) -> None:
        s = self.sesion
        ctx = self.contexto_reunion
        if not s or not s.proyecto:
            if s and ctx:   # Bandeja: el contexto aceptado es todo el contexto (sin llamada)
                self.digest, self.digest_origen = CX.digest_de_contexto(ctx), "contexto_usuario"
            else:
                self.digest_origen = "sin_proyecto"
            return
        try:
            ses = self._plan_sesion if self._plan_con_objetivos else None  # sin objetivos de plan («Otra reunión») todo queda como sin plan
            propios = [o["texto"] for o in PL.activos(s.objetivos)] if not ses else []
            foco = f"«{ses['nombre']}»; objetivos: " + "; ".join(o["texto"] for o in s.objetivos) if ses else (f"«{s.tema}»" if propios or s.tema else "")
            prio = ses["fichero_prioritario"] if ses else ""
            con_checks = True   # los checks sugeridos viajan en esta misma llamada (con o sin plan)
            con_objetivos = not ses   # sin plan: también hasta 5 objetivos sugeridos, sin llamadas nuevas
            base = self._base_checks()
            huella = hashlib.sha1("|".join(base).encode("utf-8")).hexdigest()[:8]
            if ses:
                clave = f"{ses['id']}|{foco}|chk:{huella}"
            else:   # el tema y los objetivos propios cambian lo que se sugiere
                clave = f"libre|{s.tema}|chk:{huella}|obj:" + hashlib.sha1("|".join(propios).encode("utf-8")).hexdigest()[:8]
            if ctx:   # el contexto aceptado forma parte de la clave de caché (sin él, la clave es la de siempre)
                clave += "|ctx:" + hashlib.sha1(ctx.encode("utf-8")).hexdigest()[:12]
            fuentes = await asyncio.to_thread(CX.fuentes_digest, self.g, s.proyecto, s.tema, self.cfg["knowledge"],
                                              14_000, prio, clave)
            self.digest_ficheros = [e for e, _ in fuentes.textos]
            self._vocabulario_contexto = CX.vocabulario_distintivo([t for _, t in fuentes.textos])
            self._actualizar_vocabulario()
            self.digest_solo_lectura = fuentes.solo_lectura
            self.analista.ficheros_digest = list(self.digest_ficheros)
            if prio and prio not in [e for e, _ in fuentes.textos]:
                self.avisos.append(f"El fichero prioritario de la sesión ({prio}) no está disponible o está vacío.")
            self.digest, self.digest_origen = await asyncio.to_thread(self.analista.digest, s.proyecto, fuentes, foco,
                                                                      base, con_checks, con_objetivos, propios, bool(prio), ctx)
            if con_checks and self.analista.checks_sugeridos and self.sesion is s:
                self.checks.incorporar_sugeridos(s.proyecto, s.plan_id or None, self.analista.checks_sugeridos, base)
                self._sync_checks()
            if con_objetivos and self.analista.objetivos_sugeridos and self.sesion is s:
                self._incorporar_objetivos_sugeridos(self.analista.objetivos_sugeridos)
        except ErrorAnalisis as e:
            self.digest, self.digest_origen = "", "error"
            self._registrar_error(e)
        except Exception as e:  # noqa: BLE001
            self.digest, self.digest_origen = "", "error"
            self.ultimo_error = {"tipo": "otro", "mensaje": f"No se pudo preparar el contexto: {e}"}
        self.emitir("consumo", **self.consumo.resumen())
        self._emitir_estado()

    def _registrar_error(self, e: ErrorAnalisis) -> None:
        self.ultimo_error = {"tipo": e.tipo, "mensaje": e.mensaje, "hora": datetime.now().strftime("%H:%M:%S")}
        if e.bloqueante:
            self.bloqueo = e  # no se reintenta solo; «Analizar ahora» lo desbloquea

    # ------------------------------------------------------------------ análisis periódico
    async def analizar(self, manual: bool = True, motivo: str = "") -> dict:
        s = self.sesion
        if not s or self.estado not in ("grabando", "pausada"):
            return {"ok": False, "motivo": "No hay reunión en curso."}
        if self.analizando:
            return {"ok": False, "motivo": "Ya hay un análisis en curso."}
        if s.modo_cadencia in MODOS_CON_EQUIPO:   # «Analizar ahora» con el equipo: el perfil con más puntos
            return await self.equipo.a_peticion() if manual else {"ok": False, "motivo": "En este modo habla el equipo."}
        nuevos = s.nuevos_desde_ultimo_analisis(esperar=not manual)   # a petición se lee lo recibido, sin esperar a la pareja de un Micro
        pendientes_u = s.entradas_pendientes()
        n_pal = sum(palabras(x.texto) for x in nuevos) + palabras(s.notas_para_modelo())
        minimo = self.cfg["min_palabras_analisis"]
        if manual:
            minimo = max(20, minimo // 3)
            motivo = "a petición"
        elif s.modo_cadencia == "adaptativo":
            minimo = 0   # el disparo adaptativo ya comprobó sus umbrales
        motivo = motivo or "cada %d min" % s.cadencia_min
        if s.cadencia_min and s.modo_cadencia in ("5", "10", ""):
            self.proximo_analisis = self.reloj.ahora() + s.cadencia_min * 60
        self.ultimo_analisis_t = self.reloj.ahora()
        if n_pal < minimo or not nuevos and not pendientes_u and not s.notas_nuevas():
            self.ultimo_omitido = {"palabras": n_pal, "minimo": minimo, "hora": datetime.now().strftime("%H:%M:%S"),
                                   "motivo": f"Análisis omitido: {n_pal} palabras nuevas (mínimo {minimo})."}
            self.emitir("analisis", fase="omitido", **self.ultimo_omitido)
            self._emitir_estado()
            return {"ok": False, "omitido": True, "motivo": self.ultimo_omitido["motivo"]}
        self.analizando = True
        if manual:
            self.bloqueo = None
        self.motivo_ultimo = motivo
        self.emitir("analisis", fase="inicio", motivo=motivo)
        self._emitir_estado()
        try:
            if self._digest_tarea and not self._digest_tarea.done():
                await asyncio.wait({self._digest_tarea}, timeout=120)
            lineas = limpiar_transcripcion(nuevos)
            texto_nuevo = formatear_lineas(lineas)
            titulos = s.titulos_recientes()
            base_chk = self._base_checks()
            enviados = self.checks.para_prompt(s.proyecto, s.plan_id or None, base_chk)  # solo abiertos y sin bloquear, máx. 15
            notas_modelo = s.notas_para_modelo()
            res = await asyncio.to_thread(self.analista.periodico, self.digest, s.resumen_acumulado, titulos,
                                          notas_modelo, texto_nuevo, PL.para_prompt(s.objetivos), enviados, bool(pendientes_u))
            self.n_analisis += 1
            nuevas = self._incorporar(res, lineas)  # las candidatas a contradicción salen ya como «posible»; se confirman al terminar
            PL.aplicar_por_posicion(s.objetivos, res.get("objetivos") or [])
            s.marcar_entradas_enviadas(e["id"] for e in pendientes_u)
            desde_t, hasta_t = (lineas[0].t, lineas[-1].t) if lineas else (self.reloj.ahora(), self.reloj.ahora())
            if res.get("tema"):
                s.temas.append({"analisis": self.n_analisis, "desde_t": round(desde_t, 1), "hasta_t": round(hasta_t, 1), "titulo": res["tema"]})
            s.analisis_marcas.append({"n": self.n_analisis, "t": round(self.reloj.ahora(), 1), "motivo": motivo})
            self.checks.aplicar_marcas(s.proyecto, s.plan_id or None, enviados, res.get("checks") or [], base_chk)
            s.checks = self.checks.listar(s.proyecto, s.plan_id or None, base_chk)
            s.resumen_acumulado = acumular_resumen(s.resumen_acumulado, res["resumen"], self.cfg["tope_resumen_chars"])
            COB.registrar_lectura(s, self.n_analisis, "periodico", lineas)   # el periódico lee TODO lo nuevo: lo deja cubierto
            if res["resumen"]:  # el del final no pierde el principio: cada tramo lleva su inicio y su fin
                s.resumen_completo = acumular_resumen(s.resumen_completo, f"[{mmss(lineas[0].t)}–{mmss(lineas[-1].t)}] {res['resumen']}" if lineas
                                                      else f"[--:--] {res['resumen']}", TOPE_RESUMEN_COMPLETO)
            if nuevos:
                s.ultimo_analizado_id = nuevos[-1].id
            s.notas_enviadas = s.notas
            s.guardar()
            if not self.bloqueo:
                self.ultimo_error = None
            self.ultimo_omitido = None
            self.emitir("tarjetas", nuevas=nuevas, resumen=s.resumen_acumulado, objetivos=[dict(o) for o in s.objetivos],
                      checks=[dict(c) for c in s.checks], temas=[dict(t) for t in s.temas])
            self.emitir("analisis", fase="ok", n=self.n_analisis, tarjetas=len(nuevas), motivo=motivo)
            return {"ok": True, "tarjetas": len(nuevas)}
        except ErrorAnalisis as e:
            self._registrar_error(e)
            self.emitir("analisis", fase="error", clase=e.tipo, mensaje=e.mensaje)
            return {"ok": False, "error": e.mensaje}
        except Exception as e:  # noqa: BLE001  (un fallo de análisis nunca detiene la grabación)
            self.ultimo_error = {"tipo": "otro", "mensaje": f"Error inesperado en el análisis: {e}"}
            self.emitir("analisis", fase="error", clase="otro", mensaje=self.ultimo_error["mensaje"])
            return {"ok": False, "error": str(e)}
        finally:
            self.analizando = False
            self.emitir("consumo", **self.consumo.resumen())
            self._emitir_estado()

    @staticmethod
    def _linea_cercana(lineas, minuto: str) -> str:
        seg = a_segundos(minuto)
        if seg is None or not lineas:
            return ""
        previas = [l for l in lineas if l.t <= seg + 1]
        l = previas[-1] if previas else lineas[0]
        return recortar(l.texto, 260)

    def _incorporar(self, res: dict, lineas) -> list[dict]:
        """Tarjetas del análisis -> las que se muestran: como mucho `max_tarjetas_analisis`, por prioridad, sin duplicar
        lo ya emitido (tampoco entre categorías). Las candidatas a contradicción salen al momento como «posible» (tope
        total `max_candidatas_confirmar`: son las que irán a la única llamada de confirmación del final)."""
        s = self.sesion
        ultimo = lineas[-1].t if lineas else self.reloj.ahora()
        techo = max(self.reloj.ahora(), ultimo) + 2   # ningún minuto puede ser posterior a lo que ha pasado en la reunión

        def acotar(m: str) -> str:
            seg = a_segundos(m or "")
            return mmss(ultimo) if seg is not None and seg > techo else m

        cands = []
        for t in res["tarjetas"]:
            m = acotar(t["minuto"])
            cands.append({**t, "minuto": m, "t_seg": a_segundos(m or "")})
        hueco = max(0, self.cfg["max_candidatas_confirmar"] - sum(1 for t in s.tarjetas if t.get("estado") == "posible"))
        for c in res["candidatas"][:hueco]:
            m = acotar(c["m"])
            cands.append({"categoria": "contradicción", "texto": c["x"], "minuto": m, "t_seg": a_segundos(m or ""),
                          "responsable": "", "referencia": c["q"], "estado": "posible", "linea": self._linea_cercana(lineas, m),
                          **({"perfil": res["perfil"]} if res.get("perfil") else {})})
        elegidas = TJ.seleccionar(cands, s.tarjetas, self.cfg["max_tarjetas_analisis"])
        nuevas = [self._tarjeta(t) for t in elegidas]
        s.tarjetas.extend(nuevas)
        return nuevas

    async def _confirmar_contradicciones(self) -> None:
        """UNA sola llamada (sonnet) con todas las candidatas de la reunión. Las confirmadas pasan a «confirmada» con su
        explicación; las que no se confirman se retiran. Si la llamada falla, siguen como «posible» y se muestra el error."""
        s = self.sesion
        posibles = [t for t in s.tarjetas if t.get("estado") == "posible"]
        if not posibles:
            return
        items = [{"m": t["minuto"], "x": t["texto"], "q": t.get("referencia", ""), "linea": t.get("linea", "")} for t in posibles]
        try:
            conf = await asyncio.to_thread(self.analista.confirmar, items)
        except ErrorAnalisis as e:
            self._registrar_error(e)
            return
        for i, t in enumerate(posibles):
            if i in conf:
                t["estado"], t["nota"] = "confirmada", conf[i]
            else:
                s.tarjetas.remove(t)
        self.emitir("tarjetas", nuevas=[], todas=[dict(t) for t in s.tarjetas], resumen=s.resumen_acumulado)

    def _tarjeta(self, t: dict) -> dict:
        n = len(self.sesion.tarjetas) + 1
        return {"id": f"t{n}-{random.randrange(16**4):04x}", "analisis": self.n_analisis,
                "referencia": "", "nota": "", **t, "t_seg": a_segundos(t.get("minuto") or "")}

    # ------------------------------------------------------------------ anotaciones del usuario (comentario | pregunta | idea)
    def _en_reunion(self) -> Sesion:
        if not self.sesion or self.estado not in ("grabando", "pausada"):
            raise ValueError("No hay reunión en curso.")
        return self.sesion

    def _guardar_sesion(self) -> None:
        try:
            self.sesion.guardar()
        except Exception as e:  # noqa: BLE001
            self.avisos.append(f"No se pudo guardar la sesión: {e}")

    def entrada_anadir(self, tipo: str, texto: str) -> dict:
        """Se guarda con el minuto actual, va al siguiente análisis como las notas y entra en el .md. Nunca es una decisión."""
        s = self._en_reunion()
        e = s.anadir_entrada(tipo, texto, self.reloj.ahora())
        self._guardar_sesion()
        self.emitir("entradas", entradas=[dict(x) for x in s.entradas])
        return e

    def entrada_editar(self, ident: str, texto: str, tipo: str | None = None) -> dict:
        s = self._en_reunion()
        e = s.editar_entrada(ident, texto, tipo)
        self._guardar_sesion()
        self.emitir("entradas", entradas=[dict(x) for x in s.entradas])
        return e

    def entrada_borrar(self, ident: str) -> dict:
        s = self._en_reunion()
        s.borrar_entrada(ident)
        self._guardar_sesion()
        self.emitir("entradas", entradas=[dict(x) for x in s.entradas])
        return {"ok": True}

    # ------------------------------------------------------------------ objetivos propios y sugeridos
    def _incorporar_objetivos_sugeridos(self, textos: list[str]) -> None:
        """Los del digest entran marcados como sugeridos y NO se envían al modelo hasta que el usuario los confirma."""
        s = self.sesion
        existentes = [o["texto"] for o in s.objetivos]
        for t in textos[: self.cfg["max_objetivos_sugeridos"]]:
            if any(TJ.solapamiento(t, e)[0] >= 0.6 for e in existentes):
                continue
            s.objetivos.append(PL.objetivo_nuevo(max([o["n"] for o in s.objetivos] + [0]) + 1, t, "sugerido", True))
            existentes.append(t)
        self._guardar_sesion()
        self.emitir("objetivos", objetivos=[dict(o) for o in s.objetivos])

    def objetivo_operar(self, operacion: str, n: int | None = None, texto: str = "") -> list[dict]:
        s = self._en_reunion()
        texto = " ".join((texto or "").split())[:200]
        if operacion == "anadir":
            if not texto:
                raise ValueError("Escribe el objetivo.")
            if len(s.objetivos) >= 20:
                raise ValueError("Ya hay 20 objetivos; quita alguno antes de añadir otro.")
            s.objetivos.append(PL.objetivo_nuevo(max([o["n"] for o in s.objetivos] + [0]) + 1, texto, "usuario"))
        else:
            o = next((x for x in s.objetivos if x["n"] == n), None)
            if o is None:
                raise ValueError("Ese objetivo ya no existe.")
            if o.get("origen") == "plan" and operacion in ("editar", "borrar", "descartar"):
                raise ValueError("Los objetivos del plan no se editan aquí.")
            if operacion == "editar":
                if not texto:
                    raise ValueError("El objetivo no puede quedar vacío.")
                o["texto"], o["sugerido"], o["origen"] = texto, False, "usuario" if o["origen"] == "sugerido" else o["origen"]
            elif operacion == "confirmar":
                o["sugerido"] = False
            elif operacion in ("borrar", "descartar"):
                s.objetivos.remove(o)
            else:
                raise ValueError("Operación no válida.")
        self._guardar_sesion()
        self.emitir("objetivos", objetivos=[dict(o) for o in s.objetivos])
        return [dict(o) for o in s.objetivos]

    # ------------------------------------------------------------------ «Pregúntale»: una llamada por pregunta, solo si el usuario la lanza
    async def consultar(self, pregunta: str, modelo: str = "haiku") -> dict:
        """Respuesta corta a una pregunta del usuario con el digest, el resumen por tramos, las últimas líneas y, solo si la
        pregunta los nombra, extractos locales de ficheros de contexto. No ejecuta nada; la transcripción sigue siendo dato no fiable."""
        s = self._en_reunion()
        pregunta = " ".join((pregunta or "").split())
        if len(pregunta) < 3:
            raise ValueError("Escribe la pregunta.")
        if modelo not in ("haiku", "sonnet"):
            raise ValueError("El modelo de la consulta debe ser haiku o sonnet.")
        if self._consulta_en_curso:
            raise ValueError("Ya hay una consulta en curso; espera a su respuesta.")
        if len(s.consultas) >= 60:
            raise ValueError("Se ha alcanzado el máximo de consultas de esta reunión.")
        pregunta = pregunta[:400]
        t = self.reloj.ahora()
        reg = {"id": f"q{len(s.consultas) + 1}", "pregunta": pregunta, "modelo": modelo, "minuto": mmss(t), "t_seg": round(t, 1),
               "estado": "en_curso", "respuesta": "", "citas": [], "base": None, "error": "", "tokens": None}
        s.consultas.append(reg)
        self._consulta_en_curso = True
        self.emitir("consultas", consultas=[dict(c) for c in s.consultas])
        n0 = len(self.consumo.llamadas)
        try:
            if self._digest_tarea and not self._digest_tarea.done():
                await asyncio.wait({self._digest_tarea}, timeout=20)
            lineas = limpiar_transcripcion(s.segmentos[-self.cfg["consulta_lineas"] * 3:])[-self.cfg["consulta_lineas"]:]
            trans = formatear_lineas(lineas)[-self.cfg["consulta_chars_transcripcion"]:]
            extractos = await asyncio.to_thread(CX.extractos_para_pregunta, self.g, s.proyecto, pregunta,
                                                self.cfg["consulta_chars_extractos"], self.cfg["consulta_max_ficheros"])
            self.analista.ficheros_digest = list(self.digest_ficheros)
            r = await asyncio.to_thread(self.analista.consultar, pregunta, self.digest, s.resumen_completo or s.resumen_acumulado,
                                        trans, extractos, t, modelo == "sonnet")
            reg.update(estado="ok", respuesta=r["respuesta"], citas=r["citas"], base=r["base"])
        except ErrorAnalisis as e:
            reg.update(estado="error", error=e.mensaje)
        except Exception as e:  # noqa: BLE001
            reg.update(estado="error", error=f"No se pudo responder: {e}")
        finally:
            self._consulta_en_curso = False
            reg["tokens"] = sum(u.get("entrada", 0) + u.get("cache_creacion", 0) + u.get("cache_lectura", 0) + u.get("salida", 0)
                                for c in self.consumo.llamadas[n0:] if str(c.get("tarea", "")).startswith("consulta") for u in c.get("uso", [])) or None
            if self.sesion is s:
                self._guardar_sesion()
            self.emitir("consultas", consultas=[dict(c) for c in s.consultas])
            self.emitir("consumo", **self.consumo.resumen())
        return dict(reg)

    # ------------------------------------------------------------------ «Contexto de la reunión» (inicio): dictar, generar con Claude, guardar
    def _bloqueo_dictado(self) -> str | None:
        """El dictado y la reunión comparten micro y modelo de transcripción: con una reunión en marcha (o por revisar) no se dicta."""
        if self.estado != "inactivo":
            return "Hay una reunión en curso: el dictado del contexto no está disponible."
        if self._contexto_en_curso:
            return "Espera a que Claude termine de generar el contexto."
        return None

    async def generar_contexto_reunion(self, texto: str, tema: str = "") -> dict:
        """«Generar con Claude»: UNA llamada (haiku, tarea `contexto_reunion`), solo cuando el usuario la pide, sin reintentos, por
        `Analista._llamar` (se mide en consumo.jsonl y va en serie con el resto de llamadas). El texto del usuario es dato no fiable y
        la salida se valida. No aplica nada: devuelve {contexto, objetivos, tokens} para que el usuario lo edite y lo acepte."""
        if self.estado != "inactivo":
            raise ValueError("El contexto se prepara antes de empezar la reunión.")
        texto = P.limpiar_texto_usuario(texto, P.MAX_TEXTO_CTX + 1)
        if len(texto.split()) < 3:
            raise ValueError("Escribe o dicta algo de contexto antes de pedir a Claude que lo ordene.")
        if len(texto) > P.MAX_TEXTO_CTX:
            raise ValueError(f"El texto es demasiado largo ({P.MAX_TEXTO_CTX:,} caracteres como máximo): recórtalo.".replace(",", "."))
        if self.dictado.activo:
            raise ValueError("Para el dictado antes de generar el contexto.")
        if self._contexto_en_curso:
            raise ValueError("Ya se está generando el contexto: espera a que termine.")
        tema = " ".join((tema or "").split())[:120]
        self._contexto_en_curso = True
        n0 = len(self.consumo.llamadas)
        try:
            analista = Analista(self.llm, self.cfg, self.consumo, self.g, "previa")
            self.sonda.instrumentar(analista)   # mismo punto único: traza real y un solo cerrojo para todas las llamadas
            try:
                r = await asyncio.to_thread(analista.contexto_reunion, tema, texto)
            except ErrorAnalisis as e:
                raise ValueError(e.mensaje)
            except ValueError:
                raise
            except Exception as e:  # noqa: BLE001
                raise ValueError(f"No se pudo generar el contexto: {e}")
        finally:
            self._contexto_en_curso = False
        tokens = sum(u.get("entrada", 0) + u.get("cache_creacion", 0) + u.get("cache_lectura", 0) + u.get("salida", 0)
                     for c in self.consumo.llamadas[n0:] if c.get("tarea") == "contexto_reunion" for u in c.get("uso", []))
        return {**r, "tokens": tokens or None, "modelo": self.cfg.modelo("contexto_reunion")}

    def guardar_contexto_reunion(self, proyecto: str | None, tema: str, texto: str, objetivos: list[str] | None = None) -> dict:
        """Casilla opcional «Guardar en el contexto del proyecto»: escribe `NN-contexto-reunion-<tema>.md` con `Guardian.escribir_contexto`
        y una entrada en `10-registro-de-cambios.md`. No hay Bandeja; en un proyecto compartido solo si ya tiene «00. CONTEXTO (IA)»."""
        if not proyecto:
            raise ValueError("La Bandeja no tiene contexto de proyecto donde guardar.")
        texto = P.limpiar_texto_usuario(texto)
        if not texto:
            raise ValueError("No hay contexto que guardar.")
        tema = " ".join((tema or "").split())[:120] or "Reunión sin título"
        autor = self.cfg["autor"]
        carpeta = self.g.proyecto_dir(proyecto) / CARPETA_CONTEXTO   # RutaProhibida si el proyecto no es válido
        creada = not carpeta.is_dir()
        if creada and self.g.es_compartido(proyecto):
            raise ValueError("Este proyecto es una carpeta compartida y no tiene «00. CONTEXTO (IA)»: WhisperMeet no la crea ahí, así que no se guarda.")
        if creada:
            CX.materializar_contexto(self.g, proyecto, autor)
        fichero = f"{CX.siguiente_numero_contexto(self.g, proyecto):02d}-contexto-reunion-{slug(tema, 60)}.md"
        if self.g.ruta_contexto(proyecto, fichero).exists():
            raise ValueError("Ya existe ese fichero de contexto; no se sobrescribe.")
        objs = [" ".join(str(o).split())[:200] for o in (objetivos or []) if isinstance(o, str) and str(o).strip()][:12]
        cuerpo = (f"# Contexto de la reunión: {tema}\n\n"
                  f"> Preparado antes de la reunión con ayuda de Claude (WhisperMeet). Lo ha revisado y aceptado {autor} el {date.today().isoformat()}.\n\n"
                  f"{texto}\n")
        if objs:
            cuerpo += "\n## Objetivos propuestos\n\n" + "\n".join(f"- {o}" for o in objs) + "\n"
        self.g.escribir_contexto(proyecto, fichero, cuerpo)
        registro, _ = CX.contenido_actual(self.g, proyecto, "10-registro-de-cambios.md", autor)
        self._escribir_respetando_eol("10-registro-de-cambios.md",
                                      CB.insertar_en_registro(registro or "", CB.entrada_registro_contexto(autor, tema, fichero)), proyecto)
        return {"fichero": fichero, "ruta": str(self.g.ruta_contexto(proyecto, fichero)), "carpeta_creada": creada,
                "compartido": self.g.es_compartido(proyecto)}

    # ------------------------------------------------------------------ checks de preparación
    def _base_checks(self) -> list[str]:
        ses = self._plan_sesion if self.sesion and self.sesion.plan_id else None
        return list(ses["checks"]) if ses else []

    def _bloques_finales(self) -> str:
        s = self.sesion
        return "\n\n".join(b for b in (PL.resumen_markdown(PL.activos(s.objetivos), s.plan_nombre),
                                        CK.resumen_markdown(s.checks, s.plan_nombre),
                                        AS.bloque_final(s.respuestas, s.consejos)) if b).strip()

    def _sync_checks(self) -> None:
        """Recarga los checks de la sesión desde el almacén local, los guarda en el .md y avisa a la interfaz."""
        s = self.sesion
        if not s:
            return
        s.checks = self.checks.listar(s.proyecto, s.plan_id or None, self._base_checks())
        try:
            s.guardar()
        except Exception as e:  # noqa: BLE001
            self.avisos.append(f"No se pudo guardar la sesión: {e}")
        self.emitir("checks", checks=[dict(c) for c in s.checks])

    def _resolver_checks(self, proyecto: str | None, sesion: str | None) -> tuple[str | None, str | None, list[str]]:
        proyecto = proyecto or None
        sid = (sesion or "").strip() or None
        if sid == "general":
            sid = None
        plan = PL.plan_de(self.g, proyecto) if proyecto else None
        if plan:
            ses = PL.sesion_de(plan, sid)  # ValueError si la sesión no existe en el plan
            return proyecto, sid, list(ses["checks"]) if ses else []
        if sid is not None:
            raise ValueError("Este proyecto no tiene plan de sesiones.")
        return proyecto, None, []

    def _tras_cambio_checks(self, proyecto, sid) -> None:
        s = self.sesion
        if s and s.proyecto == proyecto and (s.plan_id or None) == sid:
            self._sync_checks()

    def checks_listar(self, proyecto, sesion) -> list[dict]:
        proyecto, sid, base = self._resolver_checks(proyecto, sesion)
        return self.checks.listar(proyecto, sid, base)

    def checks_operar(self, proyecto, sesion, operacion: str, ident: str | None = None, texto: str = "",
                      hecho: bool | None = None) -> list[dict]:
        proyecto, sid, base = self._resolver_checks(proyecto, sesion)
        if operacion == "anadir":
            out = self.checks.anadir(proyecto, sid, texto, base)
        elif operacion == "editar":
            out = self.checks.editar(proyecto, sid, ident, texto, base)
        elif operacion == "borrar":
            out = self.checks.borrar(proyecto, sid, ident, base)
        elif operacion == "marcar":
            out = self.checks.marcar(proyecto, sid, ident, bool(hecho), base)
        elif operacion == "deshacer":
            out = self.checks.deshacer_auto(proyecto, sid, ident, base)
        else:
            raise ValueError("Operación no válida.")
        self._tras_cambio_checks(proyecto, sid)
        return out

    # ------------------------------------------------------------------ terminar y revisar
    async def terminar(self) -> dict:
        if self.estado not in ("grabando", "pausada"):
            raise ValueError("No hay reunión en curso.")
        s = self.sesion
        self.estado = "terminando"
        self.reloj.pausar()
        self._emitir_estado()
        if self.captura:
            await asyncio.to_thread(self.captura.detener)
        if self.transcriptor:
            fin = time.time() + 180
            while not self.transcriptor.vacio() and time.time() < fin and self.transcriptor.estado != "error":
                await asyncio.sleep(0.3)
            self.transcriptor.detener()
        for t in self._tareas:
            if t is not asyncio.current_task() and t is not self._digest_tarea:
                t.cancel()
        fin = time.time() + 120
        while (self.analizando or self.equipo.en_curso) and time.time() < fin:   # un turno del equipo en curso termina antes del cierre
            await asyncio.sleep(0.3)
        s.duracion_s = self.reloj.ahora()
        s.estado = "finalizada"
        await asyncio.to_thread(s.guardar)
        self.revision = {"estado": "generando", "resumen": "", "cambios": [], "error": "", "aplicado": None,
                         "carpeta_contexto": None, "compartido": s.compartido, "destino_contexto": "", "sin_cambios": "", "resumen_sonnet": "", "pulido": self._pulido_inicial(),
                         "objetivos": [], "avisos": [], "publicacion": self._publicacion_inicial()}
        self.estado = "revision"
        self._emitir_estado()
        asyncio.get_running_loop().create_task(self._generar_revision())
        return {"ok": True}

    async def reintentar_revision(self) -> None:
        if self.estado == "revision" and self.revision and self.revision["estado"] == "error":
            self.revision.update(estado="generando", error="")
            self._emitir_estado()
            asyncio.get_running_loop().create_task(self._generar_revision())

    def _contenidos(self, proyecto: str) -> dict[str, str | None]:
        """fichero -> texto actual, o plantilla si la carpeta aún no existe."""
        existentes = CX.ficheros_contexto(self.g, proyecto)
        if existentes:
            return dict(existentes)
        return {k: CX.plantilla_renderizada(k, proyecto, self.cfg["autor"]) for k in CX.plantillas() if "/" not in k}

    async def _generar_revision(self) -> None:
        s, rev = self.sesion, self.revision
        try:
            s.checks = self.checks.listar(s.proyecto, s.plan_id or None, self._base_checks())
            nuevos = s.nuevos_desde_ultimo_analisis(final=True)
            cierre = COB.preparar_cierre(s, self.cfg["final_chars_tramo"], self.cfg["final_chars_huecos"])   # local: sin llamadas nuevas
            self._cierre = cierre
            if not nuevos and not s.notas.strip() and not s.tarjetas and not cierre.hay and not s.resumen_completo.strip():
                s.resumen_final = ("La reunión no tiene contenido que resumir.\n\n" + self._bloques_finales()).strip()
                s.avisos_resumen = []
                s.resumen_modelo = ""
                rev.update(estado="lista", resumen=s.resumen_final, resumen_sonnet=s.resumen_final, pulido=self._pulido_inicial(), objetivos=[dict(o) for o in s.objetivos],
                           avisos=[], **self._datos_destino())
                return
            if self._digest_tarea and not self._digest_tarea.done():
                await asyncio.wait({self._digest_tarea}, timeout=60)
            tramo = cierre.tramo
            await self._confirmar_contradicciones()  # la ÚNICA llamada de confirmación de la reunión
            titulos = TJ.lineas_compactas(s.tarjetas)  # TODAS las tarjetas, de la primera a la última
            ficheros: dict[str, str] = {}
            if s.proyecto:
                consulta = " ".join([s.resumen_completo, s.notas, tramo, " ".join(titulos)])
                ficheros = await asyncio.to_thread(CX.ficheros_para_final, self.g, s.proyecto, consulta, self.cfg["autor"],
                                                   self.cfg["final_max_ficheros"], self.cfg["final_tope_fichero"])
            notas_final = "\n".join(x for x in [s.notas_nuevas()] + [s.linea_entrada(e) for e in s.entradas] if x)
            res = await asyncio.to_thread(self.analista.final, self.digest, s.resumen_completo or s.resumen_acumulado, titulos,
                                          notas_final, tramo, ficheros, PL.para_prompt(s.objetivos), mmss(s.duracion_s),
                                          self.equipo.definiciones.lineas(), cierre.huecos)
            PL.aplicar_por_posicion(s.objetivos, res.get("objetivos") or [])
            s.resumen_modelo = res["resumen"]
            s.resumen_final = (res["resumen"] + "\n\n" + self._bloques_finales()).strip()
            s.avisos_resumen = COB.avisos(res["resumen"], cierre, s)   # comprobación local: no borra ni corrige nada
            cambios = []
            if s.proyecto:
                contenidos = await asyncio.to_thread(self._contenidos, s.proyecto)
                cambios = [c.publico() for c in CB.normalizar(res["cambios"], contenidos)]
            carpeta_existe = bool(s.proyecto) and (self.g.proyecto_dir(s.proyecto) / "00. CONTEXTO (IA)").is_dir()
            sin_cambios = ""
            if s.proyecto and not any(c["valido"] for c in cambios):
                sin_cambios = res.get("sin_cambios") or "El modelo no propuso cambios y no indicó el motivo."
            rev.update(estado="lista", resumen=s.resumen_final, resumen_sonnet=s.resumen_final, pulido=self._pulido_inicial(),
                       cambios=cambios, error="", carpeta_contexto=carpeta_existe,
                       sin_cambios=sin_cambios,
                       objetivos=[dict(o) for o in s.objetivos], avisos=list(s.avisos_resumen), **self._datos_destino())
            await asyncio.to_thread(s.guardar)
        except ErrorAnalisis as e:
            self._registrar_error(e)
            rev.update(estado="error", error=e.mensaje)
        except Exception as e:  # noqa: BLE001
            rev.update(estado="error", error=f"No se pudo generar el resumen final: {e}")
        finally:
            self.emitir("consumo", **self.consumo.resumen())
            self._emitir_estado()

    @staticmethod
    def _pulido_inicial() -> dict:
        return {"estado": "ninguno", "resumen": "", "error": "", "elegida": "sonnet"}   # ninguno | generando | listo | error

    async def pulir(self) -> dict:
        """Botón opcional «Pulir con Opus» (única excepción a «nunca opus»; jamás se llama solo). UNA llamada, sin
        reintentos, con el resumen de sonnet y las tarjetas compactas. NO sustituye al de sonnet hasta que el usuario
        lo elige; si falla, la revisión sigue con la versión de sonnet."""
        s, rev = self.sesion, self.revision
        if self.estado != "revision" or not rev or rev["estado"] != "lista":
            raise ValueError("No hay revisión lista para pulir.")
        p = rev["pulido"]
        if p["estado"] in ("generando", "listo"):
            raise ValueError("Ya se está puliendo el resumen." if p["estado"] == "generando" else "Ya hay una versión pulida.")
        if not s.resumen_modelo.strip():
            raise ValueError("No hay resumen que pulir.")
        p.update(estado="generando", error="")
        self._emitir_estado()
        try:
            texto = await asyncio.to_thread(self.analista.pulir, s.resumen_modelo, TJ.lineas_compactas(s.tarjetas), mmss(s.duracion_s))
        except ErrorAnalisis as e:
            p.update(estado="error", error=e.mensaje)
        except Exception as e:  # noqa: BLE001
            p.update(estado="error", error=f"No se pudo pulir el resumen: {e}")
        else:
            p.update(estado="listo", error="", resumen=(texto + "\n\n" + self._bloques_finales()).strip())
        finally:
            self.emitir("consumo", **self.consumo.resumen())
            self._emitir_estado()
        return {"ok": p["estado"] == "listo", "error": p["error"]}

    async def elegir_resumen(self, version: str) -> dict:
        """Elige con qué versión del resumen se queda el usuario ('sonnet' u 'opus'); solo la elegida va al .md y a lo publicado."""
        s, rev = self.sesion, self.revision
        if self.estado != "revision" or not rev or rev["estado"] != "lista":
            raise ValueError("No hay revisión lista.")
        p = rev["pulido"]
        if version == "opus":
            if p["estado"] != "listo":
                raise ValueError("No hay versión pulida que elegir.")
            s.resumen_final = p["resumen"]
        elif version == "sonnet":
            s.resumen_final = rev["resumen_sonnet"]
        else:
            raise ValueError("Versión no válida.")
        p["elegida"] = version
        s.avisos_resumen = COB.avisos(s.resumen_modelo if version == "sonnet" else p["resumen"], self._cierre, s)
        rev["avisos"] = list(s.avisos_resumen)
        rev["resumen"] = s.resumen_final
        await asyncio.to_thread(s.guardar)
        self._emitir_estado()
        return {"ok": True, "elegida": version}

    def _datos_destino(self) -> dict:
        """Aviso para la revisión: si el contexto está en una carpeta compartida, dónde se escribiría."""
        s = self.sesion
        if not s or not s.proyecto or not s.compartido:
            return {"compartido": False, "destino_contexto": ""}
        return {"compartido": True, "destino_contexto": str(self.g.proyecto_dir(s.proyecto) / CARPETA_CONTEXTO)}

    def revision_publica(self) -> dict | None:
        rev, s = self.revision, self.sesion
        if rev and s and rev.get("estado") == "lista":   # borrador del correo de cierre: local, sin modelo; solo se copia, nunca se envía
            return {**rev, "correo": CC.correo_de_sesion(s)}
        return rev

    async def aplicar_revision(self, aceptados: list[str]) -> dict:
        s, rev = self.sesion, self.revision
        if self.estado != "revision" or not rev or rev["estado"] != "lista":
            raise ValueError("No hay revisión lista para aplicar.")
        if not s.proyecto:
            raise ValueError("La bandeja no tiene ficheros de contexto que actualizar.")
        res = await asyncio.to_thread(self._aplicar, set(aceptados))
        rev["aplicado"] = res
        self._emitir_estado()
        return res

    def _aplicar(self, aceptados: set[str]) -> dict:
        s, rev = self.sesion, self.revision
        elegidos = [c for c in rev["cambios"] if c["id"] in aceptados and c["valido"]]
        if not elegidos:
            return {"aplicados": [], "omitidos": [], "ficheros": [], "carpeta_creada": False, "registro": False}
        autor = self.cfg["autor"]
        carpeta = self.g.proyecto_dir(s.proyecto) / "00. CONTEXTO (IA)"
        carpeta_creada = not carpeta.is_dir()
        if carpeta_creada and s.compartido:
            raise ValueError("La carpeta «00. CONTEXTO (IA)» no existe en el proyecto compartido y WhisperMeet no la crea ahí.")
        trabajo: dict[str, str] = {}
        aplicados, omitidos = [], []
        for d in elegidos:
            c = CB.Cambio(**{k: d[k] for k in ("id", "fichero", "tipo", "motivo", "minuto", "seccion", "anterior", "nuevo")})
            try:
                if c.fichero not in trabajo:
                    if c.tipo == "crear":
                        trabajo[c.fichero] = ""
                    else:
                        actual, _ = CX.contenido_actual(self.g, s.proyecto, c.fichero, autor)
                        if actual is None:
                            raise ValueError("el fichero no existe")
                        trabajo[c.fichero] = actual
                trabajo[c.fichero] = CB.aplicar(trabajo[c.fichero], c)
                aplicados.append(c.id)
            except (ValueError, RutaProhibida) as e:
                omitidos.append({"id": c.id, "motivo": str(e)})
        if not aplicados:
            return {"aplicados": [], "omitidos": omitidos, "ficheros": [], "carpeta_creada": False, "registro": False}
        if carpeta_creada:
            CX.materializar_contexto(self.g, s.proyecto, autor)
        for fichero, texto in trabajo.items():
            self._escribir_respetando_eol(fichero, texto)
        registro_actual, _ = CX.contenido_actual(self.g, s.proyecto, "10-registro-de-cambios.md", autor)
        # redacción neutra en proyectos compartidos: el usuario puede elegir publicar o no después de aplicar
        entrada = CB.entrada_registro(autor, s.tema, sorted(trabajo), s.ruta.name, local=s.compartido)
        self._escribir_respetando_eol("10-registro-de-cambios.md", CB.insertar_en_registro(registro_actual or "", entrada))
        s.cambios_aplicados = sorted(trabajo)
        s.guardar()
        for d in rev["cambios"]:
            d["estado"] = "aplicado" if d["id"] in aplicados else d.get("estado", "")
        return {"aplicados": aplicados, "omitidos": omitidos, "ficheros": sorted(trabajo),
                "carpeta_creada": carpeta_creada, "registro": True}

    def _escribir_respetando_eol(self, fichero: str, texto: str, proyecto: str | None = None) -> None:
        proyecto = proyecto or self.sesion.proyecto
        destino = self.g.ruta_contexto(proyecto, fichero)
        crlf = destino.is_file() and b"\r\n" in destino.read_bytes()[:4096]
        self.g.escribir_contexto(proyecto, fichero, texto.replace("\n", "\r\n") if crlf else texto)

    # ------------------------------------------------------------------ publicación (proyectos compartidos)
    def _publicacion_inicial(self) -> dict | None:
        """Solo en proyectos compartidos: el documento final se publica en su «02. Sesiones» al cerrar la revisión
        (por defecto sí; el usuario puede elegir no publicar). Aquí solo se calcula el destino previsto."""
        s = self.sesion
        if not s or not s.proyecto or not s.compartido:
            return None
        carpeta = self.g.proyecto_dir(s.proyecto) / CARPETA_SESIONES
        try:
            destino = str(self.g.ruta_publicacion(s.proyecto, s.inicio.date().isoformat(), s.tema))
            error = ""
        except RutaProhibida as e:
            destino, error = "", f"No se puede publicar en esta carpeta: {e}"
        return {"aplica": True, "publicar": True, "destino": destino, "carpeta": str(carpeta),
                "carpeta_existe": carpeta.is_dir(), "estado": "error" if error else "pendiente", "error": error, "ruta": ""}

    async def elegir_publicacion(self, publicar: bool) -> dict:
        rev = self.revision
        p = rev.get("publicacion") if self.estado == "revision" and rev else None
        if not p:
            raise ValueError("Esta reunión no se publica en ninguna carpeta compartida.")
        if p["estado"] == "publicada":
            raise ValueError("El documento ya está publicado.")
        p["publicar"] = bool(publicar)
        if publicar and p["estado"] == "omitida":
            p["estado"] = "pendiente"
        self._emitir_estado()
        return p

    async def publicar(self) -> dict:
        """Publica ahora (también sirve para reintentar). Si falla, se muestra el error y la copia local se conserva."""
        s, rev = self.sesion, self.revision
        p = rev.get("publicacion") if self.estado == "revision" and rev else None
        if not p:
            raise ValueError("Esta reunión no se publica en ninguna carpeta compartida.")
        if rev["estado"] == "generando":
            raise ValueError("Espera a que termine el resumen final antes de publicar.")
        if p["estado"] == "publicada":
            return {"ok": True, "ruta": p["ruta"]}
        try:
            ruta = await asyncio.to_thread(self.g.publicar_sesion, s.proyecto, s.inicio.date().isoformat(), s.tema,
                                           s.render(publicado=True))
        except (OSError, RutaProhibida) as e:
            p.update(estado="error", error=f"No se pudo publicar en la carpeta compartida: {e}. La copia local se conserva en {s.ruta}.")
            self._emitir_estado()
            return {"ok": False, "error": p["error"]}
        p.update(estado="publicada", error="", ruta=str(ruta), publicar=True)
        s.publicada_en = str(ruta)
        try:
            await asyncio.to_thread(s.guardar)
        except Exception:  # noqa: BLE001
            pass
        self._emitir_estado()
        return {"ok": True, "ruta": str(ruta)}

    async def cerrar_revision(self, publicar: bool | None = None) -> dict:
        """Cierra la revisión. En un proyecto compartido publica antes el documento final (salvo que se elija no
        publicar); si la publicación falla NO se cierra: se muestra el error y se puede reintentar."""
        if self.estado != "revision":
            return {"ok": True}
        rev = self.revision
        p = rev.get("publicacion") if rev else None
        if p:
            if publicar is not None and p["estado"] != "publicada":
                p["publicar"] = bool(publicar)
            if p["publicar"] and p["estado"] != "publicada":
                r = await self.publicar()
                if not r["ok"]:
                    return r
            elif not p["publicar"]:
                p["estado"] = "omitida"
        ruta = p["ruta"] if p else ""
        self.estado = "inactivo"
        self.sesion = None
        self.revision = None
        self.transcriptor = self.captura = None
        self._tareas = []
        self.fuentes.olvidar_reunion()
        self._emitir_estado()
        return {"ok": True, "ruta": ruta}

    # ------------------------------------------------------------------ apagado
    def apagar(self) -> None:
        """Cierre de la app: deja constancia de que la sesión quedó interrumpida."""
        try:
            self.dictado.cancelar()
        except Exception:  # noqa: BLE001
            pass
        s = self.sesion
        if s and s.estado == "en curso":
            s.estado = "interrumpida"
            s.duracion_s = max(s.duracion_s, self.reloj.ahora())
            try:
                s.guardar()
            except Exception:  # noqa: BLE001
                pass
        if self.captura:
            try:
                self.captura.detener()
            except Exception:  # noqa: BLE001
                pass
        if self.transcriptor:
            self.transcriptor.detener()
