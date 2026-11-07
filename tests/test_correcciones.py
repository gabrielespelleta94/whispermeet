"""Correcciones tras la prueba real de 73 min: resumen final con TODAS las tarjetas, tope de tarjetas por análisis,
duplicados entre categorías, decisiones solo explícitas, una sola confirmación de contradicciones, selección de ficheros
para proponer cambios, etiquetas Micro/Reunión y el botón opcional «Pulir con Opus» (modelo falso, sin red)."""
import asyncio
import json
import shutil
from pathlib import Path

import pytest

from apuntes import contexto as CX
from apuntes import planes as PL
from apuntes import tarjetas as TJ
from apuntes.analisis import ErrorAnalisis, ModeloLLM, Respuesta, Uso
from apuntes.analisis import claude_cli as C
from apuntes.analisis import prompts as P
from apuntes.config import MODELOS_POR_DEFECTO, Config
from apuntes.consumo import Consumo
from apuntes.gestor import Gestor
from apuntes.rutas import Guardian
from apuntes.simulador import parsear
from apuntes.texto import ETIQUETAS, formatear_lineas, limpiar_transcripcion, mmss

PRUEBAS = Path(__file__).resolve().parent.parent / "pruebas" / "proyectos"
PROY = "Proyecto Ficticio Alfa"
TEMAS = ["proveedor", "cuota", "tarifa", "calendario", "moneda", "contrato", "auditoría", "hotel", "pasarela", "licencia",
         "migración", "formación", "inventario", "comisión"]


def minuto(i: int) -> str:
    return mmss(i * 300 + 30)


class Falso(ModeloLLM):
    """Cada periódico devuelve 5 tarjetas (2 decisiones, 1 pendiente, 1 pregunta, 1 riesgo) + 1 candidata; los temas
    cambian en cada análisis para que no se confundan con duplicados."""

    def __init__(self):
        self.llamadas = []
        self.n = 0
        self.confirma = lambda i: i == 0
        self.error_pulido = None
        self.sin_cambios = "Todo lo decidido ya figura en el contexto."
        self.minuto_forzado = None

    def contar(self, trozo):
        return sum(trozo in s for s, _, _ in self.llamadas)

    def completar(self, sistema, usuario, modelo, esfuerzo="", timeout_s=240, sin_razonamiento=False):
        self.llamadas.append((sistema, usuario, modelo))
        uso = [Uso(modelo, 100, 20)]
        if self.error_pulido and "pulir el resumen" in sistema:
            raise self.error_pulido
        if "compactar el contexto" in sistema:
            return Respuesta(json.dumps({"digest": "[02-alcance.md] SAP fuera de alcance."}), uso)
        if "análisis incremental" in sistema:
            self.n += 1
            i, a, b = self.n, TEMAS[(self.n - 1) % len(TEMAS)], TEMAS[(self.n + 6) % len(TEMAS)]
            m = self.minuto_forzado or minuto(i - 1)
            return Respuesta(json.dumps({
                "resumen": f"Tramo {i}: se habló de {a} y de {b}. " + "relleno " * 50,
                "t": [{"k": "decision", "x": f"Acordado contratar {a} nuevo{i} con vigencia anual{i}", "m": m},
                      {"k": "decision", "x": f"Acordado cerrar {b} nuevo{i} antes del viernes{i}", "m": m},
                      {"k": "pendiente", "x": f"Enviar presupuesto de {a} cliente{i}", "m": m, "r": "Luis"},
                      {"k": "pregunta", "x": f"¿Quién paga {b} escenario{i} definitivo{i}?", "m": m},
                      {"k": "riesgo", "x": f"Riesgo de retraso con {a} dependencia{i} externa{i}", "m": m}],
                "c": [{"x": f"Meter {b} sistema{i} en fase 1", "m": m, "q": "Integración fuera de alcance"}]}), uso)
        if "verificar candidatas" in sistema:
            candidatas = [l for l in usuario.splitlines() if l[:1].isdigit()]
            return Respuesta(json.dumps({"v": [{"i": k, "ok": bool(self.confirma(k)), "x": "Contradice el alcance"}
                                               for k in range(len(candidatas))]}), uso)
        if "pulir el resumen" in sistema:
            return Respuesta(json.dumps({"resumen": "RESUMEN PULIDO por opus"}), [Uso(modelo, 300, 80)])
        if "cierre de la reunión" in sistema:
            d = {"resumen": "Resumen final de sonnet.", "cambios": []}
            if self.sin_cambios is not None:
                d["sin_cambios"] = self.sin_cambios
            return Respuesta(json.dumps(d), uso)
        raise AssertionError("prompt inesperado")


