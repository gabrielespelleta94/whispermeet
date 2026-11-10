"""Sin freno de energía, prioridad de la reunión y CPU del equipo (apuntes/energia.py): se prueban con un `kernel32` falso; ni se toca el proceso real ni el sistema."""
import ctypes

import pytest

from apuntes import energia as E


class Kernel32Falso:
    def __init__(self, devuelve=1, lanza=None):
        self.devuelve, self.lanza, self.llamadas = devuelve, lanza, []

    def GetCurrentProcess(self):
        return 0x7FFFFFFFFFFF      # un manejador de 64 bits

    def SetProcessInformation(self, manejador, clase, puntero, tam):
        if self.lanza:
            raise self.lanza
        estado = puntero.contents
        self.llamadas.append({"manejador": manejador, "clase": clase, "version": estado.Version, "control": estado.ControlMask,
                              "estado": estado.StateMask, "tam": tam})
        return self.devuelve


def test_se_llama_con_la_clase_4_version_1_control_1_estado_0_y_el_tamano_correcto():
    k = Kernel32Falso()
    assert E.sin_freno_de_energia(k) is True
    (c,) = k.llamadas
    assert c["clase"] == 4 and c["version"] == 1 and c["control"] == 1 and c["estado"] == 0
    assert c["tam"] == ctypes.sizeof(E.PROCESS_POWER_THROTTLING_STATE) == 12     # tres ULONG de 4 bytes
    assert c["manejador"] == 0x7FFFFFFFFFFF                                      # el manejador del propio proceso, sin truncar


def test_devuelve_false_si_la_llamada_dice_que_no():
    assert E.sin_freno_de_energia(Kernel32Falso(devuelve=0)) is False


def test_devuelve_false_si_la_llamada_lanza_y_nunca_lanza():
    for exc in (OSError("sin permiso"), AttributeError("sin esa función"), RuntimeError("raro")):
        assert E.sin_freno_de_energia(Kernel32Falso(lanza=exc)) is False


def test_un_kernel32_sin_la_funcion_no_lanza():
    assert E.sin_freno_de_energia(object()) is False


def test_fuera_de_windows_devuelve_false_sin_tocar_nada(monkeypatch):
    monkeypatch.setattr(E.sys, "platform", "linux")
    assert E.sin_freno_de_energia() is False


def test_las_constantes_son_las_de_la_api_de_windows():
    assert E.PROCESS_POWER_THROTTLING == 4
    assert E.PROCESS_POWER_THROTTLING_CURRENT_VERSION == 1
    assert E.PROCESS_POWER_THROTTLING_EXECUTION_SPEED == 0x1


def test_app_py_lo_llama_una_vez_y_deja_constancia_en_el_registro():
    from pathlib import Path
    texto = (Path(__file__).resolve().parent.parent / "app.py").read_text(encoding="utf-8")
    assert texto.count("sin_freno_de_energia()") == 1 and "energia sin_freno=" in texto
    assert texto.index("sin_freno_de_energia()") < texto.index("= construir(args)")     # antes de cargar nada pesado


# ------------------------------------------------------------------ prioridad del proceso mientras se captura
class Kernel32Prioridad:
    def __init__(self, devuelve=1, lanza=None, clase=0x20):
        self.devuelve, self.lanza, self.llamadas, self.clase, self.lecturas = devuelve, lanza, [], clase, 0

    def GetPriorityClass(self, manejador):
        self.lecturas += 1
        if self.lanza:
            raise self.lanza
        return self.clase

    def GetCurrentProcess(self):
        return 0x7FFFFFFFFFFF

    def SetPriorityClass(self, manejador, clase):
        if self.lanza:
            raise self.lanza
        self.llamadas.append((manejador, clase))
        return self.devuelve


@pytest.fixture
def con_prioridad_permitida(monkeypatch):
    """pytest pone WHISPERMEET_SIN_PRIORIDAD para todos los tests: estos la quitan para probar la función de verdad (siempre con un kernel32 falso)."""
    monkeypatch.delenv(E.VARIABLE_SIN_PRIORIDAD, raising=False)


def test_las_constantes_de_prioridad_son_las_de_la_api_de_windows():
    assert E.ABOVE_NORMAL_PRIORITY_CLASS == 0x00008000 and E.NORMAL_PRIORITY_CLASS == 0x00000020
    assert E.VARIABLE_SIN_PRIORIDAD == "WHISPERMEET_SIN_PRIORIDAD"


