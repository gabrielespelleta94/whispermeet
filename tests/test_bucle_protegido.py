"""El bucle de la grabación (Gestor._bucle) no puede morir en silencio: cada parte de la pasada (Monitor, turno, tick, análisis periódico)
está protegida por separado, el fallo va a datos\\apuntes.log y al .md de la sesión, se avisa una vez (sin spam) y se avisa de la recuperación.
Excepciones inyectadas, modelo falso, sin red ni audio."""
import asyncio
import time

import pytest

from apuntes import gestor as G
from apuntes import registro
from test_equipo import RELLENO, arrancar, dice, esperar, montaje, run, tic  # noqa: F401  (montaje es un fixture)


def avisos_de_fallo(eventos):
    return [e for e in eventos if e["tipo"] == "aviso" and not e.get("recuperado")]


def avisos_de_recuperacion(eventos):
    return [e for e in eventos if e["tipo"] == "aviso" and e.get("recuperado")]


async def pasada_fallida(gestor, t):
    """Una pasada del Monitor a la hora `t` de la reunión (la cadencia del Monitor se salta, como en `tic`)."""
    gestor.reloj.fijar(t)
    gestor.equipo._ultima_comprobacion = -1e9
    await gestor._vigilar()


def test_si_monitor_pasada_falla_a_mitad_de_reunion_los_turnos_automaticos_se_reanudan(montaje):
    gestor, llm, eventos, _ = montaje

    async def go():
        await arrancar(gestor)
        dice(gestor, 5, "Para el viernes se encarga Ana de enviar el fichero. " + RELLENO)
        reales = gestor.equipo.monitor.pasada

        def rota(*a, **k):
            raise RuntimeError("pasada rota")

        gestor.equipo.monitor.pasada = rota
        llamadas_antes = len(llm.llamadas)
        await pasada_fallida(gestor, 250)
        assert gestor.equipo.n_turnos == 0 and gestor.equipo.en_curso is None
        assert len(llm.llamadas) == llamadas_antes, "un fallo del Monitor no puede provocar llamadas nuevas al modelo"
        assert gestor.estado == "grabando"
        dice(gestor, 260, "La grabación sigue recibiendo texto después del fallo.")
        assert any("después del fallo" in x.texto for x in gestor.sesion.segmentos)
        assert "RuntimeError" in registro.RUTA_LOG.read_text(encoding="utf-8") and "File " in registro.RUTA_LOG.read_text(encoding="utf-8") and ": pasada rota" not in registro.RUTA_LOG.read_text(encoding="utf-8")
        assert G.TEXTO_FALLO in gestor.avisos and gestor.snapshot()["avisos"].count(G.TEXTO_FALLO) == 1

        del gestor.equipo.monitor.pasada                      # el fallo desaparece: vuelve la pasada real
        assert gestor.equipo.monitor.pasada == reales
        await tic(gestor, 270)
        assert gestor.equipo.n_turnos == 1, "los turnos automáticos no se reanudaron"
        assert G.TEXTO_FALLO not in gestor.avisos and G.TEXTO_RECUPERADO in gestor.avisos
        assert len(avisos_de_recuperacion(eventos)) == 1
    run(go())


def test_aviso_una_sola_vez_y_luego_recuperacion_con_linea_en_el_md_sin_traza(montaje):
    gestor, llm, eventos, _ = montaje

    async def go():
        await arrancar(gestor, cadencia="5")
        eq = gestor.equipo
        reales = eq.comprobar
        eq.comprobar = lambda *a, **k: (_ for _ in ()).throw(ValueError("secreto de la reunión"))
        for i in range(5):                                     # cinco pasadas seguidas rotas en menos de 5 min
            await pasada_fallida(gestor, 100 + i * 5)
        malos = avisos_de_fallo(eventos)
        assert len(malos) == 1 and malos[0]["mensaje"] == G.TEXTO_FALLO and malos[0]["componente"] == "monitor" and not malos[0]["grave"]
        assert gestor.avisos.count(G.TEXTO_FALLO) == 1
        assert gestor.snapshot()["avisos"].count(G.TEXTO_FALLO) == 1
        eq.comprobar = reales
        await pasada_fallida(gestor, 130)
        await pasada_fallida(gestor, 135)
        assert len(avisos_de_recuperacion(eventos)) == 1 and avisos_de_recuperacion(eventos)[0]["mensaje"] == G.TEXTO_RECUPERADO
        assert G.TEXTO_RECUPERADO in gestor.avisos and G.TEXTO_FALLO not in gestor.avisos
        assert len(avisos_de_fallo(eventos)) == 1
        # una línea con minuto por incidencia y sin traza ni mensaje de la excepción
        assert gestor.sesion.incidencias[0] == "[01:40] monitor: ValueError" and gestor.sesion.incidencias[-1].endswith("monitor: recuperado")
        md = gestor.sesion.ruta.read_text(encoding="utf-8")
        assert "## Incidencias del análisis automático" in md and "- [01:40] monitor: ValueError" in md
        assert "Traceback" not in md and "secreto de la reunión" not in md
    run(go())


