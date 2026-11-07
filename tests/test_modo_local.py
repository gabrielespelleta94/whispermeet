"""Modo solo local (ola 4): sin agentes en vivo, solo transcripción y Monitor; ninguna llamada sale, se impone en la capa de modelo y el cierre
solo lanza los agentes si la petición lo confirma explícitamente."""
import asyncio
import json

import pytest

from apuntes.analisis import ErrorAnalisis
from apuntes.envios import MENSAJE_LOCAL, ModeloVigilado, marcar_tarea
from apuntes.rutas import Guardian
from ola4_utils import PROYECTO, Falso, cliente, esperar, esperar_async, montar
from test_envios import GestorMinimo, ModeloUso, _lineas_registro


def test_la_capa_de_modelo_bloquea_y_anota_el_intento_sin_llamar(tmp_path):
    g = Guardian(tmp_path / "r", tmp_path / "b", tmp_path / "c", datos=tmp_path / "datos")
    interno = ModeloUso()
    m = ModeloVigilado(interno, GestorMinimo(g, local=True))
    marcar_tarea("periodico")
    with pytest.raises(ErrorAnalisis) as e:
        m.completar("sistema", "usuario con datos", "haiku", "low", 10, True, web=True)
    assert e.value.tipo == "local" and e.value.mensaje == MENSAJE_LOCAL and not e.value.transitorio and not e.value.bloqueante
    assert interno.llamadas == []                                    # NO llegó al modelo
    [reg] = _lineas_registro(g)
    assert reg["bloqueado"] is True and reg["chars"] == 0 and reg["extracto"] == "" and reg["tarea"] == "periodico"


def test_un_gestor_en_modo_local_no_llama_nunca_pero_transcribe_y_vigila(tmp_path):
    gestor, llm, _, g, cfg = montar(tmp_path, cfg_extra={"modo_local": True})

    async def go():
        await gestor.iniciar(PROYECTO, "Seguimiento", 5, objetivos=["Cerrar el calendario del piloto"])
        assert gestor.modo_local_activo() and gestor.estado_ligero()["modo_local"]["activo"] is True
        await esperar_async(lambda: len(gestor.sesion.segmentos) >= 55)
        # el Monitor local sigue: ha mirado la transcripción y deja entradas en su feed
        gestor.equipo._ultima_comprobacion = -1e9
        await esperar_async(lambda: gestor.equipo.monitor.pasadas, 20)
        assert llm.llamadas == []
        # «Analizar ahora», Pregúntale y el digest: ninguno sale
        r = await gestor.analizar(manual=True)
        assert r["ok"] is False and "solo local" in r["motivo"]
        await gestor.consultar("¿Qué se dijo del piloto?")
        assert gestor.sesion.consultas[-1]["estado"] == "error" and "solo local" in gestor.sesion.consultas[-1]["error"]
        assert gestor.digest_origen == "local"
        assert llm.llamadas == []
        # al terminar: revisión LOCAL, sin agentes
        await gestor.terminar()
        await esperar_async(lambda: gestor.revision["estado"] == "lista")
        rev = gestor.revision
        assert rev["modo_local"] is True and rev["agentes_pendientes"] is True and rev["cambios"] == []
        assert "modo solo local" in rev["resumen"] and "solo local" in rev["sin_cambios"]
        assert llm.llamadas == []
        assert rev["metricas"]["modo_local"] is True and rev["metricas"]["tokens"]["total"] == 0
        # el usuario confirma lanzar los agentes del cierre
        await gestor.lanzar_agentes_cierre()
        await esperar_async(lambda: gestor.revision["estado"] == "lista" and not gestor.revision["modo_local"])
        assert any("cierre de la reunión" in s for s, _, _ in llm.llamadas)
        assert gestor.revision["resumen"].startswith("Resumen final.") and gestor.revision["agentes_pendientes"] is False
        await gestor.cerrar_revision()

    asyncio.run(go())
    # lo único registrado como envío es el cierre confirmado; los intentos bloqueados de antes (consulta) quedan anotados como tales
    regs = _lineas_registro(g)
    assert [r["tarea"] for r in regs if not r["bloqueado"]] == ["final"]
    assert all(r["tarea"] in ("final", "consulta", "digest") for r in regs)


def test_terminar_con_la_confirmacion_lanza_los_agentes_del_cierre(tmp_path):
    gestor, llm, _, g, cfg = montar(tmp_path, cfg_extra={"modo_local": True})

    async def go():
        await gestor.iniciar(PROYECTO, "Seguimiento", 5)
        await esperar_async(lambda: len(gestor.sesion.segmentos) >= 55)
        await gestor.terminar(lanzar_agentes=True)
        await esperar_async(lambda: gestor.revision["estado"] == "lista")
        assert gestor.revision["modo_local"] is False
        assert any("cierre de la reunión" in s for s, _, _ in llm.llamadas)
        await gestor.cerrar_revision()

    asyncio.run(go())


