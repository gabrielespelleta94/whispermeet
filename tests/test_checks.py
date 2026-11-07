"""Checks de preparación: bloqueo manual, solo abiertos en el prompt, tope de 15, persistencia, escritura confinada,
marcado automático con minuto y cita, sugeridos del digest, resumen final y publicación de proyectos compartidos."""
import asyncio
import json
import shutil
from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from apuntes import checks as CK
from apuntes import planes as PL
from apuntes.analisis import Respuesta
from apuntes.analisis import prompts as P
from apuntes.config import Config
from apuntes.consumo import Consumo
from apuntes.gestor import Gestor
from apuntes.rutas import CARPETA_CONTEXTO, CARPETA_SESIONES, Guardian, RutaProhibida
from apuntes.servidor import Difusor, crear_app
from test_gestor_plan import COMPARTIDO, PRUEBAS, Falso, ejecutar, esperar, lineas

APP = Path(__file__).resolve().parent.parent
PLAN_REAL = APP / "planes" / "planificador-grupos.json"
PLAN_BETA = PRUEBAS / "planes-beta" / "beta.json"


def listado(arbol: Path) -> list[str]:
    return sorted(p.relative_to(arbol).as_posix() for p in arbol.rglob("*"))


# ---------------------------------------------------------------- almacén (sin gestor)
@pytest.fixture
def almacen(tmp_path):
    raiz = tmp_path / "proyectos"
    shutil.copytree(PRUEBAS / "proyectos", raiz)
    g = Guardian(raiz, tmp_path / "bandeja", tmp_path / "cache", checks=tmp_path / "checks")
    return CK.AlmacenChecks(g), g, tmp_path


PROY = "Proyecto Ficticio Alfa"


def ids(lista):
    return {c["texto"]: c["id"] for c in lista}


def test_marcar_o_desmarcar_a_mano_bloquea_y_el_modelo_no_lo_cambia(almacen):
    a, _, _ = almacen
    a.anadir(PROY, None, "Uno")
    a.anadir(PROY, None, "Dos")
    a.anadir(PROY, None, "Tres")
    i = ids(a.listar(PROY, None))
    a.marcar(PROY, None, i["Uno"], True)       # marcado a mano
    a.marcar(PROY, None, i["Dos"], True)
    a.marcar(PROY, None, i["Dos"], False)      # marcado y desmarcado: abierto pero BLOQUEADO
    enviados = a.para_prompt(PROY, None)
    assert [c["texto"] for c in enviados] == ["Tres"]  # ni el hecho ni el bloqueado se mandan
    # el modelo (con un envío anterior que los incluía) intenta marcar los tres: solo cambia el libre
    previo = [{"id": i[t]} for t in ("Uno", "Dos", "Tres")]
    marcas = [{"n": n, "minuto": "01:00", "cita": "texto"} for n in (1, 2, 3)]
    tocados = a.aplicar_marcas(PROY, None, previo, marcas)
    assert tocados == [i["Tres"]]
    por = {c["texto"]: c for c in a.listar(PROY, None)}
    assert por["Uno"]["estado"] == "hecho" and por["Uno"]["bloqueado"] and not por["Uno"]["auto"]
    assert por["Dos"]["estado"] == "abierto" and por["Dos"]["bloqueado"]
    assert por["Tres"]["estado"] == "hecho" and por["Tres"]["auto"] and por["Tres"]["minuto"] == "01:00"


def test_el_usuario_gana_si_toca_el_check_mientras_el_modelo_piensa(almacen):
    a, _, _ = almacen
    a.anadir(PROY, None, "Carrera")
    enviados = a.para_prompt(PROY, None)
    a.marcar(PROY, None, enviados[0]["id"], False)   # el usuario lo toca después de enviarlo
    assert a.aplicar_marcas(PROY, None, enviados, [{"n": 1, "minuto": "00:10", "cita": "x"}]) == []
    assert a.listar(PROY, None)[0]["estado"] == "abierto"


def test_automatico_lleva_minuto_y_cita_corta_y_se_deshace_con_un_clic(almacen):
    a, _, _ = almacen
    a.anadir(PROY, None, "Auto")
    env = a.para_prompt(PROY, None)
    cita = " ".join(f"p{i}" for i in range(40))
    a.aplicar_marcas(PROY, None, env, CK.normalizar_marcas([{"i": 1, "m": "[03:15]", "q": cita}], 1))
    c = a.listar(PROY, None)[0]
    assert c["auto"] and c["estado"] == "hecho" and c["minuto"] == "03:15" and c["t_seg"] == 195
    assert len(c["cita"].rstrip("…").split()) == CK.MAX_CITA_PALABRAS and c["cita"].endswith("…")
    a.deshacer_auto(PROY, None, c["id"])
    c = a.listar(PROY, None)[0]
    assert c["estado"] == "abierto" and not c["auto"] and c["bloqueado"] and c["minuto"] == "" and c["cita"] == ""
    assert a.para_prompt(PROY, None) == []        # tras deshacer, el modelo no vuelve a tocarlo
    with pytest.raises(ValueError):
        a.deshacer_auto(PROY, None, c["id"])      # solo se deshace lo automático


