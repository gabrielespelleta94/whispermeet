"""Ola F: copia de seguridad de los datos propios de la app, en un zip dentro de la carpeta de copias del Guardián.

Qué entra: las carpetas de datos de la app que el Guardián conoce (`rutas.ATRIBUTOS_DE_COPIA`: ajustes y datos de la app, borradores de la bandeja, sesiones locales, planes,
comprobaciones, estado del backlog, seguimiento y tipos de documento); una que no existe o no está configurada se salta. Qué no entra: la caché (se regenera), los modelos de
Whisper, el entorno virtual, las copias anteriores y los documentos de los proyectos (son del usuario y pueden ser enormes).

Dentro del zip cada fichero va con su ruta relativa a la carpeta de la app (restaurar es descomprimir sobre ella) y `MANIFIESTO.json` en la raíz. Cuidados: no se siguen enlaces
simbólicos ni uniones; la ruta real de cada fichero debe caer dentro de su carpeta; lo que no se puede leer, pesa más de 200 MB, tiene nombre con pinta de secreto o un nombre que
no cabe en el zip, o repite la ruta de otro fichero va a `omitidos` con su motivo (un fallo de UN fichero nunca aborta la copia; una fecha fuera del rango del zip se recorta);
con 2 GB en total la copia se corta y se dice (`cortada`). Se escribe a un nombre temporal en la misma carpeta y se renombra al final.

El ÚNICO borrado de este módulo es el del temporal a medias que esta misma operación acaba de crear (`_quitar_temporal`). Nunca se borran copias antiguas."""
from __future__ import annotations

import json
import os
import time
import zipfile
from datetime import datetime, timedelta
from pathlib import Path

from . import __version__
from .rutas import es_secreto, esta_dentro

TOPE_FICHERO = 200 * 1024 * 1024     # un fichero por encima de esto no entra (va a `omitidos`)
TOPE_TOTAL = 2 * 1024 ** 3           # con esto en bytes sin comprimir, la copia se corta (y se dice)
NOMBRE_MANIFIESTO = "MANIFIESTO.json"
_BLOQUE = 1024 * 1024
_SUELO_FECHA = (1980, 1, 1, 0, 0, 0)         # el zip no admite fechas fuera de 1980-01-01 … 2107-12-31
_TECHO_FECHA = (2107, 12, 31, 23, 59, 58)


def _fecha_zip(mtime) -> tuple:
    """Fecha local de modificación recortada al rango que admite el zip; ante cualquier fallo, el suelo. Se compara la tupla local, no el instante UTC."""
    try:
        f = tuple(time.localtime(mtime)[:6])
    except Exception:   # noqa: BLE001  (fecha negativa, enorme o NaN: OSError, OverflowError, ValueError…)
        return _SUELO_FECHA
    return max(_SUELO_FECHA, min(_TECHO_FECHA, f))


def _serializable(texto: str) -> str:
    """Una ruta que siempre cabe en JSON y en el manifiesto (un carácter suelto no codificable pasa a «?»)."""
    return texto.encode("utf-8", "replace").decode("utf-8")


def nombre_de_copia(ahora: datetime) -> str:
    return f"whispermeet-copia-{ahora:%Y-%m-%d-%H%M%S}.zip"


def _humano(n: int) -> str:
    if n >= 1024 * 1024:
        return f"{n / (1024 * 1024):.0f} MB".replace(".0", "")
    if n >= 1024:
        return f"{n / 1024:.0f} KB"
    return f"{n} bytes"


def _ruta_real(p) -> Path:
    return Path(os.path.realpath(p))


def _es_enlace(p) -> bool:
    return os.path.islink(p) or os.path.isjunction(p)


def _leer(ruta, tope: int) -> bytes:
    """Todo el fichero, tal como esté ahora (un registro que otro proceso escribe se copia como esté). Lanza OSError si no se puede leer y ValueError si crece por encima del tope."""
    trozos, total = [], 0
    with open(ruta, "rb") as f:
        while True:
            b = f.read(_BLOQUE)
            if not b:
                break
            total += len(b)
            if total > tope:
                raise ValueError(total)
            trozos.append(b)
    return b"".join(trozos)


