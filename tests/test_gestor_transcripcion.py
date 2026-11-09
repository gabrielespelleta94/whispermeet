"""El Gestor y su transcriptor al final y durante la reunión: espera de la cola al terminar (`_esperar_transcripcion`), vigilancia de pérdidas y
retraso (`_vigilar_transcripcion`), orden emitir/guardar en `_agregar`, campos nuevos de `estado_ligero` y `vaciar_al_parar` de la captura.
Transcriptor doble y reloj simulado (nada duerme de verdad): ni audio real, ni Whisper, ni modelo, ni red. Todo en `tmp_path`."""
import asyncio
import time
from types import SimpleNamespace

import pytest

from apuntes import gestor as G
from apuntes import registro
from test_contexto_reunion import PROYECTO, iniciar_y_esperar
from test_idioma import CapturaNula, gestor_con_audio

SECRETO = "contenido-secreto-de-la-reunion"


# ================================================================ dobles
class Reloj:
    """Reloj simulado: `monotonic()` solo avanza cuando el gestor «duerme» (asyncio.sleep) o cuando el test lo mueve."""

    def __init__(self, inicio=1000.0):
        self.t = inicio

    def monotonic(self):
        return self.t


class Transcriptor2:
    """Transcriptor doble. `perfil(t)` da el audio en cola `t` segundos (de reloj simulado) después de crearlo."""

    def __init__(self, reloj=None, perfil=None, **campos):
        self.reloj, self.perfil = reloj, perfil
        self.t0 = reloj.t if reloj else 0.0
        self._pendiente = 0.0
        self.estado, self.error, self.perdidos_s, self.retraso_s = "listo", "", 0.0, 0.0
        self.ultimo_fallo, self.velocidad_x, self.alcance, self.reintentos = "", None, False, 0
        for k, v in campos.items():
            setattr(self, k, v)

    @property
    def pendiente_s(self):
        return max(0.0, self.perfil(self.reloj.t - self.t0)) if self.perfil else self._pendiente

    @pendiente_s.setter
    def pendiente_s(self, v):
        self._pendiente = v

    def vacio(self):
        return self.pendiente_s <= 0.0

    def detener(self):
        pass


@pytest.fixture
def reloj(monkeypatch):
    """Sustituye `time` y `asyncio` DENTRO de apuntes.gestor: monotonic es el reloj simulado y sleep lo adelanta sin esperar."""
    r = Reloj()
    asyncio_real = asyncio

    class _Asyncio:
        def __getattr__(self, nombre):
            return getattr(asyncio_real, nombre)

        async def sleep(self, s, *a, **k):
            r.t += s
            await asyncio_real.sleep(0)

    class _Time:
        def __getattr__(self, nombre):
            return getattr(time, nombre)

        def monotonic(self):
            return r.monotonic()

    monkeypatch.setattr(G, "asyncio", _Asyncio())
    monkeypatch.setattr(G, "time", _Time())
    return r


@pytest.fixture
def gestor(tmp_path, monkeypatch):
    """Gestor con una reunión iniciada (sin micro ni Whisper real). Los eventos van a `gestor.eventos`."""
    g, _modelo, _cfg = gestor_con_audio(tmp_path, monkeypatch)
    asyncio.run(iniciar_y_esperar(g, PROYECTO, "Tema ficticio", 5, None, []))
    g.transcriptor.detener()
    g.eventos = []
    g._emitir = g.eventos.append
    yield g


def avisos_ev(gestor):
    return [e for e in gestor.eventos if e["tipo"] == "aviso"]


def lineas_log(prefijo="transcripcion "):
    ruta = registro.RUTA_LOG
    if not ruta.exists():
        return []
    return [l for l in ruta.read_text(encoding="utf-8").splitlines() if f"] {prefijo}" in l]


def esperar(gestor):
    asyncio.run(gestor._esperar_transcripcion())


