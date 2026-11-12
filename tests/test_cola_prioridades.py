"""Cola con prioridades del transcriptor (normales, rezagados, aplazados): el contrato que arregló el retraso de 561 s en una reunión real.
Deterministas: reloj falso (el módulo `time` que ve `apuntes.transcripcion`) y `_segmentos` doblado, sin Whisper ni hilo (salvo el último
test). Se llama a `encolar`, a `_tomar()` con `_lock` cogido y a `_procesar(...)`, decidiendo `rapido` como lo hace `_bucle`."""
from __future__ import annotations

import threading
import time

import numpy as np
import pytest

from apuntes import transcripcion as T
from apuntes.transcripcion import (APLAZADO, APLAZADO_TOPE_S, BEAM_RAPIDO, COLA_ALCANCE_S, NORMAL, REZAGADO, REZAGADO_TOPE_S, RETRASO_TOPE_S,
                                   SR_WHISPER, TEMPERATURAS_RAPIDO, Transcriptor)

CFG = {"idioma": "es", "whisper_beam": 5, "whisper_modelo": "x", "whisper_hilos": 1, "whisper_palabras": True}


class Reloj:
    """Sustituye al módulo `time` de la transcripción: el módulo solo usa `monotonic`, `perf_counter` y `process_time` (aquí la CPU del proceso
    avanza igual que el reloj: un solo núcleo ocupado todo el cálculo)."""
    def __init__(self):
        self.t = 0.0

    def monotonic(self):
        return self.t

    perf_counter = process_time = monotonic


@pytest.fixture
def reloj(monkeypatch):
    r = Reloj()
    monkeypatch.setattr(T, "time", r)
    return r


def _audio(seg: float) -> np.ndarray:
    """Solo importa el tamaño: no ocupa memoria aunque dure minutos."""
    return np.broadcast_to(np.float32(0), (int(seg * SR_WHISPER),))


class Banco:
    """Un transcriptor sin Whisper: `_segmentos` devuelve un texto distinto por tramo y avanza el reloj lo que costaría transcribirlo
    (`capacidad` = segundos de audio por segundo de cálculo; None = sin coste). Con `modelo` se usa el `_segmentos` real contra ese doble."""
    def __init__(self, reloj, capacidad=None, modelo=None):
        self.reloj, self.capacidad = reloj, capacidad
        self.entregados, self.llamadas = [], []
        self.tr = Transcriptor(CFG, lambda f, t, x, **kw: self.entregados.append((f, t, x)))
        self.tr.estado = "listo"
        if modelo is not None:
            self.tr._modelo = modelo
        else:
            self.tr._segmentos = self._segmentos

    def _segmentos(self, audio, fuente, rapido=False, solo_local=False):
        self.llamadas.append((fuente, audio.size / SR_WHISPER, rapido))
        if self.capacidad:
            self.reloj.t += (audio.size / SR_WHISPER) / self.capacidad
        return [(0.0, f"Revisamos la partida {len(self.llamadas)} del presupuesto.", [])]

    def en(self, t, fuente, seg, aplazar=False, t0=None):
        """Encola en el instante `t` (el reloj queda como estaba)."""
        ahora, self.reloj.t = self.reloj.t, t
        self.tr.encolar(fuente, _audio(seg), t if t0 is None else t0, aplazar=aplazar)
        self.reloj.t = ahora

    def tomar(self):
        """Toma el próximo tramo (fuente, audio, t0, clase, instante) o None; deja `_en_curso` puesto."""
        with self.tr._lock:
            return self.tr._tomar()

    def servir(self):
        """Toma y procesa el próximo tramo decidiendo `rapido` como `_bucle`. -> (fuente, clase, t0, rapido) o None."""
        tr = self.tr
        with tr._lock:
            tramo = tr._tomar()
            if tramo is None:
                return None
            fuente, audio, t0, clase, instante = tramo
            dur = audio.size / SR_WHISPER
            en_cola_s = tr._pendiente_s - dur - (0.0 if clase == APLAZADO else tr._aplazado_s)
        rapido = clase == REZAGADO or en_cola_s >= COLA_ALCANCE_S
        tr._procesar(fuente, audio, t0, rapido, clase, instante)
        return fuente, clase, t0, rapido

    def servir_todo(self):
        salida = []
        while True:
            s = self.servir()
            if s is None:
                return salida
            salida.append(s)


