"""El Gestor y la nube: estado público, avisos, incidencias, líneas de registro y registro de envíos. Todo con el motor real pero sin red (los eventos se
inyectan en `MotorNube`) y con la carpeta de datos en `tmp_path`. Nunca contenido: se buscan cadenas centinela en el registro y en los envíos."""
import json
import re
import time
from types import SimpleNamespace

import pytest

from apuntes import gestor as G
from apuntes import registro
from apuntes.motor_nube import LOTE_ENVIOS_S, texto_aviso
from apuntes.nube import NubeError
from test_gestor_transcripcion import avisos_ev, gestor, lineas_log  # noqa: F401  (el fixture `gestor` y sus ayudas)

CLAVE = "sk-ficticia-CENTINELA-0000000000"
TEXTO = "CENTINELA-de-texto-de-la-reunion"


@pytest.fixture
def g(gestor, tmp_path):
    """El gestor de siempre con una carpeta local de datos (para el registro de envíos) y la clave puesta en el motor."""
    gestor.g.datos = tmp_path / "datos_envios"
    gestor.transcriptor.nube.proveedor_clave = lambda: CLAVE
    return gestor


def _nube(g):
    return g.transcriptor.nube


def _envios(g):
    return [json.loads(x) for x in (g.g.leer_datos("envios.jsonl") or "").splitlines()]


# ---------------------------------------------------------------- estado público
def test_tick_lleva_motor_motor_activo_y_nube(g):
    tr = g.estado_ligero()["transcripcion"]
    assert tr["motor"] == "local" and tr["motor_activo"] == "local" and tr["nube"] is None   # motor local y la nube sin usar nunca
    g.cfg.actualizar({"transcripcion_motor": "nube"}, guardar=False)
    tr = g.estado_ligero()["transcripcion"]
    assert tr["motor"] == "nube" and tr["motor_activo"] == "nube"   # antes del primer trozo: el que se usaría
    assert set(tr["nube"]) == {"estado", "causa", "mensaje", "vuelve_en_s", "trozos", "audio_s", "ms_medio", "fallos", "respaldo_trozos"}
    assert tr["nube"]["estado"] == "activa" and tr["nube"]["vuelve_en_s"] is None and tr["nube"]["ms_medio"] is None
    g._emitir_tick()
    [tick] = [e for e in g.eventos if e["tipo"] == "tick"]
    assert tick["transcripcion"]["motor"] == "nube" and tick["transcripcion"]["nube"]["estado"] == "activa"
    # los campos de siempre no cambian
    assert {"estado", "error", "pendiente_s", "retraso_s", "velocidad_x", "rapido", "perdidos_s", "aplazado_s", "retraso_reunion_s", "rezagado_s",
            "eco_descartado_s"} <= set(tr)
    g.cfg.actualizar({"transcripcion_motor": "local"}, guardar=False)
    _nube(g).anotar_respaldo(2.0)
    assert g.estado_ligero()["transcripcion"]["nube"]["respaldo_trozos"] == 1   # con el motor local pero la nube ya usada, el bloque sigue


def test_nube_null_con_motor_local_sin_uso(g):
    assert g.estado_ligero()["transcripcion"]["nube"] is None
    g.transcriptor = None
    assert g.estado_ligero()["transcripcion"] is None


def test_estado_sin_clave_y_con_solo_local(g):
    g.cfg.actualizar({"transcripcion_motor": "nube"}, guardar=False)
    _nube(g).proveedor_clave = lambda: None
    assert g.estado_ligero()["transcripcion"]["nube"]["estado"] == "sin_clave"
    _nube(g).proveedor_clave = lambda: CLAVE
    g.modo_local_sesion = True
    n = g.estado_ligero()["transcripcion"]["nube"]
    assert n["estado"] == "solo_local" and "solo local" in n["mensaje"]


