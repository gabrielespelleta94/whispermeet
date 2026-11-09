"""Jerarquía de la vista de reunión (revisión 2026-11-06, DESIGN-visual.md): escala única de cinco tamaños, cabecera de una fila, Orquestación plegada por defecto,
dos columnas con pestañas, «Ahora» con la respuesta como titular, un icono SVG por tipo con color semántico (contraste AA) y nada de glifos Unicode.
Estáticos (siempre) y dinámicos en un Edge/Chrome sin cabeza sobre la interfaz REAL con dobles de `fetch` y `WebSocket` (ver `_visual_harness.py`)."""
from __future__ import annotations

import json
import re
import socket
import time

import pytest

from _visual_harness import WEB, Edge, foto, pagina_html

APP = re.sub(r"/\*.*?\*/", "", (WEB / "app.css").read_text(encoding="utf-8"), flags=re.S)
ICONOS = (WEB / "iconos.js").read_text(encoding="utf-8")
ESCALA = {22.0, 15.0, 14.0, 12.0, 11.0}
TIPOS = ("decision", "pendiente", "pregunta", "riesgo", "contradiccion", "regla", "idea", "definicion", "objetivo", "consejo", "respuesta", "aviso", "error", "exito")


# ============================================================ estáticos
def test_el_juego_de_iconos_cubre_todos_los_tipos():
    for t in TIPOS:
        assert re.search(rf"^\s+{t}: \[", ICONOS, re.M), t
    assert "non-scaling-stroke" in APP and "stroke-width: 1.5px" in APP                       # trazo único y nítido a 1× y a 1,25×
    assert "https://" not in ICONOS.replace("https://lucide.dev", "") and "fetch(" not in ICONOS   # sin red


def test_ningun_glifo_unicode_geometrico_en_la_interfaz():
    malos = re.compile("[■-◿☀-➿⬀-⯿]")
    for n in ("index.html", "aviso.html", "app.js", "agentes.js", "reunion.js", "asesor.js", "sesion.js", "backlog.js", "equipo.js", "disposicion.js", "app.css", "equipo.css", "sesion.css", "asesor.css"):
        codigo = re.sub(r"/\*.*?\*/", "", (WEB / n).read_text(encoding="utf-8"), flags=re.S)
        codigo = "\n".join(l for l in codigo.splitlines() if not l.strip().startswith("//"))
        assert not malos.search(codigo), (n, malos.search(codigo).group(0))


def _lum(rgb):
    def c(v):
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    return 0.2126 * c(rgb[0]) + 0.7152 * c(rgb[1]) + 0.0722 * c(rgb[2])


