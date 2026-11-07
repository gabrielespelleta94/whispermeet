"""Cobertura del resumen final: qué leyó cada análisis, qué recibe el cierre (la MISMA llamada de sonnet), el recorte repartido entre todos los
tramos y los avisos locales sobre el resumen. Transcripciones SINTÉTICAS y modelo falso: ni tokens ni contenido de reuniones reales."""
import asyncio
import json
import shutil
from pathlib import Path

import pytest

from apuntes import cobertura as CB
from apuntes.analisis import ModeloLLM, Respuesta, Uso
from apuntes.config import Config
from apuntes.consumo import Consumo
from apuntes.gestor import Gestor
from apuntes.rutas import Guardian
from apuntes.sesion import Sesion
from apuntes.simulador import LineaSim
from apuntes.texto import limpiar_transcripcion, mmss

PRUEBAS = Path(__file__).resolve().parent.parent / "pruebas" / "proyectos"


def sesion_con(n=40, cada=30.0, largo=8):
    """n segmentos de Reunión, uno cada `cada` segundos (más de 20: no se unen en una línea), con palabras únicas (nada es eco ni duplicado)."""
    s = Sesion(None, "t", 5, Path("x.md"))
    for i in range(n):
        s.agregar_segmento(i * cada, "reunion", " ".join(f"palabra{i}n{j}" for j in range(largo)))
    return s


# ------------------------------------------------------------------ registro por análisis
def test_registrar_lectura_marca_lo_leido_y_deja_lo_recortado_sin_cubrir():
    s = sesion_con(10)
    lineas = limpiar_transcripcion(s.estables(0))
    assert len(lineas) == 10 and all(l.ids for l in lineas)
    e = CB.registrar_lectura(s, 1, "funcional", lineas, [0, 1, 2, 8, 9])
    assert e["leidas"] == 5 and e["lineas"] == 10
    assert e["omitidas"] == [[90.0, 210.0]]                       # un solo tramo recortado: las líneas 3 a 7
    assert s.cubiertos == {1, 2, 3, 9, 10}
    assert s.cobertura == [e]


def test_el_analisis_periodico_lo_lee_todo():
    s = sesion_con(6)
    CB.registrar_lectura(s, 1, "periodico", limpiar_transcripcion(s.estables(0)))
    assert s.cubiertos == {1, 2, 3, 4, 5, 6} and s.cobertura[0]["omitidas"] == []


# ------------------------------------------------------------------ lo que recibe el cierre
def test_el_cierre_recibe_lo_no_cubierto_con_inicio_y_fin_de_cada_tramo_y_nada_de_lo_cubierto():
    s = sesion_con(30)
    lineas = limpiar_transcripcion(s.estables(0))
    CB.registrar_lectura(s, 1, "funcional", lineas, list(range(0, 10)) + list(range(20, 30)))     # quedan sin leer los segmentos 11 a 20
    s.ultimo_analizado_id = 30
    c = CB.preparar_cierre(s, 6000, 20000)
    assert c.tramo == "" and len(c.no_cubierto) == 1 and c.omitidos == []
    assert c.no_cubierto[0] == (300.0, 570.0)
    assert c.huecos.startswith("Tramo 1 de 1, desde 05:00 hasta 09:30 (minutos de la reunión; el inicio y el fin de cada tramo están incluidos):")
    assert "palabra10n0" in c.huecos and "palabra19n7" in c.huecos
    assert "palabra9n0" not in c.huecos and "palabra20n0" not in c.huecos          # lo ya leído no se repite
    assert c.ids_entregados == set(range(11, 21))


