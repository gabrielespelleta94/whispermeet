"""Ola D en la interfaz: panel «Antes de la primera reunión» (inicio y Ajustes) y los tres ajustes nuevos (carpeta de Knowledge, vocabulario de transcripción y ancho de
búsqueda de Whisper) en un Edge sin cabeza sobre la interfaz REAL con dobles de `fetch` y `WebSocket` (`_visual_harness.py`; datos ficticios, sin servidor ni modelo)."""
from __future__ import annotations

import json
import re
import socket
import time

import pytest

from _visual_harness import WEB, Edge, foto, pagina_html

HTML = (WEB / "index.html").read_text(encoding="utf-8")
JS = (WEB / "requisitos.js").read_text(encoding="utf-8")
AJ = (WEB / "ajustes.js").read_text(encoding="utf-8")
CSS = re.sub(r"/\*.*?\*/", "", (WEB / "requisitos.css").read_text(encoding="utf-8"), flags=re.S)


def _c(clave, titulo, estado, detalle, como=""):
    return {"clave": clave, "titulo": titulo, "estado": estado, "detalle": detalle, "como_arreglarlo": como}


def requisitos(py="bien", claude="bien", modelo="bien", audio="bien", proyectos="bien", knowledge="bien", locales="bien"):
    lista = [
        _c("python", "Python", py, "Python 3.12.4." if py == "bien" else "Esta app corre con Python 3.10.1 y necesita 3.12 o superior.", "" if py == "bien" else "Instala Python 3.12 o superior desde python.org y vuelve a ejecutar instalar.bat."),
        _c("claude", "Claude Code (claude)", claude, "Se encuentra «claude» en el PATH." if claude == "bien" else "No se encuentra «claude» en el PATH. Sin él la transcripción funciona, pero no hay análisis, resúmenes ni asesor.",
           "" if claude == "bien" else "Instala Claude Code, abre una terminal nueva, escribe «claude» y entra con tu cuenta. Después pulsa «Volver a comprobar»."),
        _c("modelo_whisper", "Modelo de transcripción (Whisper)", modelo, "Modelo «small» descargado." if modelo == "bien" else "El modelo «small» todavía no está descargado.",
           "" if modelo == "bien" else "Ejecuta instalar.bat y acepta descargar el modelo, o empieza una reunión con conexión a internet: se descarga la primera vez."),
        _c("audio", "Micrófono y audio de la reunión", audio, "1 micrófono y 1 salida de audio." if audio == "bien" else "1 micrófono, pero ninguna salida de audio de la que recoger lo que dicen los demás.",
           "" if audio == "bien" else "Sin audio de la reunión solo se transcribe tu micrófono. Revisa los altavoces o auriculares que usa Windows."),
        _c("carpeta_proyectos", "Carpeta de proyectos", proyectos, "Carpeta «Proyectos»." if proyectos == "bien" else "La carpeta «Proyectos» no existe.",
           "" if proyectos == "bien" else "Crea la carpeta o elige otra en Ajustes (Privacidad, «Carpeta que contiene tus proyectos»)."),
        _c("carpeta_knowledge", "Carpeta de Knowledge", knowledge, "Sin Knowledge: es opcional (documentos de consulta de solo lectura)." if knowledge == "bien" else "La carpeta «Documentación» no existe o no está disponible.",
           "" if knowledge == "bien" else "Sin ella no se consultan esos documentos. Corrígela o vacíala en Ajustes (Privacidad)."),
        _c("carpetas_locales", "Carpetas locales de la app", locales, "Se puede escribir donde la app guarda sus datos." if locales == "bien" else "No se puede escribir en: planes.",
           "" if locales == "bien" else "Mueve la app a una carpeta donde tu usuario pueda escribir."),
    ]
    faltan, avisos = sum(x["estado"] == "falta" for x in lista), sum(x["estado"] == "aviso" for x in lista)
    return {"estado": "falta" if faltan else ("aviso" if avisos else "bien"), "faltan": faltan, "avisos": avisos, "comprobaciones": lista}


CONFIG = {"excluir_captura": True, "whisper_beam": 5, "vocabulario_transcripcion": ["Cupo de grupos", "Motor de cotización"], "knowledge": "",
          "modelos": {"digest": "haiku", "equipo": "haiku", "periodico": "haiku", "final": "sonnet", "contradicciones_confirmar": "sonnet", "consulta": "haiku", "pulido": "opus"},
          "min_palabras_analisis": 150, "esfuerzo": "low", "detectar_llamadas": True, "filtrar_eco": True, "whisper_modelo": "small", "raiz_proyectos": "X:/Proyectos"}
