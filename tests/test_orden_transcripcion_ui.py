"""La transcripción se pinta por minuto, no por orden de llegada (web/reunion.js, respaldo en web/app.js), y el aviso de estado y el nodo del transcriptor dicen la
verdad con los campos nuevos del servidor (`retraso_reunion_s`, `rezagado_s`, `eco_descartado_s`; web/app.js, web/agentes.js).

El transcriptor atiende primero a Reunión, deja para después lo que lleva más de 30 s esperando y para el final el eco del micro: los textos llegan fuera de orden
(un tramo atrasado llega minutos después con su minuto original; Micro y Reunión se intercalan). Los `id` van por orden de llegada y no cambian.
Dinámicos en un Edge/Chrome sin cabeza sobre la interfaz REAL con dobles de `fetch` y `WebSocket` (ver `_visual_harness.py`); sin servidor ni modelo."""
from __future__ import annotations

import json
import socket
import time

import pytest

from _visual_harness import Edge, foto, pagina_html


def _puerto():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def pagina(tmp_path_factory):
    return pagina_html(tmp_path_factory.mktemp("orden-trans-ui") / "app.html")


@pytest.fixture(scope="module")
def edge(tmp_path_factory):
    e = Edge(tmp_path_factory.mktemp("edge-orden-trans"), _puerto())
    yield e
    e.cerrar()


def seg(i, t, fuente="reunion", texto=None):
    return {"id": i, "t": t, "mmss": f"{int(t) // 60:02d}:{int(t) % 60:02d}", "fuente": fuente, "texto": texto or f"Línea ficticia número {i} de la prueba."}


def arrancar(e, pagina, segmentos=(), **extra):
    e.abrir(pagina.as_uri())
    e.js("localStorage.clear(); sessionStorage.clear(); 1")
    e.abrir(pagina.as_uri())
    e.js("window.__emitir(Object.assign({tipo: 'snapshot'}, %s)); 1" % json.dumps(foto(segmentos=list(segmentos), **extra)))
    time.sleep(0.5)


def llega(e, s):
    e.js("window.__emitir(%s); 1" % json.dumps({"tipo": "segmento", **s}))


def ids(e):
    return e.js("[...document.querySelectorAll('#r-trans .lin')].map((l) => Number(l.dataset.id))")


def cambian(e):
    return e.js("[...document.querySelectorAll('#r-trans .lin')].map((l) => l.classList.contains('cambia'))")


def estado(e, **tr):
    e.js("window.__emitir(%s); 1" % json.dumps({"tipo": "estado", "estado": "grabando", "transcripcion": {"estado": "listo", "error": "", **tr}}))
    time.sleep(0.4)


def aviso(e):
    return e.js("(() => { const u = document.querySelector('#orq-ult'); return { texto: u.textContent, oculto: u.hidden, avisa: u.classList.contains('avisa') }; })()")


# ============================================================ orden
def test_segmentos_fuera_de_orden_acaban_por_minuto_y_a_igualdad_por_id(edge, pagina):
    arrancar(edge, pagina)
    for s in (seg(1, 100), seg(2, 200, "yo"), seg(3, 50), seg(4, 100, "yo"), seg(5, 150), seg(6, 50, "yo"), seg(7, 300)):   # llegan por orden de transcripción
        llega(edge, s)
    assert ids(edge) == [3, 6, 1, 4, 5, 2, 7]
    assert edge.js("AP.S.segmentos.map((s) => s.id)") == [3, 6, 1, 4, 5, 2, 7]       # S.segmentos se mantiene ordenado: quien lo lea no depende del orden de llegada
    assert edge.js("[...document.querySelectorAll('#r-trans .lin')].every((l, i, a) => !i || Number(a[i - 1].dataset.t) <= Number(l.dataset.t))")


def test_lo_habitual_va_al_final_y_un_id_repetido_no_duplica(edge, pagina):
    arrancar(edge, pagina)
    for s in (seg(1, 10), seg(2, 20), seg(3, 30), seg(2, 20)):
        llega(edge, s)
    assert ids(edge) == [1, 2, 3] and edge.js("AP.S.segmentos.length") == 3


