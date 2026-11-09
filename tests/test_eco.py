"""Eco entre canales (apuntes/eco.py + Sesion): frases SINTÉTICAS, en español y en catalán. Nada de esto sale de una reunión real.

La función de decisión es pura: `quitar_eco(texto_micro, t, [(t, texto_reunion)])`. Reglas que se comprueban:
- se conserva Reunión y de Micro solo se quita la parte que coincide (ante la duda se conserva);
- los dos canales escriben distinto (otras palabras, otras marcas) y aun así coinciden;
- el resultado no depende de qué canal llega antes; mientras un Micro espera a su pareja no se entrega a ningún análisis;
- con el interruptor apagado no se toca nada.
"""
from pathlib import Path

from apuntes import eco as E
from apuntes.config import DEFAULTS, Config
from apuntes.sesion import Sesion

R_ES = "Vamos a revisar el presupuesto anual de marketing con el equipo comercial antes del cierre trimestral porque necesitamos aprobar las partidas pendientes"
R_CA = "Hem de revisar el pressupost anual de màrqueting amb l'equip comercial abans del tancament trimestral perquè necessitem aprovar les partides pendents"


# ------------------------------------------------------------------ la decisión, pura
def test_el_mismo_texto_con_errores_de_transcripcion_es_eco_en_espanol():
    micro = "vamos a revisar el presupuesto anual de marketin con el equipo comerzial antes del cierre trimestral porque necesitamos aprobar las partidas pendiente"
    assert E.quitar_eco(micro, 83.0, [(81.0, R_ES)]) == ""


def test_lo_mismo_en_catalan():
    micro = "hem de revisar el pressupost anual de marqueting amb l'equip comercial abans del tancament trimestral perque necessitem aprovar les partides pendents"
    assert E.quitar_eco(micro, 30.0, [(41.0, R_CA)]) == ""


def test_solo_se_quita_lo_que_coincide_y_se_conserva_la_voz_propia():
    micro = ("Perdona, ¿puedo preguntar una cosa antes de seguir? " + R_ES.lower().replace("marketing", "marketin")
             + " Yo creo que el proveedor nuevo cobra demasiado por el transporte.")
    resto = E.quitar_eco(micro, 100.0, [(98.0, R_ES)])
    assert "Perdona, ¿puedo preguntar una cosa antes de seguir?" in resto
    assert "Yo creo que el proveedor nuevo cobra demasiado por el transporte." in resto
    assert "presupuesto anual" not in resto and "partidas pendientes" not in resto


def test_la_pareja_puede_estar_partida_en_varios_fragmentos_de_reunion():
    a, b = R_ES.split(" antes ")[0], "antes " + R_ES.split(" antes ")[1]
    assert E.quitar_eco(R_ES.lower(), 50.0, [(44.0, a), (61.0, b)]) == ""


def test_frases_cortas_que_dicen_los_dos_canales_nunca_se_eliminan():
    for corta in ("Vale, perfecto, de acuerdo.", "Sí, sí, exacto.", "Val, molt bé, d'acord."):
        assert E.quitar_eco(corta, 10.0, [(10.0, corta)]) == corta


def test_sin_coincidencia_sostenida_no_se_toca_aunque_compartan_palabras_funcionales():
    micro = "Creo que para el equipo de ventas lo que importa es que el cliente tenga el precio antes de que cierre el trato de este mes"
    reunion = "Ayer hablamos de que el equipo de soporte tiene que mejorar el tiempo de respuesta del cliente antes de fin de año"
    assert E.quitar_eco(micro, 10.0, [(12.0, reunion)]) == micro


def test_fuera_de_la_ventana_de_tiempo_no_es_eco():
    micro = R_ES.lower()
    assert E.quitar_eco(micro, 500.0, [(100.0, R_ES)]) == micro
    assert E.quitar_eco(micro, 100.0, [(100.0 + E.VENTANA_DESPUES_S + 1, R_ES)]) == micro
    assert E.quitar_eco(micro, 100.0, [(100.0 - E.VENTANA_ANTES_S - 1, R_ES)]) == micro
    assert E.quitar_eco(micro, 100.0, [(100.0 + E.VENTANA_DESPUES_S - 1, R_ES)]) == ""