def _con(a, b):
    la, lb = sorted((_lum(a), _lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def _hex(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _mezcla(frente, alfa, fondo):
    return tuple(f * alfa + b * (1 - alfa) for f, b in zip(frente, fondo))


@pytest.mark.parametrize("tema", ["claro", "oscuro"])
def test_los_colores_por_tipo_cumplen_aa_sobre_tarjeta_aviso_y_papel(tema):
    if tema == "oscuro":
        bloque = APP[APP.index(':root[data-theme="dark"]'):APP.index("@media (prefers-color-scheme: dark)")]
        fondos = [_hex("#16161D"), _hex("#111118"), _hex("#141924"), _mezcla((201, 201, 232), .035, _mezcla((250, 46, 100), .11, _hex("#0D0D12")))]   # §0 Estéreo: aviso, grafito, papel y vidrio fino sobre el halo de la sala
    else:
        bloque = APP[APP.index(":root {"):APP.index(':root[data-theme="dark"]')]
        fondos = [_hex("#FFFFFF"), _hex("#F8FAFE"), _hex("#F0F0F4"), _mezcla((255, 255, 255), .58, _mezcla((247, 69, 116), .10, _hex("#F0F0F4")))]   # aviso, papel, fondo y vidrio fino sobre el halo de la sala (§0 Estéreo)
    tokens = dict(re.findall(r"--(t-[a-z]+): (#[0-9A-Fa-f]{6})", bloque))
    assert len(tokens) >= 10, tokens
    for nombre, valor in tokens.items():
        for f in fondos:
            assert _con(_hex(valor), f) >= 4.5, (tema, nombre, valor, round(_con(_hex(valor), f), 2))
    assert len(set(tokens[k] for k in ("t-decision", "t-pendiente", "t-riesgo", "t-contradiccion", "t-pregunta", "t-idea"))) == 6   # cada tipo, su color


def test_la_escala_tiene_cinco_tamanos_y_ningun_px_suelto_en_los_componentes():
    for n in ("app.css", "equipo.css", "sesion.css", "asesor.css", "aviso.css", "backlog.css"):
        css = re.sub(r"/\*.*?\*/", "", (WEB / n).read_text(encoding="utf-8"), flags=re.S)
        assert not re.findall(r"font-size: (?!var\(--f-)", css), n
        assert set(re.findall(r"var\(--f-(\d+)\)", css)) <= {"22", "15", "14", "12", "11"}, n


def test_html_dos_columnas_con_pestanas_y_notas_plegadas():
    html = (WEB / "index.html").read_text(encoding="utf-8")
    for t in ("avisos", "pregunta", "sesion"):   # ola 2: tres pestañas; Objetivos es zona fija y el Equipo vive en el «Detalle» de la tira
        assert f'data-tab="{t}"' in html and f'data-panel="{t}"' in html, t
    for t in ("consejos", "insights", "objetivos", "equipo"):
        assert f'data-tab="{t}"' not in html, t
    assert re.search(r'<details class="panel panel-notas" id="r-notas-det">', html)          # plegadas por defecto
    assert html.index("/static/iconos.js") < html.index("/static/agentes.js") and "/static/disposicion.js" in html


# ============================================================ dinámicos
def _puerto():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def pagina(tmp_path_factory):
    return pagina_html(tmp_path_factory.mktemp("jerarquia") / "app.html")


def _abrir(e, pagina, **cambios):
    e.abrir(pagina.as_uri())
    e.js("localStorage.clear(); sessionStorage.clear(); 1")
    e.abrir(pagina.as_uri())
    e.js("window.__emitir(Object.assign({tipo: 'snapshot'}, %s)); 1" % json.dumps(foto(**cambios)))
    time.sleep(0.9)
    for _ in range(30):
        if e.js("document.querySelectorAll('.eq-tarj').length") == 4:
            break
        time.sleep(0.15)


RESPUESTA = {"id": "r1", "pregunta": "¿Os comprometéis a tener el catálogo cargado antes del piloto, aunque lo entregue el cliente tarde?", "minuto": "04:50", "t_seg": 290, "canal": "Reunión",
             "estado": "ok", "vinetas": ["El catálogo depende de que el cliente lo entregue a tiempo: es un riesgo del plan.", "Propongo fijar una fecha de entrega."], "confianza": "media",
             "citas": [{"fuente": "02-alcance.md", "tipo": "proyecto"}], "base": True, "sin_base": False, "orientacion": False, "sin_cita": False, "modelo": "sonnet", "temas": [],
             "escalada": "", "fijada": False, "descartada": False, "profundizada": None, "error": "", "tokens": 3500}
CONSEJO = {"tipo": "cierre", "etiqueta": "Cierre y próximo paso", "accion": "Propón fijar hoy una fecha de entrega del catálogo con el cliente", "porque": "Hay prisa por cerrar la oferta",
           "minuto": "03:00", "t_seg": 180.0, "modelo": "sonnet", "fijado": False, "descartado": False, "profundizada": None}
ESTADO = {"activo": True, "presupuesto": {"usado": 12000, "limite": 100000, "fraccion": .12, "nivel": "normal"}, "sonnet": {"usados": 1, "limite": 8},
          "web": {"disponible": False, "motivo": ""}, "pendiente": False, "en_curso": False, "tokens": 12000, "stats": {}, "fuentes": {}}


def _asesor(e, respuestas, consejos):
    e.js("window.__emitir(%s); 1" % json.dumps({"tipo": "asesor", "respuestas": respuestas, "consejos": consejos, **ESTADO}))
    time.sleep(0.5)


@pytest.mark.parametrize("ancho,alto", [(1920, 1080), (1536, 880), (1440, 900)])
def test_una_fila_en_la_cabecera_sin_scroll_de_pagina_y_solo_la_escala(tmp_path, pagina, ancho, alto):
    e = Edge(tmp_path, _puerto(), ancho, alto)
    try:
        _abrir(e, pagina)
        _asesor(e, [RESPUESTA], [dict(CONSEJO, id=f"c{i}") for i in range(1, 5)])
        r = e.js("""(() => { const t = document.querySelector('#cab'), tam = new Set();
          document.querySelectorAll('#cab *, #orq *, #v-reunion *').forEach((x) => { if (x.offsetParent === null && getComputedStyle(x).position !== 'fixed') return;
            if (![...x.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim())) return; tam.add(parseFloat(getComputedStyle(x).fontSize)); });
          return { cab: Math.round(t.getBoundingClientRect().height), docAlto: document.documentElement.scrollHeight, alto: innerHeight, docAncho: document.documentElement.scrollWidth, ancho: innerWidth,
            tamanos: [...tam].sort((a, b) => a - b), orq: document.querySelector('#orq').dataset.plegado, orqAlto: Math.round(document.querySelector('#orq').getBoundingClientRect().height),
            resumen: document.querySelector('#orq-resumen').textContent, notas: document.querySelector('#r-notas-det').open,
            cron: parseFloat(getComputedStyle(document.querySelector('#r-reloj')).fontSize) }; })()""")
        assert 44 <= r["cab"] <= 52, r                                                         # UNA fila (48 + el filete)
        assert r["docAlto"] <= r["alto"] and r["docAncho"] <= r["ancho"], r                      # la página no se desplaza
        assert set(r["tamanos"]) <= ESCALA, r["tamanos"]                                         # solo los cinco tamaños de la escala
        assert r["orq"] == "true" and r["orqAlto"] <= 40 and r["cron"] == 22.0 and r["notas"] is False, r   # Orquestación y Notas plegadas; cronómetro del titular
        assert re.fullmatch(r"Equipo [^·]+ · Monitor [^·]+ · \d+ (intervención|intervenciones|análisis)( · [\d,.]+k? tokens)?", r["resumen"]), r["resumen"]
    finally:
        e.cerrar()


def test_la_orquestacion_se_despliega_con_un_clic_y_recuerda_la_preferencia(tmp_path, pagina):
    e = Edge(tmp_path, _puerto())
    try:
        _abrir(e, pagina)
        assert e.js("document.querySelector('#orq').dataset.plegado") == "true"
        e.js("document.querySelector('#orq-plegar').click(); 1")
        time.sleep(0.5)
        assert e.js("document.querySelector('#orq').dataset.plegado") == "false" and e.js("localStorage.getItem('apuntes_orq_plegado')") == "0"
        assert e.js("document.querySelector('#orq').getBoundingClientRect().height") >= 120
        _abrir(e, pagina)                                                                       # la preferencia sobrevive (sin borrar localStorage)
        e.js("localStorage.setItem('apuntes_orq_plegado', '0'); 1")
        e.abrir(pagina.as_uri())
        e.js("window.__emitir(Object.assign({tipo: 'snapshot'}, %s)); 1" % json.dumps(foto()))
        time.sleep(0.8)
        assert e.js("document.querySelector('#orq').dataset.plegado") == "false"
    finally:
        e.cerrar()


def test_pestanas_con_teclado_y_solo_un_panel_a_la_vez(tmp_path, pagina):
    e = Edge(tmp_path, _puerto())
    try:
        _abrir(e, pagina)
        r = e.js("""(() => { const vis = () => [...document.querySelectorAll('.tab-panel')].filter((p) => getComputedStyle(p).display !== 'none').map((p) => p.dataset.panel);
          const out = { inicial: vis() };
          document.querySelector('.r-tab[data-tab=pregunta]').click(); out.pregunta = vis(); out.sel = document.querySelector('.r-tab[aria-selected=true]').dataset.tab;
          document.querySelector('.r-tab[data-tab=pregunta]').dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true })); out.flecha = vis();
          document.querySelector('.r-tab[data-tab=sesion]').click(); out.sesion = vis(); out.banda = document.querySelector('#tab-sesion #sesion-banda') !== null; return out; })()""")
        assert len(r["inicial"]) == 1 and r["pregunta"] == ["pregunta"] and r["sel"] == "pregunta" and r["flecha"] == ["sesion"] and r["sesion"] == ["sesion"] and r["banda"], r
        assert e.js("localStorage.getItem('apuntes_pestana')") == "sesion"
    finally:
        e.cerrar()


def test_ahora_respuesta_de_22_y_una_no_respuesta_atenuada_y_compacta(tmp_path, pagina):
    e = Edge(tmp_path, _puerto())
    try:
        _abrir(e, pagina)
        _asesor(e, [RESPUESTA], [CONSEJO | {"id": "c1"}])
        r = e.js("""(() => { const a = document.querySelector('.as-ahora'), li = [...a.querySelectorAll('.as-vin li')].map((x) => parseFloat(getComputedStyle(x).fontSize));
          return { li, preg: parseFloat(getComputedStyle(a.querySelector('.as-preg')).fontSize), alto: Math.round(a.getBoundingClientRect().height) }; })()""")
        assert r["li"] == [22.0, 14.0] and r["preg"] == 15.0, r
        sin = dict(RESPUESTA, id="r2", pregunta="¿Qué servicio de correo envía el aviso?", vinetas=["No hay base en tus fuentes: propón comprobarlo y volver con la respuesta"], sin_base=True, base=False, confianza="baja", citas=[])
        _asesor(e, [sin], [])                                                                   # solo hay una no-respuesta: tarjeta compacta, atenuada y sin titular
        r = e.js("""(() => { const a = document.querySelector('.as-ahora'), li = a.querySelector('.as-vin li'), cs = getComputedStyle(li);
          return { tam: parseFloat(cs.fontSize), color: cs.color, soft: getComputedStyle(document.documentElement).getPropertyValue('--soft'), alto: Math.round(a.getBoundingClientRect().height), clase: a.className }; })()""")
        assert r["tam"] == 14.0 and "sin-base" in r["clase"] and r["alto"] <= 130, r
        _asesor(e, [RESPUESTA, dict(sin, t_seg=400, minuto="06:40")], [])                       # con una respuesta útil antes, la no-respuesta es UNA línea y «Ahora» sigue siendo la útil
        r = e.js("""({ ahora: document.querySelector('.as-ahora').dataset.id, linea: !!document.querySelector('.as-nobase'), altoLinea: document.querySelector('.as-nobase').getBoundingClientRect().height })""")
        assert r["ahora"] == "r1" and r["linea"] and r["altoLinea"] <= 32, r
        assert "null" not in e.js("document.querySelector('#as-carril').innerText") and "null" not in e.js("document.querySelector('#tab-avisos').innerText")
    finally:
        e.cerrar()


def test_consejos_compactos_caben_cuatro_a_1080(tmp_path, pagina):
    e = Edge(tmp_path, _puerto(), 1920, 1080)
    try:
        _abrir(e, pagina)
        _asesor(e, [RESPUESTA], [dict(CONSEJO, id=f"c{i}", t_seg=700.0 + i) for i in range(1, 7)])   # ola 2: los consejos van en la lista de Avisos, junto a los insights
        r = e.js("""(() => { const p = document.querySelector('#tab-avisos').getBoundingClientRect(), cs = [...document.querySelectorAll('#r-insights .as-cons')];
          return { alto_panel: Math.round(p.height), alto_ventana: innerHeight, n: cs.length, caben: cs.filter((c) => { const b = c.getBoundingClientRect(); return b.top >= p.top - 1 && b.bottom <= p.bottom + 1; }).length, alto: Math.round(cs[0].getBoundingClientRect().height),
            titular: parseFloat(getComputedStyle(cs[0].querySelector('.as-accion')).fontSize), peso: getComputedStyle(cs[0].querySelector('.as-accion')).fontWeight, porque: parseFloat(getComputedStyle(cs[0].querySelector('.as-porque')).fontSize) }; })()""")
        assert r["alto_panel"] < r["alto_ventana"], r                                           # la pestaña NO crece con el contenido: hace scroll en sí misma
        assert r["n"] == 6 and r["caben"] >= 3 and r["titular"] == 15.0 and r["peso"] == "600" and r["porque"] == 14.0, r
    finally:
        e.cerrar()


def test_cada_tipo_tiene_su_icono_su_color_y_lo_importante_destaca(tmp_path, pagina):
    e = Edge(tmp_path, _puerto())
    try:
        _abrir(e, pagina)
        cats = [("decisión", "decision"), ("pendiente", "pendiente"), ("riesgo", "riesgo"), ("contradicción", "contradiccion"), ("pregunta", "pregunta"), ("idea", "idea"), ("regla", "regla"), ("definición", "definicion")]
        ts = [{"id": f"q{i}", "analisis": 1, "categoria": c, "texto": f"Texto de {c}", "minuto": "01:00", "t_seg": 60 + i, "estado": "confirmada"} for i, (c, _) in enumerate(cats)]
        e.js("window.__emitir({tipo: 'tarjetas', nuevas: %s}); 1" % json.dumps(ts))
        time.sleep(0.8)
        time.sleep(0.4)
        r = e.js("""(() => { const out = {}; for (const t of document.querySelectorAll('#r-insights .tarj')) { const k = [...t.classList].find((c) => ['decision','pendiente','riesgo','contradiccion','pregunta','idea','regla','definicion'].includes(c));
          const svg = t.querySelector('svg.ic'); const cs = getComputedStyle(svg), cx = getComputedStyle(t.querySelector('.tx')), cb = getComputedStyle(t);
          out[k] = { icono: [...svg.classList].find((c) => c.startsWith('ic-')), color: cs.color, w: svg.getBoundingClientRect().width, txt: cx.color, peso: cx.fontWeight, barra: cb.borderLeftWidth }; } return out; })()""")
        assert set(r) == {k for _, k in cats}, r
        assert all(v["icono"] == "ic-" + k and v["w"] == 16 for k, v in r.items()), r
        assert len({v["color"] for v in r.values()}) == 8, r                                      # ocho colores distintos
        # DESIGN-visual.md §0 deroga la barra de color en las tarjetas importantes: ninguna lleva borde izquierdo; lo importante se distingue por el peso (600) y la tinta plena
        assert all(v["barra"] == "0px" for v in r.values()), r
        assert all(r[k]["peso"] == "600" for k in ("decision", "pendiente", "riesgo", "contradiccion")), r
        assert all(r[k]["peso"] == "400" and r[k]["txt"] != r["decision"]["txt"] for k in ("pregunta", "idea", "regla", "definicion")), r   # lo secundario: peso normal y atenuado
    finally:
        e.cerrar()


def test_modo_reunion_hereda_la_escala_y_las_pestanas(tmp_path, pagina):
    e = Edge(tmp_path, _puerto(), 1920, 1080)
    try:
        _abrir(e, pagina)
        _asesor(e, [RESPUESTA], [CONSEJO | {"id": "c1"}])
        e.js("document.body.dataset.modo = 'reunion'; document.body.dataset.mr = 'dos'; document.documentElement.style.setProperty('--mr-izq', '480px'); document.documentElement.style.setProperty('--mr-der', '480px'); 1")
        time.sleep(0.7)
        r = e.js("""(() => { const tam = new Set(); document.querySelectorAll('.col-izq *, .col-der *').forEach((x) => { if (x.offsetParent === null && getComputedStyle(x).position !== 'fixed') return;
            if (![...x.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim())) return; tam.add(parseFloat(getComputedStyle(x).fontSize)); });
          const der = document.querySelector('.col-der'); return { tam: [...tam].sort((a, b) => a - b), tabs: !!der.querySelector('#r-tabs'), carril: der.querySelector('#as-carril').parentNode.id, ancho: Math.round(der.getBoundingClientRect().width),
            resp: parseFloat(getComputedStyle(der.querySelector('.as-vin li')).fontSize) }; })()""")
        assert set(r["tam"]) <= ESCALA and r["tabs"] and r["carril"] == "ahora-top" and r["ancho"] <= 481 and r["resp"] == 22.0, r
    finally:
        e.cerrar()


# ============================================================ avisos emergentes: nunca tapan nada
MEDIR_AVISOS = """(() => {
  const caja = (el) => { const r = el.getBoundingClientRect(); return { l: r.left, t: r.top, r: r.right, b: r.bottom, w: r.width, h: r.height }; };
  const cruza = (a, b) => a.l < b.r - 0.5 && b.l < a.r - 0.5 && a.t < b.b - 0.5 && b.t < a.b - 0.5;
  const avisos = [...document.querySelectorAll('#r-notifs .notif:not(.saliendo)')].filter((n) => n.getBoundingClientRect().height > 0);
  const fijos = { ahora: '#as-carril', paso: '#ahora-paso', pestanas: '#r-tabs', avisos: '#tab-avisos', objetivos: '#zona-obj', pregunta: '#tab-pregunta', sesion: '#tab-sesion' };
  const cruces = [];
  avisos.forEach((a, i) => {
    const ca = caja(a);
    for (const [nombre, sel] of Object.entries(fijos)) { const e = document.querySelector(sel); if (!e || e.getBoundingClientRect().height === 0) continue; if (cruza(ca, caja(e))) cruces.push(['aviso' + i, nombre]); }
    avisos.forEach((o, j) => { if (j > i && cruza(ca, caja(o))) cruces.push(['aviso' + i, 'aviso' + j]); });
  });
  const mas = document.querySelector('#r-notifs .notif-mas');
  return { n: avisos.length, cruces, tipos: avisos.map((a) => a.dataset.k), opacos: avisos.map((a) => { const c = getComputedStyle(a); const m = c.backgroundColor.match(/[\d.]+/g); return [m.length > 3 ? Number(m[3]) : 1, c.backdropFilter]; }),
    mas: mas && !mas.hidden ? mas.textContent : null, dentro: avisos.every((a) => { const r = a.getBoundingClientRect(); return r.right <= innerWidth + 0.5 && r.bottom <= innerHeight + 0.5; }),
    ahora: document.querySelector('.as-ahora') ? caja(document.querySelector('.as-ahora')).h : 0 };
})()"""


def _avisos_en_pantalla(e, pagina, modo=False):
    _abrir(e, pagina)
    _asesor(e, [RESPUESTA], [CONSEJO | {"id": "c1"}])
    cats = [("decisión", "Decisión del piloto"), ("pendiente", "Pendiente de tarifas"), ("riesgo", "Riesgo del catálogo"), ("contradicción", "Contradicción con el alcance"), ("riesgo", "Otro riesgo de plazos"),
            ("idea", "Una idea suelta"), ("pregunta", "Una pregunta sin respuesta")]
    ts = [{"id": f"av{i}", "analisis": 1, "categoria": c, "texto": f"{x} " + "con bastante texto para ocupar varias líneas " * 2, "minuto": "01:0%d" % i, "t_seg": 60 + i, "estado": "confirmada"} for i, (c, x) in enumerate(cats)]
    e.previas = int(e.js("document.querySelector('#tab-n-avisos').textContent") or 0)             # las de la foto del backend
    e.js("window.__emitir({tipo: 'tarjetas', nuevas: %s}); 1" % json.dumps(ts))
    if modo:
        e.js("document.body.dataset.modo = 'reunion'; document.body.dataset.mr = 'dos'; document.documentElement.style.setProperty('--mr-izq', '480px'); document.documentElement.style.setProperty('--mr-der', '480px'); 1")
    time.sleep(4.5)                                                                           # la cola suelta una cada 900 ms
    return e.js(MEDIR_AVISOS)


@pytest.mark.parametrize("ancho,alto,modo", [(1920, 1080, False), (1536, 880, False), (1440, 900, False), (1920, 1080, True)])
def test_los_avisos_nunca_tapan_ahora_ni_las_pestanas_ni_los_consejos_ni_otro_aviso(tmp_path, pagina, ancho, alto, modo):
    e = Edge(tmp_path, _puerto(), ancho, alto)
    try:
        r = _avisos_en_pantalla(e, pagina, modo)
        assert r["n"] == 2, r                                                                 # como mucho 2 a la vez (hay 3 que merecen aviso emergente y una fija)
        assert r["cruces"] == [], r["cruces"]                                                 # ninguno se cruza con «Ahora», las pestañas, los paneles ni entre sí
        assert sorted(r["tipos"]) == ["decision", "riesgo"] or all(k in ("decision", "riesgo", "contradiccion") for k in r["tipos"]), r["tipos"]   # solo decisión, contradicción y riesgo
        assert all(o[0] == 1 and o[1] == "none" for o in r["opacos"]), r["opacos"]            # fondo opaco, sin desenfoque
        assert r["mas"] == "+1 hallazgo", r                                                   # el otro, agrupado (la contradicción sobre el alcance es FIJA: no emerge, ya está arriba de Avisos)
        assert r["dentro"] and r["ahora"] > 0, r
        sin_aviso = e.js("[...document.querySelectorAll('#r-notifs .notif')].some((n) => ['pendiente', 'idea', 'pregunta'].includes(n.dataset.k))")
        assert sin_aviso is False                                                             # pendiente, idea y pregunta no avisan
        assert "Avisos" in e.js("document.querySelector('.r-tab[data-tab=avisos]').textContent") and int(e.js("document.querySelector('#tab-n-avisos').textContent")) == e.previas + 7   # y se cuentan en su pestaña
        assert e.js("document.querySelector('#tab-n-avisos').classList.contains('nuevo')") is False   # Avisos es la pestaña a la vista: sin resaltado de «nuevo»
    finally:
        e.cerrar()


def test_el_detector_ve_un_aviso_encima_de_ahora(tmp_path, pagina):
    """El detector de cruces no es decorativo: si se fuerza un aviso sobre «Ahora», lo ve."""
    e = Edge(tmp_path, _puerto(), 1536, 880)
    try:
        _avisos_en_pantalla(e, pagina)
        e.js("(() => { const n = document.querySelector('#r-notifs .notif'); const a = document.querySelector('#as-carril').getBoundingClientRect(); n.style.position = 'fixed'; n.style.left = a.left + 'px'; n.style.top = a.top + 'px'; n.style.width = '300px'; return 1; })()")
        assert any(c[1] == "ahora" for c in e.js(MEDIR_AVISOS)["cruces"])
    finally:
        e.cerrar()
