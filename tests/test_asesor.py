"""El asesor en directo (fases 1 a 5 de la especificación): detector de preguntas, respuesta sugerida (prioridad en la cola, límites, fuentes citadas y
validadas, escalada a sonnet), el Estratega, «Profundizar» (con y sin web) y lo que llega al .md, al resumen final y al backlog. Todo con un modelo falso."""
import asyncio
import json
import shutil
import threading
import time
from pathlib import Path

import pytest

from apuntes import asesor as A
from apuntes import backlog as BL
from apuntes import config as CF
from apuntes.analisis import ErrorAnalisis, ModeloLLM, Respuesta, Uso
from apuntes.analisis import claude_cli as CLI
from apuntes.config import Config
from apuntes.consumo import Consumo
from apuntes.fuentes import Resultado
from apuntes.gestor import Gestor
from apuntes.orquesta import CerrojoPrioritario
from apuntes.rutas import Guardian
from apuntes.simulador import LineaSim

PRUEBAS = Path(__file__).resolve().parent.parent / "pruebas" / "proyectos"
PROYECTO = "Proyecto Ficticio Alfa"


# ================================================================ detector de preguntas (local, sin LLM)
@pytest.mark.parametrize("texto,esperadas", [
    ("¿Qué servicio de correo envía el mail al crear una inversión?", ["¿Qué servicio de correo envía el mail al crear una inversión?"]),
    ("¿Se cumple el objetivo del 15 de noviembre?", ["¿Se cumple el objetivo del 15 de noviembre?"]),
    ("Y eso, ¿cuánto cuesta?", ["¿cuánto cuesta?"]),
    ("¿Cómo diferencia?", ["¿Cómo diferencia?"]),
    ("Vale, ¿y cuándo podéis entregarlo?", ["¿y cuándo podéis entregarlo?"]),
    ("Què fem amb la integració de SAP? I qui ho manté?", ["¿Què fem amb la integració de SAP?", "¿I qui ho manté?"]),   # catalán, sin «¿»
    ("Habéis incluido el informe en el alcance? Porque no lo veo.", ["¿Habéis incluido el informe en el alcance?"]),
])
def test_el_detector_encuentra_preguntas_con_contenido(texto, esperadas):
    assert A.detectar_preguntas(texto) == esperadas


@pytest.mark.parametrize("texto", [
    "¿Vale?", "¿Sabes?", "¿No?", "¿Eh?", "Oi?", "¿Me oyes?", "¿Me escuchas bien?", "¿Cómo te va?", "¿Qué tal?", "¿A ver ahora?", "¿Estás ahí?",
    "¿Verdad?", "¿De acuerdo?", "M'escoltes?", "¿Qué pasa?", "¿Cómo lo ves?", "¿Sabes que estaría chulo?", "¿Entiendes?",
    "Porque ya estamos en la fase de simulación, ¿no?",            # confirmación al final de una afirmación
    "Eso lo cerramos mañana, vale?", "Lo hacemos así, ¿vale?", "Y no hay más cambios, no?",
    "Esto no es ninguna pregunta.", "",
])
def test_el_detector_descarta_muletillas_y_confirmaciones(texto):
    assert A.detectar_preguntas(texto) == []


def test_el_detector_solo_cuenta_la_pregunta_no_la_afirmacion_con_cola():
    assert A.detectar_preguntas("Lo vemos el viernes, ¿vale? ¿Y quién envía el fichero de tarifas?") == ["¿Y quién envía el fichero de tarifas?"]


def test_es_muletilla_y_palabras_de_contenido():
    assert A.es_muletilla("¿vale?") and A.es_muletilla("me oyes") and not A.es_muletilla("¿cuánto cuesta la licencia?")
    assert A.palabras_de_contenido("¿Cómo lo ves?") == [] and "licencia" in A.palabras_de_contenido("¿Cuánto cuesta la licencia?")


# ================================================================ temas que escalan a sonnet y señales del Estratega
@pytest.mark.parametrize("pregunta,tema", [
    ("¿Cuánto cuesta la licencia de la herramienta?", "precio"), ("¿Qué precio tiene el mantenimiento?", "precio"),
    ("¿Entra el informe de ocupación en el alcance?", "alcance"), ("¿Está incluido el soporte en este proyecto?", "alcance"),
    ("¿Se cumple el objetivo del 15 de noviembre?", "plazos"), ("¿Cuándo podéis entregarlo?", "plazos"),
    ("¿Hay penalización si no llegamos a la fecha en el contrato?", "contrato"), ("¿Qué SLA ofrecéis?", "contrato"),
    ("¿Qué os diferencia de Anaplan?", "competencia"), ("¿Cómo diferencia frente a otras alternativas?", "competencia"),
    ("¿Os comprometéis a tenerlo para diciembre?", "compromiso"), ("¿Nos podéis garantizar la disponibilidad?", "compromiso"),
])
def test_los_temas_sensibles_se_detectan(pregunta, tema):
    assert tema in A.temas_de(pregunta)


@pytest.mark.parametrize("pregunta", ["¿Qué servicio de correo envía el mail al crear una inversión?", "¿Cómo se conecta la app con Fabric?",
                                      "¿Quién tiene acceso al tenant?", "¿En qué carpeta está el informe semanal?"])
def test_las_preguntas_tecnicas_no_escalan(pregunta):
    assert A.temas_de(pregunta) == []


def test_es_estrategico_pide_dos_temas_o_tres_menciones():
    assert not A.es_estrategico({"precio": 1}) and not A.es_estrategico({"oportunidad": 5, "cierre": 4})
    assert A.es_estrategico({"precio": 1, "plazos": 1}) and A.es_estrategico({"precio": 3})
    hits = A.senales_estrategicas("El precio y el plazo de entrega: cuánto cuesta y para cuándo, y si firmamos el contrato. Nos gustaría una siguiente fase.")
    assert {"precio", "plazos", "contrato", "oportunidad"} <= set(hits) and A.es_estrategico(hits)


# ================================================================ la cola: en serie, pero la respuesta se adelanta
def test_el_cerrojo_prioritario_deja_entrar_primero_a_la_respuesta_y_nunca_solapa():
    c = CerrojoPrioritario()
    orden, dentro, solapes = [], [], []
    c.adquirir(2)                                   # una llamada en curso: nadie la expulsa

    def trabajar(prio, nombre):
        with c.turno(prio):
            dentro.append(nombre)
            if len(dentro) > 1:
                solapes.append(nombre)
            time.sleep(0.02)
            orden.append(nombre)
            dentro.remove(nombre)
    hilos = [threading.Thread(target=trabajar, args=a) for a in ((2, "turno-1"), (2, "turno-2"), (1, "afinar"), (0, "respuesta"))]
    for h in hilos:
        h.start()
        time.sleep(0.05)                            # llegan en este orden, con el cerrojo ocupado
    assert c.locked() and c.esperando() == 4
    c.liberar()
    for h in hilos:
        h.join()
    assert orden == ["respuesta", "afinar", "turno-1", "turno-2"] and not solapes and not c.locked()


