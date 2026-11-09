"""La transcripción no puede quedarse atrás: ventana ajustada del codificador, modo rápido con cola, tope de tokens, reintento, idioma vigente
y contabilidad (retraso, latencia, perdidos). Los tramos se transcriben de uno en uno y en orden de llegada. Todo con modelos dobles:
ni se carga Whisper ni se abre audio."""
from __future__ import annotations

import queue
import threading
import time
from types import SimpleNamespace

import numpy as np
import pytest

from apuntes.transcripcion import (BEAM_RAPIDO, COLA_ALCANCE_S, FRAMES_POR_S, IDIOMA_VIGENTE_S, MARGEN_VENTANA_S, MAX_TOKENS_WHISPER,
                                   TEMPERATURAS, TEMPERATURAS_RAPIDO, TOKENS_MARGEN, TOKENS_POR_S, TOPE_TOKENS_SEGURO, VENTANAS_S,
                                   Transcriptor, tope_tokens, ventana_frames)

SR = 16000
CFG = {"idioma": "es", "whisper_beam": 5, "whisper_modelo": "x", "whisper_hilos": 1, "whisper_palabras": True}


def _audio(seg: float, valor: float = 0.0) -> np.ndarray:
    return np.full(int(SR * seg), valor, np.float32)


def _hasta(cond, limite: float = 5.0) -> bool:
    """Espera activa y corta: True en cuanto `cond()` se cumple (o False al pasar `limite`)."""
    fin = time.time() + limite
    while time.time() < fin:
        if cond():
            return True
        time.sleep(0.005)
    return bool(cond())


# ------------------------------------------------------------------ funciones puras
def test_ventana_frames_en_los_limites_de_cada_ventana():
    f = FRAMES_POR_S
    assert ventana_frames(0) == 800 and ventana_frames(3) == 800            # 3 + 5 = 8 s: cabe justo en la menor
    assert ventana_frames(3.1) == 1000 and ventana_frames(5) == 1000
    assert ventana_frames(10) == 1500 and ventana_frames(15) == 2000
    assert ventana_frames(20) == 2500
    assert ventana_frames(25) == 3000 and ventana_frames(40) == 3000        # nunca más de los 30 s de Whisper
    assert ventana_frames(-4) == 800                                          # una duración negativa cuenta como 0
    # en cada límite de las constantes: justo en el borde se queda, un poco más sube a la siguiente
    for ant, sig in zip(VENTANAS_S, VENTANAS_S[1:]):
        assert ventana_frames(ant - MARGEN_VENTANA_S) == ant * f
        assert ventana_frames(ant - MARGEN_VENTANA_S + 0.01) == sig * f


def test_ventana_frames_con_margen_propio():
    assert ventana_frames(2, margen_s=0) == 800 and ventana_frames(8.1, margen_s=0) == 1000


def test_tope_de_tokens_sin_prompt_es_proporcional_y_none_por_encima_del_seguro():
    assert tope_tokens(0) == TOKENS_MARGEN and tope_tokens(-3) == TOKENS_MARGEN
    assert tope_tokens(8) - tope_tokens(3) == 5 * TOKENS_POR_S
    limite = (TOPE_TOKENS_SEGURO - TOKENS_MARGEN) / TOKENS_POR_S
    assert tope_tokens(limite) == TOPE_TOKENS_SEGURO
    assert tope_tokens(limite + 0.5) is None and tope_tokens(60) is None


def test_tope_de_tokens_con_prompt_conocido_nunca_supera_lo_que_cabe():
    assert tope_tokens(10, 100) == 10 * TOKENS_POR_S + TOKENS_MARGEN       # sobra sitio: manda la duración
    assert tope_tokens(60, 100) == MAX_TOKENS_WHISPER - 100 - 2            # 504 pedidos, solo 346 libres
    for dur, prompt in ((60, 100), (30, 300), (100, 200), (5, 440), (0, 10)):
        t = tope_tokens(dur, prompt)
        assert t is None or t <= MAX_TOKENS_WHISPER - prompt - 2


def test_tope_de_tokens_none_cuando_no_cabe_nada():
    assert tope_tokens(5, MAX_TOKENS_WHISPER - 2) is None          # libre = 0
    assert tope_tokens(5, MAX_TOKENS_WHISPER) is None and tope_tokens(5, 600) is None
    assert tope_tokens(5, MAX_TOKENS_WHISPER - 3) == 1             # libre = 1


