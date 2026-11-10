"""Huella del código de la app: ¿lo que hay en disco es lo mismo que cargó este proceso al arrancar?

La app se deja abierta días y el código se actualiza en disco (git pull, cambios locales) sin que la ventana abierta lo sepa. `VigiaCodigo`
guarda la huella del arranque y dice si ha cambiado, para que la interfaz avise de «cierra y vuelve a abrir». Sin modelos, sin red y sin tokens.

Lectura de CÓDIGO PROPIO bajo `APP_DIR` (`app.py`, `apuntes/**/*.py`, `web/**/*.js|html|css`), solo lectura: por eso no pasa por el `Guardian`
(que custodia los datos y proyectos del usuario). Nunca toca `datos/`, `bandeja/`, `sesiones/` ni ninguna otra carpeta de datos, y nunca escribe."""
from __future__ import annotations

import hashlib
import time
from pathlib import Path

EXTENSIONES_WEB = (".js", ".html", ".css")


def _ficheros_de_codigo(raiz: Path) -> list[Path]:
    """Los ficheros que cuentan, en orden estable (por ruta relativa con «/»). Ignora `__pycache__`."""
    encontrados: list[Path] = []
    app = raiz / "app.py"
    if app.is_file():
        encontrados.append(app)
    for carpeta, patrones in ((raiz / "apuntes", ("*.py",)), (raiz / "web", tuple("*" + e for e in EXTENSIONES_WEB))):
        if not carpeta.is_dir():
            continue
        for patron in patrones:
            encontrados.extend(p for p in carpeta.rglob(patron) if "__pycache__" not in p.parts and p.is_file())
    return sorted(set(encontrados), key=lambda p: p.relative_to(raiz).as_posix())


def _calcular(raiz: Path) -> str:
    """La huella; lanza si ni siquiera se puede listar el código (el vigía lo trata como «no sé»: no avisa)."""
    h = hashlib.sha256()
    raiz = Path(raiz)
    for ruta in _ficheros_de_codigo(raiz):
        h.update(ruta.relative_to(raiz).as_posix().encode("utf-8") + b"\0")
        try:
            h.update(ruta.read_bytes().replace(b"\r\n", b"\n"))   # CRLF y LF dan la misma huella: un git pull en Windows no cambia el texto
        except OSError:
            pass   # ilegible: cuenta su ruta, no su contenido
        h.update(b"\0")
    return h.hexdigest()


def huella_codigo(raiz: Path) -> str:
    """sha256 de la ruta relativa y el contenido de `app.py`, `apuntes/**/*.py` y `web/**/*.js|html|css`, con CRLF normalizado a LF.
    Un fichero ilegible se salta (cuenta su ruta, no su contenido). Nunca lanza."""
    try:
        return _calcular(raiz)
    except Exception:  # noqa: BLE001 — la huella nunca debe romper a quien la pide
        return hashlib.sha256(b"").hexdigest()


class VigiaCodigo:
    """Huella del arranque y `cambiado()`: ¿difiere de la de ahora? Recalcula como mucho cada `cada_s` (entre medias devuelve lo último).
    Cualquier error ⇒ False; si el disco vuelve a coincidir con lo cargado, vuelve a False."""

    def __init__(self, raiz: Path, reloj=time.monotonic, cada_s: float = 60.0):
        self.raiz, self._reloj, self._cada_s = Path(raiz), reloj, cada_s
        try:
            self._arranque = _calcular(self.raiz)
        except Exception:  # noqa: BLE001 — sin huella de partida no hay con qué comparar: nunca avisa
            self._arranque = None
        self._ultimo_calculo = self._reloj()
        self._cambiado = False

    def cambiado(self) -> bool:
        try:
            if self._arranque is None:
                return False
            ahora = self._reloj()
            if ahora - self._ultimo_calculo >= self._cada_s:
                self._ultimo_calculo = ahora
                self._cambiado = _calcular(self.raiz) != self._arranque
            return self._cambiado
        except Exception:  # noqa: BLE001
            return False
