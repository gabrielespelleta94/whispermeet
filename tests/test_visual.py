"""Giro visual (DESIGN-visual.md §14): criterios de aceptación medibles sobre la interfaz REAL.

Estáticos (siempre): tokens, radios, escala tipográfica, dónde se permite `backdrop-filter`, contraste calculado con los tokens, ids y renombrado a «Hallazgos».
Dinámicos (Edge/Chrome sin cabeza, sin servidor ni modelo; ver `_visual_harness.py`): nodos de la banda, tarjeta de perfil, animaciones en reposo y con una
tarea, Efectos, filtros de fondo, sin elipsis, «N nuevos ↑», foco con Tab, Modo reunión opaco, movimiento reducido y retirada de las clases de entrada."""
from __future__ import annotations

import json
import re
import socket
import time
from pathlib import Path

import pytest

from _visual_harness import WEB, Edge, foto, pagina_html

CSS = {n: (WEB / n).read_text(encoding="utf-8") for n in ("app.css", "equipo.css", "sesion.css")}
TODO_CSS = "\n".join(CSS.values())
JS = {n: (WEB / n).read_text(encoding="utf-8") for n in ("app.js", "agentes.js", "reunion.js", "equipo.js", "revision.js", "modo-reunion.js", "sesion.js")}
HTML = (WEB / "index.html").read_text(encoding="utf-8")


def _quita_comentarios(css: str) -> str:
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


# ============================================================ estáticos
def test_tokens_del_diseno():
    app = _quita_comentarios(CSS["app.css"])
    claro = app[app.index(":root {"):app.index(':root[data-theme="dark"]')]
    oscuro = app[app.index(':root[data-theme="dark"]'):app.index("@media (prefers-color-scheme: dark)")]
    sistema = app[app.index("@media (prefers-color-scheme: dark)"):app.index("body { --blur-n")]
    esperado_oscuro = {"--bg0": "#121317", "--ink": "#F4F4F6", "--body": "#BDBDC7", "--soft": "#9A9AA6", "--acc-t": "#7EB4FF", "--papel": "#26231F", "--elev-solido": "#1E1F26",
                       "--grafito-op": "#18191F", "--ok": "#5ED38B", "--err": "#F28B82", "--warn": "#F0A94E"}
    esperado_claro = {"--bg0": "#EEF0F4", "--ink": "#17181C", "--body": "#363842", "--soft": "#5F6170", "--acc-t": "#1D5FC4", "--papel": "#F7F2EA", "--elev-solido": "#FFFFFF",
                      "--grafito-op": "#FFFFFF", "--ok": "#1E8A4C", "--err": "#B3261E", "--warn": "#B25E09", "--acc": "#2E7CF6"}
    for tokens, bloque in ((esperado_oscuro, oscuro), (esperado_oscuro, sistema), (esperado_claro, claro)):
        for k, v in tokens.items():
            assert re.search(rf"{re.escape(k)}: {re.escape(v)}[;\s]", bloque), (k, v)
    for k in ("--luz-1", "--luz-2", "--vineta", "--grafito", "--vidrio", "--canto", "--brillo", "--vidrio-f", "--vidrio-fl", "--vidrio-blur", "--sombra-f", "--sombra", "--papel-canto",
              "--hover", "--sel", "--hair", "--hair2", "--acc-soft", "--luz", "--halo"):
        assert f"{k}:" in oscuro and f"{k}:" in claro and f"{k}:" in sistema, k
    assert "--acc: #2E7CF6" in claro
    assert "blur(16px) saturate(140%)" in oscuro and "blur(16px) saturate(120%)" in claro   # §4: desenfoque del nivel 2
    for n in ("22", "15", "14", "12", "11"):
        assert f"--f-{n}: {n}px" in claro                                                    # escala única de CINCO tamaños por variable (revisión 2026-11-06: sin 28 ni 13)
    assert "--f-28" not in app and "--f-13" not in app


def test_sin_el_azul_antiguo_ni_radios_derogados():
    assert "007AFF" not in TODO_CSS.upper()
    for n, js in JS.items():
        assert "#007AFF" not in js.upper(), n
    css = _quita_comentarios(TODO_CSS)
    radios = set(re.findall(r"border-radius: (\d+)px", css))
    assert radios <= {"0", "1", "2", "4", "6", "8", "10", "14"}, radios                       # los de §4 (más 1, 2 y 6 en trazos y pulgares internos); nunca 3
    assert not re.search(r"border-radius: 3px", css)
    # la escala tipográfica va por variable: ningún tamaño suelto fuera de :root
    sueltos = [m for m in re.findall(r"font-size: (\d+(?:\.\d+)?px)", css) if m not in ("22px", "15px", "14px", "12px", "11px")]
    assert not sueltos, sueltos
    assert not re.findall(r"font-size: (?!var\(--f-)", css)                                  # todo tamaño de letra va por variable
    assert "will-change" not in css                                                          # ningún will-change permanente (JS lo pone solo durante la entrada)


def test_backdrop_filter_solo_donde_lo_permite_el_diseno():
    css = _quita_comentarios(TODO_CSS)
    permitidos = {".registro", "#r-bandeja", ".notif", ".sb-tip", ".drawer", ".dialogo", ".ini-izq", "#r-notifs > .notif:nth-child(n+5)"}
    for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", css):
        sel, cuerpo = m.group(1).strip(), m.group(2)
        if re.search(r"backdrop-filter: (?!none)", cuerpo) and not sel.startswith("--"):
            assert all(s.strip() in permitidos for s in sel.split(",")), sel
    # y lo que no admite nunca filtro, sombra animada ni gradiente: listas largas
    for sel in (".lin", ".eq-fila", ".bj-f", ".chk-fila", ".obj", ".dl"):
        for m in re.finditer(rf"(?m)^{re.escape(sel)}(?:[ :.\[][^{{]*)?\{{([^}}]*)\}}", css):
            assert "gradient" not in m.group(1) and "backdrop" not in m.group(1) and not re.search(r"box-shadow: (?!none)", m.group(1)), (sel, m.group(1))
    assert "gradient" not in re.search(r"\.tarj \{[^}]*\}", css).group(0)
    # gradientes: solo la capa ambiente (tokens), la luz de trabajo (cónico), su máscara y el barrido del Gantt
    for prop, valor in re.findall(r"([\w-]+):\s*([^;{}]*gradient[^;{}]*)", css):
        assert prop in ("--luz-1", "--luz-2", "--vineta", "-webkit-mask", "mask") or (prop == "background" and ("conic-gradient" in valor or "linear-gradient(100deg" in valor)), (prop, valor[:60])


