"""Transcripción en la nube en la interfaz: Ajustes › Audio (motor, servicio, clave, prueba), chip de la cabecera, pie, registro de envíos y el consentimiento
(casilla «He avisado a los asistentes» de la portada y ventana de aviso de llamada). Edge sin cabeza sobre la interfaz REAL con dobles de `fetch` y `WebSocket`
(`_visual_harness.py`; datos ficticios, sin servidor ni red). La clave del ejemplo es ficticia."""
from __future__ import annotations

import json
import re
import socket
import time

import pytest

from _visual_harness import WEB, Edge, _fuentes, foto, pagina_html

CLAVE = "sk-ficticia-0000000000"
HTML = (WEB / "index.html").read_text(encoding="utf-8")
NUBE_JS = re.sub(r"/[*].*?[*]/", "", (WEB / "nube.js").read_text(encoding="utf-8"), flags=re.S)   # sin los comentarios de bloque
NUBE_CSS = (WEB / "nube.css").read_text(encoding="utf-8")

CONFIG = {"excluir_captura": True, "whisper_beam": 5, "vocabulario_transcripcion": [], "knowledge": "", "min_palabras_analisis": 150, "esfuerzo": "low",
          "detectar_llamadas": True, "filtrar_eco": True, "whisper_modelo": "small", "raiz_proyectos": "X:/Proyectos",
          "modelos": {"digest": "haiku", "equipo": "haiku", "periodico": "haiku", "final": "sonnet", "contradicciones_confirmar": "sonnet", "consulta": "haiku", "pulido": "opus"}}
NUBE_CFG = {"transcripcion_motor": "local", "nube_url_base": "https://api.openai.com/v1", "nube_modelo": "gpt-transcribe", "nube_autenticacion": "bearer", "nube_dialecto": "auto"}
SIN_CLAVE = {"puesta": False, "origen": "ninguna", "error": ""}
CLAVE_FICHERO = {"puesta": True, "origen": "fichero", "error": ""}


def info(motor="local", clave=SIN_CLAVE, host="api.openai.com", **cfg):
    return {"simulacion": False, "config": dict(CONFIG, **dict(NUBE_CFG, transcripcion_motor=motor, **cfg)),
            "nube": {"clave": clave, "dialecto_efectivo": "gpt-transcribe", "host": host}}


INFO_ANTERIOR = {"simulacion": False, "config": dict(CONFIG)}   # un servidor sin nube: ni claves nuevas ni bloque `nube`

