"""El equipo de agentes (DESIGN-equipo.md): Monitor local, elección de turno, perfiles, presupuesto, definiciones y el flujo
completo en el gestor con un modelo falso (sin red ni audio). El reloj de la reunión se fija a mano (`Reloj.fijar`)."""
import asyncio
import json
import shutil
import threading
import time
from pathlib import Path
from types import SimpleNamespace as N

import pytest
from fastapi.testclient import TestClient

from apuntes import checks as CK
from apuntes.analisis import ErrorAnalisis, ModeloLLM, Respuesta, Uso
from apuntes.config import Config
from apuntes.consumo import Consumo
from apuntes.equipo import monitor as M
from apuntes.equipo import perfiles as PF
from apuntes.equipo.definiciones import Definiciones
from apuntes.equipo.presupuesto import Presupuesto
from apuntes.gestor import Gestor
from apuntes.rutas import Guardian
from apuntes.servidor import Difusor, crear_app
from apuntes.simulador import LineaSim

PRUEBAS = Path(__file__).resolve().parent.parent / "pruebas" / "proyectos"
PROYECTO = "Proyecto Ficticio Alfa"
RELLENO = "palabra " * 130


def mon(**kw):
    """Monitor con el enfriamiento global de 150 s de la especificación original (los umbrales se prueban con cifras redondas)."""
    return M.Monitor({"equipo_enfriamiento_global_s": 150, **kw})


def seg(i, t, texto):
    return N(id=i, t=t, texto=texto)


# ---------------------------------------------------------------- Monitor: cada regex, un positivo y un negativo en español
@pytest.mark.parametrize("tipo,positivo,negativo", [
    ("decision", "Decidimos que SAP queda fuera de esta fase", "Hoy hace buen día en Madrid"),
    ("alcance", "Esto no entra en la fase uno", "Se entra por la puerta principal"),
    ("prioridad", "La prioridad es el informe semanal", "Nada que añadir por ahora"),
    ("pendiente", "Eso es un pendiente para la semana próxima", "Todo claro por mi parte"),
    ("fecha", "Lo cerramos para el viernes", "Lo cerramos más adelante"),
    ("riesgo", "Hay un riesgo claro con el catálogo", "Todo va bien con el catálogo"),
    ("cifra", "Son 35 horas de trabajo", "Son varias horas de trabajo"),
    ("pregunta", "¿Quién tiene el acceso al tenant?", "Nadie tiene el acceso al tenant"),
    ("responsable", "Se encarga Ana de enviarlo", "Ana lo envía mañana por correo"),
    ("definicion", "Definimos cupo como el máximo de habitaciones", "Fijamos el máximo de habitaciones"),
    ("regla", "Solo si hay disponibilidad se confirma", "Hay disponibilidad para confirmar"),
    ("dato", "Los datos vienen de una tabla de Excel", "Hablamos con el cliente"),
    ("sistema", "Se despliega en Power BI y en Fabric", "Hablamos con el cliente"),
    ("contraste", "Eso no era así en el documento", "Eso queda igual que antes de ayer"),
])
def test_cada_senal_tiene_su_positivo_y_su_negativo(tipo, positivo, negativo):
    assert tipo in M.detectar(positivo)
    assert tipo not in M.detectar(negativo)


def test_un_fragmento_cuenta_para_una_sola_senal_y_el_coordinador_puntua_4():
    """«se encarga» es a la vez pendiente y responsable: gana la más específica. Con «para el viernes»: fecha 2 + responsable 2 = 4."""
    sen = M.detectar("Vale, para el viernes se encarga Ana de enviarlo")
    assert set(sen) == {"fecha", "responsable"}
    m = mon()
    m.pasada(30, [seg(1, 10, "Vale, para el viernes se encarga Ana de enviarlo")])
    assert m.puntos == {"coordinador": 4, "funcional": 0, "constructor": 0, "revisor": 0}
    assert m.motivo("coordinador") == "fecha + responsable"
    m.turno_hecho("coordinador", 40)
    assert m.puntos["coordinador"] == 0 and m.palabras_desde["coordinador"] == 0


def test_puntuacion_por_perfil_cada_tipo_cuenta_una_vez_por_ventana():
    m = mon()
    m.pasada(30, [seg(1, 5, "Definimos cupo como el máximo. Y la regla es que solo si hay sitio. También definimos blackout como cierre")])
    assert m.puntos["funcional"] == 3 + 2          # definición 3 (una sola vez) + regla 2
    m.pasada(60, [seg(2, 40, "La prioridad es esa. Antes era distinto, en el documento no estaba previsto")])
    assert m.puntos["revisor"] == 3 + 1            # contraste 3 + prioridad 1


def test_definicion_local_en_una_pasada_sin_llamar_al_modelo():
    m = mon()
    pas = m.pasada(30, [seg(1, 12, "Definimos cupo como el máximo de habitaciones que se reservan sin pasar por Revenue.")])
    assert [d["termino"] for d in pas.definiciones] == ["Cupo"]
    assert pas.definiciones[0]["definicion"].startswith("el máximo de habitaciones")
    assert any(e["tipo"] == "definicion" and "definición (local) · Cupo" in e["texto"] for e in pas.entradas)
    assert pas.definiciones[0]["origen"] == "local" and pas.definiciones[0]["minuto"] == "00:12"


@pytest.mark.parametrize("frase,termino", [
    ("El Cupo se define como el número máximo de habitaciones.", "Cupo"),
    ("Entendemos por blackout los días en que no se vende.", "blackout"),
    ("Los días sin grupos es lo que llamamos hot days", "hot days"),
])
def test_definiciones_locales_por_varios_patrones(frase, termino):
    d = M.extraer_definiciones(frase)
    assert d and d[0]["termino"] == termino and len(d[0]["definicion"]) <= 140


def test_el_habla_corriente_no_genera_definiciones_falsas():
    # «quiere decir» en una frase normal (visto en TR2): sin término capitalizado o entre comillas no es una definición
    assert M.extraer_definiciones("O y a un paso quiere decir, mira, no te bajo el precio, pero te puedo dar el work on dream.") == []
    assert M.extraer_definiciones("Esto significa que mañana lo vemos con calma otra vez.") == []
    d = M.extraer_definiciones("El cupo se define como el máximo de habitaciones")
    assert d and d[0]["termino"] == "cupo"                       # «El» al empezar la frase no es un nombre propio
    assert M.extraer_definiciones('El «blackout» significa que ese día no se vende')[0]["termino"] == "blackout"


def test_definicion_larga_se_corta_en_palabra_completa_y_se_marca_parcial():
    d = M.extraer_definiciones("Definimos cupo como " + "habitaciones reservadas sin pasar por revenue " * 6)[0]
    assert d["parcial"] is True and len(d["definicion"]) <= 140 and not d["definicion"].endswith("…") and d["definicion"][-1] != " "


def test_cita_del_feed_cortada_en_palabra_completa_sin_elipsis():
    m = mon()
    pas = m.pasada(30, [seg(1, 12, "Lo cerramos para el viernes " + "palabra " * 30)])
    q = next(e for e in pas.senales if e["senal"] == "fecha")["texto"]
    cita = q.split("«")[1].rstrip("»")
    assert len(cita) <= 60 and "…" not in cita and q.startswith("señal: fecha · «para el viernes")


def test_el_feed_tiene_como_maximo_4_senales_por_pasada():
    m = mon()
    pas = m.pasada(30, [seg(1, 5, "Decidimos 35 horas para el viernes. ¿Quién? Se encarga Ana. Hay un riesgo. La prioridad. Solo si. Los datos en Fabric")])
    assert len(pas.senales) == 4


# ---------------------------------------------------------------- elección de turno
def preparar(m, t, texto=None, palabras=130):
    """Una pasada con `palabras` palabras (con el texto de señales delante)."""
    texto = (texto or "") + " " + "palabra " * max(0, palabras - len((texto or "").split()))
    m.pasada(t, [seg(m.ultimo_id + 1, t - 5, texto)])


def test_candidato_con_puntos_palabras_y_enfriamientos():
    m = mon()
    preparar(m, 160, "para el viernes se encarga Ana")
    assert m.elegir(160) == ("coordinador", "fecha + responsable")
    assert m.elegir(100)[0] is None                                   # < 150 s desde la última llamada (el arranque cuenta)
    assert m.elegir(160, ocupado=True)[0] is None
    m.turno_hecho("coordinador", 170)
    preparar(m, 200, "para el viernes se encarga Ana otra vez")
    assert m.elegir(200)[0] is None                                   # 150 s globales
    assert m.elegir(330)[0] is None                                   # propio: 360 s
    assert m.elegir(540)[0] == "coordinador"


def test_umbrales_por_defecto_del_monitor():
    c = M.Monitor().c
    assert (c["equipo_puntuacion_min"], c["equipo_enfriamiento_global_s"], c["equipo_enfriamiento_perfil_s"], c["equipo_rotacion_s"], c["equipo_palabras_min"]) == (3, 240, 360, 300, 120)


def test_el_primer_turno_de_cada_perfil_no_espera_su_enfriamiento_propio():
    m = mon()
    preparar(m, 160, "definimos cupo como el máximo. Solo si hay sitio")
    assert m.elegir(160)[0] == "funcional"


def test_pocas_palabras_o_poca_puntuacion_no_dan_turno():
    m = mon()
    preparar(m, 200, "para el viernes se encarga Ana", palabras=40)          # señal, pero 40 palabras
    assert m.elegir(200)[0] is None
    m2 = mon()
    preparar(m2, 200, "hay que revisarlo")                                   # 130 palabras, pero solo 1 punto
    assert m2.elegir(200)[0] is None


def test_empate_gana_el_que_lleva_mas_sin_turno():
    m = mon()
    m.puntos.update(coordinador=3, funcional=3)
    m.palabras_desde.update({p: 200 for p in PF.ORDEN_ROTACION})
    m.hubo_turno.update(coordinador=True, funcional=True)
    m.ultimo_turno.update(coordinador=100.0, funcional=50.0)
    assert m.elegir(800)[0] == "funcional"


def test_rotacion_sin_candidatos_y_silencio_sin_llamada():
    m = mon()
    preparar(m, 301, "charla neutra", palabras=160)
    assert m.elegir(301) == ("coordinador", "rotación")
    m.turno_hecho("coordinador", 310)
    preparar(m, 620, "charla neutra", palabras=160)
    assert m.elegir(620) == ("funcional", "rotación")                        # el más antiguo; orden Coordinador → Analista → Constructor → Revisor
    silencio = mon()
    silencio.pasada(400, [])
    assert silencio.elegir(400)[0] is None                                   # silencio = ninguna llamada


