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
    if (/\\/plan\\/proponer$/.test(u)) {
      if (m === 'POST') {
        (window.__cuerpos = window.__cuerpos || []).push(m + ' ' + o.body);
        if (window.__DEMORA_PLAN) await new Promise((ok) => setTimeout(ok, window.__DEMORA_PLAN));
        if (window.__ERR_PROP) return r({ detail: 'Claude no ha respondido.' }, false);
        return r(window.__PROPUESTA);
      }
      return r({ plan: window.__PREVIA_PLAN });
    }
    if (/\\/plan$/.test(u)) {
      if (m === 'PUT') {
        const b = JSON.parse(o.body); (window.__cuerpos = window.__cuerpos || []).push(m + ' ' + o.body);
        if (window.__PUT === '409') return r({ detail: 'El plan ha cambiado fuera de la app desde que lo abriste. Recarga para ver la versión actual; no se ha guardado nada.' }, false, 409);
        if (window.__PUT === '422') return r({ detail: 'La sesión necesita un nombre.', errores: window.__ERRORES }, false, 422);
        let n = 0; const ids = {};
        const ses = b.sesiones.map((s) => { const id = /^nueva-/.test(s.id) ? 'S' + (++n) : s.id; ids[s.id] = id; return Object.assign({}, s, { id, participantes: '' }); });
        ses.forEach((s) => { s.depende_de = s.depende_de.map((d) => ids[d] || d); });
        window.__V = (window.__V || 1) + 1;
        window.__PLAN = Object.assign({}, window.__PLAN, { plan: { sesiones: ses, con_gantt: false, con_ficha: false }, version: 'v' + window.__V });
        return r(window.__PLAN);
      }
      window.__gets = (window.__gets || 0) + 1;
      return r(window.__PLAN || { proyecto: 'x', plan: null, version: 'nuevo', descartadas: 0, ficheros_contexto: [], limites: {} });
    }
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


# ---------------------------------------------------------------- Editor del plan de sesiones y «Proponer plan» (ola C)
FICHEROS_CTX = ["01-ficha-del-proyecto.md", "02-alcance.md", "12-guion-sesion-alcance.md"]
LIMITES_PLAN = {"max_sesiones": 20, "max_objetivos": 12, "max_checks": 12, "max_dependencias": 6, "max_nombre": 120, "max_fecha": 80, "max_objetivo": 200, "max_check": 140}


def _s(id, nombre, **kw):
    return {"id": id, "nombre": nombre, "fecha": "", "fecha_iso": "", "hora": "", "participantes": "", "objetivos": [], "checks": [], "fichero_prioritario": "", "depende_de": [], **kw}


def _plan_get(sesiones=None, version="v1", descartadas=0, gantt=False):
    plan = {"sesiones": sesiones, "con_gantt": gantt, "con_ficha": False} if sesiones is not None else None
    return {"proyecto": "Compartida Demo", "plan": plan, "version": version if sesiones is not None else "nuevo", "descartadas": descartadas,
            "ficheros_contexto": FICHEROS_CTX, "limites": LIMITES_PLAN}


PLAN_BASE = [_s("S1", "Revisión del alcance", fecha_iso="2026-11-10", fecha="martes, 10 de noviembre de 2026", hora="10:30", objetivos=["Confirmar el alcance", "Acordar los entregables"],
                checks=["Leer la oferta"], fichero_prioritario="02-alcance.md"),
             _s("S2", "Modelo de datos", objetivos=["Validar las entidades"], depende_de=["S1"]),
             _s("S3", "Piloto", objetivos=["Acordar el piloto"], depende_de=["S2"])]
PREVIA_PLAN = {"modelo": "sonnet", "chars": 4200, "topes": {"max_documentos": 6, "por_documento": 6000, "total": 30000}, "mas_omitidos": 0,
               "leer": [{"nombre": "Kickoff.md", "rel": "Kickoff.md", "tipo": "arranque", "tipo_titulo": "Arranque (kick-off)", "tam": 1800, "mtime": time.time(), "asignado": 1800},
                        {"nombre": "Oferta alcance.md", "rel": "Oferta alcance.md", "tipo": "oferta", "tipo_titulo": "Oferta y alcance", "tam": 2400, "mtime": time.time(), "asignado": 2400}],
               "omitidos": [{"nombre": "Plan.xls", "rel": "Plan.xls", "tipo": "planificacion", "motivo": "formato sin lector en la app (.xls)"}]}
PROPUESTA = {"version": "plan-propuesto-v1", "proyecto": "Compartida Demo", "origen": "modelo", "modelo": "sonnet", "leidos": 2, "tokens": 9876, "descartadas": 0, "no_leidos": [], "aviso": "", "aviso_detalle": "",
             "sesiones": [{"nombre": "Alcance propuesto", "objetivos": ["Cerrar el alcance", "Fijar entregables"], "checks": ["Revisar la oferta"], "fecha_iso": "2026-11-12", "hora": "09:00", "depende_de": [],
                           "fuente": {"nombre": "Kickoff.md", "rel": "Kickoff.md"}},
                          {"nombre": "Datos propuestos", "objetivos": ["Validar el modelo"], "checks": [], "fecha_iso": "", "hora": "", "depende_de": [1], "fuente": {"nombre": "Oferta alcance.md", "rel": "Oferta alcance.md"}},
                          {"nombre": "Piloto propuesto", "objetivos": ["Definir el piloto"], "checks": [], "fecha_iso": "", "hora": "", "depende_de": [1, 2], "fuente": None}]}
