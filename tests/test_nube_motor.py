"""Política de la nube (apuntes/motor_nube.py): decisión, reintento, respaldo, cortacircuitos, bloqueo, pistas y contadores.
Reloj, `dormir` y fábrica de cliente falsos: sin red, sin hilos, sin esperas."""
import json
from collections import deque

import pytest

from apuntes.motor_nube import (CIRCUITO_S, PLAZO_TROZO_S, Decision, MotorNube, NubeFallo, texto_aviso)
from apuntes.nube import NubeError, ResultadoNube

CLAVE = "sk-ficticia-0000000000"
CFG = {"transcripcion_motor": "nube", "nube_url_base": "https://api.openai.com/v1", "nube_modelo": "gpt-transcribe",
       "nube_autenticacion": "bearer", "nube_dialecto": "auto"}


class Reloj:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


class Fabrica:
    """Fábrica de clientes falsos con un guion compartido: cada llamada toma la siguiente respuesta (un `NubeError` se lanza)."""

    def __init__(self, reloj):
        self.reloj, self.respuestas, self.llamadas, self.creados, self.avance = reloj, deque(), [], [], 0.0

    def __call__(self, *args):
        self.creados.append(args)
        return ClienteGuion(self)

    def ok(self, texto="hola", ms=800):
        self.respuestas.append(ResultadoNube(texto, "es", None, ms, 32000))
        return self

    def error(self, causa, http=None, codigo="", retry_after=None):
        self.respuestas.append(NubeError(causa, http, codigo, retry_after))
        return self


class ClienteGuion:
    def __init__(self, fab):
        self.fab, self.cerrado = fab, False

    def transcribir(self, wav, **kw):
        self.fab.llamadas.append(kw)
        r = self.fab.respuestas.popleft() if self.fab.respuestas else ResultadoNube("x", "es", None, 500, 32000)
        if isinstance(r, NubeError):
            self.fab.reloj.t += self.fab.avance
            raise r
        return r

    def cerrar(self):
        self.cerrado = True


def _motor(cfg=None, clave=CLAVE, permitir=True):
    reloj = Reloj()
    fab = Fabrica(reloj)
    dormidos = []
    estado = {"clave": clave, "permitir": permitir}
    m = MotorNube(dict(cfg or CFG), lambda: estado["clave"], lambda: estado["permitir"], reloj=reloj, dormir=dormidos.append,
                  fabrica_cliente=fab, azar=lambda: 0.5)
    m.reloj_falso, m.fab, m.dormidos, m.estado_falso = reloj, fab, dormidos, estado
    return m


def _pedir(m, sonda=False, dur=2.0, prompt="tema", claves=("SAP",)):
    return m.transcribir(b"wav", dur, idiomas=["es"], prompt=prompt, palabras_clave=list(claves), rapido=False, sonda=sonda)


def _fallar(m, causa="servidor", http=503, **kw):
    """Un trozo que falla del todo (el reintento también falla)."""
    m.fab.error(causa, http, **kw).error(causa, http, **kw)
    with pytest.raises(NubeFallo) as e:
        _pedir(m)
    return e.value


# ---------------------------------------------------------------- decisión
def test_sin_clave_decide_local_y_emite_evento_una_vez():
    m = _motor(clave=None)
    assert m.decidir() == Decision("local", "sin_clave") and m.decidir() == Decision("local", "sin_clave")
    assert m.tomar_eventos() == [{"evento": "sin_clave"}] and m.tomar_eventos() == []
    assert m.publico()["estado"] == "sin_clave"


def test_solo_local_decide_local():
    m = _motor(permitir=False)
    assert m.decidir() == Decision("local", "solo_local") and m.decidir().motivo == "solo_local"
    assert m.tomar_eventos() == [{"evento": "solo_local"}]
    assert m.publico()["estado"] == "solo_local" and "solo local" in m.publico()["mensaje"]
    m.estado_falso["permitir"] = True   # al desactivarlo a mitad, el siguiente trozo vuelve a la nube
    assert m.decidir() == Decision("nube", "")