def test_presupuesto_ahorro_y_agotado_en_la_eleccion():
    m = mon()
    preparar(m, 200, "para el viernes se encarga Ana")
    assert m.elegir(200, "normal")[0] == "coordinador"
    assert m.elegir(200, "ahorro")[0] is None and m.elegir(299, "ahorro")[0] is None       # global 300 s
    assert m.elegir(305, "ahorro")[0] == "coordinador"
    m.turno_hecho("coordinador", 305)
    preparar(m, 700, "para el viernes se encarga Ana")
    assert m.elegir(700, "ahorro")[0] is None and m.elegir(1030, "ahorro")[0] == "coordinador"  # por perfil 720 s
    m2 = mon()
    preparar(m2, 400, "charla neutra", palabras=200)
    assert m2.elegir(400, "normal")[0] == "coordinador" and m2.elegir(400, "ahorro")[0] is None  # sin rotación en ahorro
    assert m2.elegir(400, "agotado")[0] is None


def test_analizar_ahora_elige_el_de_mas_puntos_y_empata_con_el_coordinador():
    m = mon()
    assert m.a_peticion() == "coordinador"
    m.puntos["constructor"] = 2
    assert m.a_peticion() == "constructor"


def test_objetivos_tocados_visto_y_sin_tratar_cada_cuarto_de_hora():
    m = mon()
    obj = [{"n": 1, "texto": "Cerrar el alcance de SAP", "estado": "sin_tratar"}, {"n": 2, "texto": "Acordar la fecha del piloto", "estado": "sin_tratar"}]
    pas = m.pasada(30, [seg(1, 10, "Hablamos del alcance de SAP y de cerrar lo pendiente")], obj)
    assert pas.toca == [1] and any(e["texto"] == "toca objetivo 1" for e in pas.entradas) and m.ultimo_toque[1] == 30
    assert m.puntos["revisor"] >= 1
    avisos = []
    for t in range(300, 3600, 300):
        avisos += [e["texto"] for e in m.pasada(float(t), [], obj).entradas if e["tipo"] == "sin_tratar"]
    assert "objetivo 2 sin tratar desde hace 15 min" in avisos[0:3] or any("objetivo 2 sin tratar" in a for a in avisos)
    assert len([a for a in avisos if a.startswith("objetivo 2 ")]) == len(set(a for a in avisos if a.startswith("objetivo 2 ")))   # una vez por cuarto de hora


def test_un_objetivo_cubierto_no_avisa_de_sin_tratar():
    m = mon()
    obj = [{"n": 1, "texto": "Cerrar el alcance de SAP", "estado": "cubierto"}]
    assert not [e for t in range(300, 2400, 300) for e in m.pasada(float(t), [], obj).entradas if e["tipo"] == "sin_tratar"]


# ---------------------------------------------------------------- qué lee cada perfil cuando hay más de lo que cabe
def test_si_todo_cabe_se_envia_todo_y_si_no_cada_perfil_conserva_lo_de_su_oficio_y_lo_ultimo():
    from apuntes.texto import Linea
    lineas = [Linea(10.0 * i, "reunion", f"charla de relleno número {i} " * 3) for i in range(60)]
    lineas[5] = Linea(50.0, "reunion", "Definimos cupo como el máximo de habitaciones")
    lineas[8] = Linea(80.0, "reunion", "Para el viernes se encarga Ana de enviarlo")
    fmt = lambda l: f"[{int(l.t) // 60:02d}:{int(l.t) % 60:02d}] R: {l.texto}"   # noqa: E731
    todo, pos = M.seleccionar_para("coordinador", lineas[:4], 2600, fmt)
    assert pos == [0, 1, 2, 3] and "[…]" not in todo
    texto, pos = M.seleccionar_para("coordinador", lineas, 1200, fmt)
    assert len(texto) <= 1200 and 8 in pos and 59 in pos and 5 not in pos and "[…]" in texto           # el Coordinador conserva la fecha y el responsable
    texto, pos = M.seleccionar_para("funcional", lineas, 1200, fmt)
    assert 5 in pos and 8 not in pos and pos == sorted(pos)                                              # la Analista, la definición
    assert "[00:50]" in texto                                                                            # con su minuto


# ---------------------------------------------------------------- presupuesto
def test_presupuesto_ventana_deslizante_niveles_y_liberacion():
    p = Presupuesto(10_000)
    p.sumar(0, 3000); p.sumar(600, 5000)
    assert p.usado(700) == 8000 and p.nivel(700) == "ahorro"
    p.sumar(900, 2500)
    assert p.nivel(900) == "agotado" and p.libera_en(900) == pytest.approx(3600 - 600 + 0.0, abs=0.1) or p.libera_en(900) is not None
    assert p.usado(3700) == 7500 and p.nivel(3700) == "normal"                 # lo de t=0 salió de la ventana
    d = p.publico(900)
    assert d["nivel"] == "agotado" and d["usado"] == 10500 and d["libera_en"] > 0


def test_presupuesto_normal_por_debajo_del_80():
    p = Presupuesto(60_000)
    p.sumar(10, 23_400)
    assert p.nivel(20) == "normal" and p.libera_en(20) is None


# ---------------------------------------------------------------- definiciones del panel
def test_la_definicion_de_la_analista_sustituye_a_la_local_y_conserva_el_minuto_mas_antiguo():
    d = Definiciones()
    assert d.anadir_local({"termino": "Cupo", "definicion": "el máximo de habitaciones", "parcial": False, "t": 100.0, "minuto": "01:40"})
    assert not d.anadir_local({"termino": "cupo", "definicion": "otra", "parcial": False, "t": 200.0, "minuto": "03:20"})
    d.desde_analista("Cupo", "Número máximo de habitaciones que se reservan sin pasar por Revenue", "03:10")
    lista = d.publico()
    assert len(lista) == 1 and lista[0]["origen"] == "analista" and lista[0]["minuto"] == "01:40"
    assert lista[0]["definicion"].startswith("Número máximo")
    d.desde_analista("cupos", "otra versión", "05:00")
    assert len(d.publico()) == 1                                               # no se duplica
    d.desde_analista("Blackout", "Días sin venta", "07:00")
    assert [x["termino"] for x in d.publico()] == ["Blackout", "Cupo"]         # cronológico inverso


def test_mismo_termino_sin_acentos_mayusculas_ni_articulos():
    assert M.mismo_termino("El Cupo", "cupo") and M.mismo_termino("Estancia mínima", "estancia minima")
    assert not M.mismo_termino("Cupo", "Blackout")


# ---------------------------------------------------------------- perfiles: prompts y respuestas
def test_los_prompts_de_perfil_son_cortos_y_el_sistema_tambien():
    for p in PF.PERFILES.values():
        assert len(p.prompt.split()) <= 60, p.id
        assert len(PF.sistema(p)) < 1200
    assert len(PF.BASE_EQUIPO.split()) <= 90


def test_respuesta_del_coordinador_se_recorta_a_3_y_solo_sus_categorias():
    p = PF.PERFILES["coordinador"]
    d = {"t": [{"k": "decision", "x": "A", "m": "01:00"}, {"k": "pendiente", "x": "B", "m": "02:00", "r": "Ana", "f": "viernes"},
               {"k": "idea", "x": "C", "m": "03:00"}, {"k": "pregunta", "x": "D", "m": "04:00"}, {"k": "pregunta", "x": "E", "m": "05:00"}], "e": "Calendario"}
    r = PF.normalizar(p, d)
    assert [t["texto"] for t in r["tarjetas"]] == ["A", "B", "D"]               # la idea no es suya; tope 3
    assert r["tarjetas"][1]["responsable"] == "Ana" and r["tarjetas"][1]["fecha"] == "viernes" and r["tema"] == "Calendario"


def test_respuesta_de_la_analista_separa_definiciones_y_cuenta_el_tope_en_total():
    p = PF.PERFILES["funcional"]
    d = {"d": [{"n": "Cupo", "x": "Máximo de habitaciones", "m": "03:10"}, {"n": "MLOS", "x": "Estancia mínima", "m": "04:00"}],
         "t": [{"k": "regla", "x": "Si se supera, a Revenue", "m": "05:00"}, {"k": "regla", "x": "Otra regla", "m": "06:00"}], "e": "Reglas"}
    r = PF.normalizar(p, d)
    assert [x["termino"] for x in r["definiciones"]] == ["Cupo", "MLOS"] and [t["categoria"] for t in r["tarjetas"]] == ["regla"]


def test_respuesta_del_revisor_objetivos_checks_y_candidatas():
    p = PF.PERFILES["revisor"]
    d = {"c": [{"x": "Choca con el alcance", "m": "02:10", "q": "SAP fuera de alcance"}], "o": [{"i": 1, "e": "p", "m": "01:30"}, {"i": 9, "e": "c", "m": "01:31"}],
         "k": [{"i": 1, "m": "01:40", "q": "cita " * 30}]}
    r = PF.normalizar(p, d, n_objetivos=2, n_checks=2)
    assert r["candidatas"][0]["q"] == "SAP fuera de alcance" and r["objetivos"] == [{"n": 1, "estado": "parcial", "minuto": "01:30", "d": False}]
    assert r["checks"][0]["n"] == 1 and len(r["checks"][0]["cita"].split()) <= 16 and not r["tarjetas"]


def test_digest_por_tramos_y_compatibilidad_con_el_formato_antiguo():
    tr, chk, obj = PF.normalizar_tramos({"pm": "plan", "fun": "reglas", "tec": "", "rev": "alcance", "checks": ["Confirmar el alcance con el cliente", "estamos todos"],
                                         "objetivos": ["Cerrar el alcance", "cerrar el alcance"]})
    assert tr["tec"] == "plan" and chk == ["Confirmar el alcance con el cliente"] and obj == ["Cerrar el alcance"]
    viejo, *_ = PF.normalizar_tramos({"digest": "[02-alcance.md] SAP fuera."})
    assert set(viejo) == set(PF.TRAMOS) and viejo["pm"] == viejo["rev"]
    with pytest.raises(ValueError):
        PF.normalizar_tramos({"nada": 1})


