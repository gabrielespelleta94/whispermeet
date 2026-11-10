"""Texto de documentos de oficina para la recuperación local de fuentes (sin LLM, sin dependencias nuevas).

- `.docx` y `.pptx` son zips de XML: se lee solo el texto con `zipfile` (nada se ejecuta, nada se extrae a disco), con tope de tamaño por parte
  y de partes, contra zips «bomba».
- `.xlsx` y `.xlsm` (hojas de cálculo) igual, pero el XML se recorre en streaming con `expat`, con topes de hojas, filas, columnas y caracteres, y se rechaza
  cualquier parte con `<!DOCTYPE`/`<!ENTITY` (ver `texto_xlsx`).
- `.pdf` solo si hay una librería ya instalada (`pypdf`, `PyPDF2` o `fitz`); si no, `Indisponible`.
- Un fichero de OneDrive que aún no está descargado (marcador de la nube) NO se abre: abrirlo lo descargaría y podría colgar la app.
La seguridad de rutas (secretos, carpeta base) la aplica `Guardian.leer_documento`; aquí solo se extrae texto.
"""
from __future__ import annotations

import html
import math
import posixpath
import re
import zipfile
import zlib
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from xml.parsers import expat

EXT_HOJAS = {".xlsx", ".xlsm"}
EXT_OFICINA = {".docx", ".pptx"} | EXT_HOJAS
EXT_PDF = {".pdf"}
MAX_PARTE_BYTES = 12_000_000        # lo que se descomprime de cada parte XML (un zip que declare más se descarta)
MAX_PARTES = 400                    # diapositivas / partes que se leen como máximo
MAX_PAGINAS_PDF = 60

_RE_TEXTO = re.compile(r"<(?:w|a):t(?:\s[^>]*)?>([^<]*)</(?:w|a):t>")
_RE_FIN_PARRAFO = re.compile(r"</w:p>|</a:p>")
_RE_NUM = re.compile(r"(\d+)(?=\.xml$)")
_RE_FIN_BLOQUE = re.compile(r"(</w:p>|</w:tbl>)")
_RE_ESTILO = re.compile(r"<w:pStyle\b[^>]*?\bw:val=\"([^\"]*)\"")
_ESTILOS_TITULO = ("heading", "ttulo", "titulo", "título", "title")


class Indisponible(Exception):
    """El formato no se puede leer en esta máquina (p. ej. PDF sin librería) o el fichero no es legible."""


def en_la_nube(ruta: str | Path) -> bool:
    """True si es un marcador de OneDrive sin descargar (leerlo lo descargaría). Solo Windows; en otros sistemas, False."""
    import os
    try:
        attrs = getattr(os.stat(ruta), "st_file_attributes", 0)
    except OSError:
        return False
    return bool(attrs & (0x400000 | 0x40000 | 0x1000))   # RECALL_ON_DATA_ACCESS | RECALL_ON_OPEN | OFFLINE


def _xml_a_texto(xml: str) -> str:
    lineas = []
    for trozo in _RE_FIN_PARRAFO.split(xml):
        ts = _RE_TEXTO.findall(trozo)
        if ts:
            lineas.append("".join(html.unescape(t) for t in ts).strip())
    return "\n".join(l for l in lineas if l)


def _xml_a_texto_estructurado(xml: str) -> str:
    """Como `_xml_a_texto` para un .docx, pero conserva dos señales de estructura: los párrafos con estilo de título salen con `# ` (un `#` por nivel si el
    estilo lleva número, máximo 6) y tras cada tabla (`</w:tbl>`) sale una línea en blanco. Las demás líneas vacías se siguen descartando."""
    lineas: list[str] = []
    for trozo in _RE_FIN_BLOQUE.split(xml):
        if trozo == "</w:tbl>":
            if lineas and lineas[-1] != "":
                lineas.append("")
            continue
        if trozo == "</w:p>":
            continue
        ts = _RE_TEXTO.findall(trozo)
        if not ts:
            continue
        linea = "".join(html.unescape(t) for t in ts).strip()
        if not linea:
            continue
        estilo = _RE_ESTILO.search(trozo)
        if estilo and estilo.group(1).lower().startswith(_ESTILOS_TITULO):
            n = re.search(r"(\d+)\s*$", estilo.group(1))
            linea = "#" * max(1, min(6, int(n.group(1)) if n else 1)) + " " + linea
        lineas.append(linea)
    return "\n".join(lineas)


def _leer_parte(zf: zipfile.ZipFile, info: zipfile.ZipInfo) -> str:
    if info.file_size > MAX_PARTE_BYTES:
        return ""
    with zf.open(info) as f:
        return f.read(MAX_PARTE_BYTES).decode("utf-8", errors="replace")