# ================================================================ validación de lo que devuelve el modelo
def _res(i, etiqueta, tipo="proyecto", texto="Hasta 3 usuarios por hotel. El piloto es el 20 de enero.", dur=None):
    return Resultado(f"F{i}", etiqueta, tipo, texto, 1.0, None, dur)


BASE = "Hasta 3 usuarios por hotel. El piloto es el 20 de enero. [00:12] R: lo hablamos el 15 de noviembre."


def test_sin_base_la_respuesta_es_la_frase_de_siempre_y_la_confianza_baja():
    r = A.normalizar_respuesta({"v": ["Seguro que son 5."], "c": "alta", "f": [{"s": "F1"}], "b": False}, {"F1": _res(1, "02-alcance.md")}, set(), 100, BASE)
    assert r["vinetas"] == [A.SIN_BASE] and r["confianza"] == "baja" and r["citas"] == [] and r["sin_base"] and not r["base"]
    assert A.SIN_BASE == "No hay base en tus fuentes: propón comprobarlo y volver con la respuesta"


def test_una_orientacion_general_solo_vale_sin_base_y_sin_cifras():
    d = {"v": [A.SIN_BASE, "Orientación general: suele hacerse con Microsoft Graph y un permiso de envío."], "c": "alta", "f": [], "b": False}
    r = A.normalizar_respuesta(d, {}, set(), 100, BASE)
    assert r["vinetas"][0] == A.SIN_BASE and r["vinetas"][1].startswith("Orientación general") and r["orientacion"] and r["confianza"] == "baja"
    d["v"][1] = "Orientación general: cuesta unos 5000 euros."
    assert A.normalizar_respuesta(d, {}, set(), 100, BASE)["vinetas"] == [A.SIN_BASE]


def test_las_citas_se_validan_como_en_pregunta_le():
    entregadas = {"F1": _res(1, "02-alcance.md"), "F2": _res(2, "sesión 2026-10-01 · Kick off", "sesion", dur=600)}
    d = {"v": ["Hasta 3 usuarios por hotel."], "c": "alta", "b": True,
         "f": [{"s": "F1"}, {"s": "F2", "m": "05:00"}, {"s": "F2", "m": "50:00"}, {"s": "F9"}, {"f": "inventado.md"}, {"f": "01-ficha.md"}, {"m": "99:00"}, {"m": "00:12"}]}
    r = A.normalizar_respuesta(d, entregadas, {"01-ficha.md"}, 120, BASE)
    assert {"fuente": "02-alcance.md", "tipo": "proyecto"} in r["citas"]
    assert {"fuente": "sesión 2026-10-01 · Kick off", "tipo": "sesion", "minuto": "05:00"} in r["citas"]
    assert {"fuente": "sesión 2026-10-01 · Kick off", "tipo": "sesion"} in r["citas"]           # el minuto 50:00 pasa de la duración: se queda sin minuto
    assert {"fuente": "01-ficha.md", "tipo": "proyecto"} in r["citas"]                          # fichero del contexto del digest
    assert not any(c.get("fuente") in ("inventado.md",) or c.get("minuto") == "99:00" for c in r["citas"])
    assert len(r["citas"]) <= 4                                                                 # y como mucho cuatro
    # lo dicho en ESTA reunión se cita por su minuto (ya ocurrido), nunca por uno futuro
    r2 = A.normalizar_respuesta({"v": ["El piloto es el 20 de enero."], "c": "media", "b": True, "f": [{"m": "99:00"}, {"m": "00:12"}]}, {}, set(), 120, BASE)
    assert r2["citas"] == [{"minuto": "00:12", "t_seg": 12, "tipo": "reunion"}] and r2["confianza"] == "media"


def test_sin_ninguna_cita_valida_la_confianza_baja():
    r = A.normalizar_respuesta({"v": ["Hasta 3 usuarios por hotel."], "c": "alta", "f": [{"s": "F7"}], "b": True}, {}, set(), 100, BASE)
    assert r["confianza"] == "baja" and r["sin_cita"] and r["base"]


def test_cifras_que_no_estan_en_los_datos_y_promesas_se_descartan():
    d = {"v": ["Cuesta 45000 euros.", "Hasta 3 usuarios por hotel.", "Os garantizamos la entrega el viernes.", "Son 35 horas."], "c": "media", "f": [{"s": "F1"}], "b": True}
    r = A.normalizar_respuesta(d, {"F1": _res(1, "02-alcance.md")}, set(), 100, BASE)
    assert r["vinetas"] == ["Hasta 3 usuarios por hotel."] and r["confianza"] == "media"
    todo_mal = A.normalizar_respuesta({"v": ["Cuesta 45000 euros."], "c": "alta", "f": [{"s": "F1"}], "b": True}, {"F1": _res(1, "x.md")}, set(), 100, BASE)
    assert todo_mal["vinetas"] == [A.SIN_BASE] and todo_mal["sin_base"]


def test_como_mucho_tres_vinetas_cortas_y_una_salida_mal_formada_es_un_error():
    d = {"v": [f"Punto {i} " + "palabra " * 40 for i in range(6)], "c": "alta", "f": [], "b": True}
    r = A.normalizar_respuesta(d, {}, set(), 100, BASE)
    assert len(r["vinetas"]) == 3 and all(len(v) <= A.LIM_VINETA + 25 for v in r["vinetas"])
    for malo in (None, [], {"v": "texto"}, {"v": []}, {"v": [1, 2]}):
        with pytest.raises(ValueError):
            A.normalizar_respuesta(malo, {}, set(), 100, BASE)


def test_consejos_tipo_valido_sin_duplicados_sin_cifras_inventadas_y_con_tope():
    d = {"k": [{"t": "pregunta", "a": "Pregunta quién valida el catálogo de hoteles antes del piloto", "p": "Sin catálogo no hay piloto", "m": "00:10"},
               {"t": "magia", "a": "Haz algo mágico ahora mismo", "p": "porque sí", "m": "00:11"},
               {"t": "riesgo", "a": "Avisa del riesgo de retraso por el catálogo de hoteles", "p": "Depende de un tercero", "m": "99:00"},
               {"t": "cierre", "a": "Propón cerrar el piloto con 4500 horas", "p": "Hay urgencia", "m": "00:20"}]}
    r = A.normalizar_consejos(d, 60, ["Pregunta quién valida el catálogo de hoteles antes del piloto Sin catálogo"], "catálogo de hoteles piloto")
    assert [c["tipo"] for c in r] == ["riesgo"] and r[0]["minuto"] == "01:00"                       # duplicado, tipo falso y cifra inventada fuera; minuto futuro acotado
    otro = A.normalizar_consejos({"k": [{"t": "valor", "a": "Ofrece una demo del informe semanal en Power BI", "p": "Lo pidió el cliente", "m": "00:05"}] * 3}, 60, [])
    assert len(otro) == 1                                                                           # tres iguales = uno
    assert len(A.normalizar_consejos({"k": [{"t": "valor", "a": f"Acción distinta número {i} sobre algo diferente {i}x", "p": "porque sí y ya", "m": "00:05"} for i in range(5)]}, 60, [])) <= 2


