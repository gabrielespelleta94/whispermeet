"""Pantalla de inicio: secciones, favoritos, recientes, buscador, teclado y vista previa (web/proyectos.js) en un Edge sin cabeza con datos ficticios."""
from __future__ import annotations

import json
import socket
import time
from datetime import date, timedelta

import pytest

from _visual_harness import Edge, foto, pagina_html

def _dia(dias: int) -> str:
    return (date.today() - timedelta(days=dias)).isoformat()


PROYECTOS = [
    {"nombre": "Alfa Demo", "compartido": False, "extra": False, "tiene_contexto": True, "tiene_sesiones": True, "ruta": "X:/r/Alfa Demo", "plan": None,
     "n_sesiones": 3, "ultima_sesion": _dia(3), "n_md": 9},
    {"nombre": "Beta Demo", "compartido": False, "extra": False, "tiene_contexto": False, "tiene_sesiones": False, "ruta": "X:/r/Beta Demo", "plan": None, "n_md": 2},
    {"nombre": "Carpeta Ajena", "compartido": False, "extra": True, "tiene_contexto": False, "tiene_sesiones": False, "ruta": "X:/o/Ajena", "plan": None},
    {"nombre": "Compartida Demo", "compartido": True, "extra": True, "tiene_contexto": True, "tiene_sesiones": False, "ruta": "X:/c/Comp",
     "plan": {"sesiones": [], "ficha": None, "gantt": None}},
    {"nombre": "Zeta Antigua", "compartido": False, "extra": False, "tiene_contexto": True, "tiene_sesiones": True, "ruta": "X:/r/Zeta", "plan": None,
     "n_sesiones": 2, "ultima_sesion": _dia(120), "n_md": 4},
]
RESUMEN = {"Alfa Demo": {"descripcion": "Portal ficticio de reservas de grupos para una cadena hotelera.", "sesiones_por_semana": [0, 0, 1, 0, 2, 0, 1, 1], "pendientes_abiertos": 4,
                         "ultima_sesion_tema": "Seguimiento", "ultima_sesion_fecha": _dia(3),
                         "calidad_contexto": {"nivel": 3, "etiqueta": "Contexto completo", "breve": "Completo", "motivos": []}},
           "Beta Demo": {"descripcion": None, "sesiones_por_semana": [0] * 8, "pendientes_abiertos": 0,
                         "calidad_contexto": {"nivel": 1, "etiqueta": "Contexto básico", "breve": "Falta 00. CONTEXTO (IA)",
                                              "motivos": ["Falta la carpeta «00. CONTEXTO (IA)»: es lo que el asesor lee primero.", "Mientras tanto se usan los .md que hay."]}},
           "Carpeta Ajena": {"descripcion": None, "sesiones_por_semana": [0] * 8, "pendientes_abiertos": 0,
                             "calidad_contexto": {"nivel": 0, "etiqueta": "Sin contexto", "breve": "Sin ningún .md", "motivos": ["No hay ningún .md en la carpeta."]}},
           "Compartida Demo": {"descripcion": "Calculadora ficticia de cotizaciones.", "sesiones_por_semana": [0] * 8, "pendientes_abiertos": 1,
                               "proximo_hito": {"nombre": "Piloto", "fecha_iso": "2099-01-20", "fecha_texto": "20 ene"},
                               "calidad_contexto": {"nivel": 2, "etiqueta": "Contexto aceptable", "breve": "Pocos ficheros", "motivos": ["Solo 2 ficheros de contenido."]}},
           "Zeta Antigua": {"descripcion": "Proyecto parado ficticio.", "sesiones_por_semana": [0] * 8, "pendientes_abiertos": 0,
                            "calidad_contexto": {"nivel": 3, "etiqueta": "Contexto completo", "breve": "Completo", "motivos": []}}}
PEND = {"total": 7, "avisos": [], "pendientes": [{"id": f"{i:016x}", "texto": f"Pendiente ficticio número {i}", "minuto": "01:00", "responsable": None, "fecha": _dia(3), "tema": "Seguimiento", "sesion_id": "aaaaaaaaaaaaaaaa"} for i in range(5)]}
CTX = {"proyecto": "Alfa Demo", "solo_lectura": False, "truncado": False, "total": 3, "fuera": 1, "limites": {},
       "grupos": [{"clave": "ctx", "titulo": "00. CONTEXTO (IA)", "ficheros": [{"id": "0123456789abcdef", "nombre": "02-alcance.md", "rel": "00. CONTEXTO (IA)/02-alcance.md", "tam": 2048, "dejado": "", "en_digest": True}]},
                  {"clave": "raiz", "titulo": "CLAUDE.md y raíz", "ficheros": [{"id": "1123456789abcdef", "nombre": "CLAUDE.md", "rel": "CLAUDE.md", "tam": 300, "dejado": "", "en_digest": True}]},
                  {"clave": "otros", "titulo": "Otros .md", "ficheros": [{"id": "2123456789abcdef", "nombre": "docs/grande.md", "rel": "docs/grande.md", "tam": 900000, "dejado": "tamaño", "en_digest": False}]}]}
STUB = """(() => {
  window.__llamadas = [];
  const P = %s, CTX = %s, RES = %s, PEND = %s;
  window.fetch = async (u, o) => {
    const m = (o && o.method) || 'GET'; window.__llamadas.push(m + ' ' + u);
    const r = (d, ok = true, status = ok ? 200 : 400) => ({ ok, status, json: async () => d });
    if (/api\\/proyectos\\?/.test(u)) { const q = decodeURIComponent(u.split('q=')[1] || '').toLowerCase(); return r({ raiz: 'X:/r', proyectos: P.filter((p) => p.nombre.toLowerCase().includes(q)) }); }
    if (/api\\/proyectos\\/resumen/.test(u)) return r({ resumen: RES, parcial: false });
    if (/\\/pendientes$/.test(u)) return r(PEND);
    if (/\\/contexto$/.test(u)) return r(CTX);
    if (/\\/archivero\\/guardar$/.test(u) && m === 'POST') {
      const b = JSON.parse(o.body); (window.__cuerpos = window.__cuerpos || []).push(m + ' ' + o.body);
      if (window.__ERR_ARCH === 'guardar') return r({ detail: 'Fallo simulado al guardar.' }, false);
      if (window.__ERR_ARCH === 'conflicto' && b.confirmar) { window.__ERR_ARCH = ''; return r({ detail: 'El resultado ha cambiado; revisa la vista previa antes de guardar.', previa: window.__PREVIA_NUEVA }, false, 409); }
      return r(b.confirmar ? Object.assign({}, window.__PREVIA, { guardado: true }) : window.__PREVIA);
    }
    if (/\\/archivero(\\?refrescar=1)?$/.test(u) && m === 'POST') {
      if (window.__DEMORA) await new Promise((ok) => setTimeout(ok, window.__DEMORA));
      if (window.__ERR_ARCH === 'analizar') return r({ detail: 'Claude no ha respondido.' }, false);
      window.__ARCH = Object.assign({}, window.__ARCH, { resultado: window.__RES }); return r(window.__RES);
    }
    if (/\\/archivero$/.test(u)) return r(window.__ARCH || {});
    if (/documentos\\/[0-9a-f]{16}\\/tipo$/.test(u) && m === 'PUT') { (window.__cuerpos = window.__cuerpos || []).push(m + ' ' + o.body); return r({ ok: true }); }
    if (/\\/documentos$/.test(u)) return r(window.__DOCS || { total: 0, tipos: [], faltan: [], en_nube: 0, truncado: false });
    if (/sesiones-recientes/.test(u)) return r({ sesiones: [{ id: 'aaaaaaaaaaaaaaaa', fecha: '2026-11-04', tema: 'Seguimiento', inicio: '10:00' }], avisos: [] });
    if (/extra\\//.test(u) && m === 'DELETE') { const n = decodeURIComponent(u.split('extra/')[1]); const i = P.findIndex((p) => p.nombre === n); if (i >= 0) P.splice(i, 1); return r({ proyectos_extra: [] }); }
    if (/\\/api\\/info/.test(u)) return r({ simulacion: false, config: { excluir_captura: true, proyectos_extra: [], modelos: {} } });
    if (/ventana/.test(u)) return r({ nativa: false });
    return r({});
  };
})();"""


