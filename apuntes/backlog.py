"""Backlog: todas las sesiones pasadas y la lista conjunta de pendientes, ideas, decisiones, riesgos y preguntas.

Lectura pura y tolerante de los .md de sesión (sin llamadas al modelo): una sesión rara nunca lanza una excepción; se devuelve lo que se
pudo leer y se anota el motivo en `avisos`. Toda lectura pasa por el `Guardian` (mismas exclusiones y topes que el resto de la app) y los .md
NUNCA se modifican: lo que el usuario marca (hecho, descartado, aprovechada) y los temas renombrados viven en `backlog/estado.json`, que
escribe el Guardian de forma atómica y queda fuera de git.

Fuentes: `bandeja/*.md`, `sesiones/<proyecto>/*.md` (copia local de proyectos compartidos) y `<proyecto>/02. Sesiones (transcripciones)` de cada
proyecto (raíz y `proyectos_extra`). Una carpeta lenta (OneDrive sin conexión) no bloquea: cada fuente se lee en su propio hilo con tiempo
acotado; si no responde se muestra lo ya leído y se avisa, y el hilo sigue en segundo plano para la próxima vez.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
from datetime import date, datetime
from difflib import SequenceMatcher
from pathlib import Path

from .rutas import RutaProhibida, sin_acentos

TIPOS = ("pendiente", "idea", "decision", "riesgo", "pregunta", "regla", "contradiccion", "consejo")
ETIQUETA = {"pendiente": "Pendiente", "idea": "Idea", "decision": "Decisión", "riesgo": "Riesgo", "pregunta": "Pregunta",
            "regla": "Regla", "contradiccion": "Contradicción", "consejo": "Consejo"}   # «Consejo»: los del Estratega, de la sección «## Asesor» del .md
ESTADOS = {"pendiente": ("abierto", "hecho", "descartado"), "idea": ("nueva", "aprovechada", "descartada")}   # el resto solo se consulta
ESTADO_INICIAL = {"pendiente": "abierto", "idea": "nueva"}

SIN_CERRAR_SIEMPRE_H = 24    # …y con más de estas horas desde el inicio no puede seguir en curso aunque el fichero se haya tocado hace poco
SIN_CERRAR_H = 12            # «en curso» desde hace más de estas horas…
ESCRITURA_RECIENTE_MIN = 30  # …y sin que el fichero haya cambiado en este tiempo = «sin cerrar»
TIEMPO_FUENTE_S = 8.0        # tiempo máximo de espera por la lectura de todas las carpetas
MAX_FICHEROS_CARPETA = 2000
MAX_TEMA = 120

_RE_MIN = r"(?:\d{1,3}:\d{2}(?::\d{2})?)"
_RE_RANGO = rf"(?:\s*[–—\-]\s*{_RE_MIN})?"
_RE_INSIGHT = re.compile(rf"^\s*[-*+]\s*(?:\[\s*(?P<min>--:--|{_RE_MIN}){_RE_RANGO}\s*\]\s*)?\*\*(?P<tipo>[^*]{{1,80}}?)\*\*\s*:?\s*(?P<resto>.*)$")
_RE_SEGMENTO = re.compile(rf"^\s*\[\s*(?P<min>{_RE_MIN})\s*\]\s*(?:\*\*(?P<fuente>[^*]{{1,40}}?)\*\*\s*:?\s*)?(?P<texto>.*)$")
_RE_ITEM = re.compile(r"^\s*(?:[-*+]|\d{1,3}[.)])\s+(?P<cuerpo>.*\S.*)$")
_RE_H2 = re.compile(r"^##\s+(?P<titulo>\S.*?)\s*#*\s*$")
_RE_H1 = re.compile(r"^#\s+(?P<titulo>\S.*?)\s*$")
_RE_CLAVE = re.compile(r"^(?P<k>[A-Za-z_][\w\-]{0,40})\s*:\s*(?P<v>.*)$")
_RE_FECHA_NOMBRE = re.compile(r"^(\d{4}-\d{2}-\d{2})")

_MARCA_RECORTE = "[…recortado por tamaño]"


# ------------------------------------------------------------------ utilidades puras
def normalizar(texto: str) -> str:
    """Minúsculas, sin acentos ni signos, espacios colapsados: la base de la comparación y de los identificadores."""
    t = sin_acentos(str(texto or "")).lower()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", t)).strip()


def clave_repetido(texto: str) -> str:
    """Clave para detectar el mismo pendiente escrito dos veces (ver `Backlog._marcar_repetidos`)."""
    return normalizar(texto)


def a_segundos(minuto: str | None) -> int | None:
    """«MM:SS» (los minutos pueden pasar de 59) o «H:MM:SS» -> segundos; None si no es un minuto."""
    m = re.fullmatch(r"(\d{1,3}):(\d{2})(?::(\d{2}))?", (minuto or "").strip())
    if not m:
        return None
    a, b, c = int(m.group(1)), int(m.group(2)), m.group(3)
    return (a * 3600 + b * 60 + int(c)) if c is not None else (a * 60 + b)


def a_mmss(seg: int | None) -> str | None:
    return None if seg is None else f"{seg // 60:02d}:{seg % 60:02d}"


def _norm_ruta(p) -> str:
    return os.path.normcase(os.path.realpath(os.fspath(p)))


def id_sesion(ruta) -> str:
    return hashlib.sha1(("s|" + _norm_ruta(ruta)).encode("utf-8")).hexdigest()[:16]


def id_item(ruta, tipo: str, texto: str, n: int = 0) -> str:
    """Estable: depende de la ruta de la sesión, el tipo y el texto normalizado (sus primeros 60 caracteres, para que un insight recortado y su
    versión completa sigan siendo el mismo), NO del orden. `n` solo distingue repeticiones exactas dentro de la misma sesión."""
    base = f"i|{_norm_ruta(ruta)}|{tipo}|{normalizar(texto.rstrip('…. '))[:60]}" + (f"|{n}" if n else "")
    return hashlib.sha1(base.encode("utf-8")).hexdigest()[:16]


def _tokens(norm: str) -> set[str]:
    return {w for w in norm.split() if len(w) >= 4}


def _similitud(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    r = SequenceMatcher(None, a, b, autojunk=False).ratio()
    ta, tb = set(a.split()), set(b.split())
    return max(r, len(ta & tb) / len(ta | tb) if ta | tb else 0.0)


def tipo_de(etiqueta: str) -> tuple[str | None, bool, bool]:
    """Etiqueta de un insight («Decisión», «Posible contradicción», «Idea (tú)») -> (tipo, posible, es_del_usuario)."""
    t = normalizar(re.sub(r"\([^)]*\)", " ", etiqueta or ""))
    tu = "(tú)" in (etiqueta or "").lower() or "(tu)" in (etiqueta or "").lower()
    posible = t.startswith("posible ")
    if posible:
        t = t[len("posible "):]
    for prefijo, tipo in (("decision", "decision"), ("pendiente", "pendiente"), ("pregunta", "pregunta"), ("riesgo", "riesgo"), ("idea", "idea"),
                          ("regla", "regla"), ("contradiccion", "contradiccion"), ("consejo", "consejo")):
        if t.startswith(prefijo):
            return tipo, posible, tu
    return None, posible, tu


def _nombre_plausible(s: str) -> bool:
    """Un responsable explícito en el texto: una sola palabra con inicial mayúscula (Ana, Luis, Yo). Siglas y términos de varias palabras no cuentan."""
    s = (s or "").strip()
    return bool(re.fullmatch(r"[A-ZÁÉÍÓÚÑÜ][a-záéíóúñü]{0,19}", s)) and normalizar(s) not in {"sin", "ninguno", "ninguna", "nadie", "todos", "equipo"}


def _sin_enfasis(t: str) -> str:
    return re.sub(r"\s+", " ", t.replace("**", "").replace("`", "")).strip()


# ------------------------------------------------------------------ cabecera YAML y secciones
def _desquotar(v: str) -> str:
    v = v.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        return v[1:-1]
    if v[:1] in "\"'":   # comilla sin cerrar (YAML roto): se descarta solo la comilla
        return v[1:]
    return v


def parsear_cabecera(lineas: list[str]) -> tuple[dict, int, list[str]]:
    """(metadatos, índice de la primera línea tras la cabecera, avisos). Tolera una cabecera sin cerrar o con líneas que no son «clave: valor»."""
    avisos: list[str] = []
    i = 0
    while i < len(lineas) and not lineas[i].strip():
        i += 1
    if i >= len(lineas) or lineas[i].strip() != "---":
        avisos.append("El fichero no tiene cabecera YAML: tema, fecha y proyecto salen del nombre y del título.")
        return {}, 0, avisos
    meta: dict = {}
    j, cerrada, raras = i + 1, False, 0
    while j < len(lineas) and j < i + 60:
        s = lineas[j].rstrip()
        if s.strip() == "---":
            cerrada = True
            break
        if s.startswith("#"):   # el cuerpo ya ha empezado: la cabecera no se cerró
            break
        m = _RE_CLAVE.match(s)
        if m:
            meta[m.group("k").lower()] = _desquotar(m.group("v"))
        elif s.strip():
            raras += 1
        j += 1
    if not cerrada:
        avisos.append("La cabecera YAML no se cierra con «---».")
        return meta, j, avisos
    if raras:
        avisos.append(f"La cabecera YAML tiene {raras} línea(s) que no son «clave: valor»; se ignoran.")
    return meta, j + 1, avisos


def _secciones(lineas: list[str]) -> list[tuple[str, str, list[str]]]:
    """[(título normalizado, título, líneas)] por cada «## Título». Lo anterior a la primera sección se devuelve con título vacío."""
    out: list[tuple[str, str, list[str]]] = [("", "", [])]
    for s in lineas:
        m = _RE_H2.match(s)
        if m and not s.startswith("###"):
            out.append((normalizar(m.group("titulo")), m.group("titulo").strip(), []))
        else:
            out[-1][2].append(s)
    return out


