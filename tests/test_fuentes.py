"""Fuentes del asesor (fase 2): lectura de .docx y .pptx por zipfile, PDF solo con librería, exclusiones de secretos, topes, índice BM25 incremental guardado en
cache\\ solo por el Guardian, Knowledge de SOLO LECTURA y sesiones anteriores del mismo proyecto vía backlog.py."""
import os
import threading
import time
import zipfile
from pathlib import Path

import pytest

from apuntes import backlog as BL
from apuntes import documentos as DOC
from apuntes import fuentes as FU
from apuntes.config import Config
from apuntes.rutas import Guardian, RutaProhibida

W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
AA = 'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"'


def crear_docx(ruta: Path, parrafos: list[str]) -> Path:
    cuerpo = "".join(f"<w:p><w:r><w:t xml:space=\"preserve\">{p}</w:t></w:r></w:p>" for p in parrafos)
    with zipfile.ZipFile(ruta, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("word/document.xml", f"<w:document {W}><w:body>{cuerpo}</w:body></w:document>")
    return ruta


def crear_pptx(ruta: Path, diapositivas: list[list[str]], notas: dict[int, str] | None = None) -> Path:
    with zipfile.ZipFile(ruta, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        for i, textos in enumerate(diapositivas, 1):
            z.writestr(f"ppt/slides/slide{i}.xml", f"<p:sld {AA}>" + "".join(f"<a:p><a:r><a:t>{t}</a:t></a:r></a:p>" for t in textos) + "</p:sld>")
        for i, t in (notas or {}).items():
            z.writestr(f"ppt/notesSlides/notesSlide{i}.xml", f"<p:notes {AA}><a:p><a:r><a:t>{t}</a:t></a:r></a:p></p:notes>")
    return ruta


# ================================================================ lectura de documentos de oficina
def test_texto_de_docx_y_pptx_por_zipfile(tmp_path):
    d = crear_docx(tmp_path / "oferta.docx", ["Propuesta de colaboración", "El piloto empieza el 20 de enero &amp; dura 6 semanas."])
    assert DOC.texto_docx(d) == "Propuesta de colaboración\nEl piloto empieza el 20 de enero & dura 6 semanas."
    p = crear_pptx(tmp_path / "deck.pptx", [["Portada", "Stratesys"], ["Plan", "Fase 1: simulación"]], {2: "Insistir en la fase 2"})
    t = DOC.texto_pptx(p)
    assert "[Diapositiva 1]\nPortada\nStratesys" in t and "[Diapositiva 2]\nPlan\nFase 1: simulación\nNotas: Insistir en la fase 2" in t


def test_diapositivas_en_orden_numerico_y_tope_de_texto(tmp_path):
    p = crear_pptx(tmp_path / "d.pptx", [[f"Texto de la diapositiva {i}"] for i in range(1, 13)])
    t = DOC.texto_pptx(p)
    assert t.index("diapositiva 2\n") < t.index("diapositiva 10") and DOC.texto_pptx(p, 60).count("[Diapositiva") <= 3


def test_un_zip_danado_o_que_no_es_office_no_se_lee(tmp_path):
    malo = tmp_path / "roto.docx"
    malo.write_bytes(b"esto no es un zip")
    with pytest.raises(DOC.Indisponible):
        DOC.texto_docx(malo)
    vacio = tmp_path / "otro.pptx"
    with zipfile.ZipFile(vacio, "w") as z:
        z.writestr("algo.txt", "x")
    with pytest.raises(DOC.Indisponible):
        DOC.texto_pptx(vacio)
    with pytest.raises(DOC.Indisponible):
        DOC.texto_de(tmp_path / "x.odt")


def test_un_zip_bomba_se_descarta_sin_descomprimirlo(tmp_path, monkeypatch):
    monkeypatch.setattr(DOC, "MAX_PARTE_BYTES", 1000)
    d = crear_docx(tmp_path / "grande.docx", ["x" * 5000])
    assert DOC.texto_docx(d) == ""


def test_pdf_solo_con_libreria_instalada(tmp_path, monkeypatch):
    monkeypatch.setattr(DOC, "libreria_pdf", lambda: None)
    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    with pytest.raises(DOC.Indisponible, match="no hay librería"):
        DOC.texto_pdf(pdf)


def test_el_guardian_lee_documentos_con_las_mismas_reglas_que_el_resto(tmp_path):
    base = tmp_path / "Knowledge"
    base.mkdir()
    g = Guardian(tmp_path / "raiz", tmp_path / "bandeja", tmp_path / "cache", solo_lectura=[base])
    ok = crear_docx(base / "oferta.docx", ["Texto normal.", "password: abcdefgh12345678", "Otro texto."])
    t = g.leer_documento(ok, base)
    assert "Texto normal." in t and "Otro texto." in t and "abcdefgh12345678" not in t and "[línea omitida: posible secreto]" in t
    for malo in (crear_docx(base / "credenciales.docx", ["x"]), crear_docx(base / ".env.docx", ["x"])):
        with pytest.raises(RutaProhibida):
            g.leer_documento(malo, base)
    fuera = crear_docx(tmp_path / "fuera.docx", ["x"])
    with pytest.raises(RutaProhibida, match="fuera"):
        g.leer_documento(fuera, base)
    (base / "x.exe").write_bytes(b"MZ")
    with pytest.raises(RutaProhibida, match="solo se leen"):
        g.leer_documento(base / "x.exe", base)
    assert g.leer_documento(base / "nota.txt", base) if (base / "nota.txt").write_text("hola") else True


def test_un_marcador_de_la_nube_sin_descargar_no_se_abre(tmp_path, monkeypatch):
    base = tmp_path / "K"
    base.mkdir()
    g = Guardian(tmp_path / "raiz", tmp_path / "bandeja", tmp_path / "cache")
    d = crear_docx(base / "nube.docx", ["x"])
    monkeypatch.setattr(DOC, "en_la_nube", lambda ruta: True)
    with pytest.raises(RutaProhibida, match="nube"):
        g.leer_documento(d, base)


# ================================================================ índice BM25
def indice():
    return FU.Indice([
        FU.Doc("02-alcance.md", "proyecto", [("Qué entra: alta de reservas de grupos, calendario de disponibilidad y hasta 3 usuarios por hotel.", None),
                                              ("Qué no entra: integración con el sistema de facturación SAP y aplicación móvil.", None)]),
        FU.Doc("Knowledge/oferta.docx", "knowledge", [("La licencia de Power BI Premium cuesta según capacidad; el precio depende del tamaño del modelo semántico.", None)]),
        FU.Doc("sesión 2026-10-01 · Kick off", "sesion", [("[05:10] R: el objetivo era empezar a hacer budget el 15 de noviembre con esta herramienta", 310)], 1800),
        FU.Doc("Contexto de la reunión", "reunion", [("Hoy se quiere cerrar el alcance de la fase 1 y decidir qué pasa con SAP.", None)]),
    ])


def test_bm25_ordena_por_palabras_con_plurales_y_sin_acentos():
    ix = indice()
    r = ix.buscar("¿Cuántos usuarios puede tener cada hotel?")
    assert r and r[0].etiqueta == "02-alcance.md" and r[0].id == "F1"
    r = ix.buscar("¿Cuánto cuesta la licencia de Power BI?")
    assert r[0].etiqueta == "Knowledge/oferta.docx"
    r = ix.buscar("¿Se cumple el objetivo del 15 de noviembre?")
    assert r[0].tipo == "sesion" and r[0].minuto_s == 310 and r[0].duracion_s == 1800
    assert ix.buscar("zzzz qqqq xxxxx") == [] and FU.Indice().buscar("algo") == []


def test_el_peso_de_la_fuente_desempata_a_favor_de_lo_mas_cercano_a_la_reunion():
    ix = FU.Indice([FU.Doc("a.md", "knowledge", [("El alcance de la fase uno incluye reservas y calendario", None)]),
                    FU.Doc("Contexto de la reunión", "reunion", [("El alcance de la fase uno incluye reservas y calendario", None)])])
    assert ix.buscar("alcance fase uno")[0].etiqueta == "Contexto de la reunión"


def test_el_contexto_de_lo_dicho_ayuda_a_una_pregunta_eliptica():
    ix = indice()
    assert ix.buscar("¿Y cuánto cuesta?")[0].etiqueta == "Knowledge/oferta.docx"
    r = ix.buscar("¿Y eso?", contexto="hablábamos de la facturación SAP y de la aplicación móvil")
    assert r and r[0].etiqueta == "02-alcance.md"


def test_los_extractos_respetan_el_tope_de_caracteres_y_el_maximo_por_documento():
    docs = [FU.Doc("a.md", "proyecto", [(f"reservas de grupos número {i}: " + "texto de relleno " * 12, None) for i in range(10)])]
    r = FU.Indice(docs).buscar("reservas de grupos", max_chars=500, k=8)
    assert sum(len(x.texto) for x in r) <= 500 and len(r) <= 2 + 1                                     # como mucho 2 por documento (y el tope manda)
    assert len(FU.Indice(docs).buscar("reservas de grupos", k=8, max_por_doc=2)) == 2


def test_trocear_markdown_por_secciones_con_el_titulo_y_sin_trozos_gigantes():
    texto = "# Alcance\n\n## Qué entra\n\n" + "\n".join(f"- punto {i} de lo que entra en el proyecto" for i in range(60)) + "\n\n## Qué no entra\n\n- SAP queda fuera de esta fase por completo"
    t = FU.trocear(texto)
    assert all(len(x) <= FU.TOPE_TROZO + 120 for x in t) and any(x.startswith("[Qué entra]") for x in t) and any("SAP queda fuera" in x for x in t)
    assert FU.trocear("") == [] and len(FU.trocear("palabra " * 5000, maximo=5)) == 5


# ================================================================ Knowledge: solo lectura, incremental, con exclusiones y topes
@pytest.fixture
def knowledge(tmp_path):
    k = tmp_path / "Knowledge"
    (k / "Ofertas").mkdir(parents=True)
    (k / "Ofertas" / "oferta.md").write_text("# Oferta\n\nLa licencia de Fabric se factura por capacidad reservada.\n", encoding="utf-8")
    crear_docx(k / "Ofertas" / "propuesta.docx", ["Propuesta de colaboración profesional", "El piloto de simulación dura seis semanas."])
    crear_pptx(k / "deck.pptx", [["Portada"], ["Arquitectura", "Lakehouse en OneLake"]])
    (k / "nota.txt").write_text("Nota suelta sobre el catálogo de hoteles y la integración.", encoding="utf-8")
    # lo que NO debe entrar
    (k / ".env").write_text("TOKEN=abcdefghijk\n", encoding="utf-8")
    (k / "secretos.md").write_text("El secreto del proyecto es zzzsecretozzz", encoding="utf-8")
    crear_docx(k / "credenciales.docx", ["clave zzzclavezzz"])
    (k / ".git").mkdir()
    (k / ".git" / "config.md").write_text("zzzgitzzz", encoding="utf-8")
    (k / "node_modules").mkdir()
    (k / "node_modules" / "x.md").write_text("zzznodezzz", encoding="utf-8")
    (k / "~$temporal.docx").write_bytes(b"lock")
    (k / "imagen.png").write_bytes(b"\x89PNG")
    (k / "Notas.md").write_text("Línea normal del cliente.\npassword: zzzpasswordzzzzz\nOtra línea normal.\n", encoding="utf-8")
    return k


def foto(carpeta: Path) -> dict:
    return {str(p.relative_to(carpeta)): (p.stat().st_mtime_ns, p.stat().st_size) for p in carpeta.rglob("*") if p.is_file()}


def test_indexar_knowledge_lee_md_txt_docx_pptx_y_respeta_las_exclusiones(tmp_path, knowledge):
    g = Guardian(tmp_path / "raiz", tmp_path / "bandeja", tmp_path / "cache", solo_lectura=[knowledge])
    antes = foto(knowledge)
    fuentes, inf = FU.indexar_knowledge(g, knowledge, {})
    assert foto(knowledge) == antes                                                               # SOLO LECTURA: ni un fichero tocado ni creado
    nombres = {e["etiqueta"] for e in fuentes.values()}
    assert nombres == {"Knowledge/Ofertas/oferta.md", "Knowledge/Ofertas/propuesta.docx", "Knowledge/deck.pptx", "Knowledge/nota.txt", "Knowledge/Notas.md"}
    todo = " ".join(t[0] for e in fuentes.values() for t in e["trozos"])
    for prohibido in ("zzzsecretozzz", "zzzclavezzz", "zzzgitzzz", "zzznodezzz", "zzzpasswordzzzzz", "abcdefghijk"):
        assert prohibido not in todo, prohibido
    assert "Línea normal del cliente." in todo and "[línea omitida: posible secreto]" in todo and "seis semanas" in todo and "Lakehouse en OneLake" in todo
    assert inf.nuevos == 5 and inf.reutilizados == 0 and inf.completo and inf.omitidos >= 2           # .env y secretos.md/credenciales.docx por su nombre


def test_el_indice_es_incremental_por_fecha_y_tamano(tmp_path, knowledge):
    g = Guardian(tmp_path / "raiz", tmp_path / "bandeja", tmp_path / "cache", solo_lectura=[knowledge])
    f1, _ = FU.indexar_knowledge(g, knowledge, {})
    f2, inf2 = FU.indexar_knowledge(g, knowledge, f1)
    assert inf2.nuevos == 0 and inf2.reutilizados == 5 and f2 == f1
    (knowledge / "nota.txt").write_text("Nota nueva y más larga sobre el catálogo de hoteles y la integración con SAP.", encoding="utf-8")
    f3, inf3 = FU.indexar_knowledge(g, knowledge, f2)
    assert inf3.nuevos == 1 and inf3.reutilizados == 4 and "SAP" in str(f3[os.path.normcase("nota.txt")])
    (knowledge / "nota.txt").unlink()
    f4, _ = FU.indexar_knowledge(g, knowledge, f3)
    assert os.path.normcase("nota.txt") not in f4


def test_topes_de_tamano_y_de_numero_de_ficheros(tmp_path, knowledge):
    g = Guardian(tmp_path / "raiz", tmp_path / "bandeja", tmp_path / "cache", solo_lectura=[knowledge])
    (knowledge / "enorme.md").write_text("palabra " * 100_000, encoding="utf-8")
    f, inf = FU.indexar_knowledge(g, knowledge, {}, tope_bytes=200_000)
    assert "Knowledge/enorme.md" not in {e["etiqueta"] for e in f.values()} and inf.omitidos >= 1
    f, inf = FU.indexar_knowledge(g, knowledge, {}, max_ficheros=2)
    assert inf.ficheros == 2 and not inf.completo and "parcial" in " ".join(inf.avisos)
    f, inf = FU.indexar_knowledge(g, knowledge, {}, tiempo_s=-1)                                  # sin tiempo: no lee nada pero no falla ni bloquea
    assert not inf.completo and f == {}


def test_un_pdf_sin_libreria_se_omite_y_un_marcador_de_la_nube_no_se_abre(tmp_path, knowledge, monkeypatch):
    g = Guardian(tmp_path / "raiz", tmp_path / "bandeja", tmp_path / "cache", solo_lectura=[knowledge])
    (knowledge / "informe.pdf").write_bytes(b"%PDF-1.4 ...")
    monkeypatch.setattr(DOC, "libreria_pdf", lambda: None)
    f, inf = FU.indexar_knowledge(g, knowledge, {})
    assert inf.sin_formato == 1 and "Knowledge/informe.pdf" not in {e["etiqueta"] for e in f.values()}
    real = DOC.en_la_nube
    monkeypatch.setattr(DOC, "en_la_nube", lambda ruta: str(ruta).endswith("propuesta.docx") or real(ruta))
    f, inf = FU.indexar_knowledge(g, knowledge, {})
    assert inf.en_la_nube == 1 and "Knowledge/Ofertas/propuesta.docx" not in {e["etiqueta"] for e in f.values()}


def test_el_servicio_guarda_el_indice_en_cache_solo_por_el_guardian_y_no_bloquea(tmp_path, knowledge, monkeypatch):
    g = Guardian(tmp_path / "raiz", tmp_path / "bandeja", tmp_path / "cache", solo_lectura=[knowledge])
    cfg = Config(tmp_path / "config.json")
    cfg.actualizar({"knowledge": str(knowledge)}, guardar=False)
    antes = foto(knowledge)
    s = FU.ServicioFuentes(g, cfg)
    s.arrancar().join(20)
    assert s.listo_knowledge.is_set() and s.informe_knowledge.nuevos == 5
    r = s.buscar("¿Cuánto dura el piloto de simulación?")
    assert r and r[0].etiqueta == "Knowledge/Ofertas/propuesta.docx" and r[0].tipo == "knowledge"
    guardados = list((tmp_path / "cache").glob("indice-knowledge-*.json"))
    assert len(guardados) == 1 and foto(knowledge) == antes
    # un segundo arranque con la caché disponible responde AL MOMENTO, aunque la pasada de Knowledge tarde (OneDrive lento)
    suelta = threading.Event()

    def lento(*a, **k):
        suelta.wait(10)
        return {}, FU.Informe()
    monkeypatch.setattr(FU, "indexar_knowledge", lento)
    s2 = FU.ServicioFuentes(g, cfg)
    t0 = time.monotonic()
    hilo = s2.arrancar()
    assert time.monotonic() - t0 < 2 and not s2.listo_knowledge.is_set()
    assert s2.buscar("¿Cuánto dura el piloto de simulación?")[0].etiqueta == "Knowledge/Ofertas/propuesta.docx"
    suelta.set()
    hilo.join(5)


def test_el_servicio_con_knowledge_ausente_no_falla(tmp_path):
    g = Guardian(tmp_path / "raiz", tmp_path / "bandeja", tmp_path / "cache")
    cfg = Config(tmp_path / "config.json")
    cfg.actualizar({"knowledge": str(tmp_path / "no existe")}, guardar=False)
    s = FU.ServicioFuentes(g, cfg)
    s.arrancar().join(10)
    assert s.buscar("algo") == [] and s.estado()["knowledge_listo"]


# ================================================================ proyecto, contexto de la reunión y sesiones anteriores (backlog.py)
SESION_ANTERIOR = """---
tema: "Kick off"
proyecto: "ProyA"
fecha: 2026-10-01
inicio: 10:00
duracion: 30:00
estado: finalizada
---

# Kick off

## Resumen

Se acordó que la herramienta se usaría para el presupuesto de noviembre.

## Insights

- [05:10] **Decisión:** El objetivo es empezar a hacer budget el 15 de noviembre
- [07:00] **Riesgo:** El catálogo de hoteles puede llegar tarde

## Transcripción

[05:10] **Reunión:** el objetivo era empezar a hacer budget el quince de noviembre con esta herramienta
[06:00] **Reunión:** el catálogo de hoteles lo entrega el cliente
"""


@pytest.fixture
def proyecto(tmp_path):
    raiz = tmp_path / "proyectos"
    ctx = raiz / "ProyA" / "00. CONTEXTO (IA)"
    ctx.mkdir(parents=True)
    (ctx / "02-alcance.md").write_text("# Alcance\n\nHasta 3 usuarios por hotel y calendario de disponibilidad. SAP queda fuera de la fase 1.\n" + "Relleno de alcance. " * 20, encoding="utf-8")
    (raiz / "ProyA" / "02. Sesiones (transcripciones)").mkdir()
    (raiz / "ProyA" / "02. Sesiones (transcripciones)" / "2026-10-01-kick-off.md").write_text(SESION_ANTERIOR, encoding="utf-8")
    (raiz / "ProyA" / "02. Sesiones (transcripciones)" / "2026-11-05-hoy.md").write_text(SESION_ANTERIOR.replace("Kick off", "Hoy").replace("zzz", ""), encoding="utf-8")
    g = Guardian(raiz, tmp_path / "bandeja", tmp_path / "cache")
    cfg = Config(tmp_path / "config.json")
    cfg.actualizar({"raiz_proyectos": str(raiz), "knowledge": ""}, guardar=False)
    return g, cfg


def test_el_servicio_indexa_proyecto_reunion_y_sesiones_anteriores_menos_la_actual(proyecto):
    g, cfg = proyecto
    s = FU.ServicioFuentes(g, cfg, BL.Backlog(g, cfg))
    s.preparar_proyecto("ProyA", "2026-11-05-hoy.md", "Hoy queremos cerrar el alcance de la fase 1 y el calendario de pagos.").join(20)
    r = s.buscar("¿Cuántos usuarios por hotel entran?")
    assert r[0].etiqueta == "02-alcance.md" and r[0].tipo == "proyecto"
    r = s.buscar("¿Se cumple el objetivo del 15 de noviembre de empezar el budget?")
    assert r[0].tipo == "sesion" and r[0].etiqueta.startswith("sesión 2026-10-01 · Kick off") and r[0].duracion_s == 1800
    assert not any("Hoy" in x.etiqueta for x in s.buscar("objetivo budget noviembre herramienta", k=8))   # la sesión en curso no es «anterior»
    r = s.buscar("calendario de pagos de la fase 1")
    assert r[0].etiqueta == "Contexto de la reunión" and r[0].tipo == "reunion"
    assert s.estado()["proyecto"] == {"ficheros": 1, "sesiones": 1}
    # la caché del proyecto vive en cache\ (vía Guardian) y un segundo arranque reutiliza las sesiones sin releerlas
    assert len(list((g.cache).glob("indice-proyecto-*.json"))) == 1
    s.olvidar_reunion()
    assert s.buscar("calendario de pagos de la fase 1") == []


def test_sin_proyecto_solo_queda_el_contexto_de_la_reunion(proyecto):
    g, cfg = proyecto
    s = FU.ServicioFuentes(g, cfg, BL.Backlog(g, cfg))
    s.preparar_proyecto(None, "", "Queremos hablar del calendario de pagos de la fase 1.").join(10)
    assert [x.etiqueta for x in s.buscar("calendario de pagos")] == ["Contexto de la reunión"]


# ================================================================ el indexado en segundo plano no compite con la transcripción
def _servicio_con_cache(tmp_path, knowledge):
    """Servicio con Knowledge ya indexado y guardado en la caché (el estado normal al empezar una reunión) y contadores de reconstrucciones y tokenizaciones."""
    g = Guardian(tmp_path / "raiz", tmp_path / "bandeja", tmp_path / "cache", solo_lectura=[knowledge])
    cfg = Config(tmp_path / "config.json")
    cfg.actualizar({"knowledge": str(knowledge), "raiz_proyectos": str(tmp_path / "raiz")}, guardar=False)
    FU.ServicioFuentes(g, cfg).arrancar().join(20)
    return g, cfg


def test_empezar_la_reunion_no_rehace_ni_retokeniza_lo_ya_indexado(tmp_path, knowledge, monkeypatch):
    g, cfg = _servicio_con_cache(tmp_path, knowledge)
    FU._terminos_trozo.cache_clear()
    llamadas = []
    original = FU.tokenizar
    monkeypatch.setattr(FU, "tokenizar", lambda t: llamadas.append(t) or original(t))
    s = FU.ServicioFuentes(g, cfg)
    s.arrancar().join(20)
    # arranque con caché y sin cambios en Knowledge: UNA sola reconstrucción (la de la caché) y el hilo no rehace nada
    assert s.reconstrucciones == 1
    assert s.buscar("¿Cuánto dura el piloto de simulación?")[0].etiqueta == "Knowledge/Ofertas/propuesta.docx"
    base = len(llamadas)   # (buscar tokeniza la consulta; eso no es indexado)
    # empezar una reunión sin proyecto ni contexto: no se toca el índice y no se tokeniza nada
    s.preparar_proyecto(None).join(20)
    assert s.reconstrucciones == 1 and len(llamadas) == base
    # …y tampoco con una reunión previa en memoria: se rehace una vez al limpiar y NO se retokeniza Knowledge
    s.preparar_proyecto(None, "", "Contexto de esta reunión sobre el piloto de simulación y su calendario").join(20)
    assert s.reconstrucciones == 2
    nuevos = llamadas[base:]
    assert len(nuevos) == 1 and "Contexto de esta reunión" in nuevos[0]   # solo se tokeniza lo nuevo
    assert s.buscar("calendario del piloto de simulación")[0].tipo in ("reunion", "knowledge")


def test_un_fichero_de_knowledge_cambiado_si_se_vuelve_a_indexar(tmp_path, knowledge):
    g, cfg = _servicio_con_cache(tmp_path, knowledge)
    (knowledge / "nota.txt").write_text("Nota nueva sobre la migración del catálogo de tarifas a OneLake.", encoding="utf-8")
    s = FU.ServicioFuentes(g, cfg)
    s.arrancar().join(20)
    assert s.reconstrucciones == 2   # el de la caché y el de la pasada, que sí tiene un cambio
    assert s.buscar("migración del catálogo de tarifas")[0].etiqueta == "Knowledge/nota.txt"


def test_el_proyecto_se_anade_con_una_reconstruccion_y_buscar_usa_el_ultimo_indice(proyecto):
    g, cfg = proyecto
    s = FU.ServicioFuentes(g, cfg, BL.Backlog(g, cfg))
    s.preparar_proyecto("ProyA", "2026-11-05-hoy.md").join(20)
    assert s.reconstrucciones == 1   # antes eran dos: una al empezar (vacía) y otra al terminar el hilo
    assert s.buscar("¿Cuántos usuarios por hotel entran?")[0].etiqueta == "02-alcance.md"


def test_los_hilos_de_indexado_bajan_su_prioridad(tmp_path, knowledge, proyecto, monkeypatch):
    llamadas = []
    monkeypatch.setattr(FU, "_prioridad_baja", lambda: llamadas.append(threading.current_thread().name))
    g, cfg = proyecto
    s = FU.ServicioFuentes(g, cfg, BL.Backlog(g, cfg))
    s.preparar_proyecto("ProyA").join(20)
    assert llamadas == ["fuentes-proyecto"]
    cfg.actualizar({"knowledge": str(knowledge)}, guardar=False)
    s.arrancar().join(20)
    assert llamadas == ["fuentes-proyecto", "fuentes-knowledge"]


def test_prioridad_baja_no_falla_si_la_llamada_del_sistema_falla(monkeypatch):
    import ctypes
    monkeypatch.setattr(FU.os, "name", "nt")
    monkeypatch.setattr(ctypes, "windll", None, raising=False)   # sin windll (o roto): no hace nada y no lanza
    FU._prioridad_baja()
    monkeypatch.setattr(FU.os, "name", "posix")
    FU._prioridad_baja()


# ================================================================ cambiar de carpeta de Knowledge con un indexado todavía en marcha
class _IndexadoresControlados:
    """Sustituye a `indexar_knowledge`: cada llamada espera a su propio Event (en `llamadas`, por orden) y devuelve un documento con la palabra de la carpeta."""

    def __init__(self, monkeypatch):
        self.llamadas: list[tuple[str, threading.Event]] = []
        self.cortes: list[bool] = []
        monkeypatch.setattr(FU, "indexar_knowledge", self)

    def __call__(self, g, raiz, previo, *a, cortar=None, **k):
        nombre = Path(raiz).name
        suelta = threading.Event()
        self.llamadas.append((nombre, suelta))
        suelta.wait(10)
        self.cortes.append(bool(cortar and cortar()))
        inf = FU.Informe()
        inf.ficheros = len(self.llamadas) * 100 + {"A": 1, "B": 2}[nombre]       # distingue qué llamada produjo el informe
        doc = {"firma": "1:1", "etiqueta": f"Knowledge/{nombre}.md", "tipo": "knowledge", "trozos": [[f"documento exclusivo de la carpeta {nombre.lower()}zz", None]]}
        return {f"{nombre}.md": doc}, inf

    def soltar(self, i: int) -> None:
        self.llamadas[i][1].set()


def _servicio_ab(tmp_path, monkeypatch):
    g = Guardian(tmp_path / "raiz", tmp_path / "bandeja", tmp_path / "cache")
    cfg = Config(tmp_path / "config.json")
    a, b = tmp_path / "A", tmp_path / "B"
    a.mkdir()
    b.mkdir()
    cfg.actualizar({"knowledge": str(a)}, guardar=False)
    return g, cfg, FU.ServicioFuentes(g, cfg), _IndexadoresControlados(monkeypatch), a, b


def _etiquetas(s, marca):
    return [r.etiqueta for r in s.buscar(f"documento exclusivo de la carpeta {marca}")]


def _esperar(cond, s=5.0):
    t0 = time.monotonic()
    while not cond() and time.monotonic() - t0 < s:
        time.sleep(0.01)
    assert cond()


def test_el_hilo_de_la_carpeta_anterior_no_pisa_el_estado_de_la_nueva(tmp_path, monkeypatch):
    g, cfg, s, ind, a, b = _servicio_ab(tmp_path, monkeypatch)
    hilo_a = s.arrancar()
    _esperar(lambda: len(ind.llamadas) == 1)
    cfg.actualizar({"knowledge": str(b)}, guardar=False)
    hilo_b = s.cambiar_knowledge()
    _esperar(lambda: len(ind.llamadas) == 2)
    ind.soltar(0)                                                  # termina A, que ya no es la carpeta vigente
    hilo_a.join(5)
    assert not hilo_a.is_alive()
    assert not s.listo_knowledge.is_set() and s.informe_knowledge is None
    assert not list((tmp_path / "cache").glob("indice-knowledge-*.json"))        # tampoco guarda su caché
    assert "Knowledge/A.md" not in _etiquetas(s, "azz")                           # ni mete su índice
    assert ind.cortes[0] is True                                                  # y se le avisó de que dejara de leer
    ind.soltar(1)
    hilo_b.join(5)
    assert s.listo_knowledge.is_set() and s.informe_knowledge.ficheros == 202
    assert _etiquetas(s, "bzz")[:1] == ["Knowledge/B.md"] and "Knowledge/A.md" not in _etiquetas(s, "azz")


def test_de_a_a_b_y_otra_vez_a_el_primer_resultado_de_a_se_descarta(tmp_path, monkeypatch):
    g, cfg, s, ind, a, b = _servicio_ab(tmp_path, monkeypatch)
    hilo_a1 = s.arrancar()
    _esperar(lambda: len(ind.llamadas) == 1)
    cfg.actualizar({"knowledge": str(b)}, guardar=False)
    hilo_b = s.cambiar_knowledge()
    _esperar(lambda: len(ind.llamadas) == 2)
    cfg.actualizar({"knowledge": str(a)}, guardar=False)
    hilo_a3 = s.cambiar_knowledge()
    _esperar(lambda: len(ind.llamadas) == 3)
    ind.soltar(0)                                                  # el primer hilo de A: la carpeta vuelve a ser A, pero esta pasada es de otra generación
    hilo_a1.join(5)
    assert not s.listo_knowledge.is_set() and s.informe_knowledge is None
    assert not list((tmp_path / "cache").glob("indice-knowledge-*.json"))
    ind.soltar(1)
    hilo_b.join(5)
    assert not s.listo_knowledge.is_set() and s.informe_knowledge is None
    ind.soltar(2)
    hilo_a3.join(5)
    assert s.listo_knowledge.is_set() and s.informe_knowledge.ficheros == 301        # el de la tercera llamada, no el de la primera (101)
    assert _etiquetas(s, "azz")[:1] == ["Knowledge/A.md"] and "Knowledge/B.md" not in _etiquetas(s, "bzz")


def test_indexar_knowledge_se_detiene_si_se_lo_piden(tmp_path, knowledge):
    g = Guardian(tmp_path / "raiz", tmp_path / "bandeja", tmp_path / "cache", solo_lectura=[knowledge])
    fuentes, _inf = FU.indexar_knowledge(g, knowledge, {}, cortar=lambda: True)
    assert fuentes == {}
