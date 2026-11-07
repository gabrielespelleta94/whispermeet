"""Plantillas de reunión (ola 4): descubrimiento, diseño funcional, seguimiento y comité.

Cada plantilla trae objetivos, el reparto de los perfiles del equipo (peso 0, 1 o 2: cuánto puntúa cada perfil en el Monitor; 0 = no habla) y el ritmo (cadencia y
ajustes del Monitor). Las cuatro de base viven AQUÍ, versionadas en el repo (con ejemplos genéricos, sin clientes ni personas); el usuario añade las suyas en
`plantillas-usuario.json` de la carpeta local de datos (solo vía Guardian). Todo local: aplicar una plantilla no llama al modelo.
"""
from __future__ import annotations

import json
import re
import threading

from .rutas import RutaProhibida, slug

VERSION = 1
FICHERO_USUARIO = "plantillas-usuario.json"
PERFILES = ("coordinador", "funcional", "constructor", "revisor", "estratega")
CADENCIAS = ("equipo", "5", "10", "manual")
AJUSTES_PERMITIDOS = ("equipo_puntuacion_min", "equipo_enfriamiento_global_s", "equipo_enfriamiento_perfil_s", "equipo_rotacion_s",
                      "equipo_palabras_min", "equipo_rotacion_palabras", "equipo_objetivo_sin_tratar_min", "equipo_toque_repetido_s")
MAX_OBJETIVOS = 12
MAX_USUARIO = 30


def _perfiles(coordinador: int, funcional: int, constructor: int, revisor: int, estratega: int, focos: dict | None = None) -> dict:
    focos = focos or {}
    return {p: {"peso": w, "foco": focos.get(p, "")} for p, w in zip(PERFILES, (coordinador, funcional, constructor, revisor, estratega))}


BASE: list[dict] = [
    {"id": "descubrimiento", "nombre": "Descubrimiento", "version": VERSION, "origen": "base",
     "descripcion": "Primera conversación con un cliente o iniciativa: entender qué necesita y si hay encaje.",
     "objetivos": ["Entender la necesidad y el problema que quiere resolver",
                   "Conocer el presupuesto disponible o el rango que manejan",
                   "Acordar el plazo y los hitos que importan",
                   "Identificar quién decide y cómo se decide",
                   "Conocer la competencia y las alternativas que consideran"],
     "perfiles": _perfiles(1, 2, 0, 1, 2, {"funcional": "la necesidad y el alcance deseado", "estratega": "presupuesto, plazo, decisor y competencia",
                                           "coordinador": "próximos pasos y quién se lleva cada uno"}),
     "ritmo": {"cadencia": "equipo", "duracion_min": 45, "ajustes": {"equipo_enfriamiento_global_s": 200, "equipo_objetivo_sin_tratar_min": 10}}},
    {"id": "diseno-funcional", "nombre": "Diseño funcional", "version": VERSION, "origen": "base",
     "descripcion": "Sesión de trabajo para fijar reglas, datos e integraciones de una funcionalidad.",
     "objetivos": ["Cerrar las reglas de negocio de la funcionalidad",
                   "Acordar el flujo del proceso de principio a fin",
                   "Definir los datos y sus orígenes",
                   "Identificar las integraciones y los sistemas implicados",
                   "Recoger los casos límite y los criterios de aceptación"],
     "perfiles": _perfiles(1, 2, 2, 2, 0, {"funcional": "reglas, definiciones y alcance", "constructor": "datos, integraciones y cifras",
                                           "revisor": "contradicciones con lo ya acordado"}),
     "ritmo": {"cadencia": "equipo", "duracion_min": 90, "ajustes": {"equipo_enfriamiento_global_s": 180, "equipo_enfriamiento_perfil_s": 300}}},
    {"id": "seguimiento", "nombre": "Seguimiento", "version": VERSION, "origen": "base",
     "descripcion": "Reunión periódica de proyecto: avances, bloqueos y próximos pasos.",
     "objetivos": ["Repasar los pendientes de la sesión anterior",
                   "Conocer los avances y los bloqueos",
                   "Detectar riesgos nuevos",
                   "Tomar las decisiones que están pendientes",
                   "Dejar los próximos pasos con responsable y fecha"],
     "perfiles": _perfiles(2, 1, 1, 1, 0, {"coordinador": "pendientes, responsables y fechas", "revisor": "qué objetivos no se han tratado"}),
     "ritmo": {"cadencia": "equipo", "duracion_min": 30, "ajustes": {"equipo_enfriamiento_global_s": 240, "equipo_objetivo_sin_tratar_min": 8}}},
    {"id": "comite", "nombre": "Comité", "version": VERSION, "origen": "base",
     "descripcion": "Comité de seguimiento o de dirección: estado, riesgos y decisiones que necesitan al comité.",
     "objetivos": ["Presentar el estado general: hitos, presupuesto y plazo",
                   "Exponer los riesgos y lo que necesita escalarse",
                   "Obtener las decisiones y aprobaciones del comité",
                   "Dejar los acuerdos con responsable y fecha",
                   "Fijar la próxima convocatoria"],
     "perfiles": _perfiles(2, 0, 0, 2, 1, {"coordinador": "acuerdos, responsables y fechas", "revisor": "decisiones que faltan", "estratega": "riesgos y oportunidades a escalar"}),
     "ritmo": {"cadencia": "equipo", "duracion_min": 60, "ajustes": {"equipo_enfriamiento_global_s": 300, "equipo_enfriamiento_perfil_s": 420}}},
]


