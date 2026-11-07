"""Interfaz del asesor en directo (web/asesor.js, web/asesor.css): carril «Ahora» arriba con la respuesta sugerida más reciente y los consejos, «Profundizar» con la
casilla de la web (desmarcada y solo si `claude -p` la permite), fijar y descartar. Estáticos (siempre) y dinámicos en un Edge/Chrome sin cabeza sobre la interfaz REAL
con dobles de `fetch` y `WebSocket` (ver `_visual_harness.py`); sin servidor ni modelo."""
from __future__ import annotations

import json
import re
import socket
import time

import pytest

from _visual_harness import WEB, Edge, foto, pagina_html

JS = (WEB / "asesor.js").read_text(encoding="utf-8")
CSS = re.sub(r"/\*.*?\*/", "", (WEB / "asesor.css").read_text(encoding="utf-8"), flags=re.S)
HTML = (WEB / "index.html").read_text(encoding="utf-8")


# ============================================================ estáticos
def test_el_carril_esta_en_la_pagina_y_carga_despues_del_equipo():
    assert 'id="as-carril"' in HTML and "/static/asesor.css" in HTML and HTML.index("/static/equipo.js") < HTML.index("/static/asesor.js")
    assert HTML.index('class="reunion-grid"') < HTML.index('id="as-carril"') < HTML.index('id="r-tabs"') < HTML.index('id="as-consejos"')   # columna derecha: «Ahora» fijo arriba y, debajo, las pestañas (Consejos primero)
    assert 'aria-label="Asesor' in HTML


def test_reglas_del_codigo_del_asesor():
    codigo = re.sub(r"^\s*//.*$|\s//\s.*$", "", re.sub(r"/\*.*?\*/", "", JS, flags=re.S), flags=re.M)
    assert "innerHTML" not in codigo and "eval(" not in codigo and "insertAdjacentHTML" not in codigo       # todo texto por nodos de texto
    assert codigo.count("setInterval") == 1 and "clearInterval" in codigo                                   # solo el cronómetro de una llamada real
    assert "disponible === true" in codigo                                                                   # la casilla de la web solo si `claude -p` la permite
    assert re.search(r'checked: A\.web\.get\(e\.id\) \? true : null', codigo) and "checked: true" not in codigo   # y nunca marcada de salida
    assert "<a " not in codigo and "href" not in codigo                                                      # las URLs se muestran como texto: la aplicación no abre enlaces
    assert "/api/asesor/" in codigo and "profundizar" in codigo and "fijar" in codigo and "descartar" in codigo


def test_reglas_del_css_del_asesor():
    assert "text-overflow" not in CSS and "line-clamp" not in CSS and "backdrop-filter" not in CSS and "gradient" not in CSS and "will-change" not in CSS
    assert not re.findall(r"font-size: (?!var\(--f-)", CSS)                                                  # la escala tipográfica va por variable
    assert set(re.findall(r"border-radius: (\d+)px", CSS)) <= {"2", "4", "10"}
    assert 'body[data-modo="reunion"] .as-carril' in CSS and ".as-cons {" in CSS and ".as-nobase" in CSS     # Modo reunión: arriba del panel derecho; consejos compactos; una no-respuesta, en una línea
    assert "var(--f-22)" in CSS                                                                              # «Ahora»: lo más grande de la pantalla


# ============================================================ dinámicos
def _puerto():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def pagina(tmp_path_factory):
    return pagina_html(tmp_path_factory.mktemp("asesor-ui") / "app.html")


@pytest.fixture(scope="module")
def edge(tmp_path_factory):
    e = Edge(tmp_path_factory.mktemp("edge-asesor"), _puerto())
    yield e
    e.cerrar()


def R(i, pregunta, minuto, t, vinetas, **extra):
    return {"id": f"r{i}", "pregunta": pregunta, "minuto": minuto, "t_seg": t, "canal": "Reunión", "estado": "ok", "vinetas": vinetas, "confianza": "alta",
            "citas": [{"fuente": "02-alcance.md", "tipo": "proyecto"}, {"minuto": "00:50", "t_seg": 50, "tipo": "reunion"}], "base": True, "sin_base": False, "orientacion": False,
            "sin_cita": False, "modelo": "haiku", "temas": [], "escalada": "", "fijada": False, "descartada": False, "profundizada": None, "error": "", "tokens": 3500, **extra}


def C(i, tipo, etiqueta, accion, porque, minuto="01:30", **extra):
    return {"id": f"c{i}", "tipo": tipo, "etiqueta": etiqueta, "accion": accion, "porque": porque, "minuto": minuto, "t_seg": 90.0, "modelo": "haiku", "fijado": False,
            "descartado": False, "profundizada": None, **extra}


