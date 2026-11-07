"""Ola 3, punto 1 y 4: bandeja de acciones (crear, aceptar, editar, descartar), eventos por el WebSocket, pregunta del Capitán por objetivo sin tratar,
prioridad «fijo» de las contradicciones de alcance o importe, y lo que pasa al cerrar. Todo local y con modelo falso."""
import asyncio
import json

import pytest

from apuntes import tarjetas as TJ
from apuntes.acciones import pregunta_plantilla, validar_pregunta
from apuntes.analisis.analista import Analista
from ola3_util import PROYECTO, ModeloFalso, montaje, sesion_directa


def test_ciclo_de_una_accion_por_la_api(tmp_path):
    cli, gestor, cfg, g, bl, _m, eventos = montaje(tmp_path)
    with cli:
        assert cli.post("/api/acciones", json={"tipo": "pendiente", "texto": "Enviar tarifas"}).status_code == 400   # sin reunión
        sesion_directa(gestor, g)
        r = cli.post("/api/acciones", json={"tipo": "pendiente", "texto": "Enviar el fichero de tarifas", "origen": "Capitán",
                                            "cita": {"texto": "yo las envío el viernes", "minuto": "04:12"}, "datos": {"dueno": "Ana", "fecha": "viernes", "basura": "x"}})
        assert r.status_code == 200
        a = r.json()
        assert a["estado"] == "propuesta" and a["tipo"] == "pendiente" and a["origen"] == "Capitán" and a["modo"] == "proponer" and a["auto"] is False
        assert a["cita"] == {"texto": "yo las envío el viernes", "minuto": "04:12"} and a["datos"] == {"dueno": "Ana", "fecha": "viernes"}
        assert a["prioridad"] == "normal" and a["creada"] and a["id"].startswith("a")
        # duplicado: no se repite
        assert cli.post("/api/acciones", json={"tipo": "pendiente", "texto": "enviar el fichero de TARIFAS"}).status_code == 400
        # editar, aceptar, descartar, reabrir, hecha
        e = cli.put(f"/api/acciones/{a['id']}", json={"texto": "Enviar tarifas 2027", "datos": {"dueno": "Luis"}}).json()
        assert e["texto"] == "Enviar tarifas 2027" and e["datos"]["dueno"] == "Luis"
        assert cli.post(f"/api/acciones/{a['id']}/aceptar").json()["estado"] == "aceptada"
        assert cli.post(f"/api/acciones/{a['id']}/descartar").json()["estado"] == "descartada"
        assert cli.post(f"/api/acciones/{a['id']}/aceptar").status_code == 400   # descartada: primero se reabre
        assert cli.post(f"/api/acciones/{a['id']}/reabrir").json()["estado"] == "propuesta"
        assert cli.post(f"/api/acciones/{a['id']}/aceptar", json={"texto": "Enviar tarifas definitivas"}).json()["texto"] == "Enviar tarifas definitivas"
        assert cli.post(f"/api/acciones/{a['id']}/hecha").json()["estado"] == "hecha"
        assert cli.post("/api/acciones/zzz/aceptar").status_code == 400 and cli.post("/api/acciones/a999/aceptar").status_code == 400
        assert cli.post("/api/acciones", json={"tipo": "inventado", "texto": "x"}).status_code == 400
        estado = cli.get("/api/acciones").json()
        assert [x["id"] for x in estado["acciones"]] == [a["id"]] and estado["autonomia"]["pendiente"] == "proponer"
    tipos = [ev for ev in eventos if ev["tipo"] == "acciones"]
    assert tipos and tipos[0]["nuevas"][0]["id"] == a["id"] and all("autonomia" in ev for ev in tipos)
    assert gestor.snapshot()["acciones"][0]["estado"] == "hecha"


def test_el_texto_vacio_o_el_tipo_raro_se_rechazan(tmp_path):
    cli, gestor, cfg, g, *_ = montaje(tmp_path)
    with cli:
        sesion_directa(gestor, g)
        assert cli.post("/api/acciones", json={"tipo": "correo", "texto": "   "}).status_code == 400
        a = cli.post("/api/acciones", json={"tipo": "correo", "texto": "x" * 900}).json()
        assert len(a["texto"]) <= 300
        assert cli.put(f"/api/acciones/{a['id']}", json={"texto": " "}).status_code == 400