# ------------------------------------------------------------------ dobles
class ModeloPorTramos:
    """Doble de WhisperModel: cada tramo de prueba es un bloque de valor constante; devuelve un segmento por bloque con su inicio real."""
    def __init__(self):
        self.llamadas = []
        self.tr = None   # el transcriptor, para anotar `alcance` en cada llamada

    def transcribe(self, audio, **kw):
        self.llamadas.append(dict(kw, audio_s=audio.size / SR, alcance=getattr(self.tr, "alcance", None)))
        segs, i = [], 0
        while i < audio.size:
            if audio[i] == 0:
                i += 1
                continue
            j = i
            while j < audio.size and audio[j] == audio[i]:
                j += 1
            segs.append(SimpleNamespace(text=f" frase {round(float(audio[i]) * 100)} ", start=i / SR, end=j / SR,
                                        no_speech_prob=0.0, avg_logprob=-0.2))
            i = j
        return iter(segs), None


class ColaVivaz(queue.Queue):
    """Como la cola real, pero el hilo mira cada 20 ms si debe parar (el bucle espera 0,3 s por vuelta): los tests no pierden tiempo al cerrar."""
    def get(self, block=True, timeout=None):
        return super().get(block, min(timeout, 0.02) if timeout else timeout)


class TranscriptorRetenido(Transcriptor):
    """El modelo no está listo hasta que se suelta `listo`: lo encolado antes se acumula como en una reunión que va por detrás."""
    def __init__(self, config, on_texto, modelo):
        super().__init__(config, on_texto)
        self._cola = ColaVivaz()
        self._m, self.listo = modelo, threading.Event()

    def cargar_modelo(self):
        self.listo.wait(5)
        return self._m


def _transcriptor(modelo=None, palabras=False, cfg=None, auto=False, listo=False):
    emitidos, modelo = [], modelo if modelo is not None else ModeloPorTramos()
    config = dict(CFG, **(cfg or {}))
    if auto:
        config["idiomas_auto"] = ["es", "ca"]
    tr = TranscriptorRetenido(config, lambda f, t, x, **kw: emitidos.append((f, t, x)), modelo)
    modelo.tr = tr
    tr.prompt = "Reunión de trabajo: Seguimiento."
    if auto:
        tr.idioma = "auto"
    tr.entrega_palabras = palabras
    if listo:
        tr.listo.set()
    tr.iniciar()
    return tr, modelo, emitidos


def _terminar(tr):
    """Espera a que no quede nada ni modo rápido y para el hilo (sin esperas largas)."""
    _hasta(lambda: tr.vacio() and not tr.alcance)
    tr.listo.set()
    tr.detener()


def _uno_a_uno(tr, tramos):
    """Encola [(fuente, segundos, valor)] de uno en uno esperando a que cada uno acabe: la cola nunca acumula."""
    for i, (fuente, seg, valor) in enumerate(tramos):
        tr.encolar(fuente, _audio(seg, valor), float(i))
        assert _hasta(lambda: tr.vacio())


def _rapido(kw, beam=BEAM_RAPIDO):
    return kw["beam_size"] == beam and kw["temperature"] == TEMPERATURAS_RAPIDO and "word_timestamps" not in kw


def _completo(kw, beam=5, palabras=False):
    return (kw["beam_size"] == beam and kw["temperature"] == TEMPERATURAS and
            (kw.get("word_timestamps") is True) == palabras)


# ------------------------------------------------------------------ _instalar_ventana
class DobleEncode:
    def __init__(self):
        self.vistas = []

    def encode(self, features, *args, **kw):
        self.vistas.append(features.shape)
        return features


def test_instalar_ventana_recorta_las_caracteristicas_a_frames_ventana():
    tr, m = Transcriptor(CFG, lambda *a: None), DobleEncode()
    tr._instalar_ventana(m)
    tr._modelo = m
    tr._fijar_ventana(800)
    m.encode(np.zeros((80, 3000), np.float32))
    tr._fijar_ventana(1500)
    m.encode(np.zeros((80, 3000), np.float32))
    assert m.vistas == [(80, 800), (80, 1500)]