ESTADO = {"activo": True, "presupuesto": {"usado": 12000, "limite": 100000, "fraccion": .12, "nivel": "normal"}, "sonnet": {"usados": 1, "limite": 8},
          "web": {"disponible": False, "motivo": ""}, "pendiente": False, "en_curso": False, "tokens": 12000, "stats": {}, "fuentes": {}}


def arrancar(e, pagina, ancho=None):
    e.abrir(pagina.as_uri())
    e.js("localStorage.clear(); sessionStorage.clear(); 1")
    e.abrir(pagina.as_uri())
    e.js("window.__llamadas = []; const f0 = window.fetch; window.fetch = async (u, o) => { window.__llamadas.push([String(u), o && o.method, o && o.body]); return f0(u, o); }; 1")
    e.js("window.__emitir(Object.assign({tipo: 'snapshot'}, %s)); 1" % json.dumps(foto()))
    time.sleep(0.6)


def emitir(e, respuestas, consejos, **estado):
    e.js("window.__emitir(%s); 1" % json.dumps({"tipo": "asesor", "respuestas": respuestas, "consejos": consejos, **{**ESTADO, **estado}}))
    time.sleep(0.4)


def test_sin_datos_el_carril_no_ocupa_sitio(edge, pagina):
    arrancar(edge, pagina)
    assert edge.js("document.querySelector('#as-carril').hidden && document.querySelector('#as-carril').getBoundingClientRect().height === 0")


def test_ahora_muestra_la_respuesta_mas_reciente_grande_y_los_consejos_debajo(edge, pagina):
    arrancar(edge, pagina)
    emitir(edge, [R(1, "¿Cuántos usuarios puede tener cada hotel?", "00:40", 40, ["Hasta tres usuarios por hotel."]),
                  R(2, "¿Qué servicio de correo envía el aviso al crear una reserva?", "01:10", 70, ["Aún no está decidido: lo vemos con vuestro equipo de sistemas.", "Os lo confirmo esta semana."],
                    confianza="media", modelo="sonnet", escalada="hecha", temas=["plazos"], profundizada={"estado": "ok", "web": False, "vinetas": ["Primero, confirma el servicio."], "citas": [], "web_urls": [],
                                                                                                           "confianza": "media", "modelo": "sonnet", "error": ""})],
           [C(1, "pregunta", "Siguiente pregunta", "Pregunta quién valida el catálogo de hoteles antes del piloto", "Sin ese fichero el piloto no es firme"),
            C(2, "riesgo", "Objeción o riesgo", "Avisa del riesgo de retraso por el catálogo de hoteles", "Depende de un tercero"),
            C(3, "cierre", "Cierre y próximo paso", "Propón fijar hoy la fecha de entrega", "Hay prisa por cerrar la oferta")])
    d = json.loads(edge.js("""JSON.stringify((() => {
      const l = document.querySelector('#as-carril'), a = l.querySelector('.as-ahora'), g = [...a.querySelectorAll('.as-vin.grande li')];
      const tam = (e) => parseFloat(getComputedStyle(e).fontSize);
      const todo = [...document.querySelectorAll('.t-body-m, .t-body, .t-meta, .tarj, .eq-tarj .eq-l2, .eq-fila')].map(tam);
      return { hidden: l.hidden, ahora: a.dataset.id, pregunta: a.querySelector('.as-preg').textContent, bullets: g.map(x => x.textContent), tamBullet: g.map(tam),
        maxOtros: Math.max(...todo), conf: a.querySelector('.as-conf').textContent, modelo: a.querySelector('.as-modelo').textContent, nota: (a.querySelector('.as-nota') || {}).textContent,
        fuentes: [...a.querySelectorAll('.as-fuentes .as-fuente, .as-fuentes .min')].map(x => x.textContent), prof: (a.querySelector('.as-prof') || {}).textContent,
        cons: [...document.querySelectorAll('#as-consejos .as-cons')].map(c => [c.querySelector('.as-etq-c').textContent, c.querySelector('.as-accion').textContent, parseFloat(getComputedStyle(c.querySelector('.as-accion')).fontSize), parseFloat(getComputedStyle(c.querySelector('.as-porque')).fontSize)]),
        anteriores: (l.querySelector('.as-ant summary') || {}).textContent, caja: l.querySelectorAll("[data-accion='web']").length,
        alto: Math.round(l.getBoundingClientRect().height), top: Math.round(l.getBoundingClientRect().top),
        columnas: [...document.querySelectorAll('.col-izq')].map(c => Math.round(c.getBoundingClientRect().height)) };
    })())"""))
    assert not d["hidden"] and d["ahora"] == "r2" and d["pregunta"] == "¿Qué servicio de correo envía el aviso al crear una reserva?"
    assert d["bullets"] == ["Aún no está decidido: lo vemos con vuestro equipo de sistemas.", "Os lo confirmo esta semana."]
    assert d["tamBullet"][0] == 22 and all(t == 14 for t in d["tamBullet"][1:]) and d["maxOtros"] <= 15   # la respuesta es el titular (22); lo que la acompaña, cuerpo (14)
    assert d["conf"] == "Confianza media" and d["modelo"] == "Sonnet" and "afinada con Sonnet" in d["nota"] and d["prof"].upper().startswith("PROFUNDIZADO")
    assert "02-alcance.md" in d["fuentes"] and "minuto 00:50" in d["fuentes"]
    assert [c[:2] for c in d["cons"]] == [["Cierre y próximo paso", "Propón fijar hoy la fecha de entrega"], ["Objeción o riesgo", "Avisa del riesgo de retraso por el catálogo de hoteles"],
                                          ["Siguiente pregunta", "Pregunta quién valida el catálogo de hoteles antes del piloto"]]   # los tres, el más reciente primero: en su pestaña no hay tope
    assert all(c[2] == 15 and c[3] == 14 for c in d["cons"])                                   # titular a 15, «por qué» a 14
    assert d["anteriores"] == "Respuestas anteriores (1)"
    assert d["caja"] == 0                                                                       # la web no está disponible: la casilla no aparece
    assert d["alto"] <= 900 * 0.46 + 4 and d["top"] > 0 and min(d["columnas"]) > 150            # el carril no se come la columna