def test_normalizar_marcas_valida_indices_y_duplicados():
    m = CK.normalizar_marcas([{"i": 1, "m": "02:00", "q": "a b"}, {"i": 1, "m": "03:00", "q": "x"}, {"i": 9}, {"i": True},
                              {"i": 2, "m": "mal"}, "no", {"i": "2"}], 7)
    assert [(x["n"], x["minuto"]) for x in m] == [(1, "02:00"), (2, "")]
    assert len(CK.normalizar_marcas([{"i": n} for n in range(1, 40)], 15)) == 15       # nunca más marcas que checks enviados
    assert CK.normalizar_marcas(None, 3) == [] and CK.normalizar_marcas([{"i": 1}], 0) == []


def test_solo_los_abiertos_y_sin_bloquear_entran_en_el_prompt_en_formato_compacto(almacen):
    a, _, _ = almacen
    for t in ("Abierto A", "Hecho B", "Bloqueado C", "Abierto D"):
        a.anadir(PROY, None, t)
    i = ids(a.listar(PROY, None))
    a.marcar(PROY, None, i["Hecho B"], True)
    a.marcar(PROY, None, i["Bloqueado C"], False)
    env = a.para_prompt(PROY, None)
    assert CK.bloque_prompt(env) == "1 Abierto A\n2 Abierto D"
    usuario = P.usuario_periodico("dig", "res", [], "", "nuevo", "", CK.bloque_prompt(env))
    bloque = usuario.split("<<<DATOS checks_abiertos>>>")[1].split("<<<FIN>>>")[0]
    assert "Abierto A" in bloque and "Abierto D" in bloque and "Hecho B" not in bloque and "Bloqueado C" not in bloque


def test_tope_de_15_checks_por_llamada_y_los_sugeridos_van_los_ultimos(almacen):
    a, _, _ = almacen
    a.incorporar_sugeridos(PROY, None, ["Sugerido 1", "Sugerido 2"])
    for n in range(20):
        a.anadir(PROY, None, f"Check manual {n:02d}")
    env = a.para_prompt(PROY, None)
    assert len(env) == CK.MAX_PROMPT == 15
    assert all(c["origen"] == "manual" for c in env)          # los sugeridos no desplazan a los del usuario
    assert CK.bloque_prompt(env).count("\n") == 14
    # y aunque alguien pase más, el analista recorta a 15 antes de montar el prompt
    from apuntes.analisis.analista import Analista

    class Mudo:
        def completar(self, sistema, usuario, *a, **k):
            self.usuario = usuario
            return Respuesta(json.dumps({"resumen": "", "t": [], "c": []}), [])
    m = Mudo()
    cfg = Config(Path("no-existe.json"))
    Analista(m, cfg, Consumo(None), a.g, "s").periodico("d", "", [], "", "nuevo", None, [dict(c) for c in env] + [dict(env[0])] * 5)
    assert m.usuario.split("<<<DATOS checks_abiertos>>>")[1].split("<<<FIN>>>")[0].strip().count("\n") == 14


def test_sugeridos_hasta_8_sin_repetir_lo_existente(almacen):
    a, _, _ = almacen
    a.anadir(PROY, None, "Confirmar el acceso al entorno de pruebas")
    nuevos = [f"Sugerencia distinta número {n} xx{n}" for n in range(12)]
    a.incorporar_sugeridos(PROY, None, ["Confirmar el acceso al entorno de pruebas"] + nuevos)
    sug = [c for c in a.listar(PROY, None) if c["origen"] == "sugerido"]
    assert len(sug) <= CK.MAX_SUGERIDOS == 8 and all(c["texto"] != "Confirmar el acceso al entorno de pruebas" for c in sug)
    assert CK.normalizar_sugeridos(["Confirmar el punto a", "CONFIRMAR EL PUNTO A", " ", 3, *[f"Confirmar el punto {n}" for n in range(20)]])[:2] == ["Confirmar el punto a", "Confirmar el punto 0"]
    assert len(CK.normalizar_sugeridos([f"Confirmar el punto {n}" for n in range(20)])) == 8
    assert CK.normalizar_sugeridos(["estamos todos", "Confirmar fecha", "Estrategia inicial por hotel", "Si la tarifa será por tipología"]) == ["Si la tarifa será por tipología"]


def test_persistencia_sobrevive_a_reiniciar_y_los_del_plan_borrados_no_vuelven(almacen):
    a, g, tmp = almacen
    base = ["Check del plan 1", "Check del plan 2"]
    lista = a.listar(PROY, None, base)
    i = ids(lista)
    a.marcar(PROY, None, i["Check del plan 1"], True, base)
    a.borrar(PROY, None, i["Check del plan 2"], base)
    a.anadir(PROY, None, "Manual mío", base)
    # «reinicio»: otro almacén sobre el mismo disco
    b = CK.AlmacenChecks(Guardian(g.raiz, tmp / "bandeja", tmp / "cache", checks=tmp / "checks"))
    tras = b.listar(PROY, None, base)
    assert [(c["texto"], c["estado"], c["bloqueado"]) for c in tras] == [("Check del plan 1", "hecho", True), ("Manual mío", "abierto", False)]
    fichero = tmp / "checks" / "proyecto-ficticio-alfa.json"
    assert fichero.is_file() and json.loads(fichero.read_text(encoding="utf-8"))["sesiones"]["general"]["checks"]
    # por proyecto y por sesión: otra sesión del mismo proyecto no mezcla
    assert b.listar(PROY, "otra") == [] and b.anadir(PROY, "otra", "De otra")[0]["texto"] == "De otra"
    assert [c["texto"] for c in b.listar(PROY, None, base)] == ["Check del plan 1", "Manual mío"]
    # un fichero roto se ignora sin romper nada
    fichero.write_text("{no es json", encoding="utf-8")
    assert b.listar(PROY, None) == []


