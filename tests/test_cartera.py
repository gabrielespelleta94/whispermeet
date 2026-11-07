"""Vista de cartera (ola 4): salud por proyecto (sesiones recientes, pendientes abiertos y antiguos, objetivos cerrados, riesgos repetidos), ordenada por atención.

.md sintéticos en carpetas temporales; el modelo no se llama nunca."""
from datetime import date, datetime

from apuntes import cartera as CA
from apuntes.rutas import CARPETA_SESIONES
from ola4_utils import cliente, montar

AHORA = datetime(2026, 11, 5, 15, 0)
HOY = date(2026, 11, 5)


def md(proyecto, fecha, tema, resumen="", insights=()):
    L = ["---", f'tema: "{tema}"', f'proyecto: "{proyecto}"', f"fecha: {fecha}", "inicio: 10:00", "duracion: 20:00", "estado: finalizada", "---", "", f"# {tema}", ""]
    if resumen:
        L += ["## Resumen", "", resumen, ""]
    if insights:
        L += ["## Insights", "", *insights, ""]
    L += ["## Transcripción", "", "[00:05] **Reunión:** Hola a todos.", ""]
    return "\n".join(L) + "\n"


def escribir(g, proyecto, fecha, tema, **kw):
    carpeta = g.raiz / proyecto / CARPETA_SESIONES if proyecto != "Bandeja" else g.bandeja
    carpeta.mkdir(parents=True, exist_ok=True)
    (carpeta / f"{fecha}-{tema.lower().replace(' ', '-')}.md").write_text(md(proyecto, fecha, tema, **kw), encoding="utf-8")


def montar_cartera(tmp_path):
    gestor, llm, _, g, cfg = montar(tmp_path, con_proyecto=False)
    # Alfa: riesgo repetido, un pendiente viejo abierto y objetivos mal cerrados
    escribir(g, "Alfa", "2026-11-03", "Seguimiento tres", resumen="## Objetivos de la sesión\n\nCubiertos 1 de 4; parciales 1; sin tratar 2.",
             insights=["- [01:00] **Riesgo:** El proveedor de pagos puede retrasar el piloto.", "- [02:00] **Pendiente:** Enviar la tarifa nueva."])
    escribir(g, "Alfa", "2026-10-20", "Seguimiento dos", resumen="## Objetivos de la sesión\n\nCubiertos 1 de 2; parciales 0; sin tratar 1.",
             insights=["- [01:30] **Riesgo:** el proveedor de pagos  puede retrasar el piloto"])
    escribir(g, "Alfa", "2026-09-28", "Seguimiento uno", insights=["- [03:00] **Pendiente:** Cerrar el catálogo de habitaciones antiguo."])
    # Beta: sana
    escribir(g, "Beta", "2026-11-04", "Comité", resumen="## Objetivos de la sesión\n\nCubiertos 3 de 3; parciales 0; sin tratar 0.",
             insights=["- [01:00] **Decisión:** Se aprueba el calendario."])
    # Gamma: parada hace meses
    escribir(g, "Gamma", "2026-08-01", "Arranque", insights=["- [01:00] **Idea:** Probar otra cosa."])
    # la Bandeja no es un proyecto
    escribir(g, "Bandeja", "2026-11-04", "Suelta", insights=["- [01:00] **Riesgo:** algo."])
    return gestor, llm, g, cfg


# ------------------------------------------------------------------ puro
def test_objetivos_de_resumen_se_lee_del_documento():
    assert CA.objetivos_de_resumen("## Objetivos de la sesión\n\nCubiertos 3 de 5; parciales 1.") == (3, 5)
    assert CA.objetivos_de_resumen("## Objetivos de la sesión\n\n- [Cubierto] a (minuto 03:00)\n- [Parcial] b\n- [Sin tratar] c\n- [Cubierto] d") == (2, 4)
    assert CA.objetivos_de_resumen("Sin objetivos aquí.") is None and CA.objetivos_de_resumen("") is None


