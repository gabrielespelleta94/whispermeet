"""Cliente de la transcripción en la nube (apuntes/nube.py) contra un servidor falso en bucle local (tests/servidor_nube_falso.py).
Ninguna llamada de red real, ninguna clave real (`sk-ficticia-…`), nada de audio a disco."""
import builtins
import io
import socket
import threading
import time
import wave

import numpy as np
import pytest

from apuntes import nube as N
from apuntes.config import validar_url_nube
from apuntes.nube import ClienteNube, NubeError, clasificar, idioma_de_respuesta, multipart, wav_pcm16
from servidor_nube_falso import CENTINELA_MENSAJE, ServidorNubeFalso

CLAVE = "sk-ficticia-0000000000"


def _cliente(url, modelo="gpt-transcribe", **kw):
    kw.setdefault("entorno", {})   # sin la guarda de pruebas: el servidor falso ya es de bucle local
    kw.setdefault("proxies", {})
    return ClienteNube(url, modelo, kw.pop("clave", CLAVE), **kw)


def _pedir(c, **kw):
    kw.setdefault("idiomas", ["es"])
    kw.setdefault("prompt", "")
    kw.setdefault("palabras_clave", [])
    kw.setdefault("timeout_conexion", 5.0)
    kw.setdefault("timeout_lectura", 5.0)
    return c.transcribir(wav_pcm16(np.zeros(1600, dtype=np.float32)), **kw)


# ---------------------------------------------------------------- piezas puras
def test_wav_pcm16_es_riff_mono_16k_y_recorta(monkeypatch):
    def sin_disco(*a, **k):
        raise AssertionError("el audio nunca va a disco")
    monkeypatch.setattr(builtins, "open", sin_disco)
    wav = wav_pcm16(np.array([0.0, 0.5, -0.5, 1.5, -1.5], dtype=np.float32))
    assert wav[:4] == b"RIFF" and wav[8:12] == b"WAVE"
    with wave.open(io.BytesIO(wav), "rb") as w:
        assert (w.getnchannels(), w.getframerate(), w.getsampwidth()) == (1, 16000, 2)
        muestras = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2")
    assert muestras.tolist() == [0, 16383, -16383, 32767, -32767]


def test_multipart_repite_campos_con_corchetes():
    campos = [("model", "m"), ("languages[]", "es"), ("languages[]", "ca"), ("keywords[]", "SAP"), ("keywords[]", "Fiori")]
    cuerpo, tipo = multipart(campos, ("trozo.wav", b"RIFF....WAVE", "audio/wav"))
    borde = tipo.split("boundary=")[1].encode()
    assert tipo.startswith("multipart/form-data; boundary=")
    assert cuerpo.count(b'name="languages[]"') == 2 and cuerpo.count(b'name="keywords[]"') == 2
    assert b'name="file"; filename="trozo.wav"\r\nContent-Type: audio/wav' in cuerpo
    assert cuerpo.count(b"--" + borde) == len(campos) + 2 and cuerpo.endswith(b"--" + borde + b"--\r\n")
    assert multipart([], ("a", b"", "x"))[1] != multipart([], ("a", b"", "x"))[1]   # boundary único en cada cuerpo


def test_idioma_de_respuesta_nombres_y_codigos():
    assert idioma_de_respuesta({"language": "spanish"}, "clasico") == "es"
    assert idioma_de_respuesta({"language": "Catalan"}, "clasico") == "ca"
    assert idioma_de_respuesta({"language": "english"}, "clasico") == "en"
    assert idioma_de_respuesta({"language": "de"}, "clasico") == "de"
    assert idioma_de_respuesta({"languages": [{"code": "ca"}]}, "gpt-transcribe") == "ca"
    assert idioma_de_respuesta({"languages": [{"code": "ES"}, {"code": "en"}]}, "gpt-transcribe") == "es"
    for vacio in ({}, {"languages": []}, {"text": "x"}, {"language": ""}, None):
        assert idioma_de_respuesta(vacio, "gpt-transcribe") is None and idioma_de_respuesta(vacio, "clasico") is None