def _quitar_temporal(guardian, tmp: Path) -> None:
    """El único borrado del módulo: el fichero `.parcial` que esta misma operación creó dentro de la carpeta de copias. Cualquier otra ruta se ignora."""
    carpeta = guardian.copias
    if carpeta is None or not tmp.name.endswith(".parcial") or tmp.parent != carpeta or not esta_dentro(carpeta, tmp):
        return
    if tmp.is_symlink() or not tmp.is_file():
        return
    try:
        os.remove(tmp)
    except OSError:
        pass


def _arc(base: Path, carpeta: Path) -> str:
    """Prefijo de una carpeta dentro del zip: su ruta relativa a la carpeta de la app (o su nombre, si está en otro sitio)."""
    try:
        rel = Path(os.path.abspath(carpeta)).relative_to(Path(os.path.abspath(base)))
        return "" if rel.as_posix() == "." else rel.as_posix()
    except ValueError:
        return carpeta.name


def _candidatos(fuente: Path, prefijo: str, copias: Path, omitidos: list):
    """(ruta del disco, ruta dentro del zip) de cada fichero de una fuente, en orden estable. Lo que no se sigue o no se admite se anota en `omitidos`."""
    if not os.path.lexists(fuente):
        return
    if _es_enlace(fuente):
        omitidos.append({"ruta": prefijo, "motivo": "Es un enlace; no se sigue."})
        return
    if fuente.is_file():
        yield fuente, prefijo
        return
    if not fuente.is_dir():
        return
    raiz_real = _ruta_real(fuente)
    pila = [(fuente, prefijo)]
    while pila:
        carpeta, pref = pila.pop()
        try:
            entradas = sorted(os.scandir(carpeta), key=lambda e: e.name)
        except OSError as e:
            omitidos.append({"ruta": pref, "motivo": f"No se pudo leer la carpeta ({e.strerror or 'sin acceso'})."})
            continue
        subcarpetas = []
        for e in entradas:
            ruta = Path(e.path)
            rel = f"{pref}/{e.name}" if pref else e.name
            if esta_dentro(copias, ruta):
                continue   # la carpeta de copias (con sus temporales .parcial) nunca entra en una copia; fuera de ella, un .parcial es un dato más
            if _es_enlace(ruta):
                omitidos.append({"ruta": rel, "motivo": "Es un enlace; no se sigue."})
            elif e.is_dir(follow_symlinks=False):
                subcarpetas.append((ruta, rel))
            elif e.is_file(follow_symlinks=False):
                if es_secreto(e.name):
                    omitidos.append({"ruta": rel, "motivo": "El nombre parece de una clave o credencial; no entra."})
                elif not esta_dentro(raiz_real, _ruta_real(ruta)):
                    omitidos.append({"ruta": rel, "motivo": "Su ruta real queda fuera de su carpeta; no entra."})
                else:
                    yield ruta, rel
        pila.extend(reversed(subcarpetas))


