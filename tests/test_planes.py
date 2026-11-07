"""Plan de sesiones: contenido del plan real, estado de objetivos y forma de los prompts."""
import json
from pathlib import Path

import pytest

from apuntes import planes as PL
from apuntes.analisis import prompts as P
from apuntes.config import PLANES_DIR
from apuntes.contexto import fuentes_digest
from apuntes.rutas import Guardian

PLAN_REAL = PLANES_DIR / "planificador-grupos.json"


def plan_real():
    return PL.normalizar_plan(json.loads(PLAN_REAL.read_text(encoding="utf-8")))


@pytest.mark.skipif(not PLAN_REAL.is_file(), reason="el plan local de Planificador de Grupos no está (planes/ está fuera de git)")
def test_plan_planificador_de_grupos_tiene_el_contenido_pedido():
    plan = plan_real()
    assert plan["proyecto"] == "Planificador de Grupos"
    por_id = {s["id"]: s for s in plan["sesiones"]}
    assert list(por_id) == ["TR3", "TR4", "TR5", "otra"]
    tr3, tr4, tr5, otra = (por_id[i] for i in ("TR3", "TR4", "TR5", "otra"))
    assert tr3["nombre"] == "Revisión DataLake" and tr3["fecha"] == "por definir"
    assert tr3["participantes"] == "Data de Nordia, consultor Fabric"
    assert len(tr3["objetivos"]) == 4 and tr3["fichero_prioritario"] == "12-guion-sesion-data.md"
    assert tr3["objetivos"][1].startswith("Réplica del Data Lake en OneLake") and "fuera de servicio" in tr3["objetivos"][1]
    assert tr4["nombre"] == "Contrato de la petición con Salesforce" and tr4["fecha"] == "por definir"
    assert tr4["participantes"] == "Equipo Salesforce (Kaizen), Data, consultor Fabric"
    assert len(tr4["objetivos"]) == 5 and "Autenticación con Entra ID" in tr4["objetivos"]
    assert tr4["fichero_prioritario"] == "13-guion-sesion-salesforce.md"
    assert tr5["nombre"] == "Validación del diseño funcional" and "martes 10 de noviembre" in tr5["fecha"]
    assert tr5["participantes"] == "Keyusers de Revenue, jefaturas de proyecto, Data"
    assert tr5["objetivos"] == ["Presentación del diseño funcional", "Aprobación en acta"]
    assert tr5["depende_de"] == ["TR3", "TR4"]
    assert otra["nombre"] == "Otra reunión (sin objetivos)" and otra["objetivos"] == []


def test_planes_y_sesiones_fuera_de_git():
    ignorado = (Path(__file__).resolve().parent.parent / ".gitignore").read_text(encoding="utf-8").split()
    assert "planes/" in ignorado and "sesiones/" in ignorado


def test_normalizar_plan_descarta_lo_invalido():
    assert PL.normalizar_plan({"proyecto": "P", "sesiones": []}) is None
    assert PL.normalizar_plan({"sesiones": [{"id": "A", "nombre": "x"}]}) is None
    assert PL.normalizar_plan("no") is None
    plan = PL.normalizar_plan({"proyecto": "P", "sesiones": [
        {"id": "../x", "nombre": "mala"}, {"id": "A", "nombre": "buena", "fichero_prioritario": "../../02.md",
                                           "objetivos": ["uno", "", "dos"]},
        {"id": "a", "nombre": "repetida"}, 7]})
    assert [s["id"] for s in plan["sesiones"]] == ["A"]
    assert plan["sesiones"][0]["objetivos"] == ["uno", "dos"] and plan["sesiones"][0]["fichero_prioritario"] == ""


def test_cargar_planes_ignora_json_roto(tmp_path):
    (tmp_path / "planes").mkdir()
    (tmp_path / "planes" / "roto.json").write_text("{no es json", encoding="utf-8")
    (tmp_path / "planes" / "ok.json").write_text(json.dumps(
        {"proyecto": "Proy", "sesiones": [{"id": "A", "nombre": "a", "objetivos": ["x"]}]}), encoding="utf-8")
    g = Guardian(tmp_path / "r", tmp_path / "b", tmp_path / "c", planes=tmp_path / "planes")
    assert list(PL.cargar_planes(g)) == ["proy"]
    assert PL.plan_de(g, "PROY")["sesiones"][0]["id"] == "A"
    assert PL.plan_de(g, None) is None and PL.plan_de(g, "otro") is None
    with pytest.raises(ValueError):
        PL.sesion_de(PL.plan_de(g, "Proy"), "Z")
    assert PL.sesion_de(PL.plan_de(g, "Proy"), None) is None