def test_tras_cinco_minutos_vuelve_a_avisar_y_a_n_pasadas_seguidas_lo_dice_claramente(montaje):
    gestor, llm, eventos, _ = montaje

    async def go():
        await arrancar(gestor, cadencia="5")
        eq = gestor.equipo
        eq.comprobar = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("siempre roto"))
        for i in range(G.FALLOS_SEGUIDOS_GRAVE + 2):           # supera N pasadas seguidas, pero dentro de los 5 min: solo el primer aviso
            await pasada_fallida(gestor, 100 + i)
        assert [e["mensaje"] for e in avisos_de_fallo(eventos)] == [G.TEXTO_FALLO]
        gestor._salud["monitor"]["ultimo_aviso"] -= G.AVISO_FALLO_CADA_S + 1     # pasan 5 min
        await pasada_fallida(gestor, 200)
        malos = avisos_de_fallo(eventos)
        assert len(malos) == 2 and malos[1]["grave"] and "Analizar ahora" in malos[1]["mensaje"]
        assert gestor.avisos.count(malos[1]["mensaje"]) == 1 and G.TEXTO_FALLO not in gestor.avisos      # sustituye, no se acumula
        assert gestor.estado == "grabando"                    # y se sigue intentando: la siguiente pasada vuelve a llamar al Monitor
        llamadas = []
        eq.comprobar = lambda *a, **k: llamadas.append(a) or (_ for _ in ()).throw(RuntimeError("siempre roto"))
        await pasada_fallida(gestor, 210)
        assert len(llamadas) == 1
        assert "pasadas seguidas" in gestor.sesion.incidencias[-1]
    run(go())


def test_el_hilo_termina_al_parar_aunque_todo_falle(montaje):
    gestor, llm, eventos, _ = montaje

    async def go():
        await gestor.iniciar(None, "Tema", "5")
        bucle = [t for t in gestor._tareas if "_bucle" in repr(t)][0]

        def roto(*a, **k):
            raise RuntimeError("roto")

        gestor.equipo.comprobar = roto
        gestor._emitir_tick = roto
        gestor._disparar_periodico = roto
        await asyncio.sleep(1.5)
        assert not bucle.done(), "el bucle murió por un fallo"
        gestor.estado = "terminando"                          # la reunión acaba: la señal de parada no se captura
        await asyncio.wait_for(bucle, timeout=3)
        assert bucle.done() and not bucle.cancelled() and bucle.exception() is None
        for t in gestor._tareas:
            t.cancel()
        gestor.apagar()
    run(go())


def test_cancelar_el_bucle_lo_cancela_de_verdad(montaje):
    gestor, *_ = montaje

    async def go():
        await gestor.iniciar(None, "Tema", "5")
        bucle = [t for t in gestor._tareas if "_bucle" in repr(t)][0]
        await asyncio.sleep(0.2)
        bucle.cancel()
        with pytest.raises(asyncio.CancelledError):
            await bucle
        assert bucle.cancelled()
        for t in gestor._tareas:
            t.cancel()
        gestor.apagar()
    run(go())


def test_el_fallo_de_un_componente_no_bloquea_al_otro(montaje):
    gestor, llm, eventos, _ = montaje

    async def go():
        await gestor.iniciar(None, "Tema", "5")
        eq = gestor.equipo
        vistas = {"comprobar": 0, "analisis": 0}
        reales_tick = gestor._emitir_tick

        def monitor_roto(*a, **k):
            vistas["comprobar"] += 1
            raise RuntimeError("monitor roto")

        async def analizar_falso(manual=False, motivo=""):
            vistas["analisis"] += 1

        # 1) el Monitor falla: el tick y el análisis periódico siguen funcionando
        eq.comprobar = monitor_roto
        eq._ultima_comprobacion = -1e9
        gestor.analizar = analizar_falso
        gestor._toca_analizar = lambda: "cada 5 min"
        n_ticks = len([e for e in eventos if e["tipo"] == "tick"])
        await asyncio.sleep(2.3)
        assert vistas["comprobar"] >= 1
        assert len([e for e in eventos if e["tipo"] == "tick"]) > n_ticks, "el tick se paró por el fallo del Monitor"
        assert vistas["analisis"] >= 1, "el análisis periódico se paró por el fallo del Monitor"

        # 2) el tick falla: el Monitor sigue (se le fuerza a tocar en cada pasada) y el análisis también
        eq.comprobar = lambda *a, **k: vistas.__setitem__("comprobar", vistas["comprobar"] + 1) or None
        gestor._emitir_tick = lambda: (_ for _ in ()).throw(RuntimeError("tick roto"))
        comprobar0, analisis0 = vistas["comprobar"], vistas["analisis"]
        eq._ultima_comprobacion = -1e9
        await asyncio.sleep(2.3)
        assert vistas["comprobar"] > comprobar0 and vistas["analisis"] > analisis0
        assert {"tick", "monitor"} <= set(gestor._salud)
        assert "RuntimeError" in registro.RUTA_LOG.read_text(encoding="utf-8") and ": tick roto" not in registro.RUTA_LOG.read_text(encoding="utf-8")
        gestor._emitir_tick = reales_tick
        assert not [t for t in gestor._tareas if "_bucle" in repr(t)][0].done()
        for t in gestor._tareas:
            t.cancel()
        gestor.apagar()
    run(go())


def test_un_turno_que_revienta_no_se_pierde_y_se_avisa(montaje):
    gestor, llm, eventos, _ = montaje

    async def go():
        await arrancar(gestor)

        async def turno_roto():
            raise RuntimeError("turno roto")

        gestor._lanzar("turno", turno_roto())
        await esperar(lambda: any(e["tipo"] == "aviso" for e in eventos), 3)
        assert G.TEXTO_FALLO in gestor.avisos and ": turno roto" not in registro.RUTA_LOG.read_text(encoding="utf-8")

        async def turno_bueno():
            return {"ok": True}

        gestor._lanzar("turno", turno_bueno())
        await esperar(lambda: avisos_de_recuperacion(eventos), 3)
        assert G.TEXTO_RECUPERADO in gestor.avisos
    run(go())


def test_sin_sesion_activa_un_fallo_no_avisa_ni_rompe(montaje):
    gestor, *_ = montaje
    gestor._fallo("monitor", RuntimeError("x"))               # estado inactivo, sin sesión: solo el log, sin excepción
    assert gestor.avisos == [] and gestor._salud == {}
