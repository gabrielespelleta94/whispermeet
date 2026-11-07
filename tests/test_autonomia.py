"""Ola 3, punto 2: autonomía por tipo de acción (avisar | proponer | hacer). «Hacer» solo en lo local y reversible; el resto se rechaza."""
import json

from apuntes.config import AUTONOMIA_POR_DEFECTO, HACER_ADMITIDO, Config, validar_autonomia
from ola3_util import montaje


def test_valores_por_defecto():
    d = dict(AUTONOMIA_POR_DEFECTO)
    assert all(d[t] == "proponer" for t in ("pregunta", "pendiente", "cambio_contexto", "correo", "recordatorio"))
    assert d["consolidar_pendientes"] == "hacer" and set(HACER_ADMITIDO) == {"cambio_contexto", "consolidar_pendientes"}


def test_get_y_put_del_ajuste(tmp_path):
    cli, gestor, cfg, g, *_ = montaje(tmp_path)
    with cli:
        r = cli.get("/api/autonomia").json()
        assert r["autonomia"]["correo"] == "proponer" and r["niveles"] == ["avisar", "proponer", "hacer"] and r["hacer_admitido"] == list(HACER_ADMITIDO)
        assert "pregunta" in r["tipos_accion"] and "consolidar_pendientes" in r["tipos"] and r["defecto"] == AUTONOMIA_POR_DEFECTO
        r = cli.put("/api/autonomia", json={"autonomia": {"correo": "avisar", "cambio_contexto": "hacer"}})
        assert r.status_code == 200 and r.json()["autonomia"]["correo"] == "avisar" and r.json()["autonomia"]["cambio_contexto"] == "hacer"
        assert r.json()["autonomia"]["pendiente"] == "proponer"      # lo no enviado no cambia
        assert cfg["autonomia"]["correo"] == "avisar"
        assert cli.get("/api/info").json()["config"]["autonomia"]["correo"] == "avisar"
    guardado = json.loads((tmp_path / "config.json").read_text(encoding="utf-8"))
    assert guardado["autonomia"]["correo"] == "avisar"                  # persiste en la configuración local


def test_hacer_solo_se_admite_para_lo_local_y_reversible(tmp_path):
    cli, gestor, cfg, g, *_ = montaje(tmp_path)
    with cli:
        for tipo in ("pendiente", "pregunta", "correo", "recordatorio"):
            r = cli.put("/api/autonomia", json={"autonomia": {tipo: "hacer"}})
            assert r.status_code == 400 and "local y reversible" in r.json()["detail"]
        assert cfg["autonomia"]["correo"] == "proponer"
        assert cli.put("/api/autonomia", json={"autonomia": {"correo": "siempre"}}).status_code == 400
        assert cli.put("/api/autonomia", json={"autonomia": {"enviar_correo": "hacer"}}).status_code == 400
        assert cli.put("/api/autonomia", json={"autonomia": {"correo": "avisar", "pendiente": "hacer"}}).status_code == 400
        assert cfg["autonomia"]["correo"] == "proponer"                 # una petición con un error no cambia nada
        assert cli.put("/api/autonomia", json={"autonomia": {"consolidar_pendientes": "hacer", "cambio_contexto": "hacer"}}).status_code == 200


def test_la_configuracion_descarta_lo_invalido_sin_romper(tmp_path):
    cfg = Config(tmp_path / "c.json")
    cfg.actualizar({"autonomia": {"pendiente": "hacer", "correo": "avisar", "raro": "hacer", "pregunta": "nunca"}}, guardar=False)
    assert cfg["autonomia"]["pendiente"] == "proponer" and cfg["autonomia"]["correo"] == "avisar" and "raro" not in cfg["autonomia"]
    assert cfg["autonomia"]["pregunta"] == "proponer"
    cfg.actualizar({"objetivo_sin_tratar_min": 7, "seguimiento_umbral": 0.75}, guardar=False)
    assert cfg["objetivo_sin_tratar_min"] == 7 and cfg["seguimiento_umbral"] == 0.75
    cfg.actualizar({"objetivo_sin_tratar_min": -3, "seguimiento_umbral": 5}, guardar=False)
    assert cfg["objetivo_sin_tratar_min"] == 7 and cfg["seguimiento_umbral"] == 0.75
    assert Config(tmp_path / "otra.json")["objetivo_sin_tratar_min"] == 10


def test_validar_autonomia_es_pura():
    base = dict(AUTONOMIA_POR_DEFECTO)
    out = validar_autonomia({"correo": "avisar"}, base)
    assert out["correo"] == "avisar" and base["correo"] == "proponer"