def test_escritura_confinada_solo_en_la_carpeta_de_checks(almacen, tmp_path):
    a, g, tmp = almacen
    proyecto_antes = listado(g.raiz)
    a.anadir(PROY, "otra", "x")
    a.anadir(None, None, "bandeja")
    assert sorted(p.name for p in (tmp / "checks").iterdir()) == ["bandeja.json", "proyecto-ficticio-alfa.json"]
    assert listado(g.raiz) == proyecto_antes                       # nada dentro del proyecto
    assert not (tmp / "bandeja").exists()
    for malo in ("..", "../x", "Alfa/../..", "NoExiste", ".git", "a:b"):
        with pytest.raises(RutaProhibida):
            g.ruta_checks(malo)
    assert g.ruta_checks(PROY).parent == (tmp / "checks")
    with pytest.raises(RutaProhibida):
        Guardian(g.raiz, tmp / "b", tmp / "c").ruta_checks(PROY)   # sin carpeta configurada no hay dónde escribir
    with pytest.raises(ValueError):
        a.listar(PROY, "../fuera")                                 # el id de sesión no sirve para salir
    # el límite de checks por lista
    for n in range(CK.MAX_CHECKS):
        try:
            a.anadir(PROY, "tope", f"c{n}")
        except ValueError:
            break
    with pytest.raises(ValueError):
        a.anadir(PROY, "tope", "uno más")


def test_resumen_markdown_hechos_y_pendientes():
    checks = [
        {"texto": "A", "estado": "hecho", "auto": True, "minuto": "01:30", "cita": "lo dijeron", "bloqueado": False},
        {"texto": "B", "estado": "hecho", "auto": False, "minuto": "", "cita": "", "bloqueado": True},
        {"texto": "C", "estado": "abierto", "auto": False, "minuto": "", "cita": "", "bloqueado": True},
        {"texto": "D", "estado": "abierto", "auto": False, "minuto": "", "cita": "", "bloqueado": False}]
    r = CK.resumen_markdown(checks, "TR3")
    assert "Hechos 2 de 4; pendientes 2." in r
    assert "- A (automático, minuto 01:30: «lo dijeron»)" in r and "- B (a mano)" in r
    assert "- C (desmarcado a mano)" in r and "- D\n" in r + "\n"
    assert CK.resumen_markdown([]) == ""


# ---------------------------------------------------------------- prompts: sin checks no cambian
def test_sin_checks_los_prompts_de_analisis_no_cambian():
    assert P.sistema_periodico(2500, False, False) == P.sistema_periodico(2500)
    assert "CHECKS" not in P.sistema_periodico(2500, True, False) and "CHECKS" in P.sistema_periodico(2500, False, True)
    assert P.usuario_periodico("d", "r", [], "", "n") == P.usuario_periodico("d", "r", [], "", "n", "", "")
    assert "checks_abiertos" not in P.usuario_periodico("d", "r", [], "", "n", "1 [ ] obj", "")
    assert "checks" not in P.sistema_digest(6000, "foco").lower()
    assert "checks" in P.sistema_digest(6000, "foco", True).lower()
    assert P.usuario_digest([("a.md", "t")]) == P.usuario_digest([("a.md", "t")], [])


def test_aumento_de_tokens_con_15_checks_es_pequeno():
    """Medida determinista de lo que añaden 15 checks abiertos a una llamada periódica (caracteres ≈ tokens × 3,5)."""
    sin = P.sistema_periodico(2500, True) + P.usuario_periodico("d" * 3000, "r" * 800, ["t"] * 10, "", "n" * 3000, "1 [ ] objetivo")
    checks = [{"texto": f"Comprobación breve número {n:02d} del contexto"} for n in range(1, 16)]
    con = P.sistema_periodico(2500, True, True) + P.usuario_periodico("d" * 3000, "r" * 800, ["t"] * 10, "", "n" * 3000, "1 [ ] objetivo",
                                                                      CK.bloque_prompt(checks))
    extra = len(con) - len(sin)
    assert 0 < extra < 2000, extra
    print(f"\n15 checks añaden {extra} caracteres (~{extra // 3.5:.0f} tokens) a la llamada periódica")


# ---------------------------------------------------------------- el plan no inventa fechas
def _fechas_del_gantt(plan_json: dict):
    for k in ("hitos", "sesiones"):
        for x in plan_json["gantt"][k]:
            yield k, x


FECHAS_DEL_KICK_OFF = {  # las únicas fechas con día que da el kick-off (v04): semanas, Kick Off, TR2 y TR5 propuesta
    *[f"2026-{m:02d}-{d:02d}" for m, d in ((10, 26), (11, 2), (11, 9), (11, 16), (11, 23), (11, 30), (12, 7), (12, 14), (12, 21), (12, 28))],
    "2026-10-29", "2026-11-03", "2026-11-10"}