# ================================================================ _esperar_transcripcion
def test_esperar_con_cola_que_se_vacia_a_los_pocos_ciclos_no_deja_incidencia_ni_aviso(gestor, reloj):
    gestor.transcriptor = Transcriptor2(reloj, lambda t: 3.0 - t)            # se vacía a los 3 s (10 ciclos de 0,3 s)
    esperar(gestor)
    assert gestor.transcriptor.vacio()
    assert gestor.sesion.incidencias == [] and gestor.avisos == [] and avisos_ev(gestor) == []
    assert reloj.t - gestor.transcriptor.t0 < 4.0


def test_esperar_con_cola_atascada_vuelve_y_deja_incidencia_aviso_y_evento(gestor, reloj, monkeypatch):
    monkeypatch.setattr(G, "ESPERA_COLA_SIN_AVANCE_S", 2.0)
    gestor.transcriptor = Transcriptor2(reloj, lambda t: 12.4)               # pendiente constante: no avanza nunca
    esperar(gestor)
    assert 2.0 < reloj.t - gestor.transcriptor.t0 < 3.0                      # se rindió justo después del plazo sin avance
    assert len(gestor.sesion.incidencias) == 1
    inc = gestor.sesion.incidencias[0]
    assert inc.startswith("[") and inc.endswith("transcripción incompleta: 12 s de audio sin transcribir al terminar")
    assert len(gestor.avisos) == 1 and "12 s de audio" in gestor.avisos[0]
    (ev,) = avisos_ev(gestor)
    assert ev["componente"] == "transcripcion" and ev["mensaje"] == gestor.avisos[0] and ev["grave"] is True


def test_esperar_con_cola_que_avanza_despacio_no_se_corta_aunque_tarde_mas_que_el_plazo_sin_avance(gestor, reloj, monkeypatch):
    monkeypatch.setattr(G, "ESPERA_COLA_SIN_AVANCE_S", 1.0)
    gestor.transcriptor = Transcriptor2(reloj, lambda t: 50.0 - 0.5 * t)     # 100 s de espera, muy por encima de 1 s, pero siempre bajando
    esperar(gestor)
    assert gestor.transcriptor.vacio()
    assert reloj.t - gestor.transcriptor.t0 >= 99.0
    assert gestor.sesion.incidencias == [] and gestor.avisos == [] and avisos_ev(gestor) == []


def test_esperar_respeta_el_tope_absoluto_aunque_la_cola_avance(gestor, reloj, monkeypatch):
    monkeypatch.setattr(G, "ESPERA_COLA_MAX_S", 5.0)
    monkeypatch.setattr(G, "ESPERA_COLA_SIN_AVANCE_S", 100.0)
    gestor.transcriptor = Transcriptor2(reloj, lambda t: 1000.0 - t)         # avanza siempre, pero no llegaría a vaciarse
    esperar(gestor)
    assert not gestor.transcriptor.vacio()
    assert 5.0 < reloj.t - gestor.transcriptor.t0 < 6.0
    assert len(gestor.sesion.incidencias) == 1 and "transcripción incompleta: 995 s" in gestor.sesion.incidencias[0]
    assert len(avisos_ev(gestor)) == 1 and len(gestor.avisos) == 1


def test_esperar_con_transcriptor_en_error_no_espera(gestor, reloj):
    gestor.transcriptor = Transcriptor2(reloj, lambda t: 30.0, estado="error", error="el modelo no se pudo cargar")
    esperar(gestor)
    assert reloj.t == gestor.transcriptor.t0                                # ni un solo ciclo de espera


def test_esperar_emite_el_estado_cada_dos_segundos_mientras_espera(gestor, reloj):
    gestor.transcriptor = Transcriptor2(reloj, lambda t: 20.0 - t)           # 20 s de espera simulada
    esperar(gestor)
    estados = [e for e in gestor.eventos if e["tipo"] == "estado"]
    assert 8 <= len(estados) <= 10                                           # uno cada 2 s, no uno por ciclo (0,3 s)
    assert all(e["transcripcion"]["pendiente_s"] >= 0 for e in estados)


