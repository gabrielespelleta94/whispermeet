"""Contexto del proyecto: listado, selección local de fuentes (sin LLM), plantillas del kit."""
from __future__ import annotations

import hashlib
import math
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from .config import PLANTILLAS_DIR
from .rutas import CARPETA_CONTEXTO, CARPETA_SESIONES, DIRS_EXCLUIDOS, Guardian, RutaProhibida, es_secreto, sin_acentos
from .texto import tokens_utiles

PRIORIDAD = ("02", "01", "04", "03", "05", "07")
NO_ANALIZAR = ("00-INDICE.md", "10-registro-de-cambios.md", "20-guia-de-entrada.md")
SECCIONES_PERSONALES = re.compile(r"contactos", re.I)  # datos personales: no salen de la máquina


# ---------------------------------------------------------------- proyectos
def _norm(p) -> str:
    return os.path.normcase(os.path.realpath(os.fspath(p)))


def listar_proyectos(g: Guardian, q: str = "", excluir: tuple[Path, ...] = (), planes: dict | None = None) -> list[dict]:
    """Proyectos extra (fuera de la raíz, marcados si son compartidos) y subcarpetas de la raíz.
    `planes`: proyecto en minúsculas -> plan; los que tienen plan salen con `plan`."""
    planes = planes or {}
    out = []
    qn = (q or "").strip().lower()
    rutas_extra = set()
    for nombre, (ruta, compartido) in g.extras_ordenados():
        rutas_extra.add(_norm(ruta))
        if qn and qn not in nombre.lower():
            continue
        out.append({
            "nombre": nombre, "compartido": compartido,
            "tiene_contexto": os.path.isdir(os.path.join(ruta, CARPETA_CONTEXTO)),
            "tiene_sesiones": (not compartido) and os.path.isdir(os.path.join(ruta, CARPETA_SESIONES)),
            "ruta": str(ruta), "plan": planes.get(nombre.lower()), "extra": True})
    try:
        entradas = sorted(os.scandir(g.raiz), key=lambda e: e.name.lower())
    except OSError:
        return out
    for e in entradas:
        if not e.is_dir(follow_symlinks=False) or e.name.startswith(".") or e.name.lower() in DIRS_EXCLUIDOS:
            continue
        if any(os.path.normcase(os.path.realpath(e.path)) == os.path.normcase(os.path.realpath(x)) for x in excluir):
            continue
        if qn and qn not in e.name.lower():
            continue
        if e.name.lower() in g.extras or _norm(e.path) in rutas_extra:
            continue  # ya sale como proyecto extra
        out.append({
            "nombre": e.name, "compartido": False,
            "tiene_contexto": os.path.isdir(os.path.join(e.path, CARPETA_CONTEXTO)),
            "tiene_sesiones": os.path.isdir(os.path.join(e.path, CARPETA_SESIONES)),
            "ruta": e.path, "plan": planes.get(e.name.lower()), "extra": False})
    return out


# ---------------------------------------------------------------- metadatos baratos de cada proyecto (n_sesiones, ultima_sesion, n_md)
_RE_FECHA_SESION = re.compile(r"^(\d{4}-\d{2}-\d{2})")
_META_CACHE: dict[str, tuple] = {}          # ruta normalizada -> (clave de validez, valor)
_META_LOCK = threading.Lock()
_META_POOL = ThreadPoolExecutor(max_workers=4, thread_name_prefix="meta-proyecto")
META_TTL_S = 120.0                           # el recuento de .md no cambia la fecha de la carpeta raíz: se refresca cada tanto


def _carpetas_sesiones(g: Guardian, nombre: str, ruta: str | os.PathLike, compartido: bool) -> list[str]:
    cs = [os.path.join(ruta, CARPETA_SESIONES)]
    if compartido:   # las sesiones de un compartido viven también en copia local
        try:
            cs.append(os.fspath(g.carpeta_sesiones_local(nombre)))
        except RutaProhibida:
            pass
    return cs