def test_las_correcciones_y_los_chips_siguen_encontrando_la_linea_por_id_y_minuto(edge, pagina):
    arrancar(edge, pagina, [seg(1, 10), seg(2, 400)])
    llega(edge, seg(3, 200))
    assert ids(edge) == [1, 3, 2]
    edge.js("window.__emitir({tipo: 'segmento_eco', cambios: [{id: 3, texto: 'Texto sin eco.'}]}); 1")
    assert edge.js("document.querySelector('#r-trans .lin[data-id=\"3\"] .x').textContent") == "Texto sin eco."
    assert edge.js("AP.S.segmentos.find((s) => s.id === 3).texto") == "Texto sin eco."
    edge.js("window.__emitir({tipo: 'segmento_eco', cambios: [{id: 3, texto: ''}]}); 1")
    assert ids(edge) == [1, 2]
    llega(edge, seg(4, 390))   # el hueco que deja una línea quitada no descoloca a las siguientes
    assert ids(edge) == [1, 4, 2]
    edge.js("AP.hooks.irAlMinuto(395); 1")   # el chip de un minuto lleva a la línea de su minuto, no a la última que llegó
    time.sleep(0.5)
    assert edge.js("document.querySelector('#r-trans .lin.destino').dataset.id") == "4"


def test_cambia_se_calcula_con_la_vecina_real_y_tambien_en_la_siguiente(edge, pagina):
    arrancar(edge, pagina, [seg(1, 10), seg(3, 30)])
    assert cambian(edge) == [False, False]
    llega(edge, seg(2, 20, "yo"))                              # entra en medio y es de otro canal: ella cambia y la siguiente también
    assert ids(edge) == [1, 2, 3] and cambian(edge) == [False, True, True]
    arrancar(edge, pagina, [seg(1, 10), seg(3, 30, "yo")])     # la siguiente tenía cambio y al ponerle delante a su misma voz lo pierde
    assert cambian(edge) == [False, True]
    llega(edge, seg(2, 20, "yo"))
    assert ids(edge) == [1, 2, 3] and cambian(edge) == [False, True, False]
    arrancar(edge, pagina, [seg(5, 50)])                       # una atrasada que entra la primera: la que era primera ahora tiene vecina anterior
    llega(edge, seg(4, 5, "yo"))
    assert ids(edge) == [4, 5] and cambian(edge) == [False, True]


def test_pintar_una_instantanea_desordenada_pinta_ordenado(edge, pagina):
    arrancar(edge, pagina, [seg(5, 300), seg(2, 100, "yo"), seg(4, 100), seg(1, 50), seg(3, 200, "yo")])
    assert ids(edge) == [1, 2, 4, 3, 5]                        # por minuto y, a igualdad, por id
    assert edge.js("AP.S.segmentos.map((s) => s.id)") == [1, 2, 4, 3, 5]
    assert cambian(edge) == [False, True, True, True, True]
    llega(edge, seg(6, 150))                                   # y a partir de ahí sigue insertando bien
    assert ids(edge) == [1, 2, 4, 6, 3, 5]


def test_el_ultimo_segmento_es_el_mas_reciente_por_minuto(edge, pagina):
    arrancar(edge, pagina, [seg(1, 10), seg(2, 20, "yo")])
    llega(edge, seg(3, 500))
    llega(edge, seg(4, 100))                                   # llega la última pero es de un minuto anterior
    edge.js("window.__emitir({tipo: 'estado', estado: 'grabando'}); 1")
    time.sleep(0.4)
    assert edge.js("AP.S.segmentos[AP.S.segmentos.length - 1].id") == 3
    assert "08:20" in edge.js("document.querySelector('.nodo[data-nodo=reunion]').title")   # el nodo de Reunión dice el minuto de lo más reciente, no de lo último en llegar


# ============================================================ desplazamiento
def larga(n=90):
    return [seg(i, i * 10, "reunion" if i % 3 else "yo", "Una línea de prueba bastante larga para que el panel tenga que desplazarse " * 2) for i in range(1, n + 1)]


def distancia(e, id_ancla):
    return e.js("document.querySelector('#r-trans .lin[data-id=\"%d\"]').getBoundingClientRect().top - document.querySelector('#r-trans').getBoundingClientRect().top" % id_ancla)


def leer_arriba(e, id_ancla):
    """Deja al usuario leyendo hacia la mitad (no sigue el directo) y devuelve la distancia de la línea ancla al borde alto del panel."""
    e.js("(() => { const c = document.querySelector('#r-trans'); c.scrollTop = document.querySelector('#r-trans .lin[data-id=\"%d\"]').offsetTop - 40; c.dispatchEvent(new Event('scroll')); })()" % id_ancla)
    time.sleep(0.3)
    assert e.js("AP.UI.seguir") is False
    return distancia(e, id_ancla)


