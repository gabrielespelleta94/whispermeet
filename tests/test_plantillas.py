"""Plantillas de reunión (ola 4): objetivos, reparto de perfiles y ritmo; base versionada en el repo y propias del usuario en su carpeta de datos."""
import asyncio
import json
import re

import pytest

from apuntes.equipo.monitor import Monitor
from apuntes.plantillas import BASE, PERFILES, Plantillas, normalizar, pesos_de
from apuntes.rutas import Guardian
from ola4_utils import PROYECTO, cliente, esperar, esperar_async, montar


def test_las_cuatro_plantillas_de_base_estan_completas():
    assert [p["id"] for p in BASE] == ["descubrimiento", "diseno-funcional", "seguimiento", "comite"]
    for p in BASE:
        assert normalizar(p, origen="base")["id"] == p["id"]            # pasan su propia validación
        assert p["version"] >= 1 and p["nombre"] and p["descripcion"] and 3 <= len(p["objetivos"]) <= 12
        assert set(p["perfiles"]) == set(PERFILES) and all(v["peso"] in (0, 1, 2) for v in p["perfiles"].values())
        assert p["ritmo"]["cadencia"] == "equipo" and 5 <= p["ritmo"]["duracion_min"] <= 480


def test_descubrimiento_cubre_necesidad_presupuesto_plazo_decisor_y_competencia():
    d = next(p for p in BASE if p["id"] == "descubrimiento")
    texto = " ".join(d["objetivos"]).lower()
    for palabra in ("necesidad", "presupuesto", "plazo", "decide", "competencia"):
        assert palabra in texto
    assert len(d["objetivos"]) == 5 and d["perfiles"]["estratega"]["peso"] == 2


def test_las_plantillas_de_base_no_llevan_datos_personales_ni_rutas():
    crudo = json.dumps(BASE, ensure_ascii=False)
    assert not re.search(r"@|https?://|[A-Za-z]:\\", crudo)


def test_pesos_de():
    assert pesos_de(next(p for p in BASE if p["id"] == "comite")) == {"coordinador": 2, "funcional": 0, "constructor": 0, "revisor": 2, "estratega": 1}


def test_las_propias_se_validan(tmp_path):
    bueno = {"nombre": "Kick-off interno", "descripcion": "Arranque", "objetivos": ["Repartir roles", " ", "Fijar el calendario"],
             "perfiles": {"coordinador": {"peso": 2, "foco": "roles"}}, "ritmo": {"cadencia": "10", "duracion_min": 40, "ajustes": {"equipo_enfriamiento_global_s": 150}}}
    p = normalizar(bueno)
    assert p["id"] == "kick-off-interno" and p["objetivos"] == ["Repartir roles", "Fijar el calendario"] and p["origen"] == "usuario"
    assert p["perfiles"]["funcional"] == {"peso": 1, "foco": ""} and p["perfiles"]["coordinador"]["peso"] == 2
    for malo, frase in [({**bueno, "nombre": ""}, "nombre"), ({**bueno, "objetivos": []}, "objetivo"),
                        ({**bueno, "perfiles": {"revisor": {"peso": 3}}}, "peso"), ({**bueno, "ritmo": {"cadencia": "9"}}, "cadencia"),
                        ({**bueno, "ritmo": {"duracion_min": 1}}, "duración"), ({**bueno, "ritmo": {"ajustes": {"timeout_s": 5}}}, "ajuste"),
                        ({**bueno, "ritmo": {"ajustes": {"equipo_rotacion_s": -1}}}, "ajuste"), ("no es un objeto", "objeto")]:
        with pytest.raises(ValueError, match=frase):
            normalizar(malo)


