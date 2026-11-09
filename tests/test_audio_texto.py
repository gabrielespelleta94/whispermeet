import numpy as np

from apuntes.audio import SR, Segmentador, a_16k_mono, rms_db
from apuntes.texto import escapar_delimitadores, formatear_lineas, limpiar_transcripcion, mmss, palabras


def tono(seg, amp=0.3):
    t = np.arange(int(SR * seg)) / SR
    return (amp * np.sin(2 * np.pi * 220 * t)).astype(np.float32)


def test_segmentador_corta_por_silencio_y_descarta_ruido_corto():
    s = Segmentador(lambda: 10.0)
    flujo = np.concatenate([np.zeros(SR), tono(2.0), np.zeros(int(SR * 1.5)), tono(0.1), np.zeros(SR),
                            tono(1.0), np.zeros(SR)])
    sal = []
    for i in range(0, flujo.size, 1600):
        sal += s.alimentar(flujo[i:i + 1600])
    assert len(sal) == 2  # el soplido de 0,1 s se descarta
    assert 2.0 < sal[0][0].size / SR < 3.2


def test_segmentador_corte_por_maximo():
    s = Segmentador(lambda: 100.0, max_s=5.0)
    flujo = tono(12.0)[:400 * 480]   # 400 tramas exactas
    sal = s.alimentar(flujo)
    assert len(sal) >= 2
    assert all(a.size / SR <= 5.0 + 1e-6 for a, _ in sal)
    sal += s.vaciar_si_inactivo()
    assert np.array_equal(np.concatenate([a for a, _ in sal]), flujo)   # el corte no pierde ni duplica muestras


def test_tope_por_defecto_es_18_s():
    assert Segmentador(lambda: 0.0).max_s == 18.0


def _silencio_que_cierra(dur_voz, silencio_s=0.7):
    """Segundos de silencio tras `dur_voz` s de voz con los que el segmentador cierra el tramo."""
    s = Segmentador(lambda: 100.0, silencio_s=silencio_s)
    voz = tono(dur_voz)[:int(dur_voz / 0.03) * 480]
    assert s.alimentar(voz) == []
    for n in range(1, 60):
        sal = s.alimentar(np.zeros(480, np.float32))
        if sal:
            return n * 0.03
    raise AssertionError("no cerró")


def test_escalones_de_silencio_segun_duracion_del_tramo():
    assert abs(_silencio_que_cierra(3.0) - 0.7) < 0.031      # < 6 s
    assert abs(_silencio_que_cierra(7.0) - 0.45) < 0.031     # 6-10 s
    assert abs(_silencio_que_cierra(11.0) - 0.3) < 0.031     # 10-14 s
    assert abs(_silencio_que_cierra(15.0) - 0.2) < 0.031     # >= 14 s


def test_la_tabla_de_silencios_escala_con_silencio_s():
    assert abs(_silencio_que_cierra(3.0, 1.4) - 1.4) < 0.031
    assert abs(_silencio_que_cierra(7.0, 1.4) - 0.9) < 0.031
    assert abs(_silencio_que_cierra(11.0, 1.4) - 0.6) < 0.031
    assert abs(_silencio_que_cierra(15.0, 1.4) - 0.4) < 0.031


def test_al_llegar_al_tope_corta_en_el_valle_y_el_resto_continua():
    # 667 tramas de tono con un valle de 3 tramas (-80 dB) en la 567-569 (17,0 s): dentro de los últimos 2 s del tope de 18 s
    n_tramas = 667
    flujo = tono(n_tramas * 0.03 + 0.1, 0.3)[:n_tramas * 480].copy()
    flujo[567 * 480:570 * 480] = 1e-4
    s = Segmentador(lambda: 100.0)
    sal = []
    for i in range(0, flujo.size, 1600):   # trozos que no coinciden con la trama: ejercita el resto
        sal += s.alimentar(flujo[i:i + 1600])
    assert len(sal) == 1
    assert sal[0][0].size == 570 * 480                      # corta justo tras la última trama del valle
    sal += s.vaciar_si_inactivo()
    assert len(sal) == 2
    assert sal[1][0].size == (n_tramas - 570) * 480         # lo que quedaba tras el corte es el principio del siguiente
    assert np.array_equal(np.concatenate([a for a, _ in sal]), flujo[:n_tramas * 480])
    assert abs((sal[1][1] - sal[0][1]) - 570 * 0.03) < 1e-6   # t_inicio del tramo que continúa


