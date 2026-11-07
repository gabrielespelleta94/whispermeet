"""«Esto está mal» (ola 4): reglas locales de silencio para el Monitor y las tarjetas, guardadas en la carpeta local de datos vía Guardian."""
import json
from types import SimpleNamespace

import pytest

from apuntes.equipo.monitor import Monitor
from apuntes.rutas import Guardian
from apuntes.silencio import ReglasSilencio, equivalentes, normalizar_clave
from ola4_utils import PROYECTO, cliente, esperar, montar


def _g(tmp_path):
    return Guardian(tmp_path / "r", tmp_path / "b", tmp_path / "c", datos=tmp_path / "datos")


def seg(i, t, texto):
    return SimpleNamespace(id=i, t=t, texto=texto)


# ------------------------------------------------------------------ las reglas
def test_la_clave_se_normaliza_y_lo_equivalente_se_reconoce():
    assert normalizar_clave("  ¡El Plazo,   del Piloto!  ") == "el plazo del piloto"
    assert equivalentes("el plazo del piloto", "el plazo del piloto")
    assert equivalentes("revisar la integración con el sistema de reservas", "revisar la integracion con el sistema de reservas ahora")
    assert not equivalentes("el plazo del piloto", "la tarifa del grupo")
    assert not equivalentes("", "algo")


def test_alta_listado_borrado_y_persistencia(tmp_path):
    g = _g(tmp_path)
    rs = ReglasSilencio(g)
    r = rs.anadir("senal:fecha", "para el viernes que viene", "señal: fecha · «para el viernes que viene»", "ses1")
    assert r["nueva"] is True and r["tipo"] == "senal:fecha" and r["clave"] == "para el viernes que viene" and r["sesion"] == "ses1" and len(r["id"]) == 12
    assert rs.anadir("senal:fecha", "Para el viernes, que viene")["nueva"] is False                    # equivalente: no se duplica
    assert rs.anadir("senal:riesgo", "para el viernes que viene")["nueva"] is True                      # otro tipo, otra regla
    assert [x["tipo"] for x in rs.listar()] == ["senal:fecha", "senal:riesgo"]
    # persiste en la carpeta de datos y otra instancia (otra ejecución) la lee
    crudo = json.loads(g.leer_datos("reglas-silencio.json"))
    assert len(crudo) == 2
    assert ReglasSilencio(g).silenciado("senal:fecha", "para el viernes que viene") is True
    assert rs.borrar(r["id"]) is True and rs.borrar(r["id"]) is False
    assert ReglasSilencio(g).silenciado("senal:fecha", "para el viernes que viene") is False


def test_validaciones_y_sin_carpeta_de_datos(tmp_path):
    rs = ReglasSilencio(_g(tmp_path))
    with pytest.raises(ValueError):
        rs.anadir("inventado", "texto")
    with pytest.raises(ValueError):
        rs.anadir("senal:fecha", "   ")
    sin = ReglasSilencio(Guardian(tmp_path / "r", tmp_path / "b", tmp_path / "c"))
    assert sin.listar() == [] and sin.silenciado("senal:fecha", "x") is False
    with pytest.raises(ValueError):
        sin.anadir("senal:fecha", "algo")


def test_un_json_roto_no_bloquea(tmp_path):
    g = _g(tmp_path)
    g.escribir_datos("reglas-silencio.json", "{ esto no es json")
    rs = ReglasSilencio(g)
    assert rs.listar() == [] and rs.anadir("silencio", "")["nueva"] is True


def test_la_regla_de_silencio_es_de_tipo_no_de_texto(tmp_path):
    rs = ReglasSilencio(_g(tmp_path))
    rs.anadir("silencio", "lo que sea")
    assert rs.silenciado("silencio", "otro texto distinto") is True


# ------------------------------------------------------------------ el Monitor las consulta
TEXTO = "Quedamos en que para el viernes que viene hay que tener la lista de hoteles cerrada."


def _pasada(mon, ahora=40.0, texto=TEXTO):
    return mon.pasada(ahora, [seg(1, 20.0, texto)], [], [])


def test_el_monitor_sin_reglas_emite_las_senales_como_siempre():
    mon = Monitor()
    p = _pasada(mon)
    senales = [e for e in p.entradas if e["tipo"] == "senal"]
    assert senales and all(e["regla_tipo"].startswith("senal:") and e["regla_texto"] for e in senales)       # cada entrada dice con qué regla se silenciaría


