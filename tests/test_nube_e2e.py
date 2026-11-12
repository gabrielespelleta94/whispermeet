"""Extremo a extremo de la transcripción en la nube: la interfaz REAL (web/index.html + nube.js, servida por el servidor real) en un Edge sin cabeza, contra el
servidor REAL de la app (subproceso `servir_falso_contexto.py`: modelo, micro y ventana falsos; carpeta de datos temporal) y el servidor de nube falso en
127.0.0.1. SIN dobles de `fetch`: lo que se prueba es que interfaz y servidor se entienden en el camino del primer uso (motor → clave → probar ok →
probar 401 → quitar clave). Ni audio, ni Whisper, ni `claude`, ni red fuera de 127.0.0.1; la clave es ficticia."""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

from _visual_harness import Edge
from servidor_nube_falso import CENTINELA_MENSAJE, ServidorNubeFalso

AQUI = Path(__file__).resolve().parent
RAIZ = AQUI.parent
CLAVE = "sk-ficticia-0000000000"
TEXTO_401 = "La nube rechaza la clave (401)."          # §2.7 del diseño; en «Probar» sigue «Revisa la clave.»
windows = pytest.mark.skipif(sys.platform != "win32", reason="La clave se cifra con DPAPI: solo Windows")


# La enumeración REAL de dispositivos (pyaudiowpatch, GET /api/dispositivos que Ajustes pide al abrirse) tira el proceso con un acceso a memoria
# inválido (0xC0000005) de forma intermitente en este equipo; aquí no hay audio, así que el subproceso la sustituye por una lista vacía.
LANZADOR = (
    "import runpy, sys; import apuntes.servidor as s; "
    "s.listar_dispositivos = lambda: {'error': '', 'entradas': [], 'salidas': [], 'mic_defecto': None, 'sistema_defecto': None}; "
    "ruta = sys.argv[1]; sys.argv = [ruta] + sys.argv[2:]; sys.path.insert(0, %r); runpy.run_path(ruta, run_name='__main__')" % str(AQUI))


def _puerto() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class AppReal:
    """El servidor real de la app como subproceso, con TODO su estado en `base` (temporal)."""

    def __init__(self, base: Path):
        self.base = base
        self.datos = base / "datos"
        self.datos.mkdir()
        (base / "proyectos").mkdir()
        (base / "carpeta-falsa").mkdir()
        self.config = self.datos / "config.json"
        self.config.write_text(json.dumps({"knowledge": "", "raiz_proyectos": str(base / "proyectos"), "proyectos_extra": []}), encoding="utf-8")
        self.salida = base / "servidor.log"
        self.proc: subprocess.Popen | None = None
        self.url = self.token = self.base_url = ""

    def arrancar(self) -> None:
        a = self.base
        orden = [sys.executable, "-c", LANZADOR, str(AQUI / "servir_falso_contexto.py"), "--retardo", "0", "--carpeta-falsa", str(a / "carpeta-falsa"), "--",
                 "--sin-ventana", "--simular", str(RAIZ / "pruebas" / "reunion-ficticia.txt"), "--raiz", str(a / "proyectos"),
                 "--cache", str(a / "cache"), "--consumo", str(a / "consumo.jsonl"), "--config", str(self.config), "--planes", str(a / "planes"),
                 "--sesiones", str(a / "sesiones"), "--checks", str(a / "checks"), "--bandeja", str(a / "bandeja"), "--backlog", str(a / "backlog"),
                 "--copias", str(a / "copias"), "--datos", str(a / "ola4"), "--tipos", str(a / "tipos")]
        env = dict(os.environ, WHISPERMEET_REGISTRO=str(a / "registro.log"), WHISPERMEET_NUBE_SOLO_LOOPBACK="1", PYTHONIOENCODING="utf-8")
        env.pop("WHISPERMEET_CLAVE_NUBE", None)
        with open(self.salida, "wb") as f:
            self.proc = subprocess.Popen(orden, cwd=RAIZ, stdout=f, stderr=subprocess.STDOUT, env=env, stdin=subprocess.DEVNULL)
        limite = time.time() + 240
        while time.time() < limite:
            for linea in self.salida.read_text(encoding="utf-8", errors="replace").splitlines():
                if linea.startswith("APUNTES_URL="):
                    self.url = linea.split("=", 1)[1].strip()
                    base_url, self.token = self.url.split("/?t=")
                    self.base_url = base_url
                    return
            if self.proc.poll() is not None:
                break
            time.sleep(0.25)
        raise AssertionError("el servidor real no arrancó:\n" + self.salida.read_text(encoding="utf-8", errors="replace")[-1500:])

    def info(self) -> dict:
        return json.loads(self.info_texto())

    def info_texto(self) -> str:
        req = urllib.request.Request(self.base_url + "/api/info", headers={"X-Token": self.token})
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.read().decode("utf-8")

    def parar(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=10)
            except Exception:
                self.proc.kill()
                self.proc.wait(timeout=10)