def test_lo_pendiente_viaja_como_tramo_con_inicio_y_fin_y_lo_que_no_cabe_pasa_a_los_no_cubiertos():
    s = sesion_con(12)
    s.ultimo_analizado_id = 0                                      # nadie ha analizado nada
    c = CB.preparar_cierre(s, 600, 20000)                          # el tramo pendiente solo admite unas pocas líneas
    assert c.tramo.startswith("Tramo pendiente, desde ")
    assert c.tramo.endswith("palabra11n7") and "palabra0n0" not in c.tramo
    assert "palabra0n0" in c.huecos                                # lo que no cupo en el pendiente va en los no cubiertos, nunca se pierde
    for i in range(12):                                            # y cada segmento viaja una sola vez
        assert (c.tramo + c.huecos).count(f"palabra{i}n0 ") == 1


def test_si_hay_que_recortar_el_recorte_se_reparte_entre_todos_los_tramos_no_solo_el_ultimo():
    s = sesion_con(60, largo=12)
    lineas = limpiar_transcripcion(s.estables(0))
    # tres tramos sin leer de 10 segmentos cada uno (índices 5-14, 25-34 y 45-54), separados por tramos leídos
    leidos = list(range(0, 5)) + list(range(15, 25)) + list(range(35, 45)) + list(range(55, 60))
    CB.registrar_lectura(s, 1, "funcional", lineas, leidos)
    s.ultimo_analizado_id = 60
    entero = CB.preparar_cierre(s, 6000, 50000)
    assert len(entero.no_cubierto) == 3 and not entero.omitidos
    tope = int(len(entero.huecos) * 0.5)
    c = CB.preparar_cierre(s, 6000, tope)
    assert len(c.no_cubierto) == 3 and len(c.omitidos) == 3        # los TRES tramos pierden líneas, no solo el último
    assert len(c.huecos) <= tope + 3 * 200                         # y el total respeta el tope (más la cabecera y la marca de cada tramo)
    for tramo in c.huecos.split("\n\n"):
        assert "recortado por espacio" in tramo.splitlines()[0] and "líneas omitidas por falta de espacio" in tramo
        assert tramo.splitlines()[1].startswith("[") and tramo.splitlines()[-1].startswith("[")    # se conservan el principio y el final de cada tramo
    sin_leer = [(150.0, 420.0), (750.0, 1020.0), (1350.0, 1620.0)]
    for a, b in c.omitidos:                                         # lo que queda fuera se declara con sus minutos y es siempre de un tramo sin leer
        assert a <= b and any(x <= a and b <= y for x, y in sin_leer)
    assert {i for i in c.ids_entregados} < set(range(1, 61)) and len(c.ids_entregados) > 3 * 2


def test_un_tramo_pequeno_no_se_queda_sin_nada_al_repartir():
    rep = CB._repartir([100, 100, 10_000], 5_000)
    assert rep[0] == 100 and rep[1] == 100 and rep[2] < 5_000
    rep = CB._repartir([4_000, 4_000, 4_000], 6_000)
    assert max(rep) - min(rep) <= 1 and sum(rep) <= 6_000                 # reparto igual si son iguales
    assert CB._repartir([10, 20], 1_000) == [10, 20]


# ------------------------------------------------------------------ comprobación local del resumen
def test_afirmaciones_de_falta_de_contenido_con_sus_minutos():
    texto = ("Se acordó revisar el calendario.\n**Nota**\nEl resumen acumulado solo recoge dos tramos (hasta 05:00). "
             "No hay contenido registrado entre 10:00 y 20:00, ni transcripción pendiente.\nNo constan decisiones formales.")
    f = CB.afirmaciones_de_falta(texto)
    assert [x[1] for x in f] == [(300.0, 300.0), (600.0, 1200.0)]
    assert CB.afirmaciones_de_falta("Se decidió cerrar el contrato. No se han registrado pendientes.") == []      # decir que no hubo pendientes no es falta de contenido


def test_avisos_cuentan_las_lineas_que_si_se_hablaron_en_el_tramo_que_el_resumen_da_por_vacio():
    s = sesion_con(30)          # segmentos cada 30 s: de 00:00 a 14:30
    a = CB.avisos("No hay contenido registrado entre 05:00 y 09:00.", None, s)
    assert len(a) == 1 and "05:00 y 09:00" in a[0] and "9 líneas" in a[0] and "SÍ se habló" in a[0]
    assert CB.avisos("Resumen normal sin quejas. No se han registrado pendientes.", None, s) == []


