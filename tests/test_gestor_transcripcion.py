"""El Gestor y su transcriptor al final y durante la reunión: espera de la cola al terminar (`_esperar_transcripcion`), vigilancia de pérdidas y
retraso (`_vigilar_transcripcion`), orden emitir/guardar en `_agregar`, campos nuevos de `estado_ligero` y `vaciar_al_parar` de la captura.
Transcriptor doble y reloj simulado (nada duerme de verdad): ni audio real, ni Whisper, ni modelo, ni red. Todo en `tmp_path`."""
import asyncio
import re
import time
from types import SimpleNamespace

import pytest

from apuntes import gestor as G
from apuntes import registro
from test_contexto_reunion import PROYECTO, iniciar_y_esperar
from test_idioma import CapturaNula, gestor_con_audio

SECRETO = "contenido-secreto-de-la-reunion"


@pytest.fixture(autouse=True)
def _sin_lectura_real_de_cpu(monkeypatch):
    """La CPU de todo el equipo cambia en cada lectura: salvo en los tests que la fijan, el gestor no tiene lectura (`cpu_equipo=-`)."""
    monkeypatch.setattr(G, "tiempos_del_equipo", lambda kernel32=None: None)


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


def test_esperar_deja_un_latido_nada_mas_empezar_y_otro_cada_treinta_segundos(gestor, reloj):
    gestor.transcriptor = Transcriptor2(reloj, lambda t: 100.0 - t)          # 100 s de espera simulada con la cola bajando
    esperar(gestor)
    lineas = lineas_log("transcripcion cierre ")
    assert 4 <= len(lineas) <= 5                                             # a los 0, 30, 60 y 90 s (y, a lo sumo, uno más por redondeo del ciclo)
    assert lineas[0].endswith("transcripcion cierre pendiente=100s espera=0s")   # el primero, nada más empezar
    esperas = [int(l.rsplit("espera=", 1)[1].rstrip("s")) for l in lineas]
    assert esperas[1] in (30, 31) and esperas[2] in (60, 61) and esperas == sorted(esperas)


def test_esperar_con_el_latido_cada_30_s_sigue_la_constante_del_modulo(gestor, reloj, monkeypatch):
    monkeypatch.setattr(G, "LATIDO_CIERRE_CADA_S", 10.0)
    gestor.transcriptor = Transcriptor2(reloj, lambda t: 50.0 - t)
    esperar(gestor)
    assert len(lineas_log("transcripcion cierre ")) in (5, 6)                # 0, 10, 20, 30, 40 (y 50 si el último ciclo cae justo)
    assert G.LATIDO_CIERRE_CADA_S == 10.0


def test_esperar_sin_nada_pendiente_no_escribe_latido(gestor, reloj):
    gestor.transcriptor = Transcriptor2(reloj, lambda t: 0.0)
    esperar(gestor)
    assert lineas_log("transcripcion cierre ") == []


def test_el_latido_del_cierre_lleva_solo_numeros(gestor, reloj):
    gestor.sesion.tema = SECRETO
    gestor.transcriptor = Transcriptor2(reloj, lambda t: 70.0 - t)
    esperar(gestor)
    lineas = lineas_log("transcripcion cierre ")
    assert lineas
    assert all(re.search(r"transcripcion cierre pendiente=\d+s espera=\d+s$", l) for l in lineas)
    assert not any(SECRETO in l for l in lineas)


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
    assert linea.endswith("transcripcion audio_perdido=7.4s total=7.4s tipo=RuntimeError saturacion=0.0s")


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
    assert lineas_log()[1].endswith("transcripcion audio_perdido=4.6s total=12.0s tipo=OSError saturacion=0.0s")


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
    gestor._eco_audio = None                                                 # sin detector de eco: la línea no lleva `eco_eval`/`eco_marc`
    gestor.transcriptor = Transcriptor2(reloj, retraso_s=20.4, pendiente_s=33.0, velocidad_x=0.83, alcance=True, reintentos=2, perdidos_s=0.0)
    assert gestor._vigilar_transcripcion() is True
    (linea,) = lineas_log()
    assert linea.endswith("transcripcion retraso=20s cola=33s vel=0.8x rapido=True reintentos=2 perdidos=0s aplazado=0s "
                          "ret_reunion=0s rezagado=0s eco_descartado=0s lat_reunion=- lat_micro=- nucleos=- cpu_equipo=-")
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
    assert tr == {"estado": "listo", "error": "", "pendiente_s": 12.3, "retraso_s": 3.3, "velocidad_x": 1.23, "rapido": True, "perdidos_s": 5.4,
                  "aplazado_s": 0.0, "retraso_reunion_s": 0.0, "rezagado_s": 0.0, "eco_descartado_s": 0.0}


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


# ================================================================ eco en origen: un Micro que parece solo eco se aplaza
class TranscriptorEspia:
    """Guarda cómo se encola cada tramo."""

    def __init__(self):
        self.encolados = []

    def encolar(self, fuente, audio, t0, **kw):
        self.encolados.append((fuente, t0, kw))


