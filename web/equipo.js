"use strict";
/* Apuntes: el equipo de agentes (DESIGN-equipo.md). Pinta el Monitor local, las cuatro tarjetas de perfil, las Definiciones y el
   Minuto a minuto. Todo sale de datos reales del backend: `equipo` (estado de cada perfil, presupuesto), `monitor` (feed y pasadas
   locales) y los eventos `tarea` de las llamadas al modelo. Una tarjeta solo figura TRABAJANDO si hay una llamada real en curso
   (evento `tarea` de inicio); lo que sale del Monitor se etiqueta «detección local». Sin temporizadores de relleno: el único
   intervalo refresca el cronómetro mientras haya una llamada real. */
(() => {
  const AP = window.AP;
  if (!AP) return;
  const { S, UI, h, $, $$, mmss, kfmt } = AP;
  const reducido = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const dec = (n, d = 1) => n.toFixed(d).replace(".", ",");
  const crono = (ms) => { const s = Math.max(0, Math.floor(ms / 1000)); return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`; };
  const segs = (ms) => (ms >= 10000 ? `${Math.round(ms / 1000)} s` : `${dec(ms / 1000)} s`);
  const aSeg = (m) => { const p = String(m || "").split(":").map(Number); return p.length === 2 && p.every((x) => !Number.isNaN(x)) ? p[0] * 60 + p[1] : null; };
  const hoyMs = (hora) => { const [a, b, c] = String(hora || "").split(":").map(Number); if ([a, b, c].some(Number.isNaN)) return null; const d = new Date(); d.setHours(a, b, c, 0); return d.getTime(); };
  const cap = (t) => (t ? t[0].toUpperCase() + t.slice(1) : t);
  const enReunionModo = () => document.body.dataset.modo === "reunion";
  const enModoEquipo = () => !!(S.sesion && S.sesion.cadencia === "equipo");

  S.monitor = S.monitor || { feed: [], definiciones: [], pasadas: [] };
  const E = { tarjetas: new Map(), vistasDef: new Set(), vistasFeed: new Set(), primera: true, verTodas: false, ultPasada: null, indTimer: null, cronometro: null, estadoPrev: new Map() };
  // cada agente, con su nombre, color e icono (nombres.js)
  const ESTADO = { espera: "En espera", turno: "Le toca", trabajando: "Trabajando", hecho: "Hecho", error: "Error", sin_presupuesto: "Sin presupuesto" };

  // ------------------------------------------------------------ datos reales de las llamadas
  function enCursoReal(id) {
    const O = AP.O; if (!O) return null;
    for (const t of O.tareas.values()) if (t.agente === id && t.estado === "en_curso") return t;
    return null;
  }
  const inicioMs = (t) => hoyMs(t.hora) || Date.now();

  // ------------------------------------------------------------ línea del Monitor
  function textoMonitor() {
    const eq = S.equipo;
    if (!eq) return "Monitor · local · escuchando · sin señales todavía";
    const nivel = eq.presupuesto && eq.presupuesto.nivel, m = eq.monitor || {};
    if (S.estado === "pausada") return "Monitor · local · en pausa";
    if (nivel === "agotado") return "Monitor · sin presupuesto esta hora · solo detección local";
    if (nivel === "ahorro") return "Monitor · ahorro · 80 % del presupuesto";
    if (m.hace_s == null) return "Monitor · local · escuchando · sin señales todavía";
    const n = m.senales || 0;
    return `Monitor · local · última pasada hace ${Math.max(0, Math.round(m.hace_s))} s · ${n} señal${n === 1 ? "" : "es"}`;
  }
  function pintarMonitor() {
    const t = $("#eq-monitor-t"); if (!t) return;
    const txt = textoMonitor();
    if (t.textContent !== txt) t.textContent = txt;
    const b = $("#eq-monitor"); b.setAttribute("aria-label", txt + ". Detección local, sin modelo. Abre el Registro del Monitor");
    const nivel = S.equipo && S.equipo.presupuesto && S.equipo.presupuesto.nivel;
    $("#eq-ind").classList.toggle("sin", nivel === "agotado" || nivel === "ahorro");
    $("#eq-ind").classList.toggle("pausa", S.estado === "pausada");
    const eq = S.equipo, c = $("#eq-cuenta");
    const cuenta = eq && eq.turnos ? `${eq.turnos} intervencion${eq.turnos === 1 ? "" : "es"} · ${kfmt(eq.tokens || 0)}` : "";
    if (c.textContent !== cuenta) c.textContent = cuenta;
  }
  // relleno fijo de 300 ms en cada pasada del Monitor (un cambio de estado, sin bucle)
  function pulsoPasada() {
    const i = $("#eq-ind"); if (!i) return;
    i.classList.add("pasada");
    clearTimeout(E.indTimer);
    E.indTimer = setTimeout(() => i.classList.remove("pasada"), 300);
  }

  // ------------------------------------------------------------ tarjetas de perfil
  function crearTarjeta(p) {
    const marca = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    marca.setAttribute("viewBox", "0 0 16 16"); marca.setAttribute("class", "eq-marca"); marca.setAttribute("aria-hidden", "true");
    const tr = document.createElementNS("http://www.w3.org/2000/svg", "path"); tr.setAttribute("d", "M4 8.4l2.7 2.7L12 5.6"); tr.setAttribute("pathLength", "100"); marca.append(tr);
    // div[role=button] y no <button>: la tarjeta lleva dentro texto (y, en el diseño, chips de minuto), y un botón anidado en otro rompe el árbol HTML
    const abrir = (ev) => { ev.stopPropagation(); if (AP.abrirRegistro) AP.abrirRegistro(p.id); };
    const el = h("div", { role: "button", tabindex: "0", class: "eq-tarj", "data-perfil": p.id, "data-estado": "espera", title: `${p.nombre}: ${p.mision}. Abre el Registro de sus llamadas`, onclick: abrir,
      onkeydown: (ev) => { if (ev.target === el && (ev.key === "Enter" || ev.key === " ")) { ev.preventDefault(); abrir(ev); } } });
    el._p = { ind: h("i", { class: "ind-p", "aria-hidden": "true" }), nombre: h("span", { class: "t-body-m" }, p.nombre), estado: h("span", { class: "t-label" }), marca,
      l2: h("span", { class: "eq-l2 t-body" }), l3: h("span", { class: "eq-l3 t-meta" }) };
    el.append(h("span", { class: "eq-l1" }, h("span", { class: "mono ins-ag", "aria-hidden": "true", style: `--ag: ${AP.agente(p.id).color}` }, AP.icono(AP.agente(p.id).icono, "ag-ic")), h("span", { class: "eq-nombre" }, el._p.ind, el._p.nombre), h("span", { class: "eq-estado" }, el._p.marca, el._p.estado)), el._p.l2, el._p.l3);
    return el;
  }
  const hora = (s) => (s == null ? "" : mmss(s));
  function linea3(p, estado, real) {
    const partes = [];
    const t = p.turno;
    if (estado === "trabajando") {
      const tr = (real && real.tramo) || "";
      partes.push(`${p.motivo ? "motivo: " + p.motivo : ""}${p.motivo && tr ? " · " : ""}${tr ? "tramo " + tr : ""}`.trim());
      return partes.filter(Boolean).join("");
    }
    if (estado === "turno") return p.motivo ? `motivo: ${p.motivo}` : "";
    if (estado === "error") return S.analisis && S.analisis.bloqueo ? "límite del plan · equipo detenido" : "sin respuesta · se reintentará en la próxima intervención";
    if (estado === "sin_presupuesto") {
      const pr = S.equipo && S.equipo.presupuesto;
      return `Sin presupuesto esta hora${pr && pr.libera_a ? ` · siguiente a las ${pr.libera_a}` : ""}`;
    }
    const a = [];
    if (t) a.push(["última intervención " + (t.desde && t.hasta ? `${t.desde}–${t.hasta}` : ""), t.modelo, t.ms != null ? segs(t.ms) : null, t.tokens != null ? kfmt(t.tokens) : null].filter((x) => x && x.trim()).join(" · "));
    if (p.siguiente && S.estado === "grabando") {
      const s = p.siguiente;
      a.push(s.motivo === "rotación" ? `siguiente: por rotación en ${crono(s.en * 1000)}` : `siguiente: en ${crono(s.en * 1000)} · motivo: ${s.motivo}`);
    }
    if (!a.length) return "aún no ha intervenido";
    return a.join(" · ");
  }
  function textoAporte(p) {
    const a = p.aporte;
    if (!a) return null;
    return [cap(a.categoria), a.minuto || null, a.texto].filter(Boolean).join(" · ");
  }
  function pintarPerfiles() {
    const eq = S.equipo; if (!eq) return;
    const cont = $("#eq-perfiles");
    const nodos = [];
    for (const p of eq.perfiles) {
      let el = E.tarjetas.get(p.id);
      if (!el) { el = crearTarjeta(p); E.tarjetas.set(p.id, el); }
      const real = enCursoReal(p.id);
      let estado = p.estado;
      if (real) estado = "trabajando";
      else if (estado === "trabajando") estado = "turno";   // el backend ya lo eligió pero la llamada aún no ha empezado
      if (!enModoEquipo() && estado !== "trabajando" && estado !== "error") estado = "espera";
      const previo = E.estadoPrev.get(p.id);
      el.dataset.estado = estado;
      const etq = ESTADO[estado] + (estado === "trabajando" && real ? " " + crono(Date.now() - inicioMs(real)) : "");
      if (el._p.estado.textContent !== etq) el._p.estado.textContent = etq;
      const ap = textoAporte(p);
      const l2 = ap || (enModoEquipo() ? `Se pregunta: ${p.pregunta}` : "Con este ritmo, el equipo no interviene solo");
      if (el._p.l2.textContent !== l2) {
        el._p.l2.textContent = l2;
        el._p.l2.classList.toggle("vacio", !ap);
        if (ap && previo && !E.primera && !reducido()) { el.classList.remove("entra"); void el.offsetWidth; el.classList.add("entra"); }
      }
      const l3 = enModoEquipo() ? linea3(p, estado, real) : (S.sesion ? `modo ${S.sesion.cadencia === "manual" ? "solo cuando lo pidas" : "cada " + S.sesion.cadencia_min + " min"}: el análisis es el generalista` : "");
      if (el._p.l3.textContent !== l3) el._p.l3.textContent = l3;
      el._p.l3.hidden = !l3;
      if (previo === "trabajando" && estado === "hecho" && !reducido()) { el.classList.remove("traza"); void el.offsetWidth; el.classList.add("traza"); }
      E.estadoPrev.set(p.id, estado);
      el.setAttribute("aria-label", `${p.nombre}, ${ESTADO[estado].toLowerCase()}${ap ? ". " + ap : ""}${l3 ? ". " + l3 : ""}. Abre el Registro de sus llamadas`);
      nodos.push(el);
    }
    if (cont.children.length !== nodos.length || nodos.some((n, i) => cont.children[i] !== n)) cont.replaceChildren(...nodos);
  }

  // ------------------------------------------------------------ Definiciones
  const chipFuente = (d) => (d.origen === "local" ? "detección local" : AP.nombreAgente("funcional"));
  function pintarDefiniciones() {
    const lista = (S.monitor && S.monitor.definiciones) || [];
    const modo = enReunionModo();
    $("#eq-def-n").textContent = lista.length ? String(lista.length) : "";
    const mostrar = modo && !E.verDefTodas ? lista.slice(0, 3) : lista;
    const cont = $("#eq-def-lista");
    const scroll = $("#eq-scroll"), quieto = scroll && scroll.scrollTop < 2;
    if (!lista.length) { cont.replaceChildren(h("div", { class: "eq-vacio t-body" }, "Todavía no se ha definido ningún término.")); }
    else {
      cont.replaceChildren(...mostrar.map((d) => {
        const clave = d.termino + "|" + d.origen;
        const nueva = !E.primera && !E.vistasDef.has(clave) && quieto && !reducido();
        E.vistasDef.add(clave);
        const el = h("button", { type: "button", class: "eq-def-fila" + (nueva ? " nueva" : ""), "data-t": d.t == null ? null : d.t,
          "aria-label": `Definición de ${d.termino}: ${d.definicion}. ${d.minuto ? d.minuto + ", " : ""}${chipFuente(d)}. Ir a ese momento de la transcripción`,
          title: "Ir a ese momento de la transcripción",
          onclick: () => AP.hooks.irAlMinuto && d.t != null && AP.hooks.irAlMinuto(d.t) },
        h("span", { class: "eq-term t-body-m" }, d.termino), h("span", { class: "eq-desc t-body" }, d.definicion + (d.parcial ? " (parcial)" : "")),
        h("span", { class: "eq-fuente t-meta" + (d.origen === "local" ? " local" : "") }, [d.minuto, chipFuente(d)].filter(Boolean).join(" · ")));
        el.addEventListener("mouseenter", () => AP.resaltarLinea && d.t != null && AP.resaltarLinea(d.t, true));
        el.addEventListener("mouseleave", () => AP.resaltarLinea && d.t != null && AP.resaltarLinea(d.t, false));
        el.addEventListener("focus", () => AP.resaltarLinea && d.t != null && AP.resaltarLinea(d.t, true));
        el.addEventListener("blur", () => AP.resaltarLinea && d.t != null && AP.resaltarLinea(d.t, false));
        return el;
      }));
    }
    const mas = $("#eq-def-mas");
    mas.hidden = !(modo && lista.length > 3);
    if (!mas.hidden) mas.textContent = E.verDefTodas ? "Ver menos" : `Ver ${lista.length}`;
  }
  $("#eq-def-mas").addEventListener("click", () => { E.verDefTodas = !E.verDefTodas; pintarDefiniciones(); });

  // ------------------------------------------------------------ Minuto a minuto (todo local, sin modelo)
  const TOPE_FEED = 40;
  function etiquetaFila(e) { return `${e.minuto} · ${e.texto}`; }
  function pintarFeed() {
    const feed = ((S.monitor && S.monitor.feed) || []);
    const orden = [...feed].reverse();
    const cont = $("#eq-feed-lista");
    $("#eq-feed-n").textContent = feed.length ? String(feed.length) : "";
    const scroll = $("#eq-scroll"), quieto = scroll && scroll.scrollTop < 2;
    const filas = orden.slice(0, TOPE_FEED).map((e) => {
      const nueva = !E.primera && !E.vistasFeed.has(e.id) && quieto && !reducido();
      E.vistasFeed.add(e.id);
      const cls = "eq-fila t-meta" + (e.tipo === "toca" ? " apagada" : e.tipo === "sin_tratar" ? " ambar" : "") + (nueva ? " nueva" : "");
      return h("button", { type: "button", class: cls, "data-t": e.t, title: "Detección local, sin modelo. Ir a ese momento de la transcripción",
        "aria-label": `detección local · ${etiquetaFila(e)}`, onclick: () => AP.hooks.irAlMinuto && AP.hooks.irAlMinuto(e.t) }, etiquetaFila(e));
    });
    if (!filas.length) filas.push(h("div", { class: "eq-vacio t-meta" }, "El Monitor aún no ha detectado nada."));
    cont.replaceChildren(...filas);
    const todas = $("#eq-feed-todas");
    todas.hidden = feed.length <= TOPE_FEED;
    todas.textContent = `Ver todas (${feed.length})`;
    feed.forEach((e) => E.vistasFeed.add(e.id));
  }
  $("#eq-feed-todas").addEventListener("click", (ev) => { ev.stopPropagation(); AP.abrirRegistro && AP.abrirRegistro("monitor-feed"); });
  $("#eq-monitor").addEventListener("click", (ev) => { ev.stopPropagation(); AP.abrirRegistro && AP.abrirRegistro("monitor"); });

  // ------------------------------------------------------------ «visto 27:40» en objetivos y checks (el Monitor no cambia su estado)
  function pintarVistos() {
    const m = (S.equipo && S.equipo.monitor) || {};
    const toques = m.toques || {}, tchk = m.toques_checks || {};
    $$("#r-obj-lista .obj[data-n]").forEach((fila) => {
      const t = toques[fila.dataset.n];
      let v = fila.querySelector(":scope > .obj-visto");
      if (t == null) { if (v) v.remove(); return; }
      if (!v) { v = h("span", { class: "obj-visto t-meta" }); fila.append(v); }
      const txt = "visto " + mmss(t); if (v.textContent !== txt) v.textContent = txt;
    });
    $$("#r-checks .chk-fila[data-id]").forEach((fila) => {
      const t = tchk[fila.dataset.id];
      let v = fila.querySelector(":scope > .chk-visto");
      if (t == null) { if (v) v.remove(); return; }
      if (!v) { v = h("div", { class: "chk-visto t-meta" }); fila.append(v); }
      const txt = "visto " + mmss(t); if (v.textContent !== txt) v.textContent = txt;
    });
  }

  // ------------------------------------------------------------ estado vacío de Insights: lo que el Monitor ya ha detectado (local, sin modelo)
  // Mientras no haya tarjetas, la pestaña enseña lo que ya se sabe (últimas detecciones y objetivos tocados); sin datos, qué va a aparecer aquí.
  const ETQ_SENAL = { decision: "decisión", pendiente: "pendiente", riesgo: "riesgo", pregunta: "pregunta", idea: "idea", responsable: "responsable", definicion: "definición",
    regla: "regla", dato: "dato", sistema: "sistema", contraste: "contraste", plazo: "plazo", cifra: "cifra" };
  const DETECCION = { decision: "Posible decisión", pendiente: "Posible pendiente", riesgo: "Posible riesgo", pregunta: "Pregunta en el aire", idea: "Idea", responsable: "Se nombra a un responsable",
    definicion: "Posible definición", regla: "Posible regla", dato: "Dato", cifra: "Cifra", plazo: "Plazo", sistema: "Se nombra un sistema", contraste: "Contraste entre dos cosas" };
  function textoDeteccion(e) {
    const t = String(e.texto || ""), m = /^señal:\s*([^·]+?)\s*·\s*(.*)$/i.exec(t);
    if (!m) return t;
    const k = m[1].normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase().trim();
    const cita = m[2].replace(/[\s?¿!¡.,;:]+»/g, "»");   // «portal?» → «portal»: el signo es del habla, no del término
    return (DETECCION[k] || m[1]) + ": " + cita;
  }
  function vacioInsights() {
    const feed = ((S.monitor && S.monitor.feed) || []).filter((e) => (e.tipo === "senal" || e.tipo === "toca") && /[\p{L}\d]{3,}/u.test(String(e.texto || "").split("·").slice(1).join(" ")));   // sin restos como «?»
    const toques = ((S.equipo && S.equipo.monitor) || {}).toques || {};
    const objetivos = (S.objetivos || []).filter((o) => !o.sugerido && toques[o.n] != null);
    if (!feed.length && !objetivos.length) {
      return h("div", { class: "vacio-i vacio-util" },
        h("p", { class: "t-body" }, "Aquí irán apareciendo los avisos: decisiones, pendientes, riesgos y preguntas que salgan de la conversación."),
        h("p", { class: "t-meta" }, "El equipo avisa cuando se ha dicho algo que lo merece; suele ser en los primeros minutos."));
    }
    const filas = [
      ...objetivos.map((o) => h("li", { class: "vacio-fila" }, h("span", { class: "t-meta vacio-min" }, mmss(toques[o.n])), h("span", { class: "t-body" }, "Se ha tocado el objetivo «" + o.texto + "»"))),
      ...feed.slice(-5).reverse().map((e) => h("li", { class: "vacio-fila" }, h("span", { class: "t-meta vacio-min" }, e.minuto), h("span", { class: "t-body" }, textoDeteccion(e)))),
    ];
    return h("div", { class: "vacio-i vacio-util" },
      h("p", { class: "t-body" }, "Todavía no hay avisos, pero esto es lo que ya se ha detectado en la conversación:"),
      h("ul", { class: "vacio-lista" }, filas),
      h("p", { class: "t-meta" }, "Los avisos aparecen cuando el equipo analiza un tramo."));
  }
  AP.vacioInsights = vacioInsights;
  let vacioPendiente = false;
  function refrescarVacio() {
    if (vacioPendiente || (S.tarjetas || []).length || !AP.hooks.pintarInsights) return;
    vacioPendiente = true;
    requestAnimationFrame(() => { vacioPendiente = false; if (!(S.tarjetas || []).length) AP.hooks.pintarInsights(); });
  }

  // ------------------------------------------------------------ pie: presupuesto
  const previoPie = AP.hooks.pie;
  AP.hooks.pie = () => {
    if (previoPie) previoPie();
    const el = $("#p-consumo"); if (!el) return;
    if (S.estado === "inactivo" || !S.sesion || !enModoEquipo() || !S.equipo || !S.equipo.presupuesto) { el.classList.remove("ahorro", "agotado"); return; }
    const pr = S.equipo.presupuesto, c = S.consumo;
    const cuenta = (k) => Object.entries((c && c.por_modelo) || {}).filter(([m]) => m.toLowerCase().includes(k)).reduce((n, [, u]) => n + u.llamadas, 0);
    el.className = "p-presu " + pr.nivel;
    el.textContent = `Presupuesto ${kfmt(pr.usado)} / ${kfmt(pr.limite)} esta hora · haiku ${cuenta("haiku")} · sonnet ${cuenta("sonnet")} · opus ${cuenta("opus")}`;
    el.title = `Ventana de 60 minutos de reunión. Al 80 % el equipo ahorra (intervenciones más espaciadas); al 100 % solo responden «Analizar ahora» y Pregúntale. Total de la sesión: ${kfmt(((c && c.total) ? c.total.entrada + c.total.cache_creacion + c.total.cache_lectura + c.total.salida : 0))} tokens`;
  };

  // ------------------------------------------------------------ render conjunto
  let pendiente = false;
  function programar() { if (pendiente) return; pendiente = true; requestAnimationFrame(() => { pendiente = false; render(); }); }
  function render() {
    const vista = $("#v-reunion");
    if (!vista || vista.hidden) return;
    pintarMonitor(); pintarPerfiles(); pintarDefiniciones(); pintarFeed(); pintarVistos();
    E.primera = false;
    // el cronómetro de una tarjeta que trabaja se refresca cada segundo SOLO mientras haya una llamada real
    const hay = [...E.tarjetas.keys()].some((id) => enCursoReal(id));
    if (hay && !E.cronometro) E.cronometro = setInterval(() => { pintarPerfiles(); }, 1000);
    if (!hay && E.cronometro) { clearInterval(E.cronometro); E.cronometro = null; }
  }
  AP.alRenderAgentes = programar;

  const previoEvento = AP.hooks.evento;
  AP.hooks.evento = (d) => {
    if (previoEvento) previoEvento(d);
    switch (d.tipo) {
      case "snapshot":
        S.equipo = d.equipo || null;
        S.monitor = d.monitor || { feed: [], definiciones: [], pasadas: [] };
        E.vistasDef.clear(); E.vistasFeed.clear(); E.primera = true;
        programar(); break;
      case "estado": case "tick": case "equipo":
        if (d.tipo === "equipo") { const { tipo, ...resto } = d; S.equipo = resto; } else if ("equipo" in d) S.equipo = d.equipo;
        programar(); break;
      case "monitor":
        S.monitor.feed.push(...(d.entradas || []));
        if (S.monitor.feed.length > 600) S.monitor.feed.splice(0, S.monitor.feed.length - 600);
        if (d.pasada) { S.monitor.pasadas.push(d.pasada); if (S.monitor.pasadas.length > 300) S.monitor.pasadas.shift(); }
        pulsoPasada(); programar(); refrescarVacio(); break;
      case "definiciones": {
        const antes = (S.monitor.definiciones || []).length;
        S.monitor.definiciones = d.definiciones || [];
        if (S.monitor.definiciones.length > antes && AP.pulsoCabecera) requestAnimationFrame(() => AP.pulsoCabecera("#eq-def .grupo-h"));
        programar(); break;
      }
      case "tarea": case "analisis": case "tarjetas": programar(); break;
    }
  };
  const previoReinicio = AP.hooks.reiniciar;
  AP.hooks.reiniciar = () => {
    if (previoReinicio) previoReinicio();
    S.equipo = null; S.monitor = { feed: [], definiciones: [], pasadas: [] };
    E.vistasDef.clear(); E.vistasFeed.clear(); E.primera = true; E.verDefTodas = false; E.estadoPrev.clear();
    $("#eq-perfiles").replaceChildren(); E.tarjetas.clear();
    programar();
  };
  const obsObj = new MutationObserver(() => pintarVistos());
  for (const sel of ["#r-obj-lista", "#r-checks"]) { const n = $(sel); if (n) obsObj.observe(n, { childList: true, subtree: true }); }
  // el Modo reunión cambia el número de definiciones visibles
  new MutationObserver(() => programar()).observe(document.body, { attributes: true, attributeFilter: ["data-modo"] });
  AP.equipo = { render: programar, textoMonitor };
})();
