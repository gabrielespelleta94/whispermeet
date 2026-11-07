"""Modo reunión: cálculo de la distribución, de la región y de la escala DPI (puro), configuración y API con una ventana falsa."""
import pytest
from fastapi.testclient import TestClient

from apuntes import modo_reunion as MR
from apuntes.config import Config
from apuntes.consumo import Consumo
from apuntes.gestor import Gestor
from apuntes.rutas import Guardian
from apuntes.servidor import Difusor, crear_app
from test_gestor_plan import Falso, lineas


# ------------------------------------------------------------ distribución
def test_a_1440_son_360_720_360():
    l = MR.calcular_layout(1440)
    assert (l["modo"], l["izq"], l["hueco"], l["der"]) == ("dos", 360, 720, 360)


def test_a_1920_mantiene_la_proporcion():
    l = MR.calcular_layout(1920)
    assert (l["izq"], l["hueco"], l["der"]) == (480, 960, 480)


def test_umbral_1280():
    assert MR.calcular_layout(1280)["modo"] == "dos"
    assert MR.calcular_layout(1279)["modo"] == "uno"
    assert MR.calcular_layout(1024)["modo"] == "uno"


def test_por_debajo_de_1280_un_unico_panel_a_la_derecha_sin_panel_izquierdo():
    l = MR.calcular_layout(1024)
    assert l["izq"] == 0 and MR.UNICO_MIN <= l["der"] <= 1024 * MR.UNICO_MAX_FRAC
    assert l["izq"] + l["hueco"] + l["der"] == 1024
    r = MR.rectangulos_region(1024, 700, l, 1.0)
    assert r == [(1024 - l["der"], 0, 1024, 700)]   # un solo rectángulo, el del panel


@pytest.mark.parametrize("ancho", [1280, 1366, 1440, 1600, 1920, 2560, 3840])
def test_el_hueco_nunca_baja_del_minimo_ni_los_paneles(ancho):
    for izq, der in [(None, None), (10, 10), (5000, 5000), (900, 300), (300, 900)]:
        l = MR.calcular_layout(ancho, izq, der)
        assert l["izq"] >= MR.MIN_LATERAL and l["der"] >= MR.MIN_LATERAL
        assert l["hueco"] >= MR.MIN_HUECO
        assert l["izq"] + l["hueco"] + l["der"] == ancho


def test_las_medidas_recordadas_se_respetan_si_caben():
    l = MR.calcular_layout(1440, izq=420, der=300)
    assert (l["izq"], l["der"], l["hueco"]) == (420, 300, 720)


def test_panel_unico_recuerda_su_medida_y_la_acota():
    assert MR.calcular_layout(1100, uno=500)["der"] == 500
    assert MR.calcular_layout(1100, uno=5000)["der"] == round(1100 * MR.UNICO_MAX_FRAC)
    assert MR.calcular_layout(1100, uno=10)["der"] == MR.UNICO_MIN


# ------------------------------------------------------------ región y DPI
def test_region_a_100_por_cien_son_dos_rectangulos_sin_el_hueco():
    l = MR.calcular_layout(1440)
    r = MR.rectangulos_region(1440, 900, l, 1.0)
    assert r == [(0, 0, 360, 900), (1080, 0, 1440, 900)]
    assert MR.punto_en_region(r, 100, 450) and MR.punto_en_region(r, 1300, 450)
    assert not MR.punto_en_region(r, 720, 450)               # centro del hueco
    assert not MR.punto_en_region(r, 360, 450) and MR.punto_en_region(r, 359, 450)   # el borde exacto
    assert MR.punto_en_region(r, 1080, 450) and not MR.punto_en_region(r, 1079, 450)


@pytest.mark.parametrize("dpi,escala", [(96, 1.0), (120, 1.25), (144, 1.5), (168, 1.75), (192, 2.0)])
def test_escala_dpi_de_windows(dpi, escala):
    assert MR.escala_dpi(dpi) == pytest.approx(escala)


def test_escala_dpi_valores_raros_no_rompen():
    assert MR.escala_dpi(None) == 1.0 and MR.escala_dpi(0) == 1.0 and MR.escala_dpi(-5) == 1.0
    assert 0.5 <= MR.escala_dpi(1) <= 4.0 and MR.escala_dpi(10000) == 4.0