def texto_docx(ruta: str | Path, tope_chars: int = 120_000, estructura: bool = False) -> str:
    """`estructura=True`: los títulos de Word salen como `# …` y cada tabla termina en una línea en blanco (ver `_xml_a_texto_estructurado`); por defecto, la
    salida es la de siempre."""
    try:
        with zipfile.ZipFile(ruta) as zf:
            nombres = {i.filename: i for i in zf.infolist()}
            if "word/document.xml" not in nombres:
                raise Indisponible("no es un .docx legible")
            xml = _leer_parte(zf, nombres["word/document.xml"])
            texto = _xml_a_texto_estructurado(xml) if estructura else _xml_a_texto(xml)
    except zipfile.BadZipFile as e:
        raise Indisponible("el .docx está dañado o protegido") from e
    return texto[:tope_chars]


def texto_pptx(ruta: str | Path, tope_chars: int = 120_000) -> str:
    try:
        with zipfile.ZipFile(ruta) as zf:
            def orden(i):
                m = _RE_NUM.search(i.filename)
                return int(m.group(1)) if m else 0
            diapos = sorted((i for i in zf.infolist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", i.filename)), key=orden)[:MAX_PARTES]
            notas = {orden(i): i for i in zf.infolist() if re.fullmatch(r"ppt/notesSlides/notesSlide\d+\.xml", i.filename)}
            if not diapos:
                raise Indisponible("no es un .pptx legible")
            salida, total = [], 0
            for n, info in enumerate(diapos, 1):
                t = _xml_a_texto(_leer_parte(zf, info))
                nota = notas.get(orden(info))
                if nota is not None:
                    tn = _xml_a_texto(_leer_parte(zf, nota))
                    if tn:
                        t = (t + "\nNotas: " + tn).strip()
                if t:
                    bloque = f"[Diapositiva {n}]\n{t}"
                    salida.append(bloque)
                    total += len(bloque)
                    if total >= tope_chars:
                        break
    except zipfile.BadZipFile as e:
        raise Indisponible("el .pptx está dañado o protegido") from e
    return "\n\n".join(salida)[:tope_chars]


# ---------------------------------------------------------------- .xlsx / .xlsm (hojas de cálculo)
# Solo celdas: nada del libro se ejecuta (ni macros, ni fórmulas, ni vínculos externos) y no se extrae nada a disco. El XML se recorre en STREAMING con `expat`
# (no se construye ningún árbol) y se deja de leer en cuanto se alcanza un tope; cualquier parte con `<!DOCTYPE` o `<!ENTITY` se rechaza.
MAX_HOJAS = 20                      # hojas visibles que se leen como máximo
MAX_FILAS_HOJA = 2_000              # filas (elementos `<row>`) que se leen de cada hoja
MAX_COLUMNAS_HOJA = 40              # columnas que se leen de cada fila
MAX_CHARS_CELDA = 300               # caracteres que se conservan de cada celda
MAX_CADENAS = 100_000               # cadenas compartidas que se cargan (las demás celdas de texto quedan vacías y se dice)
MAX_ENTRADAS_ZIP = 20_000           # entradas del zip por encima de las cuales el libro no se abre
MAX_CELDAS_HOJA = 200_000           # elementos `<c>` que se analizan de cada hoja (más allá se corta la hoja)
MAX_BYTES_LIBRO = 24_000_000        # bytes descomprimidos que se leen de las hojas de un libro entre todas (las que quedan no se leen)
_TROZO = 65_536
_RE_PROHIBIDO = re.compile(rb"<!(?:doctype|entity)", re.I)
_RE_ESCAPE_X = re.compile(r"_x([0-9A-Fa-f]{4})_")
_RE_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\ud800-\udfff\ufffe\uffff]")   # controles, sustitutos sueltos y no caracteres: no se pueden codificar
_RE_FECHA_ISO = re.compile(r"(\d{4}-\d{2}-\d{2})(?:[T ](\d{2}:\d{2})(?::\d{2}(?:[.,]\d+)?)?)?")
_RE_ENTERO = re.compile(r"-?\d+")
_RE_COLUMNA = re.compile(r"^([A-Za-z]{1,3})")
_RE_FORMATO_NO_FECHA = re.compile(r"\"[^\"]*\"|\[[^\]]*\]|\\.|_.|\*.|general", re.I)
# formatos integrados de Excel que son de fecha y/u hora (14-22, 27-36, 45-47 y 50-58) y, de ellos, los de solo hora y el de fecha con hora
_FORMATOS_FECHA = frozenset(range(14, 23)) | frozenset(range(27, 37)) | frozenset({45, 46, 47}) | frozenset(range(50, 59))
_FORMATOS_HORA = frozenset({18, 19, 20, 21, 32, 33, 34, 35, 45, 46, 47})


class _Parar(Exception):
    """Se alcanzó un tope: se deja de leer la parte (no es un error)."""


class _ParteGrande(Exception):
    """La parte declara o entrega más de `MAX_PARTE_BYTES`."""


def _local(nombre: str) -> str:
    return nombre.rpartition("|")[2]


def _analizar_parte(zf: zipfile.ZipFile, info: zipfile.ZipInfo, enlazar, estricta: bool = True, tope: int | None = None, contar: list | None = None) -> bool:
    """Recorre una parte XML en streaming. `enlazar(parser)` pone los manejadores; si uno lanza `_Parar` se deja de leer. Nunca se descomprimen más de `MAX_PARTE_BYTES` bytes.
    `estricta`: si la parte DECLARA más de ese tamaño ni se abre (`_ParteGrande`); si no, se lee hasta el tope y, si hay más, `_ParteGrande` salta al llegar a él (con lo ya
    leído entregado a los manejadores). Devuelve True si se leyó entera. Una declaración `<!DOCTYPE`/`<!ENTITY` (en cualquier codificación) es `Indisponible`, y una
    codificación XML que `expat` no admite también. `tope`: otro límite de bytes más bajo que `MAX_PARTE_BYTES`; `contar[0]` suma los bytes descomprimidos que se leen."""
    if estricta and info.file_size > MAX_PARTE_BYTES:
        raise _ParteGrande()
    limite = MAX_PARTE_BYTES if tope is None else min(MAX_PARTE_BYTES, tope)

    def prohibido(*_args):
        raise Indisponible("el libro lleva una declaración XML que no se admite")

    p = expat.ParserCreate(None, "|")
    p.buffer_text = True
    p.buffer_size = _TROZO
    p.StartDoctypeDeclHandler = prohibido
    p.EntityDeclHandler = prohibido
    enlazar(p)
    leidos, cola = 0, b""
    try:
        with zf.open(info) as f:
            while True:
                resto = limite - leidos
                if resto <= 0:
                    if f.read(1):
                        raise _ParteGrande()
                    break
                trozo = f.read(min(_TROZO, resto))
                if not trozo:
                    break
                leidos += len(trozo)
                if contar is not None:
                    contar[0] += len(trozo)
                if _RE_PROHIBIDO.search(cola + trozo):
                    prohibido()
                cola = trozo[-9:]
                p.Parse(trozo, False)
            p.Parse(b"", True)
    except _Parar:
        return False
    except expat.ExpatError as e:
        raise Indisponible("el libro tiene XML dañado") from e
    except (LookupError, ValueError) as e:   # `encoding="foo"` desconocida / `utf-7`, `utf-32`, `shift_jis`…: expat no las admite
        raise Indisponible("el libro usa una codificación que no se admite") from e
    return True


def _limpio(s: str) -> str:
    """Texto de una celda: escapes `_x000D_` de OOXML resueltos, saltos de línea y tabuladores como un espacio, sin caracteres de control."""
    if "_x" in s:
        s = _RE_ESCAPE_X.sub(lambda m: chr(int(m.group(1), 16)), s)
    s = s.replace("\r\n", " ").replace("\r", " ").replace("\n", " ").replace("\t", " ")
    return _RE_CONTROL.sub("", s).strip()


def _columna(ref: str | None, anterior: int) -> int:
    """Índice (desde 0) de la columna de una referencia «B7»; sin referencia, la siguiente a la anterior."""
    m = _RE_COLUMNA.match(ref or "")
    if not m:
        return anterior + 1
    n = 0
    for c in m.group(1).upper():
        n = n * 26 + ord(c) - 64
    return n - 1


def _clase_codigo(codigo: str) -> str | None:
    """«fecha», «hora», «fechahora» o None para el código de un formato de número propio. Cuentan las fichas de fecha u hora fuera de comillas y corchetes
    (`[h]` de horas transcurridas incluido); `m` solo es minuto junto a una hora o unos segundos. Un formato de solo horas transcurridas es «transcurrido» y uno con
    `%` (y sin fecha ni hora) es «porcentaje»."""
    bajo = codigo.lower()
    transcurrido = bool(re.search(r"\[(?:h+|m+|s+)\]", bajo))
    hora = transcurrido or "am/pm" in bajo or "a/p" in bajo
    s = _RE_FORMATO_NO_FECHA.sub("", bajo).replace("am/pm", "").replace("a/p", "").split(";")[0]
    fecha = "y" in s or "d" in s
    hora = hora or "h" in s or "s" in s
    if "m" in s and not (fecha or hora):
        fecha = True
    if fecha and hora:
        return "fechahora"
    if fecha:
        return "fecha"
    if hora:
        return "transcurrido" if transcurrido else "hora"
    return "porcentaje" if "%" in s else None


def _clase_formato(i: int, propios: dict[int, str]) -> str | None:
    if i in propios:
        return _clase_codigo(propios[i])
    if i in (9, 10):
        return "porcentaje"
    if i in _FORMATOS_FECHA:
        return "transcurrido" if i == 46 else "hora" if i in _FORMATOS_HORA else "fechahora" if i == 22 else "fecha"
    return None


def _dia(n: int, d1904: bool) -> str | None:
    """Fecha `AAAA-MM-DD` del número de día de Excel (con el 29-02-1900 que Excel da por bueno sin existir)."""
    if d1904:
        base = date(1904, 1, 1)
    elif n == 0:
        return "1900-01-00"
    elif n == 60:
        return "1900-02-29"
    else:
        base = date(1899, 12, 31) if n < 60 else date(1899, 12, 30)
    try:
        return (base + timedelta(days=n)).isoformat()
    except OverflowError:
        return None


def _numero(texto: str) -> str:
    """Un número sin ceros de sobra: `12` y no `12.0`. Un no entero se redondea a 6 decimales (`0.153846154` y no `0.153846153846154`: así no parece un teléfono); si no es 0 y
    su valor absoluto es menor que 0,001 se escriben 6 cifras significativas para no convertirlo en 0."""
    if _RE_ENTERO.fullmatch(texto):
        try:
            return str(int(texto))   # un entero se conserva exacto (identificadores largos)
        except ValueError:           # más de 4.300 cifras: se deja como texto
            return texto
    try:
        v = float(texto)
    except ValueError:
        return texto
    if not math.isfinite(v):
        return texto
    s = "%.6g" % v if v and abs(v) < 0.001 else "%.15g" % round(v, 6)
    if "e" in s:
        try:
            plano = format(Decimal(s), "f")
            if len(plano) <= 30:
                s = plano
        except ArithmeticError:
            pass
    return "0" if s in ("-0", "-0.0") else s


def _valor_numerico(texto: str, clase: str | None, d1904: bool) -> str:
    texto = texto.strip()
    if not texto:
        return ""
    if clase is None:
        return _numero(texto)
    try:
        v = float(texto)
    except ValueError:
        return texto
    if clase == "porcentaje":
        if not math.isfinite(v):
            return _numero(texto)
        p = ("%.2f" % (v * 100)).rstrip("0").rstrip(".")
        return ("0" if p in ("", "-0") else p) + "%"
    if not math.isfinite(v) or v < 0:
        return _numero(texto)
    minutos = round(v * 1440)
    if clase == "transcurrido":
        return f"{minutos // 60:02d}:{minutos % 60:02d}"
    if clase == "hora":
        minutos %= 1440
        return f"{minutos // 60:02d}:{minutos % 60:02d}"
    if clase == "fecha":
        return _dia(int(math.floor(v)), d1904) or _numero(texto)
    dia, resto = divmod(minutos, 1440)
    d = _dia(dia, d1904)
    if d is None:
        return _numero(texto)
    return d if resto == 0 else f"{d} {resto // 60:02d}:{resto % 60:02d}"


def _libro(zf: zipfile.ZipFile, info: zipfile.ZipInfo) -> tuple[bool, list[tuple[str, str, str]]]:
    """`xl/workbook.xml` -> (sistema de fechas 1904, [(nombre, estado, id de relación)]) en el orden del libro."""
    hojas: list[tuple[str, str, str]] = []
    est = {"1904": False}

    def inicio(nombre, atr):
        n = _local(nombre)
        if n == "workbookPr":
            est["1904"] = str(atr.get("date1904", "")).lower() in ("1", "true", "on")
        elif n == "sheet":
            rid = next((v for k, v in atr.items() if _local(k) == "id"), "")
            hojas.append((atr.get("name", ""), atr.get("state", "visible"), rid))

    _analizar_parte(zf, info, lambda p: setattr(p, "StartElementHandler", inicio))
    return est["1904"], hojas


def _relaciones(zf: zipfile.ZipFile, info: zipfile.ZipInfo, otros: dict[str, str] | None = None) -> dict[str, str]:
    """`xl/_rels/workbook.xml.rels` -> {id de relación: ruta de la hoja en el zip}; solo hojas de cálculo (no gráficos ni macros). Si se pasa `otros`, se rellena con la ruta de
    las cadenas compartidas («sharedStrings») y de los estilos («styles») que declaran las relaciones."""
    rels: dict[str, str] = {}

    def inicio(nombre, atr):
        if _local(nombre) == "Relationship" and atr.get("TargetMode") != "External":
            tipo = atr.get("Type", "")
            destino = atr.get("Target", "")
            ruta = posixpath.normpath(destino.lstrip("/") if destino.startswith("/") else "xl/" + destino)
            if tipo.endswith("/worksheet"):
                rels[atr.get("Id", "")] = ruta
            elif otros is not None:
                for clave in ("sharedStrings", "styles"):
                    if tipo.endswith("/" + clave):
                        otros.setdefault(clave, ruta)

    _analizar_parte(zf, info, lambda p: setattr(p, "StartElementHandler", inicio))
    return rels


def _parte(partes: dict[str, zipfile.ZipInfo], otros: dict[str, str], clave: str, habitual: str) -> zipfile.ZipInfo | None:
    """La parte de un tipo: la que declaran las relaciones, si no la de nombre habitual y, si tampoco, esa misma sin distinguir mayúsculas."""
    for ruta in (otros.get(clave), habitual):
        if ruta in partes:
            return partes[ruta]
    bajo = habitual.lower()
    return next((i for k, i in partes.items() if k.lower() == bajo), None)


def _estilos(zf: zipfile.ZipFile, info: zipfile.ZipInfo) -> list[str | None]:
    """`xl/styles.xml` -> por cada estilo de celda (`cellXfs`), su clase de fecha: «fecha», «hora», «fechahora» o None."""
    propios: dict[int, str] = {}
    xfs: list[int] = []
    est = {"fmts": False, "xfs": False}

    def inicio(nombre, atr):
        n = _local(nombre)
        if n == "numFmts":
            est["fmts"] = True
        elif n == "cellXfs":
            est["xfs"] = True
        elif n == "numFmt" and est["fmts"]:
            try:
                propios[int(atr.get("numFmtId", ""))] = atr.get("formatCode", "")
            except ValueError:
                pass
        elif n == "xf" and est["xfs"]:
            try:
                xfs.append(int(atr.get("numFmtId", "0")))
            except ValueError:
                xfs.append(0)

    def fin(nombre):
        n = _local(nombre)
        if n == "numFmts":
            est["fmts"] = False
        elif n == "cellXfs":
            est["xfs"] = False

    def enlazar(p):
        p.StartElementHandler, p.EndElementHandler = inicio, fin

    _analizar_parte(zf, info, enlazar)
    return [_clase_formato(i, propios) for i in xfs]


def _cadenas(zf: zipfile.ZipFile, info: zipfile.ZipInfo) -> tuple[list[str], bool]:
    """`xl/sharedStrings.xml` -> (cadenas, recortado). Texto simple y con formato (varios tramos `<r>`); las guías fonéticas `<rPh>` se ignoran."""
    lista: list[str] = []
    est = {"si": False, "t": False, "rph": 0, "recortado": False}
    trozos: list[str] = []

    def inicio(nombre, atr):
        n = _local(nombre)
        if n == "si":
            est["si"], est["rph"] = True, 0
            trozos.clear()
        elif n == "rPh":
            est["rph"] += 1
        elif n == "t" and est["si"] and est["rph"] == 0:
            est["t"] = True

    def texto(s):
        if est["t"]:
            trozos.append(s)

    def fin(nombre):
        n = _local(nombre)
        if n == "t":
            est["t"] = False
        elif n == "rPh":
            est["rph"] -= 1
        elif n == "si":
            est["si"] = False
            lista.append(_limpio("".join(trozos))[:MAX_CHARS_CELDA + 1])
            if len(lista) >= MAX_CADENAS:
                est["recortado"] = True
                raise _Parar()

    def enlazar(p):
        p.StartElementHandler, p.EndElementHandler, p.CharacterDataHandler = inicio, fin, texto

    _analizar_parte(zf, info, enlazar)
    return lista, est["recortado"]


def _linea(fila: dict[int, str]) -> str:
    linea = " | ".join(fila.get(c, "") for c in range(max(fila) + 1))
    # una fila que empieza por «#» no debe leerse como un encabezado de Markdown (cortaría el filtro de las hojas de contactos): se escapa
    return "\\" + linea if linea.startswith("#") else linea


def _leer_hoja(zf: zipfile.ZipFile, info: zipfile.ZipInfo, cadenas: list[str], estilos: list[str | None], d1904: bool, presupuesto: int,
               contar: list | None = None, tope_bytes: int | None = None) -> tuple[list[str], set[str]]:
    """Una hoja de cálculo -> (líneas de texto, avisos de recorte). Una línea por fila con valores (las celdas unidas por « | », huecos conservados, vacías del final fuera);
    `presupuesto`: caracteres que quedan en total (al agotarse, el aviso «texto»). Se deja de leer en cuanto se alcanza un tope (también `MAX_CELDAS_HOJA`).
    `contar`/`tope_bytes`: ver `_analizar_parte`."""
    lineas: list[str] = []
    avisos: set[str] = set()
    e: dict = {"filas": 0, "fila": None, "col": -1, "celda": None, "tipo": "", "estilo": None, "v": [], "t": [], "en_v": False, "en_is": False, "en_t": False, "rph": 0, "usado": 0, "celdas": 0}

    def inicio(nombre, atr):
        n = _local(nombre)
        if n == "row":
            e["filas"] += 1
            if e["filas"] > MAX_FILAS_HOJA:
                avisos.add("filas")
                raise _Parar()
            e["fila"], e["col"] = {}, -1
        elif n == "c":
            e["celdas"] += 1
            if e["celdas"] > MAX_CELDAS_HOJA:
                avisos.add("grande")
                raise _Parar()
            if e["fila"] is None:
                return
            c = _columna(atr.get("r"), e["col"])
            e["col"] = c
            e["celda"], e["tipo"], e["estilo"] = c, atr.get("t", "n"), atr.get("s")
            e["v"], e["t"], e["rph"] = [], [], 0
        elif e["celda"] is not None:
            if n == "v":
                e["en_v"] = True
            elif n == "is":
                e["en_is"] = True
            elif n == "rPh":
                e["rph"] += 1
            elif n == "t" and e["en_is"] and e["rph"] == 0:
                e["en_t"] = True

    def texto(s):
        if e["en_v"]:
            e["v"].append(s)
        elif e["en_t"]:
            e["t"].append(s)

    def valor() -> str:
        tipo = e["tipo"]
        if tipo == "s":
            try:
                i = int(("".join(e["v"])).strip())
                return cadenas[i] if i >= 0 else ""
            except (ValueError, IndexError):
                return ""
        if tipo == "inlineStr":
            return _limpio("".join(e["t"]))
        if tipo == "d":
            m = _RE_FECHA_ISO.match("".join(e["v"]).strip())
            if m:
                return m.group(1) if m.group(2) in (None, "00:00") else f"{m.group(1)} {m.group(2)}"
        if tipo in ("str", "d"):
            return _limpio("".join(e["v"]))
        if tipo == "b":
            v = "".join(e["v"]).strip().lower()
            return "" if not v else "sí" if v in ("1", "true") else "no"
        if tipo == "e":
            return ""
        clase = None
        if e["estilo"] is not None:
            try:
                i = int(e["estilo"])
                clase = estilos[i] if i >= 0 else None
            except (ValueError, IndexError):
                clase = None
        return _valor_numerico("".join(e["v"]), clase, d1904)

    def fin(nombre):
        n = _local(nombre)
        if n == "v":
            e["en_v"] = False
        elif n == "t":
            e["en_t"] = False
        elif n == "is":
            e["en_is"] = False
        elif n == "rPh":
            e["rph"] = max(0, e["rph"] - 1)
        elif n == "c":
            if e["celda"] is not None:
                v = valor()
                if v and e["celda"] >= MAX_COLUMNAS_HOJA:
                    avisos.add("columnas")   # una columna de más con valor: se avisa; las celdas vacías de más (solo con formato) no cuentan
                elif v:
                    if len(v) > MAX_CHARS_CELDA:
                        v = v[:MAX_CHARS_CELDA] + "…"
                        avisos.add("celdas")
                    e["fila"][e["celda"]] = v
                e["celda"] = None
        elif n == "row":
            fila, e["fila"] = e["fila"], None
            if fila:
                linea = _linea(fila)
                if e["usado"] + len(linea) + 1 > presupuesto:
                    avisos.add("texto")
                    raise _Parar()
                lineas.append(linea)
                e["usado"] += len(linea) + 1

    def enlazar(p):
        p.StartElementHandler, p.EndElementHandler, p.CharacterDataHandler = inicio, fin, texto

    try:
        _analizar_parte(zf, info, enlazar, estricta=False, tope=tope_bytes, contar=contar)
    except _ParteGrande:
        avisos.add("grande")
    return lineas, avisos


_AVISOS_HOJA = (("filas", "(hoja recortada: quedan más filas)"),
                ("columnas", f"(hoja recortada: hay más de {MAX_COLUMNAS_HOJA} columnas)"),
                ("celdas", f"(hoja recortada: hay celdas de más de {MAX_CHARS_CELDA} caracteres)"),
                ("grande", "(hoja recortada: es demasiado grande para leerla entera)"))
_AVISO_TEXTO = "(texto recortado: se alcanzó el tope de caracteres)"
_AVISO_BYTES = "(libro recortado: es demasiado grande para leerlo entero)"
_AVISO_HOJAS = "(libro recortado: quedan más hojas)"
_AVISO_CADENAS = "(libro recortado: hay más cadenas de texto de las que se leen)"
_HOJA_VACIA = "(hoja vacía)"


def texto_xlsx(ruta: str | Path, tope_chars: int = 120_000) -> str:
    """Texto de un `.xlsx` o `.xlsm` (solo las celdas; también se lee igual un libro con macros, que no se ejecutan). Por cada hoja VISIBLE, una línea `## Hoja: nombre` y una
    línea por fila con valores, con las celdas unidas por « | » (una vacía entre dos con valor se conserva; las del final, no). Las fechas salen `AAAA-MM-DD` (con ` HH:MM` si
    llevan hora), los porcentajes multiplicados por 100 con su `%`, los decimales a 6 cifras, de una fórmula se toma el valor guardado y las hojas ocultas no se leen (se cuentan
    al final, igual que las visibles cuya parte falta). Topes: `MAX_HOJAS`, `MAX_FILAS_HOJA`, `MAX_COLUMNAS_HOJA`, `MAX_CELDAS_HOJA`, `MAX_BYTES_LIBRO`, `MAX_CHARS_CELDA` y
    `tope_chars`; lo que se recorta se dice en una línea y esas líneas nunca se parten. `Indisponible` si el fichero no es un libro legible (cifrado, dañado, sin hojas…)."""
    try:
        with zipfile.ZipFile(ruta) as zf:
            infos = zf.infolist()
            if len(infos) > MAX_ENTRADAS_ZIP:
                raise Indisponible("el libro tiene demasiadas partes")
            partes = {i.filename: i for i in infos}
            if "xl/workbook.xml" not in partes:
                raise Indisponible("no es un .xlsx legible")
            try:
                d1904, hojas = _libro(zf, partes["xl/workbook.xml"])
                otros: dict[str, str] = {}
                rels = _relaciones(zf, partes["xl/_rels/workbook.xml.rels"], otros) if "xl/_rels/workbook.xml.rels" in partes else {}
                todas = [(nombre, rels.get(rid)) for nombre, estado, rid in hojas if estado == "visible"]
                visibles = [(nombre, r) for nombre, r in todas if r in partes]
                sin_parte = len(todas) - len(visibles)
                ocultas = sum(1 for _n, estado, _r in hojas if estado != "visible")
                if not visibles:
                    raise Indisponible("el libro no tiene hojas legibles")
                cadenas, cadenas_recortadas = [], False
                info_cadenas = _parte(partes, otros, "sharedStrings", "xl/sharedStrings.xml")
                if info_cadenas is not None:
                    cadenas, cadenas_recortadas = _cadenas(zf, info_cadenas)
                info_estilos = _parte(partes, otros, "styles", "xl/styles.xml")
                estilos = _estilos(zf, info_estilos) if info_estilos is not None else []
            except _ParteGrande as e:
                raise Indisponible("el libro es demasiado grande para leerlo") from e
            tope_hojas = min(MAX_HOJAS, MAX_PARTES)
            mas_hojas = len(visibles) > tope_hojas
            # avisos que van al final: los que ya se conocen y los que pueden aparecer al leer; su sitio se reserva de antemano para que ninguno se corte
            conocidos = [a for a, hay in ((_AVISO_HOJAS, mas_hojas), (_AVISO_CADENAS, cadenas_recortadas),
                                          (f"({sin_parte} hoja no se pudo leer)" if sin_parte == 1 else f"({sin_parte} hojas no se pudieron leer)", sin_parte),
                                          (f"({ocultas} hoja oculta sin leer)" if ocultas == 1 else f"({ocultas} hojas ocultas sin leer)", ocultas)) if hay]
            reserva = sum(len(a) + 1 for a in conocidos + [_AVISO_TEXTO, _AVISO_BYTES])
            reserva_hoja = sum(len(a) + 1 for _c, a in _AVISOS_HOJA) + len(_HOJA_VACIA) + 1
            disponible = tope_chars - reserva
            salida: list[str] = []
            usado, agotado, recortado_bytes, contador = 0, False, False, [0]
            for n, (nombre, ruta_hoja) in enumerate(visibles[:tope_hojas]):
                if contador[0] >= MAX_BYTES_LIBRO:
                    recortado_bytes = True
                    break
                cabecera = "## Hoja: " + (_limpio(nombre)[:100] or str(n + 1))
                if usado + len(cabecera) + 1 > disponible:
                    agotado = True
                    break
                lineas, avisos = _leer_hoja(zf, partes[ruta_hoja], cadenas, estilos, d1904, disponible - usado - len(cabecera) - 1 - reserva_hoja,
                                            contador, MAX_BYTES_LIBRO - contador[0])
                salida.append(cabecera)
                usado += len(cabecera) + 1
                cuerpo = lineas or ([] if "texto" in avisos else [_HOJA_VACIA])
                cuerpo += [texto for clave, texto in _AVISOS_HOJA if clave in avisos]
                salida += cuerpo
                usado += sum(len(x) + 1 for x in cuerpo)
                if "texto" in avisos:
                    agotado = True
                    break
    except zipfile.BadZipFile as e:
        raise Indisponible("el .xlsx está dañado o protegido") from e
    except (zlib.error, EOFError, NotImplementedError, RuntimeError) as e:
        raise Indisponible("el .xlsx está dañado o protegido") from e
    except (Indisponible, OSError):
        raise
    except Exception as e:  # noqa: BLE001 — un libro raro nunca debe tumbar una pasada entera (quien llama solo trata Indisponible y OSError)
        raise Indisponible("no se pudo leer el libro") from e
    finales = ([_AVISO_TEXTO] if agotado else []) + ([_AVISO_BYTES] if recortado_bytes else []) + conocidos
    while salida and len("\n".join(salida + finales)) > tope_chars:   # nunca se parte una línea: si no cabe, se quitan líneas enteras del cuerpo
        salida.pop()
    while finales and len("\n".join(salida + finales)) > tope_chars:
        finales.pop()
    return "\n".join(salida + finales)


_PDF: list = []


def libreria_pdf() -> str | None:
    """Nombre de la librería de PDF ya instalada, o None (no se instala nada). Se mira una vez."""
    if _PDF:
        return _PDF[0]
    hallada = None
    for nombre in ("pypdf", "PyPDF2", "fitz"):
        try:
            __import__(nombre)
            hallada = nombre
            break
        except Exception:  # noqa: BLE001 — una librería rota cuenta como ausente
            continue
    _PDF.append(hallada)
    return hallada


def texto_pdf(ruta: str | Path, tope_chars: int = 120_000) -> str:
    lib = libreria_pdf()
    if lib is None:
        raise Indisponible("no hay librería de PDF instalada (pypdf, PyPDF2 o PyMuPDF)")
    partes, total = [], 0
    try:
        if lib == "fitz":
            import fitz  # type: ignore
            with fitz.open(str(ruta)) as doc:
                paginas = (p.get_text() for p in list(doc)[:MAX_PAGINAS_PDF])
                for t in paginas:
                    partes.append(t)
                    total += len(t)
                    if total >= tope_chars:
                        break
        else:
            mod = __import__(lib)
            lector = mod.PdfReader(str(ruta))
            if getattr(lector, "is_encrypted", False):
                raise Indisponible("el PDF está protegido con contraseña")
            for p in list(lector.pages)[:MAX_PAGINAS_PDF]:
                t = p.extract_text() or ""
                partes.append(t)
                total += len(t)
                if total >= tope_chars:
                    break
    except Indisponible:
        raise
    except Exception as e:  # noqa: BLE001
        raise Indisponible(f"no se pudo leer el PDF ({type(e).__name__})") from e
    return "\n".join(partes)[:tope_chars]


def texto_de(ruta: str | Path, tope_chars: int = 120_000, estructura: bool = False) -> str:
    """Texto de un .docx, .pptx, .xlsx, .xlsm o .pdf. `Indisponible` si no se puede. `estructura` solo afecta a los .docx (ver `texto_docx`)."""
    ext = Path(ruta).suffix.lower()
    if ext == ".docx":
        return texto_docx(ruta, tope_chars, estructura)
    if ext == ".pptx":
        return texto_pptx(ruta, tope_chars)
    if ext in EXT_HOJAS:
        return texto_xlsx(ruta, tope_chars)
    if ext == ".pdf":
        return texto_pdf(ruta, tope_chars)
    raise Indisponible(f"formato no admitido ({ext})")
