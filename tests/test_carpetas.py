"""Elegir carpeta (selector nativo) y crear carpeta nueva desde la app: Guardian, endpoints y propuesta de «Carpeta compartida».
Todo en carpetas temporales: no se abre OneDrive real ni se escribe fuera de tmp_path."""
import json
import os
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from apuntes.analisis import ModeloLLM, Respuesta, Uso
from apuntes.config import Config
from apuntes.consumo import Consumo
from apuntes.gestor import Gestor
from apuntes.rutas import Guardian, RutaProhibida, raiz_onedrive, sugerir_compartida
from apuntes.servidor import Difusor, crear_app

PUERTO, TOKEN = 8124, "t0k3n"
PRUEBAS = Path(__file__).resolve().parent.parent / "pruebas"


# ---------------------------------------------------------------- Guardian: crear carpeta
@pytest.fixture
def mundo(tmp_path):
    raiz = tmp_path / "proyectos"
    (raiz / "ProyA" / "00. CONTEXTO (IA)").mkdir(parents=True)
    knowledge = tmp_path / "Knowledge"
    knowledge.mkdir()
    fuera = tmp_path / "Clientes"
    fuera.mkdir()
    g = Guardian(raiz, tmp_path / "bandeja", tmp_path / "cache", solo_lectura=[knowledge])
    return g, raiz, knowledge, fuera, tmp_path


def test_crea_en_la_raiz_por_defecto_y_solo_esa_carpeta(mundo):
    g, raiz, *_ = mundo
    antes = sorted(p.name for p in raiz.iterdir())
    r = g.crear_carpeta_proyecto("Nuevo Cliente")
    assert r == {"nombre": "Nuevo Cliente", "ruta": str(raiz / "Nuevo Cliente"), "en_raiz": True}
    assert (raiz / "Nuevo Cliente").is_dir() and list((raiz / "Nuevo Cliente").iterdir()) == []   # vacía: no se crea nada dentro
    assert sorted(p.name for p in raiz.iterdir()) == sorted(antes + ["Nuevo Cliente"])


def test_crea_fuera_de_la_raiz_y_avisa_de_que_no_esta_en_ella(mundo):
    g, raiz, _, fuera, _ = mundo
    r = g.crear_carpeta_proyecto("Otro", str(fuera))
    assert r["en_raiz"] is False and (fuera / "Otro").is_dir()
    # una subcarpeta de un proyecto de la raíz tampoco cuelga directamente de ella
    r2 = g.crear_carpeta_proyecto("Sub", str(raiz / "ProyA"))
    assert r2["en_raiz"] is False and (raiz / "ProyA" / "Sub").is_dir()


def test_nunca_sobrescribe_ni_reutiliza_una_existente(mundo):
    g, raiz, _, fuera, _ = mundo
    (raiz / "ProyA" / "marca.txt").write_text("no tocar", encoding="utf-8")
    with pytest.raises(RutaProhibida, match="Ya existe"):
        g.crear_carpeta_proyecto("ProyA")                     # carpeta existente en la raíz
    with pytest.raises(RutaProhibida, match="Ya existe"):
        g.crear_carpeta_proyecto("proya")                     # Windows no distingue mayúsculas
    (fuera / "fichero").write_text("x", encoding="utf-8")
    with pytest.raises(RutaProhibida, match="Ya existe"):
        g.crear_carpeta_proyecto("fichero", str(fuera))      # un fichero con ese nombre tampoco se pisa
    assert (raiz / "ProyA" / "marca.txt").read_text(encoding="utf-8") == "no tocar"
    assert (fuera / "fichero").read_text(encoding="utf-8") == "x"
    g.crear_carpeta_proyecto("Nueva")
    with pytest.raises(RutaProhibida, match="Ya existe"):
        g.crear_carpeta_proyecto("Nueva")                     # ni la que acabamos de crear


@pytest.mark.parametrize("nombre", ["", "   ", ".", "..", "a/b", "a\\b", "con:dos", "a*b", "a?b", "<x>", "a|b", 'a"b', "CON", "nul", "COM1.txt",
                                    "acaba.", ".oculto", ".git", "node_modules", "__pycache__", ".venv", "secretos", "mis-credenciales",
                                    "api-key", ".env", "id_rsa", "x\x01y"])