@pytest.mark.parametrize("valor,esperado", [
    ("https://api.openai.com/v1", "https://api.openai.com/v1"),
    ("https://api.openai.com/v1/", "https://api.openai.com/v1"),
    (" https://eu.api.openai.com/v1 ", "https://eu.api.openai.com/v1"),
    ("https://recurso.ejemplo.net:8443/openai/v1///", "https://recurso.ejemplo.net:8443/openai/v1"),
    ("https://[2001:db8::1]:8443/v1", "https://[2001:db8::1]:8443/v1"),
    ("http://127.0.0.1:8000/v1", "http://127.0.0.1:8000/v1"),
    ("http://localhost:8000/v1", "http://localhost:8000/v1"),
    ("http://[::1]:8000/v1/", "http://[::1]:8000/v1"),
    ("https://host", "https://host"),
])
def test_validar_url_nube_validas(valor, esperado):
    assert validar_url_nube(valor) == esperado


@pytest.mark.parametrize("valor,texto", [
    ("http://api.openai.com/v1", "https://"),
    ("ftp://host/v1", "https://"),
    ("https://", "https://"),
    ("", "https://"),
    (None, "https://"),
    (5, "https://"),
    ("https://host /v1", "https://"),
    ("https://host:abc/v1", "https://"),
    ("https://" + "a" * 200 + ".com/v1", "https://"),
    ("https://usuario:clave@host/v1", "usuario, contraseña"),
    ("https://usuario@host/v1", "usuario, contraseña"),
    ("https://host/v1?x=1", "usuario, contraseña"),
    ("https://host/v1#a", "usuario, contraseña"),
])
def test_validar_url_nube_invalidas(valor, texto):
    with pytest.raises(ValueError) as e:
        validar_url_nube(valor)
    assert texto in str(e.value)


@pytest.mark.parametrize("estado,cuerpo,cabeceras,causa,definitiva,reintentable,retry", [
    (401, None, {}, "clave", True, False, None),
    (403, None, {}, "permiso", True, False, None),
    (404, None, {}, "config", True, False, None),
    (405, None, {}, "config", True, False, None),
    (415, None, {}, "config", True, False, None),
    (408, None, {}, "tiempo", False, True, None),
    (413, None, {}, "audio", False, False, None),
    (400, {"error": {"param": "prompt"}}, {}, "pistas", False, False, None),
    (400, {"error": {"param": "keywords"}}, {}, "pistas", False, False, None),
    (400, {"error": {"param": "keywords[]"}}, {}, "pistas", False, False, None),
    (400, {"error": {"code": "invalid_prompt_length"}}, {}, "pistas", False, False, None),
    (400, {"error": {"code": "bad_keyword"}}, {}, "pistas", False, False, None),
    (400, {"error": {"param": "model"}}, {}, "config", True, False, None),
    (400, {"error": {"param": "language"}}, {}, "config", True, False, None),
    (400, {"error": {"param": "languages[]"}}, {}, "config", True, False, None),
    (400, {"error": {"param": "response_format"}}, {}, "config", True, False, None),
    (400, {"error": {"param": "temperature"}}, {}, "config", True, False, None),
    (400, {"error": {"param": "file"}}, {}, "audio", False, False, None),
    (400, {"error": {"code": "invalid_audio_file"}}, {}, "audio", False, False, None),
    (400, {"error": {"code": "otra_cosa"}}, {}, "rechazo", False, False, None),
    (400, None, {}, "rechazo", False, False, None),
    (422, {"error": {}}, {}, "rechazo", False, False, None),
    (429, {"error": {"code": "insufficient_quota"}}, {}, "credito", True, False, None),
    (429, {"error": {"code": "credit_balance_exhausted"}}, {}, "credito", True, False, None),
    (429, {"error": {"code": "project_spend_limit_exceeded"}}, {}, "credito", True, False, None),
    (429, {"error": {"code": "organization_usage_limit_exceeded"}}, {}, "credito", True, False, None),
    (429, {"error": {"type": "billing_error"}}, {}, "credito", True, False, None),
    (429, {"error": {"code": "rate_limit_exceeded", "type": "rate_limit_error"}}, {"Retry-After": "7"}, "tasa", False, True, 7.0),
    (429, {"error": {"code": "slow_down"}}, {"retry-after": "1.5"}, "tasa", False, True, 1.5),
    (429, None, {"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"}, "tasa", False, True, None),
    (500, None, {}, "servidor", False, True, None),
    (502, None, {}, "servidor", False, True, None),
    (503, {"error": {"code": "server_is_overloaded"}}, {"Retry-After": "30"}, "servidor", False, True, 30.0),
    (504, None, {"Retry-After": "basura"}, "servidor", False, True, None),
    (418, None, {}, "rechazo", False, False, None),
    (302, None, {}, "rechazo", False, False, None),
])
def test_clasificar_tabla(estado, cuerpo, cabeceras, causa, definitiva, reintentable, retry):
    e = clasificar(estado, cuerpo, cabeceras)
    assert (e.causa, e.http, e.definitiva, e.reintentable, e.retry_after) == (causa, estado, definitiva, reintentable, retry)