def test_el_modo_local_se_conmuta_por_sesion(tmp_path):
    gestor, llm, _, g, cfg = montar(tmp_path)          # la configuración dice «no local»

    async def go():
        await gestor.iniciar(PROYECTO, "Seguimiento", 5, modo_local=True)
        assert gestor.modo_local_activo() and cfg["modo_local"] is False
        await esperar_async(lambda: len(gestor.sesion.segmentos) >= 55)
        assert llm.llamadas == []
        # se desactiva a mitad de reunión: vuelve el análisis y se prepara el contexto que se había saltado
        assert gestor.poner_modo_local(False)["activo"] is False
        await esperar_async(lambda: gestor.digest_origen in ("generado", "cache"))
        r = await gestor.analizar(manual=True)
        assert r["ok"], r
        # y se vuelve a cerrar
        assert gestor.poner_modo_local(True)["activo"] is True
        n = len(llm.llamadas)
        assert (await gestor.analizar(manual=True))["ok"] is False and len(llm.llamadas) == n
        await gestor.terminar()
        await esperar_async(lambda: gestor.revision["estado"] == "lista")
        assert gestor.revision["modo_local"] is True and len(llm.llamadas) == n
        await gestor.cerrar_revision()
        # terminada la reunión, manda la configuración
        assert gestor.modo_local_activo() is False

    asyncio.run(go())


def test_sin_reunion_el_modo_local_de_la_configuracion_bloquea_las_llamadas_previas(tmp_path):
    gestor, llm, _, g, cfg = montar(tmp_path)
    cli = cliente(gestor, cfg, g)
    with cli:
        assert cli.get("/api/modo-local").json() == {"activo": False, "sesion": None, "config": False, "agentes_cierre_confirmados": False}
        r = cli.post("/api/modo-local", json={"activo": True}).json()
        assert r["activo"] is True and r["config"] is True and cfg["modo_local"] is True
        # «Generar con Claude» (contexto de la reunión) pasa por el mismo punto: no sale
        r = cli.post("/api/contexto-reunion/generar", json={"texto": "Reunión de seguimiento del piloto con el cliente.", "tema": "x"})
        assert r.status_code == 400 and "solo local" in r.json()["detail"]
        assert llm.llamadas == []
        cli.post("/api/modo-local", json={"activo": False})


def test_endpoints_iniciar_con_modo_local_y_terminar_con_confirmacion(tmp_path):
    gestor, llm, _, g, cfg = montar(tmp_path)
    cli = cliente(gestor, cfg, g)
    with cli:
        r = cli.post("/api/sesion/iniciar", json={"proyecto": PROYECTO, "tema": "Seguimiento", "cadencia": 5, "modo_local": True})
        assert r.status_code == 200 and r.json()["modo_local"]["activo"] is True and r.json()["modo_local"]["sesion"] is True
        esperar(lambda: len(cli.get("/api/sesion").json()["segmentos"]) >= 55)
        assert cli.post("/api/sesion/analizar").json()["ok"] is False
        assert cli.post("/api/sesion/terminar", json={}).status_code == 200            # sin confirmar
        esperar(lambda: cli.get("/api/sesion").json()["revision"]["estado"] == "lista")
        rev = cli.get("/api/sesion").json()["revision"]
        assert rev["modo_local"] is True and rev["agentes_pendientes"] is True and llm.llamadas == []
        assert cli.post("/api/revision/agentes").status_code == 200
        esperar(lambda: not cli.get("/api/sesion").json()["revision"]["modo_local"] and cli.get("/api/sesion").json()["revision"]["estado"] == "lista")
        assert any("cierre de la reunión" in s for s, _, _ in llm.llamadas)
        assert cli.post("/api/revision/agentes").status_code in (200, 400)
        assert cli.post("/api/revision/cerrar", json={}).status_code == 200
        assert cli.post("/api/revision/agentes").status_code == 400                       # ya no hay revisión


def test_terminar_por_http_con_lanzar_agentes_true(tmp_path):
    gestor, llm, _, g, cfg = montar(tmp_path, cfg_extra={"modo_local": True})
    cli = cliente(gestor, cfg, g)
    with cli:
        cli.post("/api/sesion/iniciar", json={"proyecto": PROYECTO, "tema": "Seguimiento", "cadencia": 5})
        esperar(lambda: len(cli.get("/api/sesion").json()["segmentos"]) >= 55)
        assert cli.post("/api/sesion/terminar", json={"lanzar_agentes": True}).status_code == 200
        esperar(lambda: cli.get("/api/sesion").json()["revision"]["estado"] == "lista")
        assert cli.get("/api/sesion").json()["revision"]["modo_local"] is False
        assert any("cierre de la reunión" in s for s, _, _ in llm.llamadas)


def test_sin_modo_local_todo_sigue_igual(tmp_path):
    gestor, llm, _, g, cfg = montar(tmp_path)

    async def go():
        await gestor.iniciar(PROYECTO, "Seguimiento", 5)
        await esperar_async(lambda: gestor.digest_origen in ("generado", "cache"))
        await esperar_async(lambda: len(gestor.sesion.segmentos) >= 55)
        assert (await gestor.analizar(manual=True))["ok"]
        await gestor.terminar()
        await esperar_async(lambda: gestor.revision["estado"] == "lista")
        assert gestor.revision["modo_local"] is False and gestor.revision["agentes_pendientes"] is False
        await gestor.cerrar_revision()

    asyncio.run(go())
    assert {"digest", "periodico", "final"} <= {r["tarea"] for r in _lineas_registro(g)}
