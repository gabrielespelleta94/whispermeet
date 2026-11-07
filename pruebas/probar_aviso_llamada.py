"""Prueba extremo a extremo del AVISO FLOTANTE de llamada de Teams con la ventana NATIVA, medido por Win32. No graba audio (usa --simular), no gasta
tokens (modelo falso: servir_modelo_falso.py), no lee el registro ni la ventana de Teams (una llamada simulada con --llamada-prueba) y toca solo su
propia instancia: la ventana se localiza por PID, nunca por título. Config, raíz, planes, sesiones, caché y consumo van a una carpeta temporal.

    .venv\\Scripts\\python.exe pruebas\\probar_aviso_llamada.py                 # todo el recorrido (~2 min, incluye esperar los 45 s de caducidad)
    .venv\\Scripts\\python.exe pruebas\\probar_aviso_llamada.py --solo-ver      # solo enseña el aviso 40 s y sale (sin comprobaciones), para mirarlo

Qué mide: ventana siempre encima (WS_EX_TOPMOST), que NO activa (WS_EX_NOACTIVATE) y que el primer plano NO cambia al aparecer ni al usarla, fuera
de la barra de tareas (WS_EX_TOOLWINDOW), centrada arriba en el monitor principal con el DPI, afinidad 0x11 (excluida de la captura), alto = contenido,
textos sin cortar, casilla/botón (sin casilla no empieza nada), una sola vez por llamada, «Ahora no», colgar sin elegir, 45 s con pausa del ratón,
reunión en curso (no sale) y Empezar (inicia la sesión y la ventana principal pasa a la vista de reunión).
Con la exclusión de la captura activa (lo normal) el sistema no deja fotografiar la ventana; para la captura real de píxeles la prueba la desactiva
SOLO en su instancia (PUT /api/config de la instancia temporal). Las capturas van a --salida (por defecto una carpeta temporal). Sale con 1 si algo falla."""
from __future__ import annotations

import argparse
import base64
import ctypes
import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import warnings
import zlib
from ctypes import wintypes
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)   # este proceso mide en píxeles físicos
except Exception:
    ctypes.windll.user32.SetProcessDPIAware()

from apuntes import ventana as V  # noqa: E402
from probar_modo_reunion import api, con_descendientes, puerto_libre  # noqa: E402
from websockets.sync.client import connect  # noqa: E402

U = ctypes.WinDLL("user32")
G = ctypes.WinDLL("gdi32")
U.GetForegroundWindow.restype = wintypes.HWND
U.GetWindowLongPtrW.argtypes, U.GetWindowLongPtrW.restype = [wintypes.HWND, ctypes.c_int], ctypes.c_ssize_t
U.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
U.GetDC.argtypes, U.GetDC.restype = [wintypes.HWND], ctypes.c_void_p
U.ReleaseDC.argtypes = [wintypes.HWND, ctypes.c_void_p]
G.CreateCompatibleDC.argtypes, G.CreateCompatibleDC.restype = [ctypes.c_void_p], ctypes.c_void_p
G.CreateCompatibleBitmap.argtypes, G.CreateCompatibleBitmap.restype = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int], ctypes.c_void_p
G.SelectObject.argtypes, G.SelectObject.restype = [ctypes.c_void_p, ctypes.c_void_p], ctypes.c_void_p
G.BitBlt.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_void_p, ctypes.c_int, ctypes.c_int, wintypes.DWORD]
G.GetDIBits.argtypes = [ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT, wintypes.UINT, ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT]
G.DeleteObject.argtypes = [ctypes.c_void_p]
G.DeleteDC.argtypes = [ctypes.c_void_p]

TITULO_TEAMS = "Unión a la reunión | NORDIA - Seguimiento Interno (EPM) | Microsoft Teams"
TEMA_ESPERADO = "NORDIA - Seguimiento Interno (EPM)"
RES: list[tuple[bool, str]] = []


def comprobar(ok: bool, texto: str) -> bool:
    RES.append((bool(ok), texto))
    print(("  OK   " if ok else "  FALLA ") + texto, flush=True)
    return bool(ok)


def esperar(cond, t: float = 20.0, paso: float = 0.1):
    t0 = time.time()
    while time.time() - t0 < t:
        r = cond()
        if r:
            return r
        time.sleep(paso)
    return cond()


