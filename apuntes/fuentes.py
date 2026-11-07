"""Fuentes del asesor: recuperación LOCAL por palabras (BM25), sin LLM.

Sobre qué busca:
- el contexto del proyecto elegido (`00. CONTEXTO (IA)` o, sin él, CLAUDE.md, README.md y docs/: solo lectura);
- el «Contexto de la reunión» que el usuario preparó antes de empezar (en memoria, nunca se persiste aquí);
- la carpeta Knowledge (config `knowledge`, SOLO LECTURA: .md, .txt, .docx, .pptx y .pdf si hay librería instalada);
- las sesiones anteriores del MISMO proyecto, leídas con `backlog.py` (resumen, elementos y transcripción).

Cómo: el índice se construye en segundo plano al arrancar (Knowledge) y al empezar una reunión (proyecto y sesiones), es incremental por fecha de
modificación y tamaño y se guarda en `cache\\` SOLO a través del Guardian (`escribir_cache`). Nunca bloquea: `buscar` usa lo que ya hay; un
Knowledge lento o sin conexión (OneDrive) deja un índice parcial y se completa en la pasada siguiente; los marcadores de la nube sin descargar no se abren.
Mismas exclusiones de secretos que el resto de la app, topes de tamaño y de número de ficheros.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import threading
import time
from dataclasses import dataclass, field

from . import documentos as DOC
from .rutas import DIRS_EXCLUIDOS, EXT_LEGIBLES, RutaProhibida, es_secreto, sin_acentos, slug

VERSION = 1
TOPE_TROZO = 900            # caracteres por trozo recuperable
MAX_TROZOS_FICHERO = 80
MAX_TROZOS_TOTAL = 12_000
EXT_KNOWLEDGE = EXT_LEGIBLES | DOC.EXT_OFICINA | DOC.EXT_PDF
PESOS = {"reunion": 1.6, "esta_reunion": 1.4, "proyecto": 1.3, "sesion": 1.0, "knowledge": 0.9}   # a igualdad de palabras, lo más cercano a esta reunión gana

_STOP = set("""
de la que el en y a los se del las un por con no una su para es al lo como mas pero sus le ya o este si porque esta entre cuando muy sin sobre
tambien me hasta hay donde quien desde todo nos durante todos uno les ni contra otros ese eso ante ellos e esto mi antes algunos que unos yo
otro otras otra el tan poco ella estar estas algunas algo nosotros mis tu te ti tu tus ellas nosotras vosotros vosotras os mio mia mios mias
tuyo tuya tuyos tuyas suyo suya suyos suyas nuestro nuestra nuestros nuestras vuestro vuestra vuestros vuestras esos esas estoy estas estamos
estan este esté es son era eran fue ser soy eres somos sois ha han he hemos habia hacer hace hacen puede pueden vale bueno entonces ahora
els les dels amb per una uns unes com mes pero tambe fins on qui des tot som sou son era eren fou ser ha han hem hi aixo aquest aquesta
""".split())
_RE_TOKEN = re.compile(r"[a-z0-9]{2,}")


# ------------------------------------------------------------------ texto -> términos
def raiz(w: str) -> str:
    """Plural y poco más: cupos = cupo, inversiones = inversion."""
    if len(w) > 6 and w.endswith("es"):
        return w[:-2]
    if len(w) > 4 and w.endswith("s"):
        return w[:-1]
    return w


def tokenizar(texto: str) -> list[str]:
    t = sin_acentos(texto or "").lower()
    return [raiz(w) for w in _RE_TOKEN.findall(t) if w not in _STOP]


# ------------------------------------------------------------------ trocear
def trocear(texto: str, tope: int = TOPE_TROZO, maximo: int = MAX_TROZOS_FICHERO) -> list[str]:
    """Trozos de ≤`tope` caracteres: Markdown por secciones (cada trozo lleva el último título como contexto) y párrafos juntos hasta llenar el tope."""
    texto = (texto or "").replace("\r\n", "\n")
    out: list[str] = []
    titulo = ""
    actual: list[str] = []
    usado = 0

    def cerrar():
        nonlocal actual, usado
        cuerpo = "\n".join(actual).strip()
        if cuerpo and len(re.findall(r"\w+", cuerpo)) >= 3:
            out.append((f"[{titulo}] " if titulo and not cuerpo.lstrip().startswith("#") else "") + cuerpo)
        actual, usado = [], 0

    for linea in texto.split("\n"):
        if re.match(r"^#{1,6}\s", linea):
            cerrar()
            titulo = linea.lstrip("# ").strip()[:80]
        while len(linea) > tope:   # una línea enorme (p. ej. una celda o un párrafo sin saltos) se parte por palabras
            corte = linea.rfind(" ", 0, tope)
            corte = corte if corte > tope // 2 else tope
            if usado:
                cerrar()
            actual.append(linea[:corte])
            usado = corte
            cerrar()
            linea = linea[corte:].lstrip()
        if usado + len(linea) + 1 > tope and usado:
            cerrar()
        actual.append(linea)
        usado += len(linea) + 1
    cerrar()
    return out[:maximo]


def trocear_transcripcion(lineas: list[dict], tope: int = TOPE_TROZO, maximo: int = 40) -> list[tuple[str, int | None]]:
    """Líneas de una sesión pasada (`{t, m, f, x}`) -> trozos con el minuto de su primera línea: [(texto, segundos)]."""
    out: list[tuple[str, int | None]] = []
    actual: list[str] = []
    t0, usado = None, 0
    for l in lineas:
        x = (l.get("x") or "").strip()
        if not x:
            continue
        s = f"[{l.get('m') or '--:--'}] {x}"
        if usado + len(s) + 1 > tope and actual:
            out.append(("\n".join(actual), t0))
            actual, t0, usado = [], None, 0
        if t0 is None:
            t0 = l.get("t")
        actual.append(s)
        usado += len(s) + 1
    if actual:
        out.append(("\n".join(actual), t0))
    return out[:maximo]


# ------------------------------------------------------------------ índice BM25 en memoria
@dataclass
class Trozo:
    doc: int
    texto: str
    minuto_s: int | None = None      # solo sesiones pasadas: minuto de su primera línea


@dataclass
class Doc:
    etiqueta: str                    # lo que se cita: «02-alcance.md», «Knowledge/…/oferta.docx», «sesión 2026-11-04 · Tema»
    tipo: str                        # reunion | proyecto | sesion | knowledge
    trozos: list[tuple[str, int | None]] = field(default_factory=list)
    duracion_s: float | None = None  # sesiones pasadas: para validar el minuto citado


@dataclass
class Resultado:
    id: str                          # F1, F2…: lo que el modelo cita
    etiqueta: str
    tipo: str
    texto: str
    puntos: float
    minuto_s: int | None = None
    duracion_s: float | None = None


class Indice:
    """BM25 (k1 1,5; b 0,75) sobre los trozos de todos los documentos, con un peso por tipo de fuente. Se construye de una vez."""

    K1, B = 1.5, 0.75

    def __init__(self, docs: list[Doc] | None = None):
        self.docs: list[Doc] = []
        self.trozos: list[Trozo] = []
        self._post: dict[str, list[tuple[int, int]]] = {}
        self._long: list[int] = []
        self._media = 1.0
        for d in docs or []:
            self.anadir(d)
        self.construir()

    def anadir(self, d: Doc) -> None:
        idx = len(self.docs)
        self.docs.append(d)
        for texto, minuto in d.trozos:
            if len(self.trozos) >= MAX_TROZOS_TOTAL:
                break
            self.trozos.append(Trozo(idx, texto, minuto))

    def construir(self) -> None:
        self._post, self._long = {}, []
        for i, t in enumerate(self.trozos):
            toks = tokenizar(t.texto)
            self._long.append(max(1, len(toks)))
            tf: dict[str, int] = {}
            for w in toks:
                tf[w] = tf.get(w, 0) + 1
            for w, n in tf.items():
                self._post.setdefault(w, []).append((i, n))
        self._media = (sum(self._long) / len(self._long)) if self._long else 1.0

    def __len__(self) -> int:
        return len(self.trozos)

    def puntuar(self, consulta: str, contexto: str = "") -> dict[int, float]:
        n = len(self.trozos)
        if not n:
            return {}
        propios = tokenizar(consulta)
        q = {w: 1.0 for w in propios}
        for w in tokenizar(contexto):
            q.setdefault(w, 0.35)   # lo dicho justo antes ayuda a entender una pregunta elíptica, pero pesa menos
        puntos: dict[int, float] = {}
        coinc: dict[int, set[str]] = {}       # palabras de la PROPIA pregunta que tiene cada trozo (o, sin ellas, del contexto)
        raras: set[int] = set()               # trozos que casan por una palabra rara (en ≤2 trozos): una sola coincidencia basta
        rara_df = max(2, int(n * 0.01))
        for w, peso in q.items():
            lista = self._post.get(w)
            if not lista:
                continue
            df = len(lista)
            idf = math.log(1 + (n - df + 0.5) / (df + 0.5))
            for i, tf in lista:
                den = tf + self.K1 * (1 - self.B + self.B * self._long[i] / self._media)
                puntos[i] = puntos.get(i, 0.0) + peso * idf * tf * (self.K1 + 1) / den
                if peso == 1.0 or not propios:
                    coinc.setdefault(i, set()).add(w)
                    if df <= rara_df:
                        raras.add(i)
        # una sola palabra común entre cinco no es una fuente: se exigen 2 coincidencias (1 si la pregunta tiene ≤2 palabras, o si casa una palabra rara)
        minimo = 1 if len(propios) <= 2 else 2
        for i in list(puntos):
            if len(coinc.get(i, ())) < minimo and i not in raras:
                del puntos[i]
        for i in puntos:
            puntos[i] *= PESOS.get(self.docs[self.trozos[i].doc].tipo, 1.0)
        return puntos

    def buscar(self, consulta: str, contexto: str = "", k: int = 6, max_chars: int = 3500, max_por_doc: int = 2,
               minimo: float = 0.0) -> list[Resultado]:
        """Los trozos mejor puntuados (como mucho `max_por_doc` de cada documento) hasta `k` y hasta `max_chars` caracteres. Sin coincidencias, nada."""
        puntos = self.puntuar(consulta, contexto)
        orden = sorted(puntos, key=lambda i: (-puntos[i], i))
        por_doc: dict[int, int] = {}
        out: list[Resultado] = []
        usado = 0
        for i in orden:
            if len(out) >= k or puntos[i] <= minimo:
                break
            t = self.trozos[i]
            if por_doc.get(t.doc, 0) >= max_por_doc:
                continue
            d = self.docs[t.doc]
            cabe = usado + len(t.texto) <= max_chars
            texto = t.texto if cabe else t.texto[:max(0, max_chars - usado)].rsplit(" ", 1)[0]
            if not cabe and len(texto) < 60:   # lo que queda de tope no da ni para un trozo útil
                break
            out.append(Resultado(f"F{len(out) + 1}", d.etiqueta, d.tipo, texto, round(puntos[i], 3), t.minuto_s, d.duracion_s))
            por_doc[t.doc] = por_doc.get(t.doc, 0) + 1
            usado += len(texto)
            if usado >= max_chars:
                break
        return out


def fusionar(a: list[Resultado], b: list[Resultado], k: int = 6, max_chars: int = 3500) -> list[Resultado]:
    """Une dos listas de resultados (las fuentes y lo dicho antes en esta reunión), por puntuación, hasta `k` y `max_chars`, y renumera los ids (F1, F2…)."""
    out: list[Resultado] = []
    usado = 0
    for r in sorted(a + b, key=lambda x: -x.puntos):
        if len(out) >= k or usado + len(r.texto) > max_chars:
            continue
        out.append(Resultado(f"F{len(out) + 1}", r.etiqueta, r.tipo, r.texto, r.puntos, r.minuto_s, r.duracion_s))
        usado += len(r.texto)
    return out


# ------------------------------------------------------------------ persistencia en cache\ (solo vía Guardian)
def _nombre_cache(prefijo: str, clave: str) -> str:
    return f"indice-{prefijo}-{slug(clave, 40)}-{hashlib.sha1(clave.encode('utf-8')).hexdigest()[:10]}.json"


def cargar_cache(g, nombre: str) -> dict[str, dict]:
    """{clave de fichero: {firma, etiqueta, tipo, trozos, duracion_s}}; una caché ausente, rota o de otra versión es un diccionario vacío."""
    try:
        ruta = g.ruta_cache(nombre)
        if not ruta.is_file():
            return {}
        d = json.loads(ruta.read_text(encoding="utf-8"))
        if isinstance(d, dict) and d.get("version") == VERSION and isinstance(d.get("fuentes"), dict):
            return d["fuentes"]
    except (OSError, ValueError, RutaProhibida):
        pass
    return {}


def guardar_cache(g, nombre: str, fuentes: dict[str, dict]) -> bool:
    try:
        g.escribir_cache(nombre, json.dumps({"version": VERSION, "fuentes": fuentes}, ensure_ascii=False, separators=(",", ":")))
        return True
    except (OSError, RutaProhibida):
        return False


def _doc_de(e: dict) -> Doc:
    return Doc(e["etiqueta"], e["tipo"], [(t[0], t[1]) for t in e["trozos"]], e.get("duracion_s"))


# ------------------------------------------------------------------ Knowledge (solo lectura, incremental, con tiempo acotado)
class _Tope(Exception):
    """Se acabó el tiempo o el número de ficheros permitido: el índice queda parcial."""


@dataclass
class Informe:
    ficheros: int = 0
    nuevos: int = 0
    reutilizados: int = 0
    omitidos: int = 0
    en_la_nube: int = 0
    sin_formato: int = 0
    completo: bool = True
    segundos: float = 0.0
    avisos: list[str] = field(default_factory=list)

    def publico(self) -> dict:
        return {k: getattr(self, k) for k in ("ficheros", "nuevos", "reutilizados", "omitidos", "en_la_nube", "sin_formato", "completo")} | {
            "segundos": round(self.segundos, 1), "avisos": list(self.avisos)}


def indexar_knowledge(g, raiz_knowledge: str | os.PathLike | None, previo: dict[str, dict], max_ficheros: int = 800, tope_bytes: int = 200_000,
                      tope_documento_bytes: int = 15_000_000, tiempo_s: float = 40.0, profundidad: int = 6,
                      al_avanzar=None) -> tuple[dict[str, dict], Informe]:
    """Recorre Knowledge SIN escribir nada en él. Reutiliza lo que no ha cambiado (fecha de modificación y tamaño). Se detiene al agotar `tiempo_s`
    o `max_ficheros` (el índice queda parcial y la pasada siguiente lo completa). Los ficheros con nombre de secreto, de carpetas excluidas, mayores
    que el tope o sin descargar de la nube se omiten. `al_avanzar(fuentes)` se llama cada 40 ficheros nuevos para poder guardar lo hecho."""
    inf = Informe()
    t0 = time.monotonic()
    if not raiz_knowledge or not os.path.isdir(raiz_knowledge):
        return {}, inf
    base = os.fspath(raiz_knowledge)
    fuentes: dict[str, dict] = {}
    pendientes_guardar = 0
    try:
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = sorted(d for d in dirnames if d.lower() not in DIRS_EXCLUIDOS and not d.startswith(".") and not es_secreto(d))
            if dirpath[len(base):].count(os.sep) >= profundidad:
                dirnames[:] = []
            for fn in sorted(filenames):
                ext = os.path.splitext(fn)[1].lower()
                if ext not in EXT_KNOWLEDGE or fn.startswith("~$") or fn.startswith("."):
                    continue
                if es_secreto(fn):
                    inf.omitidos += 1
                    continue
                if inf.ficheros >= max_ficheros or time.monotonic() - t0 > tiempo_s:
                    inf.completo = False
                    raise _Tope()
                ruta = os.path.join(dirpath, fn)
                clave = os.path.normcase(os.path.relpath(ruta, base))
                try:
                    st = os.stat(ruta)
                except OSError:
                    continue
                inf.ficheros += 1
                if DOC.en_la_nube(ruta):
                    inf.en_la_nube += 1
                    continue
                firma = f"{st.st_mtime_ns}:{st.st_size}"
                hit = previo.get(clave)
                if hit and hit.get("firma") == firma:
                    fuentes[clave] = hit
                    inf.reutilizados += 1
                    continue
                if st.st_size > (tope_bytes if ext in EXT_LEGIBLES else tope_documento_bytes):
                    inf.omitidos += 1
                    continue
                try:
                    texto = g.leer_documento(ruta, base, tope_bytes)
                except (RutaProhibida, DOC.Indisponible, OSError):
                    inf.sin_formato += 1
                    continue
                trozos = trocear(texto)
                if not trozos:
                    continue
                fuentes[clave] = {"firma": firma, "etiqueta": "Knowledge/" + os.path.relpath(ruta, base).replace("\\", "/"), "tipo": "knowledge",
                                  "trozos": [[t, None] for t in trozos]}
                inf.nuevos += 1
                pendientes_guardar += 1
                if al_avanzar and pendientes_guardar >= 40:
                    pendientes_guardar = 0
                    al_avanzar(fuentes)
    except _Tope:
        pass
    inf.segundos = time.monotonic() - t0
    if not inf.completo:
        inf.avisos.append("Knowledge es grande o lento: el índice está parcial y se completará en el próximo arranque.")
        for k, v in previo.items():   # lo ya indexado y aún no revisado se conserva: el índice parcial no pierde lo que había
            fuentes.setdefault(k, v)
    return fuentes, inf


# ------------------------------------------------------------------ proyecto y sesiones anteriores
def docs_de_proyecto(g, proyecto: str | None, leer_contexto) -> dict[str, dict]:
    """Ficheros de contexto del proyecto (ya leídos por `contexto.contexto_legible`: mismas exclusiones y topes), con firma = hash del texto."""
    if not proyecto:
        return {}
    try:
        ficheros, _solo_lectura = leer_contexto(g, proyecto)
    except (RutaProhibida, OSError):
        return {}
    out = {}
    for nombre, texto in ficheros.items():
        if nombre in ("00-INDICE.md", "10-registro-de-cambios.md", "20-guia-de-entrada.md") or not (texto or "").strip():
            continue
        trozos = trocear(texto)
        if trozos:
            out[nombre] = {"firma": hashlib.sha1(texto.encode("utf-8")).hexdigest()[:16], "etiqueta": nombre, "tipo": "proyecto",
                           "trozos": [[t, None] for t in trozos]}
    return out


def docs_de_sesiones(g, backlog, proyecto: str | None, excluir_archivo: str = "", previo: dict[str, dict] | None = None,
                     maximo: int = 40) -> dict[str, dict]:
    """Sesiones ANTERIORES del mismo proyecto (por `backlog.py`: mismas exclusiones y topes del Guardian): resumen, elementos (decisiones,
    pendientes, riesgos…) y transcripción con minuto. Incremental por fecha de modificación y tamaño del .md. `excluir_archivo`: la sesión en curso."""
    if not proyecto or backlog is None:
        return {}
    previo = previo or {}
    out: dict[str, dict] = {}
    try:
        ix = backlog._indice_actual(True)
    except Exception:  # noqa: BLE001 — una carpeta lenta o rota nunca bloquea el asesor
        return {}
    n = 0
    for sid in ix.get("orden", []):
        s = ix["sesiones"].get(sid)
        if not s or s.get("proyecto") != proyecto or s.get("archivo") == excluir_archivo:
            continue
        if n >= maximo:
            break
        n += 1
        ruta = s.get("_ruta", "")
        try:
            st = os.stat(ruta)
            firma = f"{st.st_mtime_ns}:{st.st_size}"
        except OSError:
            continue
        clave = os.path.normcase(os.path.abspath(ruta))
        hit = previo.get(clave)
        etiqueta = f"sesión {s.get('fecha') or '?'} · {s.get('tema') or s.get('archivo')}"
        if hit and hit.get("firma") == firma:
            out[clave] = hit
            continue
        det = backlog.sesion(sid)
        if det is None:
            continue
        trozos: list[list] = [[t, None] for t in trocear(det.get("resumen") or "", maximo=20)]
        for it in det.get("items") or []:
            if it.get("texto"):
                trozos.append([f"{it.get('etiqueta') or it.get('tipo')}: {it['texto']}" + (f" ({it['responsable']})" if it.get("responsable") else ""), it.get("t")])
        trozos += [[t, m] for t, m in trocear_transcripcion(det.get("transcripcion") or [])]
        if trozos:
            out[clave] = {"firma": firma, "etiqueta": etiqueta, "tipo": "sesion", "duracion_s": s.get("duracion_s"), "trozos": trozos[:MAX_TROZOS_FICHERO + 40]}
    return out


# ------------------------------------------------------------------ servicio (lo que usa el Gestor)
class ServicioFuentes:
    """Índices en segundo plano y búsqueda sin bloqueo. `buscar` usa siempre lo último completo; nunca espera a un hilo."""

    def __init__(self, g, cfg, backlog=None):
        self.g, self.cfg, self.backlog = g, cfg, backlog
        self._lock = threading.RLock()
        self._knowledge: list[Doc] = []
        self._proyecto: list[Doc] = []
        self._reunion: list[Doc] = []
        self._indice = Indice()
        self._proyecto_clave = ""
        self.informe_knowledge: Informe | None = None
        self.informe_proyecto: dict = {}
        self._hilo_k: threading.Thread | None = None
        self._hilo_p: threading.Thread | None = None
        self.listo_knowledge = threading.Event()
        self.listo_proyecto = threading.Event()

    # ---- cola de reconstrucción del índice combinado
    def _reconstruir(self) -> None:
        with self._lock:
            docs = list(self._reunion) + list(self._proyecto) + list(self._knowledge)
        self._indice = Indice(docs)   # se construye fuera del cerrojo; el cambio de referencia es atómico

    # ---- Knowledge: al arrancar
    def _nombre_knowledge(self) -> str:
        return _nombre_cache("knowledge", os.path.normcase(str(self.cfg["knowledge"] or "sin-knowledge")))

    def arrancar(self) -> threading.Thread | None:
        """Carga la caché de Knowledge al instante y la actualiza en un hilo demonio. Idempotente."""
        if self._hilo_k is not None and self._hilo_k.is_alive():
            return self._hilo_k
        raiz = self.cfg["knowledge"]
        self.g.asegurar_cache()
        nombre = self._nombre_knowledge()
        previo = cargar_cache(self.g, nombre)
        with self._lock:
            self._knowledge = [_doc_de(e) for e in previo.values()]
        if self._knowledge:
            self._reconstruir()

        def trabajo():
            try:
                def parcial(f):
                    guardar_cache(self.g, nombre, f)
                fuentes, inf = indexar_knowledge(self.g, raiz, previo, int(self.cfg["fuentes_max_ficheros"]), int(self.cfg["tope_fichero_bytes"]),
                                                 tiempo_s=float(self.cfg["fuentes_tiempo_s"]), al_avanzar=parcial)
                self.informe_knowledge = inf
                if fuentes and (inf.nuevos or set(fuentes) != set(previo)):
                    guardar_cache(self.g, nombre, fuentes)
                with self._lock:
                    self._knowledge = [_doc_de(e) for e in fuentes.values()]
                self._reconstruir()
            except Exception as e:  # noqa: BLE001 — el índice es una ayuda: un fallo no afecta a la reunión
                from .registro import registrar_error
                registrar_error("ServicioFuentes.knowledge", e)
            finally:
                self.listo_knowledge.set()
        self._hilo_k = threading.Thread(target=trabajo, daemon=True, name="fuentes-knowledge")
        self._hilo_k.start()
        return self._hilo_k

    # ---- proyecto, sesiones anteriores y contexto de la reunión: al empezar una reunión
    def preparar_proyecto(self, proyecto: str | None, excluir_archivo: str = "", contexto_reunion: str = "") -> threading.Thread:
        """Hilo demonio: contexto del proyecto + sesiones anteriores. El contexto de la reunión entra al momento (está en memoria)."""
        from . import contexto as CX
        self.g.asegurar_cache()
        with self._lock:
            self._reunion = []
            if (contexto_reunion or "").strip():
                trozos = trocear(contexto_reunion, maximo=12)
                if trozos:
                    self._reunion = [Doc("Contexto de la reunión", "reunion", [(t, None) for t in trozos])]
            self._proyecto = []
            self._proyecto_clave = proyecto or ""
        self.listo_proyecto.clear()
        self.informe_proyecto = {}
        self._reconstruir()

        def trabajo():
            try:
                if not proyecto:
                    return
                nombre = _nombre_cache("proyecto", proyecto)
                previo = cargar_cache(self.g, nombre)
                docs = docs_de_proyecto(self.g, proyecto, CX.contexto_legible)
                ses_previas = {k: v for k, v in previo.items() if v.get("tipo") == "sesion"}
                ses = docs_de_sesiones(self.g, self.backlog, proyecto, excluir_archivo, ses_previas)
                todo = {**{"p:" + k: v for k, v in docs.items()}, **{"s:" + k: v for k, v in ses.items()}}
                if todo != previo:
                    guardar_cache(self.g, nombre, todo)
                with self._lock:
                    if self._proyecto_clave != (proyecto or ""):
                        return   # empezó otra reunión mientras tanto
                    self._proyecto = [_doc_de(e) for e in todo.values()]
                self.informe_proyecto = {"ficheros": len(docs), "sesiones": len(ses)}
                self._reconstruir()
            except Exception as e:  # noqa: BLE001
                from .registro import registrar_error
                registrar_error("ServicioFuentes.proyecto", e)
            finally:
                self.listo_proyecto.set()
        self._hilo_p = threading.Thread(target=trabajo, daemon=True, name="fuentes-proyecto")
        self._hilo_p.start()
        return self._hilo_p

    def olvidar_reunion(self) -> None:
        with self._lock:
            self._reunion, self._proyecto, self._proyecto_clave = [], [], ""
        self._reconstruir()

    # ---- búsqueda
    def buscar(self, consulta: str, contexto: str = "", k: int = 6, max_chars: int = 3500) -> list[Resultado]:
        try:
            return self._indice.buscar(consulta, contexto, k, max_chars)
        except Exception as e:  # noqa: BLE001 — sin fuentes la respuesta sigue: dirá que no hay base
            from .registro import registrar_error
            registrar_error("ServicioFuentes.buscar", e)
            return []

    def estado(self) -> dict:
        return {"trozos": len(self._indice), "knowledge_listo": self.listo_knowledge.is_set(), "proyecto_listo": self.listo_proyecto.is_set(),
                "knowledge": self.informe_knowledge.publico() if self.informe_knowledge else None, "proyecto": dict(self.informe_proyecto),
                "pdf": DOC.libreria_pdf()}
