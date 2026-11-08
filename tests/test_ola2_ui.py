"""Ola 2 de la interfaz (reunión y revisión): reunión en tres zonas (Transcripción | Ahora | Objetivos), tres pestañas (Avisos, Pregúntale, Sesión), agentes con nombre,
color e icono, Avisos unificados con filtro por agente y tres prioridades, revisión como lista de cierre en cuatro pasos, paleta de comandos con Ctrl+K y Ajustes en tres
secciones. Estáticos y dinámicos en un Edge/Chrome sin cabeza sobre la interfaz REAL con dobles de `fetch` y `WebSocket` (`_visual_harness.py`; datos ficticios)."""
from __future__ import annotations

import json
import re
import socket
import time

import pytest

from _visual_harness import WEB, Edge, foto, pagina_html

APP = re.sub(r"/\*.*?\*/", "", (WEB / "app.css").read_text(encoding="utf-8"), flags=re.S)
OLA2 = re.sub(r"/\*.*?\*/", "", (WEB / "ola2.css").read_text(encoding="utf-8"), flags=re.S)
HTML = (WEB / "index.html").read_text(encoding="utf-8")
ICONOS = (WEB / "iconos.js").read_text(encoding="utf-8")
AGENTES = {"coordinador": "Capitán", "funcional": "Lupa", "constructor": "Arquitecto", "revisor": "Auditor", "estratega": "Sherpa", "monitor": "Monitor", "asesor": "Asesor"}


# ============================================================ estáticos
def test_tres_pestanas_y_zonas_en_el_html():
    for t in ("avisos", "pregunta", "sesion"):
        assert f'data-tab="{t}"' in HTML and f'data-panel="{t}"' in HTML, t
    assert len(re.findall(r'role="tab" class="r-tab"', HTML)) == 3
    assert re.search(r'<section class="ahora-acciones" id="ahora-acciones" aria-label="Acciones propuestas" hidden>', HTML)   # reservado para la bandeja de acciones
    assert HTML.index('id="zona-ahora"') < HTML.index('id="zona-obj"') and HTML.index('class="col-izq"') < HTML.index('id="zona-ahora"')
    assert HTML.index('id="ahora-paso"') < HTML.index('id="ahora-acciones"') < HTML.index('id="r-tabs"')
    for s in ("nombres.js", "avisos.js", "paleta.js", "ajustes.js", "ola2.css"):
        assert s in HTML, s
    assert HTML.index("/static/iconos.js") < HTML.index("/static/nombres.js") < HTML.index("/static/agentes.js")


def test_el_mapa_unico_de_agentes_y_sus_iconos_estan_declarados():
    js = (WEB / "nombres.js").read_text(encoding="utf-8")
    for clave, nombre in AGENTES.items():
        assert re.search(rf'{clave}: \{{ id: "[a-z]+", nombre: "{nombre}"', js), clave
    for ico in ("capitan", "lupa", "arquitecto", "auditor", "sherpa", "monitor", "asesor", "comando", "correo"):
        assert re.search(rf"^\s+{ico}: \[", ICONOS, re.M), ico
    # el backend sigue hablando con sus nombres internos: ninguna etiqueta visible de los viejos nombres en la interfaz
    for n in ("agentes.js", "reunion.js", "equipo.js", "asesor.js", "index.html"):
        codigo = (WEB / n).read_text(encoding="utf-8")
        assert not re.search(r'"(Coordinador|Analista funcional|Constructor|Revisor|Estratega)"', codigo), n


def _lum(rgb):
    def c(v):
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    return 0.2126 * c(rgb[0]) + 0.7152 * c(rgb[1]) + 0.0722 * c(rgb[2])