def _limpio(tr):
    """Contabilidad a cero, mirando también los valores internos (las propiedades recortan a 0 un descuadre negativo)."""
    assert tr._pendiente_s == pytest.approx(0, abs=1e-6) and tr._rezagado_s == pytest.approx(0, abs=1e-6)
    assert tr._aplazado_s == pytest.approx(0, abs=1e-6)
    assert tr.pendiente_s == 0 and tr.rezagado_s == 0 and tr.aplazado_s == 0 and tr.vacio()
    assert not tr._normales and not tr._rezagados and not tr._aplazados and tr._en_curso is None


# ------------------------------------------------------------------ 1. orden entre normales
def test_1_entre_normales_reunion_antes_que_micro_y_dentro_de_cada_fuente_por_orden_de_llegada(reloj):
    b = Banco(reloj)
    llegadas = [("yo", 0.0), ("reunion", 1.0), ("yo", 2.0), ("reunion", 3.0), ("yo", 4.0), ("reunion", 5.0)]
    for i, (f, t0) in enumerate(llegadas):
        b.en(float(i), f, 2, t0=t0)   # el micro llega antes, pero lo que dicen los demás se lee primero
    assert [(f, c, t0) for f, c, t0, _r in b.servir_todo()] == [
        ("reunion", NORMAL, 1.0), ("reunion", NORMAL, 3.0), ("reunion", NORMAL, 5.0),
        ("yo", NORMAL, 0.0), ("yo", NORMAL, 2.0), ("yo", NORMAL, 4.0)]
    _limpio(b.tr)


def test_1_un_reunion_que_llega_despues_se_cuela_por_delante_de_los_micro_que_esperan(reloj):
    b = Banco(reloj)
    b.en(0.0, "yo", 2, t0=0.0)
    b.en(1.0, "yo", 2, t0=1.0)
    assert b.servir()[:3] == ("yo", NORMAL, 0.0)
    b.en(2.0, "reunion", 2, t0=2.0)
    assert [(f, t0) for f, _c, t0, _r in b.servir_todo()] == [("reunion", 2.0), ("yo", 1.0)]


# ------------------------------------------------------------------ 2. regresión del fallo de los 561 s
def test_2_reunion_continua_con_eco_aplazado_no_se_retrasa_mas_de_15_s_y_se_transcribe_como_normal(reloj):
    b = Banco(reloj, capacidad=1.2)   # transcribir 6 s de audio cuesta 5 s de reloj
    tr = b.tr
    llegadas, t = [], 6.0
    while t <= 300.0:   # cinco minutos de Reunión sin parar (un tramo de 6 s cada 6 s) y su eco en el micro, aplazado
        llegadas += [(t, "reunion", False), (t + 0.3, "yo", True)]
        t += 6.0
    i, pico, servidos, aplazado_con_normal = 0, 0.0, [], 0
    while i < len(llegadas) or not tr.vacio():
        while i < len(llegadas) and llegadas[i][0] <= reloj.t:
            tl, f, apl = llegadas[i]
            b.en(tl, f, 6, aplazar=apl, t0=tl - 6)
            i += 1
        if tr.vacio():
            reloj.t = llegadas[i][0]
            continue
        pico = max(pico, tr.retraso_reunion_s)
        hay_normal = bool(tr._normales or tr._rezagados)
        s = b.servir()
        if s[1] == APLAZADO and hay_normal:
            aplazado_con_normal += 1
        servidos.append(s)
    reunion = [s for s in servidos if s[0] == "reunion"]
    assert pico <= 15.0 and tr.latencia_max["reunion"] <= 15.0
    assert len(reunion) == 50 and all(s[1] == NORMAL for s in reunion)   # todo el audio de Reunión, como normal y en directo
    assert aplazado_con_normal == 0                                       # ningún eco pasó por delante de algo que esperaba
    assert tr.tramos_rezagados == 0 and tr.perdidos_s == 0
    assert tr.eco_descartado_s > 0 and {d[3] for d in tr.tomar_descartes()} == {"eco"}   # el eco que no cabe se descarta y se cuenta
    _limpio(tr)