def _puerto():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def pagina(tmp_path_factory):
    return pagina_html(tmp_path_factory.mktemp("proy") / "app.html")


@pytest.fixture(scope="module")
def edge(tmp_path_factory):
    e = Edge(tmp_path_factory.mktemp("edgep"), _puerto())
    yield e
    e.cerrar()


def abrir(e, pagina, antes="", proyectos=None):
    e.abrir(pagina.as_uri())
    e.js("localStorage.clear(); 1")
    e.abrir(pagina.as_uri())
    e.js(STUB % (json.dumps(PROYECTOS if proyectos is None else proyectos), json.dumps(CTX), json.dumps(RESUMEN), json.dumps(PEND)) + "; 1")
    if antes:
        e.js(antes)
    e.js("window.__emitir(Object.assign({tipo: 'snapshot'}, %s)); 1" % json.dumps(foto(estado="inactivo", sesion=None, revision=None)))
    e.js("AP.cargarProyectos(); 1")
    time.sleep(0.9)


def cabeceras(e):
    return json.loads(e.js("JSON.stringify([...document.querySelectorAll('#i-lista .lista-cab')].map((x) => x.textContent.trim()))"))


def clic(e, selector):
    e.js("document.querySelector(%s).click(); 1" % json.dumps(selector))


def tarjeta(nombre):
    return '.item[data-clave="%s"]' % nombre


def escribir_buscador(e, texto):
    e.js("(() => { const b = document.querySelector('#i-buscar'); b.value = %s; b.dispatchEvent(new Event('input')); })(); 1" % json.dumps(texto))
    time.sleep(0.7)


def tecla(e, selector, key, **extra):
    opciones = json.dumps({"key": key, "bubbles": True, **extra})
    objetivo = "document.activeElement" if selector == ":focus" else "document.querySelector(%s)" % json.dumps(selector)   # «:focus» no vale en un Edge sin foco de ventana
    e.js("%s.dispatchEvent(new KeyboardEvent('keydown', %s)); 1" % (objetivo, opciones))


def fijar_orden(e, valor):
    e.js("document.querySelector('#i-orden').value = %s; document.querySelector('#i-orden').dispatchEvent(new Event('change')); 1" % json.dumps(valor))


def fnv(n):
    x = 2166136261
    for c in n.lower():
        x = ((x ^ ord(c)) * 16777619) & 0xFFFFFFFF
    return x % 8


# ------------------------------------------------------------ galería
def test_secciones_continuar_proyectos_e_inactivos(edge, pagina):
    abrir(edge, pagina)
    assert cabeceras(edge) == ["Continuar", "Proyectos · 3", "Inactivos · 1Sin sesión en 60 días"]
    # «Continuar»: el proyecto con la sesión más reciente (aún no hay recientes) como tarjeta ancha con «Empezar aquí»
    assert edge.js("document.querySelector('.gal-continuar .pcard.hero').dataset.tarjeta") == "Alfa Demo"
    assert edge.js("document.querySelector('.gal-continuar .hero-ir').textContent.trim()") == "Empezar aquí"
    assert edge.js("document.querySelector('#i-bandeja').textContent.includes('Reunión sin proyecto')")
    assert edge.js("!!document.querySelector('#i-anadir')")
    # el héroe no se repite en «Proyectos»; el inactivo va plegado
    assert edge.js("document.querySelectorAll('.item[data-clave=\"Alfa Demo\"]').length") == 1
    assert edge.js("document.querySelector('.gal-inactivos').open") is False
    assert edge.js("!!document.querySelector('.gal-inactivos .item[data-clave=\"Zeta Antigua\"]')")
    assert edge.js("document.querySelector('#i-cuenta').textContent") == "5 proyectos"


def test_tarjeta_muestra_descripcion_pendientes_hito_grafica_y_calidad(edge, pagina):
    abrir(edge, pagina)
    hero = ".pcard.hero"
    assert edge.js("document.querySelector('%s .pc-desc').textContent" % hero) == RESUMEN["Alfa Demo"]["descripcion"]
    assert edge.js("document.querySelector('%s .chip.pend').textContent" % hero) == "4 pendientes"
    assert "Seguimiento" in edge.js("document.querySelector('%s .pc-ult').textContent" % hero)
    assert edge.js("document.querySelectorAll('%s svg.spark rect').length" % hero) == 8
    assert edge.js("document.querySelector('%s .cal').dataset.nivel" % hero) == "3"
    comp = '.pcard[data-tarjeta="Compartida Demo"]'
    assert "Piloto · 20 ene" in edge.js("document.querySelector('%s .chip.hito').textContent" % comp)
    assert edge.js("[...document.querySelectorAll('%s .tipo')].map((x) => x.textContent.trim()).join('|')" % comp) == "Compartido|Con plan"
    beta = '.pcard[data-tarjeta="Beta Demo"]'
    assert "Sin descripción" in edge.js("document.querySelector('%s .pc-desc').textContent" % beta)
    assert "00. CONTEXTO (IA)" in edge.js("document.querySelector('%s .cal').title" % beta)       # el tooltip explica qué falta
    assert edge.js("document.querySelector('%s .cal-txt').textContent" % beta) == "Falta 00. CONTEXTO (IA)"
    assert edge.js("document.querySelector('%s .cal').dataset.nivel" % beta) == "1"


def test_color_estable_por_proyecto(edge, pagina):
    abrir(edge, pagina)
    for n in ("Alfa Demo", "Beta Demo", "Carpeta Ajena", "Compartida Demo"):
        assert edge.js("AP.proyectos.colorDe(%s)" % json.dumps(n)) == fnv(n)
        assert edge.js("document.querySelector('.pcard[data-tarjeta=\"%s\"]').classList.contains('cp%d')" % (n, fnv(n)))
    assert edge.js("AP.proyectos.colorDe('ALFA demo') === AP.proyectos.colorDe('Alfa Demo')")
    assert json.loads(edge.js("JSON.stringify(['Proyecto Ficticio Alfa', 'Portal de Reservas', 'Beta', 'x'].map(AP.proyectos.iniciales))")) == ["FA", "PR", "BE", "X"]
    # los ocho colores salen de tokens que cambian con el tema (claro y oscuro): --pc resuelve al valor del token
    r = json.loads(edge.js("""JSON.stringify(['acc-t', 't-decision', 't-pendiente', 't-riesgo', 't-contradiccion', 't-pregunta', 't-idea', 't-regla'].map((tok, i) => {
      const d = document.createElement('i'); d.className = 'cp' + i; document.body.append(d);
      const pc = getComputedStyle(d).getPropertyValue('--pc').trim().toLowerCase(), t = getComputedStyle(document.documentElement).getPropertyValue('--' + tok).trim().toLowerCase(); d.remove(); return [pc, t]; }))"""))
    assert all(pc and pc == t for pc, t in r) and len({pc for pc, _ in r}) == 8, r