# ================================================================ búsqueda web: solo si el usuario la marca, consultas genéricas y sin nombres
def test_el_prompt_de_la_web_exige_consultas_genericas_y_sin_el_ruido_de_nombres():
    con = A.sistema_profundizar("una respuesta sugerida", True)
    sin = A.sistema_profundizar("una respuesta sugerida", False)
    assert "BÚSQUEDA WEB" in con and "GENÉRICAS" in con and "NO contendrán nombres del cliente" in con and "importes" in con and '"w"' in con
    assert "BÚSQUEDA WEB" not in sin and '"w"' not in sin and "No tienes herramientas y no ejecutas" in sin


def test_la_anonimizacion_quita_cliente_personas_importes_y_correos():
    texto = ("Nordia quiere pagar 45.000 € por la licencia; Pablo Ruiz, el project manager, dice que escriba a pablo@example.com. "
             "Hay que integrar con Fabric y Power BI en https://nordia.example/x. Presupuesto: 120 mil euros y 1500000.")
    out = A.anonimizar_para_web(texto, ["Nordia", "Planificador de Grupos", "Marcos Vidal"])
    for prohibido in ("Nordia", "nordia", "Pablo", "Ruiz", "45.000", "120 mil", "1500000", "@", "https://"):
        assert prohibido not in out, prohibido
    assert "Fabric" in out and "Power BI" in out


def test_las_urls_de_la_web_solo_con_la_web_habilitada_y_limpias():
    lista = [{"u": "https://learn.microsoft.com/es-es/fabric/x", "t": "Docs"}, {"u": "javascript:alert(1)", "t": "mal"}, {"u": "http://u:p@evil.com/", "t": "cred"},
             {"u": "https://learn.microsoft.com/es-es/fabric/x", "t": "repetida"}, {"u": "no es url", "t": ""}]
    assert A.normalizar_web(lista, True) == [{"u": "https://learn.microsoft.com/es-es/fabric/x", "t": "Docs"}]
    assert A.normalizar_web(lista, False) == []


def test_el_comando_de_claude_solo_habilita_la_web_cuando_se_pide():
    sin = CLI.construir_comando("claude", "sis", "haiku")
    assert sin[sin.index("--tools") + 1] == "" and "--allowedTools" not in sin and "WebSearch" not in sin
    con = CLI.construir_comando("claude", "sis", "sonnet", "low", web=True)
    assert con[con.index("--tools") + 1] == "WebSearch" and con[con.index("--allowedTools") + 1] == "WebSearch"
    assert "--strict-mcp-config" in con and "--no-session-persistence" in con and "--disable-slash-commands" in con     # el resto de aislamiento no cambia


def test_la_capacidad_web_se_lee_de_claude_help(monkeypatch):
    class P:
        stdout, stderr = "  --tools <tools...>  ...\n  --allowedTools, --allowed-tools <tools...>", ""
    monkeypatch.setattr(CLI.subprocess, "run", lambda *a, **k: P())
    assert CLI.capacidad_web("claude", forzar=True) == (True, "")
    P.stdout = "  --model <m>"
    ok, motivo = CLI.capacidad_web("claude", forzar=True)
    assert not ok and "--tools" in motivo
    CLI._CAPACIDAD_WEB.clear()


# ================================================================ flujo completo en el gestor con modelo falso
class Falso(ModeloLLM):
    """Responde a cada tarea con lo suyo y deja constancia de cada llamada (modelo, web, hilos) y de que nunca se solapan."""

    def __init__(self, espera=0.0):
        self.llamadas, self.intervalos, self.espera = [], [], espera
        self.respuesta = {"v": ["Hasta 3 usuarios por hotel."], "c": "alta", "f": [{"s": "F1"}], "b": True}
        self.consejos = {"k": [{"t": "pregunta", "a": "Pregunta quién entrega el catálogo de hoteles y cuándo", "p": "El piloto depende de ese fichero", "m": "00:10"}]}
        self.profundo = {"v": ["Primero, confirma el límite de usuarios.", "Después, ofrece ampliarlo en una fase 2."], "c": "media", "f": [{"s": "F1"}], "b": True,
                         "w": [{"u": "https://learn.microsoft.com/fabric/x", "t": "Docs de Fabric"}]}
        self.error_en = None
        self._l = threading.Lock()

    def completar(self, sistema, usuario, modelo, esfuerzo="", timeout_s=240, sin_razonamiento=False, web=False):
        t0 = time.monotonic()
        with self._l:
            self.llamadas.append({"sistema": sistema, "usuario": usuario, "modelo": modelo, "sin_razonamiento": sin_razonamiento, "web": web})
        if self.espera:
            time.sleep(self.espera)
        if self.error_en and self.error_en in sistema:
            raise ErrorAnalisis("otro", "El modelo no responde.", transitorio=False)
        uso = [Uso(modelo, 1500, 200)]
        if "compactar el contexto" in sistema:
            r = {"pm": "[04-plan-y-gobierno.md] Piloto el 20/01.", "fun": "[02-alcance.md] Hasta 3 usuarios por hotel.", "tec": "[03.md] CSV.", "rev": "[02-alcance.md] SAP fuera.", "checks": []}
        elif "acaba de hacer la pregunta" in sistema:
            r = self.respuesta
        elif "estratega comercial" in sistema:
            r = self.consejos
        elif "PROFUNDIZAR" in sistema:
            r = self.profundo
        elif "compañero del equipo" in sistema:
            r = {"t": [], "e": "Tema", "c": [], "o": [], "k": []}
        elif "verificar candidatas" in sistema:
            r = {"v": []}
        elif "cierre de la reunión" in sistema:
            r = {"resumen": "Resumen final.", "cambios": []}
        else:
            raise AssertionError("prompt inesperado: " + sistema[:80])
        with self._l:
            self.intervalos.append((t0, time.monotonic()))
        return Respuesta(json.dumps(r), uso, 10)

    def de(self, marca):
        return [x for x in self.llamadas if marca in x["sistema"]]