# ---------------------------------------------------------------- avisos, incidencias y registro
def test_evento_bloqueada_emite_aviso_fijo_incidencia_y_linea(g):
    n = _nube(g)
    n._evento(evento="bloqueada", causa="clave", http=401, codigo="invalid_api_key")
    g._vigilar_transcripcion()
    [a] = avisos_ev(g)
    assert (a["componente"], a["grave"], a["prioridad"]) == ("transcripcion", False, "fijo")
    assert a["mensaje"] == texto_aviso("clave") and "Esta reunión sigue transcribiéndose en este equipo." in a["mensaje"] and "(401)" in a["mensaje"]
    assert a["mensaje"] in g.avisos
    assert any(re.fullmatch(r"\[\d\d:\d\d\] transcripción: nube → local \(clave\)", i) for i in g.sesion.incidencias)
    assert lineas_log("transcripcion nube evento=bloqueada")[0].endswith("transcripcion nube evento=bloqueada causa=clave http=401 codigo=invalid_api_key")
    n._evento(evento="bloqueada", causa="clave", http=401, codigo="invalid_api_key")   # una vez por causa
    g._vigilar_transcripcion()
    assert len(avisos_ev(g)) == 1
    n._evento(evento="bloqueada", causa="credito", http=429, codigo="")
    g._vigilar_transcripcion()
    assert len(avisos_ev(g)) == 2 and "crédito" in avisos_ev(g)[1]["mensaje"] and lineas_log("transcripcion nube evento=bloqueada")[-1].endswith("http=429 codigo=-")


def test_sin_clave_solo_local_y_pistas_off(g):
    n = _nube(g)
    for ev in ({"evento": "sin_clave"}, {"evento": "solo_local"}, {"evento": "pistas_off", "rechazos": 3}):
        n._evento(**ev)
    g._vigilar_transcripcion()
    a = avisos_ev(g)
    assert [(x["mensaje"], x["grave"], x["prioridad"]) for x in a] == [
        (texto_aviso("sin_clave"), False, "fijo"), (texto_aviso("solo_local"), False, "discreto")]   # pistas_off: solo registro
    assert lineas_log("transcripcion nube evento=pistas_off")[0].endswith("evento=pistas_off rechazos=3")
    assert lineas_log("transcripcion nube evento=sin_clave") and lineas_log("transcripcion nube evento=solo_local")
    assert [i for i in g.sesion.incidencias if "nube → local" in i and ("sin_clave" in i or "solo_local" in i)].__len__() == 2
    assert not [i for i in g.sesion.incidencias if "pistas" in i]


def test_circuito_avisa_como_mucho_cada_5min(g):
    n = _nube(g)
    ev = {"evento": "circuito_abierto", "causa": "red", "http": None, "fallos_seguidos": 2, "vuelve_s": 60}
    n._evento(**ev)
    g._vigilar_transcripcion()
    [a] = avisos_ev(g)
    assert a["mensaje"] == "Sin conexión con la nube: la transcripción sigue en este equipo y se vuelve a probar en 60 s." and (a["grave"], a["prioridad"]) == (False, "normal")
    assert lineas_log("transcripcion nube evento=circuito_abierto")[0].endswith("evento=circuito_abierto causa=red http=- fallos_seguidos=2 vuelve_s=60")
    n._evento(**ev)
    g._vigilar_transcripcion()
    assert len(avisos_ev(g)) == 1   # no vuelve a avisar enseguida…
    assert len([i for i in g.sesion.incidencias if "nube → local (red)" in i]) == 2   # …pero el .md y el registro dicen cada evento
    g._nube_circuito_aviso_en -= G.AVISO_FALLO_CADA_S + 1
    n._evento(**{**ev, "vuelve_s": 120})
    g._vigilar_transcripcion()
    assert len(avisos_ev(g)) == 2 and "120 s" in avisos_ev(g)[1]["mensaje"]
    n._evento(evento="restablecida", tras_s=184)
    g._vigilar_transcripcion()
    r = avisos_ev(g)[-1]
    assert r["mensaje"] == "Transcripción en la nube restablecida." and (r["grave"], r["prioridad"]) == (False, "discreto")
    assert lineas_log("transcripcion nube evento=restablecida")[0].endswith("evento=restablecida tras_s=184")
    assert not [i for i in g.sesion.incidencias if "184" in i or "restablecida" in i]
    n._evento(**ev)   # tras restablecerse, la próxima caída avisa al momento
    g._vigilar_transcripcion()
    assert len(avisos_ev(g)) == 4