# ------------------------------------------------------------------ 3. un aplazado no adelanta nunca a un normal
@pytest.mark.parametrize("fuente_normal", ["reunion", "yo"])
def test_3_un_aplazado_que_lleva_diez_minutos_esperando_no_adelanta_a_un_normal_recien_llegado(reloj, fuente_normal):
    b = Banco(reloj)
    b.en(0.0, "yo", 2, aplazar=True, t0=0.0)
    reloj.t = 600.0
    b.en(600.0, fuente_normal, 2, t0=600.0)
    fuente, _audio_, _t0, clase, _inst = b.tomar()
    assert (fuente, clase) == (fuente_normal, NORMAL)
    b.tr._procesar(fuente, _audio(2), 600.0, False, NORMAL, 600.0)
    assert b.servir()[1] == APLAZADO   # solo cuando no queda nada más


def test_3_ni_un_rezagado_cede_su_turno_a_un_aplazado_viejo(reloj):
    b = Banco(reloj)
    b.en(0.0, "yo", 2, aplazar=True, t0=0.0)
    b.en(0.0, "reunion", 2, t0=0.0)
    reloj.t = 600.0   # el normal pasó a rezagado hace mucho y el aplazado espera aún más
    assert [c for _f, c, _t, _r in b.servir_todo()] == [REZAGADO, APLAZADO]


# ------------------------------------------------------------------ 4. rezagados
def _con_rezagados(reloj):
    """Dos Reunión de 2 s (t=0 y t=5) que a t=40 ya pasan del tope, más un normal de Reunión (3 s) y uno de Micro (1 s) recién llegados."""
    b = Banco(reloj)
    b.en(0.0, "reunion", 2, t0=0.0)
    b.en(5.0, "reunion", 2, t0=5.0)
    reloj.t = 40.0
    b.en(40.0, "reunion", 3, t0=40.0)
    b.en(40.0, "yo", 1, t0=40.0)
    return b


def test_4_un_normal_que_pasa_del_tope_deja_de_contar_como_retraso_y_cuenta_como_rezagado(reloj):
    assert RETRASO_TOPE_S == 30.0
    b = Banco(reloj)
    tr = b.tr
    b.en(0.0, "reunion", 4, t0=0.0)
    b.en(10.0, "yo", 3, t0=10.0)
    reloj.t = 30.0
    assert tr.retraso_de("reunion") == 30.0 and tr.rezagado_s == 0   # justo en el tope aún es normal
    reloj.t = 31.0
    assert tr.rezagado_s == 4.0 and tr.tramos_rezagados == 1 and tr.rezagado_total_s == 4.0
    assert tr.retraso_de("reunion") == 0.0                            # el rezagado ya no es retraso: nadie lo espera en directo
    assert tr.retraso_de("yo") == 21.0 and tr.retraso_s == 21.0
    assert tr.pendiente_s == 7.0 and len(tr._rezagados) == 1 and len(tr._normales) == 1


def test_4_el_rezagado_solo_sale_sin_normales_el_mas_reciente_primero_en_rapido_y_sin_tocar_la_continuidad(reloj):
    b = _con_rezagados(reloj)
    tr = b.tr
    assert tr.rezagado_s == 4.0 and tr.retraso_de("reunion") == 0.0 and tr.retraso_s == 0.0
    assert [(f, c) for f, c, _t, _r in [b.servir(), b.servir()]] == [("reunion", NORMAL), ("yo", NORMAL)]
    continuidad = dict(tr._ultima)
    assert continuidad["reunion"] and continuidad["yo"]
    b.en(41.0, "reunion", 1, t0=41.0)   # un normal nuevo pasa por delante de los rezagados que esperaban
    resto = b.servir_todo()
    assert [(c, t0, r) for _f, c, t0, r in resto] == [(NORMAL, 41.0, False), (REZAGADO, 5.0, True), (REZAGADO, 0.0, True)]
    # el texto del normal de t0=41 sí actualizó la continuidad de Reunión; los dos rezagados, no
    assert tr._ultima["reunion"] == T.ultima_frase(b.entregados[2][2]) != continuidad["reunion"]
    assert tr._ultima["yo"] == continuidad["yo"]
    _limpio(tr)