class EcoFijo:
    """Doble del detector: responde lo que se le diga y anota por qué tramos se le preguntó."""

    def __init__(self, respuesta=True, falla=False):
        self.respuesta, self.falla, self.preguntas = respuesta, falla, []

    def probable_eco(self, audio, t0):
        self.preguntas.append(t0)
        if self.falla:
            raise RuntimeError("detector roto")
        return self.respuesta


def test_un_micro_que_parece_eco_se_encola_aplazado_y_reunion_nunca(gestor):
    tr = gestor.transcriptor = TranscriptorEspia()
    eco = gestor._eco_audio = EcoFijo(True)
    gestor._on_enunciado("yo", object(), 10.0)
    gestor._on_enunciado("reunion", object(), 11.0)
    assert tr.encolados == [("yo", 10.0, {"aplazar": True}), ("reunion", 11.0, {})]
    assert eco.preguntas == [10.0]                      # por Reunión ni se pregunta: su texto es el bueno


def test_un_micro_con_voz_propia_va_en_su_orden_de_siempre(gestor):
    tr = gestor.transcriptor = TranscriptorEspia()
    gestor._eco_audio = EcoFijo(False)
    gestor._on_enunciado("yo", object(), 10.0)
    assert tr.encolados == [("yo", 10.0, {})]           # sin `aplazar`: vale también para un transcriptor que no lo conoce


def test_sin_filtro_de_eco_o_con_el_detector_roto_nada_se_aplaza(gestor):
    tr = gestor.transcriptor = TranscriptorEspia()
    gestor._eco_audio = None                            # filtro de eco desactivado en Ajustes: no hay detector
    gestor._on_enunciado("yo", object(), 1.0)
    gestor._eco_audio = EcoFijo(falla=True)             # un fallo del detector no pierde el tramo ni lo retrasa
    gestor._on_enunciado("yo", object(), 2.0)
    assert tr.encolados == [("yo", 1.0, {}), ("yo", 2.0, {})]
    assert "eco_audio" in registro.RUTA_LOG.read_text(encoding="utf-8")


def test_iniciar_audio_conecta_el_detector_de_eco_solo_con_el_filtro_activo(tmp_path, monkeypatch):
    recibido = {}

    class CapturaEspia(CapturaNula):
        def __init__(self, *a, **k):
            recibido.update(k)

    g, _modelo, cfg = gestor_con_audio(tmp_path, monkeypatch)
    monkeypatch.setattr("apuntes.audio.Captura", CapturaEspia)
    asyncio.run(iniciar_y_esperar(g, PROYECTO, "Tema ficticio", 5, None, []))
    g.transcriptor.detener()
    assert g.sesion.filtrar_eco is True and g._eco_audio is not None
    assert recibido.get("on_bloque") == g._eco_audio.bloque   # la captura le pasa los niveles de cada bloque


def test_estado_ligero_lleva_el_audio_aplazado(gestor, reloj):
    gestor.transcriptor = Transcriptor2(reloj, aplazado_s=7.26)
    assert gestor.estado_ligero()["transcripcion"]["aplazado_s"] == 7.3


# ================================================================ cola con prioridades: rezagados, saturación y eco descartado
class Transcriptor3(Transcriptor2):
    """Como el doble de siempre, pero con `tomar_descartes` (se vacía al leerlo, como el real)."""

    def __init__(self, *a, descartes=(), **k):
        super().__init__(*a, **k)
        self.descartes = list(descartes)

    def tomar_descartes(self):
        d, self.descartes = self.descartes, []
        return d


def incidencias_eco(gestor):
    return [i for i in gestor.sesion.incidencias if "eco de los altavoces" in i]


def test_estado_ligero_lleva_retraso_de_reunion_rezagado_y_eco_descartado(gestor, reloj):
    gestor.transcriptor = Transcriptor2(reloj, retraso_reunion_s=4.26, rezagado_s=33.33, eco_descartado_s=7.77)
    tr = gestor.estado_ligero()["transcripcion"]
    assert tr["retraso_reunion_s"] == 4.3 and tr["rezagado_s"] == 33.3 and tr["eco_descartado_s"] == 7.8


def test_estado_ligero_con_un_doble_sin_los_campos_de_la_cola_nueva_los_deja_a_cero(gestor):
    gestor.transcriptor = SimpleNamespace(estado="listo", error="", pendiente_s=1.0, velocidad_x=None)
    tr = gestor.estado_ligero()["transcripcion"]
    assert tr["retraso_reunion_s"] == 0.0 and tr["rezagado_s"] == 0.0 and tr["eco_descartado_s"] == 0.0


def test_snapshot_ordena_los_segmentos_por_minuto_y_no_toca_el_orden_de_llegada(gestor):
    s = gestor.sesion
    a = s.agregar_segmento(30.0, "reunion", "Segunda cosa que se dijo, llegada primero.")
    b = s.agregar_segmento(10.0, "reunion", "Primera cosa que se dijo, llegada después.")
    c = s.agregar_segmento(10.0, "yo", "Micro en el mismo minuto que la anterior.")
    assert [x["id"] for x in gestor.snapshot()["segmentos"]] == [b.id, c.id, a.id]   # por (t, id)
    assert [x.id for x in s.segmentos] == [a.id, b.id, c.id]                          # la sesión sigue en orden de llegada
    assert (a.id, b.id, c.id) == (1, 2, 3)                                            # y los id no cambian


