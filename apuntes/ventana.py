"""Ventana propia (pywebview), exclusión de la captura (SetWindowDisplayAffinity) y Modo reunión (Win32: siempre encima,
región con hueco central y opacidad)."""
from __future__ import annotations

import ctypes
import os
import sys
import threading
import time
from ctypes import wintypes

from . import modo_reunion as MR

WDA_NONE = 0x00
WDA_EXCLUDEFROMCAPTURE = 0x11
TITULO = "WhisperMeet"
APP_ID = "Stratesys.Apuntes"   # AppUserModelID: agrupa la ventana con el acceso directo anclado (crear_acceso_directo.py usa el mismo)
ICONO = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web", "marca", "apuntes.ico")

# Opacidad por ventana entera (WS_EX_LAYERED + LWA_ALPHA). El atributo se aplica y se lee de vuelta (GetLayeredWindowAttributes), pero
# que WebView2 muestre de verdad la mezcla con lo de debajo hay que mirarlo a ojo (pruebas\probar_modo_reunion.py --captura lo mide en
# píxeles donde el proceso puede leer la pantalla). Si no se viera, ponerlo a False oculta el control en la interfaz.
OPACIDAD_SOPORTADA = True

GWL_STYLE, GWL_EXSTYLE = -16, -20
WS_CAPTION, WS_THICKFRAME, WS_MAXIMIZEBOX, WS_MINIMIZEBOX = 0x00C00000, 0x00040000, 0x00010000, 0x00020000
WS_EX_LAYERED = 0x00080000
LWA_ALPHA = 0x2
HWND_TOPMOST, HWND_NOTOPMOST = -1, -2
SWP_NOZORDER, SWP_NOACTIVATE, SWP_FRAMECHANGED, SWP_SHOWWINDOW = 0x0004, 0x0010, 0x0020, 0x0040
SW_RESTORE, SW_MAXIMIZE = 9, 3
WM_SETICON, ICON_SMALL, ICON_BIG = 0x80, 0, 1
IMAGE_ICON, LR_LOADFROMFILE = 1, 0x10
MONITOR_DEFAULTTONEAREST = 2
RGN_OR = 2


class _MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT), ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]


_S = None
_U = None   # user32 y gdi32 PROPIOS (WinDLL aparte): sus argtypes no tocan a los de pywebview ni a ctypes.windll


def _gdi32():
    _user32()
    return _G