def test_instalar_ventana_deja_enteras_las_caracteristicas_con_cero_o_ya_cortas():
    tr, m = Transcriptor(CFG, lambda *a: None), DobleEncode()
    tr._instalar_ventana(m)
    tr._modelo = m
    tr._fijar_ventana(0)
    m.encode(np.zeros((80, 3000), np.float32))
    tr._fijar_ventana(2000)
    m.encode(np.zeros((80, 1200), np.float32))
    m.encode(np.zeros((80, 2000), np.float32))
    assert m.vistas == [(80, 3000), (80, 1200), (80, 2000)]


def test_instalar_ventana_pasa_argumentos_y_resultado_del_encode_original():
    class ConArgs:
        def encode(self, features, *args, **kw):
            return ("ok", features.shape, args, kw)
    tr, m = Transcriptor(CFG, lambda *a: None), ConArgs()
    tr._instalar_ventana(m)
    tr._modelo = m
    tr._fijar_ventana(800)
    assert m.encode(np.zeros((80, 3000), np.float32), 7, a=1) == ("ok", (80, 800), (7,), {"a": 1})


def test_instalar_ventana_dos_veces_no_envuelve_dos_veces():
    tr, m = Transcriptor(CFG, lambda *a: None), DobleEncode()
    tr._instalar_ventana(m)
    tr._modelo = m
    primero = m.encode
    tr._instalar_ventana(m)
    assert m.encode is primero
    tr._fijar_ventana(800)
    m.encode(np.zeros((80, 3000), np.float32))
    assert m.vistas == [(80, 800)]   # se recortó una sola vez, no dos


def test_un_modelo_compartido_lleva_la_ventana_de_cada_transcriptor_y_de_cada_hilo():
    # el dictado reutiliza el modelo entre dictados: el segundo transcriptor también recorta, y cada hilo ve SU ventana
    m = DobleEncode()
    a, b = Transcriptor(CFG, lambda *x: None), Transcriptor(CFG, lambda *x: None)
    for tr in (a, b):
        tr._instalar_ventana(m)
        tr._modelo = m
    a._fijar_ventana(800)
    m.encode(np.zeros((80, 3000), np.float32))
    a._fijar_ventana(0)
    b._fijar_ventana(1500)
    m.encode(np.zeros((80, 3000), np.float32))
    vistas_otro_hilo = []

    def otro():   # un hilo que no ha fijado ventana codifica entero, aunque este hilo tenga 1500
        vistas_otro_hilo.append(m.encode(np.zeros((80, 3000), np.float32)).shape)

    h = threading.Thread(target=otro)
    h.start()
    h.join(2)
    b._fijar_ventana(0)
    assert m.vistas[:2] == [(80, 800), (80, 1500)] and vistas_otro_hilo == [(80, 3000)]


def test_instalar_ventana_no_toca_un_doble_sin_encode():
    class SinEncode:
        pass
    tr, m = Transcriptor(CFG, lambda *a: None), SinEncode()
    tr._instalar_ventana(m)
    assert not hasattr(m, "encode")


class ModeloVeEncode(ModeloPorTramos):
    """Su `transcribe` llama a `self.encode` con una ventana entera de 30 s, como hace faster-whisper."""
    def __init__(self, falla=False):
        super().__init__()
        self.vistas, self.ventanas, self.falla = [], [], falla

    def encode(self, features, *args, **kw):
        self.vistas.append(features.shape[-1])
        return features

    def transcribe(self, audio, **kw):
        self.ventanas.append(self.tr._frames_ventana)
        self.encode(np.zeros((80, 3000), np.float32))
        if self.falla:
            raise RuntimeError("sin memoria")
        return iter([]), None


def test_de_extremo_a_extremo_el_codificador_ve_la_ventana_de_la_duracion_del_tramo():
    tr, m, _ = _transcriptor(ModeloVeEncode(), listo=True)
    try:
        _uno_a_uno(tr, [("yo", 3, 0.1), ("yo", 12, 0.1), ("yo", 28, 0.1)])
    finally:
        _terminar(tr)
    assert m.vistas == [800, 2000, 3000]
    assert m.ventanas == [ventana_frames(3), ventana_frames(12), ventana_frames(28)]
    assert tr._frames_ventana == 0


def test_la_ventana_vuelve_a_cero_tambien_si_transcribe_lanza():
    tr, m, _ = _transcriptor(ModeloVeEncode(falla=True), listo=True)
    try:
        _uno_a_uno(tr, [("yo", 3, 0.1)])
    finally:
        _terminar(tr)
    assert m.vistas == [800, 800] and tr._frames_ventana == 0   # la pasada y su reintento vieron la ventana ajustada