def _calcular_meta(g: Guardian, nombre: str, ruta: str, compartido: bool, limites: dict) -> dict:
    fechas: set[str] = set()
    n_ses = 0
    vistos: set[str] = set()
    for c in _carpetas_sesiones(g, nombre, ruta, compartido):
        try:
            with os.scandir(c) as it:
                for e in it:
                    m = _RE_FECHA_SESION.match(e.name)
                    if m and e.name.lower().endswith(".md") and e.name.lower() not in vistos and not es_secreto(e.name):
                        vistos.add(e.name.lower())
                        n_ses += 1
                        fechas.add(m.group(1))
        except OSError:
            continue
    n_md = None
    try:
        r = g.md_del_proyecto(nombre, profundidad=limites.get("profundidad", 4), plazo_s=1.0, max_visitas=2500)
        n_md = len(r["ficheros"])
    except (RutaProhibida, OSError):
        pass
    return {"n_sesiones": n_ses, "ultima_sesion": max(fechas) if fechas else None, "n_md": n_md}


def _meta_de(g: Guardian, nombre: str, ruta: str, compartido: bool, limites: dict) -> dict:
    """Calcula (o recupera de la caché por fecha de modificación) los metadatos; el que lo pide decide cuánto espera."""
    clave_ruta = _norm(ruta)
    try:
        mt = (os.stat(ruta).st_mtime_ns, tuple(os.stat(c).st_mtime_ns if os.path.isdir(c) else 0
                                               for c in _carpetas_sesiones(g, nombre, ruta, compartido)))
    except OSError:
        mt = None
    with _META_LOCK:
        previo = _META_CACHE.get(clave_ruta)
    if previo and previo[0] == mt and time.monotonic() - previo[2] < META_TTL_S:
        return previo[1]
    valor = _calcular_meta(g, nombre, ruta, compartido, limites)
    with _META_LOCK:
        _META_CACHE[clave_ruta] = (mt, valor, time.monotonic())
    return valor


def enriquecer_proyectos(g: Guardian, lista: list[dict], limites: dict | None = None, plazo_s: float = 1.5) -> list[dict]:
    """Añade `n_sesiones`, `ultima_sesion` (AAAA-MM-DD) y `n_md` a cada proyecto SIN bloquear: cada uno se calcula en un hilo propio y,
    pasado `plazo_s` en total, los que no han terminado (carpeta lenta de OneDrive…) salen sin esos campos; el hilo sigue y la
    caché los deja listos para la siguiente petición."""
    limites = limites or {}
    pendientes = {}
    for p in lista:
        try:
            pendientes[id(p)] = (p, _META_POOL.submit(_meta_de, g, p["nombre"], p["ruta"], bool(p.get("compartido")), limites))
        except RuntimeError:
            break
    fin = time.monotonic() + plazo_s
    for p, fut in pendientes.values():
        try:
            p.update(fut.result(timeout=max(0.0, fin - time.monotonic())))
        except Exception:  # noqa: BLE001 — tiempo agotado o carpeta ilegible: se omite
            pass
    return lista


# ---------------------------------------------------------------- plantillas
def _sustituir(texto: str, proyecto: str, autor: str) -> str:
    return (texto.replace("{{FECHA}}", date.today().isoformat()).replace("{{JEFE}}", autor)
            .replace("{{CLIENTE}}", proyecto).replace("{{PROYECTO}}", proyecto))


def plantillas() -> dict[str, str]:
    """Nombre relativo -> contenido bruto de las plantillas del kit."""
    out = {}
    if not PLANTILLAS_DIR.is_dir():
        return out
    for p in sorted(PLANTILLAS_DIR.rglob("*.md")):
        rel = p.relative_to(PLANTILLAS_DIR).as_posix()
        out[rel] = p.read_text(encoding="utf-8")
    return out


def plantilla_renderizada(rel: str, proyecto: str, autor: str) -> str | None:
    t = plantillas().get(rel)
    return None if t is None else _sustituir(t, proyecto, autor)


def materializar_contexto(g: Guardian, proyecto: str, autor: str) -> list[str]:
    """Crea `00. CONTEXTO (IA)` con las plantillas del kit; no pisa nada que exista."""
    creados = []
    for rel, bruto in plantillas().items():
        if rel.count("/") == 0:
            destino = g.ruta_contexto(proyecto, rel)
            plantilla = False
        elif rel in ("equipos/LEEME.md", "en-curso/LEEME.md"):
            destino = g.ruta_contexto(proyecto, rel, permitir_subcarpeta_plantilla=True)
            plantilla = True
        else:
            continue
        if destino.exists():
            continue
        g.escribir_contexto(proyecto, rel, _sustituir(bruto, proyecto, autor), plantilla=plantilla)
        creados.append(rel)
    return creados