def test_4_el_rezagado_se_transcribe_con_los_parametros_del_modo_rapido(reloj):
    class Modelo:
        def __init__(self):
            self.kw = []

        def transcribe(self, audio, **kw):
            self.kw.append(kw)
            return iter([]), None
    m = Modelo()
    b = Banco(reloj, modelo=m)
    b.en(0.0, "reunion", 2, t0=0.0)
    reloj.t = 40.0
    b.en(40.0, "reunion", 2, t0=40.0)
    assert [(c, r) for _f, c, _t, r in b.servir_todo()] == [(NORMAL, False), (REZAGADO, True)]
    normal, rezagado = m.kw
    assert normal["beam_size"] == 5 and normal["temperature"] != TEMPERATURAS_RAPIDO   # el normal sin cola, con la calidad completa
    assert rezagado["beam_size"] == BEAM_RAPIDO and rezagado["temperature"] == TEMPERATURAS_RAPIDO and "word_timestamps" not in rezagado


# ------------------------------------------------------------------ 5. presupuesto de rezagados
def test_5_al_pasar_del_presupuesto_de_rezagados_se_descarta_el_mas_antiguo_y_se_cuenta_como_perdido(reloj):
    b = Banco(reloj)
    tr = b.tr
    assert REZAGADO_TOPE_S == 480.0
    for k in range(5):   # 500 s de audio de Reunión
        b.en(float(k), "reunion", 100, t0=100.0 * k)
    reloj.t = 100.0       # todos llevan más de 30 s: pasan a rezagados y no caben (500 > 480)
    assert tr.retraso_s == 0.0
    assert tr.rezagado_s == 400.0 and tr.perdidos_s == 100.0 and tr.ultimo_fallo == "saturación"
    assert tr.eco_descartado_s == 0.0 and tr.pendiente_s == 400.0
    assert tr.tomar_descartes() == [("reunion", 0.0, 100.0, "saturacion")]   # el más antiguo, con su minuto
    assert tr.tomar_descartes() == []                                        # al leerlos se vacían


# ------------------------------------------------------------------ 6. presupuesto de aplazados
def test_6_al_pasar_del_presupuesto_de_aplazados_se_descarta_el_mas_antiguo_y_no_cuenta_como_perdido(reloj):
    b = Banco(reloj)
    tr = b.tr
    assert APLAZADO_TOPE_S == 120.0
    for k in range(4):   # 4 × 40 s = 160 s de eco: el primero no cabe
        b.en(float(k), "yo", 40, aplazar=True, t0=40.0 * k)
    assert tr.aplazado_s == 120.0 and tr.pendiente_s == 120.0
    assert tr.eco_descartado_s == 40.0 and tr.perdidos_s == 0.0 and tr.ultimo_fallo == ""
    assert tr.tomar_descartes() == [("yo", 0.0, 40.0, "eco")]
    assert tr.tomar_descartes() == []
    assert [t0 for _f, _c, t0, _r in b.servir_todo()] == [40.0, 80.0, 120.0]   # lo que se queda sigue en orden de llegada


# ------------------------------------------------------------------ 7. contabilidad
def test_7_tras_procesar_o_descartar_todo_la_contabilidad_queda_a_cero_incluso_con_descartes_de_los_dos_tipos(reloj):
    b = Banco(reloj, capacidad=2.0)
    tr = b.tr
    for k in range(4):                                  # 520 s de Reunión que pasarán a rezagados
        b.en(0.0, "reunion", 130, t0=130.0 * k)
    for k in range(5):                                  # 150 s de eco: no caben 30
        b.en(0.0, "yo", 30, aplazar=True, t0=30.0 * k)
    reloj.t = 31.0
    b.en(31.0, "reunion", 5, t0=1000.0)                 # un normal; con él se recalcula y se descartan los más antiguos
    assert tr.perdidos_s == 130.0 and tr.eco_descartado_s == 30.0
    assert tr.rezagado_s == 390.0 and tr.aplazado_s == 120.0 and tr.pendiente_s == 515.0 and not tr.vacio()
    clases = [c for _f, c, _t, _r in b.servir_todo()]
    assert clases == [NORMAL] + [REZAGADO] * 3 + [APLAZADO] * 4
    assert sorted(d[3] for d in tr.tomar_descartes()) == ["eco", "saturacion"]
    _limpio(tr)