@pytest.fixture
def montaje(tmp_path):
    raiz = tmp_path / "proyectos"
    shutil.copytree(PRUEBAS, raiz)
    g = Guardian(raiz, tmp_path / "bandeja", tmp_path / "cache")
    cfg = Config(tmp_path / "config.json")
    cfg.actualizar({"raiz_proyectos": str(raiz), "knowledge": ""}, guardar=False)
    llm = Falso()
    eventos = []
    gestor = Gestor(cfg, g, Consumo(None), llm, eventos.append, simulacion=[], velocidad=1)
    return gestor, llm, eventos, tmp_path


async def esperar(cond, t=15):
    for _ in range(int(t / 0.05)):
        if cond():
            return
        await asyncio.sleep(0.05)
    raise AssertionError("tiempo agotado")


async def reunion(gestor, n=12, proyecto=PROY):
    """n análisis manuales de 3 líneas cada uno (a los minutos 0, 5, 10…)."""
    await gestor.iniciar(proyecto, "Tema", 5)
    por_analisis = []
    for i in range(n):
        for k in range(3):
            texto = " ".join(f"termino{i}x{k}x{j}" for j in range(30))
            gestor._agregar(i * 300 + 10 + k * 20, "reunion" if k % 2 else "yo", texto)
        r = await gestor.analizar(manual=True)
        assert r["ok"], r
        por_analisis.append(r["tarjetas"])
    return por_analisis


async def terminar(gestor, n):
    gestor.reloj.fijar(n * 300)
    await gestor.terminar()
    await esperar(lambda: gestor.revision["estado"] in ("lista", "error"))


# ---------------------------------------------------------------- 4. tope de tarjetas, prioridad y duplicados
def test_maximo_3_tarjetas_por_analisis_con_prioridad(montaje):
    gestor, llm, _, _ = montaje

    async def go():
        por = await reunion(gestor, 6)
        assert all(n <= 3 for n in por) and por == [3] * 6
        cats = [t["categoria"] for t in gestor.sesion.tarjetas]
        # de 5 tarjetas + 1 candidata, entran las de mayor prioridad: 2 decisiones y la contradicción
        assert cats.count("decisión") == 12 and cats.count("contradicción") == 6
        assert "pregunta" not in cats and "riesgo" not in cats and "pendiente" not in cats

    asyncio.run(go())


