"""Calidad de la transcripción: filtros, prompt (tema + vocabulario + continuidad), copias del prompt y reintento. Sin audio ni modelo real."""
import time
from types import SimpleNamespace

import numpy as np
import pytest

from apuntes.config import Config, DEFAULTS
from apuntes import contexto as CX
from apuntes.transcripcion import (MAX_PROMPT_CHARS, Transcriptor, construir_prompt, es_copia_del_prompt, filtrar_texto,
                                   ultima_frase)


# ------------------------------------------------------------------ filtros
@pytest.mark.parametrize("texto", [
    "Vale", "vale.", "Ok", "OK, ", "Vale, entonces lo dejamos para el lunes",
    "Hay que suscribir el contrato antes del viernes",
    "El cliente suscribe el acuerdo y se suscribirá a la plataforma",
    "Mira la web www.nordia.example y rellena el formulario de grupos con los datos",
    "Gracias por la aclaración, Luis",
])
def test_se_conserva_texto_legitimo(texto):
    assert filtrar_texto(texto) == " ".join(texto.split())


@pytest.mark.parametrize("texto", [
    "Gracias", "gracias.", "¡Gracias!", "Subtítulos realizados por la comunidad de Amara.org", "Amara.org",
    "Subtítulos por Fulano", "Gracias por ver el vídeo", "Gracias por vuestra atención",
    "Suscríbete", "suscribete al canal", "Suscribíos al canal y dadle a la campanita", "Suscríbanse", "Hay que suscribirse al canal",
    "No olvides suscribirte", "www.mooji.org", "Subtítulos en www.example.com", "https://www.example.com/video",
])
def test_se_descartan_las_alucinaciones_tipicas(texto):
    assert filtrar_texto(texto) == ""


def test_la_repeticion_en_bucle_sigue_colapsando():
    assert filtrar_texto("vale vale vale vale vale") == "vale"


def test_una_frase_entera_repetida_seguida_queda_una_sola_vez():
    # el tic de Whisper cuando el tramo acaba cortado: la misma frase dos o tres veces
    assert filtrar_texto("¿Alguien tiene alguna duda sobre? ¿Alguien tiene alguna duda sobre? ¿Alguien tiene alguna duda sobre?") == "¿Alguien tiene alguna duda sobre?"
    assert filtrar_texto("Lo vemos el lunes. Lo vemos el lunes. Y después cerramos el acta.") == "Lo vemos el lunes. Y después cerramos el acta."
    # lo que NO se toca: repeticiones cortas del habla normal, frases distintas y la misma frase si no va seguida
    assert filtrar_texto("Sí. Sí. Vale, vale.") == "Sí. Sí. Vale, vale."
    assert filtrar_texto("De acuerdo. De acuerdo.") == "De acuerdo. De acuerdo."
    assert filtrar_texto("Lo vemos el lunes. Lo vemos el martes.") == "Lo vemos el lunes. Lo vemos el martes."
    assert filtrar_texto("Lo vemos el lunes. Vale. Lo vemos el lunes.") == "Lo vemos el lunes. Vale. Lo vemos el lunes."
    # una pregunta y la respuesta que la repite son dos frases distintas (cambia el signo): la respuesta no se borra
    assert filtrar_texto("¿Lo tenemos para el lunes? Lo tenemos para el lunes. Perfecto.") == "¿Lo tenemos para el lunes? Lo tenemos para el lunes. Perfecto."


# ------------------------------------------------------------------ prompt
BASE = "Reunión de trabajo: Seguimiento del piloto."


def test_sin_vocabulario_ni_continuidad_el_prompt_es_el_de_hoy():
    assert construir_prompt(BASE) == BASE
    assert construir_prompt(BASE, [], "") == BASE
    assert construir_prompt("") == ""


def test_el_prompt_lleva_tema_vocabulario_y_continuidad_en_ese_orden():
    p = construir_prompt(BASE, ["PMS", "TR2"], "Luis envía la estimación el viernes.")
    assert p == BASE + " Términos: PMS, TR2. Luis envía la estimación el viernes."
    assert construir_prompt(BASE, ["PMS"]) == BASE + " Términos: PMS."
    assert construir_prompt(BASE, [], "Hola mundo.") == BASE + " Hola mundo."


