"""Tests de las cuentas de `pruebas/probar_eco_real.py` (la prueba manual de eco con altavoces): solo las funciones puras, con niveles
inventados. Aquí no se abre ningún dispositivo de audio ni suena nada."""
import importlib.util
from pathlib import Path

import numpy as np

RUTA = Path(__file__).resolve().parent.parent / "pruebas" / "probar_eco_real.py"
spec = importlib.util.spec_from_file_location("probar_eco_real", RUTA)
P = importlib.util.module_from_spec(spec)
spec.loader.exec_module(P)

TRAMO = {"t0": 4.0, "dur": 3.0, "eco": True, "motivo": "eco", "rho": 0.9, "exceso": 0.0, "desfase_s": 0.1, "ganancia_db": -18.0,
         "dispersion_db": 2.0, "fuerte": True}
PICOS = {"reunion": -8.0, "yo": -20.0}


def bloques(ini: float, fin: float, db) -> list:
    """Un nivel cada 50 ms en (ini, fin]; `db` es un número o una función del índice del bloque."""
    n = int(round((fin - ini) / 0.05))
    return [(ini + (k + 1) * 0.05, db(k) if callable(db) else db) for k in range(n)]


def test_nivel_db_y_fraccion():
    assert P.nivel_db(np.zeros(800, np.float32)) == -120.0
    assert P.nivel_db(np.array([], np.float32)) == -120.0
    assert abs(P.nivel_db(np.full(800, 0.1, np.float32)) + 20.0) < 0.01
    assert P.fraccion([], -42.0) == 0.0
    assert P.fraccion([-30.0, -60.0, -41.0, -43.0], -42.0) == 0.5


def test_ambiente_en_silencio_mide_el_eco_que_llega():
    niveles = {"reunion": bloques(0, 3, -120.0) + bloques(3, 13, -30.0) + bloques(13, 15, -120.0),
               "yo": bloques(0, 3, -60.0) + bloques(3, 13, lambda k: -38.0 if k % 4 == 0 else -48.0) + bloques(13, 15, -60.0)}
    amb = P.ambiente(niveles, 3.0, 13.0)
    assert amb["previa"] == {"reunion_sonando": 0.0, "micro_con_sonido": 0.0}
    assert amb["sonando"]["reunion_db"] == -30.0 and amb["sonando"]["micro_db"] == -48.0
    assert amb["sonando"]["micro_sobre_umbral"] == 0.25
    assert amb["al_parar"] == {"micro_con_sonido": 0.0}


def test_ambiente_no_cuenta_la_cola_de_la_sala_pero_si_la_voz_que_sigue():
    base = {"reunion": bloques(0, 3, -120.0) + bloques(3, 13, -30.0) + bloques(13, 16, -120.0)}
    cola = dict(base, yo=bloques(0, 13, -60.0) + bloques(13, 13.5, -35.0) + bloques(13.5, 16, -60.0))
    assert P.ambiente(cola, 3.0, 13.0)["al_parar"]["micro_con_sonido"] == 0.0   # 0,5 s de reverberación: dentro de COLA_SALA_S
    voz = dict(base, yo=bloques(0, 13, -60.0) + bloques(13, 16, -35.0))
    assert P.ambiente(voz, 3.0, 13.0)["al_parar"]["micro_con_sonido"] == 1.0    # alguien habla al acabar: la sala no estaba en silencio


def test_ambiente_ve_que_el_equipo_ya_sonaba_antes():
    niveles = {"reunion": bloques(0, 15, -30.0), "yo": bloques(0, 15, -30.0)}
    amb = P.ambiente(niveles, 3.0, 13.0)
    assert amb["previa"] == {"reunion_sonando": 1.0, "micro_con_sonido": 1.0}
    assert amb["previa"]["reunion_sonando"] > P.PREVIA_REUNION_MAX and amb["previa"]["micro_con_sonido"] > P.PREVIA_MICRO_MAX


def test_ambiente_sin_bloques_no_falla():
    amb = P.ambiente({}, 3.0, 13.0)
    assert amb["sonando"] == {"reunion_db": None, "micro_db": None, "micro_sobre_umbral": 0.0}
    assert amb["previa"]["reunion_sonando"] == 0.0 and amb["al_parar"]["micro_con_sonido"] == 0.0


def test_calcular_lleva_el_ambiente_y_sin_el_queda_vacio():
    assert P.calcular([], [], {"reunion": -120.0, "yo": -120.0})["ambiente"] == {}
    amb = P.ambiente({"reunion": bloques(3, 13, -30.0), "yo": bloques(3, 13, -48.0)}, 3.0, 13.0)
    m = P.calcular([10.0], [TRAMO], PICOS, amb)
    assert m["ambiente"] == amb and m["eco"]["tramos"] == 1 and m["eco"]["porcentaje_tiempo"] == 100.0


def test_informe_avisa_de_medida_contaminada(capsys):
    amb = P.ambiente({"reunion": bloques(0, 15, -30.0), "yo": bloques(0, 15, -30.0)}, 3.0, 13.0)
    P.imprimir(P.calcular([10.0], [TRAMO], PICOS, amb), [TRAMO])
    salida = capsys.readouterr().out
    assert "MEDIDA CONTAMINADA" in salida and "apenas llega" not in salida


def test_informe_dice_cuando_el_eco_apenas_llega_al_micro(capsys):
    amb = P.ambiente({"reunion": bloques(0, 3, -120.0) + bloques(3, 13, -30.0) + bloques(13, 15, -120.0), "yo": bloques(0, 15, -55.0)}, 3.0, 13.0)
    P.imprimir(P.calcular([10.0], [], PICOS, amb), [])
    salida = capsys.readouterr().out
    assert "apenas llega al micrófono" in salida and "MEDIDA CONTAMINADA" not in salida