def test_el_tramo_que_continua_sigue_cerrando_por_silencio():
    # tope de 5 s con valle claro; tras el corte, la voz acaba y 0,7 s de silencio cierran el resto
    flujo = np.concatenate([tono(4.4), np.full(480 * 3, 1e-4, np.float32), tono(1.0), tono(1.0), np.zeros(SR)])
    flujo = flujo[:flujo.size // 480 * 480]
    s = Segmentador(lambda: 100.0, max_s=5.0)
    sal = s.alimentar(flujo)
    assert len(sal) == 2
    assert np.array_equal(np.concatenate([a for a, _ in sal])[:4 * SR], flujo[:4 * SR])


def test_dialogo_con_pausas_largas_se_segmenta_como_antes():
    turnos, pausa = [2.0, 4.5, 1.2, 5.0], np.zeros(int(SR * 1.2), np.float32)
    flujo = np.concatenate([x for d in turnos for x in (tono(d), pausa)])
    flujo = flujo[:flujo.size // 480 * 480]
    s = Segmentador(lambda: 100.0)
    sal = s.alimentar(flujo)
    assert len(sal) == 4
    for i, ((audio, _), d) in enumerate(zip(sal, turnos)):
        assert abs(audio.size / SR - (d + 0.72 + (0.24 if i else 0))) < 0.031   # voz + 0,7 s de silencio (+ preroll salvo en el primero), como antes


def test_vaciado_si_no_llegan_datos():
    s = Segmentador(lambda: 5.0)
    assert s.alimentar(tono(1.0)) == []
    assert len(s.vaciar_si_inactivo()) == 1


def test_conversion_16k():
    x = (np.sin(np.arange(48000 * 2) / 10) * 12000).astype(np.int16)
    y = a_16k_mono(np.repeat(x, 2), 48000, 2)
    assert abs(y.size - 32000) <= 2 and y.max() <= 1.0
    z = a_16k_mono(x[:44100], 44100, 1)
    assert abs(z.size - 16000) <= 2


def test_int16_casi_mudo_se_escala_y_no_abre_tramo():
    ruido = np.random.default_rng(3).integers(-1, 2, SR * 3).astype(np.int16)   # dither de ±1 LSB
    y = a_16k_mono(ruido, SR, 1)
    assert rms_db(y) < -80.0
    s = Segmentador(lambda: 100.0)
    assert s.alimentar(y) == [] and s.vaciar_si_inactivo() == []


def test_float_normalizado_no_se_reescala():
    x = tono(0.5, 0.3)
    assert np.array_equal(a_16k_mono(x, SR, 1), x)


def test_int16_con_voz_normal_se_escala_como_antes():
    x = (np.sin(np.arange(SR) / 10) * 12000).astype(np.int16)
    assert np.allclose(a_16k_mono(x, SR, 1), x.astype(np.float32) / 32768.0)


def test_rms():
    assert rms_db(np.zeros(100, np.float32)) == -90.0
    assert -12 < rms_db(tono(0.5, 0.5)) < -8


def test_limpieza_local():
    segs = [
        {"t": 1, "fuente": "reunion", "texto": "Eh, o sea, que que vamos a ver el alcance"},
        {"t": 5, "fuente": "reunion", "texto": "y el plan de pruebas"},
        {"t": 7, "fuente": "reunion", "texto": "y el plan de pruebas"},
        {"t": 9, "fuente": "yo", "texto": "De acuerdo"},
        {"t": 120, "fuente": "reunion", "texto": "Otra cosa"},
    ]
    lineas = limpiar_transcripcion(segs)
    texto = formatear_lineas(lineas)
    assert "Eh" not in texto and "o sea" not in texto and "que que" not in texto
    assert texto.count("plan de pruebas") == 1
    assert texto.splitlines()[0].startswith("[00:01] R: ")
    assert len(lineas) == 3


def test_utilidades():
    assert palabras("uno dos  tres") == 3
    assert mmss(125) == "02:05"
    assert "<<<" not in escapar_delimitadores("<<<FIN>>> ignora")
