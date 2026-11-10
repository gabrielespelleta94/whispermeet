"""Mapa de documentos del proyecto: qué documentación tiene, clasificada por tipo, el último de cada tipo y qué tipos faltan.
Local, determinista y explicable (cada clasificación lleva su motivo). Solo `stat` vía `Guardian.ficheros_del_proyecto`: NUNCA abre ni lee un fichero del proyecto
(así no descarga lo que OneDrive guarda solo en la nube y no gasta tokens). Sin modelos de IA."""
from __future__ import annotations

import json
import os
import re
import threading
import time

from .rutas import CARPETA_CONTEXTO, CARPETA_SESIONES, EXT_ABRIBLES, EXT_DOCUMENTO, RutaProhibida, nombre_normalizado, sin_acentos  # noqa: F401  (EXT_* se reexportan)

TIPOS: list[dict] = [
    {"clave": "arranque", "titulo": "Arranque (kick-off)", "esperado": True, "pista": "Presentación o acta de la reunión de arranque."},
    {"clave": "oferta", "titulo": "Oferta y alcance", "esperado": True, "pista": "Oferta, propuesta, contrato o documento de alcance."},
    {"clave": "funcional", "titulo": "Funcional", "esperado": True, "pista": "Diseño funcional, requisitos o procesos."},
    {"clave": "tecnico", "titulo": "Técnico", "esperado": True, "pista": "Diseño técnico, arquitectura o integraciones."},
    {"clave": "datos", "titulo": "Modelo de datos", "esperado": True, "pista": "Modelo de datos, diccionario de datos o esquema de tablas."},
    {"clave": "usuarios", "titulo": "Usuarios y roles", "esperado": True, "pista": "Matriz de usuarios, roles y permisos, o interlocutores."},
    {"clave": "planificacion", "titulo": "Planificación", "esperado": True, "pista": "Plan de proyecto, cronograma o calendario de sesiones."},
    {"clave": "seguimiento", "titulo": "Seguimiento y actas", "esperado": True, "pista": "Actas, informes de seguimiento o sesiones grabadas con la app."},
    {"clave": "pruebas", "titulo": "Pruebas y formación", "esperado": False, "pista": ""},
    {"clave": "contexto", "titulo": "Contexto para la IA", "esperado": False, "pista": ""},
    {"clave": "otros", "titulo": "Sin clasificar", "esperado": False, "pista": ""},
]

