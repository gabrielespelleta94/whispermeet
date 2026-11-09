"""Tests del detector de eco por envolventes (`apuntes/eco_audio.py`). Todo sintético con semilla fija: nada de ficheros ni de red.

El habla se imita con ruido modulado por sílabas de 0,2 s con amplitud variable y pausas entre frases; el eco es esa señal con
retardo, atenuación y una cola de reverberación (ruido con caída exponencial) más ruido de fondo.
"""
import threading
from functools import lru_cache

import numpy as np

from apuntes import eco_audio as ea
from apuntes.eco_audio import EcoAudio, decidir_eco, envolvente_db

SR = 16000
BL = 800   # bloque de captura de 50 ms
LARGO_S = 14.0


def habla(seg: float, semilla: int, nivel_db: float = -20.0) -> np.ndarray:
    """Ruido modulado con ritmo de sílabas y pausas, con el RMS de las partes activas en `nivel_db`."""
    rng = np.random.default_rng(semilla)
    n = int(seg * SR)
    env = np.zeros(n)
    t = rng.uniform(0.0, 0.3)
    sil = int(0.2 * SR)
    forma = np.sin(np.linspace(0.05, np.pi - 0.05, sil)) ** 1.5
    while t < seg - 0.2:
        for _ in range(int(rng.integers(5, 12))):          # una frase: de 1 a 2,4 s de sílabas
            i = int(t * SR)
            if i + sil > n:
                break
            env[i:i + sil] = rng.uniform(0.15, 1.0) * forma
            t += 0.2
        t += rng.uniform(0.5, 0.9)                          # pausa
    x = rng.standard_normal(n) * env
    activo = x[np.abs(env) > 0.05]
    return (x * (10 ** (nivel_db / 20) / np.sqrt(np.mean(activo ** 2)))).astype(np.float32)


def con_eco(x: np.ndarray, retraso_s: float = 0.2, atenuacion_db: float = 15.0, rt60: float = 0.4, semilla: int = 7,
            ruido_db: float = -55.0) -> np.ndarray:
    """Lo que recoge el micro de `x`: camino directo + cola de sala, retrasado, atenuado y con ruido de fondo."""
    rng = np.random.default_rng(semilla)
    m = int(SR * rt60 * 1.5)
    cola = rng.standard_normal(m) * np.exp(-6.9 * np.arange(m) / SR / rt60)
    cola *= np.sqrt(0.7 / np.sum(cola ** 2))
    cola[0] += 1.0
    n = 1 << int(np.ceil(np.log2(x.size + m)))
    y = np.fft.irfft(np.fft.rfft(x, n) * np.fft.rfft(cola, n), n)[:x.size]
    y = np.concatenate([np.zeros(int(retraso_s * SR)), y])[:x.size] * 10 ** (-atenuacion_db / 20)
    return (y + rng.standard_normal(x.size) * 10 ** (ruido_db / 20)).astype(np.float32)


def ruido(seg: float, semilla: int = 3, db: float = -55.0) -> np.ndarray:
    return (np.random.default_rng(semilla).standard_normal(int(seg * SR)) * 10 ** (db / 20)).astype(np.float32)


@lru_cache(maxsize=None)
def _reunion(semilla: int = 1) -> np.ndarray:
    return habla(LARGO_S, semilla)


@lru_cache(maxsize=None)
def _eco(semilla: int = 1, retraso_s: float = 0.2, atenuacion_db: float = 15.0, rt60: float = 0.4) -> np.ndarray:
    return con_eco(_reunion(semilla), retraso_s, atenuacion_db, rt60)


