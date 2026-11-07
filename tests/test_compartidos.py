"""Proyectos extra y carpetas compartidas: durante la reunión la sesión es solo local; «02. Sesiones» solo se crea al publicar (ver test_checks)."""
import os
from pathlib import Path

import pytest

from apuntes import contexto as CX
from apuntes.config import Config, DEFAULTS
from apuntes.rutas import CARPETA_CONTEXTO, CARPETA_SESIONES, Guardian, RutaProhibida


@pytest.fixture
def compartido(tmp_path):
    raiz = tmp_path / "proyectos"
    (raiz / "ProyA" / CARPETA_CONTEXTO).mkdir(parents=True)
    ajena = tmp_path / "OneDrive de otra persona" / "PROYECTO COMPARTIDO"
    (ajena / CARPETA_CONTEXTO).mkdir(parents=True)
    (ajena / CARPETA_CONTEXTO / "02-alcance.md").write_text("# 02\n", encoding="utf-8")
    knowledge = tmp_path / "Knowledge"
    knowledge.mkdir()
    sesiones = tmp_path / "sesiones"
    g = Guardian(raiz, tmp_path / "bandeja", tmp_path / "cache", solo_lectura=[knowledge],
                 extras=[{"nombre": "Planificador X", "ruta": str(ajena), "compartido": True}],
                 sesiones_locales=sesiones, planes=tmp_path / "planes")
    return g, raiz, ajena, sesiones, tmp_path


def snapshot(carpeta: Path) -> list[str]:
    return sorted(str(p.relative_to(carpeta)) for p in carpeta.rglob("*"))


def test_sesion_de_proyecto_compartido_va_a_local_y_no_crea_02_sesiones(compartido):
    g, _, ajena, sesiones, _ = compartido
    antes = snapshot(ajena)
    ruta = g.ruta_sesion("Planificador X", "2026-11-03", "Revisión DataLake")
    assert ruta == sesiones / "planificador-x" / "2026-11-03-revision-datalake.md"
    g.escribir_sesion(ruta, "Planificador X", "hola")
    assert ruta.read_text(encoding="utf-8") == "hola"
    assert not (ajena / CARPETA_SESIONES).exists()
    assert snapshot(ajena) == antes  # la carpeta compartida queda exactamente igual


def test_no_se_puede_forzar_la_sesion_dentro_de_la_carpeta_compartida(compartido):
    g, _, ajena, _, _ = compartido
    dentro = ajena / CARPETA_SESIONES / "2026-11-03-x.md"
    with pytest.raises(RutaProhibida):
        g.escribir_sesion(dentro, "Planificador X", "no")
    assert not (ajena / CARPETA_SESIONES).exists()
    # tampoco una ruta local de otro proyecto ni con traversal
    with pytest.raises(RutaProhibida):
        g.escribir_sesion(ajena.parent / "2026-11-03-x.md", "Planificador X", "no")


def test_sesion_repetida_en_local_no_pisa(compartido):
    g, *_ = compartido
    r1 = g.ruta_sesion("Planificador X", "2026-11-03", "tema")
    g.escribir_sesion(r1, "Planificador X", "uno")
    assert g.ruta_sesion("Planificador X", "2026-11-03", "tema").name == "2026-11-03-tema-2.md"


def test_contexto_compartido_solo_nn_md_y_nada_protegido(compartido):
    g, _, ajena, _, _ = compartido
    g.escribir_contexto("Planificador X", "02-alcance.md", "# nuevo\n")
    assert (ajena / CARPETA_CONTEXTO / "02-alcance.md").read_text(encoding="utf-8") == "# nuevo\n"
    for malo in ("CLAUDE.md", "AGENTS.md", "../CLAUDE.md", "docs/x.md", ".env", "02-alcance.txt", "en-curso/x.md"):
        with pytest.raises(RutaProhibida):
            g.ruta_contexto("Planificador X", malo)


def test_el_resto_de_reglas_no_se_relaja(compartido):
    g, *_ = compartido
    for proyecto in ("..", "Planificador X/..", "NoExiste", ".git", "planificador x:ads"):
        with pytest.raises(RutaProhibida):
            g.ruta_sesion(proyecto, "2026-11-03", "t")
    # un proyecto normal de la raíz sigue guardando en su 02. Sesiones
    assert g.ruta_sesion("ProyA", "2026-11-03", "t").parent.name == CARPETA_SESIONES
    # el nombre del proyecto extra no abre rutas arbitrarias
    assert g.proyecto_dir("planificador x").name == "PROYECTO COMPARTIDO"