def test_recorte_con_elipsis_solo_en_las_excepciones_admitidas():
    """Sin textos cortados (requisito del autor): ni elipsis ni line-clamp salvo barras geométricas estrechas, `.pie-ctx` y el dato del nodo (DESIGN-visual.md §14.5)."""
    css = _quita_comentarios(TODO_CSS)
    permitidos = {".g-barra .g-bt", ".sb-tema-t", ".pie-ctx"}
    for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", css):
        sel, cuerpo = m.group(1).strip(), m.group(2)
        if "text-overflow: ellipsis" in cuerpo or re.search(r"line-clamp: (?!unset|none)", cuerpo):
            assert all(x.strip() in permitidos for x in sel.split(",")), sel
    assert "recorte con tooltip" in (WEB.parent / "DESIGN-visual.md").read_text(encoding="utf-8")   # y las excepciones están documentadas


def test_ids_y_renombrado_a_hallazgos():
    for i in ("r-notifs", "r-bandeja", "r-bandeja-btn", "r-bandeja-lista", "r-bandeja-filtros", "r-bandeja-x", "r-bandeja-total", "eq-perfiles", "r-insights", "v-rev-titulo", "v-rev-cuerpo",
              "v-rev-pie", "v-rev-aplicar", "v-rev-cerrar", "mr-barra", "mr-salir", "mr-entrar", "r-trans", "r-plan-scroll", "r-ins-nuevos", "r-analizar", "r-terminar", "eq-monitor", "eq-def", "eq-feed"):
        assert f'id="{i}"' in HTML, i
    assert ">Hallazgos 0<" in HTML and 'aria-label="Hallazgos"' in HTML and '<span class="t-title">Hallazgos</span>' in HTML
    # el otro concepto, «Bandeja (reunión sin proyecto)», sigue llamándose así
    assert "Bandeja (reunión sin proyecto)" in JS["app.js"]
    assert 'Hallazgos ' in JS["reunion.js"] and "Todavía no hay hallazgos." in JS["reunion.js"]
    assert "Bandeja " not in JS["reunion.js"].split("const txt = ")[1].split(";")[0]


def test_tarjeta_de_perfil_es_div_con_rol_y_teclado():
    codigo = JS["equipo.js"]
    assert 'h("div", { role: "button", tabindex: "0", class: "eq-tarj"' in codigo and 'h("button", { type: "button", class: "eq-tarj"' not in codigo
    assert 'ev.key === "Enter"' in codigo and 'ev.key === " "' in codigo


def test_view_transitions_con_respaldo():
    codigo = JS["app.js"]
    assert "document.startViewTransition(aplicar)" in codigo and "} else aplicar();" in codigo   # un solo startViewTransition; sin la API, como siempre
    assert codigo.count("startViewTransition") == 2 and "view-transition-name: cabecera" in CSS["app.css"]


def _luminancia(rgb):
    def c(v):
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = rgb
    return 0.2126 * c(r) + 0.7152 * c(g) + 0.0722 * c(b)


