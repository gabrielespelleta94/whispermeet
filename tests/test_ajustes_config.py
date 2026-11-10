"""Ajustes que solo estaban en el fichero (ola D): carpeta de Knowledge, vocabulario de transcripción y ancho de búsqueda de Whisper en `PUT /api/config`.
Validación en el servidor (tipos, topes, la carpeta existe y no es de secretos ni se solapa con lo que la app escribe), con el error y el campo al que pertenece.
Datos ficticios."""
import asyncio
import json
import os
import re
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from apuntes.analisis import ModeloLLM
from apuntes.config import APP_DIR, BEAM_MAX, BEAM_MIN, Config, validar_beam, validar_vocabulario_estricto
from apuntes.consumo import Consumo
from apuntes.gestor import Gestor
from apuntes.rutas import Guardian, RutaProhibida
from apuntes.servidor import Difusor, crear_app

PUERTO, TOKEN = 8132, "t0k3n-aj"


class SinModelo(ModeloLLM):
    def completar(self, *a, **k):
        raise AssertionError("Ajustes no llama a ningún modelo")


def _montaje(tmp_path):
    raiz = tmp_path / "proyectos"
    (raiz / "ProyA").mkdir(parents=True)
    ajena = tmp_path / "ajena"
    ajena.mkdir()
    cfg = Config(tmp_path / "config.json")
    cfg.actualizar({"raiz_proyectos": str(raiz), "knowledge": "", "proyectos_extra": [{"nombre": "Extra", "ruta": str(ajena), "compartido": False}]}, guardar=False)
    g = Guardian(raiz, tmp_path / "bandeja", tmp_path / "cache", extras=cfg["proyectos_extra"], sesiones_locales=tmp_path / "sesiones")
    dif = Difusor()
    gestor = Gestor(cfg, g, Consumo(None), SinModelo(), dif.emitir)
    llamadas = []
    gestor.fuentes.cambiar_knowledge = lambda: llamadas.append("cambiar_knowledge")   # el índice real se prueba en test_fuentes; aquí solo que se avisa
    app = crear_app(gestor, dif, cfg, g, TOKEN, PUERTO)
    return TestClient(app, base_url=f"http://127.0.0.1:{PUERTO}", headers={"X-Token": TOKEN}), cfg, g, gestor, llamadas


def _put(cli, **cambios):
    return cli.put("/api/config", json=cambios)


def _error(r, campo):
    assert r.status_code == 400, r.text
    d = r.json()
    assert d["campo"] == campo and d["detail"], d
    return d["detail"]


# ---------------------------------------------------------------- funciones puras
@pytest.mark.parametrize("v", [BEAM_MIN, 5, BEAM_MAX])
def test_beam_valido(v):
    assert validar_beam(v) == v


@pytest.mark.parametrize("v", [0, -1, BEAM_MAX + 1, 100, "5", 5.0, 5.5, True, None, [5]])
def test_beam_invalido(v):
    with pytest.raises(ValueError):
        validar_beam(v)


def test_vocabulario_estricto_normaliza_y_rechaza():
    assert validar_vocabulario_estricto(["  Cupo   de  grupos ", "cupo de grupos", "", "SAP"]) == ["Cupo de grupos", "SAP"]
    for malo in ("SAP", ["ok", 3], ["a" * 41], [f"t{i}" for i in range(61)], ["con\x07control"], {"a": 1}, None):
        with pytest.raises(ValueError):
            validar_vocabulario_estricto(malo)
    assert len(validar_vocabulario_estricto([f"t{i}" for i in range(60)])) == 60
    assert validar_vocabulario_estricto(["a" * 40]) == ["a" * 40]


def test_el_fichero_escrito_a_mano_no_puede_poner_un_beam_fuera_de_rango(tmp_path):
    cfg = Config(tmp_path / "c.json")
    for v in (0, 99, -3, True, "7"):
        cfg.actualizar({"whisper_beam": v}, guardar=False)
        assert cfg["whisper_beam"] == 5, v
    cfg.actualizar({"whisper_beam": 8}, guardar=False)
    assert cfg["whisper_beam"] == 8


