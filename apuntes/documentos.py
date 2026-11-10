"""Texto de documentos de oficina para la recuperación local de fuentes (sin LLM, sin dependencias nuevas).

- `.docx` y `.pptx` son zips de XML: se lee solo el texto con `zipfile` (nada se ejecuta, nada se extrae a disco), con tope de tamaño por parte
  y de partes, contra zips «bomba».
- `.pdf` solo si hay una librería ya instalada (`pypdf`, `PyPDF2` o `fitz`); si no, `Indisponible`.
- Un fichero de OneDrive que aún no está descargado (marcador de la nube) NO se abre: abrirlo lo descargaría y podría colgar la app.
La seguridad de rutas (secretos, carpeta base) la aplica `Guardian.leer_documento`; aquí solo se extrae texto.
"""
from __future__ import annotations

import html
import re
import zipfile
from pathlib import Path

EXT_OFICINA = {".docx", ".pptx"}
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
    """Texto de un .docx, .pptx o .pdf. `Indisponible` si no se puede. `estructura` solo afecta a los .docx (ver `texto_docx`)."""
    ext = Path(ruta).suffix.lower()
    if ext == ".docx":
        return texto_docx(ruta, tope_chars, estructura)
    if ext == ".pptx":
        return texto_pptx(ruta, tope_chars)
    if ext == ".pdf":
        return texto_pdf(ruta, tope_chars)
    raise Indisponible(f"formato no admitido ({ext})")