def test_error_no_contiene_cuerpo_ni_clave():
    with ServidorNubeFalso() as s:
        s.error(401, code="invalid_api_key")
        with pytest.raises(NubeError) as e:
            _pedir(_cliente(s.url_base))
    err = e.value
    for texto in (str(err), repr(err), str(err.args)):
        assert CENTINELA_MENSAJE not in texto and CLAVE not in texto and "sk-" not in texto
    assert str(err) == "nube causa=clave http=401 codigo=invalid_api_key"
    assert NubeError("red").args == ("nube causa=red http=- codigo=-",)
    assert NubeError("clave", 401, "Con Mayúsculas y espacios").codigo == ""   # solo [a-z0-9_-]{1,60}
    assert NubeError("clave", 401, "a" * 61).codigo == ""
    assert CLAVE not in repr(_cliente(s.url_base))


# ---------------------------------------------------------------- dialectos y autenticación (servidor falso real en bucle local)
def test_dialecto_gpt_envia_languages_keywords_prompt_json():
    with ServidorNubeFalso() as s:
        s.ok("hola mundo", idiomas=["ca"])
        r = _pedir(_cliente(s.url_base), idiomas=["es", "ca", "en"], prompt="Reunión de trabajo: x.", palabras_clave=["SAP", "Fiori"])
        assert s.peticiones[0]["ruta"] == "/v1/audio/transcriptions"
        assert s.peticiones[0]["campos"] == [("model", "gpt-transcribe"), ("response_format", "json"), ("temperature", "0"),
                                              ("languages[]", "es"), ("languages[]", "ca"), ("languages[]", "en"),
                                              ("prompt", "Reunión de trabajo: x."), ("keywords[]", "SAP"), ("keywords[]", "Fiori")]
        f = s.peticiones[0]["fichero"]
        assert (f["nombre_campo"], f["filename"], f["tipo"], f["riff_wave"]) == ("file", "trozo.wav", "audio/wav", True)
    assert (r.texto, r.idioma, r.segmentos) == ("hola mundo", "ca", None) and r.ms >= 0 and r.bytes_enviados > 3200


def test_dialecto_clasico_envia_language_prompt_verbose_json():
    with ServidorNubeFalso() as s:
        s.ok("hola", idiomas=["es"], segmentos=[{"start": 1.5, "text": " hola ", "no_speech_prob": 0.2, "avg_logprob": -0.4}])
        r = _pedir(_cliente(s.url_base, "whisper-1"), idiomas=["es"], prompt="p", palabras_clave=["SAP"])
        assert s.peticiones[0]["campos"] == [("model", "whisper-1"), ("response_format", "verbose_json"), ("temperature", "0"),
                                              ("language", "es"), ("prompt", "p")]   # ni languages[] ni keywords[]
    assert r.idioma == "es" and r.segmentos == [{"start": 1.5, "text": "hola", "no_speech_prob": 0.2, "avg_logprob": -0.4}]