def test_seleccionar_prioridad_tope_y_duplicados_entre_categorias():
    emitidas = [{"categoria": "decisión", "texto": "Los blackouts son un calendario anual de 365 días", "minuto": "06:51", "t_seg": 411}]
    nuevas = [
        {"categoria": "pregunta", "texto": "¿Los blackouts son un calendario anual de 365 días?", "minuto": "06:51", "t_seg": 411},   # igual que lo emitido, otra categoría
        {"categoria": "riesgo", "texto": "El cálculo de desplazamiento por segmentos se hace a mano", "minuto": "08:00", "t_seg": 480},
        {"categoria": "pendiente", "texto": "Definir el umbral de desestimación por precio fuera de mercado", "minuto": "09:00", "t_seg": 540},
        {"categoria": "pregunta", "texto": "¿Quién define el umbral de desestimación por precio fuera de mercado?", "minuto": "09:00", "t_seg": 540},  # mismo minuto y asunto que el pendiente
        {"categoria": "decisión", "texto": "Las cotizaciones grandes las cotiza Revenue y no el comercial", "minuto": "09:30", "t_seg": 570},
        {"categoria": "pregunta", "texto": "¿Se mira el precio online al cotizar grupos pendientes?", "minuto": "10:00", "t_seg": 600},
    ]
    out = TJ.seleccionar(nuevas, emitidas, 3)
    assert len(out) == 3
    textos = " ".join(t["texto"] for t in out)
    assert "Revenue" in textos and "umbral" in textos and "desplazamiento" in textos     # decisión, pendiente, riesgo
    assert "calendario anual" not in textos and "precio online" not in textos            # duplicada y de menor prioridad
    assert sum("umbral" in t["texto"] for t in out) == 1                                  # la pregunta del mismo asunto no entra
    # sin tope no se cuela el duplicado cruzado
    todas = TJ.seleccionar(nuevas, emitidas, 10)
    assert not any(t["texto"].startswith("¿Quién define") or t["texto"].startswith("¿Los blackouts") for t in todas)
    # minutos lejanos: una pregunta y una decisión sobre lo mismo en momentos distintos NO se consideran la misma
    lejos = TJ.seleccionar([{"categoria": "pregunta", "texto": "¿Los blackouts son un calendario anual de 365 días?", "minuto": "40:00", "t_seg": 2400}], emitidas, 3)
    assert len(lejos) == 1


def test_la_misma_tarjeta_no_se_repite_en_analisis_sucesivos(montaje):
    gestor, llm, _, _ = montaje
    original = llm.completar

    def repetido(sistema, usuario, modelo, *a, **k):
        if "análisis incremental" in sistema:
            llm.llamadas.append((sistema, usuario, modelo))
            return Respuesta(json.dumps({"resumen": "r", "t": [
                {"k": "decision", "x": "Se acuerda contratar el proveedor de pasarela anual", "m": "00:30"}], "c": []}), [Uso(modelo, 1, 1)])
        return original(sistema, usuario, modelo, *a, **k)

    llm.completar = repetido

    async def go():
        await reunion(gestor, 3)
        assert [t["categoria"] for t in gestor.sesion.tarjetas] == ["decisión"]

    asyncio.run(go())


def test_un_minuto_inventado_posterior_a_la_reunion_se_acota(montaje):
    gestor, llm, _, _ = montaje
    llm.minuto_forzado = "99:00"

    async def go():
        await reunion(gestor, 2)
        ultimo = gestor.sesion.segmentos[-1].t
        assert all(t["t_seg"] is not None and t["t_seg"] <= ultimo for t in gestor.sesion.tarjetas)
        assert max(t["t_seg"] for t in gestor.sesion.tarjetas) < 99 * 60

    asyncio.run(go())


# ---------------------------------------------------------------- 1. el resumen final recibe TODAS las tarjetas
def test_una_decision_temprana_llega_al_prompt_final(montaje):
    gestor, llm, _, _ = montaje

    async def go():
        await reunion(gestor, 14)                       # 14 tramos de ~400 caracteres: el acumulado (tope 2.500) ya perdió el principio
        s = gestor.sesion
        assert "Tramo 1:" not in s.resumen_acumulado and "Tramo 14:" in s.resumen_acumulado
        await terminar(gestor, 14)
        assert gestor.revision["estado"] == "lista"

    asyncio.run(go())
    _, usuario, modelo = next(c for c in llm.llamadas if "cierre de la reunión" in c[0])
    assert modelo == "sonnet"
    insights = usuario.split("<<<DATOS insights_emitidos>>>")[1].split("<<<FIN>>>")[0]
    # la decisión del análisis 1 (minuto 00:30) y la del último, ambas
    assert "[00:30] decisión: Acordado contratar proveedor nuevo1" in insights
    assert "[65:30] decisión: Acordado contratar" in insights
    assert insights.count("decisión:") == 28            # 2 por análisis x 14, ninguna recortada por antigüedad
    # el resumen que ve el final es el COMPLETO, tramo a tramo con su INICIO Y SU FIN (antes solo el inicio, que un modelo podía leer como el final)
    resumen = usuario.split("<<<DATOS resumen_acumulado>>>")[1].split("<<<FIN>>>")[0]
    assert "[00:10–00:50] Tramo 1:" in resumen and "Tramo 14:" in resumen
    assert usuario.startswith("Duración de la reunión: 70:00.")


