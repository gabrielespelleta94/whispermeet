"""Ola 3: seguimiento de pendientes ENTRE sesiones. TODO LOCAL, sin modelo.

Consolida los pendientes de un proyecto (el mismo pendiente dicho en varias sesiones sale UNA vez: `Backlog._marcar_repetidos`) y los cierra solo cuando una
sesión POSTERIOR los cubre: coincidencia de palabras clave (BM25 de `fuentes.Indice` + fracción de términos del pendiente) sobre el resumen y las decisiones de esa
sesión, con un umbral configurable (`seguimiento_umbral`). Se marca `hecho` con la cita (sesión + frase). Es reversible (`reabrir`, que además impide que se vuelva
a cerrar solo).

Persistencia local, SOLO por el Guardian: `<seguimiento>/<proyecto>.json` con
  estados:       {id de pendiente: {estado, auto, cita, bloqueado, en}}   lo que el cierre automático o el usuario decidieron
  aceptados:     {clave: {texto, dueno, fecha, sesion, ...}}              pendientes que el usuario aceptó en la bandeja de acciones
  recordatorios: [{id, texto, sesion, fecha, tema, usado}]                para el brief de la próxima sesión
El estado de la lista de pendientes del backlog (`backlog/estado.json`) se mantiene en sintonía (best effort) para que la galería y «Sesiones» cuenten igual.
"""
from __future__ import annotations

import hashlib
import json
import re
import threading
from datetime import datetime

from . import backlog as BL
from .fuentes import Doc, Indice, tokenizar
from .rutas import RutaProhibida

VERSION = 1
MAX_FRASES_SESION = 80
MAX_RECORDATORIOS = 60
_RE_ENCABEZADO = re.compile(r"^\s*(?:#{1,6}\s+(?P<h>.+?)\s*#*|\*\*(?P<b>[^*]{2,80}?)\*\*\s*:?)\s*$")
# secciones del resumen cuyas líneas SÍ cuentan como «lo que se cerró»; las demás (pendientes, abierto, riesgos, preguntas…) hablan de lo que sigue abierto
_RE_SECCION_CERRADA = re.compile(r"decisi|cerrad|cumplid|acuerd|hecho|resuelt|conclusi|resumen|objetivo cubierto", re.I)
_RE_SECCION_ABIERTA = re.compile(r"pendient|abiert|sin tratar|sin cerrar|parcial|riesgo|pregunta|siguiente|proxim|próxim|por hacer|tareas", re.I)


def _limpio(t) -> str:
    return " ".join(str(t or "").split())


def _id_extra(proyecto: str, clave: str) -> str:
    return hashlib.sha1(f"{proyecto.lower()}|{clave}".encode("utf-8")).hexdigest()[:16]


def frases_de_cierre(resumen: str, decisiones: list[str]) -> list[str]:
    """Frases de una sesión que dicen que algo SE HIZO o SE DECIDIÓ: las líneas del resumen fuera de las secciones de pendientes/abierto/riesgos/preguntas
    y las decisiones (insights). FUNCIÓN PURA."""
    out: list[str] = []
    seccion = ""
    for linea in str(resumen or "").replace("\r\n", "\n").split("\n"):
        m = _RE_ENCABEZADO.match(linea)
        if m:
            seccion = _limpio(m.group("h") or m.group("b"))
            continue
        t = _limpio(re.sub(r"^\s*(?:[-*+]|\d{1,3}[.)])\s+(?:\[[ xX]\]\s*)?", "", linea))
        t = _limpio(t.replace("**", ""))
        if len(t) < 12:
            continue
        if seccion and _RE_SECCION_ABIERTA.search(seccion) and not _RE_SECCION_CERRADA.search(seccion):
            continue
        out.append(t[:400])
    out += [_limpio(d)[:400] for d in decisiones if len(_limpio(d)) >= 12]
    vistos, unicas = set(), []
    for f in out:
        k = BL.clave_repetido(f)
        if k and k not in vistos:
            vistos.add(k)
            unicas.append(f)
    return unicas[:MAX_FRASES_SESION]