def test_autonomia_avisar_y_hacer_se_reflejan_en_la_accion(tmp_path):
    cli, gestor, cfg, g, *_ = montaje(tmp_path, config={"autonomia": {"correo": "avisar", "cambio_contexto": "hacer"}})
    with cli:
        sesion_directa(gestor, g)
        assert cli.post("/api/acciones", json={"tipo": "correo", "texto": "Riesgo: plazo"}).json()["modo"] == "avisar"
        c = cli.post("/api/acciones", json={"tipo": "cambio_contexto", "texto": "02-alcance.md: añadir fila"}).json()
        assert c["modo"] == "hacer" and c["estado"] == "aceptada" and c["auto"] is True
        assert cli.post("/api/acciones", json={"tipo": "pendiente", "texto": "Algo"}).json()["estado"] == "propuesta"


def test_un_pendiente_detectado_se_propone_con_su_cita(tmp_path):
    cli, gestor, cfg, g, *_ = montaje(tmp_path)
    s = sesion_directa(gestor, g)
    t = {"id": "t1-aaaa", "categoria": "pendiente", "texto": "Mandar el catálogo", "minuto": "03:10", "responsable": "Ana", "linea": "Ana: yo mando el catálogo mañana", "perfil": "coordinador"}
    nuevas = gestor.acciones.desde_tarjetas([t, {**t, "categoria": "idea", "id": "t2"}, t])
    assert len(nuevas) == 1
    a = nuevas[0]
    assert a["origen"] == "Capitán" and a["datos"]["dueno"] == "Ana" and a["cita"] == {"texto": "Ana: yo mando el catálogo mañana", "minuto": "03:10"}
    assert len(s.acciones) == 1


# ------------------------------------------------------------------ prioridad fijo / normal / discreto
def test_prioridad_de_las_tarjetas():
    f = TJ.prioridad_de
    assert f({"categoria": "contradicción", "texto": "El alcance de la fase 1 incluye SAP, pero estaba fuera", "perfil": "revisor"}) == "fijo"
    assert f({"categoria": "contradicción", "texto": "Dicen 40.000 euros, el contexto 30.000", "perfil": "revisor"}) == "fijo"
    assert f({"categoria": "contradicción", "texto": "Importe distinto", "referencia": "presupuesto cerrado", "perfil": None}) == "fijo"
    assert f({"categoria": "contradicción", "texto": "Cambia la fecha del piloto", "perfil": "revisor"}) == "normal"
    assert f({"categoria": "contradicción", "texto": "El alcance cambia", "perfil": "constructor"}) == "normal"   # solo la ve el Auditor
    assert f({"categoria": "idea", "texto": "Delegar proyectos"}) == "discreto"
    assert f({"categoria": "decisión", "texto": "Se sigue con el plan"}) == "normal"


def test_las_tarjetas_que_emite_el_gestor_llevan_prioridad(tmp_path):
    cli, gestor, *_ = montaje(tmp_path)
    sesion_directa(gestor, gestor.g)
    t = gestor._tarjeta({"categoria": "contradicción", "texto": "El alcance incluye SAP", "minuto": "01:00", "estado": "posible", "perfil": "revisor"})
    assert t["prioridad"] == "fijo" and "id" in t and t["categoria"] == "contradicción"   # el formato anterior no cambia
    assert gestor._tarjeta({"categoria": "idea", "texto": "x", "minuto": "01:00"})["prioridad"] == "discreto"


# ------------------------------------------------------------------ pregunta del Capitán por un objetivo sin tratar
def correr(coro):
    return asyncio.run(coro)


async def _paso_y_esperar(gestor, t):
    await gestor.acciones.paso(t)
    for _ in range(100):
        if not gestor.acciones._en_curso:
            return
        await asyncio.sleep(0.02)
    raise AssertionError("la pregunta no terminó")


def test_pregunta_local_cuando_un_objetivo_lleva_diez_minutos_sin_tocarse(tmp_path):
    cli, gestor, cfg, g, bl, modelo, eventos = montaje(tmp_path)   # sin modelo: el analista no existe
    s = sesion_directa(gestor, g, objetivos=["Cerrar el alcance de la fase uno", "Acordar el calendario"], t=9 * 60)
    gestor.equipo.monitor.ultimo_toque[2] = 8 * 60   # el 2 se tocó hace un minuto

    async def todo():
        await _paso_y_esperar(gestor, 9 * 60)
        assert s.acciones == []                      # aún no han pasado 10 min
        gestor.reloj.fijar(10.5 * 60)
        await _paso_y_esperar(gestor, 10.5 * 60)
        await _paso_y_esperar(gestor, 11 * 60)       # repetir la pasada no duplica
    correr(todo())
    assert len(s.acciones) == 1
    a = s.acciones[0]
    assert a["tipo"] == "pregunta" and a["origen"] == "Capitán" and a["datos"]["objetivo"] == 1 and "alcance" in a["texto"].lower() and a["estado"] == "propuesta"
    assert modelo.llamadas == []                     # sin modelo: plantilla local, 0 tokens

    async def luego():   # el objetivo 2 también acaba pasándose, pero una sola vez por objetivo
        await _paso_y_esperar(gestor, 20 * 60)
        await _paso_y_esperar(gestor, 30 * 60)
    correr(luego())
    assert [x["datos"]["objetivo"] for x in s.acciones] == [1, 2]