def test_nombres_no_permitidos(mundo, nombre):
    g, raiz, *_ = mundo
    antes = sorted(p.name for p in raiz.iterdir())
    with pytest.raises(RutaProhibida):
        g.crear_carpeta_proyecto(nombre)
    assert sorted(p.name for p in raiz.iterdir()) == antes


def test_ubicaciones_no_permitidas(mundo):
    g, raiz, knowledge, fuera, tmp = mundo
    with pytest.raises(RutaProhibida, match="absoluta"):
        g.crear_carpeta_proyecto("X", "relativa\\carpeta")
    with pytest.raises(RutaProhibida, match="no existe"):
        g.crear_carpeta_proyecto("X", str(tmp / "no-existe"))
    with pytest.raises(RutaProhibida, match="raíz de una unidad"):
        g.crear_carpeta_proyecto("X", Path(tmp.anchor).as_posix())
    with pytest.raises(RutaProhibida, match="solo lectura"):
        g.crear_carpeta_proyecto("X", str(knowledge))
    secreta = tmp / ".ssh"
    secreta.mkdir()
    with pytest.raises(RutaProhibida, match="secretos"):
        g.crear_carpeta_proyecto("X", str(secreta))
    (fuera / "fichero.md").write_text("x", encoding="utf-8")
    with pytest.raises(RutaProhibida, match="no existe o no es una carpeta"):
        g.crear_carpeta_proyecto("X", str(fuera / "fichero.md"))
    assert not (knowledge / "X").exists() and not (tmp / "X").exists()


def test_el_nombre_no_choca_con_otro_proyecto(mundo):
    g, raiz, _, fuera, _ = mundo
    existente = fuera / "Ext"
    existente.mkdir()
    g.fijar_extras([{"nombre": "Ext", "ruta": str(existente), "compartido": False}])
    otra = fuera.parent / "Otra"
    otra.mkdir()
    with pytest.raises(RutaProhibida, match="proyecto con ese nombre"):
        g.crear_carpeta_proyecto("ext", str(otra))            # nombre de un proyecto extra
    with pytest.raises(RutaProhibida, match="proyecto con ese nombre"):
        g.crear_carpeta_proyecto("ProyA", str(otra))          # nombre de un proyecto de la raíz
    assert list(otra.iterdir()) == []


def test_deshacer_solo_retira_carpetas_vacias(mundo):
    g, raiz, *_ = mundo
    r = g.crear_carpeta_proyecto("Temporal")
    g.deshacer_carpeta_nueva(r["ruta"])
    assert not (raiz / "Temporal").exists()
    r = g.crear_carpeta_proyecto("ConCosas")
    (raiz / "ConCosas" / "a.md").write_text("x", encoding="utf-8")
    g.deshacer_carpeta_nueva(r["ruta"])
    assert (raiz / "ConCosas" / "a.md").is_file()


def test_validar_no_crea_nada(mundo):
    g, raiz, *_ = mundo
    assert g.validar_carpeta_nueva("Solo comprobar") == raiz / "Solo comprobar"
    assert not (raiz / "Solo comprobar").exists()


# ---------------------------------------------------------------- OneDrive: punto de partida y propuesta de «compartida»
def test_raiz_onedrive_usa_las_variables_y_solo_si_existe(tmp_path):
    corp, pers = tmp_path / "OneDrive - Empresa", tmp_path / "OneDrive"
    corp.mkdir()
    pers.mkdir()
    assert raiz_onedrive({"OneDriveCommercial": str(corp), "OneDrive": str(pers)}) == str(corp)   # la de la organización primero
    assert raiz_onedrive({"OneDrive": str(pers)}) == str(pers)
    assert raiz_onedrive({"OneDriveCommercial": str(tmp_path / "no-existe"), "OneDrive": str(pers)}) == str(pers)
    assert raiz_onedrive({"OneDrive": "relativa"}) is None
    assert raiz_onedrive({}) is None