def test_clasico_en_auto_no_envia_language():
    with ServidorNubeFalso() as s:
        s.ok("hola")
        _pedir(_cliente(s.url_base, "whisper-1"), idiomas=["es", "ca", "en"])
        assert "language" not in s.nombres_de_campos() and "languages[]" not in s.nombres_de_campos()
        s.ok("hola")
        _pedir(_cliente(s.url_base, "gpt-transcribe", dialecto="clasico"), idiomas=["ca"])
        assert s.valores("language") == ["ca"]


def test_dialecto_fijado_manda_sobre_el_modelo():
    with ServidorNubeFalso() as s:
        s.ok("x")
        _pedir(_cliente(s.url_base, "mi-despliegue", dialecto="gpt-transcribe"), idiomas=["es", "ca"])
        assert s.valores("languages[]") == ["es", "ca"] and s.valores("response_format") == ["json"]


def test_keywords_con_angulos_o_saltos_se_omiten():
    with ServidorNubeFalso() as s:
        s.ok("x")
        _pedir(_cliente(s.url_base), palabras_clave=["SAP", "a<b", "c>d", "uno\ndos", "tres\rcuatro", "  Power   BI  ", ""])
        assert s.valores("keywords[]") == ["SAP", "Power BI"]


def test_prompt_vacio_no_envia_el_campo():
    with ServidorNubeFalso() as s:
        s.ok("x").ok("y")
        _pedir(_cliente(s.url_base), prompt="")
        _pedir(_cliente(s.url_base, "whisper-1"), prompt="")
        assert all("prompt" not in s.nombres_de_campos(i) for i in (0, 1))


def test_bearer_y_api_key_son_excluyentes():
    with ServidorNubeFalso() as s:
        s.ok("a").ok("b")
        _pedir(_cliente(s.url_base, autenticacion="bearer"))
        _pedir(_cliente(s.url_base, autenticacion="api-key"))
        bearer, api = s.peticiones
    assert (bearer["authorization"], bearer["api_key"]) == (f"Bearer {CLAVE}", None)
    assert (api["authorization"], api["api_key"]) == (None, CLAVE)


def test_ruta_base_con_prefijo():
    with ServidorNubeFalso() as s:
        s.ok("x")
        _pedir(_cliente(s.url_base.replace("/v1", "/openai/v1/")))
        assert s.peticiones[0]["ruta"] == "/openai/v1/audio/transcriptions"


# ---------------------------------------------------------------- respuestas 200 raras
def test_respuesta_sin_languages_ni_usage_y_texto_vacio_no_son_fallo():
    with ServidorNubeFalso() as s:
        s.ok("")
        r = _pedir(_cliente(s.url_base))
        s.crudo(b'{"text": "solo texto"}')
        r2 = _pedir(_cliente(s.url_base))
    assert (r.texto, r.idioma) == ("", None) and (r2.texto, r2.idioma) == ("solo texto", None)


def test_clasico_con_texto_pero_sin_segmentos_no_pierde_el_texto():
    with ServidorNubeFalso() as s:
        s.crudo(b'{"text": "hay texto", "segments": []}')
        r = _pedir(_cliente(s.url_base, "whisper-1"))
    assert r.texto == "hay texto" and r.segmentos is None


def test_json_ilegible_es_rechazo():
    with ServidorNubeFalso() as s:
        s.crudo(b"<html>no es json</html>").crudo(b'["lista"]')
        for _ in range(2):
            with pytest.raises(NubeError) as e:
                _pedir(_cliente(s.url_base))
            assert e.value.causa == "rechazo" and e.value.http == 200


def test_error_con_retry_after_llega_al_error():
    with ServidorNubeFalso() as s:
        s.error(429, code="rate_limit_exceeded", retry_after=120)
        with pytest.raises(NubeError) as e:
            _pedir(_cliente(s.url_base))
    assert (e.value.causa, e.value.retry_after) == ("tasa", 120.0)