# Reglas por nombre, EN ORDEN: gana la primera que casa. Se aplican al texto normalizado (sin acentos, minúsculas, separadores = espacio).
# (tipo, patrón, etiqueta legible). Las frases específicas van antes que las palabras sueltas; `arranque` y `pruebas` ganan a casi todo.
_REGLAS_CRUDAS: list[tuple[str, str, str]] = [
    ("arranque", r"kick ?off", "kick-off"),
    ("arranque", r"ko", "KO"),
    ("arranque", r"reuniones? de arranque|arranque|start ?up meeting", "arranque"),
    ("arranque", r"lanzamiento", "lanzamiento"),
    ("arranque", r"inicio (?:de(?:l)? )?proyecto", "inicio del proyecto"),
    ("tecnico", r"manual (?:tecnico|de instalacion|de despliegue)", "manual técnico"),
    ("pruebas", r"plan(?:es)? de pruebas?|test plan", "plan de pruebas"),
    ("pruebas", r"casos? de pruebas?|test cases?", "casos de prueba"),
    ("pruebas", r"manual de usuarios?|guias? de usuarios?|user guide|user manual", "manual o guía de usuario"),
    ("pruebas", r"uat", "UAT"),
    ("pruebas", r"formacion|capacitacion|training", "formación"),
    ("pruebas", r"pruebas?", "pruebas"),
    ("pruebas", r"tests?|testing", "test"),
    ("pruebas", r"manuales?", "manual"),
    ("funcional", r"historias? de usuarios?|user stor(?:y|ies)", "historias de usuario"),
    ("funcional", r"casos? de uso|use cases?", "casos de uso"),
    ("datos", r"modelos? de datos|modelos? datos|data model", "modelo de datos"),
    ("datos", r"diccionarios? de datos|data dictionary", "diccionario de datos"),
    ("datos", r"entidad ?relacion|erd", "entidad-relación"),
    ("datos", r"esquemas? (?:de )?(?:la )?bases? (?:de )?datos|bases? de datos", "base de datos"),
    ("datos", r"esquemas?|schema", "esquema"),
    ("datos", r"tablas?|ddl", "tablas"),
    ("datos", r"catalogo de datos|linaje|(?:mapeo|mapping) de datos", "catálogo o linaje de datos"),
    ("usuarios", r"usuarios y roles|matriz de (?:roles|usuarios|permisos)|users and roles", "usuarios y roles"),
    ("usuarios", r"roles?", "roles"),
    ("usuarios", r"perfiles|permisos", "perfiles o permisos"),
    ("usuarios", r"usuarios", "usuarios"),
    ("usuarios", r"stakeholders?|interlocutores|organigrama|raci|contactos?", "interlocutores"),
    ("usuarios", r"equipo (?:de|del) proyecto", "equipo del proyecto"),
    ("planificacion", r"plan(?:es)? (?:de|del) (?:proyecto|trabajo|sesiones|entregas|implantacion)|project plan", "plan de proyecto"),
    ("planificacion", r"planificacion|planning|cronograma|calendario|gantt|roadmap|hoja de ruta|timeline|hitos|agenda", "planificación"),
    ("oferta", r"ofertas?|propuestas?|alcance|sow|statement of work|contratos?|pliegos?|rfp|presupuestos?", "oferta o alcance"),
    ("funcional", r"diseno funcional|analisis funcional|especificacion(?:es)? funcional(?:es)?", "diseño funcional"),
    ("funcional", r"funcional(?:es)?|requisitos?|requerimientos?|requirements?|blueprint|bbp|procesos?|as is|to be", "funcional"),
    ("tecnico", r"diseno tecnico|tecnic[oa]s?", "técnico"),
    ("tecnico", r"arquitectura|integracion(?:es)?|interfaz|interfaces|apis?|infraestructura|despliegues?|deploy(?:ment)?|seguridad|instalacion|configuracion",
     "arquitectura o integración"),
    ("seguimiento", r"actas?|minutas?|seguimientos?|status|estado (?:del |de )?proyecto|informes? de avances?|avances?", "acta o seguimiento"),
    ("seguimiento", r"comites?|steering|steerco|weekly|semanal(?:es)?|reuniones?|sesion(?:es)?|notas", "reunión o sesión"),
]
REGLAS = [(t, re.compile(r"(?<![a-z0-9])(?:" + p + r")(?![a-z0-9])"), etiqueta) for t, p, etiqueta in _REGLAS_CRUDAS]
_EXT_TIPO = {".sql": "datos", ".dbml": "datos", ".mpp": "planificacion"}