@pytest.fixture
def montaje(tmp_path):
    raiz = tmp_path / "proyectos"
    shutil.copytree(PRUEBAS, raiz)
    g = Guardian(raiz, tmp_path / "bandeja", tmp_path / "cache")
    cfg = Config(tmp_path / "config.json")
    cfg.actualizar({"raiz_proyectos": str(raiz), "knowledge": ""}, guardar=False)
    eventos, llm = [], Falso()
    gestor = Gestor(cfg, g, Consumo(None), llm, eventos.append, simulacion=[LineaSim(9999.0, "yo", "fin")], velocidad=1)
    return gestor, llm, eventos, tmp_path


def run(coro):
    return asyncio.run(coro)


async def arrancar(gestor, cadencia="equipo"):
    await gestor.iniciar(PROYECTO, "Tema", cadencia)
    for t in list(gestor._tareas):
        if t is not gestor._digest_tarea:
            t.cancel()
    await asyncio.wait({gestor._digest_tarea}, timeout=10)
    await asyncio.to_thread(gestor.fuentes.listo_proyecto.wait, 10)
    gestor.reloj.fijar(0)


def dice(gestor, t, texto, fuente="reunion"):
    gestor._agregar(t, fuente, texto)


async def esperar(cond, t=10):
    for _ in range(int(t / 0.02)):
        if cond():
            return
        await asyncio.sleep(0.02)
    raise AssertionError("tiempo agotado")


async def paso(gestor, t):
    """Fija el reloj, hace una pasada del asesor y espera a que acabe lo que lance (respuesta y, si toca, la afinación con sonnet)."""
    gestor.reloj.fijar(t)
    lanzado = gestor._asesor_paso()
    if lanzado:
        await esperar(lambda: not gestor.asesor.en_curso and all(r["estado"] != "en_curso" and r["escalada"] not in ("pendiente", "en_curso")
                                                              for r in gestor.sesion.respuestas))
    return lanzado


def test_una_pregunta_del_cliente_da_una_respuesta_sugerida_con_fuentes_validadas(montaje):
    gestor, llm, eventos, _ = montaje

    async def go():
        await arrancar(gestor)
        dice(gestor, 10, "Vale. ¿Cuántos usuarios puede tener cada hotel en el portal?")
        assert await paso(gestor, 11)
        r = gestor.sesion.respuestas[0]
        assert r["estado"] == "ok" and r["pregunta"] == "¿Cuántos usuarios puede tener cada hotel en el portal?" and r["minuto"] == "00:10"
        assert r["vinetas"] == ["Hasta 3 usuarios por hotel."] and r["confianza"] == "alta" and r["canal"] == "Reunión"
        assert r["citas"] and r["citas"][0]["fuente"] == "02-alcance.md"                     # F1 = el extracto mejor puntuado, que es el del alcance
        c = llm.de("acaba de hacer la pregunta")
        assert len(c) == 1 and c[0]["modelo"] == "haiku" and c[0]["sin_razonamiento"] is True and not c[0]["web"]
        assert "<<<DATOS fuente F1: 02-alcance.md>>>" in c[0]["usuario"] and "<<<DATOS pregunta>>>" in c[0]["usuario"]
        assert "dato no fiable" in c[0]["sistema"].lower() and "NUNCA inventes" in c[0]["sistema"]
        assert any(e["tipo"] == "asesor" and e["respuestas"] for e in eventos)
        assert gestor.snapshot()["asesor"]["respuestas"][0]["id"] == "r1"
        assert r["escalada"] == "" and not llm.de("acaba de hacer") == [] and len(llm.llamadas) >= 2
    run(go())


def test_una_pregunta_sin_base_en_las_fuentes_dice_que_no_hay_base(montaje):
    gestor, llm, *_ = montaje
    llm.respuesta = {"v": ["Cuesta 45000 euros."], "c": "alta", "f": [{"s": "F1"}], "b": False}

    async def go():
        await arrancar(gestor)
        dice(gestor, 10, "¿Qué servicio de correo envía el mail al crear una inversión?")
        await paso(gestor, 11)
        r = gestor.sesion.respuestas[0]
        assert r["vinetas"] == [A.SIN_BASE] and r["confianza"] == "baja" and r["sin_base"] and r["citas"] == []
    run(go())


def test_el_limite_de_una_respuesta_cada_20_s_y_gana_la_mas_reciente(montaje):
    gestor, llm, *_ = montaje

    async def go():
        await arrancar(gestor)
        dice(gestor, 10, "¿Cuántos usuarios puede tener cada hotel?")
        assert await paso(gestor, 10)                                   # la primera sale al momento
        dice(gestor, 12, "¿Qué entra en la primera fase del proyecto exactamente?")
        dice(gestor, 14, "¿Quién entrega el catálogo de hoteles al principio del piloto?")
        assert not await paso(gestor, 15)                               # 5 s después: dentro del límite, no se lanza
        assert gestor.asesor.pendiente["pregunta"] == "¿Quién entrega el catálogo de hoteles al principio del piloto?"   # la más reciente sustituyó a la otra
        assert gestor.asesor.stats["sustituidas"] == 1
        assert await paso(gestor, 31)                                   # pasados los 20 s se responde la más reciente
        assert [r["pregunta"] for r in gestor.sesion.respuestas] == ["¿Cuántos usuarios puede tener cada hotel?", "¿Quién entrega el catálogo de hoteles al principio del piloto?"]
        assert len(llm.de("acaba de hacer la pregunta")) == 2
    run(go())


def test_la_misma_pregunta_en_micro_y_reunion_se_responde_una_vez(montaje):
    gestor, llm, *_ = montaje

    async def go():
        await arrancar(gestor)
        gestor.sesion.filtrar_eco = False                               # sin el filtro de eco (que ya quitaría el Micro repetido) se ve la deduplicación del asesor
        dice(gestor, 10, "¿Cómo manda un mail desde Fabric cuando crean una inversión?")
        dice(gestor, 10, "¿Y cómo manda un mail por Fabric cuando crean la inversión?", "yo")
        gestor.reloj.fijar(80)                                          # el Micro ya no espera a su pareja de Reunión
        gestor.asesor.observar()
        assert gestor.asesor.stats["detectadas"] == 1 and gestor.asesor.stats["duplicadas"] == 1
    run(go())


def test_una_pregunta_que_lleva_mucho_esperando_caduca(montaje):
    gestor, llm, *_ = montaje

    async def go():
        await arrancar(gestor)
        dice(gestor, 10, "¿Cuántos usuarios puede tener cada hotel?")
        gestor.reloj.fijar(11)
        gestor.asesor.observar()
        gestor.asesor.ultimo_lanzamiento = 5
        gestor.reloj.fijar(500)
        assert gestor.asesor.siguiente() is None and gestor.asesor.stats["caducadas"] == 1 and not gestor.sesion.respuestas
    run(go())