# ---------------------------------------------------------------- lectura local
def quitar_secciones(texto: str, patron: re.Pattern) -> str:
    out, saltando, nivel = [], False, 0
    for linea in texto.splitlines():
        m = re.match(r"^(#{1,6})\s+(.*)", linea)
        if m:
            n = len(m.group(1))
            if saltando and n <= nivel:
                saltando = False
            if not saltando and patron.search(m.group(2)):
                saltando, nivel = True, n
                continue
        if not saltando:
            out.append(linea)
    return "\n".join(out)


def es_plantilla_vacia(texto: str, minimo_palabras: int = 30) -> bool:
    n = 0
    for linea in texto.splitlines():
        s = linea.strip()
        if not s or s.startswith("#") or "{{" in s or re.fullmatch(r"[|\-\s:]+", s):
            continue
        if re.fullmatch(r"\*[^*]+\*", s):  # sugerencia en cursiva de la plantilla
            continue
        s = re.sub(r"\*[^*]*\*", " ", s)
        n += len(re.findall(r"\w+", s))
    return n < minimo_palabras


def _orden(nombre: str) -> tuple:
    pref = nombre[:2]
    return (PRIORIDAD.index(pref) if pref in PRIORIDAD else 50, nombre)


def ficheros_contexto(g: Guardian, proyecto: str, tope_bytes: int = 200_000) -> dict[str, str]:
    """Ficheros .md de la raíz de `00. CONTEXTO (IA)` (lectura segura, sin personales)."""
    pdir = g.proyecto_dir(proyecto)
    carpeta = pdir / CARPETA_CONTEXTO
    out: dict[str, str] = {}
    if not carpeta.is_dir():
        return out
    for e in sorted(os.scandir(carpeta), key=lambda e: _orden(e.name)):
        if not e.is_file() or not e.name.lower().endswith(".md") or es_secreto(e.name):
            continue
        try:
            texto = g.leer(e.path, carpeta, tope_bytes)
        except RutaProhibida:
            continue
        out[e.name] = quitar_secciones(texto, SECCIONES_PERSONALES)
    return out


# Contexto ampliado de CUALQUIER proyecto: «00. CONTEXTO (IA)» (prioridad máxima, como siempre) + CLAUDE.md / AGENTS.md / README.md de la
# raíz + todos los demás .md del proyecto (recursivo, acotado). SOLO LECTURA (por el Guardian): lo único que la app escribe sigue siendo
# «00. CONTEXTO (IA)» tras aceptar el usuario.
FICHEROS_RAIZ = ("claude.md", "agents.md", "readme.md")
MAX_FICHEROS_MD = 80          # contexto_md_max_ficheros
PROFUNDIDAD_MD = 4            # contexto_md_profundidad
TOPE_TOTAL_MD = 14_000        # contexto_md_tope_total_chars (el digest nunca ha pasado de 14.000 caracteres de contexto)
TOPE_FICHERO_DIGEST = 6000    # por fichero de 00. CONTEXTO y de la raíz
TOPE_OTRO_DIGEST = 3000       # por cualquier otro .md: así caben más ficheros en el mismo presupuesto
RESERVA_RAIZ = 0.25           # parte del tope total que 00. CONTEXTO no consume si hay CLAUDE.md/README/otros .md


def limites_md(cfg) -> dict:
    """Los topes del contexto ampliado (y el de tamaño por fichero) leídos de la configuración, con los valores de siempre por defecto."""
    def v(k, d):
        try:
            return int(cfg[k])
        except (KeyError, TypeError, ValueError):
            return d
    return {"max_ficheros": max(1, v("contexto_md_max_ficheros", MAX_FICHEROS_MD)),
            "profundidad": max(0, v("contexto_md_profundidad", PROFUNDIDAD_MD)),
            "tope_total": max(1000, v("contexto_md_tope_total_chars", TOPE_TOTAL_MD)),
            "tope_bytes": max(1000, v("tope_fichero_bytes", 200_000))}


def _grupo_y_etiqueta(rel: str) -> tuple[str, str]:
    """(grupo, etiqueta) de un .md por su ruta relativa: 'ctx' (dentro de 00. CONTEXTO; los de su raíz con el nombre pelado, como siempre),
    'raiz' (CLAUDE.md, AGENTS.md, README.md de la raíz) u 'otros'."""
    partes = rel.split("/")
    if partes[0].lower() == CARPETA_CONTEXTO.lower() and len(partes) > 1:
        return "ctx", partes[-1] if len(partes) == 2 else "/".join(partes[1:])
    if len(partes) == 1 and partes[0].lower() in FICHEROS_RAIZ:
        return "raiz", rel
    return "otros", rel