def test_la_casilla_de_la_web_solo_con_web_disponible_y_nunca_marcada(edge, pagina):
    arrancar(edge, pagina)
    r = R(1, "¿Qué servicio de correo envía el aviso?", "01:10", 70, ["No hay base en tus fuentes: propón comprobarlo y volver con la respuesta"], sin_base=True, base=False, confianza="baja", citas=[])
    emitir(edge, [r], [], web={"disponible": True, "motivo": ""})
    assert edge.js("document.querySelectorAll(\"#as-carril [data-accion='web']\").length") == 1
    assert edge.js("document.querySelector(\"#as-carril [data-accion='web']\").checked") is False
    assert edge.js("document.querySelector('.as-ahora').classList.contains('sin-base') && document.querySelector('.as-vin.sin-base') !== null")
    # con la casilla marcada, «Profundizar» pide la web; sin marcarla, no
    edge.js("document.querySelector(\"#as-carril [data-accion='web']\").click(); document.querySelector(\"#as-carril [data-accion='profundizar']\").click(); 1")
    time.sleep(0.3)
    ll = edge.js("JSON.stringify(window.__llamadas.filter(x => /asesor/.test(x[0])))")
    assert json.loads(ll) == [["/api/asesor/r1/profundizar", "POST", '{"web":true}']]
    emitir(edge, [r], [], web={"disponible": False, "motivo": "Esta versión de `claude -p` no permite habilitar solo la búsqueda web."})
    assert edge.js("document.querySelectorAll(\"#as-carril [data-accion='web']\").length") == 0


def test_profundizar_sin_marcar_la_web_no_la_pide_y_fijar_y_descartar_llaman_a_la_api(edge, pagina):
    arrancar(edge, pagina)
    emitir(edge, [R(1, "¿Cuántos usuarios?", "00:40", 40, ["Tres."])], [C(1, "valor", "Aportación de valor", "Ofrece una demo del informe semanal", "Lo pidió el cliente")], web={"disponible": True, "motivo": ""})
    edge.js("document.querySelector(\"#as-carril .as-ahora [data-accion='profundizar']\").click(); document.querySelector(\"#as-carril .as-ahora [data-accion='fijar']\").click(); "
            "document.querySelector(\"#as-consejos .as-cons [data-accion='descartar']\").click(); document.querySelector(\"#as-consejos .as-cons [data-accion='profundizar']\").click(); 1")
    time.sleep(0.3)
    ll = json.loads(edge.js("JSON.stringify(window.__llamadas.filter(x => /asesor/.test(x[0])))"))
    assert ll == [["/api/asesor/r1/profundizar", "POST", '{"web":false}'], ["/api/asesor/r1/fijar", "POST", '{"valor":true}'],
                  ["/api/asesor/c1/descartar", "POST", '{"valor":true}'], ["/api/asesor/c1/profundizar", "POST", '{"web":false}']]


