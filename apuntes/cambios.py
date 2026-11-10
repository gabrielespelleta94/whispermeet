"""Cambios propuestos a los ficheros de contexto: validación, aplicación, diff y registro."""
from __future__ import annotations

import difflib
import re
import unicodedata
from dataclasses import asdict, dataclass
from datetime import datetime

from .rutas import CARPETA_CONTEXTO, CARPETA_SESIONES
from .texto import mmss, recortar

MAX_CAMBIOS = 6
MAX_NUEVO = 3000
PROHIBIDOS = {"00-INDICE.md", "10-registro-de-cambios.md"}  # los gestiona la app
_RE_FICHERO = re.compile(r"^[0-9]{2}-[a-z0-9][a-z0-9\-]{0,80}\.md$")
_RE_CREAR = re.compile(r"^(0[689]|1[1-9]|2[1-9])-[a-z0-9][a-z0-9\-]{0,80}\.md$")
_RE_MIN = re.compile(r"^\d{1,3}:\d{2}$")


@dataclass
class Cambio:
    id: str
    fichero: str
    tipo: str  # anadir | reemplazar | crear
    motivo: str
    minuto: str
    seccion: str = ""
    anterior: str = ""
    nuevo: str = ""
    valido: bool = True
    error: str = ""
    diff: str = ""
    preaceptado: bool = False   # ola 3: la cita del cambio aparece literalmente (normalizada) en la transcripción
    cita: dict | None = None    # ola 3: {texto, minuto} de esa frase en la transcripción (None si no hay cita fiable)

    def publico(self) -> dict:
        return asdict(self)


def _encabezado(linea: str):
    m = re.match(r"^(#{1,6})\s+(.*?)\s*#*\s*$", linea)
    return (len(m.group(1)), m.group(2)) if m else None


def _norm_titulo(s: str) -> str:
    return re.sub(r"^#+\s*", "", s or "").strip().lower()


def _continuo(previa: str, nueva: str) -> bool:
    """Una fila de tabla o un elemento de lista continúan sin línea en blanco."""
    if previa.lstrip().startswith("|") and nueva.lstrip().startswith("|"):
        return True
    item = re.compile(r"^\s*([-*+]|\d+[.)])\s")
    return bool(item.match(previa) and item.match(nueva))


def aplicar(texto: str, c: Cambio) -> str:
    """Devuelve el texto con el cambio aplicado. Lanza ValueError si no encaja."""
    if c.tipo == "crear":
        return c.nuevo.rstrip() + "\n"
    if c.tipo == "reemplazar":
        if not c.anterior:
            raise ValueError("falta el texto a reemplazar")
        n = texto.count(c.anterior)
        if n != 1:
            raise ValueError("el texto a reemplazar no aparece una sola vez" if n else "el texto a reemplazar ya no está en el fichero")
        return texto.replace(c.anterior, c.nuevo, 1)
    if c.tipo == "anadir":
        if not c.nuevo.strip():
            raise ValueError("nada que añadir")
        lineas = texto.rstrip("\n").split("\n")
        fin = len(lineas)
        if c.seccion:
            objetivo = _norm_titulo(c.seccion)
            for i, l in enumerate(lineas):
                h = _encabezado(l)
                if h and _norm_titulo(h[1]) == objetivo:
                    fin = len(lineas)
                    for j in range(i + 1, len(lineas)):
                        h2 = _encabezado(lineas[j])
                        if h2 and h2[0] <= h[0]:
                            fin = j
                            break
                    break
            else:
                raise ValueError(f"no existe la sección «{c.seccion}»")
        antes = lineas[:fin]
        while antes and not antes[-1].strip():
            antes.pop()
        despues = lineas[fin:]
        bloque = c.nuevo.strip("\n").split("\n")
        sep = [] if (antes and _continuo(antes[-1], bloque[0])) else [""]
        res = antes + sep + bloque + ([""] + despues if despues else [])
        return "\n".join(res).rstrip("\n") + "\n"
    raise ValueError("tipo de cambio desconocido")