def test_7_un_fallo_dentro_del_tramo_tambien_deja_la_contabilidad_a_cero(reloj):
    b = Banco(reloj)

    def falla(audio, fuente, rapido=False, solo_local=False):
        raise RuntimeError("memoria agotada (ficticia)")
    b.tr._segmentos = falla
    b.en(0.0, "reunion", 4, t0=0.0)
    b.en(0.0, "yo", 3, aplazar=True, t0=0.0)
    b.servir_todo()
    assert b.tr.perdidos_s == 7.0 and b.tr.reintentos == 2
    _limpio(b.tr)


# ------------------------------------------------------------------ 8. retraso por fuente
def test_8_el_retraso_cuenta_el_normal_en_curso_y_el_que_espera_y_ningun_otro(reloj):
    b = Banco(reloj)
    tr = b.tr
    assert tr.retraso_s == 0 and tr.retraso_de("reunion") == 0 and tr.retraso_de("yo") == 0 and tr.retraso_reunion_s == 0
    b.en(0.0, "reunion", 2, t0=0.0)
    b.en(10.0, "yo", 2, t0=10.0)
    reloj.t = 12.0
    fuente, _a, _t0, clase, _i = b.tomar()           # el de Reunión pasa a estar en curso
    assert (fuente, clase) == ("reunion", NORMAL)
    assert tr.retraso_de("reunion") == 12.0 and tr.retraso_reunion_s == 12.0   # el que se está transcribiendo cuenta
    assert tr.retraso_de("yo") == 2.0 and tr.retraso_s == 12.0                 # None = la fuente con más retraso
    tr._procesar("reunion", _audio(2), 0.0, False, NORMAL, 0.0)
    assert tr.retraso_de("reunion") == 0.0 and tr.retraso_s == 2.0


def test_8_un_rezagado_o_un_aplazado_en_curso_no_cuentan_como_retraso(reloj):
    b = Banco(reloj)
    tr = b.tr
    b.en(0.0, "yo", 2, t0=0.0)
    b.en(0.0, "reunion", 2, aplazar=True, t0=0.0)
    reloj.t = 100.0
    _f, _a, _t0, clase, _i = b.tomar()
    assert clase == REZAGADO and tr.retraso_s == 0.0 and tr.retraso_de("yo") == 0.0 and tr.rezagado_s == 2.0
    tr._procesar("yo", _audio(2), 0.0, True, REZAGADO, 0.0)
    _f, _a, _t0, clase, _i = b.tomar()
    assert clase == APLAZADO and tr.retraso_s == 0.0 and tr.retraso_de("reunion") == 0.0 and tr.aplazado_s == 2.0


# ------------------------------------------------------------------ 9. latencias
def test_9_las_latencias_solo_se_actualizan_con_tramos_normales(reloj):
    b = Banco(reloj, capacidad=1.0)
    tr = b.tr
    b.en(0.0, "yo", 3, t0=0.0)                       # será rezagado
    reloj.t = 31.0
    b.en(31.0, "reunion", 4, t0=31.0)
    b.en(31.0, "yo", 2, aplazar=True, t0=31.0)
    assert [c for _f, c, _t, _r in b.servir_todo()] == [NORMAL, REZAGADO, APLAZADO]
    assert tr.latencias == {"reunion": 4.0} and tr.latencia_max == {"reunion": 4.0} and tr.latencia_s == 4.0
    assert "yo" not in tr.latencias and "yo" not in tr.latencia_max   # ni el rezagado ni el aplazado del micro dejaron latencia
    assert tr.audio_total_s == 9.0 and tr.calculo_total_s == pytest.approx(9.0)   # pero sí cuentan como audio transcrito