def test_empezar_aqui_pasa_a_preparar_con_el_proyecto(edge, pagina):
    abrir(edge, pagina)
    clic(edge, ".hero-ir")
    time.sleep(0.4)
    assert edge.js("document.querySelector('#i-galeria').hidden") is True and edge.js("document.querySelector('#i-preparar').hidden") is False
    assert edge.js("document.querySelector('#i-proy-nombre').textContent") == "Alfa Demo"
    assert edge.js("document.querySelector('.proy-ficha .mono').textContent") == "AL"
    assert edge.js("document.querySelector('#i-cambiar').textContent") == "Cambiar proyecto"
    assert edge.js("AP.UI.sel") == "Alfa Demo"
    assert json.loads(edge.js("localStorage.getItem('apuntes_recientes')")) == ["Alfa Demo"]
    assert edge.js("document.querySelector('#i-empezar').disabled") is True and edge.js("!!document.querySelector('#i-tema')")
    clic(edge, "#i-cambiar")
    time.sleep(0.3)
    assert edge.js("document.querySelector('#i-galeria').hidden") is False and edge.js("document.querySelector('#i-preparar').hidden") is True


def test_reunion_sin_proyecto_va_directa_a_preparar(edge, pagina):
    abrir(edge, pagina)
    clic(edge, "#i-bandeja")
    time.sleep(0.3)
    assert edge.js("AP.UI.sel === null") and edge.js("document.querySelector('#i-preparar').hidden") is False
    assert "Reunión sin proyecto" in edge.js("document.querySelector('#i-proy-nombre').textContent")


def test_favoritos_y_recientes_se_recuerdan(edge, pagina):
    abrir(edge, pagina)
    clic(edge, '[data-empezar="Beta Demo"]')
    edge.js("AP.proyectos.etapa('galeria'); 1")
    clic(edge, '[data-fav="Carpeta Ajena"]')
    time.sleep(0.3)
    assert cabeceras(edge)[:3] == ["Continuar", "Favoritos · 1", "Proyectos · 2"]
    assert edge.js("document.querySelector('.gal-continuar .pcard').dataset.tarjeta") == "Beta Demo"       # el último usado sale en «Continuar»
    assert json.loads(edge.js("localStorage.getItem('apuntes_recientes')")) == ["Beta Demo"]
    assert json.loads(edge.js("localStorage.getItem('apuntes_favoritos')")) == ["Carpeta Ajena"]
    for n in ("Alfa Demo", "Beta Demo", "Carpeta Ajena", "Compartida Demo", "Zeta Antigua", "Alfa Demo", "Beta Demo"):   # máximo 5, sin repetidos, el último primero
        edge.js(f"AP.proyectos.recordar('{n}'); 1")
    assert edge.js("AP.proyectos.recientes().join(',')") == "Beta Demo,Alfa Demo,Zeta Antigua,Compartida Demo,Carpeta Ajena"


def test_sin_almacenamiento_no_rompe(edge, pagina):
    abrir(edge, pagina, "Object.defineProperty(window, 'localStorage', { get() { throw new Error('bloqueado'); } }); 1")
    assert edge.js("document.querySelectorAll('#i-lista .item').length") >= 4
    fijar_orden(edge, "nombre")                                                                        # cambiar orden o vista tampoco falla
    clic(edge, "#i-modo [data-modo=lista]")
    assert edge.js("document.querySelectorAll('.prow').length") >= 3


def test_buscador_resalta_y_estado_vacio(edge, pagina):
    abrir(edge, pagina)
    escribir_buscador(edge, "beta")
    assert edge.js("document.querySelector('.item[data-clave=\"Beta Demo\"] mark.pr-m').textContent") == "Beta"
    assert cabeceras(edge) == ["Resultados · 1"]
    escribir_buscador(edge, "zzz")
    assert "Ningún proyecto coincide con «zzz»" in edge.js("document.querySelector('#i-vacio').textContent")


def test_filtros_chips_con_recuento_y_ayuda(edge, pagina):
    abrir(edge, pagina)
    assert json.loads(edge.js("JSON.stringify([...document.querySelectorAll('#i-filtros .chipf')].map((b) => b.textContent))")) == \
        ["Todos5", "Favoritos0", "Con plan1", "Compartidos1", "Sin contexto2"]
    clic(edge, '[data-filtro="compartidos"]')
    assert cabeceras(edge) == ["Resultados · 1"] and edge.js("document.querySelector('[data-filtro=\"compartidos\"]').getAttribute('aria-pressed')") == "true"
    clic(edge, '[data-filtro="sin-contexto"]')
    assert json.loads(edge.js("JSON.stringify([...document.querySelectorAll('#i-lista .pcard .n')].map((x) => x.textContent))")) == ["Beta Demo", "Carpeta Ajena"]
    clic(edge, '[data-filtro="favoritos"]')
    assert "Marca la estrella" in edge.js("document.querySelector('#i-vacio').textContent")
    clic(edge, '[data-filtro="favoritos"]')                                                              # pulsar otra vez quita el filtro
    assert cabeceras(edge)[0] == "Continuar"


def test_orden_y_vista_se_recuerdan(edge, pagina):
    abrir(edge, pagina)
    fijar_orden(edge, "nombre")
    assert edge.js("localStorage.getItem('apuntes_orden')") == "nombre"
    assert json.loads(edge.js("JSON.stringify([...document.querySelectorAll('[data-seccion=proyectos] .pcard .n')].map((x) => x.textContent))")) == ["Beta Demo", "Carpeta Ajena", "Compartida Demo"]
    fijar_orden(edge, "pendientes")
    assert edge.js("document.querySelector('[data-seccion=proyectos] .pcard .n').textContent") == "Compartida Demo"      # 1 pendiente abierto: el único con alguno
    clic(edge, "#i-modo [data-modo=lista]")
    assert edge.js("localStorage.getItem('apuntes_vista')") == "lista" and edge.js("document.querySelectorAll('.pgrid.m-lista').length") >= 1
    assert edge.js("document.querySelectorAll('[data-seccion=proyectos] .pcard').length") == 0
    assert edge.js("document.querySelector('[data-seccion=proyectos] .prow-cab') !== null")
    # al volver a cargar la página las preferencias siguen ahí
    edge.js("localStorage.setItem('apuntes_orden', 'actividad'); 1")
    edge.abrir(pagina.as_uri())
    edge.js(STUB % (json.dumps(PROYECTOS), json.dumps(CTX), json.dumps(RESUMEN), json.dumps(PEND)) + "; 1")
    edge.js("window.__emitir(Object.assign({tipo: 'snapshot'}, %s)); AP.cargarProyectos(); 1" % json.dumps(foto(estado="inactivo", sesion=None, revision=None)))
    time.sleep(0.8)
    assert edge.js("AP.proyectos.estado().modo") == "lista" and edge.js("AP.proyectos.estado().orden") == "actividad"