def test_lineas_compactas_no_recortan_por_antiguedad_y_solo_sueltan_lo_menos_accionable():
    tarjetas = ([{"categoria": "decisión", "texto": f"decisión {i} " + "x" * 100, "minuto": mmss(i * 60), "t_seg": i * 60} for i in range(40)]
                + [{"categoria": "pregunta", "texto": f"pregunta {i} " + "x" * 100, "minuto": mmss(i * 60), "t_seg": i * 60} for i in range(40)])
    todo = TJ.lineas_compactas(tarjetas, tope_chars=10 ** 6)
    assert len(todo) == 80 and todo[0].startswith("[00:00]") and "[39:00]" in todo[-1]
    ajustado = TJ.lineas_compactas(tarjetas, tope_chars=6000)
    assert sum("decisión:" in l for l in ajustado) == 40 and sum("pregunta:" in l for l in ajustado) < 40
    assert TJ.rango_minutos(tarjetas) == ("00:00", "39:00")


# ---------------------------------------------------------------- 6. una sola llamada de confirmación, al terminar
def test_contradicciones_posibles_al_momento_y_una_sola_llamada_de_sonnet_al_final(montaje):
    gestor, llm, eventos, _ = montaje

    async def go():
        await reunion(gestor, 5)
        posibles = [t for t in gestor.sesion.tarjetas if t["categoria"] == "contradicción"]
        assert len(posibles) == 5 and all(t["estado"] == "posible" for t in posibles)   # visibles ya, sin esperar a sonnet
        assert llm.contar("verificar candidatas") == 0
        assert "Posible contradicción" in gestor.sesion.render()
        await terminar(gestor, 5)

    asyncio.run(go())
    assert llm.contar("verificar candidatas") == 1
    sistema, usuario, modelo = next(c for c in llm.llamadas if "verificar candidatas" in c[0])
    assert modelo == "sonnet" and len([l for l in usuario.splitlines() if l[:1].isdigit()]) == 5   # las 5 candidatas juntas
    final = gestor.sesion.tarjetas
    assert [t["estado"] for t in final if t["categoria"] == "contradicción"] == ["confirmada"]      # solo la primera se confirmó
    assert any(e["tipo"] == "tarjetas" and e.get("todas") for e in eventos)


def test_tope_de_candidatas_por_reunion(montaje):
    gestor, llm, _, _ = montaje

    async def go():
        await reunion(gestor, 12)
        assert sum(t.get("estado") == "posible" for t in gestor.sesion.tarjetas) == gestor.cfg["max_candidatas_confirmar"] == 8

    asyncio.run(go())


def test_si_falla_la_confirmacion_siguen_como_posibles_y_la_revision_sale(montaje):
    gestor, llm, _, _ = montaje
    original = llm.completar

    def roto(sistema, usuario, modelo, *a, **k):
        if "verificar candidatas" in sistema:
            llm.llamadas.append((sistema, usuario, modelo))
            raise ErrorAnalisis("otro", "no se pudo confirmar", transitorio=False)
        return original(sistema, usuario, modelo, *a, **k)

    llm.completar = roto

    async def go():
        await reunion(gestor, 3)
        await terminar(gestor, 3)
        assert gestor.revision["estado"] == "lista"
        assert all(t["estado"] == "posible" for t in gestor.sesion.tarjetas if t["categoria"] == "contradicción")
        insights = next(u for s, u, _ in llm.llamadas if "cierre de la reunión" in s)
        assert "[posible, sin verificar]" in insights

    asyncio.run(go())