@pytest.fixture
def nube_falsa():
    with ServidorNubeFalso() as s:
        yield s


@pytest.fixture
def app(tmp_path):
    (tmp_path / "app").mkdir()
    a = AppReal(tmp_path / "app")
    try:
        a.arrancar()
        yield a
    finally:
        a.parar()


@pytest.fixture
def edge(tmp_path):
    e = None
    try:
        e = Edge(tmp_path / "edge", _puerto(), ancho=1280, alto=900)
        yield e
    finally:
        if e is not None:
            e.cerrar()


def esperar(edge, expr, que, segundos=20):
    """Espera a que `expr` (JS) sea verdadera; si no, falla diciendo qué se esperaba."""
    fin = time.time() + segundos
    while time.time() < fin:
        try:
            if edge.js(expr):
                return
        except RuntimeError:
            pass
        time.sleep(0.15)
    raise AssertionError(f"la interfaz no llegó a: {que}")


def escribir(edge, selector, valor):
    edge.js("(() => { const e = document.querySelector(%s); e.focus(); e.value = %s; e.dispatchEvent(new Event('input', { bubbles: true })); "
            "e.dispatchEvent(new Event('change', { bubbles: true })); return 1; })()" % (json.dumps(selector), json.dumps(valor)))


def pulsar(edge, selector):
    edge.js("document.querySelector(%s).click(); 1" % json.dumps(selector))


def abrir_ajustes(edge):
    pulsar(edge, "#b-ajustes")
    esperar(edge, "document.querySelector('#d-ajustes').open && !document.querySelector('#aj-nube').hidden", "el diálogo de Ajustes abierto con el bloque de la nube")


def ficheros_con_la_clave(raiz: Path, excluir: Path) -> list[str]:
    """Todo fichero bajo `raiz` (menos el perfil del navegador) que lleve la clave en claro, en UTF-8 o UTF-16."""
    agujas = (CLAVE.encode(), CLAVE.encode("utf-16-le"))
    malos = []
    for p in raiz.rglob("*"):
        if p.is_file() and excluir not in p.parents:
            try:
                datos = p.read_bytes()
            except OSError:
                continue
            if any(a in datos for a in agujas):
                malos.append(str(p.relative_to(raiz)))
    return malos