def test_teclado_flechas_paleta_barra_e_intro(edge, pagina):
    abrir(edge, pagina)
    edge.js("document.body.dataset.vista = 'inicio'; document.activeElement.blur(); document.dispatchEvent(new KeyboardEvent('keydown', { key: '/', bubbles: true })); 1")
    assert edge.js("document.activeElement.id") == "i-buscar"
    # ola 2: Ctrl+K abre la paleta de comandos (que incluye los proyectos) y ya no enfoca el buscador; «/» sí
    edge.js("document.activeElement.blur(); document.dispatchEvent(new KeyboardEvent('keydown', { key: 'k', ctrlKey: true, bubbles: true })); 1")
    assert edge.js("document.querySelector('#paleta').open") is True and edge.js("document.activeElement.id") == "paleta-q"
    assert edge.js("AP.paleta.comandos().some((c) => c.titulo === 'Abrir el proyecto Beta Demo')") is True
    edge.js("document.querySelector('#paleta').dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true })); 1")
    assert edge.js("document.querySelector('#paleta').open") is False
    edge.js("document.activeElement.blur(); document.dispatchEvent(new KeyboardEvent('keydown', { key: '/', bubbles: true })); 1")
    assert edge.js("document.activeElement.id") == "i-buscar"
    tecla(edge, "#i-buscar", "ArrowDown")
    assert "item" in edge.js("document.activeElement.className")
    primero = edge.js("document.activeElement.dataset.clave")
    tecla(edge, ":focus", "ArrowRight")                                                             # a la derecha: la tarjeta siguiente
    assert edge.js("document.activeElement.dataset.clave") != primero
    tecla(edge, ":focus", "ArrowLeft")
    assert edge.js("document.activeElement.dataset.clave") == primero
    tecla(edge, ":focus", "ArrowUp")                                                                # arriba del todo: vuelve al buscador
    assert edge.js("document.activeElement.id") == "i-buscar"
    # E empieza la reunión con el proyecto enfocado
    edge.js("document.querySelector('.item[data-clave=\"Beta Demo\"]').focus(); 1")
    tecla(edge, ":focus", "e")
    time.sleep(0.3)
    assert edge.js("AP.UI.sel") == "Beta Demo" and edge.js("document.querySelector('#i-preparar').hidden") is False


def test_flechas_abajo_y_arriba_siguen_la_columna(edge, pagina):
    muchos = [{"nombre": f"Proyecto {i:02d}", "compartido": False, "extra": False, "tiene_contexto": True, "tiene_sesiones": False, "ruta": f"X:/r/{i}", "plan": None} for i in range(12)]
    abrir(edge, pagina, proyectos=muchos)
    edge.js("document.querySelector('.item[data-clave=\"Proyecto 01\"]').focus(); 1")
    xs = edge.js("Math.round(document.activeElement.getBoundingClientRect().left)")
    tecla(edge, ":focus", "ArrowDown")
    assert edge.js("Math.round(document.activeElement.getBoundingClientRect().left)") == xs
    abajo = edge.js("document.activeElement.dataset.clave")
    assert abajo != "Proyecto 01"
    tecla(edge, ":focus", "ArrowUp")
    assert edge.js("document.activeElement.dataset.clave") == "Proyecto 01"


# ------------------------------------------------------------ ficha del proyecto (panel)
def test_panel_abre_con_foco_contenido_y_se_cierra_con_esc(edge, pagina):
    abrir(edge, pagina)
    clic(edge, tarjeta("Alfa Demo"))
    time.sleep(0.8)
    assert edge.js("document.querySelector('#i-panel').hidden") is False and edge.js("document.querySelector('#i-panel').getAttribute('role')") == "dialog"
    assert edge.js("document.activeElement.id") == "pp-cerrar"
    assert edge.js("document.querySelector('#pp-titulo').textContent") == "Alfa Demo"
    assert edge.js("Math.round(document.querySelector('#i-panel').getBoundingClientRect().width / window.innerWidth * 100)") in range(45, 52)    # ≈ 45-50 % del ancho
    assert json.loads(edge.js("JSON.stringify([...document.querySelectorAll('#i-panel .vp-gtit')].map((x) => x.textContent))")) == \
        ["00. CONTEXTO (IA) · 1", "CLAUDE.md y raíz · 1", "Otros .md · 1"]
    assert "supera el tope de tamaño" in edge.js("document.querySelector('.vp-fila.fuera .vp-marca').textContent")
    assert edge.js("document.querySelector('#vp-resumen').textContent") == "3 ficheros · 1 fuera por los topes"
    assert edge.js("document.querySelector('#vp-sesiones .vp-n').textContent") == "Seguimiento"
    assert edge.js("document.querySelectorAll('#vp-pendientes .vp-fila').length") == 5 and edge.js("document.querySelector('#vp-pend-n').textContent") == "5 de 7"
    assert edge.js("document.querySelector('#pp-calidad .cal').dataset.nivel") == "3"
    assert edge.js("document.querySelector('#pp-sin-plan') !== null")
    assert edge.js("document.querySelector('#i-galeria').inert") is True                       # el fondo no recibe foco ni clics
    edge.js("document.querySelector('.vp-fila[data-id=\"1123456789abcdef\"] button').click(); 1")
    edge.js("document.querySelector('#vp-abrir-carpeta').click(); 1")
    time.sleep(0.3)
    llamadas = json.loads(edge.js("JSON.stringify(window.__llamadas)"))
    assert "POST /api/proyectos/Alfa%20Demo/contexto/1123456789abcdef/abrir" in llamadas and "POST /api/proyectos/Alfa%20Demo/abrir-carpeta" in llamadas
    assert edge.js("document.querySelector('#vp-quitar')") is None                             # una carpeta de la raíz no se «quita»
    tecla(edge, "#i-panel", "Escape")
    assert edge.js("document.querySelector('#i-panel').hidden") is True and edge.js("document.querySelector('#i-galeria').inert") is False
    assert edge.js("document.activeElement.dataset.clave") == "Alfa Demo"                      # el foco vuelve a la tarjeta


DOCS = {"total": 3, "en_nube": 1, "truncado": True, "ignorados": 0, "faltan": [{"clave": "tecnico", "titulo": "Técnico", "pista": "Diseño técnico, arquitectura o integraciones."}],
        "tipos": [{"clave": "oferta", "titulo": "Oferta y alcance", "esperado": True, "n": 2, "dias": 3, "mas": 0,
                   "ultimo": {"nombre": "Oferta v2.docx", "rel": "Oferta v2.docx", "mtime": time.time() - 3 * 86400},
                   "ficheros": [{"id": "aaaaaaaaaaaaaaa1", "nombre": "Oferta v2.docx", "rel": "Oferta v2.docx", "ext": ".docx", "carpeta": "", "tam": 10, "mtime": time.time() - 3 * 86400, "nube": True,
                                 "motivo": "nombre: «oferta o alcance»", "abrible": True},
                                {"id": "aaaaaaaaaaaaaaa2", "nombre": "Macro.docm", "rel": "Macro.docm", "ext": ".docm", "carpeta": "x", "tam": 10, "mtime": time.time() - 9 * 86400, "nube": False,
                                 "motivo": "nombre: «oferta o alcance»", "abrible": False}]},
                  {"clave": "tecnico", "titulo": "Técnico", "esperado": True, "n": 0, "dias": None, "ultimo": None, "ficheros": [], "mas": 0}]}


def test_panel_muestra_el_mapa_de_documentos(edge, pagina):
    abrir(edge, pagina, antes="window.__DOCS = %s; 1" % json.dumps(DOCS))
    clic(edge, tarjeta("Alfa Demo"))
    time.sleep(0.8)
    assert edge.js("document.querySelector('#vp-docs-resumen').textContent") == "3 documentos · 1 solo en la nube"
    assert edge.js("document.querySelector('#vp-docs-truncado') !== null")
    assert edge.js("document.querySelectorAll('#vp-docs details.dc-tipo').length") == 1            # solo los tipos con documentos
    assert "último: Oferta v2.docx · hace 3 días" in edge.js("document.querySelector('#vp-docs .dc-ult').textContent")
    assert edge.js("document.querySelector('#vp-docs .dc-fila .vp-marca').textContent") == "en la nube"
    assert "oferta o alcance" in edge.js("document.querySelector('#vp-docs .dc-fila .vp-n').title")
    assert edge.js("document.querySelectorAll('#vp-docs .dc-fila button').length") == 1             # el .docm no se puede abrir
    assert "Técnico" in edge.js("document.querySelector('#vp-docs-faltan').textContent") and "arquitectura" in edge.js("document.querySelector('#vp-docs-faltan').textContent")
    edge.js("document.querySelector('#vp-docs details').open = true; document.querySelector('#vp-docs .dc-fila button').click(); 1")
    time.sleep(0.3)
    assert "POST /api/proyectos/Alfa%20Demo/documentos/aaaaaaaaaaaaaaa1/abrir" in json.loads(edge.js("JSON.stringify(window.__llamadas)"))