def _rango(e: dict) -> tuple:
    """Orden de prioridad: 00. CONTEXTO (como `_orden`), luego CLAUDE.md > AGENTS.md > README.md, luego el resto por cercanía a la raíz,
    novedad y nombre."""
    if e["grupo"] == "ctx":
        return (0, 0 if e["prof"] == 1 else 1, _orden(e["etiqueta"]), e["rel"])
    if e["grupo"] == "raiz":
        return (1, FICHEROS_RAIZ.index(e["rel"].lower()), (0, ""), e["rel"])
    return (2, e["prof"], (0, ""), -e["mtime"], e["rel"])


def listar_md(g: Guardian, proyecto: str, max_ficheros: int = MAX_FICHEROS_MD, profundidad: int = PROFUNDIDAD_MD,
              tope_bytes: int = 200_000, plazo_s: float = 6.0) -> dict:
    """Los .md que forman el contexto de un proyecto, YA ordenados por prioridad y sin leer. Cada entrada: `ruta`, `rel`, `etiqueta`
    (la clave que usa el digest), `grupo` (ctx | raiz | otros), `tam`, `mtime`, `prof` y `dejado` ('' si entra; si no el motivo:
    'tamaño', 'nube', 'límite' = pasa de `max_ficheros`). `truncado`: el recorrido se cortó por tiempo o por número de entradas."""
    r = g.md_del_proyecto(proyecto, profundidad=profundidad, tope_bytes=tope_bytes, plazo_s=plazo_s)
    entradas = []
    for f in r["ficheros"]:
        grupo, etiqueta = _grupo_y_etiqueta(f["rel"])
        entradas.append({**f, "grupo": grupo, "etiqueta": etiqueta})
    entradas.sort(key=_rango)
    usados = 0
    for e in entradas:
        if e["dejado"]:
            continue
        if usados >= max_ficheros:
            e["dejado"] = "límite"
        else:
            usados += 1
    return {"ficheros": entradas, "truncado": r["truncado"]}


def estimar_uso(entradas: list[dict], tope_total: int = TOPE_TOTAL_MD, prioritario: str = "") -> None:
    """Marca en cada entrada `en_digest` según el presupuesto del digest (estimación por tamaño: caracteres ≈ bytes) con la MISMA regla que
    `fuentes_digest`. Las que no caben quedan con `dejado = 'texto'`."""
    hay_otros = any(e["grupo"] != "ctx" and not e["dejado"] for e in entradas)
    tope_ctx = int(tope_total * (1 - RESERVA_RAIZ)) if hay_otros else tope_total
    total = 0
    for e in entradas:
        if e["dejado"]:
            e["en_digest"] = False
            continue
        if e["etiqueta"] in NO_ANALIZAR and e["grupo"] == "ctx":
            e["en_digest"] = False
            e["dejado"] = "no se analiza"
            continue
        tope = TOPE_PRIORITARIO if e["etiqueta"] == prioritario else (TOPE_OTRO_DIGEST if e["grupo"] == "otros" else TOPE_FICHERO_DIGEST)
        limite = tope_ctx if e["grupo"] == "ctx" else tope_total
        cabe = min(tope, e["tam"], max(0, limite - total))
        if cabe <= 0:
            e["en_digest"] = False
            e["dejado"] = "texto"
            continue
        e["en_digest"] = True
        total += cabe