COMP = "Compartida%20Demo"


def _plan_ui(edge, pagina, plan=None, extra=""):
    """Ficha de «Compartida Demo» (la lista dice que tiene plan) o, sin `plan`, de «Alfa Demo» (sin plan), con el doble de la API del plan (`plan`: lo que devuelve el GET)."""
    antes = "window.__PLAN = %s; window.__PREVIA_PLAN = %s; window.__PROPUESTA = %s; window.confirm = () => { window.__confirm = true; return true; }; %s 1" % (
        json.dumps(plan if plan is not None else _plan_get()), json.dumps(PREVIA_PLAN), json.dumps(PROPUESTA), extra)
    abrir(edge, pagina, antes=antes)
    clic(edge, tarjeta("Alfa Demo" if plan is None else "Compartida Demo"))
    time.sleep(0.9)


def _poner(edge, selector, valor, evento="input"):
    edge.js("(() => { const e = document.querySelector(%s); e.value = %s; e.dispatchEvent(new Event(%s, { bubbles: true })); })(); 1" % (json.dumps(selector), json.dumps(valor), json.dumps(evento)))


def _nombres_sesiones(edge):
    return json.loads(edge.js("JSON.stringify([...document.querySelectorAll('#pe-lista > .pe-ses .pe-nom')].map((x) => x.textContent))"))


def _put(edge):
    puts = [c for c in _cuerpos(edge) if c.startswith("PUT ")]
    return json.loads(puts[-1][4:]) if puts else None


def test_plan_sin_plan_ofrece_crear_y_proponer_y_no_gasta_nada(edge, pagina):
    _plan_ui(edge, pagina)
    assert edge.js("document.querySelector('#pp-sin-plan') !== null")
    assert _texto(edge, "#pe-crear") == "Crear plan" and _texto(edge, "#pe-proponer") == "Proponer plan con Claude"
    assert "gasta tokens" in _texto(edge, "#pe-aviso-tokens") and "no se ejecuta solo" in _texto(edge, "#pe-aviso-tokens")
    assert not [x for x in _llamadas(edge) if x.startswith(("POST", "PUT"))]                       # abrir la ficha no gasta ni escribe nada
    assert edge.js("document.querySelector('#pe-lista')") is None


def test_plan_crear_anadir_reordenar_y_guardar(edge, pagina):
    _plan_ui(edge, pagina)
    clic(edge, "#pe-crear")
    time.sleep(0.2)
    assert edge.js("document.querySelectorAll('#pe-lista > .pe-ses').length") == 1 and _texto(edge, "#pe-estado") == "Cambios sin guardar"
    assert edge.js("document.activeElement.id") == "pe-nombre-nueva-1" and edge.js("document.querySelector('#pe-guardar').disabled") is False
    _poner(edge, "#pe-nombre-nueva-1", "Alcance")
    clic(edge, "#pe-objetivos-mas-nueva-1")
    _poner(edge, "#pe-objetivos-nueva-1-0", "Cerrar el alcance")
    clic(edge, "#pe-checks-mas-nueva-1")
    _poner(edge, "#pe-checks-nueva-1-0", "Leer la oferta")
    _poner(edge, "#pe-fecha-nueva-1", "2026-11-10", "change")
    _poner(edge, "#pe-hora-nueva-1", "10:30", "change")
    _poner(edge, "#pe-fichero-nueva-1", "02-alcance.md", "change")
    clic(edge, "#pe-anadir")
    time.sleep(0.2)
    assert edge.js("document.activeElement.id") == "pe-nombre-nueva-2"
    _poner(edge, "#pe-nombre-nueva-2", "Datos")
    edge.js("document.querySelector('#pe-deps-nueva-2 [data-dep=\"nueva-1\"]').click(); 1")
    clic(edge, "#pe-sub-nueva-2")                                                                  # reordenar con el botón (teclado)
    time.sleep(0.2)
    assert _nombres_sesiones(edge) == ["Datos", "Alcance"]
    assert edge.js("document.activeElement.id") == "pe-baj-nueva-2"                                 # el foco se queda en el botón que se usó (el de subir ya no vale)
    clic(edge, "#pe-baj-nueva-2")
    assert _nombres_sesiones(edge) == ["Alcance", "Datos"]
    clic(edge, "#pe-guardar")
    time.sleep(0.6)
    put = _put(edge)
    assert put["version"] == "nuevo" and [s["id"] for s in put["sesiones"]] == ["nueva-1", "nueva-2"]
    a, d = put["sesiones"]
    assert (a["nombre"], a["fecha_iso"], a["hora"], a["fichero_prioritario"], a["objetivos"], a["checks"]) == ("Alcance", "2026-11-10", "10:30", "02-alcance.md", ["Cerrar el alcance"], ["Leer la oferta"])
    assert "10 de noviembre de 2026" in a["fecha"] and d["depende_de"] == ["nueva-1"]
    assert edge.js("document.querySelector('#pe-lista')") is None and _texto(edge, "#pe-estado") == "Plan guardado."     # vuelve a la vista de lectura con el plan ya guardado
    assert _texto(edge, "#pe-editar") == "Editar plan"
    assert any(x.startswith("GET /api/proyectos?q=") for x in _llamadas(edge)[-10:])                 # la lista (y con ella el Gantt de la ficha) se vuelve a leer