def test_9_latencia_max_guarda_la_mayor_por_fuente(reloj):
    b = Banco(reloj, capacidad=1.0)
    b.en(0.0, "reunion", 2, t0=0.0)
    b.servir()
    reloj.t = 10.0
    b.en(10.0, "reunion", 8, t0=10.0)
    b.servir()
    reloj.t = 30.0
    b.en(30.0, "reunion", 1, t0=30.0)
    b.servir()
    assert b.tr.latencias["reunion"] == 1.0 and b.tr.latencia_max["reunion"] == 8.0


# ------------------------------------------------------------------ 10. sin tope: orden de llegada estricto (dictado)
def test_10_sin_tope_de_retraso_orden_de_llegada_entre_fuentes_y_nada_pasa_a_rezagado(reloj):
    b = Banco(reloj)
    tr = b.tr
    tr.tope_retraso_s = None
    b.en(0.0, "yo", 2, t0=0.0)
    b.en(1.0, "reunion", 2, t0=1.0)
    b.en(2.0, "yo", 2, t0=2.0)
    reloj.t = 600.0                                   # minutos esperando
    assert tr.retraso_s == 600.0 and tr.rezagado_s == 0.0 and tr.tramos_rezagados == 0
    assert [(f, c, t0) for f, c, t0, _r in b.servir_todo()] == [("yo", NORMAL, 0.0), ("reunion", NORMAL, 1.0), ("yo", NORMAL, 2.0)]
    assert tr.tramos_rezagados == 0 and tr.rezagado_total_s == 0.0
    _limpio(tr)


def test_10_el_dictado_no_usa_rezagados_ni_prioridad_entre_fuentes():
    from apuntes import dictado
    assert dictado._TranscriptorDictado.tope_retraso_s is None
    assert Transcriptor.tope_retraso_s == RETRASO_TOPE_S   # la reunión sí


# ------------------------------------------------------------------ 11. sin modelo
def test_11_encolar_con_estado_error_suma_a_perdidos_y_no_encola(reloj):
    b = Banco(reloj)
    tr = b.tr
    tr.estado = "error"
    b.en(0.0, "yo", 3)
    b.en(0.0, "reunion", 1.5, aplazar=True)
    assert tr.perdidos_s == pytest.approx(4.5)
    assert tr.pendiente_s == 0 and tr.tramos_aplazados == 0 and not tr._normales and not tr._aplazados
    _limpio(tr)


# ------------------------------------------------------------------ 12. el hilo real
def _hasta(cond, limite: float = 5.0) -> bool:
    fin = time.time() + limite
    while time.time() < fin:
        if cond():
            return True
        time.sleep(0.005)
    return bool(cond())


def test_12_con_el_hilo_en_reposo_un_tramo_se_transcribe_sin_esperar_al_ciclo_y_detener_vuelve_enseguida(monkeypatch):
    monkeypatch.setattr(T, "ESPERA_HILO_S", 3.0)   # si el hilo dependiera de su ciclo de espera, tardaría hasta 3 s
    entro = threading.Event()

    class Modelo:
        def transcribe(self, audio, **kw):
            entro.set()
            return iter([]), None

    class Tr(Transcriptor):
        def cargar_modelo(self):
            return Modelo()

    tr = Tr(CFG, lambda *a, **k: None)
    tr.iniciar()
    try:
        assert _hasta(lambda: tr.estado == "listo")
        time.sleep(0.3)   # el hilo ya está esperando en la condición con las colas vacías
        t = time.perf_counter()
        tr.encolar("reunion", np.zeros(SR_WHISPER * 2, np.float32), 0.0)
        assert entro.wait(1.5) and time.perf_counter() - t < 1.5   # lo despierta el `notify`
        assert _hasta(tr.vacio, 2.0)
        time.sleep(0.2)   # otra vez en reposo
    finally:
        t = time.perf_counter()
        tr.detener()
    assert time.perf_counter() - t < 1.5 and not tr._hilo.is_alive()   # `notify_all`: no agota los 3 s de la espera


