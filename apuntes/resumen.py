"""Resumen visual de cada proyecto para la galería de inicio (sin LLM, solo lectura).

Por proyecto: `descripcion` (primera frase con sentido de la ficha, de CLAUDE.md o del README), `sesiones_por_semana` (8 semanas, la última
es la actual), `pendientes_abiertos` (los da el backlog, que ya mira `backlog/estado.json`), `proximo_hito` (del plan, si hay) y
`calidad_contexto` ({nivel 0-3, etiqueta, motivos[]}).

Reglas: todo se lee por el Guardian (`md_del_proyecto`, `leer_md_proyecto`: mismas exclusiones y topes), las secciones «Contactos» y las
líneas con pinta de secreto, correo o teléfono nunca entran en la descripción, cada proyecto se calcula en un hilo propio con plazo común
(lo lento sale sin esos campos y la caché lo deja listo para la siguiente petición) y el resultado se guarda por fecha de modificación."""
from __future__ import annotations

import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta

from . import contexto as CX
from .rutas import CARPETA_CONTEXTO, Guardian, RutaProhibida

SEMANAS = 8
MAX_DESCRIPCION = 140
TOPE_LECTURA = 24_000                 # bytes que se leen de la ficha / CLAUDE.md / README para sacar una frase
DIAS_RECIENTE = 90                    # un contexto sin tocar desde hace más es «antiguo»
FICHEROS_BUEN_CONTEXTO = 3            # ficheros de contenido en 00. CONTEXTO (IA) para considerarlo completo
NO_CONTENIDO = {n.lower() for n in CX.NO_ANALIZAR}   # índice, registro de cambios y guía: no cuentan como contenido

_RE_MARCA_OMITIDA = "[línea omitida"
_RE_PERSONAL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+|(?<!\d)(?:\+?\d[\s.-]?){9,}(?!\d)|https?://\S*(?:token|key|secret)\S*", re.I)
_RE_SECRETO_LAXO = re.compile(r"\b(contraseñ\w*|password|passwd|clave|api[_ -]?key|token|secret\w*|credencial\w*|usuario\s*:)\b", re.I)
_RE_METADATO = re.compile(r"^\W*(última actualización|ultima actualizacion|fecha|autor|autora|versión|version|responsable|estado|cliente|proyecto|jefe|jefa)\s*[:·|]", re.I)
_RE_PLACEHOLDER = re.compile(r"\{\{|\}\}|\bTODO\b|lorem ipsum|<[^>]{1,40}>\s*$", re.I)
_RE_FRASE = re.compile(r"(?<=[.!?…])\s+(?=[A-ZÁÉÍÓÚÑ¿¡\"“«(])")


# ---------------------------------------------------------------- descripción
def _limpiar_md(linea: str) -> str:
    s = linea.strip()
    s = re.sub(r"^(?:>\s*)+", "", s)
    s = re.sub(r"^(?:[-*+]\s+|\d+[.)]\s+)", "", s)
    s = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", s)
    s = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", s)
    s = re.sub(r"\[\[([^\]|]*)(?:\|([^\]]*))?\]\]", lambda m: m.group(2) or m.group(1), s)
    s = re.sub(r"`+([^`]*)`+", r"\1", s)
    s = re.sub(r"(\*\*|__)(.+?)\1", r"\2", s)
    s = re.sub(r"(?<![\w*])[*_]([^*_]+)[*_](?![\w*])", r"\1", s)
    s = re.sub(r"<[^>]+>", "", s)
    s = re.sub(r"^\s*#{1,6}\s*", "", s)
    return " ".join(s.split())


def _recortar_palabra(s: str, maximo: int) -> str:
    if len(s) <= maximo:
        return s
    corte = s[: maximo - 1].rsplit(" ", 1)[0].rstrip(" ,;:-–—")
    return (corte or s[: maximo - 1]) + "…"