PROYECTOS = [{"nombre": "Alfa Demo", "compartido": False, "extra": False, "tiene_contexto": True, "tiene_sesiones": True, "ruta": "X:/r/Alfa Demo", "plan": None, "n_sesiones": 3, "ultima_sesion": "2026-11-05", "n_md": 9},
             {"nombre": "Beta Demo", "compartido": False, "extra": False, "tiene_contexto": False, "tiene_sesiones": False, "ruta": "X:/r/Beta Demo", "plan": None, "n_md": 2}]

# El «servidor» de la página: un enrutador de `fetch` que anota las llamadas y puede responder el error de un campo a PUT /api/config
ROUTER = """(() => {
  window.__llamadas = []; window.__puts = [];
  const CONFIG = %s, PROYECTOS = %s;
  window.__REQ = %s; window.__PUT_ERROR = null;
  window.fetch = async (u, o) => {
    const m = (o && o.method) || 'GET'; window.__llamadas.push(m + ' ' + u);
    const r = (d, ok = true, status = ok ? 200 : 400) => ({ ok, status, json: async () => d });
    if (/\\/api\\/info/.test(u)) return r({ simulacion: false, config: CONFIG });
    if (/\\/api\\/dispositivos/.test(u)) return r({ error: '', entradas: [{ indice: 1, nombre: 'Micrófono ficticio', canales: 1, frecuencia: 16000 }], salidas: [{ indice: 2, nombre: 'Altavoces ficticios', canales: 2, frecuencia: 48000 }], mic_defecto: 1, sistema_defecto: 2 });
    if (/\\/api\\/ventana/.test(u)) return r({ nativa: false });
    if (/\\/api\\/requisitos/.test(u)) { window.__veces = (window.__veces || 0) + 1; return r(window.__REQ); }
    if (/api\\/proyectos\\/resumen/.test(u)) return r({ resumen: {}, parcial: false });
    if (/api\\/proyectos\\?/.test(u)) return r({ raiz: 'X:/Proyectos', proyectos: PROYECTOS });
    if (m === 'PUT' && /\\/api\\/config/.test(u)) {
      const cuerpo = JSON.parse(o.body); window.__puts.push(cuerpo);
      if (window.__PUT_ERROR) return r(window.__PUT_ERROR, false, 400);
      return r({ config: Object.assign({}, CONFIG, cuerpo) });
    }
    return r({});
  };
  return 1;
})()"""


def _puerto():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def pagina(tmp_path_factory):
    return pagina_html(tmp_path_factory.mktemp("req-ui") / "app.html")


@pytest.fixture(scope="module")
def edge(tmp_path_factory):
    e = Edge(tmp_path_factory.mktemp("edge-req"), _puerto(), ancho=1280, alto=800)
    yield e
    e.cerrar()


def abrir(edge, pagina, req=None, ancho=1280, alto=800, esquema="dark", visto=False):
    """La interfaz en el inicio, con `req` como respuesta de /api/requisitos."""
    edge.cmd("Emulation.setDeviceMetricsOverride", width=ancho, height=alto, deviceScaleFactor=1, mobile=False)
    edge.cmd("Emulation.setEmulatedMedia", features=[{"name": "prefers-color-scheme", "value": esquema}])
    edge.abrir(pagina.as_uri())
    edge.js("localStorage.clear(); sessionStorage.clear(); 1")
    if visto:
        edge.js("localStorage.setItem('apuntes_req_visto', '1'); 1")
    edge.abrir(pagina.as_uri())
    edge.js(ROUTER % (json.dumps(CONFIG), json.dumps(PROYECTOS), json.dumps(req or requisitos())))
    edge.js("window.__emitir(Object.assign({tipo: 'snapshot'}, %s)); 1" % json.dumps(foto(estado="inactivo")))
    edge.js("(async () => { await AP.requisitos.comprobar(); await AP.cargarProyectos(); })().then(() => 1)")
    time.sleep(0.5)


