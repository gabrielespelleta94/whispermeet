"""Los tests no compiten con una reunión en marcha: prioridad baja y negativa a arrancar si hay una reunión.
Todo con dobles: ni el registro real de Windows ni la carpeta de datos real."""
import os

import pytest

import guarda_reunion as g

AHORA = 1_000_000.0
BAJA = 0x00004000


def _lector(*pares):
    return lambda: list(pares)


def _fichero(carpeta, nombre, hace):
    ruta = carpeta / nombre
    ruta.write_text("x", encoding="utf-8")
    os.utime(ruta, (AHORA - hace, AHORA - hace))
    return ruta


# ---- prioridad baja ----

def test_baja_la_prioridad_en_windows():
    llamadas = []
    assert g.bajar_prioridad({}, "win32", lambda c: llamadas.append(c) or True) is True
    assert llamadas == [BAJA]


def test_no_baja_la_prioridad_si_no_es_windows():
    llamadas = []
    assert g.bajar_prioridad({}, "linux", llamadas.append) is False
    assert llamadas == []


def test_no_baja_la_prioridad_si_se_pide_normal():
    llamadas = []
    assert g.bajar_prioridad({"WHISPERMEET_TESTS_PRIORIDAD_NORMAL": "1"}, "win32", llamadas.append) is False
    assert llamadas == []


def test_un_fallo_al_bajar_la_prioridad_no_tumba_nada():
    def falla(_clase):
        raise OSError("sin permiso")
    assert g.bajar_prioridad({}, "win32", falla) is False


def test_si_la_llamada_devuelve_falso_no_pasa_nada():
    assert g.bajar_prioridad({}, "win32", lambda _c: False) is False


# ---- micrófono ----

def test_microfono_en_uso_nombra_la_aplicacion(tmp_path):
    motivo = g.motivo_reunion(_lector(("Microsoft.Teams_8wekyb3d8bbwe", 0)), lambda: AHORA, tmp_path)
    assert motivo is not None
    assert "micrófono en uso por Microsoft.Teams_8wekyb3d8bbwe" in motivo


def test_microfono_no_enseña_la_ruta_de_nonpackaged(tmp_path):
    clave = r"NonPackaged\C:#Program Files#Zoom#bin#Zoom.exe"
    motivo = g.motivo_reunion(_lector((clave, 0)), lambda: AHORA, tmp_path)
    assert "Zoom.exe" in motivo
    assert "Program Files" not in motivo and "C:" not in motivo


def test_microfono_ya_liberado_no_es_reunion(tmp_path):
    assert g.motivo_reunion(_lector(("Microsoft.Teams_8wekyb3d8bbwe", 133_000_000_000_000_000)), lambda: AHORA, tmp_path) is None


def test_sin_señales_no_hay_reunion(tmp_path):
    assert g.motivo_reunion(_lector(), lambda: AHORA, tmp_path) is None


# ---- la app real acaba de escribir ----

@pytest.mark.parametrize("nombre", ["apuntes.log", "consumo.jsonl"])
def test_fichero_reciente_es_reunion(tmp_path, nombre):
    _fichero(tmp_path, nombre, hace=30)
    motivo = g.motivo_reunion(_lector(), lambda: AHORA, tmp_path)
    assert motivo is not None and nombre in motivo


@pytest.mark.parametrize("nombre", ["apuntes.log", "consumo.jsonl"])
def test_fichero_antiguo_no_es_reunion(tmp_path, nombre):
    _fichero(tmp_path, nombre, hace=121)
    assert g.motivo_reunion(_lector(), lambda: AHORA, tmp_path) is None


def test_ficheros_ausentes_no_son_reunion(tmp_path):
    assert g.motivo_reunion(_lector(), lambda: AHORA, tmp_path / "no_existe") is None


def test_solo_se_hace_stat_nunca_se_abren_los_ficheros(tmp_path, monkeypatch):
    _fichero(tmp_path, "apuntes.log", hace=10)
    _fichero(tmp_path, "consumo.jsonl", hace=10)
    import builtins
    import io
    def prohibido(*a, **k):
        raise AssertionError("se ha abierto un fichero")
    monkeypatch.setattr(builtins, "open", prohibido)
    monkeypatch.setattr(io, "open", prohibido)
    monkeypatch.setattr(type(tmp_path), "open", prohibido, raising=False)
    monkeypatch.setattr(type(tmp_path), "read_text", prohibido, raising=False)
    assert g.motivo_reunion(_lector(), lambda: AHORA, tmp_path) is not None


