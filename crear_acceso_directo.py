r"""Crea el acceso directo de WhisperMeet (.lnk) con icono propio y AppUserModelID, para anclarlo a la barra de tareas o a Inicio.

    .venv\Scripts\python.exe crear_acceso_directo.py                    # %APPDATA%\Microsoft\Windows\Start Menu\Programs\WhisperMeet.lnk
    .venv\Scripts\python.exe crear_acceso_directo.py --ruta C:\x\WhisperMeet.lnk
    .venv\Scripts\python.exe crear_acceso_directo.py --leer C:\x\WhisperMeet.lnk   # lee un .lnk y muestra sus datos

COM con ctypes puro (llamadas por vtable); sin pywin32. Destino: .venv\Scripts\pythonw.exe (sin consola) con app.py.
"""
from __future__ import annotations

import argparse
import ctypes
import os
import sys
from ctypes import wintypes
from pathlib import Path

from apuntes.ventana import APP_ID, ICONO

RAIZ = Path(__file__).resolve().parent
PYTHONW = RAIZ / ".venv" / "Scripts" / "pythonw.exe"
APP = RAIZ / "app.py"
DESCRIPCION = "WhisperMeet: notas de reuniones"

CLSID_ShellLink = "{00021401-0000-0000-C000-000000000046}"
IID_IShellLinkW = "{000214F9-0000-0000-C000-000000000046}"
IID_IPersistFile = "{0000010B-0000-0000-C000-000000000046}"
IID_IPropertyStore = "{886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99}"
PKEY_AppUserModel_ID = ("{9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3}", 5)
VT_LPWSTR = 31
CLSCTX_INPROC_SERVER, COINIT_APARTMENTTHREADED = 1, 2
STGM_READ = 0


class GUID(ctypes.Structure):
    _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD), ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]


class PROPERTYKEY(ctypes.Structure):
    _fields_ = [("fmtid", GUID), ("pid", wintypes.DWORD)]


class PROPVARIANT(ctypes.Structure):
    """24 bytes en x64 (vt + 3 reservados + unión de 16): el valor de texto es un puntero en el primer campo de la unión."""
    _fields_ = [("vt", wintypes.WORD), ("r1", wintypes.WORD), ("r2", wintypes.WORD), ("r3", wintypes.WORD),
                ("pwsz", ctypes.c_void_p), ("pad", ctypes.c_void_p)]


def _ole():
    o = ctypes.OleDLL("ole32")   # OleDLL: lanza OSError si un HRESULT falla
    o.CLSIDFromString.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(GUID)]
    o.CoInitializeEx.argtypes = [ctypes.c_void_p, wintypes.DWORD]
    o.CoCreateInstance.argtypes = [ctypes.POINTER(GUID), ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p)]
    o.PropVariantClear.argtypes = [ctypes.POINTER(PROPVARIANT)]
    return o


def _guid(ole, texto: str) -> GUID:
    g = GUID()
    ole.CLSIDFromString(texto, ctypes.byref(g))
    return g


def _ok(hr: int) -> int:
    if hr < 0:
        raise OSError(f"HRESULT 0x{hr & 0xFFFFFFFF:08X}")
    return hr


def _vt(obj: ctypes.c_void_p, indice: int, *tipos):
    """Método `indice` de la vtable de un objeto COM, como función ctypes (HRESULT; el primer argumento es `this`)."""
    tabla = ctypes.cast(ctypes.cast(obj, ctypes.POINTER(ctypes.c_void_p))[0], ctypes.POINTER(ctypes.c_void_p))
    proto = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, *tipos)
    return lambda *a: _ok(proto(tabla[indice])(obj, *a))


def _liberar(obj) -> None:
    if obj is not None and obj.value:
        _vt(obj, 2)()   # IUnknown::Release


def _consultar(ole, obj, iid: str) -> ctypes.c_void_p:
    salida = ctypes.c_void_p()
    _vt(obj, 0, ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p))(ctypes.byref(_guid(ole, iid)), ctypes.byref(salida))
    return salida


def _crear_enlace(ole) -> ctypes.c_void_p:
    enlace = ctypes.c_void_p()
    ole.CoCreateInstance(ctypes.byref(_guid(ole, CLSID_ShellLink)), None, CLSCTX_INPROC_SERVER,
                         ctypes.byref(_guid(ole, IID_IShellLinkW)), ctypes.byref(enlace))
    return enlace


def _clave(ole) -> PROPERTYKEY:
    k = PROPERTYKEY()
    k.fmtid, k.pid = _guid(ole, PKEY_AppUserModel_ID[0]), PKEY_AppUserModel_ID[1]
    return k