def test_avisos_de_cobertura_incompleta_con_los_minutos_que_quedaron_fuera():
    s = sesion_con(60, largo=12)
    CB.registrar_lectura(s, 1, "funcional", limpiar_transcripcion(s.estables(0)), list(range(0, 5)))
    s.ultimo_analizado_id = 60
    c = CB.preparar_cierre(s, 6000, 3000)
    assert c.omitidos
    a = CB.avisos("Resumen que no dice nada raro.", c, s)
    assert len(a) == 1 and a[0].startswith("Cobertura incompleta") and mmss(c.omitidos[0][0]) in a[0] and mmss(c.omitidos[0][1]) in a[0]


# ------------------------------------------------------------------ el .md
def test_el_md_no_repite_el_titulo_del_resumen_y_lleva_el_aviso():
    s = sesion_con(3)
    s.resumen_final = "## Resumen de la reunión (01:00)\n\nTodo bien."
    s.avisos_resumen = ["Cobertura incompleta: 02:00–03:00."]
    md = s.render()
    assert md.count("## Resumen") == 1 and "## Resumen de la reunión (01:00)" in md
    assert "## Aviso sobre el resumen\n\n- Cobertura incompleta: 02:00–03:00." in md
    s.resumen_final = "Texto sin título propio."
    assert "## Resumen\n\nTexto sin título propio." in s.render()
    s.resumen_final, s.avisos_resumen = "## Resumen\nCon título propio.", []
    md = s.render()
    assert md.count("## Resumen") == 1 and "## Aviso" not in md


# ------------------------------------------------------------------ flujo completo con el gestor y un modelo falso
class FalsoCierre(ModeloLLM):
    def __init__(self, resumen_final="Resumen final de sonnet."):
        self.llamadas = []
        self.resumen_final = resumen_final

    def completar(self, sistema, usuario, modelo, esfuerzo="", timeout_s=240, sin_razonamiento=False):
        self.llamadas.append((sistema, usuario, modelo))
        uso = [Uso(modelo, 100, 20)]
        if "compañero del equipo" in sistema:
            r = {"d": [], "t": [], "e": "Tema del tramo"}
        elif "análisis incremental" in sistema:
            r = {"resumen": "Se habló de varias cosas.", "t": [], "c": []}
        elif "cierre de la reunión" in sistema:
            r = {"resumen": self.resumen_final, "cambios": []}
        else:
            raise AssertionError("prompt inesperado")
        return Respuesta(json.dumps(r), uso, 10)


@pytest.fixture
def montaje(tmp_path):
    raiz = tmp_path / "proyectos"
    shutil.copytree(PRUEBAS, raiz)
    g = Guardian(raiz, tmp_path / "bandeja", tmp_path / "cache")
    cfg = Config(tmp_path / "config.json")
    cfg.actualizar({"raiz_proyectos": str(raiz), "knowledge": "", "equipo_chars_nuevo": 700}, guardar=False)
    llm = FalsoCierre()
    gestor = Gestor(cfg, g, Consumo(None), llm, lambda e: None, simulacion=[LineaSim(9999.0, "yo", "fin")], velocidad=1)
    return gestor, llm, tmp_path


async def arrancar(gestor, cadencia="equipo"):
    await gestor.iniciar(None, "Tema", cadencia)
    for t in list(gestor._tareas):
        t.cancel()
    gestor.reloj.fijar(0)


async def cerrar(gestor, fin_s):
    gestor.reloj.fijar(fin_s)
    await gestor.terminar()
    for _ in range(400):
        if gestor.revision["estado"] in ("lista", "error"):
            break
        await asyncio.sleep(0.05)
    assert gestor.revision["estado"] == "lista", gestor.revision