# ---------------------------------------------------------------- ancho de búsqueda y vocabulario por la API
def test_put_beam_y_vocabulario_validos(tmp_path):
    cli, cfg, _g, _ges, _ll = _montaje(tmp_path)
    with cli:
        r = _put(cli, whisper_beam=3, vocabulario_transcripcion=["  Cupo   de grupos", "SAP", "sap"])
        assert r.status_code == 200
        c = r.json()["config"]
        assert c["whisper_beam"] == 3 and c["vocabulario_transcripcion"] == ["Cupo de grupos", "SAP"]
        assert json.loads((tmp_path / "config.json").read_text(encoding="utf-8"))["whisper_beam"] == 3        # y se guarda
        assert _put(cli, vocabulario_transcripcion=[]).json()["config"]["vocabulario_transcripcion"] == []


@pytest.mark.parametrize("valor", [0, 11, "5", 2.5, True, None])
def test_put_beam_invalido_da_el_error_junto_al_campo(tmp_path, valor):
    cli, cfg, *_ = _montaje(tmp_path)
    with cli:
        _error(_put(cli, whisper_beam=valor), "whisper_beam")
    assert cfg["whisper_beam"] == 5


@pytest.mark.parametrize("valor", ["SAP, Odoo", ["ok", 3], ["a" * 41], [f"t{i}" for i in range(61)], ["mal\x00"], None])
def test_put_vocabulario_invalido_da_el_error_junto_al_campo(tmp_path, valor):
    cli, cfg, *_ = _montaje(tmp_path)
    with cli:
        _error(_put(cli, vocabulario_transcripcion=valor), "vocabulario_transcripcion")
    assert cfg["vocabulario_transcripcion"] == []


def test_un_error_no_aplica_a_medias_los_otros_cambios(tmp_path):
    cli, cfg, g, *_ = _montaje(tmp_path)
    with cli:
        _error(_put(cli, whisper_beam=8, vocabulario_transcripcion=["a" * 99], autor="Otra Persona"), "vocabulario_transcripcion")
    assert cfg["whisper_beam"] == 5 and cfg["autor"] != "Otra Persona" and not (tmp_path / "config.json").exists()


# ---------------------------------------------------------------- Knowledge
def test_knowledge_valido_se_guarda_y_el_guardian_lo_trata_como_solo_lectura(tmp_path):
    cli, cfg, g, _ges, llamadas = _montaje(tmp_path)
    doc = tmp_path / "Documentacion"
    doc.mkdir()
    with cli:
        r = _put(cli, knowledge=f"  {doc}  ")
        assert r.status_code == 200 and r.json()["config"]["knowledge"] == str(doc)
    assert cfg["knowledge"] == str(doc) and g.solo_lectura == [doc] and llamadas == ["cambiar_knowledge"]
    # lo que cuelga de Knowledge ya no admite proyectos ni escrituras: el Guardian lo sabe sin reiniciar
    dentro = doc / "ProyDentro"
    dentro.mkdir()
    with pytest.raises(RutaProhibida):
        g.validar_extra("ProyDentro", str(dentro))
    with pytest.raises(RutaProhibida):
        g._comprobar_escritura(dentro / "x.md", dentro)


def test_knowledge_vacio_lo_quita(tmp_path):
    cli, cfg, g, _ges, llamadas = _montaje(tmp_path)
    doc = tmp_path / "Documentacion"
    doc.mkdir()
    with cli:
        _put(cli, knowledge=str(doc))
        r = _put(cli, knowledge="")
        assert r.status_code == 200 and r.json()["config"]["knowledge"] == ""
        assert _put(cli, knowledge="   ").json()["config"]["knowledge"] == ""
    assert g.solo_lectura == [] and llamadas == ["cambiar_knowledge", "cambiar_knowledge"]    # al poner y al quitar; no al repetir el vacío


