"""Mapa de documentos del proyecto: clasificación por nombre, carpeta y extensión, inventario sin abrir ficheros y API con ids opacos.
Todo con un árbol ficticio en tmp_path."""
import builtins
import os
import pathlib
import time

import pytest
from fastapi.testclient import TestClient

from apuntes import inventario as INV
from apuntes.backlog import Backlog
from apuntes.config import Config
from apuntes.consumo import Consumo
from apuntes.gestor import Gestor
from apuntes.rutas import CARPETA_CONTEXTO, CARPETA_SESIONES, EXT_ABRIBLES, Guardian, RutaProhibida
from apuntes.servidor import Difusor, crear_app
from test_gestor_plan import Falso, lineas

PUERTO, TOKEN = 8125, "t0k3n"
PROY = "Reservas Norte"


# ---------------------------------------------------------------- clasificar
@pytest.mark.parametrize("rel,tipo", [
    ("Acta kick-off.docx", "arranque"),
    ("Plan de pruebas UAT.xlsx", "pruebas"),
    ("Manual de usuario.pdf", "pruebas"),
    ("Modelo de datos funcional.xlsx", "datos"),
    ("Matriz de roles y permisos.xlsx", "usuarios"),
    ("Plan de sesiones.xlsx", "planificacion"),
    ("Diseño técnico de integraciones.docx", "tecnico"),
    ("03 Funcional/DF Reservas v2.docx", "funcional"),
    ("Acta 2026-03-02.docx", "seguimiento"),
    ("Oferta económica.pdf", "oferta"),
    ("DISEÑO_TECNICO-v3.DOCX", "tecnico"),
    ("Kickoff_Reservas.pptx", "arranque"),
    ("Historias de usuarios.docx", "funcional"),
    ("Diccionario_de_datos.xlsx", "datos"),
    ("Cronograma.mpp", "planificacion"),
    ("Informe de seguimiento semanal.pdf", "seguimiento"),
    ("Formación.pptx", "pruebas"),
])
def test_clasifica_por_nombre(rel, tipo):
    assert INV.clasificar(rel)[0] == tipo


def test_motivos_explican_la_regla():
    assert INV.clasificar("Acta kick-off.docx")[1] == "nombre: «kick-off»"
    assert INV.clasificar("03 Funcional/DF Reservas v2.docx") == ("funcional", "carpeta: «03 Funcional»")
    assert INV.clasificar("scripts/crear.sql") == ("datos", "extensión .sql")
    assert INV.clasificar("x/Plan.mpp")[0] == "planificacion"
    assert INV.clasificar("x/raro.pdf") == ("otros", "sin pista en el nombre ni en la carpeta")


def test_carpetas_de_la_app():
    assert INV.clasificar(f"{CARPETA_CONTEXTO}/01-ficha.md") == ("contexto", "carpeta de contexto para la IA")
    assert INV.clasificar(f"{CARPETA_SESIONES}/2026-11-01-reunion.md") == ("seguimiento", "sesión grabada con la app")


def test_precedencia_nombre_carpeta_extension():
    assert INV.clasificar("Funcional/Notas.docx")[0] == "seguimiento"            # el nombre gana a la carpeta
    assert INV.clasificar("Planificación/crear.sql")[0] == "planificacion"      # la carpeta gana a la extensión
    assert INV.clasificar("Funcional/Técnico/algo.docx") == ("tecnico", "carpeta: «Técnico»")   # la carpeta más cercana primero
    assert INV.clasificar("Arranque/Plan de pruebas.docx")[0] == "pruebas"


# ---------------------------------------------------------------- Guardian y mapa
def escribir(p, texto="x"):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(texto, encoding="utf-8")
    return p


def guardian(tmp_path, raiz):
    return Guardian(raiz, tmp_path / "bandeja", tmp_path / "cache", sesiones_locales=tmp_path / "sesiones")


def arbol(tmp_path):
    raiz = tmp_path / "proyectos"
    p = raiz / PROY
    ahora = time.time()
    f = escribir(p / "Oferta v1.docx"); os.utime(f, (ahora - 30 * 86400,) * 2)
    f = escribir(p / "Oferta v2.docx"); os.utime(f, (ahora - 10 * 86400,) * 2)
    escribir(p / "Funcional" / "DF Reservas.docx")
    escribir(p / "Acta kick-off.pptx")
    escribir(p / "logo.png")
    escribir(p / "src" / "app.py")
    escribir(p / "~$Oferta v2.docx")
    escribir(p / ".oculta" / "Oferta secreta.docx")
    escribir(p / "node_modules" / "x" / "Oferta.docx")
    escribir(p / "credenciales.docx")
    escribir(p / "Thumbs.db")
    escribir(p / CARPETA_SESIONES / "2026-11-01-reunion.md")
    escribir(p / CARPETA_CONTEXTO / "01-ficha.md")
    escribir(p / "a" / "b" / "c" / "d" / "e" / "f" / "g" / "Hondo.docx")
    return raiz, p


