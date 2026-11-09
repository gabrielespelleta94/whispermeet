"""Notificaciones flotantes de la reunión y panel Hallazgos (web/reunion.js, DESIGN-equipo.md §5, acabado de DESIGN-visual.md; antes «Bandeja»).

Dos capas: comprobaciones estáticas de las reglas que no se rompen (siempre) y una pasada en un Edge/Chrome sin cabeza con
reunion.js y sesion.js REALES sobre un DOM mínimo y tiempo virtual (se omite si no hay navegador). Sin modelo ni red."""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

WEB = Path(__file__).resolve().parent.parent / "web"


def _texto(nombre: str) -> str:
    return (WEB / nombre).read_text(encoding="utf-8")


def _seccion_js() -> str:
    js = _texto("reunion.js")
    i = js.index("notificaciones flotantes y Bandeja (capa sobre Insights")
    codigo = js[i:js.index("// Título completo al pasar el ratón", i)]
    codigo = re.sub(r"/\*.*?\*/", "", codigo, flags=re.S)
    return re.sub(r"^\s*//.*$|\s//\s.*$", "", codigo, flags=re.M)         # sin comentarios: solo cuenta el código


def test_contenedor_y_tokens():
    html = _texto("index.html")
    assert re.search(r'<div id="r-notifs" aria-live="polite"', html)
    assert 'id="r-bandeja-btn"' in html and 'id="r-bandeja"' in html and 'id="r-bandeja-lista"' in html
    equipo = _texto("equipo.css")
    notif = re.search(r"^\.notif \{(.*?)\}", equipo, re.S | re.M).group(1)
    assert "border-radius: var(--r-l)" in notif and "background: var(--elev-solido)" in notif and "backdrop-filter" not in notif   # revisión 2026-11-06: fondo OPACO, sin vidrio ni desenfoque (nada se lee a través de un aviso)
    assert "position: fixed" not in re.search(r"^#r-notifs \{(.*?)\}", equipo, re.S | re.M).group(1)   # el carril va en el flujo de la columna derecha: nunca flota sobre «Ahora», las pestañas o los consejos
    html = _texto("index.html")
    assert "Hallazgos" in re.search(r'<aside id="r-bandeja"[^>]*>', html).group(0) and ">Hallazgos 0<" in html     # renombrado: ids iguales, texto visible nuevo
    assert "Bandeja" not in re.search(r'<aside id="r-bandeja".*?</aside>', html, re.S).group(0) and ">Bandeja" not in html


def test_reglas_del_codigo():
    js = _seccion_js()
    assert "innerHTML" not in js and "setInterval" not in js                  # texto por textContent; un setTimeout de cola y uno por notificación
    assert "AP.notificar" in js and "d.todas" in js                           # entra por la misma cola; `todas` no notifica
    assert ".submit" not in js and "requestSubmit" not in js and "api(" not in js   # Pregúntale solo rellena el campo
    css = _texto("equipo.css")
    bloque = css[css.index("avisos de lo importante"):css.index("@media (max-width: 1100px)")]
    assert "line-clamp" not in bloque and "text-overflow" not in bloque
    assert "MAX_VISIBLES = 2" in js and "notif-mas" in css and "+${n} hallazgo" in js   # como mucho 2 visibles; lo demás en cola y agrupado en «+N hallazgos»
    assert 'EMERGE = new Set(["decision", "contradiccion", "riesgo"])' in js      # solo decisión, contradicción y riesgo merecen aviso emergente