def test_pregunta_con_haiku_cuando_hay_modelo_y_presupuesto(tmp_path):
    modelo = ModeloFalso([("Capitán", {"q": "¿Quién valida el alcance de la fase uno antes del viernes?"})])
    cli, gestor, cfg, g, *_ = montaje(tmp_path, modelo=modelo)
    s = sesion_directa(gestor, g, objetivos=["Cerrar el alcance de la fase uno"], t=12 * 60)
    gestor.analista = Analista(modelo, cfg, gestor.consumo, g, "t")
    correr(_paso_y_esperar(gestor, 12 * 60))
    assert len(modelo.llamadas) == 1 and modelo.llamadas[0][2] == "haiku"
    assert s.acciones[0]["texto"] == "¿Quién valida el alcance de la fase uno antes del viernes?"


def test_pregunta_sin_modelo_util_cae_a_la_plantilla_y_no_gasta_con_el_presupuesto_agotado(tmp_path):
    modelo = ModeloFalso([("Capitán", "esto no es JSON")])
    cli, gestor, cfg, g, *_ = montaje(tmp_path, modelo=modelo)
    s = sesion_directa(gestor, g, objetivos=["Cerrar el alcance de la fase uno"], t=12 * 60)
    gestor.analista = Analista(modelo, cfg, gestor.consumo, g, "t")
    correr(_paso_y_esperar(gestor, 12 * 60))
    assert s.acciones[0]["texto"].startswith("Aún no hemos tratado")   # la respuesta no válida no rompe nada
    # presupuesto al 100 %: ni siquiera se intenta la llamada
    cli2, gestor2, cfg2, g2, *_ = montaje(tmp_path / "otro", modelo=ModeloFalso([("Capitán", {"q": "¿Qué falta para cerrarlo hoy?"})]))
    s2 = sesion_directa(gestor2, g2, objetivos=["Cerrar el alcance de la fase uno"], t=12 * 60)
    gestor2.analista = Analista(gestor2.llm, cfg2, gestor2.consumo, g2, "t")
    gestor2.equipo.presupuesto.sumar(12 * 60, 10 ** 7, "x")
    correr(_paso_y_esperar(gestor2, 12 * 60))
    assert gestor2.llm.llamadas == [] and s2.acciones[0]["tipo"] == "pregunta"


def test_un_objetivo_cubierto_o_tocado_no_genera_pregunta(tmp_path):
    cli, gestor, *_ = montaje(tmp_path)
    s = sesion_directa(gestor, gestor.g, objetivos=["Uno", "Dos"], t=15 * 60)
    s.objetivos[0]["estado"] = "cubierto"
    gestor.equipo.monitor.ultimo_toque[2] = 14 * 60
    assert gestor.acciones.candidatos_pregunta(15 * 60) == []
    gestor.cfg.actualizar({"objetivo_sin_tratar_min": 0}, guardar=False)
    s.objetivos[0]["estado"] = "sin_tratar"
    assert gestor.acciones.candidatos_pregunta(15 * 60) == []   # 0 = desactivado


def test_plantilla_y_validacion_de_la_pregunta():
    assert pregunta_plantilla({"texto": "Cerrar el alcance.", "estado": "sin_tratar"}).startswith("Aún no hemos tratado «Cerrar el alcance»")
    assert "qué falta" in pregunta_plantilla({"texto": "Calendario", "estado": "parcial"})
    assert validar_pregunta({"q": "qué falta para cerrar el alcance?"}).startswith("¿")
    for malo in (None, {}, {"q": "corta?"}, {"q": "sin signo de pregunta pero larga"}):
        with pytest.raises(ValueError):
            validar_pregunta(malo)