def test_motor_local_decide_local_motivo_config():
    m = _motor({**CFG, "transcripcion_motor": "local"})
    assert m.decidir() == Decision("local", "config") and m.tomar_eventos() == []
    assert m.publico() is None   # motor local y la nube nunca usada en esta reunión
    assert MotorNube({}, lambda: CLAVE).decidir() == Decision("local", "config")   # un config sin las claves nuevas se comporta como hoy


def test_decision_nube_normal():
    m = _motor()
    d = m.decidir()
    assert (d.motor, d.motivo, d.sonda) == ("nube", "", False)
    assert m.publico()["estado"] == "activa" and m.publico()["ms_medio"] is None and m.publico()["vuelve_en_s"] is None


# ---------------------------------------------------------------- reintentos
def test_reintenta_una_vez_500_y_acierta():
    m = _motor()
    m.fab.error("servidor", 500).ok("texto")
    r = _pedir(m)
    assert r.texto == "texto" and len(m.fab.llamadas) == 2
    assert (m.fallos, m.reintentos, m.trozos) == (1, 1, 1)
    assert m.dormidos == [0.5]   # 0,5 s × (0,75…1,25) con azar 0,5
    assert m.decidir().motor == "nube" and m.tomar_eventos() == []


def test_retry_after_corto_se_respeta():
    m = _motor()
    m.fab.error("tasa", 429, "rate_limit_exceeded", 2.0).ok()
    _pedir(m)
    assert m.dormidos == [2.0]


def test_retry_after_largo_no_reintenta_y_abre_circuito():
    m = _motor()
    m.fab.error("tasa", 429, "rate_limit_exceeded", 120.0)
    with pytest.raises(NubeFallo) as e:
        _pedir(m)
    assert e.value.error.causa == "tasa" and len(m.fab.llamadas) == 1 and m.dormidos == []
    assert m.decidir() == Decision("local", "circuito")
    [ev] = m.tomar_eventos()
    assert ev["evento"] == "circuito_abierto" and ev["causa"] == "tasa" and ev["vuelve_s"] == 120
    p = m.publico()
    assert p["estado"] == "respaldo" and p["vuelve_en_s"] == 120 and p["causa"] == "tasa" and "120 s" in p["mensaje"]
    m.reloj_falso.t += 119
    assert m.decidir().motivo == "circuito" and m.publico()["vuelve_en_s"] == 1
    m.reloj_falso.t += 1
    assert m.decidir() == Decision("nube", "", True)


def test_retry_after_enorme_se_acota_a_300s():
    m = _motor()
    m.fab.error("servidor", 503, "", 3600.0)
    with pytest.raises(NubeFallo):
        _pedir(m)
    assert m.publico()["vuelve_en_s"] == 300


def test_no_reintenta_si_el_primer_intento_tardo_mas_de_10s():
    m = _motor()
    m.fab.avance = 11.0
    m.fab.error("tiempo").ok()
    with pytest.raises(NubeFallo):
        _pedir(m)
    assert len(m.fab.llamadas) == 1 and m.dormidos == []


def test_un_error_no_reintentable_no_reintenta():
    m = _motor()
    m.fab.error("rechazo", 422).ok()
    with pytest.raises(NubeFallo):
        _pedir(m)
    assert len(m.fab.llamadas) == 1


def test_timeouts_segun_la_voz_y_la_sonda():
    m = _motor()
    _pedir(m, dur=2.0)
    assert (m.fab.llamadas[-1]["timeout_conexion"], m.fab.llamadas[-1]["timeout_lectura"]) == (5.0, 7.0)
    _pedir(m, dur=18.0)
    assert m.fab.llamadas[-1]["timeout_lectura"] == 12.0   # 6 + 0,5 · 18 = 15, acotado por el plazo total del trozo (12 s)
    _pedir(m, dur=100.0)
    assert m.fab.llamadas[-1]["timeout_lectura"] == 12.0   # tope de la lectura (20 s) y, antes, el plazo total (12 s)
    _pedir(m, sonda=True)
    assert m.fab.llamadas[-1]["timeout_conexion"] == 3.0


