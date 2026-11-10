"""Ola F1: copia de seguridad de los datos de la app (`apuntes/copia.py`, destino `copias` del Guardián, `apuntes/api_copia.py`).
Todo con carpetas temporales y datos ficticios: nada toca las carpetas reales de la app."""
import asyncio
import json
import os
import re
import subprocess
import threading
import time
import zipfile
from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from apuntes import __version__
from apuntes import copia as C
from apuntes.analisis import ModeloLLM
from apuntes.backlog import Backlog
from apuntes.config import Config
from apuntes.consumo import Consumo
from apuntes.gestor import Gestor
from apuntes.rutas import Guardian, RutaProhibida
from apuntes.servidor import Difusor, crear_app

AHORA = datetime(2026, 3, 12, 10, 42, 7)
NOMBRE = "whispermeet-copia-2026-03-12-104207.zip"


def _escribir(p: Path, texto: str = "dato ficticio") -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(texto, encoding="utf-8")
    return p


@pytest.fixture
def app(tmp_path):
    """Una «carpeta de la app» ficticia con todas las carpetas de datos que conoce el Guardián, más la caché y una carpeta de proyectos."""
    a = tmp_path / "app"
    for rel, txt in {"planes/plan-aaa.json": '{"sesiones": []}', "checks/alfa.json": "[]", "backlog/estado.json": "{}", "seguimiento/alfa.json": "[]",
                     "tipos_documento/p-1.json": "{}", "bandeja/2026-03-01-prueba.md": "# Reunión ficticia", "sesiones/Alfa/2026-03-02-tema.md": "# Sesión ficticia",
                     "datos/ola4/glosario.json": '{"cupo": "plazas reservadas"}', "datos/config.json": '{"idioma": "es"}',
                     "cache/digest-1.json": "{}", "proyectos/Alfa/doc.md": "documento del usuario"}.items():
        _escribir(a / rel, txt)
    return a


@pytest.fixture
def g(app):
    return Guardian(app / "proyectos", app / "bandeja", app / "cache", sesiones_locales=app / "sesiones", planes=app / "planes", checks=app / "checks",
                    backlog=app / "backlog", datos=app / "datos" / "ola4", tipos=app / "tipos_documento", copias=app / "copias", ajustes=app / "datos" / "config.json")


def nombres(ruta: Path) -> set[str]:
    with zipfile.ZipFile(ruta) as z:
        return set(z.namelist())


def zip_de(g, r) -> Path:
    return g.copias / r["nombre"]


# ============================================================ el módulo
def test_la_copia_lleva_rutas_relativas_a_la_carpeta_de_la_app_y_un_manifiesto(g, app):
    r = C.crear_copia(g, AHORA)
    assert r["nombre"] == NOMBRE and r["omitidos"] == []
    z = zip_de(g, r)
    assert z.is_file() and r["bytes"] == z.stat().st_size
    esperados = {"planes/plan-aaa.json", "checks/alfa.json", "backlog/estado.json", "seguimiento/alfa.json", "tipos_documento/p-1.json", "bandeja/2026-03-01-prueba.md",
                 "sesiones/Alfa/2026-03-02-tema.md", "datos/ola4/glosario.json", "datos/config.json"}
    assert nombres(z) == esperados | {"MANIFIESTO.json"}
    assert r["ficheros"] == len(esperados)
    with zipfile.ZipFile(z) as zf:
        assert all(i.compress_type == zipfile.ZIP_DEFLATED for i in zf.infolist())
        m = json.loads(zf.read("MANIFIESTO.json").decode("utf-8"))
        assert zf.read("planes/plan-aaa.json").decode("utf-8") == '{"sesiones": []}'
    assert m["version"] == 1 and m["creada"] == "2026-03-12T10:42:07" and m["app"] == __version__
    assert sorted(f["ruta"] for f in m["ficheros"]) == sorted(esperados)
    assert {f["ruta"]: f["bytes"] for f in m["ficheros"]}["planes/plan-aaa.json"] == len('{"sesiones": []}')


def test_no_entran_la_cache_ni_los_proyectos_ni_las_copias_anteriores(g, app):
    primera = C.crear_copia(g, AHORA)
    segunda = C.crear_copia(g, datetime(2026, 3, 12, 10, 43, 0))
    n = nombres(zip_de(g, segunda))
    assert not any(x.startswith(("cache/", "proyectos/", "copias/")) or x.endswith(".zip") for x in n)
    assert nombres(zip_de(g, primera)) == n   # la segunda no arrastra nada de la primera
    assert not list(g.copias.glob("*.parcial"))


