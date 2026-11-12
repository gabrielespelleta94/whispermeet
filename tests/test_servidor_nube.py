"""API de la transcripción en la nube (apuntes/servidor.py): validación en PUT /api/config, clave (PUT/DELETE /api/nube/clave), «Probar» y bloque `nube` de
/api/info. Servidor falso en bucle local, claves ficticias, DPAPI real solo sobre carpetas temporales. Ni red ni modelo."""
import json
import sys

import pytest
from fastapi.testclient import TestClient

from apuntes import requisitos as R
from apuntes.analisis import ModeloLLM
from apuntes.clave_nube import ENV_CLAVE
from apuntes.config import DEFAULTS, Config
from apuntes.consumo import Consumo
from apuntes.gestor import Gestor
from apuntes.rutas import Guardian
from apuntes.servidor import Difusor, crear_app
from servidor_nube_falso import CENTINELA_MENSAJE, ServidorNubeFalso

PUERTO, TOKEN = 8191, "t0k3n-nube"
CENTINELA = "sk-ficticia-CENTINELA-9876543210"
windows = pytest.mark.skipif(sys.platform != "win32", reason="DPAPI solo existe en Windows")


class SinModelo(ModeloLLM):
    def completar(self, *a, **k):
        raise AssertionError("la nube no llama a ningún modelo de lenguaje")


def _montaje(tmp_path, con_ajustes=True):
    raiz = tmp_path / "proyectos"
    raiz.mkdir(exist_ok=True)
    datos = tmp_path / "datos"
    cfg = Config(datos / "config.json")
    cfg.actualizar({"raiz_proyectos": str(raiz), "knowledge": ""}, guardar=False)
    g = Guardian(raiz, tmp_path / "bandeja", tmp_path / "cache", datos=datos / "ola4", ajustes=(datos / "config.json") if con_ajustes else None)
    dif = Difusor()
    gestor = Gestor(cfg, g, Consumo(None), SinModelo(), dif.emitir)
    gestor.eventos = []
    gestor._emitir = gestor.eventos.append
    app = crear_app(gestor, dif, cfg, g, TOKEN, PUERTO)
    cli = TestClient(app, base_url=f"http://127.0.0.1:{PUERTO}", headers={"X-Token": TOKEN})
    return cli, cfg, g, gestor, app


@pytest.fixture
def m(tmp_path):
    return _montaje(tmp_path)


# ---------------------------------------------------------------- PUT /api/config
@pytest.mark.parametrize("campo,valor,texto", [
    ("transcripcion_motor", "otra", "El motor de transcripción es local o nube."),
    ("transcripcion_motor", None, "El motor de transcripción es local o nube."),
    ("nube_url_base", "http://api.openai.com/v1", "La dirección debe empezar por https:// (http:// solo en este equipo)."),
    ("nube_url_base", "https://usuario:clave@host/v1", "La dirección no puede llevar usuario, contraseña, ? ni #."),
    ("nube_url_base", "https://host/v1?x=1", "La dirección no puede llevar usuario, contraseña, ? ni #."),
    ("nube_url_base", "", "La dirección debe empezar por https://"),
    ("nube_modelo", "con espacios", "Nombre de modelo no válido."),
    ("nube_modelo", "x" * 81, "Nombre de modelo no válido."),
    ("nube_autenticacion", "basic", "bearer o api-key"),
    ("nube_dialecto", "rarisimo", "auto, gpt-transcribe o clasico"),
])
def test_put_config_valida_campos_nube_con_su_campo(m, campo, valor, texto):
    cli, cfg, *_ = m
    antes = cfg.publico()
    r = cli.put("/api/config", json={campo: valor, "idioma": "ca"})   # el resto del cuerpo, válido, tampoco se aplica a medias
    assert r.status_code == 400, r.text
    d = r.json()
    assert d["campo"] == campo and texto in d["detail"]
    assert cfg.publico() == antes