# ---------------------------------------------------------------- conexión: keep-alive, tiempos, cortes y tope de respuesta
def test_keepalive_caducado_reconecta_sin_contar_fallo():
    with ServidorNubeFalso() as s:
        s.cerrar_tras_respuesta("uno").ok("dos")
        c = _cliente(s.url_base)
        assert _pedir(c).texto == "uno"
        assert _pedir(c).texto == "dos"   # el socket reutilizado estaba cerrado: se reabre y se repite sin que sea un error
        assert len(s.peticiones) == 2
        c.cerrar()


def test_conexion_persistente_se_reutiliza():
    with ServidorNubeFalso() as s:
        s.ok("a").ok("b")
        c = _cliente(s.url_base)
        _pedir(c)
        sock = c._conn.sock
        _pedir(c)
        assert c._conn.sock is sock
        c.cerrar()
        assert c._conn is None


def test_timeout_de_lectura_da_tiempo():
    with ServidorNubeFalso() as s:
        s.lento(3)
        with pytest.raises(NubeError) as e:
            _pedir(_cliente(s.url_base), timeout_lectura=1.0)
    assert e.value.causa == "tiempo" and e.value.reintentable


def test_corte_da_red():
    with ServidorNubeFalso() as s:
        s.corte()
        with pytest.raises(NubeError) as e:
            _pedir(_cliente(s.url_base))
    assert e.value.causa == "red"


def test_conexion_rechazada_da_red():
    with socket.socket() as sck:
        sck.bind(("127.0.0.1", 0))
        puerto = sck.getsockname()[1]   # un puerto libre en el que no escucha nadie
    with pytest.raises(NubeError) as e:
        _pedir(_cliente(f"http://127.0.0.1:{puerto}/v1"))
    assert e.value.causa == "red"


def test_respuesta_gigante_se_corta_a_1mb():
    with ServidorNubeFalso() as s:
        s.crudo(b'{"text": "' + b"x" * 3_000_000 + b'"}')
        c = _cliente(s.url_base)
        with pytest.raises(NubeError) as e:
            _pedir(c)
        assert e.value.causa == "rechazo"   # truncada, no es un JSON legible
        assert c._conn is None   # con cuerpo sin leer la conexión no se reutiliza


# ---------------------------------------------------------------- guarda de pruebas y proxy
def test_guarda_loopback_rechaza_host_externo_sin_abrir_socket(monkeypatch):
    def prohibido(*a, **k):
        raise AssertionError("no se debe abrir ningún socket")
    monkeypatch.setattr(socket, "create_connection", prohibido)
    monkeypatch.setattr(N.http.client, "HTTPSConnection", prohibido)
    monkeypatch.setattr(N.http.client, "HTTPConnection", prohibido)
    c = ClienteNube("https://api.openai.com/v1", "gpt-transcribe", CLAVE, entorno={N.ENV_SOLO_LOOPBACK: "1"})
    with pytest.raises(NubeError) as e:
        _pedir(c)
    assert e.value.causa == "bloqueada_pruebas" and e.value.definitiva
    assert N.host_permitido("127.0.0.1", {N.ENV_SOLO_LOOPBACK: "1"}) and N.host_permitido("[::1]", {N.ENV_SOLO_LOOPBACK: "1"})
    assert N.host_permitido("localhost", {N.ENV_SOLO_LOOPBACK: "1"}) and not N.host_permitido("api.openai.com", {N.ENV_SOLO_LOOPBACK: "1"})
    assert N.host_permitido("api.openai.com", {}) and N.host_permitido("api.openai.com", {N.ENV_SOLO_LOOPBACK: "0"})


def test_la_guarda_de_pruebas_esta_puesta_en_los_tests():
    import os
    assert os.environ.get(N.ENV_SOLO_LOOPBACK) == "1" and not os.environ.get("WHISPERMEET_CLAVE_NUBE")
    c = ClienteNube("https://api.openai.com/v1", "gpt-transcribe", CLAVE)   # el entorno real de los tests
    with pytest.raises(NubeError) as e:
        _pedir(c)
    assert e.value.causa == "bloqueada_pruebas"