def test_knowledge_sin_cambio_no_reindexa(tmp_path):
    cli, _cfg, _g, _ges, llamadas = _montaje(tmp_path)
    doc = tmp_path / "Documentacion"
    doc.mkdir()
    with cli:
        _put(cli, knowledge=str(doc))
        _put(cli, knowledge=str(doc))
    assert llamadas == ["cambiar_knowledge"]


def _casos_invalidos(tmp_path):
    raiz, ajena = tmp_path / "proyectos", tmp_path / "ajena"
    fichero = tmp_path / "fichero.txt"
    fichero.write_text("x")
    secreta = tmp_path / "credenciales"
    secreta.mkdir()
    ssh = tmp_path / ".ssh"
    ssh.mkdir()
    dentro_ssh = ssh / "docs"
    dentro_ssh.mkdir()
    return {
        "relativa": "docs/ficticia",
        "no existe": str(tmp_path / "no-existe"),
        "es un fichero": str(fichero),
        "raíz de unidad": Path(str(tmp_path)).anchor,
        "nombre de secretos": str(secreta),
        "carpeta de claves": str(ssh),
        "dentro de carpeta de claves": str(dentro_ssh),
        "la raíz de proyectos": str(raiz),
        "dentro de la raíz de proyectos": str(raiz / "ProyA"),
        "contiene la raíz de proyectos": str(tmp_path),
        "un proyecto extra": str(ajena),
        "la carpeta de la app": str(APP_DIR),
        "dentro de la carpeta de la app": str(APP_DIR / "web"),
        "número": 5,
        "lista": [str(tmp_path)],
    }


def test_knowledge_invalido_da_error_en_su_campo_y_no_cambia_nada(tmp_path):
    cli, cfg, g, _ges, llamadas = _montaje(tmp_path)
    with cli:
        for motivo, ruta in _casos_invalidos(tmp_path).items():
            d = _error(_put(cli, knowledge=ruta), "knowledge")
            assert d, motivo
            assert cfg["knowledge"] == "" and g.solo_lectura == [], motivo
    assert llamadas == []


def test_knowledge_no_puede_ser_la_carpeta_de_secretos_de_la_app(tmp_path):
    """datos/ guarda la configuración y el consumo: apuntar Knowledge a ella (o a su padre) sacaría esos ficheros hacia el índice y el modelo."""
    cli, cfg, *_ = _montaje(tmp_path)
    with cli:
        _error(_put(cli, knowledge=str(APP_DIR)), "knowledge")
        _error(_put(cli, knowledge=str(APP_DIR.parent)), "knowledge")
    assert cfg["knowledge"] == ""


def test_la_raiz_nueva_no_puede_solaparse_con_el_knowledge_que_ya_hay(tmp_path):
    cli, cfg, g, *_ = _montaje(tmp_path)
    doc = tmp_path / "Documentacion"
    doc.mkdir()
    otra = doc / "proyectos-dentro"
    otra.mkdir()
    with cli:
        assert _put(cli, knowledge=str(doc)).status_code == 200
        _error(_put(cli, raiz_proyectos=str(otra)), "raiz_proyectos")
        _error(_put(cli, raiz_proyectos=str(doc)), "raiz_proyectos")
    assert cfg["raiz_proyectos"] == str(tmp_path / "proyectos")


def test_knowledge_y_raiz_en_la_misma_peticion_se_validan_juntos(tmp_path):
    cli, cfg, *_ = _montaje(tmp_path)
    nueva = tmp_path / "otros-proyectos"
    nueva.mkdir()
    with cli:
        _error(_put(cli, raiz_proyectos=str(nueva), knowledge=str(nueva / "dentro")), "knowledge")     # no existe todavía
        (nueva / "dentro").mkdir()
        _error(_put(cli, raiz_proyectos=str(nueva), knowledge=str(nueva / "dentro")), "knowledge")     # se solapa con la raíz NUEVA, no con la actual
        assert cfg["raiz_proyectos"] == str(tmp_path / "proyectos")