# ------------------------------------------------------------------ sin cola
def test_sin_cola_una_llamada_por_tramo_con_la_calidad_completa():
    tr, m, emitidos = _transcriptor(palabras=True, listo=True)
    try:
        _uno_a_uno(tr, [("yo", 5, 0.01), ("reunion", 5, 0.02), ("yo", 5, 0.03)])
    finally:
        _terminar(tr)
    assert len(m.llamadas) == 3
    assert all(_completo(kw, palabras=True) and kw["alcance"] is False for kw in m.llamadas)
    assert all(kw["max_new_tokens"] == tope_tokens(5) for kw in m.llamadas)       # el doble no tiene tokenizador: tope sin prompt
    assert [x for _f, _t, x in emitidos] == ["frase 1", "frase 2", "frase 3"]
    assert tr.tramos_rapidos == 0 and tr.alcance is False and tr.reintentos == 0 and tr.vacio()


def test_sin_cola_no_pide_palabras_si_no_se_entregan():
    tr, m, _ = _transcriptor(palabras=False, listo=True)
    try:
        _uno_a_uno(tr, [("yo", 2, 0.01)])
    finally:
        _terminar(tr)
    assert _completo(m.llamadas[0], palabras=False)


def test_un_tramo_largo_sin_tokenizador_va_sin_tope_de_tokens():
    tr, m, _ = _transcriptor(listo=True)
    try:
        _uno_a_uno(tr, [("yo", 25, 0.01)])
    finally:
        _terminar(tr)
    assert tope_tokens(25) is None and "max_new_tokens" not in m.llamadas[0]


# ------------------------------------------------------------------ con cola
def _encolar_8_de_2s(tr):
    """8 tramos de 2 s alternando fuentes: detrás del primero esperan 14 s (por encima de COLA_ALCANCE_S)."""
    for k in range(8):
        tr.encolar("reunion" if k % 2 == 0 else "yo", _audio(2, (k + 1) / 100), float(10 * k))


def test_con_cola_una_llamada_por_tramo_sin_juntar_y_con_los_parametros_rapidos():
    tr, m, _ = _transcriptor(palabras=True)
    try:
        _encolar_8_de_2s(tr)
        assert tr.pendiente_s - 2 >= COLA_ALCANCE_S
        tr.listo.set()
        _terminar(tr)
    finally:
        tr.detener()
    assert len(m.llamadas) == 8 and all(kw["audio_s"] == 2 for kw in m.llamadas)   # nada de juntar tramos
    # el tramo k tiene detrás 14 - 2k s: rápido mientras queden ≥ COLA_ALCANCE_S (k = 0..4, el 4 justo en el borde)
    assert [_rapido(kw) for kw in m.llamadas] == [True] * 5 + [False] * 3
    assert all(kw["alcance"] for kw in m.llamadas[:5]) and not any(kw["alcance"] for kw in m.llamadas[5:])
    assert all(_completo(kw, palabras=True) for kw in m.llamadas[5:])
    assert all(kw["max_new_tokens"] == tope_tokens(2) for kw in m.llamadas)
    assert tr.tramos_rapidos == 5 and tr.vacio() and tr.pendiente_s == 0


def test_con_cola_los_textos_salen_en_el_orden_exacto_en_que_se_encolaron_con_su_t0():
    tr, m, emitidos = _transcriptor()
    try:
        orden = ["reunion", "yo", "yo", "reunion", "yo", "reunion", "reunion", "yo"]   # alternan (y repiten) las dos fuentes
        for k, f in enumerate(orden):
            tr.encolar(f, _audio(2, (k + 1) / 100), 100.0 + 7 * k)
        tr.listo.set()
        _terminar(tr)
    finally:
        tr.detener()
    assert emitidos == [(f, 100.0 + 7 * k, f"frase {k + 1}") for k, f in enumerate(orden)]
    assert [round(kw["audio_s"]) for kw in m.llamadas] == [2] * 8