def test_las_cifras_y_los_codigos_son_iguales_o_son_otra_cosa():
    reunion = "El hotel recibirá 50 mil euros para la reforma del vestíbulo y la piscina este año"
    micro = "El hotel recibirá 52 mil euros para la reforma del vestíbulo y la piscina este año"
    resto = E.quitar_eco(micro, 5.0, [(5.0, reunion)])
    assert "52" in resto            # la cifra distinta no se da por eco
    assert E.quitar_eco("la fase t1x1 de la pasarela t1x2 del hotel t1x3 de la zona t1x4 del sur", 5.0,
                        [(5.0, "la fase t1x9 de la pasarela t1x8 del hotel t1x7 de la zona t1x6 del sur")]) != ""


def test_una_palabra_con_contenido_mal_transcrita_dentro_del_eco_se_absorbe():
    reunion = "Tenemos que cerrar el contrato con el proveedor de lavandería antes del viernes y avisar al departamento financiero"
    micro = "tenemos que cerrar el contrato con el probedor de lavanderia antes del biernes y abisar al departamento financiero"
    assert E.quitar_eco(micro, 7.0, [(9.0, reunion)]) == ""


def test_un_resto_de_una_o_dos_palabras_de_relleno_pegado_al_corte_se_descarta():
    micro = "Sí. " + R_ES.lower()
    assert E.quitar_eco(micro, 3.0, [(3.0, R_ES)]) == ""


# ------------------------------------------------------------------ espera del Micro a su pareja
def test_micro_listo_por_tiempo_o_porque_reunion_ya_avanzo():
    assert not E.micro_listo(llegada=100.0, ahora=110.0, reunion=[(95.0, "x")], t=100.0)
    assert E.micro_listo(llegada=100.0, ahora=100.0 + E.ESPERA_S, reunion=[], t=100.0)          # esperó lo máximo
    assert E.micro_listo(llegada=100.0, ahora=110.0, reunion=[(100.0 + E.VENTANA_DESPUES_S + 1, "x")], t=100.0)   # Reunión ya pasó de largo
    assert E.micro_listo(llegada=100.0, ahora=101.0, reunion=[], t=100.0, final=True)


# ------------------------------------------------------------------ en la sesión: orden de llegada
def _sesion(filtrar=True):
    s = Sesion(None, "t", 5, Path("x.md"))
    s.filtrar_eco = filtrar
    reloj = [0.0]
    s.vincular_reloj(lambda: reloj[0])
    return s, reloj


MICRO = "Perdona, ¿puedo preguntar una cosa antes de seguir? " + R_ES.lower() + " Yo creo que el proveedor nuevo cobra demasiado por el transporte."


def _resultado(orden):
    s, reloj = _sesion()
    for t, fuente, texto in orden:
        reloj[0] = max(reloj[0], t)
        s.agregar_segmento(t, fuente, texto)
    return {(x.fuente, x.t): x.texto for x in s.segmentos}


def test_el_resultado_es_el_mismo_llegue_primero_micro_o_reunion():
    micro_primero = _resultado([(100.0, "yo", MICRO), (103.0, "reunion", R_ES)])
    reunion_primero = _resultado([(103.0, "reunion", R_ES), (100.0, "yo", MICRO)])
    assert micro_primero == reunion_primero
    quedan = micro_primero[("yo", 100.0)]
    assert "presupuesto" not in quedan and "Yo creo que el proveedor nuevo" in quedan and micro_primero[("reunion", 103.0)] == R_ES


def test_el_micro_que_llega_antes_se_corrige_al_llegar_su_pareja_y_se_avisa_a_la_interfaz():
    s, reloj = _sesion()
    s.agregar_segmento(100.0, "yo", MICRO)
    assert s.segmentos[0].texto == MICRO and s.recoger_cambios_eco() == []        # aún no hay pareja: se deja como llegó
    reloj[0] = 104.0
    s.agregar_segmento(103.0, "reunion", R_ES)
    cambios = s.recoger_cambios_eco()
    assert len(cambios) == 1 and cambios[0]["id"] == 1 and "presupuesto" not in cambios[0]["texto"]
    assert s.recoger_cambios_eco() == []