def test_panel_documentos_vacio(edge, pagina):
    abrir(edge, pagina)
    clic(edge, tarjeta("Alfa Demo"))
    time.sleep(0.8)
    assert edge.js("document.querySelector('#vp-docs-vacio').textContent") == "Esta carpeta no tiene documentos."


def test_panel_atrapa_el_foco_con_tab(edge, pagina):
    abrir(edge, pagina)
    clic(edge, tarjeta("Alfa Demo"))
    time.sleep(0.6)
    edge.js("document.querySelector('#pp-empezar').focus(); 1")
    tecla(edge, "#pp-empezar", "Tab")                                                          # último control: Tab da la vuelta al primero
    assert edge.js("document.querySelector('#i-panel').contains(document.activeElement)") and edge.js("document.activeElement.id") != "pp-empezar"
    edge.js("document.querySelector('#i-panel .fav').focus(); 1")                                 # el primer control del panel
    tecla(edge, ":focus", "Tab", shiftKey=True)
    assert edge.js("document.activeElement.id") == "pp-empezar"


def test_panel_empezar_reunion_lleva_a_preparar_con_cabecera(edge, pagina):
    abrir(edge, pagina)
    clic(edge, tarjeta("Compartida Demo"))
    time.sleep(0.7)
    assert edge.js("document.querySelector('#pp-plan') !== null")                              # con plan: ficha/Gantt en el panel
    clic(edge, "#pp-empezar")
    time.sleep(0.4)
    assert edge.js("document.querySelector('#i-panel').hidden") is True and edge.js("document.querySelector('#i-preparar').hidden") is False
    assert edge.js("document.querySelector('#i-proy-nombre').textContent") == "Compartida Demo"
    assert edge.js("document.querySelector('.proy-ficha .mono').textContent") == "CO"
    assert "Calculadora ficticia" in edge.js("document.querySelector('.proy-desc').textContent")
    assert edge.js("AP.UI.sel") == "Compartida Demo"


def test_panel_de_proyecto_sin_contexto_explica_como_arreglarlo(edge, pagina):
    abrir(edge, pagina)
    clic(edge, tarjeta("Carpeta Ajena"))
    time.sleep(0.6)
    t = edge.js("document.querySelector('#pp-calidad').textContent")
    assert "No hay ningún .md" in t and "Cómo arreglarlo" in t and "00. CONTEXTO (IA)" in t and "CLAUDE.md" in t


def test_quitar_carpeta_pide_confirmacion(edge, pagina):
    abrir(edge, pagina)
    clic(edge, tarjeta("Carpeta Ajena"))
    time.sleep(0.5)
    clic(edge, "#vp-quitar")
    assert "No se borra nada" in edge.js("document.querySelector('#vp-confirma').textContent")
    assert not any(x.startswith("DELETE") for x in json.loads(edge.js("JSON.stringify(window.__llamadas)")))   # aún no se ha quitado nada
    clic(edge, "#vp-quitar-si")
    time.sleep(0.9)
    assert any(x.startswith("DELETE /api/proyectos/extra/Carpeta%20Ajena") for x in json.loads(edge.js("JSON.stringify(window.__llamadas)")))
    assert edge.js("!document.querySelector('.item[data-clave=\"Carpeta Ajena\"]')")
    assert edge.js("document.querySelector('#i-panel').hidden") is True


# ------------------------------------------------------------ estados vacíos
def test_sin_proyectos_explica_que_hacer(edge, pagina):
    abrir(edge, pagina, proyectos=[])
    t = edge.js("document.querySelector('#i-vacio').textContent")
    assert "Todavía no hay proyectos" in t and "Añadir carpeta de proyecto" in t and "00. CONTEXTO (IA)" in t
    assert edge.js("!!document.querySelector('#i-vacio #i-bandeja') && !!document.querySelector('#i-vacio #i-anadir')")


def test_anadir_carpeta_abre_el_formulario_de_siempre(edge, pagina):
    abrir(edge, pagina)
    clic(edge, "#i-anadir")
    assert edge.js("document.querySelector('#i-add-carpeta').open") is True
    assert edge.js("document.activeElement.name") == "nombre" and edge.js("!!document.querySelector('#f-add-carpeta [name=ruta]')")


def test_hace_relativo(edge, pagina):
    abrir(edge, pagina)
    r = edge.js("""JSON.stringify(['2026-11-07', '2026-11-06', '2026-11-04', '2026-10-20', '2026-08-01', '2024-01-01', 'x'].map((f) => AP.proyectos.hace(f, new Date(2026, 10, 7))))""")
    assert json.loads(r) == ["hoy", "ayer", "hace 3 días", "hace 2 semanas", "hace 3 meses", "hace 2 años", ""]


def test_nada_se_desborda_ni_se_corta_en_1440_y_1024(edge, pagina):
    larga = dict(PROYECTOS[0], nombre="Proyecto con un nombre larguísimo que no cabe en una tarjeta de trescientos píxeles de ancho", ruta="X:/r/larga")
    res = dict(RESUMEN)
    res[larga["nombre"]] = dict(RESUMEN["Alfa Demo"], descripcion="Una descripción muy larga " * 8)
    abrir(edge, pagina, proyectos=[larga, *PROYECTOS[1:]])
    edge.js("window.fetch = ((f) => async (u, o) => /resumen/.test(u) ? { ok: true, json: async () => ({ resumen: %s, parcial: false }) } : f(u, o))(window.fetch); AP.hooks.alVolverAInicio(); 1" % json.dumps(res))
    time.sleep(1.0)
    medida = """(() => { const vw = document.documentElement.clientWidth, malos = [];
      for (const el of document.querySelectorAll('#v-inicio .pcard *, #v-inicio .prow *, .gal-barra *')) {
        if (el.closest('[hidden]') || !el.getBoundingClientRect().width) continue;
        const r = el.getBoundingClientRect(), cs = getComputedStyle(el);
        if (r.right > vw + 1 || r.left < -1) malos.push(['fuera', el.className]);
        const corta = el.scrollWidth > el.clientWidth + 1 && el.clientWidth > 0 && cs.overflowX !== 'visible';
        if (corta && !(cs.textOverflow === 'ellipsis' || cs.display === '-webkit-box') && !el.classList.contains('sr')) malos.push(['sin elipsis', el.className]);
        if (cs.textOverflow === 'ellipsis' && el.scrollWidth > el.clientWidth + 1 && !(el.title || el.closest('[title]'))) malos.push(['sin title', el.className]);
      }
      return JSON.stringify({ malos, docScroll: document.documentElement.scrollWidth > vw }); })()"""
    for ancho in (1440, 1024):
        edge.cmd("Emulation.setDeviceMetricsOverride", width=ancho, height=900, deviceScaleFactor=1, mobile=False)
        time.sleep(0.4)
        for modo in ("rejilla", "lista"):
            clic(edge, f"#i-modo [data-modo={modo}]")
            time.sleep(0.3)
            r = json.loads(edge.js(medida))
            assert r["malos"] == [] and r["docScroll"] is False, (ancho, modo, r)
    edge.cmd("Emulation.setDeviceMetricsOverride", width=1440, height=900, deviceScaleFactor=1, mobile=False)


