"""Apoyo de las pruebas visuales (DESIGN-visual.md): la interfaz REAL (`web/index.html` con todos sus scripts) en un Edge/Chrome sin cabeza, sin servidor ni modelo.

`fetch` y `WebSocket` se sustituyen por dobles: la página arranca con una foto real del backend en modo falso (`fixtures/visual_snapshot.json`: datos ficticios) y
los eventos (`tarea`, `tarjetas`…) se inyectan con `__emitir`. Se mide en tiempo real con el protocolo de DevTools (animaciones, capas y fotogramas no avanzan con
el tiempo virtual de `--dump-dom`). Se omite si no hay navegador ni la librería `websockets`."""
from __future__ import annotations

import base64
import json
import shutil
import subprocess
import time
import urllib.request
from pathlib import Path

import pytest

WEB = Path(__file__).resolve().parent.parent / "web"
FOTO = Path(__file__).resolve().parent / "fixtures" / "visual_snapshot.json"

STUB = """<script>
(() => {
  const INFO = { simulacion: false, config: { excluir_captura: true, modelos: { digest: "haiku", equipo: "haiku", periodico: "haiku", final: "sonnet", contradicciones_confirmar: "sonnet", consulta: "haiku", pulido: "opus" } } };
  window.fetch = async (u) => ({ ok: true, json: async () => (/\\/api\\/info/.test(u) ? INFO : /ventana/.test(u) ? { nativa: false } : {}) });
  window.WebSocket = class { constructor() { window.__ws = this; setTimeout(() => this.onopen && this.onopen(), 0); } send() {} close() {} };
  window.__emitir = (d) => window.__ws.onmessage({ data: JSON.stringify(d) });
})();
</script>"""


def navegador() -> str | None:
    for ruta in (r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe", r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
                 r"C:\Program Files\Google\Chrome\Application\chrome.exe"):
        if Path(ruta).is_file():
            return ruta
    return shutil.which("msedge") or shutil.which("chrome") or shutil.which("chromium")


def foto(**cambios) -> dict:
    d = json.loads(FOTO.read_text(encoding="utf-8"))
    d.update(cambios)
    return d


def _fuentes() -> str:   # fuentes.css usa rutas absolutas /static/…: bajo file:// no resolverían y las medidas saldrían con la tipografía de respaldo
    css = (WEB / "fuentes.css").read_text(encoding="utf-8").replace('url("/static/', f'url("{WEB.as_uri()}/')
    return "<style>" + css + "</style>"


def pagina_html(destino: Path) -> Path:
    html = (WEB / "index.html").read_text(encoding="utf-8")
    html = html.replace('"/static/', f'"{WEB.as_uri()}/').replace("<head>", "<head>\n" + STUB + "\n" + _fuentes(), 1)
    destino.write_text(html, encoding="utf-8")
    return destino


class Edge:
    """Un Edge sin cabeza con DevTools; `js` evalúa (con `await`) y devuelve el valor."""

    def __init__(self, tmp: Path, puerto: int, ancho=1440, alto=900, reducido=False, esquema="dark"):
        exe = navegador()
        if not exe:
            pytest.skip("No hay Edge ni Chrome.")
        try:
            from websockets.sync.client import connect
        except Exception:  # pragma: no cover
            pytest.skip("Falta la librería websockets.")
        args = [exe, "--headless=new", f"--remote-debugging-port={puerto}", f"--user-data-dir={tmp / ('perfil' + str(puerto))}", "--no-first-run",
                "--no-default-browser-check", f"--window-size={ancho},{alto}", "--remote-allow-origins=*", "--allow-file-access-from-files"]
        if reducido:
            args.append("--force-prefers-reduced-motion")
        self.proc = subprocess.Popen(args + ["about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        alvo = None
        for _ in range(80):
            try:
                alvo = [a for a in json.load(urllib.request.urlopen(f"http://127.0.0.1:{puerto}/json")) if a["type"] == "page"][0]
                break
            except Exception:
                time.sleep(0.25)
        if not alvo:
            self.proc.terminate()
            pytest.skip("El navegador no abrió DevTools.")
        self.ws = connect(alvo["webSocketDebuggerUrl"], max_size=None)
        self.n = 0
        self._t_vis = 0.0
        self.eventos: list[dict] = []
        self.cmd("Page.enable")
        self.cmd("Runtime.enable")
        self.cmd("Emulation.setDeviceMetricsOverride", width=ancho, height=alto, deviceScaleFactor=1, mobile=False)
        self.cmd("Emulation.setEmulatedMedia", features=[{"name": "prefers-color-scheme", "value": esquema}])

    def cmd(self, metodo, **params):
        self.n += 1
        i = self.n
        self.ws.send(json.dumps({"id": i, "method": metodo, "params": params}))
        while True:
            r = json.loads(self.ws.recv())
            if r.get("id") == i:
                if "error" in r:
                    raise RuntimeError(f"{metodo}: {r['error']}")
                return r.get("result", {})
            self.eventos.append(r)

    def despertar(self):
        """El Edge sin cabeza pasa a `visibilityState == "hidden"` por su cuenta (a los ~8-9 s, con la ventana en estado normal; no depende de las ventanas que
        la tapan: lo probamos con CalculateNativeWinOcclusion desactivado). Oculta, `requestAnimationFrame` no corre y la interfaz no pinta lo que programa con él (las
        tarjetas del equipo): falla la prueba y las siguientes del módulo. `Page.bringToFront` la devuelve a visible; se comprueba como mucho cada 0,5 s."""
        ahora = time.monotonic()
        if ahora - self._t_vis < 0.5:
            return
        self._t_vis = ahora
        r = self.cmd("Runtime.evaluate", expression="document.visibilityState", returnByValue=True)
        if r.get("result", {}).get("value") == "hidden":
            self.cmd("Page.bringToFront")
            self.ocultaciones = getattr(self, "ocultaciones", 0) + 1

    def js(self, expr: str):
        self.despertar()
        r = self.cmd("Runtime.evaluate", expression=expr, returnByValue=True, awaitPromise=True, timeout=90000)
        if "exceptionDetails" in r:
            raise RuntimeError(json.dumps(r["exceptionDetails"], ensure_ascii=False)[:1200])
        return r["result"].get("value")

    def abrir(self, url: str, listo: str = "!window.__viejo && !!window.__ws && !!document.querySelector('.nodo')"):
        try:
            self.js("window.__viejo = true; 1")   # marca de la página anterior: la nueva no la tiene (evita dar por lista la que se está sustituyendo)
        except RuntimeError:
            pass
        self.cmd("Page.navigate", url=url)
        for _ in range(100):
            time.sleep(0.15)
            try:
                if self.js(listo):
                    return
            except RuntimeError:
                pass
        raise AssertionError("la página no arrancó")

    def captura(self, ruta: Path):
        ruta.write_bytes(base64.b64decode(self.cmd("Page.captureScreenshot", format="png")["data"]))

    def cerrar(self):
        try:
            self.ws.close()
        finally:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=10)
            except Exception:
                self.proc.kill()