def test_ficheros_del_proyecto_excluye_y_respeta_profundidad(tmp_path):
    raiz, p = arbol(tmp_path)
    r = guardian(tmp_path, raiz).ficheros_del_proyecto(PROY)
    rels = {f["rel"] for f in r["ficheros"]}
    assert "Oferta v1.docx" in rels and "src/app.py" in rels and "logo.png" in rels
    assert f"{CARPETA_SESIONES}/2026-11-01-reunion.md" in rels and f"{CARPETA_CONTEXTO}/01-ficha.md" in rels
    for fuera in ("~$Oferta v2.docx", ".oculta/Oferta secreta.docx", "node_modules/x/Oferta.docx", "credenciales.docx", "Thumbs.db",
                  "a/b/c/d/e/f/g/Hondo.docx"):
        assert fuera not in rels
    f = next(x for x in r["ficheros"] if x["rel"] == "Funcional/DF Reservas.docx")
    assert os.path.isabs(f["ruta"]) and f["nombre"] == "DF Reservas.docx" and f["ext"] == ".docx" and f["prof"] == 1 and f["nube"] is False
    assert r["truncado"] is False


def test_ficheros_del_proyecto_truncado_y_proyecto_desconocido(tmp_path):
    raiz, _ = arbol(tmp_path)
    g = guardian(tmp_path, raiz)
    assert g.ficheros_del_proyecto(PROY, max_visitas=3)["truncado"] is True
    with pytest.raises(RutaProhibida):
        g.ficheros_del_proyecto("NoExiste")


def test_mapa_tipos_faltan_orden_y_conteos(tmp_path):
    raiz, _ = arbol(tmp_path)
    m = INV.mapa(guardian(tmp_path, raiz), PROY)
    assert [t["clave"] for t in m["tipos"]] == [t["clave"] for t in INV.TIPOS]
    por = {t["clave"]: t for t in m["tipos"]}
    assert [f["nombre"] for f in por["oferta"]["ficheros"]] == ["Oferta v2.docx", "Oferta v1.docx"]   # el más reciente primero
    assert por["oferta"]["ultimo"]["nombre"] == "Oferta v2.docx" and por["oferta"]["dias"] == 10 and por["oferta"]["n"] == 2
    assert por["funcional"]["ficheros"][0]["carpeta"] == "Funcional" and por["oferta"]["ficheros"][0]["carpeta"] == ""
    assert por["arranque"]["n"] == 1 and por["contexto"]["n"] == 1 and por["seguimiento"]["n"] == 1
    assert por["tecnico"]["n"] == 0 and por["tecnico"]["ultimo"] is None and por["tecnico"]["dias"] is None
    assert [x["clave"] for x in m["faltan"]] == ["tecnico", "datos", "usuarios", "planificacion"]
    assert all(x["pista"] for x in m["faltan"])
    assert m["total"] == 6 and m["ignorados"] == 2 and m["en_nube"] == 0 and m["truncado"] is False
    assert not any(f["nombre"].startswith("~$") for t in m["tipos"] for f in t["ficheros"])
    assert all(f["motivo"] for t in m["tipos"] for f in t["ficheros"])


def test_mapa_max_por_tipo_y_ahora_inyectable(tmp_path):
    raiz, p = arbol(tmp_path)
    m = INV.mapa(guardian(tmp_path, raiz), PROY, ahora=time.time() + 5 * 86400, max_por_tipo=1)
    o = next(t for t in m["tipos"] if t["clave"] == "oferta")
    assert len(o["ficheros"]) == 1 and o["mas"] == 1 and o["dias"] == 15


def test_mapa_no_abre_ningun_fichero(tmp_path, monkeypatch):
    raiz, _ = arbol(tmp_path)
    g = guardian(tmp_path, raiz)

    def prohibido(*a, **k):
        raise AssertionError("el inventario no puede abrir ficheros")
    monkeypatch.setattr(builtins, "open", prohibido)
    monkeypatch.setattr(pathlib.Path, "open", prohibido)
    monkeypatch.setattr(pathlib.Path, "read_text", prohibido)
    monkeypatch.setattr(pathlib.Path, "read_bytes", prohibido)
    assert INV.mapa(g, PROY)["total"] == 6