def test_una_excepcion_se_trata_como_sin_reunion(tmp_path):
    def roto():
        raise RuntimeError("registro roto")
    assert g.motivo_reunion(roto, lambda: AHORA, tmp_path) is None


# ---- la sesión: forzar y salir ----

def test_comprobar_no_mira_nada_si_se_fuerza(tmp_path):
    def no_debe_llamarse():
        raise AssertionError("se ha consultado el registro")
    assert g.comprobar_reunion({"WHISPERMEET_TESTS_EN_REUNION": "1"}, no_debe_llamarse, lambda: AHORA, tmp_path) is None


def test_comprobar_devuelve_el_motivo_con_la_forma_de_forzar(tmp_path):
    motivo = g.comprobar_reunion({}, _lector(("Teams", 0)), lambda: AHORA, tmp_path)
    assert motivo.startswith("Hay una reunión en marcha (micrófono en uso por Teams).")
    assert "WHISPERMEET_TESTS_EN_REUNION=1" in motivo


def test_la_sesion_termina_con_pytest_exit(tmp_path):
    with pytest.raises(pytest.exit.Exception) as e:
        g.exigir_sin_reunion({}, _lector(("Teams", 0)), lambda: AHORA, tmp_path)
    assert e.value.returncode not in (0, None)
    assert "Teams" in e.value.msg


def test_la_sesion_sigue_si_no_hay_reunion(tmp_path):
    g.exigir_sin_reunion({}, _lector(), lambda: AHORA, tmp_path)


# ---- revisión durante la batería ----

class _Reloj:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


def test_revision_no_repite_antes_de_veinte_segundos():
    llamadas, reloj = [], _Reloj()
    rev = g.RevisionPeriodica(lambda: llamadas.append(1), reloj=reloj)
    assert rev.revisar() is None and len(llamadas) == 1          # la primera vez sí mira
    reloj.t += 19.9
    assert rev.revisar() is None and len(llamadas) == 1          # antes de 20 s no vuelve a mirar
    reloj.t += 0.1
    rev.revisar()
    assert len(llamadas) == 2


def test_revision_corta_cuando_aparece_un_motivo(tmp_path):
    reloj, lector = _Reloj(), {"datos": []}
    rev = g.RevisionPeriodica(lambda: g.comprobar_reunion_iniciada({}, lambda: lector["datos"], lambda: AHORA, tmp_path), reloj=reloj)
    assert rev.revisar() is None                                  # sin reunión
    lector["datos"] = [("Teams", 0)]                              # empieza una reunión…
    assert rev.revisar() is None                                  # …pero aún no toca mirar
    reloj.t += g.REVISION_CADA_S
    mensaje = rev.revisar()
    assert mensaje is not None and "micrófono en uso por Teams" in mensaje
    assert "batería" in mensaje and "relanza" in mensaje


def test_revision_no_corta_con_la_excepcion_activada(tmp_path):
    reloj = _Reloj()

    def no_debe_llamarse():
        raise AssertionError("se ha consultado el registro")
    rev = g.RevisionPeriodica(lambda: g.comprobar_reunion_iniciada({"WHISPERMEET_TESTS_EN_REUNION": "1"}, no_debe_llamarse, lambda: AHORA, tmp_path),
                              reloj=reloj)
    assert rev.revisar() is None
    reloj.t += 60
    assert rev.revisar() is None


def test_revision_ve_el_registro_de_la_app_escrito_hace_poco(tmp_path):
    _fichero(tmp_path, "apuntes.log", hace=5)
    assert "apuntes.log" in g.comprobar_reunion_iniciada({}, _lector(), lambda: AHORA, tmp_path)


def test_un_fallo_de_la_comprobacion_no_corta_la_bateria():
    def roto():
        raise RuntimeError("registro roto")
    assert g.RevisionPeriodica(roto, reloj=_Reloj()).revisar() is None


def test_el_conftest_engancha_la_revision_en_cada_test():
    with open(os.path.join(os.path.dirname(__file__), "conftest.py"), encoding="utf-8") as f:
        texto = f.read()
    assert "def pytest_runtest_setup" in texto and "RevisionPeriodica" in texto and "returncode=3" in texto


# ---- el vigilante del consumo ----

def test_el_vigilante_menciona_la_otra_causa():
    fuente = (os.path.join(os.path.dirname(__file__), "conftest.py"))
    with open(fuente, encoding="utf-8") as f:
        texto = f.read()
    assert "un test ha escrito en datos/consumo.jsonl" in texto
    assert "app real" in texto and "en uso" in texto
