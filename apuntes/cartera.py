"""Vista de cartera (ola 4): la salud de cada proyecto de un vistazo, ordenada por lo que necesita atención. Todo local, sin modelo.

Sale del Backlog (las sesiones .md ya escritas, con el estado local de pendientes aplicado) y de las métricas guardadas. Por proyecto:
- sesiones recientes (últimos `cartera_ventana_dias` días) y días desde la última;
- pendientes abiertos y antiguos (abiertos de una sesión de hace más de `cartera_pendiente_antiguo_dias` días);
- objetivos: cerrados / total de las sesiones recientes que traen objetivos (se lee «Cubiertos N de M» del documento o, en su defecto, las líneas de objetivos);
- riesgos repetidos: mismo texto normalizado en ≥2 sesiones distintas del proyecto.
`atencion` suma puntos por cada problema (más puntos = antes en la lista) y `nivel` lo resume: bien | atencion | critico. `motivos` dice por qué, en una frase cada uno.
"""
from __future__ import annotations

import re
from datetime import date, datetime

from .backlog import normalizar

PUNTOS_RIESGO_REPETIDO = 3
PUNTOS_PENDIENTE_ANTIGUO = 2      # cada uno, hasta TOPE_ANTIGUOS
TOPE_ANTIGUOS = 5
PUNTOS_ABIERTOS_POR_5 = 1         # cada 5 pendientes abiertos
PUNTOS_SIN_ACTIVIDAD_30 = 2
PUNTOS_SIN_ACTIVIDAD_60 = 4
PUNTOS_OBJETIVOS_BAJO_50 = 3
PUNTOS_OBJETIVOS_BAJO_75 = 1
UMBRAL_CRITICO = 7
UMBRAL_ATENCION = 3
PROYECTOS_IGNORADOS = {"", "bandeja", "sin proyecto"}

_RE_CUBIERTOS = re.compile(r"Cubiertos\s+(\d+)\s+de\s+(\d+)", re.I)
_RE_LINEA_OBJ = re.compile(r"^\s*[-*]\s*\[(Cubierto|Parcial|Sin tratar)\]\s+\S", re.I | re.M)


def objetivos_de_resumen(resumen: str) -> tuple[int, int] | None:
    """(cerrados, total) de lo que el documento dice de sus objetivos, o None si no trae objetivos. FUNCIÓN PURA."""
    m = _RE_CUBIERTOS.search(resumen or "")
    if m:
        return int(m.group(1)), int(m.group(2))
    marcas = _RE_LINEA_OBJ.findall(resumen or "")
    if marcas:
        return sum(1 for x in marcas if x.lower() == "cubierto"), len(marcas)
    return None