def test_el_monitor_no_vuelve_a_emitir_un_aviso_marcado_como_mal(tmp_path):
    rs = ReglasSilencio(_g(tmp_path))
    mon = Monitor()
    mon.filtro_silencio = rs.silenciado
    e = next(x for x in _pasada(mon).entradas if x["tipo"] == "senal")
    rs.anadir(e["regla_tipo"], e["regla_texto"])
    mon2 = Monitor()
    mon2.filtro_silencio = rs.silenciado
    p2 = _pasada(mon2)
    assert not [x for x in p2.entradas if x["tipo"] == "senal" and x["regla_tipo"] == e["regla_tipo"] and x["regla_texto"] == e["regla_texto"]]
    # un aviso equivalente (otro minuto, misma frase) tampoco; otro tipo de señal o otra frase, sí
    p3 = mon2.pasada(400.0, [seg(2, 380.0, TEXTO.replace("hoteles", "hoteles pilotos"))], [], [])
    assert not [x for x in p3.entradas if x["tipo"] == "senal" and x["regla_tipo"] == e["regla_tipo"] and "viernes" in x["regla_texto"]]
    p4 = mon2.pasada(800.0, [seg(3, 780.0, "Hay un riesgo claro con el proveedor de pagos que puede retrasar todo el proyecto.")], [], [])
    assert [x for x in p4.entradas if x["tipo"] == "senal"]


def test_las_puntuaciones_siguen_aunque_el_aviso_este_silenciado(tmp_path):
    rs = ReglasSilencio(_g(tmp_path))
    mon = Monitor()
    mon.filtro_silencio = lambda t, x: True          # silencia TODO aviso
    p = _pasada(mon)
    assert not [e for e in p.entradas if e["tipo"] == "senal"] and p.tipos          # no hay avisos pero el Monitor sigue viendo las señales
    assert sum(mon.puntos.values()) > 0


def test_se_silencian_toca_sin_tratar_silencio_y_definicion():
    mon = Monitor({"equipo_objetivo_sin_tratar_min": 1})
    mon.filtro_silencio = lambda tipo, texto: tipo in ("toca", "sin_tratar", "silencio", "definicion")
    objs = [{"n": 1, "texto": "Cerrar el calendario de disponibilidad", "estado": "sin_tratar"}]
    p = mon.pasada(900.0, [seg(1, 880.0, "Hablamos del calendario de disponibilidad. Entonces definimos Cupo como el máximo de habitaciones por grupo.")], objs, [])
    tipos = {e["tipo"] for e in p.entradas}
    assert p.toca == [1] and not (tipos & {"toca", "sin_tratar", "definicion"})
    assert mon.locales and mon.locales[0]["termino"] == "Cupo"                      # la definición sigue detectada; solo se calla el aviso
    assert mon.silencio(2000.0, 80) is None


def test_los_avisos_normales_llevan_la_regla_para_silenciarlos():
    mon = Monitor({"equipo_objetivo_sin_tratar_min": 1})
    objs = [{"n": 1, "texto": "Cerrar el calendario de disponibilidad", "estado": "sin_tratar"}]
    p = mon.pasada(900.0, [seg(1, 880.0, "Hablamos del calendario de disponibilidad con calma.")], objs, [])
    toca = next(e for e in p.entradas if e["tipo"] == "toca")
    assert toca["regla_tipo"] == "toca" and toca["regla_texto"] == "Cerrar el calendario de disponibilidad"
    e = mon.silencio(2000.0, 80)
    assert e["regla_tipo"] == "silencio"


# ------------------------------------------------------------------ endpoints y tarjetas
def _sesion_con_avisos(cli, gestor):
    r = cli.post("/api/sesion/iniciar", json={"proyecto": PROYECTO, "tema": "Seguimiento", "cadencia": "equipo", "objetivos": ["Cerrar el calendario"]})
    assert r.status_code == 200, r.text
    esperar(lambda: len(cli.get("/api/sesion").json()["segmentos"]) >= 30)
    gestor.equipo._ultima_comprobacion = -1e9
    esperar(lambda: gestor.equipo.monitor.feed, 20)


