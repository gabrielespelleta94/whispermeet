"""Ola 1 de la interfaz (arreglos y fricción): diálogo propio en lugar de confirm/alert/prompt, chip de objetivos sin «null», menú «Más» de la cabecera de la
reunión, avisos que se pueden cerrar, Preparar sin scroll con la barra de «Empezar» fija y la tira de Orquestación de 36 px.
Todo en un Edge sin cabeza sobre la interfaz real (dobles de fetch/WebSocket de `_visual_harness.py`; datos ficticios)."""
from __future__ import annotations

import json
import re
import socket
import time

import pytest

from _visual_harness import WEB, Edge, foto, pagina_html


def _puerto():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# ------------------------------------------------------------------ estáticos
def test_no_quedan_dialogos_nativos_en_web():
    patron = re.compile(r"(?<![\w$])(?:window\.)?(?:confirm|alert|prompt)\s*\(")
    encontrados = []
    for f in sorted(WEB.glob("*.js")) + sorted(WEB.glob("*.html")):
        for n, linea in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if patron.search(linea):
                encontrados.append(f"{f.name}:{n}: {linea.strip()[:80]}")
    assert not encontrados, encontrados


def test_el_dialogo_propio_existe_y_es_un_alertdialog_modal():
    js = (WEB / "app.js").read_text(encoding="utf-8")
    for pieza in ("AP.confirmar", "AP.avisar", "AP.pedirTexto", 'role: "alertdialog"', '"aria-modal": "true"', "Escape", "Enter", "Tab"):
        assert pieza in js, pieza


def test_la_cadencia_se_llama_ritmo_del_equipo_y_vive_en_opciones():
    html = (WEB / "index.html").read_text(encoding="utf-8")
    assert "Ritmo del equipo" in html and "Cadencia de análisis" not in html
    assert html.index('id="i-opciones"') < html.index("Ritmo del equipo") < html.index('id="i-barra-empezar"')
    assert html.index('id="i-aviso"') > html.index('id="i-barra-empezar"') and html.index('id="i-empezar"') > html.index('id="i-aviso"')   # consentimiento y botón, en la misma barra


# ------------------------------------------------------------------ en el navegador
@pytest.fixture(scope="module")
def pagina(tmp_path_factory):
    return pagina_html(tmp_path_factory.mktemp("ola1") / "app.html")


@pytest.fixture(scope="module")
def edge(tmp_path_factory):
    e = Edge(tmp_path_factory.mktemp("edge-ola1"), _puerto(), ancho=1280, alto=720)
    yield e
    e.cerrar()


def _abrir_reunion(edge, pagina, **cambios):
    edge.abrir(pagina.as_uri())
    edge.js("localStorage.clear(); sessionStorage.clear(); 1")
    edge.abrir(pagina.as_uri())
    edge.js("window.__llamadas = []; const f0 = window.fetch; window.fetch = (u, o) => { window.__llamadas.push((o && o.method || 'GET') + ' ' + u); return f0(u, o); }; 1")
    edge.js("window.__emitir(Object.assign({tipo: 'snapshot'}, %s)); 1" % json.dumps(foto(estado="grabando", **cambios)))
    time.sleep(0.5)


def test_chip_de_objetivos_sin_cubrir_no_pinta_null(edge, pagina):
    _abrir_reunion(edge, pagina)
    objs = [{"n": i, "texto": f"Objetivo {i}", "estado": "sin_tratar", "minuto": "", "t_seg": None, "origen": "plan"} for i in range(1, 5)]
    edge.js("window.__emitir(%s); 1" % json.dumps({"tipo": "objetivos", "objetivos": objs}))
    time.sleep(0.4)
    texto = edge.js("document.querySelector('#r-obj-prog').textContent")
    assert texto == "0 de 4 objetivos" and "null" not in texto