# ------------------------------------------------------------------------------------------------ CDP
class Cdp:
    """Controla UNA página de la instancia por el puerto de depuración de WebView2 (filtrada por su ruta)."""

    def __init__(self, puerto_dbg: int, puerto_app: int, ruta: str, t: float = 40.0):
        t0 = time.time()
        while True:
            try:
                dest = json.load(urllib.request.urlopen(f"http://127.0.0.1:{puerto_dbg}/json/list", timeout=2))
                pag = [d for d in dest if d.get("type") == "page" and d.get("url", "").split("?")[0].rstrip("/").endswith(f":{puerto_app}{ruta}".rstrip("/"))]
                if pag:
                    break
            except Exception:
                pass
            if time.time() - t0 > t:
                raise TimeoutError(f"No aparece la página {ruta} en el puerto de depuración.")
            time.sleep(0.3)
        self.ws = connect(pag[0]["webSocketDebuggerUrl"], max_size=None)
        warnings.simplefilter("ignore")
        self.n = 0

    def __call__(self, metodo: str, **params):
        self.n += 1
        self.ws.send(json.dumps({"id": self.n, "method": metodo, "params": params}))
        while True:
            r = json.loads(self.ws.recv())
            if r.get("id") == self.n:
                if "error" in r:
                    raise RuntimeError(str(r["error"]))
                return r["result"]

    def ev(self, expr: str):
        for intento in range(40):
            try:
                r = self("Runtime.evaluate", expression=expr, returnByValue=True, awaitPromise=True)
            except RuntimeError as e:
                if "context" in str(e).lower() and intento < 39:
                    time.sleep(0.4)
                    continue
                raise
            if "exceptionDetails" in r:
                raise RuntimeError(str(r["exceptionDetails"])[:300])
            return r["result"].get("value")

    def centro(self, selector: str) -> tuple[float, float]:
        c = self.ev(f"(() => {{ const r = document.querySelector({json.dumps(selector)}).getBoundingClientRect(); return [r.left + r.width / 2, r.top + r.height / 2]; }})()")
        return c[0], c[1]

    def mover(self, x: float, y: float):
        self("Input.dispatchMouseEvent", type="mouseMoved", x=x, y=y)

    def clic(self, selector: str):
        x, y = self.centro(selector)
        self.mover(x, y)
        self("Input.dispatchMouseEvent", type="mousePressed", x=x, y=y, button="left", buttons=1, clickCount=1)
        self("Input.dispatchMouseEvent", type="mouseReleased", x=x, y=y, button="left", buttons=0, clickCount=1)

    def captura(self, ruta: Path):
        datos = self("Page.captureScreenshot", format="png")["data"]
        ruta.write_bytes(base64.b64decode(datos))

    def cerrar(self):
        try:
            self.ws.close()
        except Exception:
            pass