# ---------------------------------------------------------------- Agente Archivero (ola B)
def _tipos_todos(extra_otros=None):
    titulos = [("arranque", "Arranque (kick-off)"), ("oferta", "Oferta y alcance"), ("funcional", "Funcional"), ("tecnico", "Técnico"), ("datos", "Modelo de datos"),
               ("usuarios", "Usuarios y roles"), ("planificacion", "Planificación"), ("seguimiento", "Seguimiento y actas"), ("pruebas", "Pruebas y formación"),
               ("contexto", "Contexto para la IA"), ("otros", "Sin clasificar")]
    ahora = time.time()
    por = {"oferta": [{"id": "aaaaaaaaaaaaaaa1", "nombre": "Oferta v2.docx", "rel": "Oferta v2.docx", "ext": ".docx", "carpeta": "", "tam": 2048, "mtime": ahora - 3 * 86400, "nube": False,
                       "motivo": "nombre: «oferta o alcance»", "abrible": True, "corregido": False},
                      {"id": "aaaaaaaaaaaaaaa2", "nombre": "Macro.docm", "rel": "x/Macro.docm", "ext": ".docm", "carpeta": "x", "tam": 10, "mtime": ahora - 9 * 86400, "nube": False,
                       "motivo": "nombre: «oferta o alcance»", "abrible": False, "corregido": False}],
           "otros": [{"id": "aaaaaaaaaaaaaaa3", "nombre": "Cosas.docx", "rel": "Varios/Cosas.docx", "ext": ".docx", "carpeta": "Varios", "tam": 900, "mtime": ahora - 4 * 86400, "nube": False,
                      "motivo": "sin pista en el nombre ni en la carpeta", "abrible": True, "corregido": False}]}
    tipos = []
    for clave, titulo in titulos:
        fich = por.get(clave, [])
        tipos.append({"clave": clave, "titulo": titulo, "esperado": True, "n": len(fich), "dias": 3 if fich else None, "mas": 0,
                      "ultimo": {"nombre": fich[0]["nombre"], "rel": fich[0]["rel"], "mtime": fich[0]["mtime"]} if fich else None, "ficheros": fich})
    return {"total": 3, "en_nube": 0, "truncado": False, "ignorados": 0, "faltan": [], "tipos": tipos}


PLAN = {"leer": [{"nombre": "Oferta v2.docx", "rel": "Oferta v2.docx", "tipo": "oferta", "tipo_titulo": "Oferta y alcance", "tam": 2048, "mtime": time.time(), "asignado": 2000},
                 {"nombre": "Diseño funcional.md", "rel": "Funcional/Diseño funcional.md", "tipo": "funcional", "tipo_titulo": "Funcional", "tam": 900, "mtime": time.time(), "asignado": 900}],
        "omitidos": [{"nombre": "Macro.docm", "rel": "x/Macro.docm", "tipo": "oferta", "motivo": "formato sin lector en la app (.docm)"},
                     {"nombre": "Plan.xlsx", "rel": "Plan.xlsx", "tipo": "planificacion", "motivo": "solo está en la nube: no se abre para no descargarlo de OneDrive"}],
        "mas_omitidos": 0, "chars": 2900, "sin_clasificar": 1, "sin_clasificar_total": 1, "topes": {"max_documentos": 10, "por_documento": 6000, "total": 40000}, "modelo": "sonnet"}


def _faceta(clave, titulo, estado, sabemos=(), fuentes=(), falta=(), sin_leer=False):
    f = {"clave": clave, "titulo": titulo, "estado": estado, "sabemos": list(sabemos), "fuentes": [{"nombre": n, "rel": n} for n in fuentes], "falta": list(falta)}
    if sin_leer:
        f["sin_leer"] = True
    return f


RESULTADO = {"version": "archivero-v1", "proyecto": "Alfa Demo", "origen": "modelo", "generado": "2026-11-09T10:30:00", "modelo": "sonnet", "leidos": 2, "tokens": 12345,
             "desde_cache": False, "desactualizado": False, "aviso": "", "faltan": [], "no_leidos": [],
             "documentos": [{"nombre": "Oferta v2.docx", "rel": "Oferta v2.docx", "tipo": "oferta", "tipo_titulo": "Oferta y alcance", "resumen": "Alcance del portal de grupos y entregables."},
                            {"nombre": "Diseño funcional.md", "rel": "Funcional/Diseño funcional.md", "tipo": "funcional", "tipo_titulo": "Funcional", "resumen": "Procesos de cotización."}],
             "facetas": [_faceta("solucion", "La solución tal como está", "parcial", ["El portal pide cotizaciones de grupos"], ["Diseño funcional.md"], ["Casos de uso"]),
                         _faceta("datos", "Modelo de datos", "sin_documentar", falta=["Entidades y relaciones"]),
                         _faceta("usuarios", "Usuarios y roles", "sin_documentar", falta=["Perfiles y roles"]),
                         _faceta("alcance", "Alcance", "documentado", ["Catálogo y cotizador"], ["Oferta v2.docx"]),
                         _faceta("planificacion", "Planificación", "parcial", ["Tres sesiones"], ["Oferta v2.docx"], ["Fechas"])],
             "propuestas": [{"nombre": "Cosas.docx", "rel": "Varios/Cosas.docx", "carpeta": "Varios", "tipo": "tecnico", "tipo_titulo": "Técnico"}]}
PREVIA = {"huella": "aaaaaaaaaaaa", "fichero": "11-mapa-de-documentacion.md", "actualiza": False, "carpeta_nueva": False, "guardado": False, "compartido": False,
          "vista_previa": "# Mapa de documentación del proyecto\n\n## Cobertura por faceta\n\n### Alcance: documentado\n- Catálogo y cotizador\n"}


def _arch(edge, pagina, resultado=None, previa=None, extra=""):
    docs = _tipos_todos()
    antes = "window.__DOCS = %s; window.__ARCH = %s; window.__RES = %s; window.__PREVIA = %s; %s 1" % (
        json.dumps(docs), json.dumps({"plan": PLAN, "resultado": resultado}), json.dumps(resultado or RESULTADO), json.dumps(previa or PREVIA), extra)
    abrir(edge, pagina, antes=antes)
    clic(edge, tarjeta("Alfa Demo"))
    time.sleep(0.9)


def _texto(edge, selector):
    return edge.js("(document.querySelector(%s) || {}).textContent || ''" % json.dumps(selector))


def _llamadas(edge):
    return json.loads(edge.js("JSON.stringify(window.__llamadas)"))


def _cuerpos(edge):
    return json.loads(edge.js("JSON.stringify(window.__cuerpos || [])"))


def test_archivero_sin_resultado_ofrece_analizar_y_no_llama(edge, pagina):
    _arch(edge, pagina)
    assert _texto(edge, "#ar-abrir") == "Analizar con Claude"
    assert "gasta tokens" in _texto(edge, "#ar-intro") and "no se ejecuta solo" in _texto(edge, "#ar-intro")
    assert edge.js("document.querySelector('#ar-facetas')") is None
    assert not [x for x in _llamadas(edge) if x.startswith("POST")]                         # abrir la ficha no gasta nada
    clic(edge, "#ar-abrir")
    time.sleep(0.3)
    assert edge.js("document.querySelectorAll('#ar-plan-leer li').length") == 2
    assert edge.js("document.querySelectorAll('#ar-plan-omitidos li').length") == 2
    om = _texto(edge, "#ar-plan-omitidos")
    assert "formato sin lector en la app (.docm)" in om and "solo está en la nube" in om and "OneDrive" in om
    assert "Nada sale de tu equipo hasta que pulses" in _texto(edge, "#ar-plan-intro") and "1 fichero sin clasificar" in _texto(edge, "#ar-plan-sin")
    assert "gasta tokens" in _texto(edge, "#ar-plan-aviso") and "sonnet" in _texto(edge, "#ar-plan-aviso")
    assert edge.js("document.activeElement.id") == "ar-plan-analizar"                       # el foco pasa al botón del paso siguiente
    assert not [x for x in _llamadas(edge) if x.startswith("POST")]                         # ver el plan tampoco
    clic(edge, "#ar-plan-cancelar")
    time.sleep(0.3)
    assert edge.js("document.activeElement.id") == "ar-abrir" and edge.js("document.querySelector('#ar-plan-leer')") is None
    assert not [x for x in _llamadas(edge) if x.startswith("POST")]
    assert "!" not in _texto(edge, "#vp-arch")