def estado_panel(edge):
    return json.loads(edge.js("""JSON.stringify((() => {
      const p = document.querySelector('#i-requisitos'), r = p.getBoundingClientRect();
      return { oculto: p.hidden, visible: getComputedStyle(p).display !== 'none' && r.height > 0, res: document.querySelector('#req-res').textContent,
        filas: [...p.querySelectorAll('.req-fila')].map((f) => ({ clave: f.dataset.clave, estado: f.dataset.estado, est: f.querySelector('.req-est').textContent, como: !!f.querySelector('.req-como') })),
        titulo: p.querySelector('h2').textContent, rect: [r.left, r.top, r.right, r.bottom],
        ok: (() => { const o = document.querySelector('#req-ok'); return o && !o.hidden && o.getBoundingClientRect().height > 0 ? o.textContent : ''; })() };
    })())"""))


# ============================================================ estáticos
def test_el_html_tiene_el_panel_y_los_campos_nuevos():
    assert HTML.index('id="i-requisitos"') < HTML.index('id="i-lista"')                          # el panel va encima de la lista de proyectos
    assert re.search(r'<section class="requisitos" id="i-requisitos" aria-labelledby="req-tit" hidden>', HTML)
    for s in ("Antes de la primera reunión", "Volver a comprobar", "Ocultar"):
        assert s in HTML, s
    for i in ('id="req-lista"', 'id="req-ok"', 'id="aj-req-lista"', 'id="aj-req-recomprobar"', 'name="whisper_beam"', 'name="vocabulario_transcripcion"', 'name="knowledge"',
              'id="aj-beam-error"', 'id="aj-vocab-error"', 'id="aj-knowledge-error"', 'id="aj-raiz-error"', 'id="aj-modelo-error"'):
        assert i in HTML, i
    assert HTML.index('id="aj-c-beam"') < HTML.index('id="aj-c-knowledge"')
    assert re.search(r'Más ancho acierta más y va más lento', HTML)                              # la ayuda del ancho de búsqueda
    assert re.search(r'<input class="input" name="whisper_beam" type="number" min="1" max="10"', HTML)
    assert re.search(r'<label class="t-label" for="aj-vocab">', HTML) and re.search(r'<label class="t-label" for="aj-knowledge">', HTML)    # etiquetas asociadas
    assert HTML.index("/static/ajustes.js") < HTML.index("/static/requisitos.js") and "/static/requisitos.css" in HTML
    # los tres campos están en su sección: Audio (ancho y vocabulario) y Privacidad (Knowledge)
    audio, priv = HTML[HTML.index('id="aj-audio"'):HTML.index('id="aj-equipo"')], HTML[HTML.index('id="aj-privacidad"'):HTML.index('id="s-error"')]
    assert 'name="whisper_beam"' in audio and 'name="vocabulario_transcripcion"' in audio and 'id="aj-requisitos"' in audio and 'name="knowledge"' in priv


def test_css_sin_recortes_con_puntos_y_con_la_escala_de_cinco_tamanos():
    assert "text-overflow" not in CSS and "line-clamp" not in CSS
    assert not re.findall(r"font-size: (?!var\(--f-)", CSS)
    assert "uppercase" not in CSS
    codigo = re.sub(r"/\*.*?\*/", "", JS + AJ, flags=re.S)
    assert "innerHTML" not in codigo and "insertAdjacentHTML" not in codigo                      # todo texto dinámico entra con textContent
    assert not re.search(r"\.(bien|aviso|falta)\b[^{]*\{[^}]*(?<![-\w])color:\s*#", CSS)           # solo colores por variable


def test_textos_en_espanol_sin_signos_de_exclamacion():
    nuevo = HTML[HTML.index('id="i-requisitos"'):HTML.index('id="i-lista"')] + HTML[HTML.index('id="aj-c-beam"'):HTML.index('<label class="check"><input type="checkbox" name="filtrar_eco">')]
    textos = re.findall(r">([^<>]+)<", nuevo) + re.findall(r"(?:title|placeholder|aria-label)=\"([^\"]+)\"", nuevo)
    cadenas = re.findall(r"\"([^\"\n]*[a-záéíóúñ][^\"\n]*)\"", JS) + re.findall(r"`([^`\n]+)`", JS)
    for t in textos + cadenas:
        assert "!" not in t.replace("!==", "").replace("!=", "") or not re.search(r"[A-Za-zÁ-ú.]!", t), t
        assert "¡" not in t, t
    assert "Ã" not in HTML and "Ã" not in JS and "Ã" not in AJ                                  # sin mojibake