# ------------------------------------------------------------------ insights y resumen
def _quitar_sufijos(texto: str, tipo: str) -> tuple[str, str | None, str | None, bool]:
    """(texto limpio, responsable, contexto, recortado). Sufijos: « — contexto: «…»», «(Responsable)», «(turno N)», «(tramo N)», «(sin asignar)»."""
    contexto = None
    m = re.search(r"\s+—\s+contexto:\s*(?P<c>.*)$", texto, flags=re.I)
    if m:
        contexto = m.group("c").strip().strip("«»\"' ").strip() or None
        texto = texto[:m.start()]
    responsable = None
    for _ in range(4):
        m = re.search(r"\s*\((?P<p>[^()]{1,40})\)\s*\.?\s*$", texto)
        if not m:
            break
        p = m.group("p").strip()
        if re.fullmatch(r"(turno|tramo|an[aá]lisis)\s*\d+", p, flags=re.I) or re.fullmatch(r"sin (asignar|responsable)|no identificado", p, flags=re.I):
            texto = texto[:m.start()]
        elif responsable is None and tipo == "pendiente" and _nombre_plausible(p):
            responsable = p
            texto = texto[:m.start()]
        else:
            break
    texto = _sin_enfasis(texto)
    recortado = texto.endswith("…") or texto.endswith("...")
    return texto, responsable, contexto, recortado


