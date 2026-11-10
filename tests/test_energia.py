"""Sin freno de energía (apuntes/energia.py): se prueba con un `kernel32` falso; ni se toca el proceso real ni el sistema."""
import ctypes

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
