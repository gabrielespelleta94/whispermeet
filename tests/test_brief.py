"""Ola 3, punto 3: brief de preparación. Una llamada haiku por la capa existente, cacheada por hash de la entrada; sin modelo, versión local de reglas."""
import json
from datetime import datetime

from apuntes.brief import clave, entrada, local, objetivos_sin_cerrar, siguiente_sesion_del_plan, validar
from ola3_util import PROYECTO, ModeloFalso, montaje, sesion_md

RESUMEN_OBJ = """Se revisó el estado general.

## Objetivos de la sesión S1

Cubiertos 1 de 3; parciales 1; sin tratar 1.

**Cumplidos**
- Validar el alcance (minuto 02:00)

**Parciales (quedan pendientes)**
- Cerrar el modelo de datos (minuto 05:00)

**Sin tratar (quedan pendientes)**
- Fijar el calendario del piloto
"""
S1 = sesion_md("Diseño", "2026-10-27", resumen=RESUMEN_OBJ, insights=["- [04:20] **Pendiente:** Enviar el modelo de datos (Ana)",
                                                                   "- [05:10] **Pendiente:** Confirmar licencias con el proveedor"])
RESPUESTA = {"objetivos": ["Cerrar el modelo de datos", "Fijar el calendario del piloto"], "preguntas": ["¿Quién valida el modelo de datos?"], "datos": ["Listado de licencias vigentes"]}


def plan(tmp_path, sesiones):
    (tmp_path / "planes").mkdir(exist_ok=True)
    (tmp_path / "planes" / "p.json").write_text(json.dumps({"proyecto": PROYECTO, "sesiones": sesiones}), encoding="utf-8")


def test_objetivos_sin_cerrar_se_leen_del_resumen():
    assert objetivos_sin_cerrar(RESUMEN_OBJ) == ["Cerrar el modelo de datos", "Fijar el calendario del piloto"]
    assert objetivos_sin_cerrar("## Objetivos de la sesión\n\n- [Parcial] Uno (minuto 01:00)\n- [Cubierto] Dos\n- [Sin tratar] Tres\n") == ["Uno", "Tres"]
    assert objetivos_sin_cerrar("") == []


def test_siguiente_sesion_del_plan(tmp_path):
    pl = {"proyecto": "X", "sesiones": [
        {"id": "S1", "nombre": "Pasada", "fecha": "", "fecha_iso": "2020-01-10", "objetivos": ["a"], "checks": []},
        {"id": "S3", "nombre": "Lejana", "fecha": "", "fecha_iso": "2099-03-01", "objetivos": ["c"], "checks": []},
        {"id": "S2", "nombre": "Próxima", "fecha": "", "fecha_iso": "2099-02-01", "objetivos": ["b"], "checks": ["Traer el listado"]}]}
    from apuntes.planes import normalizar_plan
    # sin gantt, el estado sale de la fecha: la más cercana que aún no pasó
    s = siguiente_sesion_del_plan(normalizar_plan(pl), datetime(2026, 11, 7))
    assert s["id"] == "S2" and s["objetivos"] == ["b"] and s["checks"] == ["Traer el listado"] and s["fecha"] == "2099-02-01"
    sin_fecha = normalizar_plan({"proyecto": "X", "sesiones": [{"id": "S1", "nombre": "A", "objetivos": [], "checks": []}, {"id": "S2", "nombre": "B", "objetivos": [], "checks": []}]})
    assert siguiente_sesion_del_plan(sin_fecha)["id"] == "S1"
    todas_pasadas = normalizar_plan({"proyecto": "X", "sesiones": [{"id": "S1", "nombre": "A", "fecha_iso": "2020-01-01", "objetivos": [], "checks": []}]})
    assert siguiente_sesion_del_plan(todas_pasadas) is None and siguiente_sesion_del_plan(None) is None


def test_brief_con_modelo_se_cachea_por_hash_de_la_entrada(tmp_path):
    modelo = ModeloFalso([("Sherpa", RESPUESTA)])
    cli, gestor, cfg, g, bl, _m, _e = montaje(tmp_path, modelo=modelo, sesiones=[("2026-10-27-diseno.md", S1)])
    with cli:
        b = cli.get(f"/api/proyectos/{PROYECTO}/brief").json()
        assert b["origen"] == "modelo" and b["desde_cache"] is False and b["objetivos"] == RESPUESTA["objetivos"] and b["preguntas"] == RESPUESTA["preguntas"]
        assert b["datos"] == RESPUESTA["datos"] and b["ultima_sesion"]["tema"] == "Diseño" and b["aviso"] == ""
        assert {p["texto"] for p in b["pendientes"]} == {"Enviar el modelo de datos", "Confirmar licencias con el proveedor"}
        assert len(modelo.llamadas) == 1 and modelo.llamadas[0][2] == "haiku"
        # lo que viaja es dato no fiable y no lleva rutas
        assert "<<<DATOS" in modelo.llamadas[0][1] and str(tmp_path) not in modelo.llamadas[0][1]
        assert any(p.name.startswith("brief-") for p in (tmp_path / "cache").iterdir())
        # segunda vez: de la caché, sin llamada
        b2 = cli.get(f"/api/proyectos/{PROYECTO}/brief").json()
        assert b2["desde_cache"] is True and b2["objetivos"] == b["objetivos"] and len(modelo.llamadas) == 1
        # ?refrescar=1 vuelve a llamar
        b3 = cli.get(f"/api/proyectos/{PROYECTO}/brief?refrescar=1").json()
        assert b3["desde_cache"] is False and len(modelo.llamadas) == 2
        # cambia la entrada (un pendiente nuevo) -> otro hash -> otra llamada
        gestor.seguimiento.anadir_pendientes(PROYECTO, [{"texto": "Mandar el catálogo", "datos": {}}], {"sesion": "x.md", "fecha": "2026-11-06", "tema": "T"})
        cli.get(f"/api/proyectos/{PROYECTO}/brief")
        assert len(modelo.llamadas) == 3