def test_la_respuesta_se_adelanta_a_un_turno_del_equipo_en_la_cola(montaje):
    """Con una llamada en curso, entran en la cola un turno del equipo y después una respuesta al cliente: la respuesta pasa primero (siguen en serie)."""
    gestor, llm, *_ = montaje
    llm.espera = 0.15

    async def go():
        await arrancar(gestor)
        dice(gestor, 5, "Para el viernes se encarga Ana de enviar el fichero. " + "palabra " * 130)
        dice(gestor, 6, "¿Cuántos usuarios puede tener cada hotel?")
        gestor.reloj.fijar(250)
        gestor.equipo._ultima_comprobacion = -1e9
        n0 = len(llm.llamadas)
        gestor.sonda._turno.adquirir(0)                                 # una llamada «en curso»
        await gestor._vigilar()                                         # el Monitor elige al Coordinador: su turno queda esperando el cerrojo
        await esperar(lambda: gestor.sonda._turno.esperando() >= 1)
        gestor.reloj.fijar(251)
        assert gestor._asesor_paso()                                    # y la respuesta al cliente llega después, pero con prioridad
        await esperar(lambda: gestor.sonda._turno.esperando() >= 2)
        gestor.sonda._turno.liberar()
        await esperar(lambda: len(llm.llamadas) >= n0 + 2 and gestor.equipo.en_curso is None and not gestor.asesor.en_curso)
        orden = [("respuesta" if "acaba de hacer la pregunta" in x["sistema"] else "equipo" if "compañero del equipo" in x["sistema"] else "otra") for x in llm.llamadas[n0:]]
        assert orden[:2] == ["respuesta", "equipo"]
        s = llm.intervalos[-3:]
        assert all(a[1] <= b[0] + 1e-3 for a, b in zip(s, s[1:]))      # nunca dos a la vez
    run(go())


def test_una_pregunta_de_precio_escala_a_sonnet_despues_de_haiku(montaje):
    gestor, llm, *_ = montaje

    async def go():
        await arrancar(gestor)
        dice(gestor, 10, "¿Cuánto cuesta ampliar el alcance con usuarios extra por hotel?")
        await paso(gestor, 11)
        r = gestor.sesion.respuestas[0]
        modelos = [x["modelo"] for x in llm.de("acaba de hacer la pregunta")]
        assert modelos == ["haiku", "sonnet"]                                                    # haiku primero, sonnet después
        assert r["escalada"] == "hecha" and r["modelo"] == "sonnet" and r["previa"]["modelo"] == "haiku" and r["temas"] == ["precio", "alcance"]
        assert "no prometas ni confirmes importes" in llm.de("acaba de hacer la pregunta")[0]["sistema"]
        assert gestor.asesor.sonnet_usados() == 1
    run(go())


def test_el_limite_de_sonnet_por_hora_y_el_presupuesto_del_asesor(montaje, monkeypatch):
    gestor, llm, *_ = montaje
    assert CF.ASESOR_SONNET_HORA == 8
    import apuntes.asesor_directo as AD
    monkeypatch.setattr(AD, "ASESOR_SONNET_HORA", 1)

    async def go():
        await arrancar(gestor)
        dice(gestor, 10, "¿Cuánto cuesta ampliar el alcance con usuarios extra por hotel?")
        await paso(gestor, 11)
        dice(gestor, 40, "¿Cuándo podéis entregar la fase dos del catálogo de hoteles?")
        await paso(gestor, 41)
        r1, r2 = gestor.sesion.respuestas
        assert r1["escalada"] == "hecha" and r2["escalada"] == "limite" and r2["modelo"] == "haiku"      # la segunda se queda con haiku y lo dice
        assert [x["modelo"] for x in llm.de("acaba de hacer la pregunta")] == ["haiku", "sonnet", "haiku"]
        # presupuesto propio: al 100 % el asesor no responde solo, y el del equipo no se toca
        gestor.asesor.presupuesto.sumar(41, 10 ** 6)
        assert gestor.asesor.nivel() == "agotado" and gestor.equipo.nivel() == "normal"
        dice(gestor, 80, "¿Qué usuarios entran en el alcance de la primera fase?")
        gestor.reloj.fijar(81)
        assert not gestor._asesor_paso() and gestor.asesor.stats["sin_presupuesto"] == 1 and len(gestor.sesion.respuestas) == 2
    run(go())


def test_los_tokens_del_asesor_cuentan_en_su_presupuesto_y_no_en_el_del_equipo(montaje):
    gestor, llm, *_ = montaje

    async def go():
        await arrancar(gestor)
        antes = gestor.equipo.presupuesto.total()
        dice(gestor, 10, "¿Cuántos usuarios puede tener cada hotel?")
        await paso(gestor, 11)
        assert gestor.asesor.presupuesto.total() == 1700 and gestor.equipo.presupuesto.total() == antes
        assert gestor.sesion.respuestas[0]["tokens"] == 1700
    run(go())


def test_un_fallo_del_modelo_se_ve_en_la_tarjeta_y_no_detiene_nada(montaje):
    gestor, llm, *_ = montaje
    llm.error_en = "acaba de hacer la pregunta"

    async def go():
        await arrancar(gestor)
        dice(gestor, 10, "¿Cuántos usuarios puede tener cada hotel?")
        await paso(gestor, 11)
        r = gestor.sesion.respuestas[0]
        assert r["estado"] == "error" and "no responde" in r["error"] and not gestor.asesor.en_curso and gestor.estado == "grabando"
        assert len(llm.de("acaba de hacer la pregunta")) == 1                                    # sin reintentos
    run(go())


def test_con_el_asesor_apagado_no_se_detecta_ni_se_llama(montaje):
    gestor, llm, *_ = montaje
    gestor.cfg.actualizar({"asesor_activo": False}, guardar=False)

    async def go():
        await arrancar(gestor)
        dice(gestor, 10, "¿Cuántos usuarios puede tener cada hotel?")
        assert not await paso(gestor, 11) and not gestor.sesion.respuestas and not llm.de("acaba de hacer")
    run(go())