def test_guarda_ignora_proxy():
    c = ClienteNube("https://api.openai.com/v1", "gpt-transcribe", CLAVE, entorno={N.ENV_SOLO_LOOPBACK: "1"}, proxies={"https": "http://127.0.0.1:3128"})
    assert c._proxy() is None


def test_proxy_del_sistema_usa_tunel(monkeypatch):
    llamadas = {}

    class Doble:
        def __init__(self, host, puerto, timeout=None, context=None):
            llamadas["destino"] = (host, puerto)
            self.sock = None

        def set_tunnel(self, host, puerto):
            llamadas["tunel"] = (host, puerto)

        def connect(self):
            raise OSError("doble: sin conexión")

        def close(self):
            pass

    monkeypatch.setattr(N.http.client, "HTTPSConnection", Doble)
    monkeypatch.setattr(N.urllib.request, "proxy_bypass", lambda host: False)
    c = ClienteNube("https://api.openai.com/v1", "gpt-transcribe", CLAVE, entorno={}, proxies={"https": "http://127.0.0.1:3128"})
    with pytest.raises(NubeError) as e:
        _pedir(c)
    assert e.value.causa == "red"
    assert llamadas == {"destino": ("127.0.0.1", 3128), "tunel": ("api.openai.com", 443)}


def test_sin_proxy_va_directo_y_proxy_sin_esquema(monkeypatch):
    monkeypatch.setattr(N.urllib.request, "proxy_bypass", lambda host: False)
    directo = ClienteNube("https://api.openai.com/v1", "gpt-transcribe", CLAVE, entorno={}, proxies={})
    assert directo._proxy() is None
    sin_esquema = ClienteNube("https://api.openai.com/v1", "gpt-transcribe", CLAVE, entorno={}, proxies={"https": "proxy.ejemplo.net:8080"})
    assert sin_esquema._proxy() == ("proxy.ejemplo.net", 8080)
    local = ClienteNube("http://127.0.0.1:9/v1", "gpt-transcribe", CLAVE, entorno={}, proxies={"http": "http://127.0.0.1:3128"})
    assert local._proxy() is None   # http solo hacia este equipo: nunca por proxy
    bypass = ClienteNube("https://api.openai.com/v1", "gpt-transcribe", CLAVE, entorno={}, proxies={"https": "http://127.0.0.1:3128"})
    monkeypatch.setattr(N.urllib.request, "proxy_bypass", lambda host: True)
    assert bypass._proxy() is None


def test_valores_invalidos_en_el_constructor():
    for kw in ({"url_base": "http://api.openai.com/v1"}, {"modelo": "con espacios"}, {"autenticacion": "otra"}, {"dialecto": "rara"}):
        args = {"url_base": "https://api.openai.com/v1", "modelo": "gpt-transcribe", "autenticacion": "bearer", "dialecto": "auto", **kw}
        with pytest.raises(ValueError):
            ClienteNube(args["url_base"], args["modelo"], CLAVE, args["autenticacion"], args["dialecto"])


def test_tono_de_prueba():
    t = N.tono_prueba()
    assert t.dtype == np.float32 and t.size == 16000
    assert abs(float(np.abs(t).max()) - 10 ** (-30 / 20)) < 1e-3


# ---------------------------------------------------------------- revisión crítica: 200 sin texto, cierre, conexión y lectura con plazo
@pytest.mark.parametrize("cuerpo", [b'{"error": "algo"}', b'{"message": "portal cautivo"}', b'{"text": null}', b'{"text": 5}', b'{"text": ["a"]}', b'{}'])
def test_un_200_sin_text_de_tipo_cadena_es_rechazo(cuerpo):
    with ServidorNubeFalso() as s:
        s.crudo(cuerpo)
        with pytest.raises(NubeError) as e:
            _pedir(_cliente(s.url_base))
    assert (e.value.causa, e.value.http) == ("rechazo", 200)


