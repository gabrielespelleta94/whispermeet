"""Prueba extremo a extremo del Modo reunión con la ventana NATIVA, midiendo por Win32. No graba audio (usa --simular) ni gasta
tokens (modelo falso: servir_modelo_falso.py) y toca solo su propia instancia: localiza la ventana por PID, nunca por título.

    .venv\\Scripts\\python.exe pruebas\\probar_modo_reunion.py                 # geometría, región, WindowFromPoint, afinidad 0x11, restauración
    .venv\\Scripts\\python.exe pruebas\\probar_modo_reunion.py --captura       # además OPACIDAD medida en píxeles (la ventana se deja capturar)

Controla la página por el puerto de depuración de WebView2 (CDP) en 127.0.0.1: pulsa el botón y arrastra el divisor como un usuario.
Pone dos ventanas de Tk propias de color liso bajo/sobre los paneles para comprobar qué hay en el hueco. Sale con código 1 si algo falla.
"""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import warnings
import urllib.request
from ctypes import wintypes
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)   # este proceso mide en píxeles físicos
except Exception:
    ctypes.windll.user32.SetProcessDPIAware()

from apuntes import modo_reunion as MR  # noqa: E402
from apuntes import ventana as V  # noqa: E402
from websockets.sync.client import connect  # noqa: E402

U = ctypes.WinDLL("user32")
G = ctypes.WinDLL("gdi32")
U.WindowFromPoint.argtypes, U.WindowFromPoint.restype = [wintypes.POINT], wintypes.HWND
U.GetAncestor.argtypes, U.GetAncestor.restype = [wintypes.HWND, wintypes.UINT], wintypes.HWND
U.GetWindowRgn.argtypes, U.GetWindowRgn.restype = [wintypes.HWND, ctypes.c_void_p], ctypes.c_int
G.CreateRectRgn.argtypes, G.CreateRectRgn.restype = [ctypes.c_int] * 4, ctypes.c_void_p
U.GetDC.argtypes, U.GetDC.restype = [wintypes.HWND], ctypes.c_void_p
U.ReleaseDC.argtypes = [wintypes.HWND, ctypes.c_void_p]
G.GetPixel.argtypes, G.GetPixel.restype = [wintypes.HDC, ctypes.c_int, ctypes.c_int], wintypes.COLORREF
U.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]
U.GetWindowLongPtrW.argtypes, U.GetWindowLongPtrW.restype = [wintypes.HWND, ctypes.c_int], ctypes.c_ssize_t
GA_ROOT = 2
WS_EX_TOPMOST = 0x8

RES: list[tuple[bool, str]] = []


def comprobar(ok: bool, texto: str) -> bool:
    RES.append((bool(ok), texto))
    print(("  OK   " if ok else "  FALLA ") + texto, flush=True)
    return bool(ok)


def puerto_libre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Cdp:
    def __init__(self, puerto: int, puerto_app: int):
        t0 = time.time()
        while True:
            try:
                dest = json.load(urllib.request.urlopen(f"http://127.0.0.1:{puerto}/json/list", timeout=2))
                pag = [d for d in dest if d.get("type") == "page" and f":{puerto_app}" in d.get("url", "")]
                if pag:
                    break
            except Exception:
                pass
            if time.time() - t0 > 60:
                raise TimeoutError("No aparece la página de Apuntes en el puerto de depuración de WebView2.")
            time.sleep(0.5)
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
        for intento in range(40):   # la página puede recargarse al arrancar: se reintenta si el contexto desaparece
            try:
                r = self("Runtime.evaluate", expression=expr, returnByValue=True, awaitPromise=True)
            except RuntimeError as e:
                if "context" in str(e).lower() and intento < 39:
                    time.sleep(0.5); continue
                raise
            if "exceptionDetails" in r:
                raise RuntimeError(str(r["exceptionDetails"])[:300])
            return r["result"].get("value")

    def raton(self, tipo: str, x: float, y: float):
        self("Input.dispatchMouseEvent", type=tipo, x=x, y=y, button="left", buttons=1 if tipo != "mouseReleased" else 0, clickCount=1)


def api(base, tok, metodo, ruta, cuerpo=None):
    req = urllib.request.Request(base + ruta, method=metodo, headers={"X-Token": tok, "Content-Type": "application/json"},
                                 data=None if cuerpo is None else json.dumps(cuerpo).encode())
    return json.load(urllib.request.urlopen(req, timeout=30))


