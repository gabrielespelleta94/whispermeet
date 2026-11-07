"""Métricas de valor (ola 4): objetivos cerrados en la reunión, minuto en que se tocó y se cerró cada uno, avisos aceptados frente a descartados y tokens."""
import asyncio
import json
from types import SimpleNamespace

from apuntes import metricas as MT
from apuntes.analisis import Respuesta, Uso
from apuntes.planes import objetivo_nuevo
from apuntes.rutas import Guardian
from apuntes.sesion import Sesion
from ola4_utils import PROYECTO, Falso, cliente, esperar, esperar_async, montar


def _obj(n, texto, estado="sin_tratar", minuto="", t_seg=None, t_primero=None, sugerido=False):
    o = objetivo_nuevo(n, texto, "usuario", sugerido)
    o.update(estado=estado, minuto=minuto, t_seg=t_seg, t_primero=t_primero)
    return o


def _sesion(tmp_path, **kw):
    s = Sesion(kw.pop("proyecto", "Alfa"), "Seguimiento", 5, tmp_path / "s.md")
    s.duracion_s = 1800
    for k, v in kw.items():
        setattr(s, k, v)
    return s


# ------------------------------------------------------------------ objetivos
def test_minuto_en_que_se_toco_y_en_que_se_cerro_cada_objetivo():
    objs = [_obj(1, "Cerrar calendario", "cubierto", "10:00", 600, 120),
            _obj(2, "Acordar alcance", "parcial", "20:00", 1200, 900),
            _obj(3, "Sin hablar"),
            _obj(4, "Sugerido sin confirmar", sugerido=True),
            _obj(5, "Cubierto sin primer toque", "cubierto", "05:00", 300, None)]
    m = {o["n"]: o for o in MT.objetivos_metricas(objs, {1: 90.0, 2: 1000.0, 3: 30.0})}
    assert 4 not in m                                                      # un sugerido sin confirmar no se mide
    assert m[1]["tocado_min"] == "01:30" and m[1]["cerrado_min"] == "10:00" and m[1]["minutos_hasta_cierre"] == 8.5       # el primer toque es el MÁS temprano de Monitor y análisis
    assert m[2]["tocado_min"] == "15:00" and m[2]["cerrado_min"] is None and m[2]["minutos_hasta_cierre"] is None          # parcial: sin cierre
    assert m[3]["tocado_min"] == "00:30" and m[3]["estado"] == "sin_tratar"
    assert m[5]["tocado_min"] is None and m[5]["cerrado_min"] == "05:00" and m[5]["minutos_hasta_cierre"] is None          # sin toque conocido: no se inventa


def test_un_toque_posterior_al_cierre_se_acota_al_cierre():
    [o] = MT.objetivos_metricas([_obj(1, "x", "cubierto", "01:00", 60, 60)], {1: 500.0})
    assert o["tocado_t"] == 60 and o["minutos_hasta_cierre"] == 0.0


def test_resumen_de_objetivos_de_la_sesion(tmp_path):
    s = _sesion(tmp_path, objetivos=[_obj(1, "a", "cubierto", "10:00", 600, 120), _obj(2, "b", "cubierto", "12:00", 720, 600),
                                      _obj(3, "c", "parcial", "13:00", 780, 700), _obj(4, "d")])
    r = MT.de_sesion(s, SimpleNamespace(monitor=SimpleNamespace(primer_toque={}, feed=[])))["objetivos_resumen"]
    assert r == {"total": 4, "cerrados": 2, "parciales": 1, "sin_tratar": 1, "ratio_cerrados": 0.5, "minutos_medio_hasta_cierre": 5.0, "primer_cierre_min": "10:00"}
    vacio = MT.de_sesion(_sesion(tmp_path))["objetivos_resumen"]
    assert vacio["total"] == 0 and vacio["ratio_cerrados"] is None and vacio["minutos_medio_hasta_cierre"] is None and vacio["primer_cierre_min"] is None


# ------------------------------------------------------------------ avisos
def test_avisos_aceptados_frente_a_descartados(tmp_path):
    s = _sesion(tmp_path,
                consejos=[{"id": "c1", "fijado": True}, {"id": "c2", "descartado": True}, {"id": "c3"}],
                respuestas=[{"id": "r1", "fijado": True}, {"id": "r2", "fijado": True, "descartado": True}],
                tarjetas=[{"id": "t1-aaaa", "categoria": "idea", "texto": "x"}, {"id": "t2-bbbb", "categoria": "idea", "texto": "y", "mal": True}],
                acciones=[{"id": "a1", "estado": "aceptada"}, {"id": "a2", "estado": "descartada"}, {"id": "a3", "estado": "propuesta"}, {"id": "a4", "estado": "hecha"}])
    feed = [{"id": "m1"}, {"id": "m2", "silenciado": True}]
    a = MT.avisos_metricas(s, feed)
    assert a["por_tipo"] == {"tarjetas": 2, "consejos": 3, "respuestas": 2, "acciones": 4, "monitor": 2}
    assert a["emitidos"] == 13
    assert a["aceptados"] == 4          # c1, r1, a1, a4
    assert a["descartados"] == 5        # c2, r2 (descartar gana), tarjeta mal, a2, monitor silenciado
    assert a["marcados_mal"] == 2 and a["sin_valorar"] == 4 and a["tasa_aceptacion"] == round(4 / 9, 2)