def _extraer_insights(lineas: list[str], tu: bool = False) -> tuple[list[dict], int, int]:
    """(items, líneas no reconocidas, líneas de tipo desconocido). Una línea de la sección de insights que no es un insight no rompe nada."""
    items, ilegibles, desconocidos = [], 0, 0
    for s in lineas:
        if not s.strip() or s.lstrip().startswith("#"):
            continue
        m = _RE_INSIGHT.match(s)
        if not m:
            if _RE_ITEM.match(s):
                ilegibles += 1
            continue
        tipo, posible, es_tu = tipo_de(m.group("tipo").strip().rstrip(":"))
        if tipo is None:
            if es_tu or "comentario" in normalizar(m.group("tipo")):
                continue   # comentarios del usuario: no son un tipo de la lista
            desconocidos += 1
            continue
        texto, resp, contexto, recortado = _quitar_sufijos(m.group("resto").strip(), tipo)
        if not texto:
            ilegibles += 1
            continue
        minuto = m.group("min")
        items.append({"tipo": tipo, "texto": texto, "minuto": None if not minuto or minuto == "--:--" else minuto,
                      "responsable": resp, "contexto": contexto, "origen": "tu" if (tu or es_tu) else "insight",
                      "posible": posible, "recortado": recortado})
    return items, ilegibles, desconocidos


_APARTADOS = (("decisi", "decision"), ("pendiente", "pendiente"), ("idea", "idea"), ("riesgo", "riesgo"),
              ("regla", "regla"), ("contradic", "contradiccion"))


def tipo_apartado(titulo: str) -> tuple[str | None, bool]:
    """Título de un apartado del Resumen -> (tipo, mixto). «Preguntas y riesgos abiertos» es mixto: cada línea decide. Lo que no es un tipo
    (Objetivo, Próximos pasos, Puntos abiertos, Desarrollo…) devuelve None y cierra el apartado anterior."""
    t = normalizar(re.sub(r"\([^)]*\)", " ", titulo or ""))
    if "pregunta" in t and "riesgo" in t and (t.startswith("pregunta") or t.startswith("riesgo")):
        return "pregunta", True
    if t.startswith("pregunta"):
        return "pregunta", False
    for prefijo, tipo in _APARTADOS:
        if t.startswith(prefijo):
            return tipo, False
    return None, False


def _item_resumen(cuerpo: str, tipo: str, mixto: bool) -> dict | None:
    t = cuerpo.strip()
    minuto, resp = None, None
    m = re.match(rf"^\[\s*({_RE_MIN}){_RE_RANGO}\s*\]\s*(.*)$", t) or re.match(rf"^\*\*\s*({_RE_MIN}){_RE_RANGO}\s*\*\*\s*[:\-–—]?\s*(.*)$", t)
    if m:
        minuto, t = m.group(1), m.group(2)
    m = re.match(r"^\*\*(?P<l>[^*]{1,80}?)\*\*\s*(?P<r>.*)$", t)
    if m:
        etiqueta = m.group("l").strip().rstrip(":").strip()
        if tipo == "pendiente" and _nombre_plausible(etiqueta):
            resp, t = etiqueta, m.group("r").lstrip(": ").strip()
        elif re.search(r"sin responsable|sin asignar", etiqueta, flags=re.I):
            t = m.group("r").lstrip(": ").strip()
        else:
            t = f"{etiqueta}: {m.group('r').lstrip(': ').strip()}" if m.group("r").strip() else etiqueta
    if minuto is None:
        m = re.search(rf"\s*(?:\[\s*({_RE_MIN}){_RE_RANGO}\s*\]|\(\s*({_RE_MIN}){_RE_RANGO}(?:\s*[,;]\s*{_RE_MIN})*\s*\))\s*\.?\s*$", t)
        if m:
            minuto, t = m.group(1) or m.group(2), t[:m.start()]
    if minuto is None:   # «… el viernes [04:05]; reclamar …»: un minuto entre corchetes en mitad del texto
        m = re.search(rf"\s*\[\s*({_RE_MIN}){_RE_RANGO}\s*\]", t)
        if m:
            minuto, t = m.group(1), t[:m.start()] + t[m.end():]
    m = re.search(r"\s*\bResponsable:\s*(?P<r>.+?)\.?\s*$", t, flags=re.I)
    if m:
        quien = m.group("r").strip()
        if not re.match(r"(sin|no|n/a|ninguno)", quien, flags=re.I) and len(quien) <= 40 and resp is None:
            resp = _sin_enfasis(quien)
        t = t[:m.start()]
    t = _sin_enfasis(t).rstrip()
    t = t[:1].upper() + t[1:] if t[:1].islower() else t
    if not t or normalizar(t) in {"ninguno", "ninguna", "ninguno registrado", "ninguna registrada", "n a", "no hay"}:
        return None
    if mixto:
        tipo = "pregunta" if ("?" in t or t.startswith("¿")) else "riesgo"
    t2, r2, contexto, recortado = _quitar_sufijos(t, tipo)
    return {"tipo": tipo, "texto": t2, "minuto": minuto, "responsable": resp or r2, "contexto": contexto, "origen": "resumen",
            "posible": False, "recortado": recortado}


def _extraer_resumen(secciones: list[tuple[str, str, list[str]]]) -> list[dict]:
    """Elementos de los apartados del Resumen («**Pendientes**», «### Decisiones»…). No sale nada de lo que sea prosa en una sola línea."""
    out: list[dict] = []
    for norm, titulo, lineas in secciones:
        tipo, mixto = None, False
        if norm.startswith("resumen"):
            pass
        elif tipo_apartado(titulo)[0] is not None and "sesion" not in norm and "check" not in norm:
            tipo, mixto = tipo_apartado(titulo)   # un «## Decisiones» suelto en una sesión antigua
        else:
            continue
        for s in lineas:
            if not s.strip():
                continue
            if _RE_ITEM.match(s):
                if tipo:
                    it = _item_resumen(_RE_ITEM.match(s).group("cuerpo"), tipo, mixto)
                    if it:
                        out.append(it)
                continue
            m = (re.match(r"^\s*#{3,6}\s+(?P<t>.+?)\s*#*\s*$", s) or re.match(r"^\s*\*\*(?P<t>[^*]+?)\*\*\s*:?\s*$", s)
                 or re.match(r"^\s*\*\*(?P<t>[^*]+?)\*\*\s*:?\s*\S.*$", s))
            if m:   # una línea de título: la prosa de una sola línea tras «**Decisiones:**» no es una lista y cierra el apartado
                tipo, mixto = tipo_apartado(m.group("t"))
                if re.match(r"^\s*\*\*[^*]+\*\*\s*:?\s*\S", s) and not re.match(r"^\s*\*\*[^*]+\*\*\s*:?\s*$", s):
                    tipo = None
    return out