def test_knowledge_no_se_cambia_en_plena_reunion(tmp_path):
    cli, cfg, _g, gestor, llamadas = _montaje(tmp_path)
    doc = tmp_path / "Documentacion"
    doc.mkdir()
    gestor.estado = "grabando"
    with cli:
        d = _error(cli.put("/api/config", json=_cuerpo_de_la_interfaz(cfg, knowledge=str(doc))), "knowledge")
        assert "fuera de una reunión" in d
        assert _put(cli, whisper_beam=4).status_code == 200            # lo demás sí se puede
    assert cfg["knowledge"] == "" and llamadas == []


def test_la_api_de_ajustes_exige_token(tmp_path):
    cli, *_ = _montaje(tmp_path)
    with cli:
        assert cli.put("/api/config", json={"whisper_beam": 4}, headers={"X-Token": "otro"}).status_code == 401


# ---------------------------------------------------------------- Guardian.validar_knowledge, directo
def test_validar_knowledge_directo(tmp_path):
    g = Guardian(tmp_path / "p", tmp_path / "b", tmp_path / "c")
    (tmp_path / "p").mkdir()
    doc = tmp_path / "doc"
    doc.mkdir()
    assert g.validar_knowledge("") == "" and g.validar_knowledge(None) == "" and g.validar_knowledge("  ") == ""
    assert g.validar_knowledge(f'"{doc}"') == str(doc)
    casa = tmp_path / "casa"
    (casa / "usuario").mkdir(parents=True)
    with pytest.raises(RutaProhibida, match="demasiado amplia"):
        g.validar_knowledge(str(casa), home=casa / "usuario")        # contiene la carpeta personal
    assert g.validar_knowledge(str(casa / "usuario"), home=tmp_path / "otra-casa") == str(casa / "usuario")
    with pytest.raises(RutaProhibida):
        g.validar_knowledge(str(doc), apartadas=(doc,))
    with pytest.raises(RutaProhibida):
        g.validar_knowledge(str(doc), apartadas=(tmp_path,))


def test_un_knowledge_antiguo_que_ya_no_pasa_las_reglas_no_bloquea_otros_ajustes(tmp_path):
    """Una configuración escrita a mano antes de esta validación puede tener un Knowledge que ahora no se admitiría: guardar OTRA cosa (con la misma raíz) no se rechaza por eso."""
    cli, cfg, g, *_ = _montaje(tmp_path)
    cfg.actualizar({"knowledge": str(tmp_path)}, guardar=False)               # contiene la raíz de proyectos: no se aceptaría hoy
    with cli:
        r = _put(cli, raiz_proyectos=str(tmp_path / "proyectos"), whisper_beam=4)
        assert r.status_code == 200 and r.json()["config"]["whisper_beam"] == 4
        # pero cambiar la raíz a otra que sí se solapa, sí se rechaza
        _error(_put(cli, raiz_proyectos=str(tmp_path)), "raiz_proyectos")


# ---------------------------------------------------------------- Knowledge: la ruta se resuelve ANTES de comprobar nada
def _junction(destino: Path, enlace: Path) -> None:
    """Crea una junction (no pide permisos de administrador); si el equipo no deja, se salta el test."""
    r = subprocess.run(["cmd", "/c", "mklink", "/J", str(enlace), str(destino)], capture_output=True, encoding="oem", errors="replace")
    if r.returncode != 0 or not enlace.is_dir():
        pytest.skip("este equipo no permite crear junctions: " + (r.stdout + r.stderr).strip()[:80])