def test_plan_error_de_validacion_sale_junto_al_campo_y_se_limpia_al_editar(edge, pagina):
    errores = [{"indice": 0, "campo": "nombre", "mensaje": "La sesión necesita un nombre."}, {"indice": 1, "campo": "hora", "mensaje": "La hora no es válida (usa HH:MM, por ejemplo 10:30)."}]
    _plan_ui(edge, pagina, plan=_plan_get([_s("S1", "Uno"), _s("S2", "Dos")]), extra="window.__PUT = '422'; window.__ERRORES = %s;" % json.dumps(errores))
    clic(edge, "#pe-editar")
    _poner(edge, "#pe-nombre-S1", "Uno bis")
    clic(edge, "#pe-guardar")
    time.sleep(0.5)
    assert _texto(edge, '[data-err="0:nombre"]') == "La sesión necesita un nombre." and _texto(edge, '[data-err="1:hora"]').startswith("La hora no es válida")
    assert edge.js("document.querySelector('#pe-nombre-S1').getAttribute('aria-invalid')") == "true"
    assert edge.js("document.querySelector('#pe-nombre-S1').getAttribute('aria-describedby')") == "pe-err-S1-nombre" and edge.js("!!document.getElementById('pe-err-S1-nombre')")
    assert edge.js("document.querySelector('#pe-cuerpo-S2').hidden") is False                        # la sesión con error se despliega
    assert edge.js("document.activeElement.id") == "pe-nombre-S1"                                    # y el foco va al primer campo con error
    assert "2 errores" in _texto(edge, "#pe-estado") and edge.js("document.querySelector('#pe-guardar').disabled") is False
    _poner(edge, "#pe-nombre-S1", "Uno ter")
    assert edge.js("document.querySelector('[data-err=\"0:nombre\"]')") is None and "1 error" in _texto(edge, "#pe-estado")
    assert edge.js("document.querySelector('#pe-nombre-S1').hasAttribute('aria-invalid')") is False


def test_plan_409_se_explica_no_pierde_la_pantalla_y_permite_recargar(edge, pagina):
    _plan_ui(edge, pagina, plan=_plan_get([_s("S1", "Uno")]), extra="window.__PUT = '409';")
    clic(edge, "#pe-editar")
    _poner(edge, "#pe-nombre-S1", "Uno cambiado")
    clic(edge, "#pe-guardar")
    time.sleep(0.5)
    assert "ha cambiado fuera de la app" in _texto(edge, "#pe-conflicto") and "Recarga" in _texto(edge, "#pe-conflicto") and "No se ha guardado nada" in _texto(edge, "#pe-conflicto")
    assert edge.js("document.querySelector('#pe-nombre-S1').value") == "Uno cambiado" and edge.js("document.activeElement.id") == "pe-recargar"
    n = edge.js("window.__gets")
    clic(edge, "#pe-recargar")
    time.sleep(0.6)
    assert edge.js("window.__gets") == n + 1 and edge.js("document.querySelector('#pe-lista')") is None and _texto(edge, "#pe-editar") == "Editar plan"


def test_plan_quitar_sesion_pide_confirmacion_en_linea_sin_confirm_del_navegador(edge, pagina):
    _plan_ui(edge, pagina, plan=_plan_get(PLAN_BASE))
    clic(edge, "#pe-editar")
    assert _nombres_sesiones(edge) == ["Revisión del alcance", "Modelo de datos", "Piloto"]
    clic(edge, "#pe-del-S2")
    time.sleep(0.2)
    assert edge.js("document.querySelector('.pe-ses[data-id=\"S2\"] [role=alertdialog]') !== null") and "¿Quitar «Modelo de datos»?" in _texto(edge, ".pe-ses[data-id=\"S2\"] .pe-confirma")
    assert edge.js("document.activeElement.id") == "pe-quitar-si-S2" and len(_nombres_sesiones(edge)) == 3
    clic(edge, "#pe-quitar-no-S2")
    assert len(_nombres_sesiones(edge)) == 3 and edge.js("document.activeElement.id") == "pe-del-S2"
    clic(edge, "#pe-del-S2")
    clic(edge, "#pe-quitar-si-S2")
    time.sleep(0.2)
    assert _nombres_sesiones(edge) == ["Revisión del alcance", "Piloto"] and edge.js("window.__confirm") is None       # nunca confirm() del navegador
    assert _texto(edge, "#pe-estado") == "Cambios sin guardar"
    clic(edge, "#pe-guardar")
    time.sleep(0.5)
    put = _put(edge)
    assert [s["id"] for s in put["sesiones"]] == ["S1", "S3"] and put["sesiones"][1]["depende_de"] == [] and put["version"] == "v1"      # quien dependía de la quitada deja de depender


