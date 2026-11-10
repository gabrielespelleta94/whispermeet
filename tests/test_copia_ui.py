"""Ola F1 en la interfaz: el bloque «Copia de seguridad» de Ajustes (pestaña Privacidad) en un Edge sin cabeza sobre la interfaz REAL, con dobles de `fetch` y `WebSocket`
(`_visual_harness.py`; datos ficticios, sin servidor: no se crea ninguna copia). Capturas en claro y oscuro a 1440 px en la carpeta de `CAPTURAS_COPIA` si existe esa variable
de entorno; si no, en la carpeta temporal de la prueba."""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

import pytest

from _visual_harness import WEB, Edge, foto, pagina_html
from test_requisitos_ui import CONFIG, PROYECTOS, ROUTER, _puerto, requisitos

HTML = (WEB / "index.html").read_text(encoding="utf-8")
JS = (WEB / "copia.js").read_text(encoding="utf-8")
CSS = (WEB / "requisitos.css").read_text(encoding="utf-8")

COPIAS = [{"nombre": "whispermeet-copia-2026-03-12-104207.zip", "bytes": 1300000, "fecha": "2026-03-12T10:42:07"},
          {"nombre": "whispermeet-copia-2026-03-01-090000.zip", "bytes": 1200000, "fecha": "2026-03-01T09:00:00"}]
RESULTADO = {"nombre": "whispermeet-copia-2026-03-14-181500.zip", "ficheros": 12, "bytes": 1363148, "omitidos": [], "cortada": False}

# Un «servidor» más para /api/copia: anota las llamadas, puede retener el POST (`__soltar`) y responder un error
EXTRA = """(() => {
  const base = window.fetch;
  window.__copias = %s; window.__RESP = %s; window.__ERR = null; window.__espera = null; window.__copia_llamadas = [];
  window.__alertas = 0; window.alert = () => { window.__alertas++; };
  window.fetch = async (u, o) => {
    if (!/\\/api\\/copia/.test(u)) return base(u, o);
    const m = (o && o.method) || 'GET'; window.__copia_llamadas.push(m + ' ' + u);
    const r = (d, ok = true, status = ok ? 200 : 400) => ({ ok, status, json: async () => d });
    if (m === 'GET') return r({ copias: window.__copias, carpeta: 'X:/app/copias' });
    if (window.__espera) await window.__espera;
    if (window.__ERR) return r({ detail: window.__ERR }, false, 409);
    if (/abrir/.test(u)) return r({ ok: true });
    window.__copias = [Object.assign({ fecha: '2026-03-14T18:15:00' }, { nombre: window.__RESP.nombre, bytes: window.__RESP.bytes })].concat(window.__copias);
    return r(window.__RESP);
  };
  return 1;
})()"""


@pytest.fixture(scope="module")
def pagina(tmp_path_factory):
    return pagina_html(tmp_path_factory.mktemp("copia-ui") / "app.html")


@pytest.fixture(scope="module")
def edge(tmp_path_factory):
    e = Edge(tmp_path_factory.mktemp("edge-copia"), _puerto(), ancho=1440, alto=900)
    yield e
    e.cerrar()


def abrir_ajustes(edge, pagina, copias=None, resultado=None, esquema="dark", ancho=1440, alto=900):
    edge.cmd("Emulation.setDeviceMetricsOverride", width=ancho, height=alto, deviceScaleFactor=1, mobile=False)
    edge.cmd("Emulation.setEmulatedMedia", features=[{"name": "prefers-color-scheme", "value": esquema}])
    edge.abrir(pagina.as_uri())
    edge.js("localStorage.clear(); sessionStorage.clear(); 1")
    edge.abrir(pagina.as_uri())
    edge.js(ROUTER % (json.dumps(CONFIG), json.dumps(PROYECTOS), json.dumps(requisitos())))
    edge.js(EXTRA % (json.dumps(COPIAS if copias is None else copias), json.dumps(resultado or RESULTADO)))
    edge.js("window.__emitir(Object.assign({tipo: 'snapshot'}, %s)); 1" % json.dumps(foto(estado="inactivo")))
    edge.js("(async () => { await AP.requisitos.comprobar(); await AP.cargarProyectos(); })().then(() => 1)")
    time.sleep(0.4)
    edge.js("document.querySelector('#b-ajustes').click(); 1")
    time.sleep(0.6)                                                                              # el diálogo se abre de forma asíncrona y vuelve a la primera pestaña
    edge.js("window.AP.ajustes.ir('privacidad'); AP.copia.cargar().then(() => 1)")
    time.sleep(0.3)


