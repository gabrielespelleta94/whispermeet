"use strict";
/* Apuntes: orquestación visible. Cada nodo es un agente o tarea que EXISTE en la app y su estado sale de eventos reales
   del backend (`tarea` en el WebSocket: inicio y fin de cada llamada al modelo y de cada tramo del transcriptor).
   Nada de temporizadores que simulen actividad: sin evento no hay movimiento. Sin librerías; CSS y Web Animations API. */
(() => {
  const AP = window.AP;
  if (!AP) return;
  const { S, UI, h, $, $$, mmss, kfmt } = AP;
  const SVGNS = "http://www.w3.org/2000/svg";
  const sv = (tag, attrs = {}, ...hijos) => {
    const e = document.createElementNS(SVGNS, tag);
    for (const [k, v] of Object.entries(attrs)) if (v != null && v !== false) e.setAttribute(k, v);
    hijos.forEach((c) => c && e.append(c));
    return e;
  };
  const reducido = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const dec = (n, d = 1) => n.toFixed(d).replace(".", ",");
  const seg = (ms) => (ms >= 10000 ? `${Math.round(ms / 1000)} s` : `${dec(ms / 1000)} s`);
  const crono = (ms) => { const s = Math.max(0, Math.floor(ms / 1000)); return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`; };
  const hoyMs = (hora) => { const [a, b, c] = String(hora || "").split(":").map(Number); if ([a, b, c].some(Number.isNaN)) return null; const d = new Date(); d.setHours(a, b, c, 0); return d.getTime(); };

  // ------------------------------------------------------------ estado propio
  const O = { tareas: new Map(), traza: [], plegado: false, plegadoRev: true, filtro: null, popover: false, inicioVisto: new Map(), crono: null };
  // §0 Estéreo · flujo (2026-11-09): el flujo de agentes es el centro de la vista de reunión y llega DESPLEGADO. La preferencia «plegada» del diseño anterior era el valor por defecto de entonces y no una elección:
  // una sola vez (`apuntes_orq_v` = «2») se descarta; a partir de ahí lo que el usuario pliegue se recuerda.
  try {
    if (localStorage.getItem("apuntes_orq_v") !== "2") { localStorage.removeItem("apuntes_orq_plegado"); localStorage.setItem("apuntes_orq_v", "2"); }
    const v = localStorage.getItem("apuntes_orq_plegado"); if (v === "0" || v === "1") O.plegado = v === "1";
  } catch { /* sin almacenamiento: desplegada */ }

  // Nodos: todos existen en la app. `local` = sin modelo de Claude. `discreto` = tarea con inicio y fin (lleva anillo mientras trabaja).
  // La sala va primero (arriba) y el micro después, como en la cabecera. `canal` = nodo de captura con su punto y su medidor.
  const NODOS = [
    { id: "reunion", mono: "R", nombre: "Reunión", completo: "Escucha del audio de la reunión (captura)", col: 0, fila: 0, local: true, canal: "reunion" },
    { id: "micro", mono: "M", nombre: "Micro", completo: "Escucha del micrófono (captura)", col: 0, fila: 1, local: true, canal: "yo" },
    { id: "transcriptor", mono: "TR", nombre: "Transcriptor", completo: "Transcriptor (Whisper, local)", col: 1, fila: 0, local: true, discreto: true },
    { id: "contexto", mono: "CX", nombre: "Contexto", completo: "Contexto (resumen de los ficheros del proyecto)", col: 1, fila: 1, discreto: true, tarea: "digest" },
    { id: "monitor", mono: "MO", nombre: "Monitor", completo: "Monitor (asistente local: revisa la conversación cada 30 s, detecta señales y definiciones y decide a quién le toca intervenir; sin modelo)", col: 2, fila: 0, local: true },
    { id: "equipo", mono: "EQ", nombre: "Equipo", completo: "Equipo (Capitán, Lupa, Arquitecto, Auditor y Sherpa: cada intervención es una llamada al modelo; el Asesor responde a las preguntas del cliente). Un clic abre u oculta su detalle", col: 3, fila: 0.5, discreto: true, tarea: "equipo" },
    { id: "verificador", mono: "VE", nombre: "Verificador", completo: "Verificador de contradicciones", col: 4, fila: 0, discreto: true, tarea: "contradicciones_confirmar" },
    { id: "consultas", mono: "PR", nombre: "Consultas", completo: "Consultas («Pregúntale»: una llamada por pregunta, solo si la lanzas)", col: 4, fila: 1, discreto: true, tarea: "consulta" },
    { id: "redactor", mono: "RE", nombre: "Redactor", completo: "Redactor del resumen final", col: 5, fila: 0.5, discreto: true, tarea: "final" },
    { id: "pulidor", mono: "PU", nombre: "Pulidor", completo: "Pulidor (solo si se pulsa «Pulir con Opus»)", col: 6, fila: 0.5, discreto: true, tarea: "pulido" },
  ];
  // Rótulo de cada columna (texto fijo y explicativo: qué hace esa etapa). `ancho` = pistas que ocupa (la segunda es el hueco hasta la columna siguiente)
  const ETAPAS = [["Escucha", 1], ["Transcribe y lee", 2], ["Vigila", 1], ["Analiza", 1], ["Comprueba", 1], ["Redacta", 1], ["Pule", 1]];
  // `jog`: dónde hace el quiebro cuando los dos extremos no están a la misma altura. «destino» = junto al nodo que recibe (las entradas de un mismo nodo llegan por tramos largos y distintos);
  // «origen» = junto al nodo que emite (las salidas de un mismo nodo salen por tramos largos y distintos). `col`: color de la voz que sale (solo de los canales); el resto, degradado sala→micro.
  const ENLACES = [
    { a: "reunion", b: "transcriptor", etq: "audio", col: "sala" }, { a: "micro", b: "transcriptor", etq: "audio", col: "micro", jog: "destino" },
    { a: "transcriptor", b: "monitor", etq: "texto" }, { a: "monitor", b: "equipo", etq: "señales", jog: "destino" }, { a: "contexto", b: "equipo", etq: "contexto", jog: "destino" },
    { a: "equipo", b: "verificador", etq: "contradicciones", jog: "origen" }, { a: "equipo", b: "consultas", etq: "preguntas", jog: "origen" },
    { a: "verificador", b: "redactor", etq: "confirmado", jog: "destino" }, { a: "redactor", b: "pulidor", etq: "resumen" },
  ];
  const JOG = 10;   // px del quiebro respecto al nodo
  const AGENTES_EQUIPO = ["coordinador", "funcional", "constructor", "revisor", "analista", "estratega", "asesor"];   // el Estratega y el asesor (respuestas y «Profundizar») también trabajan bajo el nodo «Equipo"   // «analista» = el análisis generalista de las cadencias de 5 y 10 min
  // Nombres, monogramas e iconos: UN solo mapa (nombres.js). Capitán, Lupa, Arquitecto, Auditor y Sherpa son los cinco del equipo; Monitor y Asesor completan la tira.
  const NOMBRE_AGENTE = { "monitor-feed": "Minuto a minuto del Monitor", equipo: "Equipo" };
  const MONO_PERFIL = {};
  for (const k of ["monitor", "coordinador", "funcional", "constructor", "revisor", "analista", "estratega", "asesor"]) { NOMBRE_AGENTE[k] = AP.nombreAgente(k); MONO_PERFIL[k] = AP.agente(k).mono; }
  const ETQ = { espera: "En espera", trabajando: "Trabajando", hecho: "Hecho", error: "Error", omitido: "Omitido" };
  const AVATARES = ["monitor", "coordinador", "funcional", "constructor", "revisor", "estratega", "asesor"].map((k) => [k, AP.agente(k).mono, AP.agente(k).nombre]);   // el orden de la tira
  const AV_EQUIPO = ["coordinador", "funcional", "constructor", "revisor", "estratega"];   // los cinco del nodo «Equipo»: Capitán, Lupa, Arquitecto, Auditor y Sherpa
  const DOM = { avatares: {}, avEq: {}, vu: {}, nodos: {}, monos: {}, enlaces: {}, svg: null, defs: null, linea: {}, activos: [] };

  // ------------------------------------------------------------ datos reales
  const tareasDe = (agente) => [...O.tareas.values()].filter((t) => (agente === "equipo" ? AGENTES_EQUIPO.includes(t.agente) : t.agente === agente)).sort((a, b) => String(a.id).localeCompare(String(b.id), "es", { numeric: true }));
  const ultima = (agente) => { const l = tareasDe(agente); return l.length ? l[l.length - 1] : null; };
  const enCurso = (agente) => tareasDe(agente).filter((t) => t.estado === "en_curso");
  const inicioDe = (t) => { if (!O.inicioVisto.has(t.id)) O.inicioVisto.set(t.id, hoyMs(t.hora) || Date.now()); return O.inicioVisto.get(t.id); };
  const cfgModelo = (tarea) => { const m = UI.info && UI.info.config && UI.info.config.modelos; return m && tarea ? m[tarea] : null; };
  const palabrasDe = (fuente) => S.segmentos.filter((x) => x.fuente === fuente).reduce((n, x) => n + (x.texto.match(/\w+/g) || []).length, 0);
  const ultimoSeg = (fuente) => { for (let i = S.segmentos.length - 1; i >= 0; i--) if (S.segmentos[i].fuente === fuente) return S.segmentos[i]; return null; };
  const tokensDe = (t) => (t.tokens != null ? `${kfmt(t.tokens)} tokens` : null);

  function estadoNodo(n) {
    const a = S.analisis || {}, tr = S.transcripcion, fin = ["revision", "terminando"].includes(S.estado);
    const res = { estado: "espera", partes: [] };
    const modelo = n.local ? "local" : (ultima(n.id) && ultima(n.id).modelo) || cfgModelo(n.tarea);
    if (n.id === "micro" || n.id === "reunion") {
      const f = n.id === "micro" ? "yo" : "reunion", err = S.captura && S.captura.errores && S.captura.errores[f];
      const u = ultimoSeg(f), p = palabrasDe(f);
      if (S.simulacion) { res.estado = "omitido"; res.partes = ["simulación"]; }
      else if (err) { res.estado = "error"; res.partes = [String(err).slice(0, 60)]; }
      else if (S.estado === "grabando") res.estado = "trabajando";
      else if (S.estado === "pausada") res.estado = "espera";
      else if (fin) res.estado = "hecho";
      if (u) res.partes.push(`${u.mmss} · ${p} palabras`);
      res.activo = res.estado === "trabajando";
      res.sinAnillo = true;
      res.modelo = "captura";
      return res;
    }
    if (n.id === "monitor") {
      const m = (S.equipo && S.equipo.monitor) || {};
      if (S.estado === "grabando") res.estado = "trabajando";
      else if (S.estado === "pausada") res.estado = "espera";
      else if (fin) res.estado = "hecho";
      if (m.hace_s != null && S.estado === "grabando") res.partes.push(`pasada hace ${Math.round(m.hace_s)} s`, `${m.senales || 0} señal${m.senales === 1 ? "" : "es"}`);
      res.sinAnillo = true; res.modelo = "local";
      return res;
    }
    res.modelo = modelo;
    if (n.id === "transcriptor") {
      res.sinAnillo = true;   // local y en paralelo: no lleva anillo, su luz es el medidor
      const curso = enCurso("transcriptor"), ult = ultima("transcriptor");
      if (S.simulacion) { res.estado = "omitido"; res.modelo = "local"; res.partes = ["simulación sin audio"]; return res; }
      if (tr && tr.estado === "error") { res.estado = "error"; res.partes = [String(tr.error || "").slice(0, 60)]; return res; }
      // Estado de la cola. Con la máquina justa el transcriptor casi siempre está trabajando: también se dice entonces, que es cuando importa
      const cola = [];
      if (tr && AP.retrasoDe(tr) > 3) cola.push(`retraso ${Math.round(AP.retrasoDe(tr))} s`);
      if (tr && tr.rapido) cola.push("modo rápido");   // hay cola de texto útil: decodificación más barata hasta vaciarla
      if (tr && tr.rezagado_s > 1) cola.push(`audio atrasado ${Math.round(tr.rezagado_s)} s`);   // lo que no llegó a tiempo para el directo: se transcribe en los huecos y entra en su minuto
      if (tr && tr.aplazado_s > 3) cola.push(`eco en espera ${Math.round(tr.aplazado_s)} s`);   // Micro que solo repite a Reunión: se transcribe cuando no hay nada útil esperando
      if (tr && tr.eco_descartado_s > 1) cola.push(`eco descartado ${Math.round(tr.eco_descartado_s)} s`);   // eco que no cupo en su espera: no se transcribe y el acta lo anota
      if (curso.length) { res.estado = "trabajando"; res.curso = curso[0]; res.partes = [curso[0].tramo || null, ...cola].filter(Boolean); return res; }
      if (ult) {
        res.estado = ult.estado === "error" ? "error" : "hecho";
        if (ult.ms != null) res.partes.push(seg(ult.ms));
        if (ult.palabras != null) res.partes.push(`${ult.palabras} palabras`);
      }
      res.partes.push(...cola);
      return res;
    }
    const curso = enCurso(n.id), ult = ultima(n.id);
    if (n.id === "equipo") res.modelo = (curso[0] || ult || {}).modelo || cfgModelo("equipo") || "haiku";
    if (curso.length) { res.estado = "trabajando"; res.curso = curso[0]; if (n.id === "equipo") res.partes.push(curso[0].nombre); if (curso[0].tramo) res.partes.push(curso[0].tramo); return res; }
    if (ult) {
      res.estado = ult.estado === "error" ? "error" : "hecho";
      if (ult.estado === "error") res.partes.push(String(ult.error || "").slice(0, 50) || "sin respuesta");
      else {
        if (n.id === "equipo") res.partes.push(ult.nombre);
        if (ult.tramo) res.partes.push(ult.tramo);
        if (ult.ms != null) res.partes.push(seg(ult.ms));
        const t = tokensDe(ult); if (t) res.partes.push(t);
      }
    }
    if (n.id === "contexto" && !ult) {
      const o = (S.digest || {}).origen;
      if (o === "cache") { res.estado = "hecho"; res.partes = ["ya preparado antes"]; }
      else if (o === "vacio") { res.estado = "omitido"; res.partes = ["sin contenido útil"]; }
      else if (o === "sin_proyecto") { res.estado = "omitido"; res.partes = ["sin proyecto"]; }
      else if (o === "contexto_usuario") { res.estado = "hecho"; res.partes = ["el que aceptaste"]; }
      else if (o === "error") { res.estado = "error"; res.partes = ["no disponible"]; }
    }
    if (n.id === "contexto" && ult && ult.estado !== "error" && (S.digest || {}).origen === "cache") res.partes = ["ya preparado antes"];
    if (n.id === "equipo" && !ult) {
      const pr = S.equipo && S.equipo.presupuesto;
      if (S.sesion && S.sesion.cadencia !== "equipo") res.partes = ["no habla en este modo"];
      else if (pr && pr.nivel === "agotado") { res.estado = "omitido"; res.partes = ["sin presupuesto esta hora"]; }
      else res.partes = ["aún no ha intervenido"];
    }
    if (n.id === "equipo" && a.bloqueo && S.estado !== "revision") { res.estado = "error"; res.partes = [a.bloqueo.tipo === "limite" ? "límite del plan" : "sesión no iniciada"]; }
    if (n.id === "analista") {
      const om = a.ultimo_omitido;
      if (a.bloqueo && S.estado !== "revision") { res.estado = "error"; res.partes = [a.bloqueo.tipo === "limite" ? "límite del plan" : "sesión no iniciada"]; }
      else if (om && (!ult || String(om.hora) > String(ult.hora || ""))) { res.estado = "omitido"; res.partes = [`${om.palabras} palabras (mín. ${om.minimo})`]; }
      else if (!ult && a.proximo_en != null && S.estado === "grabando") res.partes = [`próximo en ${mmss(a.proximo_en)}`];
    }
    if (n.id === "verificador" && !ult && fin) {
      const hay = S.tarjetas.some((t) => t.estado === "posible");
      if (!hay) { res.estado = "omitido"; res.partes = ["sin candidatas"]; }
    }
    if (n.id === "redactor" && !ult && fin && S.revision && S.revision.estado !== "generando") { res.estado = "omitido"; res.partes = ["sin contenido que resumir"]; }
    if (n.id === "pulidor" && !ult) res.partes = ["solo si se pulsa"];
    if (n.id === "consultas" && !ult) res.partes = ["solo si preguntas"];
    return res;
  }

  // ------------------------------------------------------------ construcción
  function construir() {
    const orq = $("#orq");
    if (!orq || DOM.raiz) return;
    DOM.raiz = orq;
    const ind = h("span", { class: "ind", "aria-hidden": "true" });
    const est = h("span", { class: "orq-estado t-body-m", id: "orq-estado", "aria-live": "polite" });
    const barra = h("span", { class: "barra-pal", id: "orq-barra", "aria-hidden": "true" }, h("i"));
    const pal = h("span", { class: "orq-pal t-meta", id: "orq-pal" });
    const prox = h("span", { class: "orq-prox t-meta", id: "orq-prox" });
    const ult = h("span", { class: "orq-ult t-meta", id: "orq-ult" });
    const res = h("span", { class: "orq-resumen t-meta", id: "orq-resumen", "aria-live": "off" });
    const reg = h("button", { class: "btn btn-ghost btn-mini", type: "button", id: "orq-registro", "aria-haspopup": "dialog", "aria-expanded": "false",
      onclick: (ev) => { ev.stopPropagation(); O.filtro = null; abrirRegistro(); } }, "Registro");
    const plegar = h("button", { class: "btn btn-ghost btn-mini", type: "button", id: "orq-plegar", "aria-expanded": String(!O.plegado), "aria-controls": "orq-cuerpo",
      title: "Plegar o desplegar el flujo de agentes", onclick: () => {
        if (document.body.dataset.vista === "revision") O.plegadoRev = !O.plegadoRev;   // en la revisión llega desplegada; plegarla no cambia la preferencia de la reunión
        else { O.plegado = !O.plegado; try { localStorage.setItem("apuntes_orq_plegado", O.plegado ? "1" : "0"); } catch { /* ok */ } }
        aplicarPliegue(true);
      } }, "Plegar");
    // Tira plegada (36 px): iniciales de los agentes; solo "trabaja" el que tiene una llamada abierta (evento `tarea`). Un clic en la tira despliega el detalle.
    const avatares = h("span", { class: "orq-avatares", role: "group", "aria-label": "Agentes del equipo" },
      AVATARES.map(([id, mono, nombre]) => { const ag = AP.agente(id); const a = h("span", { class: "av ag-av", "data-agente": id, "data-estado": "espera", title: nombre + ": en espera", style: `--ag: ${ag.color}` }, AP.icono(ag.icono, "av-ic")); DOM.avatares[id] = a; return a; }));
    const linea = h("div", { class: "orq-linea" }, ind, avatares, h("div", { class: "orq-l-txt" }, est, res, h("span", { class: "orq-fila-barra" }, barra, pal, prox), ult),
      h("span", { class: "orq-acc" }, reg, plegar));
    linea.addEventListener("click", (ev) => { if (!ev.target.closest("button, a, input")) plegar.click(); });
    Object.assign(DOM.linea, { ind, est, res, barra, pal, prox, ult, reg, plegar });
    const cuerpo = h("div", { class: "orq-cuerpo", id: "orq-cuerpo" });
    DOM.svg = sv("svg", { class: "orq-svg", "aria-hidden": "true" });
    DOM.defs = sv("defs");
    DOM.svg.append(DOM.defs);
    cuerpo.append(DOM.svg);
    // rótulos de etapa, uno por columna
    ETAPAS.forEach(([txt, ancho], i) => cuerpo.append(h("span", { class: "orq-etapa", style: `grid-column: ${2 * i + 1} / span ${ancho}` }, txt)));
    NODOS.forEach((n) => {
      const marca = sv("svg", { class: "nodo-marca", viewBox: "0 0 16 16", "aria-hidden": "true" }, sv("path", { d: "M4 8.4l2.7 2.7L12 5.6", pathLength: "100" }));
      const mono = h("span", { class: "mono" + (n.local ? " local" : ""), "aria-hidden": "true" }, n.mono);
      const l1 = h("span", { class: "nodo-l1" });
      if (n.canal) l1.append(h("i", { class: "canal-dot", "aria-hidden": "true" }));
      l1.append(h("span", { class: "nodo-nombre" }, n.nombre), marca);
      if (n.canal) {   // medidor del canal: los MISMOS niveles reales que los de la cabecera (AP.hooks.medidor); sin señal, apagado
        const vu = h("span", { class: "nodo-vu", "aria-hidden": "true" }, h("i"), h("i"), h("i"), h("i"), h("i"));
        DOM.vu[n.canal] = vu; l1.append(vu);
      }
      const partes = [l1];
      if (n.id === "equipo") {   // los cinco del equipo, con el mismo icono y color que la tira plegada; el que tiene una llamada abierta lleva el anillo
        partes.push(h("span", { class: "nodo-av", role: "group", "aria-label": "Agentes del equipo" }, AV_EQUIPO.map((id) => {
          const ag = AP.agente(id), el = h("span", { class: "av ag-av", "data-agente": id, "data-estado": "espera", title: ag.nombre + ": en espera", style: `--ag: ${ag.color}` }, AP.icono(ag.icono, "av-ic"));
          DOM.avEq[id] = el; return el;
        })));
      }
      partes.push(h("span", { class: "nodo-l2 t-meta" }));
      const alto = n.fila === 0.5;
      const b = h("button", { class: "nodo" + (n.canal ? " nodo-canal" : "") + (alto ? " nodo-alto" : ""), type: "button", "data-nodo": n.id, "data-estado": "espera", title: n.completo,
        ...(n.id === "equipo" ? { "aria-expanded": "false", "aria-controls": "orq-equipo" } : {}),
        onclick: (ev) => { ev.stopPropagation(); if (n.id === "equipo") detalleEquipo(); else { O.filtro = n.id; abrirRegistro(); } } },
      mono, h("span", { class: "nodo-t" }, ...partes));
      b.style.gridColumn = String(n.col * 2 + 1);
      b.style.gridRow = alto ? "2 / span 2" : String(n.fila + 2);
      DOM.nodos[n.id] = b; DOM.monos[n.id] = mono;
      cuerpo.append(b);
    });
    // conectores: un degradado sala→micro POR conector (userSpaceOnUse: con un trazo perfectamente horizontal la caja del objeto mide 0 de alto y un degradado relativo no pinta)
    ENLACES.forEach((en) => {
      const id = "gr-" + en.a + "-" + en.b;
      let grad = null;
      if (!en.col) {
        grad = sv("linearGradient", { id, gradientUnits: "userSpaceOnUse", x1: 0, y1: 0, x2: 1, y2: 0 }, sv("stop", { class: "gs-sala", offset: "0" }), sv("stop", { class: "gs-micro", offset: "1" }));
        DOM.defs.append(grad);
      }
      const p = sv("path", { class: "enlace" + (en.col ? " de-" + en.col : ""), fill: "none" });
      const pulso = sv("path", { class: "enlace-pulso", fill: "none", pathLength: "100" });
      const haz = sv("path", { class: "haz", fill: "none" }), hazG = sv("path", { class: "haz-g", fill: "none" });
      const etq = sv("text", { class: "enlace-etq", "text-anchor": "middle", dy: ".35em" }); etq.textContent = en.etq;
      if (grad) { const u = `url(#${id})`; p.style.stroke = u; haz.style.stroke = u; pulso.style.stroke = u; }
      DOM.svg.append(p);
      DOM.enlaces[en.a + ">" + en.b] = { ...en, p, pulso, haz, hazG, etq, grad, d: "" };
    });
    // el haz recorre SOLO los conectores que entran en el nodo que trabaja (cada uno con su degradado); los pulsos de fin de tarea van por encima
    DOM.svg.append(...Object.values(DOM.enlaces).map((e) => e.hazG), ...Object.values(DOM.enlaces).map((e) => e.haz), ...Object.values(DOM.enlaces).map((e) => e.pulso), ...Object.values(DOM.enlaces).map((e) => e.etq));
    orq.replaceChildren(linea, cuerpo);
    aplicarPliegue();
    // alturas que fijan lo de alrededor: la cabecera (puede crecer si el tema envuelve) y la banda (su línea crece con el texto)
    const medir = (el, v) => new ResizeObserver(() => { const a = Math.ceil(el.getBoundingClientRect().height); if (a > 0) document.documentElement.style.setProperty(v, a + "px"); }).observe(el);
    medir($("#cab"), "--top-h"); medir(orq, "--orq-h");
    new ResizeObserver(() => trazarEnlaces()).observe(cuerpo);
    window.addEventListener("resize", () => aplicarPliegue());
    new MutationObserver(() => aplicarPliegue()).observe(document.body, { attributes: true, attributeFilter: ["data-vista", "data-modo"] });
    document.addEventListener("click", (ev) => { if (O.popover && !ev.target.closest(".registro")) cerrarRegistro(); });
    document.addEventListener("keydown", (ev) => {
      if (ev.key !== "Escape") return;
      if (O.popover) { cerrarRegistro(); DOM.linea.reg.focus(); }
      else if (detalleAbierto()) { detalleEquipo(false); DOM.nodos.equipo.focus(); }   // Esc cierra el detalle y devuelve el foco al nodo «Equipo»
    });
    if (document.fonts && document.fonts.ready) document.fonts.ready.then(() => trazarEnlaces());   // el ancho de los rótulos depende de la tipografía
    new MutationObserver(() => trazarEnlaces()).observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme", "class"] });
  }

  // Plegado: altura interpolada (260 ms). En la revisión llega desplegada; en el Modo reunión y en ventanas estrechas, siempre plegada a su línea
  const plegadoEfectivo = () => document.body.dataset.modo === "reunion" || window.innerWidth < 1100 || (document.body.dataset.vista === "revision" ? O.plegadoRev : O.plegado);
  function aplicarPliegue(anima) {
    if (!DOM.raiz) return;
    const pleg = plegadoEfectivo(), usuario = document.body.dataset.vista === "revision" ? O.plegadoRev : O.plegado;
    if (DOM.raiz.dataset.plegado !== String(pleg)) {
      if (anima && !reducido()) {
        DOM.raiz.classList.add("anima");   // el recorte solo dura el pliegue
        const fin = (ev) => { if (ev && ev.propertyName && ev.propertyName !== "height") return; DOM.raiz.classList.remove("anima"); DOM.raiz.removeEventListener("transitionend", fin); DOM.raiz.removeEventListener("transitioncancel", fin); };
        DOM.raiz.addEventListener("transitionend", fin); DOM.raiz.addEventListener("transitioncancel", fin);
      }
      DOM.raiz.dataset.plegado = String(pleg);
    }
    DOM.linea.plegar.setAttribute("aria-expanded", String(!usuario));
    DOM.linea.plegar.textContent = usuario ? "Ver flujo" : "Plegar";
    if ((pleg || document.body.dataset.vista !== "reunion") && detalleAbierto()) detalleEquipo(false);   // el detalle cuelga de la banda desplegada de la reunión
    requestAnimationFrame(trazarEnlaces);
  }

  // Detalle del equipo (#orq-equipo: tarjetas de agente, definiciones y minuto a minuto): se abre y se cierra SOLO con el nodo «Equipo» (o la paleta); desplegar la banda ya no lo abre
  const detalleAbierto = () => { const p = $("#orq-equipo"); return !!p && p.dataset.abierto === "true"; };
  function detalleEquipo(abrir) {
    const p = $("#orq-equipo"); if (!p || !DOM.nodos.equipo) return;
    const nuevo = abrir == null ? !detalleAbierto() : !!abrir;
    if (nuevo && DOM.raiz.dataset.plegado === "true") {   // desde la paleta con la banda plegada: se despliega primero (si la ventana o el Modo reunión lo impiden, no hay detalle)
      if (plegadoEfectivo() && (document.body.dataset.modo === "reunion" || window.innerWidth < 1100 || document.body.dataset.vista === "revision")) return;
      O.plegado = false; try { localStorage.setItem("apuntes_orq_plegado", "0"); } catch { /* ok */ } aplicarPliegue(true);
    }
    p.dataset.abierto = String(nuevo);
    DOM.nodos.equipo.setAttribute("aria-expanded", String(nuevo));
    if (nuevo) cerrarRegistro();
  }
  AP.detalleEquipo = detalleEquipo;

  // Conectores: ortogonales, entre el borde derecho de un nodo y el izquierdo del siguiente (medidos en el DOM). Cada conector lleva su rótulo en el tramo horizontal
  // más largo (el que no comparte con otro conector del mismo nodo); si no cabe (rótulo + 12 px) se oculta entero, nunca se corta
  function trazarEnlaces() {
    if (!DOM.svg || DOM.raiz.dataset.plegado === "true") return;
    const base = DOM.svg.parentElement.getBoundingClientRect();
    if (!base.width) return;
    DOM.svg.setAttribute("viewBox", `0 0 ${base.width} ${base.height}`);
    for (const e of Object.values(DOM.enlaces)) {
      const A = DOM.nodos[e.a].getBoundingClientRect(), B = DOM.nodos[e.b].getBoundingClientRect();
      const x1 = A.right - base.left, y1 = A.top + A.height / 2 - base.top, x2 = B.left - base.left, y2 = B.top + B.height / 2 - base.top;
      let d, t0, t1, ty;   // tramo del rótulo
      if (Math.abs(y1 - y2) < 1) { d = `M${x1},${y1} H${x2}`; t0 = x1; t1 = x2; ty = y1; }
      else if (e.jog === "origen") { const xj = x1 + JOG; d = `M${x1},${y1} H${xj} V${y2} H${x2}`; t0 = xj; t1 = x2; ty = y2; }
      else { const xj = x2 - JOG; d = `M${x1},${y1} H${xj} V${y2} H${x2}`; t0 = x1; t1 = xj; ty = y1; }
      for (const p of [e.p, e.pulso]) p.setAttribute("d", d);
      e.d = d;
      if (e.grad) { e.grad.setAttribute("x1", x1); e.grad.setAttribute("x2", x2); e.grad.setAttribute("y1", y1); e.grad.setAttribute("y2", y1); }
      // rótulo: centrado en el tramo, con un halo del color de la banda; si no cabe, fuera (display none) para que no se corte
      e.etq.classList.remove("sin-sitio");
      const ancho = e.etq.getComputedTextLength();
      if (t1 - t0 < ancho + 12) e.etq.classList.add("sin-sitio");
      else { e.etq.setAttribute("x", (t0 + t1) / 2); e.etq.setAttribute("y", ty); }
    }
    pintarHaz();
  }
  function pintarHaz() {
    for (const e of Object.values(DOM.enlaces)) {
      const on = DOM.activos.includes(e);
      if (on) { e.haz.setAttribute("d", e.d); e.hazG.setAttribute("d", e.d); }
      e.haz.classList.toggle("on", on); e.hazG.classList.toggle("on", on);
    }
  }

  // ------------------------------------------------------------ render
  let pendiente = false;
  function programar() { if (pendiente) return; pendiente = true; requestAnimationFrame(() => { pendiente = false; render(); }); }

  const corto = (lista, tope = 30) => { const out = []; let n = 0; for (const x of lista) { if (out.length && n + x.length + 3 > tope) break; out.push(x); n += x.length + 3; } return out.join(" · "); };
  function render() {
    construir();
    if (!DOM.raiz) return;
    const estados = {};
    for (const n of NODOS) {
      const e = estadoNodo(n); estados[n.id] = e;
      const b = DOM.nodos[n.id];
      if (b.dataset.estado !== e.estado) { b.dataset.estado = e.estado; }
      b.classList.toggle("sin-anillo", !!e.sinAnillo);
      const l2 = b.querySelector(".nodo-l2");
      const partes = [...(e.curso && n.id === "equipo" ? [NOMBRE_AGENTE[e.curso.agente] || e.curso.nombre] : []), e.modelo, ...(e.curso ? [crono(Date.now() - inicioDe(e.curso))] : e.partes)].filter(Boolean);
      // el nodo «Equipo» muestra el monograma del perfil que trabaja (CO, AF…) con su mismo anillo; en reposo, EQ
      const mono = n.id === "equipo" ? (e.curso && MONO_PERFIL[e.curso.agente]) || n.mono : n.mono;
      if (DOM.monos[n.id].textContent !== mono) DOM.monos[n.id].textContent = mono;
      const etq = e.sinAnillo ? ETQ[e.estado].toLowerCase().replace("trabajando", "escuchando") : ETQ[e.estado].toLowerCase();
      const lista = e.sinAnillo ? [etq, ...e.partes] : [etq, ...partes];
      const texto = lista.join(" · ");   // completo: va al tooltip y a la etiqueta accesible
      // en el nodo (48 px, dato de 11/13 que envuelve) solo cabe lo esencial: mientras trabaja, quién y cuánto lleva; en reposo, estado y lo primero
      const visible = corto(e.curso && !e.sinAnillo ? partes : lista, b.classList.contains("nodo-alto") ? 60 : 26);   // un nodo de una fila (56 px) tiene sitio para dos líneas de dato; los altos, para cuatro
      if (l2.textContent !== visible) l2.textContent = visible;
      b.setAttribute("aria-label", `${n.completo}: ${texto}`);
      b.title = `${n.completo}: ${texto}`;
    }
    // haz: solo en los conectores que ENTRAN al nodo que trabaja de verdad (con tarea abierta y anillo): lo que está leyendo
    DOM.activos = Object.values(DOM.enlaces).filter((e) => estados[e.b].estado === "trabajando" && !!estados[e.b].curso && !estados[e.b].sinAnillo);
    pintarHaz();
    for (const [id, , nombre] of AVATARES) {
      const trabaja = id !== "monitor" && enCurso(id).length > 0;
      const est = trabaja ? "trabajando" : id === "monitor" ? (S.estado === "grabando" ? "escucha" : "espera") : ultima(id) ? "hecho" : "espera";
      for (const a of [DOM.avatares[id], DOM.avEq[id]]) {   // la tira plegada y los cinco del nodo «Equipo»: el mismo estado real (solo trabaja el que tiene una llamada abierta)
        if (!a) continue;
        if (a.dataset.estado !== est) { a.dataset.estado = est; a.title = nombre + ": " + ({ trabajando: "trabajando ahora", escucha: "escuchando (local)", hecho: "ya ha intervenido", espera: "en espera" })[est]; }
      }
    }
    linea(estados);
    resumenPlegado(estados);
    ritmoCrono();
    cabecera();
    if (AP.alRenderAgentes) AP.alRenderAgentes();
  }

  // Línea del agente (fuente de verdad del estado del analista), con la microcopia de la especificación
  const miles = (n) => String(Math.round(n || 0)).replace(/\B(?=(\d{3})+(?!\d))/g, ".");
  // Línea del Monitor (modo equipo): estado real del vigía local y de quien tiene la palabra
  function lineaEquipo(estados) {
    const a = S.analisis || {}, d = DOM.linea, eq = S.equipo, m = eq.monitor || {}, pr = eq.presupuesto || {};
    const ver = estados.verificador, red = estados.redactor, pul = estados.pulidor;
    const trz = O.traza.filter((x) => x.fila === "analisis");
    const tr = S.transcripcion;
    const perfil = eq.perfiles.map((p) => ({ p, t: enCurso(p.id)[0] })).find((x) => x.t);
    let ind = "espera", txt;
    if (pul.estado === "trabajando") { ind = "confirmando"; txt = "Puliendo con opus…"; }
    else if (red.estado === "trabajando") { ind = "confirmando"; txt = `Redactando el resumen final con ${(red.curso && red.curso.modelo) || red.modelo || "sonnet"}…`; }
    else if (ver.estado === "trabajando") { ind = "confirmando"; txt = `Confirmando contradicciones con ${(ver.curso && ver.curso.modelo) || ver.modelo || "sonnet"}…`; }
    else if (perfil) { ind = "analizando"; txt = `${perfil.p.nombre} trabajando ${perfil.t.tramo ? perfil.t.tramo + " " : ""}con ${perfil.t.modelo || "haiku"}…`; }
    else if (S.estado === "revision" || S.estado === "terminando") {
      const tok = tokensTotal();
      txt = `Reunión terminada · ${eq.turnos || 0} intervencion${eq.turnos === 1 ? "" : "es"}${tok ? ` · ${kfmt(tok)} tokens` : ""}`;
    }
    else if (a.bloqueo) { ind = "error"; txt = a.bloqueo.tipo === "sesion" ? "Sesión no iniciada en Claude Code" : "Límite del plan alcanzado · equipo detenido"; }
    else if (S.estado === "pausada") { ind = "pausa"; txt = "En pausa · análisis detenido"; }
    else if (a.ultimo_error) { ind = "error"; txt = "Sin respuesta del modelo · se reintentará en la próxima intervención"; }
    else if (pr.nivel === "agotado") txt = `Monitor · sin presupuesto esta hora${pr.libera_a ? " · siguiente a las " + pr.libera_a : ""} · solo detección local`;
    else {
      const sig = eq.perfiles.filter((p) => p.siguiente).sort((x, y) => x.siguiente.en - y.siguiente.en)[0];
      const tiempo = mmss(S.t || 0), pal = `${miles(m.palabras)} palabras`;
      const cola = sig ? (sig.siguiente.motivo === "rotación" ? `${sig.nombre} habla por rotación en ${mmss(sig.siguiente.en)}` : `${sig.nombre} habla en ${mmss(sig.siguiente.en)} (${sig.siguiente.motivo})`)
        : (m.senales ? "Nadie por intervenir" : "Nadie por intervenir · sin señales");
      txt = `Monitor · ${tiempo} · ${pal} · ${cola}${pr.nivel === "ahorro" ? " · ahorro" : ""}`;
    }
    d.ind.dataset.estado = ind; d.est.textContent = txt; d.est.dataset.estado = ind;
    d.barra.hidden = d.pal.hidden = d.prox.hidden = true;
    const aviso = AP.avisoRetraso(tr, 15), retrasado = !!aviso;   // también avisa si hay audio atrasado, aunque el directo vaya casi al día
    d.ult.hidden = !retrasado; d.ult.textContent = aviso; d.ult.classList.toggle("avisa", retrasado);
    void trz;
  }

  function linea(estados) {
    if (!estados) { programar(); return; }
    const a = S.analisis || {}, d = DOM.linea, s = S.sesion;
    if (s && s.cadencia === "equipo" && S.equipo) return lineaEquipo(estados);
    const an = estados.equipo, ver = estados.verificador, red = estados.redactor, pul = estados.pulidor;
    const trz = O.traza.filter((x) => x.fila === "analisis"), ult = trz[trz.length - 1], ultAny = O.traza[O.traza.length - 1];
    const tr = S.transcripcion;
    let ind = "espera", txt;
    const modeloDe = (e, def) => (e.curso && e.curso.modelo) || e.modelo || def;
    if (pul.estado === "trabajando") { ind = "confirmando"; txt = "Puliendo con opus…"; }
    else if (red.estado === "trabajando") { ind = "confirmando"; txt = `Redactando el resumen final con ${modeloDe(red, "sonnet")}…`; }
    else if (ver.estado === "trabajando") { ind = "confirmando"; txt = `Confirmando contradicciones con ${modeloDe(ver, "sonnet")}…`; }
    else if (an.estado === "trabajando") { ind = "analizando"; txt = `Analizando ${an.curso.tramo ? an.curso.tramo + " " : ""}con ${modeloDe(an, "haiku")}${a.motivo_ultimo ? " (" + a.motivo_ultimo + ")" : ""}…`; }
    else if (S.estado === "revision" || S.estado === "terminando") {
      const n = trz.length, tok = tokensTotal();
      txt = `Reunión terminada${n ? ` · ${n} análisis` : ""}${tok ? ` · ${kfmt(tok)} tokens` : ""}`; ind = "espera";
    }
    else if (a.bloqueo) { ind = "error"; txt = a.bloqueo.tipo === "sesion" ? "Sesión no iniciada en Claude Code" : "Límite del plan alcanzado · análisis automático detenido"; }
    else if (S.estado === "pausada") { ind = "pausa"; txt = "En pausa · análisis detenido"; }
    else if (ultAny && ultAny.fila === "fallo") { ind = "error"; txt = "Sin respuesta del modelo · reintento en el próximo ciclo"; }
    else if (ultAny && ultAny.fila === "omitido" && a.ultimo_omitido) { txt = `Omitido ${mmss(ultAny.t)} · ${ultAny.palabras} palabras nuevas (mín. ${ultAny.minimo})`; }
    else if (a.modo === "adaptativo" && a.adaptativo) {   // disparo adaptativo: se mira en local cada 30 s, sin llamar al modelo
      const ad = a.adaptativo;
      if (a.palabras >= ad.palabras_senal && ad.senal && ad.enfriamiento_en > 0) txt = `Señal: ${ad.senal} · espera mínima`;
      else if (ad.senal && a.palabras < ad.palabras_senal) txt = `Escuchando · señal: ${ad.senal}`;
      else if (a.n === 0 && !(a.palabras > 0)) txt = "Escuchando · sin análisis todavía";
      else txt = "Escuchando";
    }
    else if (a.n === 0 && !(a.palabras > 0)) txt = "Escuchando · sin análisis todavía";
    else if (a.palabras != null && a.min_palabras && a.palabras >= a.min_palabras) txt = "Listo";
    else txt = "Esperando";
    if (ind === "espera" && S.estado === "grabando" && a.bloqueo == null && a.ultimo_error && !a.bloqueo) { ind = "error"; txt = "Sin respuesta del modelo · reintento en el próximo ciclo"; }
    d.ind.dataset.estado = ind;
    d.est.textContent = txt;
    d.est.dataset.estado = ind;
    // barra de palabras (la firma, 56×3), solo con dato real
    const ad = a.modo === "adaptativo" ? a.adaptativo : null;
    const minimo = ad ? (ad.senal ? ad.palabras_senal : ad.palabras_tope) : a.min_palabras;   // adaptativo: con señal se necesitan menos palabras
    const conPal = a.palabras != null && minimo > 0 && a.modo !== "manual" && S.estado === "grabando" && an.estado !== "trabajando";
    d.barra.hidden = d.pal.hidden = !conPal;
    if (conPal) {
      d.barra.firstElementChild.style.width = Math.min(56, Math.round(56 * a.palabras / minimo * 100) / 100) + "px";
      d.pal.textContent = `${a.palabras}/${minimo} palabras`;
    }
    d.prox.hidden = !((a.proximo_en != null || ad) && (S.estado === "grabando") && an.estado !== "trabajando" && !a.bloqueo);
    if (!d.prox.hidden) d.prox.textContent = ad ? `tope en ${mmss(ad.tope_en)}` : `próximo en ${mmss(a.proximo_en)}`;
    // último análisis completado (datos reales; lo que falta no se pinta)
    let u = "";
    if (ult) {
      u = ["último " + (ult.tramo || ""), ult.motivo || null, ult.modelo, ult.ms != null ? seg(ult.ms) : null, ult.tokens != null ? `${kfmt(ult.tokens)} tokens` : null,
        ult.insights + ult.objetivos + ult.checks === 0 ? "sin novedades" : null].filter((x) => x && x !== "último ").join(" · ");
    } else if (S.estado === "grabando" || S.estado === "pausada") u = "sin análisis todavía";
    if (txt.startsWith("Escuchando")) u = "";
    d.ult.hidden = !u; d.ult.textContent = u; d.ult.title = u;
    const aviso = AP.avisoRetraso(tr, 15);
    d.ult.classList.toggle("avisa", !!aviso);
    if (aviso) { d.ult.hidden = false; d.ult.textContent = aviso; }
  }
  AP.aplicarPliegueOrq = () => { if (DOM.raiz) aplicarPliegue(); };   // el Modo reunión fuerza la línea plegada sin tocar la preferencia
  AP.hooks.linea = () => render();

  // Línea plegada: «Equipo: hecho · Monitor escuchando · 3 turnos · 5,5k». Solo datos que ya existen (estados de los nodos, turnos del equipo y tokens de la sesión)
  function resumenPlegado(estados) {
    const el = DOM.linea.res;
    if (!el) return;
    const eq = estados.equipo, mon = estados.monitor;
    const etq = (e) => (e.sinAnillo ? ETQ[e.estado].toLowerCase().replace("trabajando", "escuchando") : ETQ[e.estado].toLowerCase());
    const modoEquipo = S.sesion && S.sesion.cadencia === "equipo" && S.equipo;
    const n = modoEquipo ? (S.equipo.turnos || 0) : O.traza.filter((x) => x.fila === "analisis").length;
    const tok = tokensTotal();
    // En la línea plegada, «hecho» se lee raro para un equipo que sigue escuchando: es «al día»
    const etqEquipo = ({ espera: "en espera", trabajando: "trabajando", hecho: "al día", error: "con un error", omitido: "en pausa" })[eq.estado] || etq(eq);
    const partes = [`Equipo ${etqEquipo}`, `Monitor ${etq(mon)}`, `${n} ${modoEquipo ? (n === 1 ? "intervención" : "intervenciones") : (n === 1 ? "análisis" : "análisis")}`];
    if (tok) partes.push(kfmt(tok) + " tokens");
    const txt = partes.join(" · ");
    if (el.textContent !== txt) el.textContent = txt;
  }

  function tokensTotal() {
    const c = S.consumo; if (!c || !c.llamadas) return 0;
    return c.total.entrada + c.total.cache_creacion + c.total.cache_lectura + c.total.salida;
  }

  // Cabecera: ●REC, retraso de transcripción bajo «Reunión» y medidores
  function cabecera() {
    const rec = $("#r-rec");
    if (rec) rec.dataset.estado = S.estado === "grabando" ? "grabando" : "parado";
    const tr = S.transcripcion, r = $("#r-retraso");
    if (r) {
      const p = AP.retrasoDe(tr);
      r.hidden = !(p > 5);
      if (p > 5) r.textContent = `+${Math.round(p)} s`;
      $("#vu-reunion").classList.toggle("retraso", p > 15 || (tr && tr.rezagado_s > 1));   // audio atrasado: el medidor también avisa, aunque `retraso_s` ya no suba de ~45 s
    }
  }
  AP.hooks.medidor = (f, v) => {
    const n = Math.round(v / 20);   // mismos umbrales para la cabecera y para los nodos «Reunión» y «Micro» de la banda (nivel real del audio; sin él, apagado)
    for (const el of [$("#vu-" + f), DOM.vu[f]]) if (el) [...el.children].forEach((i, k) => i.classList.toggle("on", k < n));
  };

  // Pie: contexto a la izquierda, tokens a la derecha; cambia en seco
  AP.hooks.pie = () => {
    const d = S.digest || {};
    const nombres = d.ficheros || [];
    let ctx = "";
    if (d.origen === "vacio") ctx = "Contexto · sin contenido útil en el proyecto";
    else if (d.origen === "sin_proyecto") ctx = "Contexto · sin proyecto";
    else if (d.origen === "contexto_usuario") ctx = "Contexto · el que aceptaste antes de empezar";
    else if (d.origen === "error") ctx = "Contexto · no disponible";
    else if (nombres.length) ctx = `Contexto · ${nombres.length} fichero${nombres.length === 1 ? "" : "s"} · ${nombres.slice(0, 2).join(", ")}${nombres.length > 2 ? ` +${nombres.length - 2}` : ""}`;
    else if (d.origen) ctx = "Contexto · " + ({ generado: "resumido ahora", cache: "desde caché" }[d.origen] || d.origen);
    const pc = $("#p-digest"); pc.textContent = ctx; pc.title = nombres.join("\n");
    const tr = S.transcripcion;
    $("#p-trans").textContent = tr && tr.estado === "error" ? tr.error : "";
    const c = S.consumo, cuenta = (k) => Object.entries((c && c.por_modelo) || {}).filter(([m]) => m.toLowerCase().includes(k)).reduce((n, [, u]) => n + u.llamadas, 0);
    $("#p-consumo").textContent = (S.estado === "inactivo") ? "" : `Tokens sesión ${kfmt(tokensTotal())} · haiku ${cuenta("haiku")} · sonnet ${cuenta("sonnet")} · opus ${cuenta("opus")}`;
  };

  // El cronómetro de un nodo que trabaja se actualiza cada segundo SOLO mientras haya una tarea en curso
  function ritmoCrono() {
    const hay = [...O.tareas.values()].some((t) => t.estado === "en_curso");
    if (hay && !O.crono) O.crono = setInterval(render, 1000);
    if (!hay && O.crono) { clearInterval(O.crono); O.crono = null; }
  }

  // ------------------------------------------------------------ animaciones puntuales (fin de tarea, conectores, enlace a columnas)
  function alTerminar(t) {
    const id = AGENTES_EQUIPO.includes(t.agente) ? "equipo" : t.agente;   // los cuatro perfiles y el análisis generalista son el nodo «Equipo»
    const b = Object.prototype.hasOwnProperty.call(DOM.nodos, id) ? DOM.nodos[id] : null;   // ojo: «constructor» es también una propiedad de todo objeto
    if (!b) return;
    if (t.estado === "ok" && !reducido()) {
      b.classList.remove("traza"); void b.offsetWidth; b.classList.add("traza");   // la marca se traza en 400 ms
      for (const e of Object.values(DOM.enlaces)) if (e.a === id && DOM.raiz.dataset.plegado !== "true") {
        const p = e.pulso;
        p.animate([{ strokeDashoffset: 14, opacity: 1 }, { strokeDashoffset: -100, opacity: 1 }], { duration: 400, easing: "cubic-bezier(.16,1,.3,1)", fill: "none" });
      }
    }
  }
  // Un trazo breve (400 ms) del Analista a la columna afectada; no mueve el scroll de nadie
  function enlazar(sel) {
    if (reducido()) return;
    const dest = $(sel), origen = DOM.nodos.equipo;
    if (!dest || !origen) return;
    const A = origen.getBoundingClientRect(), B = dest.getBoundingClientRect();
    if (!A.width || !B.width) return;
    const x1 = A.left + A.width / 2, y1 = A.bottom, x2 = B.left + 12, y2 = B.top + B.height / 2;
    const cap = sv("svg", { class: "enlace-col", "aria-hidden": "true", width: window.innerWidth, height: window.innerHeight },
      sv("path", { d: `M${x1},${y1} C${x1},${(y1 + y2) / 2} ${x2},${(y1 + y2) / 2} ${x2},${y2 - 6}`, fill: "none", pathLength: "100" }));
    document.body.append(cap);
    const p = cap.firstChild;
    const an = p.animate([{ strokeDashoffset: 100, opacity: 1 }, { strokeDashoffset: 0, opacity: 1 }], { duration: 400, easing: "cubic-bezier(.16,1,.3,1)", fill: "forwards" });
    an.onfinish = () => cap.animate([{ opacity: 1 }, { opacity: 0 }], { duration: 400, easing: "cubic-bezier(.16,1,.3,1)", fill: "forwards" }).onfinish = () => cap.remove();
  }
  AP.enlazar = enlazar;
  // Pulso de llegada en la cabecera de la columna que recibe resultados (400 ms, muelle): un halo que sube y se va
  AP.pulsoCabecera = (sel) => {
    const el = typeof sel === "string" ? $(sel) : sel;
    if (!el || reducido()) return;
    const cab = el.closest(".panel-h, .grupo-h") || el;
    cab.classList.remove("pulsa-h"); void cab.offsetWidth; cab.classList.add("pulsa-h");
  };
  // Las clases de entrada (nueva, entra, traza, pulsa-h, recibe) se retiran al terminar su animación: una con `fill-mode` ya terminada sigue contando en el compositor
  document.addEventListener("animationend", (ev) => {
    const t = ev.target; if (!(t instanceof Element)) return;
    switch (ev.animationName) {
      case "trazo": { const c = t.closest(".traza"); if (c) c.classList.remove("traza"); break; }
      case "aparece": case "sube": { const c = t.closest(".nueva, .entra"); if (c) c.classList.remove("nueva", "entra"); break; }
      case "pulsa-h": t.classList.remove("pulsa-h"); break;
      case "recibe": t.classList.remove("recibe"); break;
    }
  });

  // ------------------------------------------------------------ interruptor «Efectos» (DESIGN-visual.md §6): alto | medio | apagado, recordado en localStorage `apuntes_efectos`
  const EFECTOS = ["alto", "medio", "apagado"];
  const EF = { elegido: null };
  try { const v = localStorage.getItem("apuntes_efectos"); if (EFECTOS.includes(v)) EF.elegido = v; } catch { /* sin almacenamiento */ }
  const efectoActual = () => (EF.elegido || (document.body.dataset.modo === "reunion" ? "medio" : "alto"));   // sin elección: alto en vista completa, medio en Modo reunión
  function aplicarEfectos() {
    const v = efectoActual();
    document.body.dataset.efectos = v;
    const b = $("#b-efectos"); if (b) { b.textContent = "Efectos: " + v; b.setAttribute("aria-label", `Efectos: ${v}. Pulsa para cambiarlos`); }
    const s = $("#s-efectos"); if (s) s.value = EF.elegido || "auto";
  }
  function elegirEfectos(v) {
    EF.elegido = EFECTOS.includes(v) ? v : null;
    try { if (EF.elegido) localStorage.setItem("apuntes_efectos", EF.elegido); else localStorage.removeItem("apuntes_efectos"); } catch { /* sin almacenamiento */ }
    aplicarEfectos();
  }
  AP.efectos = { actual: efectoActual, elegir: elegirEfectos };
  const bEf = $("#b-efectos"), sEf = $("#s-efectos");
  if (bEf) bEf.addEventListener("click", () => elegirEfectos(EFECTOS[(EFECTOS.indexOf(efectoActual()) + 1) % EFECTOS.length]));
  if (sEf) sEf.addEventListener("change", () => elegirEfectos(sEf.value));
  new MutationObserver(aplicarEfectos).observe(document.body, { attributes: true, attributeFilter: ["data-modo"] });
  aplicarEfectos();

  // ------------------------------------------------------------ Registro (popover de 360 px)
  function filasRegistro() {
    const f = O.filtro;
    if (f === "monitor") {   // sus pasadas locales, con señales y puntuaciones
      const pas = ((S.monitor && S.monitor.pasadas) || []).slice(-40).reverse();
      return pas.map((p) => ({ hora: mmss(p.t), partes: [`${p.palabras} palabras`, p.senales && p.senales.length ? p.senales.join(" | ") : "sin señales",
        p.puntos ? "puntos " + Object.entries(p.puntos).map(([k, v]) => `${NOMBRE_AGENTE[k] || k} ${v}`).join(", ") : null].filter(Boolean), res: "detección local · sin modelo" }));
    }
    if (f === "monitor-feed") {
      return ((S.monitor && S.monitor.feed) || []).slice().reverse().map((e) => ({ hora: e.minuto, partes: [e.texto], res: null, apagado: e.tipo === "toca" }));
    }
    if (f) {
      return tareasDe(f).slice(-20).reverse().map((t) => ({
        hora: t.hora, partes: [t.tramo, t.modelo, t.ms != null ? seg(t.ms) : null, tokensDe(t), t.audio_s != null ? `${dec(t.audio_s)} s de audio` : null, t.palabras != null ? `${t.palabras} palabras` : null].filter(Boolean),
        res: t.estado === "en_curso" ? "en curso" : t.ok ? "ok" : "error" + (t.error ? ": " + String(t.error).slice(0, 80) : ""), error: t.estado === "error", curso: t.estado === "en_curso" }));
    }
    return O.traza.slice(-20).reverse().map(filaTraza);
  }
  function filaTraza(e) {
    if (e.fila === "analisis") return { hora: mmss(e.t), partes: [e.perfil ? `Intervención ${e.n}` : `Análisis ${e.n}`, e.perfil ? NOMBRE_AGENTE[e.perfil] : null, e.tramo, e.motivo || null, e.modelo, e.ms != null ? seg(e.ms) : null, e.tokens != null ? kfmt(e.tokens) : null, ...conteos(e)].filter(Boolean), res: null };
    if (e.fila === "omitido") return { hora: mmss(e.t), partes: ["Omitido", `${e.palabras} palabras nuevas (mín. ${e.minimo})`], res: null, apagado: true };
    return { hora: mmss(e.t), partes: ["Fallo", e.mensaje], res: null, error: true };
  }
  function conteos(e) {
    const c = [];
    if (e.insights) c.push(e.perfil ? `${e.insights} tarjeta${e.insights === 1 ? "" : "s"}` : `${e.insights} insight${e.insights === 1 ? "" : "s"}`);
    if (e.definiciones) c.push(`${e.definiciones} definición${e.definiciones === 1 ? "" : "es"}`);
    if (e.objetivos) c.push(`${e.objetivos} objetivo${e.objetivos === 1 ? "" : "s"}`);
    if (e.checks) c.push(`${e.checks} check${e.checks === 1 ? "" : "s"}`);
    return c;
  }
  AP.filaTraza = filaTraza; AP.conteos = conteos; AP.seg = seg;

  function abrirRegistro() {
    cerrarRegistro(true);
    if (detalleAbierto()) detalleEquipo(false);
    O.popover = true;
    DOM.linea.reg.setAttribute("aria-expanded", "true");
    const nodo = O.filtro ? (NODOS.find((n) => n.id === O.filtro) || (NOMBRE_AGENTE[O.filtro] ? { id: O.filtro, nombre: NOMBRE_AGENTE[O.filtro] } : null)) : null;
    const filas = filasRegistro();
    const pop = h("div", { class: "registro", role: "dialog", "aria-label": "Registro" + (nodo ? " de " + nodo.nombre : ""), tabindex: "-1" },
      h("div", { class: "registro-h" }, h("span", { class: "t-label" }, nodo ? `Registro · ${nodo.nombre}` : "Registro"),
        nodo ? h("button", { class: "btn btn-ghost btn-mini", type: "button", onclick: () => { O.filtro = null; abrirRegistro(); } }, "Ver todo") : null,
        h("button", { class: "btn btn-ghost btn-mini", type: "button", onclick: () => { cerrarRegistro(); DOM.linea.reg.focus(); } }, "Cerrar")),
      h("div", { class: "registro-l" }, filas.length ? filas.map((f) => h("div", { class: "reg-f t-meta" + (f.error ? " error" : "") + (f.apagado ? " apagado" : "") },
        h("span", { class: "reg-h" }, f.hora || ""), h("span", { class: "reg-t" }, f.partes.join(" · ")), f.res ? h("span", { class: "reg-r" + (f.error ? " error" : "") }, f.res) : null))
        : h("div", { class: "reg-vacio t-meta" }, nodo ? (O.filtro.startsWith("monitor") ? "El Monitor aún no ha hecho ninguna pasada." : "Todavía no ha trabajado en esta reunión.") : "Todavía no hay análisis.")));
    DOM.raiz.append(pop);
    pop.focus({ preventScroll: true });
  }
  function cerrarRegistro(sinFoco) {
    O.popover = false;
    DOM.linea.reg && DOM.linea.reg.setAttribute("aria-expanded", "false");
    $$(".registro").forEach((x) => x.remove());
  }
  AP.abrirRegistro = (agente) => { O.filtro = agente || null; abrirRegistro(); };

  // ------------------------------------------------------------ eventos del servidor
  function aplicarTarea(t) {
    const antes = O.tareas.get(t.id);
    O.tareas.set(t.id, { ...(antes || {}), ...t });
    return O.tareas.get(t.id);
  }
  AP.hooks.reiniciar = () => { O.tareas.clear(); O.traza = []; O.inicioVisto.clear(); programar(); };
  AP.hooks.evento = (d) => {
    switch (d.tipo) {
      case "snapshot":
        O.tareas = new Map((d.tareas || []).map((t) => [t.id, t]));
        O.traza = d.traza || [];
        O.inicioVisto.clear();
        programar();
        break;
      case "tarea": {
        const t = aplicarTarea(d);
        if (d.fase === "inicio") inicioDe(t);
        programar();
        if (d.fase === "fin") requestAnimationFrame(() => alTerminar(t));
        break;
      }
      case "traza":
        if (!O.traza.some((x) => x.id === d.id)) { const { tipo, ...e } = d; O.traza.push(e); }
        AP.trazaNueva && AP.trazaNueva(d);
        programar();
        break;
      case "estado": case "tick": case "analisis": case "tarjetas": case "consumo": case "checks":
        programar(); break;
    }
  };
  AP.O = O; AP.NODOS = NODOS;
  Object.defineProperty(AP, "traza", { get: () => O.traza });
  if (document.readyState !== "loading") construir(); else document.addEventListener("DOMContentLoaded", construir);
})();