def test_el_prompt_no_pasa_del_tope_y_recorta_primero_el_vocabulario():
    vocab = [f"Termino{i:02d}" for i in range(80)]
    cont = " ".join(f"palabra{i}" for i in range(30))
    p = construir_prompt(BASE, vocab, cont)
    assert len(p) <= MAX_PROMPT_CHARS
    assert p.startswith(BASE) and p.endswith(cont)          # tema y continuidad intactos
    incluidos = p.split("Términos: ")[1].split(".")[0].split(", ")
    assert incluidos == vocab[:len(incluidos)] and 0 < len(incluidos) < len(vocab)   # se conservan los primeros (los de más prioridad)


def test_si_ni_tema_y_continuidad_caben_se_acorta_la_continuidad_por_el_principio():
    cont = " ".join(f"p{i}" for i in range(200))
    p = construir_prompt(BASE, ["PMS"], cont)
    assert len(p) <= MAX_PROMPT_CHARS and p.startswith(BASE) and p.endswith("p199") and "Términos" not in p


def test_ultima_frase_con_tope_de_30_palabras():
    assert ultima_frase("Primera cosa. Segunda frase con cuerpo suficiente para ser continuidad.") == \
        "Segunda frase con cuerpo suficiente para ser continuidad."
    assert ultima_frase("Se queda con Luis pendiente de revisión. Vale.") == "Se queda con Luis pendiente de revisión. Vale."
    larga = " ".join(f"w{i}" for i in range(50)) + "."
    r = ultima_frase("Antes. " + larga)
    assert len(r.split()) == 30 and r.endswith("w49.")


# ------------------------------------------------------------------ copias del prompt
def test_copias_del_prompt_se_detectan():
    prompt = construir_prompt(BASE, ["PMS", "TR2", "Nordia"], "Luis envía la estimación el viernes.")
    assert es_copia_del_prompt("Términos: PMS, TR2, Nordia.", prompt, ["PMS", "TR2", "Nordia"])
    assert es_copia_del_prompt("PMS, Nordia, TR2", prompt, ["PMS", "TR2", "Nordia"])
    assert es_copia_del_prompt("Reunión de trabajo: Seguimiento del piloto.", prompt)
    assert es_copia_del_prompt("Luis envía la estimación el viernes.", prompt, continuidad="Luis envía la estimación el viernes.")
    assert es_copia_del_prompt("luis envia la estimacion el viernes", prompt, continuidad="Luis envía la estimación el viernes.")


def test_el_habla_real_que_menciona_vocabulario_no_es_copia():
    prompt = construir_prompt(BASE, ["PMS", "TR2", "Nordia"], "Luis envía la estimación el viernes.")
    assert not es_copia_del_prompt("El PMS de Nordia falla en la sesión TR2 cuando hay cupos", prompt, ["PMS", "TR2", "Nordia"])
    assert not es_copia_del_prompt("Vale", prompt, ["PMS"])
    assert not es_copia_del_prompt("Entonces el viernes lo vemos", prompt, ["PMS"], "Luis envía la estimación el viernes.")
    assert not es_copia_del_prompt("", prompt)


# ------------------------------------------------------------------ vocabulario (local)
def test_vocabulario_distintivo_siglas_camelcase_y_propios():
    t = ("# Planificador de Grupos\n## RESUMEN\nEl Planificador usa el PMS de Nordia y el CRS. Acordamos con Nordia que TR2 sigue. "
         "El motor MotorCotizacion llama a Nordia. IMPORTANTE revisar.\n- Usamos Excel y Excel. `CODIGO` https://www.foo.com/XYZ\n")
    v = CX.vocabulario_distintivo([t])
    assert v[0] == "Nordia"
    assert {"PMS", "CRS", "TR2", "MotorCotizacion", "Excel"} <= set(v)
    assert not {"RESUMEN", "IMPORTANTE", "CODIGO", "XYZ", "Planificador"} & set(v)   # títulos, código y enlaces fuera; sin frecuencia, tampoco
    assert CX.vocabulario_distintivo(["", "texto en minúsculas sin nada"]) == []
    assert len(CX.vocabulario_distintivo(["A1 B2 C3 D4 E5"], maximo=3)) == 3