def test_el_usuario_amplia_sus_plantillas_en_su_carpeta_de_datos(tmp_path):
    g = Guardian(tmp_path / "r", tmp_path / "b", tmp_path / "c", datos=tmp_path / "datos")
    pl = Plantillas(g)
    assert [p["id"] for p in pl.listar()] == [b["id"] for b in BASE]
    p = pl.anadir({"nombre": "Retro de sprint", "objetivos": ["Qué fue bien", "Qué mejorar"]})
    assert p["id"] == "retro-de-sprint"
    lista = pl.listar()
    assert [x["id"] for x in lista][-1] == "retro-de-sprint" and lista[-1]["origen"] == "usuario" and lista[0]["origen"] == "base"
    assert Plantillas(g).obtener("retro-de-sprint")["nombre"] == "Retro de sprint"            # persistente
    with pytest.raises(ValueError, match="base"):
        pl.anadir({"nombre": "Comité", "id": "comite", "objetivos": ["x"]})
    assert pl.borrar("retro-de-sprint") is True and pl.borrar("retro-de-sprint") is False and pl.borrar("comite") is False
    # un fichero roto o con una plantilla mala no tumba la lista
    g.escribir_datos("plantillas-usuario.json", json.dumps([{"nombre": ""}, {"nombre": "Buena", "objetivos": ["a"]}]))
    assert [x["id"] for x in pl.listar()][-1] == "buena" and len(pl.listar()) == 5
    g.escribir_datos("plantillas-usuario.json", "no es json")
    assert len(pl.listar()) == 4
    sin = Plantillas(Guardian(tmp_path / "r", tmp_path / "b", tmp_path / "c"))
    assert len(sin.listar()) == 4
    with pytest.raises(ValueError, match="datos"):
        sin.anadir({"nombre": "Nueva", "objetivos": ["a"]})


def test_el_peso_de_un_perfil_cambia_su_puntuacion_en_el_monitor():
    def pasada(pesos):
        m = Monitor()
        m.pesos = pesos
        from types import SimpleNamespace
        m.pasada(40.0, [SimpleNamespace(id=1, t=20.0, texto="Quedamos en que Ana se encarga de enviarlo para el viernes que viene sin falta.")], [], [])
        return m
    base = pasada({}).puntos["coordinador"]
    assert base > 0
    assert pasada({"coordinador": 2}).puntos["coordinador"] == 2 * base
    m0 = pasada({"coordinador": 0})
    assert m0.puntos["coordinador"] == 0
    # un perfil con peso 0 tampoco habla por rotación y el resto sí
    m0.palabras_desde = {p: 10_000 for p in m0.palabras_desde}
    perfil, motivo = m0.elegir(10_000.0)
    assert perfil != "coordinador"
    m_nadie = pasada({p: 0 for p in ("coordinador", "funcional", "constructor", "revisor")})
    m_nadie.palabras_desde = {p: 10_000 for p in m_nadie.palabras_desde}
    assert m_nadie.elegir(10_000.0) == (None, "")


def test_endpoints_listar_ampliar_y_borrar(tmp_path):
    gestor, _, _, g, cfg = montar(tmp_path)
    cli = cliente(gestor, cfg, g)
    with cli:
        lista = cli.get("/api/plantillas").json()["plantillas"]
        assert [p["id"] for p in lista][:4] == ["descubrimiento", "diseno-funcional", "seguimiento", "comite"] and lista[0]["origen"] == "base"
        r = cli.post("/api/plantillas", json={"nombre": "Revisión mensual", "objetivos": ["Estado"], "ritmo": {"cadencia": "manual", "duracion_min": 30}})
        assert r.status_code == 200 and r.json()["plantilla"]["id"] == "revision-mensual"
        assert cli.post("/api/plantillas", json={"nombre": "", "objetivos": []}).status_code == 400
        assert len(cli.get("/api/plantillas").json()["plantillas"]) == 5
        assert cli.delete("/api/plantillas/revision-mensual").json()["ok"] is True
        assert cli.delete("/api/plantillas/comite").status_code == 404


