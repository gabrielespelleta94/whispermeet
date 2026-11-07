"""Métricas de valor (ola 4): qué aportó la reunión. Todo local, sin modelo.

Por sesión: objetivos cerrados EN la reunión, minuto en que se tocó y en que se cerró cada uno, avisos aceptados frente a descartados y tokens gastados.
Se calculan al cerrar (van en `revision.metricas`), se guardan en `metricas.jsonl` de la carpeta local de datos (solo vía Guardian) y se agregan por proyecto
en `GET /api/proyectos/{n}/metricas`. No se inventa nada: un objetivo sin minuto de cierre no cuenta para el «tiempo hasta el cierre».

Definiciones:
- *tocado*: primer minuto en que el Monitor local vio hablar del objetivo (`Monitor.primer_toque`), o el de la primera evidencia que fijó el análisis (`t_primero`),
  el más temprano de los dos.
- *cerrado*: el objetivo termina `cubierto`; su minuto es el de la última evidencia (el modelo no lo cambia una vez cubierto).
- *minutos hasta el cierre*: cerrado − tocado (≥ 0).
- *avisos aceptados*: consejos y respuestas del asesor fijados y acciones propuestas aceptadas (ola 3, si la sesión las tiene); *descartados*: los descartados y los
  marcados «Esto está mal»; el resto, sin valorar. Las tarjetas de los perfiles cuentan como emitidas (solo se descartan si se marcaron «mal»).
"""
from __future__ import annotations

import json
import threading

from . import planes as PL
from .rutas import RutaProhibida
from .texto import mmss

FICHERO = "metricas.jsonl"
ACEPTADA = {"aceptada", "aceptado", "hecha", "hecho", "aplicada", "aplicado", "aprobada", "aprobado"}
DESCARTADA = {"descartada", "descartado", "rechazada", "rechazado", "omitida", "omitido"}


def _min(t) -> str | None:
    return None if t is None else mmss(t)


def objetivos_metricas(objetivos: list[dict], primer_toque: dict | None = None) -> list[dict]:
    primer_toque = primer_toque or {}
    out = []
    for o in PL.activos(objetivos):
        candidatos = [x for x in (primer_toque.get(o["n"]), o.get("t_primero")) if x is not None]
        tocado = min(candidatos) if candidatos else None
        cerrado = o.get("t_seg") if o["estado"] == PL.CUBIERTO else None
        if cerrado is not None and tocado is not None and tocado > cerrado:
            tocado = cerrado
        hasta = round((cerrado - tocado) / 60, 1) if cerrado is not None and tocado is not None else None
        out.append({"n": o["n"], "texto": o["texto"], "estado": o["estado"], "origen": o.get("origen", ""),
                    "tocado_t": None if tocado is None else round(tocado, 1), "tocado_min": _min(tocado),
                    "cerrado_t": None if cerrado is None else round(cerrado, 1), "cerrado_min": _min(cerrado),
                    "minutos_hasta_cierre": hasta})
    return out


def avisos_metricas(sesion, feed: list[dict] | None = None) -> dict:
    por_tipo = {"tarjetas": 0, "consejos": 0, "respuestas": 0, "acciones": 0, "monitor": 0}
    acept = desc = mal = 0
    for t in sesion.tarjetas:
        por_tipo["tarjetas"] += 1
        if t.get("mal"):
            mal += 1
            desc += 1
    for tipo, lista in (("consejos", sesion.consejos), ("respuestas", sesion.respuestas)):
        for x in lista:
            por_tipo[tipo] += 1
            if x.get("descartado"):
                desc += 1
            elif x.get("fijado"):
                acept += 1
    for a in getattr(sesion, "acciones", None) or []:
        por_tipo["acciones"] += 1
        estado = str(a.get("estado", "")).lower()
        if estado in ACEPTADA:
            acept += 1
        elif estado in DESCARTADA:
            desc += 1
    for e in feed or []:
        por_tipo["monitor"] += 1
        if e.get("silenciado"):
            mal += 1
            desc += 1
    total = sum(por_tipo.values())
    return {"emitidos": total, "aceptados": acept, "descartados": desc, "marcados_mal": mal, "sin_valorar": max(0, total - acept - desc),
            "por_tipo": por_tipo, "tasa_aceptacion": round(acept / (acept + desc), 2) if acept + desc else None}


def tokens_metricas(llamadas: list[dict]) -> dict:
    ent = sal = 0
    por_tarea: dict[str, int] = {}
    for reg in llamadas:
        k = 0
        for u in reg.get("uso", []):
            e = u.get("entrada", 0) + u.get("cache_creacion", 0) + u.get("cache_lectura", 0)
            ent += e
            sal += u.get("salida", 0)
            k += e + u.get("salida", 0)
        t = str(reg.get("tarea", "?"))
        por_tarea[t] = por_tarea.get(t, 0) + k
    return {"entrada": ent, "salida": sal, "total": ent + sal, "llamadas": len(llamadas), "por_tarea": por_tarea}