# ---------------------------------------------------------------- bloqueo
@pytest.mark.parametrize("causa,http,codigo", [("clave", 401, "invalid_api_key"), ("permiso", 403, ""), ("config", 404, ""),
                                               ("credito", 429, "insufficient_quota"), ("certificado", None, "")])
def test_causas_definitivas_bloquean_hasta_reiniciar(causa, http, codigo):
    m = _motor()
    m.fab.error(causa, http, codigo).ok()
    with pytest.raises(NubeFallo) as e:
        _pedir(m)
    assert e.value.error.definitiva and len(m.fab.llamadas) == 1   # sin reintento
    [ev] = m.tomar_eventos()
    assert (ev["evento"], ev["causa"], ev["http"], ev["codigo"]) == ("bloqueada", causa, http, codigo)
    for _ in range(3):
        assert m.decidir() == Decision("local", "bloqueada")
    p = m.publico()
    assert p["estado"] == "bloqueada" and p["causa"] == causa and p["mensaje"] and "{X}" not in p["mensaje"] and "Esta reunión" not in p["mensaje"]
    m.reiniciar()
    assert m.decidir() == Decision("nube", "") and m.bloqueos == 1


def test_429_credito_bloquea_429_tasa_no():
    m = _motor()
    m.fab.error("tasa", 429, "rate_limit_exceeded").error("tasa", 429, "rate_limit_exceeded")
    with pytest.raises(NubeFallo):
        _pedir(m)
    assert m.decidir().motor == "nube" and m.bloqueos == 0   # un trozo fallido solo no abre ni bloquea


def test_el_bloqueo_no_borra_los_contadores():
    m = _motor()
    _pedir(m)
    m.fab.error("clave", 401)
    with pytest.raises(NubeFallo):
        _pedir(m)
    m.reiniciar()
    assert m.trozos == 1 and m.bloqueos == 1


# ---------------------------------------------------------------- cortacircuitos
def test_dos_trozos_fallidos_abren_circuito_60s():
    m = _motor()
    _fallar(m)
    assert m.decidir().motor == "nube" and m.tomar_eventos() == []   # uno solo no abre
    _fallar(m)
    assert m.decidir() == Decision("local", "circuito")
    [ev] = m.tomar_eventos()
    assert (ev["evento"], ev["causa"], ev["fallos_seguidos"], ev["vuelve_s"]) == ("circuito_abierto", "servidor", 2, CIRCUITO_S[0])
    assert m.aperturas == 1 and m.fallos == 4   # cada trozo fallido ya incluye su reintento: cuatro intentos


def test_un_acierto_entre_dos_fallos_reinicia_la_cuenta():
    m = _motor()
    _fallar(m)
    _pedir(m)
    _fallar(m)
    assert m.decidir().motor == "nube"


def test_sonda_tras_60s_un_solo_intento_y_si_falla_duplica_hasta_300():
    m = _motor()
    _fallar(m)
    _fallar(m)
    m.tomar_eventos()
    esperados = [120, 240, 300, 300]
    espera = 60
    for siguiente in esperados:
        m.reloj_falso.t += espera - 1
        assert m.decidir().motivo == "circuito"
        m.reloj_falso.t += 1
        d = m.decidir()
        assert d == Decision("nube", "", True)
        antes, dormido = len(m.fab.llamadas), len(m.dormidos)
        m.fab.error("servidor", 503).ok()   # el segundo no se usa: la sonda es UN intento
        with pytest.raises(NubeFallo):
            _pedir(m, sonda=True)
        assert len(m.fab.llamadas) == antes + 1 and len(m.dormidos) == dormido
        m.fab.respuestas.clear()
        [ev] = m.tomar_eventos()
        assert ev["evento"] == "circuito_abierto" and ev["vuelve_s"] == siguiente
        espera = siguiente


def test_sonda_correcta_cierra_y_emite_restablecida():
    m = _motor()
    _fallar(m)
    _fallar(m)
    m.tomar_eventos()
    m.reloj_falso.t += 184
    assert m.decidir().sonda
    _pedir(m, sonda=True)
    assert m.tomar_eventos() == [{"evento": "restablecida", "tras_s": 184}]
    assert m.decidir() == Decision("nube", "") and m.publico()["estado"] == "activa"
    _fallar(m)   # tras restablecer, la cuenta de fallos y el nivel del circuito vuelven a empezar
    _fallar(m)
    assert m.tomar_eventos()[0]["vuelve_s"] == 60


