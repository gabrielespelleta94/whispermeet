"""Director del equipo: une el Monitor local, el presupuesto, las definiciones y los turnos de los cuatro perfiles con la reunión.

Los turnos son llamadas REALES a haiku (una por turno, en serie: `Sonda` serializa todas las llamadas al modelo). Nada se simula:
cada tarjeta de perfil refleja eventos `tarea` reales o una detección local etiquetada como tal.
"""
from __future__ import annotations

import asyncio
from datetime import datetime

from .. import asesor as AS
from .. import checks as CK
from .. import cobertura as CB
from .. import planes as PL
from ..analisis import ErrorAnalisis
from ..texto import a_segundos, formatear_lineas, limpiar_transcripcion, mmss, palabras
from . import perfiles as PF
from .definiciones import Definiciones
from .monitor import ETIQUETA, Monitor, seleccionar_para
from .presupuesto import Presupuesto

MODOS_CON_EQUIPO = ("equipo", "manual")      # modos en los que «Analizar ahora» llama a un perfil (en 5 y 10 min sigue el análisis generalista)
CLAVES_MONITOR = ("equipo_puntuacion_min", "equipo_enfriamiento_global_s", "equipo_enfriamiento_perfil_s", "equipo_rotacion_s",
                  "equipo_palabras_min", "equipo_objetivo_sin_tratar_min",
                  "equipo_toque_repetido_s", "equipo_silencio_aviso_s", "equipo_rotacion_palabras",
                  "asesor_separacion_llamada_s", "asesor_rotacion_s", "asesor_rotacion_palabras")
PALABRAS_A_PETICION = 20


def _tokens(llamadas: list[dict]) -> int:
    return sum(u.get("entrada", 0) + u.get("cache_creacion", 0) + u.get("cache_lectura", 0) + u.get("salida", 0)
               for r in llamadas for u in r.get("uso", []))


