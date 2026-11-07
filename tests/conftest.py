import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from apuntes.rutas import Guardian  # noqa: E402


@pytest.fixture
def entorno(tmp_path):
    raiz = tmp_path / "proyectos"
    (raiz / "ProyA" / "00. CONTEXTO (IA)").mkdir(parents=True)
    (raiz / "ProyB").mkdir()
    knowledge = tmp_path / "Knowledge"
    knowledge.mkdir()
    g = Guardian(raiz, tmp_path / "bandeja", tmp_path / "cache", solo_lectura=[knowledge])
    return g, raiz, tmp_path, knowledge


@pytest.fixture(scope="session", autouse=True)
def _no_tocar_el_consumo_real():
    """Ningún test puede escribir en datos/consumo.jsonl (el registro REAL): mezclaría llamadas de prueba con las de verdad."""
    ruta = Path(__file__).resolve().parent.parent / "datos" / "consumo.jsonl"
    antes = ruta.stat().st_size if ruta.exists() else 0
    yield
    despues = ruta.stat().st_size if ruta.exists() else 0
    assert despues == antes, "un test ha escrito en datos/consumo.jsonl"


@pytest.fixture(autouse=True)
def _registro_de_errores_en_temporal(tmp_path, monkeypatch):
    """Los errores de fondo que los tests provocan a propósito (apuntes/registro.py) no van a datos/apuntes.log, el registro REAL."""
    from apuntes import registro
    monkeypatch.setattr(registro, "RUTA_LOG", tmp_path / "apuntes.log")
    registro._vistos.clear()