def crear_copia(guardian, ahora: datetime | None = None, tope_fichero: int = TOPE_FICHERO, tope_total: int = TOPE_TOTAL) -> dict:
    """Crea la copia y devuelve `{nombre, ficheros, bytes, omitidos: [{ruta, motivo}], cortada}`. `ficheros` no cuenta el manifiesto; `bytes` es el tamaño del zip."""
    libre = ahora is None
    ahora = ahora or datetime.now()
    nombre = nombre_de_copia(ahora)
    final = guardian.ruta_copia(nombre)
    while libre and final.exists():   # dos copias en el mismo segundo: la segunda toma el siguiente (con una hora dada, se rechaza más abajo)
        ahora += timedelta(seconds=1)
        nombre = nombre_de_copia(ahora)
        final = guardian.ruta_copia(nombre)
    tmp = guardian.ruta_copia(nombre, parcial=True)
    base = guardian.raiz_de_copia()
    carpeta = guardian.copias
    carpeta.mkdir(parents=True, exist_ok=True)
    if final.exists():
        raise FileExistsError(f"Ya existe la copia {nombre}.")
    omitidos: list[dict] = []
    manifiesto: list[dict] = []
    vistos: set[str] = set()
    total, cortada = 0, False
    creado = False
    try:
        with open(tmp, "xb") as salida:
            creado = True
            with zipfile.ZipFile(salida, "w", compression=zipfile.ZIP_DEFLATED) as z:
                for fuente in guardian.fuentes_de_copia():
                    if cortada:
                        break
                    for ruta, arc in _candidatos(fuente, _arc(base, fuente), carpeta, omitidos):
                        if arc in vistos:
                            omitidos.append({"ruta": arc, "motivo": "Ya hay otro fichero con esa ruta dentro de la copia; no entra."})
                            continue
                        try:
                            st = os.lstat(ruta)
                            if st.st_size > tope_fichero:
                                omitidos.append({"ruta": arc, "motivo": f"Supera el tope de tamaño por fichero ({_humano(tope_fichero)})."})
                                continue
                            if total + st.st_size > tope_total:
                                raise OverflowError
                            datos = _leer(ruta, tope_fichero)
                        except OverflowError:
                            cortada = True
                            omitidos.append({"ruta": arc, "motivo": f"La copia se cortó aquí al llegar al tope de tamaño ({_humano(tope_total)}); este fichero y los siguientes no entraron."})
                            break
                        except ValueError:
                            omitidos.append({"ruta": arc, "motivo": f"Supera el tope de tamaño por fichero ({_humano(tope_fichero)})."})
                            continue
                        except OSError as e:
                            omitidos.append({"ruta": arc, "motivo": f"No se pudo leer el fichero ({e.strerror or 'sin acceso'})."})
                            continue
                        if total + len(datos) > tope_total:
                            cortada = True
                            omitidos.append({"ruta": arc, "motivo": f"La copia se cortó aquí al llegar al tope de tamaño ({_humano(tope_total)}); este fichero y los siguientes no entraron."})
                            break
                        try:
                            arc.encode("utf-8")   # el nombre se guarda en UTF-8: lo que no se codifica no entra
                        except UnicodeEncodeError:
                            omitidos.append({"ruta": arc, "motivo": "El nombre del fichero no se puede guardar en el zip."})
                            continue
                        try:
                            info = zipfile.ZipInfo(arc, date_time=_fecha_zip(st.st_mtime))
                            info.compress_type = zipfile.ZIP_DEFLATED
                            z.writestr(info, datos)
                        except OSError:
                            raise   # el zip de salida (disco lleno, carpeta no escribible): aborta la copia entera
                        except Exception as e:   # noqa: BLE001  (un fichero raro nunca tumba la copia)
                            omitidos.append({"ruta": arc, "motivo": f"No se pudo guardar el fichero en el zip ({type(e).__name__})."})
                            continue
                        vistos.add(arc)
                        total += len(datos)
                        manifiesto.append({"ruta": arc, "bytes": len(datos)})
                m = {"version": 1, "creada": ahora.isoformat(timespec="seconds"), "app": __version__, "ficheros": manifiesto}
                z.writestr(NOMBRE_MANIFIESTO, json.dumps(m, ensure_ascii=False, indent=2))
        os.replace(tmp, final)
    except BaseException:
        if creado:
            _quitar_temporal(guardian, tmp)
        raise
    for o in omitidos:   # la respuesta JSON no puede llevar un carácter suelto no codificable
        o["ruta"] = _serializable(o["ruta"])
    return {"nombre": nombre, "ficheros": len(manifiesto), "bytes": final.stat().st_size, "omitidos": omitidos, "cortada": cortada}