@pytest.mark.skipif(not PLAN_REAL.is_file(), reason="el plan local de Planificador de Grupos no está (planes/ está fuera de git)")
def test_el_plan_de_planificador_no_contiene_fechas_inventadas():
    crudo = json.loads(PLAN_REAL.read_text(encoding="utf-8"))
    g = crudo["gantt"]
    assert [s["id"] for s in g["semanas"]] == [f"S{n}" for n in range(1, 11)]
    for _, x in _fechas_del_gantt(crudo):
        if x["fecha_estado"] in ("por_definir", "por_confirmar"):
            assert x["fecha_iso"] == "", x                      # «por definir» y «por confirmar» se quedan así
        else:
            assert x["fecha_iso"] in FECHAS_DEL_KICK_OFF, x
    por_id = {x["id"]: x for _, x in _fechas_del_gantt(crudo)}
    for sin_dia in ("TR3", "TR4", "pruebas", "golive", "cierre", "contrato"):
        assert por_id[sin_dia]["fecha_iso"] == "" and por_id[sin_dia]["fecha_estado"] in ("por_definir", "por_confirmar")
    assert por_id["TR1"]["fecha_iso"] == "2026-10-29" and por_id["TR1"]["hora"] == "16:00"
    assert por_id["TR2"]["fecha_iso"] == "2026-11-03" and por_id["TR2"]["hora"] == "16:00"
    assert por_id["TR5"]["fecha_estado"] == "propuesta" and por_id["TR5"]["fecha_iso"] == "2026-11-10"
    # los checks base de TR3, TR4 y TR5 existen y salen de sus objetivos
    sesiones = {s["id"]: s for s in crudo["sesiones"]}
    assert all(len(sesiones[t]["checks"]) >= 4 for t in ("TR3", "TR4", "TR5")) and sesiones["otra"].get("checks", []) == []
    assert "Tenant y workspace de Fabric confirmados" in sesiones["TR3"]["checks"]
    assert crudo["ficha"]["fuente"]["fichero"].startswith("Kick_Off_Planificador_Grupos_v04")


@pytest.mark.parametrize("ruta", [PLAN_BETA, PLAN_REAL])
def test_plan_normalizado_tr1_y_tr2_celebradas_y_sin_fechas_inventadas(ruta):
    if not ruta.is_file():
        pytest.skip("plan local ausente")
    plan = PL.normalizar_plan(json.loads(ruta.read_text(encoding="utf-8")))
    assert plan and plan["gantt"] and plan["ficha"]["que_es"]
    en = PL.enriquecer(plan, datetime(2026, 11, 3, 18, 0))            # 3-nov por la tarde: TR2 (16:00) ya pasó
    est = {s["id"]: s["estado"] for s in en["gantt"]["sesiones"]}
    if ruta == PLAN_REAL:
        assert est == {"TR1": "celebrada", "TR2": "celebrada", "TR3": "por_definir", "TR4": "por_definir", "TR5": "propuesta"}
        assert {s["id"]: s["estado_gantt"] for s in en["sesiones"]}["TR3"] == "por_definir"
        assert en["gantt"]["proximos_hitos"][0] == "contrato" and "kickoff" not in en["gantt"]["proximos_hitos"]
    antes = PL.enriquecer(plan, datetime(2026, 11, 3, 10, 0))          # por la mañana TR2 aún no ha pasado
    if ruta == PLAN_REAL:
        assert {s["id"]: s["estado"] for s in antes["gantt"]["sesiones"]}["TR2"] == "hoy"
    for s in en["gantt"]["sesiones"] + en["gantt"]["hitos"]:           # sin día exacto nunca hay día
        if s["fecha_estado"] in ("por_definir", "por_confirmar"):
            assert s["fecha_iso"] == ""


def test_normalizar_gantt_no_inventa_dias():
    g = PL.normalizar_gantt({"semanas": [{"id": "S1", "inicio": "2026-10-26"}],
                             "hitos": [{"id": "x", "nombre": "H", "semana": "S1", "fecha_iso": "2026-13-45", "fecha_estado": "confirmada"},
                                       {"id": "y", "nombre": "H2", "semana": "S9", "fecha_estado": "propuesta"}],
                             "sesiones": [{"id": "T", "nombre": "T", "fecha_estado": "confirmada"}]})
    assert [(h["fecha_iso"], h["fecha_estado"], h["semana"]) for h in g["hitos"]] == [("", "por_definir", "S1"), ("", "por_definir", "")]
    assert g["sesiones"][0]["fecha_estado"] == "por_definir"
    assert PL.normalizar_gantt({"semanas": []}) is None and PL.normalizar_gantt("x") is None


# ---------------------------------------------------------------- gestor completo con modelo falso
class FalsoChecks(Falso):
    """Como `Falso`, pero marca checks (campo `k`) por texto y devuelve sugeridos en el digest."""

    def __init__(self):
        super().__init__()
        self.marcar: list[str] = []
        self.gancho = None
        self.sin_sugeridos = False

    def completar(self, sistema, usuario, modelo, *a, **k):
        r = super().completar(sistema, usuario, modelo, *a, **k)
        if "compactar el contexto" in sistema and "checks" in sistema.lower() and not self.sin_sugeridos:
            d = json.loads(r.texto)
            d["checks"] = [f"Sugerido {n}: algo del contexto xx{n}" for n in range(12)]
            return Respuesta(json.dumps(d), r.uso)
        if "análisis incremental" in sistema and "CHECKS" in sistema:
            bloque = usuario.split("<<<DATOS checks_abiertos>>>")[1].split("<<<FIN>>>")[0].strip().splitlines()
            if self.gancho:
                self.gancho()
            d = json.loads(r.texto)
            d["k"] = [{"i": int(l.split(" ", 1)[0]), "m": "01:30", "q": "cita larga " + "palabra " * 25}
                      for l in bloque if any(t in l for t in self.marcar)]
            return Respuesta(json.dumps(d), r.uso)
        return r