def test_al_vaciarse_la_cola_alcance_es_false_y_el_tramo_siguiente_va_con_calidad_completa():
    tr, m, _ = _transcriptor(palabras=True)
    try:
        for k in range(6):
            tr.encolar("reunion", _audio(3, (k + 1) / 100), float(k * 4))
        tr.listo.set()
        assert _hasta(lambda: tr.alcance)
        assert _hasta(lambda: tr.vacio() and not tr.alcance)
        assert tr.tramos_rapidos > 0
        rapidos = tr.tramos_rapidos
        tr.encolar("reunion", _audio(3, 0.5), 100.0)
        assert _hasta(lambda: len(m.llamadas) == 7 and tr.vacio())
    finally:
        _terminar(tr)
    assert _completo(m.llamadas[-1], palabras=True) and m.llamadas[-1]["audio_s"] == 3
    assert tr.alcance is False and tr.tramos_rapidos == rapidos


def test_con_poca_cola_por_debajo_del_umbral_se_mantiene_la_calidad_completa():
    tr, m, _ = _transcriptor(palabras=True)
    try:
        for k in range(3):   # detrás del primero esperan 3 s: por debajo de COLA_ALCANCE_S
            tr.encolar("yo", _audio(1.5, (k + 1) / 100), float(k * 2))
        tr.listo.set()
        _terminar(tr)
    finally:
        tr.detener()
    assert len(m.llamadas) == 3 and all(_completo(kw, palabras=True) for kw in m.llamadas)
    assert tr.tramos_rapidos == 0 and tr.alcance is False


def test_con_whisper_beam_1_el_rapido_usa_1():
    tr, m, _ = _transcriptor(cfg={"whisper_beam": 1})
    try:
        _encolar_8_de_2s(tr)
        tr.listo.set()
        _terminar(tr)
    finally:
        tr.detener()
    assert all(_rapido(kw, beam=1) for kw in m.llamadas[:5]) and all(kw["beam_size"] == 1 for kw in m.llamadas)


def test_con_whisper_beam_3_el_rapido_se_queda_en_beam_rapido():
    tr, m, _ = _transcriptor(cfg={"whisper_beam": 3})
    try:
        _encolar_8_de_2s(tr)
        tr.listo.set()
        _terminar(tr)
    finally:
        tr.detener()
    assert all(_rapido(kw, beam=BEAM_RAPIDO) for kw in m.llamadas[:5]) and m.llamadas[-1]["beam_size"] == 3


# ------------------------------------------------------------------ reintento y tramos perdidos
class ModeloQueFalla(ModeloPorTramos):
    """Falla las primeras `fallos` llamadas (al llamar, no al iterar) y luego funciona."""
    def __init__(self, fallos):
        super().__init__()
        self.fallos = fallos

    def transcribe(self, audio, **kw):
        if self.fallos > 0:
            self.fallos -= 1
            self.llamadas.append(dict(kw, audio_s=audio.size / SR, alcance=self.tr.alcance))
            raise RuntimeError("memoria agotada (ficticia)")
        return super().transcribe(audio, **kw)


def test_un_fallo_se_repite_una_vez_en_rapido_y_el_texto_se_entrega():
    tr, m, emitidos = _transcriptor(ModeloQueFalla(1), palabras=True, listo=True)
    try:
        _uno_a_uno(tr, [("yo", 4, 0.07)])
    finally:
        _terminar(tr)
    assert len(m.llamadas) == 2
    assert _completo(m.llamadas[0], palabras=True)   # la primera pasada, sin cola, con la calidad completa
    assert _rapido(m.llamadas[1])                    # el reintento, en rápido
    assert emitidos == [("yo", 0.0, "frase 7")]
    assert tr.reintentos == 1 and tr.perdidos_s == 0 and tr.ultimo_fallo == "" and tr.error == ""
    assert tr.vacio() and tr.pendiente_s == 0


def test_un_modelo_que_falla_siempre_da_el_tramo_por_perdido_y_deja_la_contabilidad_limpia():
    tr, m, emitidos = _transcriptor(ModeloQueFalla(10 ** 6), listo=True)
    try:
        _uno_a_uno(tr, [("yo", 4, 0.07)])
    finally:
        _terminar(tr)
    assert len(m.llamadas) == 2 and emitidos == []     # una pasada y UN reintento, no más
    assert tr.reintentos == 1 and tr.perdidos_s == pytest.approx(4.0)
    assert tr.ultimo_fallo == "RuntimeError" and "memoria agotada (ficticia)" in tr.error
    assert tr.vacio() and tr.pendiente_s == 0 and tr.retraso_s == 0