# ============================================================ el panel del inicio
def test_con_algo_en_falta_el_panel_sale_con_la_lista_y_que_hacer(edge, pagina):
    abrir(edge, pagina, requisitos(claude="falta", audio="aviso"))
    e = estado_panel(edge)
    assert e["visible"] and e["titulo"] == "Antes de la primera reunión" and e["res"] == "Falta 1 cosa · 1 aviso"
    assert [f["clave"] for f in e["filas"]] == ["claude", "audio"]                                # en el inicio, solo lo que no está bien
    por = {f["clave"]: f for f in e["filas"]}
    assert por["claude"]["est"] == "Falta" and por["audio"]["est"] == "Aviso"
    assert por["claude"]["como"] and por["audio"]["como"]                                        # y con «Qué hacer»
    assert e["ok"] == "Las otras 5 comprobaciones están en orden."
    texto = edge.js("document.querySelector('#req-lista').innerText")
    assert "Qué hacer:" in texto and "escribe «claude» y entra con tu cuenta" in texto
    r = e["rect"]
    assert r[0] >= 0 and r[2] <= 1280 and r[3] <= 800                                            # cabe en la ventana, no la tapa ni la desborda


def test_si_todo_esta_bien_no_molesta(edge, pagina):
    abrir(edge, pagina, requisitos())
    e = estado_panel(edge)
    assert e["oculto"] and not e["visible"]
    assert estado_panel(edge)["res"] == "Todo en orden."                                         # y el resumen sigue disponible para Ajustes


def test_solo_avisos_salen_la_primera_vez_y_ocultar_lo_recuerda(edge, pagina):
    abrir(edge, pagina, requisitos(audio="aviso"))
    assert estado_panel(edge)["visible"]                                                         # primer arranque: se enseña
    edge.js("document.querySelector('#req-cerrar').click(); 1")
    time.sleep(0.2)
    assert not estado_panel(edge)["visible"] and edge.js("localStorage.getItem('apuntes_req_visto')") == "1"
    assert edge.js("document.activeElement.id") == "i-buscar"                                    # el foco no se pierde
    abrir(edge, pagina, requisitos(audio="aviso"), visto=True)
    assert not estado_panel(edge)["visible"]                                                     # la próxima vez ya no molesta por un aviso


def test_lo_que_falta_vuelve_a_salir_aunque_se_haya_ocultado(edge, pagina):
    abrir(edge, pagina, requisitos(modelo="falta"))
    edge.js("document.querySelector('#req-cerrar').click(); 1")
    time.sleep(0.2)
    assert not estado_panel(edge)["visible"] and edge.js("localStorage.getItem('apuntes_req_visto')") is None   # «falta» no se da por visto
    abrir(edge, pagina, requisitos(modelo="falta"))
    assert estado_panel(edge)["visible"]                                                         # reabrir la app: sigue faltando, sale


def test_volver_a_comprobar_pide_de_nuevo_y_no_desaparece_bajo_el_cursor(edge, pagina):
    abrir(edge, pagina, requisitos(claude="falta"))
    antes = edge.js("window.__veces")
    edge.js("window.__REQ = %s; document.querySelector('#req-recomprobar').click(); 1" % json.dumps(requisitos()))      # el usuario arregla algo y pulsa
    time.sleep(0.4)
    e = estado_panel(edge)
    assert edge.js("window.__veces") == antes + 1 and "GET /api/requisitos" in json.loads(edge.js("JSON.stringify(window.__llamadas)"))
    assert e["visible"] and e["res"] == "Todo en orden." and e["filas"] == [] and e["ok"] == "Las 7 comprobaciones están en orden."   # sigue visible con el resultado nuevo
    assert edge.js("document.activeElement.id") == "req-recomprobar" and edge.js("document.querySelector('#req-recomprobar').disabled") is False


