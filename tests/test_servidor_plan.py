"""API: proyectos compartidos con plan en el selector de inicio y elección de sesión al empezar."""
import shutil
from pathlib import Path

from fastapi.testclient import TestClient

from apuntes.config import Config
from apuntes.consumo import Consumo
from apuntes.gestor import Gestor
from apuntes.rutas import CARPETA_SESIONES, Guardian
from apuntes.servidor import Difusor, crear_app
from test_gestor_plan import COMPARTIDO, PRUEBAS, Falso, lineas

PUERTO, TOKEN = 8123, "t0k3n"


def cliente(tmp_path):
    raiz = tmp_path / "proyectos"
    shutil.copytree(PRUEBAS / "proyectos", raiz)
    ajena = tmp_path / "ajena" / COMPARTIDO
    shutil.copytree(PRUEBAS / "compartidos" / COMPARTIDO, ajena)
    shutil.copytree(PRUEBAS / "planes-beta", tmp_path / "planes")
    cfg = Config(tmp_path / "config.json")
    cfg.actualizar({"raiz_proyectos": str(raiz), "knowledge": "",
                    "proyectos_extra": [{"nombre": COMPARTIDO, "ruta": str(ajena), "compartido": True}]}, guardar=False)
    g = Guardian(raiz, tmp_path / "bandeja", tmp_path / "cache", planes=tmp_path / "planes",
                 sesiones_locales=tmp_path / "sesiones", extras=cfg["proyectos_extra"])
    dif = Difusor()
    gestor = Gestor(cfg, g, Consumo(None), Falso(), dif.emitir, simulacion=lineas(), velocidad=200)
    app = crear_app(gestor, dif, cfg, g, TOKEN, PUERTO)
    return TestClient(app, base_url=f"http://127.0.0.1:{PUERTO}", headers={"X-Token": TOKEN}), ajena


def test_selector_muestra_compartidos_con_plan_y_se_inicia_con_sesion(tmp_path):
    cli, ajena = cliente(tmp_path)
    with cli:
        lista = {p["nombre"]: p for p in cli.get("/api/proyectos").json()["proyectos"]}
        beta = lista[COMPARTIDO]
        assert beta["compartido"] is True and beta["tiene_sesiones"] is False
        assert [s["id"] for s in beta["plan"]["sesiones"]] == ["S1", "S2", "otra"]
        assert lista["Proyecto Ficticio Alfa"]["compartido"] is False and lista["Proyecto Ficticio Alfa"]["plan"] is None
        # sesión inexistente / proyecto sin plan: error claro y nada arranca
        assert cli.post("/api/sesion/iniciar", json={"proyecto": COMPARTIDO, "tema": "x", "sesion_plan": "ZZ"}).status_code == 400
        assert cli.post("/api/sesion/iniciar", json={"proyecto": "Proyecto Ficticio Alfa", "tema": "x", "sesion_plan": "S1"}).status_code == 400
        r = cli.post("/api/sesion/iniciar", json={"proyecto": COMPARTIDO, "tema": "Mi tema", "cadencia": 5, "sesion_plan": "S1"})
        assert r.status_code == 200
        d = r.json()
        assert d["sesion"]["tema"] == "Mi tema" and d["sesion"]["plan"]["id"] == "S1" and d["sesion"]["compartido"] is True
        assert len(d["objetivos"]) == 4
        assert len(cli.get("/api/sesion").json()["objetivos"]) == 4
    assert not (ajena / CARPETA_SESIONES).exists()


def test_la_api_exige_token(tmp_path):
    cli, _ = cliente(tmp_path)
    with cli:
        assert cli.get("/api/proyectos", headers={"X-Token": "otro"}).status_code == 401