def test_una_copia_dentro_de_una_carpeta_de_datos_no_se_copia_a_si_misma(tmp_path):
    a = tmp_path / "app"
    _escribir(a / "datos" / "glosario.json")
    g2 = Guardian(a / "p", a / "b", a / "c", datos=a / "datos", copias=a / "datos" / "copias")
    C.crear_copia(g2, AHORA)
    r = C.crear_copia(g2, datetime(2026, 3, 12, 10, 43, 0))
    assert nombres(g2.copias / r["nombre"]) == {"MANIFIESTO.json", "glosario.json"}


def test_una_carpeta_que_no_existe_o_no_esta_configurada_se_salta_sin_error(tmp_path):
    a = tmp_path / "app"
    _escribir(a / "planes" / "plan-x.json")
    g2 = Guardian(a / "p", a / "b", a / "c", planes=a / "planes", checks=a / "no-existe", copias=a / "copias")
    r = C.crear_copia(g2, AHORA)
    assert r["omitidos"] == [] and r["ficheros"] == 1
    assert nombres(g2.copias / r["nombre"]) == {"MANIFIESTO.json", "planes/plan-x.json"}


def test_sin_carpeta_de_copias_configurada_se_rechaza(tmp_path):
    with pytest.raises(RutaProhibida):
        C.crear_copia(Guardian(tmp_path / "p", tmp_path / "b", tmp_path / "c", planes=tmp_path / "planes"), AHORA)


def test_los_nombres_con_pinta_de_secreto_se_omiten_y_se_dicen(g, app):
    _escribir(app / "datos" / "ola4" / "token-de-prueba.json")
    r = C.crear_copia(g, AHORA)
    assert "datos/ola4/token-de-prueba.json" not in nombres(zip_de(g, r))
    assert [o["ruta"] for o in r["omitidos"]] == ["datos/ola4/token-de-prueba.json"] and r["omitidos"][0]["motivo"]


def _enlace_de_carpeta(enlace: Path, destino: Path) -> bool:
    try:
        os.symlink(destino, enlace, target_is_directory=True)
        return True
    except (OSError, NotImplementedError):
        pass
    if os.name == "nt":   # unión de directorio: no pide privilegios
        r = subprocess.run(["cmd", "/c", "mklink", "/J", str(enlace), str(destino)], capture_output=True)
        return r.returncode == 0
    return False


def test_los_enlaces_a_carpetas_no_se_siguen(g, app, tmp_path):
    fuera = tmp_path / "fuera"
    _escribir(fuera / "ajeno.txt", "no es de la app")
    if not _enlace_de_carpeta(app / "planes" / "enlace", fuera):
        pytest.skip("No se pueden crear enlaces en esta máquina.")
    r = C.crear_copia(g, AHORA)
    assert not any("ajeno" in x or x.startswith("planes/enlace") for x in nombres(zip_de(g, r)))
    assert [o["ruta"] for o in r["omitidos"]] == ["planes/enlace"] and "enlace" in r["omitidos"][0]["motivo"].lower()


def test_los_enlaces_a_ficheros_no_se_siguen(g, app, tmp_path):
    fuera = _escribir(tmp_path / "fuera" / "ajeno.txt", "no es de la app")
    try:
        os.symlink(fuera, app / "planes" / "enlace.json")
    except (OSError, NotImplementedError):
        pytest.skip("No se pueden crear enlaces simbólicos en esta máquina.")
    r = C.crear_copia(g, AHORA)
    assert "planes/enlace.json" not in nombres(zip_de(g, r))
    assert [o["ruta"] for o in r["omitidos"]] == ["planes/enlace.json"]


def test_un_fichero_cuya_ruta_real_cae_fuera_de_su_carpeta_no_entra(g, app, tmp_path, monkeypatch):
    real = C._ruta_real
    monkeypatch.setattr(C, "_ruta_real", lambda p: tmp_path / "fuera" / "x.json" if Path(p).name == "plan-aaa.json" else real(p))
    r = C.crear_copia(g, AHORA)
    assert "planes/plan-aaa.json" not in nombres(zip_de(g, r))
    assert [o["ruta"] for o in r["omitidos"]] == ["planes/plan-aaa.json"] and "fuera" in r["omitidos"][0]["motivo"]