def test_put_config_acepta_y_normaliza_los_valores_nube(m):
    cli, cfg, _g, gestor, _a = m
    llamadas = []
    gestor.nube_config_cambiada = lambda: llamadas.append(1)
    r = cli.put("/api/config", json={"transcripcion_motor": "nube", "nube_url_base": "https://eu.api.openai.com/v1/", "nube_modelo": "whisper-1",
                                     "nube_autenticacion": "api-key", "nube_dialecto": "clasico"})
    assert r.status_code == 200
    c = r.json()["config"]
    assert (c["transcripcion_motor"], c["nube_url_base"], c["nube_modelo"], c["nube_autenticacion"], c["nube_dialecto"]) == (
        "nube", "https://eu.api.openai.com/v1", "whisper-1", "api-key", "clasico")
    assert llamadas == [1]
    assert json.loads(cfg.ruta.read_text(encoding="utf-8"))["nube_modelo"] == "whisper-1"
    cli.put("/api/config", json={"nube_modelo": "whisper-1", "idioma": "ca"})   # lo mismo de antes: no cambia nada de la nube
    assert llamadas == [1]


def test_put_config_rechaza_nube_clave(m):
    cli, cfg, g, *_ = m
    r = cli.put("/api/config", json={"nube_clave": CENTINELA, "idioma": "ca"})
    assert r.status_code == 400
    assert r.json() == {"detail": "La clave se guarda con su propio botón; no va en la configuración.", "campo": "nube_clave"}
    assert cfg["idioma"] != "ca" and CENTINELA not in json.dumps(cfg.publico())
    assert not (cfg.ruta.exists() and CENTINELA in cfg.ruta.read_text(encoding="utf-8"))
    cfg.actualizar({"nube_clave": CENTINELA})   # el fichero escrito a mano tampoco la guarda
    assert "nube_clave" not in cfg.publico() and CENTINELA not in cfg.ruta.read_text(encoding="utf-8")


def test_motor_se_puede_cambiar_en_plena_reunion(m):
    cli, cfg, _g, gestor, _a = m
    gestor.estado = "grabando"
    llamadas = []
    gestor.nube_config_cambiada = lambda: llamadas.append(1)
    for v in ("nube", "local", "nube"):
        r = cli.put("/api/config", json={"transcripcion_motor": v, "nube_modelo": "whisper-1", "nube_dialecto": "clasico", "nube_autenticacion": "api-key",
                                         "nube_url_base": "https://otro.ejemplo.net/v1"})
        assert r.status_code == 200 and cfg["transcripcion_motor"] == v
    assert len(llamadas) == 3   # el primero cambia todo; luego solo el motor
    r = cli.put("/api/config", json={"whisper_modelo": "medium"})   # esto sigue rechazado durante una reunión
    assert r.status_code == 400 and r.json()["campo"] == "whisper_modelo"
    gestor.estado = "inactivo"


def test_las_claves_de_nube_son_de_config_y_ninguna_es_secreta():
    for k in ("transcripcion_motor", "nube_url_base", "nube_modelo", "nube_autenticacion", "nube_dialecto"):
        assert k in DEFAULTS
    assert DEFAULTS["transcripcion_motor"] == "local" and DEFAULTS["nube_url_base"] == "https://api.openai.com/v1"
    assert not [k for k in DEFAULTS if "clave" in k]


# ---------------------------------------------------------------- clave
@windows
def test_put_y_delete_clave(m, tmp_path, monkeypatch):
    monkeypatch.delenv(ENV_CLAVE, raising=False)
    cli, cfg, g, gestor, _a = m
    llamadas = []
    gestor.nube_config_cambiada = lambda: llamadas.append(1)
    r = cli.put("/api/nube/clave", json={"clave": f"  {CENTINELA}  "})
    assert r.status_code == 200 and r.json() == {"clave": {"puesta": True, "origen": "fichero", "error": ""}}
    fichero = tmp_path / "datos" / "secreto-nube.dpapi"
    assert fichero.is_file() and CENTINELA.encode() not in fichero.read_bytes() and gestor.clave_nube.obtener() == CENTINELA
    assert CENTINELA not in r.text
    r = cli.delete("/api/nube/clave")
    assert r.status_code == 200 and r.json() == {"clave": {"puesta": False, "origen": "ninguna", "error": ""}} and not fichero.exists()
    assert cli.delete("/api/nube/clave").status_code == 200   # sin clave tampoco falla
    assert llamadas == [1, 1, 1]