def _unir(insights: list[dict], candidatos: list[dict]) -> list[dict]:
    """Suma lo del Resumen que no está ya en Insights. Duplicado = mismo tipo, minuto cercano (≤60 s) y texto muy parecido (≥0,6; sin minuto, ≥0,8;
    o, en el mismo minuto, la mayoría de las palabras significativas en común).
    Un insight recortado («…») cuyo texto completo está en el Resumen se sustituye por el completo. Ante la duda se conservan los dos."""
    items = [dict(i) for i in insights]
    for c in candidatos:
        cn, tc = normalizar(c["texto"]), a_segundos(c["minuto"])
        mejor, mejor_s, completa = None, 0.0, False
        tok_c = _tokens(cn)
        for i in items:
            if i["tipo"] != c["tipo"] or i.get("_resumen"):
                continue
            ti = a_segundos(i["minuto"])
            delta = abs(ti - tc) if ti is not None and tc is not None else None
            cerca = delta is not None and delta <= 60
            if not (cerca or delta is None):
                continue
            inn = normalizar(i["texto"].rstrip("….. "))
            tok_i = _tokens(inn)
            comun = len(tok_i & tok_c)
            if i["recortado"] and len(inn) >= 20 and len(cn) > len(inn) and (
                    cn.startswith(inn) or _similitud(cn[:len(inn)], inn) >= 0.9
                    or (delta is not None and delta <= 15 and len(tok_i) >= 3 and comun / len(tok_i) >= 0.5)):
                mejor, mejor_s, completa = i, 1.0, True
                break
            s = _similitud(cn, normalizar(i["texto"]))
            solape = delta is not None and delta <= 5 and comun >= 3 and comun / min(len(tok_i), len(tok_c)) >= 0.6   # mismo minuto y casi las mismas palabras
            s = max(s, 0.7 if solape else 0.0)
            if s >= (0.6 if cerca else 0.8) and s > mejor_s:
                mejor, mejor_s = i, s
        if mejor is None:
            items.append({**c, "_resumen": True})
        elif completa:
            mejor.update(texto=c["texto"], recortado=c["recortado"], completado=True)
            mejor["responsable"] = mejor.get("responsable") or c.get("responsable")
    for i in items:
        i.pop("_resumen", None)
    return items


# ------------------------------------------------------------------ una sesión
def _fecha(v) -> str | None:
    try:
        return date.fromisoformat(str(v).strip()).isoformat()
    except (TypeError, ValueError):
        return None


def _hora(v) -> str | None:
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", str(v or "").strip())
    return f"{int(m.group(1)):02d}:{m.group(2)}" if m and int(m.group(1)) < 24 and int(m.group(2)) < 60 else None