def _user32():
    global _U, _G, _S
    if _U is not None:
        return _U
    u = _U = ctypes.WinDLL("user32")
    _G = ctypes.WinDLL("gdi32")
    _S = ctypes.WinDLL("shell32")
    h, i, b, p = wintypes.HWND, ctypes.c_int, wintypes.BOOL, ctypes.c_void_p
    u.GetWindowLongPtrW.argtypes, u.GetWindowLongPtrW.restype = [h, i], ctypes.c_ssize_t
    u.SetWindowLongPtrW.argtypes, u.SetWindowLongPtrW.restype = [h, i, ctypes.c_ssize_t], ctypes.c_ssize_t
    u.SetWindowPos.argtypes, u.SetWindowPos.restype = [h, h, i, i, i, i, wintypes.UINT], b
    u.GetWindowRect.argtypes, u.GetWindowRect.restype = [h, ctypes.POINTER(wintypes.RECT)], b
    u.GetClientRect.argtypes, u.GetClientRect.restype = [h, ctypes.POINTER(wintypes.RECT)], b
    u.SetWindowRgn.argtypes, u.SetWindowRgn.restype = [h, p, b], i
    u.GetWindowRgn.argtypes, u.GetWindowRgn.restype = [h, p], i
    u.SetLayeredWindowAttributes.argtypes, u.SetLayeredWindowAttributes.restype = [h, wintypes.COLORREF, ctypes.c_ubyte, wintypes.DWORD], b
    u.GetLayeredWindowAttributes.argtypes, u.GetLayeredWindowAttributes.restype = [
        h, ctypes.POINTER(wintypes.COLORREF), ctypes.POINTER(ctypes.c_ubyte), ctypes.POINTER(wintypes.DWORD)], b
    u.MonitorFromWindow.argtypes, u.MonitorFromWindow.restype = [h, wintypes.DWORD], p
    u.GetMonitorInfoW.argtypes, u.GetMonitorInfoW.restype = [p, ctypes.POINTER(_MONITORINFO)], b
    u.IsZoomed.argtypes, u.IsZoomed.restype = [h], b
    u.ShowWindow.argtypes, u.ShowWindow.restype = [h, i], b
    u.GetDpiForWindow.argtypes, u.GetDpiForWindow.restype = [h], wintypes.UINT
    u.GetWindowTextW.argtypes, u.GetWindowTextW.restype = [h, wintypes.LPWSTR, i], i
    u.GetWindowThreadProcessId.argtypes, u.GetWindowThreadProcessId.restype = [h, ctypes.POINTER(wintypes.DWORD)], wintypes.DWORD
    u.IsWindowVisible.argtypes, u.IsWindowVisible.restype = [h], b
    u.SetWindowDisplayAffinity.argtypes, u.SetWindowDisplayAffinity.restype = [h, wintypes.DWORD], b
    u.GetWindowDisplayAffinity.argtypes, u.GetWindowDisplayAffinity.restype = [h, ctypes.POINTER(wintypes.DWORD)], b
    g = _G
    g.CreateRectRgn.argtypes, g.CreateRectRgn.restype = [i, i, i, i], p
    g.CombineRgn.argtypes, g.CombineRgn.restype = [p, p, p, i], i
    g.DeleteObject.argtypes, g.DeleteObject.restype = [p], b
    g.PtInRegion.argtypes, g.PtInRegion.restype = [p, i, i], b
    u.EnumWindows.argtypes, u.EnumWindows.restype = [ctypes.c_void_p, wintypes.LPARAM], b
    u.LoadImageW.argtypes, u.LoadImageW.restype = [p, wintypes.LPCWSTR, wintypes.UINT, i, i, wintypes.UINT], p
    u.SendMessageW.argtypes, u.SendMessageW.restype = [h, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM], ctypes.c_ssize_t
    u.FlashWindowEx.argtypes, u.FlashWindowEx.restype = [ctypes.c_void_p], b
    u.GetForegroundWindow.argtypes, u.GetForegroundWindow.restype = [], h
    u.GetDpiForSystem.argtypes, u.GetDpiForSystem.restype = [], wintypes.UINT
    u.IsWindow.argtypes, u.IsWindow.restype = [h], b
    u.SetForegroundWindow.argtypes, u.SetForegroundWindow.restype = [h], b
    u.MonitorFromPoint.argtypes, u.MonitorFromPoint.restype = [wintypes.POINT, wintypes.DWORD], p
    _S.SetCurrentProcessExplicitAppUserModelID.argtypes, _S.SetCurrentProcessExplicitAppUserModelID.restype = [wintypes.LPCWSTR], ctypes.c_long
    return u


def fijar_app_id(app_id: str = APP_ID) -> bool:
    """Identidad del proceso para la barra de tareas (antes de crear la ventana); si falla, la app abre igual."""
    if sys.platform != "win32":
        return False
    try:
        _user32()
        return _S.SetCurrentProcessExplicitAppUserModelID(app_id) == 0
    except Exception:
        return False


def poner_icono(hwnd: int, ruta: str = ICONO) -> bool:
    """Icono propio en la ventana (pequeño 16 y grande 32, de un .ico) con WM_SETICON. Si falta el fichero o falla, no rompe."""
    if sys.platform != "win32" or not hwnd or not os.path.isfile(ruta):
        return False
    try:
        u = _user32()
        puesto = False
        for tipo, lado in ((ICON_SMALL, 16), (ICON_BIG, 32)):
            icono = u.LoadImageW(None, ruta, IMAGE_ICON, lado, lado, LR_LOADFROMFILE)
            if icono:
                u.SendMessageW(hwnd, WM_SETICON, tipo, icono)   # el sistema usa el icono mientras viva la ventana: no se destruye
                puesto = True
        return puesto
    except Exception:
        return False


class _FLASHWINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("hwnd", wintypes.HWND), ("dwFlags", wintypes.DWORD),
                ("uCount", wintypes.UINT), ("dwTimeout", wintypes.DWORD)]


FLASHW_ALL, FLASHW_TIMERNOFG = 0x00000003, 0x0000000C   # caption y botón de la barra de tareas; parpadea hasta que la ventana pasa al frente


def llamar_atencion(titulo: str = TITULO) -> bool:
    """Hace parpadear el botón de la ventana en la barra de tareas para avisar de una llamada. No la trae al frente ni le
    quita el foco; si no encuentra la ventana (o no es Windows), no hace nada."""
    if sys.platform != "win32":
        return False
    try:
        hwnd = buscar_hwnd(titulo)
        if not hwnd:
            return False
        info = _FLASHWINFO(ctypes.sizeof(_FLASHWINFO), hwnd, FLASHW_ALL | FLASHW_TIMERNOFG, 0, 0)
        _user32().FlashWindowEx(ctypes.byref(info))   # su valor de retorno es el estado previo del parpadeo, no el éxito
        return True
    except Exception:  # noqa: BLE001 — un aviso visual nunca debe romper la vigilancia
        return False