def contexto_ampliado(g: Guardian, proyecto: str, limites: dict | None = None) -> tuple[dict[str, str], dict[str, str], bool]:
    """(ficheros, grupos, solo_lectura). `ficheros`: etiqueta -> texto, en orden de prioridad; `grupos`: etiqueta -> ctx | raiz | otros.
    `solo_lectura`: el proyecto NO tiene «00. CONTEXTO (IA)» (todo el contexto sale de ficheros que Apuntes no escribe nunca)."""
    lim = {**limites_md({}), **(limites or {})}
    pdir = g.proyecto_dir(proyecto)
    reales = ficheros_contexto(g, proyecto, lim["tope_bytes"])
    out: dict[str, str] = dict(reales)
    grupos: dict[str, str] = {k: "ctx" for k in reales}
    try:
        lista = listar_md(g, proyecto, lim["max_ficheros"], lim["profundidad"], lim["tope_bytes"])["ficheros"]
    except (RutaProhibida, OSError):
        lista = []
    for e in lista:
        if e["dejado"]:
            continue
        if e["grupo"] == "ctx" and e["prof"] == 1:
            continue   # los de la raíz de 00. CONTEXTO ya están (ficheros_contexto)
        try:
            texto = g.leer(e["ruta"], pdir, lim["tope_bytes"])
        except (RutaProhibida, OSError):
            continue
        texto = quitar_secciones(texto, SECCIONES_PERSONALES)
        if not texto.strip():
            continue
        clave = e["etiqueta"]
        if clave in out:
            clave = e["rel"] if e["grupo"] == "ctx" else "raíz/" + e["rel"]
        out[clave] = texto
        grupos[clave] = e["grupo"]
    return out, grupos, not reales


def ficheros_alternativos(g: Guardian, proyecto: str, tope_bytes: int = 200_000) -> dict[str, str]:
    """Los .md que NO son de «00. CONTEXTO (IA)»: CLAUDE.md, AGENTS.md, README.md y todos los demás del proyecto (recursivo y acotado;
    sin `02. Sesiones`, ocultas, generadas ni secretos). Solo lectura; sin «Contactos». Las claves son rutas relativas (`docs/a.md`)."""
    ficheros, grupos, _ = contexto_ampliado(g, proyecto, {"tope_bytes": tope_bytes})
    return {k: v for k, v in ficheros.items() if grupos[k] != "ctx"}


def contexto_legible(g: Guardian, proyecto: str, limites: dict | None = None) -> tuple[dict[str, str], bool]:
    """(ficheros, solo_lectura): «00. CONTEXTO (IA)» primero y, detrás, CLAUDE.md/AGENTS.md/README.md y el resto de .md del proyecto."""
    ficheros, _grupos, ro = contexto_ampliado(g, proyecto, limites)
    return ficheros, ro




def _plano(texto: str) -> str:
    return re.sub(r"\s+", " ", sin_acentos(texto or "").lower())


def _nombra(pregunta_plana: str, rel: str) -> int:
    """>0 si la pregunta nombra el fichero (su nombre completo, o todas las palabras de su nombre sin número ni extensión).
    Devuelve la fuerza de la coincidencia (nombre completo = 3, resto = nº de palabras)."""
    base = rel.rsplit("/", 1)[-1]
    if _plano(base) in pregunta_plana or _plano(rel) in pregunta_plana:
        return 3
    stem = re.sub(r"^\d+[-_ ]+", "", base.rsplit(".", 1)[0])
    palabras = tokens_utiles(stem.replace("-", " ").replace("_", " "))
    if not palabras:
        return 0
    q = tokens_utiles(pregunta_plana)
    return len(palabras) if palabras <= q else 0


def extractos_para_pregunta(g: Guardian, proyecto: str | None, pregunta: str, tope_total: int = 6000,
                            max_ficheros: int = 3, tope_fichero: int = 2500) -> dict[str, str]:
    """Extractos LOCALES (sin LLM) de los ficheros de contexto, SOLO de los que la pregunta nombra. Sin ficheros nombrados no
    viaja ninguno. De cada uno entran las secciones que más comparten con la pregunta, hasta los topes."""
    if not proyecto or not (pregunta or "").strip():
        return {}
    try:
        ficheros, _ = contexto_legible(g, proyecto)
    except RutaProhibida:
        return {}
    plana = _plano(pregunta)
    nombrados = sorted(((_nombra(plana, rel), rel) for rel in ficheros if rel not in NO_ANALIZAR), key=lambda x: (-x[0], x[1]))
    q = tokens_utiles(pregunta)
    out: dict[str, str] = {}
    usado = 0
    for fuerza, rel in nombrados:
        if fuerza <= 0 or len(out) >= max_ficheros or usado >= tope_total:
            break
        ext = extracto_relevante(ficheros[rel], q, min(tope_fichero, tope_total - usado))
        if ext.strip():
            out[rel] = ext
            usado += len(ext)
    return out


def contenido_actual(g: Guardian, proyecto: str, fichero: str, autor: str) -> tuple[str | None, bool]:
    """(texto, existe_en_disco). Si la carpeta no existe, devuelve la plantilla renderizada."""
    destino = g.ruta_contexto(proyecto, fichero)
    if destino.is_file():
        return g.leer(destino, destino.parent, 400_000), True
    return plantilla_renderizada(fichero, proyecto, autor), False