def test_plan_avisa_al_salir_de_la_ficha_con_cambios_sin_guardar(edge, pagina):
    _plan_ui(edge, pagina, plan=_plan_get([_s("S1", "Uno")]))
    clic(edge, "#pe-editar")
    tecla(edge, "#i-panel", "Escape")                                                              # sin cambios: cierra
    assert edge.js("document.querySelector('#i-panel').hidden") is True
    clic(edge, tarjeta("Compartida Demo"))
    time.sleep(0.6)
    clic(edge, "#pe-editar")
    _poner(edge, "#pe-nombre-S1", "Uno cambiado")
    tecla(edge, "#i-panel", "Escape")
    time.sleep(0.2)
    assert edge.js("document.querySelector('#i-panel').hidden") is False and "Hay cambios sin guardar en el plan" in _texto(edge, "#pe-salir")
    assert edge.js("document.activeElement.id") == "pe-salir-no"
    clic(edge, "#pe-salir-no")
    assert edge.js("document.querySelector('#i-panel').hidden") is False and edge.js("document.querySelector('#pe-nombre-S1').value") == "Uno cambiado"
    clic(edge, "#pp-cerrar")
    clic(edge, "#pe-salir-si")
    time.sleep(0.2)
    assert edge.js("document.querySelector('#i-panel').hidden") is True
    clic(edge, tarjeta("Compartida Demo"))                                                          # al volver a abrir, el plan sigue como estaba guardado
    time.sleep(0.6)
    assert _texto(edge, "#pe-editar") == "Editar plan" and edge.js("document.querySelector('#pe-lista')") is None
    clic(edge, "#pe-editar")
    _poner(edge, "#pe-nombre-S1", "Otra vez")
    clic(edge, "#pp-empezar")                                                                       # «Empezar reunión» también pregunta
    assert edge.js("document.querySelector('#i-panel').hidden") is False and edge.js("!!document.querySelector('#pe-salir')")
    assert not [x for x in _llamadas(edge) if x.startswith("PUT")]


def test_plan_descartar_pregunta_si_hay_cambios(edge, pagina):
    _plan_ui(edge, pagina, plan=_plan_get([_s("S1", "Uno")]))
    clic(edge, "#pe-editar")
    clic(edge, "#pe-descartar")                                                                     # sin cambios: vuelve directamente
    assert edge.js("document.querySelector('#pe-lista')") is None
    clic(edge, "#pe-editar")
    _poner(edge, "#pe-nombre-S1", "Cambiado")
    assert _texto(edge, "#pe-estado") == "Cambios sin guardar"
    clic(edge, "#pe-descartar")
    assert "¿Descartar los cambios sin guardar?" in _texto(edge, "#pe-descartar-aviso") and edge.js("document.querySelector('#pe-lista') !== null")
    clic(edge, "#pe-descartar-si")
    clic(edge, "#pe-editar")
    assert edge.js("document.querySelector('#pe-nombre-S1').value") == "Uno" and _texto(edge, "#pe-estado") == "Sin cambios"


def test_plan_objetivos_y_checks_se_anaden_quitan_y_reordenan_con_botones(edge, pagina):
    _plan_ui(edge, pagina, plan=_plan_get([_s("S1", "Uno", objetivos=["a", "b", "c"])]))
    clic(edge, "#pe-editar")
    valores = "JSON.stringify([...document.querySelectorAll('#pe-lista input[id^=\"pe-objetivos-S1-\"]')].map((x) => x.value))"
    assert json.loads(edge.js(valores)) == ["a", "b", "c"]
    clic(edge, "#pe-objetivos-baj-S1-0")
    assert json.loads(edge.js(valores)) == ["b", "a", "c"] and edge.js("document.activeElement.id") == "pe-objetivos-baj-S1-1"
    clic(edge, "#pe-objetivos-sub-S1-2")
    assert json.loads(edge.js(valores)) == ["b", "c", "a"]
    clic(edge, "#pe-objetivos-del-S1-0")
    assert json.loads(edge.js(valores)) == ["c", "a"] and edge.js("document.activeElement.id") == "pe-objetivos-S1-0"
    tecla(edge, "#pe-objetivos-S1-0", "Enter")                                                      # Intro añade un objetivo debajo y se queda escribiendo
    assert json.loads(edge.js(valores)) == ["c", "", "a"] and edge.js("document.activeElement.id") == "pe-objetivos-S1-1"
    assert edge.js("document.querySelector('#pe-objetivos-sub-S1-0').disabled") is True and edge.js("document.querySelector('#pe-objetivos-baj-S1-2').disabled") is True