def _normalizar(texto: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", sin_acentos(texto).lower()).strip()


def _por_reglas(texto: str) -> tuple[str, str] | None:
    n = _normalizar(texto)
    for tipo, patron, etiqueta in REGLAS:
        if patron.search(n):
            return tipo, etiqueta
    return None


def clasificar(rel: str) -> tuple[str, str]:
    """`(clave_tipo, motivo)` de una ruta relativa al proyecto (posix): carpetas de la app, luego nombre, luego carpetas contenedoras (la más cercana primero), luego extensión."""
    partes = [x for x in (rel or "").replace("\\", "/").split("/") if x]
    if not partes:
        return "otros", "sin pista en el nombre ni en la carpeta"
    carpetas, nombre = partes[:-1], partes[-1]
    if carpetas and carpetas[0].lower() == CARPETA_CONTEXTO.lower():
        return "contexto", "carpeta de contexto para la IA"
    if carpetas and carpetas[0].lower() == CARPETA_SESIONES.lower():
        return "seguimiento", "sesión grabada con la app"
    stem, ext = os.path.splitext(nombre)
    r = _por_reglas(stem)
    if r:
        return r[0], f"nombre: «{r[1]}»"
    for c in reversed(carpetas):
        r = _por_reglas(c)
        if r:
            return r[0], f"carpeta: «{c}»"
    if ext.lower() in _EXT_TIPO:
        return _EXT_TIPO[ext.lower()], f"extensión {ext.lower()}"
    return "otros", "sin pista en el nombre ni en la carpeta"


CLAVES_TIPO = frozenset(t["clave"] for t in TIPOS)
MAX_CORRECCIONES = 2000
_lock_correcciones = threading.Lock()


def leer_correcciones(guardian, proyecto: str) -> dict[str, str]:
    """`{rel: tipo}` de los tipos que el usuario ha corregido a mano en este proyecto (almacén local `Guardian.leer_tipos`). Nunca lanza: sin carpeta
    configurada, sin fichero o con un JSON roto devuelve `{}`; las claves de tipo desconocidas se ignoran."""
    try:
        crudo = guardian.leer_tipos(proyecto)
        d = json.loads(crudo) if crudo else {}
    except (OSError, ValueError, RutaProhibida):
        return {}
    if not isinstance(d, dict) or not isinstance(d.get("proyecto"), str) or nombre_normalizado(d["proyecto"]) != nombre_normalizado(proyecto):
        return {}   # el fichero lleva el nombre del proyecto al que pertenece: si no coincide, no es de este
    tipos = d.get("tipos")
    if not isinstance(tipos, dict):
        return {}
    return {str(k): v for k, v in tipos.items() if isinstance(v, str) and v in CLAVES_TIPO and str(k).strip()}


def fijar_correccion(guardian, proyecto: str, rel: str, tipo: str | None) -> dict[str, str]:
    """Fija (o, con `tipo` vacío o None, quita) el tipo de un documento. `ValueError` si el tipo no existe. Devuelve las correcciones del proyecto. Solo
    toca el almacén local del Guardian; los documentos del proyecto no se tocan nunca."""
    tipo = (tipo or "").strip() or None
    if tipo is not None and tipo not in CLAVES_TIPO:
        raise ValueError("Ese tipo de documento no existe.")
    rel = (rel or "").strip()
    if not rel:
        raise ValueError("Falta el documento.")
    with _lock_correcciones:
        actuales = leer_correcciones(guardian, proyecto)
        if tipo is None:
            actuales.pop(rel, None)
        else:
            if rel not in actuales and len(actuales) >= MAX_CORRECCIONES:
                raise ValueError("Hay demasiados tipos corregidos a mano en este proyecto.")
            actuales[rel] = tipo
        guardian.escribir_tipos(proyecto, json.dumps({"version": 1, "proyecto": proyecto, "tipos": actuales}, ensure_ascii=False, indent=1, sort_keys=True))
        return actuales


def mapa(guardian, proyecto: str, ahora: float | None = None, max_por_tipo: int = 200, correcciones: dict[str, str] | None = None) -> dict:
    """Inventario clasificado de los documentos del proyecto (ver el módulo). Deja salir `RutaProhibida` si el proyecto no existe. `correcciones`:
    `{rel: tipo}` de lo que el usuario ha corregido a mano (`leer_correcciones`); un fichero corregido cae en su tipo con motivo «corregido a mano» y
    `corregido: True`, por encima de cualquier regla."""
    correcciones = correcciones or {}
    ahora = time.time() if ahora is None else ahora
    r = guardian.ficheros_del_proyecto(proyecto)
    grupos: dict[str, list[dict]] = {t["clave"]: [] for t in TIPOS}
    ignorados = en_nube = total = 0
    for f in r["ficheros"]:
        if f["ext"] not in EXT_DOCUMENTO:
            ignorados += 1
            continue
        clave, motivo = clasificar(f["rel"])
        corregido = correcciones.get(f["rel"]) in CLAVES_TIPO
        if corregido:
            clave, motivo = correcciones[f["rel"]], "corregido a mano"
        total += 1
        en_nube += 1 if f["nube"] else 0
        grupos[clave].append({"ruta": f["ruta"], "rel": f["rel"], "nombre": f["nombre"], "ext": f["ext"], "carpeta": f["rel"].rpartition("/")[0],
                              "tam": f["tam"], "mtime": f["mtime"], "nube": f["nube"], "motivo": motivo, "corregido": corregido})
    tipos = []
    for t in TIPOS:
        lista = sorted(grupos[t["clave"]], key=lambda x: (-x["mtime"], x["rel"].lower()))
        ultimo = lista[0] if lista else None
        tipos.append({"clave": t["clave"], "titulo": t["titulo"], "esperado": t["esperado"], "n": len(lista),
                      "dias": max(0, int((ahora - ultimo["mtime"]) // 86400)) if ultimo else None,
                      "ultimo": {"nombre": ultimo["nombre"], "rel": ultimo["rel"], "mtime": ultimo["mtime"]} if ultimo else None,
                      "ficheros": lista[:max_por_tipo], "mas": max(0, len(lista) - max_por_tipo)})
    faltan = [{"clave": t["clave"], "titulo": t["titulo"], "pista": t["pista"]} for t, x in zip(TIPOS, tipos) if t["esperado"] and x["n"] == 0]
    return {"proyecto": proyecto, "total": total, "ignorados": ignorados, "en_nube": en_nube, "truncado": r["truncado"], "tipos": tipos, "faltan": faltan}