def test_archivero_analiza_con_estado_ocupado_y_enseña_el_resultado(edge, pagina):
    _arch(edge, pagina, extra="window.__DEMORA = 900;")
    clic(edge, "#ar-abrir")
    clic(edge, "#ar-plan-analizar")
    time.sleep(0.35)
    assert edge.js("document.querySelector('#vp-arch').getAttribute('aria-busy')") == "true"
    assert "Claude está leyendo 2 documentos" in _texto(edge, "#ar-cargando") and edge.js("document.querySelector('#ar-cargando').getAttribute('role')") == "status"
    time.sleep(1.2)
    assert edge.js("document.querySelector('#vp-arch').getAttribute('aria-busy')") == "false"
    assert "POST /api/proyectos/Alfa%20Demo/archivero" in _llamadas(edge)
    assert edge.js("document.querySelectorAll('#ar-facetas > li').length") == 5
    por = json.loads(edge.js("JSON.stringify([...document.querySelectorAll('#ar-facetas > li')].map((x) => [x.dataset.faceta, x.dataset.estado]))"))
    assert por == [["solucion", "parcial"], ["datos", "sin_documentar"], ["usuarios", "sin_documentar"], ["alcance", "documentado"], ["planificacion", "parcial"]]
    sol = _texto(edge, '#ar-facetas [data-faceta="solucion"]')
    assert "La solución tal como está" in sol and "Parcial" in sol and "El portal pide cotizaciones de grupos" in sol and "Fuentes: Diseño funcional.md" in sol and "Casos de uso" in sol
    assert "Sin documentar" in _texto(edge, '#ar-facetas [data-faceta="datos"]') and "Entidades y relaciones" in _texto(edge, '#ar-facetas [data-faceta="datos"]')
    pie = _texto(edge, "#ar-pie-datos")
    assert "09/11/2026 10:30" in pie and "modelo sonnet" in pie and "2 documentos leídos" in pie and "12.345 tokens" in pie
    edge.js("document.querySelector('#ar-docs').open = true; 1")
    assert "Alcance del portal de grupos y entregables." in _texto(edge, "#ar-docs") and "Procesos de cotización." in _texto(edge, "#ar-docs")
    assert edge.js("document.querySelector('#ar-reanalizar') !== null && document.querySelector('#ar-guardar') !== null")
    assert _texto(edge, "#ar-guardar") == "Guardar en el contexto del proyecto" and _texto(edge, "#ar-reanalizar") == "Volver a analizar"
    assert edge.js("document.activeElement.id") == "ar-reanalizar"
    assert "!" not in _texto(edge, "#vp-arch")


def test_archivero_error_en_linea_y_reintento(edge, pagina):
    _arch(edge, pagina, extra="window.__ERR_ARCH = 'analizar';")
    clic(edge, "#ar-abrir")
    clic(edge, "#ar-plan-analizar")
    time.sleep(0.5)
    assert _texto(edge, "#ar-error") == "Claude no ha respondido." and edge.js("document.querySelector('#ar-error').getAttribute('role')") == "alert"
    assert edge.js("document.querySelector('#ar-plan-analizar') !== null")                  # se puede reintentar sin salir
    assert edge.js("document.querySelector('#vp-arch').getAttribute('aria-busy')") == "false"
    edge.js("window.__ERR_ARCH = ''; 1")
    clic(edge, "#ar-plan-analizar")
    time.sleep(0.5)
    assert edge.js("document.querySelectorAll('#ar-facetas > li').length") == 5 and edge.js("document.querySelector('#ar-error')") is None


def test_archivero_volver_a_analizar_pasa_por_el_plan(edge, pagina):
    _arch(edge, pagina, resultado=RESULTADO)
    assert edge.js("document.querySelectorAll('#ar-facetas > li').length") == 5 and edge.js("document.querySelector('#ar-abrir')") is None
    clic(edge, "#ar-reanalizar")
    time.sleep(0.3)
    assert edge.js("document.querySelectorAll('#ar-plan-leer li').length") == 2
    assert not [x for x in _llamadas(edge) if x.startswith("POST")]                         # volver a analizar también espera al «Analizar»
    clic(edge, "#ar-plan-analizar")
    time.sleep(0.5)
    assert "POST /api/proyectos/Alfa%20Demo/archivero?refrescar=1" in _llamadas(edge)


def test_archivero_resultado_local_y_desactualizado(edge, pagina):
    loc = dict(RESULTADO, origen="local", modelo=None, tokens=None, leidos=0, documentos=[], propuestas=[], desactualizado=True,
               aviso="No se ha podido analizar con Claude; te enseño la cobertura local, sin leer los documentos.",
               facetas=[_faceta("solucion", "La solución tal como está", "parcial", ["Hay 1 documento de tipo «Funcional», sin leer."], ["Diseño funcional.md"], sin_leer=True),
                        _faceta("datos", "Modelo de datos", "sin_documentar", falta=["No hay documentos de los tipos que suelen cubrir «Modelo de datos»."], sin_leer=True)])
    _arch(edge, pagina, resultado=loc)
    assert _texto(edge, "#ar-origen") == "Cobertura local, sin leer" and "cobertura local" in _texto(edge, "#ar-aviso")
    assert "Hay documentos, sin leer" in _texto(edge, '#ar-facetas [data-faceta="solucion"]') and "Sin documentos" in _texto(edge, '#ar-facetas [data-faceta="datos"]')
    assert "han cambiado desde este análisis" in _texto(edge, "#ar-desactualizado")
    assert edge.js("document.querySelector('#ar-guardar')") is None                         # lo local no se guarda en el contexto
    assert "documentos leídos" not in _texto(edge, "#ar-pie-datos")