def test_config_vocabulario_transcripcion_por_defecto_vacio_y_validado(tmp_path):
    assert DEFAULTS["vocabulario_transcripcion"] == [] and DEFAULTS["whisper_beam"] == 5
    c = Config(tmp_path / "c.json")
    c.actualizar({"vocabulario_transcripcion": ["PMS", " pms ", "x" * 41, 3, "Nordia Grupos"]})
    assert c["vocabulario_transcripcion"] == ["PMS", "Nordia Grupos"]


# ------------------------------------------------------------------ Transcriptor con modelo doble
def _seg(texto, nsp=0.0, lp=-0.3):
    return SimpleNamespace(text=texto, no_speech_prob=nsp, avg_logprob=lp)


class ModeloDoble:
    """Doble de WhisperModel: devuelve guiones por orden y guarda los argumentos de cada llamada."""
    def __init__(self, respuestas):
        self.respuestas, self.llamadas = list(respuestas), []

    def transcribe(self, audio, **kw):
        self.llamadas.append(kw)
        return iter([_seg(self.respuestas.pop(0))]), None


class TranscriptorDoble(Transcriptor):
    def __init__(self, config, on_texto, modelo):
        super().__init__(config, on_texto)
        self._m = modelo

    def cargar_modelo(self):
        return self._m


def _correr(respuestas, entradas, vocab=(), beam=5, curados=()):
    """Encola `entradas` [(fuente, t)] en orden y espera a que se procesen. Devuelve (emitidos, modelo, transcriptor)."""
    emitidos, modelo = [], ModeloDoble(respuestas)
    tr = TranscriptorDoble({"idioma": "es", "whisper_beam": beam, "whisper_modelo": "x", "whisper_hilos": 1},
                           lambda f, t, x: emitidos.append((f, x)), modelo)
    tr.prompt, tr.vocabulario, tr.vocabulario_curado = BASE, list(vocab), list(curados)
    tr.iniciar()
    try:
        for fuente, t in entradas:
            tr.encolar(fuente, np.zeros(1600, dtype=np.float32), t)
            fin = time.time() + 5
            while not tr.vacio() and time.time() < fin:   # de uno en uno: la continuidad de cada tramo depende del anterior
                time.sleep(0.01)
            time.sleep(0.05)
    finally:
        tr.detener()
    return emitidos, modelo, tr


def test_transcribir_pasa_la_tupla_de_temperaturas_y_el_resto_de_parametros():
    emitidos, modelo, _ = _correr(["Hola equipo"], [("yo", 0)])
    kw = modelo.llamadas[0]
    assert kw["temperature"] == (0.0, 0.2, 0.4)
    assert kw["beam_size"] == 5 and kw["language"] == "es" and kw["vad_filter"] is True
    assert kw["condition_on_previous_text"] is False and kw["no_speech_threshold"] == 0.6
    assert kw["initial_prompt"] == BASE and emitidos == [("yo", "Hola equipo")]


def test_la_continuidad_no_se_mezcla_entre_fuentes():
    _, modelo, tr = _correr(
        ["Primera frase del micro sobre el piloto.", "Segunda frase de la reunión sobre facturación.",
         "Tercera del micro.", "Cuarta de la reunión."],
        [("yo", 0), ("reunion", 1), ("yo", 2), ("reunion", 3)], vocab=["PMS"])
    p = [c["initial_prompt"] for c in modelo.llamadas]
    assert "Primera" not in p[1] and "Segunda" not in p[0]                      # la reunión no recibe lo del micro
    assert p[1] == BASE + " Términos: PMS."
    assert p[2].endswith("Primera frase del micro sobre el piloto.") and "Segunda" not in p[2]
    assert p[3].endswith("Segunda frase de la reunión sobre facturación.") and "Primera" not in p[3]
    assert tr.prompt_para("yo").endswith("Tercera del micro.") and tr.prompt_para("reunion").endswith("Cuarta de la reunión.")


def test_un_tramo_descartado_no_es_continuidad():
    emitidos, modelo, _ = _correr(
        ["Se acuerda enviar la propuesta el lunes.", "Gracias", "Suscríbete al canal", "Siguiente punto de la agenda."],
        [("yo", 0), ("yo", 1), ("yo", 2), ("yo", 3)])
    p = [c["initial_prompt"] for c in modelo.llamadas]
    assert p[1] == p[2] == p[3] and p[1].endswith("Se acuerda enviar la propuesta el lunes.")
    assert [x for _, x in emitidos] == ["Se acuerda enviar la propuesta el lunes.", "Siguiente punto de la agenda."]


