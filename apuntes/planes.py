"""Planes de sesiones de un proyecto (`planes/*.json`, locales) y estado de sus objetivos.

El plan lo escribe el usuario; aquí solo se lee (a través del Guardian) y se normaliza. El estado de los
objetivos durante la reunión lo actualiza el análisis periódico, citando el minuto, y un objetivo cubierto
no retrocede salvo evidencia clara del modelo (`d`).
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta

from .rutas import Guardian, clave_declarada
from .texto import a_segundos, mmss, recortar

SIN_TRATAR, PARCIAL, CUBIERTO = "sin_tratar", "parcial", "cubierto"
RANGO = {SIN_TRATAR: 0, PARCIAL: 1, CUBIERTO: 2}
ETIQUETA = {SIN_TRATAR: "Sin tratar", PARCIAL: "Parcial", CUBIERTO: "Cubierto"}
_ABREV = {"c": CUBIERTO, "p": PARCIAL, "n": SIN_TRATAR}
_MARCA = {SIN_TRATAR: " ", PARCIAL: "p", CUBIERTO: "c"}

MAX_SESIONES, MAX_OBJETIVOS, MAX_CHECKS_BASE = 20, 12, 12
FECHA_ESTADOS = ("confirmada", "propuesta", "por_definir", "por_confirmar")
_RE_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_RE_HORA = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
_RE_SEMANA = re.compile(r"^S\d{1,2}$")
_RE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_\-]{0,19}$")
_RE_FICHERO = re.compile(r"^[0-9]{2}-[A-Za-z0-9][A-Za-z0-9\-]{0,80}\.md$")


def _texto(v, maximo: int) -> str:
    return recortar(" ".join(str(v or "").split()), maximo)


def _iso(v) -> str:
    s = str(v or "").strip()
    if not _RE_ISO.match(s):
        return ""
    try:
        date.fromisoformat(s)
    except ValueError:
        return ""
    return s


def _estado_fecha(v, iso: str) -> str:
    e = str(v or "").strip()
    if e not in FECHA_ESTADOS:
        e = "confirmada" if iso else "por_definir"
    return e if iso or e in ("por_definir", "por_confirmar") else "por_definir"  # sin fecha exacta no hay «confirmada»


def _semana(v) -> str:
    s = str(v or "").strip().upper()
    return s if _RE_SEMANA.match(s) else ""


def normalizar_gantt(crudo) -> dict | None:
    """-> {semanas, fases, hitos, sesiones, ventana_sesiones} o None. No inventa nada: una fecha sin ISO
    queda «por definir» o «por confirmar» y no se dibuja con día."""
    if not isinstance(crudo, dict):
        return None
    semanas = []
    for s in (crudo.get("semanas") or [])[:30]:
        if isinstance(s, dict) and _semana(s.get("id")) and _iso(s.get("inicio")):
            semanas.append({"id": _semana(s["id"]), "inicio": _iso(s["inicio"])})
    ids = {s["id"] for s in semanas}
    if not semanas:
        return None
    fases = []
    for f in (crudo.get("fases") or [])[:12]:
        if not isinstance(f, dict) or not _texto(f.get("nombre"), 60):
            continue
        d, h = _semana(f.get("desde")), _semana(f.get("hasta"))
        if d in ids and h in ids:
            fases.append({"id": _texto(f.get("id") or f.get("nombre"), 30), "nombre": _texto(f["nombre"], 60),
                          "etiqueta": _texto(f.get("etiqueta"), 30), "desde": d, "hasta": h, "nota": _texto(f.get("nota"), 200)})

    def _fecha_item(x: dict) -> dict:
        iso = _iso(x.get("fecha_iso"))
        sem = _semana(x.get("semana"))
        return {"semana": sem if sem in ids else "", "fecha_iso": iso,
                "fecha_estado": _estado_fecha(x.get("fecha_estado"), iso), "fecha_texto": _texto(x.get("fecha_texto"), 120)}

    hitos = [dict(id=_texto(h.get("id") or h.get("nombre"), 30), nombre=_texto(h["nombre"], 80),
                  tipo=("aceptacion" if h.get("tipo") == "aceptacion" else "hito"), **_fecha_item(h))
             for h in (crudo.get("hitos") or [])[:20] if isinstance(h, dict) and _texto(h.get("nombre"), 80)]
    sesiones = []
    for s in (crudo.get("sesiones") or [])[:20]:
        if not isinstance(s, dict) or not _texto(s.get("nombre"), 100) or not _RE_ID.match(str(s.get("id") or "")):
            continue
        hora = str(s.get("hora") or "").strip()
        sesiones.append({"id": str(s["id"]), "nombre": _texto(s["nombre"], 100), "hora": hora if _RE_HORA.match(hora) else "",
                         "participantes": _texto(s.get("participantes"), 200), **_fecha_item(s)})
    v = crudo.get("ventana_sesiones") if isinstance(crudo.get("ventana_sesiones"), dict) else {}
    ventana = {"desde": _semana(v.get("desde")), "hasta": _semana(v.get("hasta"))}
    if ventana["desde"] not in ids or ventana["hasta"] not in ids:
        ventana = None
    return {"semanas": semanas, "fases": fases, "hitos": hitos, "sesiones": sesiones, "ventana_sesiones": ventana}


def normalizar_ficha(crudo) -> dict | None:
    if not isinstance(crudo, dict):
        return None
    lineas = [_texto(x, 300) for x in (crudo.get("que_es") or [])[:3] if _texto(x, 300)]
    f = crudo.get("fuente") if isinstance(crudo.get("fuente"), dict) else {}
    fuente = {"fichero": _texto(f.get("fichero"), 160), "version": _texto(f.get("version"), 120)}
    return {"que_es": lineas, "fuente": fuente} if lineas else None


def normalizar_plan(crudo) -> dict | None:
    """-> {proyecto, sesiones: [{id, nombre, fecha, fecha_iso, hora, participantes, objetivos: [str], checks: [str],
    fichero_prioritario, depende_de: [id]}], ficha?, gantt?} o None si no tiene la forma esperada."""
    if not isinstance(crudo, dict) or not isinstance(crudo.get("sesiones"), list):
        return None
    proyecto = _texto(crudo.get("proyecto"), 120)
    if not proyecto:
        return None
    sesiones, ids = [], set()
    for s in crudo["sesiones"][:MAX_SESIONES]:
        if not isinstance(s, dict):
            continue
        sid = str(s.get("id") or "").strip()
        nombre = _texto(s.get("nombre"), 120)
        if not _RE_ID.match(sid) or not nombre or sid.lower() in ids:
            continue
        ids.add(sid.lower())
        objetivos = [_texto(o, 200) for o in (s.get("objetivos") or [])[:MAX_OBJETIVOS] if _texto(o, 200)]
        prio = str(s.get("fichero_prioritario") or "").strip()
        hora = str(s.get("hora") or "").strip()
        checks = []
        for c in (s.get("checks") or [])[:MAX_CHECKS_BASE]:
            c = _texto(c, 140)
            if c and c.lower() not in [x.lower() for x in checks]:
                checks.append(c)
        sesiones.append({
            "id": sid, "nombre": nombre, "fecha": _texto(s.get("fecha"), 80),
            "fecha_iso": _iso(s.get("fecha_iso")), "hora": hora if _RE_HORA.match(hora) else "", "checks": checks,
            "participantes": _texto(s.get("participantes"), 200), "objetivos": objetivos,
            "fichero_prioritario": prio if _RE_FICHERO.match(prio) else "",
            "depende_de": [str(d) for d in (s.get("depende_de") or []) if _RE_ID.match(str(d))][:6]})
    if not sesiones:
        return None
    plan = {"proyecto": proyecto, "sesiones": sesiones}
    ficha, gantt = normalizar_ficha(crudo.get("ficha")), normalizar_gantt(crudo.get("gantt"))
    if ficha:
        plan["ficha"] = ficha
    if gantt:
        plan["gantt"] = gantt
    return plan


class PlanesPorProyecto(dict):
    """clave del proyecto (`rutas.clave_declarada`: NFC y sin mayúsculas) -> plan normalizado. Quien consulta con el nombre del proyecto tal cual (`get`, `[]`, `in`) lo
    casa con la MISMA función que el editor del plan, aunque la llamada use otra forma del nombre (mayúsculas, NFD)."""

    @staticmethod
    def _k(k):
        return clave_declarada(k) if isinstance(k, str) else k

    def get(self, k, default=None):
        return super().get(self._k(k), default)

    def __getitem__(self, k):
        return super().__getitem__(self._k(k))

    def __contains__(self, k):
        return super().__contains__(self._k(k))


def cargar_planes(g: Guardian) -> dict[str, dict]:
    """proyecto (clave de `rutas.clave_declarada`, la misma del editor) -> plan normalizado. Un JSON roto se ignora sin afectar al resto."""
    out = PlanesPorProyecto()
    for _nombre, texto in g.leer_planes():
        try:
            plan = normalizar_plan(json.loads(texto))
        except ValueError:
            continue
        if plan:
            out[clave_declarada(plan["proyecto"])] = plan
    return out


def plan_de(g: Guardian, proyecto: str | None) -> dict | None:
    return cargar_planes(g).get(clave_declarada(proyecto)) if proyecto else None


def sesion_de(plan: dict | None, sesion_id: str | None) -> dict | None:
    if not plan or not sesion_id:
        return None
    for s in plan["sesiones"]:
        if s["id"].lower() == str(sesion_id).lower():
            return s
    raise ValueError("La sesión elegida no existe en el plan del proyecto.")


# ------------------------------------------------------------------ estado de objetivos
def objetivos_iniciales(sesion: dict | None) -> list[dict]:
    if not sesion:
        return []
    return [objetivo_nuevo(i, t, "plan") for i, t in enumerate(sesion["objetivos"], 1)]


def objetivo_nuevo(n: int, texto: str, origen: str = "usuario", sugerido: bool = False) -> dict:
    """`origen`: plan | usuario | sugerido. `t_primero`: segundos de la PRIMERA evidencia (la barra del Gantt de la sesión
    va de ahí a `t_seg`, la última). Un sugerido no se envía al modelo hasta que el usuario lo confirma."""
    return {"n": n, "texto": texto, "estado": SIN_TRATAR, "minuto": "", "t_seg": None, "t_primero": None,
            "origen": origen, "sugerido": sugerido}


def activos(objetivos: list[dict]) -> list[dict]:
    """Los que se evalúan en el análisis: todos menos los sugeridos aún sin confirmar."""
    return [o for o in objetivos if not o.get("sugerido")]


def para_prompt(objetivos: list[dict]) -> list[dict]:
    """Copias de los activos numeradas 1..k por posición (el modelo responde con esa posición)."""
    return [{**o, "n": i} for i, o in enumerate(activos(objetivos), 1)]


def aplicar_por_posicion(objetivos: list[dict], cambios: list[dict]) -> list[int]:
    """Como `aplicar_actualizaciones`, pero `cambios` usa la posición entre los activos (ver `para_prompt`)."""
    act = activos(objetivos)
    traducidos = [{**c, "n": act[c["n"] - 1]["n"]} for c in cambios if 1 <= c["n"] <= len(act)]
    return aplicar_actualizaciones(objetivos, traducidos)


def bloque_prompt(objetivos: list[dict]) -> str:
    """Compacto: «1 [p 08:57] texto». [ ] sin tratar, [p MM:SS] parcial, [c MM:SS] cubierto (con el minuto de su última evidencia)."""
    def marca(o: dict) -> str:
        m = _MARCA[o["estado"]]
        return f"{m} {o['minuto']}" if o["estado"] != SIN_TRATAR and o.get("minuto") else m
    return "\n".join(f"{o['n']} [{marca(o)}] {o['texto']}" for o in objetivos)


def normalizar_actualizaciones(lista, n_objetivos: int) -> list[dict]:
    """Salida del modelo -> [{n, estado, minuto, d}] válidas (índices 1..n, un cambio por objetivo)."""
    out, vistos = [], set()
    if not isinstance(lista, list):
        return out
    for u in lista[: max(0, n_objetivos)]:
        if not isinstance(u, dict):
            continue
        n, e = u.get("i"), _ABREV.get(str(u.get("e", "")).strip().lower()[:1])
        if isinstance(n, bool) or not isinstance(n, int) or not 1 <= n <= n_objetivos or e is None or n in vistos:
            continue
        vistos.add(n)
        seg = a_segundos(str(u.get("m") or ""))
        out.append({"n": n, "estado": e, "minuto": mmss(seg) if seg is not None else "",
                    "d": u.get("d") in (1, True, "1")})
    return out


def aplicar_actualizaciones(objetivos: list[dict], cambios: list[dict]) -> list[int]:
    """Aplica los cambios; devuelve los números de objetivo que cambiaron.

    - Un objetivo cubierto no retrocede (ni cambia de minuto) salvo que el modelo marque evidencia clara (`d`).
    - Un objetivo no cubierto se reevalúa en cada tramo: si avanza, toma el nuevo estado y minuto; si sigue igual,
      su minuto pasa a ser el de la evidencia más reciente (nunca a uno anterior); retroceder (parcial -> sin tratar)
      sin `d` se ignora."""
    tocados = []
    por_n = {o["n"]: o for o in objetivos}
    for c in cambios:
        o = por_n.get(c["n"])
        if not o:
            continue
        nuevo, actual = RANGO[c["estado"]], RANGO[o["estado"]]
        if nuevo < actual and not c.get("d"):
            continue
        t_nuevo = a_segundos(c["minuto"]) if c["minuto"] else None
        if c["estado"] == o["estado"]:
            if o["estado"] == CUBIERTO or not c["minuto"]:
                continue
            if o["t_seg"] is None or (t_nuevo is not None and t_nuevo > o["t_seg"]):
                o["minuto"], o["t_seg"] = c["minuto"], t_nuevo
                if o.get("t_primero") is None and t_nuevo is not None:
                    o["t_primero"] = t_nuevo
                tocados.append(o["n"])
            continue
        o["estado"] = c["estado"]
        o["minuto"] = c["minuto"]
        o["t_seg"] = t_nuevo
        if t_nuevo is not None and (o.get("t_primero") is None or t_nuevo < o["t_primero"]):
            o["t_primero"] = t_nuevo
        tocados.append(o["n"])
    return tocados


def resumen_markdown(objetivos: list[dict], nombre_sesion: str = "") -> str:
    """Bloque determinista que se añade al resumen final: qué se cumplió y qué queda pendiente."""
    if not objetivos:
        return ""
    cubiertos = [o for o in objetivos if o["estado"] == CUBIERTO]
    parciales = [o for o in objetivos if o["estado"] == PARCIAL]
    pendientes = [o for o in objetivos if o["estado"] == SIN_TRATAR]
    L = [f"## Objetivos de la sesión{' ' + nombre_sesion if nombre_sesion else ''}", "",
         f"Cubiertos {len(cubiertos)} de {len(objetivos)}; parciales {len(parciales)}; sin tratar {len(pendientes)}.", ""]
    for titulo, grupo in (("Cumplidos", cubiertos), ("Parciales (quedan pendientes)", parciales),
                          ("Sin tratar (quedan pendientes)", pendientes)):
        if not grupo:
            continue
        L.append(f"**{titulo}**")
        for o in grupo:
            L.append(f"- {o['texto']}" + (f" (minuto {o['minuto']})" if o["minuto"] else ""))
        L.append("")
    return "\n".join(L).rstrip() + "\n"


# ------------------------------------------------------------------ panel de contexto (sin LLM)
def _dt(iso: str, hora: str, fin_de_dia: bool) -> datetime:
    d = date.fromisoformat(iso)
    if hora:
        return datetime.combine(d, datetime.strptime(hora, "%H:%M").time())
    return datetime.combine(d, datetime.max.time() if fin_de_dia else datetime.min.time())


def estado_sesion_gantt(s: dict, ahora: datetime) -> str:
    """celebrada | hoy | proxima | propuesta | por_definir | por_confirmar. Una sesión con fecha cuyo momento ya pasó
    figura como celebrada; sin fecha exacta nunca se inventa una."""
    if not s["fecha_iso"]:
        return s["fecha_estado"] if s["fecha_estado"] in ("por_definir", "por_confirmar") else "por_definir"
    if _dt(s["fecha_iso"], s.get("hora", ""), True) < ahora:
        return "celebrada"
    if s["fecha_iso"] == ahora.date().isoformat():
        return "hoy"
    return "propuesta" if s["fecha_estado"] == "propuesta" else "proxima"


def fin_semana(g: dict, semana: str) -> date:
    for s in g["semanas"]:
        if s["id"] == semana:
            return date.fromisoformat(s["inicio"]) + timedelta(days=6)
    raise KeyError(semana)


def enriquecer(plan: dict | None, ahora: datetime | None = None) -> dict | None:
    """Copia del plan con `hoy` y los estados derivados del Gantt (sesiones celebradas, hitos hechos y
    próximos hitos). Es lo que muestra la pantalla de inicio; no llama a ningún modelo."""
    if not plan:
        return plan
    ahora = ahora or datetime.now()
    out = json.loads(json.dumps(plan))
    out["hoy"] = ahora.date().isoformat()
    g = out.get("gantt")
    if not g:
        return out
    for s in g["sesiones"]:
        s["estado"] = estado_sesion_gantt(s, ahora)
    proximos = []
    for h in g["hitos"]:
        if h["fecha_iso"]:
            hecho = _dt(h["fecha_iso"], "", True) < ahora
        else:
            hecho = False  # sin día exacto no se da por alcanzado
        h["estado"] = "hecho" if hecho else "pendiente"
        if not hecho:
            proximos.append(h["id"])
    g["proximos_hitos"] = proximos[:6]
    por_id = {s["id"].lower(): s for s in g["sesiones"]}  # la sesión del plan hereda el estado de su gemela del Gantt
    for s in out["sesiones"]:
        gs = por_id.get(s["id"].lower())
        s["estado_gantt"] = gs["estado"] if gs else ""
    return out