def test_propuesta_de_carpeta_compartida(tmp_path):
    od = tmp_path / "OneDrive - Empresa"
    env = {"OneDriveCommercial": str(od)}
    assert sugerir_compartida(od / "Archivos de Ana Pérez - CLIENTE" / "PROYECTO", env) is True
    assert sugerir_compartida(od / "archivos de ana" / "x", env) is True                       # sin distinguir mayúsculas
    assert sugerir_compartida(od / "Mis proyectos" / "PROYECTO", env) is False
    assert sugerir_compartida(od / "Documentos" / "Archivos" / "x", env) is False              # «Archivos» a secas no es «Archivos de …»
    assert sugerir_compartida(tmp_path / "Archivos de Ana" / "x", env) is False                 # no cuelga de OneDrive
    # sin variables, vale con que algún componente de la ruta sea OneDrive
    assert sugerir_compartida(Path("D:/Data/OneDrive/OneDrive - X/Archivos de Y/Z"), {}) is True
    assert sugerir_compartida(Path("D:/Data/Otro/Archivos de Y/Z"), {}) is False


# ---------------------------------------------------------------- endpoints
class LLMVacio(ModeloLLM):
    def completar(self, sistema, usuario, modelo, esfuerzo="", timeout_s=240, sin_razonamiento=False):
        return Respuesta(json.dumps({"pm": "a", "fun": "b", "tec": "c", "rev": "d"}), [Uso(modelo, 1, 1)])


class VentanaFalsa:
    """Hace de `Ventana` nativa: el selector devuelve lo que se le diga (sin abrir ningún diálogo de Windows)."""
    def __init__(self, elegida=None):
        self.elegida, self.recibido = elegida, []

    def elegir_carpeta(self, inicial=""):
        self.recibido.append(inicial)
        return self.elegida

    def estado_modo(self):
        return {}


def montar(tmp_path, ventana=None):
    raiz = tmp_path / "proyectos"
    shutil.copytree(PRUEBAS / "proyectos", raiz)
    cfg = Config(tmp_path / "config.json")
    cfg.actualizar({"raiz_proyectos": str(raiz), "knowledge": "", "proyectos_extra": []}, guardar=False)
    g = Guardian(raiz, tmp_path / "bandeja", tmp_path / "cache", planes=tmp_path / "planes", sesiones_locales=tmp_path / "sesiones",
                 extras=cfg["proyectos_extra"])
    dif = Difusor()
    gestor = Gestor(cfg, g, Consumo(None), LLMVacio(), dif.emitir)
    app = crear_app(gestor, dif, cfg, g, TOKEN, PUERTO, ventana=(lambda: ventana))
    return TestClient(app, base_url=f"http://127.0.0.1:{PUERTO}", headers={"X-Token": TOKEN}), cfg, g, raiz


def nombres(cli):
    return {p["nombre"]: p for p in cli.get("/api/proyectos").json()["proyectos"]}


def test_endpoint_crea_en_la_raiz_y_sale_en_la_lista_sin_registrarla_como_extra(tmp_path):
    cli, cfg, g, raiz = montar(tmp_path)
    with cli:
        r = cli.post("/api/proyectos/carpeta", json={"nombre": "Cliente Nuevo"})
        assert r.status_code == 200
        d = r.json()
        assert d["registrada_como_extra"] is False and d["proyecto"]["nombre"] == "Cliente Nuevo" and d["proyecto"]["ruta"] == str(raiz / "Cliente Nuevo")
        assert (raiz / "Cliente Nuevo").is_dir()
        assert cfg["proyectos_extra"] == []
        lista = nombres(cli)
        assert "Cliente Nuevo" in lista and lista["Cliente Nuevo"]["compartido"] is False
        # no se reutiliza ni se pisa: el segundo intento falla con el motivo
        r2 = cli.post("/api/proyectos/carpeta", json={"nombre": "cliente nuevo"})
        assert r2.status_code == 403 and "Ya existe" in r2.json()["detail"]


