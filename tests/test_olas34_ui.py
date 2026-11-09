"""Olas 3 y 4 en la interfaz (contratos en `demo/api-ola3.md` y `demo/api-ola4.md`): bandeja de acciones, autonomía, preparación sugerida, seguimiento, palabras dudosas, «Esto está
mal», modo solo local y registro de envíos, plantillas, cartera y métricas. Edge/Chrome sin cabeza sobre la interfaz REAL con un doble de la API (`_olas34_stub.py`; datos ficticios)."""
from __future__ import annotations

import json
import re
import socket
import time

import pytest

import _olas34_stub as ST
from _visual_harness import WEB, Edge, foto, pagina_html

REV = {"estado": "lista", "resumen": "Se acordó mantener el piloto el 20 de enero.", "resumen_sonnet": "Resumen.", "error": "", "aplicado": None, "carpeta_contexto": True, "compartido": False, "destino_contexto": "",
       "sin_cambios": "", "pulido": {"estado": "ninguno", "resumen": "", "error": "", "elegida": "sonnet"}, "avisos": [], "publicacion": None, "objetivos": [], "correo": "Asunto: Resumen: Piloto (06/11/2026)\n\nHola:\n\nUn saludo.",
       "cambios": [{"id": "c1", "fichero": "02-alcance.md", "motivo": "Alcance de la fase 1", "minuto": "02:10", "valido": True, "preaceptado": True, "cita": {"texto": "eso estaba fuera de alcance, lo acordamos en el kick off", "minuto": "02:45"},
                    "diff": "--- a/02-alcance.md\n+++ b/02-alcance.md\n@@ -1 +1,2 @@\n-Fase 1\n+Fase 1 sin SAP\n"}], "metricas": ST.METRICAS}
LOCAL = {"activo": True, "sesion": True, "config": False, "agentes_cierre_confirmados": False}


def _puerto():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def pagina(tmp_path_factory):
    return pagina_html(tmp_path_factory.mktemp("olas34") / "app.html")


@pytest.fixture(scope="module")
def edge(tmp_path_factory):
    e = Edge(tmp_path_factory.mktemp("edge-olas34"), _puerto(), ancho=1280, alto=720)
    yield e
    e.cerrar()


def abrir(edge, pagina, estado="grabando", stub=None, **cam):
    edge.cmd("Emulation.setDeviceMetricsOverride", width=1280, height=720, deviceScaleFactor=1, mobile=False)
    edge.cmd("Emulation.setEmulatedMedia", features=[{"name": "prefers-color-scheme", "value": "dark"}])
    edge.abrir(pagina.as_uri())
    edge.js("localStorage.clear(); sessionStorage.clear(); 1")
    edge.abrir(pagina.as_uri())
    ST.instalar(edge, **(stub or {}))
    base = {"estado": estado}
    if estado == "inactivo":
        base.update(sesion=None, revision=None)
    base.update(cam)
    edge.js("window.__emitir(Object.assign({tipo: 'snapshot'}, %s)); 1" % json.dumps(foto(**base)))
    if estado == "inactivo":
        edge.js("AP.cargarProyectos(); 1")
    time.sleep(0.8)


def llamadas(edge, patron=None):
    ll = json.loads(edge.js("JSON.stringify(window.__llamadas)"))
    return [l for l in ll if not patron or re.search(patron, l[0] + " " + l[1])]


def con_palabras(seg, dudosa=3):
    pal = [{"w": w, "p": 0.9, "d": False} for w in seg["texto"].split(" ")]
    pal[dudosa]["d"], pal[dudosa]["p"] = True, 0.31
    return dict(seg, palabras=pal, dudosas=1)


def reunion(edge, pagina, **extra):
    f = foto(estado="grabando")
    segs = [con_palabras(s) if i in (4, 7) else s for i, s in enumerate(f["segmentos"])]
    abrir(edge, pagina, "grabando", acciones=json.loads(json.dumps(ST.ACCIONES)), segmentos=segs, modo_local={"activo": False, "sesion": False, "config": False, "agentes_cierre_confirmados": False}, **extra)
    edge.js("AP.hooks.irAlMinuto && 1; 1")


# ============================================================ 1. bandeja de acciones
def test_bandeja_de_acciones_en_ahora_con_origen_cita_y_los_tres_modos(edge, pagina):
    reunion(edge, pagina)
    r = json.loads(edge.js("""JSON.stringify({ oculto: document.querySelector('#ahora-acciones').hidden, items: [...document.querySelectorAll('#ahora-acciones .acc-item')].map((i) => ({ id: i.dataset.id, estado: i.dataset.estado, modo: i.dataset.modo,
      botones: [...i.querySelectorAll('.acc-bt button')].map((b) => b.textContent.trim()), origen: i.querySelector('.ag .ag-n') ? i.querySelector('.ag .ag-n').textContent : null, color: i.querySelector('.ag') ? getComputedStyle(i.querySelector('.ag')).color : null,
      cita: i.querySelector('.acc-cita') ? i.querySelector('.acc-cita').textContent : null, estadoTxt: i.querySelector('.acc-estado') ? i.querySelector('.acc-estado').textContent : null })) })"""))
    por = {i["id"]: i for i in r["items"]}
    assert r["oculto"] is False and set(por) == {"a1", "a2", "a3"}, r
    assert por["a1"]["botones"] == ["Aceptar", "Editar", "Descartar"] and por["a1"]["origen"] == "Capitán" and "yo las envío el viernes" in por["a1"]["cita"] and "04:12" in por["a1"]["cita"], por["a1"]
    assert por["a2"]["modo"] == "avisar" and por["a2"]["botones"] == [] and por["a2"]["estadoTxt"] == "Solo es un aviso", por["a2"]          # modo avisar: sin botones
    assert por["a3"]["botones"] == ["Deshacer"] and por["a3"]["estadoTxt"] == "Lo hizo el equipo" and por["a3"]["origen"] == "Arquitecto", por["a3"]   # auto: «Lo hizo el equipo» con Deshacer
    assert len({i["color"] for i in r["items"]}) >= 2                                                                                           # cada agente, su color