# ---------------------------------------------------------------- estado de objetivos
def objs():
    return PL.objetivos_iniciales({"objetivos": ["uno", "dos", "tres"]})


def test_un_objetivo_cubierto_no_retrocede_sin_evidencia_clara():
    o = objs()
    PL.aplicar_actualizaciones(o, PL.normalizar_actualizaciones([{"i": 1, "e": "c", "m": "01:30"}, {"i": 2, "e": "p", "m": "02:00"}], 3))
    assert [(x["estado"], x["minuto"]) for x in o] == [("cubierto", "01:30"), ("parcial", "02:00"), ("sin_tratar", "")]
    # intento de retroceso sin «d»: se ignora
    tocados = PL.aplicar_actualizaciones(o, PL.normalizar_actualizaciones(
        [{"i": 1, "e": "p", "m": "09:00"}, {"i": 1, "e": "n"}, {"i": 2, "e": "n", "m": "09:10"}], 3))
    assert tocados == [] and o[0]["estado"] == "cubierto" and o[0]["minuto"] == "01:30" and o[1]["estado"] == "parcial"
    # con evidencia clara (d) sí retrocede y cita el nuevo minuto
    PL.aplicar_actualizaciones(o, PL.normalizar_actualizaciones([{"i": 1, "e": "p", "m": "10:05", "d": 1}], 3))
    assert o[0]["estado"] == "parcial" and o[0]["minuto"] == "10:05"
    # avanza de parcial a cubierto
    PL.aplicar_actualizaciones(o, PL.normalizar_actualizaciones([{"i": 2, "e": "c", "m": "11:00"}], 3))
    assert o[1]["estado"] == "cubierto" and o[1]["t_seg"] == 660


def test_repetir_el_mismo_estado_conserva_el_primer_minuto():
    o = objs()
    PL.aplicar_actualizaciones(o, PL.normalizar_actualizaciones([{"i": 3, "e": "c", "m": "03:00"}], 3))
    PL.aplicar_actualizaciones(o, PL.normalizar_actualizaciones([{"i": 3, "e": "c", "m": "08:00"}], 3))
    assert o[2]["minuto"] == "03:00"


@pytest.mark.parametrize("basura", [None, "x", {}, [1, "a"], [{"i": 0, "e": "c"}], [{"i": 4, "e": "c"}], [{"i": True, "e": "c"}],
                                    [{"i": 1, "e": "z"}], [{"i": "1", "e": "c"}], [{"i": 1}]])
def test_actualizaciones_invalidas_se_ignoran(basura):
    assert PL.normalizar_actualizaciones(basura, 3) == []


def test_minuto_invalido_se_deja_vacio():
    assert PL.normalizar_actualizaciones([{"i": 1, "e": "c", "m": "mañana"}], 3)[0]["minuto"] == ""


def test_resumen_de_objetivos_lista_cumplidos_y_pendientes():
    o = objs()
    PL.aplicar_actualizaciones(o, PL.normalizar_actualizaciones([{"i": 1, "e": "c", "m": "01:30"}, {"i": 2, "e": "p", "m": "02:00"}], 3))
    md = PL.resumen_markdown(o, "Revisión DataLake")
    assert "Objetivos de la sesión Revisión DataLake" in md and "Cubiertos 1 de 3" in md
    assert md.index("Cumplidos") < md.index("Parciales") < md.index("Sin tratar")
    assert "- uno (minuto 01:30)" in md and "- tres" in md
    assert PL.resumen_markdown([], "x") == ""


# ---------------------------------------------------------------- prompts: sin plan nada cambia
def test_sin_plan_los_prompts_no_llevan_objetivos():
    assert "OBJETIVOS" not in P.sistema_periodico(2500) and "OBJETIVOS" not in P.sistema_final(True)
    assert "objetivos_sesion" not in P.usuario_periodico("d", "r", [], "", "n")
    assert "objetivos_sesion" not in P.usuario_final("d", "r", [], "", "t", {})
    assert "reunión que se va a analizar" not in P.sistema_digest(6000)