def test_respaldo_sin_modelo_avisa_grave_y_fijo(g):
    _nube(g).anotar_sin_modelo()
    g._vigilar_transcripcion()
    a = avisos_ev(g)[-1]
    assert a["mensaje"] == texto_aviso("respaldo_sin_modelo") and (a["grave"], a["prioridad"]) == (True, "fijo")
    assert lineas_log("transcripcion nube evento=respaldo_sin_modelo") and any("sin_modelo" in i for i in g.sesion.incidencias)


# ---------------------------------------------------------------- envíos
def test_lote_de_envios_cada_120s_y_al_cerrar_sin_contenido(g):
    n = _nube(g)
    n.trozos, n.audio_s, n.chars_prompt, n.fallos, n.ms_total = 3, 12.5, 40, 1, 2400
    g._vigilar_transcripcion()
    assert _envios(g) == []   # aún no han pasado 120 s
    g._nube_lote_en -= LOTE_ENVIOS_S + 1
    g._vigilar_transcripcion()
    [e] = _envios(g)
    assert e["tarea"] == "transcripcion_nube" and e["tipo"] == "transcripcion_nube" and e["agente"] == "Transcripción en la nube"
    assert (e["modelo"], e["host"], e["audio_s"], e["trozos"], e["fallos"], e["chars"]) == ("gpt-transcribe", "api.openai.com", 12.5, 3, 1, 40)
    assert (e["bloqueado"], e["ok"], e["entrada"], e["salida"], e["extracto"], e["sesion"]) == (False, False, 0, 0, "", g.sesion.id) and e["ts"]   # hubo 1 fallo en el lote
    [ev] = [x for x in g.eventos if x["tipo"] == "envio"]   # también por el WebSocket, sin pisar el nombre del evento
    assert ev["tarea"] == "transcripcion_nube" and ev["audio_s"] == 12.5
    g._vigilar_transcripcion()
    assert len(_envios(g)) == 1   # sin trozos nuevos no hay lote
    n.trozos, n.audio_s = 5, 20.0
    g._cierre_nube(g.transcriptor)   # al cerrar, el último lote
    assert [(x["trozos"], x["audio_s"]) for x in _envios(g)] == [(3, 12.5), (2, 7.5)]
    assert [x["ok"] for x in _envios(g)] == [False, True]   # `ok` = no hubo fallos en ese lote (la fila «con fallos» de la interfaz puede salir)
    g._cierre_nube(g.transcriptor)
    assert len(_envios(g)) == 2   # una sola vez
    r = g.envios.resumir(_envios(g))
    assert r["nube"] == {"lotes": 2, "trozos": 5, "audio_s": 20.0, "fallos": 1, "bloqueadas": 0} and r["llamadas"] == 0 and r["chars"] == 0


def test_solo_local_deja_un_envio_bloqueado(g):
    _nube(g)._evento(evento="solo_local")
    g._vigilar_transcripcion()
    [e] = _envios(g)
    assert (e["tarea"], e["tipo"], e["bloqueado"], e["error"], e["audio_s"], e["trozos"]) == ("transcripcion_nube", "transcripcion_nube", True, "local", 0, 0)
    assert g.envios.resumir([e])["nube"]["bloqueadas"] == 1 and g.envios.resumir([e])["bloqueadas"] == 0


def test_resumen_cierre_linea_nube_resumen_formato(g):
    n = _nube(g)
    n.trozos, n.audio_s, n.ms_total, n.ms_max, n.fallos, n.reintentos = 412, 2710.0, 412 * 910, 4200, 3, 2
    n.respaldo_trozos, n.respaldo_s, n.silencio_trozos, n.aperturas, n.idioma_repetidos, n.bytes_enviados = 2, 14.0, 37, 1, 1, 86_000_000
    g._cierre_nube(g.transcriptor)
    [linea] = lineas_log("transcripcion nube_resumen")
    assert re.search(r"transcripcion nube_resumen trozos=412 audio=2710s ms_medio=910 ms_max=4200 fallos=3 reintentos=2 respaldo=2 respaldo_audio=14s "
                     r"silencio=37 aperturas=1 bloqueos=0 idioma_rep=1 pistas_rep=0 kb=\d+ dialecto=gpt-transcribe host=api\.openai\.com$", linea), linea
    assert "https://" not in linea