def test_plan_dependencias_solo_con_las_demas_y_fichero_prioritario_de_la_carpeta(edge, pagina):
    _plan_ui(edge, pagina, plan=_plan_get([_s("S1", "Uno", fichero_prioritario="09-que-ya-no-esta.md"), _s("S2", "Dos")]))
    clic(edge, "#pe-editar")
    clic(edge, "#pe-toggle-S1")
    assert edge.js("document.querySelector('#pe-toggle-S1').getAttribute('aria-expanded')") == "true" and edge.js("document.querySelector('#pe-cuerpo-S1').hidden") is False
    assert json.loads(edge.js("JSON.stringify([...document.querySelectorAll('#pe-deps-S1 [data-dep]')].map((x) => x.dataset.dep))")) == ["S2"]       # no se ofrece a sí misma
    opciones = json.loads(edge.js("JSON.stringify([...document.querySelectorAll('#pe-fichero-S1 option')].map((x) => x.textContent))"))
    assert opciones[:4] == ["Ninguno", *FICHEROS_CTX] and opciones[4] == "09-que-ya-no-esta.md (no está en la carpeta)"
    assert edge.js("document.querySelector('#pe-fichero-S1').value") == "09-que-ya-no-esta.md"


def test_plan_proponer_enseña_lo_que_lee_y_la_propuesta_entra_como_borrador(edge, pagina):
    _plan_ui(edge, pagina)
    clic(edge, "#pe-proponer")
    time.sleep(0.4)
    assert edge.js("document.querySelectorAll('#pe-prop-leer li').length") == 2 and edge.js("document.querySelectorAll('#pe-prop-omitidos li').length") == 1
    assert "UNA llamada" in _texto(edge, "#pe-prop-aviso") and "gasta tokens" in _texto(edge, "#pe-prop-aviso") and "no se guarda nada hasta que pulses «Guardar»" in _texto(edge, "#pe-prop-aviso")
    assert not [x for x in _llamadas(edge) if x.startswith("POST")]                                  # ver la lista no gasta nada
    clic(edge, "#pe-prop-lanzar")
    time.sleep(0.5)
    assert len([x for x in _llamadas(edge) if x.startswith("POST")]) == 1
    assert edge.js("document.querySelectorAll('#pe-props .pe-propuesta').length") == 3 and "borrador" in _texto(edge, "#pe-prop")
    assert "Sale de: Kickoff.md" in _texto(edge, '.pe-propuesta[data-j="0"]') and "Sin documento de origen indicado" in _texto(edge, '.pe-propuesta[data-j="2"]')
    assert edge.js("document.querySelector('#pe-lista')") is None                                    # todavía no hay editor ni nada que guardar
    clic(edge, "#pe-prop-add-1")                                                                      # una sola: su dependencia (la 1) no está añadida y se omite
    time.sleep(0.2)
    assert _nombres_sesiones(edge) == ["Datos propuestos"] and _texto(edge, "#pe-estado") == "Cambios sin guardar"
    assert edge.js("document.querySelector('#pe-prop-add-1').disabled") is True and _texto(edge, "#pe-prop-add-1") == "Añadida"
    clic(edge, "#pe-prop-todas")
    time.sleep(0.2)
    assert _nombres_sesiones(edge) == ["Datos propuestos", "Alcance propuesto", "Piloto propuesto"]
    assert not [x for x in _llamadas(edge) if x.startswith("PUT")]                                   # nada se guarda sin pulsar «Guardar»
    clic(edge, "#pe-guardar")
    time.sleep(0.5)
    put = _put(edge)
    por = {s["nombre"]: s for s in put["sesiones"]}
    assert set(por["Piloto propuesto"]["depende_de"]) == {por["Alcance propuesto"]["id"], por["Datos propuestos"]["id"]} and por["Datos propuestos"]["depende_de"] == []
    assert por["Alcance propuesto"]["fecha_iso"] == "2026-11-12" and por["Alcance propuesto"]["hora"] == "09:00" and put["version"] == "nuevo"


def test_plan_proponer_con_un_plan_existente_anade_sin_pisar(edge, pagina):
    _plan_ui(edge, pagina, plan=_plan_get([_s("S1", "Ya existente", objetivos=["Algo"])]))
    clic(edge, "#pe-proponer")
    time.sleep(0.3)
    clic(edge, "#pe-prop-lanzar")
    time.sleep(0.5)
    assert '"nombres":[]' in _cuerpos(edge)[-1]                                                      # fuera del editor viajan los guardados por el servidor
    clic(edge, "#pe-prop-add-0")
    time.sleep(0.2)
    assert _nombres_sesiones(edge) == ["Ya existente", "Alcance propuesto"] and edge.js("document.querySelector('#pe-nombre-S1').value") == "Ya existente"
    clic(edge, "#pe-prop-cerrar")
    clic(edge, "#pe-proponer")                                                                       # desde el editor: los nombres del editor (también los no guardados) viajan para no repetirlos
    time.sleep(0.3)
    clic(edge, "#pe-prop-lanzar")
    time.sleep(0.5)
    assert '"nombres":["Ya existente","Alcance propuesto"]' in _cuerpos(edge)[-1]