def test_aceptar_editar_descartar_y_deshacer_llaman_a_sus_endpoints(edge, pagina):
    reunion(edge, pagina)
    edge.js("document.querySelector('#ahora-acciones [data-id=a1] [data-accion=aceptar]').click(); 1")
    time.sleep(0.5)
    assert [l[:2] for l in llamadas(edge, r"api/acciones")] == [["POST", "/api/acciones/a1/aceptar"]]
    assert edge.js("document.querySelector('#ahora-acciones [data-id=a1]').dataset.estado") == "aceptada"            # el evento `acciones` repinta
    edge.js("document.querySelector('#ahora-acciones [data-id=a3] [data-accion=deshacer]').click(); 1")
    time.sleep(0.5)
    assert ["POST", "/api/acciones/a3/reabrir", None] in llamadas(edge, r"reabrir")
    assert edge.js("document.querySelector('#ahora-acciones [data-id=a3]').dataset.estado") == "propuesta"
    # Editar: diálogo propio, PUT con el texto nuevo
    edge.js("document.querySelector('#ahora-acciones [data-id=a3] [data-accion=editar]').click(); 1")
    time.sleep(0.3)
    assert edge.js("!!document.querySelector('.dp-caja')") is True
    edge.js("(() => { const c = document.querySelector('.dp-campo'); c.value = 'Añadir que SAP queda para la fase 2'; document.querySelector('[data-dp=aceptar]').click(); return 1; })()")
    time.sleep(0.5)
    put = llamadas(edge, r"^PUT /api/acciones")
    assert put and put[-1][2] == {"texto": "Añadir que SAP queda para la fase 2"}, put
    edge.js("document.querySelector('#ahora-acciones [data-id=a1] [data-accion=descartar], #ahora-acciones [data-id=a3] [data-accion=descartar]').click(); 1")
    time.sleep(0.5)
    assert any(l[1].endswith("/descartar") for l in llamadas(edge, r"descartar"))
    assert edge.js("!!document.querySelector('#ahora-acciones .acc-desc')") is True                                  # las descartadas, plegadas aparte


def test_las_acciones_tambien_salen_en_la_revision(edge, pagina):
    abrir(edge, pagina, "revision", revision=REV, acciones=json.loads(json.dumps(ST.ACCIONES)))
    edge.js("document.querySelector('#rev-stepper .rev-st[data-paso=\"4\"]').click(); 1")
    time.sleep(0.4)
    r = json.loads(edge.js("""JSON.stringify({ items: [...document.querySelectorAll('#rev-paso-4 #rev-acciones .acc-item')].map((i) => i.dataset.id), titulo: document.querySelector('#rev-acciones .t-label').textContent,
      botones: [...document.querySelectorAll('#rev-acciones [data-id=a1] .acc-bt button')].map((b) => b.textContent.trim()) })"""))
    assert r["items"] == ["a1", "a2"] and r["titulo"] == "Acciones propuestas" and r["botones"] == ["Aceptar", "Editar", "Descartar"], r
    edge.js("document.querySelector('#rev-acciones [data-id=a1] [data-accion=aceptar]').click(); 1")
    time.sleep(0.5)
    assert edge.js("document.querySelector('#rev-acciones [data-id=a1]').dataset.estado") == "aceptada"


def test_con_autonomia_proponer_lo_preaceptado_sale_resaltado_pero_sin_marcar(edge, pagina):
    abrir(edge, pagina, "revision", revision=REV)
    edge.js("document.querySelector('#rev-stepper .rev-st[data-paso=\"2\"]').click(); 1")
    r = json.loads(edge.js("""JSON.stringify({ dec: document.querySelector('.cambio[data-id=c1]').dataset.decision, res: document.querySelector('.cambio[data-id=c1]').classList.contains('preaceptado'), cita: document.querySelector('.cambio[data-id=c1] .pre-cita').textContent })"""))
    assert r["dec"] == "" and r["res"] is True and "kick off" in r["cita"] and "02:45" in r["cita"], r                 # la cita es {texto, minuto}


# ============================================================ 2. autonomía en Ajustes › Equipo
def _ajustes(edge, pestana):
    edge.js("document.querySelector('#b-ajustes').click(); 1")
    time.sleep(0.9)
    edge.js("document.querySelector('#aj-tab-%s').click(); 1" % pestana)
    time.sleep(0.3)


