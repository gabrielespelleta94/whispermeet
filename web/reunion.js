"use strict";
/* Apuntes: pantalla de reunión (transcripción compacta, objetivos, insights por traza). Sustituye por hooks a las funciones
   equivalentes de app.js. Entrada silenciosa: nada se mueve si la columna está desplazada; aparece «N nuevos ↑». */
(() => {
  const AP = window.AP;
  if (!AP) return;
  const { S, UI, h, $, $$, mmss, kfmt } = AP;
  const SVGNS = "http://www.w3.org/2000/svg";
  const sv = (tag, attrs = {}, ...hijos) => { const e = document.createElementNS(SVGNS, tag); for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v); hijos.forEach((c) => c && e.append(c)); return e; };
  const reducido = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const SALIDA = "cubic-bezier(.16,1,.3,1)";
  const aSeg = (m) => { const p = String(m || "").split(":").map(Number); return p.length === 2 && p.every((x) => !Number.isNaN(x)) ? p[0] * 60 + p[1] : null; };

  // Reconciliación con clave: solo se mueven los nodos que no están en su sitio (el resto conserva el ancla de scroll)
  function reconciliar(cont, nodos) {
    let ref = cont.firstChild;
    for (const n of nodos) {
      if (n === ref) ref = ref.nextSibling;
      else cont.insertBefore(n, ref);
    }
    while (ref) { const sig = ref.nextSibling; ref.remove(); ref = sig; }
  }

  // ------------------------------------------------------------ transcripción
  const T = { lineas: new Map(), sep: null, hastaId: null, tramo: null };
  function lineaTrans(s, previa) {
    const el = h("div", { class: "lin " + s.fuente + (previa && previa.fuente !== s.fuente ? " cambia" : ""), "data-t": s.t, "data-id": s.id },
      h("div", { class: "lin-m t-meta" }, h("span", { class: "t" }, s.mmss), h("span", { class: "q" }, s.fuente === "yo" ? "Micro" : "Reunión")),
      h("div", { class: "x t-body" }, s.texto));
    T.lineas.set(s.id, el);
    return el;
  }
  AP.hooks.pintarTrans = () => {
    const c = $("#r-trans");
    T.lineas.clear(); T.sep = null;
    const nodos = [];
    if (!S.segmentos.length) nodos.push(h("div", { class: "trans-vacio t-body" }, "Esperando a que alguien hable…"));
    S.segmentos.forEach((s, i) => nodos.push(lineaTrans(s, S.segmentos[i - 1])));
    c.replaceChildren(...nodos);
    colocarSeparador(false);
    $("#r-trans-n").textContent = "";
    if (UI.seguir) c.scrollTop = c.scrollHeight;
  };
  AP.hooks.anadirSegmento = (s) => {
    const c = $("#r-trans");
    if (!S.segmentos.some((x) => x.id === s.id)) S.segmentos.push(s);
    if (T.lineas.has(s.id)) return;
    const vacio = $(".trans-vacio", c); if (vacio) vacio.remove();
    const previa = S.segmentos[S.segmentos.length - 2];
    const el = lineaTrans(s, previa && previa.id !== s.id ? previa : null);
    if (UI.seguir && !reducido()) el.classList.add("nueva");
    c.append(el);
    if (UI.seguir) c.scrollTop = c.scrollHeight; else $("#r-alfinal").hidden = false;
  };

  // «Analizado hasta 30:00»: separador con filete que se mueve tras cada análisis (nunca atenúa lo ya leído)
  function colocarSeparador(animar) {
    const ult = [...AP.traza].reverse().find((x) => x.fila === "analisis" && x.hasta_id);
    const c = $("#r-trans");
    if (!ult) { if (T.sep) { T.sep.remove(); T.sep = null; } return; }
    const destino = T.lineas.get(ult.hasta_id);
    if (!destino) return;
    const etiqueta = "Analizado hasta " + mmss(ult.hasta_t != null ? ult.hasta_t : 0);
    const antes = T.sep && T.sep.isConnected ? T.sep.getBoundingClientRect().top : null;
    if (!T.sep) T.sep = h("div", { class: "sep-analizado", role: "separator" }, h("span", { class: "t-label" }));
    T.sep.firstChild.textContent = etiqueta;
    if (destino.nextSibling !== T.sep) destino.after(T.sep);
    if (animar && antes != null && !reducido()) {
      const dy = antes - T.sep.getBoundingClientRect().top;
      if (Math.abs(dy) > 1) T.sep.animate([{ transform: `translateY(${dy}px)` }, { transform: "none" }], { duration: 260, easing: SALIDA });
    }
  }

  // ------------------------------------------------------------ chips de minuto → línea destino
  let destinoAnim = null;
  function lineaDeSeg(seg) {
    const lineas = $$("#r-trans .lin");
    let dest = null;
    for (const l of lineas) { if (Number(l.dataset.t) <= seg + 1) dest = l; else break; }
    return dest || lineas[0] || null;
  }
  function animarScroll(c, hasta) {
    const desde = c.scrollTop, d = hasta - desde;
    if (reducido() || Math.abs(d) < 2) { c.scrollTop = hasta; return; }
    const t0 = performance.now();
    const f = (t) => { const p = Math.min(1, (t - t0) / 260); c.scrollTop = desde + d * (1 - Math.pow(1 - p, 4)); if (p < 1) requestAnimationFrame(f); };
    requestAnimationFrame(f);
  }
  AP.hooks.irAlMinuto = (seg) => {
    if (seg == null) return;
    const dest = lineaDeSeg(seg), c = $("#r-trans");
    if (!dest) return;
    UI.seguir = false;
    const objetivo = dest.offsetTop - c.clientHeight * 0.3;
    animarScroll(c, Math.max(0, Math.min(objetivo, c.scrollHeight - c.clientHeight)));
    $$("#r-trans .lin.destino, #r-trans .lin.disipa").forEach((x) => x.classList.remove("destino", "disipa"));
    dest.classList.add("destino");
    clearTimeout(destinoAnim);
    destinoAnim = setTimeout(() => { dest.classList.add("disipa"); setTimeout(() => dest.classList.remove("destino", "disipa"), 400); }, 1600);
    $("#r-alfinal").hidden = false;
  };
  const irA = (seg) => AP.hooks.irAlMinuto(seg);
  // Hover o foco en un chip: barra en la línea destino SIN desplazar
  function sobreChip(ev, on) {
    const chip = ev.target.closest && ev.target.closest(".min[data-t]");
    if (!chip) return;
    const dest = lineaDeSeg(Number(chip.dataset.t));
    if (dest) dest.classList.toggle("previa", on);
  }
  document.addEventListener("mouseover", (e) => sobreChip(e, true));
  document.addEventListener("mouseout", (e) => sobreChip(e, false));
  document.addEventListener("focusin", (e) => sobreChip(e, true));
  document.addEventListener("focusout", (e) => sobreChip(e, false));
  AP.resaltarLinea = (seg, on) => { const d = lineaDeSeg(seg); if (d) d.classList.toggle("previa", !!on); };
  const chipMin = (minuto, t) => (minuto ? h("button", { type: "button", class: "min t-meta", "data-t": t == null ? null : t, title: "Ir a ese momento de la transcripción", onclick: () => irA(t) }, minuto) : null);

  // ------------------------------------------------------------ «N nuevos ↑»
  const NUEVOS = { ins: { n: 0, btn: "#r-ins-nuevos", scroll: "#r-plan-scroll", palabra: ["nuevo", "nuevos"], destino: "#r-ins-h" },
    plan: { n: 0, btn: "#r-plan-nuevos", scroll: "#r-obj-scroll", palabra: ["cambio", "cambios"], destino: null } };
  // Cada pestaña de la columna derecha tiene su scroll (insights, objetivos y checks); en el Modo reunión, el del panel derecho entero
  const scrollDe = (x) => $(x.scroll);   // cada pestaña tiene su scroll, también en Modo reunión
  const topeDe = (x) => { const d = x.destino && $(x.destino), sc = scrollDe(x); return d && sc ? Math.max(0, d.getBoundingClientRect().top - sc.getBoundingClientRect().top + sc.scrollTop - 8) : 0; };
  function marcarNuevos(k, n) {
    const x = NUEVOS[k], sc = scrollDe(x);
    if (!n || !sc || sc.scrollTop < 2) { return; }
    x.n += n;
    const b = $(x.btn);
    b.hidden = false; b.textContent = `${x.n} ${x.palabra[x.n === 1 ? 0 : 1]} ↑`;
  }
  Object.keys(NUEVOS).forEach((k) => {
    const x = NUEVOS[k];
    const alTope = () => { x.n = 0; $(x.btn).hidden = true; };
    const llegado = () => { const sc = scrollDe(x); return !sc || sc.scrollTop < 2 || (x.destino && Math.abs(sc.scrollTop - topeDe(x)) < 3); };
    document.addEventListener("DOMContentLoaded", () => {}, { once: true });
    const arrancar = () => {
      const sc = $(x.scroll); if (sc) sc.addEventListener("scroll", () => { if (llegado()) alTope(); }, { passive: true });
      $(".col-der").addEventListener("scroll", () => { if (document.body.dataset.modo === "reunion" && llegado()) alTope(); }, { passive: true });
      $(x.btn).addEventListener("click", () => { animarScroll(scrollDe(x), topeDe(x)); alTope(); });
    };
    if (document.readyState !== "loading") arrancar(); else document.addEventListener("DOMContentLoaded", arrancar);
  });

// Iconos por tipo (iconos.js): decisión, pendiente, pregunta, riesgo, contradicción, regla, idea, definición y objetivo. Icono + color + etiqueta: nunca solo color.
const glifo = (tipo, posible) => AP.icono(posible ? "contradiccion" : tipo, "bj-g g-" + tipo + (posible ? " posible" : ""));

  // ------------------------------------------------------------ insights, agrupados por análisis
  const CATS = { "idea": ["Idea", "idea"], "decisión": ["Decisión", "decision"], "pendiente": ["Pendiente", "pendiente"], "contradicción": ["Contradicción", "contradiccion"],
    "pregunta": ["Pregunta", "pregunta"], "riesgo": ["Riesgo", "riesgo"], "regla": ["Regla", "regla"], "definición": ["Definición", "definicion"] };
  const NOMBRE_PERFIL = { coordinador: "Coordinador", funcional: "Analista funcional", constructor: "Constructor", revisor: "Revisor", estratega: "Estratega" };
  // Filtro propio de las ideas (aria-pressed), recordado
  let verIdeas = true;
  try { verIdeas = localStorage.getItem("apuntes_ver_ideas") !== "0"; } catch { /* sin almacenamiento */ }
  const I = { grupos: new Map(), tarjetas: new Map(), vistas: new Set(), primera: true };

  const motivoFallo = (e) => ({ limite: "límite del plan", sesion: "sesión no iniciada", tiempo: "sin respuesta del modelo", salida: "respuesta no interpretable" }[e.clase] || String(e.mensaje || "error").slice(0, 80));

  function filaTraza(e, n) {
    const clave = e ? e.id : "a" + n;
    let el = I.grupos.get(clave);
    if (!el) { el = h("div", { class: "traza-f t-meta", "data-clave": clave }); I.grupos.set(clave, el); }
    if (!e) { // análisis sin entrada de traza todavía: solo el número
      el.className = "traza-f t-meta"; el.replaceChildren(h("span", {}, `Análisis ${n}`)); return el;
    }
    el.className = "traza-f t-meta " + e.fila;
    if (e.fila === "analisis") {
      const partes = [e.perfil ? `Turno ${e.n}` : `Análisis ${e.n}`, e.perfil ? NOMBRE_PERFIL[e.perfil] || e.perfil : null, e.tramo, e.motivo || null, e.modelo, e.ms != null ? AP.seg(e.ms) : null, e.tokens != null ? kfmt(e.tokens) : null, ...AP.conteos(e)].filter(Boolean);
      const b = h("button", { type: "button", class: "traza-b t-meta", "aria-pressed": "false", title: "Resaltar las líneas de este tramo",
        onclick: () => resaltarTramo(e, b) }, partes.join(" · "));
      el.replaceChildren(b);
    } else if (e.fila === "omitido") {
      el.replaceChildren(h("span", {}, `${mmss(e.t)} · Omitido · ${e.palabras} palabras nuevas (mín. ${e.minimo})`));
    } else {
      el.replaceChildren(h("span", {}, `${mmss(e.t)} · Fallo · ${motivoFallo(e)}`),
        h("button", { type: "button", class: "btn btn-ghost btn-mini", onclick: () => AP.api("POST", "/api/sesion/analizar").catch(AP.alerta) }, "Reintentar"));
    }
    return el;
  }
  function resaltarTramo(e, b) {
    const ya = b.getAttribute("aria-pressed") === "true";
    $$(".traza-b[aria-pressed=true]").forEach((x) => x.setAttribute("aria-pressed", "false"));
    $$("#r-trans .lin.tramo").forEach((x) => x.classList.remove("tramo"));
    if (ya || !e.tramo) return;
    const [d, hasta] = e.tramo.split("–").map(aSeg);
    b.setAttribute("aria-pressed", "true");
    $$("#r-trans .lin").forEach((l) => { const t = Number(l.dataset.t); if (t >= d - 0.5 && t <= hasta + 0.5) l.classList.add("tramo"); });
  }

  function tarjetaEl(t) {
    let el = I.tarjetas.get(t.id);
    const [nombre, clase] = CATS[t.categoria] || [t.categoria, "pregunta"];
    const posible = t.estado === "posible";
    const etiqueta = posible ? "Posible contradicción" : nombre;
    const cls = "tarj " + clase + (posible ? " posible" : "");
    if (!el) {
      el = h("article", { class: cls, "data-id": t.id });
      const tx = h("div", { class: "tx t-body" });
      const mas = h("button", { type: "button", class: "mas t-meta", hidden: true, "aria-expanded": "false", onclick: () => { const a = el.classList.toggle("abierta"); mas.setAttribute("aria-expanded", String(a)); mas.textContent = a ? "Menos" : "Más"; } }, "Más");
      el._p = { tx, mas, cab: h("div", { class: "tarj-c" }), meta: h("div", { class: "tarj-meta t-meta" }) };
      el.append(el._p.cab, tx, mas, el._p.meta);
      I.tarjetas.set(t.id, el);
    }
    el.className = cls + (el.classList.contains("abierta") ? " abierta" : "") + (el.classList.contains("nueva") ? " nueva" : "") + (el.classList.contains("barra") ? " barra" : "");
    const p = el._p;
    p.cab.replaceChildren(h("span", { class: "t-label cat" }, glifo(clase, posible), etiqueta), chipMin(t.minuto, t.t_seg));
    if (p.tx.textContent !== t.texto) p.tx.textContent = t.texto;
    const meta = [];
    if (t.responsable) meta.push(h("span", {}, "Responsable: " + t.responsable));
    if (t.fecha) meta.push(h("span", {}, "Fecha: " + t.fecha));
    if (t.sistema) meta.push(h("span", {}, "Sistema: " + t.sistema));
    if (t.perfil) meta.push(h("span", { class: "perfil" }, NOMBRE_PERFIL[t.perfil] || t.perfil));
    if (t.referencia) { const f = String(t.referencia).match(/[\w.\-]+\.md/); meta.push(h("span", { class: "contra" }, "contra: " + (f ? f[0] : "«" + String(t.referencia).slice(0, 90) + "»"))); }
    if (t.nota) meta.push(h("span", {}, t.nota));
    p.meta.replaceChildren(...meta);
    p.meta.hidden = !meta.length;
    el.title = posible ? "Se confirmará al terminar la reunión" : "";
    return el;
  }

  AP.hooks.pintarInsights = () => {
    const c = $("#r-insights"), sc = scrollDe(NUEVOS.ins);
    const traza = AP.traza || [];
    const porAnalisis = new Map();
    S.tarjetas.forEach((t) => { if (!verIdeas && t.categoria === "idea") return; const n = t.analisis || 0; (porAnalisis.get(n) || porAnalisis.set(n, []).get(n)).push(t); });
    const nodos = [];
    const usadas = new Set();
    const nuevas = [];
    const crono = traza.map((e) => ({ e, n: e.fila === "analisis" ? e.n : null }));
    // análisis con tarjetas pero sin entrada de traza (aún no llegó): fila mínima
    for (const n of [...porAnalisis.keys()].sort((a, b) => a - b)) if (!crono.some((x) => x.n === n)) crono.push({ e: null, n });
    for (const { e, n } of crono.reverse()) {
      nodos.push(filaTraza(e, n));
      for (const t of (n != null ? porAnalisis.get(n) || [] : [])) {
        const el = tarjetaEl(t); usadas.add(t.id);
        if (!I.vistas.has(t.id)) { I.vistas.add(t.id); nuevas.push(el); }
        nodos.push(el);
      }
    }
    for (const [n, ts] of porAnalisis) if (n === 0) ts.forEach((t) => { nodos.push(tarjetaEl(t)); usadas.add(t.id); if (!I.vistas.has(t.id)) { I.vistas.add(t.id); nuevas.push(I.tarjetas.get(t.id)); } });
    if (!nodos.length) nodos.push(h("div", { class: "vacio-i t-body" }, "Todavía no hay insights. Aparecerán tras el primer análisis."));
    for (const k of [...I.tarjetas.keys()]) if (!usadas.has(k)) I.tarjetas.delete(k);
    const desplazada = sc.scrollTop > 1;
    reconciliar(c, nodos);
    // «Más» solo si el texto pasa de 3 líneas
    nodos.forEach((el) => { if (el._p) { const tx = el._p.tx; el._p.mas.hidden = !(el.classList.contains("abierta") || tx.scrollHeight > tx.clientHeight + 1); } });
    const visibles = S.tarjetas.filter((t) => verIdeas || t.categoria !== "idea").length;
    $("#r-ins-n").textContent = S.tarjetas.length ? (visibles === S.tarjetas.length ? String(S.tarjetas.length) : `${visibles} de ${S.tarjetas.length}`) : "";
    if (nuevas.length && !I.primera) {
      if (desplazada) marcarNuevos("ins", nuevas.length);
      else if (!reducido()) nuevas.forEach((el, i) => {
        el.classList.add("barra");
        el.animate([{ opacity: 0, transform: "translateY(6px)" }, { opacity: 1, transform: "none" }], { duration: 180, delay: i * 35, easing: SALIDA, fill: "backwards" });
        setTimeout(() => { el.classList.add("barra-fuera"); setTimeout(() => el.classList.remove("barra", "barra-fuera"), 400); }, 8000);
      });
    }
    I.primera = false;
    const det = $("#r-resumen-det");
    det.hidden = !S.resumen_acumulado;
    $("#r-resumen").textContent = S.resumen_acumulado || "";
  };

  // ------------------------------------------------------------ objetivos (nunca se reordenan)
  const O_ = { filas: new Map(), previo: new Map() };
  const ESTADO_OBJ = { sin_tratar: "Sin tratar", parcial: "Parcial", cubierto: "Cubierto" };
  AP.hooks.pintarObjetivos = () => {
    const os = S.objetivos || [];
    $("#r-objetivos").hidden = !os.length;
    if (!os.length) { O_.filas.clear(); O_.previo.clear(); return; }
    $("#r-obj-cuenta").textContent = `${os.filter((o) => o.estado === "cubierto").length}/${os.length} cubiertos`;
    const sc = scrollDe(NUEVOS.plan);
    const cambiados = [];
    const nodos = os.map((o) => {
      let el = O_.filas.get(o.n);
      if (!el) {
        el = h("div", { class: "obj", "data-n": o.n },
          h("span", { class: "obj-ind" }, sv("svg", { viewBox: "0 0 10 10", "aria-hidden": "true" }, sv("circle", { cx: 5, cy: 5, r: 4.25, class: "aro" }), sv("path", { d: "M5 .75a4.25 4.25 0 0 0 0 8.5Z", class: "mitad" }),
            sv("path", { d: "M2.9 5.2l1.5 1.5 2.9-3", class: "tic", pathLength: "100" }))),
          h("span", { class: "obj-tx t-body-m" }), h("span", { class: "obj-chip" }));
        O_.filas.set(o.n, el);
      }
      const antes = O_.previo.get(o.n);
      el.className = "obj " + o.estado;
      el.setAttribute("aria-label", `${o.texto}: ${ESTADO_OBJ[o.estado] || o.estado}`);
      const tx = el.querySelector(".obj-tx"); if (tx.textContent !== o.texto) { tx.textContent = o.texto; tx.title = o.texto; }
      const chip = el.querySelector(".obj-chip");
      if (chip.dataset.m !== (o.minuto || "")) { chip.dataset.m = o.minuto || ""; chip.replaceChildren(...(o.minuto ? [chipMin(o.minuto, o.t_seg)] : [])); }
      if (antes !== undefined && antes !== o.estado) cambiados.push(el);
      O_.previo.set(o.n, o.estado);
      return el;
    });
    reconciliar($("#r-obj-lista"), nodos);
    if (cambiados.length) {
      if (!reducido()) cambiados.forEach((el) => el.querySelector(".obj-ind").animate([{ transform: "scale(.8)" }, { transform: "none" }], { duration: 180, easing: SALIDA }));
      if (sc.scrollTop > 1) marcarNuevos("plan", cambiados.length);
    }
    if (cambiados.length) AP.cambioObjetivos = cambiados.length;
  };

  // ------------------------------------------------------------ enlaces visuales con las columnas y reinicio
  let autosPrevios = new Set();
  const previoReinicio = AP.hooks.reiniciar;
  AP.hooks.reiniciar = () => {
    if (previoReinicio) previoReinicio();
    T.lineas.clear(); T.sep = null; I.grupos.clear(); I.tarjetas.clear(); I.vistas.clear(); I.primera = true;
    O_.filas.clear(); O_.previo.clear(); autosPrevios = new Set();
    $("#r-insights").replaceChildren(); $("#r-obj-lista").replaceChildren();
    Object.values(NUEVOS).forEach((x) => { x.n = 0; $(x.btn).hidden = true; });
  };
  const previoEvento = AP.hooks.evento;
  AP.hooks.evento = (d) => {
    if (previoEvento) previoEvento(d);
    if (d.tipo === "traza") {
      if (d.hasta_id != null) requestAnimationFrame(() => colocarSeparador(true));
      requestAnimationFrame(() => AP.hooks.pintarInsights());
    }
    if (d.tipo === "snapshot") requestAnimationFrame(() => { colocarSeparador(false); AP.hooks.pintarInsights(); I.primera = false; });
    if (d.tipo === "tarjetas") {
      const nuevasT = (d.nuevas || []).length;
      const autos = new Set((d.checks || []).filter((c) => c.auto).map((c) => c.id));
      const nuevosAuto = [...autos].filter((id) => !autosPrevios.has(id)).length;
      if (d.checks) {
        if (autosPrevios.size || nuevosAuto) marcarNuevos("plan", nuevosAuto);
        autosPrevios = autos;
      }
      requestAnimationFrame(() => {
        if (nuevasT) { AP.enlazar("#r-ins-h"); AP.pulsoCabecera && AP.pulsoCabecera("#r-ins-h"); }
        if (AP.cambioObjetivos) { AP.enlazar("#r-obj-t"); AP.pulsoCabecera && AP.pulsoCabecera("#r-obj-t"); AP.cambioObjetivos = 0; }
        if (nuevosAuto) AP.enlazar("#r-checks-det summary");
      });
    }
  };
  const btnIdeas = $("#r-ideas");
  if (btnIdeas) {
    btnIdeas.setAttribute("aria-pressed", String(verIdeas));
    btnIdeas.addEventListener("click", () => {
      verIdeas = !verIdeas;
      btnIdeas.setAttribute("aria-pressed", String(verIdeas));
      try { localStorage.setItem("apuntes_ver_ideas", verIdeas ? "1" : "0"); } catch { /* sin almacenamiento */ }
      AP.hooks.pintarInsights();
    });
  }
  // ------------------------------------------------------------ notificaciones flotantes y Bandeja (capa sobre Insights; DESIGN-equipo.md §5)
  /* Avisos escalonados de lo importante que sale de la reunión. Entran SOLO lo nuevo de un evento real (tarjetas de `nuevas`, definiciones
     de `definiciones`, el aviso «objetivo sin tratar» del Monitor local); nunca `todas`, ni el snapshot de reconexión. Un Set de claves evita
     repetir. Una cola FIFO suelta una cada 900 ms (solo escalona: no hay tope de visibles; si la pila no cabe, `#r-notifs` hace scroll
     propio); las nuevas se añaden DEBAJO de las que se leen. La vida se pausa mientras el puntero o el foco estén sobre la pila. Sin
     setInterval: un setTimeout de cola y uno por notificación, y con todo vacío no queda ningún temporizador ni animación. Todo el texto va
     por h()/textContent (la transcripción es dato no fiable). «Ver» reutiliza el camino de los marcadores de la banda Sesión; «Pregúntale»
     solo rellena el campo: nunca lanza la pregunta.
     Hallazgos (id r-bandeja; antes «Bandeja»): panel con TODO lo que ya no está en la cola ni en la pila. No guarda nada propio: se deriva de los datos reales
     (S.tarjetas, S.monitor.definiciones y los avisos del feed del Monitor), así que sobrevive a una reconexión. */
  (() => {
    const cont = $("#r-notifs");
    if (!cont) return;
    const panel = $("#r-bandeja"), btn = $("#r-bandeja-btn");
    const ENTRADA = "cubic-bezier(.4,0,1,1)";
    const CADA = 900;
    const MONO = { coordinador: "CO", funcional: "AF", constructor: "CT", revisor: "RV", estratega: "ES" };
    const VIDA_LARGA = new Set(["decisión", "contradicción", "riesgo"]);
    const EMERGE = new Set(["decision", "contradiccion", "riesgo"]);   // solo estos tipos merecen un aviso emergente; el resto, contador y resaltado en su pestaña, y la fila en Hallazgos
    const MAX_VISIBLES = 2, CADUCA_COLA = 30000;                       // como mucho 2 avisos a la vez; lo que espera más de 30 s ya no es «ahora»: se queda en Hallazgos
    const N = { cola: [], pila: [], vistas: new Set(), manuales: new Map(), defs: [], timerCola: null, ultima: -1e9, puntero: false, foco: false, pausada: false, n: 0 };
    const enCurso = () => S.estado === "grabando" || S.estado === "pausada";
    const mayus = (t) => (t ? t[0].toUpperCase() + t.slice(1) : t);
    const norm = (x) => String(x || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase().trim();

    // ---- datos de cada notificación / fila de la Bandeja
    const admite = (t) => !!t && !!t.texto && (verIdeas || t.categoria !== "idea");
    function datosTarjeta(t) {
      const posible = t.estado === "posible";
      const [nombre, clase] = CATS[t.categoria] || [t.categoria, "pregunta"];
      const partes = [];
      if (t.responsable) partes.push("Responsable: " + t.responsable);
      if (t.fecha) partes.push("Fecha: " + t.fecha);
      if (t.sistema) partes.push("Sistema: " + t.sistema);
      if (t.referencia) { const f = String(t.referencia).match(/[\w.\-]+\.md/); partes.push("contra: " + (f ? f[0] : "«" + t.referencia + "»")); }
      const id = t.id != null ? t.id : "x" + (++N.n);
      return { clave: "t:" + id, k: posible ? "posible" : clase, tipo: clase, mono: MONO[t.perfil] || "AN", nombre: NOMBRE_PERFIL[t.perfil] || "Analista",
        cat: posible ? "Posible contradicción" : nombre, texto: t.texto, minuto: t.minuto, t: t.t_seg, meta: partes.join(" · "),
        bmeta: [t.perfil ? NOMBRE_PERFIL[t.perfil] || t.perfil : null, ...partes].filter(Boolean).join(" · "),
        ref: { t: t.t_seg, tarjeta: t.id }, preguntar: ["pregunta", "contradicción", "riesgo"].includes(t.categoria), vida: VIDA_LARGA.has(t.categoria) ? 20000 : 12000 };
    }
    // Definición del panel del equipo: {termino, definicion, origen: "local"|"analista", t, minuto}
    function datosDef(x) {
      const local = x.origen === "local";
      return { clave: "d:" + norm(x.termino), k: "definicion", tipo: "definicion", mono: local ? "MO" : "AF", nombre: local ? "Monitor · local" : "Analista funcional", cat: "Definición",
        texto: `${x.termino}: ${x.definicion}`, minuto: x.minuto, t: x.t, meta: local ? "detección local" : "", bmeta: local ? "detección local" : "Analista funcional",
        ref: { t: x.t }, preguntar: false, vida: 12000 };
    }
    // Aviso local del Monitor (monitor.py: {tipo:"sin_tratar", texto:"objetivo N sin tratar desde hace M min", objetivo:N, minuto, t})
    const datosMonitor = (e) => ({ clave: "m:" + e.id, k: "objetivo", tipo: "objetivo", mono: "MO", nombre: "Monitor · local", cat: "Objetivo sin tratar", texto: mayus(e.texto),
      minuto: e.minuto, t: e.t, meta: "", bmeta: "detección local", ref: { objetivo: e.objetivo }, preguntar: false, vida: 12000 });

    // «Ver»: el mismo camino que un marcador de la banda Sesión (su clic llama a ir(): línea de la transcripción, tarjeta y barra de 1,6 s)
    function irARef(ref) {
      const banda = AP.sesionBanda && AP.sesionBanda.raiz;
      if (!banda) { if (ref.t != null) irA(ref.t); return; }
      const m = h("button", { type: "button", class: "sb-m", hidden: true });
      m._items = [{ ref }];
      banda.append(m); m.click(); m.remove();
    }
    // «Pregúntale»: rellena el campo, lo enfoca y deja el cursor al final. Jamás lo envía: ninguna llamada sin que el usuario la lance.
    function preguntar(texto) {
      const f = $('#f-pregunta input[name="pregunta"]');
      if (!f || document.body.dataset.modo === "reunion") return;
      const det = $("#r-pregunta"); if (det) det.open = true;
      f.value = `Sobre «${texto}»: `;
      f.focus(); f.setSelectionRange(f.value.length, f.value.length);
    }

    function construir(n) {
      const d = n.d;
      const acc = [h("button", { type: "button", class: "btn btn-ghost btn-mini", onclick: () => { irARef(d.ref); descartar(n); } }, "Ver")];
      if (d.preguntar && document.body.dataset.modo !== "reunion") acc.push(h("button", { type: "button", class: "btn btn-ghost btn-mini", "data-accion": "preguntale", onclick: () => preguntar(d.texto) }, "Pregúntale"));
      return h("article", { class: "notif", "data-k": d.k },
        h("span", { class: "n-ico", "aria-hidden": "true" }, glifo(d.tipo, d.k === "posible")),
        h("div", { class: "n-cuerpo" },
          h("div", { class: "n-l1" }, h("span", { class: "n-cat t-label" }, h("span", {}, d.cat)), h("span", { class: "n-mono t-label", "aria-hidden": "true" }, d.mono), h("span", { class: "n-nombre t-meta" }, d.nombre),
            h("span", { class: "n-der" }, chipMin(d.minuto, d.t), h("button", { type: "button", class: "n-x", "aria-label": "Descartar", title: "Descartar", onclick: () => descartar(n) }, AP.icono("cerrar")))),
          h("div", { class: "n-tx t-body" }, d.texto),
          d.meta ? h("div", { class: "n-meta t-meta" }, d.meta) : null,
          h("div", { class: "n-acc" }, ...acc)));
    }

    // vida: se pausa con el puntero o el foco sobre la pila y al salir se reanuda con lo que quedaba
    function vida(n) { n.inicio = performance.now(); n.timer = setTimeout(() => descartar(n), Math.max(0, n.restante)); }
    function pausar(on) {
      if (on === N.pausada) return;
      N.pausada = on;
      const ahora = performance.now();
      for (const n of N.pila) {
        if (on) { clearTimeout(n.timer); n.timer = null; n.restante -= ahora - n.inicio; }
        else vida(n);
      }
    }
    const evaluarPausa = () => pausar(N.puntero || N.foco);
    cont.addEventListener("pointerover", (e) => { if (e.target.closest(".notif")) { N.puntero = true; evaluarPausa(); } });
    cont.addEventListener("pointerout", (e) => { if (!(e.relatedTarget && e.relatedTarget.closest && e.relatedTarget.closest(".notif") && cont.contains(e.relatedTarget))) { N.puntero = false; evaluarPausa(); } });
    cont.addEventListener("focusin", () => { N.foco = true; evaluarPausa(); });
    cont.addEventListener("focusout", (e) => { N.foco = !!(e.relatedTarget && cont.contains(e.relatedTarget)); evaluarPausa(); });

    // Sale deslizándose hacia el botón Bandeja (o hacia el borde del panel si está abierto): un duplicado fijo vuela, porque #r-notifs recorta
    function volar(el, r) {
      const abierto = panel && !panel.hidden, destino = (abierto ? panel : btn);
      const rd = destino && destino.getBoundingClientRect();
      const ghost = el.cloneNode(true);
      ghost.setAttribute("aria-hidden", "true");
      ghost.querySelectorAll("button").forEach((b) => { b.tabIndex = -1; });
      Object.assign(ghost.style, { position: "fixed", left: r.left + "px", top: r.top + "px", width: r.width + "px", margin: "0", zIndex: "31", pointerEvents: "none" });
      document.body.append(ghost);
      const ex = r.left + r.width / 2, ey = r.top + r.height / 2;
      const dx = rd && rd.width ? (abierto ? rd.left - ex : rd.left + rd.width / 2 - ex) : 16, dy = rd && rd.width && !abierto ? rd.top + rd.height / 2 - ey : 0;
      ghost.style.willChange = "transform, opacity"; ghost.style.backdropFilter = ghost.style.webkitBackdropFilter = "none"; ghost.style.background = "var(--elev-solido)";   // opaco: el duplicado que vuela tampoco deja ver lo de debajo
      const a = ghost.animate([{ opacity: 1, transform: "none" }, { opacity: 0, transform: `translate(${dx}px, ${dy}px) scale(.6)` }], { duration: 320, easing: ENTRADA, fill: "forwards" });
      a.onfinish = () => {   // el botón Hallazgos recibe con un pulso (el contador ya cambió en seco)
        ghost.remove();
        if (btn && !reducido()) { btn.classList.remove("recibe"); void btn.offsetWidth; btn.classList.add("recibe"); }
      };
    }
    function descartar(n) {
      const i = N.pila.indexOf(n);
      if (i < 0) return;
      N.pila.splice(i, 1);
      clearTimeout(n.timer); n.timer = null;
      const el = n.el;
      el.classList.add("saliendo");
      if (reducido()) el.remove();
      else {
        const r = el.getBoundingClientRect();
        volar(el, r);
        el.style.visibility = "hidden"; el.style.pointerEvents = "none"; el.style.overflow = "hidden";
        const cs = getComputedStyle(el);
        const a = el.animate([{ height: r.height + "px", marginBottom: "0px", paddingTop: cs.paddingTop, paddingBottom: cs.paddingBottom, borderTopWidth: "1px", borderBottomWidth: "1px" },
          { height: "0px", marginBottom: "-8px", paddingTop: "0px", paddingBottom: "0px", borderTopWidth: "0px", borderBottomWidth: "0px" }], { duration: 240, easing: SALIDA, fill: "forwards" });
        a.onfinish = () => el.remove();
      }
      // lo que estaba bajo el puntero o con el foco se va: se recalcula la pausa (el puntero la reactivará al entrar en otra)
      N.puntero = false;
      N.foco = !!(document.activeElement && cont.contains(document.activeElement) && document.activeElement.closest(".notif:not(.saliendo)"));
      evaluarPausa();
      programarCola();
      renderBandeja();
    }

    // cola: un único setTimeout; sale una cada 900 ms y SOLO si hay sitio (como mucho MAX_VISIBLES a la vez); lo demás espera y se agrupa en «+N hallazgos»
    const mas = h("button", { type: "button", class: "btn btn-mini notif-mas", hidden: true, title: "Lo que no ha cabido está en Hallazgos y en la pestaña Insights",
      onclick: () => { clearTimeout(N.timerCola); N.timerCola = null; N.cola.length = 0; pintarMas(); renderBandeja(); if (AP.pestana) AP.pestana("insights"); } });
    cont.append(mas);
    function pintarMas() {
      const n = N.cola.length;
      mas.hidden = !n;
      mas.textContent = n ? `+${n} hallazgo${n === 1 ? "" : "s"}` : "";
    }
    function programarCola() {
      pintarMas();
      if (N.timerCola != null || !N.cola.length || N.pila.length >= MAX_VISIBLES) return;
      N.timerCola = setTimeout(sacar, Math.max(0, N.ultima + CADA - performance.now()));
    }
    function sacar() {
      N.timerCola = null;
      const ahora = performance.now();
      while (N.cola.length && ahora - N.cola[0].enc > CADUCA_COLA) N.cola.shift();   // caducado: ya no es «ahora»; sigue en Hallazgos
      if (!N.cola.length || N.pila.length >= MAX_VISIBLES) { programarCola(); renderBandeja(); return; }
      N.ultima = ahora;
      const n = { d: N.cola.shift(), el: null, restante: 0, inicio: 0, timer: null };
      n.restante = n.d.vida;
      n.el = construir(n);
      cont.insertBefore(n.el, mas);   // debajo de las ya visibles y antes del «+N»: no empuja lo que se está leyendo
      N.pila.push(n);
      if (!reducido()) {   // entra con un fundido y 8 px de recorrido (opaco: sin desenfoque); will-change solo durante la entrada
        n.el.style.willChange = "transform, opacity";
        const a = n.el.animate([{ opacity: 0, transform: "translateY(8px)" }, { opacity: 1, transform: "none" }], { duration: 240, easing: SALIDA });
        a.onfinish = a.oncancel = () => { n.el.style.willChange = ""; };
      }
      if (!N.pausada) vida(n);
      programarCola();
      renderBandeja();
    }
    function encolar(d) {
      if (N.vistas.has(d.clave)) return false;
      N.vistas.add(d.clave);
      if (!EMERGE.has(d.tipo)) { renderBandeja(); return false; }   // sin aviso: la fila ya está en Hallazgos y su pestaña lleva el contador
      d.enc = performance.now();
      N.cola.push(d);
      programarCola();
      renderBandeja();
      return true;
    }
    // Al terminar o salir de la vista: se vacían cola y pila (lo pendiente pasa a la Bandeja, que se deriva de los datos y no se vacía)
    function vaciar() {
      clearTimeout(N.timerCola); N.timerCola = null; N.cola.length = 0; pintarMas();
      for (const n of N.pila) clearTimeout(n.timer);
      N.pila.length = 0; N.puntero = N.foco = N.pausada = false;
      cont.querySelectorAll(".notif").forEach((e) => e.remove());   // quitarla del DOM cancela su animación
      renderBandeja();
    }

    // ---- Bandeja
    const FILTROS = [["todo", "Todo"], ["decision", "Decisiones"], ["pregunta", "Preguntas"], ["pendiente", "Pendientes"], ["contradiccion", "Contradicciones"], ["riesgo", "Riesgos"],
      ["regla", "Reglas"], ["definicion", "Definiciones"], ["idea", "Ideas"], ["objetivo", "Objetivos"]];
    const B = { filas: new Map(), chips: new Map(), vistas: new Set(), pintado: false, filtro: "todo" };
    const guardar = (k, v) => { try { localStorage.setItem(k, v); } catch { /* sin almacenamiento */ } };
    const leer = (k, d) => { try { const v = localStorage.getItem(k); return v == null ? d : v; } catch { return d; } };
    B.filtro = FILTROS.some(([k]) => k === leer("apuntes_bandeja_filtro", "todo")) ? leer("apuntes_bandeja_filtro", "todo") : "todo";

    function itemsBandeja() {
      const pend = new Set(N.cola.map((d) => d.clave));
      N.pila.forEach((n) => pend.add(n.d.clave));
      const out = [], vistos = new Set();
      const poner = (d) => { if (pend.has(d.clave) || vistos.has(d.clave)) return; vistos.add(d.clave); d.seq = out.length; out.push(d); };
      (S.tarjetas || []).forEach((t) => { if (t && t.texto) poner(datosTarjeta(t)); });
      N.manuales.forEach((d) => poner({ ...d }));
      ((S.monitor && S.monitor.definiciones) || []).forEach((x) => poner(datosDef(x)));
      ((S.monitor && S.monitor.feed) || []).forEach((e) => { if (e.tipo === "sin_tratar") poner(datosMonitor(e)); });
      return out.sort((a, b) => (b.t == null ? -1 : b.t) - (a.t == null ? -1 : a.t) || b.seq - a.seq);
    }
    function llenarFila(el, d) {
      const sig = JSON.stringify([d.k, d.cat, d.texto, d.minuto, d.t, d.bmeta, d.ref.tarjeta != null]);
      if (el._sig === sig) return;
      el._sig = sig;
      el.setAttribute("data-k", d.k);
      el.setAttribute("aria-label", d.cat + (d.minuto ? ", " + d.minuto : ""));
      el.replaceChildren(...[
        h("div", { class: "bj-l1" }, glifo(d.tipo, d.k === "posible"), h("span", { class: "bj-cat t-label" }, d.cat), h("span", { class: "bj-der" }, chipMin(d.minuto, d.t))),
        h("div", { class: "bj-tx t-body" }, d.texto),
        d.bmeta ? h("div", { class: "bj-meta t-meta" }, d.bmeta) : null,
        d.ref.tarjeta != null ? h("div", { class: "n-acc" }, h("button", { type: "button", class: "btn btn-ghost btn-mini", "aria-label": "Ver " + d.cat.toLowerCase() + " en Insights",
          onclick: () => { cerrar(false); irARef(d.ref); } }, "Ver")) : null].filter(Boolean)); // replaceChildren pintaría «null» como texto
    }
    function renderBandeja() {
      if (!btn) return;
      const items = itemsBandeja();
      const txt = "Hallazgos " + items.length;
      if (btn.textContent !== txt) { btn.textContent = txt; btn.setAttribute("aria-label", `Hallazgos, ${items.length} ${items.length === 1 ? "elemento" : "elementos"}`); }
      if (!panel || panel.hidden) return;
      const cuenta = {};
      items.forEach((d) => { cuenta[d.tipo] = (cuenta[d.tipo] || 0) + 1; });
      cuenta.todo = items.length;
      const f = B.filtro === "todo" || cuenta[B.filtro] ? B.filtro : "todo";   // un filtro sin elementos no deja la lista vacía
      for (const [k, etq] of FILTROS) {
        const c = B.chips.get(k);
        c.hidden = k !== "todo" && !cuenta[k];
        c.setAttribute("aria-pressed", String(k === f));
        c.setAttribute("aria-label", `${etq}: ${cuenta[k] || 0}`);
        const n = c.lastChild; if (n.textContent !== String(cuenta[k] || 0)) n.textContent = String(cuenta[k] || 0);
      }
      $("#r-bandeja-total").textContent = items.length ? String(items.length) : "";
      const vis = items.filter((d) => f === "todo" || d.tipo === f);
      const lista = $("#r-bandeja-lista");
      const animar = B.pintado && !reducido();
      const nuevas = [];
      const nodos = vis.map((d) => {
        let el = B.filas.get(d.clave);
        if (!el) { el = h("article", { class: "bj-f" }); B.filas.set(d.clave, el); }
        llenarFila(el, d);
        if (!B.vistas.has(d.clave)) nuevas.push(el);
        return el;
      });
      B.vistas = new Set(vis.map((d) => d.clave));
      for (const k of [...B.filas.keys()]) if (!B.vistas.has(k)) B.filas.delete(k);
      if (!nodos.length) nodos.push(h("div", { class: "bj-vacio t-body" }, "Todavía no hay hallazgos."));
      const antes = panel.scrollHeight;
      reconciliar(lista, nodos);
      if (panel.scrollTop > 0) panel.scrollTop += panel.scrollHeight - antes;   // lo nuevo entra arriba sin mover lo que se lee
      if (animar && panel.scrollTop < 2) nuevas.forEach((el) => el.animate([{ opacity: 0 }, { opacity: 1 }], { duration: 180, easing: SALIDA }));   // si se está leyendo más abajo, en seco
      B.pintado = true;
      medirCabecera();
    }
    // alto de la cabecera y los filtros del panel (en Modo reunión la pila de avisos empieza justo debajo)
    function medirCabecera() {
      if (!panel || panel.hidden) return;
      const cab = panel.querySelector(".bj-cab"), fil = $("#r-bandeja-filtros");
      document.documentElement.style.setProperty("--bj-cab-h", Math.ceil((cab ? cab.offsetHeight : 0) + (fil ? fil.offsetHeight : 0)) + "px");
    }
    window.addEventListener("resize", medirCabecera);
    function abrir(foco, animar = true) {
      if (!panel) return;
      panel.hidden = false;
      btn.setAttribute("aria-expanded", "true");
      guardar("apuntes_bandeja_abierta", "1");
      document.body.dataset.hallazgos = "abierto";
      B.pintado = false;
      renderBandeja();
      medirCabecera();
      clearTimeout(B.cierre);
      panel.getAnimations().forEach((a) => a.cancel());
      if (animar && !reducido()) {   // la lámina se desliza desde la derecha (200 ms) y los chips entran escalonados (20·n)
        panel.animate([{ opacity: 0, transform: "translateX(16px)" }, { opacity: 1, transform: "none" }], { duration: 200, easing: SALIDA });
        [...B.chips.values()].filter((c) => !c.hidden).forEach((c, i) => c.animate([{ opacity: 0, transform: "translateY(6px)" }, { opacity: 1, transform: "none" }], { duration: 180, delay: i * 20, easing: SALIDA, fill: "backwards" }));
      }
      if (foco) $("#r-bandeja-x").focus();
    }
    function cerrar(devolverFoco) {
      if (!panel || panel.hidden) return;
      btn.setAttribute("aria-expanded", "false");
      guardar("apuntes_bandeja_abierta", "0");
      delete document.body.dataset.hallazgos;
      B.pintado = false;
      if (devolverFoco) btn.focus();
      if (reducido()) { panel.hidden = true; return; }
      panel.animate([{ opacity: 1, transform: "none" }, { opacity: 0, transform: "translateX(16px)" }], { duration: 160, easing: ENTRADA });   // sale en 160 ms
      clearTimeout(B.cierre);
      B.cierre = setTimeout(() => { if (btn.getAttribute("aria-expanded") === "false") panel.hidden = true; }, 170);
    }
    if (panel && btn) {
      const cf = $("#r-bandeja-filtros");
      for (const [k, etq] of FILTROS) {
        const c = h("button", { type: "button", class: "bj-chip t-meta", "aria-pressed": "false", "data-f": k, onclick: () => { B.filtro = k; guardar("apuntes_bandeja_filtro", k); renderBandeja(); } },
          k === "todo" ? null : glifo(k), h("span", {}, etq), h("span", { class: "bj-n" }, "0"));
        B.chips.set(k, c); cf.append(c);
      }
      btn.addEventListener("click", () => (panel.hidden ? abrir(true) : cerrar(true)));
      $("#r-bandeja-x").addEventListener("click", () => cerrar(true));
      document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !panel.hidden && !e.defaultPrevented) { e.preventDefault(); cerrar(true); } });
      if (leer("apuntes_bandeja_abierta", "0") === "1") abrir(false, false);
      renderBandeja();
    }

    // Expuesto para probar sin modelo: pasa por la misma cola, con las mismas reglas de ideas. Además queda en la Bandeja al cumplirse su tiempo.
    AP.notificar = (t) => {
      if (!admite(t)) return false;
      const d = datosTarjeta(t);
      N.manuales.set(d.clave, d);
      return encolar(d);
    };

    // Definiciones ya conocidas (las del snapshot y las ya vistas): la local sustituida por la de la Analista conserva su minuto y no vuelve a notificar
    function recordarDef(x) {
      const k = norm(x.termino);
      const previa = N.defs.find((p) => p.k === k || (x.origen === "analista" && p.origen === "local" && x.t != null && p.t === x.t));
      if (!previa) { N.defs.push({ k, origen: x.origen, t: x.t }); return true; }
      if (previa.k !== k) {   // sustitución con otro nombre: la notificación pendiente (si la hay) pasa a la clave nueva
        for (const d of [...N.cola, ...N.pila.map((n) => n.d)]) if (d.clave === "d:" + previa.k) d.clave = "d:" + k;
        previa.k = k;
      }
      previa.origen = x.origen; previa.t = x.t;
      return false;
    }

    const previoN = AP.hooks.evento;
    AP.hooks.evento = (d) => {
      if (previoN) previoN(d);
      if (d.tipo === "tarjetas") { if (!d.todas && Array.isArray(d.nuevas) && enCurso()) d.nuevas.forEach((t) => { if (admite(t)) encolar(datosTarjeta(t)); }); }
      else if (d.tipo === "monitor") { if (enCurso()) (d.entradas || []).forEach((e) => { if (e.tipo === "sin_tratar") encolar(datosMonitor(e)); }); }
      else if (d.tipo === "definiciones") (d.definiciones || []).forEach((x) => { if (recordarDef(x) && enCurso()) encolar(datosDef(x)); });
      else if (d.tipo === "snapshot") ((d.monitor && d.monitor.definiciones) || []).forEach((x) => recordarDef(x));   // reconexión: nunca notifica
      if ((d.tipo === "estado" || d.tipo === "snapshot") && "estado" in d && d.estado !== "grabando" && d.estado !== "pausada") vaciar();   // terminar o salir de la vista de reunión
      // S se actualiza DESPUÉS de los hooks (app.js, equipo.js): la Bandeja se repinta con los datos ya puestos
      if (["tarjetas", "monitor", "definiciones", "snapshot", "estado"].includes(d.tipo)) queueMicrotask(renderBandeja);
    };
    const previoReiniciar = AP.hooks.reiniciar;
    AP.hooks.reiniciar = () => {
      if (previoReiniciar) previoReiniciar();
      vaciar(); N.vistas.clear(); N.manuales.clear(); N.defs.length = 0; B.filas.clear(); B.vistas.clear(); B.pintado = false;
      queueMicrotask(renderBandeja);
    };
  })();

  // Título completo al pasar el ratón: app.js escribe el tema en la cabecera sin atributo title (la cabecera lo recorta)
  const temaCab = $("#r-tema");
  if (temaCab) {
    const copiarTitulo = () => { temaCab.title = temaCab.textContent; };
    copiarTitulo();
    new MutationObserver(copiarTitulo).observe(temaCab, { childList: true, characterData: true, subtree: true });
  }
})();