def test_plan_proponer_con_error_muestra_el_mensaje_y_no_inventa_nada(edge, pagina):
    _plan_ui(edge, pagina, extra="window.__ERR_PROP = true;")
    clic(edge, "#pe-proponer")
    time.sleep(0.3)
    clic(edge, "#pe-prop-lanzar")
    time.sleep(0.5)
    assert _texto(edge, "#pe-prop-error") == "Claude no ha respondido." and edge.js("document.querySelector('#pe-prop-error').getAttribute('role')") == "alert"
    assert edge.js("document.querySelector('#pe-props')") is None and edge.js("document.querySelector('#pe-lista')") is None
    clic(edge, "#pe-prop-cancelar")
    assert edge.js("document.querySelector('#pe-prop')") is None and edge.js("document.activeElement.id") == "pe-proponer"


def test_plan_proponer_sin_licencia_enseña_el_aviso_de_la_respuesta(edge, pagina):
    sin = dict(PROPUESTA, origen="ninguno", sesiones=[], modelo=None, leidos=0, tokens=None, aviso="No se ha podido proponer un plan con Claude; no hay propuesta. Puedes crear las sesiones a mano.",
               aviso_detalle="Claude no tiene la sesión iniciada.")
    _plan_ui(edge, pagina)
    edge.js("window.__PROPUESTA = %s; 1" % json.dumps(sin))
    clic(edge, "#pe-proponer")
    time.sleep(0.3)
    clic(edge, "#pe-prop-lanzar")
    time.sleep(0.5)
    assert "no hay propuesta" in _texto(edge, "#pe-prop-aviso-r") and "sesión iniciada" in _texto(edge, "#pe-prop-aviso-r") and edge.js("document.querySelector('#pe-props')") is None


def test_plan_conserva_el_gantt_de_solo_lectura_y_avisa_de_lo_que_no_se_edita(edge, pagina):
    _plan_ui(edge, pagina, plan=_plan_get([_s("S1", "Uno")], gantt=True, descartadas=2))
    assert edge.js("document.querySelector('#pp-plan') !== null") and _texto(edge, "#pe-editar") == "Editar plan"      # con plan: el Gantt de siempre más «Editar plan»
    clic(edge, "#pe-editar")
    assert edge.js("document.querySelector('#pp-plan')") is None
    assert "El Gantt y la ficha del plan no se editan aquí" in _texto(edge, "#pe-conserva") and "2 sesiones que la app no puede leer" in _texto(edge, "#pe-descartadas")
    assert "al guardar se conservan en el fichero tal como están" in _texto(edge, "#pe-descartadas")


def test_plan_editor_accesible_por_teclado_sin_exclamaciones_y_sin_desbordes(edge, pagina):
    larga = "Una sesión con un nombre larguísimo que no cabe en una línea del panel lateral " * 2
    _plan_ui(edge, pagina, plan=_plan_get([_s("S1", larga[:120], objetivos=["Un objetivo muy largo " * 9], checks=["Un check largo " * 8], depende_de=[]), _s("S2", "Dos"), _s("S3", "Tres")]))
    clic(edge, "#pe-editar")
    clic(edge, "#pe-toggle-S1")
    nombres = """JSON.stringify([...document.querySelectorAll('#pe button, #pe input, #pe select')].filter((e) => e.offsetParent !== null && !(e.labels && e.labels.length) && !e.closest('label')
      && !e.getAttribute('aria-label') && !(e.textContent || '').trim()).map((e) => e.id || e.className))"""
    assert json.loads(edge.js(nombres)) == []                                                          # todo control tiene nombre accesible
    assert edge.js("[...document.querySelectorAll('#pe button')].every((b) => b.type === 'button')")
    assert edge.js("[...document.querySelectorAll('#pe .pe-toggle')].every((b) => b.hasAttribute('aria-expanded') && b.getAttribute('aria-controls'))")
    assert edge.js("document.querySelector('#pe-lista').tagName") == "OL" and edge.js("document.querySelector('#pe-deps-S1').tagName") == "FIELDSET"
    assert "!" not in edge.js("document.querySelector('#pe').textContent") and "¡" not in edge.js("document.querySelector('#pe').textContent")
    # foco visible: un botón y un campo enfocados dibujan contorno
    for previo, esperado in (("pe-toggle-S1", "pe-baj-S1"), ("pe-baj-S1", "pe-del-S1"), ("pe-del-S1", "pe-nombre-S1")):   # se llega con el teclado: un foco puesto por script solo casa con :focus-visible si el navegador cree que se usa el teclado
        edge.js("document.getElementById(%s).focus(); 1" % json.dumps(previo))
        _tab(edge)
        f = _foco(edge)
        assert f["id"] == esperado and f["visible"] is True and f["estilo"] != "none" and f["ancho"] >= 1, (previo, f)
    medida = """(() => { const p = document.querySelector('#i-panel').getBoundingClientRect(), malos = [];
      for (const el of document.querySelectorAll('#pe *')) { if (el.closest('[hidden]') || !el.getBoundingClientRect().width) continue; const r = el.getBoundingClientRect();
        if (r.right > p.right + 1 || r.left < p.left - 1) malos.push(el.id || el.className); }
      const c = document.querySelector('.pp-cuerpo'); return JSON.stringify({ malos, scroll: c.scrollWidth > c.clientWidth + 1 }); })()"""
    for ancho in (1440, 1024):
        edge.cmd("Emulation.setDeviceMetricsOverride", width=ancho, height=900, deviceScaleFactor=1, mobile=False)
        time.sleep(0.4)
        r = json.loads(edge.js(medida))
        assert r["malos"] == [] and r["scroll"] is False, (ancho, r)
    edge.cmd("Emulation.setDeviceMetricsOverride", width=1440, height=900, deviceScaleFactor=1, mobile=False)