def test_vigilar_saturacion_dice_el_tramo_de_la_reunion_y_vacia_los_descartes_pendientes(gestor, reloj):
    gestor.transcriptor = Transcriptor3(reloj, perdidos_s=30.0, ultimo_fallo="saturación",
                                        descartes=[("reunion", 125.0, 20.0, "saturacion"), ("yo", 160.0, 10.0, "saturacion")])
    assert gestor._vigilar_transcripcion() is True
    assert gestor.sesion.incidencias[0].endswith("transcripción: 30 s de audio sin transcribir (saturación, entre 02:05 y 02:50)")
    assert gestor._descartes_sat == [] and gestor.avisos == [G.TEXTO_AUDIO_PERDIDO] and len(avisos_ev(gestor)) == 1
    (linea,) = lineas_log()
    assert linea.endswith("transcripcion audio_perdido=30.0s total=30.0s tipo=saturación saturacion=30.0s")
    gestor.transcriptor.perdidos_s = 34.0   # un fallo posterior ya no arrastra el tramo de la saturación anterior
    gestor.transcriptor.ultimo_fallo = "RuntimeError"
    gestor._vigilar_transcripcion(forzar=True)
    assert gestor.sesion.incidencias[1].endswith("transcripción: 4 s de audio sin transcribir (RuntimeError)")


def test_vigilar_saturacion_y_fallo_a_la_vez_dicen_cuanto_es_de_cada_cosa(gestor, reloj):
    gestor.transcriptor = Transcriptor3(reloj, perdidos_s=40.0, ultimo_fallo="MemoryError", descartes=[("reunion", 300.0, 30.0, "saturacion")])
    assert gestor._vigilar_transcripcion() is True
    assert gestor.sesion.incidencias[0].endswith(
        "transcripción: 40 s de audio sin transcribir (30 s por saturación, entre 05:00 y 05:30, y 10 s por fallo del tipo MemoryError)")
    assert lineas_log()[0].endswith("tipo=MemoryError saturacion=30.0s")


def test_vigilar_saturacion_espera_su_turno_y_acumula_el_intervalo(gestor, reloj):
    tr = gestor.transcriptor = Transcriptor3(reloj, perdidos_s=10.0, ultimo_fallo="saturación", descartes=[("reunion", 60.0, 10.0, "saturacion")])
    gestor._vigilar_transcripcion()
    tr.perdidos_s, tr.descartes = 25.0, [("reunion", 90.0, 15.0, "saturacion")]
    assert gestor._vigilar_transcripcion() is False and len(gestor.sesion.incidencias) == 1   # dentro de AVISO_FALLO_CADA_S
    tr.descartes.append(("reunion", 200.0, 0.0, "saturacion"))
    gestor._vigilar_transcripcion(forzar=True)
    assert gestor.sesion.incidencias[1].endswith("transcripción: 15 s de audio sin transcribir (saturación, entre 01:30 y 03:20)")


def test_vigilar_eco_descartado_deja_una_incidencia_sin_aviso_y_la_actualiza_en_su_sitio(gestor, reloj):
    tr = gestor.transcriptor = Transcriptor3(reloj, descartes=[("yo", 100.0, 20.0, "eco")])
    assert gestor._vigilar_transcripcion() is True
    (inc,) = incidencias_eco(gestor)
    assert inc.endswith("transcripción: 20 s de audio del micro que parecía eco de los altavoces no se han transcrito (entre 01:40 y 02:00)")
    assert gestor.avisos == [] and avisos_ev(gestor) == [] and gestor.transcriptor.perdidos_s == 0.0   # no es audio perdido: sin aviso de interfaz
    assert lineas_log()[-1].endswith("transcripcion eco_descartado=20.0s total=20.0s")
    prefijo = inc.split("]")[0]
    gestor.sesion.incidencias.insert(0, "[00:01] otra: cosa")   # la incidencia se localiza por su texto, no por su posición
    tr.descartes = [("yo", 200.0, 10.0, "eco")]
    assert gestor._vigilar_transcripcion() is False and incidencias_eco(gestor) == [inc]   # como mucho una vez por minuto
    reloj.t += G.ACTUALIZAR_ECO_CADA_S
    assert gestor._vigilar_transcripcion() is True
    (nueva,) = incidencias_eco(gestor)
    assert nueva.startswith(prefijo + "]") and "30 s de audio del micro" in nueva and nueva.endswith("(entre 01:40 y 03:30)")
    assert gestor.sesion.incidencias[0] == "[00:01] otra: cosa" and len(gestor.sesion.incidencias) == 2   # sustituida, no repetida
    assert lineas_log()[-1].endswith("transcripcion eco_descartado=10.0s total=30.0s")


def test_vigilar_eco_forzado_actualiza_ya_y_si_la_incidencia_ya_no_esta_la_vuelve_a_poner(gestor, reloj):
    tr = gestor.transcriptor = Transcriptor3(reloj, descartes=[("yo", 10.0, 5.0, "eco")])
    gestor._vigilar_transcripcion()
    gestor.sesion.incidencias.clear()
    tr.descartes = [("yo", 40.0, 5.0, "eco")]
    assert gestor._vigilar_transcripcion() is False and gestor.sesion.incidencias == []   # dentro del minuto: queda pendiente
    assert gestor._vigilar_transcripcion(forzar=True) is True
    (inc,) = incidencias_eco(gestor)
    assert "10 s de audio del micro" in inc and inc.endswith("(entre 00:10 y 00:45)")


