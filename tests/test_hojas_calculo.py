"""Hojas de cálculo como contexto (ola E): el lector `.xlsx`/`.xlsm` de `documentos.py` (solo biblioteca estándar: tipos de celda, fechas, hojas ocultas, topes,
seguridad frente a zips y XML maliciosos, tiempo) y quién lo consume: Guardian, Agente Archivero (datos personales), «Proponer plan» y la recuperación de fuentes.
Los libros se construyen aquí con `zipfile` (las partes mínimas) y datos ficticios; ninguna llamada real al modelo."""
import html
import json
import os
import time
import zipfile
from datetime import date
from pathlib import Path

import pytest

from apuntes import archivero as AR
from apuntes import documentos as DOC
from apuntes import fuentes as FU
from apuntes import inventario as INV
from apuntes import plan_propuesto as PP
from apuntes.analisis import ErrorAnalisis, ModeloLLM, Respuesta, Uso
from apuntes.analisis.analista import Analista
from apuntes.config import Config
from apuntes.consumo import Consumo
from apuntes.rutas import CARPETA_SESIONES, Guardian, RutaProhibida

SS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
NS = f'xmlns="{SS}" xmlns:r="{REL}"'
PROY = "Alfa Demo"
DIA = 86400

# estilos de celda del libro de prueba (posición en cellXfs)
GENERAL, FECHA, FECHA_HORA, HORA, DMY, KG, LARGO, ISO_HORA, DIA_TEXTO, TRANSCURRIDO, MES, PCT9, PCT10, PCT_PROPIO, PCT_COMILLAS, HORA_PROPIA, TRANS46, TRANS_HH = range(18)
_FORMATOS = {164: "dd/mm/yyyy", 165: '0.00" kg"', 166: r"[$-F800]dddd\, mmmm dd\, yyyy", 167: "yyyy-mm-dd hh:mm", 168: '"día" 0', 169: "[h]:mm:ss", 170: "mmm-yy",
            171: "0.0%", 172: '0" %"', 173: "hh:mm", 174: "[hh]:mm"}
_XF = [0, 14, 22, 20, 164, 165, 166, 167, 168, 169, 170, 9, 10, 171, 172, 173, 46, 174]


def estilos_xml() -> str:
    fmts = "".join(f'<numFmt numFmtId="{i}" formatCode="{html.escape(c)}"/>' for i, c in _FORMATOS.items())
    xfs = "".join(f'<xf numFmtId="{i}"/>' for i in _XF)
    # un <dxf> con otro numFmt: no debe confundirse con los formatos de las celdas
    return (f'<styleSheet {NS}><numFmts count="{len(_FORMATOS)}">{fmts}</numFmts><cellStyleXfs count="1"><xf numFmtId="14"/></cellStyleXfs>'
            f'<cellXfs count="{len(_XF)}">{xfs}</cellXfs><dxfs count="1"><dxf><numFmt numFmtId="1" formatCode="dd/mm"/></dxf></dxfs></styleSheet>')


def serie(d: date) -> int:
    return (d - date(1899, 12, 30)).days


def col(i: int) -> str:
    s = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def _celda(ref, v, cadenas):
    if v is None:
        return ""
    if isinstance(v, bool):
        return f'<c r="{ref}" t="b"><v>{int(v)}</v></c>'
    if isinstance(v, str) or (isinstance(v, tuple) and v[0] == "si"):
        i = cadenas.setdefault(v, len(cadenas))
        return f'<c r="{ref}" t="s"><v>{i}</v></c>'
    if isinstance(v, (int, float)):
        return f'<c r="{ref}"><v>{v}</v></c>'
    if v[0] == "raw":   # ("raw", ' t="e"><v>#DIV/0!</v>'): atributos y contenido tal cual
        return f'<c r="{ref}"{v[1]}</c>'
    if v[0] == "n":     # ("n", "45000", estilo): número con texto exacto y estilo
        return f'<c r="{ref}" s="{v[2]}"><v>{v[1]}</v></c>'
    raise AssertionError(v)


def fila_xml(n, valores, cadenas):
    return f'<row r="{n}">' + "".join(_celda(f"{col(i)}{n}", v, cadenas) for i, v in enumerate(valores)) + "</row>"


