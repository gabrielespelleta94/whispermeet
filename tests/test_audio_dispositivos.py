from apuntes.audio import elegir_dispositivo

ENTRADAS = [{"indice": 14}, {"indice": 15}]


def test_indice_guardado_valido_se_respeta():
    assert elegir_dispositivo(15, ENTRADAS, 14) == 15


def test_indice_que_ya_no_captura_pasa_al_de_por_defecto():
    assert elegir_dispositivo(9, ENTRADAS, 14) == 14


def test_sin_indice_guardado_usa_el_de_por_defecto():
    assert elegir_dispositivo(None, ENTRADAS, 14) == 14