def test_un_descartado_sale_y_un_fijado_se_queda_aparte_y_nada_se_corta(edge, pagina):
    arrancar(edge, pagina)
    largo = "palabra " * 60
    emitir(edge, [R(1, "¿Primera pregunta importante?", "00:40", 40, ["Primera respuesta."], fijada=True), R(2, "¿Descartada?", "00:50", 50, ["x"], descartada=True),
                  R(3, "¿Tercera pregunta con un texto larguísimo? " + largo, "01:10", 70, ["Respuesta " + largo, "Otra " + largo])],
           [C(1, "oportunidad", "Oportunidad", "Ofrece la segunda fase " + largo, "Porque sí " + largo, fijado=True)])
    d = json.loads(edge.js("""JSON.stringify((() => {
      const l = document.querySelector('#as-carril');
      const mal = [...l.querySelectorAll('*')].filter(e => getComputedStyle(e).textOverflow === 'ellipsis' || (e.scrollWidth > e.clientWidth + 1 && getComputedStyle(e).overflowX !== 'visible')).length;
      return { ahora: l.querySelector('.as-ahora').dataset.id, fijadas: [...l.querySelectorAll('.as-comp.fijada')].map(x => x.dataset.id), ids: [...l.querySelectorAll('[data-id]')].map(x => x.dataset.id),
        mal, desborde: document.documentElement.scrollWidth > innerWidth };
    })())"""))
    assert d["ahora"] == "r3" and d["fijadas"] == ["r1"] and "r2" not in d["ids"] and d["mal"] == 0 and not d["desborde"]


def test_plegar_recuerda_la_eleccion_y_en_modo_reunion_va_arriba_del_panel_derecho_apilado(edge, pagina):
    arrancar(edge, pagina)
    emitir(edge, [R(1, "¿Cuántos usuarios?", "00:40", 40, ["Tres."])], [C(1, "valor", "Aportación de valor", "Ofrece una demo", "Lo pidió el cliente")])
    edge.js("document.querySelector('#as-carril .as-plegar').click(); 1")
    time.sleep(0.4)
    assert edge.js("document.querySelector('#as-carril .as-cuerpo') === null") and edge.js("localStorage.getItem('apuntes_asesor_plegado')") == "1"
    edge.js("document.querySelector('#as-carril .as-plegar').click(); 1")
    time.sleep(0.4)
    edge.js("document.body.dataset.modo = 'reunion'; document.body.dataset.mr = 'dos'; 1")
    time.sleep(0.6)
    d = json.loads(edge.js("""JSON.stringify((() => { const l = document.querySelector('#as-carril'), p = l.parentNode;
      return { padre: p.id, primero: p.firstElementChild === l, ancho: Math.round(l.getBoundingClientRect().width), apilado: getComputedStyle(l.querySelector('.as-cuerpo')).display,
        mayor: parseFloat(getComputedStyle(l.querySelector('.as-vin.grande li')).fontSize) }; })())"""))
    assert d["padre"] == "col-der" and d["primero"] and d["ancho"] <= 1440 * 0.25 + 4 and d["apilado"] == "block" and d["mayor"] == 22
    edge.js("delete document.body.dataset.modo; delete document.body.dataset.mr; 1")
    time.sleep(0.4)
    assert edge.js("document.querySelector('#as-carril').parentNode.id") == "col-der"                     # el carril ya no viaja: es la misma columna derecha en la vista completa y en Modo reunión


def test_en_curso_muestra_el_estado_real_y_el_aviso_de_presupuesto(edge, pagina):
    arrancar(edge, pagina)
    en_curso = R(1, "¿Cuánto cuesta ampliar el alcance?", "01:10", 70, [], estado="en_curso", confianza="", escalada="pendiente", temas=["precio", "alcance"], modelo="haiku")
    emitir(edge, [en_curso], [], presupuesto={"usado": 85000, "limite": 100000, "fraccion": .85, "nivel": "ahorro"})
    t = edge.js("document.querySelector('#as-carril').innerText")
    assert "Preparando la respuesta" in t and "Ahorro: sin Sonnet automático" in t and "85,0k / 100,0k tokens" in t.replace(" ", " ").replace("\xa0", " ")
    emitir(edge, [{**en_curso, "estado": "ok", "vinetas": ["No puedo confirmar ese importe ahora."], "confianza": "media", "escalada": "en_curso"}], [])
    assert "afinando con Sonnet" in edge.js("document.querySelector('#as-carril').innerText")
    emitir(edge, [{**en_curso, "estado": "error", "error": "El modelo no responde."}], [])
    assert "El modelo no responde." in edge.js("document.querySelector('#as-carril').innerText")