def test_autonomia_un_selector_por_tipo_y_hacer_solo_donde_se_admite(edge, pagina):
    abrir(edge, pagina)
    _ajustes(edge, "equipo")
    r = json.loads(edge.js("""JSON.stringify([...document.querySelectorAll('#aj-aut-lista select')].map((s) => ({ tipo: s.dataset.tipo, valor: s.value, hacer: s.querySelector('option[value=hacer]').disabled, opciones: [...s.options].map((o) => o.value),
      nota: document.getElementById(s.getAttribute('aria-describedby')).textContent })))"""))
    por = {x["tipo"]: x for x in r}
    assert list(por) == ["pregunta", "pendiente", "cambio_contexto", "correo", "recordatorio", "consolidar_pendientes"], list(por)
    assert all(x["opciones"] == ["avisar", "proponer", "hacer"] for x in r)
    assert [t for t, x in por.items() if not x["hacer"]] == ["cambio_contexto", "consolidar_pendientes"] and por["consolidar_pendientes"]["valor"] == "hacer", por   # «hacer» desactivado en el resto
    assert "no está disponible" in por["correo"]["nota"] and "se puede deshacer" in por["cambio_contexto"]["nota"]
    edge.js("(() => { const s = document.querySelector('#aj-aut-lista [data-tipo=cambio_contexto]'); s.value = 'hacer'; s.dispatchEvent(new Event('change', { bubbles: true })); const c = document.querySelector('#aj-aut-lista [data-tipo=correo]'); c.value = 'avisar'; return 1; })()")
    edge.js("document.querySelector('#f-ajustes').requestSubmit(); 1")
    time.sleep(0.8)
    put = llamadas(edge, r"^PUT /api/autonomia")
    assert put and put[-1][2] == {"autonomia": {"cambio_contexto": "hacer", "correo": "avisar"}}, put                     # solo lo que cambia
    # con «hacer», lo preaceptado sale marcado
    edge.js("window.__emitir(Object.assign({tipo: 'snapshot'}, %s)); 1" % json.dumps(foto(estado="revision", revision=REV)))
    time.sleep(0.5)
    edge.js("document.querySelector('#rev-stepper .rev-st[data-paso=\"2\"]').click(); 1")
    assert edge.js("document.querySelector('.cambio[data-id=c1]').dataset.decision") == "si"


# ============================================================ 3. brief en la ficha y en Preparar
def test_brief_en_la_ficha_con_estado_de_carga_anadir_actualizar_y_copiar(edge, pagina):
    abrir(edge, pagina, "inactivo", stub={"brief_retardo": 700})
    edge.js("window.__copiado = null; navigator.clipboard.writeText = async (t) => { window.__copiado = t; }; AP.proyectos.abrirPanel('Alfa Demo'); 1")
    time.sleep(0.3)
    assert edge.js("document.querySelector('#pp-brief .brief-carga') !== null && document.querySelector('#pp-brief .brief').getAttribute('aria-busy')") == "true"   # mientras carga
    time.sleep(1.2)
    r = json.loads(edge.js("""JSON.stringify({ obj: [...document.querySelectorAll('#pp-brief .brief-sec')][0].querySelector('.t-label').textContent, filas: [...document.querySelectorAll('#pp-brief .brief-lista li .brief-t')].map((x) => x.textContent),
      secs: [...document.querySelectorAll('#pp-brief .brief-sec .t-label')].map((x) => x.textContent) })"""))
    assert r["secs"][:3] == ["Objetivos propuestos", "Preguntas para hacer", "Datos que pedir"] and "Cerrar el modelo de datos" in r["filas"], r
    edge.js("document.querySelector('#pp-brief .brief-anadir').click(); 1")
    assert json.loads(edge.js("JSON.stringify(AP.UI.objetivosPropios)")) == ["Cerrar el modelo de datos"]                  # entra en los objetivos de la reunión
    assert edge.js("document.querySelector('#pp-brief .brief-anadir').textContent") == "Añadido"
    edge.js("document.querySelector('#pp-brief [data-accion=copiar]').click(); 1")
    time.sleep(0.3)
    assert "Cerrar el modelo de datos" in edge.js("window.__copiado") and "¿Quién valida el modelo de datos?" in edge.js("window.__copiado")
    edge.js("document.querySelector('#pp-brief [data-accion=actualizar]').click(); 1")
    time.sleep(1.3)
    assert any("brief?refrescar=1" in l[1] for l in llamadas(edge, r"brief"))


def test_brief_sin_modelo_se_ve_la_version_local_sin_errores_y_un_fallo_se_puede_reintentar(edge, pagina):
    local = dict(ST.BRIEF, origen="local", aviso="No se pudo llamar al modelo: se muestra la versión local.", objetivos=["Revisar los pendientes abiertos"], preguntas=[], datos=[])
    abrir(edge, pagina, "inactivo", stub={"brief": local})
    edge.js("AP.proyectos.abrirPanel('Alfa Demo'); 1")
    time.sleep(0.8)
    txt = edge.js("document.querySelector('#pp-brief').innerText")
    assert "Versión local, sin Claude" in txt and "versión local" in txt and "Revisar los pendientes abiertos" in txt and not edge.js("!!document.querySelector('#pp-brief .error')")
    abrir(edge, pagina, "inactivo", stub={"brief_error": True})
    edge.js("AP.proyectos.abrirPanel('Alfa Demo'); 1")
    time.sleep(0.8)
    assert "No se pudo preparar" in edge.js("document.querySelector('#pp-brief').innerText") and edge.js("document.querySelector('#pp-brief .btn').textContent") == "Reintentar"


def test_brief_en_preparar_anade_a_los_objetivos_de_la_reunion(edge, pagina):
    abrir(edge, pagina, "inactivo")
    edge.js("AP.proyectos.empezarEn('Alfa Demo'); 1")
    time.sleep(1.0)
    assert edge.js("document.querySelector('#i-brief').hidden") is False
    edge.js("document.querySelector('#i-brief .brief-anadir').click(); 1")
    time.sleep(0.3)
    assert "Cerrar el modelo de datos" in edge.js("document.querySelector('#i-obj-lista').innerText")