ROUTER = """(() => {
  window.__reqs = []; window.__RESP = {}; window.__RETRASO = 0; window.__INFO = %s;
  window.fetch = async (u, o) => {
    const m = (o && o.method) || 'GET', url = String(u), ruta = url.split('?')[0];
    window.__reqs.push({ m, u: url, b: (o && o.body) || null });
    const r = (d, ok = true, status = ok ? 200 : 400) => ({ ok, status, json: async () => d });
    const forzada = window.__RESP[m + ' ' + ruta];
    if (/\\/api\\/nube\\/probar/.test(url) && window.__RETRASO) await new Promise((x) => setTimeout(x, window.__RETRASO));
    if (forzada) return r(forzada.body, forzada.status < 400, forzada.status);
    if (/\\/api\\/info/.test(url)) return r(window.__INFO);
    if (/\\/api\\/dispositivos/.test(url)) return r({ error: '', entradas: [{ indice: 1, nombre: 'Micrófono ficticio', canales: 1, frecuencia: 16000 }], salidas: [{ indice: 2, nombre: 'Altavoces ficticios', canales: 2, frecuencia: 48000 }], mic_defecto: 1, sistema_defecto: 2 });
    if (/\\/api\\/ventana/.test(url)) return r({ nativa: false });
    if (/\\/api\\/requisitos/.test(url)) return r({ estado: 'bien', faltan: 0, avisos: 0, comprobaciones: [] });
    if (/api\\/proyectos\\/resumen/.test(url)) return r({ resumen: {}, parcial: false });
    if (/api\\/proyectos\\?/.test(url)) return r({ raiz: 'X:/Proyectos', proyectos: [] });
    if (/\\/api\\/envios/.test(url)) return r({ envios: [], resumen: {} });
    if (/\\/api\\/modo-local/.test(url)) return r({ activo: false, sesion: false, config: false });
    if (m === 'PUT' && /\\/api\\/config/.test(url)) return r({ config: Object.assign({}, window.__INFO.config, JSON.parse(o.body)) });
    if (m === 'PUT' && /\\/api\\/nube\\/clave/.test(url)) return r({ clave: { puesta: true, origen: 'fichero', error: '' } });
    if (m === 'DELETE' && /\\/api\\/nube\\/clave/.test(url)) return r({ clave: { puesta: false, origen: 'ninguna', error: '' } });
    if (m === 'POST' && /\\/api\\/nube\\/probar/.test(url)) return r({ ok: true, ms: 820, modelo: 'gpt-transcribe', dialecto: 'gpt-transcribe', host: 'api.openai.com', idioma: null });
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
    return pagina_html(tmp_path_factory.mktemp("nube-ui") / "app.html")


@pytest.fixture(scope="module")
def edge(tmp_path_factory):
    e = Edge(tmp_path_factory.mktemp("edge-nube"), _puerto(), ancho=1280, alto=800)
    yield e
    e.cerrar()


def abrir(edge, pagina, inf=None, estado="inactivo"):
    """La interfaz con `inf` como respuesta de /api/info (por defecto, motor local y sin clave)."""
    edge.cmd("Emulation.setDeviceMetricsOverride", width=1280, height=800, deviceScaleFactor=1, mobile=False)
    edge.cmd("Emulation.setEmulatedMedia", features=[{"name": "prefers-color-scheme", "value": "dark"}])
    edge.abrir(pagina.as_uri())
    edge.js("localStorage.clear(); sessionStorage.clear(); 1")
    edge.abrir(pagina.as_uri())
    edge.js(ROUTER % json.dumps(inf or info()))
    edge.js("window.__emitir(Object.assign({tipo: 'snapshot'}, %s)); 1" % json.dumps(foto(estado=estado)))
    time.sleep(0.3)


def abrir_ajustes(edge, pagina, inf=None):
    abrir(edge, pagina, inf)
    edge.js("document.querySelector('#b-ajustes').click(); 1")
    for _ in range(40):
        time.sleep(0.15)
        if edge.js("document.querySelector('#d-ajustes').open"):
            break
    time.sleep(0.2)


def ev(edge, expr):
    return json.loads(edge.js("JSON.stringify(" + expr + ")"))


def peticiones(edge, patron=None, metodo=None):
    ll = ev(edge, "window.__reqs")
    return [l for l in ll if (not patron or re.search(patron, l["u"])) and (not metodo or l["m"] == metodo)]


def escribir(edge, selector, valor):
    edge.js("(() => { const e = document.querySelector(%s); e.value = %s; e.dispatchEvent(new Event('input', { bubbles: true })); e.dispatchEvent(new Event('change', { bubbles: true })); return 1; })()"
            % (json.dumps(selector), json.dumps(valor)))


def elegir_motor(edge, valor):
    edge.js("(() => { const r = document.querySelector('input[name=transcripcion_motor][value=%s]'); r.checked = true; r.dispatchEvent(new Event('change', { bubbles: true })); return 1; })()" % valor)


def guardar(edge):
    edge.js("document.querySelector('#s-guardar').click(); 1")
    time.sleep(0.5)


def tick(edge, **tr):
    edge.js("window.__emitir({ tipo: 'tick', t: 5, estado: 'grabando', transcripcion: %s }); 1" % json.dumps(tr))
    time.sleep(0.4)


# ============================================================ estáticos
def test_la_clave_no_tiene_name_ni_toca_el_almacenamiento_ni_la_red():
    campo = re.search(r'<input[^>]*id="aj-nube-clave"[^>]*>', HTML).group(0)
    assert 'type="password"' in campo and 'autocomplete="off"' in campo and "name=" not in campo
    assert re.search(r'<label class="t-label" for="aj-nube-clave">', HTML)
    for cadena in ("localStorage", "sessionStorage", "indexedDB"):
        assert cadena not in NUBE_JS
    for texto in (NUBE_JS, NUBE_CSS):
        assert "http://" not in texto and "https://" not in texto and "//cdn" not in texto
    assert HTML.index("/static/ajustes.js") < HTML.index("/static/nube.js") and "/static/nube.css" in HTML
    assert HTML.index('name="whisper_modelo"') < HTML.index('id="aj-nube"') < HTML.index('id="aj-c-beam"')


# ============================================================ Ajustes
def test_ajustes_muestra_motor_y_campos_desactivados_en_local(edge, pagina):
    abrir_ajustes(edge, pagina)
    r = ev(edge, """(() => { const q = (s) => document.querySelector(s), f = q('#f-ajustes');
      return { oculto: q('#aj-nube').hidden, motor: f.elements.transcripcion_motor.value, radios: [...document.querySelectorAll('input[name=transcripcion_motor]')].map((x) => x.value),
        url: f.elements.nube_url_base.value, modelo: f.elements.nube_modelo.value, auth: f.elements.nube_autenticacion.value, dialecto: f.elements.nube_dialecto.value,
        desact: ['nube_url_base', 'nube_modelo', 'nube_autenticacion', 'nube_dialecto'].map((n) => f.elements[n].disabled), probar: q('#aj-nube-probar').disabled,
        acepto: q('#aj-nube-acepto-fila').hidden, clave: q('#aj-nube-clave').value, estado: q('#aj-nube-clave-estado').textContent, quitar: q('#aj-nube-clave-quitar').disabled,
        aviso: q('#aj-nube-aviso').textContent, leyenda: q('#aj-nube legend').textContent, sinName: !q('#aj-nube-clave').hasAttribute('name') }; })()""")
    assert not r["oculto"] and r["motor"] == "local" and r["radios"] == ["local", "nube"]
    assert r["url"] == "https://api.openai.com/v1" and r["modelo"] == "gpt-transcribe" and r["auth"] == "bearer" and r["dialecto"] == "auto"
    assert r["desact"] == [True] * 4 and r["probar"] is True and r["acepto"] is True
    assert r["clave"] == "" and r["estado"] == "Sin clave" and r["quitar"] is True and r["sinName"] is True
    assert "el audio del micro y de la reunión" in r["aviso"] and "Modo solo local" in r["aviso"] and r["leyenda"] == "Dónde se transcribe"
    elegir_motor(edge, "nube")                                    # elegir la nube activa los campos del servicio al momento
    r = ev(edge, "(() => { const f = document.querySelector('#f-ajustes'); return { d: ['nube_url_base', 'nube_modelo', 'nube_autenticacion', 'nube_dialecto'].map((n) => f.elements[n].disabled), p: document.querySelector('#aj-nube-probar').disabled }; })()")
    assert r == {"d": [False] * 4, "p": False}


def test_pasar_a_nube_exige_confirmar_que_el_audio_sale(edge, pagina):
    abrir_ajustes(edge, pagina)
    elegir_motor(edge, "nube")
    assert edge.js("document.querySelector('#aj-nube-acepto-fila').hidden") is False
    guardar(edge)
    r = ev(edge, """(() => { const e = document.querySelector('#aj-nube-motor-error'), a = document.querySelector('#aj-nube-acepto');
      return { abierto: document.querySelector('#d-ajustes').open, vis: !e.hidden && e.getBoundingClientRect().height > 0, texto: e.textContent, foco: document.activeElement === a, inval: a.getAttribute('aria-invalid'),
        desc: a.getAttribute('aria-describedby') }; })()""")
    assert r["abierto"] and r["vis"] and "Entiendo que el audio sale del equipo" in r["texto"] and r["foco"] and r["inval"] == "true" and "aj-nube-motor-error" in r["desc"]
    assert not peticiones(edge, r"/api/config", "PUT")              # sin confirmar no se manda nada
    edge.js("document.querySelector('#aj-nube-acepto').click(); 1")
    assert edge.js("document.querySelector('#aj-nube-motor-error').hidden") is True
    guardar(edge)
    puts = peticiones(edge, r"/api/config", "PUT")
    assert json.loads(puts[0]["b"])["transcripcion_motor"] == "nube"
    assert edge.js("document.querySelector('#d-ajustes').open") is False


def test_quitar_la_nube_no_pide_confirmacion(edge, pagina):
    abrir_ajustes(edge, pagina, info("nube", CLAVE_FICHERO))
    assert edge.js("document.querySelector('#aj-nube-acepto-fila').hidden") is True      # ya estaba en la nube: nada que confirmar
    elegir_motor(edge, "local")
    guardar(edge)
    puts = peticiones(edge, r"/api/config", "PUT")
    assert json.loads(puts[0]["b"])["transcripcion_motor"] == "local"


def test_guardar_envia_solo_lo_cambiado_y_nunca_la_clave(edge, pagina):
    abrir_ajustes(edge, pagina, info("nube", CLAVE_FICHERO))
    escribir(edge, "#aj-nube-clave", CLAVE)                       # escrita pero sin pulsar «Guardar clave»
    escribir(edge, "[name=nube_modelo]", "whisper-1")
    guardar(edge)
    puts = peticiones(edge, r"/api/config", "PUT")
    cuerpo = json.loads(puts[0]["b"])                              # (Ajustes manda además su propio PUT de equipo: sin claves de la nube)
    assert cuerpo["nube_modelo"] == "whisper-1"
    assert not (set(cuerpo) & {"transcripcion_motor", "nube_url_base", "nube_autenticacion", "nube_dialecto"})      # lo que no cambió, no viaja
    assert all(CLAVE not in p["b"] and "clave" not in p["b"] for p in puts)
    abrir_ajustes(edge, pagina, info("local"))                    # y sin tocar nada tampoco viaja ninguna de las cinco
    guardar(edge)
    cuerpo = json.loads(peticiones(edge, r"/api/config", "PUT")[0]["b"])
    assert not (set(cuerpo) & set(NUBE_CFG))


def test_guardar_clave_usa_su_ruta_y_vacia_el_campo(edge, pagina):
    abrir_ajustes(edge, pagina)
    escribir(edge, "#aj-nube-clave", CLAVE)
    edge.js("document.querySelector('#aj-nube-clave-guardar').click(); 1")
    time.sleep(0.5)
    ll = peticiones(edge, r"/api/nube/clave")
    assert [(l["m"], json.loads(l["b"])) for l in ll] == [("PUT", {"clave": CLAVE})]
    r = ev(edge, """({ valor: document.querySelector('#aj-nube-clave').value, estado: document.querySelector('#aj-nube-clave-estado').textContent, quitar: document.querySelector('#aj-nube-clave-quitar').disabled,
      html: document.documentElement.outerHTML.includes(%s), almacen: JSON.stringify([localStorage, sessionStorage]).includes(%s), config: window.__reqs.filter((x) => /api\\/config/.test(x.u)).length })""" % (json.dumps(CLAVE), json.dumps(CLAVE)))
    assert r == {"valor": "", "estado": "Clave guardada cifrada en este equipo", "quitar": False, "html": False, "almacen": False, "config": 0}
    edge.js("document.querySelector('#aj-nube-clave-guardar').click(); 1")           # sin escribir nada: error junto al campo, sin petición
    time.sleep(0.3)
    assert len(peticiones(edge, r"/api/nube/clave")) == 1
    assert edge.js("document.querySelector('#aj-nube-clave-error').textContent") == "Escribe la clave antes de guardarla."


def test_clave_rechazada_se_pinta_junto_al_campo_y_enfoca(edge, pagina):
    abrir_ajustes(edge, pagina)
    edge.js("window.__RESP['PUT /api/nube/clave'] = { status: 400, body: { detail: 'La clave tiene de 8 a 400 caracteres visibles, sin espacios.', campo: 'nube_clave' } }; 1")
    escribir(edge, "#aj-nube-clave", "corta")
    edge.js("document.querySelector('#aj-nube-clave-guardar').click(); 1")
    time.sleep(0.5)
    r = ev(edge, "({ t: document.querySelector('#aj-nube-clave-error').textContent, foco: document.activeElement.id, v: document.querySelector('#aj-nube-clave').value })")
    assert r["t"].startswith("La clave tiene de 8 a 400") and r["foco"] == "aj-nube-clave" and r["v"] == "corta"


def test_quitar_clave(edge, pagina):
    abrir_ajustes(edge, pagina, info("nube", CLAVE_FICHERO))
    assert edge.js("document.querySelector('#aj-nube-clave-estado').textContent") == "Clave guardada cifrada en este equipo"
    assert edge.js("document.querySelector('#aj-nube-clave-quitar').disabled") is False
    edge.js("document.querySelector('#aj-nube-clave-quitar').click(); 1")
    time.sleep(0.5)
    assert [(l["m"], l["b"]) for l in peticiones(edge, r"/api/nube/clave")] == [("DELETE", None)]
    r = ev(edge, "({ e: document.querySelector('#aj-nube-clave-estado').textContent, q: document.querySelector('#aj-nube-clave-quitar').disabled })")
    assert r == {"e": "Sin clave", "q": True}
    # la clave de la variable de entorno y el error de DPAPI se dicen tal cual
    abrir_ajustes(edge, pagina, info("nube", {"puesta": True, "origen": "entorno", "error": ""}))
    assert edge.js("document.querySelector('#aj-nube-clave-estado').textContent") == "Clave de la variable de entorno WHISPERMEET_CLAVE_NUBE"
    texto = "La clave guardada no se puede leer con este usuario de Windows: vuelve a ponerla."
    abrir_ajustes(edge, pagina, info("nube", {"puesta": False, "origen": "ninguna", "error": texto}))
    assert edge.js("document.querySelector('#aj-nube-clave-estado').textContent") == texto
    assert edge.js("document.querySelector('#aj-nube-clave-quitar').disabled") is False        # con una clave ilegible se puede quitar


def test_probar_manda_valores_del_formulario_y_pinta_ok_y_error(edge, pagina):
    abrir_ajustes(edge, pagina, info("nube", CLAVE_FICHERO))
    escribir(edge, "[name=nube_modelo]", "whisper-1")
    edge.js("document.querySelector('#aj-nube-avanzado').open = true; 1")
    escribir(edge, "[name=nube_dialecto]", "clasico")
    escribir(edge, "[name=nube_autenticacion]", "api-key")
    escribir(edge, "#aj-nube-clave", CLAVE)
    edge.js("window.__RETRASO = 600; document.querySelector('#aj-nube-probar').click(); 1")
    time.sleep(0.2)
    r = ev(edge, "({ t: document.querySelector('#aj-nube-probar').textContent, d: document.querySelector('#aj-nube-probar').disabled })")
    assert r == {"t": "Probando…", "d": True}
    time.sleep(0.8)
    r = ev(edge, "({ t: document.querySelector('#aj-nube-probar').textContent, d: document.querySelector('#aj-nube-probar').disabled, res: document.querySelector('#aj-nube-probar-res').textContent, est: document.querySelector('#aj-nube-probar-res').dataset.estado })")
    assert r["t"] == "Probar conexión" and r["d"] is False and r["est"] == "ok" and "gpt-transcribe" in r["res"] and "api.openai.com" in r["res"] and "820 ms" in r["res"]
    cuerpo = json.loads(peticiones(edge, r"/api/nube/probar")[0]["b"])
    assert cuerpo == {"nube_url_base": "https://api.openai.com/v1", "nube_modelo": "whisper-1", "nube_autenticacion": "api-key", "nube_dialecto": "clasico", "clave": CLAVE}
    assert edge.js("document.querySelector('#aj-nube-clave').value") == CLAVE               # probar no la guarda ni la borra
    assert not peticiones(edge, r"/api/nube/clave")
    # fallo: el mensaje del servidor tal cual, y sin clave escrita no viaja ningún campo `clave`
    texto = "La nube rechaza la clave (401). Revisa la clave."
    edge.js("window.__RETRASO = 0; window.__RESP['POST /api/nube/probar'] = { status: 200, body: { ok: false, causa: 'clave', http: 401, mensaje: %s } }; document.querySelector('#aj-nube-clave').value = ''; document.querySelector('#aj-nube-probar').click(); 1" % json.dumps(texto))
    time.sleep(0.5)
    r = ev(edge, "({ res: document.querySelector('#aj-nube-probar-res').textContent, est: document.querySelector('#aj-nube-probar-res').dataset.estado, rol: document.querySelector('#aj-nube-probar-res').getAttribute('role') })")
    assert r == {"res": texto, "est": "error", "rol": "status"}
    assert "clave" not in json.loads(peticiones(edge, r"/api/nube/probar")[-1]["b"])


def test_error_de_campo_nube_se_pinta_junto_al_campo_y_enfoca(edge, pagina):
    abrir_ajustes(edge, pagina, info("nube", CLAVE_FICHERO))
    msg = "La dirección debe empezar por https:// (http:// solo en este equipo)."
    edge.js("window.__RESP['PUT /api/config'] = { status: 400, body: { detail: %s, campo: 'nube_url_base' } }; 1" % json.dumps(msg))
    escribir(edge, "[name=nube_url_base]", "http://ejemplo.invalid/v1")
    guardar(edge)
    r = ev(edge, """(() => { const i = document.querySelector('[name=nube_url_base]'), e = document.querySelector('#aj-nube-url-error');
      return { abierto: document.querySelector('#d-ajustes').open, t: e.textContent, vis: !e.hidden, foco: document.activeElement === i, inval: i.getAttribute('aria-invalid'), desc: i.getAttribute('aria-describedby'), rol: e.getAttribute('role'),
        general: document.querySelector('#s-error').hidden }; })()""")
    assert r["abierto"] and r["t"] == msg and r["vis"] and r["foco"] and r["inval"] == "true" and "aj-nube-url-error" in r["desc"] and r["rol"] == "alert" and r["general"] is True
    escribir(edge, "[name=nube_url_base]", "https://api.openai.com/v1")                     # al corregir, el error desaparece
    assert edge.js("document.querySelector('#aj-nube-url-error').hidden") is True
    # un campo del ajuste fino abre el desplegable
    edge.js("window.__RESP['PUT /api/config'] = { status: 400, body: { detail: 'Dialecto no válido.', campo: 'nube_dialecto' } }; document.querySelector('#aj-nube-avanzado').open = false; 1")
    escribir(edge, "[name=nube_dialecto]", "clasico")
    guardar(edge)
    r = ev(edge, "({ abierto: document.querySelector('#aj-nube-avanzado').open, t: document.querySelector('#aj-nube-dialecto-error').textContent, foco: document.activeElement.name })")
    assert r == {"abierto": True, "t": "Dialecto no válido.", "foco": "nube_dialecto"}


# ============================================================ cabecera y pie
ESTADOS = [
    ("activa", "Nube", ""), ("sonda", "Nube", "Probando la nube."), ("respaldo", "Nube · local", "Sin conexión con la nube: la transcripción sigue en este equipo y se vuelve a probar en 42 s."),
    ("bloqueada", "Local (nube caída)", "La nube rechaza la clave (401). Esta reunión sigue transcribiéndose en este equipo. Revisa la clave en Ajustes › Audio."),
    ("sin_clave", "Local (sin clave)", "La transcripción en la nube está activada, pero no hay clave. Esta reunión sigue transcribiéndose en este equipo."),
    ("solo_local", "Local", "Modo solo local: esta reunión se transcribe en este equipo, sin la nube."),
]


@pytest.mark.parametrize("estado,texto,mensaje", ESTADOS)
def test_chip_motor_por_estado(edge, pagina, estado, texto, mensaje):
    abrir(edge, pagina, estado="grabando")
    tick(edge, estado="listo", motor="nube", motor_activo="nube", nube={"estado": estado, "causa": "", "mensaje": mensaje, "vuelve_en_s": None, "trozos": 3, "audio_s": 20.0, "ms_medio": 900, "fallos": 0, "respaldo_trozos": 0})
    r = ev(edge, """(() => { const c = document.querySelector('#r-motor'); return { oculto: c.hidden, texto: c.textContent, estado: c.dataset.estado, title: c.title, aria: c.getAttribute('aria-label'), rol: c.getAttribute('role') }; })()""")
    esperado = mensaje or r["title"]
    assert r["oculto"] is False and r["texto"] == texto and r["estado"] == estado and r["title"] == esperado and r["aria"] == esperado and r["rol"] == "status" and esperado
    if estado in ("respaldo", "bloqueada"):       # los colores de aviso solo en los dos estados que lo merecen
        assert ev(edge, "getComputedStyle(document.querySelector('#r-motor')).borderTopColor") == ev(edge, "getComputedStyle(document.querySelector('#r-local')).borderTopColor")


def test_chip_oculto_sin_nube_y_con_servidor_anterior(edge, pagina):
    abrir(edge, pagina, INFO_ANTERIOR, estado="grabando")
    tick(edge, estado="listo")                                  # un servidor anterior: la transcripción no trae `nube`
    assert edge.js("document.querySelector('#r-motor').hidden") is True
    tick(edge, estado="listo", motor="nube", nube={"estado": "activa", "causa": "", "mensaje": "", "vuelve_en_s": None, "trozos": 1, "audio_s": 5.0, "ms_medio": 800, "fallos": 0, "respaldo_trozos": 0})
    assert edge.js("document.querySelector('#r-motor').hidden") is False
    tick(edge, estado="listo", motor="local", nube=None)        # motor local sin uso de la nube: `nube` es null
    assert edge.js("document.querySelector('#r-motor').hidden") is True


def test_pie_muestra_mensaje_de_respaldo(edge, pagina):
    abrir(edge, pagina, estado="grabando")
    msg = "Sin conexión con la nube: la transcripción sigue en este equipo y se vuelve a probar en 60 s."
    nube = {"estado": "respaldo", "causa": "red", "mensaje": msg, "vuelve_en_s": 60, "trozos": 9, "audio_s": 70.0, "ms_medio": 900, "fallos": 2, "respaldo_trozos": 2}
    tick(edge, estado="listo", error="", nube=nube)
    assert edge.js("document.querySelector('#p-trans').textContent") == msg
    tick(edge, estado="listo", error="", nube=dict(nube, estado="activa"))
    assert edge.js("document.querySelector('#p-trans').textContent") == ""
    tick(edge, estado="error", error="No se pudo cargar el modelo.", nube=nube)          # un error propio de la transcripción manda sobre el mensaje de la nube
    assert edge.js("document.querySelector('#p-trans').textContent") == "No se pudo cargar el modelo."
    # el aviso de retraso explica que ahora se transcribe en este equipo
    base = {"estado": "listo", "retraso_s": 20, "rezagado_s": 0}
    r = ev(edge, """({ caida: AP.avisoRetraso(Object.assign({ nube: { estado: 'respaldo' } }, %s)), bloq: AP.avisoRetraso(Object.assign({ nube: { estado: 'bloqueada' } }, %s)),
      activa: AP.avisoRetraso(Object.assign({ nube: { estado: 'activa' } }, %s)), sin: AP.avisoRetraso(%s), alDia: AP.avisoRetraso({ estado: 'listo', retraso_s: 1, nube: { estado: 'respaldo' } }) })"""
           % ((json.dumps(base),) * 4))
    assert r["caida"] == "Transcripción con 20 s de retraso · en este equipo (la nube no responde)" and r["bloq"] == r["caida"]
    assert r["activa"] == "Transcripción con 20 s de retraso" == r["sin"] and r["alDia"] == ""


# ============================================================ registro de envíos
def test_envios_nube_se_pintan_aparte_y_no_cuentan_como_llamadas(edge, pagina):
    envios = [{"ts": "2026-11-11T10:02:00", "sesion": "a1b2c3", "agente": "Transcripción en la nube", "tarea": "transcripcion_nube", "tipo": "transcripcion_nube", "modelo": "gpt-transcribe", "host": "api.openai.com",
               "audio_s": 96.4, "trozos": 13, "fallos": 0, "chars": 1820, "bloqueado": False, "ok": True, "entrada": 0, "salida": 0, "extracto": ""},
              {"ts": "2026-11-11T10:03:00", "sesion": "", "agente": "Transcripción en la nube", "tarea": "nube_prueba", "tipo": "transcripcion_nube", "modelo": "gpt-transcribe", "host": "api.openai.com",
               "audio_s": 1.0, "trozos": 1, "bloqueado": False, "ok": True, "entrada": 0, "salida": 0, "extracto": ""},
              {"ts": "2026-11-11T10:04:00", "sesion": "a1b2c3", "agente": "Transcripción en la nube", "tarea": "transcripcion_nube", "tipo": "transcripcion_nube", "modelo": "gpt-transcribe", "host": "api.openai.com",
               "audio_s": 0, "trozos": 0, "bloqueado": True, "error": "local", "ok": False, "entrada": 0, "salida": 0, "extracto": ""},
              {"ts": "2026-11-11T10:05:00", "sesion": "a1b2c3", "agente": "Coordinador", "tarea": "equipo", "tipo": "llamada", "modelo": "haiku", "bloqueado": False, "ok": True, "entrada": 1000, "salida": 200, "extracto": ""}]
    resumen = {"llamadas": 1, "entrada": 1000, "salida": 200, "bloqueadas": 1, "nube": {"lotes": 1, "trozos": 14, "audio_s": 97.4, "fallos": 0, "bloqueadas": 1}}
    abrir(edge, pagina)
    edge.js("window.__RESP['GET /api/envios'] = { status: 200, body: %s }; document.querySelector('#b-ajustes').click(); 1" % json.dumps({"envios": envios, "resumen": resumen}))
    time.sleep(1.0)
    r = ev(edge, "({ res: document.querySelector('#aj-registro-res').textContent, filas: [...document.querySelectorAll('#aj-registro-lista .aj-reg-f')].map((f) => f.textContent) })")
    assert r["res"] == "1 llamadas en total · 1,2k tokens · 1 bloqueadas por el modo local · 2 min de audio a la nube"
    nube = [f for f in r["filas"] if "Transcripción en la nube" in f]
    assert len(nube) == 3 and any("96 s de audio en 13 trozos → api.openai.com" in f for f in nube)
    assert any("prueba de conexión → api.openai.com" in f for f in nube) and any("bloqueada por el modo solo local" in f for f in nube)
    assert any("Coordinador" in f or "Capitán" in f for f in r["filas"])
    # en la reunión: los eventos `envio` del WebSocket pisan `tipo`, y aun así se separan por `tarea`
    abrir(edge, pagina, estado="grabando")
    for e in envios:
        edge.js("window.__emitir(Object.assign({}, %s, { tipo: 'envio' })); 1" % json.dumps(e))
    time.sleep(0.4)
    r = ev(edge, "({ res: document.querySelector('#ses-env-res').textContent, filas: [...document.querySelectorAll('#ses-env-lista .aj-reg-f')].map((f) => f.textContent) })")
    assert r["res"] == "1 llamadas a Claude · 1,2k tokens · 2 min de audio a la nube · 1 bloqueadas por el modo local"
    assert len(r["filas"]) == 4 and sum("Transcripción en la nube" in f for f in r["filas"]) == 3


# ============================================================ consentimiento
def test_portada_dice_que_el_audio_sale_con_el_motor_nube(edge, pagina):
    abrir(edge, pagina, info("local"))
    edge.js("AP.nube.refrescarPortada()")
    local = ev(edge, "({ oculto: document.querySelector('#i-nube').hidden, title: document.querySelector('label.ini-aviso').title, nota: document.querySelector('.ini-aviso-nota').textContent })")
    assert local["oculto"] is True and local["title"] == "La app no guarda audio, pero sí el texto, y la transcripción se enviará a Claude para analizarla."
    abrir(edge, pagina, info("nube", CLAVE_FICHERO, host="api.ejemplo.test"))
    edge.js("AP.nube.refrescarPortada()")
    r = ev(edge, """(() => { const p = document.querySelector('#i-nube'), r = p.getBoundingClientRect(); return { oculto: p.hidden, texto: p.textContent, alto: r.height, ancho: r.width, barra: document.querySelector('.ini-barra').getBoundingClientRect().width,
      title: document.querySelector('label.ini-aviso').title, nota: document.querySelector('.ini-aviso-nota').textContent, desborde: document.documentElement.scrollWidth > document.documentElement.clientWidth }; })()""")
    assert r["oculto"] is False and r["texto"] == "La transcripción se hace en la nube: el audio se envía a api.ejemplo.test."
    assert "api.ejemplo.test" in r["title"] and "nube" in r["title"] and r["title"] != local["title"] and "api.ejemplo.test" in r["nota"] and not r["desborde"]
    # al cambiar el motor en Ajustes, la portada lo refleja al cerrar el diálogo
    abrir_ajustes(edge, pagina, info("local"))
    edge.js("window.__INFO = %s; document.querySelector('#d-ajustes').close(); 1" % json.dumps(info("nube", CLAVE_FICHERO)))
    time.sleep(0.5)
    assert edge.js("document.querySelector('#i-nube').hidden") is False


def _aviso(tmp_path, nombre, inf):
    html = (WEB / "aviso.html").read_text(encoding="utf-8")
    stub = """<script>