# ------------------------------------------------------------------ al cerrar
def test_al_cerrar_los_pendientes_van_al_seguimiento_y_los_recordatorios_al_brief(tmp_path):
    cli, gestor, cfg, g, bl, *_ = montaje(tmp_path)
    with cli:
        sesion_directa(gestor, g)
        p = cli.post("/api/acciones", json={"tipo": "pendiente", "texto": "Enviar el catálogo de habitaciones", "datos": {"dueno": "Ana", "fecha": "viernes"}}).json()
        cli.post(f"/api/acciones/{p['id']}/aceptar")
        cli.post("/api/acciones", json={"tipo": "pendiente", "texto": "Revisar licencias"})                    # sin aceptar: no pasa
        r = cli.post("/api/acciones", json={"tipo": "recordatorio", "texto": "Retomar el tema de licencias"}).json()
        cli.post(f"/api/acciones/{r['id']}/aceptar")
        resumen = gestor._cierre_ola3()
        assert resumen["pendientes"] == 1 and resumen["recordatorios"] == 1
        seg = cli.get(f"/api/proyectos/{PROYECTO}/seguimiento").json()
        textos = {x["texto"]: x for x in seg["pendientes"]}
        assert list(textos) == ["Enviar el catálogo de habitaciones"]
        assert textos["Enviar el catálogo de habitaciones"]["responsable"] == "Ana" and textos["Enviar el catálogo de habitaciones"]["plazo"] == "viernes"
        brief = cli.get(f"/api/proyectos/{PROYECTO}/brief").json()
        assert [x["texto"] for x in brief["recordatorios"]] == ["Retomar el tema de licencias"]


def test_las_entradas_de_correo_aceptadas_salen_en_el_correo_de_cierre(tmp_path):
    from apuntes import correo_cierre as CC
    cli, gestor, cfg, g, *_ = montaje(tmp_path)
    with cli:
        s = sesion_directa(gestor, g)
        assert CC.correo_de_sesion(s) == ""
        a = cli.post("/api/acciones", json={"tipo": "correo", "texto": "Riesgo: el plazo de la fase uno es ajustado"}).json()
        assert CC.correo_de_sesion(s) == ""                                  # propuesta: no entra
        cli.post(f"/api/acciones/{a['id']}/aceptar")
        correo = CC.correo_de_sesion(s)
        assert "Además" in correo and "- Riesgo: el plazo de la fase uno es ajustado" in correo
        cli.post(f"/api/acciones/{a['id']}/descartar")
        assert CC.correo_de_sesion(s) == ""


def test_propuestas_locales_al_terminar_la_revision(tmp_path):
    cli, gestor, cfg, g, *_ = montaje(tmp_path)
    s = sesion_directa(gestor, g, objetivos=["Cerrar el alcance", "Fijar fecha del piloto"])
    s.objetivos[0]["estado"] = "cubierto"
    s.tarjetas += [{"id": "t1", "categoria": "riesgo", "texto": "Proveedor sin confirmar", "minuto": "02:00", "perfil": "coordinador"},
                   {"id": "t2", "categoria": "contradicción", "estado": "confirmada", "texto": "Importe distinto al presupuesto", "minuto": "03:00", "prioridad": "fijo"},
                   {"id": "t3", "categoria": "pregunta", "texto": "¿Quién valida?", "minuto": "04:00"}]
    gestor.revision = {"estado": "lista", "cambios": [
        {"id": "c1", "valido": True, "fichero": "02-alcance.md", "motivo": "Alcance", "tipo": "anadir", "minuto": "01:00", "preaceptado": True, "cita": {"texto": "x", "minuto": "01:00"}},
        {"id": "c2", "valido": True, "fichero": "03-datos.md", "motivo": "Datos", "tipo": "anadir", "minuto": "", "preaceptado": False, "cita": None},
        {"id": "c3", "valido": False, "fichero": "x.md", "motivo": "m"}]}
    gestor.cfg.actualizar({"autonomia": {"cambio_contexto": "hacer"}}, guardar=False)
    gestor.acciones.desde_revision()
    por = {(a["tipo"], a["texto"][:20]): a for a in s.acciones}
    c1, c2 = [a for a in s.acciones if a["tipo"] == "cambio_contexto"]
    assert c1["estado"] == "aceptada" and c1["auto"] is True and c1["datos"]["cambio_id"] == "c1" and c1["cita"]["minuto"] == "01:00"
    assert c2["estado"] == "propuesta" and c2["auto"] is False                 # sin cita fiable: nunca se preacepta
    assert por[("correo", "Riesgo: Proveedor si")]["origen"] == "Capitán"
    assert por[("correo", "Contradicción a acla")]["prioridad"] == "fijo" and por[("correo", "Contradicción a acla")]["origen"] == "Auditor"
    assert por[("recordatorio", "Retomar: ¿Quién vali")]["estado"] == "propuesta"
    assert por[("recordatorio", "Cerrar el objetivo: ")]["texto"].endswith("Fijar fecha del piloto")   # solo el no cubierto
    assert len([a for a in s.acciones if a["tipo"] == "recordatorio"]) == 2