def test_esperar_con_cola_ya_vacia_vuelve_sin_emitir_nada(gestor, reloj):
    gestor.transcriptor = Transcriptor2(reloj, lambda t: 0.0)
    esperar(gestor)
    assert gestor.eventos == [] and gestor.sesion.incidencias == [] and reloj.t == gestor.transcriptor.t0


# ================================================================ _vigilar_transcripcion
def test_vigilar_sin_transcriptor_devuelve_false_y_no_hace_nada(gestor):
    gestor.transcriptor = None
    assert gestor._vigilar_transcripcion() is False
    assert gestor.sesion.incidencias == [] and gestor.eventos == [] and lineas_log() == []


def test_vigilar_sin_perdidas_ni_retraso_devuelve_false(gestor, reloj):
    gestor.transcriptor = Transcriptor2(reloj)
    assert gestor._vigilar_transcripcion() is False
    assert gestor.sesion.incidencias == [] and gestor.avisos == [] and gestor.eventos == [] and lineas_log() == []


def test_vigilar_primera_perdida_deja_incidencia_aviso_evento_y_linea_de_registro(gestor, reloj):
    gestor.transcriptor = Transcriptor2(reloj, perdidos_s=7.4, ultimo_fallo="RuntimeError")
    assert gestor._vigilar_transcripcion() is True
    assert len(gestor.sesion.incidencias) == 1
    assert gestor.sesion.incidencias[0].endswith("transcripción: 7 s de audio sin transcribir (RuntimeError)")
    assert gestor.avisos == [G.TEXTO_AUDIO_PERDIDO]
    (ev,) = avisos_ev(gestor)
    assert ev["componente"] == "transcripcion" and ev["mensaje"] == G.TEXTO_AUDIO_PERDIDO and ev["grave"] is False
    (linea,) = lineas_log()
    assert linea.endswith("transcripcion audio_perdido=7.4s total=7.4s tipo=RuntimeError")


def test_vigilar_sin_tipo_de_fallo_dice_sin_modelo(gestor, reloj):
    gestor.transcriptor = Transcriptor2(reloj, perdidos_s=3.0, ultimo_fallo="")
    assert gestor._vigilar_transcripcion() is True
    assert gestor.sesion.incidencias[0].endswith("transcripción: 3 s de audio sin transcribir (sin modelo)")


def test_vigilar_segunda_llamada_sin_cambio_no_repite_nada(gestor, reloj):
    gestor.transcriptor = Transcriptor2(reloj, perdidos_s=7.4, ultimo_fallo="RuntimeError")
    assert gestor._vigilar_transcripcion() is True
    assert gestor._vigilar_transcripcion() is False
    assert len(gestor.sesion.incidencias) == 1 and len(avisos_ev(gestor)) == 1 and len(lineas_log()) == 1


def test_vigilar_segunda_perdida_espera_su_turno_acumula_y_no_duplica_el_aviso(gestor, reloj):
    tr = gestor.transcriptor = Transcriptor2(reloj, perdidos_s=7.4, ultimo_fallo="RuntimeError")
    gestor._vigilar_transcripcion()
    tr.perdidos_s, tr.ultimo_fallo = 9.0, "OSError"
    assert gestor._vigilar_transcripcion() is False                       # dentro del intervalo: se acumula, no se repite el aviso
    assert len(gestor.sesion.incidencias) == 1 and len(avisos_ev(gestor)) == 1
    tr.perdidos_s = 12.0
    reloj.t += G.AVISO_FALLO_CADA_S
    assert gestor._vigilar_transcripcion() is True
    assert len(gestor.sesion.incidencias) == 2
    assert gestor.sesion.incidencias[1].endswith("transcripción: 5 s de audio sin transcribir (OSError)")   # todo lo nuevo junto: 12,0 - 7,4
    assert gestor.avisos == [G.TEXTO_AUDIO_PERDIDO]                                                        # una sola vez en la lista
    assert len(avisos_ev(gestor)) == 2
    assert lineas_log()[1].endswith("transcripcion audio_perdido=4.6s total=12.0s tipo=OSError")