def fijar_exclusion(hwnd: int, activo: bool) -> bool:
    if sys.platform != "win32" or not hwnd:
        return False
    return bool(_user32().SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE if activo else WDA_NONE))


def leer_afinidad(hwnd: int) -> int | None:
    if sys.platform != "win32" or not hwnd:
        return None
    valor = wintypes.DWORD(0)
    return valor.value if _user32().GetWindowDisplayAffinity(hwnd, ctypes.byref(valor)) else None


def buscar_hwnd(titulo: str = TITULO, pid: int | None = None, solo_visible: bool = True) -> int:
    """HWND de la ventana visible con ese título y que pertenece a ESTE proceso (o a `pid`): nunca la de otra instancia de WhisperMeet.
    `solo_visible=False` también encuentra una ventana que aún no se ha mostrado (el aviso flotante se coloca antes de enseñarlo)."""
    if sys.platform != "win32":
        return 0
    pid = pid or os.getpid()
    u = _user32()
    hallado: list[int] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, _):
        dueno = wintypes.DWORD(0)
        u.GetWindowThreadProcessId(hwnd, ctypes.byref(dueno))
        if dueno.value == pid and (not solo_visible or u.IsWindowVisible(hwnd)):
            buf = ctypes.create_unicode_buffer(256)
            u.GetWindowTextW(hwnd, buf, 256)
            if buf.value == titulo:
                hallado.append(int(hwnd))
        return True

    u.EnumWindows(cb, 0)
    return hallado[0] if hallado else 0


def rect_ventana(hwnd: int) -> tuple[int, int, int, int]:
    r = wintypes.RECT()
    _user32().GetWindowRect(hwnd, ctypes.byref(r))
    return r.left, r.top, r.right, r.bottom


def area_trabajo(hwnd: int) -> tuple[int, int, int, int]:
    """Área de trabajo (sin la barra de tareas) del monitor en que está la ventana."""
    u = _user32()
    mon = u.MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST)
    mi = _MONITORINFO()
    mi.cbSize = ctypes.sizeof(_MONITORINFO)
    u.GetMonitorInfoW(mon, ctypes.byref(mi))
    w = mi.rcWork
    return w.left, w.top, w.right, w.bottom


def dpi_ventana(hwnd: int) -> int:
    return int(_user32().GetDpiForWindow(hwnd) or 96)


def fijar_region(hwnd: int, rects: list[tuple[int, int, int, int]]) -> bool:
    """Deja visibles solo estos rectángulos (coordenadas de ventana). El sistema se queda con la región: no se libera."""
    g = _gdi32()
    total = g.CreateRectRgn(0, 0, 0, 0)
    for a, b, c, d in rects:
        parte = g.CreateRectRgn(a, b, c, d)
        g.CombineRgn(total, total, parte, RGN_OR)
        g.DeleteObject(parte)
    return bool(_user32().SetWindowRgn(hwnd, total, True))


def quitar_region(hwnd: int) -> bool:
    return bool(_user32().SetWindowRgn(hwnd, None, True))


def hay_region(hwnd: int) -> bool:
    g, u = _gdi32(), _user32()
    copia = g.CreateRectRgn(0, 0, 0, 0)
    try:
        return u.GetWindowRgn(hwnd, copia) != 0
    finally:
        g.DeleteObject(copia)


def punto_en_region_ventana(hwnd: int, x: int, y: int) -> bool | None:
    """Con la región real de la ventana (GetWindowRgn): ¿este punto (relativo a la ventana) está dentro? None si no hay región."""
    u = _user32()
    g = _G
    copia = g.CreateRectRgn(0, 0, 0, 0)
    try:
        tipo = u.GetWindowRgn(hwnd, copia)
        if tipo in (0, 1):   # ERROR o NULLREGION
            return None if tipo == 0 else False
        return bool(g.PtInRegion(copia, x, y))
    finally:
        g.DeleteObject(copia)


def fijar_opacidad_ventana(hwnd: int, pct: int) -> bool:
    u = _user32()
    est = u.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
    if MR.opacidad_valida(pct) >= 100:
        if est & WS_EX_LAYERED:
            u.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, est & ~WS_EX_LAYERED)
        return True
    if not est & WS_EX_LAYERED:
        u.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, est | WS_EX_LAYERED)
    return bool(u.SetLayeredWindowAttributes(hwnd, 0, MR.opacidad_a_alfa(pct), LWA_ALPHA))