def test_activa_pone_above_normal_en_el_propio_proceso(con_prioridad_permitida):
    k = Kernel32Prioridad()
    assert E.prioridad_de_reunion(True, k) is True
    assert k.llamadas == [(0x7FFFFFFFFFFF, 0x00008000)]                       # el manejador de 64 bits, sin truncar


def test_inactiva_la_devuelve_a_normal(con_prioridad_permitida):
    k = Kernel32Prioridad()
    assert E.prioridad_de_reunion(False, k) is True
    assert k.llamadas == [(0x7FFFFFFFFFFF, 0x00000020)]


def test_al_bajar_se_restaura_la_clase_original_y_sin_ella_normal(con_prioridad_permitida):
    k = Kernel32Prioridad()
    assert E.prioridad_de_reunion(False, k, clase_normal=0x4000) is True
    assert E.prioridad_de_reunion(False, k, clase_normal=None) is True
    assert E.prioridad_de_reunion(True, k, clase_normal=0x4000) is True                # al subir se ignora
    assert [c for _m, c in k.llamadas] == [0x4000, 0x20, 0x8000]


@pytest.mark.parametrize("hilos,nucleos,esperado", [(4, 8, True), (6, 8, False), (2, 2, False), (1, 2, True), (1, 1, True), (0, 8, False), (-1, 8, False), (1, 3, True), (2, 3, False)])
def test_la_prioridad_solo_es_compatible_si_whisper_deja_la_mitad_de_los_nucleos(hilos, nucleos, esperado):
    assert E.prioridad_compatible(hilos, nucleos) is esperado


def test_clase_de_prioridad_lee_la_clase_del_propio_proceso(con_prioridad_permitida):
    assert E.clase_de_prioridad(Kernel32Prioridad(clase=0x4000)) == 0x4000


def test_clase_de_prioridad_none_si_falla_devuelve_cero_o_no_es_windows_y_nunca_lanza(monkeypatch, con_prioridad_permitida):
    assert E.clase_de_prioridad(Kernel32Prioridad(clase=0)) is None
    for exc in (OSError("sin permiso"), AttributeError("sin esa función"), RuntimeError("raro")):
        assert E.clase_de_prioridad(Kernel32Prioridad(lanza=exc)) is None
    assert E.clase_de_prioridad(object()) is None
    monkeypatch.setattr(E.sys, "platform", "linux")
    assert E.clase_de_prioridad() is None


def test_clase_de_prioridad_con_la_variable_de_entorno_no_llama_a_la_api(monkeypatch):
    monkeypatch.setenv(E.VARIABLE_SIN_PRIORIDAD, "1")
    k = Kernel32Prioridad(clase=0x4000)
    assert E.clase_de_prioridad(k) is None and k.lecturas == 0


def test_la_prioridad_devuelve_false_si_la_llamada_dice_que_no(con_prioridad_permitida):
    assert E.prioridad_de_reunion(True, Kernel32Prioridad(devuelve=0)) is False


def test_la_prioridad_nunca_lanza(con_prioridad_permitida):
    for exc in (OSError("sin permiso"), AttributeError("sin esa función"), RuntimeError("raro")):
        assert E.prioridad_de_reunion(True, Kernel32Prioridad(lanza=exc)) is False
    assert E.prioridad_de_reunion(True, object()) is False


def test_con_la_variable_de_entorno_no_se_llama_a_la_api(monkeypatch):
    monkeypatch.setenv(E.VARIABLE_SIN_PRIORIDAD, "1")
    k = Kernel32Prioridad()
    assert E.prioridad_de_reunion(True, k) is False and E.prioridad_de_reunion(False, k) is False
    assert k.llamadas == []


def test_pytest_ya_trae_la_variable_puesta_por_conftest():
    import os
    assert os.environ.get("WHISPERMEET_SIN_PRIORIDAD") == "1"
    assert E.prioridad_de_reunion(True) is False            # sin kernel32 inyectado: tampoco toca el proceso real de pytest


def test_la_prioridad_fuera_de_windows_devuelve_false_sin_tocar_nada(monkeypatch, con_prioridad_permitida):
    monkeypatch.setattr(E.sys, "platform", "linux")
    assert E.prioridad_de_reunion(True) is False