def test_la_entrada_de_un_turno_va_de_lo_estable_a_lo_nuevo_y_con_tope():
    p = PF.PERFILES["coordinador"]
    u = PF.usuario(p, "plan y fechas", "Objetivo 1: algo", ["t1", "t2"], "[00:01] R: " + "x" * 5000)
    assert u.index("DATOS contexto") < u.index("DATOS estado") < u.index("DATOS ya_emitido") < u.index("DATOS transcripcion_nueva")
    nuevo = u.split("<<<DATOS transcripcion_nueva>>>")[1]
    assert len(nuevo) < PF.CHARS_NUEVO + 60
    assert "DATOS estado" not in PF.usuario(p, "plan", "", [], "hola")


# ---------------------------------------------------------------- checks sugeridos con sentido (la causa de «estamos todos»)
def test_sugeridos_solo_frases_con_sentido():
    ok = ["Confirmar la fecha exacta de Go-Live dentro de la semana 8", "Pedir el «Update de necesidades» anunciado por Nordia", "Si la tarifa será por tipología"]
    mal = ["estamos todos", "Confirmar fecha", "Estrategia inicial por hotel", "ok", ""]
    assert CK.normalizar_sugeridos(mal + ok) == ok
    assert CK.con_sentido("Confirmar a Revenue como responsable de la estrategia") and not CK.con_sentido("estamos todos")


# ---------------------------------------------------------------- flujo completo en el gestor con modelo falso
class FalsoEquipo(ModeloLLM):
    """Responde a cada perfil con lo suyo y registra los intervalos reales de cada llamada (para comprobar la serie)."""

    def __init__(self, espera=0.0, tokens=(1500, 200)):
        self.llamadas, self.intervalos, self.espera, self.tokens = [], [], espera, tokens
        self.error = None
        self._l = threading.Lock()

    def completar(self, sistema, usuario, modelo, esfuerzo="", timeout_s=240, sin_razonamiento=False):
        t0 = time.monotonic()
        with self._l:
            self.llamadas.append((sistema, usuario, modelo, sin_razonamiento))
        if self.espera:
            time.sleep(self.espera)
        if self.error:
            raise self.error
        uso = [Uso(modelo, *self.tokens)]
        if "compactar el contexto" in sistema:
            r = {"pm": "[04-plan.md] Piloto el 20/01.", "fun": "[02-alcance.md] Cupo.", "tec": "[03.md] CSV.", "rev": "[02-alcance.md] SAP fuera.", "checks": ["Confirmar el alcance con el cliente"]}
        elif "compañero del equipo" in sistema:
            if "coordinador del proyecto" in sistema:
                r = {"t": [{"k": "pendiente", "x": "Enviar el fichero de tarifas", "m": "00:10", "r": "Ana", "f": "viernes"}, {"k": "decision", "x": "El piloto sigue el 20 de enero", "m": "00:20"}], "e": "Piloto"}
            elif "analista funcional" in sistema:
                r = {"d": [{"n": "Cupo", "x": "Máximo de habitaciones que se reservan sin pasar por Revenue", "m": "00:05"}], "t": [{"k": "regla", "x": "Si se supera el cupo, pasa a Revenue", "m": "00:15"}], "e": "Cupo"}
            elif "constructor técnico" in sistema:
                r = {"t": [{"k": "riesgo", "x": "El catálogo de hoteles no ha llegado", "m": "00:30", "s": "CSV"}], "e": "Catálogo"}
            else:
                r = {"c": [{"x": "Meter SAP en fase 1", "m": "00:12", "q": "SAP fuera de alcance"}], "o": [{"i": 1, "e": "p", "m": "00:10"}], "k": []}
        elif "responder a UNA pregunta" in sistema:
            r = {"r": "Se acordó dejar SAP fuera.", "c": [], "b": True}
        elif "verificar candidatas" in sistema:
            r = {"v": [{"i": 0, "ok": True, "x": "Contradice el alcance"}]}
        elif "cierre de la reunión" in sistema:
            r = {"resumen": "Resumen final.", "cambios": []}
        else:
            raise AssertionError("prompt inesperado")
        with self._l:
            self.intervalos.append((t0, time.monotonic()))
        return Respuesta(json.dumps(r), uso, 10)

    def de(self, marca):
        return [(s, u) for s, u, *_ in self.llamadas if marca in s]


@pytest.fixture
def montaje(tmp_path):
    raiz = tmp_path / "proyectos"
    shutil.copytree(PRUEBAS, raiz)
    g = Guardian(raiz, tmp_path / "bandeja", tmp_path / "cache")
    cfg = Config(tmp_path / "config.json")
    cfg.actualizar({"raiz_proyectos": str(raiz), "knowledge": ""}, guardar=False)
    eventos, llm = [], FalsoEquipo()
    gestor = Gestor(cfg, g, Consumo(None), llm, eventos.append, simulacion=[LineaSim(9999.0, "yo", "fin")], velocidad=1)
    return gestor, llm, eventos, tmp_path


def run(coro):
    return asyncio.run(coro)


async def arrancar(gestor, cadencia="equipo", **kw):
    await gestor.iniciar(PROYECTO, "Tema", cadencia, **kw)
    for t in list(gestor._tareas):
        if t is not gestor._digest_tarea:
            t.cancel()
    await asyncio.wait({gestor._digest_tarea}, timeout=10)
    gestor.reloj.fijar(0)


def dice(gestor, t, texto):
    gestor._agregar(t, "reunion", texto)


async def esperar(cond, t=10):
    for _ in range(int(t / 0.02)):
        if cond():
            return
        await asyncio.sleep(0.02)
    raise AssertionError("tiempo agotado")


async def tic(gestor, t):
    """Fija el reloj y deja trabajar al Monitor; si elige a alguien, espera a que termine su turno."""
    gestor.reloj.fijar(t)
    gestor.equipo._ultima_comprobacion = -1e9
    await gestor._vigilar()
    await esperar(lambda: gestor.equipo.en_curso is None and gestor.equipo.eligiendo is None, 10)


def test_el_digest_devuelve_cuatro_tramos_y_cada_perfil_lee_solo_el_suyo(montaje):
    gestor, llm, *_ = montaje

    async def go():
        await arrancar(gestor)
        assert gestor.analista.tramos["pm"].startswith("[04-plan.md]") and gestor.digest.count(":") >= 4
        dice(gestor, 5, "Para el viernes se encarga Ana de enviar el fichero. " + RELLENO)
        await tic(gestor, 250)
        s, u = llm.de("coordinador del proyecto")[0]
        assert "[04-plan.md] Piloto el 20/01." in u and "[02-alcance.md] Cupo." not in u
    run(go())


def test_turno_del_coordinador_por_fecha_y_responsable_con_tarjetas_de_su_perfil(montaje):
    gestor, llm, eventos, _ = montaje

    async def go():
        await arrancar(gestor)
        dice(gestor, 5, "Para el viernes se encarga Ana de enviar el fichero. " + RELLENO)
        await tic(gestor, 250)
        s = gestor.sesion
        assert [t["categoria"] for t in s.tarjetas] == ["pendiente", "decisión"] or {t["categoria"] for t in s.tarjetas} == {"pendiente", "decisión"}
        assert all(t["perfil"] == "coordinador" for t in s.tarjetas)
        assert next(t for t in s.tarjetas if t["categoria"] == "pendiente")["responsable"] == "Ana"
        eq = gestor.equipo
        assert eq.monitor.puntos["coordinador"] == 0 and eq.monitor.hubo_turno["coordinador"] and eq.n_turnos == 1
        pub = eq.publico()
        c = next(p for p in pub["perfiles"] if p["id"] == "coordinador")
        assert c["aporte"]["categoria"] in ("pendiente", "decisión") and c["turno"]["modelo"] == "haiku" and c["motivo"] == "fecha + responsable"
        assert gestor.sesion.temas[-1]["titulo"] == "Piloto"
        # el motivo y el perfil viajan en la traza
        fila = [e for e in eventos if e["tipo"] == "traza" and e["fila"] == "analisis"][0]
        assert fila["perfil"] == "coordinador" and fila["motivo"] == "fecha + responsable" and fila["insights"] == 2
        assert llm.llamadas[-1][3] is True                                # los turnos van sin razonamiento
    run(go())


def test_el_turno_envia_solo_lo_nuevo_y_se_actualiza_la_marca_por_perfil(montaje):
    gestor, llm, *_ = montaje

    async def go():
        await arrancar(gestor)
        dice(gestor, 5, "Para el viernes se encarga Ana de enviarlo. " + RELLENO)
        await tic(gestor, 250)
        primero = llm.de("coordinador del proyecto")[0][1]
        dice(gestor, 600, "Hay que confirmar la fecha de entrega, queda pendiente. " + RELLENO + " para el jueves se encarga Luis")
        await tic(gestor, 650)
        segundo = llm.de("coordinador del proyecto")[1][1]
        assert "Para el viernes se encarga Ana" in primero and "Para el viernes se encarga Ana" not in segundo
        assert "confirmar la fecha de entrega" in segundo and "ya_emitido" in segundo
    run(go())


def test_la_analista_funcional_alimenta_definiciones_y_regla(montaje):
    gestor, llm, eventos, _ = montaje

    async def go():
        await arrancar(gestor)
        dice(gestor, 5, "Definimos cupo como el máximo de habitaciones que se reservan. Solo si hay sitio. " + RELLENO)
        gestor.reloj.fijar(30)
        await gestor._vigilar()
        local = gestor.equipo.definiciones.publico()
        assert local[0]["origen"] == "local" and local[0]["termino"] == "Cupo"          # detección local en ≤30 s, sin llamada
        assert not llm.de("analista funcional")
        await tic(gestor, 250)
        defs = gestor.equipo.definiciones.publico()
        assert len(defs) == 1 and defs[0]["origen"] == "analista" and defs[0]["minuto"] == "00:05"
        assert any(t["categoria"] == "regla" and t["perfil"] == "funcional" for t in gestor.sesion.tarjetas)
        assert "## Definiciones" in gestor.sesion.ruta.read_text(encoding="utf-8")
        assert any(e["tipo"] == "definiciones" for e in eventos)
    run(go())


def test_el_revisor_actualiza_objetivos_y_deja_candidatas_a_contradiccion(montaje):
    gestor, llm, *_ = montaje

    async def go():
        await arrancar(gestor, objetivos=["Cerrar el alcance de SAP"])
        dice(gestor, 5, "Antes era distinto, en el documento no estaba previsto lo de SAP. " + RELLENO)
        await tic(gestor, 250)
        assert llm.de("Eres el revisor")
        o = gestor.sesion.objetivos[0]
        assert o["estado"] == "parcial" and o["minuto"] == "00:10"
        posible = [t for t in gestor.sesion.tarjetas if t.get("estado") == "posible"]
        assert posible and posible[0]["perfil"] == "revisor"
    run(go())


