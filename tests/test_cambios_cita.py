"""Ola 3, punto 5: los cambios al contexto salen `preaceptado` con su `cita` solo si la frase aparece LITERALMENTE (normalizada) en la transcripción."""
from apuntes import cambios as CB
from apuntes.analisis import prompts as P

CONTENIDOS = {"02-alcance.md": "# Alcance\n\n## Cambios de alcance\n\n| fecha | cambio |\n|---|---|\n"}
TRANSCRIPCION = [(10.0, "Vale, entonces el piloto arranca con dos hoteles en enero."),
                 (75.0, "Y lo de las licencias lo cerramos con el proveedor"),
                 (80.0, "antes de que termine el mes, sin falta."),
                 (90.0, "Eh, bueno, sí.")]


def cambio(q=None, **extra):
    c = {"f": "02-alcance.md", "tipo": "anadir", "sec": "Cambios de alcance", "nuevo": "| 2026-11-06 | Piloto con dos hoteles |", "motivo": "m", "m": "00:10"}
    if q is not None:
        c["q"] = q
    return {**c, **extra}


def test_cita_literal_normalizada_preacepta():
    r = CB.normalizar([cambio("el piloto ARRANCA con dos hoteles en enero")], CONTENIDOS, TRANSCRIPCION)[0]
    assert r.valido and r.preaceptado is True
    assert r.cita == {"texto": "Vale, entonces el piloto arranca con dos hoteles en enero.", "minuto": "00:10"}
    assert r.publico()["preaceptado"] is True and r.publico()["cita"]["minuto"] == "00:10"


def test_cita_a_caballo_entre_dos_fragmentos_seguidos():
    r = CB.normalizar([cambio("cerramos con el proveedor antes de que termine el mes")], CONTENIDOS, TRANSCRIPCION)[0]
    assert r.preaceptado and r.cita["minuto"] == "01:15" and "proveedor" in r.cita["texto"] and "termine el mes" in r.cita["texto"]


def test_sin_cita_o_cita_inventada_o_corta_no_se_preacepta():
    for q in (None, "", "el piloto arranca con tres hoteles en enero", "dos hoteles", "licencias proveedor mes", 12345):
        r = CB.normalizar([cambio(q)], CONTENIDOS, TRANSCRIPCION)[0]
        assert r.valido and r.preaceptado is False and r.cita is None, q
    # sin transcripción (como antes de la ola 3): nada cambia
    r = CB.normalizar([cambio("el piloto arranca con dos hoteles en enero")], CONTENIDOS)[0]
    assert r.preaceptado is False and r.cita is None


def test_un_cambio_invalido_nunca_se_preacepta():
    r = CB.normalizar([cambio("el piloto arranca con dos hoteles en enero", f="99-nada.md")], CONTENIDOS, TRANSCRIPCION)[0]
    assert r.valido is False and r.preaceptado is False


def test_acepta_el_alias_cita_y_el_prompt_pide_la_frase_literal():
    r = CB.normalizar([{**cambio(), "cita": "el piloto arranca con dos hoteles en enero"}], CONTENIDOS, TRANSCRIPCION)[0]
    assert r.preaceptado
    assert '"q"' in P.sistema_final(True) and "LITERAL" in P.sistema_final(True) and '"q"' not in P.sistema_final(False)


def test_buscar_cita_es_pura():
    assert CB.buscar_cita("hola que tal estas hoy", [(0, "¡Hola! ¿Qué tal estás hoy?")]) == {"texto": "¡Hola! ¿Qué tal estás hoy?", "minuto": "00:00"}
    assert CB.buscar_cita("hola que tal", [(0, "Hola, qué tal")]) is None   # menos de cuatro palabras
    assert CB.buscar_cita("", []) is None