class Director:
    def __init__(self, gestor):
        self.g = gestor
        self.ajustes_sesion: dict = {}          # ola 4: ritmo de la plantilla de reunión (claves de CLAVES_MONITOR); manda sobre la configuración durante la sesión
        self.monitor = Monitor({k: gestor.cfg[k] for k in CLAVES_MONITOR})
        self._enganchar_silencio()
        self.presupuesto = Presupuesto(gestor.cfg["presupuesto_tokens_hora"])
        self.definiciones = Definiciones()
        self.estado = {p: self._perfil_nuevo() for p in PF.ORDEN_PERFILES}
        self.ultimo_id = {p: 0 for p in PF.ORDEN_PERFILES}
        self.en_curso: str | None = None
        self.eligiendo: str | None = None      # elegido por el Monitor, aún sin llamada (esperando su vez)
        self.n_turnos = 0
        self.tokens_equipo = 0
        self._ultima_comprobacion = -1e9
        self._n_pal_pasada = 0

    @staticmethod
    def _perfil_nuevo() -> dict:
        return {"aporte": None, "turno": None, "error": "", "motivo": ""}

    def reiniciar(self) -> None:
        cfg = self.g.cfg
        self.ajustes_sesion = {}
        self.monitor = Monitor({k: cfg[k] for k in CLAVES_MONITOR})
        self._enganchar_silencio()
        self.presupuesto = Presupuesto(cfg["presupuesto_tokens_hora"])
        self.definiciones = Definiciones()
        self.estado = {p: self._perfil_nuevo() for p in PF.ORDEN_PERFILES}
        self.ultimo_id = {p: 0 for p in PF.ORDEN_PERFILES}
        self.en_curso = self.eligiendo = None
        self.n_turnos = self.tokens_equipo = 0
        self._ultima_comprobacion = -1e9
        self.g.sonda.al_terminar = self._al_terminar

    def _enganchar_silencio(self) -> None:
        """ola 4: el Monitor consulta las reglas locales de «Esto está mal» antes de emitir un aviso."""
        reglas = getattr(self.g, "reglas_silencio", None)
        self.monitor.filtro_silencio = reglas.silenciado if reglas is not None else None

    # ---------------------------------------------------------------- presupuesto
    def _al_terminar(self, reg: dict, llamadas: list[dict]) -> None:
        """Cada llamada al modelo (digest, turnos, Pregúntale, cierre) cuenta en la hora de reunión en que terminó."""
        k = _tokens(llamadas)
        tarea = str(reg.get("tarea", ""))
        if tarea.startswith("asesor_"):   # el asesor en directo tiene su presupuesto propio: no le quita turnos al equipo ni al revés
            self.g.asesor.presupuesto.sumar(self.g.reloj.ahora(), k, tarea)
            self.g.asesor.tokens += k
            return
        self.presupuesto.sumar(self.g.reloj.ahora(), k, tarea)
        if tarea.startswith("equipo_"):
            self.tokens_equipo += k

    def nivel(self) -> str:
        self.presupuesto.fijar_limite(self.g.cfg["presupuesto_tokens_hora"])
        return self.presupuesto.nivel(self.g.reloj.ahora())

    # ---------------------------------------------------------------- Monitor (cada `adaptativo_comprobar_s`)
    def _segmentos_nuevos(self) -> list:
        return self.g.sesion.estables(self.monitor.ultimo_id)   # sin el eco de Reunión y sin los Micro que aún esperan a su pareja

    def _objetivos_monitor(self) -> list[dict]:
        s = self.g.sesion
        return [o for o in PL.activos(s.objetivos)]

    def comprobar(self, ahora: float, auto: bool) -> dict | None:
        """Una pasada del Monitor si toca (local, sin modelo). Devuelve {pasada, turno} con el turno (perfil, motivo) elegido o None.
        `auto`: puede elegir turno automático (modo equipo, sin bloqueo y sin llamada en curso)."""
        c = self.g.cfg
        if ahora - self._ultima_comprobacion < max(1, c["adaptativo_comprobar_s"]):
            return None
        self._ultima_comprobacion = ahora
        s = self.g.sesion
        # los parámetros del Monitor se leen de la configuración en cada pasada (se pueden cambiar en Ajustes)
        self.monitor.c.update({k: c[k] for k in CLAVES_MONITOR})
        self.monitor.c.update(self.ajustes_sesion)   # ola 4: el ritmo de la plantilla de reunión
        segs = self._segmentos_nuevos()
        pas = self.monitor.pasada(ahora, segs, self._objetivos_monitor(), s.checks)
        for d in pas.definiciones:
            self.definiciones.anadir_local(d)
        self._n_pal_pasada = pas.palabras
        asesor_on = bool(c["asesor_activo"]) and self.monitor.pesos.get("estratega", 1) > 0   # ola 4: la plantilla de reunión puede dejar al Estratega sin turno
        if asesor_on and segs:   # señales estratégicas (precio, plazos, oportunidad, cierre…): suman al Estratega, todo local
            self.monitor.sumar_estratega(AS.senales_estrategicas(" ".join(x.texto for x in segs)).keys())
        turno = None
        if auto and self.en_curso is None and not self.g.bloqueo and not self.g.analizando:
            perfil, motivo = self.monitor.elegir(ahora, self.nivel(), False)
            if not perfil and asesor_on and len(s.consejos) < c["asesor_max_consejos"]:   # el Estratega, solo si nadie más tiene turno
                perfil, motivo = self.monitor.elegir_estratega(ahora, self.g.asesor.nivel(), c["asesor_consejo_cada_s"], False)
            if perfil:
                turno = (perfil, motivo)
            elif ahora - self.monitor.ultima_llamada >= 300:
                e = self.monitor.silencio(ahora, self.monitor.palabras_desde[min(PF.ORDEN_ROTACION, key=lambda p: self.monitor.ultimo_turno[p])])
                if e:
                    pas.entradas.append(e)
        return {"pasada": pas, "turno": turno}

    # ---------------------------------------------------------------- un turno
    def _estado_prompt(self, perfil: str) -> tuple[str, list[dict]]:
        """(texto del bloque «estado», checks enviados). ≤12 líneas. Solo el Revisor recibe objetivos y checks para actualizarlos;
        los demás ven (≤4 líneas) los objetivos que la conversación ha tocado hace poco."""
        s = self.g.sesion
        act = PL.para_prompt(s.objetivos)
        if perfil != "revisor":
            ahora = self.g.reloj.ahora()
            originales = PL.activos(s.objetivos)   # el Monitor guarda los toques por número original; el modelo ve la posición
            tocados = [o for o, orig in zip(act, originales) if ahora - self.monitor.ultimo_toque.get(orig["n"], -1e9) <= 300]
            return ("\n".join(f"Objetivo {o['n']}: {o['texto'][:90]}" for o in tocados[:4]), [])
        base_chk = self.g._base_checks()
        enviados = self.g.checks.para_prompt(s.proyecto, s.plan_id or None, base_chk)
        lineas = [f"{o['n']} [{PL._MARCA[o['estado']]}] {o['texto'][:100]}" for o in sorted(act, key=lambda o: (o["estado"] == "cubierto", o["n"]))
                  if o["estado"] != "cubierto"][:8]
        hueco = PF.MAX_LINEAS_ESTADO - len(lineas)
        chk = []
        if enviados and hueco > 0:
            toques = self.monitor.ultimo_toque_check
            orden = sorted(range(len(enviados)), key=lambda i: (-toques.get(enviados[i].get("id"), -1.0), i))[:hueco]
            chk = [f"{i + 1} {enviados[i]['texto'][:100]}" for i in sorted(orden)]
        partes = []
        if lineas:
            partes.append("Objetivos (número [estado minuto] texto; c cubierto, p parcial):\n" + "\n".join(lineas))
        if chk:
            partes.append("Checks abiertos (número texto):\n" + "\n".join(chk))
        return "\n".join(partes), enviados

    async def turno(self, perfil: str, motivo: str, manual: bool = False) -> dict:
        """Un turno: UNA llamada real. Devuelve {ok, ...}."""
        if perfil == "estratega":
            return await self.turno_estratega(motivo, manual)
        g, s = self.g, self.g.sesion
        p = PF.PERFILES[perfil]
        if not s or self.en_curso is not None or g.analizando:
            return {"ok": False, "motivo": "Ya hay una llamada en curso."}
        nuevos = s.estables(self.ultimo_id[perfil], esperar=not manual)   # a petición se lee lo recibido, sin esperar a la pareja de un Micro
        n_pal = sum(palabras(x.texto) for x in nuevos)
        if not nuevos or (manual and n_pal < PALABRAS_A_PETICION):
            return {"ok": False, "omitido": True, "motivo": f"Solo {n_pal} palabras nuevas para el {p.nombre} (mínimo {PALABRAS_A_PETICION})."}
        self.eligiendo = perfil
        self.en_curso = perfil
        g.analizando = True
        if manual:
            g.bloqueo = None
        g.motivo_ultimo = motivo
        self.estado[perfil]["motivo"] = motivo
        self.estado[perfil]["error"] = ""
        try:
            if g._digest_tarea and not g._digest_tarea.done():
                await asyncio.wait({g._digest_tarea}, timeout=120)
            lineas = limpiar_transcripcion(nuevos)
            # lo que cabe en el turno: todo, o lo más relevante para el oficio del perfil más lo último (local, sin modelo)
            texto_nuevo, pos = seleccionar_para(perfil, lineas, g.cfg["equipo_chars_nuevo"], lambda l: formatear_lineas([l]))
            leidas = [lineas[i] for i in pos] or lineas
            tramo = g.analista.tramos.get(p.tramo) or g.digest
            estado, enviados = self._estado_prompt(perfil)
            titulos = [f"[{t.get('minuto') or '--:--'}] {t['categoria']}: {t['texto'][:70]}" for t in s.tarjetas if t.get("perfil") == perfil][-PF.MAX_TITULOS:]
            usuario = PF.usuario(p, tramo, estado, titulos, texto_nuevo, g.cfg["equipo_chars_nuevo"])
            desde_t, hasta_t = (leidas[0].t, leidas[-1].t) if leidas else (g.reloj.ahora(), g.reloj.ahora())
            g.sonda.tramo_actual = f"{mmss(desde_t)}–{mmss(hasta_t)}"
            g.emitir("analisis", fase="inicio", motivo=motivo, perfil=perfil, desde_t=desde_t, hasta_t=hasta_t)
            self.emitir_estado()
            n_obj = len(PL.activos(s.objetivos))
            n_chk = len(enviados)
            res = await asyncio.to_thread(g.analista.turno, perfil, usuario, n_obj, n_chk)
            g.n_analisis += 1
            CB.registrar_lectura(s, g.n_analisis, perfil, lineas, pos)   # qué tramo leyó y qué recortó el tope: lo recortado queda «no cubierto»
            self.n_turnos += 1
            fin_id = nuevos[-1].id
            self.ultimo_id[perfil] = fin_id
            s.ultimo_analizado_id = max(s.ultimo_analizado_id, fin_id)
            for t in res["tarjetas"]:
                t["perfil"] = perfil
            res["resumen"] = ""
            nuevas = g._incorporar(res, lineas)
            n_def = self._definiciones(res, desde_t)
            if perfil == "revisor":
                PL.aplicar_por_posicion(s.objetivos, res.get("objetivos") or [])
                base_chk = g._base_checks()
                g.checks.aplicar_marcas(s.proyecto, s.plan_id or None, enviados, res.get("checks") or [], base_chk)
                s.checks = g.checks.listar(s.proyecto, s.plan_id or None, base_chk)
            if res.get("tema"):
                s.temas.append({"analisis": g.n_analisis, "desde_t": round(desde_t, 1), "hasta_t": round(hasta_t, 1), "titulo": res["tema"], "perfil": perfil})
                parcial = f" (lectura parcial: {len(pos)} de {len(lineas)} líneas del tramo)" if len(pos) < len(lineas) else ""
                s.resumen_completo = (s.resumen_completo + f"\n[{mmss(desde_t)}–{mmss(hasta_t)}] {res['tema']}{parcial}").strip()
            s.analisis_marcas.append({"n": g.n_analisis, "t": round(g.reloj.ahora(), 1), "motivo": f"{p.nombre} · {motivo}"})
            aporte = self._aporte(res, nuevas)
            now = g.reloj.ahora()
            reg = next((t for t in reversed(g.sonda.tareas) if t.get("tarea") == p.tarea), {})
            self.estado[perfil].update(aporte=aporte or self.estado[perfil]["aporte"], error="", turno={
                "desde": mmss(desde_t), "hasta": mmss(hasta_t), "modelo": reg.get("modelo"), "ms": reg.get("ms"), "tokens": reg.get("tokens"),
                "tarjetas": len(nuevas), "definiciones": n_def, "t": round(now, 1), "n": self.n_turnos})
            self.monitor.turno_hecho(perfil, now)
            s.guardar()
            if not g.bloqueo:
                g.ultimo_error = None
            g.ultimo_omitido = None
            g.emitir("tarjetas", nuevas=nuevas, resumen=s.resumen_acumulado, objetivos=[dict(o) for o in s.objetivos],
                     checks=[dict(c) for c in s.checks], temas=[dict(t) for t in s.temas], definiciones=n_def, hasta_id=fin_id)
            g.emitir("definiciones", definiciones=self.definiciones.publico())
            g.emitir("analisis", fase="ok", n=g.n_analisis, tarjetas=len(nuevas), motivo=motivo, perfil=perfil)
            return {"ok": True, "tarjetas": len(nuevas), "perfil": perfil}
        except ErrorAnalisis as e:
            g._registrar_error(e)
            self.estado[perfil]["error"] = e.mensaje
            g.emitir("analisis", fase="error", clase=e.tipo, mensaje=e.mensaje, perfil=perfil)
            return {"ok": False, "error": e.mensaje}
        except Exception as e:  # noqa: BLE001  (un fallo del equipo nunca detiene la grabación)
            g.ultimo_error = {"tipo": "otro", "mensaje": f"Error inesperado en el turno del {p.nombre}: {e}"}
            self.estado[perfil]["error"] = g.ultimo_error["mensaje"]
            g.emitir("analisis", fase="error", clase="otro", mensaje=g.ultimo_error["mensaje"], perfil=perfil)
            return {"ok": False, "error": str(e)}
        finally:
            self.en_curso = self.eligiendo = None
            g.analizando = False
            g.sonda.tramo_actual = ""
            g.emitir("consumo", **g.consumo.resumen())
            g._emitir_estado()

    async def turno_estratega(self, motivo: str, manual: bool = False) -> dict:
        """Un turno del Estratega (quinto perfil): UNA llamada (`asesor_consejo`: haiku, o sonnet si el tramo toca precio, alcance, plazos, contrato, competencia o
        compromiso y queda sonnet por hora) con el tramo nuevo, el contexto y los extractos mejor puntuados. Devuelve consejos de una frase de acción más su porqué;
        sin duplicados con los ya mostrados ni con las tarjetas, y con tope por reunión. Presupuesto propio."""
        g, s = self.g, self.g.sesion
        a = g.asesor
        if not s or self.en_curso is not None or g.analizando:
            return {"ok": False, "motivo": "Ya hay una llamada en curso."}
        cupo = min(AS.MAX_CONSEJOS_TURNO, g.cfg["asesor_max_consejos"] - len(s.consejos))
        nuevos = s.estables(self.ultimo_id["estratega"], esperar=not manual)
        if not nuevos or cupo <= 0:
            return {"ok": False, "omitido": True, "motivo": "Sin tramo nuevo o ya hay el máximo de consejos de la reunión."}
        self.eligiendo = self.en_curso = "estratega"
        g.analizando = True
        self.estado["estratega"].update(motivo=motivo, error="")
        try:
            if g._digest_tarea and not g._digest_tarea.done():
                await asyncio.wait({g._digest_tarea}, timeout=20)
            lineas = limpiar_transcripcion(nuevos)
            nuevo = PF.recortar_nuevo(formatear_lineas(lineas), 3000)
            ahora = g.reloj.ahora()
            hits = AS.senales_estrategicas(nuevo)
            sonnet = AS.es_estrategico(hits) and a.sonnet_disponible(ahora)
            tarea = "asesor_consejo_sonnet" if sonnet else "asesor_consejo"
            if sonnet:
                a.sonnet_t.append(ahora)
            desde_t, hasta_t = (lineas[0].t, lineas[-1].t) if lineas else (ahora, ahora)
            g.sonda.tramo_actual = f"{mmss(desde_t)}–{mmss(hasta_t)}"
            g.emitir("analisis", fase="inicio", motivo=motivo, perfil="estratega", desde_t=desde_t, hasta_t=hasta_t)
            self.emitir_estado()
            consulta = " ".join(x.texto for x in lineas[-6:])
            extractos = await asyncio.to_thread(g.fuentes.buscar, consulta, "", 3, 1500)
            existentes = [f"{c['accion']} {c['porque']}" for c in s.consejos] + [t["texto"] for t in s.tarjetas[-30:]]
            ya = [f"{c['etiqueta']}: {c['accion']}" for c in s.consejos[-8:]]
            base = "\n".join([g.digest, nuevo] + [r.texto for r in extractos])
            usuario = AS.usuario_estratega(g.digest, extractos, ya, nuevo, mmss(ahora))
            n0 = len(g.consumo.llamadas)
            res = await asyncio.to_thread(g.analista.asesorar, tarea, AS.sistema_estratega(), usuario,
                                          lambda d: AS.normalizar_consejos(d, max(ahora, hasta_t), existentes, base, cupo))
            tokens = sum(u.get("entrada", 0) + u.get("cache_creacion", 0) + u.get("cache_lectura", 0) + u.get("salida", 0)
                         for c in g.consumo.llamadas[n0:] if c.get("tarea") == tarea for u in c.get("uso", [])) or None
            nuevos_c = []
            for c in res:
                a.n_c += 1
                c.update(id=f"c{a.n_c}", modelo=g.cfg.modelo(tarea), fijado=False, descartado=False, profundizada=None, perfil="estratega", tokens=tokens)
                s.consejos.append(c)
                nuevos_c.append(c)
            g.n_analisis += 1
            self.n_turnos += 1
            self.ultimo_id["estratega"] = nuevos[-1].id
            now = g.reloj.ahora()
            aporte = ({"categoria": nuevos_c[0]["etiqueta"].lower(), "minuto": nuevos_c[0]["minuto"], "t_seg": nuevos_c[0]["t_seg"], "texto": nuevos_c[0]["accion"], "responsable": ""}
                      if nuevos_c else self.estado["estratega"]["aporte"])
            reg = next((t for t in reversed(g.sonda.tareas) if t.get("tarea") == tarea), {})
            self.estado["estratega"].update(aporte=aporte, error="", turno={
                "desde": mmss(desde_t), "hasta": mmss(hasta_t), "modelo": reg.get("modelo"), "ms": reg.get("ms"), "tokens": reg.get("tokens"),
                "tarjetas": len(nuevos_c), "definiciones": 0, "t": round(now, 1), "n": self.n_turnos})
            self.monitor.turno_hecho("estratega", now)
            s.analisis_marcas.append({"n": g.n_analisis, "t": round(now, 1), "motivo": f"Estratega · {motivo}"})
            s.guardar()
            a.emitir()
            g.emitir("analisis", fase="ok", n=g.n_analisis, tarjetas=len(nuevos_c), motivo=motivo, perfil="estratega")
            return {"ok": True, "consejos": len(nuevos_c), "perfil": "estratega"}
        except ErrorAnalisis as e:
            if e.bloqueante:
                g._registrar_error(e)
            self.estado["estratega"]["error"] = e.mensaje
            self.monitor.turno_hecho("estratega", g.reloj.ahora())   # sin reintento inmediato: el siguiente turno ya trae lo nuevo
            g.emitir("analisis", fase="error", clase=e.tipo, mensaje=e.mensaje, perfil="estratega")
            return {"ok": False, "error": e.mensaje}
        except Exception as e:  # noqa: BLE001  (un fallo del Estratega nunca detiene la grabación)
            self.estado["estratega"]["error"] = f"Error inesperado en el turno del Estratega: {e}"
            self.monitor.turno_hecho("estratega", g.reloj.ahora())
            g.emitir("analisis", fase="error", clase="otro", mensaje=self.estado["estratega"]["error"], perfil="estratega")
            return {"ok": False, "error": str(e)}
        finally:
            self.en_curso = self.eligiendo = None
            g.analizando = False
            g.sonda.tramo_actual = ""
            g.emitir("consumo", **g.consumo.resumen())
            g._emitir_estado()

    def _definiciones(self, res: dict, ahora: float) -> int:
        n = 0
        for d in res.get("definiciones") or []:
            self.definiciones.desde_analista(d["termino"], d["definicion"], d["minuto"], ahora)
            n += 1
        self.g.sesion.definiciones = self.definiciones.publico()
        return n

    @staticmethod
    def _aporte(res: dict, nuevas: list[dict]) -> dict | None:
        """Lo último que aportó el perfil (lo que se pinta en su tarjeta): su tarjeta de más prioridad o su definición."""
        if nuevas:
            t = nuevas[0]
            return {"categoria": t["categoria"], "minuto": t.get("minuto") or "", "t_seg": t.get("t_seg"), "texto": t["texto"], "responsable": t.get("responsable") or ""}
        d = (res.get("definiciones") or [None])[0]
        if d:
            return {"categoria": "definición", "minuto": d["minuto"], "t_seg": a_segundos(d["minuto"]), "texto": f"{d['termino']}: {d['definicion']}", "responsable": ""}
        return None

    async def a_peticion(self) -> dict:
        """«Analizar ahora» en modo equipo: el perfil con más puntos (empate: Coordinador), sin enfriamientos y aunque no quede presupuesto."""
        s = self.g.sesion
        if not s or self.g.estado not in ("grabando", "pausada"):
            return {"ok": False, "motivo": "No hay reunión en curso."}
        if self.en_curso is not None or self.g.analizando:
            return {"ok": False, "motivo": "Ya hay un análisis en curso."}
        # pasada previa para tener las señales al día
        self._ultima_comprobacion = -1e9
        self.comprobar(self.g.reloj.ahora(), False)
        perfil = self.monitor.a_peticion()
        return await self.turno(perfil, "a petición", manual=True)

    # ---------------------------------------------------------------- estado para la interfaz
    def publico(self) -> dict:
        g = self.g
        ahora = g.reloj.ahora()
        nivel = self.nivel()
        sig = self.monitor.siguiente(ahora, nivel) if g.sesion and g.sesion.modo_cadencia == "equipo" else {}
        perfiles = []
        nivel_asesor = g.asesor.nivel()
        for pid in PF.ORDEN_PERFILES:
            p, e = PF.PERFILES[pid], self.estado[pid]
            agotado = (nivel_asesor if pid == "estratega" else nivel) == "agotado"
            estado = "trabajando" if self.en_curso == pid else "turno" if self.eligiendo == pid else "error" if e["error"] else \
                "sin_presupuesto" if agotado and g.sesion and g.sesion.modo_cadencia == "equipo" else "espera"
            hubo = self.monitor.estratega["hubo_turno"] if pid == "estratega" else self.monitor.hubo_turno[pid]
            if estado == "espera" and e["turno"] and not e["error"] and hubo and ahora - e["turno"]["t"] < 6:
                estado = "hecho"
            perfiles.append({"id": pid, "nombre": p.nombre, "rol": p.rol, "mision": p.mision, "pregunta": p.pregunta, "estado": estado,
                             "aporte": e["aporte"], "turno": e["turno"], "error": e["error"], "motivo": e["motivo"],
                             "puntos": self.monitor.estratega["puntos"] if pid == "estratega" else self.monitor.puntos[pid],
                             "siguiente": (self.monitor.siguiente_estratega(ahora, nivel_asesor, g.cfg["asesor_consejo_cada_s"])
                                           if pid == "estratega" and sig is not None and g.sesion and g.sesion.modo_cadencia == "equipo" and g.cfg["asesor_activo"]
                                           else sig.get(pid))})
        pres = self.presupuesto.publico(ahora, g.velocidad if g.sim is not None else 1.0, datetime.now())
        return {"modo": g.sesion.modo_cadencia if g.sesion else "", "perfiles": perfiles, "en_curso": self.en_curso, "turnos": self.n_turnos,
                "tokens": self.tokens_equipo, "presupuesto": pres,
                "monitor": {**self.monitor.publico(ahora, nivel), "hace_s": round(ahora - self.monitor.t_pasada, 1) if self.monitor.t_pasada else None}}

    def emitir_estado(self) -> None:
        self.g.emitir("equipo", **self.publico())

    def snapshot(self) -> dict:
        return {"feed": [dict(e) for e in self.monitor.feed[-200:]], "definiciones": self.definiciones.publico(),
                "pasadas": list(self.monitor.pasadas[-100:])}