def test_knowledge_con_puntos_que_acaba_en_la_raiz_de_la_unidad_se_rechaza_por_la_api(tmp_path):
    cli, cfg, g, _ges, llamadas = _montaje(tmp_path)
    primera = tmp_path.parts[1]                                             # una carpeta de primer nivel de la unidad de tmp_path
    disfrazada = f"{tmp_path.anchor}{primera}{os.sep}.."                    # = la raíz de la unidad
    assert os.path.realpath(disfrazada) == tmp_path.anchor
    with cli:
        d = _error(_put(cli, knowledge=disfrazada), "knowledge")
        assert "unidad" in d
    assert cfg["knowledge"] == "" and g.solo_lectura == [] and llamadas == []


def test_knowledge_con_puntos_que_acaba_en_la_carpeta_personal_se_rechaza(tmp_path):
    g = Guardian(tmp_path / "p", tmp_path / "b", tmp_path / "c")
    casa = tmp_path / "casa"
    (casa / "sub").mkdir(parents=True)
    with pytest.raises(RutaProhibida, match="demasiado amplia"):
        g.validar_knowledge(str(casa / "sub" / ".."), home=casa)


def test_knowledge_junction_hacia_una_carpeta_de_claves_se_rechaza(tmp_path):
    g = Guardian(tmp_path / "p", tmp_path / "b", tmp_path / "c")
    ssh = tmp_path / "casa" / ".ssh"
    ssh.mkdir(parents=True)
    enlace = tmp_path / "Docs"
    _junction(ssh, enlace)
    with pytest.raises(RutaProhibida, match="secretos"):
        g.validar_knowledge(str(enlace), home=tmp_path / "otra-casa")


def test_knowledge_junction_hacia_la_raiz_de_proyectos_se_rechaza(tmp_path):
    raiz = tmp_path / "p"
    raiz.mkdir()
    g = Guardian(raiz, tmp_path / "b", tmp_path / "c")
    enlace = tmp_path / "Docs"
    _junction(raiz, enlace)
    with pytest.raises(RutaProhibida, match="solapa"):
        g.validar_knowledge(str(enlace), home=tmp_path / "otra-casa")


def test_knowledge_se_guarda_la_ruta_resuelta(tmp_path):
    cli, cfg, g, *_ = _montaje(tmp_path)
    doc = tmp_path / "Documentacion"
    (doc / "otra").mkdir(parents=True)
    escrita = f"{doc}{os.sep}otra{os.sep}.."
    with cli:
        r = _put(cli, knowledge=escrita)
        assert r.status_code == 200 and r.json()["config"]["knowledge"] == str(doc)
    assert cfg["knowledge"] == str(doc) and g.solo_lectura == [doc]


# ---------------------------------------------------------------- durante una reunión: se rechaza solo lo que CAMBIA
JS = Path(__file__).resolve().parent.parent / "web"


def _cuerpo_de_la_interfaz(cfg, **cambios):
    """Lo que envía el formulario de Ajustes al guardar: SIEMPRE las claves de `const cambios` de web/app.js (con los valores vigentes) y, de web/ajustes.js,
    solo las nuevas que el usuario ha cambiado. Se comprueba contra el código de la interfaz para que el test no se quede atrás si cambia."""
    texto = (JS / "app.js").read_text(encoding="utf-8")
    bloque = re.search(r"const cambios = \{(.*?)\};", texto, re.S).group(1)
    claves = set(re.findall(r"\b([a-z_0-9]+):", bloque.split("modelos:")[0])) | {"modelos"}
    c = cfg.publico()
    cuerpo = {k: c[k] for k in claves}
    cuerpo["modelos"] = dict(c["modelos"])
    assert {"raiz_proyectos", "whisper_modelo", "esfuerzo", "excluir_captura", "dispositivo_mic"} <= set(cuerpo)
    ajustes = (JS / "ajustes.js").read_text(encoding="utf-8")
    assert "cambios.whisper_beam" in ajustes and "cambios.vocabulario_transcripcion" in ajustes and "cambios.knowledge" in ajustes   # solo si cambian
    cuerpo.update(cambios)
    return cuerpo