def test_tras_perder_un_tramo_el_siguiente_se_procesa_con_normalidad():
    tr, m, emitidos = _transcriptor(ModeloQueFalla(2), listo=True)   # falla la pasada y el reintento del primer tramo
    try:
        _uno_a_uno(tr, [("yo", 4, 0.07), ("reunion", 3, 0.08)])
    finally:
        _terminar(tr)
    assert emitidos == [("reunion", 1.0, "frase 8")]
    assert len(m.llamadas) == 3 and _completo(m.llamadas[2])
    assert tr.perdidos_s == pytest.approx(4.0) and tr.reintentos == 1 and tr.vacio() and tr.pendiente_s == 0


def test_un_fallo_dentro_de_la_cola_no_deja_retraso_fantasma():
    tr, m, _ = _transcriptor(ModeloQueFalla(10 ** 6))
    try:
        for k in range(5):
            tr.encolar("yo", _audio(3, 0.1), float(k))
        tr.listo.set()
        _terminar(tr)
    finally:
        tr.detener()
    assert tr.vacio() and tr.pendiente_s == 0 and tr.retraso_s == 0 and tr.perdidos_s == pytest.approx(15.0)
    assert tr.alcance is False and len(m.llamadas) == 10   # dos llamadas (pasada + reintento) por tramo


# ------------------------------------------------------------------ rechazo del tope
class Exigente(ModeloPorTramos):
    """Como faster-whisper: con `max_new_tokens` el error salta al iterar."""
    def transcribe(self, audio, **kw):
        if "max_new_tokens" in kw:
            self.llamadas.append(dict(kw, audio_s=audio.size / SR, alcance=None))

            def falla():
                raise ValueError("The length of the prompt is 340 ... This exceeds the `max_length` of the Whisper model: 448.")
                yield
            return falla(), None
        return super().transcribe(audio, **kw)


def test_si_faster_whisper_rechaza_el_tope_se_repite_sin_el():
    tr, m, emitidos = _transcriptor(Exigente(), listo=True)
    try:
        _uno_a_uno(tr, [("yo", 2, 0.07)])
    finally:
        _terminar(tr)
    assert [("max_new_tokens" in kw) for kw in m.llamadas] == [True, False]
    assert emitidos == [("yo", 0.0, "frase 7")] and tr.error == ""
    assert tr.reintentos == 0 and tr.perdidos_s == 0     # no cuenta como fallo del tramo


def test_un_value_error_que_no_habla_de_max_length_cuenta_como_fallo_y_se_reintenta_en_rapido():
    class Otro(ModeloPorTramos):
        def __init__(self):
            super().__init__()
            self.n = 0

        def transcribe(self, audio, **kw):
            self.n += 1
            if self.n == 1:
                raise ValueError("otra cosa")
            return super().transcribe(audio, **kw)
    tr, m, emitidos = _transcriptor(Otro(), listo=True)
    try:
        _uno_a_uno(tr, [("yo", 2, 0.07)])
    finally:
        _terminar(tr)
    assert tr.reintentos == 1 and emitidos == [("yo", 0.0, "frase 7")] and _rapido(m.llamadas[0])


# ------------------------------------------------------------------ tokens del prompt
class TokenizadorFalso:
    """hf_tokenizer.encode(texto, add_special_tokens=False) -> objeto con .ids; `n` ids por cada texto."""
    def __init__(self, n):
        self.n, self.textos = n, []

    def encode(self, texto, add_special_tokens=True):
        assert add_special_tokens is False
        self.textos.append(texto)
        return SimpleNamespace(ids=list(range(self.n)))


def test_el_tope_que_llega_a_transcribe_respeta_el_tamano_real_del_prompt():
    m = ModeloPorTramos()
    m.hf_tokenizer = TokenizadorFalso(100)
    tr, _, _ = _transcriptor(m, listo=True)
    tr.vocabulario = ["SAP", "Fiori"]   # con vocabulario hay hotwords: otro texto que cuenta
    try:
        _uno_a_uno(tr, [("yo", 40, 0.01), ("yo", 3, 0.02)])
    finally:
        _terminar(tr)
    # 5 marcas + 100 de hotwords + 100 de prompt = 205 tokens; libres = 448 - 205 - 2 = 241
    assert m.llamadas[0]["max_new_tokens"] == 241 == tope_tokens(40, 205)
    assert m.llamadas[0]["max_new_tokens"] <= MAX_TOKENS_WHISPER - 205 - 2
    assert m.llamadas[1]["max_new_tokens"] == tope_tokens(3, 205) == 3 * TOKENS_POR_S + TOKENS_MARGEN   # el tramo corto manda la duración
    assert all(t.startswith(" ") for t in m.hf_tokenizer.textos)