# ---------------------------------------------------------------- 2. cambios al contexto: motivo si no hay ninguno
def test_sin_cambios_la_revision_dice_el_motivo(montaje):
    gestor, llm, _, _ = montaje

    async def go():
        await reunion(gestor, 2)
        await terminar(gestor, 2)
        assert gestor.revision["cambios"] == [] and gestor.revision["sin_cambios"] == "Todo lo decidido ya figura en el contexto."
        # el prompt pide comparar las decisiones con los ficheros y explicar el motivo
        sistema = next(s for s, _, _ in llm.llamadas if "cierre de la reunión" in s)
        assert "sin_cambios" in sistema and "no figura en ellos" in sistema

    asyncio.run(go())


def test_sin_motivo_del_modelo_se_dice_igualmente(montaje):
    gestor, llm, _, _ = montaje
    llm.sin_cambios = None

    async def go():
        await reunion(gestor, 2)
        await terminar(gestor, 2)
        assert "no indicó el motivo" in gestor.revision["sin_cambios"]

    asyncio.run(go())


def test_ficheros_para_final_no_prefiere_el_fichero_mas_grande(tmp_path):
    raiz = tmp_path / "p"
    ctx = raiz / "Proy" / "00. CONTEXTO (IA)"
    ctx.mkdir(parents=True)
    (ctx / "02-alcance.md").write_text("# Alcance\n\n## Qué entra\n\nCotización de grupos y cupos por hotel.\n\n## Cambios de alcance\n\n| Fecha | Cambio |\n|---|---|\n", encoding="utf-8")
    (ctx / "03-precios.md").write_text("# Precios\n\nLos descuentos por ocupación y segmento (Leisure, MICE) se fijan en Revenue.\n", encoding="utf-8")
    # bitácora enorme y con mucho vocabulario: comparte términos con la reunión, pero por pura longitud
    dia = lambda i: " ".join(f"tema{i}x{j} descuentos ocupación segmento" for j in range(120))
    (ctx / "11-bitacora.md").write_text("# Bitácora\n\n" + "\n\n".join(f"## Día {i}\n\n{dia(i)}" for i in range(40)), encoding="utf-8")
    g = Guardian(raiz, tmp_path / "b", tmp_path / "c")
    consulta = "Se decide que los descuentos dependen de la ocupación y el segmento; cupos por hotel"
    fs = CX.ficheros_para_final(g, "Proy", consulta, "x", maximo=2)
    assert "02-alcance.md" in fs and "03-precios.md" in fs and "11-bitacora.md" not in fs


def test_extracto_de_fichero_largo_lleva_los_encabezados_y_las_secciones_cercanas():
    texto = "# Titulo\n\n" + "\n\n".join(f"## Seccion {i}\n\n" + ("relleno " * 80) for i in range(30)) + "\n\n## Cambios de alcance\n\ndescuentos por ocupación\n"
    ext = CX.extracto_relevante(texto, {"descuentos", "ocupación"}, 3000)
    assert len(ext) <= 3100 and ext.startswith("[Secciones del fichero:") and "Cambios de alcance" in ext.split("\n")[0]
    assert "descuentos por ocupación" in ext          # la sección relevante entra aunque esté al final del fichero


