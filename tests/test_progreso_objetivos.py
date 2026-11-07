"""Chip de progreso de objetivos en la cabecera de la reunión («3 de 4 objetivos · 12:40») y en la barra del Modo reunión.
Estáticos y dinámicos en un Edge sin cabeza sobre la interfaz real (dobles de fetch/WebSocket, ver `_visual_harness.py`)."""
from __future__ import annotations

import json
import re
import socket
import time

import pytest

from _visual_harness import WEB, Edge, foto, pagina_html

HTML = (WEB / "index.html").read_text(encoding="utf-8")
CSS = (WEB / "app.css").read_text(encoding="utf-8")
JS_MR = (WEB / "modo-reunion.js").read_text(encoding="utf-8")


def test_estaticos_el_chip_esta_en_la_cabecera_y_viaja_al_modo_reunion():
    assert 'id="r-obj-prog"' in HTML and HTML.index('id="r-cab"') < HTML.index('id="r-obj-prog"') < HTML.index('id="r-pausa"')
    assert '"r-obj-prog"' in JS_MR
    regla = re.search(r"\.obj-prog \{([^}]*)\}", CSS).group(1)
    assert "font-size" not in regla                         # el tamaño viene de t-meta (var(--f-12))
    assert 'id="r-obj-prog" role="status" hidden' in HTML   # oculto de salida: sin objetivos no se ve


def _puerto():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def pagina(tmp_path_factory):
    return pagina_html(tmp_path_factory.mktemp("progreso-obj") / "app.html")


@pytest.fixture(scope="module")
def edge(tmp_path_factory):
    e = Edge(tmp_path_factory.mktemp("edge-progreso"), _puerto())
    yield e
    e.cerrar()


def O(n, estado, minuto="", t=None, **x):
    return {"n": n, "texto": f"Objetivo {n}", "estado": estado, "minuto": minuto, "t_seg": t, "origen": "plan", **x}


def chip(e):
    return json.loads(e.js("""JSON.stringify((() => { const c = document.querySelector('#r-obj-prog'); const r = c.getBoundingClientRect();
      return { hidden: c.hidden, texto: c.textContent, titulo: c.title, completo: c.classList.contains('completo'), ancho: Math.round(r.width), px: parseFloat(getComputedStyle(c).fontSize) }; })())"""))


def test_el_chip_sigue_al_estado_de_los_objetivos(edge, pagina):
    edge.abrir(pagina.as_uri())
    edge.js("localStorage.clear(); sessionStorage.clear(); 1")
    edge.abrir(pagina.as_uri())
    edge.js("window.__emitir(Object.assign({tipo: 'snapshot'}, %s)); 1" % json.dumps(foto()))
    time.sleep(0.5)
    assert chip(edge)["hidden"]                                                  # sin objetivos no hay chip
    objs = [O(1, "cubierto", "05:10", 310), O(2, "cubierto", "12:40", 760), O(3, "parcial"), O(4, "sin_tratar")]
    edge.js("window.__emitir(%s); 1" % json.dumps({"tipo": "objetivos", "objetivos": objs}))
    time.sleep(0.4)
    c = chip(edge)
    assert not c["hidden"] and c["texto"] == "2 de 4 objetivos · 12:40" and not c["completo"] and c["px"] == 12
    assert "minuto 12:40" in c["titulo"]
    objs[2]["estado"] = "cubierto"; objs[2]["minuto"] = "20:05"; objs[2]["t_seg"] = 1205
    edge.js("window.__emitir(%s); 1" % json.dumps({"tipo": "objetivos", "objetivos": objs}))
    time.sleep(0.4)
    assert chip(edge)["texto"] == "3 de 4 objetivos · 20:05"
    # un objetivo sugerido (sin confirmar) no cuenta
    objs.append(O(5, "sin_tratar", sugerido=True))
    edge.js("window.__emitir(%s); 1" % json.dumps({"tipo": "objetivos", "objetivos": objs}))
    time.sleep(0.4)
    assert chip(edge)["texto"] == "3 de 4 objetivos · 20:05"
    objs[3]["estado"] = "cubierto"; objs[3]["minuto"] = "25:00"; objs[3]["t_seg"] = 1500
    edge.js("window.__emitir(%s); 1" % json.dumps({"tipo": "objetivos", "objetivos": objs}))
    time.sleep(0.4)
    c = chip(edge)
    assert c["texto"] == "4 de 4 objetivos · 25:00" and c["completo"]
    edge.js("window.__emitir(%s); 1" % json.dumps({"tipo": "objetivos", "objetivos": []}))
    time.sleep(0.4)
    assert chip(edge)["hidden"]


def test_la_revision_muestra_el_correo_y_copiar_no_envia_nada(edge, pagina):
    correo = "Asunto: Resumen: Seguimiento (06/11/2026)\n\nHola:\n\nCerrado\n- Decisión: Vamos con A\n\nAbierto\n- Pendiente: Estimar SAP (Luis)\n\nUn saludo."
    rev = {"estado": "lista", "resumen": "Resumen.", "resumen_sonnet": "Resumen.", "cambios": [], "error": "", "aplicado": None, "carpeta_contexto": True, "compartido": False,
           "destino_contexto": "", "sin_cambios": "", "pulido": {"estado": "ninguno", "resumen": "", "error": "", "elegida": "sonnet"}, "objetivos": [], "avisos": [],
           "publicacion": None, "correo": correo}
    edge.abrir(pagina.as_uri())
    edge.js("localStorage.clear(); sessionStorage.clear(); 1")
    edge.abrir(pagina.as_uri())
    edge.js("window.__llamadas = []; const f0 = window.fetch; window.fetch = async (u, o) => { window.__llamadas.push([String(u), o && o.method]); return f0(u, o); }; "
            "window.__copiado = null; navigator.clipboard.writeText = async (t) => { window.__copiado = t; }; 1")
    edge.js("window.__emitir(Object.assign({tipo: 'snapshot'}, %s)); 1" % json.dumps(foto(estado="revision", revision=rev)))
    time.sleep(0.6)
    assert edge.js("document.querySelector('#v-rev-correo-texto').textContent") == correo
    assert edge.js("document.querySelector('#v-rev-correo .t-label').textContent") == "Correo de cierre"
    edge.js("document.querySelector('#v-rev-correo-copiar').click(); 1")
    time.sleep(0.4)
    assert edge.js("window.__copiado") == correo and edge.js("document.querySelector('#v-rev-correo-estado').textContent") == "Copiado"
    assert not edge.js("window.__llamadas.some(l => /correo|mail|enviar/i.test(l[0]))")
    assert not edge.js("!!document.querySelector('a[href^=\"mailto\"]')")
    # sin correo no hay sección
    edge.js("window.__emitir(Object.assign({tipo: 'snapshot'}, %s)); 1" % json.dumps(foto(estado="revision", revision={**rev, "correo": ""})))
    time.sleep(0.5)
    assert edge.js("!document.querySelector('#v-rev-correo')")
