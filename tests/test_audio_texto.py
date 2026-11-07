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
    sal = s.alimentar(tono(12.0))
    assert len(sal) >= 2


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