# ---------------------------------------------------------------- arreglos tras la revisión de la ola C
def _plan_con_avisos(sesiones, descartadas=0, ilegibles=()):
    d = _plan_get(sesiones, descartadas=descartadas)
    d["ilegibles"], d["ilegibles_total"] = list(ilegibles)[:5], len(ilegibles)
    return d


AVISO_DESCARTADAS = "El fichero del plan tiene %s que la app no puede leer (sin id, con id repetido o por encima del máximo). %s"


def test_plan_2_aviso_de_sesiones_ilegibles_al_crear_y_al_editar_con_el_texto_exacto(edge, pagina):
    plural = AVISO_DESCARTADAS % ("3 sesiones", "No se enseñan aquí; al guardar se conservan en el fichero tal como están.")
    singular = AVISO_DESCARTADAS % ("1 sesión", "No se enseña aquí; al guardar se conserva en el fichero tal como está.")
    _plan_ui(edge, pagina, extra="window.__PLAN = %s;" % json.dumps(_plan_con_avisos(None, descartadas=3)))   # sin sesión válida: «Crear plan», y el aviso ya está
    assert _texto(edge, "#pe-descartadas") == plural and _texto(edge, "#pe-crear") == "Crear plan"
    clic(edge, "#pe-crear")                                                                    # y sigue al crear
    assert _texto(edge, "#pe-descartadas") == plural
    _plan_ui(edge, pagina, plan=_plan_con_avisos([_s("S1", "Uno")], descartadas=1))
    assert edge.js("document.querySelector('#pe-descartadas')") is None                       # con plan, el aviso sale al editar
    clic(edge, "#pe-editar")
    assert _texto(edge, "#pe-descartadas") == singular


def test_plan_6_ficheros_ilegibles_se_avisan_solo_cuando_no_hay_plan(edge, pagina):
    _plan_ui(edge, pagina, extra="window.__PLAN = %s;" % json.dumps(_plan_con_avisos(None, ilegibles=["roto.json", "otro (v2).json"])))
    assert _texto(edge, "#pe-ilegibles") == ("En la carpeta de planes hay 2 ficheros que no se pueden leer (roto.json, otro (v2).json). "
                                              "Si alguno es el plan de este proyecto, arréglalo antes de crear uno nuevo.")
    assert edge.js("document.querySelector('#pe-crear') !== null")
    _plan_ui(edge, pagina, extra="window.__PLAN = %s;" % json.dumps(_plan_con_avisos(None, ilegibles=["roto.json"])))
    assert "1 fichero que no se puede leer (roto.json)" in _texto(edge, "#pe-ilegibles")
    _plan_ui(edge, pagina, plan=_plan_con_avisos([_s("S1", "Uno")], ilegibles=["roto.json"]))      # con plan no se enseña
    assert edge.js("document.querySelector('#pe-ilegibles')") is None
    clic(edge, "#pe-editar")
    assert edge.js("document.querySelector('#pe-ilegibles')") is None


def test_plan_7_una_propuesta_quitada_no_deja_dependencias_fantasma(edge, pagina):
    _plan_ui(edge, pagina)
    clic(edge, "#pe-proponer")
    time.sleep(0.4)
    clic(edge, "#pe-prop-lanzar")
    time.sleep(0.5)
    clic(edge, "#pe-prop-add-0")
    time.sleep(0.2)
    assert _nombres_sesiones(edge) == ["Alcance propuesto"]
    clic(edge, "#pe-del-nueva-1")
    clic(edge, "#pe-quitar-si-nueva-1")
    assert _nombres_sesiones(edge) == [] and edge.js("document.querySelector('#pe-prop-add-0').disabled") is False and _texto(edge, "#pe-prop-add-0") == "Añadir"   # vuelve a poder añadirse
    clic(edge, "#pe-prop-add-1")                                                              # depende de la 1.ª, que ya no está en el editor
    time.sleep(0.2)
    assert _nombres_sesiones(edge) == ["Datos propuestos"]
    clic(edge, "#pe-guardar")
    time.sleep(0.5)
    put = _put(edge)
    assert [s["nombre"] for s in put["sesiones"]] == ["Datos propuestos"] and put["sesiones"][0]["depende_de"] == []