def de_sesion(sesion, equipo=None, llamadas: list[dict] | None = None, envios: dict | None = None, modo_local: bool = False) -> dict:
    """Métricas de una sesión (en curso o cerrada). `equipo`: el Director (Monitor: primer toque y feed); `llamadas`: las de `Consumo`."""
    mon = equipo.monitor if equipo is not None else None
    objs = objetivos_metricas(sesion.objetivos, mon.primer_toque if mon else None)
    cerr = [o for o in objs if o["estado"] == PL.CUBIERTO]
    tiempos = [o["minutos_hasta_cierre"] for o in cerr if o["minutos_hasta_cierre"] is not None]
    cierres = [o["cerrado_t"] for o in cerr if o["cerrado_t"] is not None]
    resumen = {"total": len(objs), "cerrados": len(cerr), "parciales": sum(1 for o in objs if o["estado"] == PL.PARCIAL),
               "sin_tratar": sum(1 for o in objs if o["estado"] == PL.SIN_TRATAR),
               "ratio_cerrados": round(len(cerr) / len(objs), 2) if objs else None,
               "minutos_medio_hasta_cierre": round(sum(tiempos) / len(tiempos), 1) if tiempos else None,
               "primer_cierre_min": _min(min(cierres)) if cierres else None}
    return {"sesion": sesion.id, "proyecto": sesion.proyecto or "Bandeja", "tema": sesion.tema, "fecha": f"{sesion.inicio:%Y-%m-%d}",
            "duracion_s": round(sesion.duracion_s, 1), "duracion": mmss(sesion.duracion_s), "plan": sesion.plan_nombre or None,
            "modo_local": bool(modo_local), "objetivos": objs, "objetivos_resumen": resumen,
            "avisos": avisos_metricas(sesion, mon.feed if mon else None), "tokens": tokens_metricas(llamadas or []),
            "envios": envios}


# ------------------------------------------------------------------ almacén local y agregado por proyecto
class AlmacenMetricas:
    def __init__(self, guardian):
        self.g = guardian
        self._lock = threading.Lock()

    def guardar(self, m: dict) -> bool:
        if not self.g.hay_datos():
            return False
        try:
            with self._lock:
                self.g.anadir_datos(FICHERO, json.dumps(m, ensure_ascii=False))
            return True
        except (OSError, RutaProhibida):
            return False

    def todas(self) -> list[dict]:
        """Una por sesión (si se guardó varias veces, la última), en orden de cierre."""
        try:
            texto = self.g.leer_datos(FICHERO) or ""
        except (OSError, RutaProhibida):
            return []
        por_id: dict[str, dict] = {}
        for linea in texto.splitlines():
            try:
                m = json.loads(linea)
            except ValueError:
                continue
            if isinstance(m, dict) and m.get("sesion"):
                por_id.pop(m["sesion"], None)
                por_id[m["sesion"]] = m
        return list(por_id.values())

    def de_proyecto(self, proyecto: str) -> list[dict]:
        p = (proyecto or "").strip().lower()
        return [m for m in self.todas() if str(m.get("proyecto", "")).lower() == p]


def agregar(registros: list[dict]) -> dict:
    """Agregado de un proyecto a partir de las métricas guardadas de sus sesiones."""
    tot_obj = cerr = 0
    tiempos: list[float] = []
    acept = desc = emit = mal = 0
    ent = sal = dur = 0
    serie = []
    for m in registros:
        r = m.get("objetivos_resumen") or {}
        tot_obj += r.get("total", 0)
        cerr += r.get("cerrados", 0)
        tiempos += [o["minutos_hasta_cierre"] for o in m.get("objetivos", []) if o.get("minutos_hasta_cierre") is not None]
        a = m.get("avisos") or {}
        acept += a.get("aceptados", 0)
        desc += a.get("descartados", 0)
        emit += a.get("emitidos", 0)
        mal += a.get("marcados_mal", 0)
        t = m.get("tokens") or {}
        ent += t.get("entrada", 0)
        sal += t.get("salida", 0)
        dur += m.get("duracion_s", 0) or 0
        serie.append({"sesion": m.get("sesion"), "fecha": m.get("fecha"), "tema": m.get("tema"), "objetivos": r.get("total", 0),
                      "cerrados": r.get("cerrados", 0), "ratio_cerrados": r.get("ratio_cerrados"),
                      "minutos_medio_hasta_cierre": r.get("minutos_medio_hasta_cierre"), "tokens": t.get("total", 0),
                      "aceptados": a.get("aceptados", 0), "descartados": a.get("descartados", 0), "modo_local": bool(m.get("modo_local"))})
    n = len(registros)
    return {"sesiones": n, "duracion_total_s": round(dur, 1),
            "objetivos": {"total": tot_obj, "cerrados": cerr, "ratio_cerrados": round(cerr / tot_obj, 2) if tot_obj else None,
                          "minutos_medio_hasta_cierre": round(sum(tiempos) / len(tiempos), 1) if tiempos else None,
                          "con_tiempo_de_cierre": len(tiempos)},
            "avisos": {"emitidos": emit, "aceptados": acept, "descartados": desc, "marcados_mal": mal,
                       "tasa_aceptacion": round(acept / (acept + desc), 2) if acept + desc else None},
            "tokens": {"entrada": ent, "salida": sal, "total": ent + sal, "por_sesion": round((ent + sal) / n) if n else 0,
                       "por_objetivo_cerrado": round((ent + sal) / cerr) if cerr else None},
            "serie": serie}