# ============================================================ 4. seguimiento en la ficha
def test_seguimiento_pendientes_con_estado_cita_reabrir_y_marcar_hecho(edge, pagina):
    abrir(edge, pagina, "inactivo")
    edge.js("AP.proyectos.abrirPanel('Alfa Demo'); 1")
    time.sleep(1.0)
    r = json.loads(edge.js("""JSON.stringify({ cab: document.querySelector('#pp-seguimiento .vp-sub').innerText, filas: [...document.querySelectorAll('#pp-seguimiento .seg-f')].map((f) => ({ id: f.dataset.id, estado: f.dataset.estado,
      botones: [...f.querySelectorAll('button')].map((b) => b.textContent), cita: f.querySelector('.seg-cita') ? f.querySelector('.seg-cita').textContent : null, linea: f.querySelector('.seg-l2').textContent })) })"""))
    por = {f["id"]: f for f in r["filas"]}
    assert "2 abiertos" in r["cab"] and "1 hechos" in r["cab"], r["cab"]
    assert por["1111111111111111"]["estado"] == "hecho" and por["1111111111111111"]["botones"] == ["Reabrir"] and "sesión 2026-10-27 · Seguimiento" in por["1111111111111111"]["cita"] and "quedó validada" in por["1111111111111111"]["cita"], por
    assert "Cerrado por la app" in por["1111111111111111"]["linea"] and por["2222222222222222"]["botones"] == ["Marcar hecho"], por
    assert [f["estado"] for f in r["filas"]] == ["abierto", "abierto", "hecho"]                                               # abiertos primero
    edge.js("document.querySelector('#pp-seguimiento [data-id=\"2222222222222222\"] [data-accion=hecho]').click(); 1")
    time.sleep(0.7)
    assert ["POST", "/api/proyectos/Alfa%20Demo/seguimiento/2222222222222222/hecho", None] in llamadas(edge, r"seguimiento/2222")
    assert edge.js("document.querySelector('#pp-seguimiento [data-id=\"2222222222222222\"]').dataset.estado") == "hecho"
    edge.js("document.querySelector('#pp-seguimiento [data-id=\"1111111111111111\"] [data-accion=reabrir]').click(); 1")
    time.sleep(0.7)
    assert any(l[1].endswith("1111111111111111/reabrir") for l in llamadas(edge, r"reabrir")) and edge.js("document.querySelector('#pp-seguimiento [data-id=\"1111111111111111\"]').dataset.estado") == "abierto"


# ============================================================ 5. palabras dudosas
def test_palabras_dudosas_subrayadas_accesibles_y_corregibles_con_glosario(edge, pagina):
    reunion(edge, pagina)
    r = json.loads(edge.js("""JSON.stringify({ n: document.querySelectorAll('#r-trans .pd').length, tag: document.querySelector('#r-trans .pd').tagName, subrayado: getComputedStyle(document.querySelector('#r-trans .pd')).textDecorationLine,
      aria: document.querySelector('#r-trans .pd').getAttribute('aria-label'), tab: document.querySelector('#r-trans .pd').tabIndex, sinDatos: document.querySelectorAll('#r-trans .lin:not(:has(.pd)) .x button').length,
      alto: parseFloat(getComputedStyle(document.querySelector('#r-trans .pd'), '::after').height) })"""))
    assert r["n"] == 2 and r["tag"] == "BUTTON" and "underline" in r["subrayado"] and r["tab"] == 0 and "Palabra dudosa" in r["aria"] and r["sinDatos"] == 0 and r["alto"] >= 32, r
    edge.js("(() => { const b = document.querySelector('#r-trans .pd'); b.scrollIntoView({ block: 'center' }); b.focus(); b.click(); return 1; })()")
    time.sleep(0.3)
    assert edge.js("document.querySelector('#corr') !== null && document.activeElement.id") == "corr-texto"
    edge.js("(() => { document.querySelector('#corr-texto').value = 'Nórdia'; document.querySelector('#corr-gl').checked = true; document.querySelector('#corr-ok').click(); return 1; })()")
    time.sleep(0.5)
    c = llamadas(edge, r"corregir")
    assert c and re.fullmatch(r"/api/sesion/segmento/\d+/corregir", c[-1][1]), c
    assert c[-1][2]["glosario"] == "proyecto" and "Nórdia" in c[-1][2]["texto"] and c[-1][2]["termino"] == "Nórdia", c[-1][2]
    assert "Corregido en este segmento y en 4 sitios derivados" in edge.js("document.querySelector('#corr-estado').textContent")      # límites dichos a las claras
    # el evento `segmento_corregido` quita el subrayado de ese segmento y pone el texto nuevo
    sid = c[-1][1].split("/")[4]
    edge.js("window.__emitir({tipo: 'segmento_corregido', segmento: { id: %s, texto: 'Texto corregido de ejemplo', corregido: true }, sustituciones: [['a', 'b']], propagado: {} }); 1" % sid)
    time.sleep(0.4)
    assert edge.js("document.querySelector('#r-trans [data-id=\"%s\"] .x').textContent" % sid) == "Texto corregido de ejemplo" and edge.js("document.querySelectorAll('#r-trans .pd').length") == 1


def test_anadir_al_glosario_desde_la_ventanita_y_esc_devuelve_el_foco(edge, pagina):
    reunion(edge, pagina)
    edge.js("(() => { const b = document.querySelector('#r-trans .pd'); b.scrollIntoView({ block: 'center' }); b.focus(); b.click(); document.querySelector('#corr-texto').value = 'Cupo Flex'; document.querySelector('#corr-glosario').click(); return 1; })()")
    time.sleep(0.5)
    g = llamadas(edge, r"api/glosario")
    assert g and g[-1][2] == {"termino": "Cupo Flex", "proyecto": "Proyecto Ficticio Alfa"}, g
    assert "Añadido al glosario" in edge.js("document.querySelector('#corr-estado').textContent")
    edge.js("document.querySelector('#corr-texto').dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true })); 1")
    time.sleep(0.2)
    assert edge.js("document.querySelector('#corr')") is None and "pd" in edge.js("document.activeElement.className")