# ---------------------------------------------------------------- 3. objetivos: se reevalúan y el minuto es el más reciente
def test_objetivo_no_cubierto_actualiza_minuto_con_la_evidencia_mas_reciente():
    o = PL.objetivos_iniciales({"objetivos": ["uno", "dos", "tres"]})
    aplicar = lambda lista: PL.aplicar_actualizaciones(o, PL.normalizar_actualizaciones(lista, 3))
    aplicar([{"i": 1, "e": "p", "m": "08:57"}])
    assert (o[0]["estado"], o[0]["minuto"]) == ("parcial", "08:57")
    assert aplicar([{"i": 1, "e": "p", "m": "31:10"}]) == [1] and (o[0]["minuto"], o[0]["t_seg"]) == ("31:10", 1870)   # sigue parcial, minuto nuevo
    assert aplicar([{"i": 1, "e": "p", "m": "05:00"}]) == [] and o[0]["minuto"] == "31:10"                            # una evidencia más antigua no lo mueve atrás
    assert aplicar([{"i": 1, "e": "n", "m": "40:00"}]) == [] and o[0]["estado"] == "parcial"                          # no retrocede sin «d»
    aplicar([{"i": 1, "e": "c", "m": "50:00"}])
    assert (o[0]["estado"], o[0]["minuto"]) == ("cubierto", "50:00")
    assert aplicar([{"i": 1, "e": "c", "m": "60:00"}]) == [] and o[0]["minuto"] == "50:00"                           # el cubierto conserva su minuto
    assert aplicar([{"i": 1, "e": "p", "m": "61:00"}]) == [] and o[0]["estado"] == "cubierto"
    aplicar([{"i": 1, "e": "p", "m": "62:00", "d": 1}])
    assert (o[0]["estado"], o[0]["minuto"]) == ("parcial", "62:00")


def test_el_prompt_envia_el_estado_actual_y_el_minuto_y_pide_reevaluar():
    o = PL.objetivos_iniciales({"objetivos": ["uno", "dos", "tres"]})
    PL.aplicar_actualizaciones(o, PL.normalizar_actualizaciones([{"i": 1, "e": "p", "m": "08:57"}, {"i": 2, "e": "c", "m": "12:00"}], 3))
    assert PL.bloque_prompt(o) == "1 [p 08:57] uno\n2 [c 12:00] dos\n3 [ ] tres"
    s = P.sistema_periodico(2500, True)
    assert "REEVALÚA" in s and "MÁS RECIENTE" in s and "NO están cubiertos" in s


# ---------------------------------------------------------------- 5. decisiones: asunto resuelto, nunca una posibilidad (prompt)
def test_prompt_periodico_define_decision_y_preguntas_sin_responder():
    s = P.sistema_periodico(2500)
    assert "acuerdo explícito" in s and "regla de negocio" in s and "NO es decisión" in s and "pendiente" in s
    assert "sigue sin respuesta" in s and "como máximo 3 elementos" in s
    assert "ni lo emitas dos veces con distinta categoría" in s
    f = P.sistema_final(True)
    assert "no conviertas propuestas ni preguntas en decisiones" in f and "ENTERA" in f


# ---------------------------------------------------------------- 8. etiquetas
def test_etiquetas_micro_y_reunion_en_prompts_md_y_simulador(montaje):
    assert ETIQUETAS == {"yo": "M", "reunion": "R"}
    for s in (P.BASE, P.sistema_periodico(2500, True, True), P.sistema_final(True, True), P.sistema_pulido()):
        assert "VARIAS personas" in s and "Y = " not in s and "«Yo»" not in s
    assert "sin asignar" in P.sistema_periodico(2500) and "«Yo»" not in P.sistema_periodico(2500)
    from apuntes.texto import Linea
    assert formatear_lineas([Linea(5, "yo", "hola"), Linea(9, "reunion", "adiós")]) == "[00:05] M: hola\n[00:09] R: adiós"
    gestor, _, _, _ = montaje

    async def go():
        await gestor.iniciar(PROY, "Tema", 5)
        gestor._agregar(3, "yo", "hola")
        gestor._agregar(6, "reunion", "adiós")
        md = gestor.sesion.render()
        assert "**Micro:** hola" in md and "**Reunión:** adiós" in md and "**Yo:**" not in md

    asyncio.run(go())
    assert [l.fuente for l in parsear("[00:01] Micro: a\n[00:02] Yo: b\n[00:03] Reunión: c")] == ["yo", "yo", "reunion"]