def test_un_micro_no_se_entrega_a_un_analisis_hasta_que_llega_su_pareja_o_pasa_la_espera():
    s, reloj = _sesion()
    s.agregar_segmento(10.0, "reunion", "Primera frase de la reunión que no tiene nada que ver con lo siguiente")
    reloj[0] = 20.0
    s.agregar_segmento(20.0, "yo", MICRO)
    s.agregar_segmento(21.0, "reunion", "Una frase posterior de la reunión sobre otro asunto distinto")
    reloj[0] = 25.0
    assert [x.id for x in s.estables(0)] == [1]                                   # el Micro (2) y lo que llegó después (3) esperan
    assert [x.id for x in s.estables(0, esperar=False)] == [1, 2, 3]              # «Analizar ahora» lee lo recibido
    assert [x.id for x in s.estables(0, final=True)] == [1, 2, 3]                 # el cierre lo entrega todo
    reloj[0] = 20.0 + E.ESPERA_S
    assert [x.id for x in s.estables(0)] == [1, 2, 3]                             # esperó lo máximo
    s2, reloj2 = _sesion()
    s2.agregar_segmento(20.0, "yo", MICRO)
    reloj2[0] = 21.0
    assert s2.estables(0) == []
    s2.agregar_segmento(20.0 + E.VENTANA_DESPUES_S + 5, "reunion", "Más de cuarenta y cinco segundos después Reunión sigue hablando de otra cosa")
    assert [x.id for x in s2.estables(0)] == [1, 2]                               # Reunión ya pasó de largo: no vendrá su pareja


def test_un_micro_que_era_todo_eco_no_se_entrega_ni_se_escribe():
    s, reloj = _sesion()
    s.agregar_segmento(10.0, "reunion", R_ES)
    reloj[0] = 12.0
    s.agregar_segmento(11.0, "yo", R_ES.lower())
    assert s.segmentos[1].texto == "" and s.segmentos[1].original == R_ES.lower()
    assert [x.id for x in s.estables(0, final=True)] == [1]
    md = s.render()
    assert md.count("**Micro:**") == 0 and md.count("**Reunión:**") == 1


def test_con_el_interruptor_apagado_no_se_toca_nada_y_no_se_espera():
    s, reloj = _sesion(filtrar=False)
    s.agregar_segmento(10.0, "reunion", R_ES)
    s.agregar_segmento(11.0, "yo", R_ES.lower())
    assert s.segmentos[1].texto == R_ES.lower()
    assert [x.id for x in s.estables(0)] == [1, 2]


def test_voces_distintas_en_el_micro_se_conservan_aunque_hablen_a_la_vez_que_reunion():
    s, reloj = _sesion()
    s.agregar_segmento(10.0, "reunion", R_ES)
    reloj[0] = 12.0
    s.agregar_segmento(11.0, "yo", "Una persona de la sala dice que el calendario de obras no encaja con la reforma de la cocina")
    s.agregar_segmento(12.0, "yo", "Otra persona responde que hablará con el arquitecto para mover la fecha de entrega al mes siguiente")
    assert [x.texto for x in s.segmentos[1:]] == [x.original for x in s.segmentos[1:]]


# ------------------------------------------------------------------ configuración
def test_filtrar_eco_esta_activo_por_defecto_y_solo_admite_booleanos(tmp_path):
    assert DEFAULTS["filtrar_eco"] is True
    cfg = Config(tmp_path / "c.json")
    assert cfg["filtrar_eco"] is True
    cfg.actualizar({"filtrar_eco": False}, guardar=False)
    assert cfg["filtrar_eco"] is False
    cfg.actualizar({"filtrar_eco": "no"}, guardar=False)
    assert cfg["filtrar_eco"] is False
    assert cfg["final_chars_huecos"] >= 19_000      # una reunión de ~12 min (~19.400 caracteres con etiquetas, sin filtrar) entra entera


# ------------------------------------------------------------------ cifras: una sola forma canónica
def _claves(texto):
    return [p.clave for p in E.palabras(texto)]


def test_las_cifras_en_letras_y_en_digitos_son_la_misma():
    assert _claves("noventa y cinco")[0] == "95" == _claves("95")[0]
    assert _claves("95 €") == _claves("noventa y cinco euros") == ["95", "euros"]
    assert _claves("dos mil quinientos") == ["2500"] and _claves("2.500") == ["2500"]
    assert _claves("treinta y uno") == ["31"] and _claves("vint-i-u persones")[0] == "21"
    assert _claves("cinco cinco") == ["5", "5"]                    # dos cifras seguidas no se funden