def test_con_tokenizador_un_tramo_largo_lleva_tope_aunque_sin_el_no_lo_llevaria():
    m = ModeloPorTramos()
    m.hf_tokenizer = TokenizadorFalso(10)
    tr, _, _ = _transcriptor(m, listo=True)
    try:
        _uno_a_uno(tr, [("yo", 25, 0.01)])
    finally:
        _terminar(tr)
    assert tope_tokens(25) is None
    assert m.llamadas[0]["max_new_tokens"] == tope_tokens(25, 15) == 25 * TOKENS_POR_S + TOKENS_MARGEN


def test_un_prompt_enorme_se_cuenta_con_el_tope_de_faster_whisper_y_si_no_cabe_va_sin_tope():
    m = ModeloPorTramos()
    m.hf_tokenizer = TokenizadorFalso(10 ** 4)   # cada texto cuenta como mucho MAX_TOKENS_WHISPER // 2 - 1 = 223
    tr, _, _ = _transcriptor(m, listo=True)
    tr.vocabulario = ["SAP"]
    try:
        _uno_a_uno(tr, [("yo", 5, 0.01)])
    finally:
        _terminar(tr)
    # 5 + 223 + 223 = 451 > 448: no cabe nada
    assert "max_new_tokens" not in m.llamadas[0]


def test_si_el_tokenizador_falla_se_usa_el_tope_sin_prompt():
    class Roto:
        def encode(self, *a, **k):
            raise RuntimeError("tokenizador roto")
    m = ModeloPorTramos()
    m.hf_tokenizer = Roto()
    tr, _, _ = _transcriptor(m, listo=True)
    try:
        _uno_a_uno(tr, [("yo", 5, 0.01), ("yo", 40, 0.02)])
    finally:
        _terminar(tr)
    assert m.llamadas[0]["max_new_tokens"] == tope_tokens(5) and "max_new_tokens" not in m.llamadas[1]


# ------------------------------------------------------------------ idioma vigente en modo rápido
class ModeloDetecta(ModeloPorTramos):
    def __init__(self):
        super().__init__()
        self.detecciones = []   # (índice del tramo en curso, segundos de audio)

    def detect_language(self, audio=None, **kw):
        self.detecciones.append((len(self.llamadas), audio.size / SR))
        p = [("ca", 0.95), ("es", 0.03)]
        return p[0][0], p[0][1], p


def test_con_cola_una_fuente_no_vuelve_a_detectar_el_idioma_y_la_otra_detecta_por_su_cuenta():
    tr, m, _ = _transcriptor(ModeloDetecta(), auto=True)
    try:
        # 8 tramos de 3 s (24 s): los seis primeros van con cola ≥ COLA_ALCANCE_S, los dos últimos ya no
        for k, f in enumerate(["yo", "yo", "reunion", "yo", "reunion", "yo", "yo", "reunion"]):
            tr.encolar(f, _audio(3, (k + 1) / 100), float(k))
        tr.listo.set()
        _terminar(tr)
    finally:
        tr.detener()
    assert tr.tramos_rapidos == 6 and [kw["alcance"] for kw in m.llamadas][:6] == [True] * 6
    # en rápido solo detectan el primer tramo de cada fuente (0 «yo», 2 «reunion»); los dos últimos, ya sin cola, detectan cada uno
    assert [i for i, _s in m.detecciones] == [0, 2, 6, 7]
    assert [kw["language"] for kw in m.llamadas] == ["ca"] * 8   # los reutilizados usan el idioma detectado