def libro(ruta, hojas, *, d1904=False, con_estilos=True, extra=None, cadenas_previas=None):
    """`hojas`: [(nombre, filas[, estado])]; una fila es una lista de valores (None = sin celda) o None (sin fila). Devuelve la ruta."""
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    cadenas: dict = dict(cadenas_previas or {})
    hojas_xml, entradas, rels = [], [], []
    for n, h in enumerate(hojas, 1):
        nombre, filas = h[0], h[1]
        estado = h[2] if len(h) > 2 else "visible"
        cuerpo = "".join(fila_xml(r, f, cadenas) for r, f in enumerate(filas, 1) if f is not None)
        hojas_xml.append(f'<worksheet {NS}><sheetData>{cuerpo}</sheetData></worksheet>')
        st = "" if estado == "visible" else f' state="{estado}"'
        entradas.append(f'<sheet name="{html.escape(nombre)}" sheetId="{n}"{st} r:id="rId{n}"/>')
        rels.append(f'<Relationship Id="rId{n}" Type="{REL}/worksheet" Target="worksheets/sheet{n}.xml"/>')
    si = "".join(f"<si>{k[1]}</si>" if isinstance(k, tuple) else f'<si><t xml:space="preserve">{html.escape(k, quote=False)}</t></si>' for k in cadenas)
    with zipfile.ZipFile(ruta, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("xl/workbook.xml", f'<workbook {NS}><workbookPr date1904="{int(d1904)}"/><sheets>{"".join(entradas)}</sheets></workbook>')
        z.writestr("xl/_rels/workbook.xml.rels", f'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">{"".join(rels)}</Relationships>')
        z.writestr("xl/sharedStrings.xml", f'<sst {NS} count="{len(cadenas)}" uniqueCount="{len(cadenas)}">{si}</sst>')
        if con_estilos:
            z.writestr("xl/styles.xml", estilos_xml())
        for n, x in enumerate(hojas_xml, 1):
            z.writestr(f"xl/worksheets/sheet{n}.xml", x)
        for nombre, datos in (extra or {}).items():
            z.writestr(nombre, datos)
    return ruta


def zip_con(ruta, partes: dict):
    with zipfile.ZipFile(ruta, "w", zipfile.ZIP_DEFLATED) as z:
        for k, v in partes.items():
            z.writestr(k, v)
    return Path(ruta)


# ================================================================ el lector
def test_una_hoja_sencilla_sale_con_su_cabecera_y_una_linea_por_fila(tmp_path):
    p = libro(tmp_path / "a.xlsx", [("Roles", [["Rol", "Descripción"], ["Revenue", "Aprueba cotizaciones"], ["Ventas", "Pide cotizaciones"]])])
    assert DOC.texto_xlsx(p) == "## Hoja: Roles\nRol | Descripción\nRevenue | Aprueba cotizaciones\nVentas | Pide cotizaciones"


def test_tipos_de_celda_huecos_filas_vacias_y_saltos_de_linea(tmp_path):
    rico = ("si", '<r><rPr><b/></rPr><t xml:space="preserve">Parte </t></r><r><t>dos</t></r><rPh sb="0" eb="1"><t>ふりがな</t></rPh>')
    filas = [
        ["Texto", rico, ("raw", ' t="inlineStr"><is><t>En línea</t></is>'), ("raw", ' t="str"><f>A1&amp;"x"</f><v>Fórmula de texto</v>')],
        None,                                           # sin fila
        [],                                             # fila sin celdas
        ["A", None, "C", ("raw", ' t="s"><v>0</v>'), None],   # hueco entre dos con valor; las vacías del final se quitan
        [True, False, ("raw", ' t="e"><v>#DIV/0!</v>'), 12, ("raw", '><v>12.0</v>'), 0.35],
        ["Línea uno\nlínea dos\r\ny tres"],
        [("raw", '><f>SUM(A1:A2)</f><v>3</v>'), ("raw", ' t="inlineStr"><is><t>   </t></is>'), "Fin"],
    ]
    t = DOC.texto_xlsx(libro(tmp_path / "t.xlsx", [("Mezcla", filas)]))
    assert t.split("\n") == ["## Hoja: Mezcla", "Texto | Parte dos | En línea | Fórmula de texto", "A |  | C | Texto", "sí | no |  | 12 | 12 | 0.35",
                             "Línea uno línea dos y tres", "3 |  | Fin"]
    assert "SUM" not in t and "ふりがな" not in t and "DIV" not in t               # nunca la fórmula, ni las guías fonéticas, ni el texto del error


def test_los_numeros_salen_sin_ceros_de_sobra(tmp_path):
    valores = [("n", x, GENERAL) for x in ("12.0", "0.35", "-7.50", "1E3", "0.30000000000000004", "1.5E-5", "123456789", "6.00123456E8", "-0", "abc")]
    t = DOC.texto_xlsx(libro(tmp_path / "n.xlsx", [("N", [valores])]))
    assert t.split("\n")[1] == "12 | 0.35 | -7.5 | 1000 | 0.3 | 0.000015 | 123456789 | 600123456 | 0 | abc"


@pytest.mark.parametrize("valor,estilo,esperado", [
    (serie(date(2026, 11, 10)), FECHA, "2026-11-10"),
    (serie(date(2026, 11, 10)), DMY, "2026-11-10"),
    (serie(date(2026, 11, 10)), LARGO, "2026-11-10"),
    (serie(date(2026, 11, 10)) + 0.4375, FECHA_HORA, "2026-11-10 10:30"),
    (serie(date(2026, 11, 10)) + 0.4375, ISO_HORA, "2026-11-10 10:30"),
    (serie(date(2026, 11, 10)), FECHA_HORA, "2026-11-10"),                       # sin hora (00:00) no se añade
    (serie(date(2026, 11, 10)) + 0.99999, FECHA_HORA, "2026-11-11"),             # el redondeo al minuto pasa de día
    (serie(date(2026, 11, 10)) + 0.4375, FECHA, "2026-11-10"),                   # formato de solo fecha: sin hora
    (0.4375, HORA, "10:30"),
    (1.5, TRANSCURRIDO, "36:00"),                                         # horas transcurridas: 36:00
    (serie(date(2026, 11, 1)), MES, "2026-11-01"),
    (serie(date(2026, 11, 10)), GENERAL, str(serie(date(2026, 11, 10)))),        # un número sin formato de fecha sigue siendo número
    (3.5, KG, "3.5"),                                                            # formato propio con comillas: no es fecha
    (7, DIA_TEXTO, "7"),                                                         # «día» entre comillas tampoco
    (59, FECHA, "1900-02-28"),
    (60, FECHA, "1900-02-29"),                                                   # el error histórico de Excel
    (61, FECHA, "1900-03-01"),
    (1, FECHA, "1900-01-01"),
    (2958465, FECHA, "9999-12-31"),
    (3000000, FECHA, "3000000"),                                                 # fuera de rango: se deja el número
    (-5, FECHA, "-5"),
])
def test_fechas_y_horas(tmp_path, valor, estilo, esperado):
    p = libro(tmp_path / "f.xlsx", [("F", [[("n", repr(valor), estilo)]])])
    assert DOC.texto_xlsx(p).split("\n")[1] == esperado


def test_sistema_1904_y_libro_sin_estilos(tmp_path):
    p = libro(tmp_path / "m.xlsx", [("M", [[("n", "0", FECHA), ("n", "1462", FECHA), ("n", "30000.5", FECHA_HORA)]])], d1904=True)
    assert DOC.texto_xlsx(p).split("\n")[1] == "1904-01-01 | 1908-01-02 | 1986-02-19 12:00"
    # sin styles.xml no hay forma de saber qué es una fecha: el número queda como número
    q = libro(tmp_path / "s.xlsx", [("S", [[("n", "46000", FECHA)]])], con_estilos=False)
    assert DOC.texto_xlsx(q).split("\n")[1] == "46000"


def test_las_hojas_ocultas_no_se_leen_y_se_cuentan_con_su_plural(tmp_path):
    una = libro(tmp_path / "1.xlsx", [("Visible", [["dato visible"]]), ("Interna", [["SECRETO-INTERNO"]], "hidden")])
    t = DOC.texto_xlsx(una)
    assert "dato visible" in t and "SECRETO-INTERNO" not in t and "Interna" not in t and t.endswith("\n(1 hoja oculta sin leer)")
    dos = libro(tmp_path / "2.xlsx", [("A", [["uno"]]), ("B", [["SECRETO-B"]], "veryHidden"), ("C", [["SECRETO-C"]], "hidden"), ("D", [["cuatro"]])])
    t2 = DOC.texto_xlsx(dos)
    assert "## Hoja: A" in t2 and "## Hoja: D" in t2 and "SECRETO" not in t2 and t2.endswith("\n(2 hojas ocultas sin leer)")
    assert "oculta" not in DOC.texto_xlsx(libro(tmp_path / "0.xlsx", [("A", [["x"]])]))


def test_un_libro_con_todas_las_hojas_ocultas_o_sin_hojas_es_ilegible(tmp_path):
    for hojas in ([("A", [["x"]], "hidden")], []):
        with pytest.raises(DOC.Indisponible):
            DOC.texto_xlsx(libro(tmp_path / "x.xlsx", hojas))
    # una hoja visible sin datos: cabecera y aviso, no error
    assert DOC.texto_xlsx(libro(tmp_path / "v.xlsx", [("Vacía", [])])) == "## Hoja: Vacía\n(hoja vacía)"


def test_xlsm_se_lee_igual_y_no_se_toca_ninguna_macro(tmp_path):
    p = libro(tmp_path / "m.xlsm", [("Datos", [["a", "b"]])], extra={"xl/vbaProject.bin": b"\xd0\xcf\x11\xe0 macro", "xl/externalLinks/externalLink1.xml": "<externalLink/>"})
    assert DOC.texto_de(p) == DOC.texto_de(libro(tmp_path / "m.xlsx", [("Datos", [["a", "b"]])])) == "## Hoja: Datos\na | b"
    mayusculas = libro(tmp_path / "MAYUS.XLSX", [("Datos", [["a", "b"]])])
    assert DOC.texto_de(mayusculas) == "## Hoja: Datos\na | b"


def test_las_rutas_de_las_partes_se_resuelven_por_las_relaciones(tmp_path):
    """El orden y el fichero de cada hoja salen de workbook.xml y de sus relaciones, no del nombre sheetN.xml; un destino absoluto o con «..» también vale."""
    partes = {
        "xl/workbook.xml": f'<workbook {NS}><sheets><sheet name="Segunda" sheetId="2" r:id="rId9"/><sheet name="Primera" sheetId="1" r:id="rId7"/></sheets></workbook>',
        "xl/_rels/workbook.xml.rels": ('<Relationships xmlns="x"><Relationship Id="rId7" Type="' + REL + '/worksheet" Target="/xl/worksheets/hoja_a.xml"/>'
                                       '<Relationship Id="rId9" Type="' + REL + '/worksheet" Target="../xl/worksheets/hoja_b.xml"/>'
                                       '<Relationship Id="rId1" Type="' + REL + '/chartsheet" Target="chartsheets/sheet1.xml"/></Relationships>'),
        "xl/worksheets/hoja_a.xml": f'<worksheet {NS}><sheetData><row r="1"><c r="A1" t="inlineStr"><is><t>de la primera</t></is></c></row></sheetData></worksheet>',
        "xl/worksheets/hoja_b.xml": f'<worksheet {NS}><sheetData><row r="1"><c r="A1" t="inlineStr"><is><t>de la segunda</t></is></c></row></sheetData></worksheet>',
    }
    t = DOC.texto_xlsx(zip_con(tmp_path / "r.xlsx", partes))
    assert t == "## Hoja: Segunda\nde la segunda\n## Hoja: Primera\nde la primera"


def test_prefijos_de_espacio_de_nombres_distintos_y_celdas_sin_referencia(tmp_path):
    """Algunos programas escriben `<x:row>` con prefijo y sin atributo `r`: las celdas siguen el orden."""
    hoja = (f'<x:worksheet xmlns:x="{SS}"><x:sheetData><x:row><x:c t="inlineStr"><x:is><x:t>uno</x:t></x:is></x:c><x:c t="inlineStr"><x:is><x:t>dos</x:t></x:is></x:c></x:row>'
            f'<x:row r="5"><x:c r="C5" t="inlineStr"><x:is><x:t>tres</x:t></x:is></x:c></x:row></x:sheetData></x:worksheet>')
    partes = {"xl/workbook.xml": f'<x:workbook xmlns:x="{SS}" xmlns:r="{REL}"><x:sheets><x:sheet name="P" sheetId="1" r:id="rId1"/></x:sheets></x:workbook>',
              "xl/_rels/workbook.xml.rels": f'<Relationships><Relationship Id="rId1" Type="{REL}/worksheet" Target="worksheets/sheet1.xml"/></Relationships>',
              "xl/worksheets/sheet1.xml": hoja}
    assert DOC.texto_xlsx(zip_con(tmp_path / "p.xlsx", partes)) == "## Hoja: P\nuno | dos\n |  | tres"


# ---------------------------------------------------------------- topes
def test_tope_de_hojas(tmp_path):
    hojas = [(f"H{i}", [[f"dato{i}"]]) for i in range(1, DOC.MAX_HOJAS + 4)]
    t = DOC.texto_xlsx(libro(tmp_path / "h.xlsx", hojas))
    assert t.count("## Hoja:") == DOC.MAX_HOJAS == 20 and f"dato{DOC.MAX_HOJAS}" in t and f"dato{DOC.MAX_HOJAS + 1}" not in t
    assert "(libro recortado: quedan más hojas)" in t


def test_tope_de_filas_y_se_dice(tmp_path):
    filas = [[f"fila{i}"] for i in range(1, DOC.MAX_FILAS_HOJA + 50)]
    t = DOC.texto_xlsx(libro(tmp_path / "f.xlsx", [("Larga", filas)]))
    lineas = t.split("\n")
    assert DOC.MAX_FILAS_HOJA == 2000 and lineas[1] == "fila1" and lineas[DOC.MAX_FILAS_HOJA] == "fila2000" and "fila2001" not in t
    assert lineas[-1] == "(hoja recortada: quedan más filas)"
    exacto = DOC.texto_xlsx(libro(tmp_path / "e.xlsx", [("Justa", filas[:DOC.MAX_FILAS_HOJA])]))
    assert "recortada" not in exacto and exacto.endswith("fila2000")


def test_tope_de_columnas_y_de_caracteres_por_celda(tmp_path):
    ancha = [f"c{i}" for i in range(1, 61)]
    t = DOC.texto_xlsx(libro(tmp_path / "c.xlsx", [("Ancha", [ancha, ["x" * 500, "corto"]])]))
    lineas = t.split("\n")
    assert DOC.MAX_COLUMNAS_HOJA == 40 and lineas[1] == " | ".join(ancha[:40]) and "c41" not in t
    assert lineas[2] == "x" * 300 + "… | corto" and DOC.MAX_CHARS_CELDA == 300
    assert "(hoja recortada: hay más de 40 columnas)" in t and "(hoja recortada: hay celdas de más de 300 caracteres)" in t


def test_tope_de_caracteres_total_y_se_dice(tmp_path):
    p = libro(tmp_path / "t.xlsx", [("A", [[f"linea {i:03d} " + "y" * 40] for i in range(200)]), ("B", [["no debe llegar"]])])
    t = DOC.texto_xlsx(p, tope_chars=1000)
    assert len(t) <= 1000 and "linea 000" in t and "no debe llegar" not in t and t.endswith("(texto recortado: se alcanzó el tope de caracteres)")
    assert len(DOC.texto_xlsx(p, tope_chars=30)) <= 30                                  # un tope diminuto no rompe nada


def test_una_cadena_compartida_enorme_y_muchas_cadenas_no_se_cargan_enteras(tmp_path, monkeypatch):
    monkeypatch.setattr(DOC, "MAX_CADENAS", 5)
    p = libro(tmp_path / "s.xlsx", [("S", [[f"texto{i}" for i in range(10)]])])
    t = DOC.texto_xlsx(p)
    assert t.split("\n")[1] == "texto0 | texto1 | texto2 | texto3 | texto4" and "(libro recortado: hay más cadenas de texto de las que se leen)" in t


# ---------------------------------------------------------------- seguridad
@pytest.mark.parametrize("parte", ["xl/workbook.xml", "xl/worksheets/sheet1.xml", "xl/sharedStrings.xml", "xl/styles.xml", "xl/_rels/workbook.xml.rels"])
@pytest.mark.parametrize("peligro", ['<!DOCTYPE x [<!ENTITY a "b">]>', '<!ENTITY a "b">', '<!DOCTYPE lolz>', '<!doctype x>'])
def test_una_parte_con_doctype_o_entity_se_rechaza(tmp_path, parte, peligro):
    base = libro(tmp_path / "base.xlsx", [("A", [["dato"]])])
    with zipfile.ZipFile(base) as z:
        partes = {n: z.read(n) for n in z.namelist()}
    partes[parte] = b'<?xml version="1.0"?>' + peligro.encode() + partes[parte].split(b"?>", 1)[-1] if partes[parte].startswith(b"<?xml") else peligro.encode() + partes[parte]
    with pytest.raises(DOC.Indisponible):
        DOC.texto_xlsx(zip_con(tmp_path / "mal.xlsx", partes))


def test_la_bomba_de_entidades_no_se_expande(tmp_path):
    lolz = ('<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY a "aaaaaaaaaa"><!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;"><!ENTITY c "&b;&b;&b;&b;&b;&b;&b;&b;&b;&b;">]>'
            f'<worksheet {NS}><sheetData><row r="1"><c r="A1" t="inlineStr"><is><t>&c;</t></is></c></row></sheetData></worksheet>')
    base = libro(tmp_path / "b.xlsx", [("A", [["x"]])])
    with zipfile.ZipFile(base) as z:
        partes = {n: z.read(n) for n in z.namelist()}
    partes["xl/worksheets/sheet1.xml"] = lolz.encode()
    t0 = time.monotonic()
    with pytest.raises(DOC.Indisponible):
        DOC.texto_xlsx(zip_con(tmp_path / "bomba.xlsx", partes))
    assert time.monotonic() - t0 < 30


def test_doctype_en_utf16_tambien_se_rechaza(tmp_path):
    base = libro(tmp_path / "b.xlsx", [("A", [["x"]])])
    with zipfile.ZipFile(base) as z:
        partes = {n: z.read(n) for n in z.namelist()}
    partes["xl/worksheets/sheet1.xml"] = ('<?xml version="1.0" encoding="UTF-16"?><!DOCTYPE x [<!ENTITY a "b">]><worksheet/>').encode("utf-16")
    with pytest.raises(DOC.Indisponible):
        DOC.texto_xlsx(zip_con(tmp_path / "u16.xlsx", partes))


def test_un_libro_cifrado_un_zip_ajeno_o_un_xml_roto_dan_el_error_limpio(tmp_path):
    cifrado = tmp_path / "cifrado.xlsx"
    cifrado.write_bytes(bytes.fromhex("D0CF11E0A1B11AE1") + b"\x00" * 600)       # contenedor OLE: así se guarda un libro con contraseña
    ajeno = zip_con(tmp_path / "ajeno.xlsx", {"algo.txt": "hola"})
    sin_hojas = zip_con(tmp_path / "sin.xlsx", {"xl/workbook.xml": f'<workbook {NS}><sheets/></workbook>', "xl/_rels/workbook.xml.rels": "<Relationships/>"})
    roto = zip_con(tmp_path / "roto.xlsx", {"xl/workbook.xml": "<workbook><sheets><sheet"})
    vacio = tmp_path / "vacio.xlsx"
    vacio.write_bytes(b"")
    for malo in (cifrado, ajeno, sin_hojas, roto, vacio):
        with pytest.raises(DOC.Indisponible):
            DOC.texto_xlsx(malo)
        with pytest.raises(DOC.Indisponible):
            DOC.texto_de(malo)


def test_un_xml_roto_en_una_hoja_es_un_libro_ilegible_y_no_una_traza(tmp_path):
    base = libro(tmp_path / "b.xlsx", [("A", [["x"]])])
    with zipfile.ZipFile(base) as z:
        partes = {n: z.read(n) for n in z.namelist()}
    partes["xl/worksheets/sheet1.xml"] = b"<worksheet><sheetData><row><c></row>"
    with pytest.raises(DOC.Indisponible):
        DOC.texto_xlsx(zip_con(tmp_path / "roto.xlsx", partes))


def test_tamano_declarado_de_las_partes_estructurales_y_numero_de_partes(tmp_path, monkeypatch):
    p = libro(tmp_path / "a.xlsx", [("A", [["x" * 50]])])
    monkeypatch.setattr(DOC, "MAX_PARTE_BYTES", 200)             # el sharedStrings declara más: el libro no se lee
    with pytest.raises(DOC.Indisponible, match="grande"):
        DOC.texto_xlsx(p)
    monkeypatch.undo()
    monkeypatch.setattr(DOC, "MAX_ENTRADAS_ZIP", 3)
    with pytest.raises(DOC.Indisponible, match="partes"):
        DOC.texto_xlsx(p)


def test_una_hoja_mayor_que_el_tope_de_parte_se_lee_solo_hasta_el_tope(tmp_path, monkeypatch):
    """Una hoja que declara más de `MAX_PARTE_BYTES` no se descomprime entera: se lee lo que cabe (nunca más) y se dice."""
    p = libro(tmp_path / "g.xlsx", [("Grande", [[("raw", f' t="inlineStr"><is><t>fila{i}</t></is>'), i] for i in range(1, 3000)]), ("Pequeña", [["cabe"]])])
    monkeypatch.setattr(DOC, "MAX_PARTE_BYTES", 40_000)
    t = DOC.texto_xlsx(p)
    assert "fila1 | 1" in t and "fila2999" not in t and "(hoja recortada: es demasiado grande para leerla entera)" in t
    assert "## Hoja: Pequeña" in t and t.endswith("cabe")                   # las demás hojas siguen


def test_no_se_descomprime_mas_del_tope_aunque_la_hoja_sea_enorme(tmp_path, monkeypatch):
    base = libro(tmp_path / "b.xlsx", [("A", [["x"]])])
    with zipfile.ZipFile(base) as z:
        partes = {n: z.read(n) for n in z.namelist()}
    relleno = b"<worksheet><sheetData>" + b" " * 200_000
    partes["xl/worksheets/sheet1.xml"] = relleno
    monkeypatch.setattr(DOC, "MAX_PARTE_BYTES", 50_000)
    visto = []
    real = zipfile.ZipExtFile.read

    def leer(self, n=-1):
        d = real(self, n)
        visto.append(len(d))
        return d
    monkeypatch.setattr(zipfile.ZipExtFile, "read", leer)
    t = DOC.texto_xlsx(zip_con(tmp_path / "m.xlsx", partes))
    assert sum(visto) < 50_000 + 20_000 + 4096 and "demasiado grande" in t


# ---------------------------------------------------------------- tiempo
def test_un_libro_enorme_respeta_los_topes_y_para_pronto(tmp_path):
    n = 200_000
    filas = "".join(f'<row r="{i}"><c r="A{i}" t="inlineStr"><is><t>producto {i}</t></is></c><c r="B{i}"><v>{i}.5</v></c><c r="C{i}" s="1"><v>46000</v></c></row>' for i in range(1, n + 1))
    p = tmp_path / "enorme.xlsx"
    libro(p, [("Datos", [["x"]])])
    with zipfile.ZipFile(p) as z:
        partes = {k: z.read(k) for k in z.namelist()}
    partes["xl/worksheets/sheet1.xml"] = f'<worksheet {NS}><sheetData>{filas}</sheetData></worksheet>'.encode()
    zip_con(p, partes)
    t0 = time.monotonic()
    t = DOC.texto_xlsx(p)
    seg = time.monotonic() - t0
    lineas = t.split("\n")
    assert seg < 30, seg                                                              # cota holgada: con la máquina cargada el reloj no es fiable; lo que manda son los topes de abajo
    assert lineas[0] == "## Hoja: Datos" and lineas[1] == "producto 1 | 1.5 | " + date.fromordinal(date(1899, 12, 30).toordinal() + 46000).isoformat()
    assert lineas[DOC.MAX_FILAS_HOJA].startswith("producto 2000 |") and "producto 2001" not in t and lineas[-1] == "(hoja recortada: quedan más filas)"


# ================================================================ quién lo consume
def test_el_despachador_y_las_constantes_de_extensiones():
    assert {".xlsx", ".xlsm"} <= DOC.EXT_OFICINA and {".xlsx", ".xlsm"} <= FU.EXT_KNOWLEDGE and {".xlsx", ".xlsm"} <= AR.EXT_LEIBLES
    assert not ({".xls", ".ods", ".vsdx", ".mpp"} & AR.EXT_LEIBLES)
    with pytest.raises(DOC.Indisponible):
        DOC.texto_de("x.xls")


def esquema(tmp_path):
    raiz = tmp_path / "proyectos"
    p = raiz / PROY
    antes = time.time() - 2 * DIA
    libro(p / "Matriz de roles.xlsx", [
        ("Roles", [["Rol", "Qué puede hacer"], ["Revenue", "Aprueba cotizaciones"], ["Ventas", "Pide cotizaciones"]]),
        ("Equipo", [["Nombre", "Correo electrónico", "Teléfono", "Móvil"],
                    ["Ana Prueba", "ana.prueba@ejemplo.test", ("n", "600123456", GENERAL), "+34 611 22 33 44"],
                    ["Luis Demo", "luis.demo@ejemplo.test", ("n", "911234567", GENERAL), "611-22-33-55"]]),
        ("Contactos", [["Nombre", "Cargo"], ["Marta Ficticia", "Directora de proyecto"]]),
        ("Datos de contacto", [["Quién", "Dónde"], ["Pedro Inventado", "Calle Falsa 123"]]),
        ("Planificación", [["Sesión", "Fecha", "Hora"], ["Alcance", ("n", str(serie(date(2026, 11, 10))), FECHA), ("n", "0.4375", HORA)],
                           ["Piloto", ("n", str(serie(date(2026, 12, 15))), FECHA), None]]),
        ("Notas internas", [["NO-DEBE-SALIR"]], "hidden"),
    ])
    os.utime(p / "Matriz de roles.xlsx", (antes, antes))
    (p / "Kickoff.txt").write_text("Reunión de arranque del proyecto. Objetivo: portal de grupos.\n" * 2, encoding="utf-8")
    return raiz, p


def guardian(tmp_path, raiz, **kw):
    return Guardian(raiz, tmp_path / "bandeja", tmp_path / "cache", sesiones_locales=tmp_path / "sesiones", tipos=tmp_path / "tipos", **kw)


def configuracion(tmp_path, raiz, **extra):
    cfg = Config(tmp_path / "config.json")
    cfg.actualizar({"raiz_proyectos": str(raiz), "knowledge": "", **extra}, guardar=False)
    return cfg


def test_el_guardian_lee_hojas_con_las_mismas_reglas_que_el_resto(tmp_path):
    raiz, p = esquema(tmp_path)
    g = guardian(tmp_path, raiz)
    libro(p / "Datos mezclados.xlsx", [("S", [["Dato normal"], ["password: abc123456789xyz"], ["Otro dato"]])])
    for t in (g.leer_para_archivero(PROY, p / "Datos mezclados.xlsx"), g.leer_documento(p / "Datos mezclados.xlsx", p)):
        assert "Dato normal" in t and "Otro dato" in t and "abc123456789xyz" not in t
    t = g.leer_para_archivero(PROY, p / "Matriz de roles.xlsx")
    assert "## Hoja: Roles" in t and "NO-DEBE-SALIR" not in t
    # confinamiento: nombre de secreto, carpeta oculta, nube, tope de tamaño
    libro(p / "credenciales.xlsx", [("S", [["x"]])])
    libro(p / ".oculta" / "a.xlsx", [("S", [["x"]])])
    libro(p / "~$Bloqueo.xlsx", [("S", [["x"]])])
    libro(p / CARPETA_SESIONES / "sesion.xlsx", [("S", [["x"]])])
    for malo in (p / "credenciales.xlsx", p / ".oculta" / "a.xlsx", p / "~$Bloqueo.xlsx", p / CARPETA_SESIONES / "sesion.xlsx"):
        with pytest.raises(RutaProhibida):
            g.leer_para_archivero(PROY, malo)
    with pytest.raises(RutaProhibida):
        g.leer_para_archivero(PROY, p / "Matriz de roles.xlsx", tope_oficina_bytes=100)
    with pytest.raises(RutaProhibida, match="formato sin lector"):
        g.leer_para_archivero(PROY, p / "Antigua.xls")
    # un libro ilegible sube como `Indisponible`, que los llamadores ya saben tratar
    (p / "Cifrado.xlsx").write_bytes(bytes.fromhex("D0CF11E0A1B11AE1") + b"\x00" * 300)
    with pytest.raises(DOC.Indisponible):
        g.leer_para_archivero(PROY, p / "Cifrado.xlsx")


def mapa(g):
    return INV.mapa(g, PROY, max_por_tipo=100000)


def test_el_archivero_selecciona_la_hoja_y_los_formatos_sin_lector_siguen_marcados(tmp_path):
    raiz, p = esquema(tmp_path)
    (p / "Matriz de roles v0.xls").write_bytes(b"PK" + bytes(50))
    (p / "Roles y permisos.ods").write_bytes(b"PK" + b"\x00" * 50)
    g = guardian(tmp_path, raiz)
    cfg = configuracion(tmp_path, raiz)
    sel = AR.seleccionar(mapa(g), AR.topes(cfg))
    assert "Matriz de roles.xlsx" in {f["rel"] for f in sel["leer"]}
    motivos = {o["rel"]: o["motivo"] for o in sel["omitidos"]}
    assert "Matriz de roles.xlsx" not in motivos
    assert motivos["Matriz de roles v0.xls"] == "formato sin lector en la app (.xls)" and motivos["Roles y permisos.ods"] == "formato sin lector en la app (.ods)"


def test_el_texto_de_una_hoja_sale_sin_contactos_correos_ni_telefonos(tmp_path):
    raiz, p = esquema(tmp_path)
    g = guardian(tmp_path, raiz)
    cfg = configuracion(tmp_path, raiz)
    sel = AR.seleccionar(mapa(g), AR.topes(cfg))
    docs, fuera = AR.leer_documentos(g, PROY, sel, AR.topes(cfg))
    d = next(x for x in docs if x["nombre"] == "Matriz de roles.xlsx")
    t = d["texto"]
    assert "## Hoja: Roles" in t and "Revenue | Aprueba cotizaciones" in t and "NO-DEBE-SALIR" not in t
    # las dos hojas de contactos se sustituyen por la marca; sus filas no salen
    assert t.count(AR.LINEA_CONTACTOS) == 2
    for prohibido in ("Marta Ficticia", "Directora de proyecto", "Pedro Inventado", "Calle Falsa"):
        assert prohibido not in t, prohibido
    # una columna de correo o de teléfono llega enmascarada, sea número o texto
    for prohibido in ("ana.prueba@ejemplo.test", "luis.demo@ejemplo.test", "600123456", "911234567", "611 22 33 44", "611-22-33-55"):
        assert prohibido not in t, prohibido
    assert "Ana Prueba | [correo] | [teléfono] | [teléfono]" in t and "Luis Demo | [correo] | [teléfono] | [teléfono]" in t
    # y la hoja siguiente a las de contactos sigue ahí, con sus fechas legibles
    assert "## Hoja: Planificación" in t and "Alcance | 2026-11-10 | 10:30" in t and "Piloto | 2026-12-15" in t


def test_el_enmascarado_conserva_el_espacio_que_separa_las_celdas():
    assert AR.enmascarar("Ana | 600123456 | b | 611 22 33 44 | c. Fin 600 123 456") == "Ana | [teléfono] | b | [teléfono] | c. Fin [teléfono]"
    assert AR.enmascarar("2026-03-04 600 123 456 | x") == "2026-03-04 [teléfono] | x"


def test_una_hoja_de_contactos_en_singular_o_con_numeracion_tambien_se_quita(tmp_path):
    texto = DOC.texto_xlsx(libro(tmp_path / "c.xlsx", [("Roles", [["Rol"]]), ("Contacto", [["Nombre"], ["Persona Uno"]]), ("2. Contactos del cliente", [["Nombre"], ["Persona Dos"]]),
                                                       ("Resto", [["sigue aquí"]])]))
    limpio = AR.preparar_texto(texto, 10_000)
    assert "Persona Uno" not in limpio and "Persona Dos" not in limpio and "sigue aquí" in limpio and limpio.count(AR.LINEA_CONTACTOS) == 2
    # una celda que empieza por «#» no se confunde con un apartado ni corta lo anterior
    t2 = DOC.texto_xlsx(libro(tmp_path / "d.xlsx", [("Contactos", [["Nombre"], ["# Contactos"], ["Persona Tres"]])]))
    assert "Persona Tres" not in AR.preparar_texto(t2, 10_000)


class ModeloArchivero(ModeloLLM):
    def __init__(self):
        self.llamadas = []

    def completar(self, sistema, usuario, modelo, esfuerzo="", timeout_s=240, sin_razonamiento=False, web=False):
        self.llamadas.append((sistema, usuario, modelo))
        n = usuario.count("<<<DATOS documento ")
        d = {"documentos": [{"i": i, "resumen": f"Resumen {i}"} for i in range(1, n + 1)], "sin_clasificar": []}
        return Respuesta(json.dumps(d), [Uso(modelo, 50, 10)])


def test_el_prompt_del_archivero_lleva_la_hoja_ya_limpia(tmp_path):
    raiz, p = esquema(tmp_path)
    g = guardian(tmp_path, raiz)
    cfg = configuracion(tmp_path, raiz)
    modelo = ModeloArchivero()
    sv = AR.ServicioArchivero(g, cfg, lambda: Analista(modelo, cfg, Consumo(None), g, "archivero"))
    r = sv.analizar(PROY)
    assert r["origen"] == "modelo" and len(modelo.llamadas) == 1
    usuario = modelo.llamadas[0][1]
    assert "Matriz de roles.xlsx" in usuario and "Revenue | Aprueba cotizaciones" in usuario
    for prohibido in ("ana.prueba@ejemplo.test", "600123456", "Marta Ficticia", "Pedro Inventado", "NO-DEBE-SALIR"):
        assert prohibido not in usuario, prohibido


# ---------------------------------------------------------------- «Proponer plan»
class ModeloPlan(ModeloLLM):
    def __init__(self, salida):
        self.salida, self.llamadas = salida, []

    def completar(self, sistema, usuario, modelo, esfuerzo="", timeout_s=240, sin_razonamiento=False, web=False):
        self.llamadas.append((sistema, usuario, modelo))
        return Respuesta(json.dumps(self.salida), [Uso(modelo, 50, 10)])


def test_proponer_plan_ve_las_fechas_de_una_hoja_como_aaaa_mm_dd(tmp_path):
    raiz, p = esquema(tmp_path)
    (p / "Kickoff.txt").unlink()
    libro(p / "Plan de sesiones.xlsx", [("Calendario", [["Sesión", "Fecha", "Hora"], ["Alcance del portal", ("n", str(serie(date(2027, 2, 3))), FECHA), ("n", "0.4375", HORA)],
                                                         ["Datos", ("n", str(serie(date(2027, 2, 17))) + ".5", FECHA_HORA), None]])])
    g = guardian(tmp_path, raiz)
    cfg = configuracion(tmp_path, raiz)
    salida = {"sesiones": [
        {"nombre": "Alcance del portal", "objetivos": ["Confirmar el alcance", "Cerrar lo que queda fuera"], "checks": [], "fecha_iso": "2027-02-03", "hora": "10:30", "depende_de": [], "fuente": 1},
        {"nombre": "Datos", "objetivos": ["Validar el modelo de datos"], "checks": [], "fecha_iso": "2027-02-17", "hora": "12:00", "depende_de": [], "fuente": 1},
        {"nombre": "Inventada", "objetivos": ["Algo que no está en la hoja"], "checks": [], "fecha_iso": "2027-03-03", "hora": "", "depende_de": [], "fuente": 1}]}
    modelo = ModeloPlan(salida)
    sv = PP.ServicioPlanPropuesto(g, cfg, lambda: Analista(modelo, cfg, Consumo(None), g, "plan_propuesto"))
    r = sv.proponer(PROY)
    usuario = modelo.llamadas[0][1]
    assert "2027-02-03 | 10:30" in usuario and "2027-02-17 12:00" in usuario                # lo que ve el modelo
    por = {s["nombre"]: s for s in r["sesiones"]}
    assert por["Alcance del portal"]["fecha_iso"] == "2027-02-03" and por["Alcance del portal"]["hora"] == "10:30"
    assert por["Datos"]["fecha_iso"] == "2027-02-17" and por["Datos"]["hora"] == "12:00"       # se valida contra el texto de la hoja
    assert por["Inventada"]["fecha_iso"] == ""                                              # una fecha que no está en la hoja no se acepta (la sesión se conserva)
    assert r["origen"] == "modelo" and r["leidos"] >= 1


# ---------------------------------------------------------------- Knowledge y asesor
@pytest.fixture
def knowledge(tmp_path):
    k = tmp_path / "Knowledge"
    libro(k / "Inventario" / "interfaces.xlsx", [("Interfaces", [["Interfaz", "Origen", "Destino"], ["Tarifas diarias", "Revenue", "Portal"], ["Reservas", "Portal", "Sistema central"]])])
    libro(k / "Inventario" / "macros.xlsm", [("Dic", [["Término", "Significado"], ["Cupo", "Habitaciones reservadas para un grupo"]])], extra={"xl/vbaProject.bin": b"\x00macro"})
    (k / "nota.txt").write_text("Nota suelta sobre el catálogo.", encoding="utf-8")
    libro(k / "secretos.xlsx", [("S", [["zzzsecretozzz"]])])
    return k


def test_knowledge_indexa_las_hojas_y_la_busqueda_las_encuentra(tmp_path, knowledge):
    g = Guardian(tmp_path / "raiz", tmp_path / "bandeja", tmp_path / "cache", solo_lectura=[knowledge])
    def foto():
        return {str(x.relative_to(knowledge)): (x.stat().st_mtime_ns, x.stat().st_size) for x in knowledge.rglob("*") if x.is_file()}
    antes = foto()
    fuentes, inf = FU.indexar_knowledge(g, knowledge, {})
    assert foto() == antes                                                                         # SOLO LECTURA
    etiquetas = {e["etiqueta"] for e in fuentes.values()}
    assert etiquetas == {"Knowledge/Inventario/interfaces.xlsx", "Knowledge/Inventario/macros.xlsm", "Knowledge/nota.txt"}      # secretos.xlsx, por su nombre, no
    todo = " ".join(t[0] for e in fuentes.values() for t in e["trozos"])
    assert "zzzsecretozzz" not in todo and "Tarifas diarias | Revenue | Portal" in todo and "Habitaciones reservadas" in todo
    indice = FU.Indice([FU._doc_de(e) for e in fuentes.values()])
    hit = indice.buscar("qué significa cupo", k=3, max_chars=2000)
    assert hit and hit[0].etiqueta == "Knowledge/Inventario/macros.xlsm"


def test_una_cache_de_antes_de_esta_ola_se_completa_sola_con_las_hojas(tmp_path, knowledge):
    """Una carpeta ya indexada (la caché no tiene las hojas) las incorpora en la pasada siguiente sin tocar lo ya indexado; no hace falta subir la versión."""
    g = Guardian(tmp_path / "raiz", tmp_path / "bandeja", tmp_path / "cache", solo_lectura=[knowledge])
    completo, _ = FU.indexar_knowledge(g, knowledge, {})
    previo = {k: v for k, v in completo.items() if not k.lower().endswith((".xlsx", ".xlsm"))}
    assert len(previo) == 1                                         # lo que había antes: solo la nota
    nuevo, inf = FU.indexar_knowledge(g, knowledge, previo)
    assert inf.reutilizados == 1 and inf.nuevos == 2 and len(nuevo) == 3
    assert nuevo[next(k for k in previo)] is previo[next(k for k in previo)]
    # y por la ruta real: el servicio carga la caché antigua, indexa en segundo plano y guarda
    g.asegurar_cache()
    cfg = configuracion(tmp_path, tmp_path / "raiz", knowledge=str(knowledge))
    sv = FU.ServicioFuentes(g, cfg)
    FU.guardar_cache(g, sv._nombre_knowledge(), previo)
    hilo = sv.arrancar()
    hilo.join(30)
    assert {e.etiqueta for e in sv._knowledge} >= {"Knowledge/Inventario/interfaces.xlsx", "Knowledge/Inventario/macros.xlsm"}


def test_un_libro_ilegible_en_knowledge_se_cuenta_y_no_rompe_el_indice(tmp_path, knowledge):
    (knowledge / "cifrado.xlsx").write_bytes(bytes.fromhex("D0CF11E0A1B11AE1") + b"\x00" * 300)
    g = Guardian(tmp_path / "raiz", tmp_path / "bandeja", tmp_path / "cache", solo_lectura=[knowledge])
    fuentes, inf = FU.indexar_knowledge(g, knowledge, {})
    assert inf.sin_formato == 1 and inf.nuevos == 3 and not any("cifrado" in e["etiqueta"] for e in fuentes.values())


# ---------------------------------------------------------------- ayuda y documentación
def test_la_ayuda_y_los_manuales_dicen_que_las_hojas_se_leen():
    raiz = Path(__file__).resolve().parent.parent
    html_ = (raiz / "web" / "index.html").read_text(encoding="utf-8")
    ayuda = html_.split('id="aj-knowledge-ayuda">')[1].split("</span>")[0]
    assert "xlsx" in ayuda
    assert "`.xlsx`" in (raiz / "MANUAL.md").read_text(encoding="utf-8")
    assert "xlsx" in (raiz / "README.md").read_text(encoding="utf-8") and "xlsx" in (raiz / "CLAUDE.md").read_text(encoding="utf-8")


# ================================================================ arreglos tras la revisión de la ola E
def reescribir(ruta, *, cambios=None, quitar=(), renombrar=None):
    """Reescribe un libro: `cambios` {parte: bytes|str} (nuevas o sustituidas), `quitar` partes fuera, `renombrar` {parte: nombre nuevo}."""
    ruta = Path(ruta)
    with zipfile.ZipFile(ruta) as z:
        partes = {n: z.read(n) for n in z.namelist()}
    for n in quitar:
        partes.pop(n)
    for n, nuevo in (renombrar or {}).items():
        partes[nuevo] = partes.pop(n)
    for n, v in (cambios or {}).items():
        partes[n] = v.encode("utf-8") if isinstance(v, str) else v
    return zip_con(ruta, partes)


def texto_de(tmp_path, filas, nombre="t.xlsx", **kw):
    return DOC.texto_xlsx(libro(tmp_path / nombre, [("H", filas)], **kw)).split("\n")[1:]


# ---------------------------------------------------------------- A. nada escapa del lector
@pytest.mark.parametrize("codificacion", ["foo", "utf-7", "utf-32", "shift_jis"])
def test_una_codificacion_xml_rara_es_indisponible_y_no_una_excepcion_suelta(tmp_path, codificacion):
    p = libro(tmp_path / "r.xlsx", [("H", [["x"]])])
    with zipfile.ZipFile(p) as z:
        hoja = z.read("xl/worksheets/sheet1.xml").decode("utf-8")
    reescribir(p, cambios={"xl/worksheets/sheet1.xml": f'<?xml version="1.0" encoding="{codificacion}"?>' + hoja})
    with pytest.raises(DOC.Indisponible, match="codificación"):
        DOC.texto_xlsx(p)


def test_cualquier_otra_excepcion_del_analizador_sale_como_indisponible(tmp_path, monkeypatch):
    p = libro(tmp_path / "r.xlsx", [("H", [["x"]])])
    monkeypatch.setattr(DOC, "_leer_hoja", lambda *a, **k: (_ for _ in ()).throw(ArithmeticError("raro")))
    with pytest.raises(DOC.Indisponible, match="no se pudo leer el libro"):
        DOC.texto_xlsx(p)
    monkeypatch.setattr(DOC, "_leer_hoja", lambda *a, **k: (_ for _ in ()).throw(PermissionError("sin permiso")))
    with pytest.raises(OSError):                       # los errores de disco los trata quien llama
        DOC.texto_xlsx(p)


def libro_raro(ruta):
    p = libro(ruta, [("H", [["x"]])])
    return reescribir(p, cambios={"xl/workbook.xml": '<?xml version="1.0" encoding="utf-7"?>' + f'<workbook {NS}><sheets><sheet name="H" sheetId="1" r:id="rId1"/></sheets></workbook>'})


def test_un_libro_raro_no_rompe_la_pasada_del_archivero(tmp_path):
    raiz, p = esquema(tmp_path)
    libro_raro(p / "Matriz de roles bis.xlsx")
    g = guardian(tmp_path, raiz)
    cfg = configuracion(tmp_path, raiz)
    sel = AR.seleccionar(mapa(g), AR.topes(cfg))
    assert "Matriz de roles bis.xlsx" in {f["rel"] for f in sel["leer"]}
    docs, fuera = AR.leer_documentos(g, PROY, sel, AR.topes(cfg))
    assert [f["motivo"] for f in fuera if f["rel"] == "Matriz de roles bis.xlsx"] == ["no se pudo leer: el libro usa una codificación que no se admite"]
    assert "Matriz de roles.xlsx" in {d["nombre"] for d in docs} and "Kickoff.txt" in {d["nombre"] for d in docs}


def test_un_libro_raro_no_impide_indexar_los_demas_ficheros_de_knowledge(tmp_path, knowledge):
    libro_raro(knowledge / "raro.xlsx")
    g = Guardian(tmp_path / "raiz", tmp_path / "bandeja", tmp_path / "cache", solo_lectura=[knowledge])
    fuentes, inf = FU.indexar_knowledge(g, knowledge, {})
    assert inf.sin_formato == 1 and inf.nuevos == 3 and not any("raro" in e["etiqueta"] for e in fuentes.values())


# ---------------------------------------------------------------- B. caracteres que no se pueden codificar
def test_los_escapes_a_sustitutos_y_no_caracteres_se_descartan(tmp_path):
    malo = "A_xD800_B_xDFFF_C_xFFFE_D_xFFFF_E"
    p = libro(tmp_path / "b.xlsx", [(malo, [[malo, ("raw", f' t="inlineStr"><is><t>{malo}</t></is>')]])])
    t = DOC.texto_xlsx(p)
    t.encode("utf-8")                                   # no lanza
    assert t == "## Hoja: ABCDE\nABCDE | ABCDE"
    assert not any(c in t for c in map(chr, (0xD800, 0xDFFF, 0xFFFE, 0xFFFF)))


# ---------------------------------------------------------------- C. números
def test_un_decimal_simple_no_se_enmascara_como_telefono():
    for t in ("Ratio | 0.153846153846154", "Importe | 1250000.75", "Pi | 3.14159265358979", "x | 123456789.5 | y"):
        assert AR.enmascarar(t) == t, t
    # lo que sí es un teléfono sigue tapado (un entero de 9 cifras o más no se distingue de uno guardado como número: límite conocido)
    assert AR.enmascarar("600.123.456") == "[teléfono]"
    assert AR.enmascarar("+34 600 123 456") == "[teléfono]"
    assert AR.enmascarar("600123456") == "[teléfono]"
    assert AR.enmascarar("Total | 1234567890 | x") == "Total | [teléfono] | x"


def test_los_decimales_se_redondean_a_seis_y_los_muy_pequenos_no_se_vuelven_cero(tmp_path):
    valores = [("n", x, GENERAL) for x in ("0.153846153846154", "1234.56789012346", "1250000.75", "0.0004567891234", "-0.00001234567", "0.0000001", "123456789012", "2.5")]
    assert texto_de(tmp_path, [valores]) == ["0.153846 | 1234.56789 | 1250000.75 | 0.000456789 | -0.0000123457 | 0.0000001 | 123456789012 | 2.5"]
    t = DOC.texto_xlsx(libro(tmp_path / "n2.xlsx", [("N", [[("n", "0.153846153846154", GENERAL)]])]))
    assert AR.enmascarar(t) == t                        # y así llega entero al modelo


@pytest.mark.parametrize("valor,estilo,esperado", [
    ("0.35", PCT9, "35%"), ("0.3333", PCT10, "33.33%"), ("1", PCT9, "100%"), ("0", PCT9, "0%"), ("0.123456", PCT_PROPIO, "12.35%"),
    ("-0.25", PCT9, "-25%"), ("0.125", PCT10, "12.5%"), ("0.5", PCT_COMILLAS, "0.5"),            # el % entre comillas no es un porcentaje
    ("0.35", GENERAL, "0.35"),
])
def test_los_porcentajes_salen_por_cien_con_su_signo(tmp_path, valor, estilo, esperado):
    assert texto_de(tmp_path, [[("n", valor, estilo)]]) == [esperado]


# ---------------------------------------------------------------- D. peor caso de tiempo
def _libro_de_veinte_hojas_que_apuntan_a_la_misma_parte(ruta, hoja_xml):
    p = libro(ruta, [("H1", [["x"]])])
    wb = f'<workbook {NS}><sheets>' + "".join(f'<sheet name="H{i}" sheetId="{i}" r:id="rId{i}"/>' for i in range(1, 21)) + "</sheets></workbook>"
    rels = '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' + "".join(
        f'<Relationship Id="rId{i}" Type="{REL}/worksheet" Target="worksheets/sheet1.xml"/>' for i in range(1, 21)) + "</Relationships>"
    return reescribir(p, cambios={"xl/workbook.xml": wb, "xl/_rels/workbook.xml.rels": rels, "xl/worksheets/sheet1.xml": hoja_xml})


@pytest.mark.parametrize("forma", ["filas anchas", "una fila gigante"])
def test_veinte_hojas_anchas_se_paran_por_celdas_y_por_bytes_del_libro(tmp_path, monkeypatch, forma):
    if forma == "filas anchas":
        cuerpo = ("<row>" + "<c><v>1</v></c>" * 5600 + "</row>") * 136                 # 11,4 MB; por debajo del tope de filas
    else:
        cuerpo = "<row>" + "<c><v>1</v></c>" * 800_000 + "</row>"                      # una sola fila de 12 MB, más allá de la columna 40
    p = _libro_de_veinte_hojas_que_apuntan_a_la_misma_parte(tmp_path / "w.xlsx", f"<worksheet {NS}><sheetData>{cuerpo}</sheetData></worksheet>")
    visto = []
    real = zipfile.ZipExtFile.read

    def leer(self, n=-1):
        d = real(self, n)
        visto.append(len(d))
        return d
    monkeypatch.setattr(zipfile.ZipExtFile, "read", leer)
    t0 = time.monotonic()
    t = DOC.texto_xlsx(p)
    seg = time.monotonic() - t0
    print(f"[{forma}] {seg:.2f} s, {sum(visto)} bytes leídos")
    assert seg < 30, seg                                                              # cota holgada: lo que manda es la cuenta de bytes leídos
    assert sum(visto) <= DOC.MAX_BYTES_LIBRO + 70_000, sum(visto)                      # no se lee más de la cuenta
    leidas = t.count("## Hoja: ")
    assert 1 <= leidas < 20 and t.count("(hoja recortada: es demasiado grande para leerla entera)") >= leidas - 1
    assert t.split("\n")[-1] == "(libro recortado: es demasiado grande para leerlo entero)"


def test_el_tope_de_celdas_por_hoja_corta_la_hoja_y_lo_dice(tmp_path, monkeypatch):
    monkeypatch.setattr(DOC, "MAX_CELDAS_HOJA", 50)
    t = DOC.texto_xlsx(libro(tmp_path / "c.xlsx", [("A", [[1] * 20, [2] * 20, [3] * 20, [4] * 20]), ("B", [["ok"]])]))
    assert "(hoja recortada: es demasiado grande para leerla entera)" in t and "2 | 2" in t and "3 | 3" not in t
    assert "## Hoja: B" in t and t.endswith("ok")                                    # las demás hojas siguen


# ---------------------------------------------------------------- E. los avisos finales no se cortan
@pytest.mark.parametrize("tope", [600, 2000, 5000])
def test_los_avisos_finales_caben_enteros_con_topes_pequenos(tmp_path, monkeypatch, tope):
    monkeypatch.setattr(DOC, "MAX_HOJAS", 2)
    monkeypatch.setattr(DOC, "MAX_CADENAS", 3)
    def t_(x):
        return ("raw", f' t="inlineStr"><is><t>{x}</t></is>')
    primera = [[t_("a" * 400)], [t_("c")] * 41] + [[t_(f"fila {i:03d} " + "x" * 40)] for i in range(80)]
    hojas = [("Uno", primera), ("Dos", [[t_("dos")]]), ("Tres", [[t_("tres")]]), ("Cuatro", [[t_("cuatro")]]), ("Oculta", [[t_("o")]], "hidden")]
    cadenas = {f"s{i}": i for i in range(6)}
    p = libro(tmp_path / "e.xlsx", hojas, cadenas_previas=cadenas)
    reescribir(p, quitar=["xl/worksheets/sheet2.xml"])                                  # una visible sin parte (apartado F)
    t = DOC.texto_xlsx(p, tope_chars=tope)
    lineas = t.split("\n")
    assert len(t) <= tope
    avisos = [x for x in lineas if x.startswith("(")]
    for esperado in ("(libro recortado: quedan más hojas)", "(libro recortado: hay más cadenas de texto de las que se leen)", "(1 hoja oculta sin leer)",
                     "(1 hoja no se pudo leer)", "(texto recortado: se alcanzó el tope de caracteres)"):
        assert esperado in avisos, (esperado, lineas[-6:])
    for x in lineas:
        assert x.startswith("## Hoja: ") or (x.startswith("(") and x.endswith(")")) or x == "a" * 300 + "…" or x == " | ".join(["c"] * 40) or (x.startswith("fila ") and len(x) == 49), x
    assert lineas[-1].endswith(")")


# ---------------------------------------------------------------- F. hoja visible sin parte en el zip
def test_una_hoja_visible_sin_parte_se_cuenta(tmp_path):
    p = libro(tmp_path / "f.xlsx", [("A", [["uno"]]), ("B", [["dos"]]), ("C", [["tres"]])])
    reescribir(p, quitar=["xl/worksheets/sheet2.xml"])
    assert DOC.texto_xlsx(p).split("\n") == ["## Hoja: A", "uno", "## Hoja: C", "tres", "(1 hoja no se pudo leer)"]
    reescribir(p, quitar=["xl/worksheets/sheet3.xml"])
    assert DOC.texto_xlsx(p).split("\n")[-1] == "(2 hojas no se pudieron leer)"
    reescribir(p, quitar=["xl/worksheets/sheet1.xml"])
    with pytest.raises(DOC.Indisponible):
        DOC.texto_xlsx(p)


# ---------------------------------------------------------------- G. el enmascarado no cruza líneas
def test_el_enmascarado_de_telefonos_no_cruza_saltos_de_linea():
    plan = "## Hoja: Plan1\n2026-11-12 | Kickoff | 3\n2026-11-19 | Diseño | 5\n2026-11-26 | Piloto | 6"
    assert AR.enmascarar(plan) == plan
    assert AR.enmascarar("Total | 12\n600 123 456 | móvil") == "Total | 12\n[teléfono] | móvil"
    assert AR.enmascarar("## Hoja: Hoja1\n20261112 | 5") == "## Hoja: Hoja1\n20261112 | 5"
    assert AR.enmascarar("a 12\r\n600123456 b") == "a 12\r\n[teléfono] b"
    for tel in ("600 123 456", "600 123 456", "+34 600 123 456", "(+34) 600-123-456", "600.123.456"):
        t = AR.enmascarar(f"Tel: {tel} | fin")
        assert "[teléfono]" in t and "600" not in t.replace("[teléfono]", "") and t.endswith("| fin"), (tel, t)
    assert AR.enmascarar("1\n2\n3\n4\n5\n6\n7\n8\n9\n0") == "1\n2\n3\n4\n5\n6\n7\n8\n9\n0"


def test_proponer_plan_conserva_las_fechas_de_filas_que_acaban_en_numero(tmp_path):
    raiz, p = esquema(tmp_path)
    (p / "Kickoff.txt").unlink()
    libro(p / "Plan de sesiones.xlsx", [("Plan1", [[("n", str(serie(date(2027, 3, 2))), FECHA), "Kickoff", 3], [("n", str(serie(date(2027, 3, 9))), FECHA), "Diseño", 5],
                                       [("n", str(serie(date(2027, 3, 16))), FECHA), "Piloto", 6]])])
    g = guardian(tmp_path, raiz)
    cfg = configuracion(tmp_path, raiz)
    salida = {"sesiones": [{"nombre": n, "objetivos": ["Cerrar " + n], "checks": [], "fecha_iso": f, "hora": "", "depende_de": [], "fuente": 1}
                           for n, f in (("Kickoff", "2027-03-02"), ("Diseño", "2027-03-09"), ("Piloto", "2027-03-16"))]}
    modelo = ModeloPlan(salida)
    sv = PP.ServicioPlanPropuesto(g, cfg, lambda: Analista(modelo, cfg, Consumo(None), g, "plan_propuesto"))
    r = sv.proponer(PROY)
    usuario = modelo.llamadas[0][1]
    assert "2027-03-02 | Kickoff | 3\n2027-03-09 | Diseño | 5\n2027-03-16 | Piloto | 6" in usuario and "[teléfono]" not in usuario
    assert {s["nombre"]: s["fecha_iso"] for s in r["sesiones"]} == {"Kickoff": "2027-03-02", "Diseño": "2027-03-09", "Piloto": "2027-03-16"}


# ---------------------------------------------------------------- H. una hora sola sobre un valor con fecha
@pytest.mark.parametrize("valor,estilo,esperado", [
    ("45000.75", HORA, "18:00"), ("45000.75", HORA_PROPIA, "18:00"), ("1.5", HORA, "12:00"), ("0.4375", HORA_PROPIA, "10:30"),
    ("45000.75", TRANSCURRIDO, "1080018:00"), ("45000.75", TRANS46, "1080018:00"), ("45000.75", TRANS_HH, "1080018:00"), ("1.5", TRANS46, "36:00"),
    ("0.99999", HORA, "00:00"),
])
def test_una_hora_sola_usa_los_minutos_del_dia_y_la_transcurrida_acumula(tmp_path, valor, estilo, esperado):
    assert texto_de(tmp_path, [[("n", valor, estilo)]]) == [esperado]


# ---------------------------------------------------------------- I. partes por nombre y valores raros
def test_las_cadenas_y_los_estilos_se_localizan_por_sus_relaciones(tmp_path):
    filas = [["Hola", ("n", str(serie(date(2026, 11, 10))), FECHA)]]
    p = libro(tmp_path / "m.xlsx", [("H", filas)])
    reescribir(p, renombrar={"xl/sharedStrings.xml": "xl/SharedStrings.xml"})                      # mayúscula (exportadores)
    assert DOC.texto_xlsx(p).split("\n")[1] == "Hola | 2026-11-10"
    q = libro(tmp_path / "n.xlsx", [("H", filas)])
    with zipfile.ZipFile(q) as z:
        rels = z.read("xl/_rels/workbook.xml.rels").decode("utf-8")
    rels = rels.replace("</Relationships>", f'<Relationship Id="rId90" Type="{REL}/sharedStrings" Target="textos/cualquiera.xml"/>'
                                             f'<Relationship Id="rId91" Type="{REL}/styles" Target="/xl/formatos/est.xml"/></Relationships>')
    reescribir(q, renombrar={"xl/sharedStrings.xml": "xl/textos/cualquiera.xml", "xl/styles.xml": "xl/formatos/est.xml"}, cambios={"xl/_rels/workbook.xml.rels": rels})
    assert DOC.texto_xlsx(q).split("\n")[1] == "Hola | 2026-11-10"
    r = libro(tmp_path / "o.xlsx", [("H", filas)])
    reescribir(r, renombrar={"xl/styles.xml": "xl/Styles.xml"})                                    # sin relación: búsqueda sin mayúsculas
    assert DOC.texto_xlsx(r).split("\n")[1] == "Hola | 2026-11-10"


def test_un_indice_negativo_de_cadena_o_de_estilo_es_invalido(tmp_path):
    filas = [["primera", "última", ("raw", ' t="s"><v>-1</v>'), ("raw", ' s="-1"><v>45000</v>')]]
    assert texto_de(tmp_path, filas) == ["primera | última |  | 45000"]


def test_un_entero_de_miles_de_cifras_no_tumba_el_libro(tmp_path):
    enorme = "9" * 5000
    t = texto_de(tmp_path, [["antes", ("raw", f"><v>{enorme}</v>"), "después"]])
    assert t[0].startswith("antes | " + "9" * 300 + "…") and t[0].endswith("| después")


# ---------------------------------------------------------------- J. las hojas de contactos no llegan al índice de fuentes
def test_knowledge_no_indexa_las_hojas_de_contactos(tmp_path):
    k = tmp_path / "Knowledge"
    libro(k / "equipo.xlsx", [("Contactos", [["Nombre", "Cargo"], ["Persona Ficticia", "Directora zzcontactozz"]]), ("Roles", [["Rol", "Función"], ["Revenue", "Aprueba cotizaciones"]])])
    g = Guardian(tmp_path / "raiz", tmp_path / "bandeja", tmp_path / "cache", solo_lectura=[k])
    fuentes, _inf = FU.indexar_knowledge(g, k, {})
    todo = " ".join(t[0] for e in fuentes.values() for t in e["trozos"])
    assert "Revenue | Aprueba cotizaciones" in todo and "Roles" in todo
    assert "Persona Ficticia" not in todo and "zzcontactozz" not in todo and "Contactos" not in todo


# ---------------------------------------------------------------- K. menores
def test_una_celda_de_fecha_iso_sale_sin_la_hora_en_cero(tmp_path):
    filas = [[("raw", ' t="d"><v>2024-03-01T00:00:00</v>'), ("raw", ' t="d"><v>2024-03-01T18:30:00</v>'), ("raw", ' t="d"><v>2024-03-01</v>'),
              ("raw", ' t="d"><v>2024-03-01T18:30:15.5Z</v>'), ("raw", ' t="d"><v>no es fecha</v>')]]
    assert texto_de(tmp_path, filas) == ["2024-03-01 | 2024-03-01 18:30 | 2024-03-01 | 2024-03-01 18:30 | no es fecha"]


@pytest.mark.parametrize("marca", ["1", "true", "TRUE", "on", "ON"])
def test_date1904_se_reconoce_con_varias_marcas(tmp_path, marca):
    p = libro(tmp_path / "d.xlsx", [("H", [[("n", "0", FECHA)]])])
    with zipfile.ZipFile(p) as z:
        wb = z.read("xl/workbook.xml").decode("utf-8")
    reescribir(p, cambios={"xl/workbook.xml": wb.replace('date1904="0"', f'date1904="{marca}"')})
    assert DOC.texto_xlsx(p).split("\n")[1] == "1904-01-01"