def crear(ruta: Path) -> None:
    if not PYTHONW.is_file():
        raise FileNotFoundError(f"No existe {PYTHONW} (¿falta el entorno .venv?)")
    if not os.path.isfile(ICONO):
        raise FileNotFoundError(f"No existe {ICONO} (ejecuta marca\\generar_logo.py)")
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ole = _ole()
    ole.CoInitializeEx(None, COINIT_APARTMENTTHREADED)
    enlace = almacen = fichero = None
    try:
        enlace = _crear_enlace(ole)
        W = wintypes.LPCWSTR
        _vt(enlace, 20, W)(str(PYTHONW))                  # SetPath
        _vt(enlace, 11, W)(f'"{APP}"')                    # SetArguments
        _vt(enlace, 9, W)(str(RAIZ))                      # SetWorkingDirectory
        _vt(enlace, 17, W, ctypes.c_int)(ICONO, 0)        # SetIconLocation
        _vt(enlace, 7, W)(DESCRIPCION)                    # SetDescription
        almacen = _consultar(ole, enlace, IID_IPropertyStore)
        texto = ctypes.create_unicode_buffer(APP_ID)      # SetValue copia la cadena: el búfer solo ha de vivir hasta la llamada
        valor = PROPVARIANT()
        valor.vt, valor.pwsz = VT_LPWSTR, ctypes.cast(texto, ctypes.c_void_p).value
        _vt(almacen, 6, ctypes.POINTER(PROPERTYKEY), ctypes.POINTER(PROPVARIANT))(ctypes.byref(_clave(ole)), ctypes.byref(valor))
        _vt(almacen, 7)()                                 # Commit
        fichero = _consultar(ole, enlace, IID_IPersistFile)
        _vt(fichero, 6, W, wintypes.BOOL)(str(ruta), True)   # Save
    finally:
        for o in (fichero, almacen, enlace):
            _liberar(o)
        ole.CoUninitialize()


def leer(ruta: Path) -> dict:
    ole = _ole()
    ole.CoInitializeEx(None, COINIT_APARTMENTTHREADED)
    enlace = almacen = fichero = None
    try:
        enlace = _crear_enlace(ole)
        fichero = _consultar(ole, enlace, IID_IPersistFile)
        _vt(fichero, 5, wintypes.LPCWSTR, wintypes.DWORD)(str(ruta), STGM_READ)   # Load
        almacen = _consultar(ole, enlace, IID_IPropertyStore)

        def texto(indice: int) -> str:   # GetDescription 6, GetWorkingDirectory 8, GetArguments 10
            b = ctypes.create_unicode_buffer(1024)
            _vt(enlace, indice, wintypes.LPWSTR, ctypes.c_int)(b, 1024)
            return b.value

        destino = ctypes.create_unicode_buffer(1024)
        _vt(enlace, 3, wintypes.LPWSTR, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD)(destino, 1024, None, 0)   # GetPath
        icono, indice = ctypes.create_unicode_buffer(1024), ctypes.c_int()
        _vt(enlace, 16, wintypes.LPWSTR, ctypes.c_int, ctypes.POINTER(ctypes.c_int))(icono, 1024, ctypes.byref(indice))
        valor = PROPVARIANT()
        _vt(almacen, 5, ctypes.POINTER(PROPERTYKEY), ctypes.POINTER(PROPVARIANT))(ctypes.byref(_clave(ole)), ctypes.byref(valor))
        app_id = ctypes.wstring_at(valor.pwsz) if valor.vt == VT_LPWSTR and valor.pwsz else None
        ole.PropVariantClear(ctypes.byref(valor))
        return {"ruta": destino.value, "argumentos": texto(10), "carpeta": texto(8), "icono": icono.value, "icono_indice": indice.value,
                "descripcion": texto(6), "app_id": app_id}
    finally:
        for o in (almacen, fichero, enlace):
            _liberar(o)
        ole.CoUninitialize()


def ruta_por_defecto() -> Path:
    return Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "WhisperMeet.lnk"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Crea el acceso directo de WhisperMeet (anclable a la barra de tareas).")
    ap.add_argument("--ruta", metavar="FICHERO.lnk", help="dónde crearlo (por defecto, el menú Inicio del usuario)")
    ap.add_argument("--leer", metavar="FICHERO.lnk", help="solo lee un .lnk y muestra sus datos")
    args = ap.parse_args(argv)
    if sys.platform != "win32":
        print("Solo Windows.", file=sys.stderr)
        return 1
    if args.leer:
        for k, v in leer(Path(args.leer)).items():
            print(f"{k}: {v}")
        return 0
    ruta = Path(args.ruta).resolve() if args.ruta else ruta_por_defecto()
    crear(ruta)
    print(f"Acceso directo creado: {ruta}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