@windows
def test_put_clave_con_variable_de_entorno_guarda_pero_manda_la_variable(m, tmp_path, monkeypatch):
    monkeypatch.setenv(ENV_CLAVE, "sk-ficticia-del-entorno")
    cli, _cfg, _g, gestor, _a = m
    r = cli.put("/api/nube/clave", json={"clave": CENTINELA})
    assert r.status_code == 200
    assert r.json() == {"clave": {"puesta": True, "origen": "entorno", "error": ""},
                        "nota": "Manda la variable de entorno WHISPERMEET_CLAVE_NUBE mientras exista."}
    assert (tmp_path / "datos" / "secreto-nube.dpapi").is_file() and gestor.clave_nube.obtener() == "sk-ficticia-del-entorno"


@pytest.mark.parametrize("cuerpo", [{"clave": "corta"}, {"clave": "con espacios dentro"}, {"clave": "a" * 401}, {"clave": ""}, {"clave": None}, {}, {"clave": 12345678}])
def test_put_clave_invalida_400_campo(m, cuerpo):
    cli, _cfg, g, *_ = m
    r = cli.put("/api/nube/clave", json=cuerpo)
    assert r.status_code == 400
    assert r.json() == {"detail": "La clave tiene de 8 a 400 caracteres visibles, sin espacios.", "campo": "nube_clave"}
    assert not g.ruta_secreto_nube().exists()


def test_put_clave_sin_ajustes_da_400(tmp_path):
    cli, *_ = _montaje(tmp_path, con_ajustes=False)
    r = cli.put("/api/nube/clave", json={"clave": CENTINELA})
    assert r.status_code == 400
    assert r.json() == {"detail": "No hay carpeta de datos donde guardar la clave.", "campo": "nube_clave"}
    assert cli.delete("/api/nube/clave").status_code == 200


# ---------------------------------------------------------------- /api/info y /api/requisitos
@windows
def test_info_tiene_estado_de_clave_y_nunca_la_clave(m, monkeypatch):
    monkeypatch.delenv(ENV_CLAVE, raising=False)
    monkeypatch.setattr(R, "comprobar_audio", lambda *a, **k: R._r("audio", "Audio", "bien", "ok"))
    monkeypatch.setattr(R, "comprobar_claude", lambda *a, **k: R._r("claude", "Claude", "bien", "ok"))
    cli, *_ = m
    n = cli.get("/api/info").json()["nube"]
    assert n == {"clave": {"puesta": False, "origen": "ninguna", "error": ""}, "dialecto_efectivo": "gpt-transcribe", "host": "api.openai.com"}
    cli.put("/api/config", json={"transcripcion_motor": "nube", "nube_modelo": "mi-despliegue", "nube_url_base": "https://recurso.ejemplo.net/openai/v1"})
    assert cli.put("/api/nube/clave", json={"clave": CENTINELA}).status_code == 200
    info, req = cli.get("/api/info"), cli.get("/api/requisitos")
    assert info.json()["nube"] == {"clave": {"puesta": True, "origen": "fichero", "error": ""}, "dialecto_efectivo": "clasico", "host": "recurso.ejemplo.net"}
    assert CENTINELA not in info.text and CENTINELA not in req.text and "sk-ficticia" not in info.text
    [nube] = [c for c in req.json()["comprobaciones"] if c["clave"] == "nube"]
    assert nube["estado"] == "bien" and "recurso.ejemplo.net" in nube["detalle"] and "/openai" not in nube["detalle"]
    whisper = [c for c in req.json()["comprobaciones"] if c["clave"] == "modelo_whisper"][0]
    assert whisper["detalle"].endswith(" Es el respaldo si falla la nube.")


def test_requisitos_con_motor_local_no_lleva_la_comprobacion(m, monkeypatch):
    monkeypatch.setattr(R, "comprobar_audio", lambda *a, **k: R._r("audio", "Audio", "bien", "ok"))
    cli, *_ = m
    assert "nube" not in [c["clave"] for c in cli.get("/api/requisitos").json()["comprobaciones"]]