def parsear_sesion(texto: str, nombre: str = "", proyecto_fuente: str | None = None) -> dict:
    """Lee el texto de un .md de sesión. Nunca lanza: lo que no se entiende se anota en `avisos` y el resto se devuelve."""
    avisos: list[str] = []
    r = {"tema": None, "proyecto": None, "fecha": None, "inicio": None, "duracion_s": None, "estado_raw": "", "cadencia": None,
         "publicada_en": None, "resumen": "", "items": [], "definiciones": [], "transcripcion": [], "avisos": avisos}
    try:
        lineas = str(texto or "").replace("\r\n", "\n").replace("\r", "\n").lstrip("﻿").split("\n")
        meta, desde, a = parsear_cabecera(lineas)
        avisos += a
        cuerpo = lineas[desde:]
        secs = _secciones(cuerpo)
        fecha_nombre = _RE_FECHA_NOMBRE.match(nombre or "")
        r["fecha"] = _fecha(meta.get("fecha")) or _fecha(fecha_nombre.group(1) if fecha_nombre else None)
        if meta.get("fecha") and not _fecha(meta.get("fecha")):
            avisos.append("La fecha de la cabecera no es válida" + ("; se usa la del nombre del fichero." if r["fecha"] else "."))
        elif not r["fecha"]:
            avisos.append("No se pudo saber la fecha de la sesión.")
        r["inicio"] = _hora(meta.get("inicio"))
        d = a_segundos(meta.get("duracion")) if meta.get("duracion") else None
        r["duracion_s"] = d
        if meta.get("duracion") and d is None:
            avisos.append("La duración de la cabecera no es válida.")
        r["estado_raw"] = normalizar(meta.get("estado", ""))
        r["cadencia"] = meta.get("cadencia") or None
        r["publicada_en"] = meta.get("publicada_en") or None
        h1 = next((m.group("titulo") for s in cuerpo if (m := _RE_H1.match(s))), None)
        slug = re.sub(r"^\d{4}-\d{2}-\d{2}-?", "", Path(nombre).stem).replace("-", " ").strip() if nombre else ""
        r["tema"] = (meta.get("tema") or "").strip() or (h1 or "").strip() or (slug[:1].upper() + slug[1:] if slug else "Sin tema")
        if not meta.get("tema"):
            avisos.append("La cabecera no trae el tema; se usa el título o el nombre del fichero.")
        r["proyecto"] = (meta.get("proyecto") or "").strip() or proyecto_fuente or "Sin proyecto"

        insights, ilegibles, desconocidos, tuyos, consejos = [], 0, 0, [], []
        resumen_md: list[str] = []
        for norm, titulo, ls in secs:
            if norm == "insights" or norm.startswith("insights "):
                insights, ilegibles, desconocidos = _extraer_insights(ls)
            elif norm.startswith("tus comentarios"):
                tuyos, _, _ = _extraer_insights(ls, tu=True)
            elif norm == "asesor":   # respuestas sugeridas y consejos: solo los consejos son elementos del backlog (las preguntas del cliente no son tuyas)
                consejos += [i for i in _extraer_insights(ls)[0] if i["tipo"] == "consejo"]   # aparte: «## Asesor» va ANTES que «## Insights» en el .md y éste reasigna la lista
            elif norm.startswith("transcripcion"):
                for s in ls:
                    m = _RE_SEGMENTO.match(s)
                    if not m and s.strip().startswith("[línea omitida"):   # una línea con pinta de secreto que el Guardian sustituyó
                        r["transcripcion"].append({"t": None, "m": "", "f": "", "x": s.strip()})
                    elif m:
                        t = a_segundos(m.group("min"))
                        r["transcripcion"].append({"t": t, "m": a_mmss(t), "f": (m.group("fuente") or "").strip(": "), "x": m.group("texto").strip()})
            elif norm.startswith("definiciones"):
                for s in ls:
                    m = _RE_INSIGHT.match(s)
                    if m:
                        r["definiciones"].append({"minuto": None if m.group("min") in (None, "--:--") else m.group("min"),
                                                  "termino": _sin_enfasis(m.group("tipo")).rstrip(":"), "definicion": _sin_enfasis(m.group("resto"))})
            if titulo and norm not in ("insights", "transcripcion") and not norm.startswith("transcripcion") and not norm.startswith("insights"):
                cuerpo_md = "\n".join(ls).strip("\n")
                if cuerpo_md.strip() or norm != "resumen":
                    resumen_md.append(cuerpo_md if norm == "resumen" else f"## {titulo}\n\n{cuerpo_md}")
        r["resumen"] = "\n\n".join(x for x in resumen_md if x.strip()).strip()
        if ilegibles:
            avisos.append(f"{ilegibles} línea(s) de Insights no se pudieron leer.")
        if desconocidos:
            avisos.append(f"{desconocidos} insight(s) con un tipo que no es de la lista se han dejado fuera.")
        r["items"] = _unir(insights + consejos + tuyos, _extraer_resumen(secs))
        if not r["transcripcion"] and not any(n.startswith("transcripcion") for n, _, _ in secs):
            avisos.append("El fichero no tiene sección de transcripción.")
        if texto and str(texto).rstrip().endswith(_MARCA_RECORTE):
            avisos.append("El fichero es más grande que el tope de lectura: la transcripción está recortada.")
    except Exception as e:   # tolerancia total: un .md raro nunca rompe la lista
        avisos.append(f"No se pudo interpretar el fichero por completo ({type(e).__name__}).")
        r["tema"] = r["tema"] or (Path(nombre).stem if nombre else "Sin tema")
        r["proyecto"] = r["proyecto"] or proyecto_fuente or "Sin proyecto"
    return r


# ------------------------------------------------------------------ el backlog (fuentes, caché, estado local)
class _Escaneo:
    """Lectura de UNA carpeta en un hilo propio y demonio: si OneDrive no responde no bloquea ni impide cerrar la app."""

    def __init__(self, fuente: dict, funcion):
        self.fuente, self.listo, self.resultado = fuente, threading.Event(), None
        self.hilo = threading.Thread(target=self._correr, args=(funcion,), daemon=True, name="backlog-" + fuente["clave"][:20])
        self.hilo.start()

    def _correr(self, funcion):
        try:
            self.resultado = funcion(self.fuente)
        except Exception as e:   # nunca se propaga
            self.resultado = {"sesiones": [], "avisos": [f"«{self.fuente['etiqueta']}»: no se pudo leer ({type(e).__name__})."]}
        finally:
            self.listo.set()