def test_terminar_abre_el_dialogo_propio_con_foco_atrapado_y_teclas(edge, pagina):
    _abrir_reunion(edge, pagina)
    r = json.loads(edge.js("""JSON.stringify((() => {
      const b = document.querySelector('#r-terminar'); b.focus(); b.click();
      const d = document.querySelector('.dp-caja'); if (!d) return { hay: false };
      const foco = document.activeElement;
      return { hay: true, rol: d.getAttribute('role'), modal: d.getAttribute('aria-modal'), titulo: d.querySelector('.dp-titulo').textContent,
        botones: [...d.querySelectorAll('button')].map((x) => x.textContent), foco: foco.textContent, aislado: document.querySelector('#app').inert === true };
    })())"""))
    assert r["hay"] and r["rol"] == "alertdialog" and r["modal"] == "true" and r["titulo"].startswith("¿Terminar")
    assert r["botones"] == ["Seguir grabando", "Terminar"] and r["foco"] == "Terminar" and r["aislado"]
    # Tab y Mayús+Tab no salen del diálogo
    edge.js("document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Tab', bubbles: true, cancelable: true})); 1")
    assert edge.js("!!document.activeElement.closest('.dp-caja')")
    edge.js("document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Tab', shiftKey: true, bubbles: true, cancelable: true})); 1")
    assert edge.js("!!document.activeElement.closest('.dp-caja')")
    # Esc cancela: no se llama al servidor, el diálogo desaparece y el foco vuelve al botón que lo abrió
    edge.js("document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true, cancelable: true})); 1")
    time.sleep(0.2)
    assert edge.js("!document.querySelector('.dp-caja') && document.activeElement.id === 'r-terminar' && document.querySelector('#app').inert === false")
    assert not [x for x in json.loads(edge.js("JSON.stringify(window.__llamadas)")) if "terminar" in x]
    # Intro acepta: ahora sí se pide terminar
    edge.js("document.querySelector('#r-terminar').click(); 1")
    edge.js("document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Enter', bubbles: true, cancelable: true})); 1")
    time.sleep(0.3)
    assert edge.js("!document.querySelector('.dp-caja')")
    assert any("POST /api/sesion/terminar" in x for x in json.loads(edge.js("JSON.stringify(window.__llamadas)")))


def test_menu_mas_de_la_cabecera_con_teclado(edge, pagina):
    _abrir_reunion(edge, pagina)
    r = json.loads(edge.js("""JSON.stringify((() => {
      const m = document.querySelector('#r-mas'), p = document.querySelector('#r-mas-panel');
      const prim = [...document.querySelectorAll('#r-cab .btn-primary')].map((b) => b.id);
      return { haspopup: m.getAttribute('aria-haspopup'), expandido: m.getAttribute('aria-expanded'), cerrado: p.hidden, primarios: prim,
        items: [...p.querySelectorAll('[role=menuitem]')].map((b) => b.id) };
    })())"""))
    assert r["haspopup"] == "menu" and r["expandido"] == "false" and r["cerrado"]
    assert r["primarios"] == ["r-terminar"]                                                   # una sola acción principal
    assert r["items"] == ["r-bandeja-btn", "r-contexto", "r-pausa", "r-analizar"]
    tecla = lambda k, sel="document": edge.js("(%s.activeElement || document.activeElement).dispatchEvent(new KeyboardEvent('keydown', {key: %s, bubbles: true, cancelable: true})); 1" % (sel, json.dumps(k)))
    edge.js("document.querySelector('#r-mas').focus(); 1")
    tecla("ArrowDown")
    assert edge.js("document.querySelector('#r-mas').getAttribute('aria-expanded')") == "true" and edge.js("document.activeElement.id") == "r-bandeja-btn"
    tecla("ArrowDown"); assert edge.js("document.activeElement.id") == "r-contexto"
    tecla("End"); assert edge.js("document.activeElement.id") == "r-analizar"
    tecla("ArrowDown"); assert edge.js("document.activeElement.id") == "r-bandeja-btn"          # vuelta al principio
    tecla("ArrowUp"); assert edge.js("document.activeElement.id") == "r-analizar"
    tecla("Escape")
    assert edge.js("document.querySelector('#r-mas-panel').hidden") and edge.js("document.activeElement.id") == "r-mas"
    assert edge.js("document.querySelector('#r-mas').getAttribute('aria-expanded')") == "false"


def test_el_aviso_se_cierra_y_no_vuelve_en_esa_sesion(edge, pagina):
    _abrir_reunion(edge, pagina, avisos=["El fichero prioritario de la sesión (04-plan.md) no está disponible o está vacío."])
    assert edge.js("!document.querySelector('#r-avisos').hidden && document.querySelectorAll('#r-avisos .aviso-x').length") == 1
    edge.js("document.querySelector('#r-avisos .aviso-x').click(); 1")
    assert edge.js("document.querySelector('#r-avisos').hidden")
    # llega otro estado con el mismo aviso: sigue cerrado
    edge.js("window.__emitir({tipo: 'estado', estado: 'grabando', avisos: %s}); 1" % json.dumps(["El fichero prioritario de la sesión (04-plan.md) no está disponible o está vacío."]))
    time.sleep(0.3)
    assert edge.js("document.querySelector('#r-avisos').hidden")