def test_endpoint_mal_sobre_un_aviso_del_monitor(tmp_path):
    gestor, llm, eventos, g, cfg = montar(tmp_path, simulacion=[])
    cli = cliente(gestor, cfg, g)
    with cli:
        cli.post("/api/sesion/iniciar", json={"proyecto": PROYECTO, "tema": "Seguimiento", "cadencia": "manual"})
        gestor.equipo.monitor.pasada(gestor.reloj.ahora() + 100, [seg(1, 20.0, TEXTO)], [], [])      # el Monitor ve la frase (a mano: sin carreras con el bucle)
        e = next(x for x in gestor.equipo.monitor.feed if x["tipo"] == "senal")
        r = cli.post(f"/api/avisos/{e['id']}/mal", json={"motivo": "no es una fecha"})
        assert r.status_code == 200, r.text
        regla = r.json()["regla"]
        assert r.json()["origen"] == "monitor" and regla["nueva"] is True and regla["tipo"] == e["regla_tipo"] and regla["sesion"] == gestor.sesion.id
        assert e["silenciado"] is True and any(ev.get("tipo") == "aviso_silenciado" and ev["id"] == e["id"] for ev in eventos)
        # el Monitor ya no lo vuelve a emitir (misma frase en otra pasada)
        gestor.equipo.monitor.pasada(gestor.reloj.ahora() + 400, [seg(99, gestor.reloj.ahora() + 380, TEXTO)], [], [])
        nuevas = [x for x in gestor.equipo.monitor.feed if x["id"] != e["id"] and x["tipo"] == "senal" and x["regla_tipo"] == e["regla_tipo"] and "viernes" in x["regla_texto"]]
        assert not nuevas
        # listado y borrado
        lista = cli.get("/api/reglas-silencio").json()
        assert lista["total"] == 1 and lista["reglas"][0]["id"] == regla["id"]
        assert cli.delete(f"/api/reglas-silencio/{regla['id']}").json()["ok"] is True
        assert cli.get("/api/reglas-silencio").json()["total"] == 0
        assert cli.delete(f"/api/reglas-silencio/{regla['id']}").status_code == 404
        assert cli.delete("/api/reglas-silencio/../x").status_code in (400, 404, 405)
        # ids que no son silenciables
        assert cli.post("/api/avisos/m99999/mal").status_code == 404
        assert cli.post("/api/avisos/c1/mal").status_code == 400
        assert cli.post("/api/avisos/loquesea/mal").status_code == 400


def test_endpoint_mal_sobre_una_tarjeta_y_el_gestor_no_la_vuelve_a_emitir(tmp_path):
    gestor, llm, eventos, g, cfg = montar(tmp_path)
    cli = cliente(gestor, cfg, g)
    with cli:
        cli.post("/api/sesion/iniciar", json={"proyecto": PROYECTO, "tema": "Seguimiento", "cadencia": 5})
        esperar(lambda: len(cli.get("/api/sesion").json()["segmentos"]) >= 55)
        assert cli.post("/api/sesion/analizar").json()["ok"]
        tarjetas = cli.get("/api/sesion").json()["tarjetas"]
        pend = next(t for t in tarjetas if t["categoria"] == "pendiente")
        r = cli.post(f"/api/avisos/{pend['id']}/mal")
        assert r.status_code == 200 and r.json()["origen"] == "tarjeta" and r.json()["regla"]["tipo"] == "tarjeta:pendiente"
        assert next(t for t in gestor.sesion.tarjetas if t["id"] == pend["id"])["mal"] is True
        n = len(gestor.sesion.tarjetas)
        # un segundo análisis devuelve de nuevo ese mismo pendiente: ya no sale
        gestor.sesion.ultimo_analizado_id = 0
        assert cli.post("/api/sesion/analizar").json()["ok"]
        assert not [t for t in gestor.sesion.tarjetas[n:] if t["categoria"] == "pendiente" and "SAP" in t["texto"]]
        assert any(t["categoria"] == "decisión" for t in gestor.sesion.tarjetas[n:]) or len(gestor.sesion.tarjetas) >= n


def test_sin_reunion_o_sin_datos_el_endpoint_responde_con_un_error_claro(tmp_path):
    gestor, llm, eventos, g, cfg = montar(tmp_path, datos=False)
    cli = cliente(gestor, cfg, g)
    with cli:
        assert cli.post("/api/avisos/m1/mal").status_code == 400            # sin reunión
        assert cli.get("/api/reglas-silencio").json() == {"reglas": [], "total": 0}