def estado(edge):
    return json.loads(edge.js("""JSON.stringify((() => {
      const q = (s) => document.querySelector(s), c = q('#aj-copia-crear'), d = q('#aj-copia-omitidos');
      return { crear: c.textContent, deshabilitado: c.disabled, ocupado: c.getAttribute('aria-busy'), abrir: q('#aj-copia-abrir').textContent, abrirOff: q('#aj-copia-abrir').disabled,
        error: q('#aj-copia-error').hidden ? '' : q('#aj-copia-error').textContent, resultado: q('#aj-copia-resultado').textContent, ultima: q('#aj-copia-ultima').textContent,
        omitidosVisible: !d.hidden && d.getBoundingClientRect().height > 0, omitidosAbierto: d.open, omitidosRes: q('#aj-copia-omitidos-res').textContent,
        omitidos: [...document.querySelectorAll('#aj-copia-omitidos-lista li')].map((l) => l.textContent), foco: document.activeElement && document.activeElement.id,
        llamadas: window.__copia_llamadas, alertas: window.__alertas };
    })())"""))


# ============================================================ estáticos
def test_el_html_tiene_el_bloque_en_privacidad_con_sus_huecos():
    priv = HTML[HTML.index('id="aj-privacidad"'):HTML.index('id="s-error"')]
    for i in ('id="aj-copia"', 'id="aj-copia-crear"', 'id="aj-copia-abrir"', 'id="aj-copia-error"', 'id="aj-copia-resultado"', 'id="aj-copia-omitidos"', 'id="aj-copia-omitidos-lista"',
              'id="aj-copia-ultima"', "Copia de seguridad", ">Crear copia<", ">Abrir la carpeta de copias<"):
        assert i in priv, i
    assert re.search(r'id="aj-copia-error" role="alert" hidden', priv)                           # el hueco de error de Ajustes
    for t in ("la caché", "los modelos de transcripción", "el entorno virtual", "las copias anteriores", "los documentos de tus proyectos", "transcripciones", "fuera de una reunión"):
        assert t in priv, t
    assert 'type="button"' in re.search(r'<button[^>]*id="aj-copia-crear"[^>]*>', priv).group(0)   # dentro del formulario: no lo envía
    assert HTML.index("/static/ajustes.js") < HTML.index("/static/copia.js")


def test_js_y_css_sin_alert_sin_html_inyectado_y_con_el_tono_del_resto():
    codigo = re.sub(r"/\*.*?\*/", "", JS, flags=re.S)
    assert "alert(" not in codigo and "confirm(" not in codigo and "innerHTML" not in codigo and "insertAdjacentHTML" not in codigo
    nuevo = HTML[HTML.index('id="aj-copia"'):HTML.index('id="s-error"')]
    textos = re.findall(r">([^<>]+)<", nuevo) + re.findall(r"\"([^\"\n]*[a-záéíóúñ][^\"\n]*)\"", codigo) + re.findall(r"`([^`\n]+)`", codigo)
    for t in (x for x in textos if not re.search(r"[;(){}=]", x.replace("${", ""))):
        assert "!" not in t and "..." not in t and "…" not in t, t
    css = CSS[CSS.index("copia de seguridad"):]
    assert "text-overflow" not in css and "line-clamp" not in css and not re.findall(r"font-size: (?!var\(--f-)", css)