def cobertura(pendiente: str, indice: Indice, umbral: float) -> tuple[dict, float] | None:
    """La mejor frase que cubre el pendiente (o None). Cubrir = el BM25 la encuentra Y contiene al menos `umbral` de las palabras clave del pendiente
    (y no menos de 2, salvo pendientes de una sola palabra clave). Devuelve ({etiqueta, frase}, fracción)."""
    q = set(tokenizar(pendiente))
    if not q or not len(indice):
        return None
    puntos = indice.puntuar(pendiente)
    mejor = None
    for i, p in puntos.items():
        t = indice.trozos[i]
        comunes = q & set(tokenizar(t.texto))
        frac = len(comunes) / len(q)
        if frac >= umbral and len(comunes) >= min(2, len(q)):
            clave = (frac, p)
            if mejor is None or clave > mejor[0]:
                mejor = (clave, {"etiqueta": indice.docs[t.doc].etiqueta, "frase": t.texto}, frac)
    return (mejor[1], round(mejor[2], 2)) if mejor else None


class Seguimiento:
    def __init__(self, guardian, backlog, cfg, ahora=None):
        self.g, self.bl, self.cfg = guardian, backlog, cfg
        self.ahora = ahora or datetime.now
        self._lock = threading.RLock()
        self.aviso_roto: dict[str, str] = {}

    # ------------------------------------------------------------ almacén
    @staticmethod
    def _vacio() -> dict:
        return {"version": VERSION, "estados": {}, "aceptados": {}, "recordatorios": []}

    def _cargar(self, proyecto: str) -> dict:
        try:
            texto = self.g.leer_seguimiento(proyecto)
        except OSError:
            return self._vacio()
        if not texto:
            return self._vacio()
        try:
            d = json.loads(texto)
            if not isinstance(d, dict):
                raise ValueError("no es un objeto")
        except ValueError:
            try:
                nuevo = self.g.apartar_seguimiento(proyecto)
                self.aviso_roto[proyecto.lower()] = f"El seguimiento estaba dañado y se apartó como {nuevo.name if nuevo else 'copia'}; se empieza de cero."
            except (OSError, RutaProhibida):
                pass
            return self._vacio()
        base = self._vacio()
        for k in ("estados", "aceptados"):
            if isinstance(d.get(k), dict):
                base[k] = d[k]
        if isinstance(d.get("recordatorios"), list):
            base["recordatorios"] = [r for r in d["recordatorios"] if isinstance(r, dict) and r.get("id")]
        return base

    def _guardar(self, proyecto: str, datos: dict) -> None:
        self.g.escribir_seguimiento(proyecto, json.dumps(datos, ensure_ascii=False, indent=1))

    # ------------------------------------------------------------ entradas desde la bandeja de acciones (al cerrar la revisión)
    def anadir_pendientes(self, proyecto: str, acciones: list[dict], ref: dict) -> int:
        """Los `pendiente` aceptados (dueño y fecha incluidos) se guardan como complemento de los del backlog, por clave de texto normalizado."""
        n = 0
        with self._lock:
            d = self._cargar(proyecto)
            for a in acciones:
                clave = BL.clave_repetido(a.get("texto"))
                if not clave:
                    continue
                datos = a.get("datos") or {}
                d["aceptados"][clave] = {"texto": _limpio(a["texto"])[:300], "dueno": _limpio(datos.get("dueno"))[:60], "fecha": _limpio(datos.get("fecha"))[:40],
                                         "cita": a.get("cita"), "sesion": ref.get("sesion"), "fecha_sesion": ref.get("fecha"), "tema": ref.get("tema"),
                                         "en": self.ahora().isoformat(timespec="seconds")}
                n += 1
            if n:
                self._guardar(proyecto, d)
        return n

    def anadir_recordatorios(self, proyecto: str, acciones: list[dict], ref: dict) -> int:
        """Los recordatorios de sesiones ANTERIORES pasan a «usados» (ya se vieron en el brief de esta) y se guardan los nuevos."""
        with self._lock:
            d = self._cargar(proyecto)
            for r in d["recordatorios"]:
                if r.get("sesion") != ref.get("sesion"):
                    r["usado"] = True
            existentes = {BL.clave_repetido(r.get("texto")) for r in d["recordatorios"] if not r.get("usado")}
            n = 0
            for a in acciones:
                clave = BL.clave_repetido(a.get("texto"))
                if not clave or clave in existentes:
                    continue
                existentes.add(clave)
                d["recordatorios"].append({"id": "r" + hashlib.sha1(f"{ref.get('sesion')}|{clave}".encode("utf-8")).hexdigest()[:10], "texto": _limpio(a["texto"])[:300],
                                           "sesion": ref.get("sesion"), "fecha": ref.get("fecha"), "tema": ref.get("tema"), "usado": False})
                n += 1
            d["recordatorios"] = d["recordatorios"][-MAX_RECORDATORIOS:]
            self._guardar(proyecto, d)
        return n

    def recordatorios(self, proyecto: str) -> list[dict]:
        with self._lock:
            return [dict(r) for r in self._cargar(proyecto)["recordatorios"] if not r.get("usado")]

    # ------------------------------------------------------------ pendientes consolidados del proyecto
    def _indice(self, refrescar: bool) -> dict:
        return self.bl._indice_actual(refrescar)

    def _consolidados(self, proyecto: str, refrescar: bool) -> tuple[list[dict], list[dict]]:
        """([pendientes consolidados, del más reciente al más antiguo], [sesiones del proyecto, de la más reciente a la más antigua])."""
        ix = self._indice(refrescar)
        sesiones = [ix["sesiones"][i] for i in ix["orden"] if (ix["sesiones"][i]["proyecto"] or "").lower() == proyecto.lower()]
        items = []
        for pos, s in enumerate(sesiones):
            for it in s["_items"]:
                if it["tipo"] == "pendiente" and not it.get("duplicado"):
                    items.append({**it, "_pos": pos})
        return items, sesiones

    def _cerrar_por(self, it: dict, sesiones: list[dict], umbral: float) -> dict | None:
        """Cita de la primera sesión POSTERIOR (la más cercana, de la más antigua a la más reciente) que cubre el pendiente, o None."""
        posteriores = sesiones[:it["_pos"]]   # `sesiones` va de la más reciente a la más antigua: lo que está antes que `_pos` es posterior
        for s in reversed(posteriores):
            if s.get("estado") == "interrumpida":
                continue
            decisiones = [x["texto"] for x in s["_items"] if x["tipo"] == "decision"]
            frases = frases_de_cierre(s.get("_resumen", ""), decisiones)
            if not frases:
                continue
            etiqueta = f"sesión {s.get('fecha') or ''} · {s.get('tema') or ''}".strip(" ·")
            idx = Indice([Doc(etiqueta, "sesion", [(f, None) for f in frases])])
            hallado = cobertura(it["texto"], idx, umbral)
            if hallado:
                (info, frac) = hallado
                return {"sesion_id": s["id"], "sesion": etiqueta, "fecha": s.get("fecha"), "tema": s.get("tema"), "texto": info["frase"], "coincidencia": frac}
        return None

    def _publico(self, it: dict, d: dict, proyecto: str) -> dict:
        est = d["estados"].get(it["id"]) or {}
        clave = BL.clave_repetido(it["texto"])
        acept = d["aceptados"].get(clave) or {}
        estado = it.get("estado") or "abierto"   # la verdad del estado es la del backlog (se mantiene en sintonía); aquí solo la cita y quién lo cerró
        if estado == "hecho" and est.get("estado") != "hecho":
            est = {}
        return {"id": it["id"], "texto": it["texto"], "minuto": it.get("minuto"), "responsable": acept.get("dueno") or it.get("responsable"),
                "plazo": acept.get("fecha") or "", "sesion_id": it["sesion_id"], "fecha": it.get("fecha"), "tema": it.get("sesion_tema"),
                "veces": it.get("veces", 1), "estado": estado, "auto": bool(est.get("auto")) and estado == "hecho", "cita": est.get("cita") if estado == "hecho" else None,
                "aceptado": bool(acept), "origen": "sesiones", "cierre_propuesto": None}

    def _sincronizar_backlog(self, iid: str, estado: str) -> None:
        try:
            self.bl.fijar_estado(iid, estado)
        except (ValueError, OSError, RutaProhibida):
            pass

    def lista(self, proyecto: str, refrescar: bool = False, evaluar: bool = True) -> dict:
        """Pendientes consolidados del proyecto con su estado. Con `evaluar`, aplica el cierre automático según la autonomía de «consolidar_pendientes»:
        `hacer` los cierra (con cita) y los demás niveles solo los dejan como `cierre_propuesto`. Un pendiente reabierto a mano no se vuelve a cerrar solo."""
        self.g.proyecto_dir(proyecto)   # valida que el proyecto existe
        umbral = float(self.cfg["seguimiento_umbral"])
        nivel = (self.cfg["autonomia"] or {}).get("consolidar_pendientes", "hacer")
        with self._lock:
            d = self._cargar(proyecto)
            items, sesiones = self._consolidados(proyecto, refrescar)
            salida, cambios = [], False
            for it in items:
                p = self._publico(it, d, proyecto)
                est = d["estados"].get(it["id"]) or {}
                if evaluar and p["estado"] == "abierto" and not est.get("bloqueado"):
                    cita = self._cerrar_por(it, sesiones, umbral)
                    if cita and nivel == "hacer":
                        d["estados"][it["id"]] = {"estado": "hecho", "auto": True, "cita": cita, "bloqueado": False, "en": self.ahora().isoformat(timespec="seconds")}
                        cambios = True
                        self._sincronizar_backlog(it["id"], "hecho")
                        it["estado"] = "hecho"
                        p = self._publico(it, d, proyecto)
                    elif cita:
                        p["cierre_propuesto"] = cita
                salida.append(p)
            # pendientes aceptados en la bandeja que aún no aparecen en ninguna sesión leída (p. ej. la sesión no se ha podido leer): salen igualmente
            claves = {BL.clave_repetido(i["texto"]) for i in items}
            for clave, a in d["aceptados"].items():
                if clave in claves:
                    continue
                iid = _id_extra(proyecto, clave)
                est = d["estados"].get(iid) or {}
                salida.append({"id": iid, "texto": a.get("texto", ""), "minuto": None, "responsable": a.get("dueno") or None, "plazo": a.get("fecha") or "",
                               "sesion_id": None, "fecha": a.get("fecha_sesion"), "tema": a.get("tema"), "veces": 1, "estado": est.get("estado") or "abierto",
                               "auto": bool(est.get("auto")), "cita": est.get("cita"), "aceptado": True, "origen": "acciones", "cierre_propuesto": None})
            if cambios:
                self._guardar(proyecto, d)
            abiertos = sum(1 for p in salida if p["estado"] == "abierto")
            return {"proyecto": proyecto, "pendientes": salida, "abiertos": abiertos, "hechos": sum(1 for p in salida if p["estado"] == "hecho"),
                    "autonomia": nivel, "umbral": umbral, "avisos": [self.aviso_roto[proyecto.lower()]] if proyecto.lower() in self.aviso_roto else []}

    # ------------------------------------------------------------ operaciones manuales
    def _item(self, proyecto: str, iid: str) -> str:
        if not re.fullmatch(r"[0-9a-f]{16}", iid or ""):
            raise ValueError("Identificador no válido.")
        return iid

    def _existe(self, proyecto: str, iid: str) -> bool:
        items, _ = self._consolidados(proyecto, False)
        if any(i["id"] == iid for i in items):
            return True
        d = self._cargar(proyecto)
        return any(_id_extra(proyecto, c) == iid for c in d["aceptados"])

    def marcar_hecho(self, proyecto: str, iid: str, cita=None) -> dict:
        """Lo marca el usuario (`auto` false); `cita` opcional (p. ej. la `cierre_propuesto` que aceptó)."""
        self.g.proyecto_dir(proyecto)
        iid = self._item(proyecto, iid)
        with self._lock:
            if not self._existe(proyecto, iid):
                raise LookupError("Ese pendiente ya no existe.")
            d = self._cargar(proyecto)
            c = None
            if isinstance(cita, dict) and _limpio(cita.get("texto")):
                c = {k: _limpio(cita.get(k))[:300] for k in ("sesion_id", "sesion", "fecha", "tema", "texto") if cita.get(k)}
            d["estados"][iid] = {"estado": "hecho", "auto": False, "cita": c, "bloqueado": True, "en": self.ahora().isoformat(timespec="seconds")}
            self._guardar(proyecto, d)
            self._sincronizar_backlog(iid, "hecho")
        return self._uno(proyecto, iid)

    def reabrir(self, proyecto: str, iid: str) -> dict:
        """Deshace un cierre (automático o a mano) y evita que se vuelva a cerrar solo."""
        self.g.proyecto_dir(proyecto)
        iid = self._item(proyecto, iid)
        with self._lock:
            if not self._existe(proyecto, iid):
                raise LookupError("Ese pendiente ya no existe.")
            d = self._cargar(proyecto)
            d["estados"][iid] = {"estado": "abierto", "auto": False, "cita": None, "bloqueado": True, "en": self.ahora().isoformat(timespec="seconds")}
            self._guardar(proyecto, d)
            self._sincronizar_backlog(iid, "abierto")
        return self._uno(proyecto, iid)

    def _uno(self, proyecto: str, iid: str) -> dict:
        r = self.lista(proyecto, False, evaluar=False)
        p = next((x for x in r["pendientes"] if x["id"] == iid), None)
        if p is None:
            raise LookupError("Ese pendiente ya no existe.")
        return p

    # ------------------------------------------------------------ al cerrar una sesión
    def tras_cerrar(self, proyecto: str) -> dict:
        """Relee las sesiones (la recién cerrada ya está guardada) y aplica el cierre automático. Nunca lanza."""
        try:
            return self.lista(proyecto, refrescar=True, evaluar=True)
        except Exception:   # noqa: BLE001
            return {}