def test_brief_sin_modelo_es_local_con_pendientes_y_objetivos_sin_cerrar(tmp_path):
    cli, gestor, cfg, g, bl, modelo, _e = montaje(tmp_path, sesiones=[("2026-10-27-diseno.md", S1)])   # el modelo falla siempre
    with cli:
        b = cli.get(f"/api/proyectos/{PROYECTO}/brief").json()
        assert b["origen"] == "local" and "versión local" in b["aviso"] and "(" not in b["aviso"]
        assert "Cerrar el modelo de datos" in b["objetivos"] and "Fijar el calendario del piloto" in b["objetivos"] and not any(o.startswith("Cerrar: ") for o in b["objetivos"])
        assert any("Enviar el modelo de datos" in o for o in b["objetivos"])
        assert any("modelo de datos" in q for q in b["preguntas"])
        assert not list((tmp_path / "cache").glob("brief-*")) if (tmp_path / "cache").exists() else True   # lo local no se cachea


def test_brief_con_respuesta_invalida_cae_a_lo_local(tmp_path):
    modelo = ModeloFalso([("Sherpa", "no es json")])
    cli, gestor, cfg, g, bl, _m, _e = montaje(tmp_path, modelo=modelo, sesiones=[("2026-10-27-diseno.md", S1)])
    with cli:
        b = cli.get(f"/api/proyectos/{PROYECTO}/brief").json()
        assert b["origen"] == "local" and b["objetivos"]


def test_brief_incluye_la_siguiente_sesion_del_plan_y_los_recordatorios(tmp_path):
    plan(tmp_path, [{"id": "S1", "nombre": "Cierre de diseño", "fecha_iso": "2099-02-01", "objetivos": ["Aprobar el diseño"], "checks": ["Traer el listado de hoteles"]}])
    cli, gestor, cfg, g, bl, _m, _e = montaje(tmp_path, sesiones=[("2026-10-27-diseno.md", S1)])
    with cli:
        gestor.seguimiento.anadir_recordatorios(PROYECTO, [{"texto": "Retomar la cuestión de licencias"}], {"sesion": "2026-10-27-diseno.md", "fecha": "2026-10-27", "tema": "Diseño"})
        b = cli.get(f"/api/proyectos/{PROYECTO}/brief").json()
        assert b["siguiente_sesion"]["nombre"] == "Cierre de diseño" and b["siguiente_sesion"]["objetivos"] == ["Aprobar el diseño"]
        assert "Aprobar el diseño" in b["objetivos"] and "Retomar la cuestión de licencias" in b["objetivos"] and "Traer el listado de hoteles" in b["datos"]
        assert [r["texto"] for r in b["recordatorios"]] == ["Retomar la cuestión de licencias"]


def test_proyecto_nuevo_sin_nada_y_proyecto_inexistente(tmp_path):
    cli, gestor, cfg, g, bl, modelo, _e = montaje(tmp_path)
    with cli:
        b = cli.get(f"/api/proyectos/{PROYECTO}/brief").json()
        assert b["origen"] == "local" and "Todavía no hay" in b["aviso"] and modelo.llamadas == []
        assert cli.get("/api/proyectos/Inventado/brief").status_code == 404


def test_validar_y_clave():
    assert validar({"objetivos": ["a", "A", " b "], "preguntas": [], "datos": ["x" * 400]})["objetivos"] == ["a", "b"]
    assert len(validar({"datos": ["x" * 400]})["datos"][0]) <= 140
    for malo in (None, [], {}, {"objetivos": [], "preguntas": [], "datos": []}):
        try:
            validar(malo)
            assert False
        except ValueError:
            pass
    d = entrada("P", None, [], [], None, 6000)
    assert clave(d, "haiku") == clave(dict(d), "haiku") != clave(d, "sonnet")
    assert local(d) == {"objetivos": [], "preguntas": [], "datos": []}