def test_estado_sonda_cuando_vence_el_circuito():
    m = _motor()
    _fallar(m)
    _fallar(m)
    m.reloj_falso.t += 61
    assert m.publico()["estado"] == "sonda"


def test_audio_400_no_cuenta_para_el_circuito():
    m = _motor()
    for _ in range(5):
        m.fab.error("audio", 400, "invalid_audio")
        with pytest.raises(NubeFallo) as e:
            _pedir(m)
        assert e.value.error.causa == "audio"
    assert m.decidir() == Decision("nube", "") and m.aperturas == 0 and m.bloqueos == 0


def test_rechazo_si_cuenta_para_el_circuito():
    m = _motor()
    _fallar(m, "rechazo", 422)
    _fallar(m, "rechazo", 422)
    assert m.decidir().motivo == "circuito"


# ---------------------------------------------------------------- pistas
def test_pistas_400_reintenta_sin_prompt_ni_keywords():
    m = _motor()
    m.fab.error("pistas", 400, "invalid_prompt").ok("bien")
    r = _pedir(m, prompt="tema largo", claves=("SAP", "Fiori"))
    assert r.texto == "bien" and len(m.fab.llamadas) == 2
    assert (m.fab.llamadas[0]["prompt"], m.fab.llamadas[0]["palabras_clave"]) == ("tema largo", ["SAP", "Fiori"])
    assert (m.fab.llamadas[1]["prompt"], m.fab.llamadas[1]["palabras_clave"]) == ("", [])
    assert m.pistas_reintentos == 1 and m.reintentos == 0 and m.fallos == 0 and m.dormidos == []   # inmediato y sin gastar el reintento breve
    assert m.chars_prompt == 0   # nada de pistas llegó a salir con éxito


def test_tres_rechazos_de_pistas_las_apagan_en_la_sesion():
    m = _motor()
    for _ in range(3):
        m.fab.error("pistas", 400, "invalid_prompt").ok()
        _pedir(m)
    [ev] = m.tomar_eventos()
    assert ev == {"evento": "pistas_off", "rechazos": 3}
    _pedir(m)
    assert m.fab.llamadas[-1]["prompt"] == "" and m.fab.llamadas[-1]["palabras_clave"] == []   # ni siquiera se intenta
    m.reiniciar()
    _pedir(m)
    assert m.fab.llamadas[-1]["prompt"] == "tema"


def test_pistas_que_siguen_rechazadas_sin_pistas_son_un_rechazo():
    m = _motor()
    m.fab.error("pistas", 400).error("pistas", 400)
    with pytest.raises(NubeFallo) as e:
        _pedir(m)
    assert e.value.error.causa == "rechazo"


# ---------------------------------------------------------------- contadores, lote, resumen y publico
def test_contadores_y_lote_por_deltas():
    m = _motor()
    assert m.tomar_lote() is None
    _pedir(m, dur=4.0)
    _pedir(m, dur=6.0, prompt="abc", claves=("SAP",))
    m.anotar_respaldo(5.0)
    m.anotar_silencio()
    m.anotar_idioma_repetido()
    lote = m.tomar_lote()
    assert lote == {"trozos": 2, "audio_s": 10.0, "chars": len("tema") + len("SAP") + len("abc") + len("SAP"), "fallos": 0, "ok": True,
                    "modelo": "gpt-transcribe", "host": "api.openai.com"}
    assert m.tomar_lote() is None   # nada nuevo
    _pedir(m, dur=1.0)
    assert m.tomar_lote()["trozos"] == 1
    r = m.resumen()
    assert (r["trozos"], r["respaldo_trozos"], r["respaldo_s"], r["silencio_trozos"], r["idioma_repetidos"]) == (3, 1, 5, 1, 1)
    assert r["dialecto"] == "gpt-transcribe" and r["host"] == "api.openai.com" and r["ms_medio"] == 500 and r["kb"] == 93