def test_niveles():
    assert [CA.nivel_de(p) for p in (0, 2, 3, 6, 7, 20)] == ["bien", "bien", "atencion", "atencion", "critico", "critico"]


def test_salud_de_un_proyecto_sin_nada_que_decir():
    s = CA.salud_de_proyecto("X", [{"id": "1", "fecha": "2026-11-04", "tema": "t", "resumen": "Cubiertos 2 de 2", "items": []}], HOY)
    assert s["nivel"] == "bien" and s["atencion"] == 0 and s["motivos"] == [] and s["objetivos"]["ratio_cerrados"] == 1.0
    assert s["sesiones"]["dias_desde_ultima"] == 1 and s["sesiones"]["recientes"] == 1


def test_riesgos_repetidos_solo_cuentan_en_sesiones_distintas():
    def sesion(i, fecha, riesgos):
        return {"id": str(i), "fecha": fecha, "tema": "t", "resumen": "", "items": [{"tipo": "riesgo", "texto": r} for r in riesgos]}
    una = CA.salud_de_proyecto("X", [sesion(1, "2026-11-01", ["El plazo es ajustado.", "El plazo es ajustado."])], HOY)       # dos veces en la MISMA sesión: no es repetido
    assert una["riesgos_repetidos"] == []
    dos = CA.salud_de_proyecto("X", [sesion(1, "2026-11-01", ["El plazo es ajustado."]), sesion(2, "2026-10-01", ["el plazo es   ajustado"]), sesion(3, "2026-09-01", ["Otro riesgo distinto."])], HOY)
    assert len(dos["riesgos_repetidos"]) == 1 and dos["riesgos_repetidos"][0]["sesiones"] == 2 and dos["atencion"] == 3 and dos["nivel"] == "atencion"


def test_pendientes_antiguos_y_abiertos():
    items = [{"tipo": "pendiente", "estado": "abierto", "texto": f"p{i}", "duplicado": False} for i in range(6)]
    items += [{"tipo": "pendiente", "estado": "hecho", "texto": "hecho"}, {"tipo": "pendiente", "estado": "abierto", "texto": "repe", "duplicado": True}]
    s = CA.salud_de_proyecto("X", [{"id": "1", "fecha": "2026-10-10", "tema": "t", "resumen": "", "items": items}], HOY)         # 26 días
    assert s["pendientes"]["abiertos"] == 6 and s["pendientes"]["antiguos"] == 6 and s["pendientes"]["mas_antiguos"][0]["dias"] == 26
    assert s["atencion"] == 2 * 5 + 1                                                       # antiguos con tope 5 + un punto por cada 5 abiertos


# ------------------------------------------------------------------ con el backlog real
def test_la_cartera_ordena_por_atencion(tmp_path):
    gestor, llm, g, cfg = montar_cartera(tmp_path)
    cli = cliente(gestor, cfg, g, ahora=lambda: AHORA)
    with cli:
        d = cli.get("/api/cartera").json()
    assert [p["proyecto"] for p in d["proyectos"]] == ["Alfa", "Gamma", "Beta"]                 # Bandeja fuera
    assert d["resumen"] == {"proyectos": 3, "critico": 1, "atencion": 1, "bien": 1} and d["hoy"] == "2026-11-05"
    a, gamma, beta = d["proyectos"]
    assert a["nivel"] == "critico" and a["atencion"] == 8
    assert a["sesiones"] == {"total": 3, "recientes": 2, "ventana_dias": 30, "ultima_fecha": "2026-11-03", "dias_desde_ultima": 2, "ultima_tema": "Seguimiento tres"}
    assert a["pendientes"]["abiertos"] == 2 and a["pendientes"]["antiguos"] == 1 and a["pendientes"]["mas_antiguos"][0]["dias"] == 38
    assert a["objetivos"] == {"cerrados": 2, "total": 6, "ratio_cerrados": 0.33, "sesiones_con_objetivos": 2}
    assert len(a["riesgos_repetidos"]) == 1 and a["riesgos_repetidos"][0]["sesiones"] == 2 and "proveedor" in a["riesgos_repetidos"][0]["texto"]
    assert len(a["motivos"]) == 3
    assert gamma["nivel"] == "atencion" and gamma["sesiones"]["dias_desde_ultima"] == 96 and "sin sesiones" in gamma["motivos"][0]
    assert beta["nivel"] == "bien" and beta["atencion"] == 0 and beta["objetivos"]["ratio_cerrados"] == 1.0
    assert llm.llamadas == []                                                                  # la cartera es local