def test_con_cola_un_idioma_detectado_hace_mas_de_idioma_vigente_s_no_se_reutiliza():
    tr, m, _ = _transcriptor(ModeloDetecta(), auto=True)
    tr._ultimo_idioma["yo"] = "es"
    tr._t_deteccion["yo"] = time.monotonic() - IDIOMA_VIGENTE_S - 1   # detectado hace demasiado
    try:
        for k in range(5):   # 5 tramos de 3 s: los tres primeros van en rápido
            tr.encolar("yo", _audio(3, (k + 1) / 100), float(k))
        tr.listo.set()
        _terminar(tr)
    finally:
        tr.detener()
    assert tr.tramos_rapidos == 3
    # el primero (rápido) detecta porque el vigente caducó; el 1 y el 2 reutilizan esa detección; el 3 y el 4, sin cola, detectan
    assert [i for i, _s in m.detecciones] == [0, 3, 4]
    assert [kw["language"] for kw in m.llamadas] == ["ca"] * 5


def test_sin_cola_se_detecta_el_idioma_en_cada_tramo_de_al_menos_2_s():
    tr, m, _ = _transcriptor(ModeloDetecta(), auto=True, listo=True)
    try:
        _uno_a_uno(tr, [("yo", 3, 0.01), ("yo", 3, 0.02), ("yo", 1, 0.03), ("reunion", 2, 0.04), ("yo", 3, 0.05)])
    finally:
        _terminar(tr)
    assert m.detecciones == [(0, 3.0), (1, 3.0), (3, 2.0), (4, 3.0)]   # el de 1 s no detecta
    assert [kw["language"] for kw in m.llamadas] == ["ca"] * 5          # el corto reutiliza el último idioma de su fuente
    assert tr.tramos_rapidos == 0


# ------------------------------------------------------------------ retraso_s y latencia_s
class ModeloBloqueado(ModeloPorTramos):
    def __init__(self):
        super().__init__()
        self.entro, self.suelta = threading.Event(), threading.Event()

    def transcribe(self, audio, **kw):
        self.entro.set()
        self.suelta.wait(5)
        return super().transcribe(audio, **kw)


def test_retraso_y_latencia_son_cero_sin_pendientes_y_el_retraso_crece_mientras_un_tramo_espera():
    tr, m, emitidos = _transcriptor(ModeloBloqueado(), listo=True)
    try:
        assert tr.retraso_s == 0 and tr.latencia_s is None
        tr.encolar("yo", _audio(2, 0.05), 0.0)
        assert m.entro.wait(5)
        time.sleep(0.05)
        r1 = tr.retraso_s
        assert r1 > 0 and tr.pendiente_s == pytest.approx(2.0) and not tr.vacio()
        time.sleep(0.05)
        assert tr.retraso_s > r1
        m.suelta.set()
        assert _hasta(lambda: tr.vacio())
    finally:
        m.suelta.set()
        _terminar(tr)
    assert tr.retraso_s == 0 and tr.latencia_s is not None and tr.latencia_s >= r1
    assert emitidos == [("yo", 0.0, "frase 5")]


def test_retraso_es_el_del_tramo_pendiente_mas_antiguo():
    tr, m, _ = _transcriptor(ModeloBloqueado(), listo=True)
    try:
        tr.encolar("yo", _audio(2, 0.05), 0.0)
        assert m.entro.wait(5)
        time.sleep(0.15)
        tr.encolar("reunion", _audio(2, 0.06), 1.0)
        assert tr.retraso_s >= 0.1   # no se reinicia al llegar otro tramo
    finally:
        m.suelta.set()
        _terminar(tr)


# ------------------------------------------------------------------ encolar sin modelo y tras detener
def test_encolar_con_estado_error_no_acumula_y_cuenta_como_perdido():
    tr = Transcriptor(CFG, lambda *a: None)
    tr.estado = "error"
    tr.encolar("yo", _audio(3), 0.0)
    tr.encolar("reunion", _audio(1.5), 1.0)
    assert tr.perdidos_s == pytest.approx(4.5) and tr.pendiente_s == 0
    assert tr._cola.empty() and tr.vacio() and tr.retraso_s == 0


def test_tras_detener_un_tramo_que_termina_tarde_no_entrega_texto():
    tr, m, emitidos = _transcriptor(ModeloBloqueado(), listo=True)
    try:
        tr.encolar("yo", _audio(2, 0.05), 0.0)
        assert m.entro.wait(5)
        tr._parar.set()   # lo que pone `detener()`, sin esperar al hilo
        m.suelta.set()
        tr._hilo.join(3)
        assert not tr._hilo.is_alive()
    finally:
        m.suelta.set()
        tr._parar.set()
    assert emitidos == [] and tr.vacio() and tr.pendiente_s == 0