def test_un_doble_sin_tomar_descartes_no_rompe_la_vigilancia(gestor, reloj):
    gestor.transcriptor = Transcriptor2(reloj, perdidos_s=2.0, ultimo_fallo="ValueError")
    assert gestor._vigilar_transcripcion() is True
    assert gestor.sesion.incidencias[0].endswith("(ValueError)") and incidencias_eco(gestor) == []


def test_vigilar_linea_de_diagnostico_con_los_campos_de_la_cola_nueva(gestor, reloj):
    gestor._eco_audio = None
    gestor.transcriptor = Transcriptor2(reloj, retraso_s=20.4, pendiente_s=33.0, velocidad_x=0.83, alcance=True, reintentos=2, perdidos_s=0.0,
                                        retraso_reunion_s=18.2, rezagado_s=40.0, eco_descartado_s=12.0, aplazado_s=3.0,
                                        latencias={"reunion": 6.4, "yo": 11.6})
    assert gestor._vigilar_transcripcion() is True
    (linea,) = lineas_log()
    assert linea.endswith("transcripcion retraso=20s cola=33s vel=0.8x rapido=True reintentos=2 perdidos=0s aplazado=3s "
                          "ret_reunion=18s rezagado=40s eco_descartado=12s lat_reunion=6s lat_micro=12s nucleos=- cpu_equipo=-")


def test_vigilar_con_audio_rezagado_registra_aunque_el_retraso_sea_bajo(gestor, reloj):
    gestor.transcriptor = Transcriptor2(reloj, retraso_s=1.0, rezagado_s=25.0)
    assert gestor._vigilar_transcripcion() is True
    assert "retraso=1s" in lineas_log()[0] and "rezagado=25s" in lineas_log()[0]
    assert gestor._vigilar_transcripcion() is False   # y con el mismo límite de una cada REGISTRO_RETRASO_CADA_S
    reloj.t += G.REGISTRO_RETRASO_CADA_S
    assert gestor._vigilar_transcripcion() is True and len(lineas_log()) == 2


def test_vigilar_sin_rezagado_y_con_retraso_bajo_sigue_sin_registrar(gestor, reloj):
    gestor.transcriptor = Transcriptor2(reloj, retraso_s=1.0, rezagado_s=0.0)
    assert gestor._vigilar_transcripcion() is False and lineas_log() == []


def test_esperar_deja_una_linea_de_resumen_solo_con_medidas(gestor, reloj):
    gestor.sesion.agregar_segmento(5.0, "yo", SECRETO)
    gestor.transcriptor = Transcriptor2(reloj, audio_total_s=300.0, calculo_total_s=250.0, latencia_max={"reunion": 14.2, "yo": 6.0},
                                        rezagado_total_s=20.0, perdidos_s=0.0, eco_descartado_s=8.0, tramos_aplazados=5, tramos_rezagados=2,
                                        reintentos=1)
    esperar(gestor)
    (linea,) = lineas_log("transcripcion resumen")
    assert linea.endswith("transcripcion resumen audio=300s calculo=250s vel_media=1.2x lat_max_reunion=14s lat_max_micro=6s rezagado_total=20s "
                          "perdidos=0s eco_descartado=8s aplazados=5 rezagados=2 reintentos=1 nucleos=- hilos=- prioridad=normal prompt_med=-")
    assert SECRETO not in registro.RUTA_LOG.read_text(encoding="utf-8")


class EcoConDiagnostico:
    """Doble del detector con contadores fijos."""

    def __init__(self, diag):
        self.diag = diag

    def diagnostico(self):
        return self.diag


DIAG_ECO = {"eval": 12, "eco": 3, "fuertes": 2, "sin_ref": 1, "motivos": {"correlacion_baja": 5, "voz_no_explicada": 3, "tramo_corto": 1},
            "rho": [4, 3, 2, 1, 2], "disp": [0, 1, 1, 1, 0], "exceso": [1, 1, 1, 0, 0]}


def test_la_linea_periodica_lleva_al_final_lo_evaluado_y_lo_marcado_si_hay_detector(gestor, reloj):
    gestor._eco_audio = EcoConDiagnostico(DIAG_ECO)
    gestor.transcriptor = Transcriptor2(reloj, retraso_s=20.4, pendiente_s=33.0, velocidad_x=0.83, alcance=True, reintentos=2, perdidos_s=0.0)
    assert gestor._vigilar_transcripcion() is True
    (linea,) = lineas_log()
    assert linea.endswith("lat_reunion=- lat_micro=- eco_eval=12 eco_marc=3 nucleos=- cpu_equipo=-")


def test_la_linea_periodica_no_lleva_eco_si_no_hay_detector_ni_si_este_falla(gestor, reloj):
    for det in (None, EcoFijo(True)):                                        # EcoFijo no tiene `diagnostico`
        gestor._eco_audio = det
        assert gestor._sufijo_eco() == ""
    assert gestor._diagnostico_eco() is None


