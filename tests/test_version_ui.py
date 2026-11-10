"""Aviso «hay una versión nueva en disco» (web/version.js): sale en la portada solo si `/api/info` dice `codigo_cambiado: true`, y durante una reunión
da, como mucho, UNA nota discreta por ventana. Edge/Chrome sin cabeza sobre la interfaz REAL con dobles de `fetch` y `WebSocket` (`_visual_harness.py`)."""
from __future__ import annotations

import json
import socket
import time

import pytest

from _visual_harness import Edge, foto, pagina_html


def _puerto():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def pagina(tmp_path_factory):
    return pagina_html(tmp_path_factory.mktemp("version-ui") / "app.html")


@pytest.fixture(scope="module")
def edge(tmp_path_factory):
    e = Edge(tmp_path_factory.mktemp("edge-version"), _puerto())
    yield e
    e.cerrar()


def arrancar(e, pagina):
    e.abrir(pagina.as_uri())
    e.js("localStorage.clear(); sessionStorage.clear(); 1")
    e.abrir(pagina.as_uri())
    e.js("window.__emitir(Object.assign({tipo: 'snapshot'}, %s)); 1" % json.dumps(foto()))
    time.sleep(0.4)


def preguntar(e, cambiado):
    """El servidor (doble de `fetch`) dice `cambiado`; se fuerza la petición (salta el mínimo de 30 s) y se espera su pintado."""
    e.js("window.fetch = async () => ({ ok: true, json: async () => ({ codigo_cambiado: %s }) }); AP.version.comprobar(true)" % json.dumps(cambiado))
    time.sleep(0.2)


def test_el_aviso_de_la_portada_sale_solo_si_el_servidor_dice_que_hay_codigo_nuevo(edge, pagina):
    arrancar(edge, pagina)
    assert edge.js("document.querySelector('#i-actualizado').hidden") is True          # el doble de /api/info no dice nada: oculto
    preguntar(edge, True)
    assert edge.js("document.querySelector('#i-actualizado').hidden") is False
    assert "Ciérralo y vuelve a abrirlo" in edge.js("document.querySelector('#i-actualizado').textContent")
    assert edge.js("document.querySelector('#i-actualizado').getAttribute('role')") == "status"
    preguntar(edge, False)
    assert edge.js("document.querySelector('#i-actualizado').hidden") is True


def test_en_reunion_solo_una_nota_discreta_por_ventana(edge, pagina):
    arrancar(edge, pagina)
    edge.js("window.__emitir(%s); 1" % json.dumps({"tipo": "estado", "estado": "grabando", "transcripcion": {"estado": "listo", "error": ""}}))
    time.sleep(0.3)
    preguntar(edge, True)
    nota = "document.querySelector('#r-avisos').textContent.split('versión nueva del programa').length - 1"
    assert edge.js(nota) == 1
    edge.js("document.querySelector('#r-avisos .aviso-x').click(); 1")                  # la cierran…
    preguntar(edge, True)                                                               # …y no vuelve a salir en esta ventana
    assert edge.js(nota) == 0