def test_publico_y_lote_sin_contenido():
    m = _motor(clave="sk-ficticia-CENTINELA-DE-CLAVE")
    m.fab.ok("CENTINELA-DE-TEXTO")
    _pedir(m, prompt="CENTINELA-DE-PROMPT", claves=("CENTINELA-DE-KEYWORD",))
    m.fab.error("clave", 401, "invalid_api_key")
    with pytest.raises(NubeFallo):
        _pedir(m, prompt="CENTINELA-DE-PROMPT")
    volcado = json.dumps([m.publico(), m.tomar_lote(), m.resumen(), m.tomar_eventos()], ensure_ascii=False)
    for c in ("CENTINELA", "sk-ficticia", "wav"):
        assert c not in volcado
    assert "https://" not in volcado   # del host, solo el nombre


def test_publico_con_trozos():
    m = _motor()
    _pedir(m, dur=3.0)
    m.fab.ok(ms=1000)
    _pedir(m, dur=2.0)
    p = m.publico()
    assert (p["estado"], p["trozos"], p["audio_s"], p["ms_medio"], p["fallos"], p["respaldo_trozos"]) == ("activa", 2, 5.0, 750, 0, 0)
    assert p["causa"] == "" and p["mensaje"] == "" and p["vuelve_en_s"] is None
    m2 = _motor({**CFG, "transcripcion_motor": "local"})
    m2.anotar_respaldo(1.0)
    assert m2.publico() is not None   # motor local pero la nube se usó antes en esta reunión


def test_sin_clave_al_transcribir_no_cuenta_como_fallo():
    m = _motor()
    m.estado_falso["clave"] = None
    with pytest.raises(NubeFallo) as e:
        _pedir(m)
    assert e.value.error.causa == "sin_clave" and m.fallos == 0 and m.decidir().motivo == "sin_clave"


def test_anotar_sin_modelo_emite_evento():
    m = _motor()
    m.anotar_sin_modelo()
    assert m.tomar_eventos() == [{"evento": "respaldo_sin_modelo"}]


# ---------------------------------------------------------------- cliente
def test_cambio_de_url_recrea_cliente():
    cfg = dict(CFG)
    m = _motor(cfg)
    _pedir(m)
    _pedir(m)
    assert len(m.fab.creados) == 1   # se reutiliza mientras nada cambie
    primero = m._cliente
    m.config["nube_url_base"] = "https://eu.api.openai.com/v1"
    _pedir(m)
    assert len(m.fab.creados) == 2 and primero.cerrado and m.fab.creados[-1][0] == "https://eu.api.openai.com/v1"
    m.config["nube_modelo"] = "whisper-1"
    _pedir(m)
    m.config["nube_autenticacion"] = "api-key"
    _pedir(m)
    m.config["nube_dialecto"] = "clasico"
    _pedir(m)
    m.estado_falso["clave"] = "sk-ficticia-otra-clave-nueva"
    _pedir(m)
    assert len(m.fab.creados) == 6 and m.fab.creados[-1][2] == "sk-ficticia-otra-clave-nueva"
    m.cerrar()
    assert m._cliente is None


def test_fabrica_que_falla_por_valores_invalidos_es_config():
    def mala(*a):
        raise ValueError("url")
    m = MotorNube(dict(CFG), lambda: CLAVE, fabrica_cliente=mala)
    with pytest.raises(NubeFallo) as e:
        _pedir(m)
    assert e.value.error.causa == "config" and m.decidir() == Decision("local", "bloqueada")