def test_esperar_deja_una_linea_de_diagnostico_del_eco_solo_con_numeros(gestor, reloj):
    gestor.sesion.tema = SECRETO
    gestor._eco_audio = EcoConDiagnostico(DIAG_ECO)
    gestor.transcriptor = Transcriptor2(reloj, lambda t: 0.0)
    esperar(gestor)
    (linea,) = lineas_log("eco diagnostico")
    assert linea.endswith("eco diagnostico eval=12 eco=3 fuertes=2 sin_ref=1 motivos=correlacion_baja:5,voz_no_explicada:3,tramo_corto:1 "
                          "rho=4/3/2/1/2 disp=0/1/1/1/0 exceso=1/1/1/0/0")
    assert SECRETO not in registro.RUTA_LOG.read_text(encoding="utf-8")


def test_esperar_no_deja_diagnostico_del_eco_sin_detector_o_sin_tramos_evaluados(gestor, reloj):
    gestor.transcriptor = Transcriptor2(reloj, lambda t: 0.0)
    gestor._eco_audio = None
    esperar(gestor)
    gestor._eco_audio = EcoConDiagnostico({**DIAG_ECO, "eval": 0})
    esperar(gestor)
    assert lineas_log("eco diagnostico") == []


def test_esperar_con_detector_real_sin_tramos_evaluados_no_deja_diagnostico(gestor, reloj):
    gestor.transcriptor = Transcriptor2(reloj, lambda t: 0.0)
    esperar(gestor)
    assert lineas_log("eco diagnostico") == []


def test_esperar_sin_audio_transcrito_no_deja_resumen(gestor, reloj):
    gestor.transcriptor = Transcriptor2(reloj)
    esperar(gestor)
    assert lineas_log("transcripcion resumen") == []


def test_esperar_con_resto_de_eco_dice_cuanto_era_eco_en_una_sola_frase(gestor, reloj, monkeypatch):
    monkeypatch.setattr(G, "ESPERA_COLA_SIN_AVANCE_S", 2.0)
    gestor.transcriptor = Transcriptor2(reloj, lambda t: 12.4, aplazado_s=5.0)
    esperar(gestor)
    assert gestor.sesion.incidencias[0].endswith(
        "transcripción incompleta: 12 s de audio sin transcribir al terminar, de los que 5 s eran audio del micro que parecía eco de los altavoces")
    assert gestor.avisos == ["La transcripción está incompleta: quedaron 12 s de audio sin transcribir al terminar, "
                             "de los que 5 s eran audio del micro que parecía eco de los altavoces."]
    assert "(" not in gestor.avisos[0]


def test_esperar_con_resto_sin_eco_importante_deja_el_texto_de_siempre(gestor, reloj, monkeypatch):
    monkeypatch.setattr(G, "ESPERA_COLA_SIN_AVANCE_S", 2.0)
    gestor.transcriptor = Transcriptor2(reloj, lambda t: 12.4, aplazado_s=1.0)
    esperar(gestor)
    assert gestor.sesion.incidencias[0].endswith("transcripción incompleta: 12 s de audio sin transcribir al terminar")


def test_reiniciar_la_reunion_borra_los_descartes_y_la_incidencia_de_eco(gestor, reloj):
    gestor.transcriptor = Transcriptor3(reloj, descartes=[("yo", 10.0, 5.0, "eco")])
    gestor._vigilar_transcripcion()
    assert gestor._eco_total_s == 5.0 and gestor._eco_texto
    gestor._reiniciar_descartes()
    assert gestor._eco_total_s == 0.0 and gestor._eco_texto is None and gestor._descartes_sat == [] and gestor._descartes_eco == []


# ================================================================ sesion.render: la transcripción del .md va por minuto
def test_render_escribe_la_transcripcion_por_minuto_con_segmentos_llegados_fuera_de_orden(gestor):
    s = gestor.sesion
    s.agregar_segmento(125.0, "reunion", "Tercera frase de la reunión ficticia.")
    s.agregar_segmento(5.0, "reunion", "Primera frase de la reunión ficticia.")
    s.agregar_segmento(65.0, "yo", "Segunda frase del micro ficticio.")
    s.agregar_segmento(65.0, "reunion", "Segunda frase de la reunión ficticia.")
    lineas = s.render().split("## Transcripción\n\n")[1].splitlines()
    assert [l[:7] for l in lineas] == ["[00:05]", "[01:05]", "[01:05]", "[02:05]"]
    assert "Micro" in lineas[1] and "Reunión" in lineas[2]                       # mismo minuto: por orden de llegada (id)
    assert [x.t for x in s.segmentos] == [125.0, 5.0, 65.0, 65.0]               # la sesión no se reordena


# ================================================================ capacidad: prioridad del proceso mientras se captura
@pytest.fixture
def prioridades(monkeypatch):
    """Sustituye la llamada a la API de prioridad por un espía: anota `activa` y dice que sí."""
    llamadas = []
    monkeypatch.setattr(G, "prioridad_de_reunion", lambda activa, kernel32=None, clase_normal=None: llamadas.append(activa) or True)
    monkeypatch.setattr(G.os, "cpu_count", lambda: 16)                              # Whisper (6 hilos) deja la mitad de los núcleos: la prioridad se sube
    monkeypatch.setattr(G, "clase_de_prioridad", lambda kernel32=None: 0x20)
    return llamadas