# ============================================================ comportamiento
def test_sin_copias_dice_que_todavia_no_hay_ninguna(edge, pagina):
    abrir_ajustes(edge, pagina, copias=[])
    e = estado(edge)
    assert e["ultima"] == "Todavía no hay ninguna copia." and e["crear"] == "Crear copia" and e["abrir"] == "Abrir la carpeta de copias"
    assert e["resultado"] == "" and e["error"] == "" and not e["omitidosVisible"]


def test_con_copias_dice_la_fecha_de_la_ultima(edge, pagina):
    abrir_ajustes(edge, pagina)
    assert estado(edge)["ultima"] == "Última copia: 12 de marzo, 10:42."


def test_mientras_se_crea_el_boton_queda_desactivado_y_al_terminar_dice_que_ha_pasado(edge, pagina):
    abrir_ajustes(edge, pagina)
    edge.js("window.__espera = new Promise((r) => { window.__soltar = r; }); document.querySelector('#aj-copia-crear').focus(); document.querySelector('#aj-copia-crear').click(); 1")
    time.sleep(0.2)
    e = estado(edge)
    assert e["crear"] == "Creando la copia" and e["deshabilitado"] and e["ocupado"] == "true" and "POST /api/copia" in e["llamadas"]
    edge.js("document.querySelector('#aj-copia-crear').click(); 1")             # un segundo clic no lanza otra copia
    edge.js("window.__soltar(); 1")
    time.sleep(0.5)
    e = estado(edge)
    assert e["llamadas"].count("POST /api/copia") == 1
    assert e["resultado"] == "Copia creada: whispermeet-copia-2026-03-14-181500.zip (12 ficheros, 1,3 MB)." and e["error"] == ""
    assert e["crear"] == "Crear copia" and not e["deshabilitado"] and e["ocupado"] is None and e["foco"] == "aj-copia-crear"
    assert e["ultima"] == "Última copia: 14 de marzo, 18:15." and not e["omitidosVisible"]


def test_los_omitidos_salen_en_una_lista_desplegable(edge, pagina):
    r = dict(RESULTADO, omitidos=[{"ruta": "sesiones/Alfa/2026-03-02-tema.md", "motivo": "No se pudo leer el fichero (Permission denied)."},
                                  {"ruta": "datos/ola4/grande.json", "motivo": "Supera el tope de tamaño por fichero (200 MB)."}])
    abrir_ajustes(edge, pagina, resultado=r)
    edge.js("document.querySelector('#aj-copia-crear').click(); 1")
    time.sleep(0.5)
    e = estado(edge)
    assert e["omitidosVisible"] and not e["omitidosAbierto"] and e["omitidosRes"] == "2 ficheros no entraron en la copia."
    assert e["omitidos"] == ["sesiones/Alfa/2026-03-02-tema.md: No se pudo leer el fichero (Permission denied).", "datos/ola4/grande.json: Supera el tope de tamaño por fichero (200 MB)."]
    edge.js("document.querySelector('#aj-copia-omitidos-res').click(); 1")
    assert estado(edge)["omitidosAbierto"]


def test_un_solo_omitido_y_un_solo_fichero_en_singular(edge, pagina):
    abrir_ajustes(edge, pagina, resultado=dict(RESULTADO, ficheros=1, bytes=800, omitidos=[{"ruta": "a/b.json", "motivo": "m."}]))
    edge.js("document.querySelector('#aj-copia-crear').click(); 1")
    time.sleep(0.5)
    e = estado(edge)
    assert e["resultado"] == "Copia creada: whispermeet-copia-2026-03-14-181500.zip (1 fichero, 0,1 MB)." and e["omitidosRes"] == "1 fichero no entró en la copia."