def test_cerrar_un_pendiente_lo_saca_de_la_cartera(tmp_path):
    gestor, llm, g, cfg = montar_cartera(tmp_path)
    cli = cliente(gestor, cfg, g, ahora=lambda: AHORA)
    with cli:
        antes = next(p for p in cli.get("/api/cartera").json()["proyectos"] if p["proyecto"] == "Alfa")
        assert antes["pendientes"]["abiertos"] == 2
        items = cli.get("/api/backlog/items").json()["items"]
        viejo = next(i for i in items if i["tipo"] == "pendiente" and "catálogo" in i["texto"])
        assert cli.put(f"/api/backlog/items/{viejo['id']}", json={"estado": "hecho"}).status_code == 200
        despues = next(p for p in cli.get("/api/cartera", params={"refrescar": True}).json()["proyectos"] if p["proyecto"] == "Alfa")
        assert despues["pendientes"]["abiertos"] == 1 and despues["pendientes"]["antiguos"] == 0 and despues["atencion"] == 6


def test_la_ventana_y_el_umbral_son_configurables(tmp_path):
    gestor, llm, g, cfg = montar_cartera(tmp_path)
    cfg.actualizar({"cartera_ventana_dias": 7, "cartera_pendiente_antiguo_dias": 60}, guardar=False)
    cli = cliente(gestor, cfg, g, ahora=lambda: AHORA)
    with cli:
        a = next(p for p in cli.get("/api/cartera").json()["proyectos"] if p["proyecto"] == "Alfa")
    assert a["sesiones"]["recientes"] == 1 and a["pendientes"]["antiguos"] == 0 and a["objetivos"] == {"cerrados": 1, "total": 4, "ratio_cerrados": 0.25, "sesiones_con_objetivos": 1}


def test_cartera_vacia(tmp_path):
    gestor, llm, _, g, cfg = montar(tmp_path, con_proyecto=False)
    cli = cliente(gestor, cfg, g, ahora=lambda: AHORA)
    with cli:
        d = cli.get("/api/cartera").json()
    assert d["proyectos"] == [] and d["resumen"]["proyectos"] == 0


def test_la_cartera_incluye_lo_medido_en_las_reuniones(tmp_path):
    gestor, llm, g, cfg = montar_cartera(tmp_path)
    gestor.metricas.guardar({"sesion": "s1", "proyecto": "Beta", "fecha": "2026-11-04", "duracion_s": 600, "objetivos": [{"minutos_hasta_cierre": 5.0}],
                             "objetivos_resumen": {"total": 2, "cerrados": 1, "ratio_cerrados": 0.5, "minutos_medio_hasta_cierre": 5.0},
                             "avisos": {"aceptados": 3, "descartados": 1}, "tokens": {"total": 10}})
    cli = cliente(gestor, cfg, g, ahora=lambda: AHORA)
    with cli:
        d = cli.get("/api/cartera").json()
    beta = next(p for p in d["proyectos"] if p["proyecto"] == "Beta")
    assert beta["valor"] == {"sesiones_medidas": 1, "ratio_cerrados": 0.5, "minutos_medio_hasta_cierre": 5.0, "tasa_aceptacion": 0.75}
    assert "valor" not in next(p for p in d["proyectos"] if p["proyecto"] == "Alfa")