def test_teclado_y_foco_visible_y_areas_de_pulsacion(edge, pagina):
    abrir(edge, pagina, requisitos(claude="falta"))
    r = json.loads(edge.js("""JSON.stringify([...document.querySelectorAll('#req-recomprobar, #req-cerrar')].map((b) => { const c = b.getBoundingClientRect(); return [b.id, Math.round(c.height), b.tabIndex]; }))"""))
    assert all(h >= 32 and t >= 0 for _i, h, t in r), r                                          # ≥ 32 px y alcanzables con Tab
    # Tab desde «Volver a comprobar» llega a «Ocultar» con el anillo de foco visible (se mide con eventos de teclado reales)
    edge.js("document.querySelector('#req-recomprobar').focus(); 1")
    edge.cmd("Input.dispatchKeyEvent", type="keyDown", key="Tab", code="Tab", windowsVirtualKeyCode=9)
    edge.cmd("Input.dispatchKeyEvent", type="keyUp", key="Tab", code="Tab", windowsVirtualKeyCode=9)
    medida = json.loads(edge.js("""JSON.stringify((() => { const a = document.activeElement, s = getComputedStyle(a); return { id: a.id, visible: a.matches(':focus-visible'), anillo: s.outlineStyle !== 'none' && parseFloat(s.outlineWidth) > 0 || s.boxShadow !== 'none' }; })())"""))
    assert medida["id"] == "req-cerrar" and medida["visible"] and medida["anillo"], medida
    # y el panel es una región con nombre para lectores de pantalla
    assert edge.js("document.querySelector('#i-requisitos').getAttribute('aria-labelledby')") == "req-tit"


@pytest.mark.parametrize("ancho,alto", [(1280, 720), (1024, 720), (900, 700)])
def test_el_panel_no_desborda_ni_recorta_texto(edge, pagina, ancho, alto):
    abrir(edge, pagina, requisitos(py="falta", claude="falta", modelo="falta", audio="aviso", proyectos="falta", knowledge="aviso", locales="falta"), ancho, alto)
    r = json.loads(edge.js("""JSON.stringify((() => {
      const p = document.querySelector('#i-requisitos');
      const mal = [...p.querySelectorAll('*')].filter((e) => e.getBoundingClientRect().height > 0 && e.scrollWidth > e.clientWidth + 1).map((e) => e.className || e.tagName);
      const fuera = [...p.querySelectorAll('*')].filter((e) => e.getBoundingClientRect().right > innerWidth + 1).length;
      return { mal, fuera, doc: [document.documentElement.scrollWidth, innerWidth], filas: p.querySelectorAll('.req-fila').length };
    })())"""))
    assert r["mal"] == [] and r["fuera"] == 0 and r["doc"][0] <= r["doc"][1] and r["filas"] == 7, r


@pytest.mark.parametrize("esquema", ["dark", "light"])
def test_contraste_de_los_estados_cumple_aa(edge, pagina, esquema):
    abrir(edge, pagina, requisitos(claude="falta", audio="aviso"), esquema=esquema)
    c = json.loads(edge.js("""JSON.stringify((() => {
      const fondo = (e) => { while (e) { const b = getComputedStyle(e).backgroundColor; const m = b.match(/[\\d.]+/g); if (m && (m.length === 3 || +m[3] > 0.9)) return m.slice(0, 3).map(Number); e = e.parentElement; } return [255, 255, 255]; };
      const rgb = (s) => s.match(/[\\d.]+/g).slice(0, 3).map(Number);
      return [...document.querySelectorAll('#i-requisitos .req-est, #i-requisitos .req-det, #i-requisitos .req-como, #i-requisitos .req-tit')].map((e) => ({ k: e.className, fg: rgb(getComputedStyle(e).color), bg: fondo(e) }));
    })())"""))

    def lum(rgb):
        f = [(v / 255 / 12.92) if v / 255 <= 0.03928 else (((v / 255) + 0.055) / 1.055) ** 2.4 for v in rgb]
        return 0.2126 * f[0] + 0.7152 * f[1] + 0.0722 * f[2]
    for x in c:
        a, b = sorted((lum(x["fg"]), lum(x["bg"])), reverse=True)
        assert (a + 0.05) / (b + 0.05) >= 4.5, (esquema, x)


# ============================================================ Ajustes
def abrir_ajustes(edge, pagina, **kw):
    abrir(edge, pagina, **kw)
    edge.js("document.querySelector('#b-ajustes').click(); 1")
    time.sleep(0.6)