def test_iniciar_con_plantilla_pone_objetivos_cadencia_perfiles_y_ritmo(tmp_path):
    gestor, llm, _, g, cfg = montar(tmp_path)
    cli = cliente(gestor, cfg, g)
    with cli:
        r = cli.post("/api/sesion/iniciar", json={"proyecto": PROYECTO, "tema": "Primera toma de contacto", "plantilla": "descubrimiento"})
        assert r.status_code == 200, r.text
        est = r.json()
        assert est["plantilla"] == {"id": "descubrimiento", "nombre": "Descubrimiento"}
        assert [o["texto"] for o in est["objetivos"]] == next(p for p in BASE if p["id"] == "descubrimiento")["objetivos"]
        assert all(o["origen"] == "plantilla" and o["estado"] == "sin_tratar" for o in est["objetivos"])
        assert est["sesion"]["cadencia"] == "equipo"
        mon = gestor.equipo.monitor
        assert mon.pesos == {"coordinador": 1, "funcional": 2, "constructor": 0, "revisor": 1, "estratega": 2}
        assert gestor.equipo.ajustes_sesion == {"equipo_enfriamiento_global_s": 200, "equipo_objetivo_sin_tratar_min": 10}
        esperar(lambda: len(cli.get("/api/sesion").json()["segmentos"]) >= 20)
        gestor.equipo._ultima_comprobacion = -1e9
        gestor.equipo.comprobar(gestor.reloj.ahora(), False)
        assert gestor.equipo.monitor.c["equipo_enfriamiento_global_s"] == 200            # el ritmo de la plantilla manda sobre la configuración
        assert cfg["equipo_enfriamiento_global_s"] == 240                                  # …sin tocarla
        cli.post("/api/sesion/terminar")
        esperar(lambda: cli.get("/api/sesion").json()["revision"]["estado"] in ("lista", "error"))
        cli.post("/api/revision/cerrar", json={})
        # la siguiente reunión, sin plantilla, vuelve a lo de siempre
        r = cli.post("/api/sesion/iniciar", json={"proyecto": PROYECTO, "tema": "Otra"})
        assert r.json()["plantilla"] is None and r.json()["objetivos"] == [] and gestor.equipo.ajustes_sesion == {} and gestor.equipo.monitor.pesos == {}


def test_los_objetivos_propios_mandan_sobre_los_de_la_plantilla_y_la_cadencia_pedida_tambien(tmp_path):
    gestor, _, _, g, cfg = montar(tmp_path)
    cli = cliente(gestor, cfg, g)
    with cli:
        r = cli.post("/api/sesion/iniciar", json={"proyecto": PROYECTO, "tema": "T", "plantilla": "comite", "objetivos": ["Mi objetivo"], "cadencia": 10})
        assert [o["texto"] for o in r.json()["objetivos"]] == ["Mi objetivo"] and r.json()["objetivos"][0]["origen"] == "usuario"
        assert r.json()["sesion"]["cadencia"] == "10"


def test_una_plantilla_inexistente_se_rechaza_antes_de_empezar(tmp_path):
    gestor, _, _, g, cfg = montar(tmp_path)
    cli = cliente(gestor, cfg, g)
    with cli:
        r = cli.post("/api/sesion/iniciar", json={"proyecto": PROYECTO, "tema": "T", "plantilla": "no-existe"})
        assert r.status_code == 400 and "plantilla" in r.json()["detail"]
        assert gestor.estado == "inactivo" and gestor.sesion is None


def test_sin_plantilla_el_inicio_no_cambia(tmp_path):
    gestor, _, _, g, cfg = montar(tmp_path)
    cli = cliente(gestor, cfg, g)
    with cli:
        r = cli.post("/api/sesion/iniciar", json={"proyecto": PROYECTO, "tema": "T", "cadencia": 5})
        assert r.status_code == 200 and r.json()["plantilla"] is None and r.json()["sesion"]["cadencia"] == "5"