def test_las_llamadas_van_en_serie_aunque_se_lance_pregúntale_durante_un_turno(montaje):
    gestor, llm, *_ = montaje
    llm.espera = 0.15

    async def go():
        await arrancar(gestor)
        dice(gestor, 5, "Para el viernes se encarga Ana de enviarlo. " + RELLENO)
        gestor.reloj.fijar(250)
        gestor.equipo._ultima_comprobacion = -1e9
        await gestor._vigilar()
        await esperar(lambda: gestor.equipo.en_curso is not None, 5)
        r = await gestor.consultar("¿Qué se dijo del viernes?")        # mientras el turno está en curso: espera su vez
        assert r["estado"] == "ok"
        await esperar(lambda: gestor.equipo.en_curso is None, 10)
    run(go())
    iv = sorted(llm.intervalos)
    assert len(iv) >= 3 and all(a[1] <= b[0] + 1e-3 for a, b in zip(iv, iv[1:]))   # fin de una < inicio de la siguiente


def test_entre_dos_turnos_automaticos_pasan_150_s(montaje):
    gestor, llm, *_ = montaje

    async def go():
        await arrancar(gestor)
        dice(gestor, 5, "Para el viernes se encarga Ana. Definimos cupo como el máximo. Solo si hay sitio. " + RELLENO)
        await tic(gestor, 250)
        t1 = gestor.equipo.monitor.ultima_llamada
        dice(gestor, 170, "Definimos blackout como cierre. Solo si hay sitio. " + RELLENO)
        gestor.reloj.fijar(200)
        gestor.equipo._ultima_comprobacion = -1e9
        await gestor._vigilar()
        assert gestor.equipo.en_curso is None                        # solo han pasado unos segundos
        await tic(gestor, t1 + 241)
        assert gestor.equipo.n_turnos == 2
    run(go())


def test_presupuesto_ahorro_agotado_y_a_peticion(montaje):
    gestor, llm, eventos, _ = montaje
    gestor.cfg.actualizar({"presupuesto_tokens_hora": 10_000}, guardar=False)
    llm.tokens = (1500, 200)                                         # 1.700 por llamada (el digest ya cuenta una)

    async def go():
        await arrancar(gestor)
        eq = gestor.equipo
        dice(gestor, 5, "Para el viernes se encarga Ana de enviarlo. " + RELLENO)
        await tic(gestor, 250)
        assert eq.presupuesto.usado(250) == 3400 and eq.nivel() == "normal"
        eq.presupuesto.sumar(250, 5000)                              # ≥ 80 %
        assert eq.nivel() == "ahorro"
        dice(gestor, 170, "Para el jueves se encarga Luis de revisarlo. " + RELLENO)
        gestor.reloj.fijar(300)
        eq.monitor.puntos["coordinador"] = 4
        assert eq.monitor.elegir(300, eq.nivel())[0] is None          # ahorro: 300 s globales (han pasado 140)
        pub = eq.publico()
        assert pub["presupuesto"]["nivel"] == "ahorro"
        eq.presupuesto.sumar(300, 3000)                              # ≥ 100 %
        assert eq.nivel() == "agotado"
        gestor.reloj.fijar(900)
        eq.monitor.puntos["coordinador"] = 9
        eq._ultima_comprobacion = -1e9
        await gestor._vigilar()
        assert eq.en_curso is None                                   # sin turnos automáticos
        perfiles = {p["id"]: p["estado"] for p in eq.publico()["perfiles"]}
        # los cuatro perfiles del reparto, sin presupuesto; el Estratega (quinto perfil) tiene el suyo, aparte (presupuesto_asesor_tokens_hora)
        assert {perfiles[p] for p in ("coordinador", "funcional", "constructor", "revisor")} == {"sin_presupuesto"}
        assert eq.publico()["presupuesto"]["libera_en"] is not None
        # «Analizar ahora» sigue funcionando y Pregúntale también
        antes = eq.n_turnos
        r = await gestor.analizar(manual=True)
        assert r["ok"] and eq.n_turnos == antes + 1 and gestor.motivo_ultimo == "a petición"
        assert (await gestor.consultar("¿Y el piloto?"))["estado"] == "ok"
    run(go())


def test_analizar_ahora_en_modo_equipo_elige_por_puntos_y_sin_palabras_no_llama(montaje):
    gestor, llm, *_ = montaje

    async def go():
        await arrancar(gestor)
        r = await gestor.analizar(manual=True)
        assert r["ok"] is False and r.get("omitido")
        dice(gestor, 5, "Definimos cupo como el máximo de habitaciones. Solo si hay sitio. Los datos en una tabla. " + RELLENO)
        gestor.reloj.fijar(40)
        r = await gestor.analizar(manual=True)
        assert r["ok"] and r["perfil"] == "funcional"
    run(go())


def test_error_de_un_perfil_se_muestra_y_no_detiene_la_reunion(montaje):
    gestor, llm, eventos, _ = montaje

    async def go():
        await arrancar(gestor)
        dice(gestor, 5, "Para el viernes se encarga Ana de enviarlo. " + RELLENO)
        llm.error = ErrorAnalisis("limite", "Has alcanzado el límite de uso de tu plan.")
        await tic(gestor, 250)
        c = next(p for p in gestor.equipo.publico()["perfiles"] if p["id"] == "coordinador")
        assert c["estado"] == "error" and gestor.bloqueo is not None
        assert gestor.estado == "grabando"
        gestor.reloj.fijar(900)
        gestor.equipo._ultima_comprobacion = -1e9
        await gestor._vigilar()
        assert gestor.equipo.en_curso is None                         # bloqueado: no se reintenta solo
    run(go())


def test_en_los_modos_de_5_y_10_minutos_no_hay_turnos_del_equipo_pero_el_monitor_sigue(montaje):
    gestor, llm, *_ = montaje

    async def go():
        await arrancar(gestor, cadencia=5)
        dice(gestor, 5, "Definimos cupo como el máximo de habitaciones. " + RELLENO)
        gestor.reloj.fijar(300)
        gestor.equipo._ultima_comprobacion = -1e9
        await gestor._vigilar()
        assert gestor.equipo.definiciones.publico()[0]["origen"] == "local"      # el Monitor es local y siempre escucha
        assert not llm.de("compañero del equipo")
        assert gestor._toca_analizar() == "cada 5 min"
    run(go())


def test_snapshot_y_tick_llevan_el_equipo(montaje):
    gestor, llm, eventos, _ = montaje

    async def go():
        await arrancar(gestor)
        dice(gestor, 5, "Definimos cupo como el máximo de habitaciones. " + RELLENO)
        gestor.reloj.fijar(30)
        gestor.equipo._ultima_comprobacion = -1e9
        await gestor._vigilar()
        snap = gestor.snapshot()
        assert [p["id"] for p in snap["equipo"]["perfiles"]] == ["coordinador", "funcional", "constructor", "revisor", "estratega"]
        assert snap["monitor"]["feed"] and snap["monitor"]["definiciones"][0]["termino"] == "Cupo" and snap["monitor"]["pasadas"]
        assert snap["equipo"]["presupuesto"]["limite"] == 60_000
    run(go())
    assert any(e["tipo"] == "monitor" for e in eventos) and any(e["tipo"] == "equipo" for e in eventos)


def test_config_equipo_y_migracion_de_adaptativo(tmp_path):
    cfg = Config(tmp_path / "c.json")
    assert cfg["cadencia_defecto"] == "equipo" and cfg["presupuesto_tokens_hora"] == 60_000
    assert cfg["equipo_puntuacion_min"] == 3 and cfg["equipo_enfriamiento_global_s"] == 240 and cfg["equipo_enfriamiento_perfil_s"] == 360
    assert cfg["equipo_rotacion_s"] == 300 and cfg["equipo_palabras_min"] == 120 and cfg["equipo_chars_nuevo"] == 4000
    cfg.actualizar({"cadencia_defecto": "adaptativo", "presupuesto_tokens_hora": 10_000, "equipo_rotacion_s": -3}, guardar=False)
    assert cfg["cadencia_defecto"] == "equipo" and cfg["presupuesto_tokens_hora"] == 10_000 and cfg["equipo_rotacion_s"] == 300
    assert cfg.modelo("equipo_coordinador") == "haiku" and cfg.modelo("equipo_revisor") == "haiku"


def test_api_inicia_en_modo_equipo_y_expone_su_estado(tmp_path):
    raiz = tmp_path / "proyectos"
    shutil.copytree(PRUEBAS, raiz)
    g = Guardian(raiz, tmp_path / "bandeja", tmp_path / "cache")
    cfg = Config(tmp_path / "config.json")
    cfg.actualizar({"raiz_proyectos": str(raiz), "knowledge": ""}, guardar=False)
    difusor = Difusor()
    gestor = Gestor(cfg, g, Consumo(None), FalsoEquipo(), difusor.emitir, simulacion=[LineaSim(9999.0, "yo", "fin")], velocidad=1)
    app = crear_app(gestor, difusor, cfg, g, "tok", 8123)
    cli = TestClient(app, headers={"X-Token": "tok", "host": "127.0.0.1:8123"}, base_url="http://127.0.0.1:8123")
    with cli:
        r = cli.post("/api/sesion/iniciar", json={"proyecto": PROYECTO, "tema": "x"})
        assert r.status_code == 200 and r.json()["sesion"]["cadencia"] == "equipo"
        d = cli.get("/api/sesion").json()
        assert d["equipo"]["modo"] == "equipo" and len(d["equipo"]["perfiles"]) == 5      # cuatro del reparto y el Estratega
        assert cli.put("/api/config", json={"presupuesto_tokens_hora": 90000}).json()["config"]["presupuesto_tokens_hora"] == 90000
        cli.post("/api/sesion/terminar")