def test_la_region_en_pixeles_fisicos_sigue_la_escala():
    # 1920x1080 físicos a 125 %: 1536 px CSS -> 384 / 768 / 384 px CSS -> 480 / 960 / 480 físicos
    e = MR.escala_dpi(120)
    l = MR.calcular_layout(MR.a_css(1920, e))
    assert (l["izq"], l["hueco"], l["der"]) == (384, 768, 384)
    assert MR.rectangulos_region(1920, 1040, l, e) == [(0, 0, 480, 1040), (1440, 0, 1920, 1040)]
    # a 150 %: 2560x1440 físicos = 1706,67 px CSS
    e = MR.escala_dpi(144)
    l = MR.calcular_layout(MR.a_css(2560, e))
    r = MR.rectangulos_region(2560, 1400, l, e)
    assert r[0][2] == round(l["izq"] * 1.5) and r[1][0] == 2560 - round(l["der"] * 1.5)
    assert r[0][2] <= r[1][0]   # nunca se cruzan


def test_el_hueco_en_fisicos_equivale_al_hueco_css():
    for dpi in (96, 120, 144, 192):
        e = MR.escala_dpi(dpi)
        ancho_px = 3000
        l = MR.calcular_layout(MR.a_css(ancho_px, e))
        izq, der = MR.rectangulos_region(ancho_px, 1000, l, e)
        assert abs((der[0] - izq[2]) - l["hueco"] * e) <= 2   # redondeo de ±1 px por borde


def test_cambio_de_dpi_recalcula_la_region():
    # misma ventana física de 1920 px con un panel recordado de 400 px CSS: al pasar de 100 % a 150 % cambian los CSS disponibles
    # (1920 -> 1280) y los píxeles físicos de cada panel (400 -> 600)
    a = MR.rectangulos_region(1920, 1000, MR.calcular_layout(MR.a_css(1920, 1.0), izq=400), 1.0)
    b = MR.rectangulos_region(1920, 1000, MR.calcular_layout(MR.a_css(1920, 1.5), izq=400), 1.5)
    assert a[0][2] == 400 and b[0][2] == 600
    # sin medidas recordadas, el 25 % de la misma ventana física es el mismo a cualquier escala
    c = MR.rectangulos_region(1920, 1000, MR.calcular_layout(MR.a_css(1920, 1.5)), 1.5)
    assert c[0][2] == 480


def test_devicepixelratio_distinto_manda_sobre_el_dpi_de_windows():
    assert MR.elegir_escala(96, None) == 1.0
    assert MR.elegir_escala(120, 1.25) == pytest.approx(1.25)
    assert MR.elegir_escala(96, 1.5) == pytest.approx(1.5)        # WebView2 pinta a 1,5: la región debe seguirlo
    assert MR.elegir_escala(96, 99) == 1.0                         # basura: se ignora
    assert MR.elegir_escala(96, 1.001) == 1.0                      # diferencia < 1 %


def test_region_con_ventana_estrecha_no_produce_rectangulos_vacios_ni_fuera():
    l = {"modo": "dos", "ancho": 100, "izq": 400, "der": 400, "hueco": 0}
    for r in MR.rectangulos_region(100, 50, l, 1.0):
        assert 0 <= r[0] < r[2] <= 100 and 0 <= r[1] < r[3] <= 50


# ------------------------------------------------------------ opacidad
def test_opacidad_se_acota_a_60_100_y_pasa_a_alfa():
    assert MR.opacidad_valida(10) == 60 and MR.opacidad_valida(500) == 100 and MR.opacidad_valida("x") == 100
    assert MR.opacidad_a_alfa(100) == 255 and MR.opacidad_a_alfa(60) == 153 and MR.opacidad_a_alfa(0) == 153


# ------------------------------------------------------------ configuración
def test_config_modo_reunion_valida_y_persiste(tmp_path):
    cfg = Config(tmp_path / "c.json")
    assert cfg["modo_reunion"] == {"izq": None, "der": None, "uno": None, "opacidad": 100}
    cfg.actualizar({"modo_reunion": {"izq": 400.4, "der": "x", "uno": 5, "opacidad": 20}})
    assert cfg["modo_reunion"] == {"izq": 400, "der": None, "uno": None, "opacidad": 60}   # basura descartada, opacidad acotada
    assert Config(tmp_path / "c.json")["modo_reunion"]["izq"] == 400
    cfg.actualizar({"modo_reunion": {"izq": None}})
    assert cfg["modo_reunion"]["izq"] is None