@windows
def test_primer_uso_de_la_nube_con_la_interfaz_y_el_servidor_reales(app, nube_falsa, edge, tmp_path):
    secreto = app.datos / "secreto-nube.dpapi"
    edge.abrir(app.url, listo="!window.__viejo && !!window.AP && !!window.AP.nube && !!document.querySelector('.nodo')")
    edge.js("localStorage.clear(); sessionStorage.clear(); 1")

    # ---- 1. Elegir «En la nube», confirmar que el audio sale, poner la dirección del falso y guardar
    abrir_ajustes(edge)
    edge.js("(() => { const r = document.querySelector('input[name=transcripcion_motor][value=nube]'); r.checked = true; "
            "r.dispatchEvent(new Event('change', { bubbles: true })); return 1; })()")
    esperar(edge, "!document.querySelector('#aj-nube-acepto-fila').hidden", "la casilla de confirmación visible al elegir la nube")
    pulsar(edge, "#aj-nube-acepto")
    escribir(edge, "[name=nube_url_base]", nube_falsa.url_base)
    pulsar(edge, "#s-guardar")
    try:
        esperar(edge, "!document.querySelector('#d-ajustes').open", "el diálogo cerrado tras guardar")
    except AssertionError:
        raise AssertionError("PASO 1: el servidor o la interfaz rechazaron el guardado. Errores visibles: " + str(edge.js(
            "[...document.querySelectorAll('#d-ajustes .error:not([hidden])')].map((e) => e.id + ': ' + e.textContent).concat([document.querySelector('#s-error').hidden ? '' : document.querySelector('#s-error').textContent])")))
    info = app.info()
    assert info["config"]["transcripcion_motor"] == "nube", "PASO 1: /api/info no dice motor «nube»: " + str(info["config"].get("transcripcion_motor"))
    assert info["nube"]["host"] == "127.0.0.1", "PASO 1: /api/info › nube.host no es 127.0.0.1: " + str(info.get("nube"))
    assert info["config"]["nube_url_base"] == nube_falsa.url_base

    # ---- 2. Escribir la clave ficticia y guardarla con su botón
    abrir_ajustes(edge)
    assert edge.js("document.querySelector('#aj-nube-clave-estado').textContent") == "Sin clave"
    escribir(edge, "#aj-nube-clave", CLAVE)
    pulsar(edge, "#aj-nube-clave-guardar")
    esperar(edge, "document.querySelector('#aj-nube-clave-estado').textContent.includes('guardada')", "el estado «Clave guardada…»")
    estado = edge.js("document.querySelector('#aj-nube-clave-estado').textContent")
    assert estado == "Clave guardada cifrada en este equipo", "PASO 2: estado visible inesperado: " + estado
    assert edge.js("document.querySelector('#aj-nube-clave').value") == "", "PASO 2: el campo de la clave no quedó vacío"
    assert edge.js("document.querySelector('#aj-nube-clave-error').hidden") is True
    assert secreto.is_file(), "PASO 2: no existe secreto-nube.dpapi junto al config.json"
    assert CLAVE.encode() not in secreto.read_bytes() and CLAVE.encode("utf-16-le") not in secreto.read_bytes(), "PASO 2: la clave está en claro en el fichero cifrado"
    texto_info = app.info_texto()
    assert CLAVE not in texto_info, "PASO 2: la clave aparece en GET /api/info"
    assert app.info()["nube"]["clave"] == {"puesta": True, "origen": "fichero", "error": ""}
    assert CLAVE not in app.config.read_text(encoding="utf-8"), "PASO 2: la clave está en config.json"
    assert CLAVE not in edge.js("document.documentElement.outerHTML"), "PASO 2: la clave quedó en el DOM"
    assert CLAVE not in json.dumps(edge.js("JSON.stringify([localStorage, sessionStorage])"))

    # ---- 3. «Probar» con el falso respondiendo bien (el campo está vacío: la clave sale del fichero guardado)
    nube_falsa.ok("hola", idiomas=["es"])
    pulsar(edge, "#aj-nube-probar")
    esperar(edge, "document.querySelector('#aj-nube-probar-res').dataset.estado", "un resultado de «Probar»", 30)
    res = edge.js("({ e: document.querySelector('#aj-nube-probar-res').dataset.estado, t: document.querySelector('#aj-nube-probar-res').textContent })")
    assert res["e"] == "ok" and res["t"].startswith("Funciona"), "PASO 3: la interfaz no muestra éxito: " + json.dumps(res, ensure_ascii=False)
    assert edge.js("document.querySelector('#aj-nube-probar').textContent") == "Probar conexión" and edge.js("document.querySelector('#aj-nube-probar').disabled") is False
    llegadas = list(nube_falsa.peticiones)
    assert len(llegadas) == 1, f"PASO 3: el falso recibió {len(llegadas)} peticiones, no 1: {[p['ruta'] for p in llegadas]}"
    p = llegadas[0]
    assert p["ruta"] == "/v1/audio/transcriptions", "PASO 3: ruta inesperada " + p["ruta"]
    assert p["authorization"] == f"Bearer {CLAVE}", "PASO 3: cabecera Authorization inesperada: " + str(p["authorization"])
    assert p["fichero"] and p["fichero"]["riff_wave"], "PASO 3: la petición no lleva un fichero WAV: " + str(p["fichero"])

    # ---- 4. Un 401 programado: mensaje fijo de «clave rechazada», sin el cuerpo del error
    nube_falsa.error(401, code="invalid_api_key", param=None)
    pulsar(edge, "#aj-nube-probar")
    esperar(edge, "document.querySelector('#aj-nube-probar-res').dataset.estado === 'error'", "el error de «Probar»", 30)
    texto = edge.js("document.querySelector('#aj-nube-probar-res').textContent")
    assert TEXTO_401 in texto and "Revisa la clave" in texto, "PASO 4: mensaje de clave rechazada inesperado: " + texto
    for prohibido in (CENTINELA_MENSAJE, "Incorrect API key", CLAVE, "invalid_request_error", "invalid_api_key"):
        assert prohibido not in texto, f"PASO 4: el mensaje deja pasar el cuerpo del error ({prohibido!r}): {texto}"
    assert len(nube_falsa.peticiones) == 2

    # ---- 5. Quitar la clave con su botón
    pulsar(edge, "#aj-nube-clave-quitar")
    esperar(edge, "document.querySelector('#aj-nube-clave-estado').textContent === 'Sin clave'", "el estado «Sin clave»")
    assert not secreto.exists(), "PASO 5: secreto-nube.dpapi sigue existiendo tras quitar la clave"
    assert app.info()["nube"]["clave"]["puesta"] is False

    # ---- en ningún momento la clave estuvo en claro en el disco de la prueba (menos el perfil del navegador)
    assert ficheros_con_la_clave(tmp_path, tmp_path / "edge") == []