def test_un_200_con_text_vacio_sigue_siendo_un_exito_silencio():
    with ServidorNubeFalso() as s:
        s.crudo(b'{"text": ""}')
        assert _pedir(_cliente(s.url_base)).texto == ""


def test_clasico_con_segments_que_no_es_lista_es_rechazo_y_sin_segments_vale():
    with ServidorNubeFalso() as s:
        s.crudo(b'{"text": "hola", "segments": "no soy una lista"}').crudo(b'{"text": "hola"}')
        c = _cliente(s.url_base, modelo="whisper-1")
        with pytest.raises(NubeError) as e:
            _pedir(c)
        assert e.value.causa == "rechazo"
        r = _pedir(c)
        assert r.texto == "hola" and r.segmentos is None
        c.cerrar()


def test_cerrar_impide_enviar_y_no_abre_ningun_socket():
    with ServidorNubeFalso() as s:
        s.ok("uno")
        c = _cliente(s.url_base)
        assert _pedir(c).texto == "uno"
        c.cerrar()
        with pytest.raises(NubeError) as e:
            _pedir(c)
        assert e.value.causa == "red" and len(s.peticiones) == 1 and c._conn is None


def test_un_error_sobre_conexion_reutilizada_tras_cerrar_no_reabre_ni_reenvia():
    with ServidorNubeFalso() as s:
        s.ok("uno").ok("dos")
        c = _cliente(s.url_base)
        _pedir(c)
        conn = c._conn

        def request_cortado(*a, **k):   # el cierre llega mientras el trozo está en marcha y la conexión reutilizada falla
            c.cerrar()
            raise ConnectionResetError()
        conn.request = request_cortado
        with pytest.raises(NubeError) as e:
            _pedir(c)
        assert e.value.causa == "red" and len(s.peticiones) == 1 and c._conn is None


class _ConexionLenta:
    """Una conexión cuyo `connect()` tarda (DNS o TLS colgados); anota si se cierra."""
    sock = None

    def __init__(self, tarda):
        self.tarda, self.timeout, self.cerrada, self.fin = tarda, None, threading.Event(), threading.Event()

    def connect(self):
        time.sleep(self.tarda)
        self.sock = object()
        self.fin.set()

    def close(self):
        self.cerrada.set()


def test_la_conexion_esta_acotada_por_el_plazo_aunque_connect_se_cuelgue():
    c = _cliente("http://127.0.0.1:9/v1")
    lenta = _ConexionLenta(0.8)
    c._nueva_conexion = lambda timeout: lenta
    ini = time.monotonic()
    with pytest.raises(NubeError) as e:
        _pedir(c, timeout_conexion=0.2)
    assert e.value.causa == "tiempo" and time.monotonic() - ini < 0.7   # no espera a que `connect()` acabe
    assert c._conn is None
    assert lenta.fin.wait(3) and lenta.cerrada.wait(3)   # al completarse la conexión abandonada, el hilo la cierra


def test_el_plazo_total_del_intento_acota_tambien_la_conexion():
    c = _cliente("http://127.0.0.1:9/v1")
    c._nueva_conexion = lambda timeout: _ConexionLenta(0.8)
    ini = time.monotonic()
    with pytest.raises(NubeError) as e:
        _pedir(c, timeout_conexion=5.0, timeout_lectura=5.0, plazo_total=0.2)
    assert e.value.causa == "tiempo" and time.monotonic() - ini < 0.7


def test_la_lectura_lleva_plazo_total_no_por_lectura():
    """Una respuesta que gotea (cada lectura cabe en su tiempo de espera pero el total no) se corta con `tiempo`."""
    class Goteo:
        def read(self, n):
            time.sleep(0.15)
            return b"x"
    c = _cliente("http://127.0.0.1:9/v1")
    ini = time.monotonic()
    with pytest.raises(TimeoutError):
        c._leer(Goteo(), time.monotonic() + 0.5)
    assert 0.4 < time.monotonic() - ini < 1.2