# ------------------------------------------------------------ Win32
class _PE(ctypes.Structure):
    _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("pid", wintypes.DWORD), ("heap", ctypes.c_void_p),
                ("modulo", wintypes.DWORD), ("hilos", wintypes.DWORD), ("padre", wintypes.DWORD), ("prio", ctypes.c_long),
                ("flags", wintypes.DWORD), ("exe", ctypes.c_wchar * 260)]


def con_descendientes(raiz_pid: int) -> set[int]:
    """El PID dado y todos sus procesos hijos (el python.exe de un venv es un lanzador: la app real es un hijo)."""
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.CreateToolhelp32Snapshot.restype = ctypes.c_void_p
    k.Process32FirstW.argtypes = k.Process32NextW.argtypes = [ctypes.c_void_p, ctypes.POINTER(_PE)]
    k.CloseHandle.argtypes = [ctypes.c_void_p]
    snap = k.CreateToolhelp32Snapshot(2, 0)
    pares, pe = [], _PE()
    pe.dwSize = ctypes.sizeof(_PE)
    ok = k.Process32FirstW(snap, ctypes.byref(pe))
    while ok:
        pares.append((pe.pid, pe.padre)); ok = k.Process32NextW(snap, ctypes.byref(pe))
    k.CloseHandle(snap)
    todos = {raiz_pid}
    while True:
        nuevos = {h for h, p in pares if p in todos and h not in todos}
        if not nuevos:
            return todos
        todos |= nuevos


def ventana_de_instancia(raiz_pid: int) -> int:
    for pid in con_descendientes(raiz_pid):
        h = V.buscar_hwnd(pid=pid)
        if h:
            return h
    return 0


def raiz_de(hwnd) -> int:
    return int(U.GetAncestor(hwnd, GA_ROOT) or 0) if hwnd else 0


def ventana_en(x: int, y: int) -> int:
    return raiz_de(U.WindowFromPoint(wintypes.POINT(x, y)))


def pixel(x: int, y: int) -> tuple[int, int, int]:
    """Color del píxel de pantalla ya compuesto por DWM (BitBlt de 1x1 con CAPTUREBLT: GetPixel directo sobre la pantalla falla)."""
    for f, a, r in (("CreateCompatibleDC", [ctypes.c_void_p], ctypes.c_void_p), ("CreateCompatibleBitmap", [ctypes.c_void_p, ctypes.c_int, ctypes.c_int], ctypes.c_void_p),
                    ("SelectObject", [ctypes.c_void_p, ctypes.c_void_p], ctypes.c_void_p), ("DeleteObject", [ctypes.c_void_p], ctypes.c_int),
                    ("DeleteDC", [ctypes.c_void_p], ctypes.c_int),
                    ("BitBlt", [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_void_p, ctypes.c_int, ctypes.c_int, wintypes.DWORD], ctypes.c_int)):
        getattr(G, f).argtypes, getattr(G, f).restype = a, r
    G.GetPixel.argtypes, G.GetPixel.restype = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int], wintypes.DWORD
    pant = U.GetDC(None)
    mem = G.CreateCompatibleDC(pant)
    bmp = G.CreateCompatibleBitmap(pant, 1, 1)
    viejo = G.SelectObject(mem, bmp)
    G.BitBlt(mem, 0, 0, 1, 1, pant, x, y, 0x00CC0020 | 0x40000000)   # SRCCOPY | CAPTUREBLT
    v = G.GetPixel(mem, 0, 0)
    G.SelectObject(mem, viejo); G.DeleteObject(bmp); G.DeleteDC(mem); U.ReleaseDC(None, pant)
    return v & 255, (v >> 8) & 255, (v >> 16) & 255


def perfil_region(hwnd: int, ancho: int, y: int) -> list[tuple[int, int]]:
    """Tramos [a, b) de la fila `y` que están dentro de la región REAL de la ventana (GetWindowRgn + PtInRegion)."""
    tramos, ini = [], None
    for x in range(ancho + 1):
        d = V.punto_en_region_ventana(hwnd, x, y) if x < ancho else False
        if d and ini is None:
            ini = x
        elif not d and ini is not None:
            tramos.append((ini, x)); ini = None
    return tramos