@pytest.fixture
def montaje(tmp_path):
    raiz = tmp_path / "proyectos"
    shutil.copytree(PRUEBAS / "proyectos", raiz)
    ajena = tmp_path / "OneDrive ajeno" / COMPARTIDO
    shutil.copytree(PRUEBAS / "compartidos" / COMPARTIDO, ajena)
    shutil.copytree(PRUEBAS / "planes-beta", tmp_path / "planes")
    g = Guardian(raiz, tmp_path / "bandeja", tmp_path / "cache", planes=tmp_path / "planes", checks=tmp_path / "checks",
                 sesiones_locales=tmp_path / "sesiones", extras=[{"nombre": COMPARTIDO, "ruta": str(ajena), "compartido": True}])
    cfg = Config(tmp_path / "config.json")
    cfg.actualizar({"raiz_proyectos": str(raiz), "knowledge": ""}, guardar=False)
    llm = FalsoChecks()
    eventos = []
    return Gestor(cfg, g, Consumo(None), llm, eventos.append, simulacion=lineas(), velocidad=200), llm, eventos, ajena, tmp_path


async def cerrar(gestor):
    await gestor.terminar()
    await esperar(lambda: gestor.revision["estado"] in ("lista", "error"))


def por_texto(gestor, sesion="S1"):
    return {c["texto"]: c for c in gestor.checks_listar(COMPARTIDO, sesion)}


def test_flujo_completo_base_sugeridos_manual_automatico_bloqueo_y_resumen(montaje):
    gestor, llm, eventos, ajena, tmp = montaje

    async def go():
        # antes de empezar ya hay checks base del plan, y se pueden tocar sin reunión
        previos = por_texto(gestor)
        assert len(previos) == 6 and all(c["origen"] == "plan" for c in previos.values())
        gestor.checks_operar(COMPARTIDO, "S1", "anadir", texto="Check mío de antes de la reunión")
        await gestor.iniciar(COMPARTIDO, "", 5, "S1")
        await esperar(lambda: gestor.digest_origen in ("generado", "cache"))
        c = por_texto(gestor)
        sug = [x for x in c.values() if x["origen"] == "sugerido"]
        assert 0 < len(sug) <= 8 and "Check mío de antes de la reunión" in c   # sugeridos (marca «sugerido») sin pisar lo del usuario
        assert gestor.sesion.checks and any(e["tipo"] == "checks" for e in eventos)
        # el usuario hace lo suyo durante la reunión
        gestor.checks_operar(COMPARTIDO, "S1", "marcar", c["Precios por tipología confirmados"]["id"], hecho=True)
        gestor.checks_operar(COMPARTIDO, "S1", "marcar", c["Las cuatro tablas replicadas en el almacén"]["id"], hecho=True)
        gestor.checks_operar(COMPARTIDO, "S1", "marcar", c["Las cuatro tablas replicadas en el almacén"]["id"], hecho=False)
        llm.marcar = ["Inquilino", "Inventario", "Precios", "Las cuatro tablas", "Acceso al entorno"]
        await esperar(lambda: len(gestor.sesion.segmentos) >= 30)
        assert (await gestor.analizar(manual=True))["ok"]
        c = por_texto(gestor)
        # lo que se envió: solo abiertos y sin bloquear
        periodico = [u for s, u, _ in llm.llamadas if "análisis incremental" in s][-1]
        bloque = periodico.split("<<<DATOS checks_abiertos>>>")[1].split("<<<FIN>>>")[0]
        assert "Inquilino" in bloque and "Precios por tipología" not in bloque and "Las cuatro tablas" not in bloque
        assert len([l for l in bloque.strip().splitlines()]) <= 15
        # automáticos: minuto y cita corta; los bloqueados a mano, intactos
        for t in ("Inquilino y espacio de trabajo confirmados", "Inventario por tipología disponible", "Acceso al entorno de pruebas confirmado"):
            assert c[t]["estado"] == "hecho" and c[t]["auto"] and c[t]["minuto"] == "01:30" and 0 < len(c[t]["cita"].rstrip("…").split()) <= 15
        assert c["Precios por tipología confirmados"]["estado"] == "hecho" and not c["Precios por tipología confirmados"]["auto"]
        assert c["Las cuatro tablas replicadas en el almacén"]["estado"] == "abierto" and c["Las cuatro tablas replicadas en el almacén"]["bloqueado"]
        assert any(e["tipo"] == "tarjetas" and e["checks"] for e in eventos)
        # un clic deshace un automático
        gestor.checks_operar(COMPARTIDO, "S1", "deshacer", c["Acceso al entorno de pruebas confirmado"]["id"])
        assert por_texto(gestor)["Acceso al entorno de pruebas confirmado"]["estado"] == "abierto"
        await cerrar(gestor)
        r = gestor.revision["resumen"]
        assert "## Checks de la sesión" in r and "**Hechos**" in r and "**Pendientes**" in r
        assert "- Inquilino y espacio de trabajo confirmados (automático, minuto 01:30: «cita larga" in r
        assert "- Precios por tipología confirmados (a mano)" in r
        assert "- Las cuatro tablas replicadas en el almacén (desmarcado a mano)" in r
        # también en el .md de la sesión (copia local) y, al publicar, en el documento de la carpeta compartida
        assert "## Checks de la sesión" in gestor.sesion.ruta.read_text(encoding="utf-8")
        assert (await gestor.cerrar_revision())["ok"]

    ejecutar(go())
    publicado = next((ajena / CARPETA_SESIONES).glob("*.md")).read_text(encoding="utf-8")
    assert "## Checks de la sesión" in publicado and "Precios por tipología confirmados (a mano)" in publicado
    # y se guardaron en local, fuera de la carpeta compartida
    assert (tmp / "checks" / "proyecto-compartido-beta.json").is_file()
    assert not any("checks" in p.name.lower() for p in ajena.rglob("*"))