# ---------------------------------------------------------------- 9. el simulador respeta los minutos de la transcripción
def test_simulador_no_desplaza_los_minutos_con_lineas_largas():
    larga = " ".join(["palabra"] * 60)          # 60 palabras = 24 s según la regla de 0,4 s por palabra
    lineas = parsear("\n".join(f"[{i // 60:02d}:{i % 60:02d}] Reunión: {larga}" for i in range(0, 120, 6)))   # una cada 6 s
    assert [l.t for l in lineas] == list(range(0, 120, 6))      # antes se iban acumulando (24 s por línea)
    sin_marca = parsear("[00:10] Micro: a b c d e\nReunión: sin marca")
    assert sin_marca[1].t == 10 + max(2.0, 5 * 0.4)             # solo las líneas SIN marca avanzan por palabras


def test_la_simulacion_para_el_reloj_en_su_ultima_linea(tmp_path):
    from apuntes.simulador import LineaSim
    raiz = tmp_path / "proyectos"
    shutil.copytree(PRUEBAS, raiz)
    g = Guardian(raiz, tmp_path / "bandeja", tmp_path / "cache")
    cfg = Config(tmp_path / "config.json")
    gestor = Gestor(cfg, g, Consumo(None), Falso(), lambda e: None,
                    simulacion=[LineaSim(1.0, "yo", "uno dos tres"), LineaSim(5.0, "reunion", "cuatro cinco seis")], velocidad=500)

    async def go():
        await gestor.iniciar(None, "Sim", 5)
        await esperar(lambda: gestor._sim_fin)
        t = gestor.reloj.ahora()
        await asyncio.sleep(0.3)
        assert t == gestor.reloj.ahora() == 5.0                  # la reunión simulada acaba en su último minuto

    asyncio.run(go())


# ---------------------------------------------------------------- 7. consumo: tokens de razonamiento
def test_el_uso_distingue_el_razonamiento_de_la_salida():
    d = {"modelUsage": {"claude-haiku-5-5": {"inputTokens": 2, "outputTokens": 1700, "costUSD": 0.001}},
         "usage": {"output_tokens": 1700, "output_tokens_details": {"thinking_tokens": 1400}}}
    u = C.extraer_uso(d, "haiku")[0]
    assert (u.salida, u.razonamiento) == (1700, 1400)
    assert C.extraer_uso({"usage": {"output_tokens": 5}}, "haiku")[0].razonamiento == 0


def test_los_topes_de_longitud_se_aplican_a_la_respuesta_del_modelo():
    d = {"resumen": "r" * 900, "t": [{"k": "decision", "x": "x" * 400, "m": "01:00"}] * 9,
         "c": [{"x": "y" * 400, "m": "01:00", "q": "q" * 400}]}
    out = P.normalizar_periodico(d, 2500)
    assert len(out["resumen"]) <= P.LIM_RESUMEN + 61 and len(out["tarjetas"]) <= 2 * P.MAX_TARJETAS
    assert all(len(t["texto"]) <= P.LIM_TARJETA + 21 for t in out["tarjetas"]) and len(out["candidatas"][0]["q"]) <= P.LIM_CITA + 41


# ---------------------------------------------------------------- «Pulir con Opus»
def test_opus_solo_en_pulido_y_nunca_por_defecto():
    assert MODELOS_POR_DEFECTO["pulido"] == "opus"
    assert [k for k, v in MODELOS_POR_DEFECTO.items() if "opus" in v] == ["pulido"]