def test_un_fichero_ilegible_va_a_omitidos_y_la_copia_sigue(g, app, monkeypatch):
    leer = C._leer

    def falla(ruta, tope):
        if Path(ruta).name == "alfa.json" and Path(ruta).parent.name == "checks":
            raise PermissionError(13, "Acceso denegado")
        return leer(ruta, tope)
    monkeypatch.setattr(C, "_leer", falla)
    r = C.crear_copia(g, AHORA)
    n = nombres(zip_de(g, r))
    assert "checks/alfa.json" not in n and "planes/plan-aaa.json" in n
    assert [o["ruta"] for o in r["omitidos"]] == ["checks/alfa.json"] and "leer" in r["omitidos"][0]["motivo"].lower()
    assert r["ficheros"] == len(n) - 1   # sin contar el manifiesto
    with zipfile.ZipFile(zip_de(g, r)) as z:
        assert "checks/alfa.json" not in [f["ruta"] for f in json.loads(z.read("MANIFIESTO.json"))["ficheros"]]


def test_un_fichero_que_otro_proceso_esta_escribiendo_se_copia_tal_como_esta(g, app):
    log = app / "datos" / "ola4" / "consumo.jsonl"
    with open(log, "a", encoding="utf-8", newline="\n") as f:
        f.write('{"tokens": 1}\n')
        f.flush()
        r = C.crear_copia(g, AHORA)
    assert r["omitidos"] == []
    with zipfile.ZipFile(zip_de(g, r)) as z:
        assert z.read("datos/ola4/consumo.jsonl").decode("utf-8") == '{"tokens": 1}\n'


def test_un_fichero_por_encima_del_tope_por_fichero_va_a_omitidos(g, app):
    _escribir(app / "backlog" / "grande.json", "x" * 500)
    r = C.crear_copia(g, AHORA, tope_fichero=100)
    assert "backlog/grande.json" not in nombres(zip_de(g, r))
    assert [o["ruta"] for o in r["omitidos"]] == ["backlog/grande.json"] and "tamaño" in r["omitidos"][0]["motivo"]
    assert C.TOPE_FICHERO == 200 * 1024 * 1024 and C.TOPE_TOTAL == 2 * 1024 ** 3


def test_el_tope_total_corta_la_copia_y_lo_dice(g, app):
    for i in range(5):
        _escribir(app / "sesiones" / "Alfa" / f"2026-03-1{i}-s.md", "y" * 100)
    r = C.crear_copia(g, AHORA, tope_total=250)
    assert r["cortada"] is True
    assert r["omitidos"] and "tope" in r["omitidos"][-1]["motivo"].lower()
    with zipfile.ZipFile(zip_de(g, r)) as z:
        m = json.loads(z.read("MANIFIESTO.json"))
        assert z.testzip() is None
    assert sum(f["bytes"] for f in m["ficheros"]) <= 250 and r["ficheros"] == len(m["ficheros"])
    assert C.crear_copia(g, datetime(2026, 3, 12, 11, 0, 0))["cortada"] is False


def test_si_algo_falla_se_borra_el_temporal_y_no_queda_un_zip_a_medias(g, app, monkeypatch):
    _escribir(g.copias / "whispermeet-copia-2025-01-01-000000.zip", "copia antigua")   # una copia anterior que nunca se toca
    original = zipfile.ZipFile.writestr
    llamadas = []

    def falla(self, *a, **k):
        llamadas.append(1)
        if len(llamadas) == 3:
            raise OSError(28, "No queda espacio en el dispositivo")
        return original(self, *a, **k)
    monkeypatch.setattr(zipfile.ZipFile, "writestr", falla)
    with pytest.raises(OSError):
        C.crear_copia(g, AHORA)
    assert sorted(p.name for p in g.copias.iterdir()) == ["whispermeet-copia-2025-01-01-000000.zip"]
    assert (g.copias / "whispermeet-copia-2025-01-01-000000.zip").read_text(encoding="utf-8") == "copia antigua"