def test_un_error_sale_junto_al_boton_sin_alert_y_deja_volver_a_intentar(edge, pagina):
    abrir_ajustes(edge, pagina)
    edge.js("window.__ERR = 'Haz la copia fuera de una reunión.'; document.querySelector('#aj-copia-crear').focus(); document.querySelector('#aj-copia-crear').click(); 1")
    time.sleep(0.5)
    e = estado(edge)
    assert e["error"] == "Haz la copia fuera de una reunión." and e["alertas"] == 0 and e["resultado"] == ""
    assert e["crear"] == "Crear copia" and not e["deshabilitado"] and e["foco"] == "aj-copia-crear"
    r = json.loads(edge.js("""JSON.stringify((() => { const x = document.querySelector('#aj-copia-error'), b = document.querySelector('#aj-copia-crear'); const rx = x.getBoundingClientRect(), rb = b.getBoundingClientRect();
      return { rol: x.getAttribute('role'), junto: rx.top >= rb.bottom - 1 && rx.top - rb.bottom < 48, descrito: b.getAttribute('aria-describedby').includes('aj-copia-error'), invalido: b.getAttribute('aria-invalid') }; })())"""))
    assert r == {"rol": "alert", "junto": True, "descrito": True, "invalido": None}   # aria-invalid no es válido en un botón
    edge.js("window.__ERR = null; document.querySelector('#aj-copia-crear').click(); 1")
    time.sleep(0.5)
    e = estado(edge)
    assert e["error"] == "" and e["resultado"].startswith("Copia creada: ")


def test_abrir_la_carpeta_llama_a_la_api_y_un_error_sale_en_su_hueco(edge, pagina):
    abrir_ajustes(edge, pagina)
    edge.js("document.querySelector('#aj-copia-abrir').click(); 1")
    time.sleep(0.3)
    e = estado(edge)
    assert "POST /api/copia/abrir" in e["llamadas"] and e["error"] == "" and not e["abrirOff"]
    edge.js("window.__ERR = 'No se pudo abrir la carpeta: sin explorador.'; document.querySelector('#aj-copia-abrir').click(); 1")
    time.sleep(0.3)
    assert estado(edge)["error"] == "No se pudo abrir la carpeta: sin explorador."


def test_teclado_enter_en_el_boton_crea_la_copia_y_el_foco_se_ve(edge, pagina):
    abrir_ajustes(edge, pagina)
    edge.js("document.querySelector('#aj-copia-crear').focus(); 1")
    for tipo in ("keyDown", "keyUp"):
        edge.cmd("Input.dispatchKeyEvent", type=tipo, key="Enter", code="Enter", windowsVirtualKeyCode=13, **({"text": "\r"} if tipo == "keyDown" else {}))
    time.sleep(0.5)
    assert "POST /api/copia" in estado(edge)["llamadas"]
    r = json.loads(edge.js("""JSON.stringify((() => { const b = document.querySelector('#aj-copia-crear'); b.focus(); const s = getComputedStyle(b);
      return { visible: b.matches(':focus-visible'), contorno: s.outlineStyle, ancho: parseFloat(s.outlineWidth), alto: b.getBoundingClientRect().height }; })())"""))
    assert r["visible"] and r["contorno"] != "none" and r["ancho"] >= 2 and r["alto"] >= 32


def test_al_abrir_ajustes_se_vuelve_a_leer_la_lista_y_se_limpia_el_error(edge, pagina):
    abrir_ajustes(edge, pagina, copias=[])
    edge.js("window.__ERR = 'Ya hay una copia en curso.'; document.querySelector('#aj-copia-crear').click(); 1")
    time.sleep(0.4)
    assert estado(edge)["error"] == "Ya hay una copia en curso."
    edge.js("window.__ERR = null; window.__copias = %s; document.querySelector('#d-ajustes').close(); document.querySelector('#b-ajustes').click(); 1" % json.dumps(COPIAS))
    time.sleep(0.5)
    e = estado(edge)
    assert e["error"] == "" and e["ultima"] == "Última copia: 12 de marzo, 10:42."