def test_plan_8_la_barra_de_acciones_llega_al_borde_del_area_de_scroll(edge, pagina):
    sesiones = [_s("S%d" % i, "Sesión número %d" % i, objetivos=["Un objetivo de la sesión %d" % i] * 4, checks=["Un check"] * 3) for i in range(1, 9)]
    _plan_ui(edge, pagina, plan=_plan_get(sesiones))
    clic(edge, "#pe-editar")
    for i in (1, 2, 3):
        clic(edge, "#pe-toggle-S%d" % i)
    medir = """(() => { const c = document.querySelector('.pp-cuerpo'), p = document.querySelector('.pe-pie').getBoundingClientRect(), b = c.getBoundingClientRect();
      const ult = [...document.querySelectorAll('#pe-lista input, #pe-lista select, #pe-lista button')].filter((e) => e.offsetParent !== null).pop().getBoundingClientRect();
      return JSON.stringify({ desborda: c.scrollHeight > c.clientHeight + 40, pie_bottom: p.bottom, cuerpo_bottom: b.bottom, ult_bottom: ult.bottom, pie_top: p.top, scroll: c.scrollTop }); })()"""
    for posicion in ("0", "document.querySelector('.pp-cuerpo').scrollHeight", "document.querySelector('.pp-cuerpo').scrollHeight / 2"):
        edge.js("document.querySelector('.pp-cuerpo').scrollTop = %s; 1" % posicion)
        time.sleep(0.2)
        m = json.loads(edge.js(medir))
        assert m["desborda"], m
        assert m["pie_bottom"] >= m["cuerpo_bottom"] - 1, (posicion, m)                          # nada del texto de la sesión asoma por debajo de la barra
    edge.js("document.querySelector('.pp-cuerpo').scrollTop = document.querySelector('.pp-cuerpo').scrollHeight; 1")
    time.sleep(0.2)
    m = json.loads(edge.js(medir))
    assert m["ult_bottom"] <= m["pie_top"] + 1, m                                                  # al llegar al final, el último campo queda por encima de la barra


def test_plan_9_salir_de_inicio_con_cambios_sin_guardar_no_cierra_la_ficha(edge, pagina):
    _plan_ui(edge, pagina, plan=_plan_get([_s("S1", "Uno")]))
    clic(edge, "#pe-editar")
    _poner(edge, "#pe-nombre-S1", "Uno cambiado")
    edge.js("AP.hooks.alVolverAInicio(); 1")                                                       # lo que hace la app al volver a «inicio» desde otra vista
    time.sleep(0.3)
    assert edge.js("document.querySelector('#i-panel').hidden") is False
    assert edge.js("document.querySelector('#pe-nombre-S1').value") == "Uno cambiado" and _texto(edge, "#pe-estado") == "Cambios sin guardar"
    assert edge.js("AP.planEditor.sucio()") is True
    clic(edge, "#pe-descartar")                                                                     # sin cambios, volver a inicio sí cierra la ficha como siempre
    clic(edge, "#pe-descartar-si")
    edge.js("AP.hooks.alVolverAInicio(); 1")
    time.sleep(0.3)
    assert edge.js("document.querySelector('#i-panel').hidden") is True


def _tab(edge):
    for tipo in ("keyDown", "keyUp"):
        edge.cmd("Input.dispatchKeyEvent", type=tipo, key="Tab", code="Tab", windowsVirtualKeyCode=9)


def _foco(edge):
    return json.loads(edge.js("""(() => { const e = document.activeElement, c = getComputedStyle(e);
      return JSON.stringify({ id: e.id, visible: e.matches(':focus-visible'), estilo: c.outlineStyle, ancho: parseFloat(c.outlineWidth) }); })()"""))


def test_plan_11_los_botones_del_editor_se_alcanzan_con_tab_y_dibujan_contorno(edge, pagina):
    _plan_ui(edge, pagina, plan=_plan_get([_s("S1", "Uno"), _s("S2", "Dos"), _s("S3", "Tres")]))
    clic(edge, "#pe-editar")
    # (a) los botones del editor no se quedan sin contorno por ninguna regla propia: tras un Tab de teclado, :focus-visible y contorno de 2 px
    for previo, esperado in (("pe-toggle-S1", "pe-baj-S1"), ("pe-baj-S1", "pe-del-S1"), ("pe-toggle-S2", "pe-sub-S2"), ("pe-sub-S2", "pe-baj-S2"), ("pe-baj-S2", "pe-del-S2")):
        edge.js("document.getElementById(%s).focus(); 1" % json.dumps(previo))
        _tab(edge)
        f = _foco(edge)
        assert f["id"] == esperado, (previo, f)                                                    # se llega con el teclado
        assert f["visible"] is True and f["estilo"] != "none" and f["ancho"] >= 1, f                 # y dibuja contorno
    # (b) ninguna regla le quita el contorno a un control visible del editor cuando recibe el foco con el teclado
    sin = edge.js("""(() => { const sin = [...document.querySelectorAll('#pe button, #pe input, #pe select')].filter((e) => e.offsetParent !== null && !e.disabled).filter((e) => {
      e.focus(); const c = getComputedStyle(e); return document.activeElement !== e || c.outlineStyle === 'none' || parseFloat(c.outlineWidth) < 1; }); return sin.map((e) => e.id); })()""")
    assert sin == [], sin