# ------------------------------------------------------------------ de punta a punta: revisión real con modelo falso
def test_revision_real_cambios_con_cita_acciones_y_cierre(tmp_path):
    from apuntes import correo_cierre as CC
    final = {"resumen": "Se acordó arrancar el piloto en enero.", "o": [], "cambios": [
        {"f": "02-alcance.md", "tipo": "anadir", "sec": "Cambios de alcance", "nuevo": "| 2026-11-06 | Piloto en enero | Cliente | Reunión |", "motivo": "Piloto", "m": "00:10",
         "q": "entonces el piloto arranca con dos hoteles en enero"},
        {"f": "02-alcance.md", "tipo": "anadir", "sec": "Cambios de alcance", "nuevo": "| 2026-11-06 | Algo inventado | Cliente | Reunión |", "motivo": "Sin cita", "m": "00:20",
         "q": "esta frase no se dijo nunca en la reunión de hoy"}]}
    modelo = ModeloFalso([("cierre de la reunión", final)])
    cli, gestor, cfg, g, bl, _m, eventos = montaje(tmp_path, modelo=modelo)
    (tmp_path / "proyectos" / PROYECTO / "00. CONTEXTO (IA)" / "02-alcance.md").write_text("# Alcance\n\n## Cambios de alcance\n\n| fecha | cambio | quien | fuente |\n|---|---|---|---|\n", encoding="utf-8")
    s = sesion_directa(gestor, g, objetivos=["Cerrar el alcance", "Fijar fecha del piloto"])
    s.agregar_segmento(10.0, "reunion", "Vale, entonces el piloto arranca con dos hoteles en enero y lo demás se verá después de las pruebas con el cliente.")
    s.agregar_segmento(20.0, "reunion", "Ana se encarga de enviar el catálogo antes del viernes para que podamos cerrar el alcance de la primera fase.")
    gestor.analista = Analista(modelo, cfg, gestor.consumo, g, s.id)
    gestor.digest = "Contexto."

    async def flujo():
        await gestor.terminar()
        for _ in range(200):
            if gestor.revision["estado"] in ("lista", "error"):
                break
            await asyncio.sleep(0.05)
        assert gestor.revision["estado"] == "lista", gestor.revision
        rev = gestor.revision
        c1, c2 = rev["cambios"]
        assert c1["valido"] and c1["preaceptado"] is True and c1["cita"]["minuto"] == "00:10" and "dos hoteles" in c1["cita"]["texto"]
        assert c2["valido"] and c2["preaceptado"] is False and c2["cita"] is None
        # la revisión pública lleva el formato de siempre más los campos nuevos
        assert gestor.revision_publica()["cambios"][0]["preaceptado"] is True
        # acciones locales de la revisión
        tipos = [(a["tipo"], a["estado"]) for a in s.acciones]
        assert tipos.count(("cambio_contexto", "propuesta")) == 2 and ("recordatorio", "propuesta") in tipos
        # el usuario acepta un pendiente y una entrada de correo; cierra la revisión
        p = gestor.acciones.crear("pendiente", "Enviar el catálogo", "Capitán", None, {"dueno": "Ana", "fecha": "viernes"})
        gestor.acciones.aceptar(p["id"])
        k = gestor.acciones.crear("correo", "Riesgo: depende del catálogo")
        gestor.acciones.aceptar(k["id"])
        assert "Riesgo: depende del catálogo" in gestor.revision_publica()["correo"]
        assert any(ev["tipo"] == "estado" and ev["revision"] and "Además" in (ev["revision"].get("correo") or "") for ev in eventos)
        await gestor.cerrar_revision(None)

    asyncio.run(flujo())
    assert gestor.estado == "inactivo"
    guardado = json.loads((tmp_path / "seguimiento" / "proyecto-ola-tres.json").read_text(encoding="utf-8"))
    assert [v["texto"] for v in guardado["aceptados"].values()] == ["Enviar el catálogo"] and list(guardado["aceptados"].values())[0]["dueno"] == "Ana"