@pytest.mark.parametrize("ancho,alto", [(1440, 900), (1024, 768), (600, 800)])
def test_el_bloque_no_desborda_ni_recorta_con_un_resultado_largo(edge, pagina, ancho, alto):
    largo = [{"ruta": "sesiones/" + "Proyecto-con-un-nombre-muy-largo-" * 4 + "/2026-03-02-tema-de-reunion-largo.md", "motivo": "No se pudo leer el fichero (el proceso no tiene acceso al archivo porque está en uso por otro programa)."}]
    abrir_ajustes(edge, pagina, resultado=dict(RESULTADO, omitidos=largo), ancho=ancho, alto=alto)
    edge.js("document.querySelector('#aj-copia-crear').click(); 1")
    time.sleep(0.5)
    edge.js("document.querySelector('#aj-copia-omitidos').open = true; document.querySelector('#aj-copia').scrollIntoView({ block: 'center' }); 1")
    r = json.loads(edge.js("""JSON.stringify((() => { const d = document.querySelector('#d-ajustes').getBoundingClientRect(); const c = document.querySelector('.d-cuerpo');
      const mal = [...document.querySelectorAll('#aj-copia *')].filter((e) => e.getBoundingClientRect().height > 0 && (e.getBoundingClientRect().right > d.right + 1 || e.scrollWidth > e.clientWidth + 1 && getComputedStyle(e).overflow === 'visible' && e.tagName !== 'BUTTON')).map((e) => e.id || e.tagName);
      const bs = [...document.querySelectorAll('#aj-copia button')].map((b) => b.getBoundingClientRect().height);
      return { mal, scrollH: c.scrollWidth <= c.clientWidth + 1, botones: bs.every((h) => h >= 32) }; })())"""))
    assert r == {"mal": [], "scrollH": True, "botones": True}, r


@pytest.mark.parametrize("esquema", ["dark", "light"])
def test_capturas_en_claro_y_oscuro(edge, pagina, esquema, tmp_path):
    destino = Path(os.environ.get("CAPTURAS_COPIA") or tmp_path)
    destino.mkdir(parents=True, exist_ok=True)
    r = dict(RESULTADO, omitidos=[{"ruta": "sesiones/Alfa/2026-03-02-tema.md", "motivo": "No se pudo leer el fichero (en uso)."}])
    abrir_ajustes(edge, pagina, resultado=r, esquema=esquema)
    edge.js("document.querySelector('#aj-copia-crear').click(); 1")
    time.sleep(0.6)
    edge.js("document.querySelector('#aj-copia-omitidos').open = true; document.querySelector('#aj-copia').scrollIntoView({ block: 'end' }); 1")
    time.sleep(0.3)
    edge.captura(destino / f"copia-ajustes-{'oscuro' if esquema == 'dark' else 'claro'}-1440.png")
    assert (destino / f"copia-ajustes-{'oscuro' if esquema == 'dark' else 'claro'}-1440.png").stat().st_size > 5000


# ============================================================ F1-arreglos: copia cortada, accesibilidad y marcador del desplegable
CORTADA = dict(RESULTADO, ficheros=3, bytes=1363148, cortada=True,
               omitidos=[{"ruta": "sesiones/Alfa/2026-03-05-tema.md", "motivo": "La copia se cortó aquí al llegar al tope de tamaño (2 GB); este fichero y los siguientes no entraron."}])


def crear_y_esperar(edge):
    edge.js("document.querySelector('#aj-copia-crear').click(); 1")
    time.sleep(0.5)


def test_una_copia_cortada_se_dice_como_incompleta_y_con_la_frase_visible(edge, pagina):
    abrir_ajustes(edge, pagina, resultado=CORTADA)
    crear_y_esperar(edge)
    e = estado(edge)
    assert e["resultado"] == "Copia incompleta: whispermeet-copia-2026-03-14-181500.zip (3 ficheros, 1,3 MB)."
    c = json.loads(edge.js("""JSON.stringify((() => { const x = document.querySelector('#aj-copia-cortada'), d = document.querySelector('#aj-copia-omitidos');
      return { texto: x.textContent, visible: !x.hidden && x.getBoundingClientRect().height > 0, desplegado: d.open }; })())"""))
    assert c == {"texto": "La copia se cortó al llegar al tope de tamaño: faltan ficheros.", "visible": True, "desplegado": False}   # visible sin desplegar nada
    assert e["omitidosVisible"] and e["omitidos"] == ["sesiones/Alfa/2026-03-05-tema.md: " + CORTADA["omitidos"][0]["motivo"]]