def test_extras_peligrosos_se_descartan(tmp_path):
    ok = tmp_path / "ok"
    ok.mkdir()
    knowledge = tmp_path / "Knowledge"
    knowledge.mkdir()
    secreto = tmp_path / ".git"
    secreto.mkdir()
    raiz_unidad = Path(tmp_path.anchor)
    g = Guardian(tmp_path / "r", tmp_path / "b", tmp_path / "c", solo_lectura=[knowledge], extras=[
        {"nombre": "Bueno", "ruta": str(ok), "compartido": True},
        {"nombre": "Inexistente", "ruta": str(tmp_path / "nada"), "compartido": True},
        {"nombre": "EnKnowledge", "ruta": str(knowledge), "compartido": True},
        {"nombre": "Git", "ruta": str(secreto), "compartido": True},
        {"nombre": "Unidad", "ruta": str(raiz_unidad), "compartido": True},
        {"nombre": "Relativa", "ruta": "carpeta/relativa", "compartido": True},
        {"nombre": "..", "ruta": str(ok), "compartido": True},
        {"nombre": ".oculto", "ruta": str(ok), "compartido": True},
        {"nombre": "con/barra", "ruta": str(ok), "compartido": True},
        "no soy un dict", {"ruta": str(ok)}])
    assert list(g.extras) == ["bueno"]


def test_proyecto_extra_no_compartido_sigue_el_flujo_normal(tmp_path):
    p = tmp_path / "fuera" / "Otro"
    p.mkdir(parents=True)
    g = Guardian(tmp_path / "r", tmp_path / "b", tmp_path / "c",
                 extras=[{"nombre": "Otro", "ruta": str(p), "compartido": False}], sesiones_locales=tmp_path / "s")
    assert not g.es_compartido("Otro")
    assert g.ruta_sesion("Otro", "2026-11-03", "t").parent == p / CARPETA_SESIONES


def test_listar_proyectos_marca_compartidos_y_no_duplica(compartido):
    g, raiz, ajena, _, _ = compartido
    lista = CX.listar_proyectos(g, "", (), {"planificador x": {"sesiones": []}})
    por_nombre = {p["nombre"]: p for p in lista}
    assert por_nombre["Planificador X"]["compartido"] is True and por_nombre["Planificador X"]["plan"] is not None
    assert por_nombre["Planificador X"]["tiene_sesiones"] is False
    assert por_nombre["ProyA"]["compartido"] is False and por_nombre["ProyA"]["plan"] is None
    # si la misma carpeta también está dentro de la raíz, sale una sola vez (como extra)
    (raiz / "Duplicada").mkdir()
    g.fijar_extras([{"nombre": "Duplicada", "ruta": str(raiz / "Duplicada"), "compartido": True}])
    assert [p["nombre"] for p in CX.listar_proyectos(g)].count("Duplicada") == 1
    assert CX.listar_proyectos(g, "calc") == [] or all("calc" in p["nombre"].lower() for p in CX.listar_proyectos(g, "calc"))


# ---------------------------------------------------------------- configuración
def test_config_no_trae_proyectos_extra_por_defecto(tmp_path):
    cfg = Config(tmp_path / "c.json")
    assert cfg["proyectos_extra"] == []


def test_config_valida_proyectos_extra(tmp_path):
    cfg = Config(tmp_path / "c.json")
    cfg.actualizar({"proyectos_extra": [
        {"nombre": " A ", "ruta": " D:\\x ", "compartido": True}, {"nombre": "a", "ruta": "D:\\y"},
        {"nombre": "B", "ruta": "D:\\z", "compartido": "si"}, {"nombre": "", "ruta": "D:\\q"}, 5, {"nombre": "C"}]}, guardar=False)
    assert cfg["proyectos_extra"] == [{"nombre": "A", "ruta": "D:\\x", "compartido": True},
                                      {"nombre": "B", "ruta": "D:\\z", "compartido": False}]
    cfg.actualizar({"proyectos_extra": "no es una lista"}, guardar=False)
    assert len(cfg["proyectos_extra"]) == 2
    assert DEFAULTS["proyectos_extra"] == []  # los valores por defecto no se mutan