def test_archivero_aplicar_propuesta_y_cambiar_tipo_a_mano(edge, pagina):
    _arch(edge, pagina, resultado=RESULTADO)
    assert edge.js("document.querySelectorAll('#ar-propuestas li').length") == 1
    assert "Cosas.docx" in _texto(edge, "#ar-propuestas") and "→ Técnico" in _texto(edge, "#ar-propuestas")
    assert edge.js("document.querySelector('#ar-propuestas button').getAttribute('aria-label')") == "Aplicar el tipo Técnico a Varios/Cosas.docx"
    clic(edge, "#ar-propuestas button")
    time.sleep(0.6)
    assert "PUT /api/proyectos/Alfa%20Demo/documentos/aaaaaaaaaaaaaaa3/tipo" in _llamadas(edge)
    assert 'PUT {"tipo":"tecnico"}' in _cuerpos(edge)
    assert _llamadas(edge).count("GET /api/proyectos/Alfa%20Demo/archivero") >= 2 and _llamadas(edge).count("GET /api/proyectos/Alfa%20Demo/documentos") >= 2   # se vuelve a leer lo nuevo
    # una forma de cambiar el tipo accesible con teclado: un <select> nativo con su nombre accesible en cada fila
    edge.js("document.querySelector('#vp-docs details[data-tipo=oferta]').open = true; document.querySelector('#vp-docs details[data-tipo=otros]').open = true; 1")
    assert edge.js("document.querySelectorAll('#vp-docs .dc-fila select.dc-tipo-sel').length") == 3
    sel = "#ar-tipo-aaaaaaaaaaaaaaa1"
    assert edge.js("document.querySelector(%s).getAttribute('aria-label')" % json.dumps(sel)) == "Tipo de documento de Oferta v2.docx"
    assert edge.js("document.querySelector(%s).tabIndex" % json.dumps(sel)) == 0 and edge.js("document.querySelector(%s).value" % json.dumps(sel)) == "oferta"
    opciones = json.loads(edge.js("JSON.stringify([...document.querySelector(%s).options].map((o) => o.textContent))" % json.dumps(sel)))
    assert opciones[:3] == ["Arranque (kick-off)", "Oferta y alcance", "Funcional"] and len(opciones) == 11 and "Quitar la corrección (volver a las reglas)" not in opciones
    edge.js("(() => { const s = document.querySelector(%s); s.value = 'datos'; s.dispatchEvent(new Event('change')); })(); 1" % json.dumps(sel))
    time.sleep(0.5)
    assert 'PUT {"tipo":"datos"}' in _cuerpos(edge)


def test_archivero_tipo_corregido_se_marca_y_se_puede_quitar(edge, pagina):
    docs = _tipos_todos()
    docs["tipos"][1]["ficheros"][0].update({"corregido": True, "motivo": "corregido a mano"})
    abrir(edge, pagina, antes="window.__DOCS = %s; window.__ARCH = {plan: %s, resultado: null}; 1" % (json.dumps(docs), json.dumps(PLAN)))
    clic(edge, tarjeta("Alfa Demo"))
    time.sleep(0.9)
    edge.js("document.querySelector('#vp-docs details[data-tipo=oferta]').open = true; 1")
    fila = "#vp-docs .dc-fila[data-id=aaaaaaaaaaaaaaa1]"
    assert "tipo corregido" in _texto(edge, fila + " .ar-corregido")
    assert "Quitar la corrección (volver a las reglas)" in json.loads(edge.js("JSON.stringify([...document.querySelector('#ar-tipo-aaaaaaaaaaaaaaa1').options].map((o) => o.textContent))"))
    edge.js("(() => { const s = document.querySelector('#ar-tipo-aaaaaaaaaaaaaaa1'); s.value = ''; s.dispatchEvent(new Event('change')); })(); 1")
    time.sleep(0.5)
    assert 'PUT {"tipo":null}' in _cuerpos(edge)


def test_archivero_fila_que_no_se_abre_dice_por_que(edge, pagina):
    _arch(edge, pagina)
    edge.js("document.querySelector('#vp-docs details[data-tipo=oferta]').open = true; 1")
    marca = edge.js("[...document.querySelectorAll('#vp-docs .dc-fila[data-id=aaaaaaaaaaaaaaa2] .vp-marca')].map((x) => x.textContent + '|' + x.title)")
    assert len(marca) == 1 and marca[0].startswith("no se abre desde aquí|") and "macros" in marca[0]
    assert edge.js("document.querySelector('#vp-docs .dc-fila[data-id=aaaaaaaaaaaaaaa1] button').textContent") == "Abrir"
    assert edge.js("document.querySelector('#vp-docs .dc-fila[data-id=aaaaaaaaaaaaaaa2] button')") is None


def test_archivero_guardar_vista_previa_cancelar_y_confirmar(edge, pagina):
    _arch(edge, pagina, resultado=RESULTADO)
    clic(edge, "#ar-guardar")
    time.sleep(0.4)
    assert _cuerpos(edge) == ['POST {"confirmar":false}']                                   # solo la vista previa: nada se escribe todavía
    assert "Mapa de documentación del proyecto" in _texto(edge, "#ar-previa .ar-previa-md")
    assert "Se guardará como «11-mapa-de-documentacion.md» en «00. CONTEXTO (IA)»" in _texto(edge, "#ar-previa")
    assert edge.js("document.activeElement.id") == "ar-guardar-si" and edge.js("document.querySelector('#ar-previa .ar-previa-md').tabIndex") == 0
    clic(edge, "#ar-guardar-no")
    time.sleep(0.3)
    assert edge.js("document.querySelector('#ar-previa')") is None and _cuerpos(edge) == ['POST {"confirmar":false}']
    clic(edge, "#ar-guardar")
    time.sleep(0.4)
    clic(edge, "#ar-guardar-si")
    time.sleep(0.5)
    assert _cuerpos(edge)[-1] == 'POST {"confirmar":true,"huella":"aaaaaaaaaaaa"}'   # la confirmación lleva la huella de la vista previa que se enseñó
    assert "Guardado como «11-mapa-de-documentacion.md»" in _texto(edge, "#ar-guardado") and edge.js("document.querySelector('#ar-previa')") is None


def test_archivero_guardar_avisa_si_reescribe_y_muestra_el_error(edge, pagina):
    _arch(edge, pagina, resultado=RESULTADO, previa=dict(PREVIA, actualiza=True, carpeta_nueva=True))
    clic(edge, "#ar-guardar")
    time.sleep(0.4)
    t = _texto(edge, "#ar-previa")
    assert "Ya existe «11-mapa-de-documentacion.md»" in t and "se reescribirá" in t and "único caso" in t and "no existe: se creará" in t
    assert _texto(edge, "#ar-guardar-si") == "Guardar y reescribir"
    edge.js("window.__ERR_ARCH = 'guardar'; 1")
    clic(edge, "#ar-guardar-si")
    time.sleep(0.5)
    assert _texto(edge, "#ar-error") == "Fallo simulado al guardar." and edge.js("document.querySelector('#ar-previa') !== null")   # la vista previa se queda para reintentar


def test_archivero_guardar_con_409_enseña_la_vista_previa_nueva_y_no_guarda(edge, pagina):
    nueva = dict(PREVIA, huella="bbbbbbbbbbbb", vista_previa="# Mapa de documentación del proyecto\n\n### Alcance: parcial\n- Esto es lo que ha cambiado\n")
    _arch(edge, pagina, resultado=RESULTADO, extra="window.__PREVIA_NUEVA = %s;" % json.dumps(nueva))
    clic(edge, "#ar-guardar")
    time.sleep(0.4)
    assert "Catálogo y cotizador" in _texto(edge, "#ar-previa .ar-previa-md")
    edge.js("window.__ERR_ARCH = 'conflicto'; 1")
    clic(edge, "#ar-guardar-si")
    time.sleep(0.5)
    assert _cuerpos(edge)[-1] == 'POST {"confirmar":true,"huella":"aaaaaaaaaaaa"}'
    assert _texto(edge, "#ar-error") == "El resultado ha cambiado; revisa la vista previa antes de guardar."
    assert "Esto es lo que ha cambiado" in _texto(edge, "#ar-previa .ar-previa-md") and edge.js("document.querySelector('#ar-guardado')") is None   # la nueva vista previa, sin guardar
    assert edge.js("document.activeElement.id") == "ar-guardar-si"
    clic(edge, "#ar-guardar-si")                                                            # tras revisarla, se confirma con la huella nueva
    time.sleep(0.5)
    assert _cuerpos(edge)[-1] == 'POST {"confirmar":true,"huella":"bbbbbbbbbbbb"}'
    assert "Guardado como «11-mapa-de-documentacion.md»" in _texto(edge, "#ar-guardado") and edge.js("document.querySelector('#ar-error')") is None
