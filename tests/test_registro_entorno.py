"""El registro (`datos\apuntes.log`) se aparta por el entorno: los subprocesos de las pruebas (que arrancan la app de verdad) nunca escriben en el real."""
import os
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent


def _ruta_log(entorno):
    r = subprocess.run([sys.executable, "-c", "from apuntes import registro; print(registro.RUTA_LOG)"], cwd=RAIZ, env=entorno,
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr
    return Path(r.stdout.strip())


def test_con_la_variable_el_registro_va_al_fichero_indicado(tmp_path):
    destino = tmp_path / "otro" / "registro.log"
    assert _ruta_log({**os.environ, "WHISPERMEET_REGISTRO": str(destino)}) == destino


def test_sin_la_variable_va_a_datos_apuntes_log():
    from apuntes.config import DATOS_DIR
    entorno = {k: v for k, v in os.environ.items() if k != "WHISPERMEET_REGISTRO"}
    assert _ruta_log(entorno) == DATOS_DIR / "apuntes.log"       # solo se lee la ruta: no se escribe nada


def test_pytest_deja_un_registro_temporal_para_sus_subprocesos():
    from apuntes.config import DATOS_DIR
    ruta = Path(os.environ["WHISPERMEET_REGISTRO"]).resolve()
    assert DATOS_DIR.resolve() not in ruta.parents


def test_los_servidores_de_ayuda_lo_apartan_antes_de_importar_la_app():
    for nombre in ("tests/servir_falso_contexto.py", "pruebas/servir_modelo_falso.py"):
        texto = (RAIZ / nombre).read_text(encoding="utf-8")
        assert texto.index("WHISPERMEET_REGISTRO") < texto.index("import app as aplicacion"), nombre


def test_la_salida_de_pythonw_va_al_mismo_fichero_que_el_registro():
    texto = (RAIZ / "app.py").read_text(encoding="utf-8")
    assert 'DATOS_DIR / "apuntes.log"' not in texto and "open(RUTA_LOG" in texto