# ============================================================ 6. «Esto está mal» y avisos silenciados
def test_esto_esta_mal_en_el_monitor_y_en_las_tarjetas_con_deshacer(edge, pagina):
    f = foto(estado="grabando")
    feed = f["monitor"]["feed"]
    feed[0].update(regla_tipo="senal:sistema", regla_texto="señal: sistema")
    abrir(edge, pagina, "grabando", monitor=dict(f["monitor"], feed=feed), tarjetas=[dict(t, id=f"t9-{i:04d}") for i, t in enumerate(f["tarjetas"])])
    edge.js("document.querySelector('.nodo[data-nodo=equipo]').click(); 1")             # §0 Estéreo · flujo (2026-11-09): el detalle del equipo lo abre el nodo «Equipo», no desplegar la banda
    time.sleep(0.6)
    botones = json.loads(edge.js("JSON.stringify([...document.querySelectorAll('#eq-feed-lista > *')].map((x) => [x.className, !!x.querySelector('[data-accion=mal]')]))"))
    assert sum(1 for b in botones if b[1]) == 1, botones                                                                    # solo el que trae `regla_tipo` se puede silenciar
    edge.js("document.querySelector('#eq-feed-lista [data-accion=mal]').click(); 1")
    time.sleep(0.5)
    p = llamadas(edge, r"/mal$")
    assert p and p[-1][0] == "POST" and re.fullmatch(r"/api/avisos/m\d+/mal", p[-1][1]), p
    assert "Silenciado" in edge.js("document.querySelector('#eq-feed-lista .mal-hecho').textContent")
    edge.js("document.querySelector('#eq-feed-lista [data-accion=deshacer-mal]').click(); 1")
    time.sleep(0.5)
    assert llamadas(edge, r"^DELETE /api/reglas-silencio/")
    # tarjetas de agente (Avisos)
    edge.js("document.querySelector('.nodo[data-nodo=equipo]').click(); 1")             # cierra el detalle
    edge.js("document.querySelector('#r-insights .tarj[data-id=\"t9-0000\"] [data-accion=mal]').click(); 1")
    time.sleep(0.5)
    assert any(re.fullmatch(r"/api/avisos/t9-0000/mal", l[1]) for l in llamadas(edge, r"/mal$"))
    assert "Silenciado" in edge.js("document.querySelector('#r-insights .tarj[data-id=\"t9-0000\"] .mal-hecho').textContent")


def test_ajustes_equipo_lista_los_avisos_silenciados_y_permite_borrarlos(edge, pagina):
    abrir(edge, pagina)
    _ajustes(edge, "equipo")
    r = json.loads(edge.js("JSON.stringify([...document.querySelectorAll('#aj-sil-lista .aj-sil-f')].map((f) => [f.dataset.id, f.innerText, f.querySelector('button').textContent]))"))
    assert r and r[0][0] == "9f2c1a7b3d0e" and "para el viernes que viene" in r[0][1] and "4 veces" in r[0][1] and r[0][2] == "Borrar", r
    edge.js("document.querySelector('#aj-sil-lista .aj-sil-f button').click(); 1")
    time.sleep(0.6)
    assert llamadas(edge, r"^DELETE /api/reglas-silencio/9f2c1a7b3d0e") and "No has silenciado ningún aviso" in edge.js("document.querySelector('#aj-sil-lista').innerText")


# ============================================================ 7. privacidad: modo local y registro de envíos
def test_ajustes_privacidad_modo_local_y_registro_de_envios_con_resumen(edge, pagina):
    abrir(edge, pagina, "inactivo")
    _ajustes(edge, "privacidad")
    r = json.loads(edge.js("""JSON.stringify({ solo: document.querySelector('#aj-solo-local').hidden, reg: document.querySelector('#aj-registro-envios').hidden, res: document.querySelector('#aj-registro-res').textContent,
      filas: [...document.querySelectorAll('#aj-registro-lista .aj-reg-f')].map((f) => f.innerText.replace(/\\s+/g, ' ')) })"""))
    assert r["solo"] is False and r["reg"] is False and "2 llamadas en total" in r["res"] and "7,8k tokens" in r["res"], r
    assert r["filas"][0].startswith("10:38") and "Capitán" in r["filas"][0] and "Enviado" in r["filas"][0] and "10:32" in r["filas"][1] and "Analista" in r["filas"][1], r["filas"]   # qué salió, a qué agente, tokens y hora
    edge.js("document.querySelector('#aj-modo-local').click(); 1")
    time.sleep(0.5)
    assert ["POST", "/api/modo-local", {"activo": True}] in llamadas(edge, r"modo-local")