def test_no_se_pule_sin_clic_y_no_sustituye_sin_aceptar(montaje):
    gestor, llm, _, _ = montaje

    async def go():
        await reunion(gestor, 3)
        await terminar(gestor, 3)
        rev = gestor.revision
        assert rev["estado"] == "lista" and rev["pulido"]["estado"] == "ninguno"
        assert llm.contar("pulir el resumen") == 0                        # nunca automático
        sonnet = rev["resumen"]
        assert sonnet.startswith("Resumen final de sonnet.")
        r = await gestor.pulir()
        assert r["ok"] and llm.contar("pulir el resumen") == 1
        assert rev["pulido"]["estado"] == "listo" and rev["pulido"]["resumen"].startswith("RESUMEN PULIDO por opus")
        # las dos versiones conviven; el documento sigue siendo el de sonnet hasta que se elige
        assert rev["resumen"] == sonnet == rev["resumen_sonnet"] and "PULIDO" not in gestor.sesion.render()
        with pytest.raises(ValueError):
            await gestor.pulir()                                           # una sola llamada
        await gestor.elegir_resumen("opus")
        assert rev["resumen"].startswith("RESUMEN PULIDO") and "RESUMEN PULIDO por opus" in gestor.sesion.render()
        assert "Resumen final de sonnet." not in gestor.sesion.render()
        await gestor.elegir_resumen("sonnet")                              # la de sonnet no se pierde
        assert rev["resumen"] == sonnet and "PULIDO" not in gestor.sesion.render() and "Resumen final de sonnet." in gestor.sesion.render()
        with pytest.raises(ValueError):
            await gestor.elegir_resumen("otra")

    asyncio.run(go())
    sistema, usuario, modelo = next(c for c in llm.llamadas if "pulir el resumen" in c[0])
    assert modelo == "opus"
    # solo el resumen de sonnet y las tarjetas: ni transcripción ni contexto
    assert "<<<DATOS transcripcion" not in usuario and "<<<DATOS contexto" not in usuario and "termino0x0x0" not in usuario
    assert "<<<DATOS resumen_final>>>\nResumen final de sonnet." in usuario and "decisión: Acordado contratar" in usuario
    assert "sin añadir" in sistema.lower() or "NO añadas nada" in sistema


def test_un_fallo_del_pulido_se_muestra_sin_reintentos_y_no_bloquea(montaje):
    gestor, llm, _, _ = montaje
    llm.error_pulido = ErrorAnalisis("otro", "Opus no respondió", transitorio=True)

    async def go():
        await reunion(gestor, 2)
        await terminar(gestor, 2)
        rev = gestor.revision
        r = await gestor.pulir()
        assert not r["ok"] and rev["pulido"]["estado"] == "error" and "Opus no respondió" in rev["pulido"]["error"]
        assert llm.contar("pulir el resumen") == 1                         # ni un reintento aunque el error sea transitorio
        assert rev["estado"] == "lista" and rev["resumen"].startswith("Resumen final de sonnet.")
        with pytest.raises(ValueError):
            await gestor.elegir_resumen("opus")                            # no hay nada pulido que elegir
        assert (await gestor.aplicar_revision([]))["aplicados"] == []      # la revisión sigue funcionando
        assert (await gestor.cerrar_revision())["ok"]

    asyncio.run(go())


def test_la_llamada_de_pulido_se_registra_como_tarea_pulido(montaje, tmp_path):
    gestor, llm, _, _ = montaje
    gestor.consumo = Consumo(tmp_path / "consumo.jsonl")

    async def go():
        await reunion(gestor, 2)
        gestor.analista.consumo = gestor.consumo
        await terminar(gestor, 2)
        await gestor.pulir()

    asyncio.run(go())
    tareas = [json.loads(l)["tarea"] for l in (tmp_path / "consumo.jsonl").read_text(encoding="utf-8").splitlines()]
    assert tareas.count("pulido") == 1


def test_el_pulido_usa_el_modelo_de_config(montaje):
    gestor, llm, _, _ = montaje

    async def go():
        await reunion(gestor, 1)
        await terminar(gestor, 1)
        await gestor.pulir()

    asyncio.run(go())
    assert gestor.cfg.modelo("pulido") == "opus"
    assert [m for s, _, m in llm.llamadas if "pulir el resumen" in s] == ["opus"]