def test_una_copia_del_prompt_se_descarta_y_no_pasa_a_continuidad():
    emitidos, modelo, tr = _correr(
        ["Luis envía la estimación el viernes.", "Términos: PMS, TR2, Nordia.", "Luis envía la estimación el viernes.", "El PMS falla."],
        [("reunion", 0), ("reunion", 1), ("reunion", 2), ("reunion", 3)], vocab=["PMS", "TR2", "Nordia"])
    assert [x for _, x in emitidos] == ["Luis envía la estimación el viernes.", "El PMS falla."]   # copia del vocabulario y repetición exacta fuera
    assert tr._ultima["reunion"] == "El PMS falla."
    assert modelo.llamadas[3]["initial_prompt"].endswith("Luis envía la estimación el viernes.")  # la copia descartada no la sustituyó


# ------------------------------------------------------------------ el gestor reparte el vocabulario al transcriptor
def test_el_gestor_pasa_al_transcriptor_el_vocabulario_de_config_y_del_contexto_sin_llamar_al_modelo(tmp_path):
    from apuntes.analisis import ModeloLLM
    from apuntes.consumo import Consumo
    from apuntes.gestor import Gestor
    from apuntes.rutas import Guardian

    class SinLlamadas(ModeloLLM):
        def completar(self, *a, **k):
            raise AssertionError("el vocabulario no debe llamar al modelo")

    cfg = Config(tmp_path / "c.json")
    cfg.actualizar({"vocabulario_transcripcion": ["Mi término", "PMS"]}, guardar=False)
    g = Gestor(cfg, Guardian(tmp_path / "p", tmp_path / "b", tmp_path / "c"), Consumo(None), SinLlamadas(), lambda e: None)
    g.transcriptor = Transcriptor(cfg, lambda *a: None)
    g._vocabulario_contexto = CX.vocabulario_distintivo(["Habla de PMS y de Nordia. Con Nordia y PMS y TR2."])
    g._actualizar_vocabulario()
    assert g.transcriptor.vocabulario[:2] == ["Mi término", "PMS"]          # lo de config manda, sin duplicar
    assert "Nordia" in g.transcriptor.vocabulario and "TR2" in g.transcriptor.vocabulario
    assert [t.lower() for t in g.transcriptor.vocabulario].count("pms") == 1


# ------------------------------------------------------------------ Silero VAD, hotwords y glosario
from apuntes.transcripcion import construir_hotwords, corregir_glosario


def _modelo_con(cfg_extra, vocab=()):
    emitidos, modelo = [], ModeloDoble(["Hola equipo"])
    tr = TranscriptorDoble({"idioma": "es", "whisper_beam": 5, "whisper_modelo": "x", "whisper_hilos": 1, **cfg_extra},
                           lambda f, t, x: emitidos.append((f, x)), modelo)
    tr.prompt, tr.vocabulario = BASE, list(vocab)
    tr._modelo = modelo
    tr.transcribir(np.zeros(16000, dtype=np.float32), "yo")
    return modelo.llamadas[0]


def test_vad_por_defecto_activo_con_500_ms_y_se_pasa_a_transcribe():
    kw = _modelo_con({})
    assert kw["vad_filter"] is True and kw["vad_parameters"] == {"min_silence_duration_ms": 500}
    assert DEFAULTS["whisper_vad"] is True and DEFAULTS["whisper_vad_min_silencio_ms"] == 500


def test_vad_se_puede_cambiar_y_apagar():
    kw = _modelo_con({"whisper_vad": True, "whisper_vad_min_silencio_ms": 800})
    assert kw["vad_parameters"] == {"min_silence_duration_ms": 800}
    kw = _modelo_con({"whisper_vad": False})
    assert kw["vad_filter"] is False and "vad_parameters" not in kw


def test_la_config_valida_las_claves_del_vad(tmp_path):
    c = Config(tmp_path / "c.json")
    c.actualizar({"whisper_vad": False, "whisper_vad_min_silencio_ms": 300})
    assert c["whisper_vad"] is False and c["whisper_vad_min_silencio_ms"] == 300
    c.actualizar({"whisper_vad": "no", "whisper_vad_min_silencio_ms": -5})
    assert c["whisper_vad"] is False and c["whisper_vad_min_silencio_ms"] == 300


