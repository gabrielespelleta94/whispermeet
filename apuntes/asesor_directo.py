"""El asesor en directo, parte VIVA: detecta preguntas del cliente en la reunión y propone qué responder, y atiende «Profundizar».

Qué hace (nada de esto llama al modelo salvo lo indicado):
- cada segundo, el bucle de la grabación le pasa lo nuevo (`observar`): Reunión al momento, Micro cuando ya es definitivo (sin el eco de Reunión);
  el detector local (`asesor.detectar_preguntas`) saca las interrogativas con contenido; las repetidas (la misma frase en Micro y en Reunión) se juntan;
- una pregunta nueva espera su turno: como máximo UNA respuesta cada `asesor_respuesta_cada_s` (20 s) y, si llegan varias, gana la más reciente;
- entonces, UNA llamada a haiku (`asesor_respuesta`) que se adelanta a los turnos del equipo en la cola de llamadas (siguen en serie) con las fuentes
  mejor puntuadas por el índice local (`fuentes.py`). Si la pregunta toca precio, alcance, plazos, contrato, competencia o compromiso, DESPUÉS otra a sonnet
  (`asesor_respuesta_sonnet`) que afina la respuesta, dentro del límite de sonnet por hora (`config.ASESOR_SONNET_HORA`);
- «Profundizar» (`profundizar`): UNA llamada a sonnet con más extractos y, solo si el usuario lo marca, la búsqueda web de `claude -p` con la entrada
  anonimizada y un prompt que exige consultas genéricas.
Presupuesto PROPIO (`presupuesto_asesor_tokens_hora`, ventana de 60 min de reunión): al 80 % no hay sonnet automático y al 100 % no hay llamadas automáticas
(«Profundizar» sigue, el usuario lo pidió). Un fallo se muestra en su tarjeta y nunca detiene la grabación.
"""
from __future__ import annotations

import asyncio

from . import asesor as A
from .analisis import ErrorAnalisis
from .config import ASESOR_SONNET_HORA
from .equipo.presupuesto import Presupuesto
from .fuentes import Doc, Indice, Resultado, fusionar, trocear_transcripcion
from .texto import ETIQUETAS, formatear_lineas, limpiar_transcripcion, mmss

CADUCA_PREGUNTA_S = 90      # una pregunta que lleva tanto esperando turno ya no es de la conversación en curso
VENTANA_DUPLICADAS_S = 90   # la misma frase en Micro y en Reunión (o repetida) cuenta una vez
MAX_RESPUESTAS = 80         # por reunión, de seguridad
MAX_VISTAS = 60