def test_sin_uso_de_la_nube_no_deja_nube_resumen(g):
    g._cierre_nube(g.transcriptor)
    assert lineas_log("transcripcion nube_resumen") == []


def test_resumen_transcripcion_se_escribe_aunque_no_haya_audio_local():
    def tr(audio, trozos, calculo=0.0):
        return SimpleNamespace(audio_total_s=audio, calculo_total_s=calculo, nube=SimpleNamespace(trozos=trozos) if trozos is not None else None)
    G.Gestor._registrar_resumen_transcripcion(tr(0.0, 5))
    G.Gestor._registrar_resumen_transcripcion(tr(60.0, 5, 30.0))
    G.Gestor._registrar_resumen_transcripcion(tr(60.0, 0, 30.0))
    G.Gestor._registrar_resumen_transcripcion(tr(60.0, None, 30.0))
    G.Gestor._registrar_resumen_transcripcion(tr(0.0, 0))
    G.Gestor._registrar_resumen_transcripcion(tr(0.0, None))
    lineas = lineas_log("transcripcion resumen")
    assert [re.search(r"motor=(\w+)$", x).group(1) for x in lineas] == ["nube", "mixto", "local", "local"]
    assert "vel_media=-" in lineas[0]


def test_sufijo_de_la_linea_periodica(g):
    n = _nube(g)
    assert G.Gestor._sufijo_nube(g.transcriptor) == ""
    n.trozos, n.ms_total, n.fallos, n.respaldo_trozos = 4, 3640, 3, 2
    assert G.Gestor._sufijo_nube(g.transcriptor) == " motor=nube nube_ms=910 nube_fallos=3 respaldo=2"
    assert G.Gestor._sufijo_nube(SimpleNamespace()) == ""


# ---------------------------------------------------------------- cambios de configuración y confidencialidad
def test_cambio_de_config_reinicia_motor(g):
    n = _nube(g)
    g.cfg.actualizar({"transcripcion_motor": "nube"}, guardar=False)
    n._bloqueo = NubeError("clave", 401)
    n._pistas_off = True
    n._evento(evento="bloqueada", causa="clave", http=401, codigo="")
    g._vigilar_transcripcion()
    assert n.decidir().motivo == "bloqueada" and len(avisos_ev(g)) == 1
    g.nube_config_cambiada()
    assert n.decidir().motivo == "" and n._pistas_off is False
    n._bloqueo = NubeError("clave", 401)
    n._evento(evento="bloqueada", causa="clave", http=401, codigo="")
    g._vigilar_transcripcion()
    assert len(avisos_ev(g)) == 2   # la causa vuelve a avisar tras arreglar la configuración
    g.transcriptor = None
    g.nube_config_cambiada()   # sin reunión: no falla


def test_el_transcriptor_recibe_clave_y_permiso_del_gestor(g):
    n = _nube(g)
    g.modo_local_sesion = False
    assert n._permitido() is True
    g.modo_local_sesion = True
    assert n._permitido() is False   # «Solo local» (de la sesión) veta la nube


def test_registro_no_contiene_clave_ni_texto(g):
    n = _nube(g)
    n._evento(evento="bloqueada", causa="clave", http=401, codigo="invalid_api_key")
    n._evento(evento="circuito_abierto", causa="red", http=None, fallos_seguidos=2, vuelve_s=60)
    n._evento(evento="restablecida", tras_s=10)
    n.trozos, n.audio_s, n.ms_total, n.chars_prompt = 2, 5.0, 1000, 12
    g._vigilar_transcripcion()
    g._cierre_nube(g.transcriptor)
    g.registrar_prueba_nube({"ok": True}, "gpt-transcribe", "api.openai.com")
    volcado = registro.RUTA_LOG.read_text(encoding="utf-8") + json.dumps(_envios(g)) + "\n".join(g.sesion.incidencias) + json.dumps(g.avisos)
    volcado += json.dumps([e for e in g.eventos if e["tipo"] in ("aviso", "envio")])
    assert "CENTINELA" not in volcado and "sk-" not in volcado and TEXTO not in volcado
    assert re.search(r"https?://", registro.RUTA_LOG.read_text(encoding="utf-8")) is None   # nunca la URL completa