def test_ajustes_muestra_los_valores_y_la_lista_de_requisitos(edge, pagina):
    abrir_ajustes(edge, pagina, req=requisitos(modelo="falta"))
    r = json.loads(edge.js("""JSON.stringify({ beam: document.querySelector('[name=whisper_beam]').value, vocab: document.querySelector('#aj-vocab').value, cuenta: document.querySelector('#aj-vocab-cuenta').textContent,
      knowledge: document.querySelector('#aj-knowledge').value, abierto: document.querySelector('#d-ajustes').open, filas: document.querySelectorAll('#aj-req-lista .req-fila').length,
      res: document.querySelector('#aj-req-res').textContent, boton: document.querySelector('#aj-knowledge-elegir').hidden })"""))
    assert r["beam"] == "5" and r["vocab"] == "Cupo de grupos\nMotor de cotización" and r["cuenta"] == "2 de 60 términos." and r["knowledge"] == "" and r["abierto"]
    assert r["filas"] == 7 and r["res"] == "Falta 1 cosa" and r["boton"] is True                    # el selector nativo solo con ventana nativa


def test_ajustes_sin_cambios_no_manda_las_claves_nuevas(edge, pagina):
    abrir_ajustes(edge, pagina)
    edge.js("document.querySelector('#s-guardar').click(); 1")
    time.sleep(0.5)
    puts = json.loads(edge.js("JSON.stringify(window.__puts)"))
    principal = [p for p in puts if "raiz_proyectos" in p]                                       # (otros módulos de Ajustes mandan su propio PUT con lo suyo)
    assert len(principal) == 1 and not ({"whisper_beam", "vocabulario_transcripcion", "knowledge"} & set(principal[0])), principal[0].keys()
    assert edge.js("document.querySelector('#d-ajustes').open") is False


def test_ajustes_manda_solo_lo_que_cambia_y_el_vocabulario_como_lista(edge, pagina):
    abrir_ajustes(edge, pagina)
    edge.js("""(() => { const f = document.querySelector('#f-ajustes'); const poner = (el, v) => { el.value = v; el.dispatchEvent(new Event('input', { bubbles: true })); };
      poner(f.whisper_beam, '3'); poner(document.querySelector('#aj-vocab'), '  Cupo de grupos \\n\\nSAP\\n   \\nOdoo ERP'); poner(f.knowledge, '  X:/Documentacion  '); return 1; })()""")
    assert edge.js("document.querySelector('#aj-vocab-cuenta').textContent") == "3 de 60 términos."
    edge.js("document.querySelector('#s-guardar').click(); 1")
    time.sleep(0.5)
    put = json.loads(edge.js("JSON.stringify(window.__puts[0])"))
    assert put["whisper_beam"] == 3 and put["vocabulario_transcripcion"] == ["Cupo de grupos", "SAP", "Odoo ERP"] and put["knowledge"] == "X:/Documentacion"
    assert edge.js("document.querySelector('#d-ajustes').open") is False


def test_un_beam_vacio_o_no_numerico_va_al_servidor_para_que_lo_rechace(edge, pagina):
    abrir_ajustes(edge, pagina)
    edge.js("""(() => { const f = document.querySelector('#f-ajustes'); f.whisper_beam.value = ''; return 1; })()""")
    edge.js("document.querySelector('#s-guardar').click(); 1")
    time.sleep(0.4)
    assert json.loads(edge.js("JSON.stringify(window.__puts[0])"))["whisper_beam"] is None