# ---------------------------------------------------------------- contexto de la reunión (lo que el usuario acepta antes de empezar)
def digest_de_contexto(texto: str) -> str:
    """El contexto aceptado como único contexto (Bandeja, o un proyecto sin nada que compactar): sin llamada al modelo."""
    return "[Contexto de la reunión, aportado por el usuario]\n" + (texto or "").strip()

def siguiente_numero_contexto(g: Guardian, proyecto: str) -> int:
    """Primer NN libre para un fichero nuevo de `00. CONTEXTO (IA)`: 11-19 y después 21-89 (00, 01-07, 10 y 20 son del kit)."""
    usados: set[int] = set()
    carpeta = g.proyecto_dir(proyecto) / CARPETA_CONTEXTO
    if carpeta.is_dir():
        for e in os.scandir(carpeta):
            m = re.match(r"^(\d{2})-", e.name)
            if m:
                usados.add(int(m.group(1)))
    for n in (*range(11, 20), *range(21, 90)):
        if n not in usados:
            return n
    raise RutaProhibida("no queda ningún número libre en «00. CONTEXTO (IA)»")


# ---------------------------------------------------------------- fuentes del digest
@dataclass
class Fuentes:
    textos: list[tuple[str, str]] = field(default_factory=list)  # (etiqueta, texto)
    clave: str = ""
    solo_lectura: bool = False   # el contexto sale solo de CLAUDE.md, README.md y otros .md (el proyecto no tiene «00. CONTEXTO (IA)»)

    @property
    def vacio(self) -> bool:
        return not self.textos


def knowledge_candidatos(raiz: str | os.PathLike | None, consulta: str, g: Guardian,
                         maximo: int = 1, tope_ficheros: int = 4000) -> list[tuple[str, str]]:
    """Knowledge entra solo con coincidencia clara (>=2 términos distintivos en ruta/nombre)."""
    if not raiz or not os.path.isdir(raiz):
        return []
    q = tokens_utiles(consulta)
    if len(q) < 2:
        return []
    puntuados, vistos = [], 0
    base = os.fspath(raiz)
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = [d for d in dirnames if d.lower() not in DIRS_EXCLUIDOS and not d.startswith(".")]
        if dirpath[len(base):].count(os.sep) > 4:
            dirnames[:] = []
        for fn in filenames:
            vistos += 1
            if vistos > tope_ficheros:
                break
            if not fn.lower().endswith(".md") or es_secreto(fn):
                continue
            ruta = os.path.join(dirpath, fn)
            coincide = q & tokens_utiles(os.path.relpath(ruta, base))
            if len(coincide) >= 2:
                puntuados.append((len(coincide), ruta))
        if vistos > tope_ficheros:
            break
    puntuados.sort(key=lambda x: (-x[0], x[1]))
    out = []
    for _, ruta in puntuados[:maximo]:
        try:
            out.append((f"Knowledge/{os.path.relpath(ruta, base)}", g.leer(ruta, base, 6000)[:4000]))
        except RutaProhibida:
            continue
    return out


TOPE_PRIORITARIO = 9000  # el fichero prioritario de la sesión admite más texto que el resto


