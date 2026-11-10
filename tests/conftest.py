import os
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from apuntes.rutas import Guardian  # noqa: E402
import guarda_reunion  # noqa: E402


def pytest_sessionstart(session):
    """Antes de recoger tests: prioridad baja (la heredan Edge y los servidores de prueba) y no arrancar con una reunión en marcha."""
    guarda_reunion.bajar_prioridad()
    from apuntes.config import DATOS_DIR
    guarda_reunion.exigir_sin_reunion(os.environ, guarda_reunion.leer_microfono_registro if sys.platform == "win32" else (lambda: []), time.time, DATOS_DIR)


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