def test_vigilar_con_el_modelo_caido_no_avisa_en_cada_pasada(gestor, reloj):
    # sin modelo, cada tramo que llega se pierde: una pasada por segundo no puede ser un aviso por segundo
    tr = gestor.transcriptor = Transcriptor2(reloj, estado="error", perdidos_s=2.0)
    for _ in range(60):
        gestor._vigilar_transcripcion()
        tr.perdidos_s += 2.0
        reloj.t += 1.0
    assert len(gestor.sesion.incidencias) == 1 and len(avisos_ev(gestor)) == 1 and gestor.avisos == [G.TEXTO_AUDIO_PERDIDO]


def test_vigilar_forzado_dice_lo_que_quedaba_por_decir(gestor, reloj):
    tr = gestor.transcriptor = Transcriptor2(reloj, perdidos_s=3.0, ultimo_fallo="RuntimeError")
    gestor._vigilar_transcripcion()
    tr.perdidos_s = 8.0
    assert gestor._vigilar_transcripcion() is False
    assert gestor._vigilar_transcripcion(forzar=True) is True
    assert gestor.sesion.incidencias[-1].endswith("transcripción: 5 s de audio sin transcribir (RuntimeError)")


def test_esperar_anota_lo_perdido_durante_el_vaciado_final(gestor, reloj):
    # el bucle de la reunión ya no corre al terminar: un tramo que falla mientras se vacía la cola no puede quedar sin rastro
    tr = gestor.transcriptor = Transcriptor2(reloj, lambda t: 1.5 - t, ultimo_fallo="MemoryError")
    tr.perdidos_s = 4.0
    esperar(gestor)
    assert any(i.endswith("transcripción: 4 s de audio sin transcribir (MemoryError)") for i in gestor.sesion.incidencias)
    assert gestor.avisos == [G.TEXTO_AUDIO_PERDIDO] and len(avisos_ev(gestor)) == 1


def test_vigilar_linea_de_retraso_con_sus_medidas_y_sin_texto_de_la_reunion(gestor, reloj):
    gestor.sesion.agregar_segmento(5.0, "yo", SECRETO)
    gestor.transcriptor = Transcriptor2(reloj, retraso_s=20.4, pendiente_s=33.0, velocidad_x=0.83, alcance=True, reintentos=2, perdidos_s=0.0)
    assert gestor._vigilar_transcripcion() is True
    (linea,) = lineas_log()
    assert linea.endswith("transcripcion retraso=20s cola=33s vel=0.8x rapido=True reintentos=2 perdidos=0s")
    assert gestor.sesion.incidencias == [] and gestor.avisos == [] and avisos_ev(gestor) == []             # el retraso solo se registra, no se avisa
    assert SECRETO not in registro.RUTA_LOG.read_text(encoding="utf-8")


def test_vigilar_retraso_sin_velocidad_medida_pone_guion(gestor, reloj):
    gestor.transcriptor = Transcriptor2(reloj, retraso_s=G.RETRASO_A_REGISTRAR_S, velocidad_x=None)
    assert gestor._vigilar_transcripcion() is True
    assert " vel=- " in lineas_log()[0]


def test_vigilar_retraso_por_debajo_del_umbral_no_registra(gestor, reloj):
    gestor.transcriptor = Transcriptor2(reloj, retraso_s=G.RETRASO_A_REGISTRAR_S - 0.1)
    assert gestor._vigilar_transcripcion() is False
    assert lineas_log() == []


def test_vigilar_linea_de_retraso_como_mucho_una_cada_intervalo(gestor, reloj):
    gestor.transcriptor = Transcriptor2(reloj, retraso_s=40.0)
    assert gestor._vigilar_transcripcion() is True and len(lineas_log()) == 1
    assert gestor._vigilar_transcripcion() is False and len(lineas_log()) == 1       # misma pasada: nada
    reloj.t += G.REGISTRO_RETRASO_CADA_S - 1.0
    assert gestor._vigilar_transcripcion() is False and len(lineas_log()) == 1       # aún dentro del intervalo
    reloj.t += 1.0
    assert gestor._vigilar_transcripcion() is True and len(lineas_log()) == 2        # cumplido el intervalo: otra línea