def test_preparar_con_solo_local_y_plantilla_se_envian_al_iniciar_y_empezar_sigue_a_la_vista(edge, pagina):
    abrir(edge, pagina, "inactivo")
    edge.js("AP.proyectos.empezarEn('Alfa Demo'); 1")
    time.sleep(1.0)
    ch = json.loads(edge.js("JSON.stringify([...document.querySelectorAll('#i-plantillas [role=radio]')].map((b) => b.textContent))"))
    assert ch == ["Descubrimiento", "Diseño funcional", "Seguimiento", "Comité", "Ninguna"], ch
    assert edge.js("document.querySelector('#i-plantillas [aria-checked=true]') === null") is True or edge.js("document.querySelector('#i-plantillas [aria-checked=true]').textContent") == "Ninguna"
    edge.js("document.querySelector('#i-plantillas [data-plantilla=comite]').click(); 1")
    time.sleep(0.3)
    r = json.loads(edge.js("""JSON.stringify({ obj: [...document.querySelectorAll('#i-plantilla-detalle .pl-obj li')].map((x) => x.textContent), bajo: Math.round(document.querySelector('#i-empezar').getBoundingClientRect().bottom), alto: innerHeight,
      tapa: (() => { const b = document.querySelector('#i-empezar').getBoundingClientRect(); const e = document.elementFromPoint(b.left + b.width / 2, b.top + b.height / 2); return e && (e.id === 'i-empezar' || !!e.closest('#i-empezar')); })(),
      izq: Math.round(document.querySelector('.ini-izq').getBoundingClientRect().bottom), barra: Math.round(document.querySelector('.ini-barra').getBoundingClientRect().top), ancho: document.querySelector('#i-plantillas').scrollWidth <= document.querySelector('#i-plantillas').clientWidth + 1,
      filasChips: new Set([...document.querySelectorAll('#i-plantillas button')].map((b) => Math.round(b.getBoundingClientRect().top))).size })"""))
    assert r["obj"] == ["Presentar el estado", "Tomar las decisiones pendientes"] or len(r["obj"]) >= 2, r
    assert r["bajo"] <= r["alto"] and r["tapa"] is True and r["izq"] <= r["barra"], r                                                  # la columna izquierda no pasa por debajo de la barra y «Empezar» se ve sin scroll
    edge.js("(() => { document.querySelector('#i-local').click(); const t = document.querySelector('#i-tema'); t.value = 'Seguimiento del piloto'; t.dispatchEvent(new Event('input', { bubbles: true })); const a = document.querySelector('#i-aviso'); a.click(); a.dispatchEvent(new Event('change', { bubbles: true })); return 1; })()")
    time.sleep(0.3)
    edge.js("document.querySelector('#i-empezar').click(); 1")
    time.sleep(0.6)
    ini = json.loads(edge.js("JSON.stringify(window.__iniciar)"))
    assert ini["plantilla"] == "comite" and ini["modo_local"] is True and ini["proyecto"] == "Alfa Demo", ini


def test_reunion_en_modo_local_lo_dice_claro_y_la_pestana_sesion_muestra_los_envios(edge, pagina):
    abrir(edge, pagina, "grabando", modo_local=LOCAL)
    r = json.loads(edge.js("""JSON.stringify({ chip: !document.querySelector('#r-local').hidden, texto: document.querySelector('#r-local').textContent, aviso: document.querySelector('#ahora-local').innerText, body: document.body.dataset.local })"""))
    assert r["chip"] and r["texto"] == "Solo local" and "nada sale de este equipo" in r["aviso"] and r["body"] == "1", r
    abrir(edge, pagina, "grabando", modo_local={"activo": False, "sesion": False, "config": False, "agentes_cierre_confirmados": False})
    assert edge.js("document.querySelector('#r-local').hidden") is True and edge.js("document.querySelector('#ahora-local').hidden") is True
    edge.js("document.querySelector('.r-tab[data-tab=sesion]').click(); window.__emitir(%s); 1" % json.dumps(dict(ST.ENVIO, tipo="envio", bloqueado=True, ok=False, error="local", agente="Asesor", entrada=0, salida=0)))
    time.sleep(0.6)
    r = json.loads(edge.js("""JSON.stringify({ res: document.querySelector('#ses-env-res').textContent, filas: [...document.querySelectorAll('#ses-env-lista .aj-reg-f')].map((f) => f.innerText.replace(/\\s+/g, ' ')), visible: document.querySelector('#ses-envios').getBoundingClientRect().height > 0 })"""))
    assert r["visible"] and "llamadas a Claude" in r["res"] and "1 bloqueadas por el modo local" in r["res"] and any("Bloqueado: modo local" in f for f in r["filas"]), r


def test_revision_en_modo_local_pide_permiso_con_dialogo_propio_antes_de_analizar_con_el_equipo(edge, pagina):
    rev = dict(REV, modo_local=True, agentes_pendientes=True, cambios=[], resumen="Reunión en modo solo local: sin Claude.", sin_cambios="Modo solo local: no se proponen cambios.")
    abrir(edge, pagina, "revision", revision=rev, modo_local=LOCAL)
    r = json.loads(edge.js("JSON.stringify({ banner: document.querySelector('#rev-local').innerText, boton: document.querySelector('#rev-agentes').textContent, chip: !document.querySelector('#r-local').hidden })"))
    assert "modo solo local" in r["banner"].lower() and r["boton"] == "Analizar con el equipo" and r["chip"] is True, r
    edge.js("document.querySelector('#rev-agentes').click(); 1")
    time.sleep(0.3)
    texto = edge.js("document.querySelector('.dp-caja').innerText")
    assert "se enviarán a Claude" in texto and not llamadas(edge, r"revision/agentes"), texto                               # explica antes de enviar nada
    edge.js("document.querySelector('[data-dp=cancelar]').click(); 1")
    time.sleep(0.3)
    assert not llamadas(edge, r"revision/agentes")
    edge.js("document.querySelector('#rev-agentes').click(); 1")
    time.sleep(0.3)
    edge.js("document.querySelector('[data-dp=aceptar]').click(); 1")
    time.sleep(0.5)
    assert ["POST", "/api/revision/agentes", None] in llamadas(edge, r"revision/agentes")
    # sin pendientes (ya lanzados) no hay botón
    abrir(edge, pagina, "revision", revision=dict(rev, agentes_pendientes=False), modo_local=LOCAL)
    assert edge.js("document.querySelector('#rev-agentes')") is None