class Asesor:
    def __init__(self, gestor):
        self.g = gestor
        self.presupuesto = Presupuesto(gestor.cfg["presupuesto_asesor_tokens_hora"])
        self.tokens = 0
        self.reiniciar()

    # ------------------------------------------------------------------ estado
    def reiniciar(self) -> None:
        self.cursor_r = 0                       # segmentos de Reunión ya mirados (índice en `sesion.segmentos`)
        self.cursor_m = 0                       # id del último segmento ya entregado por `Sesion.estables` (Micro, sin eco)
        self.vistas: list[tuple[float, str]] = []
        self.pendiente: dict | None = None
        self.ultimo_lanzamiento = -1e9
        self.en_curso = False
        self.sonnet_t: list[float] = []
        self.n_r = self.n_c = 0
        self.stats = {"detectadas": 0, "duplicadas": 0, "sustituidas": 0, "caducadas": 0, "sin_presupuesto": 0}
        self.presupuesto = Presupuesto(self.g.cfg["presupuesto_asesor_tokens_hora"])
        self.tokens = 0
        self._web: tuple[bool, str] | None = None

    @property
    def sesion(self):
        return self.g.sesion

    def ahora(self) -> float:
        return self.g.reloj.ahora()

    def nivel(self) -> str:
        self.presupuesto.fijar_limite(self.g.cfg["presupuesto_asesor_tokens_hora"])
        return self.presupuesto.nivel(self.ahora())

    def sonnet_usados(self, ahora: float | None = None) -> int:
        ahora = self.ahora() if ahora is None else ahora
        return sum(1 for t in self.sonnet_t if ahora - t < 3600)

    def sonnet_disponible(self, ahora: float | None = None) -> bool:
        """Sonnet automático: dentro del límite por hora y mientras el presupuesto del asesor no llegue al 80 %."""
        ahora = self.ahora() if ahora is None else ahora
        return self.sonnet_usados(ahora) < ASESOR_SONNET_HORA and self.nivel() == "normal"

    def web_disponible(self) -> tuple[bool, str]:
        """¿Ofrece esta versión de `claude -p` la búsqueda web? (consulta `claude --help` una vez, sin tokens). La configuración puede apagarla."""
        if not self.g.cfg["asesor_web"]:
            return False, "La búsqueda web está desactivada en la configuración."
        if self._web is None:
            from .analisis.claude_cli import capacidad_web
            self._web = capacidad_web()
        return self._web

    def sondear_web(self) -> None:
        """Calcula la capacidad web en un hilo (la app lo hace al arrancar; los tests no)."""
        import threading
        threading.Thread(target=lambda: self.web_disponible(), daemon=True, name="asesor-web").start()

    # ------------------------------------------------------------------ detección local (cada segundo, sin modelo)
    def _nueva(self, t: float, pregunta: str, canal: str, antecedente: str = "") -> None:
        if any(abs(t - ts) <= VENTANA_DUPLICADAS_S and A.parecida(pregunta, q, 0.6) for ts, q in self.vistas):
            self.stats["duplicadas"] += 1
            return
        self.vistas.append((t, pregunta))
        del self.vistas[:-MAX_VISTAS]
        self.stats["detectadas"] += 1
        if self.pendiente is not None:
            self.stats["sustituidas"] += 1     # llegó otra mientras la anterior esperaba su turno: gana la más reciente
        self.pendiente = {"pregunta": pregunta, "t": t, "canal": canal, "detectada": self.ahora(), "antecedente": antecedente}

    def observar(self) -> int:
        """Mira los segmentos nuevos (Reunión al momento; Micro cuando ya no espera a su pareja de Reunión) y anota las preguntas con contenido.
        Devuelve cuántas nuevas hay. Sin modelo, sin disco."""
        s, g = self.sesion, self.g
        if not s or not g.cfg["asesor_activo"] or g.estado != "grabando":
            return 0
        antes = self.stats["detectadas"]
        nuevos = s.segmentos[self.cursor_r:]
        self.cursor_r += len(nuevos)
        lista = [(x.t, x.texto, "reunion") for x in nuevos if x.fuente == "reunion" and x.texto.strip()]
        micro = s.estables(self.cursor_m)
        if micro:
            self.cursor_m = max(x.id for x in micro)
            lista += [(x.t, x.texto, "yo") for x in micro if x.fuente == "yo"]
        for t, texto, canal in sorted(lista, key=lambda x: x[0]):
            for q, antecedente in A.detectar_con_antecedente(texto):
                self._nueva(t, q, canal, antecedente)
        return self.stats["detectadas"] - antes

    def siguiente(self) -> dict | None:
        """La pregunta que toca responder ahora (y la marca como lanzada), o None: sin pregunta, una respuesta en curso, antes de los 20 s del límite,
        caducada o sin presupuesto. Con el presupuesto agotado la pregunta no se responde sola (queda el aviso en el carril)."""
        p = self.pendiente
        if p is None or self.en_curso:
            return None
        ahora = self.ahora()
        if ahora - p["detectada"] > CADUCA_PREGUNTA_S:
            self.pendiente = None
            self.stats["caducadas"] += 1
            return None
        if ahora - self.ultimo_lanzamiento < self.g.cfg["asesor_respuesta_cada_s"]:
            return None
        if self.nivel() == "agotado":
            self.pendiente = None
            self.stats["sin_presupuesto"] += 1
            self.emitir()
            return None
        if len(self.sesion.respuestas) >= MAX_RESPUESTAS:
            self.pendiente = None
            return None
        self.pendiente = None
        self.en_curso = True
        self.ultimo_lanzamiento = ahora
        return p

    # ------------------------------------------------------------------ lo que ve la interfaz
    def estado_publico(self) -> dict:
        ahora = self.ahora()
        web, motivo = (self._web if self._web is not None else (None, ""))
        if not self.g.cfg["asesor_web"]:
            web, motivo = False, "La búsqueda web está desactivada en la configuración."
        return {"activo": bool(self.g.cfg["asesor_activo"]), "presupuesto": self.presupuesto.publico(ahora, self.g.velocidad if self.g.sim is not None else 1.0),
                "sonnet": {"usados": self.sonnet_usados(ahora), "limite": ASESOR_SONNET_HORA},
                "web": {"disponible": web, "motivo": motivo}, "pendiente": self.pendiente is not None, "en_curso": self.en_curso,
                "tokens": self.tokens, "stats": dict(self.stats), "fuentes": self.g.fuentes.estado()}

    def publico(self) -> dict:
        s = self.sesion
        return {"respuestas": [dict(r) for r in s.respuestas] if s else [], "consejos": [dict(c) for c in s.consejos] if s else [],
                **self.estado_publico()}

    def emitir(self) -> None:
        self.g.emitir("asesor", **self.publico())

    def _guardar(self) -> None:
        try:
            self.sesion.guardar()
        except Exception as e:  # noqa: BLE001
            self.g.avisos.append(f"No se pudo guardar la sesión: {e}")

    # ------------------------------------------------------------------ preparar lo que viaja con una pregunta
    def _transcripcion(self, chars: int) -> tuple[str, list]:
        """(las últimas líneas de la reunión, enteras y hasta `chars` caracteres, y las anteriores a ellas): lo reciente viaja tal cual; lo anterior se busca."""
        s = self.sesion
        lineas = limpiar_transcripcion([x for x in s.segmentos if x.texto.strip()])
        elegidas, usado = [], 0
        for l in reversed(lineas[-30:]):
            tx = formatear_lineas([l])
            if elegidas and usado + len(tx) + 1 > chars:
                break
            elegidas.insert(0, l)
            usado += len(tx) + 1
        return formatear_lineas(elegidas)[-chars:], lineas[:len(lineas) - len(elegidas)]

    def _preparar(self, texto: str, k: int, chars_extractos: int, chars_trans: int, contexto_extra: str = "") -> dict:
        g = self.g
        reciente, anteriores = self._transcripcion(chars_trans)
        contexto = " ".join(reciente.splitlines()[-4:]) + " " + contexto_extra
        extractos = g.fuentes.buscar(texto, contexto, k, chars_extractos)
        propios = bool(g.fuentes.buscar(texto, "", 1, 800))   # ¿hay algo que case con las palabras de la PROPIA pregunta (sin el contexto que ayuda a las elípticas)?
        if anteriores:   # lo dicho antes en ESTA reunión y que ya no cabe en la ventana reciente (p. ej. «el objetivo era el 15 de noviembre», 20 minutos atrás)
            hist = Doc("Esta reunión", "esta_reunion", trocear_transcripcion([{"t": l.t, "m": mmss(l.t), "x": f"{ETIQUETAS.get(l.fuente, 'R')}: {l.texto}"} for l in anteriores],
                                                                           maximo=400))
            extractos = fusionar(extractos, Indice([hist]).buscar(texto, contexto, 2, 1200), k, chars_extractos)
            propios = propios or bool(Indice([hist]).buscar(texto, "", 1, 800))
        entregadas = {r.id: r for r in extractos}
        base = "\n".join([g.digest, reciente] + [r.texto for r in extractos])
        return {"digest": g.digest, "extractos": extractos, "entregadas": entregadas, "transcripcion": reciente, "base": base,
                "ficheros": set(g.digest_ficheros), "propios": propios}

    def _tokens_de(self, tarea: str, n0: int) -> int | None:
        return sum(u.get("entrada", 0) + u.get("cache_creacion", 0) + u.get("cache_lectura", 0) + u.get("salida", 0)
                   for c in self.g.consumo.llamadas[n0:] if c.get("tarea") == tarea for u in c.get("uso", [])) or None

    # ------------------------------------------------------------------ respuesta sugerida
    async def responder(self, p: dict) -> None:
        """UNA llamada a haiku (con prioridad en la cola) y, si el tema es sensible, después otra a sonnet. Nunca lanza: un fallo queda en la tarjeta."""
        g, s = self.g, self.sesion
        if s is None:
            self.en_curso = False
            return
        self.n_r += 1
        temas = A.temas_de(p["pregunta"])
        reg = {"id": f"r{self.n_r}", "pregunta": p["pregunta"], "minuto": mmss(p["t"]), "t_seg": round(p["t"], 1),
               "canal": "Reunión" if p["canal"] == "reunion" else "Micro", "estado": "en_curso", "vinetas": [], "confianza": "", "citas": [],
               "base": None, "sin_base": False, "orientacion": False, "sin_cita": False, "modelo": g.cfg.modelo("asesor_respuesta"), "temas": temas,
               "escalada": "pendiente" if temas else "", "fijada": False, "descartada": False, "profundizada": None, "error": "", "tokens": None}
        s.respuestas.append(reg)
        self.emitir()
        ctx = None
        try:
            if g._digest_tarea and not g._digest_tarea.done():
                await asyncio.wait({g._digest_tarea}, timeout=8)    # el contexto ayuda, pero la pregunta no espera mucho por él
            ctx = await asyncio.to_thread(self._preparar, p["pregunta"] + " " + p.get("antecedente", ""), 6, g.cfg["asesor_chars_extractos"], g.cfg["asesor_chars_transcripcion"])
            ahora_s = max(self.ahora(), p["t"])
            if len(A.palabras_de_contenido(p["pregunta"])) >= 3 and not ctx["propios"] and not A.hay_pista(p["pregunta"], ctx["digest"], ctx["transcripcion"]):
                # una pregunta concreta (≥3 palabras con contenido) sin una sola coincidencia con las fuentes, el contexto ni lo dicho: no hay con qué responder,
                # y no se gasta una llamada en decirlo (las elípticas, «¿y cuánto cuesta?», sí van al modelo: se entienden por lo que se dijo antes)
                self.stats["sin_pista_local"] = self.stats.get("sin_pista_local", 0) + 1
                reg.update(estado="ok", modelo="local", escalada="", tokens=0, **A.respuesta_sin_base_local())
                self.en_curso = False
                if g.sesion is s:
                    self._guardar()
                    self.emitir()
                return
            sistema = A.sistema_respuesta(temas)
            usuario = A.usuario_respuesta(p["pregunta"], reg["minuto"], reg["canal"][0], ctx["digest"], ctx["extractos"], ctx["transcripcion"], mmss(ahora_s),
                                          p.get("antecedente", ""))
            n0 = len(g.consumo.llamadas)
            res = await asyncio.to_thread(g.analista.asesorar, "asesor_respuesta", sistema, usuario,
                                          lambda d: A.normalizar_respuesta(d, ctx["entregadas"], ctx["ficheros"], ahora_s, ctx["base"]))
            reg.update(estado="ok", tokens=self._tokens_de("asesor_respuesta", n0), **res)
        except ErrorAnalisis as e:
            reg.update(estado="error", error=e.mensaje, escalada="")
            if e.bloqueante:
                g._registrar_error(e)
        except Exception as e:  # noqa: BLE001 — un fallo del asesor nunca detiene la grabación
            reg.update(estado="error", error=f"No se pudo responder: {e}", escalada="")
        finally:
            self.en_curso = False
        if g.sesion is s:
            self._guardar()
            self.emitir()
            g.emitir("consumo", **g.consumo.resumen())
        if reg["estado"] == "ok" and temas and g.sesion is s:
            g._lanzar("asesor", self.afinar(reg, p, temas, ctx))
        elif reg["escalada"] == "pendiente":
            reg["escalada"] = ""

    async def afinar(self, reg: dict, p: dict, temas: list[str], ctx: dict) -> None:
        """La misma pregunta con sonnet, DESPUÉS de la de haiku (la prioridad de la cola lo deja detrás de cualquier respuesta nueva). Sustituye la respuesta de haiku
        si sale bien; si no hay sonnet disponible (límite por hora o presupuesto), lo dice y deja la de haiku."""
        g, s = self.g, self.sesion
        if s is None:
            return
        ahora = self.ahora()
        if not self.sonnet_disponible(ahora):
            reg["escalada"] = "limite"
            self.emitir()
            return
        self.sonnet_t.append(ahora)
        reg["escalada"] = "en_curso"
        self.emitir()
        previa = {"vinetas": list(reg["vinetas"]), "confianza": reg["confianza"], "citas": list(reg["citas"]), "modelo": reg["modelo"]}
        try:
            ahora_s = max(self.ahora(), p["t"])
            usuario = A.usuario_respuesta(p["pregunta"], reg["minuto"], reg["canal"][0], ctx["digest"], ctx["extractos"], ctx["transcripcion"], mmss(ahora_s),
                                          p.get("antecedente", ""))
            n0 = len(g.consumo.llamadas)
            res = await asyncio.to_thread(g.analista.asesorar, "asesor_respuesta_sonnet", A.sistema_respuesta(temas), usuario,
                                          lambda d: A.normalizar_respuesta(d, ctx["entregadas"], ctx["ficheros"], ahora_s, ctx["base"]))
            reg.update(res, modelo=g.cfg.modelo("asesor_respuesta_sonnet"), escalada="hecha", previa=previa,
                       tokens=(reg.get("tokens") or 0) + (self._tokens_de("asesor_respuesta_sonnet", n0) or 0))
        except ErrorAnalisis as e:
            reg.update(escalada="error", error_escalada=e.mensaje)
        except Exception as e:  # noqa: BLE001
            reg.update(escalada="error", error_escalada=f"No se pudo afinar: {e}")
        if g.sesion is s:
            self._guardar()
            self.emitir()
            g.emitir("consumo", **g.consumo.resumen())

    # ------------------------------------------------------------------ Profundizar
    def _buscar_elemento(self, ident: str) -> tuple[str, dict]:
        s = self.sesion
        for lista, clase in ((s.respuestas, "respuesta"), (s.consejos, "consejo")):
            e = next((x for x in lista if x["id"] == ident), None)
            if e is not None:
                return clase, e
        raise ValueError("Ese elemento del asesor ya no existe.")

    def _nombres_sensibles(self) -> list[str]:
        s, cfg = self.sesion, self.g.cfg
        nombres = [s.proyecto or "", s.tema or "", cfg["autor"]]
        for t in (s.proyecto or "", s.tema or "", cfg["autor"]):
            nombres += [w for w in t.replace("-", " ").split() if len(w) >= 4]
        return [n for n in nombres if n]

    def preparar_profundizar(self, clase: str, e: dict, web: bool) -> tuple[str, str, dict]:
        """(sistema, usuario, contexto) de «Profundizar». Con la web habilitada TODO lo que viaja (elemento, contexto, extractos, transcripción) va anonimizado:
        sin el nombre del cliente, del proyecto ni del tema, sin personas conocidas por el contexto, correos, enlaces ni importes."""
        g = self.g
        elemento = A.texto_elemento(clase, e)
        cfg = g.cfg
        ctx = self._preparar(elemento, 8, cfg["asesor_chars_extractos_profundizar"], cfg["asesor_chars_transcripcion"] * 2, e.get("pregunta") or e.get("accion") or "")
        digest, trans, extractos = ctx["digest"], ctx["transcripcion"], ctx["extractos"]
        if web:   # lo que viaja al modelo con la búsqueda habilitada va anonimizado (también los nombres de los ficheros); las citas siguen apuntando a los reales
            nombres = self._nombres_sensibles()
            anon = lambda t: A.anonimizar_para_web(t, nombres)   # noqa: E731
            elemento, digest, trans = anon(elemento), anon(digest), anon(trans)
            extractos = [Resultado(r.id, anon(r.etiqueta), r.tipo, anon(r.texto), r.puntos, r.minuto_s, r.duracion_s) for r in extractos]
        que = "una respuesta sugerida a una pregunta del cliente" if clase == "respuesta" else "un consejo del Estratega"
        usuario = A.usuario_profundizar(elemento, digest, extractos, trans, mmss(self.ahora()))
        return A.sistema_profundizar(que, web), usuario, ctx

    async def profundizar(self, ident: str, web: bool = False) -> dict:
        """«Profundizar»: UNA llamada a sonnet con más extractos (y, solo si `web`, la búsqueda web de `claude -p`). La pide el usuario: no depende del
        límite por hora ni del presupuesto (cuenta en ambos). Nunca automática."""
        g = self.g
        s = g._en_reunion()
        clase, e = self._buscar_elemento(ident)
        if (e.get("profundizada") or {}).get("estado") == "en_curso":
            raise ValueError("Ya se está profundizando en este elemento.")
        if clase == "respuesta" and e.get("estado") != "ok":
            raise ValueError("Espera a que la respuesta esté lista para profundizar.")
        if web:
            ok, motivo = self.web_disponible()
            if not ok:
                raise ValueError(motivo or "La búsqueda web no está disponible.")
        e["profundizada"] = {"estado": "en_curso", "web": bool(web), "vinetas": [], "confianza": "", "citas": [], "web_urls": [], "error": "",
                             "modelo": g.cfg.modelo("asesor_profundizar")}
        self.emitir()
        ahora = self.ahora()
        self.sonnet_t.append(ahora)
        n0 = len(g.consumo.llamadas)
        try:
            sistema, usuario, ctx = await asyncio.to_thread(self.preparar_profundizar, clase, e, web)
            res = await asyncio.to_thread(
                g.analista.asesorar, "asesor_profundizar", sistema, usuario,
                lambda d: {**A.normalizar_respuesta(d, ctx["entregadas"], ctx["ficheros"], ahora, ctx["base"], profundo=True, comprobar_cifras=not web, orientaciones=3 if web else 1),
                           "web_urls": A.normalizar_web(d.get("w") if isinstance(d, dict) else None, web)}, web)
            e["profundizada"].update(estado="ok", vinetas=res["vinetas"], confianza=res["confianza"], citas=res["citas"], base=res["base"],
                                     web=bool(web), web_urls=res["web_urls"], tokens=self._tokens_de("asesor_profundizar", n0))
        except ErrorAnalisis as err:
            e["profundizada"].update(estado="error", error=err.mensaje)
            if err.bloqueante:
                g._registrar_error(err)
        except Exception as err:  # noqa: BLE001
            e["profundizada"].update(estado="error", error=f"No se pudo profundizar: {err}")
        if g.sesion is s:
            self._guardar()
            self.emitir()
            g.emitir("consumo", **g.consumo.resumen())
        return {"ok": e["profundizada"]["estado"] == "ok", "error": e["profundizada"]["error"]}

    # ------------------------------------------------------------------ fijar y descartar
    def marcar(self, ident: str, campo: str, valor: bool) -> dict:
        """`campo`: fijar | descartar. Se ve en el carril y en el .md; no gasta nada."""
        g = self.g
        g._en_reunion()
        clase, e = self._buscar_elemento(ident)
        if campo == "fijar":
            e["fijada" if clase == "respuesta" else "fijado"] = bool(valor)
        elif campo == "descartar":
            e["descartada" if clase == "respuesta" else "descartado"] = bool(valor)
            if valor:
                e["fijada" if clase == "respuesta" else "fijado"] = False
        else:
            raise ValueError("Operación no válida.")
        self._guardar()
        self.emitir()
        return dict(e)