def test_guardar_ajustes_en_plena_reunion_con_el_cuerpo_real_de_la_interfaz_funciona(tmp_path):
    cli, cfg, _g, gestor, llamadas = _montaje(tmp_path)
    gestor.estado = "grabando"
    with cli:
        r = cli.put("/api/config", json=_cuerpo_de_la_interfaz(cfg, vocabulario_transcripcion=["Término nuevo"]))
        assert r.status_code == 200, r.text
        assert r.json()["config"]["vocabulario_transcripcion"] == ["Término nuevo"]
    assert cfg["vocabulario_transcripcion"] == ["Término nuevo"] and llamadas == []


def test_en_plena_reunion_la_misma_carpeta_escrita_de_otra_forma_no_es_un_cambio(tmp_path):
    cli, cfg, g, gestor, _l = _montaje(tmp_path)
    gestor.estado = "grabando"
    raiz = cfg["raiz_proyectos"]
    otra_forma = raiz.upper() + os.sep + "ProyA" + os.sep + ".." + os.sep
    with cli:
        r = cli.put("/api/config", json=_cuerpo_de_la_interfaz(cfg, raiz_proyectos=otra_forma, vocabulario_transcripcion=["Otro"]))
        assert r.status_code == 200, r.text
    assert cfg["vocabulario_transcripcion"] == ["Otro"]


def test_en_plena_reunion_cambiar_la_raiz_se_rechaza_junto_a_su_campo(tmp_path):
    cli, cfg, g, gestor, _l = _montaje(tmp_path)
    nueva = tmp_path / "otros"
    nueva.mkdir()
    gestor.estado = "grabando"
    with cli:
        d = _error(cli.put("/api/config", json=_cuerpo_de_la_interfaz(cfg, raiz_proyectos=str(nueva), vocabulario_transcripcion=["Nada"])), "raiz_proyectos")
        assert "fuera de una reunión" in d
    assert cfg["raiz_proyectos"] == str(tmp_path / "proyectos") and g.raiz == tmp_path / "proyectos" and cfg["vocabulario_transcripcion"] == []   # no se aplica nada a medias


def test_en_plena_reunion_cambiar_el_modelo_se_rechaza_junto_a_su_campo(tmp_path):
    cli, cfg, _g, gestor, _l = _montaje(tmp_path)
    gestor.estado = "grabando"
    with cli:
        d = _error(cli.put("/api/config", json=_cuerpo_de_la_interfaz(cfg, whisper_modelo="medium")), "whisper_modelo")
        assert "fuera de una reunión" in d
    assert cfg["whisper_modelo"] == "small"


def test_fuera_de_una_reunion_la_raiz_y_el_modelo_si_se_cambian(tmp_path):
    cli, cfg, g, _ges, _l = _montaje(tmp_path)
    nueva = tmp_path / "otros"
    nueva.mkdir()
    with cli:
        assert cli.put("/api/config", json=_cuerpo_de_la_interfaz(cfg, raiz_proyectos=str(nueva), whisper_modelo="medium")).status_code == 200
    assert cfg["raiz_proyectos"] == str(nueva) and cfg["whisper_modelo"] == "medium" and g.raiz == nueva


def test_en_plena_reunion_el_mismo_knowledge_escrito_de_otra_forma_no_es_un_cambio(tmp_path):
    cli, cfg, _g, gestor, llamadas = _montaje(tmp_path)
    doc = tmp_path / "Documentacion"
    (doc / "sub").mkdir(parents=True)
    with cli:
        assert _put(cli, knowledge=str(doc)).status_code == 200
        llamadas.clear()
        gestor.estado = "grabando"
        guardada_sin_resolver = f"{doc}{os.sep}"                                  # la de un fichero escrito a mano
        cfg.actualizar({"knowledge": guardada_sin_resolver}, guardar=False)
        r = cli.put("/api/config", json=_cuerpo_de_la_interfaz(cfg, knowledge=f"{doc}{os.sep}sub{os.sep}..", vocabulario_transcripcion=["Uno"]))
        assert r.status_code == 200, r.text
    assert llamadas == [] and cfg["vocabulario_transcripcion"] == ["Uno"]       # no se reindexa: es la misma carpeta