# ---------------------------------------------------------------- Probar
def _cuerpo(s, **extra):
    return {"nube_url_base": s.url_base, "nube_modelo": "gpt-transcribe", "nube_autenticacion": "bearer", "nube_dialecto": "auto", "clave": CENTINELA, **extra}


def test_probar_contra_falso_ok_y_401(m, tmp_path):
    cli, cfg, g, gestor, _a = m
    with ServidorNubeFalso() as s:
        s.ok("", idiomas=["es"])
        r = cli.post("/api/nube/probar", json=_cuerpo(s))
        assert r.status_code == 200
        d = r.json()
        assert d["ok"] is True and isinstance(d["ms"], int) and d["modelo"] == "gpt-transcribe" and d["dialecto"] == "gpt-transcribe"
        assert d["host"] == "127.0.0.1" and d["idioma"] == "es" and CENTINELA not in r.text
        p = s.peticiones[0]
        assert p["authorization"] == f"Bearer {CENTINELA}" and p["fichero"]["riff_wave"] and p["fichero"]["tam"] == 44 + 2 * 16000   # un tono de 1 s
        s.error(401, code="invalid_api_key")
        r = cli.post("/api/nube/probar", json=_cuerpo(s))
        assert r.json() == {"ok": False, "causa": "clave", "http": 401, "mensaje": "La nube rechaza la clave (401). Revisa la clave."}
        assert CENTINELA not in r.text and CENTINELA_MENSAJE not in r.text and len(s.peticiones) == 2   # una petición por «Probar», sin reintentos
    assert not g.ruta_secreto_nube().exists() and CENTINELA not in json.dumps(cfg.publico())   # la clave de la petición nunca se guarda
    assert cli.get("/api/info").json()["nube"]["clave"]["puesta"] is False
    regs = [json.loads(x) for x in (g.leer_datos("envios.jsonl") or "").splitlines()]
    assert [(x["tarea"], x["tipo"], x["sesion"], x["audio_s"], x["trozos"], x["ok"]) for x in regs] == [
        ("nube_prueba", "transcripcion_nube", "", 1.0, 1, True), ("nube_prueba", "transcripcion_nube", "", 1.0, 1, False)]
    assert CENTINELA not in json.dumps(regs)
    eventos = [e for e in gestor.eventos if e["tipo"] == "envio"]   # `tipo` del registro no pisa el nombre del evento
    assert len(eventos) == 2 and all(e["tarea"] == "nube_prueba" for e in eventos)


@windows
def test_probar_usa_la_clave_guardada_y_los_valores_guardados(m, monkeypatch):
    monkeypatch.delenv(ENV_CLAVE, raising=False)
    cli, cfg, *_ = m
    with ServidorNubeFalso() as s:
        cfg.actualizar({"nube_url_base": s.url_base, "nube_modelo": "whisper-1", "nube_autenticacion": "api-key"}, guardar=False)
        r = cli.post("/api/nube/probar", json={})
        assert r.json() == {"ok": False, "causa": "sin_clave", "http": None, "mensaje": "No hay clave: escríbela o guárdala antes de probar."}
        assert s.peticiones == []
        cli.put("/api/nube/clave", json={"clave": CENTINELA})
        s.ok("")
        r = cli.post("/api/nube/probar")   # sin cuerpo
        assert r.json()["ok"] is True and r.json()["dialecto"] == "clasico"
        assert (s.peticiones[0]["authorization"], s.peticiones[0]["api_key"]) == (None, CENTINELA)
        assert s.valores("model") == ["whisper-1"] and s.valores("language") == ["es"]


def test_probar_con_valores_invalidos_da_400_con_su_campo(m):
    cli, *_ = m
    for campo, valor in (("nube_url_base", "http://api.openai.com/v1"), ("nube_modelo", "a b"), ("nube_autenticacion", "x"), ("nube_dialecto", "x")):
        r = cli.post("/api/nube/probar", json={campo: valor, "clave": CENTINELA})
        assert r.status_code == 400 and r.json()["campo"] == campo
    r = cli.post("/api/nube/probar", json={"clave": "corta"})
    assert r.status_code == 400 and r.json()["campo"] == "nube_clave"