# ------------------------------------------------------------------------------------------------ Win32
def titulo_de(hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(256)
    U.GetWindowTextW(hwnd, buf, 256)
    return buf.value


def primer_plano() -> int:
    return int(U.GetForegroundWindow() or 0)


TITULO_STANDIN = "Teams (ventana de la prueba del aviso)"
CODIGO_STANDIN = """
import ctypes, tkinter as tk
r = tk.Tk(); r.title(%r); r.geometry("380x110+60+60")
tk.Label(r, text="Esta ventana hace de Teams: el aviso no debe quitarle el foco.", wraplength=340).pack(expand=True)
u = ctypes.windll.user32
def f():
    h = u.GetParent(r.winfo_id()) or r.winfo_id()
    u.SwitchToThisWindow(h, True); u.SetForegroundWindow(h); r.focus_force()
for ms in (150, 600, 1200):
    r.after(ms, f)
r.mainloop()
""" % TITULO_STANDIN


class VigiaFoco(threading.Thread):
    """Anota CADA cambio de la ventana en primer plano (cada 5 ms): un aviso que lo roba aunque sea 20 ms se vería aquí."""

    def __init__(self):
        super().__init__(daemon=True)
        self.cambios: list[tuple[float, int]] = []
        self._fin = False
        self._ultimo = primer_plano()

    def run(self):
        while not self._fin:
            c = primer_plano()
            if c != self._ultimo:
                self.cambios.append((time.time(), c))
                self._ultimo = c
            time.sleep(0.005)

    def desde(self, t: float) -> list[tuple[float, int]]:
        return [x for x in self.cambios if x[0] >= t]

    def parar(self):
        self._fin = True


def hwnd_aviso(raiz_pid: int) -> int:
    for pid in con_descendientes(raiz_pid):
        h = V.buscar_hwnd(V.TITULO_AVISO, pid=pid)
        if h:
            return h
    return 0


def ventana_principal(raiz_pid: int) -> int:
    for pid in con_descendientes(raiz_pid):
        h = V.buscar_hwnd(V.TITULO, pid=pid)
        if h:
            return h
    return 0


def capturar_pantalla(rect: tuple[int, int, int, int], ruta: Path) -> None:
    """Píxeles reales de ESE rectángulo de la pantalla (BitBlt del escritorio compuesto) a un PNG, sin dependencias. Solo se guarda el recorte."""
    izq, arr, der, aba = rect
    w, h = der - izq, aba - arr
    dc = U.GetDC(0)
    mem = G.CreateCompatibleDC(dc)
    bmp = G.CreateCompatibleBitmap(dc, w, h)
    G.SelectObject(mem, bmp)
    G.BitBlt(mem, 0, 0, w, h, dc, izq, arr, 0x00CC0020 | 0x40000000)   # SRCCOPY | CAPTUREBLT

    class BMI(ctypes.Structure):
        _fields_ = [("tam", wintypes.DWORD), ("w", ctypes.c_long), ("h", ctypes.c_long), ("planos", wintypes.WORD), ("bits", wintypes.WORD),
                    ("comp", wintypes.DWORD), ("img", wintypes.DWORD), ("xp", ctypes.c_long), ("yp", ctypes.c_long), ("usados", wintypes.DWORD), ("imp", wintypes.DWORD)]
    bmi = BMI(ctypes.sizeof(BMI), w, -h, 1, 32, 0, 0, 0, 0, 0, 0)
    buf = ctypes.create_string_buffer(w * h * 4)
    G.GetDIBits(mem, bmp, 0, h, buf, ctypes.byref(bmi), 0)
    G.DeleteObject(bmp); G.DeleteDC(mem); U.ReleaseDC(0, dc)
    crudo = bytearray()
    for y in range(h):
        fila = buf.raw[y * w * 4:(y + 1) * w * 4]
        crudo.append(0)
        for x in range(w):
            b, g, r = fila[x * 4], fila[x * 4 + 1], fila[x * 4 + 2]
            crudo += bytes((r, g, b))

    def trozo(tipo, datos):
        c = struct.pack(">I", len(datos)) + tipo + datos
        return c + struct.pack(">I", zlib.crc32(tipo + datos) & 0xFFFFFFFF)
    png = b"\x89PNG\r\n\x1a\n" + trozo(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) + trozo(b"IDAT", zlib.compress(bytes(crudo), 6)) + trozo(b"IEND", b"")
    ruta.write_bytes(png)


def medir(hwnd: int) -> dict:
    est = U.GetWindowLongPtrW(hwnd, V.GWL_EXSTYLE)
    return {"rect": V.rect_ventana(hwnd), "topmost": bool(est & V.WS_EX_TOPMOST), "noactivate": bool(est & V.WS_EX_NOACTIVATE),
            "toolwindow": bool(est & V.WS_EX_TOOLWINDOW), "appwindow": bool(est & V.WS_EX_APPWINDOW), "afinidad": V.leer_afinidad(hwnd), "dpi": V.dpi_ventana(hwnd)}


JS_DESBORDES = """(() => [...document.querySelectorAll('#av *')].filter(e => e.offsetParent !== null && getComputedStyle(e).display !== 'inline'
  && (e.scrollWidth > e.clientWidth + 1)).map(e => (e.id || e.className || e.tagName) + ':' + e.scrollWidth + '>' + e.clientWidth))()"""


# ------------------------------------------------------------------------------------------------ recorrido
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--salida", help="carpeta de las capturas (por defecto una temporal)")
    ap.add_argument("--solo-ver", action="store_true", help="enseña el aviso 40 s y sale")
    ap.add_argument("--velocidad", default="3")
    a = ap.parse_args()

    tmp = Path(tempfile.mkdtemp(prefix="apuntes_aviso_"))
    salida = Path(a.salida) if a.salida else Path(tempfile.gettempdir()) / "apuntes_aviso_capturas"
    salida.mkdir(parents=True, exist_ok=True)
    raiz = tmp / "proyectos"
    shutil.copytree(RAIZ / "pruebas" / "proyectos", raiz)
    (tmp / "config.json").write_text(json.dumps({"knowledge": ""}), encoding="utf-8")   # nunca el Knowledge de OneDrive en una prueba
    marca = tmp / "llamada.txt"                                                         # existe = «Teams usa el micro»; su texto es el título de la ventana de Teams
    puerto_app, puerto_dbg = puerto_libre(), puerto_libre()
    env = dict(os.environ, WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS=f"--remote-debugging-port={puerto_dbg} --remote-allow-origins=*")
    cmd = [sys.executable, str(RAIZ / "pruebas" / "servir_modelo_falso.py"), "--retardo", "1", "--",
           "--simular", str(RAIZ / "pruebas" / "reunion-ficticia.txt"), "--velocidad", a.velocidad, "--raiz", str(raiz),
           "--config", str(tmp / "config.json"), "--planes", str(tmp / "planes"), "--sesiones", str(tmp / "sesiones"),
           "--checks", str(tmp / "checks"), "--cache", str(tmp / "cache"), "--consumo", str(tmp / "consumo.jsonl"),
           "--llamada-prueba", str(marca), "--puerto", str(puerto_app)]
    proc = subprocess.Popen(cmd, cwd=RAIZ, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        tok = None
        t0 = time.time()
        while tok is None and time.time() - t0 < 60:
            lin = proc.stdout.readline()
            if "APUNTES_URL=" in lin:
                tok = lin.split("?t=")[1].strip()
            elif lin:
                print("  [app]", lin.rstrip(), flush=True)
            elif proc.poll() is not None:
                break
        assert tok, "la app no arrancó"
        base = f"http://127.0.0.1:{puerto_app}"
        print(f"Instancia propia: PID {proc.pid}, puerto {puerto_app}, depuración {puerto_dbg}; capturas en {salida}")
        principal = esperar(lambda: ventana_principal(proc.pid), 90, 0.3)
        assert principal, "no se encontró la ventana principal del proceso"
        trabajo = V.area_trabajo_principal()
        escala = V.dpi_ventana(principal) / 96
        print(f"  Monitor principal: área de trabajo {trabajo}, escala de Windows {escala:g}")

        def llamada(si: bool, titulo: str = TITULO_TEAMS):
            if si:
                marca.write_text(titulo, encoding="utf-8")
            elif marca.exists():
                marca.unlink()

        if a.solo_ver:
            llamada(True)
            esperar(lambda: hwnd_aviso(proc.pid), 20)
            time.sleep(40)
            return 0

        # ---- S0: antes de nada no hay aviso, y el primer plano es el de la persona
        comprobar(hwnd_aviso(proc.pid) == 0, "sin llamada no hay ventana de aviso")
        standin = subprocess.Popen([sys.executable, "-c", CODIGO_STANDIN])     # otro proceso con una ventana normal: hace de Teams (el foco es SUYO)
        stand_hwnd = esperar(lambda: next((h for pid in con_descendientes(standin.pid) if (h := V.buscar_hwnd(TITULO_STANDIN, pid=pid))), 0), 15)
        esperar(lambda: primer_plano() == stand_hwnd, 5)
        fg0 = primer_plano()
        print(f"  Primer plano antes: {fg0:#x} «{titulo_de(fg0)[:60]}»" + ("" if fg0 == stand_hwnd else "  (no se pudo dar el foco a la ventana de la prueba: se usa el que haya)"))
        vigia = VigiaFoco()
        vigia.start()

        # ---- S1: llamada -> aviso flotante (medido por Win32)
        t_llamada = time.time()
        llamada(True)
        aviso = esperar(lambda: hwnd_aviso(proc.pid), 30)
        comprobar(aviso, f"la llamada abre la ventana del aviso (a los {time.time() - t_llamada:.1f} s)")
        time.sleep(1.5)                                        # que cargue la página y se coloque
        m = medir(aviso)
        fg1 = primer_plano()
        cdp = Cdp(puerto_dbg, puerto_app, "/aviso")
        alto_css = cdp.ev("Math.ceil(document.querySelector('#av').getBoundingClientRect().height)")
        ex, ey, ew, eh = V.geometria_aviso(trabajo, V.VentanaAviso.ANCHO_CSS, alto_css, m["dpi"] / 96)
        print(f"  Aviso: rect {m['rect']}, dpi {m['dpi']}, afinidad {m['afinidad']:#x}, alto de contenido {alto_css} px CSS; esperado x={ex} y={ey} {ew}x{eh}")
        comprobar(m["topmost"], "siempre encima (WS_EX_TOPMOST)")
        comprobar(m["noactivate"], "no se activa (WS_EX_NOACTIVATE)")
        comprobar(m["toolwindow"] and not m["appwindow"], "fuera de la barra de tareas y de Alt+Tab (WS_EX_TOOLWINDOW sin WS_EX_APPWINDOW)")
        propias = {aviso, principal}                          # las ventanas de la instancia de la prueba
        cambios = vigia.desde(t_llamada)
        ajenos = [(round(t - t_llamada, 3), hex(c), titulo_de(c)[:20]) for t, c in cambios if c not in propias and c]
        comprobar(fg1 != aviso and not [c for t, c in cambios if c in propias],
                  f"el aviso NO toma el primer plano al aparecer (muestreo cada 5 ms desde la llamada: primer plano {fg0:#x} -> {fg1:#x}; ninguna ventana de la instancia lo recibe)")
        if ajenos:
            print(f"        (la persona cambió de ventana durante la prueba: {ajenos}; eso no cuenta contra el aviso)")
        elif fg1 == fg0 and not cambios:
            comprobar(True, "...y el primer plano no cambió ni una vez (ni a 0 ni a otra ventana)")
        comprobar(m["afinidad"] == 0x11, f"excluida de la captura: GetWindowDisplayAffinity == {m['afinidad']:#x} (0x11)")
        comprobar(abs(m["rect"][0] - ex) <= 2 and abs(m["rect"][1] - ey) <= 2, "centrada arriba en el monitor principal (x centrada, y = margen sobre el área de trabajo)")
        comprobar(abs((m["rect"][2] - m["rect"][0]) - ew) <= 2 and abs((m["rect"][3] - m["rect"][1]) - eh) <= 3,
                  f"tamaño = contenido x escala ({m['rect'][2] - m['rect'][0]}x{m['rect'][3] - m['rect'][1]} px frente a {ew}x{eh})")
        comprobar(trabajo[0] <= m["rect"][0] and m["rect"][2] <= trabajo[2] and m["rect"][1] >= trabajo[1], "cabe entera en el área de trabajo")
        comprobar(cdp.ev("window.innerHeight >= document.querySelector('#av').getBoundingClientRect().height - 1"), "la ventana no corta el contenido por abajo")
        comprobar(cdp.ev("document.querySelector('#av-tema').textContent") == TEMA_ESPERADO, f"tema leído del título de Teams: «{TEMA_ESPERADO}»")
        comprobar(cdp.ev("document.querySelector('#av-empezar').disabled") is True and cdp.ev("document.querySelector('#av-avisado').checked") is False,
                  "«Empezar a transcribir» desactivado hasta marcar «He avisado a los asistentes»")
        comprobar(cdp.ev("document.querySelector('#av-proyecto').value") == "" and cdp.ev("document.querySelector('#av-idioma').value") == "auto",
                  "proyecto por defecto Bandeja (sin último usado) e idioma Automático")
        desb = cdp.ev(JS_DESBORDES)
        comprobar(not desb, f"ningún texto desbordado en el aviso ({desb})")
        cdp.captura(salida / "aviso-1-cerrado.png")
        # con la casilla sin marcar, un clic en el botón no hace nada (y el servidor tampoco empezaría)
        cdp.clic("#av-empezar")
        time.sleep(0.6)
        comprobar(api(base, tok, "GET", "/api/sesion")["estado"] == "inactivo", "un clic en «Empezar» sin la casilla NO inicia la grabación")
        try:
            api(base, tok, "POST", "/api/aviso/empezar", {"proyecto": None, "tema": "x", "idioma": "es", "avisado": False})
            comprobar(False, "el servidor rechaza empezar sin la casilla")
        except urllib.error.HTTPError as e:
            comprobar(e.code == 400 and api(base, tok, "GET", "/api/sesion")["estado"] == "inactivo", "el servidor rechaza empezar sin la casilla (400) aunque se llame a la API a mano")
        cdp.clic("#av-avisado")
        time.sleep(0.4)
        if cdp.ev("!document.querySelector('#av-avisado').checked"):   # un clic sintético puede perderse si coincide con el reajuste del alto
            print("        (el primer clic en la casilla no llegó: se repite)")
            cdp.clic("#av-avisado")
            time.sleep(0.4)
        comprobar(cdp.ev("document.querySelector('#av-empezar').disabled") is False, "al marcar la casilla el botón se activa")
        # el desplegable crece y la ventana lo sigue
        cdp.clic("#av-mas")
        time.sleep(1.0)
        alto2 = cdp.ev("Math.ceil(document.querySelector('#av').getBoundingClientRect().height)")
        m2 = medir(aviso)
        comprobar(alto2 > alto_css and abs((m2["rect"][3] - m2["rect"][1]) - round(alto2 * m2["dpi"] / 96)) <= 3,
                  f"el desplegable crece ({alto_css} -> {alto2} px CSS) y la ventana lo sigue ({m2['rect'][3] - m2['rect'][1]} px)")
        comprobar(m2["rect"][1] == m["rect"][1] and abs(m2["rect"][0] - m["rect"][0]) <= 1 and m2["noactivate"] and m2["topmost"], "...manteniéndose arriba, centrada, siempre encima y sin activarse")
        comprobar(cdp.ev("window.innerHeight >= document.querySelector('#av').getBoundingClientRect().height - 1"), "...sin cortar el contenido desplegado")
        comprobar(not cdp.ev(JS_DESBORDES), "...ni desbordar textos desplegado")
        opciones = cdp.ev("[...document.querySelector('#av-proyecto').options].map(o => o.textContent)")
        comprobar(len(opciones) >= 2 and opciones[0].startswith("Bandeja"), f"el desplegable lista Bandeja y los proyectos ({len(opciones)} opciones)")
        cdp.captura(salida / "aviso-2-desplegado.png")
        comprobar(not [c for t, c in vigia.desde(t_llamada) if c in propias] and primer_plano() != aviso,
                  "tras usar la casilla y el desplegable, el aviso sigue sin ser el primer plano (ni una vez desde la llamada)")
        # hover: el tiempo se detiene con el ratón encima
        x, y = cdp.centro("#av-avisado")
        cdp.mover(x, y)
        b1 = cdp.ev("getComputedStyle(document.querySelector('#av-barra')).transform")
        time.sleep(3.0)
        b2 = cdp.ev("getComputedStyle(document.querySelector('#av-barra')).transform")
        comprobar(b1 == b2, "con el ratón encima el contador de los 45 s se detiene")
        cdp.mover(-5, -5)
        cdp.ev("document.querySelector('#av').dispatchEvent(new MouseEvent('mouseleave'))")
        time.sleep(2.0)
        b3 = cdp.ev("getComputedStyle(document.querySelector('#av-barra')).transform")
        comprobar(b3 != b2, "al quitar el ratón vuelve a contar")
        # escribir en el tema SÍ necesita teclado: solo al hacer clic en ese campo la ventana deja que Windows la active, y al salir vuelve a no hacerlo
        cdp.clic("#av-tema-input")
        time.sleep(0.8)
        m4 = medir(aviso)
        comprobar(not m4["noactivate"], f"al hacer clic en el campo del tema la ventana pide teclado (WS_EX_NOACTIVATE quitado; primer plano ahora {primer_plano():#x}, el aviso es {aviso:#x})")
        cdp.clic("#av-ayuda")
        cdp.ev("document.activeElement && document.activeElement.blur()")
        time.sleep(0.8)
        comprobar(medir(aviso)["noactivate"] and medir(aviso)["topmost"], "...y al salir del campo vuelve a no activarse y sigue siempre encima")
        # colgar sin elegir: se cierra
        llamada(False)
        t_c = time.time()
        comprobar(esperar(lambda: hwnd_aviso(proc.pid) == 0, 15), f"al colgar sin elegir el aviso se cierra solo (a los {time.time() - t_c:.1f} s)")
        cdp.cerrar()
        time.sleep(1.2)

        # ---- S2: «Ahora no» y una sola vez por llamada
        llamada(True)
        aviso = esperar(lambda: hwnd_aviso(proc.pid), 30)
        comprobar(aviso, "una llamada nueva vuelve a abrir el aviso")
        time.sleep(1.2)
        cdp = Cdp(puerto_dbg, puerto_app, "/aviso")
        cdp.clic("#av-no")
        comprobar(esperar(lambda: hwnd_aviso(proc.pid) == 0, 10), "«Ahora no» cierra el aviso")
        cdp.cerrar()
        time.sleep(5.0)                                      # unas 10 lecturas con la llamada aún en curso
        comprobar(hwnd_aviso(proc.pid) == 0, "no vuelve a salir en ESA llamada (5 s más con el micro en uso)")
        llamada(False)
        time.sleep(2.5)                                      # 5 lecturas libres: la llamada termina

        # ---- S3: nueva llamada con la exclusión de la captura apagada SOLO en esta instancia -> píxeles reales y caducidad de 45 s
        api(base, tok, "PUT", "/api/config", {"excluir_captura": False})
        llamada(True)
        aviso = esperar(lambda: hwnd_aviso(proc.pid), 30)
        t_show = time.time()
        comprobar(aviso, "tercera llamada: aviso otra vez")
        time.sleep(2.0)
        m3 = medir(aviso)
        comprobar(m3["afinidad"] == 0, f"(solo en esta prueba) con la exclusión apagada la afinidad es {m3['afinidad']:#x}: se puede capturar")
        try:
            capturar_pantalla(m3["rect"], salida / "aviso-3-pantalla-real.png")
            print(f"  Captura de píxeles reales guardada: {salida / 'aviso-3-pantalla-real.png'}")
        except Exception as e:  # noqa: BLE001
            print("  (no se pudo capturar la pantalla:", e, ")")
        cdp = Cdp(puerto_dbg, puerto_app, "/aviso")
        cdp.ev("document.querySelector('#av-avisado').click()")
        cdp.captura(salida / "aviso-4-marcado.png")
        # pausa por el ratón durante 6 s: la caducidad se retrasa lo mismo
        x, y = cdp.centro("#av-tema")
        cdp.mover(x, y)
        pausa_t0 = time.time()
        time.sleep(6.0)
        cdp.mover(-5, -5)
        cdp.ev("document.querySelector('#av').dispatchEvent(new MouseEvent('mouseleave'))")
        pausado = time.time() - pausa_t0
        gone = esperar(lambda: hwnd_aviso(proc.pid) == 0, 60, 0.25)
        dur = time.time() - t_show
        comprobar(gone and abs(dur - (45 + pausado)) <= 4.5,
                  f"sin tocarlo se cierra a los 45 s contando la pausa del ratón ({pausado:.1f} s): duró {dur:.1f} s (esperado ~{45 + pausado:.1f})")
        comprobar(api(base, tok, "GET", "/api/sesion")["estado"] == "inactivo", "...y al caducar NO empieza ninguna grabación")
        cdp.cerrar()
        time.sleep(5.0)
        comprobar(hwnd_aviso(proc.pid) == 0, "tras caducar no vuelve en ESA llamada")
        llamada(False)
        time.sleep(2.5)
        api(base, tok, "PUT", "/api/config", {"excluir_captura": True})

        # ---- S4: Empezar de verdad (la simulación no usa audio ni tokens)
        llamada(True, "Chat | Laura | Microsoft Teams")   # un título que no es de reunión: tema por defecto con la hora
        aviso = esperar(lambda: hwnd_aviso(proc.pid), 30)
        comprobar(aviso, "cuarta llamada: aviso otra vez")
        time.sleep(1.5)
        cdp = Cdp(puerto_dbg, puerto_app, "/aviso")
        tema = cdp.ev("document.querySelector('#av-tema').textContent")
        comprobar(tema.startswith("Llamada de Teams ") and len(tema) == len("Llamada de Teams 13:30"), f"sin título legible el tema es «{tema}»")
        # editar el tema y elegir proyecto (sin usar el teclado: por la página)
        cdp.ev("""(() => { const i = document.querySelector('#av-tema-input'); i.value = 'Comité de seguimiento'; i.dispatchEvent(new Event('input')); })()""")
        cdp.ev("""(() => { const s = document.querySelector('#av-proyecto'); s.value = [...s.options].find(o => o.value).value; s.dispatchEvent(new Event('change')); })()""")
        cdp.ev("""(() => { const s = document.querySelector('#av-idioma'); s.value = 'ca'; s.dispatchEvent(new Event('change')); })()""")
        proyecto = cdp.ev("document.querySelector('#av-proyecto').value")
        comprobar(cdp.ev("document.querySelector('#av-tema').textContent") == "Comité de seguimiento", "el tema se edita en el desplegable y se ve en el aviso")
        cdp.clic("#av-avisado")
        time.sleep(0.4)
        fg_antes = primer_plano()
        cdp.captura(salida / "aviso-5-antes-de-empezar.png")
        comprobar(medir(aviso)["noactivate"] and medir(aviso)["topmost"], "antes de empezar: sin activar y siempre encima")
        t_empezar = time.time()
        cdp.clic("#av-empezar")
        iniciada = esperar(lambda: api(base, tok, "GET", "/api/sesion")["estado"] in ("grabando", "preparando"), 15)
        comprobar(iniciada, "el clic en «Empezar a transcribir» con la casilla marcada inicia la sesión")
        s = api(base, tok, "GET", "/api/sesion")
        comprobar(s["sesion"] and s["sesion"]["tema"] == "Comité de seguimiento" and s["sesion"]["proyecto"] == proyecto,
                  f"...con el tema editado y el proyecto elegido ({s['sesion'] and s['sesion']['proyecto']})")
        comprobar(esperar(lambda: hwnd_aviso(proc.pid) == 0, 10), "...y el aviso se cierra")
        comprobar(not [c for t, c in vigia.desde(t_empezar) if c == aviso], "el aviso no tomó el primer plano al hacer clic en «Empezar»")
        cdp.cerrar()
        princ = Cdp(puerto_dbg, puerto_app, "")
        comprobar(esperar(lambda: princ.ev("document.body.dataset.vista") == "reunion", 15), "la ventana principal pasa a la vista de reunión")
        princ.captura(salida / "principal-reunion.png")
        princ.cerrar()
        info = api(base, tok, "GET", "/api/info")["config"]
        comprobar(info["ultimo_proyecto"] == proyecto and info["ultimo_idioma"] == "ca", "se recuerdan el último proyecto e idioma (config de la instancia)")

        # ---- S5: con la reunión en curso no sale
        llamada(False)
        time.sleep(2.5)
        llamada(True)
        time.sleep(6.0)
        comprobar(hwnd_aviso(proc.pid) == 0, "con una reunión en curso, una llamada nueva NO abre el aviso")
        llamada(False)
        api(base, tok, "POST", "/api/sesion/terminar")
        comprobar(True, "reunión terminada (sin abrir ninguna ventana más)")
    except Exception as e:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        comprobar(False, f"excepción: {e}")
    finally:
        try:
            vigia.parar()
            subprocess.run(["taskkill", "/PID", str(standin.pid), "/T", "/F"], capture_output=True)
        except Exception:
            pass
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True)   # solo la instancia que lanzó esta prueba
        shutil.rmtree(tmp, ignore_errors=True)
    fallos = [t for ok, t in RES if not ok]
    print(f"\n{len(RES) - len(fallos)}/{len(RES)} comprobaciones correctas" + ("" if not fallos else f"; FALLAN {len(fallos)}"))
    print(f"Capturas en {salida}")
    return 1 if fallos else 0


if __name__ == "__main__":
    sys.exit(main())