# ---------------------------------------------------------------- Knowledge y carpetas añadidas, en los dos sentidos
def test_una_carpeta_anadida_que_contiene_el_knowledge_se_rechaza(tmp_path):
    doc = tmp_path / "Proyectos-ajenos" / "Documentacion"
    doc.mkdir(parents=True)
    g = Guardian(tmp_path / "p", tmp_path / "b", tmp_path / "c", solo_lectura=[doc])
    with pytest.raises(RutaProhibida, match="solo lectura"):
        g.validar_extra("Contenedor", str(doc.parent))                       # la CONTIENE
    with pytest.raises(RutaProhibida, match="solo lectura"):
        g.validar_extra("Dentro", str(doc))                                  # es ella misma
    otra = tmp_path / "otra-cosa"
    otra.mkdir()
    assert g.validar_extra("Otra", str(otra))["nombre"] == "Otra"


def test_la_api_de_proyectos_extra_rechaza_una_carpeta_que_contiene_el_knowledge(tmp_path):
    cli, cfg, g, *_ = _montaje(tmp_path)
    doc = tmp_path / "Contenedor" / "Documentacion"
    doc.mkdir(parents=True)
    with cli:
        assert _put(cli, knowledge=str(doc)).status_code == 200
        r = cli.post("/api/proyectos/extra", json={"nombre": "Contenedor", "ruta": str(doc.parent), "compartido": False})
        assert r.status_code == 403, r.text
    assert [e["nombre"] for e in cfg["proyectos_extra"]] == ["Extra"]


def test_el_knowledge_se_valida_contra_las_carpetas_anadidas_nuevas_no_contra_las_de_antes(tmp_path):
    cli, cfg, g, *_ = _montaje(tmp_path)
    ajena = tmp_path / "ajena"                                               # es el proyecto extra de ANTES
    nueva = tmp_path / "nueva"
    nueva.mkdir()
    with cli:
        # Knowledge en la carpeta del extra antiguo, que se quita en la misma petición: vale
        r = _put(cli, knowledge=str(ajena), proyectos_extra=[])
        assert r.status_code == 200, r.text
        assert cfg["knowledge"] == str(ajena) and cfg["proyectos_extra"] == []
        # Knowledge que se solapa con un extra NUEVO de la misma petición: se rechaza, con el campo de Knowledge
        _error(_put(cli, knowledge=str(nueva), proyectos_extra=[{"nombre": "Nuevo", "ruta": str(nueva), "compartido": False}]), "knowledge")
        assert cfg["knowledge"] == str(ajena) and cfg["proyectos_extra"] == []


# ---------------------------------------------------------------- la validación y el reindexado no corren en el bucle de eventos
def test_validar_knowledge_y_reindexar_corren_fuera_del_bucle_de_eventos(tmp_path):
    cli, cfg, g, _ges, _l = _montaje(tmp_path)
    doc = tmp_path / "Documentacion"
    doc.mkdir()
    en_bucle = {}

    def en_el_bucle() -> bool:
        try:
            asyncio.get_running_loop()
            return True
        except RuntimeError:
            return False
    original = g.validar_knowledge

    def validar(*a, **k):
        en_bucle["validar"] = en_el_bucle()
        return original(*a, **k)
    g.validar_knowledge = validar
    _ges.fuentes.cambiar_knowledge = lambda: en_bucle.__setitem__("indexar", en_el_bucle())
    with cli:
        assert _put(cli, knowledge=str(doc)).status_code == 200
    assert en_bucle == {"validar": False, "indexar": False}