def test_probar_host_externo_bloqueado_por_la_guarda(m):
    cli, _cfg, g, *_ = m
    r = cli.post("/api/nube/probar", json={"nube_url_base": "https://api.openai.com/v1", "clave": CENTINELA})
    d = r.json()
    assert r.status_code == 200 and d["ok"] is False and d["causa"] == "bloqueada_pruebas" and d["http"] is None and d["mensaje"]
    assert not g.leer_datos("envios.jsonl")   # no salió nada: no hay nada que registrar


def test_probar_esta_permitido_con_solo_local(m):
    cli, cfg, _g, gestor, _a = m
    cfg.actualizar({"modo_local": True}, guardar=False)
    assert gestor.modo_local_activo()
    with ServidorNubeFalso() as s:
        s.ok("")
        assert cli.post("/api/nube/probar", json=_cuerpo(s)).json()["ok"] is True


# ---------------------------------------------------------------- seguridad
def test_rutas_nube_exigen_token(m):
    *_resto, app = m
    sin = TestClient(app, base_url=f"http://127.0.0.1:{PUERTO}")
    for metodo, ruta in (("put", "/api/nube/clave"), ("delete", "/api/nube/clave"), ("post", "/api/nube/probar"), ("get", "/api/info")):
        r = getattr(sin, metodo)(ruta, **({"json": {"clave": CENTINELA}} if metodo in ("put", "post") else {}))
        assert r.status_code == 401, (metodo, ruta)
    malo = TestClient(app, base_url=f"http://127.0.0.1:{PUERTO}", headers={"X-Token": "otro"})
    assert malo.put("/api/nube/clave", json={"clave": CENTINELA}).status_code == 401


@windows
def test_config_json_en_disco_no_contiene_la_clave(m, tmp_path, monkeypatch):
    monkeypatch.delenv(ENV_CLAVE, raising=False)
    cli, cfg, *_ = m
    assert cli.put("/api/nube/clave", json={"clave": CENTINELA}).status_code == 200
    assert cli.put("/api/config", json={"transcripcion_motor": "nube", "idioma": "ca"}).status_code == 200
    texto = cfg.ruta.read_text(encoding="utf-8")
    assert "transcripcion_motor" in texto and CENTINELA not in texto and "clave" not in texto
    for f in (tmp_path / "datos").rglob("*"):
        if f.is_file() and f.name != "secreto-nube.dpapi":
            assert CENTINELA.encode() not in f.read_bytes(), f


def test_probar_otra_direccion_sin_clave_no_usa_la_guardada_ni_hace_llamada(m, monkeypatch):
    monkeypatch.setenv(ENV_CLAVE, CENTINELA)   # hay una clave guardada (aquí, por entorno)
    cli, cfg, g, *_ = m
    llamadas = []
    monkeypatch.setattr("apuntes.servidor.MotorNube.probar", staticmethod(lambda efectiva, clave, *a, **k: llamadas.append((efectiva["nube_url_base"], clave)) or {"ok": True, "ms": 1}))
    r = cli.post("/api/nube/probar", json={"nube_url_base": "https://otro-servicio.example/v1"})
    assert r.json() == {"ok": False, "causa": "sin_clave", "http": None, "mensaje": "Para probar otra dirección, escribe también la clave."}
    assert llamadas == [] and not g.leer_datos("envios.jsonl") and CENTINELA not in r.text
    # con la clave escrita en la petición sí se prueba; y con la dirección guardada (mismo host) se usa la guardada
    assert cli.post("/api/nube/probar", json={"nube_url_base": "https://otro-servicio.example/v1", "clave": CENTINELA}).json()["ok"] is True
    assert cli.post("/api/nube/probar", json={"nube_url_base": cfg["nube_url_base"]}).json()["ok"] is True
    assert llamadas == [("https://otro-servicio.example/v1", CENTINELA), (cfg["nube_url_base"], CENTINELA)]