HARNESS = """<!doctype html><html lang="es"><head><meta charset="utf-8">
<link rel="stylesheet" href="%(web)s/app.css"><link rel="stylesheet" href="%(web)s/equipo.css"></head>
<body data-vista="reunion" style="overflow:auto">
<script>document.documentElement.dataset.theme = "light";</script>
<section id="v-reunion"><div class="reunion-grid"><div class="col-izq"><div id="r-trans"></div></div>
<div class="col-der"><div id="r-plan-scroll"></div><div id="r-obj-scroll"></div><button id="r-plan-nuevos" hidden></button><button id="r-ins-nuevos" hidden></button><div id="r-ins-h"></div>
<span id="r-ins-n"></span><details id="r-resumen-det" hidden><p id="r-resumen"></p></details><div id="r-insights"></div>
<details id="r-pregunta"><form id="f-pregunta"><input name="pregunta" maxlength="400"></form></details></div></div></section>
<button id="r-bandeja-btn" type="button" aria-expanded="false">Hallazgos 0</button>
<aside id="r-bandeja" hidden><div class="bj-cab"><span class="t-title">Hallazgos</span><span id="r-bandeja-total"></span><button id="r-bandeja-x" type="button">Cerrar</button></div>
<div id="r-bandeja-filtros"></div><div id="r-bandeja-lista"></div></aside>
<div id="r-notifs" aria-live="polite"></div><pre id="res">pendiente</pre>
<script>
const vivos = new Set(), setReal = window.setTimeout.bind(window), clearReal = window.clearTimeout.bind(window);
window.setTimeout = (f, ms, ...a) => { const id = setReal(() => { vivos.delete(id); f(...a); }, ms); vivos.add(id); return id; };
window.clearTimeout = (id) => { vivos.delete(id); clearReal(id); };
const h = (tag, attrs = {}, ...hijos) => { const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) { if (v === false || v == null) continue; if (k === "class") e.className = v; else if (k.startsWith("on")) e.addEventListener(k.slice(2), v); else e.setAttribute(k, v === true ? "" : v); }
  for (const c of hijos.flat()) if (c != null && c !== false) e.append(c.nodeType ? c : document.createTextNode(String(c))); return e; };
window.AP = { hooks: {}, S: { estado: "grabando", segmentos: [], tarjetas: [], objetivos: [], checks: [], t: 0 }, UI: {}, h,
  $: (s, r = document) => r.querySelector(s), $$: (s, r = document) => [...r.querySelectorAll(s)],
  mmss: (s) => String(Math.floor(s / 60)).padStart(2, "0") + ":" + String(Math.floor(s %% 60)).padStart(2, "0"), kfmt: (n) => String(n), traza: [], enlazar: () => {} };
AP.S.monitor = { definiciones: [], feed: [] };
</script>
<script src="%(web)s/iconos.js"></script>
<script src="%(web)s/nombres.js"></script>
<script src="%(web)s/reunion.js"></script>
<script src="%(web)s/sesion.js"></script>
<script>
(async () => { try {
  const AP = window.AP, S = AP.S, cont = document.getElementById("r-notifs");
  const esp = (ms) => { document.getElementById("res").textContent = "paso " + Math.round(performance.now()); return new Promise((r) => setReal(r, ms)); };
  const res = { aparicion: [], errores: [] };
  window.addEventListener("error", (e) => res.errores.push(String(e.message)));
  const visibles = () => [...cont.querySelectorAll(".notif:not(.saliendo)")];
  new MutationObserver((ms) => ms.forEach((m) => m.addedNodes.forEach((n) => { if (n.classList && n.classList.contains("notif")) res.aparicion.push(Math.round(performance.now())); }))).observe(cont, { childList: true });
  const T = (id, categoria, extra = {}) => ({ id, analisis: 1, categoria, texto: "Texto " + id, minuto: "01:0" + id.slice(-1), t_seg: 61, estado: "confirmada", ...extra });
  S.tarjetas = [T("t1", "decisión")]; AP.hooks.pintarInsights();                   // la tarjeta de Insights a la que llevará «Ver»
  await esp(200);
  // 1) evento real con cinco tarjetas (una repetida no cuenta): sin tope, salen todas, escalonadas. app.js añade `nuevas` a S.tarjetas DESPUÉS del hook
  const nuevas = [T("t1", "decisión", { perfil: "coordinador", responsable: "Ana", fecha: "viernes", sistema: "SAP", referencia: "ver 03-alcance.md línea 4" }),
    T("t2", "pregunta", { perfil: "funcional" }), T("t3", "idea"), T("t5", "riesgo", { perfil: "constructor" }), T("t6", "pendiente"), T("t1", "decisión")];
  AP.hooks.evento({ tipo: "tarjetas", nuevas }); S.tarjetas = nuevas.filter((t, i) => nuevas.findIndex((u) => u.id === t.id) === i);
  await esp(300);
  res.cuentaPendiente = document.getElementById("r-bandeja-btn").textContent;           // pregunta, idea y pendiente no avisan: están en Hallazgos desde el primer momento; decisión y riesgo, en cola o en pantalla
  await esp(4300);
  res.visibles1 = visibles().length;
  res.monos = visibles().map((n) => n.querySelector(".n-nombre").textContent);   // §0: el agente se reconoce por su icono y su nombre en su color, sin iniciales
  res.metaDecision = (visibles()[0].querySelector(".n-meta") || {}).textContent;
  res.acciones = visibles().map((n) => [...n.querySelectorAll(".n-acc button")].map((b) => b.textContent));
  res.sombraClaro = getComputedStyle(visibles()[0]).boxShadow !== "none"; res.radio = getComputedStyle(visibles()[0]).borderRadius;
  { const cs = getComputedStyle(visibles()[0]); res.opaco = [cs.backgroundColor, cs.backdropFilter, getComputedStyle(cont).position];
    const rs = visibles().map((n) => n.getBoundingClientRect()); res.sinSolape = rs.every((r, i) => rs.every((q, j) => i === j || r.bottom <= q.top + 0.5 || q.bottom <= r.top + 0.5)); }
  // 2) `todas` y snapshot no notifican (ni las definiciones del snapshot)
  const antes = res.aparicion.length;
  AP.hooks.evento({ tipo: "tarjetas", todas: [T("t9", "decisión")] });
  const previa = { termino: "Previa", definicion: "algo ya conocido", origen: "analista", t: 10, minuto: "00:10" };
  S.monitor = { definiciones: [previa], feed: [] };
  AP.hooks.evento({ tipo: "snapshot", estado: "grabando", tarjetas: [T("t8", "decisión")], monitor: S.monitor });
  await esp(1000);
  res.sinNuevas = res.aparicion.length === antes;
  // 2b) el evento real `definiciones` notifica solo lo nuevo; la local sustituida por la de la Analista no repite
  const cupo = { termino: "Cupo", definicion: "máximo de habitaciones", origen: "local", t: 70, minuto: "01:10" };
  S.monitor = { definiciones: [cupo, previa], feed: [] };
  AP.hooks.evento({ tipo: "definiciones", definiciones: S.monitor.definiciones });
  await esp(1500);
  const dn = visibles().find((n) => n.querySelector(".n-tx").textContent.startsWith("Cupo"));   // una definición ya NO avisa: queda en Hallazgos y en su pestaña
  res.defNotif = dn ? [dn.querySelector(".n-mono").textContent, dn.querySelector(".n-nombre").textContent, dn.querySelector(".n-cat").textContent, dn.querySelector(".n-tx").textContent, (dn.querySelector(".n-meta") || {}).textContent] : null;
  const cupoA = { termino: "Cupo", definicion: "tope de habitaciones sin pasar por Revenue", origen: "analista", t: 70, minuto: "01:10" };
  S.monitor = { definiciones: [cupoA, previa], feed: [] };
  const antesDef = res.aparicion.length;
  AP.hooks.evento({ tipo: "definiciones", definiciones: S.monitor.definiciones });
  await esp(1500);
  res.defSinRepetir = res.aparicion.length === antesDef;
  // 3) «Pregúntale» rellena, enfoca y deja el cursor al final sin enviar nada; «Ver» usa el camino de la banda y descarta
  const preg = visibles().find((n) => n.querySelector('[data-accion="preguntale"]'));
  preg.querySelector('[data-accion="preguntale"]').click();
  const campo = document.querySelector("#f-pregunta input");
  res.campo = campo.value; res.focoEnCampo = document.activeElement === campo; res.cursorAlFinal = campo.selectionStart === campo.value.length;
  const ver = visibles()[0]; ver.querySelector(".n-acc button").click();
  res.fantasma = !!document.body.querySelector(":scope > .notif");                 // la notificación vuela hacia el botón Hallazgos
  await esp(100);
  res.barra = document.querySelector('#r-insights .tarj[data-id="t1"]').classList.contains("barra");
  // 4) hueco liberado: sale la siguiente tras el colapso; la pausa congela la vida
  await esp(1500);
  res.visibles2 = visibles().length;
  const n1 = visibles()[0]; n1.dispatchEvent(new PointerEvent("pointerover", { bubbles: true }));
  await esp(14000);
  res.siguenPausadas = visibles().length === res.visibles2;
  n1.dispatchEvent(new PointerEvent("pointerout", { bubbles: true, relatedTarget: null }));
  await esp(21000);
  res.tras = visibles().length;
  // 4b) Hallazgos: lo que ya no está en la cola ni en la pila, derivado de los datos; filtros, glifos, Esc y foco
  const bt = document.getElementById("r-bandeja-btn"), pb = document.getElementById("r-bandeja");
  res.bandejaCuenta = bt.textContent;
  bt.click(); await esp(300);
  const filas = () => [...document.querySelectorAll("#r-bandeja-lista .bj-f")];
  res.bandejaFilas = filas().length;
  res.primera = filas()[0].querySelector(".bj-tx").textContent;                       // la definición de la Analista sustituyó a la local, en su sitio y sin duplicar
  res.chips = [...document.querySelectorAll("#r-bandeja-filtros .bj-chip:not([hidden])")].map((c) => c.getAttribute("aria-label"));
  res.glifos = [...new Set(filas().map((f) => f.querySelector("svg.bj-g").getAttribute("class").split(" ").filter((c) => c.startsWith("g-") || c.startsWith("ic-")).join(" ")))].sort();   // el icono: ic-<tipo> + g-<tipo>
  res.etiquetasEnFila = filas().every((f) => f.querySelector(".bj-cat").textContent.length > 3);
  res.abierto = !pb.hidden && bt.getAttribute("aria-expanded") === "true";
  document.querySelector('#r-bandeja-filtros [data-f="definicion"]').click();
  res.filtroDef = filas().length; res.filtroPulsado = document.querySelector('#r-bandeja-filtros [data-f="definicion"]').getAttribute("aria-pressed");
  document.querySelector('#r-bandeja-filtros [data-f="todo"]').click();
  document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
  await esp(400);                                                                      // sale en 160 ms (DESIGN-visual.md §7) y entonces queda oculto
  res.cierraConEsc = pb.hidden && document.activeElement === bt && localStorage.getItem("apuntes_bandeja_abierta") === "0";
  // 5) modo reunión: sin «Pregúntale»; fin de reunión: todo vacío y sin temporizadores ni animaciones
  AP.notificar(T("t20", "riesgo")); await esp(1200);
  document.body.dataset.modo = "reunion";
  res.preguntaEnModo = [...cont.querySelectorAll('[data-accion="preguntale"]')].some((b) => getComputedStyle(b).display !== "none");
  delete document.body.dataset.modo;
  AP.hooks.evento({ tipo: "estado", estado: "revision" });
  await esp(500);
  res.finVacio = cont.querySelectorAll(".notif").length === 0;
  res.bandejaTrasFin = Number(bt.textContent.split(" ")[1]);                          // lo pendiente pasó a Hallazgos; no se vacía
  // doce avisos altos de golpe: como mucho 2 a la vez, apilados sin solaparse, y el resto agrupado en «+10 hallazgos»; al pulsarlo pasan a Hallazgos
  const antesGrupo = Number(bt.textContent.split(" ")[1]);
  for (let i = 0; i < 12; i++) AP.notificar(T("s" + i, "decisión", { texto: "palabra ".repeat(40) }));
  await esp(11300);
  { const mas = cont.querySelector(".notif-mas"), rs = visibles().map((n) => n.getBoundingClientRect());
    res.grupo = { n: visibles().length, mas: mas && !mas.hidden ? mas.textContent : null, sinSolape: rs.every((r, i) => rs.every((q, j) => i === j || r.bottom <= q.top + 0.5 || q.bottom <= r.top + 0.5)) };
    mas.click(); await esp(100);
    res.grupoClic = { mas: mas.hidden, cuentaAntes: antesGrupo, cuentaDespues: Number(bt.textContent.split(" ")[1]) }; }
  AP.hooks.evento({ tipo: "estado", estado: "revision" }); await esp(200);
  AP.notificar(T("t30", "decisión", { texto: "<img src=x onerror=alert(1)> y texto largo ".repeat(12) })); await esp(1000);
  res.sinHtml = !cont.querySelector("img") && cont.querySelector(".n-tx").textContent.length > 300;
  AP.hooks.evento({ tipo: "estado", estado: "revision" }); await esp(100);
  res.temporizadores = vivos.size;   // (las animaciones no avanzan con el tiempo virtual del navegador sin cabeza: solo se comprueban los temporizadores)
  document.getElementById("res").textContent = JSON.stringify(res);
} catch (e) { document.getElementById("res").textContent = "ERROR " + e.stack; } })();
</script></body></html>
"""