@pytest.mark.parametrize("campo,entrada,error,seccion,mensaje", [
    ("whisper_beam", "[name=whisper_beam]", "#aj-beam-error", "audio", "El ancho de búsqueda va de 1 a 10."),
    ("vocabulario_transcripcion", "#aj-vocab", "#aj-vocab-error", "audio", "Como máximo 60 términos (hay 61)."),
    ("knowledge", "#aj-knowledge", "#aj-knowledge-error", "privacidad", "La carpeta no existe o no es una carpeta."),
    ("raiz_proyectos", "[name=raiz_proyectos]", "#aj-raiz-error", "privacidad", "Cambia la carpeta de proyectos fuera de una reunión."),       # durante una reunión
    ("whisper_modelo", "[name=whisper_modelo]", "#aj-modelo-error", "audio", "Cambia el modelo de transcripción fuera de una reunión."),
])
def test_el_error_del_servidor_sale_junto_a_su_campo_y_lleva_el_foco(edge, pagina, campo, entrada, error, seccion, mensaje):
    abrir_ajustes(edge, pagina)
    # el usuario estaba en otra sección: el error le lleva a la del campo
    edge.js("window.AP.ajustes.ir('equipo'); window.__PUT_ERROR = %s; document.querySelector('[name=whisper_beam]').value = '3'; document.querySelector('#aj-knowledge').value = 'X:/mal'; document.querySelector('#s-guardar').click(); 1"
            % json.dumps({"detail": mensaje, "campo": campo}))
    time.sleep(0.5)
    r = json.loads(edge.js("""JSON.stringify((() => { const e = document.querySelector(%s), i = document.querySelector(%s), s = document.querySelector('#s-error');
      return { texto: e.textContent, visible: !e.hidden && e.getBoundingClientRect().height > 0, invalido: i.getAttribute('aria-invalid'), foco: document.activeElement === i,
        seccion: window.AP.ajustes.seccion(), abierto: document.querySelector('#d-ajustes').open, generico: s.hidden, descrito: i.getAttribute('aria-describedby').includes(e.id),
        cerca: Math.abs(e.getBoundingClientRect().top - i.getBoundingClientRect().bottom) < 140 }; })())""" % (json.dumps(error), json.dumps(entrada))))
    assert r["texto"] == mensaje and r["visible"] and r["invalido"] == "true" and r["foco"] and r["seccion"] == seccion and r["abierto"] and r["generico"] is True, r
    assert r["descrito"] and r["cerca"], r                                                       # el error está asociado al campo (lectores de pantalla) y pegado a él
    # al corregir, el error desaparece
    edge.js("(() => { const i = document.querySelector(%s); i.value = i.value + ' '; i.dispatchEvent(new Event('input', { bubbles: true })); return 1; })()" % json.dumps(entrada))
    assert edge.js("document.querySelector(%s).hidden" % json.dumps(error)) is True and edge.js("document.querySelector(%s).hasAttribute('aria-invalid')" % json.dumps(entrada)) is False


def test_un_error_sin_campo_sigue_saliendo_en_el_aviso_general(edge, pagina):
    abrir_ajustes(edge, pagina)
    edge.js("window.__PUT_ERROR = %s; document.querySelector('[name=whisper_beam]').value = '4'; document.querySelector('#s-guardar').click(); 1" % json.dumps({"detail": "La carpeta raíz de proyectos no existe."}))
    time.sleep(0.5)
    r = json.loads(edge.js("JSON.stringify({ general: document.querySelector('#s-error').textContent, visible: !document.querySelector('#s-error').hidden, ninguno: [...document.querySelectorAll('.aj-error')].every((e) => e.hidden) })"))
    assert r == {"general": "La carpeta raíz de proyectos no existe.", "visible": True, "ninguno": True}


def test_volver_a_comprobar_en_ajustes_y_teclado_de_los_campos(edge, pagina):
    abrir_ajustes(edge, pagina, req=requisitos(claude="falta"))
    antes = edge.js("window.__veces")
    edge.js("window.__REQ = %s; document.querySelector('#aj-req-recomprobar').click(); 1" % json.dumps(requisitos()))
    time.sleep(0.4)
    assert edge.js("window.__veces") == antes + 1 and edge.js("document.querySelector('#aj-req-res').textContent") == "Todo en orden."
    medir = """JSON.stringify([...document.querySelectorAll('#aj-c-beam input, #aj-vocab, #aj-knowledge, #aj-req-recomprobar')].map((e) => [e.id || e.name, e.tabIndex >= 0, Math.round(e.getBoundingClientRect().height)]))"""
    r = json.loads(edge.js(medir))
    edge.js("window.AP.ajustes.ir('privacidad'); 1")
    r += json.loads(edge.js(medir))                                                              # (cada medida solo vale con su sección a la vista)
    assert all(t and h >= 32 for _n, t, h in r if h), r
    assert {n for n, _t, h in r if h} == {"whisper_beam", "aj-vocab", "aj-req-recomprobar", "aj-knowledge"}, r


