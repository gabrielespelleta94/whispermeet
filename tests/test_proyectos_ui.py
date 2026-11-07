"""Pantalla de inicio: secciones, favoritos, recientes, buscador, teclado y vista previa (web/proyectos.js) en un Edge sin cabeza con datos ficticios."""
from __future__ import annotations

import json
import socket
import time

import pytest

from _visual_harness import Edge, foto, pagina_html

PROYECTOS = [
    {"nombre": "Alfa Demo", "compartido": False, "extra": False, "tiene_contexto": True, "tiene_sesiones": True, "ruta": "X:/r/Alfa Demo", "plan": None,
     "n_sesiones": 3, "ultima_sesion": "2026-11-04", "n_md": 9},
    {"nombre": "Beta Demo", "compartido": False, "extra": False, "tiene_contexto": False, "tiene_sesiones": False, "ruta": "X:/r/Beta Demo", "plan": None, "n_md": 2},
    {"nombre": "Carpeta Ajena", "compartido": False, "extra": True, "tiene_contexto": False, "tiene_sesiones": False, "ruta": "X:/o/Ajena", "plan": None},
    {"nombre": "Compartida Demo", "compartido": True, "extra": True, "tiene_contexto": True, "tiene_sesiones": False, "ruta": "X:/c/Comp", "plan": None},
]
CTX = {"proyecto": "Alfa Demo", "solo_lectura": False, "truncado": False, "total": 3, "fuera": 1, "limites": {},
       "grupos": [{"clave": "ctx", "titulo": "00. CONTEXTO (IA)", "ficheros": [{"id": "0123456789abcdef", "nombre": "02-alcance.md", "rel": "00. CONTEXTO (IA)/02-alcance.md", "tam": 2048, "dejado": "", "en_digest": True}]},
                  {"clave": "raiz", "titulo": "CLAUDE.md y raíz", "ficheros": [{"id": "1123456789abcdef", "nombre": "CLAUDE.md", "rel": "CLAUDE.md", "tam": 300, "dejado": "", "en_digest": True}]},
                  {"clave": "otros", "titulo": "Otros .md", "ficheros": [{"id": "2123456789abcdef", "nombre": "docs/grande.md", "rel": "docs/grande.md", "tam": 900000, "dejado": "tamaño", "en_digest": False}]}]}