def fuentes_digest(g: Guardian, proyecto: str, tema: str, knowledge: str | None,
                   tope_total: int = 20_000, prioritario: str = "", sesion_clave: str = "", limites: dict | None = None) -> Fuentes:
    """Selección LOCAL (sin LLM) de lo que alimenta el digest, y su clave de caché.

    `prioritario`: fichero de 00. CONTEXTO de la sesión del plan; entra el primero y con más tope.
    `sesion_clave`: identifica la sesión (y su foco) y forma parte de la clave de caché.
    Orden y presupuesto: 00. CONTEXTO primero (como mucho el 75 % del tope si hay más ficheros), luego CLAUDE.md/AGENTS.md/README.md y
    después el resto de .md por cercanía a la raíz y novedad. La clave incluye los nombres de TODOS los ficheros candidatos: si cambia el
    conjunto (aunque el nuevo se quede fuera del tope) cambia la clave."""
    textos: list[tuple[str, str]] = []
    total = 0
    ficheros, grupos, solo_lectura = contexto_ampliado(g, proyecto, limites)
    ctx = [n for n in ficheros if grupos[n] == "ctx"]
    resto = [n for n in ficheros if grupos[n] != "ctx"]
    if prioritario in ctx:
        ctx.remove(prioritario)
        ctx.insert(0, prioritario)
    tope_ctx = int(tope_total * (1 - RESERVA_RAIZ)) if resto else tope_total
    for nombre in (*ctx, *resto):
        texto = ficheros[nombre]
        es_ctx = grupos[nombre] == "ctx"
        if nombre in NO_ANALIZAR or (es_ctx and not solo_lectura and es_plantilla_vacia(texto)):
            continue
        tope = TOPE_PRIORITARIO if nombre == prioritario else (TOPE_OTRO_DIGEST if grupos[nombre] == "otros" else TOPE_FICHERO_DIGEST)
        texto = texto[: max(0, min(tope, (tope_ctx if es_ctx else tope_total) - total))]
        if not texto.strip():
            if es_ctx:
                continue   # 00 sin hueco: aún pueden entrar los de la raíz
            break
        textos.append((nombre, texto))
        total += len(texto)
    textos += knowledge_candidatos(knowledge, f"{proyecto} {tema}", g)
    h = hashlib.sha256(b"digest-v5")  # v5: cuatro tramos (uno por perfil del equipo), checks y, sin plan, objetivos sugeridos
    h.update(b"ro" if solo_lectura else b"ctx")
    h.update(("sesion:" + sesion_clave).encode("utf-8"))
    for etiqueta, texto in textos:
        h.update(etiqueta.encode("utf-8"))
        h.update(hashlib.sha256(texto.encode("utf-8")).digest())
    if resto:   # el conjunto de ficheros candidatos (también los que se quedan fuera del tope) forma parte de la clave
        h.update(b"conjunto:" + "|".join(sorted(ficheros)).encode("utf-8"))
    return Fuentes(textos=textos, clave=h.hexdigest()[:20], solo_lectura=solo_lectura and bool(textos))



def _secciones(texto: str) -> list[str]:
    """Trozos del Markdown que empiezan en cada encabezado (el primero puede no tenerlo)."""
    trozos, actual = [], []
    for linea in texto.split("\n"):
        if re.match(r"^#{1,6}\s", linea) and actual:
            trozos.append("\n".join(actual))
            actual = []
        actual.append(linea)
    if actual:
        trozos.append("\n".join(actual))
    return trozos