def test_digest_con_plan_pide_sugeridos_y_sin_plan_es_el_de_siempre(montaje):
    gestor, llm, *_ = montaje

    async def una(sesion_plan):
        gestor.sim = lineas()
        await gestor.iniciar(COMPARTIDO, "t", 5, sesion_plan)
        await esperar(lambda: gestor.digest_origen in ("generado", "cache"))
        origen = gestor.digest_origen
        await cerrar(gestor)
        await gestor.cerrar_revision(publicar=False)
        return origen

    assert ejecutar(una("S1")) == "generado"
    assert ejecutar(una("S1")) == "cache"          # la caché trae también los sugeridos
    assert len([c for c in gestor.checks_listar(COMPARTIDO, "S1") if c["origen"] == "sugerido"]) <= 8
    ejecutar(una("otra"))
    d_s1, d_otra = [(s, u) for s, u, _ in llm.llamadas if "compactar el contexto" in s]
    assert "checks_existentes" in d_s1[1] or "checks" in d_s1[0].lower()
    # sin plan («Otra reunión») el digest TAMBIÉN sugiere checks y objetivos (misma llamada, sin llamadas nuevas)
    assert "checks" in d_otra[0].lower() and '"objetivos"' in d_otra[0] and '"objetivos"' not in d_s1[0]


def test_bloqueo_si_el_usuario_toca_el_check_durante_la_llamada(montaje):
    gestor, llm, *_ = montaje

    async def go():
        await gestor.iniciar(COMPARTIDO, "", 5, "S1")
        await esperar(lambda: gestor.digest_origen in ("generado", "cache"))
        i = por_texto(gestor)["Inquilino y espacio de trabajo confirmados"]["id"]
        llm.marcar = ["Inquilino"]
        llm.gancho = lambda: gestor.checks.marcar(COMPARTIDO, "S1", i, False, [])   # el usuario lo desmarca mientras piensa el modelo
        await esperar(lambda: len(gestor.sesion.segmentos) >= 30)
        await gestor.analizar(manual=True)
        c = por_texto(gestor)["Inquilino y espacio de trabajo confirmados"]
        assert c["estado"] == "abierto" and c["bloqueado"] and not c["auto"]
        await cerrar(gestor)
        await gestor.cerrar_revision(publicar=False)

    ejecutar(go())


def test_sin_plan_ni_checks_el_periodico_no_cambia(montaje):
    gestor, llm, *_ = montaje
    llm.sin_sugeridos = True    # sin sugeridos del digest y sin checks propios: nada de checks en el periódico

    async def go():
        await gestor.iniciar(COMPARTIDO, "Libre", 5, "otra")
        await esperar(lambda: len(gestor.sesion.segmentos) >= 30)
        await gestor.analizar(manual=True)
        await cerrar(gestor)
        assert "Checks" not in gestor.revision["resumen"]
        await gestor.cerrar_revision(publicar=False)

    ejecutar(go())
    (s, u), = [(s, u) for s, u, _ in llm.llamadas if "análisis incremental" in s]
    assert "CHECKS" not in s and "checks_abiertos" not in u and "OBJETIVOS" not in s


def test_checks_manuales_sin_plan_en_la_bandeja_y_en_proyecto_sin_plan(montaje):
    gestor, *_ = montaje
    gestor.checks_operar(None, None, "anadir", texto="Algo en la bandeja")
    gestor.checks_operar("Proyecto Ficticio Alfa", None, "anadir", texto="Algo en Alfa")
    assert [c["texto"] for c in gestor.checks_listar(None, None)] == ["Algo en la bandeja"]
    with pytest.raises(ValueError, match="no tiene plan"):
        gestor.checks_listar("Proyecto Ficticio Alfa", "S1")
    with pytest.raises(ValueError, match="no existe"):
        gestor.checks_listar(COMPARTIDO, "TR9")
    with pytest.raises(RutaProhibida):
        gestor.checks_listar("Proyecto Inventado", None)