def _fecha(s) -> date | None:
    try:
        return datetime.strptime(str(s)[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def nivel_de(puntos: int) -> str:
    return "critico" if puntos >= UMBRAL_CRITICO else "atencion" if puntos >= UMBRAL_ATENCION else "bien"


def salud_de_proyecto(nombre: str, sesiones: list[dict], hoy: date, ventana_dias: int = 30, antiguo_dias: int = 14) -> dict:
    """`sesiones`: las del proyecto como las da `Backlog.sesion(id)` (con `items`, `resumen`, `fecha`, `id`, `tema`). FUNCIÓN PURA."""
    sesiones = sorted(sesiones, key=lambda s: s.get("fecha") or "", reverse=True)
    recientes = [s for s in sesiones if (f := _fecha(s.get("fecha"))) and 0 <= (hoy - f).days <= ventana_dias]
    ultima = _fecha(sesiones[0].get("fecha")) if sesiones else None
    dias_ultima = (hoy - ultima).days if ultima else None
    abiertos, antiguos = [], []
    for s in sesiones:
        f = _fecha(s.get("fecha"))
        for it in s.get("items", []):
            if it.get("tipo") == "pendiente" and it.get("estado") == "abierto" and not it.get("duplicado"):
                abiertos.append(it)
                if f and (hoy - f).days > antiguo_dias:
                    antiguos.append({"texto": it["texto"], "fecha": s.get("fecha"), "dias": (hoy - f).days, "sesion_id": s.get("id")})
    cerr = tot = 0
    for s in recientes:
        o = objetivos_de_resumen(s.get("resumen", ""))
        if o:
            cerr += o[0]
            tot += o[1]
    ratio = round(cerr / tot, 2) if tot else None
    # riesgos repetidos: el mismo texto normalizado en sesiones distintas
    por_clave: dict[str, dict] = {}
    for s in sesiones:
        for it in s.get("items", []):
            if it.get("tipo") != "riesgo":
                continue
            clave = normalizar(it["texto"].rstrip("…. "))[:80]
            if not clave:
                continue
            r = por_clave.setdefault(clave, {"texto": it["texto"], "sesiones": set(), "ultima": s.get("fecha")})
            r["sesiones"].add(s.get("id"))
    riesgos = sorted(({"texto": r["texto"], "sesiones": len(r["sesiones"]), "ultima_fecha": r["ultima"]} for r in por_clave.values() if len(r["sesiones"]) >= 2),
                     key=lambda r: (-r["sesiones"], r["texto"]))
    puntos, motivos = 0, []
    if riesgos:
        puntos += PUNTOS_RIESGO_REPETIDO * len(riesgos)
        motivos.append(f"{len(riesgos)} riesgo(s) repetido(s) en varias sesiones")
    if antiguos:
        puntos += PUNTOS_PENDIENTE_ANTIGUO * min(len(antiguos), TOPE_ANTIGUOS)
        motivos.append(f"{len(antiguos)} pendiente(s) abierto(s) de hace más de {antiguo_dias} días")
    if len(abiertos) >= 5:
        puntos += PUNTOS_ABIERTOS_POR_5 * (len(abiertos) // 5)
        motivos.append(f"{len(abiertos)} pendientes abiertos")
    if dias_ultima is not None and dias_ultima > 60:
        puntos += PUNTOS_SIN_ACTIVIDAD_60
        motivos.append(f"sin sesiones desde hace {dias_ultima} días")
    elif dias_ultima is not None and dias_ultima > 30:
        puntos += PUNTOS_SIN_ACTIVIDAD_30
        motivos.append(f"sin sesiones desde hace {dias_ultima} días")
    if ratio is not None and ratio < 0.5:
        puntos += PUNTOS_OBJETIVOS_BAJO_50
        motivos.append(f"solo se cierra el {round(ratio * 100)} % de los objetivos")
    elif ratio is not None and ratio < 0.75:
        puntos += PUNTOS_OBJETIVOS_BAJO_75
        motivos.append(f"se cierra el {round(ratio * 100)} % de los objetivos")
    return {"proyecto": nombre, "nivel": nivel_de(puntos), "atencion": puntos, "motivos": motivos,
            "sesiones": {"total": len(sesiones), "recientes": len(recientes), "ventana_dias": ventana_dias, "ultima_fecha": sesiones[0].get("fecha") if sesiones else None,
                         "dias_desde_ultima": dias_ultima, "ultima_tema": sesiones[0].get("tema") if sesiones else None},
            "pendientes": {"abiertos": len(abiertos), "antiguos": len(antiguos), "mas_antiguos": sorted(antiguos, key=lambda a: -a["dias"])[:3]},
            "objetivos": {"cerrados": cerr, "total": tot, "ratio_cerrados": ratio, "sesiones_con_objetivos": sum(1 for s in recientes if objetivos_de_resumen(s.get("resumen", "")))},
            "riesgos_repetidos": riesgos[:5]}


def cartera(backlog, ventana_dias: int = 30, antiguo_dias: int = 14, refrescar: bool = False, metricas=None) -> dict:
    """La cartera completa: un elemento por proyecto con sesiones, de más a menos necesidad de atención (desempate: la actividad más reciente primero)."""
    hoy = backlog.ahora().date() if hasattr(backlog.ahora(), "date") else date.today()
    lista = backlog.sesiones(refrescar)
    por_proyecto: dict[str, list[dict]] = {}
    nombres: dict[str, str] = {}
    for s in lista["sesiones"]:
        clave = (s.get("proyecto") or "").strip().lower()
        if clave in PROYECTOS_IGNORADOS:
            continue
        nombres.setdefault(clave, s["proyecto"])
        completa = backlog.sesion(s["id"])
        if completa:
            por_proyecto.setdefault(clave, []).append(completa)
    out = [salud_de_proyecto(nombres[k], v, hoy, ventana_dias, antiguo_dias) for k, v in por_proyecto.items()]
    if metricas is not None:   # lo medido en reuniones (objetivos cerrados, tokens) cuando hay
        for p in out:
            regs = metricas.de_proyecto(p["proyecto"])
            if regs:
                from .metricas import agregar
                a = agregar(regs)
                p["valor"] = {"sesiones_medidas": a["sesiones"], "ratio_cerrados": a["objetivos"]["ratio_cerrados"],
                              "minutos_medio_hasta_cierre": a["objetivos"]["minutos_medio_hasta_cierre"], "tasa_aceptacion": a["avisos"]["tasa_aceptacion"]}
    out.sort(key=lambda p: (-p["atencion"], p["sesiones"]["dias_desde_ultima"] if p["sesiones"]["dias_desde_ultima"] is not None else 10 ** 6, p["proyecto"].lower()))
    return {"hoy": hoy.isoformat(), "ventana_dias": ventana_dias, "pendiente_antiguo_dias": antiguo_dias, "proyectos": out,
            "resumen": {"proyectos": len(out), "critico": sum(1 for p in out if p["nivel"] == "critico"),
                        "atencion": sum(1 for p in out if p["nivel"] == "atencion"), "bien": sum(1 for p in out if p["nivel"] == "bien")},
            "avisos": lista.get("avisos", [])}