def test_un_turno_con_tope_deja_lo_recortado_sin_cubrir_y_el_cierre_lo_recibe_en_UNA_llamada(montaje):
    gestor, llm, _ = montaje

    async def go():
        await arrancar(gestor)
        for i in range(30):
            gestor._agregar(i * 30.0, "reunion", " ".join(f"termino{i}n{j}" for j in range(15)))
        gestor.reloj.fijar(900)
        r = await gestor.equipo.turno("funcional", "señales", manual=True)
        assert r["ok"], r
        s = gestor.sesion
        c = s.cobertura[0]
        assert c["perfil"] == "funcional" and c["leidas"] < c["lineas"] and c["omitidas"]            # el tope recortó parte de lo nuevo
        assert s.ultimo_analizado_id == 30                                                          # …aunque todo cuenta como «ya mirado»
        assert len(s.cubiertos) < 30
        assert s.resumen_completo.startswith("[") and "–" in s.resumen_completo.split("]")[0]       # inicio Y fin del tramo
        assert "Tema del tramo (lectura parcial:" in s.resumen_completo
        await cerrar(gestor, 900)
        return c

    c = asyncio.run(go())
    finales = [x for x in llm.llamadas if "cierre de la reunión" in x[0]]
    assert len(finales) == 1 and finales[0][2] == "sonnet"                                         # la MISMA llamada final, ninguna nueva
    assert not [x for x in llm.llamadas if "verificar candidatas" in x[0]]
    sistema, usuario, _ = finales[0]
    assert "<<<DATOS transcripcion_no_cubierta>>>" in usuario and "transcripcion_no_cubierta" in sistema
    nc = usuario.split("<<<DATOS transcripcion_no_cubierta>>>")[1].split("<<<FIN>>>")[0]
    turno = next(x for x in llm.llamadas if "compañero del equipo" in x[0])[1]
    for i in range(30):                                            # cada línea la leyó el turno O llega al cierre, nunca ninguna de las dos ni las dos
        assert (f"termino{i}n0 " in turno) != (f"termino{i}n0 " in nc), i
    assert "Tramo 1 de" in nc and "desde 00:" in nc and c["leidas"] == 30 - nc.count("termino") // 15
    assert gestor.sesion.avisos_resumen == [] and gestor.revision["avisos"] == []
    assert "Cada entrada de «resumen_acumulado» va marcada «[MM:SS–MM:SS]»" in sistema


def test_sin_huecos_el_prompt_final_no_lleva_el_bloque_ni_su_regla(montaje):
    gestor, llm, _ = montaje

    async def go():
        await arrancar(gestor, 5)
        for i in range(6):
            gestor._agregar(i * 30.0, "reunion", " ".join(f"cosa{i}n{j}" for j in range(40)))
        gestor.reloj.fijar(180)
        assert (await gestor.analizar(manual=True))["ok"]
        await cerrar(gestor, 180)

    asyncio.run(go())
    sistema, usuario, _ = next(x for x in llm.llamadas if "cierre de la reunión" in x[0])
    assert "transcripcion_no_cubierta" not in usuario and "transcripcion_no_cubierta" not in sistema
    assert "[00:00–02:30] Se habló de varias cosas." in usuario


def test_si_el_resumen_afirma_falta_de_contenido_la_revision_y_el_md_lo_avisan_sin_borrar_nada(montaje):
    gestor, llm, _ = montaje
    llm.resumen_final = "## Resumen de la reunión (03:00)\n\nSe habló de varias cosas.\nNo hay contenido registrado entre 01:00 y 02:00."

    async def go():
        await arrancar(gestor, 5)
        for i in range(6):
            gestor._agregar(i * 30.0, "reunion", " ".join(f"cosa{i}n{j}" for j in range(40)))
        gestor.reloj.fijar(180)
        assert (await gestor.analizar(manual=True))["ok"]
        await cerrar(gestor, 180)

    asyncio.run(go())
    rev, s = gestor.revision, gestor.sesion
    assert len(rev["avisos"]) == 1 and "01:00 y 02:00" in rev["avisos"][0] and "3 líneas" in rev["avisos"][0] and "SÍ se habló" in rev["avisos"][0]
    assert "No hay contenido registrado entre 01:00 y 02:00." in s.resumen_final            # el texto del modelo no se toca
    md = s.render()
    assert "## Aviso sobre el resumen" in md and md.count("## Resumen") == 1
    assert md.count("**Reunión:**") == 6                                                      # y la transcripción sigue entera