def test_una_palabra_ambigua_suelta_no_es_una_cifra():
    assert not any(c.isdigit() for c in _claves("un hotel y una sala; nou persones"))


def test_micro_con_la_cifra_en_letras_no_la_pierde_si_reunion_dice_una_frase_parecida_sin_ella():
    micro = "Queda decidido: precio noventa y cinco euros por pasajero"
    for reunion in ("Queda decidido: precio por pasajero", "Queda decidido el precio por pasajero y por habitación"):
        resto = E.quitar_eco(micro, 100.0, [(100.0, reunion)])
        assert "noventa y cinco euros" in resto


def test_con_la_cifra_en_digitos_en_reunion_sigue_siendo_eco_y_con_otra_cifra_no():
    micro = "Queda decidido: precio noventa y cinco euros por pasajero"
    assert E.quitar_eco(micro, 100.0, [(100.0, "Queda decidido: precio 95 € por pasajero")]) == ""
    assert E.quitar_eco(micro, 100.0, [(101.0, "Queda decidido: precio 95 euros por pasajero")]) == ""
    resto = E.quitar_eco(micro, 100.0, [(100.0, "Queda decidido: precio 90 euros por pasajero")])
    assert "noventa y cinco" in resto


def test_nunca_se_quita_un_tramo_con_una_cifra_que_reunion_no_tiene():
    m = E.palabras("hemos cerrado un acuerdo para ochenta mil euros con el cliente")
    r = E.palabras("hemos cerrado un acuerdo para el pago con el cliente")
    assert E._sin_cifras_nuevas([(0, len(m) - 1)], m, r) == []
    assert E._sin_cifras_nuevas([(0, 3)], m, r) == [(0, 3)]


# ---------------------------------------------------------------- caché de la tokenización: misma salida que sin caché
_TEXTOS_CACHE = [
    "", "   ", "Vale.", "El presupuesto de la fase uno son noventa y cinco euros, cuatro por ciento más.",
    "Són 1.500 € de pressupost; vint-i-u dies, dos-cents cinquanta euros i 95,5 per cent.",
    "¿Cuántos pasajeros? Tres mil doscientos cuarenta y uno. ¡Perfecto!", "Hem de tancar la xifra dimarts, per què no demà?",
    "ÁÉÍÓÚ ñ ç ll qu cu hh vvv zzz", "Cifras: 12, 3.000, 7,5 y 52 en el código ov2 termino3x1.", "un uno una u nou deu set mil",
    "Quinientos mil euros de inversión en migración; la reunión fue el pasado jueves.",
]


def test_palabras_con_cache_igual_a_sin_cache_incluso_llamando_dos_veces():
    for t in _TEXTOS_CACHE:
        esperado = list(E._palabras_sin_cache(t))
        assert E.palabras(t) == esperado
        assert E.palabras(t) == esperado   # segunda llamada: ya sale de la caché
    assert E.palabras(None) == []


def test_plegar_con_cache_igual_a_sin_cache():
    for t in _TEXTOS_CACHE:
        for w in t.split():
            assert E._plegar(w) == E._plegar.__wrapped__(w)
            assert E._plegar(w) == E._plegar.__wrapped__(w)


def test_modificar_lo_que_devuelve_palabras_no_corrompe_la_cache():
    t = "El presupuesto de la fase uno son noventa y cinco euros"
    limpio = list(E._palabras_sin_cache(t))
    primera = E.palabras(t)
    primera.clear()
    primera.append("basura")
    assert E.palabras(t) == limpio


def test_quitar_eco_con_cache_igual_en_llamadas_repetidas():
    reunion = [(0.0, "El presupuesto de la fase uno son noventa y cinco euros por pasajero."), (5.0, "Lo cerramos el martes con el cliente.")]
    micro = "el presupuesto de la fase uno son 95 € por pasajero y además me falta confirmar la fecha"
    primero = E.quitar_eco(micro, 2.0, reunion)
    assert E.quitar_eco(micro, 2.0, reunion) == primero
    E._palabras_cacheada.cache_clear()
    assert E.quitar_eco(micro, 2.0, reunion) == primero