def test_una_copia_completa_no_enseña_la_frase_de_corte_y_la_siguiente_la_oculta(edge, pagina):
    abrir_ajustes(edge, pagina, resultado=CORTADA)
    crear_y_esperar(edge)
    edge.js("window.__RESP = %s; 1" % json.dumps(RESULTADO))
    crear_y_esperar(edge)
    e = estado(edge)
    assert e["resultado"].startswith("Copia creada: ") and "incompleta" not in e["resultado"]
    assert edge.js("document.querySelector('#aj-copia-cortada').hidden") is True


def test_aria_invalid_no_se_usa_y_los_roles_de_los_avisos_son_los_que_tocan(edge, pagina):
    abrir_ajustes(edge, pagina)
    edge.js("window.__ERR = 'Ya hay una copia en curso.'; document.querySelector('#aj-copia-crear').click(); 1")
    time.sleep(0.4)
    r = json.loads(edge.js("""JSON.stringify({ invalido: [...document.querySelectorAll('#aj-copia [aria-invalid]')].length, ultima: document.querySelector('#aj-copia-ultima').getAttribute('role'),
      resultado: document.querySelector('#aj-copia-resultado').getAttribute('role'), error: document.querySelector('#aj-copia-error').getAttribute('role') })"""))
    assert r == {"invalido": 0, "ultima": None, "resultado": "status", "error": "alert"}


def test_el_foco_no_se_roba_si_el_usuario_se_fue_a_otro_control_mientras_se_creaba(edge, pagina):
    abrir_ajustes(edge, pagina)
    edge.js("window.__espera = new Promise((r) => { window.__soltar = r; }); document.querySelector('#aj-copia-crear').click(); 1")
    time.sleep(0.2)
    edge.js("document.querySelector('#aj-copia-abrir').focus(); window.__soltar(); 1")
    time.sleep(0.5)
    assert estado(edge)["foco"] == "aj-copia-abrir"


def test_el_resumen_de_omitidos_ensena_un_indicador_y_se_abre_con_teclado(edge, pagina):
    for esquema in ("dark", "light"):
        abrir_ajustes(edge, pagina, resultado=CORTADA, esquema=esquema)
        crear_y_esperar(edge)
        r = json.loads(edge.js("""JSON.stringify((() => { const s = document.querySelector('#aj-copia-omitidos-res'), b = getComputedStyle(s, '::before'), c = getComputedStyle(s);
          return { contenido: b.content !== 'none' && b.content !== 'normal', ancho: parseFloat(b.width), borde: b.borderRightWidth, color: b.borderRightColor, fondo: c.backgroundColor, tinta: c.color, cursor: c.cursor }; })())"""))
        assert r["contenido"] and r["ancho"] >= 5 and r["cursor"] == "pointer" and r["color"] == r["tinta"] and r["borde"] != "0px", (esquema, r)
    edge.js("document.querySelector('#aj-copia-omitidos-res').focus(); 1")
    for tipo in ("keyDown", "keyUp"):
        edge.cmd("Input.dispatchKeyEvent", type=tipo, key="Enter", code="Enter", windowsVirtualKeyCode=13, **({"text": "\r"} if tipo == "keyDown" else {}))
    time.sleep(0.2)
    assert estado(edge)["omitidosAbierto"]


def test_captura_de_la_copia_cortada_en_oscuro(edge, pagina, tmp_path):
    destino = Path(os.environ.get("CAPTURAS_COPIA") or tmp_path)
    destino.mkdir(parents=True, exist_ok=True)
    abrir_ajustes(edge, pagina, resultado=CORTADA, esquema="dark")
    crear_y_esperar(edge)
    edge.js("document.querySelector('#aj-copia-omitidos').open = true; document.querySelector('#aj-copia').scrollIntoView({ block: 'end' }); 1")
    time.sleep(0.3)
    edge.captura(destino / "copia-ajustes-cortada-oscuro-1440.png")
    assert (destino / "copia-ajustes-cortada-oscuro-1440.png").stat().st_size > 5000