def test_leyendo_arriba_una_insercion_por_encima_no_mueve_lo_que_se_lee(edge, pagina):
    arrancar(edge, pagina, larga())
    assert edge.js("(() => { const c = document.querySelector('#r-trans'); return c.scrollHeight > c.clientHeight + 400; })()")
    antes = leer_arriba(edge, 40)
    llega(edge, seg(500, 15, "yo", "Un tramo atrasado que llega por encima de lo que se lee, con bastante texto como para ocupar más de una línea de la pantalla."))
    assert abs(distancia(edge, 40) - antes) <= 1
    time.sleep(0.3)
    assert abs(distancia(edge, 40) - antes) <= 1               # tampoco después: el navegador y la interfaz no compensan dos veces
    assert edge.js("AP.UI.seguir") is False


def test_leyendo_arriba_una_insercion_por_debajo_no_mueve_nada_y_ofrece_ir_al_final(edge, pagina):
    arrancar(edge, pagina, larga())
    antes = leer_arriba(edge, 40)
    edge.js("document.querySelector('#r-alfinal').hidden = true; 1")
    arriba = edge.js("(() => { AP.hooks.anadirSegmento(%s); return document.querySelector('#r-alfinal').hidden; })()" % json.dumps(seg(501, 5)))
    assert arriba is True                                      # lo nuevo queda por encima: la propia inserción no hace aparecer el botón
    edge.js("document.querySelector('#r-alfinal').hidden = true; 1")
    abajo = edge.js("(() => { AP.hooks.anadirSegmento(%s); return document.querySelector('#r-alfinal').hidden; })()" % json.dumps(seg(502, 905)))
    assert abajo is False                                      # lo nuevo queda por debajo de lo que se ve: sí
    llega(edge, seg(503, 450))                                 # insertada en medio, por debajo de lo que se lee
    time.sleep(0.3)
    assert edge.js("AP.UI.seguir") is False
    # la inserción 501 (por encima) movió el texto el alto de una línea y lo compensó: ni 502 ni 503 lo tocan
    assert abs(distancia(edge, 40) - antes) <= 1


def test_siguiendo_el_directo_una_insercion_por_encima_se_queda_abajo(edge, pagina):
    arrancar(edge, pagina, larga())
    edge.js("(() => { const c = document.querySelector('#r-trans'); c.scrollTop = c.scrollHeight; c.dispatchEvent(new Event('scroll')); })()")
    time.sleep(0.3)
    assert edge.js("AP.UI.seguir") is True
    llega(edge, seg(504, 15, "yo"))
    llega(edge, seg(505, 905))
    assert edge.js("(() => { const c = document.querySelector('#r-trans'); return c.scrollHeight - c.scrollTop - c.clientHeight; })()") <= 2
    assert edge.js("AP.UI.seguir") is True


def test_la_linea_insertada_conserva_el_resalte_nueva_solo_si_se_sigue_el_directo(edge, pagina):
    arrancar(edge, pagina, larga(10))
    llega(edge, seg(600, 25))
    assert edge.js("document.querySelector('#r-trans .lin[data-id=\"600\"]').classList.contains('nueva')")
    edge.js("AP.UI.seguir = false; 1")
    llega(edge, seg(601, 35))
    assert not edge.js("document.querySelector('#r-trans .lin[data-id=\"601\"]').classList.contains('nueva')")


# ============================================================ separador «Analizado hasta»
def secuencia(e):
    return e.js("[...document.querySelector('#r-trans').children].map((n) => n.classList.contains('sep-analizado') ? 'sep' : Number(n.dataset.id))")


TRAZA = [{"fila": "analisis", "n": 1, "t": 100.0, "hasta_t": 30, "hasta_id": 3, "id": "z1", "insights": 0, "objetivos": 0, "checks": 0}]