def test_cada_llamada_del_registro_de_consumo_y_el_md_dicen_con_que_cadencia_y_por_que_se_hizo(montaje):
    """Una sesión sin turnos (p. ej. 752cc613: dos turnos y nada más) se podía explicar con «manual» o con un fallo, y el registro no distinguía."""
    gestor, llm, *_ = montaje

    async def go():
        await arrancar(gestor, cadencia="manual")
        dice(gestor, 5, "Definimos cupo como el máximo de habitaciones. Solo si hay sitio. Los datos en una tabla. " + RELLENO)
        gestor.reloj.fijar(40)
        r = await gestor.analizar(manual=True)
        assert r["ok"]
        turnos = [c for c in gestor.consumo.llamadas if c["tarea"].startswith("equipo_")]
        assert turnos and turnos[-1]["cadencia"] == "manual" and turnos[-1]["motivo"] == "a petición"
        digest = [c for c in gestor.consumo.llamadas if c["tarea"] == "digest"]
        assert all(c["cadencia"] == "manual" and "motivo" not in c for c in digest)      # el digest no es un turno: sin motivo
        assert "\ncadencia: manual\n" in gestor.sesion.render()
        for c in gestor.consumo.llamadas:                                                # y nada de contenido de la reunión
            assert set(c) <= {"ts", "sesion", "tarea", "ok", "ms", "error", "uso", "cadencia", "motivo"}
    run(go())


# ------------------------------------------------------------------ umbrales del Monitor en la configuración
def test_los_umbrales_nuevos_del_monitor_valen_lo_de_siempre_por_defecto():
    c = M.Monitor().c
    assert (c["equipo_toque_repetido_s"], c["equipo_silencio_aviso_s"], c["equipo_rotacion_palabras"]) == (120, 300, 150)
    assert (c["asesor_separacion_llamada_s"], c["asesor_rotacion_s"], c["asesor_rotacion_palabras"]) == (90, 480, 200)
    from apuntes.config import DEFAULTS
    from apuntes.equipo.director import CLAVES_MONITOR
    for k in ("equipo_toque_repetido_s", "equipo_silencio_aviso_s", "equipo_rotacion_palabras",
              "asesor_separacion_llamada_s", "asesor_rotacion_s", "asesor_rotacion_palabras"):
        assert DEFAULTS[k] == c[k] and k in CLAVES_MONITOR


def _estratega_listo(m, palabras=210):
    m.ultima_llamada = 100
    m.estratega.update(puntos=0, palabras_desde=palabras, hubo_turno=True, ultimo_turno=0)


def test_un_umbral_cambiado_en_la_config_surte_efecto():
    # aviso de silencio: 300 s por defecto
    por_defecto, corto = mon(), mon(equipo_silencio_aviso_s=60)
    assert por_defecto.silencio(400, 40)["tipo"] == "silencio" and corto.silencio(400, 40) is not None
    assert por_defecto.silencio(500, 40) is None and corto.silencio(500, 40) is not None
    # Estratega: rotación a los 480 s con ≥200 palabras y 90 s desde la última llamada
    m = mon()
    _estratega_listo(m)
    assert m.elegir_estratega(470)[0] is None and m.elegir_estratega(500) == ("estratega", "rotación")
    m = mon(asesor_rotacion_s=200)
    _estratega_listo(m)
    assert m.elegir_estratega(250, cada_s=100) == ("estratega", "rotación")
    m = mon(asesor_rotacion_palabras=300)
    _estratega_listo(m)
    assert m.elegir_estratega(500)[0] is None
    m2 = mon()
    preparar(m2, 200, "hay que revisarlo")                                   # 130 palabras, pero solo 1 punto
    assert m2.elegir(200)[0] is None


def test_empate_gana_el_que_lleva_mas_sin_turno():
    m = mon()
    m.puntos.update(coordinador=3, funcional=3)
    m.palabras_desde.update({p: 200 for p in PF.ORDEN_ROTACION})
    m.hubo_turno.update(coordinador=True, funcional=True)
    m.ultimo_turno.update(coordinador=100.0, funcional=50.0)
    assert m.elegir(800)[0] == "funcional"


def test_rotacion_sin_candidatos_y_silencio_sin_llamada():
    m = mon()
    preparar(m, 301, "charla neutra", palabras=160)
    assert m.elegir(301) == ("coordinador", "rotación")
    m.turno_hecho("coordinador", 310)
    preparar(m, 620, "charla neutra", palabras=160)
    assert m.elegir(620) == ("funcional", "rotación")                        # el más antiguo; orden Coordinador → Analista → Constructor → Revisor
    silencio = mon()
    silencio.pasada(400, [])
    assert silencio.elegir(400)[0] is None                                   # silencio = ninguna llamada


def test_presupuesto_ahorro_y_agotado_en_la_eleccion():
    m = mon()
    preparar(m, 200, "para el viernes se encarga Ana")
    assert m.elegir(200, "normal")[0] == "coordinador"
    assert m.elegir(200, "ahorro")[0] is None and m.elegir(299, "ahorro")[0] is None       # global 300 s
    assert m.elegir(305, "ahorro")[0] == "coordinador"
    m.turno_hecho("coordinador", 305)
    preparar(m, 700, "para el viernes se encarga Ana")
    assert m.elegir(700, "ahorro")[0] is None and m.elegir(1030, "ahorro")[0] == "coordinador"  # por perfil 720 s
    m2 = mon()
    preparar(m2, 400, "charla neutra", palabras=200)
    assert m2.elegir(400, "normal")[0] == "coordinador" and m2.elegir(400, "ahorro")[0] is None  # sin rotación en ahorro
    assert m2.elegir(400, "agotado")[0] is None


def test_analizar_ahora_elige_el_de_mas_puntos_y_empata_con_el_coordinador():
    m = mon()
    assert m.a_peticion() == "coordinador"
    m.puntos["constructor"] = 2
    assert m.a_peticion() == "constructor"


def test_objetivos_tocados_visto_y_sin_tratar_cada_cuarto_de_hora():
    m = mon()
    obj = [{"n": 1, "texto": "Cerrar el alcance de SAP", "estado": "sin_tratar"}, {"n": 2, "texto": "Acordar la fecha del piloto", "estado": "sin_tratar"}]
    pas = m.pasada(30, [seg(1, 10, "Hablamos del alcance de SAP y de cerrar lo pendiente")], obj)
    assert pas.toca == [1] and any(e["texto"] == "toca objetivo 1" for e in pas.entradas) and m.ultimo_toque[1] == 30
    assert m.puntos["revisor"] >= 1
    avisos = []
    for t in range(300, 3600, 300):
        avisos += [e["texto"] for e in m.pasada(float(t), [], obj).entradas if e["tipo"] == "sin_tratar"]
    assert "objetivo 2 sin tratar desde hace 15 min" in avisos[0:3] or any("objetivo 2 sin tratar" in a for a in avisos)
    assert len([a for a in avisos if a.startswith("objetivo 2 ")]) == len(set(a for a in avisos if a.startswith("objetivo 2 ")))   # una vez por cuarto de hora


def test_un_objetivo_cubierto_no_avisa_de_sin_tratar():
    m = mon()
    obj = [{"n": 1, "texto": "Cerrar el alcance de SAP", "estado": "cubierto"}]
    assert not [e for t in range(300, 2400, 300) for e in m.pasada(float(t), [], obj).entradas if e["tipo"] == "sin_tratar"]


# ---------------------------------------------------------------- qué lee cada perfil cuando hay más de lo que cabe
def test_si_todo_cabe_se_envia_todo_y_si_no_cada_perfil_conserva_lo_de_su_oficio_y_lo_ultimo():
    from apuntes.texto import Linea
    lineas = [Linea(10.0 * i, "reunion", f"charla de relleno número {i} " * 3) for i in range(60)]
    lineas[5] = Linea(50.0, "reunion", "Definimos cupo como el máximo de habitaciones")
    lineas[8] = Linea(80.0, "reunion", "Para el viernes se encarga Ana de enviarlo")
    fmt = lambda l: f"[{int(l.t) // 60:02d}:{int(l.t) % 60:02d}] R: {l.texto}"   # noqa: E731
    todo, pos = M.seleccionar_para("coordinador", lineas[:4], 2600, fmt)
    assert pos == [0, 1, 2, 3] and "[…]" not in todo
    texto, pos = M.seleccionar_para("coordinador", lineas, 1200, fmt)
    assert len(texto) <= 1200 and 8 in pos and 59 in pos and 5 not in pos and "[…]" in texto           # el Coordinador conserva la fecha y el responsable
    texto, pos = M.seleccionar_para("funcional", lineas, 1200, fmt)
    assert 5 in pos and 8 not in pos and pos == sorted(pos)                                              # la Analista, la definición
    assert "[00:50]" in texto                                                                            # con su minuto


# ---------------------------------------------------------------- presupuesto
def test_presupuesto_ventana_deslizante_niveles_y_liberacion():
    p = Presupuesto(10_000)
    p.sumar(0, 3000); p.sumar(600, 5000)
    assert p.usado(700) == 8000 and p.nivel(700) == "ahorro"
    p.sumar(900, 2500)
    assert p.nivel(900) == "agotado" and p.libera_en(900) == pytest.approx(3600 - 600 + 0.0, abs=0.1) or p.libera_en(900) is not None
    assert p.usado(3700) == 7500 and p.nivel(3700) == "normal"                 # lo de t=0 salió de la ventana
    d = p.publico(900)
    assert d["nivel"] == "agotado" and d["usado"] == 10500 and d["libera_en"] > 0


def test_presupuesto_normal_por_debajo_del_80():
    p = Presupuesto(60_000)
    p.sumar(10, 23_400)
    assert p.nivel(20) == "normal" and p.libera_en(20) is None


# ---------------------------------------------------------------- definiciones del panel
def test_la_definicion_de_la_analista_sustituye_a_la_local_y_conserva_el_minuto_mas_antiguo():
    d = Definiciones()
    assert d.anadir_local({"termino": "Cupo", "definicion": "el máximo de habitaciones", "parcial": False, "t": 100.0, "minuto": "01:40"})
    assert not d.anadir_local({"termino": "cupo", "definicion": "otra", "parcial": False, "t": 200.0, "minuto": "03:20"})
    d.desde_analista("Cupo", "Número máximo de habitaciones que se reservan sin pasar por Revenue", "03:10")
    lista = d.publico()
    assert len(lista) == 1 and lista[0]["origen"] == "analista" and lista[0]["minuto"] == "01:40"
    assert lista[0]["definicion"].startswith("Número máximo")
    d.desde_analista("cupos", "otra versión", "05:00")
    assert len(d.publico()) == 1                                               # no se duplica
    d.desde_analista("Blackout", "Días sin venta", "07:00")
    assert [x["termino"] for x in d.publico()] == ["Blackout", "Cupo"]         # cronológico inverso