# ---------------------------------------------------------------- publicación en la carpeta compartida
def test_no_publicar_nunca_crea_02_sesiones_y_conserva_la_copia_local(montaje):
    gestor, llm, eventos, ajena, tmp = montaje
    antes = listado(ajena)

    async def go():
        await gestor.iniciar(COMPARTIDO, "Prueba descartable", 5, "S1")
        await esperar(lambda: len(gestor.sesion.segmentos) >= 30)
        await cerrar(gestor)
        p = gestor.revision["publicacion"]
        assert p["publicar"] is True and p["estado"] == "pendiente" and p["carpeta_existe"] is False
        assert p["destino"].endswith("-prueba-descartable.md") and CARPETA_SESIONES in p["destino"]
        await gestor.elegir_publicacion(False)
        ruta_local = gestor.sesion.ruta
        r = await gestor.cerrar_revision()
        assert r["ok"] and r["ruta"] == ""
        assert ruta_local.is_file()

    ejecutar(go())
    assert listado(ajena) == antes and not (ajena / CARPETA_SESIONES).exists()


def test_publicar_crea_la_carpeta_y_nunca_sobrescribe(montaje):
    gestor, llm, eventos, ajena, tmp = montaje
    previo = ajena / CARPETA_SESIONES
    previo.mkdir()

    async def una():
        gestor.sim = lineas()
        await gestor.iniciar(COMPARTIDO, "Misma reunión", 5, "S1")
        await esperar(lambda: len(gestor.sesion.segmentos) >= 30)
        await cerrar(gestor)
        return await gestor.cerrar_revision()

    from datetime import date
    existente = previo / f"{date.today().isoformat()}-misma-reunion.md"
    existente.write_text("contenido que no se puede pisar", encoding="utf-8")
    r1 = ejecutar(una())
    r2 = ejecutar(una())
    assert existente.read_text(encoding="utf-8") == "contenido que no se puede pisar"
    assert r1["ruta"].endswith("-misma-reunion-2.md") and r2["ruta"].endswith("-misma-reunion-3.md")
    assert {p.name for p in previo.glob("*.md")} == {existente.name, existente.stem + "-2.md", existente.stem + "-3.md"}


def test_si_falla_la_publicacion_se_muestra_conserva_la_copia_y_se_puede_reintentar(montaje):
    gestor, llm, eventos, ajena, tmp = montaje
    (ajena / CARPETA_SESIONES).write_text("soy un fichero, no una carpeta", encoding="utf-8")   # bloquea la creación

    async def go():
        await gestor.iniciar(COMPARTIDO, "Con fallo", 5, "S1")
        await esperar(lambda: len(gestor.sesion.segmentos) >= 30)
        await cerrar(gestor)
        local = gestor.sesion.ruta
        assert gestor.revision["publicacion"]["estado"] == "error"   # ya al calcular el destino: la carpeta no es válida
        r = await gestor.cerrar_revision()
        assert r["ok"] is False and r["error"] and gestor.revision["publicacion"]["estado"] == "error"
        assert gestor.estado == "revision" and local.is_file()       # no se cierra y no se pierde nada
        (ajena / CARPETA_SESIONES).unlink()                          # el usuario arregla el problema
        r = await gestor.publicar()
        assert r["ok"] and Path(r["ruta"]).is_file()
        assert (await gestor.cerrar_revision())["ok"] and gestor.estado == "inactivo"
        assert local.is_file()

    ejecutar(go())


def test_el_guardian_solo_admite_la_ruta_de_publicacion_de_un_proyecto_compartido(montaje):
    gestor, _, _, ajena, tmp = montaje
    g = gestor.g
    destino = g.ruta_publicacion(COMPARTIDO, "2026-11-03", "Tema")
    assert destino == ajena / CARPETA_SESIONES / "2026-11-03-tema.md" and not (ajena / CARPETA_SESIONES).exists()  # solo calcula
    with pytest.raises(RutaProhibida):
        g.ruta_publicacion("Proyecto Ficticio Alfa", "2026-11-03", "t")          # no compartido
    with pytest.raises(RutaProhibida):
        g.ruta_publicacion(None, "2026-11-03", "t")
    with pytest.raises(RutaProhibida):
        g.escribir_sesion(destino, COMPARTIDO, "no")                               # la escritura incremental sigue siendo solo local
    for malo in (ajena / "2026-11-03-x.md", ajena / CARPETA_CONTEXTO / "2026-11-03-x.md", ajena / CARPETA_SESIONES / "sub" / "2026-11-03-x.md",
                 ajena / CARPETA_SESIONES / "CLAUDE.md", ajena.parent / "2026-11-03-x.md"):
        with pytest.raises(RutaProhibida):
            g._validar_ruta_sesion(malo, COMPARTIDO, publicar=True)
    with pytest.raises(RutaProhibida):
        g._validar_ruta_sesion(destino, "Proyecto Ficticio Alfa", publicar=True)
    p = g.publicar_sesion(COMPARTIDO, "2026-11-03", "Tema", "uno")
    q = g.publicar_sesion(COMPARTIDO, "2026-11-03", "Tema", "dos")
    assert p.read_text(encoding="utf-8") == "uno" and q.name == "2026-11-03-tema-2.md" and q.read_text(encoding="utf-8") == "dos"