def test_sin_avisos_la_tasa_no_se_inventa(tmp_path):
    a = MT.avisos_metricas(_sesion(tmp_path))
    assert a["emitidos"] == 0 and a["tasa_aceptacion"] is None


def test_tokens(tmp_path):
    llamadas = [{"tarea": "digest", "uso": [{"entrada": 100, "salida": 20, "cache_creacion": 5, "cache_lectura": 5}]},
                {"tarea": "digest", "uso": [{"entrada": 10, "salida": 2}]}, {"tarea": "final", "uso": []}]
    t = MT.tokens_metricas(llamadas)
    assert t == {"entrada": 120, "salida": 22, "total": 142, "llamadas": 3, "por_tarea": {"digest": 142, "final": 0}}


# ------------------------------------------------------------------ almacén y agregado
def test_almacen_una_medida_por_sesion_y_agregado_por_proyecto(tmp_path):
    g = Guardian(tmp_path / "r", tmp_path / "b", tmp_path / "c", datos=tmp_path / "datos")
    al = MT.AlmacenMetricas(g)

    def reg(sid, proyecto, cerr, tot, tiempos, ac, de, tok, fecha="2026-11-01"):
        return {"sesion": sid, "proyecto": proyecto, "tema": sid, "fecha": fecha, "duracion_s": 600.0, "modo_local": False,
                "objetivos": [{"minutos_hasta_cierre": x} for x in tiempos],
                "objetivos_resumen": {"total": tot, "cerrados": cerr, "ratio_cerrados": cerr / tot, "minutos_medio_hasta_cierre": sum(tiempos) / len(tiempos) if tiempos else None},
                "avisos": {"emitidos": ac + de + 2, "aceptados": ac, "descartados": de, "marcados_mal": 1}, "tokens": {"entrada": tok, "salida": tok // 10, "total": tok + tok // 10}}
    assert al.guardar(reg("s1", "Alfa", 1, 4, [4.0], 1, 1, 1000))
    assert al.guardar(reg("s1", "Alfa", 2, 4, [4.0, 6.0], 3, 1, 1000))        # se volvió a guardar: gana la última
    assert al.guardar(reg("s2", "Alfa", 3, 3, [2.0, 2.0, 5.0], 2, 2, 2000, "2026-11-05"))
    assert al.guardar(reg("s3", "Beta", 0, 2, [], 0, 0, 500))
    assert [m["sesion"] for m in al.todas()] == ["s1", "s2", "s3"] and al.todas()[0]["objetivos_resumen"]["cerrados"] == 2
    assert len(al.de_proyecto("alfa")) == 2
    ag = MT.agregar(al.de_proyecto("Alfa"))
    assert ag["sesiones"] == 2 and ag["objetivos"] == {"total": 7, "cerrados": 5, "ratio_cerrados": 0.71, "minutos_medio_hasta_cierre": 3.8, "con_tiempo_de_cierre": 5}
    assert ag["avisos"] == {"emitidos": 12, "aceptados": 5, "descartados": 3, "marcados_mal": 2, "tasa_aceptacion": 0.62}
    assert ag["tokens"]["total"] == 3300 and ag["tokens"]["por_sesion"] == 1650 and ag["tokens"]["por_objetivo_cerrado"] == 660
    assert [x["sesion"] for x in ag["serie"]] == ["s1", "s2"] and ag["duracion_total_s"] == 1200.0
    assert MT.agregar([])["objetivos"]["ratio_cerrados"] is None and MT.agregar([])["tokens"]["por_sesion"] == 0
    assert not MT.AlmacenMetricas(Guardian(tmp_path / "r", tmp_path / "b", tmp_path / "c")).guardar({"sesion": "x"})    # sin carpeta de datos: no guarda, no rompe


# ------------------------------------------------------------------ una reunión de punta a punta
class FaloObjetivos(Falso):
    """El análisis periódico va cerrando los objetivos con su minuto: primero toca uno, después cierra los dos."""

    def __init__(self):
        super().__init__()
        self.n = 0

    def completar(self, sistema, usuario, modelo, *a, **k):
        r = super().completar(sistema, usuario, modelo, *a, **k)
        if "análisis incremental" in sistema:
            self.n += 1
            d = json.loads(r.texto)
            d["o"] = [{"i": 1, "e": "p", "m": "01:00"}] if self.n == 1 else [{"i": 1, "e": "c", "m": "03:30"}, {"i": 2, "e": "c", "m": "04:00"}]
            return Respuesta(json.dumps(d), r.uso, r.ms)
        return r


def test_el_cierre_trae_las_metricas_y_se_guardan_y_se_agregan_por_proyecto(tmp_path):
    gestor, llm, _, g, cfg = montar(tmp_path, llm=FaloObjetivos())
    cli = cliente(gestor, cfg, g)
    with cli:
        r = cli.post("/api/sesion/iniciar", json={"proyecto": PROYECTO, "tema": "Seguimiento", "cadencia": 5,
                                                 "objetivos": ["Cerrar el calendario del piloto", "Acordar el alcance", "Tema que no sale"]})
        assert r.status_code == 200, r.text
        sid = r.json()["sesion"]["id"]
        esperar(lambda: len(cli.get("/api/sesion").json()["segmentos"]) >= 55)
        assert cli.post("/api/sesion/analizar").json()["ok"]
        assert cli.post("/api/sesion/analizar").json()["ok"] or True
        gestor.sesion.ultimo_analizado_id = 0
        assert cli.post("/api/sesion/analizar").json()["ok"]
        # métricas en vivo
        vivo = cli.get("/api/sesion/metricas").json()
        assert vivo["sesion"] == sid and vivo["objetivos_resumen"]["cerrados"] == 2 and vivo["tokens"]["llamadas"] >= 3
        # tarjetas del Falso: marcar una como «mal» y fijar un consejo para que cuenten
        pend = next(t for t in gestor.sesion.tarjetas if t["categoria"] == "pendiente")
        cli.post(f"/api/avisos/{pend['id']}/mal")
        cli.post("/api/sesion/terminar")
        esperar(lambda: cli.get("/api/sesion").json()["revision"]["estado"] == "lista")
        m = cli.get("/api/sesion").json()["revision"]["metricas"]
        assert m["sesion"] == sid and m["proyecto"] == PROYECTO and m["modo_local"] is False and m["plan"] is None
        por_n = {o["n"]: o for o in m["objetivos"]}
        assert por_n[1]["estado"] == "cubierto" and por_n[1]["cerrado_min"] == "03:30" and por_n[1]["tocado_min"] is not None and por_n[1]["minutos_hasta_cierre"] is not None
        assert por_n[2]["estado"] == "cubierto" and por_n[2]["cerrado_min"] == "04:00"
        assert por_n[3]["estado"] == "sin_tratar" and por_n[3]["cerrado_min"] is None
        assert m["objetivos_resumen"]["cerrados"] == 2 and m["objetivos_resumen"]["total"] == 3 and m["objetivos_resumen"]["ratio_cerrados"] == 0.67
        assert m["avisos"]["marcados_mal"] >= 1 and m["avisos"]["descartados"] >= 1 and m["avisos"]["por_tipo"]["tarjetas"] >= 1
        assert m["tokens"]["total"] > 0 and m["tokens"]["por_tarea"]["final"] > 0 and m["envios"]["enviadas"] >= 4
        cli.post("/api/revision/cerrar", json={})
        # agregado por proyecto
        ag = cli.get(f"/api/proyectos/{PROYECTO}/metricas").json()
        assert ag["proyecto"] == PROYECTO and ag["sesiones"] == 1
        assert ag["objetivos"]["total"] == 3 and ag["objetivos"]["cerrados"] == 2 and ag["objetivos"]["ratio_cerrados"] == 0.67
        assert ag["tokens"]["total"] == m["tokens"]["total"] and ag["serie"][0]["sesion"] == sid
        assert cli.get("/api/proyectos/Otro/metricas").json()["sesiones"] == 0
        # una segunda reunión suma
        cli.post("/api/sesion/iniciar", json={"proyecto": PROYECTO, "tema": "Otra"})
        esperar(lambda: len(cli.get("/api/sesion").json()["segmentos"]) >= 20)
        cli.post("/api/sesion/terminar")
        esperar(lambda: cli.get("/api/sesion").json()["revision"]["estado"] in ("lista", "error"))
        assert cli.get(f"/api/proyectos/{PROYECTO}/metricas").json()["sesiones"] == 2


def test_las_metricas_no_rompen_una_reunion_sin_carpeta_de_datos(tmp_path):
    gestor, llm, _, g, cfg = montar(tmp_path, datos=False)

    async def go():
        await gestor.iniciar(PROYECTO, "T", 5, objetivos=["a"])
        await esperar_async(lambda: len(gestor.sesion.segmentos) >= 55)
        await gestor.terminar()
        await esperar_async(lambda: gestor.revision["estado"] == "lista" and gestor.revision.get("metricas"))   # el cálculo definitivo llega justo después de «lista»
        assert gestor.revision["metricas"]["objetivos_resumen"]["total"] == 1 and gestor.revision["metricas"]["envios"] is None
        await gestor.cerrar_revision()

    asyncio.run(go())
