"""`GET /api/info` dice si el código en disco ya no es el que cargó el proceso (`codigo_cambiado`, apuntes/huella.py). El vigía se inyecta (`vigia_codigo`)."""
from fastapi.testclient import TestClient

from apuntes.config import Config
from apuntes.consumo import Consumo
from apuntes.gestor import Gestor
from apuntes.huella import VigiaCodigo
from apuntes.rutas import Guardian
from apuntes.servidor import Difusor, crear_app
from ola3_util import ModeloFalso

PUERTO, TOKEN = 8199, "t0k3n"


class VigiaFalso:
    def __init__(self, cambiado=False):
        self.valor, self.llamadas = cambiado, 0

    def cambiado(self):
        self.llamadas += 1
        return self.valor


def cliente(tmp_path, **extra):
    raiz = tmp_path / "proyectos"
    raiz.mkdir()
    g = Guardian(raiz, tmp_path / "bandeja", tmp_path / "cache")
    cfg = Config(tmp_path / "config.json")
    cfg.actualizar({"raiz_proyectos": str(raiz), "knowledge": ""}, guardar=False)
    dif = Difusor()
    gestor = Gestor(cfg, g, Consumo(None), ModeloFalso(fallar=True), dif.emitir)
    app = crear_app(gestor, dif, cfg, g, TOKEN, PUERTO, **extra)
    return TestClient(app, base_url=f"http://127.0.0.1:{PUERTO}", headers={"X-Token": TOKEN})


def test_info_dice_false_si_el_codigo_no_ha_cambiado(tmp_path):
    vigia = VigiaFalso(False)
    with cliente(tmp_path, vigia_codigo=vigia) as cli:
        d = cli.get("/api/info").json()
    assert d["codigo_cambiado"] is False and vigia.llamadas == 1


def test_info_dice_true_cuando_el_codigo_ha_cambiado_y_vuelve_a_false(tmp_path):
    vigia = VigiaFalso(True)
    with cliente(tmp_path, vigia_codigo=vigia) as cli:
        assert cli.get("/api/info").json()["codigo_cambiado"] is True
        vigia.valor = False
        assert cli.get("/api/info").json()["codigo_cambiado"] is False


def test_info_conserva_sus_campos_de_siempre(tmp_path):
    with cliente(tmp_path, vigia_codigo=VigiaFalso(False)) as cli:
        d = cli.get("/api/info").json()
    assert {"version", "simulacion", "config", "raiz_existe", "codigo_cambiado"} <= set(d)


def test_sin_vigia_inyectado_se_crea_uno_real_que_no_avisa_al_arrancar(tmp_path):
    with cliente(tmp_path) as cli:
        assert cli.get("/api/info").json()["codigo_cambiado"] is False


def test_el_vigia_real_sobre_una_carpeta_ficticia_avisa_al_cambiar_el_codigo(tmp_path):
    raiz = tmp_path / "app"
    (raiz / "apuntes").mkdir(parents=True)
    (raiz / "apuntes" / "a.py").write_text("X = 1\n", encoding="utf-8")
    t = [0.0]
    vigia = VigiaCodigo(raiz, reloj=lambda: t[0], cada_s=60.0)
    with cliente(tmp_path, vigia_codigo=vigia) as cli:
        assert cli.get("/api/info").json()["codigo_cambiado"] is False
        (raiz / "apuntes" / "a.py").write_text("X = 2\n", encoding="utf-8")
        t[0] = 61.0
        assert cli.get("/api/info").json()["codigo_cambiado"] is True


def test_la_api_info_sigue_exigiendo_token(tmp_path):
    with cliente(tmp_path, vigia_codigo=VigiaFalso(True)) as cli:
        assert cli.get("/api/info", headers={"X-Token": "otro"}).status_code == 401