def test_los_servidores_de_ayuda_ponen_la_variable_antes_de_importar_la_app():
    from pathlib import Path
    raiz = Path(__file__).resolve().parent.parent
    for nombre in ("tests/servir_falso_contexto.py", "pruebas/servir_modelo_falso.py"):
        texto = (raiz / nombre).read_text(encoding="utf-8")
        assert 'os.environ.setdefault("WHISPERMEET_SIN_PRIORIDAD"' in texto, nombre
        assert texto.index("WHISPERMEET_SIN_PRIORIDAD") < texto.index("import app as aplicacion"), nombre
    conftest = (raiz / "tests" / "conftest.py").read_text(encoding="utf-8")
    assert conftest.index("WHISPERMEET_SIN_PRIORIDAD") < conftest.index("from apuntes.rutas import Guardian")


# ------------------------------------------------------------------ CPU de todo el equipo (GetSystemTimes)
class Kernel32Tiempos:
    def __init__(self, ocioso, kernel, usuario, devuelve=1, lanza=None):
        self.valores, self.devuelve, self.lanza = (ocioso, kernel, usuario), devuelve, lanza

    def GetSystemTimes(self, ocioso, kernel, usuario):
        if self.lanza:
            raise self.lanza
        for puntero, v in zip((ocioso, kernel, usuario), self.valores):
            puntero.contents.Bajo, puntero.contents.Alto = v & 0xFFFFFFFF, v >> 32
        return self.devuelve


def test_tiempos_del_equipo_ocupado_es_kernel_mas_usuario_menos_ocioso_en_segundos():
    ocioso, kernel, usuario = 40 * 10_000_000, 60 * 10_000_000, 30 * 10_000_000      # intervalos de 100 ns
    assert E.tiempos_del_equipo(Kernel32Tiempos(ocioso, kernel, usuario)) == pytest.approx((50.0, 90.0))


def test_tiempos_del_equipo_junta_la_parte_alta_y_la_baja():
    grande = (5 << 32) | 123                                                       # más de 2**32 intervalos
    r = E.tiempos_del_equipo(Kernel32Tiempos(0, grande, 0))
    assert r == pytest.approx((grande / 1e7, grande / 1e7)) and r[1] > 2 ** 32 / 1e7


def test_tiempos_del_equipo_none_si_falla_y_nunca_lanza(monkeypatch):
    assert E.tiempos_del_equipo(Kernel32Tiempos(1, 2, 3, devuelve=0)) is None
    for exc in (OSError("x"), AttributeError("sin esa función"), RuntimeError("raro")):
        assert E.tiempos_del_equipo(Kernel32Tiempos(1, 2, 3, lanza=exc)) is None
    assert E.tiempos_del_equipo(object()) is None
    monkeypatch.setattr(E.sys, "platform", "linux")
    assert E.tiempos_del_equipo() is None


def test_uso_de_cpu_es_el_porcentaje_del_intervalo():
    assert E.uso_de_cpu((10.0, 20.0), (19.0, 30.0)) == 90
    assert E.uso_de_cpu((0.0, 0.0), (0.0, 10.0)) == 0
    assert E.uso_de_cpu((0.0, 0.0), (10.0, 10.0)) == 100
    assert E.uso_de_cpu((0.0, 0.0), (11.0, 10.0)) == 100                           # nunca pasa de 100
    assert E.uso_de_cpu((5.0, 10.0), (4.0, 20.0)) == 0                             # ni baja de 0


def test_uso_de_cpu_none_sin_lecturas_o_sin_tiempo():
    assert E.uso_de_cpu(None, (1.0, 2.0)) is None and E.uso_de_cpu((1.0, 2.0), None) is None
    assert E.uso_de_cpu((1.0, 2.0), (1.0, 2.0)) is None


def test_las_lecturas_reales_del_equipo_son_coherentes_en_windows():
    import sys
    if sys.platform != "win32":
        pytest.skip("solo Windows")
    a = E.tiempos_del_equipo()
    assert a is not None and 0.0 <= a[0] <= a[1]
    b = E.tiempos_del_equipo()
    assert b[1] >= a[1] and E.uso_de_cpu(a, b) in (None, *range(0, 101))