def test_el_borrado_del_temporal_solo_alcanza_a_un_fichero_parcial_de_la_carpeta_de_copias(g, app, tmp_path):
    ajeno = _escribir(app / "planes" / "plan-aaa.json.parcial")
    C._quitar_temporal(g, ajeno)                                          # fuera de la carpeta de copias
    otro = _escribir(g.copias / "whispermeet-copia-2025-01-01-000000.zip")
    C._quitar_temporal(g, otro)                                           # no es un temporal
    assert ajeno.exists() and otro.exists()
    propio = _escribir(g.copias / (NOMBRE + ".parcial"))
    C._quitar_temporal(g, propio)
    assert not propio.exists()


def test_dos_copias_en_el_mismo_segundo_no_se_pisan(g, app, monkeypatch):
    class Reloj(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 3, 12, 10, 42, 7)
    monkeypatch.setattr(C, "datetime", Reloj)
    a, b = C.crear_copia(g), C.crear_copia(g)
    assert (a["nombre"], b["nombre"]) == (NOMBRE, "whispermeet-copia-2026-03-12-104208.zip")
    assert (g.copias / NOMBRE).is_file() and (g.copias / b["nombre"]).is_file()


def test_no_se_pisa_una_copia_con_el_mismo_nombre(g, app):
    C.crear_copia(g, AHORA)
    antes = (g.copias / NOMBRE).read_bytes()
    with pytest.raises(FileExistsError):
        C.crear_copia(g, AHORA)
    assert (g.copias / NOMBRE).read_bytes() == antes and not list(g.copias.glob("*.parcial"))


def test_nunca_borra_copias_antiguas(g, app):
    viejas = [_escribir(g.copias / f"whispermeet-copia-2025-01-0{i}-000000.zip", "vieja") for i in range(1, 4)]
    C.crear_copia(g, AHORA)
    assert all(v.exists() for v in viejas)


# ============================================================ el Guardián
def test_ruta_copia_valida_el_nombre_con_un_patron_estricto(g):
    assert g.ruta_copia(NOMBRE) == g.copias / NOMBRE
    assert g.ruta_copia(NOMBRE, parcial=True) == g.copias / (NOMBRE + ".parcial")
    for malo in ("../" + NOMBRE, "sub/" + NOMBRE, "sub\\" + NOMBRE, NOMBRE + "\n", NOMBRE.replace(".zip", ".exe"), "copia.zip", "", "..", "C:/x.zip",
                 "whispermeet-copia-2026-03-12-1042.zip", NOMBRE.upper(), None, 5):
        with pytest.raises(RutaProhibida):
            g.ruta_copia(malo)


def test_el_guardian_sin_copias_configuradas_no_da_ruta(tmp_path):
    g2 = Guardian(tmp_path / "p", tmp_path / "b", tmp_path / "c")
    with pytest.raises(RutaProhibida):
        g2.ruta_copia(NOMBRE)
    with pytest.raises(RutaProhibida):
        g2.listar_copias()