def test_el_faster_whisper_instalado_acepta_vad_y_hotwords():
    import inspect
    from faster_whisper import WhisperModel
    params = inspect.signature(WhisperModel.transcribe).parameters
    assert {"vad_filter", "vad_parameters", "hotwords"} <= set(params)


def test_los_terminos_van_tambien_como_hotwords_con_tope():
    kw = _modelo_con({}, vocab=["SAP", "Fiori", "TPV"])
    assert kw["hotwords"] == "SAP, Fiori, TPV"
    assert _modelo_con({}).get("hotwords") is None
    largo = [f"Termino{i:02d}" * 2 for i in range(40)]
    h = construir_hotwords(largo)
    assert 0 < len(h) <= 200 and h.startswith(largo[0]) and not h.endswith(",")
    assert construir_hotwords(largo[:3], tope=40) == ", ".join(largo[:2])


@pytest.mark.parametrize("texto,esperado", [
    ("hemos hablado con sap sobre fiori y el tpv", "hemos hablado con SAP sobre Fiori y el TPV"),
    ("Sap, FIORI. tpv?", "SAP, Fiori. TPV?"),
    ("el sapo y los tpvs no son sap2 ni fiorin", "el sapo y los tpvs no son sap2 ni fiorin"),   # solo palabras completas
    ("La opcion de pago", "La Opción de pago"),                                                # acentos del término
    ("power bi y power point", "Power BI y power point"),
    ("sin terminos aqui", "sin terminos aqui"),
])
def test_corregir_glosario(texto, esperado):
    assert corregir_glosario(texto, ["SAP", "Fiori", "TPV", "Opción", "Power BI"], curados=["Fiori", "Opción"]) == esperado


def test_corregir_glosario_no_fuerza_palabras_comunes_del_contexto():
    # «Reserva» sale del contexto con solo la inicial: «la reserva» se queda como está
    assert corregir_glosario("la reserva del cupo", ["Reserva"]) == "la reserva del cupo"
    assert corregir_glosario("la reserva y sap", ["Reserva", "SAP"]) == "la reserva y SAP"
    # ≥2 mayúsculas o un dígito: se corrige aunque venga del contexto
    assert corregir_glosario("powerbi, tr2 y tpv", ["PowerBI", "TR2", "TPV"]) == "PowerBI, TR2 y TPV"
    # lo que puso el usuario en su vocabulario se corrige siempre, aunque solo tenga la inicial
    assert corregir_glosario("la reserva", ["Reserva"], curados=["reserva"]) == "la Reserva"
    assert corregir_glosario("fiori y reserva", ["Fiori", "Reserva"], curados=["Fiori"]) == "Fiori y reserva"


def test_el_transcriptor_solo_impone_lo_curado_o_las_siglas():
    emitidos, modelo = [], ModeloDoble(["la reserva de sap con fiori"])
    tr = TranscriptorDoble({"idioma": "es", "whisper_beam": 5, "whisper_modelo": "x", "whisper_hilos": 1},
                           lambda f, t, x: emitidos.append(x), modelo)
    tr.vocabulario, tr.vocabulario_curado = ["SAP", "Reserva", "Fiori"], ["Fiori"]
    tr.iniciar()
    try:
        tr.encolar("yo", np.zeros(1600, dtype=np.float32), 0.0)
        fin = time.time() + 5
        while not tr.vacio() and time.time() < fin:
            time.sleep(0.01)
        time.sleep(0.05)
    finally:
        tr.detener()
    assert emitidos == ["la reserva de SAP con Fiori"]


def test_corregir_glosario_sin_glosario_o_texto_vacio_no_toca_nada():
    assert corregir_glosario("sap y fiori", []) == "sap y fiori"
    assert corregir_glosario("", ["SAP"]) == ""


def test_el_glosario_se_aplica_antes_de_emitir_el_segmento():
    emitidos, _, tr = _correr(["hemos abierto sap fiori en el tpv"], [("reunion", 0)], vocab=["SAP", "Fiori", "TPV"], curados=["Fiori"])
    assert emitidos == [("reunion", "hemos abierto SAP Fiori en el TPV")]