(() => {
  const INFO = %s;
  window.fetch = async (u) => ({ ok: true, status: 200, json: async () => (/\\/api\\/info/.test(u) ? INFO : /\\/api\\/aviso$/.test(u) ? { tema: 'Revisión de ejemplo', proyectos: ['Alfa Demo'], proyecto: '', idioma: 'auto', caduca_s: 600 } : {}) });
})();
</script>""" % json.dumps(inf)
    html = html.replace('"/static/', f'"{WEB.as_uri()}/').replace("<head>", "<head>\n" + stub + "\n" + _fuentes(), 1)
    ruta = tmp_path / nombre
    ruta.write_text(html, encoding="utf-8")
    return ruta


@pytest.mark.parametrize("motor,visible", [("local", False), ("nube", True)])
def test_aviso_de_llamada_dice_que_el_audio_sale_con_el_motor_nube(edge, tmp_path, motor, visible):
    ruta = _aviso(tmp_path, f"aviso-{motor}.html", info(motor, CLAVE_FICHERO, host="api.ejemplo.test"))
    edge.abrir(ruta.as_uri(), listo="!window.__viejo && !!window.__avisoListo")
    time.sleep(0.5)
    r = ev(edge, """(() => { const p = document.querySelector('#av-nube'), c = document.querySelector('#av-avisado'); return { oculto: p.hidden, texto: p.textContent, alto: p.getBoundingClientRect().height,
      desc: c.getAttribute('aria-describedby'), antes: !!(p.compareDocumentPosition(c) & Node.DOCUMENT_POSITION_FOLLOWING), desborde: document.documentElement.scrollWidth > document.documentElement.clientWidth }; })()""")
    assert r["desborde"] is False and r["desc"] == "av-nube" and r["antes"] is True            # el aviso se lee antes que la casilla y la describe
    if visible:
        assert r["oculto"] is False and r["alto"] > 0 and r["texto"] == "La transcripción se hace en la nube: el audio se envía a api.ejemplo.test."
    else:
        assert r["oculto"] is True and r["texto"] == ""


def test_aviso_sin_datos_de_info_queda_como_siempre(edge, tmp_path):
    ruta = _aviso(tmp_path, "aviso-viejo.html", {"simulacion": False})
    edge.abrir(ruta.as_uri(), listo="!window.__viejo && !!window.__avisoListo")
    time.sleep(0.4)
    assert edge.js("document.querySelector('#av-nube').hidden") is True


# ============================================================ consola
def test_sin_errores_de_consola(edge, pagina):
    desde = len(edge.eventos)
    abrir_ajustes(edge, pagina, INFO_ANTERIOR)                   # servidor anterior: sin claves ni bloque `nube`
    r = ev(edge, "({ oculto: document.querySelector('#aj-nube').hidden, chip: document.querySelector('#r-motor').hidden, portada: document.querySelector('#i-nube').hidden })")
    assert r == {"oculto": True, "chip": True, "portada": True}
    edge.js("document.querySelector('#s-guardar').click(); 1")
    time.sleep(0.4)
    puts = peticiones(edge, r"/api/config", "PUT")
    assert puts and not (set(json.loads(puts[0]["b"])) & set(NUBE_CFG))
    abrir_ajustes(edge, pagina, info("nube", CLAVE_FICHERO))
    elegir_motor(edge, "local")
    elegir_motor(edge, "nube")
    tick(edge, estado="listo", nube=None)
    tick(edge, estado="listo", nube={"estado": "respaldo", "mensaje": "x"})
    edge.js("1")
    malos = [e for e in edge.eventos[desde:]
             if e.get("method") == "Runtime.exceptionThrown"
             or (e.get("method") == "Runtime.consoleAPICalled" and e["params"].get("type") == "error")]
    assert not malos, json.dumps(malos)[:800]