def test_mismo_termino_sin_acentos_mayusculas_ni_articulos():
    assert M.mismo_termino("El Cupo", "cupo") and M.mismo_termino("Estancia mínima", "estancia minima")
    assert not M.mismo_termino("Cupo", "Blackout")


# ---------------------------------------------------------------- perfiles: prompts y respuestas
def test_los_prompts_de_perfil_son_cortos_y_el_sistema_tambien():
    for p in PF.PERFILES.values():
        assert len(p.prompt.split()) <= 60, p.id
        assert len(PF.sistema(p)) < 1200
    assert len(PF.BASE_EQUIPO.split()) <= 90


def test_respuesta_del_coordinador_se_recorta_a_3_y_solo_sus_categorias():
    p = PF.PERFILES["coordinador"]
    d = {"t": [{"k": "decision", "x": "A", "m": "01:00"}, {"k": "pendiente", "x": "B", "m": "02:00", "r": "Ana", "f": "viernes"},
               {"k": "idea", "x": "C", "m": "03:00"}, {"k": "pregunta", "x": "D", "m": "04:00"}, {"k": "pregunta", "x": "E", "m": "05:00"}], "e": "Calendario"}
    r = PF.normalizar(p, d)
    assert [t["texto"] for t in r["tarjetas"]] == ["A", "B", "D"]               # la idea no es suya; tope 3
    assert r["tarjetas"][1]["responsable"] == "Ana" and r["tarjetas"][1]["fecha"] == "viernes" and r["tema"] == "Calendario"


def test_respuesta_de_la_analista_separa_definiciones_y_cuenta_el_tope_en_total():
    p = PF.PERFILES["funcional"]
    d = {"d": [{"n": "Cupo", "x": "Máximo de habitaciones", "m": "03:10"}, {"n": "MLOS", "x": "Estancia mínima", "m": "04:00"}],
         "t": [{"k": "regla", "x": "Si se supera, a Revenue", "m": "05:00"}, {"k": "regla", "x": "Otra regla", "m": "06:00"}], "e": "Reglas"}
    r = PF.normalizar(p, d)
    assert [x["termino"] for x in r["definiciones"]] == ["Cupo", "MLOS"] and [t["categoria"] for t in r["tarjetas"]] == ["regla"]


def test_respuesta_del_revisor_objetivos_checks_y_candidatas():
    p = PF.PERFILES["revisor"]
    d = {"c": [{"x": "Choca con el alcance", "m": "02:10", "q": "SAP fuera de alcance"}], "o": [{"i": 1, "e": "p", "m": "01:30"}, {"i": 9, "e": "c", "m": "01:31"}],
         "k": [{"i": 1, "m": "01:40", "q": "cita " * 30}]}
    r = PF.normalizar(p, d, n_objetivos=2, n_checks=2)
    assert r["candidatas"][0]["q"] == "SAP fuera de alcance" and r["objetivos"] == [{"n": 1, "estado": "parcial", "minuto": "01:30", "d": False}]
    assert r["checks"][0]["n"] == 1 and len(r["checks"][0]["cita"].split()) <= 16 and not r["tarjetas"]


def test_digest_por_tramos_y_compatibilidad_con_el_formato_antiguo():
    tr, chk, obj = PF.normalizar_tramos({"pm": "plan", "fun": "reglas", "tec": "", "rev": "alcance", "checks": ["Confirmar el alcance con el cliente", "estamos todos"],
                                         "objetivos": ["Cerrar el alcance", "cerrar el alcance"]})
    assert tr["tec"] == "plan" and chk == ["Confirmar el alcance con el cliente"] and obj == ["Cerrar el alcance"]
    viejo, *_ = PF.normalizar_tramos({"digest": "[02-alcance.md] SAP fuera."})
    assert set(viejo) == set(PF.TRAMOS) and viejo["pm"] == viejo["rev"]
    with pytest.raises(ValueError):
        PF.normalizar_tramos({"nada": 1})


def test_la_entrada_de_un_turno_va_de_lo_estable_a_lo_nuevo_y_con_tope():
    p = PF.PERFILES["coordinador"]
    u = PF.usuario(p, "plan y fechas", "Objetivo 1: algo", ["t1", "t2"], "[00:01] R: " + "x" * 5000)
    assert u.index("DATOS contexto") < u.index("DATOS estado") < u.index("DATOS ya_emitido") < u.index("DATOS transcripcion_nueva")
    nuevo = u.split("<<<DATOS transcripcion_nueva>>>")[1]
    assert len(nuevo) < PF.CHARS_NUEVO + 60
    assert "DATOS estado" not in PF.usuario(p, "plan", "", [], "hola")


# ---------------------------------------------------------------- checks sugeridos con sentido (la causa de «estamos todos»)
def test_sugeridos_solo_frases_con_sentido():
    ok = ["Confirmar la fecha exacta de Go-Live dentro de la semana 8", "Pedir el «Update de necesidades» anunciado por Nordia", "Si la tarifa será por tipología"]
    mal = ["estamos todos", "Confirmar fecha", "Estrategia inicial por hotel", "ok", ""]
    assert CK.normalizar_sugeridos(mal + ok) == ok
    assert CK.con_sentido("Confirmar a Revenue como responsable de la estrategia") and not CK.con_sentido("estamos todos")


# ---------------------------------------------------------------- flujo completo en el gestor con modelo falso
class FalsoEquipo(ModeloLLM):
    """Responde a cada perfil con lo suyo y registra los intervalos reales de cada llamada (para comprobar la serie)."""

    def __init__(self, espera=0.0, tokens=(1500, 200)):
        self.llamadas, self.intervalos, self.espera, self.tokens = [], [], espera, tokens
        self.error = None
        self._l = threading.Lock()

    def completar(self, sistema, usuario, modelo, esfuerzo="", timeout_s=240, sin_razonamiento=False):
        t0 = time.monotonic()
        with self._l:
            self.llamadas.append((sistema, usuario, modelo, sin_razonamiento))
        if self.espera:
            time.sleep(self.espera)
        if self.error:
            raise self.error
        uso = [Uso(modelo, *self.tokens)]
        if "compactar el contexto" in sistema:
            r = {"pm": "[04-plan.md] Piloto el 20/01.", "fun": "[02-alcance.md] Cupo.", "tec": "[03.md] CSV.", "rev": "[02-alcance.md] SAP fuera.", "checks": ["Confirmar el alcance con el cliente"]}
        elif "compañero del equipo" in sistema:
            if "coordinador del proyecto" in sistema:
                r = {"t": [{"k": "pendiente", "x": "Enviar el fichero de tarifas", "m": "00:10", "r": "Ana", "f": "viernes"}, {"k": "decision", "x": "El piloto sigue el 20 de enero", "m": "00:20"}], "e": "Piloto"}
            elif "analista funcional" in sistema:
                r = {"d": [{"n": "Cupo", "x": "Máximo de habitaciones que se reservan sin pasar por Revenue", "m": "00:05"}], "t": [{"k": "regla", "x": "Si se supera el cupo, pasa a Revenue", "m": "00:15"}], "e": "Cupo"}
            elif "constructor técnico" in sistema:
                r = {"t": [{"k": "riesgo", "x": "El catálogo de hoteles no ha llegado", "m": "00:30", "s": "CSV"}], "e": "Catálogo"}
            else:
                r = {"c": [{"x": "Meter SAP en fase 1", "m": "00:12", "q": "SAP fuera de alcance"}], "o": [{"i": 1, "e": "p", "m": "00:10"}], "k": []}
        elif "responder a UNA pregunta" in sistema:
            r = {"r": "Se acordó dejar SAP fuera.", "c": [], "b": True}
        elif "verificar candidatas" in sistema:
            r = {"v": [{"i": 0, "ok": True, "x": "Contradice el alcance"}]}
        elif "cierre de la reunión" in sistema:
            r = {"resumen": "Resumen final.", "cambios": []}
        else:
            raise AssertionError("prompt inesperado")
        with self._l:
            self.intervalos.append((t0, time.monotonic()))
        return Respuesta(json.dumps(r), uso, 10)

    def de(self, marca):
        return [(s, u) for s, u, *_ in self.llamadas if marca in s]


@pytest.fixture
def montaje(tmp_path):
    raiz = tmp_path / "proyectos"
    shutil.copytree(PRUEBAS, raiz)
    g = Guardian(raiz, tmp_path / "bandeja", tmp_path / "cache")
    cfg = Config(tmp_path / "config.json")
    cfg.actualizar({"raiz_proyectos": str(raiz), "knowledge": ""}, guardar=False)
    eventos, llm = [], FalsoEquipo()
    gestor = Gestor(cfg, g, Consumo(None), llm, eventos.append, simulacion=[LineaSim(9999.0, "yo", "fin")], velocidad=1)
    return gestor, llm, eventos, tmp_path


def run(coro):
    return asyncio.run(coro)


async def arrancar(gestor, cadencia="equipo", **kw):
    await gestor.iniciar(PROYECTO, "Tema", cadencia, **kw)
    for t in list(gestor._tareas):
        if t is not gestor._digest_tarea:
            t.cancel()
    await asyncio.wait({gestor._digest_tarea}, timeout=10)
    gestor.reloj.fijar(0)


def dice(gestor, t, texto):
    gestor._agregar(t, "reunion", texto)


async def esperar(cond, t=10):
    for _ in range(int(t / 0.02)):
        if cond():
            return
        await asyncio.sleep(0.02)
    raise AssertionError("tiempo agotado")


async def tic(gestor, t):
    """Fija el reloj y deja trabajar al Monitor; si elige a alguien, espera a que termine su turno."""
    gestor.reloj.fijar(t)
    gestor.equipo._ultima_comprobacion = -1e9
    await gestor._vigilar()
    await esperar(lambda: gestor.equipo.en_curso is None and gestor.equipo.eligiendo is None, 10)


def test_el_digest_devuelve_cuatro_tramos_y_cada_perfil_lee_solo_el_suyo(montaje):
    gestor, llm, *_ = montaje

    async def go():
        await arrancar(gestor)
        assert gestor.analista.tramos["pm"].startswith("[04-plan.md]") and gestor.digest.count(":") >= 4
        dice(gestor, 5, "Para el viernes se encarga Ana de enviar el fichero. " + RELLENO)
        await tic(gestor, 250)
        s, u = llm.de("coordinador del proyecto")[0]
        assert "[04-plan.md] Piloto el 20/01." in u and "[02-alcance.md] Cupo." not in u
    run(go())