# ---------------------------------------------------------------- probar
def test_probar_tono_un_intento():
    m = _motor()
    fab = Fabrica(Reloj())
    fab.respuestas.append(ResultadoNube("", "es", None, 812, 32000))
    r = MotorNube.probar({k: CFG[k] for k in CFG if k != "transcripcion_motor"}, CLAVE, fab)
    assert r == {"ok": True, "ms": 812, "modelo": "gpt-transcribe", "dialecto": "gpt-transcribe", "host": "api.openai.com", "idioma": "es"}
    assert len(fab.llamadas) == 1 and fab.llamadas[0]["prompt"] == "" and fab.llamadas[0]["palabras_clave"] == []
    fab.error("clave", 401, "invalid_api_key")
    r = MotorNube.probar({k: CFG[k] for k in CFG if k != "transcripcion_motor"}, CLAVE, fab)
    assert r == {"ok": False, "causa": "clave", "http": 401, "mensaje": "La nube rechaza la clave (401). Revisa la clave."}
    assert len(fab.llamadas) == 2   # sin reintentos
    r = MotorNube.probar(CFG, "", fab)
    assert r == {"ok": False, "causa": "sin_clave", "http": None, "mensaje": "No hay clave: escríbela o guárdala antes de probar."}
    assert len(fab.llamadas) == 2
    assert m.fab.llamadas == []   # el motor no interviene


def test_probar_cada_causa_tiene_mensaje_y_no_lleva_la_clave():
    for causa in ("clave", "permiso", "credito", "config", "certificado", "red", "tiempo", "servidor", "tasa", "audio", "rechazo", "bloqueada_pruebas"):
        fab = Fabrica(Reloj())
        fab.error(causa, 500)
        r = MotorNube.probar(CFG, CLAVE, fab)
        assert r["ok"] is False and r["causa"] == causa and r["mensaje"].endswith(".") and CLAVE not in json.dumps(r)


def test_textos_de_aviso():
    assert texto_aviso("clave").startswith("La nube rechaza la clave (401). Esta reunión sigue transcribiéndose en este equipo. Revisa la clave en Ajustes")
    assert texto_aviso("clave", con_reunion=False) == "La nube rechaza la clave (401). Revisa la clave en Ajustes › Audio."
    assert texto_aviso("circuito_abierto", 42) == "Sin conexión con la nube: la transcripción sigue en este equipo y se vuelve a probar en 42 s."
    assert texto_aviso("restablecida") == "Transcripción en la nube restablecida."


# ---------------------------------------------------------------- revisión crítica: plazo total, permiso entre intentos, cierre, estado local y lote
def test_plazo_total_cada_intento_recibe_lo_que_queda():
    m = _motor()
    m.fab.avance = 8.0
    m.fab.error("servidor", 503).error("servidor", 503)
    with pytest.raises(NubeFallo):
        _pedir(m)
    a, b = m.fab.llamadas
    assert (a["timeout_conexion"], a["timeout_lectura"], a["plazo_total"]) == (5.0, 7.0, 12.0)
    assert (b["timeout_conexion"], b["timeout_lectura"], b["plazo_total"]) == (4.0, 4.0, 4.0)   # al reintento solo le quedan 12 - 8 s


def test_si_quedan_menos_de_2_s_no_se_reintenta():
    m = _motor()
    m.fab.avance = 9.7
    m.fab.error("servidor", 503).ok()
    with pytest.raises(NubeFallo) as e:
        _pedir(m)
    assert len(m.fab.llamadas) == 1 and m.reintentos == 0 and m.fallos == 1 and e.value.error.causa == "servidor"


def test_un_trozo_lento_no_retiene_mas_del_plazo_con_reloj_y_dormir_inyectados():
    m = _motor()

    class ClienteLento:   # cada intento agota el tiempo que se le dio
        def transcribir(self, wav, **kw):
            m.reloj_falso.t += min(kw["timeout_lectura"], kw["plazo_total"])
            raise NubeError("tiempo")

        def cerrar(self):
            pass
    m.fabrica_cliente = lambda *a: ClienteLento()
    ini = m.reloj_falso.t
    with pytest.raises(NubeFallo):
        _pedir(m)
    assert m.reloj_falso.t - ini <= PLAZO_TROZO_S + 0.01 and len(m.dormidos) == 1   # intento + reintento, sin pasar de 12 s
    assert PLAZO_TROZO_S == 12.0