def test_el_cierre_sin_ninguna_llamada_previa_manda_toda_la_reunion_sin_eco(montaje):
    gestor, llm, _ = montaje

    async def go():
        await arrancar(gestor)
        gestor.reloj.fijar(100)
        gestor._agregar(10.0, "reunion", "El proveedor de lavandería entregará el presupuesto firmado antes del viernes de la semana próxima")
        gestor._agregar(12.0, "yo", "el proveedor de lavanderia entregara el presupuesto firmado antes del viernes de la semana proxima")
        gestor._agregar(30.0, "yo", "Pregunto yo si el contrato incluye también la ropa de piscina de los hoteles de la costa")
        await cerrar(gestor, 100)

    asyncio.run(go())
    usuario = next(x for x in llm.llamadas if "cierre de la reunión" in x[0])[1]
    todo = usuario.split("<<<DATOS transcripcion_pendiente>>>")[1]                          # sin turnos previos, todo es «pendiente»
    assert todo.count("proveedor de lavandería") == 1 and "[00:12] M:" not in todo           # el eco no viaja
    assert "Pregunto yo si el contrato incluye" in todo                                       # la voz propia sí


def test_el_gestor_avisa_a_la_interfaz_del_eco_y_no_muestra_un_micro_que_era_todo_eco(tmp_path):
    raiz = tmp_path / "proyectos"
    shutil.copytree(PRUEBAS, raiz)
    cfg = Config(tmp_path / "config.json")
    cfg.actualizar({"raiz_proyectos": str(raiz), "knowledge": ""}, guardar=False)
    eventos = []
    gestor = Gestor(cfg, Guardian(raiz, tmp_path / "bandeja", tmp_path / "cache"), Consumo(None), FalsoCierre(), eventos.append,
                    simulacion=[LineaSim(9999.0, "yo", "fin")], velocidad=1)
    frase = "Revisamos el calendario de obras del hotel de la costa y decidimos adelantar la reforma de la piscina al mes de marzo"

    async def go():
        await arrancar(gestor)
        gestor.reloj.fijar(50)
        gestor._agregar(10.0, "yo", "Antes de nada, " + frase.lower())                      # Micro primero: sale tal cual…
        gestor._agregar(12.0, "reunion", frase)                                              # …y al llegar Reunión se corrige
        gestor._agregar(40.0, "reunion", "Pasamos al siguiente punto del orden del día que trata sobre la contratación de personal")
        gestor._agregar(41.0, "yo", "pasamos al siguiente punto del orden del dia que trata sobre la contratacion de personal")   # Reunión primero: ni se muestra

    asyncio.run(go())
    segs = [e for e in eventos if e["tipo"] == "segmento"]
    assert [e["fuente"] for e in segs] == ["yo", "reunion", "reunion"] and segs[0]["texto"].startswith("Antes de nada")
    eco = [e for e in eventos if e["tipo"] == "segmento_eco"]
    assert len(eco) == 1 and eco[0]["cambios"] == [{"id": 1, "texto": "Antes de nada,"}]
    snap = gestor.snapshot()
    assert [x["id"] for x in snap["segmentos"]] == [1, 2, 3] and snap["segmentos"][0]["texto"] == "Antes de nada,"
    assert not any(e["tipo"] == "segmento" and e["id"] == 4 for e in eventos) and gestor.sesion.segmentos[3].texto == ""