def test_endpoint_fuera_de_la_raiz_se_registra_como_proyecto_extra(tmp_path):
    cli, cfg, g, raiz = montar(tmp_path)
    fuera = tmp_path / "Clientes"
    fuera.mkdir()
    with cli:
        r = cli.post("/api/proyectos/carpeta", json={"nombre": "Externo", "ubicacion": str(fuera), "compartido": False})
        assert r.status_code == 200
        d = r.json()
        assert d["registrada_como_extra"] is True and d["proyecto"] == {"nombre": "Externo", "ruta": str(fuera / "Externo"), "compartido": False}
        assert (fuera / "Externo").is_dir()
        assert [e["nombre"] for e in cfg["proyectos_extra"]] == ["Externo"] and "externo" in g.extras
        assert "Externo" in nombres(cli)
        # el alta pasó por validar_extra: mismo nombre en otra ubicación, rechazado y sin carpeta huérfana
        otra = tmp_path / "Otra"
        otra.mkdir()
        r2 = cli.post("/api/proyectos/carpeta", json={"nombre": "Externo", "ubicacion": str(otra)})
        assert r2.status_code == 403 and not (otra / "Externo").exists()
        assert [e["nombre"] for e in cfg["proyectos_extra"]] == ["Externo"]


def test_endpoint_compartida_se_guarda_como_compartida(tmp_path):
    cli, cfg, g, _ = montar(tmp_path)
    fuera = tmp_path / "Archivos de Ana"
    fuera.mkdir()
    with cli:
        r = cli.post("/api/proyectos/carpeta", json={"nombre": "Comp", "ubicacion": str(fuera), "compartido": True})
        assert r.status_code == 200 and r.json()["proyecto"]["compartido"] is True
        assert g.es_compartido("Comp") and cfg["proyectos_extra"][0]["compartido"] is True


def test_si_el_alta_falla_a_medias_no_queda_carpeta_huerfana(tmp_path, monkeypatch):
    cli, cfg, g, _ = montar(tmp_path)
    fuera = tmp_path / "Clientes"
    fuera.mkdir()

    def falla(*a, **k):
        raise RutaProhibida("no se puede añadir")
    monkeypatch.setattr(g, "validar_extra", falla)
    with cli:
        r = cli.post("/api/proyectos/carpeta", json={"nombre": "Huerfana", "ubicacion": str(fuera)})
        assert r.status_code == 403
    assert not (fuera / "Huerfana").exists() and cfg["proyectos_extra"] == []


@pytest.mark.parametrize("cuerpo", [{"nombre": ""}, {"nombre": "../escape"}, {"nombre": ".git"}, {"nombre": "ok", "ubicacion": "relativa"},
                                    {"nombre": "ok", "ubicacion": "Z:\\no\\existe"}])
def test_endpoint_rechaza_lo_peligroso_sin_crear_nada(tmp_path, cuerpo):
    cli, cfg, g, raiz = montar(tmp_path)
    antes = sorted(p.name for p in tmp_path.rglob("*"))
    with cli:
        assert cli.post("/api/proyectos/carpeta", json=cuerpo).status_code in (400, 403)
    assert sorted(p.name for p in tmp_path.rglob("*")) == antes and cfg["proyectos_extra"] == []


def test_los_endpoints_exigen_token(tmp_path):
    cli, *_ = montar(tmp_path)
    with cli:
        for ruta in ("/api/proyectos/carpeta", "/api/ventana/elegir-carpeta"):
            assert cli.post(ruta, json={"nombre": "x"}, headers={"X-Token": "otro"}).status_code == 401


def test_elegir_carpeta_sin_ventana_nativa_falla_y_el_boton_no_aparece(tmp_path):
    cli, *_ = montar(tmp_path, ventana=None)
    with cli:
        assert cli.get("/api/ventana").json() == {"nativa": False}     # la interfaz oculta el botón con esto
        r = cli.post("/api/ventana/elegir-carpeta")
        assert r.status_code == 400 and "ventana nativa" in r.json()["detail"]