def test_el_plazo_lo_comparten_el_reintento_sin_pistas_y_la_repeticion():
    m = _motor()
    h = m.nuevo_plazo()
    m.fab.error("pistas", 400).ok()   # el rechazo de pistas reintenta al momento: sigue en el mismo plazo
    m.transcribir(b"wav", 2.0, idiomas=["es"], prompt="tema", palabras_clave=["SAP"], rapido=False, sonda=False, hasta=h)
    m.reloj_falso.t += 11   # queda 1 s
    with pytest.raises(NubeFallo):
        m.transcribir(b"wav", 2.0, idiomas=["es"], prompt="tema", palabras_clave=[], rapido=False, sonda=False, hasta=h, repeticion=True)
    assert len(m.fab.llamadas) == 2


def test_solo_local_entre_el_primer_intento_y_el_reintento_no_sube_nada_mas():
    m = _motor()
    m.dormir = lambda s: m.estado_falso.update(permitir=False)   # el usuario activa «Solo local» durante la espera del reintento
    m.fab.error("servidor", 503).ok()
    with pytest.raises(NubeFallo) as e:
        _pedir(m)
    assert len(m.fab.llamadas) == 1 and e.value.error.causa == "solo_local"


def test_la_repeticion_sin_permiso_o_sin_plazo_cae_a_local_sin_contar_fallo():
    m = _motor()
    h = m.nuevo_plazo()
    m.estado_falso["permitir"] = False
    with pytest.raises(NubeFallo):
        m.transcribir(b"wav", 2.0, idiomas=["es"], prompt="", palabras_clave=[], rapido=False, sonda=False, hasta=h, repeticion=True)
    m.estado_falso["permitir"] = True
    m.reloj_falso.t += 11
    with pytest.raises(NubeFallo):
        m.transcribir(b"wav", 2.0, idiomas=["es"], prompt="", palabras_clave=[], rapido=False, sonda=False, hasta=h, repeticion=True)
    assert m.fab.llamadas == [] and m.fallos == 0 and m._fallos_seguidos == 0


def test_la_repeticion_por_idioma_no_cuenta_dos_veces_trozos_ni_audio_pero_si_los_bytes():
    m = _motor()
    h = m.nuevo_plazo()
    for rep in (False, True):
        m.transcribir(b"wav", 4.0, idiomas=["es"], prompt="", palabras_clave=[], rapido=False, sonda=False, hasta=h, repeticion=rep)
    r = m.resumen()
    assert (r["trozos"], r["audio_s"], r["ms_medio"], r["bytes_enviados"]) == (1, 4, 500, 64000)


def test_cerrar_impide_nuevos_envios():
    m = _motor()
    _pedir(m)
    m.cerrar()
    with pytest.raises(NubeFallo):
        _pedir(m)
    assert len(m.fab.llamadas) == 1


def test_con_el_motor_configurado_en_local_el_estado_publico_es_local_aunque_se_usara_la_nube():
    m = _motor()
    _pedir(m)
    assert m.publico()["estado"] == "activa"
    m.config["transcripcion_motor"] = "local"
    p = m.publico()
    assert (p["estado"], p["mensaje"], p["causa"], p["vuelve_en_s"]) == ("local", "", "", None) and p["trozos"] == 1
    _fallar(m, "clave", 401)   # bloqueada por la clave: con el motor en local sigue diciendo «local»
    assert m.publico()["estado"] == "local"
    m.config["transcripcion_motor"] = "nube"
    assert m.publico()["estado"] == "bloqueada"


def test_el_lote_lleva_ok_segun_haya_fallos_en_ese_lote():
    m = _motor()
    _pedir(m)
    assert m.tomar_lote()["ok"] is True
    m.fab.error("servidor", 503).ok()
    _pedir(m)   # el reintento acierta, pero hubo un fallo en el lote
    assert m.tomar_lote()["ok"] is False
    _pedir(m)
    assert m.tomar_lote()["ok"] is True


def test_otra_direccion_compara_solo_el_host():
    assert MotorNube.otra_direccion("https://api.openai.com/v1", "https://otro.example/v1")
    assert not MotorNube.otra_direccion("https://API.openai.com/v1", "https://api.openai.com/otra/ruta")
    assert MotorNube.respuesta_otra_direccion() == {"ok": False, "causa": "sin_clave", "http": None,
                                                    "mensaje": "Para probar otra dirección, escribe también la clave."}