@pytest.mark.parametrize("esquema", ["dark", "light"])
def test_ajustes_nuevos_no_desbordan_en_los_dos_temas(edge, pagina, esquema):
    abrir_ajustes(edge, pagina, req=requisitos(claude="falta", audio="aviso"), esquema=esquema)
    for sec in ("audio", "privacidad"):
        edge.js("window.AP.ajustes.ir(%s); 1" % json.dumps(sec))
        r = json.loads(edge.js("""JSON.stringify((() => { const d = document.querySelector('#d-ajustes').getBoundingClientRect(); const c = document.querySelector('.d-cuerpo');
          const mal = [...document.querySelectorAll('.aj-sec:not([hidden]) *')].filter((e) => e.getBoundingClientRect().height > 0 && e.scrollWidth > e.clientWidth + 1 && getComputedStyle(e).overflow === 'visible' && !e.closest('.seg-mod')).map((e) => e.id || e.className);
          return { mal, dentro: d.right <= innerWidth && d.bottom <= innerHeight, scrollH: c.scrollWidth <= c.clientWidth + 1 }; })())"""))
        assert r["mal"] == [] and r["dentro"] and r["scrollH"], (sec, r)


# ============================================================ el panel del inicio ocupa lo justo: solo lo que no está bien + una línea con el resto
@pytest.mark.parametrize("kw,claves,linea", [
    ({"claude": "falta"}, ["claude"], "Las otras 6 comprobaciones están en orden."),
    ({"claude": "falta", "audio": "aviso"}, ["claude", "audio"], "Las otras 5 comprobaciones están en orden."),
    ({"py": "falta", "claude": "falta", "modelo": "falta", "audio": "aviso", "proyectos": "falta", "knowledge": "aviso"}, ["python", "claude", "modelo_whisper", "audio", "carpeta_proyectos", "carpeta_knowledge"],
     "La otra comprobación está en orden."),
    ({"py": "falta", "claude": "falta", "modelo": "falta", "audio": "aviso", "proyectos": "falta", "knowledge": "aviso", "locales": "falta"},
     ["python", "claude", "modelo_whisper", "audio", "carpeta_proyectos", "carpeta_knowledge", "carpetas_locales"], ""),
])
def test_en_el_inicio_solo_salen_las_filas_que_no_estan_bien_y_una_linea_con_el_resto(edge, pagina, kw, claves, linea):
    abrir(edge, pagina, requisitos(**kw))
    e = estado_panel(edge)
    assert e["visible"] and [f["clave"] for f in e["filas"]] == claves and all(f["estado"] != "bien" for f in e["filas"])
    assert e["ok"] == linea                                                                      # singular correcto con una; nada si no hay ninguna
    assert edge.js("document.querySelectorAll('#req-lista .req-fila').length") == len(claves)


def test_el_panel_del_inicio_ya_no_empuja_continuar_fuera_de_la_vista(edge, pagina):
    abrir(edge, pagina, requisitos(claude="falta"), 1440, 900)
    e = estado_panel(edge)
    assert e["visible"] and e["rect"][3] - e["rect"][1] < 220, e["rect"]                         # con una sola cosa en falta, una fila y la línea (antes, siete filas: ~500 px)
    assert e["filas"][0]["clave"] == "claude" and e["ok"].startswith("Las otras 6")


def test_ajustes_sigue_con_la_lista_completa_aunque_el_inicio_solo_enseñe_lo_que_falla(edge, pagina):
    abrir_ajustes(edge, pagina, req=requisitos(claude="falta", audio="aviso"))
    r = json.loads(edge.js("""JSON.stringify({ filas: [...document.querySelectorAll('#aj-req-lista .req-fila')].map((f) => f.dataset.estado), inicio: document.querySelectorAll('#req-lista .req-fila').length,
      ok: !!document.querySelector('#aj-req-ok') })"""))
    assert r["filas"] == ["bien", "falta", "bien", "aviso", "bien", "bien", "bien"] and r["inicio"] == 2 and r["ok"] is False


def test_la_ayuda_de_knowledge_lista_los_formatos_que_de_verdad_se_leen():
    """La lista sale de EXT_KNOWLEDGE (lo que indexa la app); el PDF solo se lee si hay lector instalado y la ayuda y el manual lo dicen."""
    from apuntes.fuentes import EXT_KNOWLEDGE
    ayuda = re.search(r'id="aj-knowledge-ayuda">(.*?)</span>', HTML, re.S).group(1)
    manual = (WEB.parent / "MANUAL.md").read_text(encoding="utf-8")
    for ext in EXT_KNOWLEDGE:
        assert ext.lstrip(".") in ayuda, ext
        assert f"`{ext}`" in manual.split("carpeta de Knowledge**")[1].split(chr(10))[0], ext
    assert "lector de PDF" in ayuda and "lector de PDF" in manual