# ---------------------------------------------------------------- el Estratega (quinto perfil)
def test_el_estratega_lo_elige_el_monitor_con_senales_estrategicas_y_da_consejos(montaje):
    gestor, llm, eventos, _ = montaje

    async def go():
        await arrancar(gestor)
        dice(gestor, 5, "El precio de la licencia y el plazo de entrega nos preocupan; necesitamos cerrar la oferta pronto. " + "palabra " * 130)
        gestor.reloj.fijar(400)
        gestor.equipo._ultima_comprobacion = -1e9
        await gestor._vigilar()
        await esperar(lambda: gestor.equipo.en_curso is None and gestor.equipo.eligiendo is None)
        await esperar(lambda: gestor.sesion.consejos or llm.de("estratega comercial"))
        await esperar(lambda: gestor.equipo.en_curso is None)
        c = gestor.sesion.consejos
        assert len(c) == 1 and c[0]["tipo"] == "pregunta" and c[0]["etiqueta"] == "Siguiente pregunta" and c[0]["id"] == "c1"
        llamadas = llm.de("estratega comercial")
        assert len(llamadas) == 1 and llamadas[0]["modelo"] == "sonnet"                           # precio + plazos + contexto estratégico: sonnet
        pub = gestor.equipo.publico()
        e = next(p for p in pub["perfiles"] if p["id"] == "estratega")
        assert e["nombre"] == "Estratega" and e["turno"]["tarjetas"] == 1 and e["aporte"]["texto"].startswith("Pregunta quién entrega")
        assert gestor.asesor.sonnet_usados() == 1
        assert any(ev["tipo"] == "asesor" and ev["consejos"] for ev in eventos)
    run(go())


def test_el_estratega_usa_haiku_si_no_hay_senales_estrategicas_y_no_repite(montaje):
    gestor, llm, *_ = montaje

    async def go():
        await arrancar(gestor)
        dice(gestor, 5, "Hablamos de la pantalla de reservas y del calendario de disponibilidad por hotel. " + "palabra " * 220)
        gestor.reloj.fijar(500)                                              # rotación: ≥480 s y ≥200 palabras nuevas, sin señales estratégicas
        gestor.equipo._ultima_comprobacion = -1e9
        gestor.equipo.comprobar(500, False)                                  # una pasada del Monitor (local) para que cuente las palabras
        assert gestor.equipo.monitor.elegir_estratega(500, "normal", 360) == ("estratega", "rotación")
        res = await gestor.equipo.turno_estratega("rotación")
        assert res["ok"] and [x["modelo"] for x in llm.de("estratega comercial")] == ["haiku"] and len(gestor.sesion.consejos) == 1
        # el mismo consejo en otro turno no se repite
        dice(gestor, 600, "Seguimos con la pantalla de reservas. " + "palabra " * 220)
        gestor.reloj.fijar(900)
        res = await gestor.equipo.turno_estratega("rotación")
        assert res["ok"] and len(llm.de("estratega comercial")) == 2 and len(gestor.sesion.consejos) == 1
    run(go())


def test_el_estratega_tiene_enfriamiento_y_presupuesto_propios_y_tope_de_consejos(montaje):
    gestor, llm, *_ = montaje
    m = gestor.equipo.monitor

    async def go():
        await arrancar(gestor)
        m.estratega.update(puntos=4, palabras_desde=200)
        assert m.elegir_estratega(1000, "normal", 360)[0] == "estratega" and m.elegir_estratega(1000, "agotado", 360)[0] is None
        m.estratega.update(hubo_turno=True, ultimo_turno=900)
        assert m.elegir_estratega(1000, "normal", 360)[0] is None                         # 100 s < 360 s
        assert m.elegir_estratega(1300, "ahorro", 360)[0] is None and m.elegir_estratega(1300, "normal", 360)[0] == "estratega"   # el doble al 80 %
        m.ultima_llamada = 1290
        assert m.elegir_estratega(1300, "normal", 360)[0] is None                         # no pegado a la llamada de otro perfil
        gestor.cfg.actualizar({"asesor_max_consejos": 0}, guardar=False)
        dice(gestor, 5, "algo nuevo " * 100)
        res = await gestor.equipo.turno_estratega("x")
        assert res.get("omitido") and not llm.de("estratega comercial")
    run(go())


# ---------------------------------------------------------------- «Profundizar», fijar y descartar
def test_profundizar_hace_una_llamada_sonnet_con_mas_extractos_y_sin_web_por_defecto(montaje):
    gestor, llm, *_ = montaje

    async def go():
        await arrancar(gestor)
        dice(gestor, 10, "¿Cuántos usuarios puede tener cada hotel en el portal?")
        await paso(gestor, 11)
        n0 = len(llm.llamadas)
        res = await gestor.asesor.profundizar("r1")
        assert res["ok"]
        nuevas = llm.llamadas[n0:]
        assert len(nuevas) == 1 and nuevas[0]["modelo"] == "sonnet" and nuevas[0]["web"] is False and "PROFUNDIZAR" in nuevas[0]["sistema"]
        assert "BÚSQUEDA WEB" not in nuevas[0]["sistema"]
        corta = llm.de("acaba de hacer la pregunta")[0]["usuario"].count("<<<DATOS fuente")
        assert nuevas[0]["usuario"].count("<<<DATOS fuente") >= corta                                     # más extractos que la respuesta corta
        p = gestor.sesion.respuestas[0]["profundizada"]
        assert p["estado"] == "ok" and not p["web"] and p["vinetas"][0].startswith("Primero") and p["web_urls"] == []     # sin web, el modelo no puede colar URLs
        with pytest.raises(ValueError, match="Ya se está profundizando"):
            gestor.sesion.respuestas[0]["profundizada"]["estado"] = "en_curso"
            await gestor.asesor.profundizar("r1")
    run(go())


def test_profundizar_con_web_anonimiza_lo_que_viaja_y_devuelve_urls(montaje, monkeypatch):
    gestor, llm, *_ = montaje
    monkeypatch.setattr(CLI, "_CAPACIDAD_WEB", {"r": (True, "")})

    async def go():
        await arrancar(gestor)
        dice(gestor, 10, "¿Cuántos usuarios puede tener cada hotel en el portal del Proyecto Ficticio Alfa de Pablo Ruiz por 45.000 €?")
        await paso(gestor, 11)
        n0 = len(llm.llamadas)
        res = await gestor.asesor.profundizar("r1", web=True)
        assert res["ok"]
        c = llm.llamadas[n0]
        assert c["web"] is True and c["modelo"] == "sonnet" and "BÚSQUEDA WEB" in c["sistema"]
        for prohibido in ("Proyecto Ficticio Alfa", "Ficticio", "Pablo", "Ruiz", "45.000"):
            assert prohibido not in c["usuario"], prohibido
        assert gestor.sesion.respuestas[0]["profundizada"]["web"] and gestor.sesion.respuestas[0]["profundizada"]["web_urls"] == [
            {"u": "https://learn.microsoft.com/fabric/x", "t": "Docs de Fabric"}]
    run(go())