# ============================================================ 9. cartera
def test_cartera_en_la_galeria_ordenada_por_atencion_con_motivos(edge, pagina):
    abrir(edge, pagina, "inactivo")
    assert edge.js("document.querySelector('#i-modo [data-modo=cartera]').textContent.trim()") == "Cartera"
    edge.js("document.querySelector('#i-modo [data-modo=cartera]').click(); 1")
    time.sleep(0.8)
    r = json.loads(edge.js("""JSON.stringify({ aria: document.querySelector('#i-modo [data-modo=cartera]').getAttribute('aria-checked'), filas: [...document.querySelectorAll('#cartera .cart-fila')].map((f) => [f.dataset.proyecto, f.dataset.nivel,
      f.querySelector('.cart-nivel').textContent, [...f.querySelectorAll('.cart-motivos li')].length, f.innerText.includes('Hace 38 días'), f.innerText.includes('Riesgo repetido en 2 sesiones')]), cab: document.querySelector('.cart-cab').innerText,
      filtros: document.querySelector('#i-filtros').hidden })"""))
    assert r["aria"] == "true" and [f[:2] for f in r["filas"]] == [["Alfa Demo", "critico"], ["Beta Demo", "atencion"], ["Zeta Antigua", "bien"]], r["filas"]
    assert r["filas"][0][2] == "Crítico" and r["filas"][0][3] == 3 and r["filas"][0][4] and r["filas"][0][5], r["filas"][0]   # nivel, motivos, pendientes antiguos y riesgos repetidos
    assert "3 proyectos" in r["cab"] and "1 crítico " in r["cab"] + " " and r["filtros"] is True and llamadas(edge, r"api/cartera")
    edge.js("document.querySelector('#cartera .cart-fila .cart-nom').click(); 1")
    time.sleep(0.5)
    assert edge.js("AP.proyectos.estado().panel") == "Alfa Demo"                                                            # «Alfa Demo» abre su ficha
    edge.js("document.querySelector('#i-modo [data-modo=rejilla]').click(); 1")
    time.sleep(0.4)
    assert edge.js("!document.querySelector('#cartera')") is True


def test_cartera_microcopy_concuerda_en_singular_con_mayuscula_inicial_y_sin_cero_por_cien(edge, pagina):
    uno = json.loads(json.dumps(ST.CARTERA))
    uno["resumen"] = {"proyectos": 1, "critico": 0, "atencion": 1, "bien": 0}
    p = uno["proyectos"][1]
    p["motivos"] = ["solo se cierra el 0 % de los objetivos", "2 pendiente(s) abierto(s) de hace más de 14 días"]
    p["objetivos"] = {"cerrados": 0, "total": 4, "ratio_cerrados": 0.0, "sesiones_con_objetivos": 1}
    uno["proyectos"] = [p]
    abrir(edge, pagina, "inactivo", stub={"cartera": uno})
    edge.js("document.querySelector('#i-modo [data-modo=cartera]').click(); 1")
    time.sleep(0.8)
    r = json.loads(edge.js("JSON.stringify({ cab: document.querySelector('.cart-cab').innerText, motivos: [...document.querySelectorAll('.cart-motivos li')].map((l) => l.textContent) })"))
    assert "1 proyecto ·" in r["cab"] and "0 críticos" in r["cab"] or "0 crítico" in r["cab"], r
    assert r["motivos"] == ["Aún no se ha cerrado ningún objetivo", "2 pendiente(s) abierto(s) de hace más de 14 días"], r


def test_ficha_con_seguimiento_no_repite_los_pendientes_y_el_brief_sale_sin_ellos(edge, pagina):
    abrir(edge, pagina, "inactivo")
    edge.js("AP.proyectos.abrirPanel('Alfa Demo'); 1")
    time.sleep(1.2)
    r = json.loads(edge.js("""JSON.stringify({ seg: !!document.querySelector('#pp-seguimiento .seg-f'), vp: [...document.querySelectorAll('#i-panel .vp-sub .caps')].map((x) => x.textContent), brief: document.querySelector('#pp-brief').innerText })"""))
    assert r["seg"] and r["vp"].count("Pendientes abiertos") == 0 and "pendientes abiertos" not in r["brief"].lower(), r
    # en Preparar no hay seguimiento: el brief sí lleva sus pendientes
    edge.js("AP.proyectos.cerrarPanel(false); AP.proyectos.empezarEn('Alfa Demo'); 1")
    time.sleep(1.0)
    assert "pendientes abiertos" in edge.js("document.querySelector('#i-brief').innerText").lower()


def test_brief_con_aviso_no_ensena_nombres_de_excepcion(edge, pagina):
    local = dict(ST.BRIEF, origen="local", aviso="No se ha podido preparar con Claude; te enseño la versión local.", aviso_detalle="AssertionError")
    abrir(edge, pagina, "inactivo", stub={"brief": local})
    edge.js("AP.proyectos.abrirPanel('Alfa Demo'); 1")
    time.sleep(0.9)
    assert "AssertionError" not in edge.js("document.querySelector('#pp-brief').innerText") and "AssertionError" in edge.js("document.querySelector('#pp-brief .brief-aviso').title")