def extracto_relevante(texto: str, q: set[str], tope: int) -> str:
    """Si el fichero cabe en `tope`, entero. Si no, un índice con TODOS sus encabezados (para poder «anadir» a una
    sección existente) y, hasta llenar el tope, las secciones que más comparten con la reunión, en su orden original."""
    if len(texto) <= tope:
        return texto
    trozos = _secciones(texto)
    indice = [t.split("\n", 1)[0].strip() for t in trozos if re.match(r"^#{1,6}\s", t)]
    cabecera = "[Secciones del fichero: " + " | ".join(i.lstrip("# ").strip() for i in indice) + "]\n"
    cabecera = cabecera[: tope // 3]
    libre = tope - len(cabecera)
    orden = sorted(range(len(trozos)), key=lambda i: (-len(q & tokens_utiles(trozos[i])), i))
    elegidos, usado = set(), 0
    for i in orden:
        if usado + len(trozos[i]) + 1 <= libre:
            elegidos.add(i)
            usado += len(trozos[i]) + 1
    return cabecera + "\n".join(trozos[i] for i in sorted(elegidos))


def ficheros_para_final(g: Guardian, proyecto: str, consulta: str, autor: str,
                        maximo: int = 4, tope_fichero: int = 5000) -> dict[str, str]:
    """Solo los ficheros de 00. CONTEXTO que es verosímil que se modifiquen (puntuación local, sin LLM).

    Puntuación = términos distintivos que comparte el fichero con la reunión, ponderados por rareza entre los ficheros
    del proyecto y divididos por la raíz de su tamaño: un fichero enorme (bitácora, peticiones) no gana solo por tener
    más palabras. Los de alcance y plan (02, 04) suman un empujón. De cada fichero largo entra un extracto con las
    secciones más cercanas a la reunión, no sus primeros `tope_fichero` caracteres."""
    reales = {k: v for k, v in ficheros_contexto(g, proyecto).items() if k not in NO_ANALIZAR[:2]}
    if not reales:  # la carpeta no existe aún: se propone sobre las plantillas del kit
        reales = {k: plantilla_renderizada(k, proyecto, autor) or "" for k in plantillas()
                  if "/" not in k and k not in NO_ANALIZAR[:2]}
        reales = {k: quitar_secciones(v, SECCIONES_PERSONALES) for k, v in reales.items() if k[:2] in PRIORIDAD}
    q = tokens_utiles(consulta)
    tokens = {n: tokens_utiles(t) for n, t in reales.items()}
    df: dict[str, int] = {}
    for ts in tokens.values():
        for w in ts:
            df[w] = df.get(w, 0) + 1
    n = max(1, len(reales))
    puntuados = []
    for nombre in reales:
        ts = tokens[nombre]
        peso = sum(math.log(1 + n / df[w]) for w in q & ts)
        puntos = peso / math.sqrt(max(1, len(ts))) * (1.25 if nombre[:2] in ("02", "04") else 1.0)
        puntuados.append((puntos, nombre))
    puntuados.sort(key=lambda x: (-x[0], _orden(x[1])))
    return {nombre: extracto_relevante(reales[nombre], q, tope_fichero) for _, nombre in puntuados[:maximo]}


# ---------------------------------------------------------------- vocabulario para Whisper (local, sin LLM)
_RE_CODIGO = re.compile(r"```.*?```|`[^`\n]*`", re.S)
_RE_ENLACE = re.compile(r"https?://\S+|www\.\S+|\S+@\S+|\]\([^)]*\)")
_MAY, _MIN = "A-ZÁÉÍÓÚÑ", "a-záéíóúñ"
_RE_SIGLA = re.compile(rf"(?<![\w-])(?:[{_MAY}]{{2,6}}\d{{0,2}}|[{_MAY}]{{1,4}}\d{{1,2}})(?![\w-])")
_RE_CAMEL = re.compile(rf"(?<![\w-])[{_MAY}][{_MIN}]+(?:[{_MAY}][{_MIN}0-9]*)+(?![\w-])")
_RE_PROPIO = re.compile(rf"(?<=[{_MIN}0-9,;:)] )[{_MAY}][{_MIN}]{{3,}}(?![\w-])")   # con mayúscula inicial y NO tras punto ni inicio de línea
_NO_SIGLA = {"OK", "NO", "SI", "SÍ", "NOTA", "NOTAS", "TODO", "AVISO", "FIN", "EJ", "MD", "ID", "IA"}


def vocabulario_distintivo(textos, maximo: int = 40) -> list[str]:
    """Siglas (PMS, TR2), nombres en CamelCase y nombres propios (varias veces, a mitad de frase) de los textos de contexto YA
    cargados por la app. Solo regex y recuento: ni lee ficheros ni llama al modelo. Orden: más frecuentes primero (a igualdad,
    por orden de aparición). Las siglas en títulos de sección (EN MAYÚSCULAS) no cuentan, salvo si llevan cifra."""
    cuenta: dict[str, int] = {}
    primera: dict[str, int] = {}
    orden = 0

    def sumar(termino: str) -> None:
        nonlocal orden
        k = termino.lower()
        cuenta[k] = cuenta.get(k, 0) + 1
        if k not in primera:
            primera[k] = orden
            orden += 1
        forma.setdefault(k, termino)

    forma: dict[str, str] = {}
    minimo: dict[str, int] = {}   # apariciones necesarias según el tipo de término
    for texto in textos:
        t = _RE_ENLACE.sub(" ", _RE_CODIGO.sub(" ", texto or ""))
        for linea in t.splitlines():
            titulo = linea.lstrip().startswith("#")
            linea = re.sub(r"^[\s#>*\-+\d.)]+", "", linea)
            for m in _RE_SIGLA.finditer(linea):
                w = m.group(0)
                if w in _NO_SIGLA or (titulo and not re.search(r"\d", w)):
                    continue
                sumar(w)
                minimo[w.lower()] = 1
            for m in _RE_CAMEL.finditer(linea):
                sumar(m.group(0))
                minimo[m.group(0).lower()] = 1
            for m in _RE_PROPIO.finditer(linea):
                sumar(m.group(0))
                minimo.setdefault(m.group(0).lower(), 2)
    validos = [k for k, n in cuenta.items() if n >= minimo.get(k, 2)]
    validos.sort(key=lambda k: (-cuenta[k], primera[k]))
    return [forma[k] for k in validos[:maximo]]