def test_elegir_carpeta_devuelve_ruta_nombre_y_propuesta_y_empieza_en_onedrive(tmp_path, monkeypatch):
    od = tmp_path / "OneDrive - Empresa"
    od.mkdir()
    monkeypatch.setenv("OneDriveCommercial", str(od))
    elegida = od / "Archivos de Ana Pérez - CLIENTE" / "PROYECTO X"
    elegida.mkdir(parents=True)
    v = VentanaFalsa(str(elegida))
    cli, cfg, g, _ = montar(tmp_path, ventana=v)
    with cli:
        r = cli.post("/api/ventana/elegir-carpeta")
        assert r.status_code == 200
        assert r.json() == {"cancelado": False, "ruta": str(elegida), "nombre": "PROYECTO X", "compartida_sugerida": True}
        assert v.recibido == [str(od)]                       # el selector se abre en el OneDrive del usuario
        assert cfg["proyectos_extra"] == []                  # elegir NO registra nada: el alta sigue yendo por /api/proyectos/extra
        # una carpeta normal: sin propuesta
        propia = tmp_path / "propia"
        propia.mkdir()
        v.elegida = str(propia)
        assert cli.post("/api/ventana/elegir-carpeta").json()["compartida_sugerida"] is False
        # cancelar el selector no es un error
        v.elegida = None
        assert cli.post("/api/ventana/elegir-carpeta").json() == {"cancelado": True}


def test_sin_onedrive_el_selector_se_abre_donde_decida_windows(tmp_path, monkeypatch):
    for var in ("OneDriveCommercial", "OneDrive", "OneDriveConsumer"):
        monkeypatch.delenv(var, raising=False)
    v = VentanaFalsa(None)
    cli, *_ = montar(tmp_path, ventana=v)
    with cli:
        cli.post("/api/ventana/elegir-carpeta")
    assert v.recibido == [""]


def test_la_carpeta_elegida_se_da_de_alta_por_el_camino_de_siempre(tmp_path, monkeypatch):
    """Elegir + Añadir = POST /api/proyectos/extra con validar_extra: una carpeta con pinta de secreto o la raíz se rechazan igual."""
    cli, cfg, g, raiz = montar(tmp_path)
    buena = tmp_path / "Mi carpeta"
    buena.mkdir()
    with cli:
        assert cli.post("/api/proyectos/extra", json={"nombre": "Mi carpeta", "ruta": str(buena)}).status_code == 200
        assert cli.post("/api/proyectos/extra", json={"nombre": "Raiz", "ruta": str(raiz)}).status_code == 403
        secreta = tmp_path / ".aws"
        secreta.mkdir()
        assert cli.post("/api/proyectos/extra", json={"nombre": "Aws", "ruta": str(secreta)}).status_code == 403


def test_ventana_elegir_carpeta_usa_el_dialogo_de_carpetas_de_pywebview(monkeypatch):
    """`Ventana.elegir_carpeta` llama a create_file_dialog con el tipo CARPETA y el directorio inicial, y un solo selector a la vez."""
    import sys
    import types

    from apuntes.ventana import Ventana

    llamadas = []

    class W:
        def create_file_dialog(self, tipo, directory="", **k):
            llamadas.append((tipo, directory))
            return ("D:\\elegida",)

    fake = types.SimpleNamespace(FileDialog=types.SimpleNamespace(FOLDER=20), FOLDER_DIALOG=20)
    monkeypatch.setitem(sys.modules, "webview", fake)
    v = Ventana("http://127.0.0.1:1/", True)
    with pytest.raises(ValueError, match="todavía no está lista"):
        v.elegir_carpeta("D:\\x")
    v._w = W()
    assert v.elegir_carpeta("D:\\inicio") == "D:\\elegida"
    assert llamadas == [(20, "D:\\inicio")]
    v._dialogo.acquire()
    with pytest.raises(ValueError, match="Ya hay un selector"):
        v.elegir_carpeta("")
    v._dialogo.release()
    v._w = types.SimpleNamespace(create_file_dialog=lambda *a, **k: None)
    assert v.elegir_carpeta("") is None                      # cancelar -> None