def frase_descriptiva(texto: str, maximo: int = MAX_DESCRIPCION) -> str | None:
    """Primera frase con sentido de un .md: sin markdown, sin títulos, tablas, código, YAML, plantillas sin rellenar, secciones «Contactos»
    ni líneas con pinta de secreto, correo o teléfono. Acotada a `maximo` caracteres. None si no hay nada que valga."""
    texto = CX.quitar_secciones(texto.replace("\r\n", "\n"), CX.SECCIONES_PERSONALES)
    en_codigo = False
    en_yaml = texto.lstrip().startswith("---")
    primera = True
    candidatas: list[str] = []
    for linea in texto.split("\n"):
        crudo = linea.strip()
        if primera and crudo:
            primera = False
            if crudo == "---":
                continue
        if en_yaml:
            if crudo == "---" and not primera:
                en_yaml = False
            continue
        if crudo.startswith("```") or crudo.startswith("~~~"):
            en_codigo = not en_codigo
            continue
        if en_codigo or not crudo or crudo.startswith("#") or crudo.startswith("|") or crudo.startswith("<!--") or re.fullmatch(r"[-=*_\s|:]+", crudo):
            continue
        if _RE_MARCA_OMITIDA in crudo or _RE_PERSONAL.search(crudo) or _RE_SECRETO_LAXO.search(crudo) or _RE_PLACEHOLDER.search(crudo) or _RE_METADATO.search(_limpiar_md(crudo)):
            continue
        limpia = _limpiar_md(crudo)
        if len(re.findall(r"\w+", limpia)) < 5:        # etiquetas sueltas («Cliente: X») no describen nada
            continue
        candidatas.append(limpia)
        if len(candidatas) >= 4:
            break
    for c in candidatas:
        for frase in _RE_FRASE.split(c):
            frase = frase.strip()
            if len(re.findall(r"\w+", frase)) >= 5:
                return _recortar_palabra(frase.rstrip(" ,;:"), maximo)
    return None


def _descripcion(g: Guardian, nombre: str, entradas: list[dict]) -> str | None:
    """Ficha de 00. CONTEXTO (IA) → CLAUDE.md → README.md (en ese orden). Lee a través del Guardian."""
    ficha, claude, readme, otros = [], [], [], []
    for e in entradas:
        if e["dejado"]:
            continue
        grupo, etiqueta = CX._grupo_y_etiqueta(e["rel"])
        bajo = etiqueta.lower()
        if grupo == "ctx" and "ficha" in bajo and e["prof"] == 1:
            ficha.append(e)
        elif e["rel"].lower() == "claude.md":
            claude.append(e)
        elif e["rel"].lower() == "readme.md":
            readme.append(e)
        elif grupo == "ctx" and e["prof"] == 1 and etiqueta.lower() not in NO_CONTENIDO:
            otros.append(e)
    ficha.sort(key=lambda e: e["rel"].lower())
    otros.sort(key=lambda e: e["rel"].lower())
    for e in [*ficha, *claude, *readme, *otros]:
        try:
            texto = g.leer_md_proyecto(nombre, e["ruta"], TOPE_LECTURA)
        except (RutaProhibida, OSError):
            continue
        frase = frase_descriptiva(texto)
        if frase:
            return frase
    return None


# ---------------------------------------------------------------- actividad
def sesiones_por_semana(fechas, hoy: date, n: int = SEMANAS) -> list[int]:
    """Sesiones por semana (lunes a domingo) de las últimas `n` semanas, de la más antigua a la actual (la última)."""
    lunes = hoy - timedelta(days=hoy.weekday())
    cuenta = [0] * n
    for f in fechas:
        try:
            d = date.fromisoformat(f)
        except (TypeError, ValueError):
            continue
        i = n - 1 - (lunes - (d - timedelta(days=d.weekday()))).days // 7
        if 0 <= i < n:
            cuenta[i] += 1
    return cuenta