def leer_alfa(hwnd: int) -> int | None:
    u = _user32()
    if not u.GetWindowLongPtrW(hwnd, GWL_EXSTYLE) & WS_EX_LAYERED:
        return 255
    alfa, banderas, clave = ctypes.c_ubyte(0), wintypes.DWORD(0), wintypes.COLORREF(0)
    return int(alfa.value) if u.GetLayeredWindowAttributes(hwnd, ctypes.byref(clave), ctypes.byref(alfa), ctypes.byref(banderas)) else None


# ---------------------------------------------------------------- aviso flotante de llamada de Teams
WS_EX_TOPMOST, WS_EX_TOOLWINDOW, WS_EX_APPWINDOW, WS_EX_NOACTIVATE = 0x00000008, 0x00000080, 0x00040000, 0x08000000
SW_SHOWNOACTIVATE = 4
MONITOR_DEFAULTTOPRIMARY = 1
DWMWA_WINDOW_CORNER_PREFERENCE, DWMWCP_ROUND = 33, 2
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
TITULO_AVISO = "WhisperMeet · Aviso de llamada"
EXES_TEAMS = frozenset({"ms-teams.exe", "msteams.exe", "teams.exe"})   # Teams nuevo (empaquetado) y clásico


def titulos_ventanas_de(exes=EXES_TEAMS) -> list[str]:
    """Títulos de las ventanas visibles de los procesos cuyo ejecutable (nombre, sin ruta) está en `exes`, de la de más arriba en el orden Z
    a la de más abajo. Solo lee Win32 (EnumWindows, GetWindowText, QueryFullProcessImageName): nada sale de la máquina. Nunca lanza."""
    if sys.platform != "win32":
        return []
    try:
        u = _user32()
        k = ctypes.WinDLL("kernel32", use_last_error=True)
        k.OpenProcess.argtypes, k.OpenProcess.restype = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD], wintypes.HANDLE
        k.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
        k.QueryFullProcessImageNameW.restype = wintypes.BOOL
        k.CloseHandle.argtypes, k.CloseHandle.restype = [wintypes.HANDLE], wintypes.BOOL
        nombres: dict[int, str] = {}
        salida: list[str] = []
        buscados = {e.lower() for e in exes}

        def exe_de(pid: int) -> str:
            if pid not in nombres:
                nombres[pid] = ""
                h = k.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
                if h:
                    try:
                        buf, n = ctypes.create_unicode_buffer(520), wintypes.DWORD(520)
                        if k.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n)):
                            nombres[pid] = os.path.basename(buf.value).lower()
                    finally:
                        k.CloseHandle(h)
            return nombres[pid]

        @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def cb(hwnd, _):
            if u.IsWindowVisible(hwnd):
                dueno = wintypes.DWORD(0)
                u.GetWindowThreadProcessId(hwnd, ctypes.byref(dueno))
                buf = ctypes.create_unicode_buffer(400)
                u.GetWindowTextW(hwnd, buf, 400)
                if buf.value and exe_de(dueno.value) in buscados:
                    salida.append(buf.value)
            return True

        u.EnumWindows(cb, 0)
        return salida
    except Exception:  # noqa: BLE001 — leer el título es un extra: si falla, el aviso usa el tema por defecto
        return []