def test_el_separador_sigue_detras_de_su_linea_al_llegar_una_atrasada(edge, pagina):
    arrancar(edge, pagina, [seg(i, i * 10) for i in range(1, 7)], traza=TRAZA)
    assert secuencia(edge) == [1, 2, 3, "sep", 4, 5, 6]
    llega(edge, seg(100, 15, "yo"))                            # cae por encima de la analizada: se queda encima del separador y este no se mueve
    assert secuencia(edge) == [1, 100, 2, 3, "sep", 4, 5, 6]
    llega(edge, seg(101, 30, "yo"))                            # mismo minuto que la analizada y llega después: va detrás de ella, es decir, bajo el separador
    assert secuencia(edge) == [1, 100, 2, 3, "sep", 101, 4, 5, 6]
    llega(edge, seg(102, 25))                                  # justo delante de la analizada
    assert secuencia(edge) == [1, 100, 2, 102, 3, "sep", 101, 4, 5, 6]
    assert edge.js("document.querySelectorAll('#r-trans .sep-analizado').length") == 1
    assert edge.js("document.querySelector('#r-trans .sep-analizado').previousElementSibling.dataset.id") == "3"
    llega(edge, seg(103, 700))                                 # y lo normal, al final, tampoco lo toca
    assert secuencia(edge)[-1] == 103 and edge.js("document.querySelectorAll('#r-trans .sep-analizado').length") == 1


def test_el_separador_sigue_su_linea_si_la_instantanea_llega_desordenada(edge, pagina):
    arrancar(edge, pagina, [seg(5, 50), seg(3, 30), seg(1, 10), seg(4, 40), seg(2, 20)], traza=TRAZA)
    assert secuencia(edge) == [1, 2, 3, "sep", 4, 5]


# ============================================================ aviso de estado
def test_aviso_de_saturacion_gana_a_los_demas(edge, pagina):
    arrancar(edge, pagina)
    estado(edge, retraso_s=40.0, retraso_reunion_s=2.0, rezagado_s=12.4, eco_descartado_s=0.0, rapido=True)
    assert aviso(edge) == {"texto": "Transcripción saturada: 12 s de audio se transcribirán más tarde.", "oculto": False, "avisa": True}
    estado(edge, retraso_s=1.0, retraso_reunion_s=1.0, rezagado_s=1.2)                        # con el directo al día, el audio atrasado también se avisa
    assert aviso(edge)["texto"] == "Transcripción saturada: 1 s de audio se transcribirán más tarde."
    estado(edge, retraso_s=1.0, retraso_reunion_s=1.0, rezagado_s=1.0)                        # hasta 1 s no es noticia
    assert aviso(edge)["oculto"] is True


def test_aviso_de_que_solo_el_micro_va_atrasado(edge, pagina):
    arrancar(edge, pagina)
    estado(edge, retraso_s=21.0, retraso_reunion_s=1.0, rezagado_s=0.0, rapido=True)
    assert aviso(edge) == {"texto": "El texto del micro va con 21 s de retraso; el de la reunión va al día.", "oculto": False, "avisa": True}
    estado(edge, retraso_s=21.0, retraso_reunion_s=3.0, rezagado_s=0.0)                       # en el umbral de 3 s la reunión aún va al día
    assert aviso(edge)["texto"].startswith("El texto del micro va con 21 s")
    estado(edge, retraso_s=21.0, retraso_reunion_s=3.5, rezagado_s=0.0, rapido=True)          # por encima, el atraso es de los dos
    assert aviso(edge)["texto"] == "Transcripción con 21 s de retraso · alcanzando el directo"


def test_aviso_de_retraso_de_siempre_y_al_dia(edge, pagina):
    arrancar(edge, pagina)
    estado(edge, retraso_s=20.0, retraso_reunion_s=19.0, rezagado_s=0.0, rapido=True)
    assert aviso(edge)["texto"] == "Transcripción con 20 s de retraso · alcanzando el directo"
    estado(edge, retraso_s=20.0, retraso_reunion_s=19.0, rezagado_s=0.0, rapido=False)
    assert aviso(edge)["texto"] == "Transcripción con 20 s de retraso"
    estado(edge, retraso_s=4.0, retraso_reunion_s=4.0, rezagado_s=0.0)                        # la línea del equipo no avisa por debajo de 15 s
    assert aviso(edge)["oculto"] is True


def test_servidor_anterior_sin_campos_nuevos_dice_lo_de_siempre(edge, pagina):
    arrancar(edge, pagina)
    estado(edge, retraso_s=20.0, rapido=True, pendiente_s=30.0, aplazado_s=0.0, perdidos_s=0.0, velocidad_x=0.9)
    assert aviso(edge) == {"texto": "Transcripción con 20 s de retraso · alcanzando el directo", "oculto": False, "avisa": True}
    estado(edge, pendiente_s=25.0, rapido=False)                                              # aún más antiguo: solo audio pendiente
    assert aviso(edge)["texto"] == "Transcripción con 25 s de retraso"
    assert edge.js("[AP.avisoRetraso({retraso_s: 5}), AP.avisoRetraso({retraso_s: 3}), AP.avisoRetraso(null), AP.avisoRetraso({retraso_s: 5, retraso_reunion_s: 0}, 15)]") == [
        "Transcripción con 5 s de retraso", "", "", ""]                                        # el respaldo de app.js avisa desde 3 s; la línea del equipo, desde 15 s