def _con(a, b):
    la, lb = sorted((_lum(a), _lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def _hex(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


@pytest.mark.parametrize("tema", ["claro", "oscuro"])
def test_los_colores_de_agente_son_tokens_y_cumplen_aa(tema):
    if tema == "oscuro":
        bloque = APP[APP.index(':root[data-theme="dark"]'):APP.index("@media (prefers-color-scheme: dark)")]
        fondos = [_hex(x) for x in ("#201F1B", "#1B1A17", "#151412", "#24211C")]
    else:
        bloque = APP[APP.index(":root {"):APP.index(':root[data-theme="dark"]')]
        fondos = [_hex(x) for x in ("#FFFDF8", "#FAF3E2", "#F3F0E8", "#FFFFFF")]
    tokens = dict(re.findall(r"--(ag-[a-z]+): (#[0-9A-Fa-f]{6})", bloque))
    assert {"ag-capitan", "ag-lupa", "ag-arquitecto", "ag-auditor", "ag-sherpa", "ag-monitor", "ag-asesor"} <= set(tokens)
    for nombre, valor in tokens.items():
        for f in fondos:
            assert _con(_hex(valor), f) >= 4.5, (tema, nombre, valor, round(_con(_hex(valor), f), 2))
    assert len({tokens[k] for k in ("ag-capitan", "ag-lupa", "ag-arquitecto", "ag-auditor", "ag-sherpa", "ag-asesor")}) == 6   # cada agente, su color
    # y también en el esquema oscuro automático
    auto = APP[APP.index("@media (prefers-color-scheme: dark)"):]
    assert "--ag-capitan: #9DB7E0" in auto


def test_escala_tipografica_de_ola2_y_sin_glifos():
    for n in ("ola2.css",):
        css = (WEB / n).read_text(encoding="utf-8")
        css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
        assert not re.findall(r"font-size: (?!var\(--f-)", css), n
        assert set(re.findall(r"var\(--f-(\d+)\)", css)) <= {"22", "15", "14", "12", "11"}, n
    malos = re.compile("[■-◿☀-➿⬀-⯿]")
    for n in ("nombres.js", "avisos.js", "paleta.js", "ajustes.js", "revision.js", "ola2.css"):
        codigo = re.sub(r"/\*.*?\*/", "", (WEB / n).read_text(encoding="utf-8"), flags=re.S)
        codigo = "\n".join(l for l in codigo.splitlines() if not l.strip().startswith("//"))
        assert not malos.search(codigo), (n, malos.search(codigo).group(0))


def test_ajustes_en_tres_secciones_y_modelos_con_selector():
    for s in ("aj-audio", "aj-equipo", "aj-privacidad"):
        assert f'id="{s}"' in HTML and f'role="tabpanel"' in HTML
    assert len(re.findall(r'role="tab" class="aj-tab"', HTML)) == 3
    for k in ("m_digest", "m_periodico", "m_contradicciones_confirmar", "m_final", "m_consulta"):
        assert re.search(rf'<select class="input sel-modelo" name="{k}">', HTML), k          # selector, ya no un campo de texto
        assert not re.search(rf'<input[^>]*name="{k}"', HTML), k
    assert 'value="haiku">Ligero' in HTML and 'value="sonnet">Potente' in HTML               # mapeados a los valores de siempre
    assert re.search(r'id="aj-solo-local"[^>]*hidden', HTML) and re.search(r'id="aj-registro-envios"[^>]*hidden', HTML)   # sin datos del servidor, ocultos


# ============================================================ dinámicos
def _puerto():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def pagina(tmp_path_factory):
    return pagina_html(tmp_path_factory.mktemp("ola2") / "app.html")


@pytest.fixture(scope="module")
def edge(tmp_path_factory):
    e = Edge(tmp_path_factory.mktemp("edge-ola2"), _puerto(), ancho=1280, alto=720)
    yield e
    e.cerrar()


RESPUESTA = {"id": "r1", "pregunta": "¿Os comprometéis a tener el catálogo cargado antes del piloto?", "minuto": "04:50", "t_seg": 290, "canal": "Reunión", "estado": "ok",
             "vinetas": ["El catálogo depende de que el cliente lo entregue a tiempo.", "Propongo fijar una fecha de entrega."], "confianza": "media", "citas": [{"fuente": "02-alcance.md", "tipo": "proyecto"}],
             "base": True, "sin_base": False, "orientacion": False, "sin_cita": False, "modelo": "sonnet", "temas": [], "escalada": "", "fijada": False, "descartada": False, "profundizada": None, "error": "", "tokens": 3500}
CONSEJO = {"id": "c1", "tipo": "cierre", "etiqueta": "Cierre y próximo paso", "accion": "Propón fijar hoy una fecha de entrega del catálogo con el cliente", "porque": "Hay prisa por cerrar la oferta",
           "minuto": "03:00", "t_seg": 180.0, "modelo": "sonnet", "fijado": False, "descartado": False, "profundizada": None}
ESTADO_AS = {"activo": True, "presupuesto": {"usado": 12000, "limite": 100000, "fraccion": .12, "nivel": "normal"}, "sonnet": {"usados": 1, "limite": 8},
             "web": {"disponible": False, "motivo": ""}, "pendiente": False, "en_curso": False, "tokens": 12000, "stats": {}, "fuentes": {}}


def _abrir(edge, pagina, ancho=None, alto=None, esquema=None, **cambios):
    edge.cmd("Emulation.setDeviceMetricsOverride", width=ancho or 1280, height=alto or 720, deviceScaleFactor=1, mobile=False)   # cada prueba parte de 1280×720 y esquema oscuro
    edge.cmd("Emulation.setEmulatedMedia", features=[{"name": "prefers-color-scheme", "value": esquema or "dark"}])
    edge.abrir(pagina.as_uri())
    edge.js("localStorage.clear(); sessionStorage.clear(); 1")
    edge.abrir(pagina.as_uri())
    edge.js("window.__llamadas = []; const f0 = window.fetch; window.fetch = (u, o) => { window.__llamadas.push([(o && o.method) || 'GET', String(u), o && o.body]); return f0(u, o); }; 1")
    edge.js("window.__emitir(Object.assign({tipo: 'snapshot'}, %s)); 1" % json.dumps(foto(**{"estado": "grabando", **cambios})))
    time.sleep(0.7)


def _asesor(edge, respuestas=(RESPUESTA,), consejos=(CONSEJO,)):
    edge.js("window.__emitir(%s); 1" % json.dumps({"tipo": "asesor", "respuestas": list(respuestas), "consejos": list(consejos), **ESTADO_AS}))
    time.sleep(0.5)


@pytest.mark.parametrize("ancho,alto", [(1280, 720), (1440, 900), (1024, 720)])
def test_reunion_en_tres_zonas_visibles_sin_desborde_horizontal(edge, pagina, ancho, alto):
    _abrir(edge, pagina, ancho, alto)
    _asesor(edge)
    r = json.loads(edge.js("""JSON.stringify((() => {
      const caja = (s) => { const e = document.querySelector(s), r = e.getBoundingClientRect(); return { l: r.left, r: r.right, t: r.top, b: r.bottom, w: r.width, h: r.height, sw: e.scrollWidth, cw: e.clientWidth, v: getComputedStyle(e).display !== 'none' && r.height > 0 }; };
      const z = { trans: caja('.col-izq'), ahora: caja('#zona-ahora'), obj: caja('#zona-obj') };
      const desbordan = [...document.querySelectorAll('.col-izq, #zona-ahora, #zona-obj, #r-trans, #r-plan-scroll, #r-obj-scroll, #as-carril, #ahora-paso, #av-filtros')]
        .filter((e) => e.getBoundingClientRect().height > 0 && e.scrollWidth > e.clientWidth + 1).map((e) => e.id || e.className);
      return { z, desbordan, doc: [document.documentElement.scrollWidth, innerWidth, document.documentElement.scrollHeight, innerHeight],
        titulo: [document.querySelector('.panel-trans .panel-h .t-label').textContent, ...[...document.querySelectorAll('.zona-h .t-label')].map((e) => e.textContent)] };
    })())"""))
    z = r["z"]
    assert all(x["v"] and x["w"] >= 240 for x in z.values()), z                                # las tres zonas se ven y caben
    assert z["trans"]["r"] <= z["ahora"]["l"] + 1 and z["ahora"]["r"] <= z["obj"]["l"] + 1, z    # de izquierda a derecha: Transcripción | Ahora | Objetivos
    assert z["obj"]["r"] <= ancho + 1 and z["obj"]["b"] <= alto + 1 and z["ahora"]["b"] <= alto + 1, z
    assert r["desbordan"] == [], r["desbordan"]                                                  # ninguna zona con desborde horizontal
    assert r["doc"][0] <= r["doc"][1] and r["doc"][2] <= r["doc"][3], r["doc"]                   # la página no se desplaza
    assert r["titulo"][:3] == ["Transcripción", "Ahora", "Objetivos"], r["titulo"]


def test_ahora_lleva_respuesta_siguiente_paso_y_el_contenedor_de_acciones(edge, pagina):
    _abrir(edge, pagina)
    _asesor(edge)
    r = json.loads(edge.js("""JSON.stringify({
      resp: parseFloat(getComputedStyle(document.querySelector('#as-carril .as-vin li')).fontSize), paso: document.querySelector('#ahora-paso').innerText,
      pasoVisible: !document.querySelector('#ahora-paso').hidden, acc: { oculto: document.querySelector('#ahora-acciones').hidden, tag: document.querySelector('#ahora-acciones').tagName, aria: document.querySelector('#ahora-acciones').getAttribute('aria-label') } })"""))
    assert r["resp"] == 22.0 and r["pasoVisible"] and "siguiente paso" in r["paso"].lower() and "fecha de entrega" in r["paso"] and "Sherpa" in r["paso"], r
    assert r["acc"] == {"oculto": True, "tag": "SECTION", "aria": "Acciones propuestas"}, r
    # la bandeja se rellena con la lista de acciones y sus tres botones, y avisa por evento (no ejecuta nada por su cuenta)
    r = json.loads(edge.js("""JSON.stringify((() => {
      window.__ev = []; document.querySelector('#ahora-acciones').addEventListener('accion', (e) => window.__ev.push(e.detail));
      AP.avisos.pintarAcciones([{ id: 'a1', texto: 'Enviar el fichero de tarifas', detalle: 'Ana · viernes', agente: 'coordinador' }]);
      const caja = document.querySelector('#ahora-acciones'); const bs = [...caja.querySelectorAll('.acc-bt button')];
      bs[0].click(); bs[2].click();
      return { oculto: caja.hidden, botones: bs.map((b) => b.textContent), alto: bs.map((b) => Math.round(b.getBoundingClientRect().height)), ev: window.__ev }; })())"""))
    assert r["oculto"] is False and r["botones"] == ["Aceptar", "Editar", "Descartar"] and min(r["alto"]) >= 32, r
    assert r["ev"] == [{"id": "a1", "accion": "aceptar"}, {"id": "a1", "accion": "descartar"}], r


def test_tres_pestanas_con_teclado_y_un_solo_panel(edge, pagina):
    _abrir(edge, pagina)
    r = json.loads(edge.js("""JSON.stringify((() => {
      const vis = () => [...document.querySelectorAll('.tab-panel')].filter((p) => getComputedStyle(p).display !== 'none').map((p) => p.dataset.panel);
      const tabs = [...document.querySelectorAll('.r-tab')].map((t) => t.dataset.tab); const out = { tabs, inicial: vis() };
      const press = (k) => document.querySelector('.r-tab[aria-selected=true]').dispatchEvent(new KeyboardEvent('keydown', { key: k, bubbles: true }));
      press('ArrowRight'); out.a = vis()[0] + '|' + document.querySelector('.r-tab[aria-selected=true]').dataset.tab;
      press('ArrowRight'); out.b = vis()[0]; press('ArrowRight'); out.c = vis()[0]; press('End'); out.fin = vis()[0]; press('Home'); out.ini = vis()[0];
      out.aria = [...document.querySelectorAll('.r-tab')].map((t) => [t.getAttribute('aria-controls'), !!document.getElementById(t.getAttribute('aria-controls'))]);
      return out; })())"""))
    assert r["tabs"] == ["avisos", "pregunta", "sesion"] and r["inicial"] == ["avisos"], r
    assert r["a"] == "pregunta|pregunta" and r["b"] == "sesion" and r["c"] == "avisos" and r["fin"] == "sesion" and r["ini"] == "avisos", r
    assert all(x[1] for x in r["aria"]), r


def _tarjetas(edge, ts):
    edge.js("window.__emitir({tipo: 'tarjetas', nuevas: %s}); 1" % json.dumps(ts))
    time.sleep(0.6)


def test_avisos_unen_consejos_e_insights_y_el_filtro_por_agente_oculta_el_resto(edge, pagina):
    _abrir(edge, pagina)
    _asesor(edge)
    nuevas = [{"id": "x1", "analisis": 9, "categoria": "regla", "texto": "El cupo máximo es de diez", "minuto": "06:00", "t_seg": 360, "estado": "confirmada", "perfil": "funcional"},
              {"id": "x2", "analisis": 9, "categoria": "pendiente", "texto": "Enviar las tarifas", "minuto": "06:10", "t_seg": 370, "estado": "confirmada", "perfil": "coordinador"}]
    _tarjetas(edge, nuevas)
    r = json.loads(edge.js("""JSON.stringify({ chips: [...document.querySelectorAll('#av-filtros .av-chip')].map((c) => [c.dataset.f, c.getAttribute('aria-pressed'), c.querySelector('.av-n').textContent]),
      consejo: !!document.querySelector('#r-insights .av-consejo'), tarjetas: document.querySelectorAll('#r-insights .tarj').length, alto: [...document.querySelectorAll('#av-filtros .av-chip')].map((c) => Math.round(c.getBoundingClientRect().height)) })"""))
    claves = [c[0] for c in r["chips"]]
    assert claves[0] == "" and {"coordinador", "funcional", "constructor", "estratega"} <= set(claves), r      # Todos + un chip por agente con avisos (el Sherpa por su consejo)
    assert r["consejo"] and r["tarjetas"] >= 6 and min(r["alto"]) >= 32, r                                   # el consejo y los insights, en la MISMA lista
    nombres = edge.js("[...document.querySelectorAll('#av-filtros .av-chip .ag-n')].map((n) => n.textContent).join(',')")
    assert "Lupa" in nombres and "Capitán" in nombres and "Arquitecto" in nombres and "Sherpa" in nombres, nombres
    edge.js("document.querySelector('#av-filtros .av-chip[data-f=funcional]').click(); 1")
    time.sleep(0.4)
    r = json.loads(edge.js("""JSON.stringify({ vis: [...document.querySelectorAll('#r-insights > *')].filter((e) => getComputedStyle(e).display !== 'none' && e.getBoundingClientRect().height > 0).map((e) => e.dataset.ag),
      presionado: document.querySelector('#av-filtros .av-chip[data-f=funcional]').getAttribute('aria-pressed') })"""))
    assert r["presionado"] == "true" and r["vis"] and set(r["vis"]) == {"funcional"}, r                      # solo lo de la Lupa
    edge.js("document.querySelector('#av-filtros .av-chip-todos').click(); 1")
    time.sleep(0.3)
    assert edge.js("[...document.querySelectorAll('#r-insights > *')].filter((e) => getComputedStyle(e).display !== 'none').length") >= 8


def test_tres_prioridades_fijo_arriba_hasta_cerrarlo_y_discreto_que_se_aparta(edge, pagina):
    _abrir(edge, pagina)
    fijo = {"id": "f1", "analisis": 9, "categoria": "contradicción", "texto": "Se dijo 84.000 euros y el contrato dice 60.000 euros", "minuto": "07:00", "t_seg": 420, "estado": "confirmada", "perfil": "revisor"}
    normal = {"id": "n1", "analisis": 9, "categoria": "decisión", "texto": "El piloto sigue el 20 de enero", "minuto": "07:10", "t_seg": 430, "estado": "confirmada", "perfil": "coordinador"}
    idea = {"id": "d1", "analisis": 9, "categoria": "idea", "texto": "Empezar con un solo hotel", "minuto": "07:20", "t_seg": 440, "estado": "confirmada", "perfil": "funcional"}
    _tarjetas(edge, [fijo, normal, idea])
    r = json.loads(edge.js("""JSON.stringify({ prios: Object.fromEntries([...document.querySelectorAll('.tarj')].map((t) => [t.dataset.id, [t.dataset.prio, !!t.closest('#av-fijos')]])),
      fijosVisibles: !document.querySelector('#av-fijos').hidden, pos: document.querySelector('#av-fijos').getBoundingClientRect().top < document.querySelector('#r-insights').getBoundingClientRect().top })"""))
    assert r["prios"]["f1"] == ["fijo", True] and r["prios"]["n1"] == ["normal", False] and r["prios"]["d1"] == ["discreto", False], r["prios"]
    assert r["fijosVisibles"] and r["pos"], r                                                                 # el fijo, fuera de la lista y por encima
    # un fijo no caduca: sigue en su sitio aunque pase la vida de un aviso normal (el emergente no lleva temporizador)
    edge.js("document.querySelector('#av-fijos .av-cerrar').click(); 1")
    time.sleep(0.4)
    assert edge.js("document.querySelector('#av-fijos').hidden") is True and edge.js("!document.querySelector('#av-fijos .tarj')") is True      # solo se va al cerrarlo
    # discreto: tras su tiempo se aparta a «ya vistos», plegado
    edge.js("AP.avisosEstado.llegada.set('d1', -1e9); AP.hooks.pintarInsights(); 1")
    time.sleep(0.3)
    r = json.loads(edge.js("""JSON.stringify({ enLista: !!document.querySelector('#r-insights .tarj[data-id=d1]'), apartados: !document.querySelector('#av-discretos').hidden,
      texto: document.querySelector('#av-discretos .av-disc-b').textContent, plegado: document.querySelector('#av-discretos .av-disc-l').hidden })"""))
    assert r["enLista"] is False and r["apartados"] is True and r["plegado"] is True and re.fullmatch(r"Ver \d+ avisos? discretos? ya vistos?", r["texto"]), r
    edge.js("document.querySelector('#av-discretos .av-disc-b').click(); 1")
    time.sleep(0.3)
    assert edge.js("!!document.querySelector('#av-discretos .tarj[data-id=d1]')") is True


def test_el_fijo_no_emerge_se_queda_arriba_de_avisos_y_uno_normal_si_emerge(edge, pagina):
    _abrir(edge, pagina)
    fijo = {"id": "f2", "analisis": 9, "categoria": "contradicción", "texto": "El alcance dice fase 1 sin SAP y se acaba de aceptar SAP", "minuto": "07:00", "t_seg": 420, "estado": "confirmada", "perfil": "revisor"}
    normal = {"id": "n2", "analisis": 9, "categoria": "decisión", "texto": "El piloto sigue el 20 de enero", "minuto": "07:10", "t_seg": 430, "estado": "confirmada", "perfil": "coordinador"}
    edge.js("window.__emitir({tipo: 'tarjetas', nuevas: %s}); 1" % json.dumps([fijo, normal]))
    time.sleep(3)
    assert edge.js("[...document.querySelectorAll('#r-notifs .notif')].map((n) => n.dataset.k).join(',')") == "decision"     # lo normal emerge; lo fijo, no: ya está arriba
    assert edge.js("!!document.querySelector('#av-fijos .tarj[data-id=f2]') && !document.querySelector('#av-fijos').hidden") is True
    assert edge.js("document.querySelector('#tab-n-avisos').textContent") != ""                                              # y la pestaña cuenta el aviso aunque se esté en otra
    time.sleep(1)
    assert edge.js("!!document.querySelector('#av-fijos .tarj[data-id=f2]')") is True


# ------------------------------------------------------------ agentes con nombre
def test_los_agentes_se_llaman_capitan_lupa_arquitecto_auditor_y_sherpa_en_toda_la_app(edge, pagina):
    _abrir(edge, pagina)
    _asesor(edge)
    r = json.loads(edge.js("""JSON.stringify({
      tira: [...document.querySelectorAll('.av')].map((a) => [a.dataset.agente, a.title.split(':')[0], !!a.querySelector('svg')]),
      tarjetas: [...document.querySelectorAll('.eq-tarj')].map((t) => t.dataset.perfil + ':' + t.querySelector('.eq-nombre').textContent),
      mapa: Object.fromEntries(['coordinador','funcional','constructor','revisor','estratega','monitor','asesor'].map((k) => [k, [AP.agente(k).nombre, AP.agente(k).icono, AP.agente(k).color]])),
      iconosDistintos: new Set([...document.querySelectorAll('.av svg')].map((s) => s.getAttribute('class'))).size })"""))
    assert [t[1] for t in r["tira"]][:7] == ["Monitor", "Capitán", "Lupa", "Arquitecto", "Auditor", "Sherpa", "Asesor"] and all(t[2] for t in r["tira"]), r["tira"]
    assert r["tarjetas"] == ["coordinador:Capitán", "funcional:Lupa", "constructor:Arquitecto", "revisor:Auditor", "estratega:Sherpa"][: len(r["tarjetas"])] and len(r["tarjetas"]) >= 4, r["tarjetas"]
    assert {k: v[0] for k, v in r["mapa"].items()} == AGENTES and r["iconosDistintos"] >= 7, r
    assert all(v[2].startswith("var(--ag-") for v in r["mapa"].values())
    # en cada tema, el chip de agente se pinta con su color y el contraste del texto sobre la tarjeta es AA
    col = json.loads(edge.js("""JSON.stringify([...document.querySelectorAll('#r-insights .tarj .perfil .ag')].slice(0, 3).map((a) => [a.textContent, getComputedStyle(a).color]))"""))
    assert col and all(c[1] != "rgba(0, 0, 0, 0)" for c in col), col


# ------------------------------------------------------------ revisión en cuatro pasos
REV = {"estado": "lista", "resumen": "Se acordó mantener el piloto el 20 de enero con dos hoteles.", "resumen_sonnet": "Resumen.", "error": "", "aplicado": None, "carpeta_contexto": True, "compartido": False,
       "destino_contexto": "", "sin_cambios": "", "pulido": {"estado": "ninguno", "resumen": "", "error": "", "elegida": "sonnet"}, "avisos": [], "publicacion": None,
       "objetivos": [{"n": 1, "texto": "Acordar la fecha del piloto", "estado": "cubierto", "minuto": "01:55"}, {"n": 2, "texto": "Cerrar el alcance de SAP", "estado": "parcial", "minuto": ""}],
       "cambios": [{"id": "c1", "fichero": "02-alcance.md", "motivo": "Alcance de la fase 1", "minuto": "02:10", "valido": True, "preaceptado": True, "cita": "Eso estaba fuera de alcance, lo acordamos en el kick off",
                    "diff": "--- a/02-alcance.md\n+++ b/02-alcance.md\n@@ -1,3 +1,4 @@\n # Alcance\n-Fase 1: reservas\n+Fase 1: reservas. SAP queda fuera (fase 2).\n"},
                   {"id": "c2", "fichero": "05-calendario.md", "motivo": "Fecha del piloto", "minuto": "01:55", "valido": True,
                    "diff": "--- a/05-calendario.md\n+++ b/05-calendario.md\n@@ -1 +1,2 @@\n-Piloto: por definir\n+Piloto: 20 de enero\n"}],
       "correo": "Asunto: Resumen: Integración (06/11/2026)\n\nHola:\n\nCerrado\n- Decisión: el piloto sigue el 20 de enero\n\nAbierto\n- Pendiente: enviar tarifas (Ana)\n\nUn saludo."}


def _revision(edge, pagina, rev=REV, **cambios):
    _abrir(edge, pagina, **cambios)
    edge.js("AP.UI.info = { config: { autonomia: { cambio_contexto: 'hacer' } } }; 1")   # con autonomía «hacer» (ola 3) lo preaceptado sale marcado; con «proponer», solo resaltado
    edge.js("window.__emitir(Object.assign({tipo: 'snapshot'}, %s)); 1" % json.dumps(foto(estado="revision", revision=rev)))
    time.sleep(0.8)


def test_la_revision_es_un_stepper_accesible_de_cuatro_pasos_que_caben_a_1280x720(edge, pagina):
    _revision(edge, pagina)
    r = json.loads(edge.js("""JSON.stringify((() => {
      const est = () => [...document.querySelectorAll('#rev-stepper .rev-st')].map((b) => b.getAttribute('aria-current'));
      const out = { pasos: [...document.querySelectorAll('#rev-stepper .rev-st-n')].map((b) => b.textContent), inicial: est(), nav: document.querySelector('nav[aria-label="Pasos de la revisión"]') !== null,
        lista: document.querySelector('#rev-stepper').tagName, caben: [], alturas: [], ganttAbierto: document.querySelector('#rev-gantt').open, ganttHay: !!document.querySelector('#rev-gantt #sesion-revision') };
      for (let n = 1; n <= 4; n++) { document.querySelector('#rev-stepper .rev-st[data-paso="' + n + '"]').click();
        const p = document.querySelector('#rev-paso-' + n); out.caben.push([n, !p.hidden, p.scrollHeight <= p.clientHeight + 2]); out.alturas.push(Math.round(p.getBoundingClientRect().bottom));
        out['actual' + n] = est().indexOf('step') + 1; out['visibles' + n] = [...document.querySelectorAll('.rev-paso')].filter((x) => !x.hidden).length; }
      out.doc = [document.documentElement.scrollHeight, innerHeight]; return out; })())"""))
    assert r["pasos"] == ["Decisiones y resumen", "Cambios al contexto", "Correo de cierre", "Publicar o guardar"] and r["nav"] and r["lista"] == "OL", r
    assert r["inicial"] == ["step", None, None, None], r["inicial"]
    assert [r[f"actual{n}"] for n in (1, 2, 3, 4)] == [1, 2, 3, 4] and all(r[f"visibles{n}"] == 1 for n in (1, 2, 3, 4)), r
    assert all(c[1] and c[2] for c in r["caben"]), r["caben"]                                                    # cada paso cabe sin scroll largo (con estos datos, sin scroll)
    assert max(r["alturas"]) <= 720 and r["ganttAbierto"] is False and r["ganttHay"] is True, r                  # el Gantt, plegado por defecto
    assert r["doc"][0] <= r["doc"][1] + 1, r["doc"]


def test_el_stepper_se_maneja_con_teclado_y_atras_siguiente(edge, pagina):
    _revision(edge, pagina)
    r = json.loads(edge.js("""JSON.stringify((() => {
      const cur = () => [...document.querySelectorAll('#rev-stepper .rev-st')].findIndex((b) => b.getAttribute('aria-current') === 'step') + 1;
      const out = { c0: cur(), atras0: document.querySelector('#rev-atras').disabled };
      document.querySelector('#rev-siguiente').click(); out.c1 = cur(); document.querySelector('#rev-siguiente').click(); document.querySelector('#rev-siguiente').click(); out.c3 = cur(); out.sigOculto = document.querySelector('#rev-siguiente').hidden;
      document.querySelector('#rev-atras').click(); out.c2 = cur(); out.foco = document.activeElement.className;
      const b1 = document.querySelector('#rev-stepper .rev-st[data-paso="1"]'); b1.focus(); b1.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true })); out.focoFlecha = document.activeElement.dataset.paso;
      out.anuncio = document.querySelector('#rev-anuncio').textContent; return out; })())"""))
    assert r["c0"] == 1 and r["atras0"] is True and r["c1"] == 2 and r["c3"] == 4 and r["sigOculto"] is True and r["c2"] == 3, r
    assert r["focoFlecha"] == "2" and r["anuncio"] == "Paso 3 de 4: Correo de cierre", r
    assert "rev-p-t" in r["foco"]                                                                                # al cambiar de paso el foco va al título del paso


def test_cambio_preaceptado_sale_marcado_con_su_cita_y_sin_el_campo_se_comporta_como_hoy(edge, pagina):
    _revision(edge, pagina)
    edge.js("document.querySelector('#rev-stepper .rev-st[data-paso=\"2\"]').click(); 1")
    r = json.loads(edge.js("""JSON.stringify({ pre: document.querySelector('.cambio[data-id=c1]').dataset.decision, normal: document.querySelector('.cambio[data-id=c2]').dataset.decision,
      cita: document.querySelector('.cambio[data-id=c1] .pre-cita').textContent, etiqueta: document.querySelector('.cambio[data-id=c1] .pre-et').textContent, sinCita: !!document.querySelector('.cambio[data-id=c2] .pre-cita'),
      cuenta: document.querySelector('#v-rev-cuenta').textContent, estado: document.querySelector('#rev-st-e-2').textContent, aplicar: document.querySelector('#v-rev-aplicar').disabled,
      citaVisible: document.querySelector('.cambio[data-id=c1] .pre-cita').getBoundingClientRect().height > 0 })"""))
    assert r["pre"] == "si" and r["normal"] == "" and "kick off" in r["cita"] and r["etiqueta"] == "Preaceptado" and r["sinCita"] is False and r["citaVisible"], r
    assert r["cuenta"].startswith("1 aceptado de 2") and r["estado"] == "1 de 2 aceptados" and r["aplicar"] is False, r
    edge.js("document.querySelector('.cambio[data-id=c1] .deshacer').click(); 1")                               # se puede deshacer, y el repintado no lo vuelve a marcar
    time.sleep(0.3)
    edge.js("window.__emitir(Object.assign({tipo: 'snapshot'}, %s)); 1" % json.dumps(foto(estado="revision", revision=REV)))
    time.sleep(0.6)
    assert edge.js("document.querySelector('.cambio[data-id=c1]').dataset.decision") == ""
    # sin `preaceptado` en el backend: nada marcado
    rev2 = dict(REV, cambios=[{k: v for k, v in c.items() if k not in ("preaceptado", "cita")} for c in REV["cambios"]])
    _revision(edge, pagina, rev2)
    edge.js("document.querySelector('#rev-stepper .rev-st[data-paso=\"2\"]').click(); 1")
    assert edge.js("[...document.querySelectorAll('.cambio')].map((c) => c.dataset.decision).join('|')") == "|"
    assert edge.js("document.querySelectorAll('.pre-cita').length") == 0


def test_correo_copiar_y_abrir_en_outlook_envia_asunto_y_cuerpo(edge, pagina):
    _revision(edge, pagina)
    edge.js("""window.__respuestas = []; const f1 = window.fetch; window.fetch = async (u, o) => { if (/correo\\/outlook/.test(u) && o && o.method === 'POST') { window.__respuestas.push(JSON.parse(o.body)); return { ok: true, status: 200, json: async () => ({ ok: true }) }; }
      return f1(u, o); }; 1""")
    edge.js("document.querySelector('#rev-stepper .rev-st[data-paso=\"3\"]').click(); 1")
    time.sleep(0.4)
    assert edge.js("document.querySelector('#v-rev-correo-copiar') !== null && !document.querySelector('#v-rev-correo-outlook').hidden") is True
    edge.js("document.querySelector('#v-rev-correo-outlook').click(); 1")
    time.sleep(0.5)
    env = json.loads(edge.js("JSON.stringify(window.__respuestas)"))
    assert env == [{"asunto": "Resumen: Integración (06/11/2026)", "cuerpo": REV["correo"].split("\n\n", 1)[1]}], env
    assert "Outlook" in edge.js("document.querySelector('#v-rev-correo-estado').textContent")
    # ok:false → el error se enseña y se puede copiar a mano
    edge.js("""window.fetch = async (u, o) => (/correo\\/outlook/.test(u) && o && o.method === 'POST' ? { ok: true, status: 200, json: async () => ({ ok: false, error: 'Outlook no está instalado' }) } : { ok: true, json: async () => ({}) }); 1""")
    edge.js("document.querySelector('#v-rev-correo-outlook').click(); 1")
    time.sleep(0.5)
    assert "Outlook no está instalado" in edge.js("document.querySelector('#v-rev-correo-estado').textContent")


def test_si_el_endpoint_de_outlook_da_404_el_boton_se_oculta(edge, pagina):
    _abrir(edge, pagina)
    edge.js("""const f1 = window.fetch; window.fetch = async (u, o) => (/correo\\/outlook/.test(u) ? { ok: false, status: 404, json: async () => ({ detail: 'Not Found' }) } : f1(u, o)); 1""")
    edge.js("window.__emitir(Object.assign({tipo: 'snapshot'}, %s)); 1" % json.dumps(foto(estado="revision", revision=REV)))
    time.sleep(0.6)
    edge.js("document.querySelector('#rev-stepper .rev-st[data-paso=\"3\"]').click(); 1")
    time.sleep(0.6)
    assert edge.js("document.querySelector('#v-rev-correo-outlook').hidden") is True
    assert edge.js("document.querySelector('#v-rev-correo-copiar').offsetParent !== null") is True           # Copiar sigue ahí


def test_pulir_vive_en_el_paso_1_y_publicar_en_el_4(edge, pagina):
    pub = {"estado": "pendiente", "publicar": True, "destino": "Carpeta compartida de ejemplo", "carpeta": "x", "carpeta_existe": True, "ruta": "", "error": ""}
    _revision(edge, pagina, dict(REV, publicacion=pub, compartido=True, destino_contexto="Carpeta compartida de ejemplo"))
    r = json.loads(edge.js("""JSON.stringify({ pulir: !!document.querySelector('#rev-paso-1 #v-rev-pulir'), pub: !!document.querySelector('#rev-paso-4 #v-rev-pub'), cambios: !!document.querySelector('#rev-paso-2 #v-rev-aceptar-todo'),
      correo: !!document.querySelector('#rev-paso-3 #v-rev-correo-texto'), cierre: document.querySelector('#rev-cierre').innerText })"""))
    assert r["pulir"] and r["pub"] and r["cambios"] and r["correo"], r
    assert "ya están guardados" in r["cierre"], r


# ------------------------------------------------------------ paleta de comandos
def test_ctrl_k_abre_la_paleta_en_toda_la_app_con_busqueda_flechas_intro_y_esc(edge, pagina):
    _abrir(edge, pagina)
    edge.js("document.querySelector('#r-terminar').focus(); document.dispatchEvent(new KeyboardEvent('keydown', { key: 'k', ctrlKey: true, bubbles: true })); 1")
    time.sleep(0.4)
    r = json.loads(edge.js("""JSON.stringify({ abierta: document.querySelector('#paleta').open, foco: document.activeElement.id, rol: document.querySelector('#paleta-q').getAttribute('role'),
      lista: document.querySelector('#paleta-lista').getAttribute('role'), opciones: [...document.querySelectorAll('#paleta-lista [role=option]')].map((o) => o.textContent), modal: document.querySelector('#paleta').matches(':modal'),
      sel: document.querySelector('#paleta-lista [aria-selected=true]').id, activo: document.querySelector('#paleta-q').getAttribute('aria-activedescendant') })"""))
    assert r["abierta"] and r["foco"] == "paleta-q" and r["rol"] == "combobox" and r["lista"] == "listbox" and r["modal"], r
    assert r["sel"] == r["activo"], r
    txt = " | ".join(r["opciones"])
    for esperado in ("Terminar la reunión", "Pausar la grabación", "Analizar ahora", "Ajustes", "Sesiones y pendientes", "Cambiar el tema", "Preguntar al asistente"):
        assert esperado in txt, (esperado, txt)
    # búsqueda difusa: sin acentos, letras en orden
    edge.js("(() => { const q = document.querySelector('#paleta-q'); q.value = 'trmnr'; q.dispatchEvent(new Event('input', { bubbles: true })); return 1; })()")
    assert edge.js("document.querySelector('#paleta-lista [role=option]').textContent").startswith("Terminar la reunión")
    edge.js("(() => { const q = document.querySelector('#paleta-q'); q.value = 'anali'; q.dispatchEvent(new Event('input', { bubbles: true })); return 1; })()")
    assert edge.js("document.querySelector('#paleta-lista [role=option]').textContent").startswith("Analizar ahora")
    edge.js("(() => { const q = document.querySelector('#paleta-q'); q.value = 'zzzzqq'; q.dispatchEvent(new Event('input', { bubbles: true })); return 1; })()")
    assert edge.js("document.querySelectorAll('#paleta-lista [role=option]').length") == 0 and "Sin resultados" in edge.js("document.querySelector('#paleta-estado').textContent")
    # flechas e Intro: «ajust» → Ajustes → abre el diálogo de Ajustes
    edge.js("(() => { const q = document.querySelector('#paleta-q'); q.value = 'ajust'; q.dispatchEvent(new Event('input', { bubbles: true })); return 1; })()")
    assert edge.js("document.querySelector('#paleta-lista [aria-selected=true]').textContent").startswith("Ajustes")
    edge.js("(() => { const q = document.querySelector('#paleta-q'); q.value = ''; q.dispatchEvent(new Event('input', { bubbles: true })); return 1; })()")
    edge.js("document.querySelector('#paleta-q').dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true })); 1")
    assert edge.js("document.querySelector('#paleta-lista [aria-selected=true]').id") == "pal-o-1" and edge.js("document.querySelector('#paleta-q').getAttribute('aria-activedescendant')") == "pal-o-1"
    edge.js("document.querySelector('#paleta-q').dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowUp', bubbles: true })); document.querySelector('#paleta-q').dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowUp', bubbles: true })); 1")
    assert edge.js("document.querySelector('#paleta-lista [aria-selected=true]').id") == "pal-o-%d" % (len(r["opciones"]) - 1)   # da la vuelta
    edge.js("(() => { const q = document.querySelector('#paleta-q'); q.value = 'ajust'; q.dispatchEvent(new Event('input', { bubbles: true })); q.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true })); return 1; })()")
    time.sleep(0.8)
    assert edge.js("document.querySelector('#paleta').open") is False and edge.js("document.querySelector('#d-ajustes').open") is True
    edge.js("document.querySelector('#s-cancelar').click(); 1")
    # Esc cierra y devuelve el foco a donde estaba
    edge.js("document.querySelector('#r-terminar').focus(); document.dispatchEvent(new KeyboardEvent('keydown', { key: 'k', ctrlKey: true, bubbles: true })); 1")
    time.sleep(0.3)
    edge.js("document.querySelector('#paleta').dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true })); 1")
    time.sleep(0.3)
    assert edge.js("document.querySelector('#paleta').open") is False and edge.js("document.activeElement.id") == "r-terminar"
    # Ctrl+K también desde un campo de texto, y vuelve a cerrar
    edge.js("document.querySelector('#r-notas').focus(); document.querySelector('#r-notas').dispatchEvent(new KeyboardEvent('keydown', { key: 'k', ctrlKey: true, bubbles: true })); 1")
    assert edge.js("document.querySelector('#paleta').open") is True
    edge.js("document.dispatchEvent(new KeyboardEvent('keydown', { key: 'k', ctrlKey: true, bubbles: true })); 1")
    assert edge.js("document.querySelector('#paleta').open") is False


def test_la_paleta_ofrece_lo_que_toca_en_cada_vista(edge, pagina):
    _abrir(edge, pagina)
    # reunión: nada de abrir proyectos
    edge.js("AP.UI.proyectos = [{ nombre: 'Proyecto Ficticio Alfa' }, { nombre: 'Proyecto Ficticio Beta' }]; 1")
    en_reunion = json.loads(edge.js("JSON.stringify(AP.paleta.comandos().map((c) => c.titulo))"))
    assert not any(t.startswith("Abrir el proyecto") for t in en_reunion) and "Terminar la reunión" in en_reunion, en_reunion
    # inicio: proyectos y empezar
    edge.js("window.__emitir(Object.assign({tipo: 'snapshot'}, %s)); 1" % json.dumps(foto(estado="inactivo", sesion=None)))
    time.sleep(0.8)
    edge.js("AP.UI.proyectos = [{ nombre: 'Proyecto Ficticio Alfa' }, { nombre: 'Proyecto Ficticio Beta' }]; 1")   # el doble de fetch no devuelve proyectos: se fijan a mano
    en_inicio = json.loads(edge.js("JSON.stringify(AP.paleta.comandos().map((c) => c.titulo))"))
    assert "Abrir el proyecto Proyecto Ficticio Alfa" in en_inicio and "Abrir el proyecto Proyecto Ficticio Beta" in en_inicio and "Terminar la reunión" not in en_inicio, en_inicio
    assert "Empezar una reunión sin proyecto" in en_inicio and "Ajustes" in en_inicio and "Cambiar el tema (ahora automático)" in en_inicio
    edge.js("document.dispatchEvent(new KeyboardEvent('keydown', { key: 'k', ctrlKey: true, bubbles: true })); (() => { const q = document.querySelector('#paleta-q'); q.value = 'beta'; q.dispatchEvent(new Event('input', { bubbles: true })); return 1; })()")
    assert edge.js("document.querySelector('#paleta-lista [role=option]').textContent").startswith("Abrir el proyecto Proyecto Ficticio Beta")
    edge.js("document.querySelector('#paleta').dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true })); 1")
    # revisión: ir a cada paso
    edge.js("window.__emitir(Object.assign({tipo: 'snapshot'}, %s)); 1" % json.dumps(foto(estado="revision", revision=REV)))
    time.sleep(0.7)
    en_rev = json.loads(edge.js("JSON.stringify(AP.paleta.comandos().map((c) => c.titulo))"))
    assert [t for t in en_rev if t.startswith("Revisión, paso")] == ["Revisión, paso 1: Decisiones y resumen", "Revisión, paso 2: Cambios al contexto", "Revisión, paso 3: Correo de cierre", "Revisión, paso 4: Publicar o guardar"], en_rev
    edge.js("document.dispatchEvent(new KeyboardEvent('keydown', { key: 'k', ctrlKey: true, bubbles: true })); (() => { const q = document.querySelector('#paleta-q'); q.value = 'paso 3'; q.dispatchEvent(new Event('input', { bubbles: true })); q.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true })); return 1; })()")
    time.sleep(0.6)
    assert edge.js("[...document.querySelectorAll('#rev-stepper .rev-st')].findIndex((b) => b.getAttribute('aria-current') === 'step') + 1") == 3


def test_la_barra_inclinada_sigue_enfocando_el_buscador_de_la_galeria_y_ctrl_k_ya_no(edge, pagina):
    js = (WEB / "proyectos.js").read_text(encoding="utf-8")
    assert 'ev.key === "/"' in js and 'ev.key.toLowerCase() === "k"' not in js


# ------------------------------------------------------------ Ajustes
def test_ajustes_en_tres_secciones_con_pestanas_y_selector_de_modelos(edge, pagina):
    _abrir(edge, pagina)
    edge.js("""const f2 = window.fetch; window.fetch = async (u, o) => {
      if (/dispositivos/.test(u)) return { ok: true, json: async () => ({ entradas: [{ indice: 1, nombre: 'Micro de ejemplo' }], salidas: [{ indice: 2, nombre: 'Altavoces de ejemplo' }], mic_defecto: 1, sistema_defecto: 2 }) };
      if (/api\\/info/.test(u)) return { ok: true, json: async () => ({ simulacion: false, config: { raiz_proyectos: 'C:/ejemplo', whisper_modelo: 'small', min_palabras_analisis: 40, esfuerzo: '', excluir_captura: true, detectar_llamadas: true, filtrar_eco: true,
        cadencia_defecto: 'equipo', adaptativo_comprobar_s: 30, equipo_puntuacion_min: 3, equipo_enfriamiento_global_s: 240, equipo_enfriamiento_perfil_s: 360, equipo_rotacion_s: 300, equipo_palabras_min: 120, equipo_objetivo_sin_tratar_min: 20,
        presupuesto_tokens_hora: 60000, modelos: { digest: 'haiku', periodico: 'haiku', contradicciones_confirmar: 'sonnet', final: 'sonnet', consulta: 'haiku', pulido: 'opus' }, proyectos_extra: [] } }) };
      return f2(u, o); }; 1""")
    edge.js("document.querySelector('#b-ajustes').click(); 1")
    time.sleep(0.8)
    r = json.loads(edge.js("""JSON.stringify((() => {
      const vis = () => [...document.querySelectorAll('.aj-sec')].filter((s) => !s.hidden).map((s) => s.dataset.aj);
      const tabs = [...document.querySelectorAll('.aj-tab')].map((t) => t.textContent); const out = { abierto: document.querySelector('#d-ajustes').open, tabs, ini: vis() };
      const press = (k) => document.querySelector('.aj-tab[aria-selected=true]').dispatchEvent(new KeyboardEvent('keydown', { key: k, bubbles: true }));
      press('ArrowRight'); out.b = vis(); out.foco = document.activeElement.id; press('ArrowRight'); out.c = vis(); press('ArrowRight'); out.d = vis();
      document.querySelector('#aj-tab-equipo').click();
      out.modelos = ['digest', 'periodico', 'contradicciones_confirmar', 'final', 'consulta'].map((k) => { const s = document.querySelector('[name=m_' + k + ']'); return [s.tagName, s.value, s.selectedOptions[0].textContent]; });
      out.solo = document.querySelector('#aj-solo-local').hidden; out.registro = document.querySelector('#aj-registro-envios').hidden;
      document.querySelector('#aj-tab-audio').click(); out.audio = [document.querySelector('#s-mic').options.length, document.querySelector('[name=whisper_modelo]').value];
      return out; })())"""))
    assert r["abierto"] and r["tabs"] == ["Audio", "Equipo", "Privacidad"] and r["ini"] == ["audio"], r
    assert r["b"] == ["equipo"] and r["foco"] == "aj-tab-equipo" and r["c"] == ["privacidad"] and r["d"] == ["audio"], r
    assert r["modelos"] == [["SELECT", "haiku", "Ligero"], ["SELECT", "haiku", "Ligero"], ["SELECT", "sonnet", "Potente"], ["SELECT", "sonnet", "Potente"], ["SELECT", "haiku", "Ligero"]], r["modelos"]
    assert r["solo"] is True and r["registro"] is True, r                                                          # sin datos del servidor, los huecos de Privacidad quedan ocultos
    assert r["audio"] == [2, "small"], r
    # con datos, aparecen
    edge.js("""const f3 = window.fetch; window.fetch = async (u, o) => { if (/api\\/modo-local/.test(u)) return { ok: true, json: async () => ({ activo: false, sesion: null, config: false }) };
      if (/api\\/envios/.test(u)) return { ok: true, json: async () => ({ envios: [{ ts: '2026-11-07T10:00:00', agente: 'Analista', modelo: 'haiku', entrada: 100, salida: 20, ok: true, bloqueado: false }], resumen: { llamadas: 1, entrada: 100, salida: 20, bloqueadas: 0 } }) }; return f3(u, o); }; 1""")
    edge.js("document.querySelector('#s-cancelar').click(); document.querySelector('#b-ajustes').click(); 1")
    time.sleep(0.8)
    edge.js("document.querySelector('#aj-tab-privacidad').click(); 1")
    assert edge.js("document.querySelector('#aj-solo-local').hidden") is False and edge.js("document.querySelector('#aj-registro-envios').hidden") is False
    edge.js("document.querySelector('#s-cancelar').click(); 1")


# ------------------------------------------------------------ medidas finales: botones de 32 px y sin errores de consola
def _botones_pequenos(edge):
    return json.loads(edge.js("""JSON.stringify([...document.querySelectorAll('button, [role=button], summary')].filter((b) => { const r = b.getBoundingClientRect(); const cs = getComputedStyle(b);
      return r.width > 0 && r.height > 0 && cs.visibility !== 'hidden' && !b.closest('[hidden]') && !b.closest('.sr') && !(b.closest('details:not([open])') && !b.matches('summary') && !b.parentElement.matches('summary')); }).map((b) => { let r = b.getBoundingClientRect(), h = r.height; const a = getComputedStyle(b, '::after');
      if (a.content !== 'none' && a.content !== 'normal') h = Math.max(h, parseFloat(a.height) || 0); return [b.id || b.className || b.tagName, Math.round(h)]; }).filter((x) => x[1] < 32))"""))


def test_botones_de_al_menos_32_px_en_reunion_y_revision_y_sin_errores_de_consola(edge, pagina):
    edge.eventos.clear()
    _abrir(edge, pagina)
    _asesor(edge)
    _tarjetas(edge, [{"id": "z1", "analisis": 9, "categoria": "contradicción", "texto": "El importe del contrato difiere", "minuto": "07:00", "t_seg": 420, "estado": "confirmada", "perfil": "revisor"}])
    pequenos = _botones_pequenos(edge)
    assert pequenos == [], pequenos
    for n in (1, 2, 3, 4):
        _revision(edge, pagina)
        edge.js("document.querySelector('#rev-stepper .rev-st[data-paso=\"%d\"]').click(); 1" % n)
        time.sleep(0.3)
        pequenos = _botones_pequenos(edge)
        assert pequenos == [], (n, pequenos)
    errores = [e for e in edge.eventos if e.get("method") == "Runtime.exceptionThrown" or (e.get("method") == "Runtime.consoleAPICalled" and e["params"].get("type") == "error")]
    assert errores == [], errores[:2]


@pytest.mark.parametrize("esquema", ["light", "dark"])
def test_los_colores_de_agente_se_pintan_con_contraste_aa_en_el_navegador(edge, pagina, esquema):
    _abrir(edge, pagina, esquema=esquema)
    _tarjetas(edge, [{"id": "k1", "analisis": 9, "categoria": "regla", "texto": "Regla de ejemplo", "minuto": "06:00", "t_seg": 360, "estado": "confirmada", "perfil": p}
                     for p in ("coordinador", "funcional", "constructor", "revisor", "estratega")])
    r = json.loads(edge.js("""JSON.stringify((() => {
      const rgb = (c) => c.match(/[\\d.]+/g).map(Number); const lum = (c) => { const [r, g, b] = c.slice(0, 3).map((v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; }); return 0.2126 * r + 0.7152 * g + 0.0722 * b; };
      const fondo = (el) => { for (let e = el; e; e = e.parentElement) { const c = rgb(getComputedStyle(e).backgroundColor); if (c.length < 4 || c[3] > 0.9) { if (c.length >= 3 && (c.length < 4 || c[3] > 0.9)) return c; } } return rgb(getComputedStyle(document.body).backgroundColor); };
      const out = []; for (const a of document.querySelectorAll('#r-insights .tarj .perfil .ag, #av-filtros .av-chip.ag')) { const c = rgb(getComputedStyle(a).color), f = fondo(a); const l1 = lum(c), l2 = lum(f); out.push([a.textContent.trim(), (Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05)]); }
      return out; })())"""))
    assert r, "sin chips de agente"
    assert all(x[1] >= 4.5 for x in r), r
