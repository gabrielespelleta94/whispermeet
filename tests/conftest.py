import os
import sys
import tempfile
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Los servidores de prueba son subprocesos que arrancan la app de verdad: su registro va a un fichero temporal (lo heredan por el entorno),
# nunca a datos/apuntes.log. Tiene que estar puesto ANTES de importar `apuntes.registro`. En este proceso lo aparta además `_registro_aparte`.
_REGISTRO_PRUEBAS = Path(tempfile.gettempdir()) / f"whispermeet-pruebas-{os.getpid()}.log"
os.environ["WHISPERMEET_REGISTRO"] = str(_REGISTRO_PRUEBAS)
os.environ["WHISPERMEET_SIN_PRIORIDAD"] = "1"   # ningún test cambia la prioridad de pytest ni la de los servidores de ayuda (`energia.prioridad_de_reunion`)

# Transcripción en la nube: ningún test sale a internet ni usa una clave real. Con la guarda, el cliente rechaza todo host que no sea de bucle local
# (antes de abrir un socket) y no usa proxy; la variable de la clave se borra para que no se cuele la del usuario. Los subprocesos de prueba lo heredan.
os.environ["WHISPERMEET_NUBE_SOLO_LOOPBACK"] = "1"
os.environ.pop("WHISPERMEET_CLAVE_NUBE", None)

from apuntes.rutas import Guardian  # noqa: E402
import guarda_reunion  # noqa: E402


def pytest_sessionstart(session):
    """Antes de recoger tests: prioridad baja (la heredan Edge y los servidores de prueba) y no arrancar con una reunión en marcha."""
    guarda_reunion.bajar_prioridad()
    from apuntes.config import DATOS_DIR
    guarda_reunion.exigir_sin_reunion(os.environ, guarda_reunion.leer_microfono_registro if sys.platform == "win32" else (lambda: []), time.time, DATOS_DIR)


def pytest_sessionfinish(session, exitstatus):
    """El registro temporal de los subprocesos de prueba no se queda en el equipo."""
    try:
        _REGISTRO_PRUEBAS.unlink(missing_ok=True)
    except OSError:
        pass


_revision_reunion = None


def pytest_runtest_setup(item):
    """Durante la batería: como mucho cada 20 s vuelve a mirar si ha empezado una reunión (la guarda de arriba solo mira al arrancar) y, si es así, corta."""
    global _revision_reunion
    if _revision_reunion is None:
        from apuntes.config import DATOS_DIR
        lector = guarda_reunion.leer_microfono_registro if sys.platform == "win32" else (lambda: [])
        _revision_reunion = guarda_reunion.RevisionPeriodica(
            lambda: guarda_reunion.comprobar_reunion_iniciada(os.environ, lector, time.time, DATOS_DIR))
    mensaje = _revision_reunion.revisar()
    if mensaje:
        pytest.exit(mensaje, returncode=3)


@pytest.fixture
def entorno(tmp_path):
    raiz = tmp_path / "proyectos"
    (raiz / "ProyA" / "00. CONTEXTO (IA)").mkdir(parents=True)
    (raiz / "ProyB").mkdir()
    knowledge = tmp_path / "Knowledge"
    knowledge.mkdir()
    g = Guardian(raiz, tmp_path / "bandeja", tmp_path / "cache", solo_lectura=[knowledge], copias=tmp_path / "copias")   # las copias de seguridad, siempre en la carpeta temporal
    return g, raiz, tmp_path, knowledge


@pytest.fixture(scope="session", autouse=True)
def _no_tocar_el_consumo_real():
    """Ningún test puede escribir en datos/consumo.jsonl (el registro REAL): mezclaría llamadas de prueba con las de verdad."""
    ruta = Path(__file__).resolve().parent.parent / "datos" / "consumo.jsonl"
    antes = ruta.stat().st_size if ruta.exists() else 0
    yield
    despues = ruta.stat().st_size if ruta.exists() else 0
    assert despues == antes, "un test ha escrito en datos/consumo.jsonl (o la app real estuvo en uso mientras corrían los tests)"


@pytest.fixture(scope="session", autouse=True)
def _no_tocar_las_copias_reales():
    """Ningún test puede crear ni cambiar la carpeta `copias` REAL (copias de seguridad con datos de reuniones). Solo se mira si existe y su fecha: nunca se abre ni se lista."""
    ruta = Path(__file__).resolve().parent.parent / "copias"

    def marca():
        return ruta.stat().st_mtime_ns if ruta.exists() else None
    antes = marca()
    yield
    assert marca() == antes, "un test ha creado o cambiado la carpeta copias real"


@pytest.fixture(autouse=True)
def _registro_de_errores_en_temporal(tmp_path, monkeypatch):
    """Los errores de fondo que los tests provocan a propósito (apuntes/registro.py) no van a datos/apuntes.log, el registro REAL."""
    from apuntes import registro
    monkeypatch.setattr(registro, "RUTA_LOG", tmp_path / "apuntes.log")
    registro._vistos.clear()