def test_mapa_proyecto_desconocido(tmp_path):
    raiz, _ = arbol(tmp_path)
    with pytest.raises(RutaProhibida):
        INV.mapa(guardian(tmp_path, raiz), "NoExiste")


# ---------------------------------------------------------------- abrir_documento_proyecto
def test_abrir_documento_lista_cerrada_y_confinamiento(tmp_path):
    raiz, p = arbol(tmp_path)
    escribir(p / "Macro.docm")
    escribir(p / "Hoja.xlsm")
    g = guardian(tmp_path, raiz)
    abiertos = []
    g.abrir_documento_proyecto(PROY, p / "Oferta v1.docx", abiertos.append)
    g.abrir_documento_proyecto(PROY, p / CARPETA_SESIONES / "2026-11-01-reunion.md", abiertos.append)   # aquí sí se admiten las sesiones
    assert len(abiertos) == 2
    ajeno = escribir(tmp_path / "fuera.docx")
    for malo in (p / "Macro.docm", p / "Hoja.xlsm", p / "logo.png", p / "credenciales.docx", p / ".oculta" / "Oferta secreta.docx",
                 p / "NoExiste.docx", ajeno, p / "Funcional"):
        with pytest.raises(RutaProhibida):
            g.abrir_documento_proyecto(PROY, malo, abiertos.append)
    assert len(abiertos) == 2 and ".docm" not in EXT_ABRIBLES and ".xlsm" not in EXT_ABRIBLES


# ---------------------------------------------------------------- API
def cliente(tmp_path, abiertos):
    raiz, p = arbol(tmp_path)
    escribir(p / "Macro.docm")
    escribir(raiz / "Otro" / "Oferta otro.docx")
    cfg = Config(tmp_path / "config.json")
    cfg.actualizar({"raiz_proyectos": str(raiz), "knowledge": ""}, guardar=False)
    g = Guardian(raiz, tmp_path / "bandeja", tmp_path / "cache", sesiones_locales=tmp_path / "sesiones")
    dif = Difusor()
    gestor = Gestor(cfg, g, Consumo(None), Falso(), dif.emitir, simulacion=lineas(), velocidad=200)
    bl = Backlog(g, cfg, abridor=abiertos.append)
    app = crear_app(gestor, dif, cfg, g, TOKEN, PUERTO, backlog=bl)
    return TestClient(app, base_url=f"http://127.0.0.1:{PUERTO}", headers={"X-Token": TOKEN}), p


def test_api_documentos_sin_rutas_y_abrir_con_ids(tmp_path):
    abiertos = []
    cli, p = cliente(tmp_path, abiertos)
    with cli:
        r = cli.get(f"/api/proyectos/{PROY}/documentos")
        assert r.status_code == 200
        assert str(tmp_path) not in r.text and str(tmp_path).replace("\\", "/") not in r.text and "ruta" not in r.text
        d = r.json()
        fich = [f for t in d["tipos"] for f in t["ficheros"]]
        oferta = next(f for f in fich if f["nombre"] == "Oferta v1.docx")
        macro = next(f for f in fich if f["nombre"] == "Macro.docm")
        assert oferta["abrible"] is True and macro["abrible"] is False
        assert cli.post(f"/api/proyectos/{PROY}/documentos/{oferta['id']}/abrir").status_code == 200
        assert abiertos == [str(p / "Oferta v1.docx")]
        assert cli.post(f"/api/proyectos/{PROY}/documentos/{macro['id']}/abrir").status_code == 404
        for malo in ("0123456789abcdef", "C:/Windows/win.ini", "Oferta v1.docx"):
            assert cli.post(f"/api/proyectos/{PROY}/documentos/{malo}/abrir").status_code in (404, 405)
        # un id de otro proyecto (o del listado de este usado en otro) no vale
        assert cli.post(f"/api/proyectos/Otro/documentos/{oferta['id']}/abrir").status_code == 404
        otro = cli.get("/api/proyectos/Otro/documentos").json()
        idotro = otro["tipos"][1]["ficheros"][0]["id"]
        assert cli.post(f"/api/proyectos/{PROY}/documentos/{idotro}/abrir").status_code == 404
        assert cli.get("/api/proyectos/NoExiste/documentos").status_code == 404
        assert abiertos == [str(p / "Oferta v1.docx")]