# ------------------------------------------------------------------ arreglos de la revisión de la cola
def test_siguiente_tras_detener_no_toma_nada_y_los_tramos_siguen_en_la_cola(reloj):
    b = Banco(reloj)
    tr = b.tr
    b.en(0.0, "reunion", 2)
    b.en(0.0, "yo", 2, aplazar=True)
    tr._parar.set()
    assert tr._siguiente() is None
    assert len(tr._normales) == 1 and len(tr._aplazados) == 1 and tr._en_curso is None and tr.pendiente_s == 4.0


def test_siguiente_tampoco_toma_un_tramo_que_llega_mientras_el_hilo_esperaba_si_ya_se_pidio_parar(reloj):
    b = Banco(reloj)
    tr = b.tr

    def espera_y_para(_timeout=None):   # mientras el hilo espera entra un tramo y se llama a `detener()`
        tr._normales.append(("reunion", _audio(2), 0.0, 0.0))   # sin pasar por `encolar`: el hilo tiene cogido el cerrojo
        tr._pendiente_s += 2.0
        tr._parar.set()
    tr._hay.wait = espera_y_para
    assert tr._siguiente() is None
    assert len(tr._normales) == 1 and tr._en_curso is None


def _desbordar_rezagados(b, antes=None):
    for k in range(5):   # 500 s: no caben 480
        b.en(float(k), "reunion", 100, t0=100.0 * k)
    if antes:
        antes()   # (con el modelo ya en error `encolar` no encola: el estado cambia después de llenar la cola)
    b.reloj.t = 100.0
    return b.tr.retraso_s


def test_saturar_con_el_modelo_en_error_no_tapa_el_fallo_real(reloj):
    b = Banco(reloj)
    def cae_el_modelo():
        b.tr.estado, b.tr.ultimo_fallo = "error", "OSError"
    _desbordar_rezagados(b, cae_el_modelo)
    assert b.tr.perdidos_s == 100.0 and b.tr.ultimo_fallo == "OSError"


def test_saturar_con_el_modelo_listo_pone_el_fallo_a_saturacion_aunque_hubiera_otro(reloj):
    b = Banco(reloj)
    b.tr.ultimo_fallo = "RuntimeError"
    _desbordar_rezagados(b)
    assert b.tr.perdidos_s == 100.0 and b.tr.ultimo_fallo == "saturación"


def test_cargas_con_solo_rezagados_en_cola_no_hay_normales_detras_pero_el_modo_rapido_sigue(reloj):
    b = Banco(reloj)
    tr = b.tr
    b.en(0.0, "reunion", 10, t0=0.0)
    b.en(1.0, "reunion", 10, t0=10.0)
    reloj.t = 40.0
    fuente, audio, _t0, clase, _i = b.tomar()   # el más reciente de los dos rezagados
    assert clase == REZAGADO
    with tr._lock:
        en_cola_s, normal_detras_s = tr._cargas(clase, audio.size / SR_WHISPER)
    assert normal_detras_s == 0.0          # el atraso acumulado no enciende «alcanzando el directo»
    assert en_cola_s == 10.0 >= COLA_ALCANCE_S   # pero sí sigue yendo en rápido: hay audio que recuperar


def test_cargas_con_normales_detras_de_un_rezagado_o_de_un_normal_las_cuenta(reloj):
    b = Banco(reloj)
    tr = b.tr
    b.en(0.0, "reunion", 10, t0=0.0)
    reloj.t = 40.0
    _f, audio, _t0, clase, _i = b.tomar()
    assert clase == REZAGADO
    b.en(40.0, "yo", 12, t0=40.0)           # 12 s de normales detrás del rezagado en curso
    with tr._lock:
        assert tr._cargas(clase, 10.0)[1] == 12.0 >= COLA_ALCANCE_S
    tr._procesar(_f, audio, _t0, True, clase, _i)
    _f, audio, _t0, clase, _i = b.tomar()   # ahora el normal en curso, con otros 12 s de normales detrás
    b.en(40.0, "reunion", 12, t0=41.0)
    with tr._lock:
        assert tr._cargas(clase, 12.0)[1] == 12.0