STUB = """(() => {
  window.__llamadas = [];
  const P = %s, CTX = %s;
  window.fetch = async (u, o) => {
    const m = (o && o.method) || 'GET'; window.__llamadas.push(m + ' ' + u);
    const r = (d, ok = true) => ({ ok, json: async () => d });
    if (/api\\/proyectos\\?/.test(u)) { const q = decodeURIComponent(u.split('q=')[1] || '').toLowerCase(); return r({ raiz: 'X:/r', proyectos: P.filter((p) => p.nombre.toLowerCase().includes(q)) }); }
    if (/\\/contexto$/.test(u)) return r(CTX);
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


def abrir(e, pagina, antes=""):
    e.abrir(pagina.as_uri())
    e.js("localStorage.clear(); 1")
    e.abrir(pagina.as_uri())
    e.js(STUB % (json.dumps(PROYECTOS), json.dumps(CTX)) + "; 1")
    if antes:
        e.js(antes)
    e.js("window.__emitir(Object.assign({tipo: 'snapshot'}, %s)); 1" % json.dumps(foto(estado="inactivo", sesion=None, revision=None)))
    e.js("AP.cargarProyectos(); 1")
    time.sleep(0.6)


def cabeceras(e):
    return json.loads(e.js("JSON.stringify([...document.querySelectorAll('#i-lista .lista-cab')].map((x) => x.textContent))"))


def test_secciones_con_recuento_y_etiquetas(edge, pagina):
    abrir(edge, pagina)
    assert cabeceras(edge) == ["Proyectos · 2", "Carpetas añadidas · 1", "Compartidas · 1"]
    tag = edge.js("document.querySelector('.item[data-clave=\"Alfa Demo\"] .tag').textContent")
    assert tag.startswith("contexto · 3 sesiones · última ")
    assert edge.js("!!document.querySelector('.item[data-clave=\"Compartida Demo\"] svg.ic-compartida')")
    assert edge.js("document.querySelector('.item.bandeja') !== null")


def test_favoritos_y_recientes_se_recuerdan(edge, pagina):
    abrir(edge, pagina)
    edge.js("document.querySelector('.item[data-clave=\"Beta Demo\"]').click(); 1")
    edge.js("document.querySelector('[data-fav=\"Carpeta Ajena\"]').click(); 1")
    time.sleep(0.3)
    assert cabeceras(edge)[:2] == ["Recientes · 1", "Favoritos · 1"]
    assert json.loads(edge.js("localStorage.getItem('apuntes_recientes')")) == ["Beta Demo"]
    assert json.loads(edge.js("localStorage.getItem('apuntes_favoritos')")) == ["Carpeta Ajena"]
    for n in ("Alfa Demo", "Beta Demo", "Carpeta Ajena", "Compartida Demo", "Alfa Demo", "Beta Demo"):   # máximo 5, sin repetidos, el último primero
        edge.js(f"AP.proyectos.recordar('{n}'); 1")
    assert edge.js("AP.proyectos.recientes().join(',')") == "Beta Demo,Alfa Demo,Compartida Demo,Carpeta Ajena"


def test_sin_almacenamiento_no_rompe(edge, pagina):
    abrir(edge, pagina, "Object.defineProperty(window, 'localStorage', { get() { throw new Error('bloqueado'); } }); 1")
    assert edge.js("document.querySelectorAll('#i-lista .item').length") >= 4


def test_buscador_resalta_y_estado_vacio(edge, pagina):
    abrir(edge, pagina)
    edge.js("(() => { const b = document.querySelector('#i-buscar'); b.value = 'beta'; b.dispatchEvent(new Event('input')); })(); 1")
    time.sleep(0.7)
    assert edge.js("document.querySelector('.item[data-clave=\"Beta Demo\"] mark.pr-m').textContent") == "Beta"
    assert len(cabeceras(edge)) == 1
    edge.js("(() => { const b = document.querySelector('#i-buscar'); b.value = 'zzz'; b.dispatchEvent(new Event('input')); })(); 1")
    time.sleep(0.7)
    assert "Ningún proyecto coincide con «zzz»" in edge.js("document.querySelector('#i-vacio').textContent")


def test_teclado_flechas_ctrl_k_y_barra(edge, pagina):
    abrir(edge, pagina)
    edge.js("document.body.dataset.vista = 'inicio'; document.activeElement.blur(); document.dispatchEvent(new KeyboardEvent('keydown', { key: '/', bubbles: true })); 1")
    assert edge.js("document.activeElement.id") == "i-buscar"
    edge.js("document.activeElement.blur(); document.dispatchEvent(new KeyboardEvent('keydown', { key: 'k', ctrlKey: true, bubbles: true })); 1")
    assert edge.js("document.activeElement.id") == "i-buscar"
    edge.js("document.querySelector('#i-buscar').dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true })); 1")
    assert "item" in edge.js("document.activeElement.className")
    edge.js("document.activeElement.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true })); 1")
    assert edge.js("document.activeElement.dataset.clave") == "Alfa Demo"


def test_vista_previa_ficheros_marcas_sesiones_y_abrir(edge, pagina):
    abrir(edge, pagina)
    edge.js("document.querySelector('.item[data-clave=\"Alfa Demo\"]').click(); 1")
    time.sleep(0.6)
    assert edge.js("document.querySelector('#i-preview').hidden") is False
    assert json.loads(edge.js("JSON.stringify([...document.querySelectorAll('#i-preview .vp-gtit')].map((x) => x.textContent))")) == \
        ["00. CONTEXTO (IA) · 1", "CLAUDE.md y raíz · 1", "Otros .md · 1"]
    assert "supera el tope de tamaño" in edge.js("document.querySelector('.vp-fila.fuera .vp-marca').textContent")
    assert edge.js("document.querySelector('#vp-resumen').textContent") == "3 ficheros · 1 fuera por los topes"
    edge.js("document.querySelector('.vp-fila[data-id=\"1123456789abcdef\"] button').click(); 1")
    edge.js("document.querySelector('#vp-abrir-carpeta').click(); 1")
    time.sleep(0.3)
    llamadas = json.loads(edge.js("JSON.stringify(window.__llamadas)"))
    assert "POST /api/proyectos/Alfa%20Demo/contexto/1123456789abcdef/abrir" in llamadas and "POST /api/proyectos/Alfa%20Demo/abrir-carpeta" in llamadas
    assert edge.js("document.querySelector('#vp-sesiones .vp-n').textContent") == "Seguimiento"
    assert edge.js("document.querySelector('#vp-quitar')") is None                      # una carpeta de la raíz no se «quita»


def test_quitar_carpeta_pide_confirmacion(edge, pagina):
    abrir(edge, pagina)
    edge.js("document.querySelector('.item[data-clave=\"Carpeta Ajena\"]').click(); 1")
    time.sleep(0.5)
    edge.js("document.querySelector('#vp-quitar').click(); 1")
    assert "No se borra nada" in edge.js("document.querySelector('#vp-confirma').textContent")
    assert not any(x.startswith("DELETE") for x in json.loads(edge.js("JSON.stringify(window.__llamadas)")))   # aún no se ha quitado nada
    edge.js("document.querySelector('#vp-quitar-si').click(); 1")
    time.sleep(0.8)
    assert any(x.startswith("DELETE /api/proyectos/extra/Carpeta%20Ajena") for x in json.loads(edge.js("JSON.stringify(window.__llamadas)")))
    assert edge.js("!document.querySelector('.item[data-clave=\"Carpeta Ajena\"]')")
    assert edge.js("document.querySelector('#i-preview').hidden") is True


def test_hace_relativo(edge, pagina):
    abrir(edge, pagina)
    r = edge.js("""JSON.stringify(['2026-11-07', '2026-11-06', '2026-11-04', '2026-10-20', '2026-08-01', '2024-01-01', 'x'].map((f) => AP.proyectos.hace(f, new Date(2026, 10, 7))))""")
    assert json.loads(r) == ["hoy", "ayer", "hace 3 días", "hace 2 semanas", "hace 3 meses", "hace 2 años", ""]