def _navegador():
    for ruta in (r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe", r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
                 r"C:\Program Files\Google\Chrome\Application\chrome.exe"):
        if Path(ruta).is_file():
            return ruta
    return shutil.which("msedge") or shutil.which("chrome") or shutil.which("chromium")


def test_cola_escalonada_pausa_y_vaciado(tmp_path):
    exe = _navegador()
    if not exe:
        pytest.skip("No hay Edge ni Chrome para ejecutar la página de prueba.")
    pagina = tmp_path / "notificaciones.html"
    pagina.write_text(HARNESS % {"web": WEB.as_uri()}, encoding="utf-8")
    salida = subprocess.run([exe, "--headless=new", "--disable-gpu", "--no-first-run", f"--user-data-dir={tmp_path / 'perfil'}", "--window-size=1426,900",
                             "--virtual-time-budget=80000", "--dump-dom", pagina.as_uri()], capture_output=True, text=True, timeout=180, encoding="utf-8").stdout
    m = re.search(r'<pre id="res">(.*?)</pre>', salida, re.S)
    assert m and m.group(1).strip().startswith("{"), salida[-500:]
    r = json.loads(m.group(1).replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"'))
    assert r["errores"] == [], r["errores"]
    assert r["cuentaPendiente"] == "Hallazgos 3"                                # pregunta, idea y pendiente no avisan: ya están en Hallazgos; decisión y riesgo, en pantalla
    assert r["visibles1"] == 2                                                 # solo decisión y riesgo avisan (y nunca más de 2 a la vez)
    huecos = [b - a for a, b in zip(r["aparicion"], r["aparicion"][1:])]
    assert all(g >= 880 for g in huecos[:4]), huecos                           # escalonado de 900 ms
    assert r["monos"][:2] == ["Capitán", "Arquitecto"], r["monos"]               # perfil → nombre del agente
    assert r["metaDecision"] == "Responsable: Ana · Fecha: viernes · Sistema: SAP · contra: 03-alcance.md"
    assert r["acciones"][:2] == [["Ver"], ["Ver", "Pregúntale"]]                     # Pregúntale solo en riesgo y contradicción
    assert r["sombraClaro"] and r["radio"] == "8px"   # §0 Estéreo: radio de capa flotante (--r-l, esquinas vivas)
    assert r["opaco"][0].startswith("rgb(") and r["opaco"][1] == "none" and r["opaco"][2] != "fixed", r["opaco"]   # fondo opaco, sin desenfoque y en el flujo (no flotante)
    assert r["sinSolape"], r
    assert r["grupo"]["n"] == 2 and r["grupo"]["mas"] == "+10 hallazgos" and r["grupo"]["sinSolape"], r["grupo"]   # 12 de golpe: 2 visibles y el resto agrupado
    assert r["grupoClic"]["mas"] is True and r["grupoClic"]["cuentaDespues"] >= r["grupoClic"]["cuentaAntes"] + 10, r["grupoClic"]   # al pulsarlo pasan a Hallazgos con su contador
    assert r["sinNuevas"], r                                                    # `todas` y el snapshot (con sus definiciones) no notifican
    assert r["defNotif"] is None, r["defNotif"]                                 # una definición no avisa (solo Hallazgos y el contador de su pestaña)
    assert r["defSinRepetir"], r                                                # la local sustituida por la de la Analista no vuelve a notificar
    assert r["fantasma"]                                                        # al descartar, vuela hacia el botón Hallazgos
    assert r["campo"] == "Sobre «Texto t5»: " and r["focoEnCampo"] and r["cursorAlFinal"]
    assert r["barra"]                                                           # «Ver» recorre el camino de la banda Sesión hasta la tarjeta
    assert r["siguenPausadas"]                                                  # con el puntero encima, la vida se detiene
    assert r["tras"] == 0, r
    assert r["bandejaCuenta"] == "Hallazgos 7", r["bandejaCuenta"]                  # cinco tarjetas y dos definiciones, todo lo que ya salió de la pila
    assert r["bandejaFilas"] == 7 and r["abierto"] and r["primera"] == "Cupo: tope de habitaciones sin pasar por Revenue", r
    assert r["chips"] == ["Todo: 7", "Decisiones: 1", "Preguntas: 1", "Pendientes: 1", "Riesgos: 1", "Definiciones: 2", "Ideas: 1"], r["chips"]   # sin Reglas, Contradicciones ni Objetivos (contador 0)
    assert r["glifos"] == ["ic-decision g-decision", "ic-definicion g-definicion", "ic-idea g-idea", "ic-pendiente g-pendiente", "ic-pregunta g-pregunta", "ic-riesgo g-riesgo"], r["glifos"]   # un icono SVG por tipo
    assert r["etiquetasEnFila"] and r["filtroDef"] == 2 and r["filtroPulsado"] == "true" and r["cierraConEsc"], r
    assert r["bandejaTrasFin"] >= 8, r                                          # lo pendiente de la pila pasa a Hallazgos al terminar
    assert r["preguntaEnModo"] is False                                         # nunca «Pregúntale» en Modo reunión
    assert r["finVacio"] and r["sinHtml"]
    assert r["temporizadores"] == 0, r                                           # con todo vacío, ningún setTimeout vivo
