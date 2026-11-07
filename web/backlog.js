"use strict";
/* WhisperMeet: pantalla «Sesiones» (backlog): todas las sesiones pasadas y la lista conjunta de pendientes, ideas, decisiones, riesgos y preguntas.
   Sin llamadas al modelo: lee /api/backlog/* (los .md de sesión no se modifican nunca; el estado que marca el usuario vive en backlog\estado.json).
   Todo el texto dinámico entra como nodo de texto (nunca como HTML): el markdown del resumen se interpreta aquí con un conjunto mínimo y seguro
   (títulos, listas, negrita, cursiva, código); el HTML crudo se ve como texto y los enlaces no se siguen.
   No toca la sesión en curso: es una capa sobre las vistas, que siguen viva por debajo (body[data-backlog]). */
(() => {
  const AP = window.AP;
  if (!AP) return;
  const { h, $, api } = AP;
  const raiz = $("#v-backlog"), boton = $("#b-sesiones");
  if (!raiz || !boton) return;

  const SVGNS = "http://www.w3.org/2000/svg";
  const sv = (tag, attrs = {}, ...hijos) => {
    const e = document.createElementNS(SVGNS, tag);
    for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
    hijos.flat().forEach((c) => c && e.append(c));
    return e;
  };
  // los mismos iconos que los Hallazgos de la reunión (iconos.js): icono + color + etiqueta, nunca solo color
  const glifo = (tipo) => AP.icono(tipo, "bj-g g-" + tipo);

  const TIPOS = [["pendiente", "Pendientes", "Pendiente"], ["idea", "Ideas", "Idea"], ["decision", "Decisiones", "Decisión"], ["riesgo", "Riesgos", "Riesgo"],
    ["pregunta", "Preguntas", "Pregunta"], ["regla", "Reglas", "Regla"], ["contradiccion", "Contradicciones", "Contradicción"], ["consejo", "Consejos", "Consejo"]];
  const ETQ_TIPO = Object.fromEntries(TIPOS.map(([k, , s]) => [k, s]));
  const ETQ_ESTADO = { abierto: "Abierto", hecho: "Hecho", descartado: "Descartado", nueva: "Nueva", aprovechada: "Aprovechada", descartada: "Descartada" };
  const ETQ_SESION = { en_curso: "En curso", sin_cerrar: "Sin cerrar", interrumpida: "Interrumpida" };
  const TITULO_SESION = { en_curso: "La sesión se está grabando o se cerró hace poco", sin_cerrar: "Empezó hace más de 12 h y no llegó a cerrarse: la app se cerró sin terminar la sesión",
    interrumpida: "La sesión se interrumpió antes de terminar" };
  const ORIGEN = { bandeja: "Bandeja", local: "Copia local (proyecto compartido)", publicada: "Publicada en la carpeta compartida", proyecto: "Carpeta del proyecto" };
  const MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"];
  const fFecha = (iso) => { if (!iso) return "sin fecha"; const [a, m, d] = iso.split("-").map(Number); return `${d} ${MESES[m - 1]} ${a}`; };
  const norm = (s) => String(s || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
  const plural = (n, uno, varios) => `${n} ${n === 1 ? uno : varios}`;
  const aSeg = (m) => { const p = String(m || "").split(":").map(Number); return p.some(Number.isNaN) ? null : p.length === 3 ? p[0] * 3600 + p[1] * 60 + p[2] : p[0] * 60 + p[1]; };

  // ------------------------------------------------------------ estado de la pantalla
  const B = {
    abierto: false, cargando: false, error: "", sesiones: [], items: [], proyectos: [], avisos: [], tab: "sesiones",
    sel: null, det: {}, detTab: "resumen", q: "", proy: "", objetivo: null, busTr: "", renombrando: false, deshacer: null,
    f: { tipos: new Set(["pendiente"]), estado: "abiertos", proy: "", q: "", agrupar: "sesion" },
  };
  const D = {};   // nodos fijos

  // ------------------------------------------------------------ markdown seguro
  const RE_MIN = "\\d{1,3}:\\d{2}(?::\\d{2})?";
  function botonMin(texto, alMin, minuto) {
    return h("button", { class: "bl-min", type: "button", title: "Ir a la transcripción en ese minuto", onclick: () => alMin(minuto || texto.split(/\s*[–—-]\s*/)[0]) }, texto);
  }
  function mdSeguro(texto, alMin) {
    const out = h("div", { class: "bl-md" });
    const reMin = new RegExp(`^${RE_MIN}(?:\\s*[–—-]\\s*${RE_MIN})?$`);
    const reInline = new RegExp(`(\\*\\*[^*]+\\*\\*|\`[^\`]+\`|\\[${RE_MIN}(?:\\s*[–—-]\\s*${RE_MIN})?\\]|\\*[^*\\s][^*]*\\*)`, "g");
    const inline = (t) => {
      const frag = document.createDocumentFragment();
      let ult = 0, m;
      reInline.lastIndex = 0;
      while ((m = reInline.exec(t))) {
        if (m.index > ult) frag.append(t.slice(ult, m.index));
        const p = m[0];
        if (p.startsWith("**")) { const d = p.slice(2, -2); frag.append(alMin && reMin.test(d.trim()) ? botonMin(d.trim(), alMin) : h("b", {}, d)); }
        else if (p.startsWith("`")) frag.append(h("code", {}, p.slice(1, -1)));
        else if (p.startsWith("[")) frag.append(alMin ? botonMin(p.slice(1, -1).trim(), alMin) : p);
        else frag.append(h("i", {}, p.slice(1, -1)));
        ult = m.index + p.length;
      }
      if (ult < t.length) frag.append(t.slice(ult));
      return frag;
    };
    let lista = null, par = [], codigo = null;
    const cierraPar = () => { if (par.length) { out.append(h("p", {}, inline(par.join(" ")))); par = []; } };
    for (const linea of String(texto || "").replace(/\r\n/g, "\n").split("\n")) {
      if (/^\s*```/.test(linea)) { if (codigo) { out.append(h("pre", {}, codigo.join("\n"))); codigo = null; } else { cierraPar(); lista = null; codigo = []; } continue; }
      if (codigo) { codigo.push(linea); continue; }
      const t = linea.trim();
      let m;
      if (!t) { cierraPar(); lista = null; continue; }
      if ((m = t.match(/^(#{1,6})\s+(.*)$/))) { cierraPar(); lista = null; out.append(h(m[1].length <= 2 ? "h3" : "h4", {}, inline(m[2].replace(/\s*#+$/, "")))); }
      else if (/^([-*_])(\s*\1){2,}$/.test(t)) { cierraPar(); lista = null; out.append(h("hr")); }
      else if ((m = t.match(/^([-*+]|\d+[.)])\s+(.*)$/))) {
        cierraPar();
        const ord = /\d/.test(m[1]);
        if (!lista || lista.ord !== ord) { lista = { ord, el: h(ord ? "ol" : "ul") }; out.append(lista.el); }
        lista.el.append(h("li", {}, inline(m[2])));
      } else if ((m = t.match(/^>\s?(.*)$/))) { cierraPar(); lista = null; out.append(h("blockquote", {}, inline(m[1]))); }
      else { lista = null; par.push(t); }
    }
    if (codigo) out.append(h("pre", {}, codigo.join("\n")));
    cierraPar();
    return out;
  }

  // ------------------------------------------------------------ piezas
  const chipSesion = (s) => (ETQ_SESION[s.estado] ? h("span", { class: "bl-est " + s.estado, title: TITULO_SESION[s.estado] }, ETQ_SESION[s.estado]) : null);
  function cuentas(rec) {
    const caja = h("span", { class: "bl-cuentas" });
    TIPOS.forEach(([k, plu, sing]) => { const n = rec[k] || 0; if (n) caja.append(h("span", { class: "bl-n", title: `${plural(n, sing.toLowerCase(), plu.toLowerCase())}` }, glifo(k), h("span", {}, n))); });
    if (!caja.children.length) caja.append(h("span", { class: "t-meta soft" }, "Sin insights"));
    return caja;
  }
  const metaSesion = (s) => [s.proyecto, fFecha(s.fecha), s.inicio, s.duracion].filter(Boolean).join(" · ");

  function resaltar(texto, q) {
    if (!q) return texto;
    const frag = document.createDocumentFragment(), a = norm(texto), b = norm(q);
    // norm() puede cambiar la longitud (ligaduras): si pasa, no se resalta, pero el filtro sigue valiendo
    if (a.length !== texto.length) return texto;
    let ult = 0, i;
    while ((i = a.indexOf(b, ult)) !== -1) { if (i > ult) frag.append(texto.slice(ult, i)); frag.append(h("mark", { class: "bl-m" }, texto.slice(i, i + b.length))); ult = i + b.length; }
    if (ult < texto.length) frag.append(texto.slice(ult));
    return frag;
  }

  // ------------------------------------------------------------ carga
  async function cargar(refrescar = true) {
    if (B.cargando) return;
    B.cargando = true; B.error = "";
    pintarEstadoCarga();
    try {
      const [s, it] = await Promise.all([api("GET", "/api/backlog/sesiones?refrescar=" + (refrescar ? "true" : "false")), api("GET", "/api/backlog/items")]);
      B.sesiones = s.sesiones || []; B.proyectos = s.proyectos || []; B.items = it.items || [];
      B.avisos = [...new Set([...(s.avisos || []), ...(it.avisos || [])])];
      if (refrescar) B.det = {};
      if (B.sel && !B.sesiones.some((x) => x.id === B.sel)) B.sel = null;
    } catch (e) { B.error = "No se pudieron leer las sesiones: " + e.message; }
    B.cargando = false;
    pintarTodo();
    if (B.sel && !B.det[B.sel]) cargarDetalle(B.sel);
  }
  async function cargarDetalle(sid) {
    try { B.det[sid] = await api("GET", "/api/backlog/sesiones/" + sid); }
    catch (e) { B.det[sid] = { error: e.message }; }
    if (B.sel === sid) pintarDetalle();
  }
  function pintarEstadoCarga() {
    D.cargando.hidden = !B.cargando;
    D.actualizar.disabled = B.cargando;
  }

  // ------------------------------------------------------------ montaje
  function montar() {
    D.cargando = h("span", { class: "t-meta soft", role: "status", hidden: true }, "Leyendo sesiones…");
    D.resumen = h("span", { class: "t-meta soft", id: "bl-resumen" });
    D.tabS = h("button", { type: "button", role: "tab", id: "bl-t-sesiones", "aria-selected": "true", "aria-controls": "bl-p-sesiones", onclick: () => ponerTab("sesiones") }, "Sesiones");
    D.tabP = h("button", { type: "button", role: "tab", id: "bl-t-pendientes", "aria-selected": "false", "aria-controls": "bl-p-pendientes", onclick: () => ponerTab("pendientes") }, "Pendientes e ideas");
    D.actualizar = h("button", { class: "btn btn-ghost", id: "bl-actualizar", type: "button", title: "Vuelve a leer las carpetas de sesiones", onclick: () => cargar(true) }, "Actualizar");
    D.cerrar = h("button", { class: "btn btn-ghost", id: "bl-cerrar", type: "button", onclick: cerrar }, "Cerrar");
    D.avisos = h("details", { class: "bl-avisos", id: "bl-avisos", hidden: true });
    D.error = h("div", { class: "error bl-error", role: "alert", hidden: true });

    // --- pestaña Sesiones
    D.buscar = h("input", { class: "input", id: "bl-buscar", type: "search", placeholder: "Buscar sesiones…", autocomplete: "off", "aria-label": "Buscar sesiones",
      oninput: (e) => { B.q = e.target.value; pintarLista(); } });
    D.proy = h("select", { class: "input", id: "bl-proy", "aria-label": "Filtrar por proyecto", onchange: (e) => { B.proy = e.target.value; pintarLista(); } });
    D.cuenta = h("div", { class: "t-meta soft bl-cuenta", id: "bl-cuenta", "aria-live": "polite" });
    D.lista = h("div", { class: "bl-lista", id: "bl-lista", role: "list", "aria-label": "Sesiones" });
    D.detalle = h("section", { class: "bl-der", id: "bl-detalle", "aria-label": "Detalle de la sesión" });
    D.pS = h("div", { class: "bl-p bl-p-ses", id: "bl-p-sesiones", role: "tabpanel", "aria-labelledby": "bl-t-sesiones" },
      h("div", { class: "bl-izq" }, h("div", { class: "bl-barra" }, D.buscar, D.proy), D.cuenta, D.lista), D.detalle);

    // --- pestaña Pendientes e ideas
    D.chips = h("div", { class: "bl-chips", role: "group", "aria-label": "Tipos" });
    D.estado = h("select", { class: "input", id: "bl-f-estado", "aria-label": "Estado", onchange: (e) => { B.f.estado = e.target.value; pintarPendientes(); } },
      ...[["abiertos", "Abiertos / nuevos"], ["cerrados", "Hechos / aprovechadas"], ["descartados", "Descartados"], ["todos", "Todos los estados"]].map(([v, t]) => h("option", { value: v }, t)));
    D.fproy = h("select", { class: "input", id: "bl-f-proy", "aria-label": "Proyecto", onchange: (e) => { B.f.proy = e.target.value; pintarPendientes(); } });
    D.fq = h("input", { class: "input", id: "bl-f-q", type: "search", placeholder: "Buscar en el texto…", autocomplete: "off", "aria-label": "Buscar en los elementos", oninput: (e) => { B.f.q = e.target.value; pintarPendientes(); } });
    D.agS = h("button", { type: "button", "aria-pressed": "true", onclick: () => ponerAgrupar("sesion") }, "Por sesión");
    D.agF = h("button", { type: "button", "aria-pressed": "false", onclick: () => ponerAgrupar("fecha") }, "Por fecha");
    D.pcuenta = h("span", { class: "t-meta soft", id: "bl-p-cuenta", "aria-live": "polite" });
    D.plista = h("div", { class: "bl-plista", id: "bl-plista" });
    D.pP = h("div", { class: "bl-p bl-p-pend", id: "bl-p-pendientes", role: "tabpanel", "aria-labelledby": "bl-t-pendientes", hidden: true },
      h("div", { class: "bl-pbarra" }, D.chips,
        h("div", { class: "bl-pfiltros" }, D.estado, D.fproy, D.fq, h("div", { class: "seg seg-mini", role: "group", "aria-label": "Agrupar" }, D.agS, D.agF), D.pcuenta)),
      D.plista);

    D.toast = h("div", { class: "bl-toast", role: "status", hidden: true });
    raiz.replaceChildren(
      h("div", { class: "bl-cab" }, h("h1", { class: "t-display" }, "Sesiones"),
        h("div", { class: "seg", role: "tablist", "aria-label": "Vista" }, D.tabS, D.tabP), D.resumen, D.cargando, h("span", { class: "grow" }), D.actualizar, D.cerrar),
      D.error, D.avisos, D.pS, D.pP, D.toast);
    raiz.addEventListener("keydown", (e) => { if (e.key === "Escape" && !e.target.matches("input, select, textarea")) cerrar(); });
    boton.addEventListener("click", () => (B.abierto ? cerrar() : abrir()));
  }

  function abrir() {
    B.abierto = true;
    raiz.hidden = false;
    document.body.dataset.backlog = "1";
    boton.setAttribute("aria-pressed", "true");
    cargar(true);
    setTimeout(() => (B.tab === "sesiones" ? D.buscar : D.fq).focus({ preventScroll: true }), 0);
  }
  function cerrar() {
    B.abierto = false;
    raiz.hidden = true;
    delete document.body.dataset.backlog;
    boton.setAttribute("aria-pressed", "false");
    boton.focus({ preventScroll: true });
  }
  function ponerTab(t) {
    B.tab = t;
    D.tabS.setAttribute("aria-selected", String(t === "sesiones")); D.tabP.setAttribute("aria-selected", String(t === "pendientes"));
    D.pS.hidden = t !== "sesiones"; D.pP.hidden = t !== "pendientes";
    if (t === "pendientes") pintarPendientes(); else pintarLista();
  }
  function ponerAgrupar(a) {
    B.f.agrupar = a;
    D.agS.setAttribute("aria-pressed", String(a === "sesion")); D.agF.setAttribute("aria-pressed", String(a === "fecha"));
    pintarPendientes();
  }

  function pintarTodo() {
    D.error.hidden = !B.error; D.error.textContent = B.error;
    pintarEstadoCarga();
    const n = B.sesiones.length, el = B.items.filter((i) => i.tipo === "pendiente" && i.estado === "abierto").length;
    D.resumen.textContent = n ? `${plural(n, "sesión", "sesiones")} · ${plural(el, "pendiente abierto", "pendientes abiertos")}` : "";
    D.avisos.hidden = !B.avisos.length;
    if (B.avisos.length) {
      D.avisos.replaceChildren(h("summary", { class: "t-meta" }, `${plural(B.avisos.length, "aviso", "avisos")} al leer las sesiones`), h("ul", {}, B.avisos.map((a) => h("li", { class: "t-meta" }, a))));
    }
    for (const sel of [D.proy, D.fproy]) {
      const v = sel === D.proy ? B.proy : B.f.proy;
      sel.replaceChildren(h("option", { value: "" }, "Todos los proyectos"), ...B.proyectos.map((p) => h("option", { value: p }, p)));
      sel.value = B.proyectos.includes(v) ? v : "";
    }
    D.estado.value = B.f.estado;
    pintarLista();
    pintarDetalle();
    pintarPendientes();
  }

  // ------------------------------------------------------------ lista de sesiones
  function visibles() {
    const q = norm(B.q).trim();
    return B.sesiones.filter((s) => (!B.proy || s.proyecto === B.proy) && (!q || norm([s.tema, s.tema_original, s.proyecto, s.fecha, s.archivo, s.busqueda].join(" ")).includes(q)));
  }
  function pintarLista() {
    const v = visibles();
    D.cuenta.textContent = B.cargando ? "" : v.length === B.sesiones.length ? plural(v.length, "sesión", "sesiones") : `${v.length} de ${plural(B.sesiones.length, "sesión", "sesiones")}`;
    if (!v.length) {
      D.lista.replaceChildren(h("div", { class: "bl-vacio t-body" }, B.cargando ? "" : B.sesiones.length ? "Ninguna sesión coincide con la búsqueda." : "Todavía no hay sesiones guardadas."));
      return;
    }
    D.lista.replaceChildren(...v.map((s) => h("button", { class: "bl-ses", type: "button", role: "listitem", "data-id": s.id, "aria-current": s.id === B.sel ? "true" : null, onclick: () => seleccionar(s.id) },
      h("span", { class: "bl-ses-l1" }, h("span", { class: "t-body-m bl-ses-tema" }, s.tema), chipSesion(s)),
      h("span", { class: "t-meta bl-ses-meta" }, metaSesion(s)),
      cuentas(s.recuentos))));
  }

  function seleccionar(sid, opciones = {}) {
    B.sel = sid; B.renombrando = false; B.busTr = opciones.conservarBusqueda ? B.busTr : "";
    B.detTab = opciones.tab || "resumen";
    B.detAuto = !opciones.tab;   // sin una pestaña pedida, si la sesión no tiene resumen se abre en sus insights o, si no hay, en la transcripción
    if (!opciones.tab) B.objetivo = null;   // venir de un minuto concreto resalta la línea; abrir la sesión a secas, no
    $$ses().forEach((b) => b.setAttribute("aria-current", String(b.dataset.id === sid)));
    pintarDetalle();
    if (!B.det[sid]) cargarDetalle(sid);
  }
  const $$ses = () => [...D.lista.querySelectorAll(".bl-ses")];

  // ------------------------------------------------------------ detalle de una sesión
  function pintarDetalle() {
    if (!B.sel) { D.detalle.replaceChildren(h("div", { class: "bl-vacio t-body" }, B.sesiones.length ? "Elige una sesión para ver su resumen, sus insights y la transcripción." : "")); return; }
    const s = B.sesiones.find((x) => x.id === B.sel), d = B.det[B.sel];
    if (!s) return;
    if (d && !d.error && B.detAuto && B.detTab === "resumen" && !(d.resumen || "").trim()) { B.detTab = d.items && d.items.length ? "insights" : "transcripcion"; B.detAuto = false; }
    const cab = [];
    if (B.renombrando) {
      const inp = h("input", { class: "input bl-tema-inp", type: "text", maxlength: "120", value: s.tema, "aria-label": "Tema de la sesión", id: "bl-tema-inp",
        onkeydown: (e) => { if (e.key === "Enter") guardarTema(inp.value); else if (e.key === "Escape") { e.stopPropagation(); B.renombrando = false; pintarDetalle(); } } });
      cab.push(h("div", { class: "bl-tema-edit" }, inp, h("button", { class: "btn btn-primary", type: "button", onclick: () => guardarTema(inp.value) }, "Guardar"),
        h("button", { class: "btn btn-ghost", type: "button", onclick: () => { B.renombrando = false; pintarDetalle(); } }, "Cancelar"),
        s.renombrado ? h("button", { class: "btn btn-ghost", type: "button", title: `Volver a «${s.tema_original}»`, onclick: () => guardarTema("") }, "Restaurar original") : null));
      setTimeout(() => { const i = $("#bl-tema-inp"); if (i) { i.focus(); i.select(); } }, 0);
    } else {
      cab.push(h("div", { class: "bl-tema-l" }, h("h2", { class: "t-display bl-tema" }, s.tema), chipSesion(s),
        h("span", { class: "grow" }),
        h("button", { class: "btn btn-ghost", type: "button", id: "bl-renombrar", title: "Cambia el título que se ve aquí; el .md no se modifica", onclick: () => { B.renombrando = true; pintarDetalle(); } }, "Renombrar"),
        h("button", { class: "btn btn-ghost", type: "button", id: "bl-abrir", title: "Abre el .md con la aplicación del sistema", onclick: () => abrirMd(s.id) }, "Abrir .md")));
    }
    cab.push(h("div", { class: "t-meta bl-det-meta" }, metaSesion(s) + (s.renombrado ? ` · originalmente «${s.tema_original}»` : "")));
    cab.push(h("div", { class: "t-meta soft bl-det-meta" }, (ORIGEN[s.origen] || s.origen) + " · " + s.archivo + (s.vinculada ? ` · hay también una copia (${(ORIGEN[s.vinculada.origen] || s.vinculada.origen).toLowerCase()}: ${s.vinculada.archivo})` : "")));
    if (s.estado === "sin_cerrar") cab.push(h("div", { class: "bl-nota t-meta" }, "Esta sesión quedó en curso y no llegó a cerrarse: puede faltar el resumen y los insights finales."));
    if (s.estado === "interrumpida") cab.push(h("div", { class: "bl-nota t-meta" }, "La sesión se interrumpió antes de terminar: puede estar incompleta."));
    if (s.avisos && s.avisos.length) cab.push(h("details", { class: "bl-avisos-s" }, h("summary", { class: "t-meta" }, plural(s.avisos.length, "aviso de lectura", "avisos de lectura")), h("ul", {}, s.avisos.map((a) => h("li", { class: "t-meta" }, a)))));

    const nIns = d && d.items ? d.items.length : s.total, nTr = d && d.transcripcion ? d.transcripcion.length : s.n_transcripcion;
    const tabs = h("div", { class: "seg seg-mini", role: "tablist", "aria-label": "Contenido de la sesión" },
      ...[["resumen", "Resumen"], ["insights", `Insights ${nIns}`], ["transcripcion", `Transcripción ${nTr}`]].map(([k, t]) =>
        h("button", { type: "button", role: "tab", "data-dt": k, "aria-selected": String(B.detTab === k), onclick: () => { B.detTab = k; pintarDetalle(); } }, t)));
    const cuerpo = h("div", { class: "bl-det-cuerpo", id: "bl-det-cuerpo" });
    if (!d) cuerpo.append(h("div", { class: "t-meta soft bl-vacio" }, "Leyendo la sesión…"));
    else if (d.error) cuerpo.append(h("div", { class: "error" }, "No se pudo leer la sesión: " + d.error));
    else if (B.detTab === "resumen") cuerpo.append(vistaResumen(s, d));
    else if (B.detTab === "insights") cuerpo.append(vistaInsights(d));
    else cuerpo.append(vistaTranscripcion(s, d));
    D.detalle.replaceChildren(h("div", { class: "bl-det-cab" }, cab), tabs, cuerpo);
    if (B.detTab === "transcripcion") enfocarDestino();
  }

  function vistaResumen(s, d) {
    const caja = h("div", { class: "bl-resumen" });
    if (d.resumen && d.resumen.trim()) caja.append(mdSeguro(d.resumen, (m) => irAMinuto(s.id, m)));
    else caja.append(h("p", { class: "t-body soft" }, "Esta sesión no tiene resumen" + (s.estado === "finalizada" ? "." : " todavía (no llegó a cerrarse).")));
    if (d.definiciones && d.definiciones.length) {
      caja.append(h("h3", { class: "bl-h" }, "Definiciones"),
        h("ul", { class: "bl-defs" }, d.definiciones.map((x) => h("li", {}, x.minuto ? botonMin(x.minuto, (m) => irAMinuto(s.id, m)) : null, " ", h("b", {}, x.termino + ": "), x.definicion))));
    }
    return caja;
  }
  function vistaInsights(d) {
    if (!d.items.length) return h("p", { class: "t-body soft bl-vacio" }, "Esta sesión no tiene insights.");
    return h("div", { class: "bl-its" }, d.items.map((it) => filaItem(it, { sesion: false })));
  }
  function vistaTranscripcion(s, d) {
    const ts = d.transcripcion || [];
    const inp = h("input", { class: "input", id: "bl-busca-tr", type: "search", placeholder: "Buscar en la transcripción…", autocomplete: "off", "aria-label": "Buscar en la transcripción", value: B.busTr,
      oninput: (e) => { B.busTr = e.target.value; pintarLineas(); } });
    const info = h("span", { class: "t-meta soft", "aria-live": "polite" });
    const lineas = h("div", { class: "bl-trans", id: "bl-trans", tabindex: "0", "aria-label": "Transcripción" });
    const caja = h("div", { class: "bl-tr" }, h("div", { class: "bl-tr-barra" }, inp, info), lineas);
    function pintarLineas() {
      const q = norm(B.busTr).trim();
      const ob = !q && B.objetivo && B.objetivo.sid === s.id ? B.objetivo.t : null;
      let idx = -1;
      if (ob != null && ts.length) { let mejor = Infinity; ts.forEach((l, i) => { const dd = l.t == null ? Infinity : Math.abs(l.t - ob); if (dd < mejor) { mejor = dd; idx = i; } }); }
      const filtradas = ts.map((l, i) => [l, i]).filter(([l]) => !q || norm(l.x + " " + l.f).includes(q));
      info.textContent = !ts.length ? "" : q ? `${filtradas.length} de ${ts.length} líneas` : `${plural(ts.length, "línea", "líneas")}`;
      if (!ts.length) { lineas.replaceChildren(h("p", { class: "t-body soft bl-vacio" }, "Esta sesión no tiene transcripción.")); return; }
      if (!filtradas.length) { lineas.replaceChildren(h("p", { class: "t-body soft bl-vacio" }, "Ninguna línea coincide.")); return; }
      lineas.replaceChildren(...filtradas.map(([l, i]) => h("div", { class: "bl-lin " + (l.f === "Micro" ? "micro" : "otra") + (i === idx ? " destino" : ""), "data-t": l.t == null ? "" : String(l.t), "aria-current": i === idx ? "true" : null },
        h("span", { class: "bl-lin-m t-meta" }, l.m || ""), h("span", { class: "bl-lin-f t-meta" }, l.f), h("span", { class: "bl-lin-x" }, resaltar(l.x, q)))));
    }
    pintarLineas();
    return caja;
  }
  function enfocarDestino() {
    const el = D.detalle.querySelector(".bl-lin.destino");
    if (el) setTimeout(() => el.scrollIntoView({ block: "center" }), 0);
  }

  async function guardarTema(valor) {
    const s = B.sesiones.find((x) => x.id === B.sel);
    if (!s) return;
    try {
      const r = await api("PUT", `/api/backlog/sesiones/${s.id}/tema`, { tema: valor });
      Object.assign(s, { tema: r.tema, renombrado: r.renombrado });
      B.items.forEach((i) => { if (i.sesion_id === s.id) i.sesion_tema = r.tema; });
      B.renombrando = false;
      pintarLista(); pintarDetalle(); pintarPendientes();
    } catch (e) { toast("No se pudo guardar el tema: " + e.message); }
  }
  async function abrirMd(sid) {
    try { await api("POST", `/api/backlog/sesiones/${sid}/abrir`); toast("Abriendo el .md con la aplicación del sistema…"); }
    catch (e) { toast("No se pudo abrir el fichero: " + e.message); }
  }

  // ------------------------------------------------------------ elementos (filas compartidas por Insights y Pendientes e ideas)
  function filaItem(it, { sesion }) {
    const ctrl = it.estados && it.estados.length
      ? h("div", { class: "seg seg-mini bl-estados", role: "group", "aria-label": "Estado" }, it.estados.map((e) => h("button", { type: "button", "data-estado": e, "aria-pressed": String(it.estado === e),
        onclick: () => cambiarEstado(it, e) }, ETQ_ESTADO[e])))
      : null;
    const meta = [];
    if (sesion) meta.push(h("button", { class: "bl-sesion-l", type: "button", title: "Abrir la sesión", onclick: () => abrirSesion(it.sesion_id) }, it.sesion_tema), h("span", {}, metaFecha(it)));
    if (it.responsable) meta.push(h("span", { class: "bl-resp", title: "Responsable que figura en el texto" }, it.responsable));
    if (it.origen === "tu") meta.push(h("span", { class: "bl-resp", title: "Lo anotaste tú durante la reunión" }, "tú"));
    if (it.origen === "resumen") meta.push(h("span", { class: "bl-resp", title: "Solo aparece en el resumen de la sesión" }, "del resumen"));
    if (it.veces > 1) meta.push(h("span", { class: "bl-resp", title: "El mismo pendiente salió en varias sesiones; aquí se muestra el de la más reciente" }, `Salió en ${it.veces} sesiones`));
    if (it.recortado) meta.push(h("span", { class: "bl-resp", title: "El texto original estaba recortado" }, "recortado"));
    const enlace = it.minuto
      ? h("button", { class: "bl-min", type: "button", title: "Ver la transcripción en ese minuto", onclick: () => irAMinuto(it.sesion_id, it.minuto) }, it.minuto + " →")
      : h("button", { class: "bl-min", type: "button", title: "Abrir la sesión", onclick: () => abrirSesion(it.sesion_id) }, "sesión →");
    return h("div", { class: "bl-it", "data-id": it.id, "data-tipo": it.tipo, "data-estado": it.estado || "" },
      h("span", { class: "bl-it-tipo t-label" }, glifo(it.tipo), h("span", {}, it.etiqueta)),
      h("div", { class: "bl-it-c" },
        h("div", { class: "bl-it-tx t-body" }, it.texto),
        h("div", { class: "bl-it-meta t-meta" }, enlace, ...meta),
        it.contexto ? h("div", { class: "bl-it-ctx t-meta soft" }, "Contexto: " + it.contexto) : null),
      ctrl);
  }
  const metaFecha = (it) => [it.proyecto, fFecha(it.fecha), it.inicio].filter(Boolean).join(" · ");

  async function cambiarEstado(it, estado) {
    if (it.estado === estado) return;
    const antes = it.estado;
    try {
      await api("PUT", `/api/backlog/items/${it.id}`, { estado });
      aplicarEstado(it.id, estado);
      toast(`«${recorta(it.texto)}»: ${ETQ_ESTADO[estado].toLowerCase()}`, async () => { await cambiarEstadoSilencioso(it.id, antes); });
    } catch (e) { toast("No se pudo guardar el estado: " + e.message); }
  }
  async function cambiarEstadoSilencioso(id, estado) {
    try { await api("PUT", `/api/backlog/items/${id}`, { estado }); aplicarEstado(id, estado); } catch (e) { toast("No se pudo deshacer: " + e.message); }
  }
  function aplicarEstado(id, estado) {
    B.items.forEach((i) => { if (i.id === id) i.estado = estado; });
    Object.values(B.det).forEach((d) => d && d.items && d.items.forEach((i) => { if (i.id === id) i.estado = estado; }));
    pintarDetalle(); pintarPendientes(); pintarTodoResumen();
  }
  function pintarTodoResumen() {
    const n = B.sesiones.length, el = B.items.filter((i) => i.tipo === "pendiente" && i.estado === "abierto").length;
    D.resumen.textContent = n ? `${plural(n, "sesión", "sesiones")} · ${plural(el, "pendiente abierto", "pendientes abiertos")}` : "";
  }
  const recorta = (t) => (t.length > 60 ? t.slice(0, 57) + "…" : t);

  let tToast = 0;
  function toast(texto, deshacer) {
    clearTimeout(tToast);
    D.toast.replaceChildren(...[h("span", { class: "t-body" }, texto), deshacer ? h("button", { class: "btn btn-mini", type: "button", onclick: () => { D.toast.hidden = true; deshacer(); } }, "Deshacer") : null].filter(Boolean));
    D.toast.hidden = false;
    tToast = setTimeout(() => { D.toast.hidden = true; }, deshacer ? 7000 : 4500);
  }

  // ------------------------------------------------------------ navegación entre pantallas
  function abrirSesion(sid, tab) {
    ponerTab("sesiones");
    B.proy = ""; B.q = ""; D.buscar.value = ""; D.proy.value = "";
    pintarLista();
    seleccionar(sid, { tab });
    const el = D.lista.querySelector(`[data-id="${sid}"]`);
    if (el) el.scrollIntoView({ block: "nearest" });
  }
  function irAMinuto(sid, minuto) {
    B.objetivo = { sid, t: aSeg(minuto) };
    abrirSesion(sid, "transcripcion");
  }

  // ------------------------------------------------------------ lista conjunta
  function pintarPendientes() {
    // chips de tipo con su total
    const tot = {}; B.items.forEach((i) => { tot[i.tipo] = (tot[i.tipo] || 0) + 1; });
    D.chips.replaceChildren(...TIPOS.map(([k, plu]) => h("button", { class: "bj-chip bl-chip", type: "button", "data-tipo": k, "aria-pressed": String(B.f.tipos.has(k)),
      onclick: () => { if (B.f.tipos.has(k)) B.f.tipos.delete(k); else B.f.tipos.add(k); pintarPendientes(); } }, glifo(k), h("span", {}, plu), h("span", { class: "bj-n" }, String(tot[k] || 0)))));
    D.estado.value = B.f.estado;
    const q = norm(B.f.q).trim();
    const grupoEstado = (e) => (e === "hecho" || e === "aprovechada" ? "cerrados" : e === "descartado" || e === "descartada" ? "descartados" : "abiertos");
    const v = B.items.filter((i) => B.f.tipos.has(i.tipo) && (!B.f.proy || i.proyecto === B.f.proy)
      && (B.f.estado === "todos" || !(i.estados && i.estados.length) || grupoEstado(i.estado) === B.f.estado)
      && (!q || norm([i.texto, i.sesion_tema, i.responsable, i.contexto].join(" ")).includes(q)));
    D.pcuenta.textContent = B.cargando ? "" : plural(v.length, "elemento", "elementos");
    if (!v.length) {
      D.plista.replaceChildren(h("div", { class: "bl-vacio t-body" }, B.cargando ? "" : !B.items.length ? "Todavía no hay elementos: ninguna sesión tiene insights."
        : !B.f.tipos.size ? "Elige al menos un tipo." : "No hay elementos con estos filtros."));
      return;
    }
    const grupos = new Map();
    for (const it of v) {
      const clave = B.f.agrupar === "sesion" ? it.sesion_id : (it.fecha || "sin fecha");
      if (!grupos.has(clave)) grupos.set(clave, []);
      grupos.get(clave).push(it);
    }
    const bloques = [];
    for (const [clave, lista] of grupos) {
      const primero = lista[0];
      const cab = B.f.agrupar === "sesion"
        ? h("div", { class: "bl-grupo-h" }, h("button", { class: "bl-grupo-t t-body-m", type: "button", title: "Abrir la sesión", onclick: () => abrirSesion(clave) }, primero.sesion_tema),
          h("span", { class: "t-meta soft" }, metaFecha(primero)), h("span", { class: "grow" }), h("span", { class: "t-meta soft" }, plural(lista.length, "elemento", "elementos")))
        : h("div", { class: "bl-grupo-h" }, h("span", { class: "t-body-m" }, fFecha(primero.fecha)), h("span", { class: "grow" }), h("span", { class: "t-meta soft" }, plural(lista.length, "elemento", "elementos")));
      bloques.push(h("section", { class: "bl-grupo", "aria-label": B.f.agrupar === "sesion" ? primero.sesion_tema : fFecha(primero.fecha) }, cab,
        ...lista.map((it) => filaItem(it, { sesion: B.f.agrupar === "fecha" }))));
    }
    D.plista.replaceChildren(...bloques);
  }

  // los .md se leen en el servidor: aquí solo se pide «busqueda» ya normalizada para el buscador de la lista
  montar();
  // para pruebas y para otros módulos
  AP.backlog = { abrir, cerrar, estado: B, irAMinuto, abrirSesion, mdSeguro };
})();