# ---------------------------------------------------------------- calidad del contexto
def calidad_contexto(*, n_md: int, n_ctx: int, n_contenido: int, dias: int | None, hay_claude: bool) -> dict:
    """Nivel 0 = sin ningún .md · 1 = solo .md sueltos (CLAUDE.md, README…) · 2 = 00. CONTEXTO con algo que mejorar · 3 = completo
    (00. CONTEXTO con ≥3 ficheros de contenido, tocado en los últimos 90 días). `motivos`: qué falta, en frases que dicen cómo arreglarlo;
    `breve`: lo mismo en pocas palabras para la tarjeta."""
    motivos: list[str] = []
    if n_md == 0:
        return {"nivel": 0, "etiqueta": "Sin contexto", "breve": "Sin ningún .md",
                "motivos": ["No hay ningún .md en la carpeta: el asesor no tendrá nada que leer.",
                            "Crea «00. CONTEXTO (IA)» con una ficha (01-ficha-del-proyecto.md) o añade un CLAUDE.md o un README.md."]}
    if n_ctx == 0:
        return {"nivel": 1, "etiqueta": "Contexto básico", "breve": "Falta 00. CONTEXTO (IA)",
                "motivos": ["Falta la carpeta «00. CONTEXTO (IA)»: es lo que el asesor lee primero y donde la app propone cambios.",
                            "Mientras tanto se usan los .md que hay (CLAUDE.md, README…) en solo lectura."]}
    puntos, breve = 1, []
    if n_contenido >= FICHEROS_BUEN_CONTEXTO:
        puntos += 1
    else:
        breve.append("pocos ficheros")
        motivos.append(f"Solo {n_contenido} {'fichero' if n_contenido == 1 else 'ficheros'} de contenido en «00. CONTEXTO (IA)»: con {FICHEROS_BUEN_CONTEXTO} o más "
                       "(ficha, alcance, plan) el asesor responde mejor.")
    if dias is not None and dias <= DIAS_RECIENTE:
        puntos += 1
    elif dias is not None:
        breve.append(f"sin tocar hace {dias} d")
        motivos.append(f"El contexto no se toca desde hace {dias} días: revísalo si algo ha cambiado.")
    nivel = min(3, puntos)
    etiqueta = {1: "Contexto pobre", 2: "Contexto aceptable", 3: "Contexto completo"}[nivel]
    return {"nivel": nivel, "etiqueta": etiqueta, "breve": ", ".join(breve).capitalize() if breve else "Completo", "motivos": motivos}


# ---------------------------------------------------------------- hito del plan
def proximo_hito(plan: dict | None) -> dict | None:
    """El próximo hito del Gantt del plan (el primero de `proximos_hitos`, ya calculado por `planes.enriquecer`). Sin plan o sin hitos: None."""
    g = (plan or {}).get("gantt") or {}
    por_id = {h.get("id"): h for h in g.get("hitos") or []}
    for hid in g.get("proximos_hitos") or []:
        h = por_id.get(hid)
        if h:
            return {"nombre": h.get("nombre") or "", "fecha_iso": h.get("fecha_iso") or "", "fecha_texto": h.get("fecha_texto") or ""}
    return None


# ---------------------------------------------------------------- cálculo con caché y plazo
_CACHE: dict[str, tuple] = {}
_LOCK = threading.Lock()
_POOL = ThreadPoolExecutor(max_workers=4, thread_name_prefix="resumen-proyecto")
TTL_S = 120.0


def _mtime(p) -> int:
    try:
        return os.stat(p).st_mtime_ns
    except OSError:
        return 0


def _firma(g: Guardian, nombre: str, ruta: str, compartido: bool) -> tuple:
    return (_mtime(ruta), _mtime(os.path.join(ruta, CARPETA_CONTEXTO)),
            tuple(_mtime(c) for c in CX._carpetas_sesiones(g, nombre, ruta, compartido)),
            _mtime(os.path.join(ruta, "CLAUDE.md")), _mtime(os.path.join(ruta, "README.md")))