class Backlog:
    def __init__(self, guardian, cfg=None, ahora=None, abridor=None, tiempo_fuente_s: float | None = None, tope_bytes: int | None = None):
        self.g = guardian
        self.cfg = cfg
        self.ahora = ahora or datetime.now
        self.abridor = abridor
        self.tiempo_fuente_s = TIEMPO_FUENTE_S if tiempo_fuente_s is None else tiempo_fuente_s
        self.tope_bytes = tope_bytes
        self._cache: dict[str, tuple[int, int, dict]] = {}       # ruta normalizada -> (mtime_ns, tamaño, registro)
        self._por_fuente: dict[str, dict] = {}                   # última lectura completa de cada carpeta
        self._en_curso: dict[str, _Escaneo] = {}
        self._carga = threading.Lock()
        self._estado_lock = threading.RLock()
        self._indice: dict | None = None
        self._aviso_estado_roto: str | None = None

    # ---------------------------------------------------------- lectura de carpetas
    def _tope(self) -> int:
        if self.tope_bytes:
            return self.tope_bytes
        try:
            return int(self.cfg["tope_fichero_bytes"]) if self.cfg is not None else 200_000
        except (KeyError, TypeError, ValueError):
            return 200_000

    def _escanear(self, fuente: dict) -> dict:
        avisos: list[str] = []
        sesiones: list[dict] = []
        carpeta = fuente["carpeta"]
        try:
            archivos, omitidos = self.g.listar_sesiones_md(carpeta)
        except (RutaProhibida, OSError) as e:
            return {"sesiones": [], "avisos": [f"«{fuente['etiqueta']}»: no se pudo abrir la carpeta ({e})."] if not isinstance(e, FileNotFoundError) else []}
        if omitidos:
            avisos.append(f"«{fuente['etiqueta']}»: {omitidos} fichero(s) omitido(s) por su nombre (pinta de secreto).")
        for ruta in archivos:
            clave = _norm_ruta(ruta)
            try:
                mtime, tam = self.g.estado_sesion_md(ruta, carpeta)
                hit = self._cache.get(clave)
                if hit and hit[0] == mtime and hit[1] == tam:
                    sesiones.append(hit[2])
                    continue
                texto = self.g.leer_sesion_md(ruta, carpeta, self._tope())
                p = parsear_sesion(texto, Path(ruta).name, fuente.get("proyecto"))
                rec = {**p, "ruta": str(ruta), "ruta_norm": clave, "base": str(carpeta), "archivo": Path(ruta).name, "origen": fuente["origen"],
                       "fuente": fuente["clave"], "mtime_ns": mtime, "mtime": mtime / 1e9, "tam": tam}
                self._cache[clave] = (mtime, tam, rec)
                sesiones.append(rec)
            except (RutaProhibida, OSError) as e:
                avisos.append(f"{Path(ruta).name}: no se pudo leer ({e}).")
            except Exception as e:
                avisos.append(f"{Path(ruta).name}: no se pudo interpretar ({type(e).__name__}).")
        return {"sesiones": sesiones, "avisos": avisos}

    def _leer_fuentes(self) -> tuple[list[dict], list[str]]:
        fuentes = self.g.fuentes_sesiones()
        for f in fuentes:
            e = self._en_curso.get(f["clave"])
            if e is not None and e.listo.is_set() and e.resultado is not None:
                self._por_fuente[f["clave"]] = e.resultado   # un escaneo lento que acabó después del tiempo acotado
            if e is None or e.listo.is_set():
                self._en_curso[f["clave"]] = _Escaneo(f, self._escanear)
        limite = time.monotonic() + max(0.0, self.tiempo_fuente_s)
        sesiones: list[dict] = []
        avisos: list[str] = []
        for f in fuentes:
            e = self._en_curso[f["clave"]]
            e.listo.wait(timeout=max(0.0, limite - time.monotonic()))
            if e.listo.is_set() and e.resultado is not None:
                self._por_fuente[f["clave"]] = e.resultado
                res = e.resultado
            else:
                res = self._por_fuente.get(f["clave"]) or {"sesiones": [], "avisos": []}
                avisos.append(f"«{f['etiqueta']}» tarda en responder (¿sin conexión?): se muestra lo ya leído; vuelve a abrir esta pantalla en unos segundos.")
            sesiones += res["sesiones"]
            avisos += res["avisos"]
        return sesiones, avisos

    # ---------------------------------------------------------- ensamblado
    def _estado_sesion(self, rec: dict, ahora: datetime) -> tuple[str, str]:
        raw = rec["estado_raw"]
        if raw.startswith("en curso"):
            try:
                inicio = datetime.fromisoformat(f"{rec['fecha']}T{rec['inicio']}") if rec["fecha"] and rec["inicio"] else None
            except ValueError:
                inicio = None
            antiguedad_h = ((ahora - inicio).total_seconds() if inicio else (ahora.timestamp() - rec["mtime"])) / 3600
            sin_escribir_min = (ahora.timestamp() - rec["mtime"]) / 60
            # Pasadas SIN_CERRAR_H horas de la hora de inicio, solo sigue «en curso» si el fichero se está escribiendo ahora; y con más de
            # SIN_CERRAR_SIEMPRE_H desde el inicio, nunca (una copia o la sincronización de OneDrive cambian la fecha de modificación).
            if antiguedad_h > SIN_CERRAR_H and (sin_escribir_min > ESCRITURA_RECIENTE_MIN or (inicio is not None and antiguedad_h > SIN_CERRAR_SIEMPRE_H)):
                return "sin_cerrar", "Sin cerrar"
            return "en_curso", "En curso"
        if raw.startswith("interrump"):
            return "interrumpida", "Interrumpida"
        if raw.startswith("finaliz"):
            return "finalizada", "Finalizada"
        return "otro", (raw.capitalize() if raw else "Sin estado")

    def _agrupar(self, recs: list[dict]) -> list[list[dict]]:
        """Una sesión compartida puede estar en local (sesiones\\) y publicada (02. Sesiones): se une por `publicada_en` y, si no, por
        proyecto+fecha+hora+tema entre copias de distinto origen."""
        padre = list(range(len(recs)))

        def raiz(i):
            while padre[i] != i:
                padre[i] = padre[padre[i]]
                i = padre[i]
            return i

        def unir(a, b):
            padre[raiz(a)] = raiz(b)

        por_ruta = {r["ruta_norm"]: k for k, r in enumerate(recs)}
        por_clave: dict[tuple, int] = {}
        for k, r in enumerate(recs):
            if r.get("publicada_en"):
                try:
                    destino = por_ruta.get(_norm_ruta(r["publicada_en"]))
                except (OSError, ValueError):
                    destino = None
                if destino is not None and destino != k:
                    unir(k, destino)
            if r["fecha"] and r["inicio"]:
                clave = (normalizar(r["proyecto"]), r["fecha"], r["inicio"], normalizar(r["tema"]))
                if clave in por_clave and (recs[por_clave[clave]]["origen"] == "local") != (r["origen"] == "local"):
                    unir(k, por_clave[clave])
                por_clave.setdefault(clave, k)
        grupos: dict[int, list[dict]] = {}
        for k, r in enumerate(recs):
            grupos.setdefault(raiz(k), []).append(r)
        return list(grupos.values())

    def _cargar_estado(self) -> dict:
        with self._estado_lock:
            vacio = {"version": 1, "items": {}, "temas": {}}
            try:
                texto = self.g.leer_backlog_estado()
            except RutaProhibida:
                return vacio
            except OSError:
                return vacio
            if texto is None:
                return vacio
            try:
                datos = json.loads(texto)
                if not isinstance(datos, dict) or not isinstance(datos.get("items", {}), dict) or not isinstance(datos.get("temas", {}), dict):
                    raise ValueError("forma inesperada")
            except (ValueError, TypeError):
                try:
                    nuevo = self.g.apartar_backlog_estado()
                    self._aviso_estado_roto = f"El estado local del backlog estaba dañado: se apartó como «{nuevo.name}» y se empieza de cero." if nuevo else None
                except (RutaProhibida, OSError):
                    self._aviso_estado_roto = "El estado local del backlog está dañado y no se pudo apartar; se ignora."
                return vacio
            datos.setdefault("items", {})
            datos.setdefault("temas", {})
            datos["version"] = 1
            return datos

    def _ensamblar(self, sesiones: list[dict], avisos: list[str]) -> dict:
        ahora = self.ahora()
        vistas: dict[str, dict] = {}
        for r in sesiones:
            vistas.setdefault(r["ruta_norm"], r)
        estado = self._cargar_estado()
        rank = {"publicada": 0, "proyecto": 1, "local": 2, "bandeja": 3}
        res_sesiones: dict[str, dict] = {}
        res_items: dict[str, dict] = {}
        alias: dict[str, str] = {}
        for grupo in self._agrupar(list(vistas.values())):
            grupo.sort(key=lambda r: (rank.get(r["origen"], 9), r["archivo"]))
            pref, otros = grupo[0], grupo[1:]
            sid = id_sesion(pref["ruta"])
            alias_sid = [id_sesion(o["ruta"]) for o in otros]
            for a in alias_sid:
                alias[a] = sid
            codigo, texto_estado = self._estado_sesion(pref, ahora)
            tema_guardado = None
            for k in [sid, *alias_sid]:
                t = estado["temas"].get(k)
                if isinstance(t, dict) and isinstance(t.get("tema"), str) and t["tema"].strip():
                    tema_guardado = t["tema"].strip()
                    break
            tema = tema_guardado or pref["tema"]
            vistos: dict[str, int] = {}
            items = []
            for orden, it in enumerate(sorted(pref["items"], key=lambda x: (a_segundos(x["minuto"]) is None, a_segundos(x["minuto"]) or 0))):
                clave = (it["tipo"], normalizar(it["texto"].rstrip("…. "))[:60])
                n = vistos.get(clave, 0)
                vistos[clave] = n + 1
                iid = id_item(pref["ruta"], it["tipo"], it["texto"], n)
                ids_alt = [id_item(o["ruta"], it["tipo"], it["texto"], n) for o in otros]
                guardado = None
                for k in [iid, *ids_alt]:
                    g = estado["items"].get(k)
                    if isinstance(g, dict) and g.get("estado") in ESTADOS.get(it["tipo"], ()):
                        guardado = g["estado"]
                        break
                t = a_segundos(it["minuto"])
                registro = {"id": iid, "sesion_id": sid, "tipo": it["tipo"], "etiqueta": ETIQUETA[it["tipo"]] + (" (posible)" if it["posible"] else ""),
                            "texto": it["texto"], "minuto": a_mmss(t) if t is not None else None, "t": t, "responsable": it["responsable"],
                            "contexto": it["contexto"], "origen": it["origen"], "posible": it["posible"], "recortado": it["recortado"],
                            "completado": bool(it.get("completado")),
                            "estados": list(ESTADOS.get(it["tipo"], ())),
                            "estado": guardado or ESTADO_INICIAL.get(it["tipo"])}
                items.append(registro)
                res_items[iid] = registro
                for a in ids_alt:
                    alias[a] = iid
            recuentos = {t: 0 for t in TIPOS}
            for it in items:
                recuentos[it["tipo"]] += 1
            aviso_s = list(pref["avisos"])
            vinculo = ({"archivo": otros[0]["archivo"], "origen": otros[0]["origen"]} if otros else None)
            res_sesiones[sid] = {
                "id": sid, "tema": tema, "tema_original": pref["tema"], "renombrado": bool(tema_guardado), "proyecto": pref["proyecto"],
                "fecha": pref["fecha"], "inicio": pref["inicio"], "duracion": a_mmss(pref["duracion_s"]), "duracion_s": pref["duracion_s"],
                "estado": codigo, "estado_texto": texto_estado, "estado_raw": pref["estado_raw"], "cadencia": pref["cadencia"],
                "origen": pref["origen"], "archivo": pref["archivo"], "vinculada": vinculo,
                "recuentos": recuentos, "total": len(items), "n_transcripcion": len(pref["transcripcion"]), "avisos": aviso_s,
                "_items": items, "_resumen": pref["resumen"], "_transcripcion": pref["transcripcion"], "_definiciones": pref["definiciones"],
                "_ruta": pref["ruta"], "_base": pref["base"]}
            for it in items:
                it.update(sesion_tema=tema, proyecto=pref["proyecto"], fecha=pref["fecha"], inicio=pref["inicio"], sesion_estado=codigo)
        orden = sorted(res_sesiones.values(), key=lambda s: (s["fecha"] or "", s["inicio"] or "", s["archivo"]), reverse=True)
        self._marcar_repetidos(orden)
        todos_avisos = list(avisos)
        if self._aviso_estado_roto:
            todos_avisos.append(self._aviso_estado_roto)
        return {"sesiones": {s["id"]: s for s in orden}, "orden": [s["id"] for s in orden], "items": res_items, "alias": alias, "avisos": todos_avisos}

    @staticmethod
    def _marcar_repetidos(orden: list[dict]) -> None:
        """El mismo pendiente dicho en varias sesiones del mismo proyecto (texto normalizado: minúsculas, sin acentos ni signos, espacios
        colapsados) sale UNA vez: el de la sesión más reciente (`orden` va de más reciente a más antigua), con `veces` = en cuántas sesiones
        salió. Los demás quedan con `duplicado: True` (siguen en su sesión, pero no cuentan en la lista conjunta ni en los recuentos del proyecto).
        No cierra nada: el estado de cada uno sigue siendo el suyo."""
        grupos: dict[tuple[str, str], list[dict]] = {}
        for s in orden:
            for it in s["_items"]:
                it["veces"], it["duplicado"] = 1, False
                if it["tipo"] != "pendiente":
                    continue
                clave = clave_repetido(it["texto"])
                if clave:
                    grupos.setdefault(((s["proyecto"] or "").lower(), clave), []).append(it)
        for its in grupos.values():
            sesiones = {it["sesion_id"] for it in its}
            its[0]["veces"] = len(sesiones)
            for it in its[1:]:
                it["duplicado"] = True

    def _indice_actual(self, refrescar: bool = True) -> dict:
        with self._carga:
            if self._indice is None or refrescar:
                recs, avisos = self._leer_fuentes()
                self._indice = self._ensamblar(recs, avisos)
            return self._indice

    # ---------------------------------------------------------- API
    @staticmethod
    def _publica(s: dict) -> dict:
        return {k: v for k, v in s.items() if not k.startswith("_")}

    def sesiones(self, refrescar: bool = True) -> dict:
        ix = self._indice_actual(refrescar)
        lista = []
        for i in ix["orden"]:
            s = ix["sesiones"][i]
            # texto normalizado de los elementos para el buscador de la lista (la transcripción no entra: se busca dentro de cada sesión)
            lista.append({**self._publica(s), "busqueda": normalizar(" ".join(it["texto"] for it in s["_items"]))[:20000]})
        proyectos = sorted({s["proyecto"] for s in lista}, key=str.lower)
        return {"sesiones": lista, "proyectos": proyectos, "avisos": ix["avisos"]}

    def resumen_proyectos(self, refrescar: bool = False, top: int = 5) -> dict[str, dict]:
        """Por proyecto (en minúsculas): pendientes abiertos (con el estado local ya aplicado), los `top` más recientes y la última sesión
        (`fecha`, `tema`, `id`). Solo lee la caché del índice (si no está cargada, la carga con los tiempos acotados de siempre)."""
        ix = self._indice_actual(refrescar)
        out: dict[str, dict] = {}
        for i in ix["orden"]:                      # de la más reciente a la más antigua
            s = ix["sesiones"][i]
            r = out.setdefault((s["proyecto"] or "").lower(), {"abiertos": 0, "pendientes": [], "ultima": None})
            if r["ultima"] is None:
                r["ultima"] = {"fecha": s["fecha"], "tema": s["tema"], "id": s["id"]}
            for it in s["_items"]:
                if it["tipo"] == "pendiente" and it["estado"] == "abierto" and not it.get("duplicado"):
                    r["abiertos"] += 1
                    if len(r["pendientes"]) < top:
                        r["pendientes"].append({"id": it["id"], "texto": it["texto"], "minuto": it["minuto"], "responsable": it["responsable"],
                                                "fecha": s["fecha"], "tema": s["tema"], "sesion_id": s["id"], "veces": it.get("veces", 1)})
        return out

    def items(self, refrescar: bool = False) -> dict:
        ix = self._indice_actual(refrescar)
        lista = [it for i in ix["orden"] for it in ix["sesiones"][i]["_items"] if not it.get("duplicado")]   # un pendiente repetido sale una vez (el más reciente)
        return {"items": lista, "tipos": [{"tipo": t, "etiqueta": ETIQUETA[t]} for t in TIPOS], "avisos": ix["avisos"]}

    def sesion(self, sid: str) -> dict | None:
        ix = self._indice_actual(False)
        s = ix["sesiones"].get(ix["alias"].get(sid, sid))
        if s is None:
            return None
        return {**self._publica(s), "resumen": s["_resumen"], "items": s["_items"], "transcripcion": s["_transcripcion"], "definiciones": s["_definiciones"]}

    def fijar_estado(self, iid: str, estado: str) -> dict | None:
        ix = self._indice_actual(False)
        it = ix["items"].get(ix["alias"].get(iid, iid))
        if it is None:
            return None
        posibles = ESTADOS.get(it["tipo"], ())
        if estado not in posibles:
            raise ValueError("Ese elemento solo se consulta." if not posibles else f"Estado no válido; usa uno de: {', '.join(posibles)}.")
        with self._estado_lock:
            datos = self._cargar_estado()
            if estado == ESTADO_INICIAL[it["tipo"]]:
                datos["items"].pop(it["id"], None)
            else:
                datos["items"][it["id"]] = {"estado": estado, "en": self.ahora().isoformat(timespec="seconds")}
            self.g.escribir_backlog_estado(json.dumps(datos, ensure_ascii=False, indent=1))
        it["estado"] = estado
        return it

    def fijar_tema(self, sid: str, tema: str) -> dict | None:
        ix = self._indice_actual(False)
        s = ix["sesiones"].get(ix["alias"].get(sid, sid))
        if s is None:
            return None
        limpio = re.sub(r"\s+", " ", re.sub(r"[\x00-\x1f\x7f]", " ", str(tema or ""))).strip()
        if len(limpio) > MAX_TEMA:
            raise ValueError(f"El tema no puede pasar de {MAX_TEMA} caracteres.")
        with self._estado_lock:
            datos = self._cargar_estado()
            if not limpio or limpio == s["tema_original"]:
                datos["temas"].pop(s["id"], None)
            else:
                datos["temas"][s["id"]] = {"tema": limpio, "en": self.ahora().isoformat(timespec="seconds")}
            self.g.escribir_backlog_estado(json.dumps(datos, ensure_ascii=False, indent=1))
        s["tema"] = limpio or s["tema_original"]
        s["renombrado"] = s["tema"] != s["tema_original"]
        for it in s["_items"]:
            it["sesion_tema"] = s["tema"]
        return self._publica(s)

    def abrir(self, sid: str) -> dict | None:
        """Abre el .md de una sesión ya listada con la aplicación del sistema. Solo se acepta un id de sesión conocido: nunca una ruta."""
        ix = self._indice_actual(False)
        s = ix["sesiones"].get(ix["alias"].get(sid, sid))
        if s is None:
            return None
        self.g.abrir_sesion_md(s["_ruta"], s["_base"], self.abridor)
        return {"ok": True, "archivo": s["archivo"]}
