"""Editor del plan de sesiones (ola C de `HOJA-DE-RUTA.md`): leer el plan editable, validarlo y guardarlo SIN perder lo que el editor no conoce.

Reglas que no se rompen:
- El plan solo se escribe desde aquí, por acción explícita del usuario (`PUT /api/proyectos/{n}/plan`) y SIEMPRE a través de `Guardian.escribir_plan` (atómico,
  confinado a la carpeta `planes`, con copia `.bak` del anterior). Un plan que ya existe se localiza por el proyecto que declara DENTRO (no por el nombre del
  fichero); si dos ficheros declaran el mismo proyecto no se adivina cuál: error claro y no se escribe. El plan nuevo va a `plan-<hash>.json` (`Guardian.nombre_fichero_plan`).
- Se parte del JSON CRUDO y se aplican solo los cambios: `ficha`, `gantt`, los campos de cada sesión que el editor no toca (`participantes`…) y cualquier clave
  desconocida se conservan tal cual. Nunca se escribe la versión normalizada: un campo que el usuario no ha cambiado (el valor recibido es el normalizado que enseñó la
  app) se deja EXACTAMENTE como estaba en el fichero, aunque esté escrito a mano de otra forma. Las sesiones crudas que la app no enseña (sin id, id repetido o no válido,
  sin nombre, por encima del máximo) se conservan tal cual al final de la lista.
- Validación con las mismas reglas de `planes.normalizar_plan` (ids, topes, formato de fecha y de hora, fichero prioritario) más las que `normalizar_plan` descarta en
  silencio y aquí son error (dependencias que no existen, ciclos, textos demasiado largos, duplicados): error por campo y nada se escribe a medias.
- Los ids de sesión los genera la app (`S<n>`, estables: una sesión conserva su id aunque cambie de nombre o de orden) y no se reutilizan nunca (`siguiente_id` dentro del JSON).
- Control de concurrencia: `version` es un hash del contenido del fichero (o «nuevo» si no había plan) y el `PUT` debe traer la que recibió; si no coincide, `ConflictoPlan`.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import date

from . import planes as PL
from .rutas import TOPE_PLAN_BYTES, Guardian, RutaProhibida

VERSION_NUEVO = "nuevo"
CAMPOS_EDITABLES = ("nombre", "fecha", "fecha_iso", "hora", "objetivos", "checks", "fichero_prioritario", "depende_de")
MAX_DEPENDENCIAS = 6
MAX_NOMBRE, MAX_FECHA, MAX_OBJETIVO, MAX_CHECK = 120, 80, 200, 140
_RE_ID_S = re.compile(r"^[Ss](\d+)$")


class PlanInvalido(Exception):
    """Errores de validación por campo: `errores` = [{indice, campo, mensaje}] (`indice` None = error del plan entero)."""

    def __init__(self, errores: list[dict]):
        super().__init__(errores[0]["mensaje"] if errores else "El plan no es válido.")
        self.errores = errores


class ConflictoPlan(Exception):
    """El fichero del plan cambió fuera de la app desde que el cliente lo leyó."""

    def __init__(self):
        super().__init__("El plan ha cambiado fuera de la app desde que lo abriste. Recarga para ver la versión actual; no se ha guardado nada.")


class PlanAmbiguo(ValueError):
    pass


def version_de(datos: bytes | None) -> str:
    return VERSION_NUEVO if datos is None else hashlib.sha256(datos).hexdigest()[:16]


def _limpio(v) -> str:
    return " ".join(str(v if v is not None else "").split())


def localizar(g: Guardian, proyecto: str) -> tuple[str | None, bytes | None]:
    """(fichero, bytes) del plan que declara este proyecto, o (None, None). Dos ficheros que lo declaran = `PlanAmbiguo` (el editor no adivina)."""
    ficheros = g.planes_de(proyecto)
    if len(ficheros) > 1:
        raise PlanAmbiguo(f"Hay {len(ficheros)} ficheros en la carpeta de planes que declaran el proyecto «{proyecto}»: el editor no sabe cuál es el bueno. "
                          "Deja uno solo (o cambia el nombre del proyecto dentro del otro) y recarga.")
    return ficheros[0] if ficheros else (None, None)


def _crudo(datos: bytes | None) -> dict | None:
    if datos is None:
        return None
    try:
        d = json.loads(datos.decode("utf-8-sig", errors="replace"))
    except ValueError:
        return None
    return d if isinstance(d, dict) else None


def _partir(crudo: dict | None) -> tuple[dict[str, dict], list, set[str]]:
    """Las sesiones crudas tal como las reparte `normalizar_plan`: (visibles, descartadas, ids). `visibles`: id (minúsculas) -> sesión cruda de las que la app enseña;
    `descartadas`: las entradas crudas que NO enseña (sin id válido, id repetido, sin nombre, por encima del máximo, o que ni son un objeto), en su orden original;
    `ids`: todos los ids que aparecen en el crudo, también los de las descartadas (los ids nuevos no pueden chocar con ninguno)."""
    lista = (crudo or {}).get("sesiones")
    if not isinstance(lista, list):
        return {}, [], set()
    norm = {s["id"].lower() for s in (PL.normalizar_plan(crudo) or {}).get("sesiones", [])}
    visibles: dict[str, dict] = {}
    descartadas: list = []
    ids: set[str] = set()
    for i, s in enumerate(lista):
        sid = str(s.get("id") or "").strip() if isinstance(s, dict) else ""
        if sid:
            ids.add(sid.lower())
        if i < PL.MAX_SESIONES and isinstance(s, dict) and PL._RE_ID.match(sid) and sid.lower() in norm and sid.lower() not in visibles:
            visibles[sid.lower()] = s
        else:
            descartadas.append(s)
    return visibles, descartadas, ids


def _editable(s: dict, ids: set[str]) -> dict:
    """Una sesión normalizada tal como la edita la interfaz. Las dependencias que apuntan a un id que no existe (o a ella misma) no se enseñan: no hay casilla para quitarlas."""
    return {"id": s["id"], "nombre": s["nombre"], "fecha": s["fecha"], "fecha_iso": s["fecha_iso"], "hora": s["hora"], "participantes": s["participantes"],
            "objetivos": list(s["objetivos"]), "checks": list(s["checks"]), "fichero_prioritario": s["fichero_prioritario"],
            "depende_de": [d for d in s["depende_de"] if d.lower() in ids and d.lower() != s["id"].lower()]}


def _mostradas(crudo: dict | None) -> dict[str, dict]:
    """id (minúsculas) -> la sesión tal como la enseña el editor (normalizada), recalculada del crudo actual con la misma función que usa `leer`."""
    norm = PL.normalizar_plan(crudo) if crudo is not None else None
    if not norm:
        return {}
    ids = {s["id"].lower() for s in norm["sesiones"]}
    return {s["id"].lower(): _editable(s, ids) for s in norm["sesiones"]}


def limites() -> dict:
    return {"max_sesiones": PL.MAX_SESIONES, "max_objetivos": PL.MAX_OBJETIVOS, "max_checks": PL.MAX_CHECKS_BASE, "max_dependencias": MAX_DEPENDENCIAS,
            "max_nombre": MAX_NOMBRE, "max_fecha": MAX_FECHA, "max_objetivo": MAX_OBJETIVO, "max_check": MAX_CHECK}


def leer(g: Guardian, proyecto: str) -> dict:
    """El plan editable del proyecto (o `plan: null`), la marca de versión y los ficheros de `00. CONTEXTO (IA)` que valen como fichero prioritario. `descartadas`: sesiones
    crudas del fichero que la app no enseña (se conservan al guardar; se cuentan también cuando no hay ninguna válida). `ilegibles`: nombres (máximo 5) de los `.json` de
    la carpeta de planes que no se pueden leer (de ellos no se sabe de qué proyecto son), con `ilegibles_total`."""
    g.proyecto_dir(proyecto)   # el proyecto debe existir
    _fichero, datos = localizar(g, proyecto)
    crudo = _crudo(datos)
    plan = PL.normalizar_plan(crudo) if crudo is not None else None
    _visibles, descartadas, _ids = _partir(crudo)
    if plan is not None:
        ids = {s["id"].lower() for s in plan["sesiones"]}
        plan = {"sesiones": [_editable(s, ids) for s in plan["sesiones"]], "con_gantt": "gantt" in plan, "con_ficha": "ficha" in plan}
    ilegibles = g.planes_ilegibles()
    return {"proyecto": proyecto, "plan": plan, "version": version_de(datos), "descartadas": len(descartadas),
            "ilegibles": ilegibles[:5], "ilegibles_total": len(ilegibles),
            "ficheros_contexto": g.nombres_contexto(proyecto), "limites": limites()}


# ------------------------------------------------------------------ validación
def _hay_ciclo(deps: dict[str, list[str]]) -> list[str] | None:
    """Un ciclo de dependencias (lista de ids) o None."""
    estado: dict[str, int] = {}
    pila: list[str] = []

    def visita(n: str) -> list[str] | None:
        estado[n] = 1
        pila.append(n)
        for m in deps.get(n, []):
            if estado.get(m, 0) == 1:
                return pila[pila.index(m):] + [m]
            if estado.get(m, 0) == 0:
                c = visita(m)
                if c:
                    return c
        pila.pop()
        estado[n] = 2
        return None

    for n in deps:
        if estado.get(n, 0) == 0:
            c = visita(n)
            if c:
                return c
    return None


def _id_nuevo(usados: set[str], contador: int) -> tuple[str, int]:
    while f"s{contador}" in usados:
        contador += 1
    return f"S{contador}", contador + 1


def construir(sesiones: list[dict], crudo: dict | None, proyecto: str) -> tuple[dict, list[dict]]:
    """Valida `sesiones` (lo que manda la interfaz) y devuelve `(plan_crudo, sesiones_finales)`: el JSON a escribir (el crudo original con los cambios; los ids nuevos ya
    asignados) y las sesiones finales. Lanza `PlanInvalido`. No toca el disco.

    Por cada sesión que ya existía y por cada campo editable se compara lo recibido con el valor NORMALIZADO que la app enseñó (`_mostradas`): si es igual, el campo crudo
    se deja como estaba (no se valida ni se reescribe); solo si difiere se valida y se escribe. Las sesiones crudas que la app no enseña se conservan al final."""
    errores: list[dict] = []

    def err(i, campo, msg):
        errores.append({"indice": i, "campo": campo, "mensaje": msg})

    if not isinstance(sesiones, list) or not sesiones:
        raise PlanInvalido([{"indice": None, "campo": "sesiones", "mensaje": "El plan necesita al menos una sesión."}])
    if len(sesiones) > PL.MAX_SESIONES:
        raise PlanInvalido([{"indice": None, "campo": "sesiones", "mensaje": f"Un plan admite como máximo {PL.MAX_SESIONES} sesiones."}])
    originales, descartadas, ids_crudo = _partir(crudo)
    mostradas = _mostradas(crudo)
    usados = set(ids_crudo)
    sig = (crudo or {}).get("siguiente_id")
    contador = max([1, sig if isinstance(sig, int) and not isinstance(sig, bool) else 1] + [int(m.group(1)) + 1 for m in (_RE_ID_S.match(k) for k in usados) if m])
    # 1) ids: los que ya existían se conservan; el resto se genera aquí (el id que traiga el cliente solo sirve para enlazar dependencias entre sesiones nuevas)
    finales: dict[str, str] = {}     # id del cliente (minúsculas) -> id final
    ids_final: list[str] = []
    for i, s in enumerate(sesiones):
        if not isinstance(s, dict):
            err(i, "id", "La sesión no tiene la forma esperada.")
            ids_final.append("")
            continue
        cid = _limpio(s.get("id")).lower()
        if cid in originales:
            final = str(originales[cid].get("id")).strip()
        else:
            final, contador = _id_nuevo(usados, contador)
            usados.add(final.lower())
        if cid and cid in finales:
            err(i, "id", "Esta sesión está repetida.")
        elif cid:
            finales[cid] = final
        ids_final.append(final)
    conocidos = {x.lower() for x in ids_final if x}
    cuentan = [_limpio(s.get("nombre")).lower() if isinstance(s, dict) else "" for s in sesiones]
    out: list[dict] = []
    cambiados: list[set[str]] = []     # campos que el usuario ha cambiado (en una sesión nueva, todos)
    for i, s in enumerate(sesiones):
        if not isinstance(s, dict):
            out.append({})
            cambiados.append(set())
            continue
        previa = mostradas.get(ids_final[i].lower()) if _limpio(s.get("id")).lower() in originales else None
        if previa is None:
            cambia = set(CAMPOS_EDITABLES)
        else:
            cambia = set()
            for campo in ("nombre", "fecha", "fecha_iso", "hora", "fichero_prioritario"):
                if _limpio(s.get(campo)) != previa[campo]:
                    cambia.add(campo)
            for campo in ("objetivos", "checks"):
                if [_limpio(x) for x in (s.get(campo) or []) if _limpio(x)] != previa[campo]:
                    cambia.add(campo)
            if [_limpio(d).lower() for d in (s.get("depende_de") or []) if _limpio(d)] != [d.lower() for d in previa["depende_de"]]:
                cambia.add("depende_de")
        valor = {k: (previa[k] if previa is not None else None) for k in CAMPOS_EDITABLES}
        nombre = _limpio(s.get("nombre"))
        if "nombre" in cambia:
            if not nombre:
                err(i, "nombre", "La sesión necesita un nombre.")
            elif len(nombre) > MAX_NOMBRE:
                err(i, "nombre", f"El nombre es demasiado largo (máximo {MAX_NOMBRE} caracteres).")
            elif nombre and cuentan.count(nombre.lower()) > 1:
                err(i, "nombre", "Ya hay otra sesión con este nombre.")
            valor["nombre"] = nombre
        fecha_iso = _limpio(s.get("fecha_iso"))
        if "fecha_iso" in cambia:
            if fecha_iso:
                try:
                    if not PL._RE_ISO.match(fecha_iso):
                        raise ValueError
                    date.fromisoformat(fecha_iso)
                except ValueError:
                    err(i, "fecha_iso", "La fecha no es válida (usa el selector de fecha).")
                    fecha_iso = ""
            valor["fecha_iso"] = fecha_iso
        fecha = _limpio(s.get("fecha"))
        if "fecha" in cambia:
            if len(fecha) > MAX_FECHA:
                err(i, "fecha", f"El texto de la fecha es demasiado largo (máximo {MAX_FECHA} caracteres).")
            valor["fecha"] = fecha
        hora = _limpio(s.get("hora"))
        if "hora" in cambia:
            if hora and not PL._RE_HORA.match(hora):
                err(i, "hora", "La hora no es válida (usa HH:MM, por ejemplo 10:30).")
            valor["hora"] = hora
        if "objetivos" in cambia:
            objetivos = [_limpio(o) for o in (s.get("objetivos") or []) if _limpio(o)]
            if len(objetivos) > PL.MAX_OBJETIVOS:
                err(i, "objetivos", f"Una sesión admite como máximo {PL.MAX_OBJETIVOS} objetivos.")
            if any(len(o) > MAX_OBJETIVO for o in objetivos):
                err(i, "objetivos", f"Un objetivo es demasiado largo (máximo {MAX_OBJETIVO} caracteres).")
            valor["objetivos"] = objetivos
        if "checks" in cambia:
            checks = [_limpio(c) for c in (s.get("checks") or []) if _limpio(c)]
            if len(checks) > PL.MAX_CHECKS_BASE:
                err(i, "checks", f"Una sesión admite como máximo {PL.MAX_CHECKS_BASE} checks.")
            if any(len(c) > MAX_CHECK for c in checks):
                err(i, "checks", f"Un check es demasiado largo (máximo {MAX_CHECK} caracteres).")
            if len({c.lower() for c in checks}) != len(checks):
                err(i, "checks", "Hay checks repetidos.")
            valor["checks"] = checks
        if "fichero_prioritario" in cambia:
            prio = _limpio(s.get("fichero_prioritario"))
            if prio and not PL._RE_FICHERO.match(prio):
                err(i, "fichero_prioritario", "El fichero prioritario debe ser uno de «00. CONTEXTO (IA)» con el formato NN-nombre.md.")
            valor["fichero_prioritario"] = prio
        deps: list[str] = []
        for d in s.get("depende_de") or []:
            d = _limpio(d).lower()
            final = finales.get(d)
            if "depende_de" not in cambia:
                if final is not None and final.lower() in conocidos and final.lower() != ids_final[i].lower() and final not in deps:
                    deps.append(final)
                continue
            if final is None or final.lower() not in conocidos:
                err(i, "depende_de", "Depende de una sesión que no existe.")
            elif final.lower() == ids_final[i].lower():
                err(i, "depende_de", "Una sesión no puede depender de sí misma.")
            elif final not in deps:
                deps.append(final)
        if "depende_de" in cambia and len(deps) > MAX_DEPENDENCIAS:
            err(i, "depende_de", f"Una sesión admite como máximo {MAX_DEPENDENCIAS} dependencias.")
        valor["depende_de"] = deps
        out.append({"id": ids_final[i], **valor})
        cambiados.append(cambia)
    if not errores:
        ciclo = _hay_ciclo({s["id"]: s["depende_de"] for s in out})
        if ciclo:
            por_id = {s["id"]: i for i, s in enumerate(out)}
            nombres_c = " → ".join(out[por_id[c]]["nombre"] for c in ciclo)
            err(por_id[ciclo[0]], "depende_de", f"Las dependencias forman un ciclo: {nombres_c}.")
    if errores:
        raise PlanInvalido(errores)
    # 2) al JSON crudo: lo cambiado se sustituye; lo demás (ficha, gantt, claves desconocidas, campos de sesión que el editor no toca y los que el usuario no ha cambiado)
    #    se conserva tal cual, y las sesiones que la app no enseña van al final en su orden original
    base = json.loads(json.dumps(crudo)) if crudo is not None else {"proyecto": proyecto}
    nuevas = []
    for s, cambia in zip(out, cambiados):
        previa = originales.get(s["id"].lower())
        d = json.loads(json.dumps(previa)) if previa is not None else {"id": s["id"]}
        d.update({k: s[k] for k in CAMPOS_EDITABLES if k in cambia})
        nuevas.append(d)
    base["sesiones"] = nuevas + json.loads(json.dumps(descartadas))
    base["siguiente_id"] = contador
    # 3) red de seguridad: lo que se va a escribir tiene que ser un plan que `normalizar_plan` lea con estas sesiones primero y sin cambiar nada de lo que el usuario ha cambiado
    norm = PL.normalizar_plan(base)
    if norm is None or [x["id"] for x in norm["sesiones"]][:len(out)] != [s["id"] for s in out] or \
            any(any(x[k] != s[k] for k in cambia) for x, s, cambia in zip(norm["sesiones"], out, cambiados)):
        raise PlanInvalido([{"indice": None, "campo": "sesiones", "mensaje": "El plan no pasa la validación de la app; no se ha guardado."}])
    return base, out


def guardar(g: Guardian, proyecto: str, version: str | None, sesiones: list[dict]) -> dict:
    """Valida y escribe. `version`: la marca que recibió el cliente (`leer`); si el fichero ha cambiado, `ConflictoPlan` y no se escribe. Devuelve lo mismo que `leer`
    (el plan guardado, con la versión nueva). Errores: `PlanInvalido` (por campo), `ConflictoPlan`, `PlanAmbiguo`, `RutaProhibida`."""
    g.proyecto_dir(proyecto)
    fichero, datos = localizar(g, proyecto)
    if not version or version != version_de(datos):
        raise ConflictoPlan()
    crudo = _crudo(datos)
    plan, _finales = construir(sesiones, crudo, proyecto)
    texto = json.dumps(plan, ensure_ascii=False, indent=2) + "\n"
    if datos is not None and b"\r\n" in datos:
        texto = texto.replace("\n", "\r\n")
    n = len(texto.encode("utf-8"))
    if n > TOPE_PLAN_BYTES:   # la app no lee planes por encima del tope: escribirlo lo haría desaparecer
        raise PlanInvalido([{"indice": None, "campo": "sesiones", "mensaje": f"El plan ocupa demasiado para que la app lo lea ({-(-n // 1000)} kB de un máximo de "
                                                                                f"{TOPE_PLAN_BYTES // 1000} kB): quita objetivos o checks, o acorta los textos."}])
    nuevo = fichero is None
    if nuevo:
        fichero = g.nombre_fichero_plan(proyecto)
    try:
        g.escribir_plan(proyecto, fichero, texto, nuevo=nuevo)
    except RutaProhibida as e:
        if nuevo and "ya existe" in str(e):   # otro fichero con ese nombre que NO declara este proyecto: no se pisa
            raise ValueError("En la carpeta de planes ya hay un fichero con el nombre que usaría este plan y no es de este proyecto; no se ha guardado.")
        raise
    return leer(g, proyecto)