def test_la_web_no_se_ofrece_si_claude_no_la_permite_ni_si_la_config_la_apaga(montaje, monkeypatch):
    gestor, llm, *_ = montaje
    monkeypatch.setattr(CLI, "_CAPACIDAD_WEB", {"r": (False, "Esta versión de `claude -p` no permite habilitar solo la búsqueda web.")})

    async def go():
        await arrancar(gestor)
        dice(gestor, 10, "¿Cuántos usuarios puede tener cada hotel en el portal?")
        await paso(gestor, 11)
        n0 = len(llm.llamadas)
        with pytest.raises(ValueError, match="no permite habilitar"):
            await gestor.asesor.profundizar("r1", web=True)
        assert len(llm.llamadas) == n0 and gestor.sesion.respuestas[0]["profundizada"] is None
        assert gestor.asesor.estado_publico()["web"]["disponible"] is False
        monkeypatch.setattr(CLI, "_CAPACIDAD_WEB", {"r": (True, "")})
        gestor.asesor._web = None
        gestor.cfg.actualizar({"asesor_web": False}, guardar=False)
        with pytest.raises(ValueError, match="desactivada"):
            await gestor.asesor.profundizar("r1", web=True)
    run(go())


def test_fijar_y_descartar_se_ven_en_el_md_y_no_gastan(montaje):
    gestor, llm, *_ = montaje

    async def go():
        await arrancar(gestor)
        dice(gestor, 10, "¿Cuántos usuarios puede tener cada hotel en el portal?")
        await paso(gestor, 11)
        n0 = len(llm.llamadas)
        gestor.asesor.marcar("r1", "fijar", True)
        assert gestor.sesion.respuestas[0]["fijada"] and "fijada" in gestor.sesion.render()
        gestor.asesor.marcar("r1", "descartar", True)
        assert gestor.sesion.respuestas[0]["descartada"] and not gestor.sesion.respuestas[0]["fijada"] and "Pregunta del cliente" not in gestor.sesion.render()
        with pytest.raises(ValueError):
            gestor.asesor.marcar("r99", "fijar", True)
        assert len(llm.llamadas) == n0
    run(go())


# ---------------------------------------------------------------- al .md, al resumen final y al backlog
def test_el_md_lleva_la_seccion_asesor_el_resumen_final_el_bloque_y_el_backlog_lo_ve_como_consejo(montaje, tmp_path):
    gestor, llm, *_ = montaje

    async def go():
        await arrancar(gestor)
        dice(gestor, 10, "¿Cuántos usuarios puede tener cada hotel en el portal?")
        await paso(gestor, 11)
        dice(gestor, 20, "El plazo y el precio nos preocupan, necesitamos cerrar. " + "palabra " * 130)
        gestor.reloj.fijar(400)
        gestor.equipo._ultima_comprobacion = -1e9
        await gestor._vigilar()
        await esperar(lambda: gestor.equipo.en_curso is None and gestor.equipo.eligiendo is None)
        await esperar(lambda: gestor.sesion.consejos)
        await gestor.asesor.profundizar("c1")
        md = gestor.sesion.render()
        assert "## Asesor" in md and "### Respuestas sugeridas" in md and "### Consejos" in md
        assert "**Pregunta del cliente:** ¿Cuántos usuarios puede tener cada hotel en el portal?" in md and "Hasta 3 usuarios por hotel." in md
        assert "confianza alta" in md and "fuentes: 02-alcance.md" in md and "Profundizado" in md
        assert "**Consejo (siguiente pregunta):** Pregunta quién entrega el catálogo de hoteles y cuándo — por qué: El piloto depende de ese fichero" in md
        bloque = gestor._bloques_finales()
        assert "## Respuestas sugeridas y consejos" in bloque and "Siguiente pregunta" in bloque and "¿Cuántos usuarios" in bloque
        # el backlog lee la sección «Asesor» y muestra los consejos como tipo «Consejo»
        p = BL.parsear_sesion(md, "2026-11-05-prueba.md", PROYECTO)
        consejos = [i for i in p["items"] if i["tipo"] == "consejo"]
        assert len(consejos) == 1 and consejos[0]["texto"].startswith("Pregunta quién entrega el catálogo") and consejos[0]["minuto"] == "00:10"
        assert BL.ETIQUETA["consejo"] == "Consejo" and "consejo" in BL.TIPOS
    run(go())


def test_la_revision_final_incluye_respuestas_y_consejos(montaje):
    gestor, llm, *_ = montaje

    async def go():
        await arrancar(gestor)
        dice(gestor, 10, "¿Cuántos usuarios puede tener cada hotel en el portal?")
        await paso(gestor, 11)
        await gestor.terminar()
        await esperar(lambda: gestor.revision and gestor.revision["estado"] in ("lista", "error"), 20)
        assert gestor.revision["estado"] == "lista"
        assert "## Respuestas sugeridas y consejos" in gestor.revision["resumen"] and "Cuántos usuarios" in gestor.revision["resumen"]
    run(go())


# ---------------------------------------------------------------- la API
def test_api_del_asesor(montaje, tmp_path):
    from fastapi.testclient import TestClient
    from apuntes.servidor import Difusor, crear_app
    gestor, llm, _, tmp = montaje
    difusor = Difusor()
    gestor._emitir = difusor.emitir
    app = crear_app(gestor, difusor, gestor.cfg, gestor.g, "tok", 8124)
    cli = TestClient(app, headers={"X-Token": "tok", "host": "127.0.0.1:8124"}, base_url="http://127.0.0.1:8124")

    async def preparar():
        await arrancar(gestor)
        dice(gestor, 10, "¿Cuántos usuarios puede tener cada hotel en el portal?")
        await paso(gestor, 11)
    with cli:
        loop = asyncio.new_event_loop()
        gestor._loop = loop
        loop.run_until_complete(preparar())
        loop.close()
        d = cli.get("/api/asesor").json()
        assert d["respuestas"][0]["id"] == "r1" and d["sonnet"]["limite"] == 8 and "web" in d and d["presupuesto"]["limite"] == 100000
        assert cli.post("/api/asesor/r1/fijar", json={"valor": True}).json()["fijada"] is True
        assert cli.post("/api/asesor/r1/descartar", json={"valor": True}).json()["descartada"] is True
        assert cli.post("/api/asesor/x1/fijar", json={"valor": True}).status_code == 404
        assert cli.post("/api/asesor/r7/fijar", json={"valor": True}).status_code == 400          # no existe
        assert cli.post("/api/asesor/../profundizar", json={}).status_code in (404, 405)