# ---------------------------------------------------------------- API
def cliente(tmp_path):
    raiz = tmp_path / "proyectos"
    shutil.copytree(PRUEBAS / "proyectos", raiz)
    ajena = tmp_path / "ajena" / COMPARTIDO
    shutil.copytree(PRUEBAS / "compartidos" / COMPARTIDO, ajena)
    shutil.copytree(PRUEBAS / "planes-beta", tmp_path / "planes")
    cfg = Config(tmp_path / "config.json")
    cfg.actualizar({"raiz_proyectos": str(raiz), "knowledge": "",
                    "proyectos_extra": [{"nombre": COMPARTIDO, "ruta": str(ajena), "compartido": True}]}, guardar=False)
    g = Guardian(raiz, tmp_path / "bandeja", tmp_path / "cache", planes=tmp_path / "planes", checks=tmp_path / "checks",
                 sesiones_locales=tmp_path / "sesiones", extras=cfg["proyectos_extra"])
    dif = Difusor()
    gestor = Gestor(cfg, g, Consumo(None), FalsoChecks(), dif.emitir, simulacion=lineas(), velocidad=200)
    app = crear_app(gestor, dif, cfg, g, "t0k", 8124)
    return TestClient(app, base_url="http://127.0.0.1:8124", headers={"X-Token": "t0k"}), ajena, tmp_path


def test_api_de_checks_y_panel_del_gantt_sin_llamar_al_modelo(tmp_path):
    cli, ajena, tmp = cliente(tmp_path)
    antes = listado(ajena)
    with cli:
        beta = {p["nombre"]: p for p in cli.get("/api/proyectos").json()["proyectos"]}[COMPARTIDO]
        g = beta["plan"]["gantt"]
        assert beta["plan"]["hoy"] and {s["id"] for s in g["sesiones"]} == {"S1", "S2"} and g["sesiones"][0]["estado"] == "por_definir"
        lista = cli.get("/api/checks", params={"proyecto": COMPARTIDO, "sesion": "S1"}).json()["checks"]
        assert len(lista) == 6 and lista[0]["origen"] == "plan"
        r = cli.post("/api/checks", json={"proyecto": COMPARTIDO, "sesion": "S1", "texto": "  Uno   nuevo "}).json()["checks"]
        nuevo = next(c for c in r if c["texto"] == "Uno nuevo")
        cuerpo = {"proyecto": COMPARTIDO, "sesion": "S1"}
        r = cli.put(f"/api/checks/{nuevo['id']}", json={**cuerpo, "hecho": True}).json()["checks"]
        assert next(c for c in r if c["id"] == nuevo["id"])["bloqueado"]
        r = cli.put(f"/api/checks/{nuevo['id']}", json={**cuerpo, "texto": "Editado"}).json()["checks"]
        assert any(c["texto"] == "Editado" for c in r)
        assert cli.post(f"/api/checks/{nuevo['id']}/deshacer", json=cuerpo).status_code == 400   # no era automático
        r = cli.delete(f"/api/checks/{nuevo['id']}", params=cuerpo).json()["checks"]
        assert all(c["id"] != nuevo["id"] for c in r)
        assert cli.post("/api/checks", json={**cuerpo, "texto": " "}).status_code == 400
        assert cli.get("/api/checks", params={"proyecto": COMPARTIDO, "sesion": "ZZ"}).status_code == 400
        assert cli.get("/api/checks", params={"proyecto": "../x"}).status_code in (400, 403)
        assert cli.get("/api/checks", headers={"X-Token": "mal"}).status_code == 401
        # con la reunión en marcha, el cierre admite «No publicar»
        assert cli.post("/api/sesion/iniciar", json={"proyecto": COMPARTIDO, "tema": "x", "cadencia": 5, "sesion_plan": "S1"}).status_code == 200
        est = cli.get("/api/sesion").json()
        assert len(est["checks"]) >= 6 and est["sesion"]["plan"]["id"] == "S1"
        assert cli.post("/api/revision/publicar").status_code == 400    # aún no hay revisión
    assert listado(ajena) == antes
    assert (tmp / "checks" / "proyecto-compartido-beta.json").is_file()


def test_se_puede_elegir_no_publicar_incluso_despues_de_aplicar_cambios(montaje):
    gestor, llm, eventos, ajena, tmp = montaje

    async def go():
        await gestor.iniciar(COMPARTIDO, "Prueba tras aplicar", 5, "S1")
        await esperar(lambda: len(gestor.sesion.segmentos) >= 30)
        await cerrar(gestor)
        validos = [c["id"] for c in gestor.revision["cambios"] if c["valido"]]
        assert validos
        assert (await gestor.aplicar_revision(validos))["ficheros"]
        await gestor.elegir_publicacion(False)
        r = await gestor.cerrar_revision()
        assert r["ok"] and r["ruta"] == ""

    ejecutar(go())
    assert not (ajena / CARPETA_SESIONES).exists()
    registro = (ajena / CARPETA_CONTEXTO / "10-registro-de-cambios.md").read_text(encoding="utf-8")
    assert "guardada en local por WhisperMeet" in registro


def test_confirmar_una_sugerencia_la_convierte_en_check_propio(almacen):
    """«Confirmar» en la interfaz = editar sin cambiar el texto: el sugerido pasa a manual (y sigue abierto)."""
    a, _, _ = almacen
    a.incorporar_sugeridos(PROY, None, ["Confirmar el alcance con el cliente"])
    c = next(c for c in a.listar(PROY, None) if c["origen"] == "sugerido")
    lista = a.editar(PROY, None, c["id"], c["texto"])
    c2 = next(x for x in lista if x["id"] == c["id"])
    assert c2["origen"] == "manual" and c2["estado"] == "abierto" and c2["texto"] == c["texto"]