def test_vigilar_perdida_y_retraso_a_la_vez_dejan_las_dos_lineas(gestor, reloj):
    gestor.transcriptor = Transcriptor2(reloj, perdidos_s=2.0, ultimo_fallo="ValueError", retraso_s=60.0)
    assert gestor._vigilar_transcripcion() is True
    ls = lineas_log()
    assert len(ls) == 2 and "audio_perdido=2.0s" in ls[0] and "retraso=60s" in ls[1] and "perdidos=2s" in ls[1]
    assert SECRETO not in registro.RUTA_LOG.read_text(encoding="utf-8")


# ================================================================ _agregar: primero a la pantalla, después al disco
def test_agregar_emite_el_segmento_antes_de_guardar_la_sesion(gestor, monkeypatch):
    orden = []
    gestor._emitir = lambda ev: orden.append(ev["tipo"])
    monkeypatch.setattr(gestor.sesion, "guardar", lambda *a, **k: orden.append("guardar"), raising=False)
    gestor._agregar(10.0, "yo", "Una frase de prueba para la reunión ficticia.")
    assert orden.index("segmento") < orden.index("guardar")
    assert orden.count("segmento") == 1 and orden.count("guardar") == 1


def test_agregar_si_guardar_falla_el_segmento_ya_salio_y_queda_el_aviso(gestor, monkeypatch):
    def roto(*a, **k):
        raise OSError("disco lleno")

    monkeypatch.setattr(gestor.sesion, "guardar", roto, raising=False)
    gestor._agregar(10.0, "yo", "Otra frase de prueba, distinta de la anterior.")
    assert [e for e in gestor.eventos if e["tipo"] == "segmento"], "el segmento debía emitirse aunque el guardado falle"
    assert any(a.startswith("No se pudo guardar la transcripción") for a in gestor.avisos)


# ================================================================ estado_ligero y Captura
def test_estado_ligero_lleva_los_campos_nuevos_de_la_transcripcion(gestor, reloj):
    gestor.transcriptor = Transcriptor2(reloj, pendiente_s=12.34, retraso_s=3.26, velocidad_x=1.234, alcance=True, perdidos_s=5.44)
    tr = gestor.estado_ligero()["transcripcion"]
    assert tr == {"estado": "listo", "error": "", "pendiente_s": 12.3, "retraso_s": 3.3, "velocidad_x": 1.23, "rapido": True, "perdidos_s": 5.4}


def test_estado_ligero_valores_por_defecto_y_sin_transcriptor(gestor, reloj):
    gestor.transcriptor = Transcriptor2(reloj)
    tr = gestor.estado_ligero()["transcripcion"]
    assert tr["retraso_s"] == 0.0 and tr["rapido"] is False and tr["perdidos_s"] == 0.0 and tr["velocidad_x"] is None and tr["pendiente_s"] == 0.0
    gestor.transcriptor = None
    assert gestor.estado_ligero()["transcripcion"] is None


def test_estado_ligero_aguanta_un_transcriptor_sin_los_campos_nuevos(gestor):
    viejo = SimpleNamespace(estado="listo", error="", pendiente_s=1.0, velocidad_x=None)
    gestor.transcriptor = viejo
    tr = gestor.estado_ligero()["transcripcion"]
    assert tr["retraso_s"] == 0.0 and tr["rapido"] is False and tr["perdidos_s"] == 0.0


def test_iniciar_audio_crea_la_captura_con_vaciar_al_parar(tmp_path, monkeypatch):
    recibido = {}

    class CapturaEspia(CapturaNula):
        def __init__(self, *a, **k):
            recibido.update(k)

    g, _modelo, _cfg = gestor_con_audio(tmp_path, monkeypatch)
    monkeypatch.setattr("apuntes.audio.Captura", CapturaEspia)
    asyncio.run(iniciar_y_esperar(g, PROYECTO, "Tema ficticio", 5, None, []))
    g.transcriptor.detener()
    assert recibido.get("vaciar_al_parar") is True