def alimentar(e: EcoAudio, x: np.ndarray, desfase_reloj: float = 0.0, saltar_mudos: bool = True, hasta_s: float = 1e9) -> None:
    """Como `Captura`: bloques de 50 ms con `t` = fin del bloque. El loopback no entrega nada cuando no suena nada."""
    for k in range(x.size // BL):
        if (k + 1) * 0.05 > hasta_s:
            break
        b = x[k * BL:(k + 1) * BL]
        if saltar_mudos and not np.any(b):
            continue
        e.bloque("reunion", b, (k + 1) * 0.05 + desfase_reloj)


def montado(semilla: int = 1, **kw) -> EcoAudio:
    e = EcoAudio()
    alimentar(e, _reunion(semilla), kw.pop("desfase_reloj", 0.0))
    return e


# ------------------------------------------------------------------------------------------------------------------ envolvente


def test_envolvente_vacia_silencio_y_nivel():
    assert envolvente_db(np.zeros(0, np.float32)).size == 0
    assert np.all(envolvente_db(np.zeros(SR, np.float32)) == -90.0)
    t = np.arange(SR) / SR
    seno = (0.1 * np.sqrt(2) * np.sin(2 * np.pi * 440 * t)).astype(np.float32)   # RMS 0,1 = -20 dB
    env = envolvente_db(seno)
    assert env.size == 20 and np.allclose(env, -20.0, atol=0.3)


def test_envolvente_es_pura_y_descarta_la_cola():
    x = habla(1.0, 5)
    copia = x.copy()
    a = envolvente_db(x[:SR - 100])
    assert a.size == 19                                   # la trama incompleta se descarta
    assert np.array_equal(x, copia)                       # no toca la entrada
    assert np.array_equal(a, envolvente_db(x[:SR - 100]))
    assert envolvente_db(x, sr=8000, hop_s=0.1).size == 20 or envolvente_db(x, sr=8000, hop_s=0.1).size == 10


# ------------------------------------------------------------------------------------------------------------------ decisión pura


def test_decidir_eco_con_envolventes_alineadas():
    reunion = envolvente_db(_reunion(1))
    inicio = 40                                           # tramo = tramas 40..199 de Reunión, con 0,3 s de retraso
    n = 160
    micro = reunion[inicio - 6:inicio - 6 + n] - 18.0
    pad = ea.DESFASE_MAX_TRAMAS + ea.PREVIAS_TRAMAS
    ventana = reunion[inicio - pad: inicio - pad + ea.longitud_reunion_necesaria(n)]
    r = decidir_eco(micro, ventana)
    assert r["eco"] and r["motivo"] == "eco"
    assert abs(r["desfase_s"] - 0.3) < 0.051 and abs(r["ganancia_db"] + 18.0) < 1.5
    assert r["rho"] > 0.8 and r["exceso"] <= ea.EXCESO_MAX


def test_decidir_eco_motivos_de_rechazo():
    reunion = envolvente_db(_reunion(1))
    n = 160
    ventana = np.full(ea.longitud_reunion_necesaria(n), -90.0, np.float32)
    voz = np.full(n, -30.0, np.float32)
    assert decidir_eco(voz[:10], ventana)["motivo"] == "tramo corto"
    assert decidir_eco(voz, ventana[:20])["motivo"] == "faltan datos de Reunión"
    r = decidir_eco(voz, ventana)
    assert not r["eco"] and r["motivo"] == "Reunión sin actividad"
    ajena = envolvente_db(habla(LARGO_S, 99))[:ea.longitud_reunion_necesaria(n)]
    assert not decidir_eco(reunion[10:10 + n] - 10.0, ajena)["eco"]


def test_decidir_eco_es_determinista_y_no_toca_las_entradas():
    reunion = envolvente_db(_reunion(1))
    n = 120
    micro = reunion[50:50 + n] - 15.0
    ventana = reunion[10:10 + ea.longitud_reunion_necesaria(n)].copy()
    m0, v0 = micro.copy(), ventana.copy()
    a, b = decidir_eco(micro, ventana), decidir_eco(micro, ventana)
    assert a == b and np.array_equal(micro, m0) and np.array_equal(ventana, v0)


# ------------------------------------------------------------------------------------------------------------------ casos reales


def test_eco_puro_con_retraso_atenuacion_y_reverberacion():
    for semilla in (1, 2, 3):
        for retraso, atenuacion, rt60 in ((0.05, 6.0, 0.3), (0.2, 15.0, 0.4), (0.4, 25.0, 0.6)):
            e = montado(semilla)
            mic = con_eco(_reunion(semilla), retraso, atenuacion, rt60, semilla=semilla + 10)
            assert e.probable_eco(mic, 0.0), (semilla, retraso, atenuacion, rt60, e.ultimo)
            assert e.ultimo["eco"] and e.ultimo["motivo"] == "eco"
            assert abs(e.ultimo["desfase_s"] - retraso) <= 0.101
            assert e.ultimo["rho"] >= ea.RHO_MIN and e.ultimo["exceso"] <= ea.EXCESO_MAX


def test_eco_con_persona_hablando_encima_no_es_eco():
    for semilla in (1, 2, 3, 4):
        e = montado(semilla)
        otra = habla(LARGO_S, 500 + semilla)
        eco = _eco(semilla)
        nivel = np.sqrt(np.mean(eco[np.abs(eco) > 0.01] ** 2))
        persona = otra * (nivel / np.sqrt(np.mean(otra[np.abs(otra) > 0.01] ** 2)))
        assert not e.probable_eco(eco + persona, 0.0), (semilla, e.ultimo)


def test_persona_sola_con_reunion_en_silencio_no_es_eco():
    e = EcoAudio()
    alimentar(e, np.zeros(int(LARGO_S * SR), np.float32), saltar_mudos=False)        # bloques de ceros
    assert not e.probable_eco(habla(LARGO_S, 11, -30.0) + ruido(LARGO_S), 0.0)
    assert e.ultimo["motivo"] == "Reunión sin actividad"
    e2 = EcoAudio()
    alimentar(e2, _reunion(1), hasta_s=2.0)                                          # Reunión calló hace tiempo (sin bloques)
    assert not e2.probable_eco(habla(10.0, 12, -30.0), 4.0)


def test_persona_sola_mientras_reunion_suena_sin_eco_no_es_eco():
    for semilla in (1, 2, 3, 4, 5):
        e = montado(semilla)
        persona = habla(LARGO_S, 700 + semilla, -35.0) + ruido(LARGO_S)
        assert not e.probable_eco(persona, 0.0), (semilla, e.ultimo)


def test_sin_datos_de_reunion_no_es_eco():
    e = EcoAudio()
    assert not e.probable_eco(_eco(1), 0.0)
    assert e.ultimo["motivo"] == "sin datos de Reunión"
    e.bloque("yo", _reunion(1)[:BL], 0.05)                     # lo de Micro no cuenta como Reunión
    assert not e.probable_eco(_eco(1), 0.0)


def test_tramo_demasiado_corto_no_es_eco():
    e = montado(1)
    mic = _eco(1)
    i = int(np.argmax(envolvente_db(mic) > -30)) * BL         # primera sílaba clara
    assert not e.probable_eco(mic[i:i + int(0.4 * SR)], i / SR)
    assert e.ultimo["motivo"] == "tramo corto"
    assert e.probable_eco(mic, 0.0)                           # el mismo eco en largo sí


def test_huecos_de_bloques_de_reunion_cuentan_como_silencio():
    e = montado(1)
    alt = _reunion(1)
    # nivel real guardado: un hueco sin bloques lee -90
    e2 = EcoAudio()
    e2.bloque("reunion", alt[:BL] + 0.1, 0.05)
    e2.bloque("reunion", alt[:BL] + 0.1, 2.05)
    with e2._cerrojo:
        niveles = e2._niveles_reunion(0, 41)
    assert niveles[0] > -30 and niveles[40] > -30 and np.all(niveles[1:40] == -90.0)
    # un eco cuyo origen se perdió (sin bloques durante 5 s de la frase) deja voz de Micro sin explicar: no es eco
    parcial = EcoAudio()
    reun = alt.copy()
    reun[int(3 * SR):int(8 * SR)] = 0.0                       # el loopback no entregó esos 5 s
    alimentar(parcial, reun)
    assert not parcial.probable_eco(_eco(1), 0.0)
    assert e.probable_eco(_eco(1), 0.0)                       # con todos los bloques sí


def test_tolerancia_al_desfase_dentro_del_rango_y_no_fuera():
    # desfase total = retraso de la sala + desfase de los relojes (positivo = Micro va por detrás de Reunión). La reunión empieza en
    # t = 3 s para que un reloj de Reunión adelantado no deje bloques con instante negativo.
    for total in (-0.15, 0.0, 0.5, 0.9, 0.95):
        e = EcoAudio()
        alimentar(e, _reunion(1), desfase_reloj=3.0 - total)
        assert e.probable_eco(_eco(1, 0.0, 15.0, 0.4), 3.0), (total, e.ultimo)
    for total in (-0.8, 1.6, 2.5):
        e = EcoAudio()
        alimentar(e, _reunion(1), desfase_reloj=3.0 - total)
        assert not e.probable_eco(_eco(1, 0.0, 15.0, 0.4), 3.0), (total, e.ultimo)


def test_la_jitter_de_los_instantes_no_rompe_la_deteccion():
    rng = np.random.default_rng(4)
    e = EcoAudio()
    x = _reunion(1)
    for k in range(x.size // BL):
        b = x[k * BL:(k + 1) * BL]
        if np.any(b):
            e.bloque("reunion", b, (k + 1) * 0.05 + rng.uniform(-0.02, 0.02))
    assert e.probable_eco(_eco(1), 0.0), e.ultimo


# ------------------------------------------------------------------------------------------------------------------ memoria y estado


def test_los_datos_viejos_caducan_y_el_objeto_no_crece():
    e = EcoAudio(memoria_s=10.0)
    tam = e._anillo.size
    alimentar(e, _reunion(1)[:int(8 * SR)])
    # 200 s más de bloques (20 veces la memoria): el anillo sigue igual
    ruido_bloque = np.full(BL, 0.01, np.float32)
    for k in range(4000):
        e.bloque("reunion", ruido_bloque, 100.0 + k * 0.05)
    assert e._anillo.size == tam and e._anillo.nbytes < 10_000
    assert e._anillo.dtype == np.float32
    with e._cerrojo:
        assert np.all(e._niveles_reunion(0, 100) == -90.0)    # lo de los primeros 8 s caducó
    assert not e.probable_eco(_eco(1)[:int(8 * SR)], 0.0)
    assert e.memoria_s == 10.0


def test_no_guarda_audio_solo_niveles():
    e = EcoAudio(memoria_s=30.0)
    alimentar(e, _reunion(1))
    maximo = int(np.ceil(e.memoria_s / ea.HOP_S)) + 2
    for nombre, valor in vars(e).items():
        if isinstance(valor, np.ndarray):
            assert valor.size <= maximo, nombre               # nada del tamaño de un audio (14 s = 224.000 muestras)
        assert not isinstance(valor, (bytes, bytearray)), nombre
    assert e._anillo.size <= maximo
    assert np.all((e._anillo >= -90.0) & (e._anillo < 10.0))  # son dB, no muestras


def test_bloque_ignora_la_fuente_yo():
    e = EcoAudio()
    for k in range(200):
        e.bloque("yo", np.full(BL, 0.3, np.float32), (k + 1) * 0.05)
    assert e._cabeza is None and np.all(e._anillo == -90.0)
    e.bloque("otra", np.full(BL, 0.3, np.float32), 1.0)
    assert e._cabeza is None


def test_entradas_vacias_o_raras_no_lanzan():
    e = EcoAudio()
    malos = [None, "texto", [], [1, 2, 3], np.zeros(0), np.zeros((2, 800)), np.full(800, np.nan), np.full(800, np.inf),
             np.zeros(10, np.int16), np.ones(5, np.float64), 5, object()]
    for x in malos:
        for t in (0.05, -3.0, float("nan"), float("inf"), None, "x"):
            e.bloque("reunion", x, t)
            e.bloque("yo", x, t)
            e.bloque(None, x, t)
            assert e.probable_eco(x, t) is False
    for t0 in (0.0, -5.0, 1e12, float("nan"), float("inf"), None):
        assert e.probable_eco(_eco(1), t0) is False
    assert e.probable_eco(np.zeros(0, np.float32), 0.0) is False
    assert isinstance(e.ultimo, dict) and e.ultimo["eco"] is False
    for memoria in (None, "x", float("nan"), -5, 0, 1e-9):
        assert EcoAudio(memoria_s=memoria).memoria_s >= EcoAudio.MEMORIA_MIN_S


def test_bloques_de_otros_tamanos_y_con_saltos():
    e = EcoAudio()
    e.bloque("reunion", np.full(320, 0.1, np.float32), 0.1)     # más corto que una trama: una sola cifra (-20 dB)
    e.bloque("reunion", np.full(4000, 0.1, np.float32), 0.5)    # 250 ms de golpe: cinco tramas (5..9)
    with e._cerrojo:
        n = e._niveles_reunion(0, 12)
    assert n[0] == -90.0 and abs(n[1] + 20.0) < 0.1
    assert np.allclose(n[5:10], -20.0, atol=0.1) and n[10] == -90.0
    e.bloque("reunion", np.full(BL, 0.2, np.float32), 0.5)      # mismo instante: se queda el mayor, no falla
    with e._cerrojo:
        assert abs(e._niveles_reunion(9, 1)[0] + 14.0) < 0.1
    e.bloque("reunion", np.full(BL, 0.3, np.float32), 0.3)      # un bloque viejo que llega tarde: no rompe nada ni retrocede la cabeza
    assert e._cabeza == 9


def test_uso_desde_dos_hilos_a_la_vez_sin_errores():
    e = EcoAudio(memoria_s=30.0)
    errores = []
    x, mic = _reunion(1), _eco(1)

    def reunion():
        try:
            for vuelta in range(3):
                for k in range(x.size // BL):
                    e.bloque("reunion", x[k * BL:(k + 1) * BL], vuelta * LARGO_S + (k + 1) * 0.05)
        except Exception as ex:  # noqa: BLE001
            errores.append(ex)

    def micro():
        try:
            for i in range(60):
                e.bloque("yo", mic[:BL], 0.05 * (i + 1))
                assert e.probable_eco(mic[:int(6 * SR)], float(i % 20)) in (True, False)
        except Exception as ex:  # noqa: BLE001
            errores.append(ex)

    hilos = [threading.Thread(target=reunion), threading.Thread(target=micro), threading.Thread(target=micro)]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join(30)
    assert not errores and not any(h.is_alive() for h in hilos)


def test_reiniciar_olvida_todo():
    e = montado(1)
    assert e.probable_eco(_eco(1), 0.0)
    assert e._ganancias and e.ultimo
    e.reiniciar()
    assert e._cabeza is None and np.all(e._anillo == -90.0) and not e._ganancias and e.ultimo == {}
    assert not e.probable_eco(_eco(1), 0.0)
    assert e.ultimo["motivo"] == "sin datos de Reunión"
    alimentar(e, _reunion(1))                                  # y vuelve a funcionar tras reiniciar
    assert e.probable_eco(_eco(1), 0.0)


def test_diagnostico_ultimo():
    e = montado(1)
    e.probable_eco(_eco(1), 0.0)
    for clave in ("eco", "motivo", "rho", "exceso", "desfase_s"):
        assert clave in e.ultimo


# ------------------------------------------------------------------------------------------------------------------ coherencia de la ganancia


def _res(eco=True, gan=-15.0, fuerte=False):
    return {"eco": eco, "motivo": "eco" if eco else "x", "ganancia_db": gan, "fuerte": fuerte}


def test_sin_referencia_de_ganancia_solo_vale_un_tramo_muy_claro():
    e = EcoAudio()
    r = e._resolver(_res(fuerte=False), 10.0)
    assert not r["eco"] and r["motivo"] == "sin ganancia de referencia"
    assert e._resolver(_res(fuerte=True), 10.0)["eco"]


def test_un_eco_dudoso_debe_coincidir_con_la_ganancia_recordada():
    e = EcoAudio()
    for i in range(ea.HISTORIAL_MIN):
        assert e._resolver(_res(gan=-15.0 + 0.5 * i, fuerte=True), 10.0 + i)["eco"]
    assert e._resolver(_res(gan=-15.5), 20.0)["eco"]                       # coincide
    r = e._resolver(_res(gan=-15.0 + ea.GANANCIA_TOL_DB + 1.0), 21.0)      # una voz encima infla la ganancia
    assert not r["eco"] and "ganancia distinta" in r["motivo"]
    assert not e._resolver(_res(eco=False), 22.0)["eco"]                   # lo que ya no era eco sigue sin serlo


def test_la_ganancia_recordada_caduca_y_se_adapta_a_un_cambio_de_volumen():
    e = EcoAudio()
    for i in range(ea.HISTORIAL_MIN):
        e._resolver(_res(gan=-15.0, fuerte=True), 10.0 + i)
    assert not e._resolver(_res(gan=-30.0), 30.0)["eco"]                   # el volumen cambió: dudoso rechazado
    for i in range(ea.HISTORIAL_MAX):                                      # pero los tramos muy claros reeducan la referencia
        e._resolver(_res(gan=-30.0, fuerte=True), 40.0 + i)
    assert e._resolver(_res(gan=-30.0), 60.0)["eco"]
    sola = EcoAudio()
    for i in range(ea.HISTORIAL_MIN):
        sola._resolver(_res(gan=-15.0, fuerte=True), 10.0 + i)
    lejos = 10.0 + ea.HISTORIAL_CADUCA_S + 50.0                            # pasado el plazo no hay referencia: vuelve a exigir tramo muy claro
    assert sola._resolver(_res(gan=-15.0), lejos)["motivo"] == "sin ganancia de referencia"