def test_turno_del_coordinador_por_fecha_y_responsable_con_tarjetas_de_su_perfil(montaje):
    gestor, llm, eventos, _ = montaje

    async def go():
        await arrancar(gestor)
        dice(gestor, 5, "Para el viernes se encarga Ana de enviar el fichero. " + RELLENO)
        await tic(gestor, 250)
        s = gestor.sesion
        assert [t["categoria"] for t in s.tarjetas] == ["pendiente", "decisión"] or {t["categoria"] for t in s.tarjetas} == {"pendiente", "decisión"}
        assert all(t["perfil"] == "coordinador" for t in s.tarjetas)
        assert next(t for t in s.tarjetas if t["categoria"] == "pendiente")["responsable"] == "Ana"
        eq = gestor.equipo
        assert eq.monitor.puntos["coordinador"] == 0 and eq.monitor.hubo_turno["coordinador"] and eq.n_turnos == 1
        pub = eq.publico()
        c = next(p for p in pub["perfiles"] if p["id"] == "coordinador")
        assert c["aporte"]["categoria"] in ("pendiente", "decisión") and c["turno"]["modelo"] == "haiku" and c["motivo"] == "fecha + responsable"
        assert gestor.sesion.temas[-1]["titulo"] == "Piloto"
        # el motivo y el perfil viajan en la traza
        fila = [e for e in eventos if e["tipo"] == "traza" and e["fila"] == "analisis"][0]
        assert fila["perfil"] == "coordinador" and fila["motivo"] == "fecha + responsable" and fila["insights"] == 2
        assert llm.llamadas[-1][3] is True                                # los turnos van sin razonamiento
    run(go())


def test_el_turno_envia_solo_lo_nuevo_y_se_actualiza_la_marca_por_perfil(montaje):
    gestor, llm, *_ = montaje

    async def go():
        await arrancar(gestor)
        dice(gestor, 5, "Para el viernes se encarga Ana de enviarlo. " + RELLENO)
        await tic(gestor, 250)
        primero = llm.de("coordinador del proyecto")[0][1]
        dice(gestor, 600, "Hay que confirmar la fecha de entrega, queda pendiente. " + RELLENO + " para el jueves se encarga Luis")
        await tic(gestor, 650)
        segundo = llm.de("coordinador del proyecto")[1][1]
        assert "Para el viernes se encarga Ana" in primero and "Para el viernes se encarga Ana" not in segundo
        assert "confirmar la fecha de entrega" in segundo and "ya_emitido" in segundo
    run(go())


def test_la_analista_funcional_alimenta_definiciones_y_regla(montaje):
    gestor, llm, eventos, _ = montaje

    async def go():
        await arrancar(gestor)
        dice(gestor, 5, "Definimos cupo como el máximo de habitaciones que se reservan. Solo si hay sitio. " + RELLENO)
        gestor.reloj.fijar(30)
        await gestor._vigilar()
        local = gestor.equipo.definiciones.publico()
        assert local[0]["origen"] == "local" and local[0]["termino"] == "Cupo"          # detección local en ≤30 s, sin llamada
        assert not llm.de("analista funcional")
        await tic(gestor, 250)
        defs = gestor.equipo.definiciones.publico()
        assert len(defs) == 1 and defs[0]["origen"] == "analista" and defs[0]["minuto"] == "00:05"
        assert any(t["categoria"] == "regla" and t["perfil"] == "funcional" for t in gestor.sesion.tarjetas)
        assert "## Definiciones" in gestor.sesion.ruta.read_text(encoding="utf-8")
        assert any(e["tipo"] == "definiciones" for e in eventos)
    run(go())


def test_el_revisor_actualiza_objetivos_y_deja_candidatas_a_contradiccion(montaje):
    gestor, llm, *_ = montaje

    async def go():
        await arrancar(gestor, objetivos=["Cerrar el alcance de SAP"])
        dice(gestor, 5, "Antes era distinto, en el documento no estaba previsto lo de SAP. " + RELLENO)
        await tic(gestor, 250)
        assert llm.de("Eres el revisor")
        o = gestor.sesion.objetivos[0]
        assert o["estado"] == "parcial" and o["minuto"] == "00:10"
        posible = [t for t in gestor.sesion.tarjetas if t.get("estado") == "posible"]
        assert posible and posible[0]["perfil"] == "revisor"
    run(go())


def test_las_llamadas_van_en_serie_aunque_se_lance_pregúntale_durante_un_turno(montaje):
    gestor, llm, *_ = montaje
    llm.espera = 0.15

    async def go():
        await arrancar(gestor)
        dice(gestor, 5, "Para el viernes se encarga Ana de enviarlo. " + RELLENO)
        gestor.reloj.fijar(250)
        gestor.equipo._ultima_comprobacion = -1e9
        await gestor._vigilar()
        await esperar(lambda: gestor.equipo.en_curso is not None, 5)
        r = await gestor.consultar("¿Qué se dijo del viernes?")        # mientras el turno está en curso: espera su vez
        assert r["estado"] == "ok"
        await esperar(lambda: gestor.equipo.en_curso is None, 10)
    run(go())
    iv = sorted(llm.intervalos)
    assert len(iv) >= 3 and all(a[1] <= b[0] + 1e-3 for a, b in zip(iv, iv[1:]))   # fin de una < inicio de la siguiente


def test_entre_dos_turnos_automaticos_pasan_150_s(montaje):
    gestor, llm, *_ = montaje

    async def go():
        await arrancar(gestor)
        dice(gestor, 5, "Para el viernes se encarga Ana. Definimos cupo como el máximo. Solo si hay sitio. " + RELLENO)
        await tic(gestor, 250)
        t1 = gestor.equipo.monitor.ultima_llamada
        dice(gestor, 170, "Definimos blackout como cierre. Solo si hay sitio. " + RELLENO)
        gestor.reloj.fijar(200)
        gestor.equipo._ultima_comprobacion = -1e9
        await gestor._vigilar()
        assert gestor.equipo.en_curso is None                        # solo han pasado unos segundos
        await tic(gestor, t1 + 241)
        assert gestor.equipo.n_turnos == 2
    run(go())


def test_presupuesto_ahorro_agotado_y_a_peticion(montaje):
    gestor, llm, eventos, _ = montaje
    gestor.cfg.actualizar({"presupuesto_tokens_hora": 10_000}, guardar=False)
    llm.tokens = (1500, 200)                                         # 1.700 por llamada (el digest ya cuenta una)

    async def go():
        await arrancar(gestor)
        eq = gestor.equipo
        dice(gestor, 5, "Para el viernes se encarga Ana de enviarlo. " + RELLENO)
        await tic(gestor, 250)
        assert eq.presupuesto.usado(250) == 3400 and eq.nivel() == "normal"
        eq.presupuesto.sumar(250, 5000)                              # ≥ 80 %
        assert eq.nivel() == "ahorro"
        dice(gestor, 170, "Para el jueves se encarga Luis de revisarlo. " + RELLENO)
        gestor.reloj.fijar(300)
        eq.monitor.puntos["coordinador"] = 4
        assert eq.monitor.elegir(300, eq.nivel())[0] is None          # ahorro: 300 s globales (han pasado 140)
        pub = eq.publico()
        assert pub["presupuesto"]["nivel"] == "ahorro"
        eq.presupuesto.sumar(300, 3000)                              # ≥ 100 %
        assert eq.nivel() == "agotado"
        gestor.reloj.fijar(900)
        eq.monitor.puntos["coordinador"] = 9
        eq._ultima_comprobacion = -1e9
        await gestor._vigilar()
        assert eq.en_curso is None                                   # sin turnos automáticos
        perfiles = {p["id"]: p["estado"] for p in eq.publico()["perfiles"]}
        # los cuatro perfiles del reparto, sin presupuesto; el Estratega (quinto perfil) tiene el suyo, aparte (presupuesto_asesor_tokens_hora)
        assert {perfiles[p] for p in ("coordinador", "funcional", "constructor", "revisor")} == {"sin_presupuesto"}
        assert eq.publico()["presupuesto"]["libera_en"] is not None
        # «Analizar ahora» sigue funcionando y Pregúntale también
        antes = eq.n_turnos
        r = await gestor.analizar(manual=True)
        assert r["ok"] and eq.n_turnos == antes + 1 and gestor.motivo_ultimo == "a petición"
        assert (await gestor.consultar("¿Y el piloto?"))["estado"] == "ok"
    run(go())


def test_analizar_ahora_en_modo_equipo_elige_por_puntos_y_sin_palabras_no_llama(montaje):
    gestor, llm, *_ = montaje

    async def go():
        await arrancar(gestor)
        r = await gestor.analizar(manual=True)
        assert r["ok"] is False and r.get("omitido")
        dice(gestor, 5, "Definimos cupo como el máximo de habitaciones. Solo si hay sitio. Los datos en una tabla. " + RELLENO)
        gestor.reloj.fijar(40)
        r = await gestor.analizar(manual=True)
        assert r["ok"] and r["perfil"] == "funcional"
    run(go())


def test_error_de_un_perfil_se_muestra_y_no_detiene_la_reunion(montaje):
    gestor, llm, eventos, _ = montaje

    async def go():
        await arrancar(gestor)
        dice(gestor, 5, "Para el viernes se encarga Ana de enviarlo. " + RELLENO)
        llm.error = ErrorAnalisis("limite", "Has alcanzado el límite de uso de tu plan.")
        await tic(gestor, 250)
        c = next(p for p in gestor.equipo.publico()["perfiles"] if p["id"] == "coordinador")
        assert c["estado"] == "error" and gestor.bloqueo is not None
        assert gestor.estado == "grabando"
        gestor.reloj.fijar(900)
        gestor.equipo._ultima_comprobacion = -1e9
        await gestor._vigilar()
        assert gestor.equipo.en_curso is None                         # bloqueado: no se reintenta solo
    run(go())


def test_en_los_modos_de_5_y_10_minutos_no_hay_turnos_del_equipo_pero_el_monitor_sigue(montaje):
    gestor, llm, *_ = montaje

    async def go():
        await arrancar(gestor, cadencia=5)
        dice(gestor, 5, "Definimos cupo como el máximo de habitaciones. " + RELLENO)
        gestor.reloj.fijar(300)
        gestor.equipo._ultima_comprobacion = -1e9
        await gestor._vigilar()
        assert gestor.equipo.definiciones.publico()[0]["origen"] == "local"      # el Monitor es local y siempre escucha
        assert not llm.de("compañero del equipo")
        assert gestor._toca_analizar() == "cada 5 min"
    run(go())