def test_con_plan_los_objetivos_van_en_la_llamada_periodica_y_compactos():
    sin = P.sistema_periodico(2500) + P.usuario_periodico("d", "r", [], "", "n")
    o = PL.objetivos_iniciales({"objetivos": ["Tenant y workspace de Fabric", "Frecuencia y calidad de la carga"]})
    con = P.sistema_periodico(2500, True) + P.usuario_periodico("d", "r", [], "", "n", PL.bloque_prompt(o))
    assert "<<<DATOS objetivos_sesion>>>\n1 [ ] Tenant y workspace de Fabric\n2 [ ] Frecuencia y calidad de la carga" in con
    assert 0 < len(con) - len(sin) < 1500


def test_normalizar_periodico_y_final_traen_objetivos():
    d = P.normalizar_periodico({"resumen": "", "t": [], "c": [], "o": [{"i": 2, "e": "c", "m": "03:10"}, {"i": 9, "e": "c"}]}, 500, 3)
    assert d["objetivos"] == [{"n": 2, "estado": "cubierto", "minuto": "03:10", "d": False}]
    assert P.normalizar_periodico({"resumen": "", "t": [], "c": []}, 500, 3)["objetivos"] == []
    assert P.normalizar_final({"resumen": "r", "o": [{"i": 1, "e": "p", "m": "01:00"}]}, 2)["objetivos"][0]["estado"] == "parcial"
    assert P.normalizar_final({"resumen": "r", "o": [{"i": 1, "e": "p"}]}, 0)["objetivos"] == []


# ---------------------------------------------------------------- digest: fichero prioritario y sesión en la clave
def montar(tmp_path):
    raiz = tmp_path / "r"
    ctx = raiz / "Proy" / "00. CONTEXTO (IA)"
    ctx.mkdir(parents=True)
    texto = "\n".join(f"- hecho {i} del proyecto con palabras suficientes para no ser plantilla vacía" for i in range(30))
    for nombre in ("01-ficha.md", "02-alcance.md", "12-guion-sesion-data.md", "13-guion-sesion-salesforce.md"):
        (ctx / nombre).write_text(f"# {nombre}\n\n{texto}\n", encoding="utf-8")
    return Guardian(raiz, tmp_path / "b", tmp_path / "c")


def test_digest_pone_primero_el_fichero_prioritario(tmp_path):
    g = montar(tmp_path)
    normal = fuentes_digest(g, "Proy", "t", None)
    assert [e for e, _ in normal.textos] == ["02-alcance.md", "01-ficha.md", "12-guion-sesion-data.md", "13-guion-sesion-salesforce.md"]
    prio = fuentes_digest(g, "Proy", "t", None, 20_000, "13-guion-sesion-salesforce.md", "TR4|foco")
    assert prio.textos[0][0] == "13-guion-sesion-salesforce.md"
    assert {e for e, _ in prio.textos} == {e for e, _ in normal.textos}


def test_clave_de_cache_incluye_la_sesion(tmp_path):
    g = montar(tmp_path)
    base = fuentes_digest(g, "Proy", "t", None).clave
    tr3 = fuentes_digest(g, "Proy", "t", None, 20_000, "12-guion-sesion-data.md", "TR3|a").clave
    tr4 = fuentes_digest(g, "Proy", "t", None, 20_000, "13-guion-sesion-salesforce.md", "TR4|a").clave
    assert len({base, tr3, tr4}) == 3
    assert fuentes_digest(g, "Proy", "t", None, 20_000, "12-guion-sesion-data.md", "TR3|a").clave == tr3  # estable
    assert fuentes_digest(g, "Proy", "t", None, 20_000, "", "").clave == base


def test_prioritario_que_no_existe_no_rompe(tmp_path):
    g = montar(tmp_path)
    f = fuentes_digest(g, "Proy", "t", None, 20_000, "99-no-existe.md", "X|y")
    assert f.textos and "99-no-existe.md" not in [e for e, _ in f.textos]