def diff_unificado(antes: str, despues: str, fichero: str) -> str:
    d = difflib.unified_diff(antes.splitlines(), despues.splitlines(), fromfile=f"a/{fichero}",
                             tofile=f"b/{fichero}", n=2, lineterm="")
    return "\n".join(d)


MIN_PALABRAS_CITA = 4


def _plano(texto: str) -> str:
    """Minúsculas, sin acentos ni signos, espacios colapsados: para comparar una cita con la transcripción."""
    t = unicodedata.normalize("NFD", str(texto or "").lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", t)).strip()


def buscar_cita(cita, transcripcion) -> dict | None:
    """ola 3. `cita`: frase que el modelo dice haber oído; `transcripcion`: [(t_seg, texto)] en orden. Devuelve {texto, minuto} (el texto, tal como
    figura en la transcripción) solo si la cita normalizada, de al menos `MIN_PALABRAS_CITA` palabras, aparece LITERALMENTE dentro de un fragmento
    o a caballo entre dos seguidos; si no, None (ante la duda no se da por fiable). FUNCIÓN PURA."""
    q = _plano(cita)
    if len(q.split()) < MIN_PALABRAS_CITA or not transcripcion:
        return None
    planos = [(t, texto, _plano(texto)) for t, texto in transcripcion]
    for t, texto, p in planos:
        if q in p:
            return {"texto": " ".join(str(texto).split()), "minuto": mmss(t)}
    for (t, texto, p), (_t2, texto2, p2) in zip(planos, planos[1:]):
        if q in f"{p} {p2}":
            return {"texto": " ".join(f"{texto} {texto2}".split()), "minuto": mmss(t)}
    return None


def normalizar(raw, contenidos: dict[str, str | None], transcripcion=None) -> list[Cambio]:
    """Valida la salida del modelo. `contenidos`: fichero -> texto actual (None si no existe). `transcripcion` (opcional, ola 3): [(t_seg, texto)]; un
    cambio válido cuya cita (`q`) aparece literalmente en ella sale `preaceptado` y con su `cita`."""
    out: list[Cambio] = []
    if not isinstance(raw, list):
        return out
    for i, r in enumerate(raw[:MAX_CAMBIOS]):
        if not isinstance(r, dict):
            continue
        fichero = str(r.get("f") or r.get("fichero") or "").strip()
        tipo = str(r.get("tipo") or "anadir").strip().lower()
        tipo = {"añadir": "anadir"}.get(tipo, tipo)
        c = Cambio(
            id=f"c{i + 1}", fichero=fichero, tipo=tipo,
            motivo=recortar(str(r.get("motivo") or ""), 240),
            minuto=str(r.get("m") or r.get("minuto") or "") if _RE_MIN.match(str(r.get("m") or r.get("minuto") or "")) else "",
            seccion=recortar(str(r.get("sec") or r.get("seccion") or ""), 120),
            anterior=str(r.get("ant") or r.get("anterior") or "")[:MAX_NUEVO],
            nuevo=str(r.get("nuevo") or "")[:MAX_NUEVO],
        )
        try:
            if tipo not in ("anadir", "reemplazar", "crear"):
                raise ValueError("tipo no admitido")
            if fichero in PROHIBIDOS or not _RE_FICHERO.match(fichero):
                raise ValueError("fichero no permitido")
            if tipo == "crear":
                if not _RE_CREAR.match(fichero) or fichero in contenidos:
                    raise ValueError("no se puede crear ese fichero")
                actual = ""
            else:
                if fichero not in contenidos or contenidos[fichero] is None:
                    raise ValueError("el fichero no existe en el contexto")
                actual = contenidos[fichero]
            c.diff = diff_unificado(actual, aplicar(actual, c), fichero)
            if not c.diff:
                raise ValueError("el cambio no modifica nada")
            c.cita = buscar_cita(r.get("q") or r.get("cita"), transcripcion)
            c.preaceptado = c.cita is not None
        except ValueError as e:
            c.valido, c.error = False, str(e)
        out.append(c)
    return out


def entrada_registro(autor: str, tema: str, ficheros: list[str], ruta_sesion: str, ahora: datetime | None = None,
                     local: bool = False) -> str:
    ahora = ahora or datetime.now()
    lista = ", ".join(f"`{f}`" for f in ficheros)
    donde = (f"transcripción guardada en local por WhisperMeet (`{ruta_sesion}`) y, si el usuario la publica al cerrar la revisión, "
             f"en `{CARPETA_SESIONES}/{ruta_sesion}`" if local
             else f"transcripción en `{CARPETA_SESIONES}/{ruta_sesion}`")
    return (
        f"### {ahora:%Y-%m-%d %H:%M} · Contexto actualizado desde la reunión «{recortar(tema, 80)}»\n\n"
        f"- **Quién:** {autor} (con Claude, desde WhisperMeet)\n"
        f"- **Qué y por qué:** el usuario aceptó {len(ficheros)} cambio(s) propuesto(s) a partir de la transcripción de la reunión.\n"
        f"- **Ficheros o documentos:** {lista}; {donde}.\n"
        f"- **Pendiente:** contrastar los cambios con el cliente antes de darlos por confirmados.\n"
    )


def entrada_registro_contexto(autor: str, tema: str, fichero: str, ahora: datetime | None = None) -> str:
    """Entrada de `10-registro-de-cambios.md` cuando el usuario guarda en el contexto del proyecto el «Contexto de la reunión»."""
    ahora = ahora or datetime.now()
    return (
        f"### {ahora:%Y-%m-%d %H:%M} · Contexto de reunión añadido: «{recortar(tema, 80)}»\n\n"
        f"- **Quién:** {autor} (con Claude, desde WhisperMeet)\n"
        f"- **Qué y por qué:** el usuario aceptó el contexto que preparó antes de la reunión y pidió guardarlo en el contexto del proyecto.\n"
        f"- **Ficheros o documentos:** `{fichero}`.\n"
        f"- **Pendiente:** contrastar el contenido con el cliente o el equipo antes de darlo por confirmado.\n"
    )


def entrada_registro_archivero(autor: str, fichero: str, actualizado: bool, n_documentos: int, ahora: datetime | None = None) -> str:
    """Entrada de `10-registro-de-cambios.md` cuando el usuario guarda en el contexto del proyecto el resultado del Agente Archivero."""
    ahora = ahora or datetime.now()
    return (
        f"### {ahora:%Y-%m-%d %H:%M} · Mapa de documentación {'actualizado' if actualizado else 'añadido'}\n\n"
        f"- **Quién:** {autor} (con Claude, desde WhisperMeet)\n"
        f"- **Qué y por qué:** el usuario aceptó guardar en el contexto del proyecto el resultado del Agente Archivero: la cobertura por faceta de la documentación "
        f"y el resumen de {n_documentos} {'documento leído' if n_documentos == 1 else 'documentos leídos'}.\n"
        f"- **Ficheros o documentos:** `{fichero}`.\n"
        f"- **Pendiente:** contrastar el contenido con los documentos originales antes de darlo por confirmado.\n"
    )


def insertar_en_registro(registro: str, entrada: str) -> str:
    """La entrada más reciente va arriba: antes del primer `### ` real (tras la plantilla)."""
    lineas = registro.split("\n")
    en_codigo = False
    for i, l in enumerate(lineas):
        if l.strip().startswith("```"):
            en_codigo = not en_codigo
        if not en_codigo and l.startswith("### "):
            return "\n".join(lineas[:i] + entrada.rstrip("\n").split("\n") + [""] + lineas[i:])
    return registro.rstrip("\n") + "\n\n" + entrada