# ------------------------------------------------------------ API (ventana falsa)
class VentanaFalsa:
    def __init__(self):
        self.modo_activo, self.llamadas, self.op = False, [], 100

    def estado_modo(self):
        return {"activo": self.modo_activo, "layout": MR.calcular_layout(1440) if self.modo_activo else None, "escala": 1.0,
                "opacidad": self.op, "opacidad_soportada": True, "afinidad": 0x11}

    def entrar(self, prefs, dpr=None):
        self.llamadas.append(("entrar", dict(prefs), dpr)); self.modo_activo = True
        return self.estado_modo()

    def actualizar(self, prefs, dpr=None):
        self.llamadas.append(("actualizar", dict(prefs), dpr))
        return self.estado_modo()

    def salir(self):
        self.llamadas.append(("salir",)); self.modo_activo = False
        return self.estado_modo()

    def fijar_opacidad(self, pct):
        self.op = MR.opacidad_valida(pct); self.llamadas.append(("opacidad", self.op))
        return True


def _cliente(tmp_path, ventana):
    cfg = Config(tmp_path / "config.json")
    g = Guardian(tmp_path / "p", tmp_path / "b", tmp_path / "c")
    dif = Difusor()
    gestor = Gestor(cfg, g, Consumo(None), Falso(), dif.emitir, simulacion=lineas(), velocidad=200)
    app = crear_app(gestor, dif, cfg, g, "tk", 8124, None, (lambda: ventana) if ventana is not None else (lambda: None))
    return TestClient(app, base_url="http://127.0.0.1:8124", headers={"X-Token": "tk"}), cfg, gestor


def test_sin_ventana_nativa_la_api_lo_dice_y_rechaza_el_modo(tmp_path):
    cli, _, _ = _cliente(tmp_path, None)
    with cli:
        assert cli.get("/api/ventana").json() == {"nativa": False}
        r = cli.post("/api/ventana/modo-reunion", json={"activo": True})
        assert r.status_code == 400 and "ventana nativa" in r.json()["detail"]
        assert cli.post("/api/ventana/opacidad", json={"pct": 80}).status_code == 400


def test_el_modo_solo_se_activa_con_reunion_en_curso(tmp_path):
    v = VentanaFalsa()
    cli, _, _ = _cliente(tmp_path, v)
    with cli:
        r = cli.post("/api/ventana/modo-reunion", json={"activo": True})
        assert r.status_code == 400 and not v.llamadas
        assert cli.get("/api/ventana").json()["nativa"] is True


def test_entrar_actualizar_y_salir_con_reunion_en_curso(tmp_path):
    v = VentanaFalsa()
    cli, cfg, gestor = _cliente(tmp_path, v)
    with cli:
        assert cli.post("/api/sesion/iniciar", json={"proyecto": None, "tema": "x", "cadencia": 5}).status_code == 200
        r = cli.post("/api/ventana/modo-reunion", json={"activo": True, "izq": 400, "dpr": 1.25})
        assert r.status_code == 200 and r.json()["activo"] is True
        assert v.llamadas[0][0] == "entrar" and v.llamadas[0][1]["izq"] == 400 and v.llamadas[0][2] == 1.25
        assert cfg["modo_reunion"]["izq"] is None                       # sin `guardar` no se recuerda nada
        cli.post("/api/ventana/modo-reunion", json={"activo": True, "izq": 420, "der": 300, "guardar": True})
        assert v.llamadas[1][0] == "actualizar" and v.llamadas[1][1]["der"] == 300
        assert cfg["modo_reunion"]["izq"] == 420 and cfg["modo_reunion"]["der"] == 300   # recordadas
        # la reunión sigue en marcha mientras dura el modo
        assert gestor.estado in ("grabando", "pausada")
        assert cli.post("/api/ventana/modo-reunion", json={"activo": False}).json()["activo"] is False
        assert v.llamadas[-1] == ("salir",) and gestor.estado in ("grabando", "pausada")
        # salir siempre se permite aunque la reunión haya terminado
        v.modo_activo = True
        assert cli.post("/api/ventana/modo-reunion", json={"activo": False}).status_code == 200
        gestor.apagar()


def test_la_opacidad_se_acota_y_se_recuerda(tmp_path):
    v = VentanaFalsa()
    cli, cfg, _ = _cliente(tmp_path, v)
    with cli:
        r = cli.post("/api/ventana/opacidad", json={"pct": 10, "guardar": True}).json()
        assert r["opacidad"] == 60 and cfg["modo_reunion"]["opacidad"] == 60
        cli.post("/api/ventana/opacidad", json={"pct": 85})
        assert v.op == 85 and cfg["modo_reunion"]["opacidad"] == 85