def _contraste(a, b):
    la, lb = sorted((_luminancia(a), _luminancia(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def _hex(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _mezcla(frente, alfa, fondo):
    return tuple(f * alfa + b * (1 - alfa) for f, b in zip(frente, fondo))


@pytest.mark.parametrize("tema", ["oscuro", "claro"])
def test_contraste_sobre_el_vidrio_flotante_en_su_punto_mas_iluminado(tema):
    """§14.4: --body ≥ 7:1; --soft, --acc-t y las etiquetas ≥ 4,5:1, sobre el color efectivo del vidrio flotante en el punto donde más lo ilumina el ambiente."""
    if tema == "oscuro":
        bg0, ambiente, vf, vfl, body, soft, acc_t, ink, texto = _hex("#121317"), (0.20, (46, 124, 246)), (0.90, (28, 29, 36)), (0.92, (24, 25, 31)), "#BDBDC7", "#9A9AA6", "#7EB4FF", "#F4F4F6", "#F4F4F6"
    else:
        bg0, ambiente, vf, vfl, body, soft, acc_t, ink, texto = _hex("#EEF0F4"), (0.16, (46, 124, 246)), (0.90, (255, 255, 255)), (0.90, (255, 255, 255)), "#363842", "#5F6170", "#1D5FC4", "#17181C", "#17181C"
    iluminado = _mezcla(ambiente[1], ambiente[0], bg0)
    for alfa_rgb in (vf, vfl):
        fondo = _mezcla(alfa_rgb[1], alfa_rgb[0], iluminado)
        assert _contraste(_hex(body), fondo) >= 7, (tema, "body", _contraste(_hex(body), fondo))
        assert _contraste(_hex(ink), fondo) >= 7
        assert _contraste(_hex(soft), fondo) >= 4.5, (tema, "soft", _contraste(_hex(soft), fondo))
        assert _contraste(_hex(acc_t), fondo) >= 4.5, (tema, "acc-t", _contraste(_hex(acc_t), fondo))
        # peor caso si el desenfoque falla: justo debajo hay un píxel de texto del otro extremo de luminosidad (la tinta de la propia pantalla)
        peor = _mezcla(alfa_rgb[1], alfa_rgb[0], _hex(texto))
        assert _contraste(_hex(ink), peor) >= 7, (tema, "ink con texto debajo", _contraste(_hex(ink), peor))
        assert _contraste(_hex(soft), peor) >= 4.5, (tema, "soft con texto debajo", _contraste(_hex(soft), peor))
        assert _contraste(_hex(acc_t), peor) >= 4.5, (tema, "acc-t con texto debajo", _contraste(_hex(acc_t), peor))
    # el papel (lo que escribe el usuario) también cumple con su tinta
    papel = _hex("#26231F" if tema == "oscuro" else "#F7F2EA")
    assert _contraste(_hex(ink), papel) >= 7 and _contraste(_hex(soft), papel) >= 4.5


# ============================================================ dinámicos
def _puerto():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def pagina(tmp_path_factory):
    return pagina_html(tmp_path_factory.mktemp("visual") / "app.html")


@pytest.fixture(scope="module")
def edge(tmp_path_factory, pagina):
    e = Edge(tmp_path_factory.mktemp("edge"), _puerto())
    yield e
    e.cerrar()


def arrancar(e, pagina, snapshot=None, antes=""):
    """Página limpia (sin preferencias recordadas) con la foto del backend puesta."""
    e.abrir(pagina.as_uri())
    e.js("localStorage.clear(); sessionStorage.clear(); localStorage.setItem('apuntes_orq_plegado', '0'); 1")   # estas pruebas miden la banda DESPLEGADA; por defecto llega plegada (ver test_jerarquia.py)
    e.abrir(pagina.as_uri())
    if antes:
        e.js(antes)
    e.js("window.__emitir(Object.assign({tipo: 'snapshot'}, %s)); 1" % json.dumps(snapshot or foto()))
    time.sleep(0.6)
    for _ in range(40):                                                                   # el pintado va en requestAnimationFrame: si el navegador va justo, se espera
        if snapshot is not None or e.js("document.querySelectorAll('.eq-tarj').length") == 4:
            break
        time.sleep(0.15)
    if snapshot is None:
        estado = e.js("JSON.stringify([document.body.dataset.vista, document.querySelectorAll('.eq-tarj').length, document.querySelectorAll('#r-trans .lin').length, location.href.slice(-20), document.visibilityState])")
        assert json.loads(estado)[:2] == ["reunion", 4], estado


def evento(e, **d):
    e.js("window.__emitir(%s); 1" % json.dumps(d))


def tarea(e, fase, ident=900, agente="constructor", nombre="Constructor", **extra):
    base = {"tipo": "tarea", "id": ident, "agente": agente, "nombre": nombre, "tarea": "equipo_" + agente, "modelo": "haiku", "tramo": "00:05–10:10", "hora": time.strftime("%H:%M:%S")}
    if fase == "inicio":
        base.update(fase="inicio", estado="en_curso")
    else:
        base.update(fase="fin", estado="ok", ok=True, ms=6400, tokens=2900)
    base.update(extra)
    evento(e, **base)


ANIMS = """(() => document.getAnimations().map(a => {
  const t = a.effect && a.effect.target, c = t && (t.id || (t.className && t.className.baseVal !== undefined ? t.className.baseVal : t.className) || t.tagName);
  return { n: a.animationName || a.transitionProperty || 'waapi', t: String(c) + ((a.effect && a.effect.pseudoElement) || ''), estado: a.playState };
}))()"""


def nombres(e):
    return sorted(x["n"] + "@" + x["t"].split(" ")[0] for x in e.js(ANIMS))


def test_los_diez_nodos_de_la_banda_miden_lo_que_dice_el_diseno(edge, pagina):
    arrancar(edge, pagina)
    r = edge.js("""(() => {
      const c = document.querySelector('#orq-cuerpo'), cs = getComputedStyle(c);
      const nodos = [...document.querySelectorAll('.nodo')];
      return { cols: cs.gridTemplateColumns.split(' ').length, filas: cs.gridTemplateRows, alto: document.querySelector('#orq').getBoundingClientRect().height,
        n: nodos.length, desborda: nodos.filter(n => n.scrollWidth > n.clientWidth).map(n => n.dataset.nodo), altoNodos: nodos.map(n => Math.round(n.getBoundingClientRect().height)),
        mono: nodos.map(n => { const m = n.querySelector('.mono').getBoundingClientRect(); return [Math.round(m.width), Math.round(m.height)]; }),
        nombre: (() => { const s = getComputedStyle(nodos[3].querySelector('.nodo-nombre')); return [s.fontSize, s.lineHeight, s.fontWeight]; })(),
        dato: (() => { const s = getComputedStyle(nodos[3].querySelector('.nodo-l2')); return [s.fontSize, s.lineHeight]; })(),
        textoFuera: nodos.filter(n => n.querySelector('.nodo-t').scrollHeight > n.clientHeight + 1).map(n => n.dataset.nodo) };
    })()""")
    assert r["n"] == 10 and r["cols"] == 7 and r["filas"] == "48px 48px", r
    assert r["alto"] == 122 and set(r["altoNodos"]) <= {48, 102}, r                    # los de «Equipo», «Redactor» y «Pulidor» ocupan las dos filas (48 + 6 + 48)
    assert all(m == [24, 24] for m in r["mono"]), r["mono"]
    assert r["nombre"] == ["12px", "15px", "600"] and r["dato"] == ["11px", "13px"], r
    assert r["desborda"] == [] and r["textoFuera"] == [], r                              # ningún nodo con scrollWidth > clientWidth y el dato cabe


def test_tarjeta_de_perfil_div_role_button_y_teclado(edge, pagina):
    arrancar(edge, pagina)
    r = edge.js("""(() => {
      const t = [...document.querySelectorAll('.eq-tarj')];
      return { n: t.length, tags: t.map(x => x.tagName + ':' + x.getAttribute('role') + ':' + x.getAttribute('tabindex')),
        anidados: document.querySelectorAll('button button, [role=button] button, button [role=button]').length };
    })()""")
    assert r["n"] == 4 and set(r["tags"]) == {"DIV:button:0"} and r["anidados"] == 0, r
    edge.js("document.querySelector('.eq-tarj').dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true })); 1")
    assert edge.js("!!document.querySelector('.registro')")                          # Intro abre el Registro de sus llamadas, como el clic


def test_animaciones_en_reposo_y_con_una_tarea(edge, pagina):
    arrancar(edge, pagina)
    time.sleep(0.5)
    assert set(x.split("@")[0] for x in nombres(edge)) == {"rec"}, nombres(edge)       # reposo: solo ●REC
    tarea(edge, "inicio")
    time.sleep(0.7)
    n = nombres(edge)
    assert [x for x in n if x.startswith("haz@")] and len([x for x in n if x.startswith("haz@")]) == 1, n   # un solo haz (el trazo único de los conectores de entrada)
    anillos = [x for x in n if x.startswith("gira@")]
    assert 1 <= len(anillos) <= 2, n                                                     # la tarjeta del perfil y el nodo «Equipo» (que muestra su monograma); nada más
    assert edge.js("document.querySelector('.nodo[data-nodo=equipo] .mono').textContent") == "CT"
    assert edge.js("document.querySelector('.eq-tarj[data-perfil=constructor]').dataset.estado") == "trabajando"
    tarea(edge, "fin")
    time.sleep(1.2)
    assert set(x.split("@")[0] for x in nombres(edge)) == {"rec"}, nombres(edge)       # al `tarea fin` desaparecen el anillo y el haz
    assert edge.js("document.querySelector('.eq-tarj[data-perfil=constructor]').dataset.estado") == "hecho"
    assert edge.js("document.querySelector('.nodo[data-nodo=equipo] .mono').textContent") == "EQ"


def test_efecto_apagado_sin_filtros_ni_ambiente_ni_anillo_y_estados_distinguibles(edge, pagina):
    arrancar(edge, pagina)
    edge.js("document.querySelector('#b-efectos').click(); document.querySelector('#b-efectos').click(); 1")           # alto → medio → apagado
    assert edge.js("document.body.dataset.efectos") == "apagado" and edge.js("localStorage.getItem('apuntes_efectos')") == "apagado"
    edge.js("document.querySelector('#r-bandeja-btn').click(); AP.abrirRegistro('constructor'); 1")
    time.sleep(0.4)
    r = edge.js("""(() => {
      const con = [...document.querySelectorAll('*')].filter(e => { const c = getComputedStyle(e); return c.backdropFilter !== 'none'; });
      const amb = document.querySelector('.ambiente');
      return { filtros: con.map(e => e.id || e.className), ambiente: !amb || getComputedStyle(amb).display, grafito: getComputedStyle(document.querySelector('.top')).backgroundColor };
    })()""")
    assert r["filtros"] == [] and r["ambiente"] == "none", r
    assert r["grafito"] == "rgb(24, 25, 31)", r                                          # sin Efectos, el grafito es opaco (#18191F)
    tarea(edge, "inicio", agente="funcional", nombre="Analista funcional")
    time.sleep(0.6)
    assert edge.js("[...document.getAnimations()].filter(a => a.animationName === 'gira').length") == 0   # sin anillo cónico
    est = edge.js("""(() => {
      const c = document.querySelector('.eq-tarj[data-perfil=revisor]'), out = {};
      for (const e of ['espera', 'turno', 'trabajando', 'error', 'sin_presupuesto', 'hecho']) {
        c.dataset.estado = e; const s = getComputedStyle(c), m = getComputedStyle(c.querySelector('.eq-marca')), i = getComputedStyle(c.querySelector('.ind-p')), b = getComputedStyle(c, '::before');
        out[e] = [s.borderTopColor, s.boxShadow !== 'none' && s.boxShadow.includes('28px'), m.display, i.backgroundColor, b.opacity].join('|');
      }
      c.dataset.estado = 'espera'; return out; })()""")
    assert len(set(est.values())) == 6, est                                              # seis estados, seis aspectos (canto, halo, marca, punto y barra), sin anillo
    for etiqueta in ("En espera", "Su turno", "Trabajando", "Hecho", "Error", "Sin presupuesto"):
        assert f'"{etiqueta}"' in JS["equipo.js"]                                      # y cada uno con su texto


def test_filtros_de_fondo_como_mucho_seis_y_nunca_en_las_listas(edge, pagina):
    arrancar(edge, pagina)
    for i in range(7):
        edge.js("AP.notificar({id: 'n%d', analisis: 1, categoria: 'decisión', texto: 'Decisión número %d con un texto algo largo para ocupar varias líneas en la pila de avisos', minuto: '01:0%d', t_seg: 61, estado: 'confirmada'}); 1" % (i, i, i % 10))
    time.sleep(3.0)                                                                     # la cola suelta una cada 900 ms
    edge.js("document.querySelector('#r-bandeja-btn').click(); AP.abrirRegistro('coordinador'); 1")
    time.sleep(0.6)
    r = edge.js("""(() => {
      const con = [...document.querySelectorAll('*')].filter(e => { const c = getComputedStyle(e); return c.backdropFilter !== 'none'; });
      const prohibido = con.filter(e => e.closest('.trans, #eq-feed-lista, #r-insights, #r-bandeja-lista, .sb-plot'));
      return { total: con.length, notifs: document.querySelectorAll('.notif').length, conFiltro: con.filter(e => e.classList.contains('notif')).length,
        quienes: con.map(e => e.id || String(e.className.baseVal !== undefined ? e.className.baseVal : e.className).split(' ')[0]), prohibido: prohibido.length, enStyle: document.querySelectorAll('[style*=backdrop]').length };
    })()""")
    assert r["notifs"] == 2, r                                                          # como mucho 2 a la vez (siete decisiones: el resto, en cola y agrupado en «+N hallazgos»)
    assert r["total"] <= 6 and r["conFiltro"] <= 4 and r["prohibido"] == 0 and r["enStyle"] <= 6, r
    assert "r-bandeja" in r["quienes"] and "registro" in r["quienes"], r


def test_sin_elipsis_ni_line_clamp_ni_desborde_en_tarjetas_avisos_hallazgos_feed_y_definiciones(edge, pagina):
    arrancar(edge, pagina)
    for i in range(3):
        edge.js("AP.notificar({id: 'e%d', analisis: 1, categoria: 'riesgo', texto: 'Riesgo %d: ' + 'palabra '.repeat(60), minuto: '02:00', t_seg: 120, estado: 'confirmada'}); 1" % (i, i))
    time.sleep(3)
    edge.js("document.querySelector('#r-bandeja-btn').click(); 1")
    time.sleep(0.5)
    r = edge.js("""(() => {
      const base = [...document.querySelectorAll('.tarj, .notif, .bj-f, .eq-fila, .eq-def-fila, .eq-tarj')];
      const todos = base.flatMap(e => [e, ...e.querySelectorAll('*')]);
      const malos = todos.filter(e => { const c = getComputedStyle(e); return c.textOverflow === 'ellipsis' || (c.webkitLineClamp && c.webkitLineClamp !== 'none'); }).map(e => e.className || e.tagName);
      const desborda = base.filter(e => e.scrollWidth > e.clientWidth + 1).map(e => e.className);
      return { n: base.length, malos, desborda };
    })()""")
    assert r["n"] >= 12 and r["malos"] == [] and r["desborda"] == [], r


def test_insights_desplazados_no_se_mueven_y_avisan_de_los_nuevos(edge, pagina):
    arrancar(edge, pagina)
    # muchas tarjetas, repartidas por análisis, para que la columna tenga scroll
    edge.js("""(() => {
      const ts = []; for (let i = 0; i < 40; i++) ts.push({ id: 'x' + i, analisis: 1 + Math.floor(i / 5), categoria: ['decisión', 'pregunta', 'riesgo', 'pendiente'][i % 4], texto: 'Tarjeta ' + i + ' con un texto de varias palabras para que ocupe espacio', minuto: '0' + (i % 10) + ':10', t_seg: 60 + i, estado: 'confirmada' });
      window.__emitir({ tipo: 'tarjetas', nuevas: ts }); return 1; })()""")
    time.sleep(0.8)
    edge.js("document.querySelector('#r-plan-scroll').scrollTop = 600; 1")
    time.sleep(0.3)
    antes = edge.js("""(() => { const sc = document.querySelector('#r-plan-scroll'); const t = [...document.querySelectorAll('#r-insights .tarj')].find(x => x.getBoundingClientRect().top > sc.getBoundingClientRect().top + 40);
      window.__ref = t; return { id: t.dataset.id, top: t.getBoundingClientRect().top, scroll: sc.scrollTop }; })()""")
    assert antes["scroll"] >= 590, antes
    edge.js("""(() => { const nuevas = []; for (let i = 0; i < 5; i++) nuevas.push({ id: 'nuevo' + i, analisis: 20, categoria: 'idea', texto: 'Nueva ' + i, minuto: '09:0' + i, t_seg: 540 + i, estado: 'confirmada' });
      window.__emitir({ tipo: 'tarjetas', nuevas }); return 1; })()""")
    time.sleep(0.8)
    despues = edge.js("({ top: window.__ref.getBoundingClientRect().top, texto: document.querySelector('#r-ins-nuevos').textContent, oculto: document.querySelector('#r-ins-nuevos').hidden })")
    assert abs(despues["top"] - antes["top"]) < 1.5, (antes, despues)                  # la línea que se está leyendo no se mueve
    assert despues["oculto"] is False and despues["texto"] == "5 nuevos ↑", despues


def test_foco_visible_con_tab_en_todo_lo_interactivo(edge, pagina):
    arrancar(edge, pagina)
    edge.js("document.querySelector('#r-bandeja-btn').click(); 1")
    time.sleep(0.4)
    edge.js("document.activeElement && document.activeElement.blur(); document.body.focus(); 1")
    vistos, sin_foco = set(), []
    for _ in range(90):
        for tipo in ("keyDown", "keyUp"):
            edge.cmd("Input.dispatchKeyEvent", type=tipo, key="Tab", code="Tab", windowsVirtualKeyCode=9)
        r = edge.js("""(() => { const e = document.activeElement; if (!e || e === document.body) return null; window.__v = window.__v || []; const c = getComputedStyle(e);
        const repetido = window.__v.includes(e); window.__v.push(e);
        return { id: e.id || String(e.className) || e.tagName, n: window.__v.length, repetido, vis: e.matches(':focus-visible'), ancho: c.outlineWidth, estilo: c.outlineStyle, color: c.outlineColor, sombra: c.boxShadow }; })()""")
        if not r:
            continue
        if r["repetido"]:
            break
        vistos.add(r["n"])
        interior = r["id"] in ("r-trans", "trans") or bool({"lin", "eq-fila", "bj-f"} & set(str(r["id"]).split()))   # filas de lista: anillo interior (outline-offset −2)
        if not (r["vis"] and r["estilo"] == "solid" and r["ancho"] == "2px" and (interior or r["sombra"] != "none")):
            sin_foco.append(r)
    assert len(vistos) >= 25, vistos                                                    # se recorrió buena parte de la pantalla (botones, chips, filas, campos…)
    assert sin_foco == [], sin_foco                                                     # anillo doble: contorno azul de 2 px + separación del fondo


def test_interruptor_efectos_se_recuerda_y_modo_reunion_arranca_en_medio(edge, pagina):
    arrancar(edge, pagina)
    ciclo = []
    for _ in range(4):
        ciclo.append(edge.js("document.body.dataset.efectos + '|' + document.querySelector('#b-efectos').textContent"))
        edge.js("document.querySelector('#b-efectos').click(); 1")
    assert ciclo == ["alto|Efectos: alto", "medio|Efectos: medio", "apagado|Efectos: apagado", "alto|Efectos: alto"], ciclo
    assert edge.js("localStorage.getItem('apuntes_efectos')") == "medio"                 # (la cuarta pulsación dejó «medio»)
    assert edge.js("document.querySelector('#s-efectos').value") == "medio"
    edge.js("localStorage.removeItem('apuntes_efectos'); AP.efectos.elegir('auto'); 1")
    assert edge.js("document.body.dataset.efectos") == "alto"                          # vista completa: alto por defecto
    edge.js("document.body.dataset.modo = 'reunion'; 1")
    time.sleep(0.2)
    assert edge.js("document.body.dataset.efectos") == "medio"                         # Modo reunión: medio por defecto
    r = edge.js("""(() => { const amb = document.querySelector('.ambiente'); return [getComputedStyle(amb).display, getComputedStyle(document.body).getPropertyValue('--blur-n').trim()]; })()""")
    assert r == ["none", "none"], r                                                      # sin capa ambiente ni desenfoque en las notificaciones
    edge.js("delete document.body.dataset.modo; 1")


def test_modo_reunion_paneles_opacos_y_vidrio_solo_dentro_del_derecho(edge, pagina):
    arrancar(edge, pagina)
    edge.js("""(() => { const r = document.documentElement; r.style.setProperty('--mr-izq', '360px'); r.style.setProperty('--mr-der', '360px');
      document.body.dataset.mr = 'dos'; document.body.dataset.modo = 'reunion'; document.querySelector('#mr-barra').hidden = false; return 1; })()""")
    edge.js("AP.efectos.elegir('alto'); document.querySelector('#r-bandeja-btn').click(); 1")
    time.sleep(0.6)
    r = edge.js("""(() => {
      const bg = s => getComputedStyle(document.querySelector(s)).backgroundColor;
      const f = [...document.querySelectorAll('*')].filter(e => { const c = getComputedStyle(e); return c.backdropFilter !== 'none'; });
      const inRect = document.querySelector('.col-der').getBoundingClientRect();
      return { izq: bg('.col-izq'), der: bg('.col-der'), barra: bg('#mr-barra'), orq: bg('#orq'), filtros: f.map(e => e.id || String(e.className.baseVal !== undefined ? e.className.baseVal : e.className).split(' ')[0]),
        barraConFiltro: getComputedStyle(document.querySelector('#mr-barra')).backdropFilter, fuera: f.filter(e => { const b = e.getBoundingClientRect(); return b.left < inRect.left - 1; }).length };
    })()""")
    for k in ("izq", "der", "barra", "orq"):
        assert r[k] == "rgb(24, 25, 31)", (k, r)                                        # alfa 1: la opacidad la pone la ventana, no el CSS
    assert r["barraConFiltro"] == "none" and r["fuera"] == 0, r                         # ni la barra ni nada fuera del panel derecho lleva desenfoque
    assert "r-bandeja" in r["filtros"], r
    edge.js("delete document.body.dataset.modo; delete document.body.dataset.mr; 1")


def test_las_clases_de_entrada_se_retiran_al_terminar_la_animacion(edge, pagina):
    arrancar(edge, pagina)
    edge.js("AP.pestana('equipo'); 1")                                                  # la tarjeta del perfil vive en la pestaña «Equipo»: oculta no anima y no puede terminar
    edge.js("AP.hooks.anadirSegmento({ id: 9999, t: 625, mmss: '10:25', fuente: 'yo', texto: 'Una línea nueva' }); 1")
    assert edge.js("document.querySelector('#r-trans .lin[data-id=\"9999\"]').classList.contains('nueva')")
    tarea(edge, "inicio", ident=901)
    time.sleep(0.5)
    tarea(edge, "fin", ident=901)
    time.sleep(0.2)
    assert edge.js("document.querySelector('.eq-tarj[data-perfil=constructor]').classList.contains('traza')")
    time.sleep(1.2)
    r = edge.js("""(() => ({ nueva: document.querySelectorAll('.nueva, .entra, .traza').length, terminadas: [...document.getAnimations()].filter(a => a.playState === 'finished').length }))()""")
    assert r == {"nueva": 0, "terminadas": 0}, r                                       # ni clases ni animaciones terminadas que sigan contando


def test_cambio_de_pantalla_con_view_transition_y_con_respaldo(edge, pagina):
    arrancar(edge, pagina, antes="window.__vt = 0; const o = document.startViewTransition && document.startViewTransition.bind(document); if (o) document.startViewTransition = (f) => { window.__vt++; return o(f); };")
    evento(edge, tipo="estado", estado="revision")
    time.sleep(0.8)
    assert edge.js("document.body.dataset.vista") == "revision"
    assert edge.js("window.__vt") == 1                                                  # un único startViewTransition envuelve el cambio
    arrancar(edge, pagina, antes="document.startViewTransition = undefined;")
    evento(edge, tipo="estado", estado="revision")
    time.sleep(0.4)
    assert edge.js("document.body.dataset.vista") == "revision"                         # sin la API, cambia igual (respaldo)


def test_hover_pulsacion_y_foco_de_los_materiales(edge, pagina):
    arrancar(edge, pagina)
    r = edge.js("""(() => { const g = (s, p = null) => { const e = document.querySelector(s); if (!e) throw new Error('falta ' + s); return getComputedStyle(e, p); };
      return { tarj: [g('.eq-tarj').transitionDuration, g('.eq-tarj').transitionProperty], btn: [g('#r-pausa').transitionDuration, g('#r-pausa').transitionProperty],
        fila: [g('#r-trans .lin').transitionDuration, g('#r-trans .lin').transitionProperty], radio: [g('.eq-tarj').borderRadius, g('.btn').borderRadius, g('.input').borderRadius, g('.panel-notas').borderRadius, g('.min').borderRadius, g('.nodo').borderRadius] }; })()""")
    assert "0.16s" in r["tarj"][0] and "translate" in r["tarj"][1] and "scale" in r["tarj"][1], r
    assert "translate" in r["btn"][1] and "scale" in r["btn"][1] and "0.16s" in r["btn"][0], r
    assert r["fila"][1].startswith("background-color") and "translate" not in r["fila"][1], r   # las filas de lista solo cambian el fondo
    assert r["radio"] == ["10px", "8px", "8px", "10px", "4px", "8px"], r
    css = _quita_comentarios(CSS["app.css"])
    assert ".btn:active:not(:disabled) { scale: .985" in css and ".min:active { scale: .96" in css


def test_movimiento_reducido_deja_solo_estado_fijo(tmp_path, pagina):
    e = Edge(tmp_path, _puerto(), reducido=True)
    try:
        arrancar(e, pagina)
        tarea(e, "inicio")
        time.sleep(0.6)
        assert e.js(ANIMS) == [], e.js(ANIMS)                                          # ni ●REC ni anillo ni haz: todo en seco
        assert e.js("document.querySelector('.eq-tarj[data-perfil=constructor]').dataset.estado") == "trabajando"   # pero el halo fijo y el texto dicen que trabaja
        e.js("AP.notificar({id: 'r1', analisis: 1, categoria: 'decisión', texto: 'Aviso', minuto: '01:00', t_seg: 60, estado: 'confirmada'}); 1")
        time.sleep(1.2)
        r = e.js("""(() => ({ notif: document.querySelectorAll('.notif').length, anims: document.getAnimations().length,
          blur: [...document.querySelectorAll('*')].filter(x => /blur/.test(getComputedStyle(x).filter)).length,
          halo: getComputedStyle(document.querySelector('.eq-tarj[data-perfil=constructor]')).boxShadow.includes('28px'),
          anillo: getComputedStyle(document.querySelector('.eq-tarj[data-perfil=constructor]'), '::after').animationName }))()""")
        assert r["notif"] == 1 and r["anims"] == 0 and r["blur"] == 0 and r["halo"] and r["anillo"] == "none", r
    finally:
        e.cerrar()


def test_inicio_y_revision_cargan_con_el_nuevo_acabado(edge, pagina):
    arrancar(edge, pagina, snapshot=foto(estado="inactivo", sesion=None, revision=None))
    time.sleep(0.4)
    r = edge.js("""(() => { const l = document.querySelector('.ini-izq'); const c = getComputedStyle(l);
      return { vista: document.body.dataset.vista, radio: c.borderRadius, filtro: c.backdropFilter, ancho: Math.round(l.getBoundingClientRect().width), btn: getComputedStyle(document.querySelector('#i-empezar')).height }; })()""")
    assert r["vista"] == "inicio" and r["radio"] == "14px" and r["filtro"] != "none" and r["ancho"] == 400 and r["btn"] == "40px", r   # lámina de vidrio flotante única, 400 px
    arrancar(edge, pagina, snapshot=foto(estado="revision", revision={"estado": "generando"}))
    time.sleep(0.6)
    assert edge.js("document.body.dataset.vista") == "revision" and edge.js("document.querySelector('#orq').dataset.plegado") == "false"   # la revisión llega con la banda desplegada


# ============================================================ revisión de capturas (2026-11-04)
@pytest.mark.parametrize("nivel", ["alto", "medio", "apagado"])
def test_en_modo_reunion_los_avisos_son_siempre_solidos(edge, pagina, nivel):
    arrancar(edge, pagina)
    edge.js("""(() => { const r = document.documentElement; r.style.setProperty('--mr-izq', '360px'); r.style.setProperty('--mr-der', '360px'); document.body.dataset.mr = 'dos'; document.body.dataset.modo = 'reunion';
      AP.efectos.elegir('%s'); for (let i = 0; i < 2; i++) AP.notificar({ id: 's' + i, analisis: 1, categoria: 'riesgo', texto: 'Aviso ' + i, minuto: '05:4' + i, t_seg: 340, estado: 'confirmada' }); return 1; })()""" % nivel)
    time.sleep(2.2)
    r = edge.js("""(() => [...document.querySelectorAll('.notif')].map(x => { const c = getComputedStyle(x); return [c.backgroundColor, c.backdropFilter]; }))()""")
    assert len(r) == 2 and all(f == ["rgb(30, 31, 38)", "none"] for f in r), r         # --elev-solido (#1E1F26): alfa 1 y sin desenfoque
    edge.js("delete document.body.dataset.modo; delete document.body.dataset.mr; 1")


def test_el_modo_reunion_real_activa_el_nivel_medio_sin_forzar_el_dataset(edge, pagina):
    """modo-reunion.js hace `body.dataset.modo = "reunion"` al entrar; el nivel medio debe salir de ahí y volver a alto al salir (sin elección del usuario)."""
    arrancar(edge, pagina)
    assert edge.js("document.body.dataset.efectos") == "alto"
    edge.js("document.body.dataset.modo = 'reunion'; 1")                                 # exactamente lo que hace montarDom(true)
    time.sleep(0.2)
    assert edge.js("document.body.dataset.efectos") == "medio"
    edge.js("delete document.body.dataset.modo; 1")
    time.sleep(0.2)
    assert edge.js("document.body.dataset.efectos") == "alto"
    assert 'body.dataset.modo = "reunion"' in JS["modo-reunion.js"]


MEDIR_PANEL = """(() => { const dentro = (e) => { const r = e.getBoundingClientRect(); const t = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2); return !!t && (t === e || e.contains(t)); };
  const objetivos = [document.querySelector('#r-bandeja-x'), ...document.querySelectorAll('#r-bandeja-filtros .bj-chip:not([hidden])'), document.querySelector('#r-bandeja .t-title')];
  const pila = document.querySelector('#r-notifs').getBoundingClientRect(), panel = document.querySelector('#r-bandeja').getBoundingClientRect();
  return { n: objetivos.length, fallan: objetivos.filter(e => !dentro(e)).map(e => e.id || e.textContent), notifs: document.querySelectorAll('.notif').length, pilaDer: Math.round(pila.right), panelIzq: Math.round(panel.left),
    boton: dentro(document.querySelector('#r-bandeja-btn')) }; })()"""


def test_la_pila_de_avisos_no_tapa_cerrar_ni_los_filtros_de_hallazgos(edge, pagina):
    arrancar(edge, pagina)
    for i in range(3):
        edge.js("AP.notificar({id: 'h%d', analisis: 1, categoria: 'decisión', texto: 'Decisión %d ' + 'con bastante texto '.repeat(6), minuto: '01:0%d', t_seg: 61, estado: 'confirmada'}); 1" % (i, i, i))
    edge.js("document.querySelector('#r-bandeja-btn').click(); 1")
    time.sleep(3.2)
    r = edge.js(MEDIR_PANEL)
    assert r["notifs"] >= 2 and r["n"] >= 4 and r["fallan"] == [] and r["boton"], r         # vista normal: «Cerrar», filtros y título pulsables (como mucho 2 avisos en cola de salida)
    assert edge.js("getComputedStyle(document.querySelector('#r-notifs')).display") == "none", r   # con Hallazgos abierto el carril se aparta: la lámina ya lo lista todo y nada se tapa
    # Modo reunión: no hay otro sitio; la pila empieza bajo la cabecera y los filtros del panel
    edge.js("""(() => { const r = document.documentElement; r.style.setProperty('--mr-izq', '360px'); r.style.setProperty('--mr-der', '360px'); document.body.dataset.mr = 'dos'; document.body.dataset.modo = 'reunion';
      document.querySelector('#mr-barra').hidden = false; window.dispatchEvent(new Event('resize')); return 1; })()""")
    time.sleep(0.6)
    r = edge.js(MEDIR_PANEL)
    assert r["notifs"] >= 2 and r["fallan"] == [], r
    edge.js("delete document.body.dataset.modo; delete document.body.dataset.mr; 1")


MEDIR_TEMAS = """(() => { const t = [...document.querySelectorAll('.sb-tema')].map(x => { const r = x.getBoundingClientRect(); return { l: r.left, r: r.right, titulo: x.title }; }).sort((a, b) => a.l - b.l);
  const cruces = []; for (let i = 1; i < t.length; i++) if (t[i].l < t[i - 1].r - 0.5) cruces.push([t[i - 1].titulo, t[i].titulo]);
  return { n: t.length, cruces, titulos: t.map(x => x.titulo).join(' | ') }; })()"""


def test_los_temas_de_la_banda_sesion_nunca_se_solapan(edge, pagina):
    arrancar(edge, pagina)
    edge.js("AP.pestana('sesion'); 1")                                                  # la banda vive en la pestaña «Sesión»: con la pestaña oculta no mide nada
    time.sleep(0.5)                                                                  # la foto trae tres tramos que empiezan a la vez (00:05), uno por perfil
    r = edge.js(MEDIR_TEMAS)
    assert r["n"] >= 2 and r["cruces"] == [], r
    for titulo in ("Calendario del piloto", "Reglas del cupo", "Catálogo de hoteles"):
        assert titulo in r["titulos"], r                                                    # ningún dato se pierde (si se absorbe, queda en el tooltip)
    f = foto()                                                                              # tramos casi iguales: los de ancho casi nulo se absorben en el más reciente
    f["temas"] = [{"analisis": i, "desde_t": 5, "hasta_t": 20 + i, "titulo": f"Tema {i}", "perfil": "coordinador"} for i in range(1, 6)] + [{"analisis": 9, "desde_t": 5, "hasta_t": 610, "titulo": "Final", "perfil": "revisor"}]
    edge.js("window.__emitir(Object.assign({tipo: 'snapshot'}, %s)); 1" % json.dumps(f))
    time.sleep(1.2)
    r = edge.js(MEDIR_TEMAS)
    assert r["cruces"] == [], r
    assert all(f"Tema {i}" in r["titulos"] for i in range(1, 6)) and "Final" in r["titulos"], r
    evento(edge, tipo="estado", estado="revision")                                          # y en la revisión
    time.sleep(1.0)
    assert edge.js(MEDIR_TEMAS)["cruces"] == []


@pytest.mark.parametrize("esquema", ["dark", "light"])
def test_leyenda_de_la_banda_sesion_con_colores_reales_y_contraste(tmp_path, pagina, esquema):
    e = Edge(tmp_path, _puerto(), esquema=esquema)
    try:
        arrancar(e, pagina)
        r = e.js("""(() => { const num = (c) => c.match(/[\\d.]+/g).slice(0, 3).map(Number); const bg = num(getComputedStyle(document.body).backgroundColor);
        const lum = (rgb) => { const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; }; return 0.2126 * f(rgb[0]) + 0.7152 * f(rgb[1]) + 0.0722 * f(rgb[2]); };
        const con = (a, b) => { const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p); return (x + 0.05) / (y + 0.05); };
        const sal = []; const colores = {};
        document.querySelectorAll('.sb-filtro:has(svg)').forEach((b) => { for (const on of [true, false]) { b.setAttribute('aria-pressed', String(on)); const c = num(getComputedStyle(b.querySelector('svg')).color);
          sal.push([b.dataset.tipo, on, Math.round(con(c, bg) * 100) / 100]); if (on) colores[b.dataset.tipo] = c.join(','); } b.setAttribute('aria-pressed', 'true'); });
        const fills = [...document.querySelectorAll('.sb-filtro svg .lleno')].map((x) => getComputedStyle(x).fill);
        return { sal, colores, fills }; })()""")
        assert len(r["sal"]) >= 12, r
        assert min(x[2] for x in r["sal"] if x[0] != "tu") >= 3, [x for x in r["sal"] if x[2] < 3]            # ≥ 3:1, activos o no
        assert "rgb(0, 0, 0)" not in r["fills"], r["fills"]                                                    # nunca el negro por defecto del SVG
        assert len({r["colores"][k] for k in ("pendiente", "riesgo", "decision")}) == 3, r["colores"]        # y cada tipo con su color
    finally:
        e.cerrar()


SELECTORES_SIN_CORTE = ".reunion-id, .reunion-tema, .reunion-meta, .item .n, .item .tag, .orq-estado, .orq-ult, .traza-b, .ctx-proy, .cambio-h .m, .tarj, .notif, .bj-f, .eq-fila, .eq-def-fila, .eq-tarj"


def _sin_cortes(e):
    sel = json.dumps(SELECTORES_SIN_CORTE)
    return e.js("""(() => { const l = [...document.querySelectorAll(%s)].filter((x) => x.offsetParent !== null || getComputedStyle(x).position === 'fixed');
      const cortados = l.flatMap((x) => [x, ...x.querySelectorAll('*')]).filter((x) => { const c = getComputedStyle(x);
        return c.textOverflow === 'ellipsis' || (c.webkitLineClamp && c.webkitLineClamp !== 'none') || (x.matches(%s) && (x.scrollWidth > x.clientWidth + 1 || (c.overflowY !== 'visible' && x.scrollHeight > x.clientHeight + 1))); })
        .map((x) => String(x.className || x.tagName)); return { n: l.length, cortados }; })()""" % (sel, sel))


@pytest.mark.parametrize("ancho", [1440, 1280])
def test_cabecera_y_lineas_sin_texto_cortado_ni_desborde_horizontal(tmp_path, pagina, ancho):
    e = Edge(tmp_path, _puerto(), ancho=ancho)
    try:
        f = foto()
        f["sesion"] = dict(f["sesion"], proyecto="Planificador de Grupos (carpeta compartida de otra persona)", tema="Integración de tarifas, cupos y reglas de Revenue con el equipo de Nordia")
        arrancar(e, pagina)
        e.js("window.__emitir(Object.assign({tipo: 'snapshot'}, %s)); document.querySelector('#mr-entrar').hidden = false; 1" % json.dumps(f))
        time.sleep(1.0)
        r = e.js("""(() => { const t = document.querySelector('.top'), id = document.querySelector('.reunion-id');
          return { docAncho: document.documentElement.scrollWidth, ventana: innerWidth, top: t.getBoundingClientRect().height, topScroll: t.scrollWidth, topClient: t.clientWidth, idDentro: id.getBoundingClientRect().right <= t.getBoundingClientRect().right + 0.5,
            idTexto: id.textContent, hijosFuera: [...t.querySelectorAll(':scope > *, #r-cab > *')].filter((x) => x.offsetParent && x.getBoundingClientRect().right > innerWidth + 0.5).map((x) => x.id || x.className) }; })()""")
        assert r["docAncho"] <= r["ventana"] and r["topScroll"] <= r["topClient"] and r["idDentro"] and r["hijosFuera"] == [], r
        assert "Planificador de Grupos (carpeta compartida de otra persona)" in r["idTexto"] and "Integración de tarifas, cupos y reglas" in r["idTexto"], r     # el texto entero
        n, cortados = 0, []
        for pestana in ("consejos", "insights", "objetivos", "equipo", "pregunta", "sesion"):   # cada pestaña de la columna derecha, una a una (solo una está a la vista)
            e.js("AP.pestana('%s'); 1" % pestana)
            time.sleep(0.15)
            c = _sin_cortes(e)
            n += c["n"]
            cortados += c["cortados"]
        assert cortados == [] and n >= 15, (n, cortados)
        e.js("document.body.dataset.modo = 'reunion'; 1")                                    # la línea de orquestación plegada (la de Modo reunión) crece en altura con su texto
        time.sleep(0.6)
        alto = e.js("document.querySelector('#orq').getBoundingClientRect().height")
        e.js("document.querySelector('#orq-estado').dataset.estado = 'analizando'; document.querySelector('#orq-estado').textContent = 'Analista funcional trabajando 00:05–10:10 con haiku, a petición del usuario, con un texto largo que no cabe ' + 'y sigue y sigue '.repeat(8); 1")
        time.sleep(0.3)
        assert e.js("document.querySelector('#orq').getBoundingClientRect().height") > alto
        assert _sin_cortes(e)["cortados"] == []
    finally:
        e.cerrar()


def test_inicio_ruta_cadencia_papel_y_boton_empezar(edge, pagina):
    arrancar(edge, pagina, snapshot=foto(estado="inactivo", sesion=None, revision=None))
    time.sleep(0.4)
    edge.js("""(() => { document.querySelector('#i-raiz').textContent = 'Raíz de proyectos: C:\\\\Proyectos\\\\apuntes\\\\pruebas\\\\proyectos\\\\una\\\\ruta\\\\muy\\\\larga\\\\sin\\\\espacios\\\\ni\\\\saltos';
      document.querySelector('#i-obj-campo').hidden = false;
      const l = document.querySelector('#i-lista'); const it = document.createElement('button'); it.className = 'item'; it.innerHTML = '<span class="n">Bandeja (reunión sin proyecto)</span><span class="tag">se guarda en apuntes bandeja y es un texto largo</span>'; l.append(it); return 1; })()""")
    time.sleep(0.3)
    r = edge.js("""(() => { const p = document.querySelector('.ini-izq').getBoundingClientRect(), raiz = document.querySelector('#i-raiz').getBoundingClientRect();
      const bs = [...document.querySelectorAll('.seg-4 button')].map((b) => b.getBoundingClientRect()); const papel = getComputedStyle(document.querySelector('#i-obj-campo'));
      const it = document.querySelector('#i-lista .item:last-child'), ik = it.querySelector('.n'), tg = it.querySelector('.tag');
      const v = document.querySelector('#v-inicio'); v.scrollTop = v.scrollHeight; const b = document.querySelector('#i-empezar').getBoundingClientRect(), m = document.querySelector('main').getBoundingClientRect();
      return { raizDentro: raiz.right <= p.right + 0.5 && raiz.left >= p.left, raizScroll: document.querySelector('#i-raiz').scrollWidth <= document.querySelector('#i-raiz').clientWidth + 1,
        filas: new Set(bs.map((x) => Math.round(x.top))).size, cols: new Set(bs.map((x) => Math.round(x.left))).size, anchos: bs.map((x) => Math.round(x.width)), alturas: new Set(bs.map((x) => Math.round(x.height))).size,
        papelPad: [papel.paddingTop, papel.paddingLeft, papel.marginTop], filaCorte: [ik.scrollWidth > ik.clientWidth + 1, tg.scrollWidth > tg.clientWidth + 1, getComputedStyle(ik).textOverflow, getComputedStyle(tg).textOverflow],
        botonVisible: b.top >= m.top && b.bottom <= m.bottom + 0.5 }; })()""")
    assert r["raizDentro"] and r["raizScroll"], r                                          # la ruta envuelve dentro de la lámina
    assert r["filas"] == 2 and r["cols"] == 2 and r["alturas"] == 1 and max(r["anchos"]) - min(r["anchos"]) <= 1, r   # cadencia: rejilla 2×2 sin huecos
    assert all(float(x[:-2]) >= 12 for x in r["papelPad"]), r                               # el bloque de papel con aire
    assert r["filaCorte"] == [False, False, "clip", "clip"], r                              # «se guarda en apunt…» ya no se corta
    assert r["botonVisible"], r                                                             # «Empezar reunión» se alcanza en el scroll a 900 px de alto