def caja_region(hwnd: int) -> tuple[int, tuple[int, int, int, int]]:
    """(tipo, caja) de la región de la ventana: tipo 0 = sin región; 1 vacía; 2 simple; 3 compleja."""
    G.GetRgnBox.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.RECT)]
    rg = G.CreateRectRgn(0, 0, 0, 0)
    tipo = U.GetWindowRgn(hwnd, rg)
    r = wintypes.RECT()
    if tipo:
        G.GetRgnBox(rg, ctypes.byref(r))
    G.DeleteObject(ctypes.c_void_p(rg))
    return tipo, (r.left, r.top, r.right, r.bottom)


def estilos(hwnd: int) -> tuple[int, int]:
    return U.GetWindowLongPtrW(hwnd, V.GWL_STYLE), U.GetWindowLongPtrW(hwnd, V.GWL_EXSTYLE)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--captura", action="store_true", help="deja la ventana capturable y mide la opacidad en píxeles")
    ap.add_argument("--velocidad", default="3")
    a = ap.parse_args()

    tmp = Path(tempfile.mkdtemp(prefix="apuntes_mr_"))
    raiz = tmp / "proyectos"
    shutil.copytree(RAIZ / "pruebas" / "proyectos", raiz)
    (tmp / "config.json").write_text(json.dumps({"knowledge": ""}), encoding="utf-8")   # nunca el Knowledge de OneDrive en una prueba
    puerto_app, puerto_dbg = puerto_libre(), puerto_libre()
    env = dict(os.environ, WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS=f"--remote-debugging-port={puerto_dbg} --remote-allow-origins=*")
    cmd = [sys.executable, str(RAIZ / "pruebas" / "servir_modelo_falso.py"), "--retardo", "1", "--",
           "--simular", str(RAIZ / "pruebas" / "reunion-ficticia.txt"), "--velocidad", a.velocidad, "--raiz", str(raiz),
           "--config", str(tmp / "config.json"), "--planes", str(tmp / "planes"), "--sesiones", str(tmp / "sesiones"),
           "--checks", str(tmp / "checks"), "--cache", str(tmp / "cache"), "--consumo", str(tmp / "consumo.jsonl"), "--puerto", str(puerto_app)]
    if a.captura:
        cmd.append("--mostrar-en-captura")
    proc = subprocess.Popen(cmd, cwd=RAIZ, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    import tkinter as tk
    tks: list = []

    def pulso(seg: float):
        t0 = time.time()
        while time.time() - t0 < seg:
            for t in tks:
                t.update()
            time.sleep(0.03)

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
        print(f"Instancia propia: PID {proc.pid}, puerto {puerto_app}, depuración {puerto_dbg}")
        hwnd = 0
        while not hwnd and time.time() - t0 < 90:
            hwnd = ventana_de_instancia(proc.pid); time.sleep(0.3)
        assert hwnd, "no se encontró la ventana nativa del proceso"
        cdp = Cdp(puerto_dbg, puerto_app)
        cdp.ev("new Promise(r => { const t = () => document.querySelector('#mr-entrar') ? r(1) : setTimeout(t, 100); t(); })")

        # --- una reunión simulada (sin audio) y la vista de reunión
        api(base, tok, "POST", "/api/sesion/iniciar", {"proyecto": "Proyecto Ficticio Alfa", "tema": "Prueba del modo", "cadencia": 5})
        cdp.ev("new Promise(r => { const t = () => document.body.dataset.vista === 'reunion' && !document.querySelector('#mr-entrar').hidden ? r(1) : setTimeout(t, 100); t(); })")
        comprobar(cdp.ev("!document.querySelector('#mr-entrar').hidden"), "con ventana nativa el botón «Modo reunión» está visible")
        dpr = cdp.ev("window.devicePixelRatio")
        dpi = V.dpi_ventana(hwnd)
        print(f"  (escala de Windows {dpi / 96:g}; devicePixelRatio de la página {dpr:g})")
        comprobar(abs(dpr - dpi / 96) < 0.01, f"devicePixelRatio de WebView2 ({dpr:g}) == escala de Windows ({dpi / 96:g}): el mismo factor CSS -> físicos")

        antes = {"rect": V.rect_ventana(hwnd), "estilos": estilos(hwnd), "afin": V.leer_afinidad(hwnd), "zoom": bool(U.IsZoomed(hwnd))}
        antes["region"] = caja_region(hwnd)
        print(f"  Región antes de entrar (tipo, caja): {antes['region']}")
        print(f"  Antes: rect {antes['rect']}, estilo {antes['estilos'][0]:#x}, afinidad {antes['afin']:#x}, maximizada {antes['zoom']}")
        if not a.captura:
            comprobar(antes["afin"] == 0x11, "antes del modo: GetWindowDisplayAffinity == 0x11")
        s0 = api(base, tok, "GET", "/api/sesion")
        n_seg0 = len(s0.get("segmentos", []))

        # --- entrar pulsando el botón de la cabecera
        cdp.ev("document.querySelector('#mr-entrar').click()")
        t0 = time.time()
        while time.time() - t0 < 15 and not api(base, tok, "GET", "/api/ventana").get("activo"):
            time.sleep(0.1)
        pulso(1.0)
        est = api(base, tok, "GET", "/api/ventana")
        comprobar(est.get("activo"), "el botón activa el modo (estado del backend)")
        rect = V.rect_ventana(hwnd)
        trabajo = V.area_trabajo(hwnd)
        r = wintypes.RECT(); U.SystemParametersInfoW(0x30, 0, ctypes.byref(r), 0)
        print(f"  Dentro: rect {rect}, área de trabajo {trabajo}, SPI_GETWORKAREA {(r.left, r.top, r.right, r.bottom)}")
        comprobar(rect == trabajo, f"la ventana ocupa el área de trabajo del monitor {trabajo} (sin tapar la barra de tareas)")
        comprobar(trabajo == (r.left, r.top, r.right, r.bottom), "...y esa área de trabajo coincide con SPI_GETWORKAREA (monitor principal)")
        est_s, est_x = estilos(hwnd)
        comprobar(est_x & WS_EX_TOPMOST != 0, "la ventana es siempre encima (WS_EX_TOPMOST)")
        comprobar(est_s & V.WS_CAPTION == 0 and est_s & V.WS_THICKFRAME == 0, "sin marco ni barra de título (la región coincide con el área cliente)")
        afin = V.leer_afinidad(hwnd)
        if not a.captura:
            comprobar(afin == 0x11, f"DENTRO del modo: GetWindowDisplayAffinity == {afin:#x} (0x11 = excluida de la captura)")
            comprobar(not est["afinidad_reaplicada"], "...sin que el código tuviera que volver a aplicarla (la conservó sola)")
        W, H = rect[2] - rect[0], rect[3] - rect[1]
        lay, esc = est["layout"], est["escala"]
        print(f"  Layout {lay}, escala {esc}")
        comprobar(lay["modo"] == "dos", "a este ancho hay dos paneles y hueco")
        izq_f, der_f = round(lay["izq"] * esc), round(lay["der"] * esc)

        # --- región real
        y = H // 2
        tramos = perfil_region(hwnd, W, y)
        esperado = [(0, izq_f), (W - der_f, W)]
        comprobar(tramos == esperado, f"región REAL (GetWindowRgn) en la fila central: {tramos} == panel izq y der {esperado}")
        tramos_arriba, tramos_abajo = perfil_region(hwnd, W, 2), perfil_region(hwnd, W, H - 3)
        comprobar(tramos_arriba == esperado and tramos_abajo == esperado, "la región es igual arriba y abajo (hueco de arriba a abajo)")
        cx = (izq_f + (W - der_f)) // 2
        comprobar(V.punto_en_region_ventana(hwnd, cx, y) is False, f"centro del hueco ({cx},{y}) FUERA de la región")
        comprobar(V.punto_en_region_ventana(hwnd, izq_f // 2, y) and V.punto_en_region_ventana(hwnd, W - der_f // 2, y), "centro de cada panel DENTRO de la región")
        comprobar(V.punto_en_region_ventana(hwnd, izq_f - 1, y) and not V.punto_en_region_ventana(hwnd, izq_f, y), "borde exacto del panel izquierdo")
        comprobar(not V.punto_en_region_ventana(hwnd, W - der_f - 1, y) and V.punto_en_region_ventana(hwnd, W - der_f, y), "borde exacto del panel derecho")
        print(f"  Medidas CSS: {lay['izq']} / {lay['hueco']} / {lay['der']} (ancho CSS {lay['ancho']})")

        # --- qué hay en el hueco: una ventana de Tk propia, de color liso y siempre encima, justo en el hueco
        A = tk.Tk(); tks.append(A)
        A.overrideredirect(True); A.attributes("-topmost", True); A.configure(bg="#ff0000")
        A.geometry(f"{W - der_f - izq_f}x{H}+{rect[0] + izq_f}+{rect[1]}")
        pulso(0.8)
        hA = int(U.GetAncestor(A.winfo_id(), GA_ROOT))
        sx, sy = rect[0], rect[1]
        en = lambda x, yy: ventana_en(sx + x, sy + yy)  # noqa: E731
        c = en(cx, y)
        comprobar(c == hA, f"WindowFromPoint en el centro del hueco devuelve la ventana de debajo ({c:#x}), no la app ({hwnd:#x})")
        comprobar(c != hwnd, "...y no pertenece a la app")
        comprobar(en(izq_f // 2, y) == hwnd and en(W - der_f // 2, y) == hwnd, "WindowFromPoint en cada panel devuelve la app")
        comprobar(en(izq_f + 1, y) == hA and en(izq_f - 1, y) == hwnd, "borde izquierdo del hueco: dentro del hueco es la de debajo, a un píxel es la app")
        comprobar(en(W - der_f - 1, y) == hA and en(W - der_f + 1, y) == hwnd, "borde derecho del hueco, igual")
        comprobar(all(en(cx, yy) == hA for yy in (2, H // 4, H - 3)), "el hueco llega de arriba (barra incluida) a abajo")
        leer_pantalla = False
        if a.captura:
            px_h, px_p = pixel(sx + cx, sy + y), pixel(sx + 3, sy + y)
            leer_pantalla = px_h == (255, 0, 0)
            if leer_pantalla:
                comprobar(px_p != (255, 0, 0), f"pixel en el panel {px_p} es de la app y en el centro del hueco {px_h} es el rojo de la ventana de debajo (se ve nítida)")
            else:
                print(f"  OMITIDO: este proceso no puede leer la pantalla compuesta (pixel del hueco {px_h}, esperado rojo): la mezcla de la opacidad NO se mide aquí")
        A.destroy(); tks.clear()

        # --- opacidad (en píxeles; solo con --captura)
        if a.captura and leer_pantalla:
            B = tk.Tk(); tks.append(B)
            B.overrideredirect(True); B.configure(bg="#00ff00")
            B.geometry(f"{izq_f}x{H}+{rect[0]}+{rect[1]}")
            pulso(0.8)
            px_x, px_y = sx + 3, sy + H // 2
            res = {}
            for pct in (100, 60, 80, 100):
                api(base, tok, "POST", "/api/ventana/opacidad", {"pct": pct})
                pulso(0.7)
                res.setdefault(pct, []).append(pixel(px_x, px_y))
                alfa = V.leer_alfa(hwnd)
                print(f"  opacidad {pct} %: alfa de la ventana {alfa}, pixel en el panel {res[pct][-1]} (verde de debajo = (0,255,0))")
            bg = res[100][0]
            for pct in (60, 80):
                p = res[pct][0]
                k = pct / 100
                esp = tuple(round(k * bg[i] + (1 - k) * (0, 255, 0)[i]) for i in range(3))
                comprobar(all(abs(p[i] - esp[i]) <= 14 for i in range(3)), f"opacidad {pct} %: el pixel {p} es la mezcla esperada {esp} del panel {bg} con lo de debajo")
            comprobar(res[100][1] == bg, "al volver a 100 % el pixel vuelve a ser el del panel")
            comprobar(res[60][0] != bg, "la opacidad SÍ funciona con WebView2 (el panel deja ver lo de debajo)")
            B.destroy(); tks.clear()
        else:
            if a.captura:
                print("  OMITIDO: opacidad medida en píxeles (pantalla no legible); solo se comprueba el atributo Win32 aplicado")
            api(base, tok, "POST", "/api/ventana/opacidad", {"pct": 70})
            alfa = V.leer_alfa(hwnd)
            comprobar(alfa == round(70 * 255 / 100), f"opacidad 70 %: alfa de la ventana (GetLayeredWindowAttributes) = {alfa}")
            api(base, tok, "POST", "/api/ventana/opacidad", {"pct": 100})

        # --- orquestación plegada (mínimo 32 px; crece si el texto envuelve, sin cortarlo), un solo scroll y mandos en la barra
        m = cdp.ev("""(() => { const R = (s) => { const e = document.querySelector(s); const r = e.getBoundingClientRect(); return [Math.round(r.left), Math.round(r.top), Math.round(r.width), Math.round(r.height)]; };
          return { orq: R('#orq'), izq: R('.col-izq'), der: R('.col-der'), barra: R('#mr-barra'), rec: !!document.querySelector('#mr-f1 #r-rec'), reloj: !!document.querySelector('#mr-f1 #r-reloj'),
            analizar: !!document.querySelector('#mr-f1 #r-analizar'), salir: !!document.querySelector('#mr-f1 #mr-salir'), opac: !!document.querySelector('#mr-opac') && !document.querySelector('#mr-opac-campo').hidden,
            ins: getComputedStyle(document.querySelector('#r-ins-scroll')).overflowY, plan: getComputedStyle(document.querySelector('#r-plan-scroll')).overflowY,
            colder: getComputedStyle(document.querySelector('.col-der')).overflowY, plegado: document.querySelector('#orq').dataset.plegado, iw: innerWidth, ih: innerHeight }; })()""")
        print(f"  Interfaz: {m}")
        comprobar(m["orq"][3] >= 32 and m["plegado"] == "true" and m["orq"][1] + m["orq"][3] == m["ih"] and m["izq"][1] + m["izq"][3] <= m["orq"][1], f"orquestación plegada a {m['orq'][3]} px, pegada abajo y sin pisar la transcripción")
        comprobar(m["rec"] and m["reloj"] and m["analizar"] and m["salir"] and m["opac"], "mandos arriba: REC, cronómetro, Analizar ahora, Salir y opacidad")
        comprobar(m["ins"] == "visible" and m["plan"] == "visible" and m["colder"] in ("auto", "scroll"), "insights, objetivos y checks comparten un único scroll (el del panel derecho)")
        comprobar(abs(m["izq"][2] - lay["izq"]) <= 1 and abs(m["der"][2] - lay["der"]) <= 1, f"anchos CSS de los paneles {m['izq'][2]} y {m['der'][2]} == layout {lay['izq']} y {lay['der']}")
        comprobar(abs(m["iw"] - lay["ancho"]) <= 1, f"innerWidth ({m['iw']}) == ancho CSS usado por el backend ({lay['ancho']}): CSS y región coinciden")

        # --- la grabación y el análisis siguen
        s1 = api(base, tok, "GET", "/api/sesion")
        comprobar(s1["estado"] == "grabando", f"la reunión sigue en estado «{s1['estado']}» dentro del modo")
        t1 = s1.get("t")
        cdp.ev("document.querySelector('#r-analizar').click()")
        pulso(3.0)
        s2 = api(base, tok, "GET", "/api/sesion")
        comprobar(len(s2.get("segmentos", [])) > n_seg0 and s2["t"] > t1, f"siguen llegando líneas y corre el reloj ({n_seg0} -> {len(s2.get('segmentos', []))} líneas)")
        comprobar(cdp.ev("document.querySelectorAll('#r-insights .tarj, #r-insights .traza-f').length") > 0, "«Analizar ahora» desde la barra del modo produce un análisis (insights visibles)")

        # --- divisores: arrastre real (eventos de ratón de CDP) y medida recordada
        x_div = lay["izq"] - 4
        cdp.raton("mouseMoved", x_div, 300); cdp.raton("mousePressed", x_div, 300)
        for dx in (20, 40, 60):
            cdp.raton("mouseMoved", x_div + dx, 300); pulso(0.2)
        cdp.raton("mouseReleased", x_div + 60, 300)
        pulso(0.8)
        est2 = api(base, tok, "GET", "/api/ventana")
        lay2 = est2["layout"]
        print(f"  Tras arrastrar el divisor izquierdo 60 px: layout {lay2}")
        comprobar(lay2["izq"] == lay["izq"] + 60, f"el divisor izquierdo se arrastra: {lay['izq']} -> {lay2['izq']} px CSS")
        tr2 = perfil_region(hwnd, W, y)
        comprobar(tr2 == [(0, round(lay2["izq"] * esc)), (W - round(lay2["der"] * esc), W)], f"la región se recalcula al arrastrar: {tr2}")
        cfg = json.loads((tmp / "config.json").read_text(encoding="utf-8"))["modo_reunion"]
        comprobar(cfg["izq"] == lay2["izq"] and cfg["der"] is None, f"la medida se recuerda (config): {cfg}")
        # ...y teclado
        cdp.ev("document.querySelector('#mr-div-der').focus()")
        cdp("Input.dispatchKeyEvent", type="keyDown", key="ArrowLeft", code="ArrowLeft", windowsVirtualKeyCode=37)
        cdp("Input.dispatchKeyEvent", type="keyUp", key="ArrowLeft", code="ArrowLeft", windowsVirtualKeyCode=37)
        pulso(0.8)
        lay3 = api(base, tok, "GET", "/api/ventana")["layout"]
        comprobar(lay3["der"] == lay2["der"] + 16, f"el divisor derecho responde al teclado (←): {lay2['der']} -> {lay3['der']}")
        # límites: no deja el hueco por debajo del mínimo
        cdp.raton("mouseMoved", lay3["izq"] - 4, 300); cdp.raton("mousePressed", lay3["izq"] - 4, 300)
        cdp.raton("mouseMoved", lay3["ancho"] - 100, 300); pulso(0.3)
        cdp.raton("mouseReleased", lay3["ancho"] - 100, 300); pulso(0.8)
        lay4 = api(base, tok, "GET", "/api/ventana")["layout"]
        comprobar(lay4["hueco"] >= MR.MIN_HUECO, f"arrastrando al extremo el hueco no baja de {MR.MIN_HUECO} px: {lay4['hueco']}")
        perfil_final = perfil_region(hwnd, W, y)

        # --- redimensionar: la región se recalcula sola (resize de la página -> backend)
        def tamano(w, hh, texto):
            U.SetWindowPos(hwnd, wintypes.HWND(V.HWND_TOPMOST), rect[0] + 40, rect[1] + 30, w, hh, 0x0010)
            pulso(1.5)
            r2 = V.rect_ventana(hwnd)
            return r2[2] - r2[0], r2[3] - r2[1], api(base, tok, "GET", "/api/ventana")
        W2, H2, est5 = tamano(1800, 850, "")
        l5 = est5["layout"]
        tr5 = perfil_region(hwnd, W2, H2 // 2)
        print(f"  Ventana redimensionada a {W2}x{H2} ({est5['escala']:g}x): layout {l5}, región {tr5}")
        comprobar(l5["modo"] == "dos" and tr5 == [(0, round(l5["izq"] * esc)), (W2 - round(l5["der"] * esc), W2)] and tr5[1][1] == W2,
                  "al redimensionar la ventana la región se recalcula con el nuevo ancho")
        # ...con otra escala DPI (la página informa de su devicePixelRatio; aquí forzado a 1,5 por la API: solo la cañería)
        est6 = api(base, tok, "POST", "/api/ventana/modo-reunion", {"activo": True, "dpr": 1.5})
        l6, e6 = est6["layout"], est6["escala"]
        tr6 = perfil_region(hwnd, W2, H2 // 2)
        esp6 = [(a_, c_) for a_, _b, c_, _d in MR.rectangulos_region(W2, H2, l6, 1.5)]
        comprobar(e6 == 1.5 and tr6 == esp6, f"con escala 1,5 la región se recalcula ({l6['modo']}): {tr6} == {esp6} (escala {e6})")
        api(base, tok, "POST", "/api/ventana/modo-reunion", {"activo": True, "dpr": dpr}); pulso(0.5)
        # ...y por debajo de 1280 px CSS (1500 físicos = 1200 CSS): un único panel lateral, sin hueco que gestionar
        W3, H3, est7 = tamano(1500, 850, "")
        l7 = est7["layout"]
        tr7 = perfil_region(hwnd, W3, H3 // 2)
        print(f"  Ventana de {W3}x{H3} ({W3 / esc:.0f} px CSS): layout {l7}, región {tr7}")
        comprobar(l7["modo"] == "uno" and l7["izq"] == 0 and tr7 == [(W3 - round(l7["der"] * esc), W3)], "por debajo de 1280 px: un único panel lateral (un solo tramo de región, a la derecha)")
        m7 = cdp.ev("""(() => { const v = (s) => getComputedStyle(document.querySelector(s)).display; return { modo: document.body.dataset.mr, tabs: !document.querySelector('#mr-tabs').hidden,
          izq: v('.col-izq'), der: v('.col-der'), divizq: document.querySelector('#mr-div-izq').hidden }; })()""")
        comprobar(m7["modo"] == "uno" and m7["tabs"] and m7["divizq"], f"...con pestañas y sin divisor izquierdo ({m7})")
        cdp.ev("document.querySelector('#mr-tabs [data-tab=ins]').click()")
        m8 = cdp.ev("({ izq: getComputedStyle(document.querySelector('.col-izq')).display, der: getComputedStyle(document.querySelector('.col-der')).display })")
        comprobar(m8["izq"] == "none" and m8["der"] != "none", f"...la pestaña Insights muestra el panel de insights ({m8})")
        U.SetWindowPos(hwnd, wintypes.HWND(V.HWND_TOPMOST), rect[0], rect[1], W, H, 0x0010)
        pulso(1.5)
        comprobar(perfil_region(hwnd, W, y) == perfil_final, "al devolver el tamaño, vuelve la región de dos paneles de antes")
        if not a.captura:
            comprobar(V.leer_afinidad(hwnd) == 0x11, "tras redimensionar y arrastrar: afinidad sigue en 0x11")

        # --- salir
        cdp.ev("document.querySelector('#mr-salir').click()")
        t0 = time.time()
        while time.time() - t0 < 15 and api(base, tok, "GET", "/api/ventana").get("activo"):
            time.sleep(0.1)
        pulso(1.0)
        despues = {"rect": V.rect_ventana(hwnd), "estilos": estilos(hwnd), "afin": V.leer_afinidad(hwnd), "zoom": bool(U.IsZoomed(hwnd))}
        print(f"  Después: rect {despues['rect']}, estilo {despues['estilos'][0]:#x}, afinidad {despues['afin']:#x}")
        comprobar(despues["rect"] == antes["rect"], f"al salir se restaura tamaño y posición {antes['rect']}")
        comprobar(despues["estilos"][0] == antes["estilos"][0], "...y el estilo de ventana (marco y barra de título)")
        comprobar(despues["estilos"][1] & WS_EX_TOPMOST == 0, "...ya no es siempre encima")
        reg = caja_region(hwnd)
        print(f"  Reintentos de quitar región en esta salida: {api(base, tok, 'GET', '/api/ventana').get('region_reintentos')}")
        print(f"  Región tras salir (tipo, caja): {reg}")
        comprobar(reg == antes["region"] or reg[0] == 0, f"...la región vuelve a ser la de antes de entrar {antes['region']} (sin recorte)")
        comprobar(V.leer_alfa(hwnd) == 255, "...ni opacidad")
        comprobar(despues["zoom"] == antes["zoom"], "...ni cambia el estado maximizada")
        comprobar(despues["afin"] == antes["afin"], f"afinidad tras salir == antes ({despues['afin']:#x})")
        if not a.captura:
            comprobar(despues["afin"] == 0x11, "tras salir: GetWindowDisplayAffinity == 0x11")
        comprobar(cdp.ev("!document.body.dataset.modo && !!document.querySelector('#r-cab #r-analizar') && !!document.querySelector('#r-cab #r-reloj')"),
                  "la cabecera recupera sus mandos y la interfaz vuelve a la vista completa")
        comprobar(api(base, tok, "GET", "/api/sesion")["estado"] == "grabando", "la reunión sigue grabando tras salir")

        # --- ciclo repetido y salida automática al terminar
        for i in range(2):
            cdp.ev("document.querySelector('#mr-entrar').click()"); pulso(1.2)
            cdp.ev("document.querySelector('#mr-salir').click()"); pulso(1.2)
        comprobar(V.rect_ventana(hwnd) == antes["rect"] and V.leer_afinidad(hwnd) == antes["afin"], "dos ciclos más entrar/salir: misma posición y afinidad")
        cdp.ev("document.querySelector('#mr-entrar').click()"); pulso(1.2)
        api(base, tok, "POST", "/api/sesion/terminar")
        t0 = time.time()
        while time.time() - t0 < 60 and api(base, tok, "GET", "/api/ventana").get("activo"):
            pulso(0.3)
        pulso(1.0)
        comprobar(not api(base, tok, "GET", "/api/ventana").get("activo") and V.rect_ventana(hwnd) == antes["rect"],
                  "al terminar la reunión el modo se cierra solo y la ventana vuelve a su sitio")
    except Exception as e:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        comprobar(False, f"excepción: {e}")
    finally:
        for t in tks:
            try:
                t.destroy()
            except Exception:
                pass
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True)   # solo la instancia que lanzó esta prueba
        shutil.rmtree(tmp, ignore_errors=True)
    fallos = [t for ok, t in RES if not ok]
    print(f"\n{len(RES) - len(fallos)}/{len(RES)} comprobaciones correctas" + ("" if not fallos else f"; FALLAN {len(fallos)}"))
    return 1 if fallos else 0


if __name__ == "__main__":
    sys.exit(main())