def gestor_en_marcha(tmp_path, monkeypatch, config=None):
    g, _modelo, _cfg = gestor_con_audio(tmp_path, monkeypatch, config)
    asyncio.run(iniciar_y_esperar(g, PROYECTO, "Tema ficticio", 5, None, []))
    g.transcriptor.detener()
    g.eventos = []
    g._emitir = g.eventos.append
    return g


def terminar_sin_revision(g):
    async def sin_revision():
        return None
    g._generar_revision = sin_revision
    return asyncio.run(g.terminar())


def lineas_energia():
    return [l.split("] ", 1)[1] for l in lineas_log("energia ")]


def test_al_empezar_la_captura_se_sube_la_prioridad_y_se_anota(tmp_path, monkeypatch, prioridades):
    g = gestor_en_marcha(tmp_path, monkeypatch)
    assert prioridades == [True] and g._prioridad_alta is True
    assert lineas_energia() == ["energia prioridad=alta"]


def test_al_terminar_se_baja_despues_de_vaciar_la_cola_y_se_anota(tmp_path, monkeypatch, prioridades):
    g = gestor_en_marcha(tmp_path, monkeypatch)
    visto = []
    esperar_real = g._esperar_transcripcion

    async def esperar():
        visto.append(list(prioridades))        # mientras se vacía la cola de transcripción sigue alta
        await esperar_real()
    g._esperar_transcripcion = esperar
    terminar_sin_revision(g)
    assert visto == [[True]]
    assert prioridades == [True, False] and g._prioridad_alta is False
    assert lineas_energia() == ["energia prioridad=alta", "energia prioridad=normal"]


def test_si_el_cierre_falla_la_prioridad_se_baja_igualmente(tmp_path, monkeypatch, prioridades):
    g = gestor_en_marcha(tmp_path, monkeypatch)

    async def falla():
        raise RuntimeError("cola rota")
    g._esperar_transcripcion = falla
    with pytest.raises(RuntimeError, match="cola rota"):
        terminar_sin_revision(g)
    assert prioridades == [True, False] and g._prioridad_alta is False
    assert lineas_energia()[-1] == "energia prioridad=normal"


def test_con_el_ajuste_en_false_no_se_toca_nada(tmp_path, monkeypatch, prioridades):
    g = gestor_en_marcha(tmp_path, monkeypatch, {"prioridad_reunion": False})
    assert prioridades == [] and g._prioridad_alta is False
    terminar_sin_revision(g)
    assert prioridades == [] and lineas_energia() == []


def test_si_la_api_dice_que_no_no_se_anota_ni_se_baja(tmp_path, monkeypatch):
    llamadas = []
    monkeypatch.setattr(G, "prioridad_de_reunion", lambda activa, kernel32=None, clase_normal=None: llamadas.append(activa) or False)
    monkeypatch.setattr(G.os, "cpu_count", lambda: 16)
    g = gestor_en_marcha(tmp_path, monkeypatch)
    terminar_sin_revision(g)
    assert llamadas == [True] and lineas_energia() == [] and g._prioridad_alta is False


def test_un_fallo_de_la_api_nunca_rompe_la_reunion(tmp_path, monkeypatch):
    def rota(activa, kernel32=None, clase_normal=None):
        raise OSError("sin permiso")
    monkeypatch.setattr(G, "prioridad_de_reunion", rota)
    monkeypatch.setattr(G.os, "cpu_count", lambda: 16)
    g = gestor_en_marcha(tmp_path, monkeypatch)
    assert g._prioridad_alta is False
    terminar_sin_revision(g)


def test_apagar_la_app_devuelve_la_prioridad_a_normal(tmp_path, monkeypatch, prioridades):
    g = gestor_en_marcha(tmp_path, monkeypatch)
    g.apagar()
    assert prioridades == [True, False]


def test_reunion_y_dictado_comparten_la_prioridad_y_solo_baja_la_ultima(tmp_path, monkeypatch, prioridades):
    g, _modelo, _cfg = gestor_con_audio(tmp_path, monkeypatch)
    g._prioridad_dictado(True)
    g._subir_prioridad("reunion")
    assert prioridades == [True]               # la segunda petición no vuelve a llamar
    g._bajar_prioridad("reunion")
    assert prioridades == [True] and g._prioridad_alta is True    # el dictado sigue abierto
    g._prioridad_dictado(False)
    assert prioridades == [True, False] and g._prioridad_alta is False
    g._prioridad_dictado(False)                # bajar de más no hace nada
    assert prioridades == [True, False]


def test_el_gestor_le_da_su_funcion_de_prioridad_al_dictado(tmp_path, monkeypatch, prioridades):
    from test_contexto_reunion import dictado_falso
    g, _modelo, _cfg = gestor_con_audio(tmp_path, monkeypatch)
    assert g.dictado._prioridad == g._prioridad_dictado
    d, piezas, _ = dictado_falso()
    d._prioridad = g._prioridad_dictado
    d.iniciar()
    assert prioridades == [True]
    d.detener()
    assert prioridades == [True, False]