def test_el_tramo_en_curso_no_cuenta_contra_el_presupuesto_de_rezagados(reloj):
    b = Banco(reloj)
    tr = b.tr
    for k in range(3):
        b.en(0.0, "reunion", 150, t0=150.0 * k)
    reloj.t = 40.0
    assert tr.rezagado_s == 450.0
    assert b.tomar()[3] == REZAGADO                 # 150 s en curso: ya no se pueden descartar
    b.en(40.0, "reunion", 100, t0=500.0)
    reloj.t = 80.0
    assert tr.rezagado_s == 550.0                   # 300 + 100 en cola (≤ 480) y 150 en curso
    assert tr.perdidos_s == 0.0 and tr.tomar_descartes() == []


def test_el_tramo_en_curso_no_cuenta_contra_el_presupuesto_de_aplazados(reloj):
    b = Banco(reloj)
    tr = b.tr
    b.en(0.0, "yo", 60, aplazar=True, t0=0.0)
    b.en(1.0, "yo", 60, aplazar=True, t0=60.0)
    assert b.tomar()[3] == APLAZADO                 # 60 s en curso
    b.en(2.0, "yo", 50, aplazar=True, t0=120.0)
    assert tr.aplazado_s == 170.0 and tr.eco_descartado_s == 0.0 and tr.tomar_descartes() == []   # 60 + 50 en cola (≤ 120)
    b.en(3.0, "yo", 70, aplazar=True, t0=170.0)     # ahora sí: 180 s en cola
    assert tr.eco_descartado_s == 60.0 and tr.tomar_descartes() == [("yo", 60.0, 60.0, "eco")]


def test_leer_el_retraso_tras_superar_el_tope_mueve_el_tramo_a_rezagados(reloj):
    b = Banco(reloj)
    tr = b.tr
    b.en(0.0, "reunion", 4, t0=0.0)
    reloj.t = 31.0
    assert len(tr._normales) == 1 and not tr._rezagados   # nadie lo ha ordenado aún
    assert tr.retraso_reunion_s == 0.0                    # leer el retraso ya lo degrada
    assert not tr._normales and len(tr._rezagados) == 1 and tr._rezagado_s == 4.0


def test_leer_rezagado_s_tambien_ordena_la_cola(reloj):
    b = Banco(reloj)
    b.en(0.0, "reunion", 4, t0=0.0)
    reloj.t = 31.0
    assert b.tr.rezagado_s == 4.0 and not b.tr._normales


# ------------------------------------------------------------------ diagnóstico de capacidad: CPU del cálculo y audio recibido
def test_el_transcriptor_acumula_el_audio_recibido_y_la_cpu_del_calculo(reloj):
    b = Banco(reloj, capacidad=2.0)                       # 6 s de audio cuestan 3 s de reloj (y, en el doble, 3 s de CPU)
    tr = b.tr
    assert tr.audio_recibido_s == 0 and tr.cpu_total_s == 0 and tr.calculo_total_s == 0
    b.en(0.0, "reunion", 6)
    b.en(0.0, "yo", 4, aplazar=True)
    assert tr.audio_recibido_s == pytest.approx(10.0)      # lo que entra en la cola, sea cual sea su clase
    b.servir_todo()
    assert tr.audio_total_s == pytest.approx(10.0) and tr.calculo_total_s == pytest.approx(5.0)
    assert tr.cpu_total_s == pytest.approx(5.0)            # núcleos = cpu / reloj de cálculo
    assert tr.cpu_total_s / tr.calculo_total_s == pytest.approx(1.0)


def test_un_tramo_que_falla_no_suma_cpu_ni_calculo(reloj):
    b = Banco(reloj)

    def falla(audio, fuente, rapido=False, solo_local=False):
        reloj.t += 1.0
        raise RuntimeError("memoria agotada (ficticia)")
    b.tr._segmentos = falla
    b.en(0.0, "reunion", 6)
    b.servir_todo()
    assert b.tr.cpu_total_s == 0 and b.tr.calculo_total_s == 0 and b.tr.audio_recibido_s == pytest.approx(6.0)