def _calcular(g: Guardian, nombre: str, ruta: str, compartido: bool, limites: dict, ahora: datetime) -> dict:
    _n, _distintas, fechas = CX._sesiones_de(g, nombre, ruta, compartido)
    n_md = n_ctx = n_contenido = 0
    hay_claude = False
    ultimo = 0.0
    entradas: list[dict] = []
    try:
        r = g.md_del_proyecto(nombre, profundidad=limites.get("profundidad", 4), tope_bytes=limites.get("tope_bytes", 200_000),
                              plazo_s=1.0, max_visitas=2500)
        entradas = r["ficheros"]
    except (RutaProhibida, OSError):
        pass
    for e in entradas:
        n_md += 1
        grupo, etiqueta = CX._grupo_y_etiqueta(e["rel"])
        if grupo == "ctx":
            n_ctx += 1
            if etiqueta.lower() not in NO_CONTENIDO and e["tam"] > 120:
                n_contenido += 1
            ultimo = max(ultimo, e["mtime"])
        elif grupo == "raiz":
            hay_claude = True
    dias = max(0, int((ahora.timestamp() - ultimo) // 86400)) if ultimo else None
    return {"fechas": sorted(fechas), "descripcion": _descripcion(g, nombre, entradas), "n_md": n_md,
            "calidad": calidad_contexto(n_md=n_md, n_ctx=n_ctx, n_contenido=n_contenido, dias=dias, hay_claude=hay_claude)}


def _de_cache(g: Guardian, nombre: str, ruta: str, compartido: bool, limites: dict, ahora: datetime) -> dict:
    clave = CX._norm(ruta)
    firma = _firma(g, nombre, ruta, compartido)
    with _LOCK:
        previo = _CACHE.get(clave)
    if previo and previo[0] == firma and time.monotonic() - previo[2] < TTL_S:
        return previo[1]
    valor = _calcular(g, nombre, ruta, compartido, limites, ahora)
    with _LOCK:
        _CACHE[clave] = (firma, valor, time.monotonic())
    return valor


def resumir(g: Guardian, lista: list[dict], limites: dict | None = None, planes: dict | None = None, pendientes: dict | None = None,
            hoy: date | None = None, plazo_s: float = 2.5) -> dict:
    """{'resumen': {nombre: {...}}, 'parcial': bool}. `lista`: salida de `listar_proyectos`; `planes`: proyecto en minúsculas -> plan
    enriquecido; `pendientes`: proyecto en minúsculas -> nº de pendientes abiertos (None = no se pudo leer el backlog a tiempo: el campo se
    omite). Un proyecto que no termina en `plazo_s` sale sin descripcion/sesiones/calidad."""
    limites = limites or {}
    planes = planes or {}
    ahora = datetime.now() if hoy is None else datetime.combine(hoy, datetime.min.time())
    hoy = ahora.date()
    futuros = {}
    for p in lista:
        try:
            futuros[p["nombre"]] = _POOL.submit(_de_cache, g, p["nombre"], p["ruta"], bool(p.get("compartido")), limites, ahora)
        except RuntimeError:
            break
    fin = time.monotonic() + plazo_s
    out: dict[str, dict] = {}
    parcial = len(futuros) < len(lista)
    for p in lista:
        nombre = p["nombre"]
        r: dict = {}
        fut = futuros.get(nombre)
        if fut is not None:
            try:
                v = fut.result(timeout=max(0.0, fin - time.monotonic()))
                r.update(descripcion=v["descripcion"], sesiones_por_semana=sesiones_por_semana(v["fechas"], hoy), calidad_contexto=v["calidad"])
            except Exception:  # noqa: BLE001 — tiempo agotado o carpeta ilegible: se omite, nunca bloquea
                parcial = True
        if pendientes is not None:
            r["pendientes_abiertos"] = int(pendientes.get(nombre.lower(), 0))
        hito = proximo_hito(planes.get(nombre.lower()) or p.get("plan"))
        if hito:
            r["proximo_hito"] = hito
        out[nombre] = r
    return {"resumen": out, "parcial": parcial}