def test_el_dictado_baja_la_prioridad_al_cancelar_y_no_la_sube_si_el_micro_falla():
    from test_contexto_reunion import dictado_falso
    eventos = []
    d, piezas, _ = dictado_falso()
    d._prioridad = eventos.append
    d.iniciar()
    d.cancelar()
    d.cancelar()
    assert eventos == [True, False]
    d2, _p2, _ = dictado_falso(errores={"yo": "sin micro"})
    d2._prioridad = eventos.append
    with pytest.raises(ValueError):
        d2.iniciar()
    assert eventos == [True, False]            # ni subió ni bajó


@pytest.mark.parametrize("nucleos,hilos,sube", [(8, 4, True), (8, 6, False), (2, 2, False), (8, 1, True), (8, 0, False)])
def test_la_prioridad_solo_se_sube_si_whisper_deja_la_mitad_de_los_nucleos(tmp_path, monkeypatch, prioridades, nucleos, hilos, sube):
    monkeypatch.setattr(G.os, "cpu_count", lambda: nucleos)
    g, _modelo, _cfg = gestor_con_audio(tmp_path, monkeypatch, {"whisper_hilos": hilos, "whisper_hilos_auto": False})
    g._subir_prioridad("reunion")
    assert prioridades == ([True] if sube else []) and g._prioridad_alta is sube


def test_al_bajar_se_restaura_la_clase_que_tenia_el_proceso(tmp_path, monkeypatch):
    destinos = []
    monkeypatch.setattr(G, "prioridad_de_reunion", lambda activa, kernel32=None, clase_normal=None: destinos.append((activa, clase_normal)) or True)
    monkeypatch.setattr(G.os, "cpu_count", lambda: 16)
    monkeypatch.setattr(G, "clase_de_prioridad", lambda kernel32=None: 0x4000)      # BELOW_NORMAL
    g, _modelo, _cfg = gestor_con_audio(tmp_path, monkeypatch)
    g._subir_prioridad("reunion")
    g._bajar_prioridad("reunion")
    assert destinos == [(True, None), (False, 0x4000)] and g._prioridad_clase_original is None
    monkeypatch.setattr(G, "clase_de_prioridad", lambda kernel32=None: None)        # no se pudo leer: al bajar, NORMAL (clase_normal=None)
    destinos.clear()
    g._subir_prioridad("reunion")
    g._bajar_prioridad("reunion")
    assert destinos == [(True, None), (False, None)]


@pytest.mark.parametrize("clase", [0x8000, 0x80, 0x100])
def test_si_el_proceso_ya_tiene_prioridad_alta_no_se_toca_nada(tmp_path, monkeypatch, prioridades, clase):
    monkeypatch.setattr(G, "clase_de_prioridad", lambda kernel32=None: clase)
    g, _modelo, _cfg = gestor_con_audio(tmp_path, monkeypatch)
    g._subir_prioridad("reunion")
    g._bajar_prioridad("reunion")
    assert prioridades == [] and g._prioridad_alta is False and lineas_energia() == []


def test_la_prioridad_no_se_sube_si_falla_construir_la_captura(tmp_path, monkeypatch, prioridades):
    class CapturaRota(CapturaNula):
        def __init__(self, *a, **k):
            raise OSError("sin dispositivo")
    g, _modelo, _cfg = gestor_con_audio(tmp_path, monkeypatch)
    monkeypatch.setattr("apuntes.audio.Captura", CapturaRota)
    with pytest.raises(OSError):
        asyncio.run(g._iniciar_audio("Tema ficticio"))
    assert prioridades == [] and g._prioridad_alta is False


def test_la_prioridad_no_se_sube_si_la_captura_no_arranca(tmp_path, monkeypatch, prioridades):
    class CapturaQueNoArranca(CapturaNula):
        def iniciar(self):
            raise OSError("sin micro")
    g, _modelo, _cfg = gestor_con_audio(tmp_path, monkeypatch)
    monkeypatch.setattr("apuntes.audio.Captura", CapturaQueNoArranca)
    asyncio.run(g._iniciar_audio("Tema ficticio"))
    assert prioridades == [] and any("No se pudo abrir el audio" in a for a in g.avisos)
    g.transcriptor.detener()


def test_un_dictado_cancelado_mientras_inicia_no_sube_la_prioridad():
    from test_contexto_reunion import CapturaFalsa, Config, Dictado, Path, TranscriptorFalso
    eventos = []

    class CapturaQueSeCancela(CapturaFalsa):
        def iniciar(self):
            d.cancelar()                         # otro hilo cancela justo mientras se abre el micro
    d = Dictado(Config(Path("no-existe.json")), lambda e: None, None, lambda *a: CapturaQueSeCancela(*a), TranscriptorFalso, eventos.append)
    d.iniciar()
    assert eventos == [] and d.estado == "parado" and d._captura is None and d._transcriptor is None