# ============================================================ 10. métricas
def test_metricas_de_la_sesion_en_la_revision_y_las_del_proyecto_en_la_ficha(edge, pagina):
    abrir(edge, pagina, "revision", revision=REV)
    edge.js("document.querySelector('#rev-stepper .rev-st[data-paso=\"4\"]').click(); 1")
    time.sleep(0.3)
    r = json.loads(edge.js("""JSON.stringify([...document.querySelectorAll('#rev-metricas .met-t')].map((t) => [t.querySelector('.t-label').textContent, t.querySelector('.met-v').textContent, t.innerText.replace(/\\s+/g, ' ')]))"""))
    assert [t[0] for t in r] == ["Objetivos cerrados", "Hasta cerrar", "Avisos aceptados", "Tokens"], r
    assert r[0][1] == "2 de 3" and "67 %" in r[0][2] and r[1][1] == "8,5 min" and "Primer cierre: 10:00" in r[1][2] and r[2][1] == "4 de 9" and "5 descartados" in r[2][2] and "2 «mal»" in r[2][2] and r[3][1] == "34,3k" and "9 llamadas" in r[3][2], r
    assert edge.js("(() => { const p = document.querySelector('#rev-paso-4'); return p.scrollHeight <= p.clientHeight + 2; })()") is True       # el paso 4 sigue cabiendo
    abrir(edge, pagina, "inactivo")
    edge.js("AP.proyectos.abrirPanel('Alfa Demo'); 1")
    time.sleep(1.0)
    r = json.loads(edge.js("""JSON.stringify({ tiles: [...document.querySelectorAll('#pp-metricas .met-t')].map((t) => t.innerText.replace(/\\s+/g, ' ')), barras: document.querySelectorAll('#pp-metricas .met-barra').length })"""))
    assert any("5 de 7" in t and "71 %" in t and "3,8 min" in t for t in r["tiles"]) and any("62 %" in t for t in r["tiles"]) and r["barras"] == 2, r


# ============================================================ medidas finales
@pytest.mark.parametrize("esquema", ["dark", "light"])
def test_botones_de_32_px_sin_desborde_y_sin_errores_en_las_pantallas_nuevas(edge, pagina, esquema):
    edge.eventos.clear()
    medir = """JSON.stringify({ peq: [...document.querySelectorAll('button, summary, select')].filter((b) => { const r = b.getBoundingClientRect(), cs = getComputedStyle(b);
      if (!(r.width > 0 && r.height > 0) || cs.visibility === 'hidden' || b.closest('[hidden]') || b.closest('.sr') || (b.closest('details:not([open])') && !b.matches('summary') && !b.parentElement.matches('summary'))) return false;
      let h = r.height; const a = getComputedStyle(b, '::after'); if (a.content !== 'none' && a.content !== 'normal') h = Math.max(h, parseFloat(a.height) || 0); return h < 32; }).map((b) => b.id || b.className),
      desb: [...document.querySelectorAll('.col-izq, #zona-ahora, #zona-obj, #ahora-top, #ahora-acciones, #cartera, .ini-izq, .ini-der')].filter((x) => x.getBoundingClientRect().height > 0 && x.scrollWidth > x.clientWidth + 1).map((x) => x.id || x.className) })"""
    abrir(edge, pagina, "grabando", acciones=json.loads(json.dumps(ST.ACCIONES)), modo_local=LOCAL)
    edge.cmd("Emulation.setEmulatedMedia", features=[{"name": "prefers-color-scheme", "value": esquema}])
    r = json.loads(edge.js(medir))
    assert r["peq"] == [] and r["desb"] == [], ("reunion", r)
    abrir(edge, pagina, "inactivo")
    edge.cmd("Emulation.setEmulatedMedia", features=[{"name": "prefers-color-scheme", "value": esquema}])
    edge.js("AP.proyectos.empezarEn('Alfa Demo'); 1")
    time.sleep(1.0)
    edge.js("document.querySelector('#i-plantillas [data-plantilla=descubrimiento]').click(); 1")
    r = json.loads(edge.js(medir))
    assert r["peq"] == [] and r["desb"] == [], ("preparar", r)
    edge.js("AP.proyectos.etapa('galeria'); document.querySelector('#i-modo [data-modo=cartera]').click(); 1")
    time.sleep(0.8)
    r = json.loads(edge.js(medir))
    assert r["peq"] == [] and r["desb"] == [], ("cartera", r)
    errores = [e for e in edge.eventos if e.get("method") == "Runtime.exceptionThrown" or (e.get("method") == "Runtime.consoleAPICalled" and e["params"].get("type") == "error")]
    assert errores == [], errores[:2]


def test_estaticos_sin_glifos_ni_tamanos_sueltos_y_nombres_de_agente():
    css = re.sub(r"/\*.*?\*/", "", (WEB / "olas34.css").read_text(encoding="utf-8"), flags=re.S)
    assert not re.findall(r"font-size: (?!var\(--f-)", css) and set(re.findall(r"var\(--f-(\d+)\)", css)) <= {"22", "15", "14", "12", "11"}
    malos = re.compile("[■-◿☀-➿⬀-⯿]")
    codigo = re.sub(r"/\*.*?\*/", "", (WEB / "olas34.js").read_text(encoding="utf-8"), flags=re.S)
    assert not malos.search(codigo) and "innerHTML" not in codigo and "confirm(" not in codigo.replace("AP.confirmar(", "") and "alert(" not in codigo
    html = (WEB / "index.html").read_text(encoding="utf-8")
    for i in ("i-plantillas", "i-local", "i-brief", "aj-aut-lista", "aj-sil-lista", "aj-modo-local", "aj-registro-envios", "r-local", "ahora-local", 'data-modo="cartera"'):
        assert i in html, i
    assert html.index("/static/olas34.js") > html.index("/static/avisos.js") and "/static/olas34.css" in html