# ---------------------------------------------------------------- lo dicho antes en esta reunión también es una fuente; sin pista, sin llamada
def test_hay_pista_pide_una_palabra_con_contenido_en_comun_sin_contar_la_propia_pregunta():
    digest = "Plan y fechas: piloto el 20 de enero. Alcance: hasta 3 usuarios por hotel."
    reciente = "[00:10] R: hablamos del catálogo de hoteles\n[00:40] R: ¿Qué tiempo hará en Valencia mañana por la tarde?"
    assert A.hay_pista("¿Cuántos usuarios puede tener cada hotel?", digest, reciente)
    assert A.hay_pista("¿Quién entrega el catálogo de hoteles?", digest, reciente)
    assert not A.hay_pista("¿Qué tiempo hará en Valencia mañana por la tarde?", digest, reciente)      # la línea de la propia pregunta no cuenta
    assert not A.hay_pista("¿Cómo lo ves?", digest, reciente) and A.respuesta_sin_base_local()["vinetas"] == [A.SIN_BASE]


def test_sin_fuentes_ni_pista_se_responde_en_local_sin_gastar_una_llamada(montaje):
    gestor, llm, *_ = montaje

    async def go():
        await arrancar(gestor)
        dice(gestor, 10, "Hablamos del calendario de reservas por hotel.")
        dice(gestor, 20, "¿Qué previsión meteorológica tendremos mañana en Valencia?")
        await paso(gestor, 21)
        r = gestor.sesion.respuestas[0]
        assert r["estado"] == "ok" and r["vinetas"] == [A.SIN_BASE] and r["modelo"] == "local" and r["tokens"] == 0 and r["sin_base"] and r["confianza"] == "baja"
        assert not llm.de("acaba de hacer la pregunta") and gestor.asesor.stats["sin_pista_local"] == 1 and not gestor.asesor.en_curso
    run(go())


def test_lo_dicho_hace_mucho_en_esta_reunion_se_busca_y_se_cita_por_su_minuto(montaje):
    gestor, llm, *_ = montaje
    llm.respuesta = {"v": ["Era empezar el presupuesto con la herramienta el 15 de noviembre."], "c": "media", "f": [{"s": "F1", "m": "00:10"}, {"s": "F1", "m": "99:00"}], "b": True}

    async def go():
        await arrancar(gestor)
        dice(gestor, 10, "El objetivo era empezar a hacer el presupuesto con esta herramienta el 15 de noviembre.")
        for i in range(60):       # mucho después: la frase ya no cabe en la ventana reciente que viaja con la pregunta
            dice(gestor, 20 + i * 5, f"Seguimos con otra cosa distinta, tema número {i}, hablando de pantallas, colores y permisos varios del portal.")
        dice(gestor, 400, "¿Se cumple el objetivo del presupuesto con la herramienta?")
        await paso(gestor, 401)
        r = gestor.sesion.respuestas[0]
        u = llm.de("acaba de hacer la pregunta")[0]["usuario"]
        assert "<<<DATOS fuente F1: Esta reunión>>>" in u and "[00:10] R: El objetivo era empezar" in u.split("<<<DATOS fuente F1")[1].split("<<<FIN>>>")[0]
        assert "[00:10] R: El objetivo era" not in u.split("<<<DATOS transcripcion_reciente>>>")[1]            # y no está en lo reciente: solo llega por la búsqueda
        assert r["citas"] == [{"minuto": "00:10", "t_seg": 10, "tipo": "reunion"}] and r["confianza"] == "media"      # el minuto futuro (99:00) se descarta
    run(go())


def test_las_letras_de_canal_no_se_ensenan_y_la_web_admite_orientaciones_de_sector():
    assert A.sin_letras_de_canal("Según R en 14:25 y M dijo; R&D, 100 M€, el lenguaje R2") == "Según el cliente en 14:25 y el micro dijo; R&D, 100 M€, el lenguaje R2"
    r = A.normalizar_consejos({"k": [{"t": "pregunta", "a": "Pregunta al cliente qué quiere resolver primero con la demo", "p": "Lo pidió R en 14:25 al empezar", "m": "00:10"}]}, 60, [], "[14:25] R: empezamos")
    assert r[0]["porque"] == "Lo pidió el cliente en 14:25 al empezar"
    d = {"v": [A.SIN_BASE, "Orientación general (web): Microsoft Graph permite enviar correo con el permiso Mail.Send en 25 pasos.", "Orientación general (web): también Azure Communication Services.",
               "Orientación general (web): o Power Automate.", "Orientación general (web): una cuarta que sobra."], "c": "baja", "f": [], "b": False}
    web = A.normalizar_respuesta(d, {}, set(), 100, BASE, profundo=True, comprobar_cifras=False, orientaciones=3)
    assert web["vinetas"][0] == A.SIN_BASE and len(web["vinetas"]) == 4 and web["orientacion"] and web["confianza"] == "baja"
    sin_web = A.normalizar_respuesta(d, {}, set(), 100, BASE, profundo=True)
    assert sin_web["vinetas"] == [A.SIN_BASE, "Orientación general (web): también Azure Communication Services."]   # sin web: la que lleva una cifra se descarta y solo cabe una


def test_la_pregunta_lleva_lo_que_la_precede_en_su_misma_frase():
    r = A.detectar_con_antecedente("Nos gustaría una segunda fase con el informe de ocupación, ¿lo veis posible? Otra cosa: ¿cuánto cuesta?")
    assert r == [("¿lo veis posible?", "Nos gustaría una segunda fase con el informe de ocupación"), ("¿cuánto cuesta?", "Otra cosa")]
    assert A.detectar_preguntas("Nos gustaría una segunda fase con el informe de ocupación, ¿lo veis posible?") == ["¿lo veis posible?"]
    assert "Nos gustaría una segunda fase" in A.usuario_respuesta("¿lo veis posible?", "06:00", "R", "", [], "", "06:05", "Nos gustaría una segunda fase")
    assert A.usuario_respuesta("¿lo veis posible?", "06:00", "R", "", [], "", "06:05").endswith("R: ¿lo veis posible?\n<<<FIN>>>")


def test_el_md_con_una_profundizacion_con_web_lleva_las_urls_y_no_falla(montaje, monkeypatch):
    gestor, llm, *_ = montaje
    monkeypatch.setattr(CLI, "_CAPACIDAD_WEB", {"r": (True, "")})

    async def go():
        await arrancar(gestor)
        dice(gestor, 10, "¿Cuántos usuarios puede tener cada hotel en el portal?")
        await paso(gestor, 11)
        assert (await gestor.asesor.profundizar("r1", web=True))["ok"]
        md = gestor.sesion.render()                         # antes de arreglarlo, `web` (bool) y `web_urls` (lista) se confundían y guardar la sesión fallaba
        assert "Profundizado (con búsqueda web):" in md and "    - Web: https://learn.microsoft.com/fabric/x" in md
        assert "No se pudo guardar" not in " ".join(gestor.avisos)
    run(go())