def test_listar_copias_ordena_las_mas_recientes_primero_y_solo_lista_copias(g, app):
    assert g.listar_copias() == []   # la carpeta aún no existe
    a = _escribir(g.copias / "whispermeet-copia-2026-01-01-000000.zip", "a")
    b = _escribir(g.copias / "whispermeet-copia-2026-02-01-000000.zip", "bb")
    c = _escribir(g.copias / "whispermeet-copia-2026-03-01-000000.zip", "ccc")
    _escribir(g.copias / "notas.txt")
    _escribir(g.copias / (NOMBRE + ".parcial"))
    for i, p in enumerate((a, b, c)):
        os.utime(p, (1_700_000_000 + i * 100, 1_700_000_000 + i * 100))
    lista = g.listar_copias()
    assert [x["nombre"] for x in lista] == [c.name, b.name, a.name]
    assert [x["bytes"] for x in lista] == [3, 2, 1]
    assert all(re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", x["fecha"]) for x in lista)


def test_el_guardian_no_gana_ningun_metodo_de_borrado():
    malos = [n for n in dir(Guardian) if "copia" in n and re.search(r"borr|elimin|remov|delet|quit|limpi|purg|unlink", n)]
    assert malos == []


def test_abrir_la_carpeta_de_copias_la_crea_si_falta_y_usa_el_abridor(g):
    abiertos = []
    assert not g.copias.exists()
    g.abrir_carpeta_copias(abiertos.append)
    assert g.copias.is_dir() and abiertos == [str(g.copias)]


# ============================================================ la API
class Mudo(ModeloLLM):
    def completar(self, *a, **k):   # pragma: no cover
        raise AssertionError("la copia no llama al modelo")


@pytest.fixture
def servidor(tmp_path, g):
    cfg = Config(tmp_path / "config.json")
    cfg.actualizar({"raiz_proyectos": str(tmp_path / "app" / "proyectos"), "knowledge": ""}, guardar=False)
    abiertos = []
    dif = Difusor()
    gestor = Gestor(cfg, g, Consumo(None), Mudo(), dif.emitir)
    app_ = crear_app(gestor, dif, cfg, g, "t0k3n", 8124, backlog=Backlog(g, cfg, abridor=abiertos.append))
    cli = TestClient(app_, base_url="http://127.0.0.1:8124", headers={"X-Token": "t0k3n"})
    return cli, gestor, g, abiertos


def test_la_api_exige_el_token(servidor):
    cli, *_ = servidor
    with cli:
        for metodo, ruta in (("get", "/api/copia"), ("post", "/api/copia"), ("post", "/api/copia/abrir")):
            assert getattr(cli, metodo)(ruta, headers={"X-Token": "otro"}).status_code == 401


def test_get_lista_las_copias_y_la_carpeta(servidor):
    cli, gestor, g, _ = servidor
    with cli:
        d = cli.get("/api/copia").json()
        assert d == {"copias": [], "carpeta": g.copias.name}   # solo el nombre: la ruta local no sale del servidor
        r = cli.post("/api/copia")
        assert r.status_code == 200
        d = cli.get("/api/copia").json()
        assert [x["nombre"] for x in d["copias"]] == [r.json()["nombre"]] and set(d["copias"][0]) == {"nombre", "bytes", "fecha"}


def test_post_crea_la_copia_y_devuelve_el_resultado(servidor):
    cli, gestor, g, _ = servidor
    with cli:
        r = cli.post("/api/copia")
    assert r.status_code == 200
    d = r.json()
    assert re.fullmatch(r"whispermeet-copia-\d{4}-\d{2}-\d{2}-\d{6}\.zip", d["nombre"]) and d["omitidos"] == [] and d["bytes"] > 0
    assert d["ficheros"] == len(nombres(g.copias / d["nombre"])) - 1


@pytest.mark.parametrize("estado", ["preparando", "grabando", "pausada", "terminando"])
def test_durante_una_reunion_responde_409_y_no_crea_nada(servidor, estado):
    cli, gestor, g, _ = servidor
    gestor.estado = estado
    with cli:
        r = cli.post("/api/copia")
    assert r.status_code == 409 and r.json()["detail"] == "Haz la copia fuera de una reunión."
    assert not g.copias.exists() or not any(g.copias.iterdir())


def test_con_una_copia_en_curso_responde_409(servidor, monkeypatch):
    cli, gestor, g, _ = servidor
    dentro, soltar = threading.Event(), threading.Event()
    original = C.crear_copia

    def lenta(*a, **k):
        dentro.set()
        assert soltar.wait(20)
        return original(*a, **k)
    monkeypatch.setattr(C, "crear_copia", lenta)
    primera = {}
    with cli:
        t = threading.Thread(target=lambda: primera.update(r=cli.post("/api/copia")))
        t.start()
        assert dentro.wait(20)
        segunda = cli.post("/api/copia")
        soltar.set()
        t.join(30)
        tercera = cli.post("/api/copia")
    assert segunda.status_code == 409 and segunda.json()["detail"] == "Ya hay una copia en curso."
    assert primera["r"].status_code == 200
    assert tercera.status_code == 200   # el cerrojo se libera


def test_el_trabajo_de_disco_no_corre_en_el_bucle_de_asyncio(servidor, monkeypatch):
    cli, gestor, g, _ = servidor
    visto = []
    original = C.crear_copia

    def mide(*a, **k):
        try:
            asyncio.get_running_loop()
            visto.append("en el bucle")
        except RuntimeError:
            visto.append("en un hilo")
        return original(*a, **k)
    monkeypatch.setattr(C, "crear_copia", mide)
    with cli:
        assert cli.post("/api/copia").status_code == 200
    assert visto == ["en un hilo"]


def test_un_fallo_libera_el_cerrojo_y_se_dice(servidor, monkeypatch):
    cli, gestor, g, _ = servidor
    original = C.crear_copia
    monkeypatch.setattr(C, "crear_copia", lambda *a, **k: (_ for _ in ()).throw(OSError(28, "No queda espacio en el dispositivo")))
    with cli:
        r = cli.post("/api/copia")
        assert r.status_code == 400 and "No se pudo crear la copia" in r.json()["detail"]
        monkeypatch.setattr(C, "crear_copia", original)
        assert cli.post("/api/copia").status_code == 200


def test_abrir_usa_el_abridor_y_crea_la_carpeta_si_falta(servidor):
    cli, gestor, g, abiertos = servidor
    assert not g.copias.exists()
    with cli:
        r = cli.post("/api/copia/abrir")
    assert r.status_code == 200 and r.json() == {"ok": True}
    assert abiertos == [str(g.copias)] and g.copias.is_dir()


def test_abrir_funciona_durante_una_reunion(servidor):
    cli, gestor, g, abiertos = servidor
    gestor.estado = "grabando"
    with cli:
        assert cli.post("/api/copia/abrir").status_code == 200
    assert abiertos == [str(g.copias)]


def test_el_servidor_construye_el_guardian_con_la_carpeta_de_copias_de_la_configuracion(tmp_path):
    """`app.construir` de verdad, con todas las rutas en la carpeta temporal: la carpeta de copias es la de --copias y el fichero de ajustes es el de la configuración."""
    import argparse
    import app as A
    t = tmp_path / "t"
    cfg_json = t / "config.json"
    cfg_json.parent.mkdir(parents=True)
    cfg_json.write_text(json.dumps({"raiz_proyectos": str(t / "proyectos"), "knowledge": "", "proyectos_extra": []}), encoding="utf-8")
    (t / "proyectos").mkdir()
    pr = lambda n: str(t / n)   # noqa: E731
    args = argparse.Namespace(config=str(cfg_json), raiz=None, extra=[f"Ficticio={t / 'proyectos'}"], simular=None, planes=pr("planes"), sesiones=pr("sesiones"), checks=pr("checks"),
                              tipos=pr("tipos"), copias=pr("copias"), cache=pr("cache"), bandeja=pr("bandeja"), backlog=pr("backlog"), datos=pr("datos"), consumo=pr("consumo.jsonl"), velocidad=30.0)
    cfg, guardian, gestor, difusor = A.construir(args)
    assert guardian.copias == (t / "copias").resolve() and guardian.ajustes == cfg.ruta == cfg_json.resolve()
    assert not (t / "copias").exists()   # construir no crea la carpeta de copias
    from apuntes import config
    assert config.COPIAS_DIR == config.APP_DIR / "copias" and config.COPIAS_DIR.parent == config.DATOS_DIR.parent
    assert "copias/" in (Path(config.APP_DIR) / ".gitignore").read_text(encoding="utf-8").split()
    assert "/MANIFIESTO.json" in (Path(config.APP_DIR) / ".gitignore").read_text(encoding="utf-8").split()


def test_las_pruebas_no_pueden_apuntar_a_la_carpeta_de_copias_real(entorno):
    g, raiz, tmp_path, _ = entorno
    from apuntes.config import APP_DIR
    assert g.copias is not None and tmp_path in g.copias.parents and not str(g.copias).startswith(str(APP_DIR / "copias"))


# ============================================================ F1-arreglos: un fichero raro no tumba la copia
def _con_fecha(ruta: Path, instante: float) -> Path:
    os.utime(ruta, (instante, instante))
    return ruta


def test_un_fichero_con_fecha_posterior_a_2107_entra_con_la_fecha_recortada(g, app):
    _con_fecha(app / "planes" / "plan-aaa.json", 7258118400)   # año 2200
    r = C.crear_copia(g, AHORA)
    assert r["omitidos"] == [] and "planes/plan-aaa.json" in nombres(zip_de(g, r))
    with zipfile.ZipFile(zip_de(g, r)) as z:
        assert z.getinfo("planes/plan-aaa.json").date_time[0] == 2107
        assert z.read("planes/plan-aaa.json").decode("utf-8") == '{"sesiones": []}'


def test_un_fichero_con_fecha_de_1975_entra_con_la_fecha_del_suelo(g, app):
    _con_fecha(app / "planes" / "plan-aaa.json", 157766400)   # 1975
    r = C.crear_copia(g, AHORA)
    assert r["omitidos"] == []
    with zipfile.ZipFile(zip_de(g, r)) as z:
        assert z.getinfo("planes/plan-aaa.json").date_time == (1980, 1, 1, 0, 0, 0)


def test_la_fecha_del_zip_con_una_zona_de_desfase_negativo_no_baja_de_1980(monkeypatch):
    # el suelo en UTC (315532800) es el 31-12-1979 en una zona al oeste de Greenwich: se simula sin tocar el reloj del sistema
    monkeypatch.setattr(C.time, "localtime", lambda t=None: time.struct_time((1979, 12, 31, 19, 0, 0, 0, 365, 0)))
    assert C._fecha_zip(315532800) == (1980, 1, 1, 0, 0, 0)
    zipfile.ZipInfo("x", date_time=C._fecha_zip(315532800))   # no lanza


@pytest.mark.parametrize("mtime", [-5e12, 1e30, float("nan"), float("inf"), -1.0])
def test_una_fecha_que_localtime_no_admite_da_una_fecha_valida(mtime):
    f = C._fecha_zip(mtime)
    assert (1980, 1, 1, 0, 0, 0) <= f <= (2107, 12, 31, 23, 59, 58)
    zipfile.ZipInfo("x", date_time=f)


def test_localtime_que_falla_da_el_suelo(monkeypatch):
    def falla(t=None):
        raise OSError(22, "Invalid argument")
    monkeypatch.setattr(C.time, "localtime", falla)
    assert C._fecha_zip(1_700_000_000) == (1980, 1, 1, 0, 0, 0)


def test_la_fecha_normal_se_conserva_y_el_techo_es_2107():
    assert C._fecha_zip(1_700_000_000) == tuple(time.localtime(1_700_000_000)[:6])
    assert (2107, 1, 1, 0, 0, 0) <= C._fecha_zip(7258118400) <= (2107, 12, 31, 23, 59, 58)


def test_un_nombre_que_no_se_puede_codificar_va_a_omitidos_y_la_copia_sigue(g, app, monkeypatch):
    real = app / "planes" / "plan-aaa.json"
    original = C._candidatos

    def con_suplente(fuente, prefijo, copias, omitidos):
        yield from original(fuente, prefijo, copias, omitidos)
        if prefijo == "planes":
            yield real, "planes/raro-\udc80.json"
    monkeypatch.setattr(C, "_candidatos", con_suplente)
    r = C.crear_copia(g, AHORA)
    assert "checks/alfa.json" in nombres(zip_de(g, r)) and r["ficheros"] == 9
    assert len(r["omitidos"]) == 1 and r["omitidos"][0]["motivo"].endswith(".") and "nombre" in r["omitidos"][0]["motivo"].lower()
    json.dumps(r, ensure_ascii=False).encode("utf-8")           # la respuesta es serializable
    with zipfile.ZipFile(zip_de(g, r)) as z:
        m = json.loads(z.read("MANIFIESTO.json").decode("utf-8"))
    assert all("\udc80" not in f["ruta"] for f in m["ficheros"])


def test_un_fallo_de_un_fichero_al_escribir_su_entrada_va_a_omitidos(g, app, monkeypatch):
    original = zipfile.ZipFile.writestr

    def falla(self, info, data, *a, **k):
        if getattr(info, "filename", info) == "checks/alfa.json":
            raise ValueError("entrada rara")
        return original(self, info, data, *a, **k)
    monkeypatch.setattr(zipfile.ZipFile, "writestr", falla)
    r = C.crear_copia(g, AHORA)
    assert [o["ruta"] for o in r["omitidos"]] == ["checks/alfa.json"] and "checks/alfa.json" not in nombres(zip_de(g, r))
    assert "planes/plan-aaa.json" in nombres(zip_de(g, r))


# ============================================================ F1-arreglos: lo que no entra no se calla
def test_un_fichero_parcial_fuera_de_la_carpeta_de_copias_es_un_dato_mas(g, app):
    _escribir(app / "datos" / "ola4" / "informe.json.parcial", "dato parcial ficticio")
    r = C.crear_copia(g, AHORA)
    assert "datos/ola4/informe.json.parcial" in nombres(zip_de(g, r)) and r["omitidos"] == []


def test_un_parcial_dentro_de_la_carpeta_de_copias_no_entra_aunque_este_en_datos(tmp_path):
    a = tmp_path / "app"
    _escribir(a / "datos" / "glosario.json")
    g2 = Guardian(a / "p", a / "b", a / "c", datos=a / "datos", copias=a / "datos" / "copias")
    _escribir(g2.copias / "whispermeet-copia-2020-01-01-000000.zip.parcial")
    r = C.crear_copia(g2, AHORA)
    assert nombres(g2.copias / r["nombre"]) == {"MANIFIESTO.json", "glosario.json"} and r["omitidos"] == []


def test_dos_ficheros_con_la_misma_ruta_dentro_del_zip_el_segundo_va_a_omitidos(tmp_path, monkeypatch):
    a = tmp_path / "app"
    _escribir(a / "datos" / "x.json", "dentro")
    _escribir(tmp_path / "uno" / "datos" / "a.json", "primero")
    _escribir(tmp_path / "dos" / "datos" / "a.json", "segundo")   # misma carpeta final «datos»: misma ruta en el zip
    g2 = Guardian(a / "p", a / "b", a / "c", datos=a / "datos", copias=a / "copias")
    monkeypatch.setattr(g2, "fuentes_de_copia", lambda: [tmp_path / "uno" / "datos", tmp_path / "dos" / "datos"])
    r = C.crear_copia(g2, AHORA)
    assert nombres(g2.copias / r["nombre"]) == {"MANIFIESTO.json", "datos/a.json"}
    with zipfile.ZipFile(g2.copias / r["nombre"]) as z:
        assert z.read("datos/a.json").decode("utf-8") == "primero"
    assert len(r["omitidos"]) == 1 and r["omitidos"][0]["ruta"] == "datos/a.json" and "otro fichero" in r["omitidos"][0]["motivo"]


# ============================================================ F1-arreglos: la API
def test_un_fallo_inesperado_se_dice_en_espanol_sin_traza_y_queda_en_el_registro(servidor, monkeypatch, tmp_path):
    cli, gestor, g, _ = servidor
    original = C.crear_copia
    monkeypatch.setattr(C, "crear_copia", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("detalle interno de la ruta secreta")))
    with cli:
        r = cli.post("/api/copia")
        assert r.status_code == 400 and r.json()["detail"].startswith("No se pudo crear la copia")
        assert "RuntimeError" not in r.text and "secreta" not in r.text and "Traceback" not in r.text
        monkeypatch.setattr(C, "crear_copia", original)
        assert cli.post("/api/copia").status_code == 200   # el cerrojo se liberó
    assert "RuntimeError" in (tmp_path / "apuntes.log").read_text(encoding="utf-8")