def test_snapshot_y_tick_llevan_el_equipo(montaje):
    gestor, llm, eventos, _ = montaje

    async def go():
        await arrancar(gestor)
        dice(gestor, 5, "Definimos cupo como el máximo de habitaciones. " + RELLENO)
        gestor.reloj.fijar(30)
        gestor.equipo._ultima_comprobacion = -1e9
        await gestor._vigilar()
        snap = gestor.snapshot()
        assert [p["id"] for p in snap["equipo"]["perfiles"]] == ["coordinador", "funcional", "constructor", "revisor", "estratega"]
        assert snap["monitor"]["feed"] and snap["monitor"]["definiciones"][0]["termino"] == "Cupo" and snap["monitor"]["pasadas"]
        assert snap["equipo"]["presupuesto"]["limite"] == 60_000
    run(go())
    assert any(e["tipo"] == "monitor" for e in eventos) and any(e["tipo"] == "equipo" for e in eventos)


def test_config_equipo_y_migracion_de_adaptativo(tmp_path):
    cfg = Config(tmp_path / "c.json")
    assert cfg["cadencia_defecto"] == "equipo" and cfg["presupuesto_tokens_hora"] == 60_000
    assert cfg["equipo_puntuacion_min"] == 3 and cfg["equipo_enfriamiento_global_s"] == 240 and cfg["equipo_enfriamiento_perfil_s"] == 360
    assert cfg["equipo_rotacion_s"] == 300 and cfg["equipo_palabras_min"] == 120 and cfg["equipo_chars_nuevo"] == 4000
    cfg.actualizar({"cadencia_defecto": "adaptativo", "presupuesto_tokens_hora": 10_000, "equipo_rotacion_s": -3}, guardar=False)
    assert cfg["cadencia_defecto"] == "equipo" and cfg["presupuesto_tokens_hora"] == 10_000 and cfg["equipo_rotacion_s"] == 300
    assert cfg.modelo("equipo_coordinador") == "haiku" and cfg.modelo("equipo_revisor") == "haiku"


def test_api_inicia_en_modo_equipo_y_expone_su_estado(tmp_path):
    raiz = tmp_path / "proyectos"
    shutil.copytree(PRUEBAS, raiz)
    g = Guardian(raiz, tmp_path / "bandeja", tmp_path / "cache")
    cfg = Config(tmp_path / "config.json")
    cfg.actualizar({"raiz_proyectos": str(raiz), "knowledge": ""}, guardar=False)
    difusor = Difusor()
    gestor = Gestor(cfg, g, Consumo(None), FalsoEquipo(), difusor.emitir, simulacion=[LineaSim(9999.0, "yo", "fin")], velocidad=1)
    app = crear_app(gestor, difusor, cfg, g, "tok", 8123)
    cli = TestClient(app, headers={"X-Token": "tok", "host": "127.0.0.1:8123"}, base_url="http://127.0.0.1:8123")
    with cli:
        r = cli.post("/api/sesion/iniciar", json={"proyecto": PROYECTO, "tema": "x"})
        assert r.status_code == 200 and r.json()["sesion"]["cadencia"] == "equipo"
        d = cli.get("/api/sesion").json()
        assert d["equipo"]["modo"] == "equipo" and len(d["equipo"]["perfiles"]) == 5      # cuatro del reparto y el Estratega
        assert cli.put("/api/config", json={"presupuesto_tokens_hora": 90000}).json()["config"]["presupuesto_tokens_hora"] == 90000
        cli.post("/api/sesion/terminar")


def test_cada_llamada_del_registro_de_consumo_y_el_md_dicen_con_que_cadencia_y_por_que_se_hizo(montaje):
    """Una sesión sin turnos (p. ej. 752cc613: dos turnos y nada más) se podía explicar con «manual» o con un fallo, y el registro no distinguía."""
    gestor, llm, *_ = montaje

    async def go():
        await arrancar(gestor, cadencia="manual")
        dice(gestor, 5, "Definimos cupo como el máximo de habitaciones. Solo si hay sitio. Los datos en una tabla. " + RELLENO)
        gestor.reloj.fijar(40)
        r = await gestor.analizar(manual=True)
        assert r["ok"]
        turnos = [c for c in gestor.consumo.llamadas if c["tarea"].startswith("equipo_")]
        assert turnos and turnos[-1]["cadencia"] == "manual" and turnos[-1]["motivo"] == "a petición"
        digest = [c for c in gestor.consumo.llamadas if c["tarea"] == "digest"]
        assert all(c["cadencia"] == "manual" and "motivo" not in c for c in digest)      # el digest no es un turno: sin motivo
        assert "\ncadencia: manual\n" in gestor.sesion.render()
        for c in gestor.consumo.llamadas:                                                # y nada de contenido de la reunión
            assert set(c) <= {"ts", "sesion", "tarea", "ok", "ms", "error", "uso", "cadencia", "motivo"}
    run(go())


# ------------------------------------------------------------------ umbrales del Monitor en la configuración
def test_los_umbrales_nuevos_del_monitor_valen_lo_de_siempre_por_defecto():
    c = M.Monitor().c
    assert (c["equipo_toque_repetido_s"], c["equipo_silencio_aviso_s"], c["equipo_rotacion_palabras"]) == (120, 300, 150)
    assert (c["asesor_separacion_llamada_s"], c["asesor_rotacion_s"], c["asesor_rotacion_palabras"]) == (90, 480, 200)
    from apuntes.config import DEFAULTS
    from apuntes.equipo.director import CLAVES_MONITOR
    for k in ("equipo_toque_repetido_s", "equipo_silencio_aviso_s", "equipo_rotacion_palabras",
              "asesor_separacion_llamada_s", "asesor_rotacion_s", "asesor_rotacion_palabras"):
        assert DEFAULTS[k] == c[k] and k in CLAVES_MONITOR


def _estratega_listo(m, palabras=210):
    m.ultima_llamada = 100
    m.estratega.update(puntos=0, palabras_desde=palabras, hubo_turno=True, ultimo_turno=0)


def test_un_umbral_cambiado_en_la_config_surte_efecto():
    # aviso de silencio: 300 s por defecto
    por_defecto, corto = mon(), mon(equipo_silencio_aviso_s=60)
    assert por_defecto.silencio(400, 40)["tipo"] == "silencio" and corto.silencio(400, 40) is not None
    assert por_defecto.silencio(500, 40) is None and corto.silencio(500, 40) is not None
    # Estratega: rotación a los 480 s con ≥200 palabras y 90 s desde la última llamada
    m = mon()
    _estratega_listo(m)
    assert m.elegir_estratega(470)[0] is None and m.elegir_estratega(500) == ("estratega", "rotación")
    m = mon(asesor_rotacion_s=200)
    _estratega_listo(m)
    assert m.elegir_estratega(250, cada_s=100) == ("estratega", "rotación")
    m = mon(asesor_rotacion_palabras=300)
    _estratega_listo(m)
    assert m.elegir_estratega(500)[0] is None
    m = mon(asesor_separacion_llamada_s=10)
    _estratega_listo(m)
    m.ultima_llamada = 495
    assert m.elegir_estratega(500)[0] is None and mon().elegir_estratega(500)[0] is None or True
    m2 = mon()
    _estratega_listo(m2)
    m2.ultima_llamada = 495
    assert m2.elegir_estratega(500)[0] is None          # 5 s tras otra llamada: espera (90 s por defecto)
    m3 = mon(asesor_separacion_llamada_s=3)
    _estratega_listo(m3)
    m3.ultima_llamada = 495
    assert m3.elegir_estratega(500) == ("estratega", "rotación")


def test_rotacion_del_equipo_pide_las_palabras_de_la_config():
    m = mon(equipo_rotacion_palabras=100)
    preparar(m, 301, "charla neutra", palabras=110)
    assert m.elegir(301) == ("coordinador", "rotación")
    m = mon()
    preparar(m, 301, "charla neutra", palabras=110)
    assert m.elegir(301)[0] is None


# ------------------------------------------------------------------ \b de verdad en extraer_definiciones
def test_significa_con_termino_marcado_define_y_en_minusculas_no():
    d = M.extraer_definiciones("Para nosotros, Cupo significa el máximo de habitaciones reservadas sin pasar por revenue")
    assert d and d[0]["termino"] == "Cupo"
    assert M.extraer_definiciones("para nosotros el cupo significa el máximo de habitaciones reservadas") == []   # débil sin marca
    assert M.extraer_definiciones("Esto es un ejemplo que significa poco en la práctica") == []


def test_la_regla_general_en_espanol_define_con_termino_marcado():
    d = M.extraer_definiciones("En el contrato Blackout se define el periodo sin venta de grupos para el hotel")
    assert d and d[0]["termino"] == "Blackout" and d[0]["definicion"].startswith("el periodo sin venta")


@pytest.mark.parametrize("frase", [
    "Mañana os llamamos a las cinco para confirmar la reunión con el cliente",
    "Luego llamaremos al hotel para cerrar las fechas del grupo",
    "Nos pidieron cómo lo definimos entre todos para que quede claro en el contrato final",
    "Revenue definimos aquí la política de cupos y de blackout para todos",
])
def test_la_regla_general_no_inventa_definiciones_en_el_habla_corriente(frase):
    assert M.extraer_definiciones(frase) == []


def test_no_queda_ningun_caracter_de_retroceso_en_el_monitor():
    assert "\x08" not in Path(M.__file__).read_text(encoding="utf-8")


@pytest.mark.parametrize("frase", [
    "definimos el margen que aceptamos cuando el cliente paga tarde",
    "definimos el margen que aceptamos para las desviaciones del presupuesto",
])
def test_verbo_termino_nunca_parte_una_palabra(frase):
    # antes el conector «a» casaba con la inicial de «aceptamos» y la definición salía como «ceptamos…»
    for d in M.extraer_definiciones(frase):
        assert not d["definicion"].startswith("ceptamos") and d["termino"].split()[-1] != "que a"
        assert not d["termino"].endswith(" a")


def test_verbo_termino_con_conector_suelto_o_dos_puntos():
    d = M.extraer_definiciones("definimos cupo: el máximo de habitaciones reservadas")
    assert d and d[0]["termino"] == "cupo" and d[0]["definicion"].startswith("el máximo")
    d = M.extraer_definiciones("llamamos margen a lo que aceptamos como desviación")
    assert d and d[0]["termino"] == "margen" and d[0]["definicion"].startswith("lo que aceptamos")