def test_un_dictado_que_llega_a_su_tope_baja_la_prioridad_aunque_siga_abierto(monkeypatch):
    from apuntes import dictado as DI
    from test_contexto_reunion import dictado_falso
    monkeypatch.setattr(DI, "MAX_DICTADO_S", -1)
    eventos, avisos = [], []
    d, piezas, _ = dictado_falso(emitir=avisos.append)
    d._prioridad = eventos.append
    d.iniciar()
    fin = time.time() + 5
    while time.time() < fin and not any("10 minutos" in (a.get("error") or "") for a in avisos):
        time.sleep(0.02)
    assert piezas["cap"].pausada is True and d.estado == "dictando"
    assert eventos == [True, False]
    d.detener()
    assert eventos == [True, False]            # al parar no vuelve a bajar


def test_un_fallo_al_cambiar_la_prioridad_no_rompe_el_dictado():
    from test_contexto_reunion import dictado_falso

    def rota(activa):
        raise RuntimeError("raro")
    d, piezas, _ = dictado_falso()
    d._prioridad = rota
    assert d.iniciar()["estado"] == "dictando"
    assert d.detener()["estado"] == "parado"


# ================================================================ capacidad: núcleos y CPU del equipo en el registro
def test_la_linea_periodica_lleva_los_nucleos_y_la_cpu_del_equipo_del_intervalo(gestor, reloj, monkeypatch):
    gestor._eco_audio = None
    gestor._muestra_capacidad = (0.0, 0.0, (10.0, 20.0))                     # lectura anterior: (ocupado_s, total_s)
    monkeypatch.setattr(G, "tiempos_del_equipo", lambda kernel32=None: (19.0, 30.0))
    tr = gestor.transcriptor = Transcriptor2(reloj, retraso_s=20.0, cpu_total_s=8.4, calculo_total_s=4.0)
    assert gestor._vigilar_transcripcion() is True
    assert lineas_log()[-1].endswith(" nucleos=2.1 cpu_equipo=90")
    # segunda línea: solo cuenta lo que pasó desde la primera
    reloj.t += G.REGISTRO_RETRASO_CADA_S
    monkeypatch.setattr(G, "tiempos_del_equipo", lambda kernel32=None: (22.0, 40.0))
    tr.cpu_total_s, tr.calculo_total_s = 8.4 + 3.0, 4.0 + 3.0
    assert gestor._vigilar_transcripcion() is True
    assert lineas_log()[-1].endswith(" nucleos=1.0 cpu_equipo=30")


def test_sin_calculo_en_el_intervalo_o_sin_lectura_del_equipo_hay_guiones(gestor, reloj, monkeypatch):
    gestor._eco_audio = None
    gestor._muestra_capacidad = (5.0, 4.0, None)
    gestor.transcriptor = Transcriptor2(reloj, retraso_s=20.0, cpu_total_s=5.0, calculo_total_s=4.0)    # nada de cálculo desde la línea anterior
    assert gestor._vigilar_transcripcion() is True
    assert lineas_log()[-1].endswith(" nucleos=- cpu_equipo=-")


def test_la_cpu_del_equipo_nunca_lleva_texto_de_la_reunion(gestor, reloj):
    gestor.sesion.agregar_segmento(5.0, "yo", SECRETO)
    gestor.transcriptor = Transcriptor2(reloj, retraso_s=20.0)
    gestor._vigilar_transcripcion()
    assert SECRETO not in registro.RUTA_LOG.read_text(encoding="utf-8")


def test_el_resumen_lleva_nucleos_hilos_prioridad_prompt_y_demanda():
    tr = Transcriptor2(None, audio_total_s=300.0, calculo_total_s=250.0, cpu_total_s=525.0, hilos=4, prompt_chars_total=9000, prompt_llamadas=30,
                       audio_recibido_s=420.0, latencia_max={"reunion": 14.2, "yo": 6.0}, rezagado_total_s=20.0, perdidos_s=0.0,
                       eco_descartado_s=8.0, tramos_aplazados=5, tramos_rezagados=2, reintentos=1)
    G.Gestor._registrar_resumen_transcripcion(tr, 300.0, "alta")
    (linea,) = lineas_log("transcripcion resumen")
    assert linea.endswith("aplazados=5 rezagados=2 reintentos=1 nucleos=2.1 hilos=4 prioridad=alta prompt_med=300 demanda=1.40")
    assert "transcripcion resumen audio=300s calculo=250s vel_media=1.2x" in linea


def test_el_resumen_sin_duracion_ni_datos_no_inventa_nada():
    tr = Transcriptor2(None, audio_total_s=60.0, calculo_total_s=30.0)
    G.Gestor._registrar_resumen_transcripcion(tr)
    (linea,) = lineas_log("transcripcion resumen")
    assert linea.endswith("reintentos=0 nucleos=- hilos=- prioridad=normal prompt_med=-") and "demanda" not in linea


def test_esperar_registra_la_prioridad_real_del_gestor_en_el_resumen(gestor, reloj):
    gestor._prioridad_alta = True
    gestor.transcriptor = Transcriptor2(reloj, audio_total_s=60.0, calculo_total_s=30.0, cpu_total_s=60.0, hilos=4)
    esperar(gestor)
    (linea,) = lineas_log("transcripcion resumen")
    assert "nucleos=2.0 hilos=4 prioridad=alta" in linea
