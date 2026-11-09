"""Eventos REALES de la orquestación: inicio y fin de cada tarea (agente, modelo, tramo, duración, tokens, resultado)
y traza por análisis. Con modelo falso; sin llamadas nuevas ni cambios en el reparto de modelos."""
import asyncio

from apuntes.analisis import ErrorAnalisis
from apuntes.orquesta import Sonda

from test_gestor import esperar, montaje  # noqa: F401  (fixture)

PROYECTO = "Proyecto Ficticio Alfa"


def tareas(eventos):
    return [e for e in eventos if e["tipo"] == "tarea"]


def test_cada_llamada_emite_inicio_y_fin_en_serie_con_el_modelo_real(montaje):
    gestor, llm, eventos, _, _ = montaje

    async def go():
        await gestor.iniciar(PROYECTO, "Seguimiento", 5)
        await esperar(lambda: len(gestor.sesion.segmentos) >= 40)
        assert (await gestor.analizar(manual=True))["ok"]
        await esperar(lambda: len(gestor.sesion.segmentos) >= 60)
        await gestor.terminar()
        await esperar(lambda: gestor.revision["estado"] == "lista")
        await gestor.cerrar_revision()

    asyncio.run(go())
    t = tareas(eventos)
    agentes = [(e["agente"], e["fase"]) for e in t]
    # cada tarea tiene un inicio y un fin, y nunca dos llamadas al LLM a la vez entre el análisis y el final
    assert sorted(set(a for a, _ in agentes)) == ["analista", "contexto", "redactor", "verificador"]
    for a in ("contexto", "analista", "verificador", "redactor"):
        assert agentes.count((a, "inicio")) == 1 and agentes.count((a, "fin")) == 1
    orden = [a for a, f in agentes if f == "inicio" and a in ("analista", "verificador", "redactor")]
    assert orden == ["analista", "verificador", "redactor"]
    fin = {e["agente"]: e for e in t if e["fase"] == "fin"}
    assert fin["analista"]["modelo"] == "haiku" and fin["verificador"]["modelo"] == "sonnet" and fin["redactor"]["modelo"] == "sonnet"
    assert fin["analista"]["ok"] is True and fin["analista"]["tokens"] == 120 and fin["analista"]["ms"] >= 0
    assert "–" in fin["analista"]["tramo"]            # tramo analizado (minuto inicial–final), dato real
    assert "tramo" not in fin["verificador"]          # lo que no aplica no se inventa
    assert len(llm.llamadas) == 4                      # el instrumento no añade llamadas al modelo


def test_un_fallo_emite_fin_con_error_y_traza_de_fallo(montaje):
    gestor, llm, eventos, _, _ = montaje

    async def go():
        await gestor.iniciar(PROYECTO, "Seguimiento", 5)
        await esperar(lambda: len(gestor.sesion.segmentos) >= 40 and gestor.digest_origen in ("generado", "cache", "error"))
        llm.error = ErrorAnalisis("limite", "Límite del plan.")
        r = await gestor.analizar(manual=True)
        assert not r["ok"]
        await gestor.terminar()
        await esperar(lambda: gestor.revision["estado"] in ("lista", "error"))

    asyncio.run(go())
    fin = [e for e in tareas(eventos) if e["fase"] == "fin" and e["agente"] == "analista"]
    assert fin and fin[-1]["ok"] is False and fin[-1]["clase"] == "limite"
    filas = [e for e in eventos if e["tipo"] == "traza"]
    assert filas[-1]["fila"] == "fallo" and filas[-1]["clase"] == "limite" and filas[-1]["bloqueante"] is True


def test_traza_por_analisis_y_omision(montaje):
    gestor, _, eventos, _, _ = montaje

    async def go():
        await gestor.iniciar(PROYECTO, "Seguimiento", 5)
        # el guion entero (60 líneas de 12 palabras, a 200x) ya entregado: si no, entra una línea más entre los dos análisis
        await esperar(lambda: gestor._sim_fin)
        assert (await gestor.analizar(manual=True))["ok"]
        r = await gestor.analizar(manual=True)       # sin palabras nuevas: omitido, y no llama al modelo
        assert r.get("omitido")
        snap = gestor.snapshot()
        await gestor.terminar()
        await esperar(lambda: gestor.revision["estado"] in ("lista", "error"))
        return snap

    snap = asyncio.run(go())
    filas = [e for e in eventos if e["tipo"] == "traza"]
    assert [f["fila"] for f in filas] == ["analisis", "omitido"]
    a = filas[0]
    assert a["n"] == 1 and a["modelo"] == "haiku" and a["tokens"] == 120 and a["insights"] == 3   # 2 tarjetas + 1 posible contradicción
    assert a["hasta_id"] and "tramo" in a and a["hasta_t"] is not None
    assert filas[1]["palabras"] == 0 and filas[1]["minimo"] >= 20
    # el snapshot (reconexión) lleva tareas y traza; y las palabras nuevas desde el último análisis
    assert snap["traza"] and snap["tareas"] and snap["analisis"]["palabras"] is not None


def test_sonda_transcripcion_registra_tramos_locales():
    eventos = []
    s = Sonda(eventos.append)
    s.transcripcion("inicio", 1, fuente="yo", audio_s=3.2)
    assert eventos[-1]["agente"] == "transcriptor" and eventos[-1]["modelo"] == "local" and eventos[-1]["estado"] == "en_curso"
    s.transcripcion("fin", 1, ok=True, ms=900, palabras=12)
    e = eventos[-1]
    assert e["fase"] == "fin" and e["ok"] is True and e["ms"] == 900 and e["palabras"] == 12 and e["id"] == "w1"
    assert s.publico()["tareas"][0]["id"] == "w1"
    s.transcripcion("inicio", 2, fuente="reunion", audio_s=1.0)
    s.transcripcion("fin", 2, ok=False, error="fallo", ms=10)
    assert eventos[-1]["ok"] is False and eventos[-1]["error"] == "fallo"