# ------------------------------------------------------------------ validación (las del usuario llegan de fuera)
def _txt(v, maximo: int) -> str:
    return " ".join(str(v or "").split())[:maximo]


def normalizar(crudo, origen: str = "usuario") -> dict:
    """Plantilla válida a partir de lo que llegue. ValueError con un mensaje claro si no se puede."""
    if not isinstance(crudo, dict):
        raise ValueError("La plantilla debe ser un objeto.")
    nombre = _txt(crudo.get("nombre"), 60)
    if not nombre:
        raise ValueError("La plantilla necesita un nombre.")
    ident = re.sub(r"[^a-z0-9\-]", "", slug(crudo.get("id") or nombre, 40)) or "plantilla"
    objetivos = [_txt(o, 200) for o in (crudo.get("objetivos") or []) if isinstance(o, str) and _txt(o, 200)][:MAX_OBJETIVOS]
    if not objetivos:
        raise ValueError("La plantilla necesita al menos un objetivo.")
    perfiles = {}
    crudo_p = crudo.get("perfiles") if isinstance(crudo.get("perfiles"), dict) else {}
    for p in PERFILES:
        v = crudo_p.get(p) if isinstance(crudo_p.get(p), dict) else {}
        peso = v.get("peso", 1)
        if isinstance(peso, bool) or not isinstance(peso, int) or not 0 <= peso <= 2:
            raise ValueError(f"El peso de «{p}» debe ser 0, 1 o 2.")
        perfiles[p] = {"peso": peso, "foco": _txt(v.get("foco"), 120)}
    r = crudo.get("ritmo") if isinstance(crudo.get("ritmo"), dict) else {}
    cadencia = str(r.get("cadencia", "equipo"))
    if cadencia not in CADENCIAS:
        raise ValueError("La cadencia debe ser equipo, 5, 10 o manual.")
    dur = r.get("duracion_min", 60)
    if isinstance(dur, bool) or not isinstance(dur, int) or not 5 <= dur <= 480:
        raise ValueError("La duración prevista debe estar entre 5 y 480 minutos.")
    ajustes = {}
    for k, v in (r.get("ajustes") or {}).items():
        if k not in AJUSTES_PERMITIDOS:
            raise ValueError(f"El ajuste «{k}» no se puede cambiar en una plantilla.")
        if isinstance(v, bool) or not isinstance(v, int) or v < 0:
            raise ValueError(f"El ajuste «{k}» debe ser un número entero no negativo.")
        ajustes[k] = v
    return {"id": ident, "nombre": nombre, "version": int(crudo.get("version") or 1), "origen": origen, "descripcion": _txt(crudo.get("descripcion"), 200),
            "objetivos": objetivos, "perfiles": perfiles, "ritmo": {"cadencia": cadencia, "duracion_min": dur, "ajustes": ajustes}}


class Plantillas:
    def __init__(self, guardian):
        self.g = guardian
        self._lock = threading.Lock()

    def _usuario(self) -> list[dict]:
        try:
            crudo = json.loads(self.g.leer_datos(FICHERO_USUARIO) or "[]")
        except (ValueError, RutaProhibida):
            return []
        out = []
        for c in crudo if isinstance(crudo, list) else []:
            try:
                out.append(normalizar(c))
            except ValueError:
                continue   # una plantilla rota del usuario no tumba la lista
        return out

    def listar(self) -> list[dict]:
        base = [json.loads(json.dumps(p)) for p in BASE]
        ids = {p["id"] for p in base}
        return base + [p for p in self._usuario() if p["id"] not in ids]

    def obtener(self, ident: str) -> dict | None:
        return next((p for p in self.listar() if p["id"] == ident), None)

    def anadir(self, crudo) -> dict:
        p = normalizar(crudo)
        if p["id"] in {b["id"] for b in BASE}:
            raise ValueError("Ese identificador es de una plantilla de base; elige otro nombre.")
        if not self.g.hay_datos():
            raise ValueError("No hay carpeta local de datos donde guardar la plantilla.")
        with self._lock:
            actuales = [x for x in self._usuario() if x["id"] != p["id"]]
            if len(actuales) >= MAX_USUARIO:
                raise ValueError("Hay demasiadas plantillas propias; borra alguna.")
            self.g.escribir_datos(FICHERO_USUARIO, json.dumps(actuales + [p], ensure_ascii=False, indent=2))
        return p

    def borrar(self, ident: str) -> bool:
        with self._lock:
            actuales = self._usuario()
            nuevas = [x for x in actuales if x["id"] != ident]
            if len(nuevas) == len(actuales):
                return False
            self.g.escribir_datos(FICHERO_USUARIO, json.dumps(nuevas, ensure_ascii=False, indent=2))
            return True


def pesos_de(plantilla: dict) -> dict[str, int]:
    return {p: int(v["peso"]) for p, v in plantilla["perfiles"].items()}