@pytest.mark.parametrize("ancho", [1440, 1100])
def test_los_tres_avisos_caben_sin_romper_la_cabecera(edge, pagina, ancho):
    edge.cmd("Emulation.setDeviceMetricsOverride", width=ancho, height=900, deviceScaleFactor=1, mobile=False)
    try:
        arrancar(edge, pagina)
        estado(edge, retraso_s=0.0)
        alto0 = edge.js("Math.round(document.querySelector('.orq').getBoundingClientRect().height)")   # la banda no puede crecer por el aviso: es una columna estrecha y el texto envuelve
        for campos in ({"retraso_s": 400.0, "retraso_reunion_s": 3.0, "rezagado_s": 480.0}, {"retraso_s": 44.0, "retraso_reunion_s": 1.0}, {"retraso_s": 444.0, "retraso_reunion_s": 400.0, "rapido": True}):
            estado(edge, **campos)
            m = edge.js("""(() => { const u = document.querySelector('#orq-ult'), r = u.getBoundingClientRect(), cs = getComputedStyle(u), cab = document.querySelector('.orq');
              return { visible: !!u.offsetParent && !u.hidden, lineas: Math.round(r.height / parseFloat(cs.lineHeight)), derecha: Math.round(r.right), ancho: innerWidth,
                       horizontal: document.documentElement.scrollWidth - innerWidth, desborda: u.scrollWidth - u.clientWidth, alto: Math.round(cab.getBoundingClientRect().height), cab_der: cab ? Math.round(cab.getBoundingClientRect().right) : null }; })()""")
            assert m["visible"] and m["lineas"] <= 4 and m["alto"] == alto0 and m["derecha"] <= m["ancho"] and m["horizontal"] <= 0 and m["desborda"] <= 1, (campos, m)
            if m["cab_der"] is not None:
                assert m["derecha"] <= m["cab_der"] + 1, (campos, m)
    finally:
        edge.cmd("Emulation.setDeviceMetricsOverride", width=1440, height=900, deviceScaleFactor=1, mobile=False)


# ============================================================ nodo del transcriptor
def nodo(e):
    return e.js("document.querySelector('.nodo[data-nodo=transcriptor]').title")   # el texto completo va al tooltip: en el nodo solo cabe lo esencial


def test_el_nodo_del_transcriptor_dice_audio_atrasado_y_eco_descartado(edge, pagina):
    arrancar(edge, pagina)
    estado(edge, retraso_s=2.0, retraso_reunion_s=1.0, rezagado_s=20.2, eco_descartado_s=7.7, aplazado_s=0.0)
    t = nodo(edge)
    assert "audio atrasado 20 s" in t and "eco descartado 8 s" in t, t
    estado(edge, retraso_s=2.0, retraso_reunion_s=1.0, rezagado_s=1.0, eco_descartado_s=1.0)   # hasta 1 s no se dice
    t = nodo(edge)
    assert "audio atrasado" not in t and "eco descartado" not in t, t
    estado(edge, retraso_s=2.0)                                                                  # servidor anterior: sin los campos nuevos y sin error
    t = nodo(edge)
    assert "audio atrasado" not in t and "eco descartado" not in t, t
    estado(edge, retraso_s=30.0, rapido=True, aplazado_s=12.0, rezagado_s=33.0, eco_descartado_s=9.0)   # y junto a los de siempre
    t = nodo(edge)
    assert "retraso 30 s" in t and "modo rápido" in t and "eco en espera 12 s" in t and "audio atrasado 33 s" in t and "eco descartado 9 s" in t, t


def test_el_nodo_tambien_lo_dice_mientras_transcribe(edge, pagina):
    arrancar(edge, pagina)
    edge.js("window.__emitir(%s); 1" % json.dumps({"tipo": "tarea", "id": 901, "agente": "transcriptor", "nombre": "Transcriptor", "tarea": "transcribir", "modelo": "local",
                                                    "fase": "inicio", "estado": "en_curso", "tramo": "tramo atrasado", "hora": time.strftime("%H:%M:%S")}))
    estado(edge, retraso_s=2.0, rezagado_s=60.0, eco_descartado_s=0.0)
    t = nodo(edge)
    assert "audio atrasado 60 s" in t, t