def _router(servidor):
    from apuntes import api_copia
    cli, gestor, g, _ = servidor
    return api_copia, api_copia.crear_router(gestor, None, g, lambda f: f)


def test_si_se_cancela_la_espera_con_la_copia_en_marcha_una_segunda_peticion_no_arranca_otra(servidor, monkeypatch):
    api_copia, r = _router(servidor)
    dentro, soltar, llamadas = threading.Event(), threading.Event(), []

    def lenta(guardian, *a, **k):
        llamadas.append(1)
        dentro.set()
        assert soltar.wait(20)
        return {"nombre": "x"}
    monkeypatch.setattr(C, "crear_copia", lenta)

    async def escenario():
        tarea = asyncio.ensure_future(asyncio.to_thread(r.copiar_en_hilo))
        await asyncio.to_thread(dentro.wait, 20)
        tarea.cancel()                                   # el cliente se desconecta: la espera se cancela, el hilo sigue
        with pytest.raises(asyncio.CancelledError):
            await tarea
        with pytest.raises(api_copia.CopiaEnCurso):      # el hilo sigue escribiendo: el cerrojo sigue cogido
            await asyncio.to_thread(r.copiar_en_hilo)
        soltar.set()
    asyncio.run(escenario())
    assert len(llamadas) == 1                            # la segunda no arrancó otra copia
    fin = time.time() + 20
    while time.time() < fin:                             # cuando el hilo acaba, el cerrojo se libera solo
        try:
            assert r.copiar_en_hilo() == {"nombre": "x"}
            break
        except api_copia.CopiaEnCurso:
            time.sleep(0.05)
    assert len(llamadas) == 2


def test_el_cerrojo_empieza_libre_y_no_se_coge_fuera_de_la_funcion_del_hilo(servidor):
    api_copia, r = _router(servidor)
    assert r.cerrojo.acquire(blocking=False)
    r.cerrojo.release()