def _tema_del_sistema_claro() -> bool:
    """¿El sistema usa el tema claro para las aplicaciones? (Solo para el color de fondo mientras carga la página.)"""
    try:
        import winreg as _w
        with _w.OpenKey(_w.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as k:
            return int(_w.QueryValueEx(k, "AppsUseLightTheme")[0]) == 1
    except Exception:  # noqa: BLE001
        return False


def ventana_en_primer_plano() -> int:
    return int(_user32().GetForegroundWindow() or 0) if sys.platform == "win32" else 0


def area_trabajo_principal() -> tuple[int, int, int, int]:
    """Área de trabajo (sin barra de tareas) del monitor PRINCIPAL, en píxeles físicos."""
    u = _user32()
    mon = u.MonitorFromPoint(wintypes.POINT(0, 0), MONITOR_DEFAULTTOPRIMARY)
    mi = _MONITORINFO()
    mi.cbSize = ctypes.sizeof(_MONITORINFO)
    u.GetMonitorInfoW(mon, ctypes.byref(mi))
    w = mi.rcWork
    return w.left, w.top, w.right, w.bottom


def geometria_aviso(trabajo: tuple[int, int, int, int], ancho_css: float, alto_css: float, escala: float, margen_css: float = 14) -> tuple[int, int, int, int]:
    """(x, y, ancho, alto) en píxeles físicos del aviso: centrado en horizontal sobre el área de trabajo y pegado arriba con un margen.
    Función pura (con tests)."""
    izq, arr, der, _ = trabajo
    ancho, alto = max(1, round(ancho_css * escala)), max(1, round(alto_css * escala))
    return izq + (der - izq - ancho) // 2, arr + round(margen_css * escala), ancho, alto


class VentanaAviso:
    """Ventana flotante del aviso de llamada: pywebview sin marco, siempre encima, pequeña, centrada arriba en el monitor principal, que NO
    toma el foco (WS_EX_NOACTIVATE + SWP_NOACTIVATE + ShowWindow(SW_SHOWNOACTIVATE)), fuera de la barra de tareas (WS_EX_TOOLWINDOW) y
    excluida de la captura con la misma afinidad que la ventana principal. Se localiza por PID, nunca solo por título.
    Solo cuando la persona hace clic en el campo del tema (hace falta teclado) `pedir_teclado` la activa; al salir del campo vuelve a no activarse."""
    ANCHO_CSS, ALTO_CSS = 420, 190

    def __init__(self, excluir_captura: bool = True, al_cerrar=None, titulo: str = TITULO_AVISO):
        self.titulo, self.excluir, self.al_cerrar = titulo, excluir_captura, al_cerrar
        self.hwnd = 0
        self.afinidad: int | None = None
        self._w = None
        self._cerrada = False
        self._teclado = False   # la persona hizo clic en el campo del tema: ahora sí puede tener el foco
        self._lock = threading.RLock()

    def abrir(self, url: str, esperar_s: float = 15.0) -> None:
        """Crea la ventana, la coloca y la enseña sin activarla. Lanza si algo falla (el llamador cae al banner).

        NO se crea con `hidden=True`: pywebview la mostraría y ocultaría de golpe (`Show(); Hide()`), y ese parpadeo de 20 ms sí le quita el foco a
        la ventana de Teams y pierde `WS_EX_NOACTIVATE`. Con `focus=False` el estilo se pone antes del primer `Show()` y la ventana nace ya en su
        sitio (posición calculada en píxeles físicos y pasada en lógicos), sin activarse."""
        import webview
        if self._w is not None:
            return
        u = _user32()
        previo = int(u.GetForegroundWindow() or 0)     # quien tiene el foco ahora (Teams, normalmente): se le devuelve si algo se lo quita
        escala_sistema = (u.GetDpiForSystem() or 96) / 96      # la que usa pywebview al crear la ventana (el proceso es DPI-aware de sistema)
        x, y, _, _ = geometria_aviso(area_trabajo_principal(), self.ANCHO_CSS, self.ALTO_CSS, escala_sistema)
        self._w = webview.create_window(self.titulo, url, width=self.ANCHO_CSS, height=self.ALTO_CSS, x=round(x / escala_sistema), y=round(y / escala_sistema),
                                        frameless=True, easy_drag=False, on_top=True, focus=False, resizable=False,
                                        background_color="#FFFFFF" if _tema_del_sistema_claro() else "#1E1F26")
        if self._w is None:
            raise RuntimeError("pywebview no pudo crear la ventana del aviso.")
        self._w.events.closed += self._al_cerrarse
        t0 = time.time()
        while not self.hwnd and time.time() - t0 < esperar_s:
            self.hwnd = buscar_hwnd(self.titulo, solo_visible=False)
            if not self.hwnd:
                time.sleep(0.05)
        if not self.hwnd:
            raise RuntimeError("No se encontró la ventana del aviso (por PID).")
        with self._lock:
            # Sin ocultar ni volver a enseñar la ventana: hacerlo mientras WebView2 aún se inicializa lo deja con visibilityState «hidden»
            # (la página no pinta ni cuenta fotogramas: se vería una ventana vacía). El estilo se cambia con la ventana ya visible.
            est = u.GetWindowLongPtrW(self.hwnd, GWL_EXSTYLE)
            # WinForms pone WS_EX_APPWINDOW (botón en la barra de tareas): fuera. Medido por captura de la barra: al quitarlo con la ventana ya
            # visible, el botón desaparece sin ocultarla.
            u.SetWindowLongPtrW(self.hwnd, GWL_EXSTYLE, (est | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW) & ~WS_EX_APPWINDOW)
            try:
                ctypes.windll.dwmapi.DwmSetWindowAttribute(self.hwnd, DWMWA_WINDOW_CORNER_PREFERENCE, ctypes.byref(ctypes.c_int(DWMWCP_ROUND)), 4)
            except Exception:  # noqa: BLE001 — esquinas redondeadas: solo estética (Windows 11)
                pass
            self.poner_exclusion(self.excluir)
            self._colocar(self.ALTO_CSS, mostrar=True)
        threading.Thread(target=self._guardar_foco, args=(previo,), daemon=True, name="aviso-foco").start()

    def _guardar_foco(self, previo: int, durante_s: float = 4.0) -> None:
        """Mientras la página carga, WebView2 puede pedir el foco para su ventana (si la app ya era la ventana activa, Windows se lo permite aunque la
        ventana lleve WS_EX_NOACTIVATE). Si eso pasa sin que la persona haya hecho clic en el tema, el foco vuelve a quien lo tenía."""
        u = _user32()
        t0 = time.time()
        while time.time() - t0 < durante_s and self.hwnd and not self._cerrada:
            try:
                if not self._teclado and previo and previo != self.hwnd and int(u.GetForegroundWindow() or 0) == self.hwnd and u.IsWindow(previo):
                    u.SetForegroundWindow(previo)
            except Exception:  # noqa: BLE001
                return
            time.sleep(0.01)

    def escala(self) -> float:
        return (dpi_ventana(self.hwnd) if self.hwnd else 96) / 96

    def _en_hilo_gui(self, fn) -> None:
        """Ejecuta `fn` en el hilo de la interfaz nativa (el dueño de la ventana). Medido: desde otro hilo, con una ventana ajena en primer plano
        (Teams), `SetWindowPos(HWND_TOPMOST)` no deja la ventana siempre encima; desde el hilo que la creó, sí."""
        nativa = getattr(self._w, "native", None)
        try:
            from System import Func, Type
            if nativa is not None and nativa.InvokeRequired:
                nativa.Invoke(Func[Type](fn))
                return
        except Exception:  # noqa: BLE001 — sin pythonnet o sin ventana nativa: se hace desde este hilo
            pass
        fn()

    def _colocar(self, alto_css: float, mostrar: bool = False) -> None:
        u = _user32()
        x, y, ancho, alto = geometria_aviso(area_trabajo_principal(), self.ANCHO_CSS, alto_css, self.escala())
        banderas = SWP_NOACTIVATE | (SWP_SHOWWINDOW if mostrar else 0)

        def poner():
            nativa = getattr(self._w, "native", None)
            if mostrar and nativa is not None and not u.GetWindowLongPtrW(self.hwnd, GWL_EXSTYLE) & WS_EX_TOPMOST:
                # Medido: con una ventana ajena en primer plano, WinForms creó la ventana pero sin WS_EX_TOPMOST y SetWindowPos(HWND_TOPMOST) no
                # lo arregla; quitar y volver a poner TopMost desde el hilo de la interfaz sí la deja siempre encima (sin activarla).
                nativa.TopMost = False
                nativa.TopMost = True
            u.SetWindowPos(self.hwnd, HWND_TOPMOST, x, y, ancho, alto, banderas)
            if mostrar:
                u.ShowWindow(self.hwnd, SW_SHOWNOACTIVATE)
        self._en_hilo_gui(poner)

    def poner_exclusion(self, activo: bool) -> None:
        self.excluir = activo
        if self.hwnd:
            fijar_exclusion(self.hwnd, activo)
            self.afinidad = leer_afinidad(self.hwnd)

    def redimensionar(self, alto_css: float) -> None:
        """Cambia el alto (el desplegable crece o se recoge) manteniendo el aviso centrado arriba y sin activarlo."""
        with self._lock:
            if self.hwnd and not self._cerrada:
                self._colocar(max(80.0, min(float(alto_css), 640.0)))

    def pedir_teclado(self, si: bool) -> None:
        """Solo tras un clic en el campo del tema: la ventana se deja activar para poder escribir; al salir del campo vuelve a no activarse."""
        with self._lock:
            if not self.hwnd or self._cerrada:
                return
            u = _user32()
            est = u.GetWindowLongPtrW(self.hwnd, GWL_EXSTYLE)
            self._teclado = si
            if si:
                u.SetWindowLongPtrW(self.hwnd, GWL_EXSTYLE, est & ~WS_EX_NOACTIVATE)
                u.SetForegroundWindow(self.hwnd)
            else:
                u.SetWindowLongPtrW(self.hwnd, GWL_EXSTYLE, est | WS_EX_NOACTIVATE)

    def medir(self) -> dict:
        """Lo que ve Win32 ahora mismo (para las pruebas y los diagnósticos)."""
        if not self.hwnd:
            return {}
        u = _user32()
        est = u.GetWindowLongPtrW(self.hwnd, GWL_EXSTYLE)
        return {"hwnd": self.hwnd, "rect": rect_ventana(self.hwnd), "topmost": bool(est & WS_EX_TOPMOST), "noactivate": bool(est & WS_EX_NOACTIVATE),
                "toolwindow": bool(est & WS_EX_TOOLWINDOW), "appwindow": bool(est & WS_EX_APPWINDOW), "afinidad": leer_afinidad(self.hwnd), "dpi": dpi_ventana(self.hwnd),
                "visible": bool(u.IsWindowVisible(self.hwnd))}

    def _al_cerrarse(self, *_):
        self._cerrada = True
        self.hwnd = 0
        if self.al_cerrar:
            try:
                self.al_cerrar()
            except Exception:  # noqa: BLE001
                pass

    def cerrar(self) -> None:
        with self._lock:
            w, self._cerrada = self._w, True
        if w is not None:
            try:
                w.destroy()
            except Exception:  # noqa: BLE001 — si la ventana ya no existe, da igual
                pass




class Ventana:
    def __init__(self, url: str, excluir_captura: bool, verificar_y_cerrar_s: float | None = None):
        self.url, self.excluir = url, excluir_captura
        self.hwnd = 0
        self.afinidad: int | None = None
        self._cerrar_tras = verificar_y_cerrar_s
        self._w = None
        self._lock = threading.RLock()
        self._dialogo = threading.Lock()   # un solo selector de carpetas a la vez
        # Modo reunión
        self.modo_activo = False
        self.layout: dict | None = None
        self.escala = 1.0
        self.opacidad = 100
        self._guardado: dict | None = None
        self.afinidad_reaplicada = False
        self.region_reintentos = 0

    # ------------------------------------------------------------ captura
    def _asegurar_hwnd(self) -> int:
        if not self.hwnd:
            self.hwnd = buscar_hwnd()
        return self.hwnd

    def aplicar(self, activo: bool) -> None:
        self.excluir = activo
        self._asegurar_hwnd()
        fijar_exclusion(self.hwnd, activo)
        self.afinidad = leer_afinidad(self.hwnd)

    # ------------------------------------------------------------ selector de carpetas
    def elegir_carpeta(self, inicial: str = "") -> str | None:
        """Selector de carpetas NATIVO de Windows (FOLDER_DIALOG de pywebview; FileDialog.FOLDER en las versiones nuevas). Se puede llamar
        desde cualquier hilo: pywebview lo muestra en el hilo de la interfaz y bloquea al que llama hasta que el usuario elige o cancela
        (por eso el servidor lo llama con `asyncio.to_thread`, nunca desde su bucle de eventos). `inicial`: carpeta donde se abre (si no
        existe, la elige Windows). Devuelve la ruta elegida o None si cancela."""
        if self._w is None:
            raise ValueError("La ventana nativa de WhisperMeet todavía no está lista.")
        if not self._dialogo.acquire(blocking=False):
            raise ValueError("Ya hay un selector de carpetas abierto.")
        try:
            import webview
            tipo = webview.FileDialog.FOLDER if hasattr(webview, "FileDialog") else webview.FOLDER_DIALOG
            elegido = self._w.create_file_dialog(tipo, directory=inicial or "")
        finally:
            self._dialogo.release()
        return str(elegido[0]) if elegido else None

    # ------------------------------------------------------------ Modo reunión
    def estado_modo(self) -> dict:
        hwnd = self._asegurar_hwnd()
        e = {"activo": self.modo_activo, "layout": self.layout, "escala": self.escala, "opacidad": self.opacidad,
             "opacidad_soportada": OPACIDAD_SOPORTADA, "afinidad": leer_afinidad(hwnd) if hwnd else None,
             "afinidad_reaplicada": self.afinidad_reaplicada, "region_reintentos": self.region_reintentos}
        if hwnd:
            e["rect"] = list(rect_ventana(hwnd))
            e["dpi"] = dpi_ventana(hwnd)
        return e

    def _calcular_y_aplicar_region(self, hwnd: int, prefs: dict, dpr: float | None, ancho_px: int, alto_px: int) -> None:
        self.escala = MR.elegir_escala(dpi_ventana(hwnd), dpr)
        self.layout = MR.calcular_layout(MR.a_css(ancho_px, self.escala), prefs.get("izq"), prefs.get("der"), prefs.get("uno"))
        fijar_region(hwnd, MR.rectangulos_region(ancho_px, alto_px, self.layout, self.escala))

    def entrar(self, prefs: dict, dpr: float | None = None) -> dict:
        """Ventana sin marco, siempre encima y del tamaño del área de trabajo; solo los paneles forman parte de la ventana."""
        with self._lock:
            hwnd = self._asegurar_hwnd()
            if not hwnd:
                raise RuntimeError("No se encontró la ventana de WhisperMeet.")
            u = _user32()
            if not self.modo_activo:
                zoomed = bool(u.IsZoomed(hwnd))
                if zoomed:
                    u.ShowWindow(hwnd, SW_RESTORE)
                self._guardado = {"rect": rect_ventana(hwnd), "estilo": u.GetWindowLongPtrW(hwnd, GWL_STYLE),
                                  "estilo_ex": u.GetWindowLongPtrW(hwnd, GWL_EXSTYLE), "maximizada": zoomed}
            izq, arr, der, aba = area_trabajo(hwnd)
            ancho, alto = der - izq, aba - arr
            # 1.º la región (con el tamaño de destino) y 2.º el tamaño: así no hay ni un fotograma con la ventana entera tapando Teams
            self._calcular_y_aplicar_region(hwnd, prefs, dpr, ancho, alto)
            estilo = self._guardado["estilo"] & ~(WS_CAPTION | WS_THICKFRAME | WS_MAXIMIZEBOX | WS_MINIMIZEBOX)
            u.SetWindowLongPtrW(hwnd, GWL_STYLE, estilo)
            u.SetWindowPos(hwnd, HWND_TOPMOST, izq, arr, ancho, alto, SWP_FRAMECHANGED | SWP_SHOWWINDOW)
            self.modo_activo = True
            self._calcular_y_aplicar_region(hwnd, prefs, dpr, *self._tam_cliente(hwnd))   # con el tamaño real que dejó WinForms
            self.afinidad_reaplicada = False
            if self.excluir and leer_afinidad(hwnd) != WDA_EXCLUDEFROMCAPTURE:
                fijar_exclusion(hwnd, True)
                self.afinidad_reaplicada = True
            self.afinidad = leer_afinidad(hwnd)
            if OPACIDAD_SOPORTADA:
                self.fijar_opacidad(prefs.get("opacidad", self.opacidad))
            return self.estado_modo()

    @staticmethod
    def _tam_cliente(hwnd: int) -> tuple[int, int]:
        r = wintypes.RECT()
        _user32().GetClientRect(hwnd, ctypes.byref(r))
        return r.right - r.left, r.bottom - r.top

    def actualizar(self, prefs: dict, dpr: float | None = None) -> dict:
        """Recalcula la región (cambio de tamaño, de escala DPI o de medidas de los paneles)."""
        with self._lock:
            if not self.modo_activo or not self.hwnd:
                return self.estado_modo()
            self._calcular_y_aplicar_region(self.hwnd, prefs, dpr, *self._tam_cliente(self.hwnd))
            return self.estado_modo()

    def fijar_opacidad(self, pct) -> bool:
        with self._lock:
            self.opacidad = MR.opacidad_valida(pct)
            if not (OPACIDAD_SOPORTADA and self.modo_activo and self.hwnd):
                return False
            return fijar_opacidad_ventana(self.hwnd, self.opacidad)

    def salir(self) -> dict:
        """Vuelve al tamaño, posición y estado (maximizada o no) de antes y deja de estar siempre encima."""
        with self._lock:
            hwnd = self._asegurar_hwnd()
            if not (self.modo_activo and hwnd and self._guardado):
                self.modo_activo = False
                return self.estado_modo()
            u, g = _user32(), self._guardado
            fijar_opacidad_ventana(hwnd, 100)
            u.SetWindowLongPtrW(hwnd, GWL_STYLE, g["estilo"])
            izq, arr, der, aba = g["rect"]
            u.SetWindowPos(hwnd, HWND_NOTOPMOST, izq, arr, der - izq, aba - arr, SWP_FRAMECHANGED | SWP_SHOWWINDOW)
            # La región se quita al final (así no aparece la ventana entera a tamaño de pantalla) y se comprueba: medido, alguna vez
            # el cambio de marco la deja puesta; se reintenta hasta que GetWindowRgn confirma que no hay región.
            self.region_reintentos = 0
            for i in range(20):
                quitar_region(hwnd)
                if not hay_region(hwnd):
                    break
                self.region_reintentos = i + 1
                time.sleep(0.05)
            if g["maximizada"]:
                u.ShowWindow(hwnd, SW_MAXIMIZE)
            self.modo_activo, self.layout, self._guardado = False, None, None
            self.afinidad = leer_afinidad(hwnd)
            return self.estado_modo()

    def abrir(self) -> None:
        """Bloquea en el hilo principal hasta cerrar la ventana."""
        import webview
        fijar_app_id()
        self._w = webview.create_window(TITULO, self.url, width=1360, height=860, min_size=(1000, 680),
                                        background_color="#F6F6F3")

        def al_mostrar():
            self.aplicar(self.excluir)
            poner_icono(self._asegurar_hwnd())
            if self._cerrar_tras is not None:
                threading.Timer(self._cerrar_tras, self._w.destroy).start()

        self._w.events.shown += al_mostrar
        webview.start()