def test_orquestacion_plegada_es_una_tira_de_36_px_con_avatares(edge, pagina):
    _abrir_reunion(edge, pagina)
    r = json.loads(edge.js("""JSON.stringify((() => {
      const o = document.querySelector('#orq'), r = o.getBoundingClientRect();
      return { alto: r.height, plegado: o.dataset.plegado, avatares: [...o.querySelectorAll('.av')].map((a) => a.textContent), animados: [...o.querySelectorAll('.av')].filter((a) => a.dataset.estado === 'trabajando').length };
    })())"""))
    assert r["plegado"] == "true" and r["alto"] <= 36 and r["avatares"][:5] == ["MO", "CO", "AF", "CT", "RV"] and r["animados"] == 0   # sin tarea abierta, nada se anima
    edge.js("window.__emitir({tipo: 'tarea', id: 't1', agente: 'coordinador', estado: 'en_curso', hora: '10:00:00', modelo: 'haiku', tarea: 'equipo'}); 1")
    time.sleep(0.4)
    assert edge.js("document.querySelector('.av[data-agente=coordinador]').dataset.estado") == "trabajando"
    edge.js("window.__emitir({tipo: 'tarea', id: 't1', agente: 'coordinador', estado: 'hecho', hora: '10:00:03', modelo: 'haiku', ms: 3000, tarea: 'equipo'}); 1")
    time.sleep(0.4)
    assert edge.js("document.querySelector('.av[data-agente=coordinador]').dataset.estado") != "trabajando"
    edge.js("document.querySelector('#orq .orq-linea').click(); 1")                            # un clic en la tira despliega el detalle
    time.sleep(0.5)
    assert edge.js("document.querySelector('#orq').dataset.plegado") == "false"


def test_estado_vacio_de_insights_enseña_lo_detectado_o_dice_que_va_a_aparecer(edge, pagina):
    _abrir_reunion(edge, pagina, tarjetas=[], traza=[], monitor={"feed": [], "definiciones": [], "pasadas": []})
    vacio = edge.js("document.querySelector('#r-insights .vacio-util').textContent")
    assert "Todavía no hay insights" not in vacio and "decisiones" in vacio and "pendientes" in vacio
    entradas = [{"id": "m1", "t": 85, "minuto": "01:25", "tipo": "senal", "texto": "señal: decisión · «queda el piloto el veinte de enero»", "local": True, "senal": "decision"}]
    edge.js("window.__emitir(%s); 1" % json.dumps({"tipo": "monitor", "entradas": entradas}))
    time.sleep(0.5)
    vacio = edge.js("document.querySelector('#r-insights .vacio-util').textContent")
    assert "01:25" in vacio and "Posible decisión" in vacio and "queda el piloto" in vacio


def test_preparar_cabe_en_1280x720_y_el_boton_empezar_esta_dentro(edge, pagina):
    edge.abrir(pagina.as_uri())
    edge.js("localStorage.clear(); sessionStorage.clear(); 1")
    edge.abrir(pagina.as_uri())
    edge.js("window.__emitir(Object.assign({tipo: 'snapshot'}, %s)); 1" % json.dumps(foto(estado="inactivo", sesion=None)))
    edge.js("document.querySelector('#i-galeria').hidden = true; document.querySelector('#i-preparar').hidden = false; document.querySelector('#v-inicio').hidden = false; 1")
    time.sleep(0.4)
    r = json.loads(edge.js("""JSON.stringify((() => {
      const v = document.querySelector('#v-inicio'), e = document.querySelector('#i-empezar').getBoundingClientRect(), a = document.querySelector('#i-aviso').getBoundingClientRect();
      return { scroll: v.scrollHeight - v.clientHeight, abajo: e.bottom, vh: innerHeight, mismaLinea: Math.abs((e.top + e.height / 2) - (a.top + a.height / 2)) < 24 };
    })())"""))
    assert r["scroll"] <= 0 and r["abajo"] <= r["vh"] and r["mismaLinea"]
