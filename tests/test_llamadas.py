"""Aviso de llamada de Teams: lectura del micro (registro, sin tocarlo), detector de llamadas y vigilancia de fondo (sin registro real)."""
import asyncio
from types import SimpleNamespace

import pytest

from apuntes import llamadas as LL
from apuntes.llamadas import DetectorLlamada, micro_en_uso, teams_usando_micro, vigilar_llamadas


def test_micro_en_uso_solo_si_empezo_y_no_ha_soltado():
    assert micro_en_uso(1_000, 0) is True
    assert micro_en_uso(1_000, 2_000) is False   # ya soltó
    assert micro_en_uso(0, 0) is False           # nunca lo usó
    assert micro_en_uso(0, 2_000) is False


def test_uso_breve_de_una_lectura_no_avisa():
    d = DetectorLlamada()
    assert d.actualizar(True, False) is None
    assert d.actualizar(False, False) is None
    assert d.actualizar(False, False) is None


def test_dos_lecturas_avisan_una_sola_vez_durante_la_llamada():
    d = DetectorLlamada()
    assert d.actualizar(True, False) is None
    assert d.actualizar(True, False) == "inicio"
    assert d.actualizar(True, False) is None
    assert d.actualizar(True, False) is None


def test_fin_tras_dos_lecturas_libres():
    d = DetectorLlamada()
    d.actualizar(True, False)
    assert d.actualizar(True, False) == "inicio"
    assert d.actualizar(False, False) is None      # Teams suelta el micro un momento al silenciarse
    assert d.actualizar(False, False) == "fin"
    assert d.actualizar(False, False) is None


def test_grabando_no_avisa():
    d = DetectorLlamada()
    assert d.actualizar(True, True) is None
    assert d.actualizar(True, True) is None
    assert d.actualizar(True, True) is None


def test_terminar_de_grabar_en_la_misma_llamada_no_repite_el_aviso():
    d = DetectorLlamada()
    d.actualizar(True, True)
    d.actualizar(True, True)                       # llamada vista mientras se graba
    assert d.actualizar(True, False) is None       # deja de grabar durante la misma llamada: no avisa
    assert d.actualizar(True, False) is None
    assert d.actualizar(False, False) is None      # al colgar tampoco hay «fin»: nunca hubo aviso
    assert d.actualizar(False, False) is None


def test_empezar_a_grabar_con_aviso_da_fin_y_no_se_repite():
    d = DetectorLlamada()
    d.actualizar(True, False)
    assert d.actualizar(True, False) == "inicio"
    assert d.actualizar(True, True) == "fin"       # el usuario empezó a grabar: se quita el aviso
    assert d.actualizar(True, True) is None
    assert d.actualizar(True, False) is None       # misma llamada: no vuelve a avisar
    assert d.actualizar(False, False) is None
    assert d.actualizar(False, False) is None      # ni «fin» otra vez


def test_llamada_nueva_avisa_otra_vez_tras_liberarse_el_micro():
    d = DetectorLlamada()
    d.actualizar(True, False)
    assert d.actualizar(True, False) == "inicio"
    assert d.actualizar(False, False) is None
    assert d.actualizar(False, False) == "fin"
    assert d.actualizar(True, False) is None
    assert d.actualizar(True, False) == "inicio"


def test_teams_usando_micro_no_lanza_si_el_registro_falla(monkeypatch):
    def falla(*_a, **_k):
        raise OSError("sin acceso al registro")

    monkeypatch.setattr(LL, "winreg", SimpleNamespace(HKEY_CURRENT_USER=0, OpenKey=falla, EnumKey=falla, QueryValueEx=falla))
    assert teams_usando_micro() is False


def test_teams_usando_micro_no_lanza_ante_un_error_inesperado(monkeypatch):
    def explota(*_a, **_k):
        raise RuntimeError("fallo raro")

    monkeypatch.setattr(LL, "winreg", SimpleNamespace(HKEY_CURRENT_USER=0, OpenKey=explota))
    assert teams_usando_micro() is False


def test_teams_usando_micro_sin_registro_disponible(monkeypatch):
    monkeypatch.setattr(LL, "winreg", None)
    assert teams_usando_micro() is False


class GestorFalso:
    def __init__(self, estado="inactivo"):
        self.estado = estado
        self.llamada = False
        self.eventos = []

    def emitir(self, tipo, **datos):
        self.eventos.append((tipo, datos))


def _lectura_desde(valores):
    """Lectura falsa: devuelve la secuencia y después «libre» para siempre."""
    cola = list(valores)

    def leer():
        return cola.pop(0) if cola else False
    return leer


async def _esperar(cond, t=10):
    for _ in range(int(t / 0.01)):
        if cond():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("tiempo agotado")


def test_vigilar_llamadas_avisa_y_emite_inicio_y_fin():
    gestor = GestorFalso()
    cfg = SimpleNamespace(datos={"detectar_llamadas": True})
    avisos = []
    leer = _lectura_desde([True, True, False, False])

    async def go():
        tarea = asyncio.create_task(vigilar_llamadas(gestor, cfg, lambda: avisos.append(1), intervalo=0.001, leer=leer))
        await _esperar(lambda: len(gestor.eventos) >= 2)
        tarea.cancel()
        with pytest.raises(asyncio.CancelledError):
            await tarea

    asyncio.run(go())
    assert gestor.eventos == [("llamada", {"activa": True}), ("llamada", {"activa": False})]
    assert avisos == [1]
    assert gestor.llamada is False   # la llamada terminó


def test_vigilar_llamadas_no_se_para_si_falla_el_aviso_ni_una_lectura():
    gestor = GestorFalso()
    cfg = SimpleNamespace(datos={"detectar_llamadas": True})
    lecturas = {"n": 0}

    def leer():
        lecturas["n"] += 1
        if lecturas["n"] == 1:
            raise OSError("lectura rota una vez")
        return True                      # sigue en uso: no debe haber «fin» antes de cancelar

    def aviso_roto():
        raise RuntimeError("ventana cerrada")

    async def go():
        tarea = asyncio.create_task(vigilar_llamadas(gestor, cfg, aviso_roto, intervalo=0.001, leer=leer))
        await _esperar(lambda: len(gestor.eventos) >= 1)
        tarea.cancel()
        with pytest.raises(asyncio.CancelledError):
            await tarea

    asyncio.run(go())
    assert gestor.eventos[0] == ("llamada", {"activa": True})
    assert gestor.llamada is True


def test_vigilar_llamadas_con_deteccion_desactivada_no_avisa():
    gestor = GestorFalso()
    cfg = SimpleNamespace(datos={"detectar_llamadas": False})

    async def go():
        tarea = asyncio.create_task(vigilar_llamadas(gestor, cfg, intervalo=0.001, leer=lambda: True))
        await asyncio.sleep(0.1)
        tarea.cancel()
        with pytest.raises(asyncio.CancelledError):
            await tarea

    asyncio.run(go())
    assert gestor.eventos == []
