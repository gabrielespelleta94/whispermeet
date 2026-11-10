"use strict";
/* WhisperMeet: inicio = galería de proyectos a todo el ancho (sin llamadas al modelo).
   Dos etapas dentro de la vista de inicio: «galería» (elegir proyecto) y «preparar» (tema, idioma, cadencia, contexto y objetivos con el proyecto ya elegido).
   - Barra superior: buscador (#i-buscar, «/»), filtros (Todos, Favoritos, Con plan, Compartidos, Sin contexto), orden (Recientes, Actividad,
     Pendientes, Nombre) y rejilla/lista. Orden y vista se recuerdan en localStorage (con try/catch: puede no haber almacenamiento).
   - Secciones: «Continuar» (último proyecto usado, tarjeta ancha con «Empezar aquí»), Favoritos, Proyectos e «Inactivos» (sin sesión en 60 días, plegados).
     «Reunión sin proyecto» (Bandeja) y «Añadir carpeta de proyecto» viven en la fila de Continuar. Con búsqueda o filtro, una sola lista de resultados.
   - Tarjeta: monograma con color estable por proyecto (hash del nombre → una de 8 variables de color de los tokens, válidas en claro y oscuro), nombre,
     descripción, etiquetas, última sesión, pendientes abiertos, próximo hito, gráfica de sesiones por semana (SVG) y barra de calidad del contexto.
     Datos de GET /api/proyectos (rápido) + GET /api/proyectos/resumen (acotado y en caché; lo que no llega a tiempo simplemente no se pinta).
   - Teclado: flechas entre tarjetas, Intro abre la ficha, «E» empieza la reunión. La ficha es un panel lateral con trampa de foco y Esc.
   Todo el texto dinámico entra como nodo de texto (nunca como HTML). El respaldo antiguo de la lista sigue en app.js (pintarLista). */
(() => {
  const AP = window.AP;
  if (!AP) return;
  const { UI, h, $, $$, api } = AP;
  const K_REC = "apuntes_recientes", K_FAV = "apuntes_favoritos", K_MODO = "apuntes_vista", K_ORDEN = "apuntes_orden", MAX_REC = 5, VISIBLES = 8, DIAS_INACTIVO = 60;
  const FILTROS = [["todos", "Todos"], ["favoritos", "Favoritos"], ["plan", "Con plan"], ["compartidos", "Compartidos"], ["sin-contexto", "Sin contexto"]];
  const AYUDA_FILTRO = { favoritos: "Marca la estrella de un proyecto para verlo aquí.", plan: "Un plan de sesiones (planes\\*.json) añade Gantt, hitos y objetivos por sesión.",
    compartidos: "Las carpetas compartidas se añaden con «Añadir carpeta de proyecto» marcando «Carpeta compartida».", "sin-contexto": "Todos los proyectos tienen ya su contexto." };

  const leer = (k) => { try { const v = JSON.parse(localStorage.getItem(k) || "[]"); return Array.isArray(v) ? v.filter((x) => typeof x === "string") : []; } catch { return []; } };
  const guardar = (k, v) => { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* sin almacenamiento */ } };
  const leerTxt = (k, validos, def) => { try { const v = localStorage.getItem(k); return validos.includes(v) ? v : def; } catch { return def; } };
  const guardarTxt = (k, v) => { try { localStorage.setItem(k, v); } catch { /* sin almacenamiento */ } };
  const P = { rec: leer(K_REC).slice(0, MAX_REC), fav: leer(K_FAV), modo: leerTxt(K_MODO, ["rejilla", "lista"], "rejilla"), orden: leerTxt(K_ORDEN, ["recientes", "actividad", "pendientes", "nombre"], "recientes"),
    filtro: "todos", etapa: "galeria", res: {}, resT: 0, resCargando: false, resOk: false, reintentos: 0, inactivosAbiertos: false,
    panel: null, opener: null, n: 0, ctx: null, doc: null, ses: null, pen: null, arch: null, aru: null, confirmar: false, expandido: {}, errorQuitar: "" };

  // ------------------------------------------------------------ utilidades puras
  function hace(iso, ahora = new Date()) {
    const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso || "");
    if (!m) return "";
    const d = new Date(+m[1], +m[2] - 1, +m[3]), hoy = new Date(ahora.getFullYear(), ahora.getMonth(), ahora.getDate());
    const dias = Math.round((hoy - d) / 86400000);
    if (dias < 0) return "";
    if (dias === 0) return "hoy";
    if (dias === 1) return "ayer";
    if (dias < 7) return `hace ${dias} días`;
    if (dias < 30) { const n = Math.floor(dias / 7); return n === 1 ? "hace 1 semana" : `hace ${n} semanas`; }
    if (dias < 365) { const n = Math.floor(dias / 30); return n === 1 ? "hace 1 mes" : `hace ${n} meses`; }
    const n = Math.floor(dias / 365);
    return n === 1 ? "hace 1 año" : `hace ${n} años`;
  }
  function diasDesde(iso, ahora = new Date()) {
    const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso || "");
    if (!m) return null;
    return Math.round((new Date(ahora.getFullYear(), ahora.getMonth(), ahora.getDate()) - new Date(+m[1], +m[2] - 1, +m[3])) / 86400000);
  }
  function etiquetas(p) {
    const t = [p.tiene_contexto ? "contexto" : p.n_md ? `${p.n_md} .md` : "sin contexto"];
    if (p.plan) t.push("plan");
    if (typeof p.n_sesiones === "number" && p.n_sesiones > 0) t.push(p.n_sesiones === 1 ? "1 sesión" : `${p.n_sesiones} sesiones`);
    const u = hace(p.ultima_sesion);
    if (u) t.push("última " + u);
    return t.join(" · ");
  }
  const sinAcentos = (s) => s.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
  function resaltar(texto, q) {
    if (!q) return texto;
    const a = sinAcentos(texto), b = sinAcentos(q);
    if (a.length !== texto.length || !b) return texto;
    const frag = document.createDocumentFragment();
    let ult = 0, i;
    while ((i = a.indexOf(b, ult)) !== -1) {
      if (i > ult) frag.append(texto.slice(ult, i));
      frag.append(h("mark", { class: "pr-m" }, texto.slice(i, i + b.length)));
      ult = i + b.length;
    }
    if (ult < texto.length) frag.append(texto.slice(ult));
    return frag;
  }
  const kb = (n) => (n < 1024 ? `${n} B` : `${(n / 1024).toFixed(n < 10240 ? 1 : 0).replace(".", ",")} kB`);
  const MOTIVOS = { "tamaño": "fuera: supera el tope de tamaño", "límite": "fuera: pasa del máximo de ficheros", "texto": "fuera del resumen: no cabe en el tope de texto",
    "nube": "fuera: en la nube sin descargar", "no se analiza": "no se analiza (índice o registro)" };
  /** Color estable por proyecto: FNV-1a del nombre → 0..7 (la clase «cN» fija --pc a un color de los tokens, claro y oscuro). */
  function colorDe(nombre) {
    let x = 2166136261;
    for (const c of String(nombre || "").toLowerCase()) { x ^= c.codePointAt(0); x = Math.imul(x, 16777619) >>> 0; }
    return x % 8;
  }
  const SIN_VALOR = new Set(["proyecto", "project", "de", "del", "la", "el", "los", "las", "y", "the", "of", "and", "demo"]);
  function iniciales(nombre) {
    const pal = String(nombre || "").split(/[\s_\-–—.]+/).filter(Boolean);
    const buenas = pal.filter((w) => !SIN_VALOR.has(sinAcentos(w)));
    const usar = buenas.length ? buenas : pal;
    if (!usar.length) return "?";
    const t = usar.length === 1 ? Array.from(usar[0]).slice(0, 2).join("") : Array.from(usar[0])[0] + Array.from(usar[1])[0];
    return t.toLocaleUpperCase("es");
  }
  const datos = (p) => P.res[p.nombre] || {};
  const lista = () => UI.proyectos || [];
  const porNombre = (n) => lista().find((p) => p.nombre === n) || null;
  const esFav = (p) => P.fav.includes(p.nombre);

  // ------------------------------------------------------------ recientes y favoritos
  function recordar(nombre) {
    P.rec = [nombre, ...P.rec.filter((x) => x !== nombre)].slice(0, MAX_REC);
    guardar(K_REC, P.rec);
  }
  function alternarFav(nombre) {
    P.fav = P.fav.includes(nombre) ? P.fav.filter((x) => x !== nombre) : [...P.fav, nombre];
    guardar(K_FAV, P.fav);
    pintarLista();
    if (P.panel) pintarPanel();
  }
  function olvidar(nombre) {
    P.rec = P.rec.filter((x) => x !== nombre); P.fav = P.fav.filter((x) => x !== nombre);
    guardar(K_REC, P.rec); guardar(K_FAV, P.fav);
  }

  // ------------------------------------------------------------ piezas de las tarjetas
  const NS = "http://www.w3.org/2000/svg";
  function monograma(nombre, grande) {
    return h("span", { class: "mono cp" + colorDe(nombre) + (grande ? " grande" : ""), "aria-hidden": "true" }, iniciales(nombre));
  }
  function spark(vals, ancho = 88, alto = 22) {
    const s = document.createElementNS(NS, "svg");
    s.setAttribute("viewBox", `0 0 ${ancho} ${alto}`); s.setAttribute("class", "spark"); s.setAttribute("role", "img");
    s.setAttribute("aria-label", `Sesiones por semana, últimas ${vals.length}: ${vals.join(", ")}`);
    const max = Math.max(1, ...vals), bw = ancho / vals.length;
    vals.forEach((v, i) => {
      const alt = v ? Math.max(3, Math.round((alto * v) / max)) : 1.5;
      const r = document.createElementNS(NS, "rect");
      r.setAttribute("x", String(+(i * bw + 1).toFixed(2))); r.setAttribute("width", String(+(bw - 2).toFixed(2)));
      r.setAttribute("y", String(+(alto - alt).toFixed(2))); r.setAttribute("height", String(alt)); r.setAttribute("rx", "1");
      r.setAttribute("class", (v ? "on" : "off") + (i === vals.length - 1 ? " act" : ""));
      s.append(r);
    });
    return s;
  }
  function calidadDe(p) {
    const c = datos(p).calidad_contexto;
    if (c) return c;
    if (typeof p.n_md === "number" || p.tiene_contexto !== undefined) {   // aún sin resumen: una aproximación con lo que ya se sabe
      return p.tiene_contexto ? { nivel: 2, etiqueta: "Contexto", breve: "", motivos: [], aprox: true }
        : p.n_md ? { nivel: 1, etiqueta: "Contexto básico", breve: "Falta 00. CONTEXTO (IA)", motivos: ["Falta la carpeta «00. CONTEXTO (IA)»."], aprox: true }
        : { nivel: 0, etiqueta: "Sin contexto", breve: "Sin ningún .md", motivos: ["No hay ningún .md en la carpeta."], aprox: true };
    }
    return null;
  }
  function barraCalidad(p, conTexto = true) {
    const c = calidadDe(p);
    if (!c) return null;
    const pistas = [c.etiqueta, ...(c.motivos || [])].join(". ");
    return h("span", { class: "cal", "data-nivel": String(c.nivel), title: pistas },
      h("span", { class: "cal-barra", "aria-hidden": "true" }, h("i"), h("i"), h("i")),
      conTexto ? h("span", { class: "cal-txt t-meta" }, c.nivel === 3 ? c.etiqueta : c.breve || c.etiqueta) : h("span", { class: "sr" }, c.etiqueta));
  }
  function chipPendientes(p) {
    const n = datos(p).pendientes_abiertos;
    if (typeof n !== "number") return null;
    return h("span", { class: "chip" + (n ? " pend" : ""), title: n ? "Pendientes abiertos en sus sesiones" : "Ningún pendiente abierto" }, n ? `${n} ${n === 1 ? "pendiente" : "pendientes"}` : "Sin pendientes");
  }
  function chipHito(p) {
    const hi = datos(p).proximo_hito;
    if (!hi) return null;
    const f = hi.fecha_texto && hi.fecha_texto !== "por definir" ? hi.fecha_texto : "";
    return h("span", { class: "chip hito", title: `Próximo hito: ${hi.nombre}${f ? " · " + f : ""}` }, AP.icono("hito"), h("span", { class: "chip-t" }, hi.nombre + (f ? " · " + f : "")));
  }
  function textoUltima(p) {
    if (!p.ultima_sesion) return typeof p.n_sesiones === "number" ? "Sin sesiones todavía" : "";
    const r = datos(p), tema = r.ultima_sesion_tema && r.ultima_sesion_fecha === p.ultima_sesion ? r.ultima_sesion_tema : "";
    return `Última sesión ${hace(p.ultima_sesion)}${tema ? " · " + tema : ""}`;
  }
  function etiquetasTipo(p) {
    const t = [];
    if (p.compartido) t.push(h("span", { class: "tipo comp", title: "Carpeta compartida: la sesión se guarda en local y se publica al terminar" }, AP.icono("compartida", "ic-comp"), "Compartido"));
    else if (p.extra) t.push(h("span", { class: "tipo", title: "Carpeta añadida desde fuera de la raíz de proyectos" }, "Carpeta añadida"));
    if (p.plan) t.push(h("span", { class: "tipo plan", title: "Tiene plan de sesiones (Gantt, hitos y objetivos)" }, "Con plan"));
    return t;
  }
  function descripcion(p, clase = "pc-desc") {
    const d = datos(p).descripcion;
    return d ? h("p", { class: clase, title: d }, d) : h("p", { class: clase + " vacia" }, P.resOk || datos(p).calidad_contexto ? "Sin descripción: añade una ficha en 00. CONTEXTO (IA) o un CLAUDE.md." : "");
  }
  function botonFav(p) {
    const es = esFav(p);
    return h("button", { type: "button", class: "fav", "aria-pressed": String(es), "data-fav": p.nombre, "aria-label": (es ? "Quitar de favoritos: " : "Marcar como favorito: ") + p.nombre,
      title: es ? "Quitar de favoritos" : "Favorito", onclick: (ev) => { ev.stopPropagation(); alternarFav(p.nombre); } }, AP.icono("favorito"));
  }
  function botonEmpezar(p, texto, clase = "btn btn-ghost btn-mini pc-ir") {
    return h("button", { type: "button", class: clase, "data-empezar": p.nombre, title: `Empezar una reunión en «${p.nombre}» (E)`, "aria-label": `${texto}: ${p.nombre}`,
      onclick: (ev) => { ev.stopPropagation(); empezarEn(p.nombre); } }, AP.icono("empezar"), texto);
  }
  function abrirBtn(p, clase, hijos) {
    return h("button", { type: "button", role: "option", class: "item " + clase, "aria-selected": String(UI.sel === p.nombre), "data-clave": p.nombre,
      title: `${p.nombre}${datos(p).descripcion ? " — " + datos(p).descripcion : ""}`, "aria-haspopup": "dialog", onclick: (ev) => abrirPanel(p.nombre, ev.currentTarget) }, hijos);
  }

  /** Tarjeta de la rejilla. */
  function tarjeta(p, q) {
    const r = datos(p);
    const sem = r.sesiones_por_semana;
    return h("div", { class: "pcard cp" + colorDe(p.nombre), "data-tarjeta": p.nombre },
      abrirBtn(p, "pcard-abrir",
        [h("span", { class: "pc-cab" }, monograma(p.nombre),
          h("span", { class: "pc-tit" }, h("span", { class: "n", title: p.nombre }, resaltar(p.nombre, q)), h("span", { class: "pc-tipos" }, etiquetasTipo(p)))),
        descripcion(p),
        h("span", { class: "pc-ult t-meta", title: textoUltima(p) }, textoUltima(p)),
        h("span", { class: "pc-chips" }, chipPendientes(p), chipHito(p)),
        h("span", { class: "pc-graf" }, sem ? [spark(sem), h("span", { class: "t-meta soft" }, `${sem.reduce((a, b) => a + b, 0)} en 8 semanas`)] : null)]),
      h("div", { class: "pc-pie" }, barraCalidad(p) || h("span"), botonEmpezar(p, "Empezar")),
      botonFav(p));
  }
  /** Tarjeta ancha de «Continuar». */
  function heroe(p) {
    const r = datos(p), sem = r.sesiones_por_semana;
    return h("div", { class: "pcard hero cp" + colorDe(p.nombre), "data-tarjeta": p.nombre },
      abrirBtn(p, "pcard-abrir hero-abrir",
        [h("span", { class: "hero-izq" },
          h("span", { class: "pc-cab" }, monograma(p.nombre, true),
            h("span", { class: "pc-tit" }, h("span", { class: "n t-display", title: p.nombre }, p.nombre), h("span", { class: "pc-tipos" }, etiquetasTipo(p)))),
          descripcion(p, "pc-desc hero-desc"),
          h("span", { class: "pc-ult t-meta", title: textoUltima(p) }, textoUltima(p)),
          h("span", { class: "pc-chips" }, chipPendientes(p), chipHito(p))),
        h("span", { class: "hero-der" },
          sem ? h("span", { class: "pc-graf grande" }, spark(sem, 160, 40), h("span", { class: "t-meta soft" }, `${sem.reduce((a, b) => a + b, 0)} sesiones en 8 semanas`)) : null,
          barraCalidad(p))]),
      h("div", { class: "hero-pie" }, h("span", { class: "t-meta soft" }, "Último proyecto usado"), botonEmpezar(p, "Empezar aquí", "btn btn-primary hero-ir")),
      botonFav(p));
  }
  /** Fila del modo lista. */
  function fila(p, q) {
    const r = datos(p), sem = r.sesiones_por_semana;
    return h("div", { class: "prow cp" + colorDe(p.nombre), "data-tarjeta": p.nombre },
      abrirBtn(p, "prow-abrir",
        [monograma(p.nombre),
        h("span", { class: "prow-nom" }, h("span", { class: "n", title: p.nombre }, resaltar(p.nombre, q)), descripcion(p, "pc-desc una")),
        h("span", { class: "prow-ult t-meta", title: textoUltima(p) }, textoUltima(p).replace("Última sesión ", "")),
        h("span", { class: "prow-pend" }, chipPendientes(p)),
        h("span", { class: "prow-hito" }, chipHito(p)),
        h("span", { class: "prow-graf" }, sem ? spark(sem, 72, 20) : null),
        h("span", { class: "prow-cal" }, barraCalidad(p))]),
      botonFav(p), botonEmpezar(p, "Empezar"));
  }
  function cabLista() {
    return h("div", { class: "prow-cab t-label", "aria-hidden": "true" }, h("span"), h("span", {}, "Proyecto"), h("span", {}, "Última sesión"), h("span", {}, "Pendientes"), h("span", { class: "col-hito" }, "Próximo hito"),
      h("span", { class: "col-graf" }, "8 semanas"), h("span", {}, "Contexto"));
  }

  // ------------------------------------------------------------ filtros, orden y secciones
  const consulta = () => $("#i-buscar").value.trim();
  function cumple(p, f) {
    if (f === "favoritos") return esFav(p);
    if (f === "plan") return !!p.plan;
    if (f === "compartidos") return !!p.compartido;
    if (f === "sin-contexto") { const c = calidadDe(p); return c ? c.nivel <= 1 : !p.tiene_contexto; }
    return true;
  }
  const actividad = (p) => (datos(p).sesiones_por_semana || []).reduce((a, b) => a + b, 0);
  function ordenar(ps) {
    const idxRec = (p) => { const i = P.rec.indexOf(p.nombre); return i < 0 ? 99 : i; };
    const porNom = (a, b) => a.nombre.localeCompare(b.nombre, "es", { sensitivity: "base" });
    const porFecha = (a, b) => (b.ultima_sesion || "").localeCompare(a.ultima_sesion || "");
    const cmp = {
      recientes: (a, b) => idxRec(a) - idxRec(b) || porFecha(a, b) || porNom(a, b),
      actividad: (a, b) => actividad(b) - actividad(a) || porFecha(a, b) || porNom(a, b),
      pendientes: (a, b) => (datos(b).pendientes_abiertos || 0) - (datos(a).pendientes_abiertos || 0) || porFecha(a, b) || porNom(a, b),
      nombre: porNom }[P.orden];
    return [...ps].sort(cmp);
  }
  function inactivo(p) { const d = diasDesde(p.ultima_sesion); return d !== null && d > DIAS_INACTIVO; }
  function proyectoHeroe(todos) {
    for (const n of P.rec) { const p = todos.find((x) => x.nombre === n); if (p) return p; }
    if (typeof UI.sel === "string") { const p = todos.find((x) => x.nombre === UI.sel); if (p) return p; }
    const conSesion = todos.filter((p) => p.ultima_sesion && !inactivo(p)).sort((a, b) => b.ultima_sesion.localeCompare(a.ultima_sesion));
    return conSesion[0] || null;
  }
  function tarjetaAccion(clase, id, icono, titulo, texto, onclick) {
    return h("button", { type: "button", class: "item acc-card " + clase, id, onclick }, h("span", { class: "acc-ic" }, AP.icono(icono)),
      h("span", { class: "acc-t" }, h("span", { class: "n" }, titulo), h("span", { class: "t-meta soft" }, texto)));
  }
  function accionBandeja() {
    return tarjetaAccion("bandeja", "i-bandeja", "respuesta", "Reunión sin proyecto", "Se guarda en apuntes\\bandeja", () => { AP.elegirProyecto(null, null); etapa("preparar"); });
  }
  function accionAnadir() {
    return tarjetaAccion("anadir", "i-anadir", "mas", "Añadir carpeta de proyecto", "Cualquier carpeta de tu equipo o de OneDrive", () => {
      const d = $("#i-add-carpeta"); d.open = true; d.scrollIntoView({ block: "center" }); const n = $("input[name=nombre]", d); if (n) n.focus({ preventScroll: true });
    });
  }
  function vacioGeneral() {
    return h("div", { class: "gal-vacio", id: "i-vacio" },
      h("h2", { class: "t-title" }, "Todavía no hay proyectos"),
      h("p", { class: "t-body" }, "La raíz de proyectos no tiene subcarpetas y no has añadido ninguna carpeta. Hay tres formas de empezar:"),
      h("ol", { class: "t-body" },
        h("li", {}, "Añade una carpeta que ya tengas (también sirve una de OneDrive) con «Añadir carpeta de proyecto»."),
        h("li", {}, "Cambia la raíz de proyectos en Ajustes: cada subcarpeta será un proyecto."),
        h("li", {}, "O graba ya en la Bandeja y decide luego dónde va.")),
      h("p", { class: "t-meta soft" }, "Para que el asesor entienda el proyecto, dentro de su carpeta crea «00. CONTEXTO (IA)» con una ficha (01-ficha-del-proyecto.md) o un CLAUDE.md."),
      h("div", { class: "gal-acciones" }, accionBandeja(), accionAnadir()));
  }

  function pintarChips() {
    const caja = $("#i-filtros");
    if (!caja.children.length) {
      for (const [k, t] of FILTROS) caja.append(h("button", { type: "button", class: "chipf", "data-filtro": k, "aria-pressed": "false",
        title: k === "sin-contexto" ? "Proyectos sin «00. CONTEXTO (IA)»: solo con CLAUDE.md o README, o sin ningún .md" : "",
        onclick: () => { P.filtro = P.filtro === k ? "todos" : k; pintarLista(); } }, h("span", { class: "chipf-t" }, t), h("span", { class: "chipf-n t-meta" })));
    }
    const todos = lista();
    for (const b of caja.children) {
      const k = b.dataset.filtro;
      b.setAttribute("aria-pressed", String(P.filtro === k));
      b.lastChild.textContent = String(k === "todos" ? todos.length : todos.filter((p) => cumple(p, k)).length);
    }
  }
  function seccion(clave, titulo, ps, q, extraCab) {
    if (!ps.length) return null;
    const grid = h("div", { class: "pgrid m-" + P.modo, role: "presentation" }, P.modo === "lista" ? [cabLista(), ...ps.map((p) => fila(p, q))] : ps.map((p) => tarjeta(p, q)));
    return h("section", { class: "gal-sec", "data-seccion": clave }, h("h2", { class: "lista-cab" }, titulo ? `${titulo} · ${ps.length}` : "", extraCab || null), grid);
  }

  function pintarLista() {
    const l = $("#i-lista"), q = consulta(), act = document.activeElement;
    let foco = null;
    if (act && l.contains(act)) foco = act.dataset.fav ? { fav: act.dataset.fav } : act.dataset.empezar ? { empezar: act.dataset.empezar } : { clave: act.dataset.clave, id: act.id };
    const scroll = $("#v-inicio").scrollTop;
    l.replaceChildren();
    $("#i-filtros").hidden = P.modo === "cartera";   // la cartera es otra mirada: salud de cada proyecto, ordenada por lo que necesita atención
    if (P.modo === "cartera" && AP.cartera) { $$("#i-modo [data-modo]").forEach((b) => b.setAttribute("aria-checked", String(b.dataset.modo === P.modo))); l.append(AP.cartera.pintar()); return; }
    pintarChips();
    const todos = lista();
    const filtrando = !!q || P.filtro !== "todos";
    $("#i-cuenta").textContent = !todos.length ? "" : filtrando ? "" : `${todos.length} ${todos.length === 1 ? "proyecto" : "proyectos"}`;
    $("#i-orden").value = P.orden;
    $$("#i-modo [data-modo]").forEach((b) => b.setAttribute("aria-checked", String(b.dataset.modo === P.modo)));
    if (!todos.length && !q) {
      l.append(vacioGeneral());
    } else if (filtrando) {
      const res = ordenar(todos.filter((p) => cumple(p, P.filtro)));
      if (!res.length) {
        l.append(h("div", { class: "lista-vacio gal-vacio-min", id: "i-vacio" }, h("p", { class: "t-body" }, q ? `Ningún proyecto coincide con «${q}».` : "Ningún proyecto cumple este filtro."),
          h("p", { class: "t-meta soft" }, q ? "Prueba con otra palabra o quita los filtros." : AYUDA_FILTRO[P.filtro] || ""),
          h("button", { type: "button", class: "btn btn-ghost btn-mini", onclick: () => { P.filtro = "todos"; $("#i-buscar").value = ""; $("#i-buscar").dispatchEvent(new Event("input")); pintarLista(); } }, "Quitar filtros")));
      } else l.append(seccion("resultados", "Resultados", res, q));
    } else {
      const heroeP = proyectoHeroe(todos);
      const resto = todos.filter((p) => p !== heroeP);
      l.append(h("section", { class: "gal-sec gal-continuar", "data-seccion": "continuar" },
        heroeP ? h("h2", { class: "lista-cab" }, "Continuar") : null,
        h("div", { class: "continuar-fila" }, heroeP ? heroe(heroeP) : null, h("div", { class: "acc-col" }, accionBandeja(), accionAnadir()))));
      const favs = ordenar(resto.filter(esFav));
      const noFav = resto.filter((p) => !esFav(p));
      const activos = ordenar(noFav.filter((p) => !inactivo(p))), parados = ordenar(noFav.filter(inactivo));
      for (const s of [seccion("favoritos", "Favoritos", favs, q), seccion("proyectos", "Proyectos", activos, q)]) if (s) l.append(s);
      if (parados.length) {
        const det = h("details", { class: "gal-sec gal-inactivos", "data-seccion": "inactivos" },
          h("summary", { class: "lista-cab", title: `Sin sesiones en ${DIAS_INACTIVO} días` }, `Inactivos · ${parados.length}`, h("span", { class: "t-meta soft" }, `Sin sesión en ${DIAS_INACTIVO} días`)),
          h("div", { class: "pgrid m-" + P.modo, role: "presentation" }, P.modo === "lista" ? parados.map((p) => fila(p, q)) : parados.map((p) => tarjeta(p, q))));
        det.open = P.inactivosAbiertos;
        det.addEventListener("toggle", () => { P.inactivosAbiertos = det.open; });
        l.append(det);
      }
    }
    if (foco) {
      const el = foco.fav ? l.querySelector(`[data-fav="${CSS.escape(foco.fav)}"]`) : foco.empezar ? l.querySelector(`[data-empezar="${CSS.escape(foco.empezar)}"]`)
        : foco.id ? document.getElementById(foco.id) : l.querySelector(`.item[data-clave="${CSS.escape(foco.clave || "")}"]`);
      if (el) el.focus({ preventScroll: true });
    }
    $("#v-inicio").scrollTop = scroll;
    if (P.panel) refrescarPanel();
    if (P.etapa === "preparar") pintarCabPrep();
  }
  AP.hooks.pintarLista = pintarLista;
  AP.hooks.alElegirProyecto = (clave) => { if (typeof clave === "string") recordar(clave); P.confirmar = false; P.errorQuitar = ""; };
  AP.hooks.errorLista = (e) => {
    const l = $("#i-lista");
    l.replaceChildren(h("div", { class: "lista-vacio t-meta", id: "i-vacio" }, "No se pudieron leer los proyectos (¿carpeta lenta o sin conexión?): " + e.message + " ",
      h("button", { type: "button", class: "btn btn-ghost btn-mini", onclick: () => AP.cargarProyectos() }, "Reintentar")));
  };

  // ------------------------------------------------------------ resumen visual (acotado: lo lento llega después o no llega)
  async function pedirResumen(forzar) {
    if (P.resCargando) return;
    if (!forzar && P.resOk && Date.now() - P.resT < 15000) return;
    P.resCargando = true;
    try {
      const r = await api("GET", "/api/proyectos/resumen");
      if (r && r.resumen && typeof r.resumen === "object") {
        P.res = r.resumen; P.resOk = !r.parcial; P.resT = Date.now();
        pintarLista();
        if (r.parcial && P.reintentos < 3) { P.reintentos++; setTimeout(() => pedirResumen(true), 3500); } else if (!r.parcial) P.reintentos = 0;
      }
    } catch { /* sin resumen: la galería se queda con lo que ya tiene */ }
    finally { P.resCargando = false; }
  }
  AP.hooks.proyectosCargados = () => { pedirResumen(lista().some((p) => !P.res[p.nombre]) && !consulta()); };
  AP.hooks.alVolverAInicio = () => { cerrarPanel(false); etapa("galeria"); pedirResumen(true); };

  // ------------------------------------------------------------ etapas: galería | preparar
  function etapa(e) {
    P.etapa = e;
    $("#i-galeria").hidden = e !== "galeria"; $("#i-preparar").hidden = e !== "preparar";
    document.body.dataset.inicio = e;
    if (e === "preparar") pintarCabPrep();
    $("#v-inicio").scrollTop = 0;
  }
  function pintarCabPrep() {
    const cab = $("#i-proy-cab"), p = typeof UI.sel === "string" ? (UI.proy || porNombre(UI.sel)) : null;
    const nombre = p ? p.nombre : UI.sel === null ? "Reunión sin proyecto" : "Sin proyecto elegido";
    const desc = p ? datos(p).descripcion || textoUltima(p) : UI.sel === null ? "La transcripción se guarda en apuntes\\bandeja." : "";
    cab.replaceChildren(h("div", { class: "proy-top" }, h("h1", { class: "t-display" }, "Nueva reunión"),
        h("button", { type: "button", class: "btn btn-ghost", id: "i-cambiar", title: "Volver a la galería de proyectos", onclick: () => cambiarProyecto() }, "Cambiar proyecto")),
      h("div", { class: "proy-ficha " + (p ? "cp" + colorDe(p.nombre) : "cp" + colorDe("bandeja")), "data-proyecto": nombre },
        p ? monograma(nombre, true) : h("span", { class: "mono grande bandeja", "aria-hidden": "true" }, AP.icono("respuesta")),
        h("div", { class: "proy-txt" }, h("div", { class: "proy-nom", id: "i-proy-nombre", title: nombre }, nombre), desc ? h("div", { class: "t-meta soft proy-desc", title: desc }, desc) : null,
          p ? h("div", { class: "pc-tipos" }, etiquetasTipo(p)) : null)));
  }
  function cambiarProyecto() {
    etapa("galeria");
    const el = typeof UI.sel === "string" ? document.querySelector(`#i-lista .item[data-clave="${CSS.escape(UI.sel)}"]`) : null;
    (el || $("#i-buscar")).focus({ preventScroll: false });
  }
  /** «Empezar reunión» / «Empezar aquí» / tecla E: elige el proyecto y pasa a preparar la reunión (tema, idioma, cadencia…). */
  function empezarEn(nombre) {
    const p = porNombre(nombre);
    if (!p) return;
    cerrarPanel(false);
    AP.elegirProyecto(nombre, p);
    etapa("preparar");
    const t = $("#i-tema"); if (t) t.focus({ preventScroll: true });
  }
  $("#i-llamada-si").addEventListener("click", () => {   // llamada de Teams: ir a preparar con el último proyecto usado (o la Bandeja)
    const ult = P.rec.find((n) => porNombre(n)) || (typeof UI.sel === "string" && porNombre(UI.sel) ? UI.sel : null);
    if (ult) { cerrarPanel(false); AP.elegirProyecto(ult, porNombre(ult)); } else AP.elegirProyecto(null, null);
    etapa("preparar");
    const a = $("#i-aviso"); a.scrollIntoView({ block: "center" }); a.focus({ preventScroll: true });
  });

  // ------------------------------------------------------------ barra: orden, vista y buscador
  $("#i-orden").addEventListener("change", (ev) => { P.orden = ev.target.value; guardarTxt(K_ORDEN, P.orden); pintarLista(); });
  $$("#i-modo [data-modo]").forEach((b) => { const ic = $(".gal-ic", b); if (ic) ic.replaceWith(AP.icono({ lista: "lista", cartera: "cartera" }[b.dataset.modo] || "rejilla"));
    b.addEventListener("click", () => { P.modo = b.dataset.modo; guardarTxt(K_MODO, P.modo); pintarLista(); }); });

  // ------------------------------------------------------------ teclado
  const visibles = () => $$("#i-lista .item").filter((e) => e.offsetParent !== null);
  function vecino(el, dir) {
    const fs = visibles(), i = fs.indexOf(el);
    if (i < 0) return null;
    if (dir === "right") return fs[i + 1] || null;
    if (dir === "left") return fs[i - 1] || null;
    const r = el.getBoundingClientRect(), cx = r.left + r.width / 2, cy = r.top + r.height / 2;
    const cand = fs.map((f) => ({ f, r: f.getBoundingClientRect() })).filter(({ r: q }) => (dir === "down" ? q.top >= r.bottom - 4 : q.bottom <= r.top + 4));   // enteramente debajo / encima: una tarjeta al lado no cuenta
    if (!cand.length) return null;
    const dy = (c) => Math.abs(c.r.top + c.r.height / 2 - cy), dx = (c) => Math.abs(c.r.left + c.r.width / 2 - cx);
    const fila = Math.min(...cand.map(dy));
    return cand.filter((c) => dy(c) <= fila + 8).sort((a, b) => dx(a) - dx(b))[0].f;
  }
  const enVistaInicio = () => document.body.dataset.vista === "inicio";
  $("#i-buscar").addEventListener("keydown", (ev) => {
    if (ev.key === "ArrowDown") { ev.preventDefault(); const fs = visibles(); (consulta() ? fs.find((f) => !f.classList.contains("acc-card")) || fs[0] : fs.find((f) => f.getAttribute("aria-selected") === "true") || fs[0])?.focus(); }
    else if (ev.key === "Enter") { const fs = visibles(); const primero = consulta() ? fs.find((f) => !f.classList.contains("acc-card")) : null; if (primero) { ev.preventDefault(); primero.click(); } }
    else if (ev.key === "Escape" && consulta()) { ev.preventDefault(); $("#i-buscar").value = ""; $("#i-buscar").dispatchEvent(new Event("input")); }
  });
  $("#i-lista").addEventListener("keydown", (ev) => {
    const el = ev.target.closest(".item");
    if (!el || ev.ctrlKey || ev.metaKey || ev.altKey) return;
    const dir = { ArrowDown: "down", ArrowUp: "up", ArrowRight: "right", ArrowLeft: "left" }[ev.key];
    if (dir) {
      ev.preventDefault();
      const v = vecino(el, dir);
      if (v) v.focus(); else if (dir === "up" || dir === "left") $("#i-buscar").focus();
    } else if ((ev.key === "e" || ev.key === "E") && el.dataset.clave) { ev.preventDefault(); empezarEn(el.dataset.clave); }
    else if (ev.key === "Home" || ev.key === "End") { const fs = visibles(); ev.preventDefault(); (ev.key === "Home" ? fs[0] : fs[fs.length - 1])?.focus(); }
  });
  document.addEventListener("keydown", (ev) => {
    if (!enVistaInicio() || document.body.dataset.backlog) return;
    const t = ev.target, escribiendo = t && (t.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(t.tagName));
    // Ctrl+K ya no enfoca el buscador: abre la paleta de comandos (paleta.js), que también lista los proyectos. «/» sigue llevando al buscador.
    if (ev.key === "/" && !escribiendo && !ev.ctrlKey && !ev.metaKey && !ev.altKey && P.etapa === "galeria" && !P.panel) { ev.preventDefault(); $("#i-buscar").focus(); $("#i-buscar").select(); }
  });

  // ------------------------------------------------------------ ficha del proyecto (panel lateral)
  function abrirPanel(nombre, opener) {
    P.panel = nombre; P.opener = opener || null; P.confirmar = false; P.errorQuitar = ""; P.expandido = {};
    cargarPanel(nombre);
    $("#i-scrim").hidden = false; $("#i-panel").hidden = false;
    $("#i-galeria").inert = true;
    pintarPanel();
    const f = $("#pp-cerrar"); if (f) f.focus();
  }
  function cerrarPanel(devolverFoco = true) {
    if (!P.panel) return;
    const op = P.opener;
    P.panel = null; P.opener = null; P.n++; P.ctx = P.doc = P.ses = P.pen = P.arch = P.aru = null;
    $("#i-panel").hidden = true; $("#i-scrim").hidden = true; $("#i-panel").replaceChildren();
    $("#i-galeria").inert = false;
    if (devolverFoco && op && op.isConnected) op.focus({ preventScroll: true });
    else if (devolverFoco && typeof UI.sel === "string") document.querySelector(`#i-lista .item[data-clave="${CSS.escape(UI.sel)}"]`)?.focus({ preventScroll: true });
  }
  $("#i-scrim").addEventListener("click", () => cerrarPanel());
  $("#i-panel").addEventListener("keydown", (ev) => {
    if (ev.key === "Escape") { ev.preventDefault(); ev.stopPropagation(); cerrarPanel(); return; }
    if (ev.key !== "Tab") return;
    const fs = $$("button:not([disabled]), a[href], input, select, textarea, [tabindex]:not([tabindex='-1'])", $("#i-panel")).filter((e) => e.offsetParent !== null);
    if (!fs.length) return;
    const primero = fs[0], ultimo = fs[fs.length - 1];
    if (ev.shiftKey && (document.activeElement === primero || !$("#i-panel").contains(document.activeElement))) { ev.preventDefault(); ultimo.focus(); }
    else if (!ev.shiftKey && (document.activeElement === ultimo || !$("#i-panel").contains(document.activeElement))) { ev.preventDefault(); primero.focus(); }
  });
  document.addEventListener("keydown", (ev) => { if (P.panel && ev.key === "Escape" && !$("#i-panel").contains(ev.target)) { ev.preventDefault(); cerrarPanel(); } });

  function cargarPanel(nombre) {
    const id = ++P.n;
    P.ctx = { estado: "cargando" }; P.doc = { estado: "cargando" }; P.ses = { estado: "cargando" }; P.pen = { estado: "cargando" }; P.arch = { estado: "cargando" }; P.aru = nuevoAru();
    const pedir = async (ruta, campo) => {
      try { const d = await api("GET", `/api/proyectos/${encodeURIComponent(nombre)}/${ruta}`); if (id === P.n) P[campo] = { estado: "ok", d }; }
      catch (e) { if (id === P.n) P[campo] = { estado: "error", msg: e.message }; }
      if (id === P.n) pintarPanel();
    };
    pedir("contexto", "ctx"); pedir("documentos", "doc"); pedir("sesiones-recientes", "ses"); pedir("pendientes", "pen"); pedir("archivero", "arch");
  }
  function refrescarPanel() { if (porNombre(P.panel)) pintarPanel(); else cerrarPanel(false); }
  async function abrirMd(nombre, ident, boton) {
    boton.disabled = true;
    try { await api("POST", `/api/proyectos/${encodeURIComponent(nombre)}/contexto/${ident}/abrir`); } catch (e) { boton.title = "No se pudo abrir: " + e.message; boton.textContent = "No se pudo"; }
    finally { setTimeout(() => { boton.disabled = false; if (boton.textContent === "No se pudo") boton.textContent = "Abrir"; }, 2500); }
  }
  async function abrirDocumento(nombre, ident, boton) {
    boton.disabled = true;
    try { await api("POST", `/api/proyectos/${encodeURIComponent(nombre)}/documentos/${ident}/abrir`); } catch (e) { boton.title = "No se pudo abrir: " + e.message; boton.textContent = "No se pudo"; }
    finally { setTimeout(() => { boton.disabled = false; if (boton.textContent === "No se pudo") boton.textContent = "Abrir"; }, 2500); }
  }
  async function abrirCarpeta(nombre, boton) {
    boton.disabled = true;
    try { await api("POST", `/api/proyectos/${encodeURIComponent(nombre)}/abrir-carpeta`); } catch (e) { boton.textContent = "No se pudo abrir"; }
    finally { setTimeout(() => { boton.disabled = false; boton.textContent = "Abrir carpeta"; }, 2500); }
  }
  async function quitar(nombre) {
    P.errorQuitar = "";
    try {
      await AP.carpetas.quitar(nombre);
      olvidar(nombre);
      cerrarPanel(false);
      UI.sel = undefined; UI.proy = null; P.confirmar = false;
      try { localStorage.removeItem("apuntes_proy"); } catch { /* sin almacenamiento */ }
      await AP.cargarProyectos();
      $("#i-buscar").focus();
    } catch (e) { P.errorQuitar = e.message; P.confirmar = false; pintarPanel(); }
  }
  function bloqueFicheros(nombre, d) {
    const total = d.total, fuera = d.fuera;
    const cab = h("div", { class: "vp-sub" }, h("span", { class: "caps" }, "Contexto que se usará"),
      h("span", { class: "t-meta soft", id: "vp-resumen" }, total ? `${total} ${total === 1 ? "fichero" : "ficheros"}${fuera ? ` · ${fuera} fuera por los topes` : ""}` : ""));
    if (!total) return h("div", { class: "vp-bloque" }, cab, h("p", { class: "t-meta", id: "vp-sin-md" },
      "Este proyecto no tiene ningún .md, así que la reunión no tendrá contexto previo. Puedes escribir o dictar el contexto de la reunión al prepararla."));
    const partes = [cab];
    if (d.solo_lectura) partes.push(h("p", { class: "t-meta" }, "No tiene «00. CONTEXTO (IA)»: se usan sus .md en solo lectura (la app no escribe en ellos)."));
    if (d.truncado) partes.push(h("p", { class: "t-meta vp-aviso" }, "La carpeta es muy grande o tarda en responder: puede haber más ficheros de los que se listan."));
    for (const g of d.grupos) {
      if (!g.ficheros.length) continue;
      const abierto = P.expandido[g.clave];
      const vistos = abierto ? g.ficheros : g.ficheros.slice(0, VISIBLES);
      partes.push(h("div", { class: "vp-grupo", "data-grupo": g.clave },
        h("div", { class: "vp-gtit t-label" }, `${g.titulo} · ${g.ficheros.length}`),
        h("ul", { class: "vp-lista" }, vistos.map((f) => h("li", { class: "vp-fila" + (f.dejado ? " fuera" : ""), "data-id": f.id },
          h("span", { class: "vp-n", title: f.rel }, f.nombre),
          f.dejado ? h("span", { class: "vp-marca", title: MOTIVOS[f.dejado] || f.dejado }, MOTIVOS[f.dejado] || "fuera") : null,
          h("span", { class: "vp-tam t-meta" }, kb(f.tam)),   // el tamaño va siempre el último antes de «Abrir», en columna fija (con o sin nota)
          h("button", { type: "button", class: "btn btn-ghost btn-mini", "aria-label": "Abrir " + f.rel, onclick: (ev) => abrirMd(nombre, f.id, ev.currentTarget) }, "Abrir")))),
        g.ficheros.length > VISIBLES ? h("button", { type: "button", class: "btn btn-ghost btn-mini vp-mas", onclick: () => { P.expandido[g.clave] = !abierto; pintarPanel(); } },
          abierto ? "Ver menos" : `Ver los ${g.ficheros.length}`) : null));
    }
    return h("div", { class: "vp-bloque" }, partes);
  }
  // Mapa de documentos del proyecto (GET .../documentos): por tipo, con el último y lo que falta. Todo texto dinámico entra como nodo de texto.
  const isoDe = (mtime) => { const d = new Date(mtime * 1000); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`; };
  // ------------------------------------------------------------ Agente Archivero (ola B)
  // Lectura MANUAL de los documentos clave del proyecto con UNA llamada a claude -p. GET .../archivero es gratis (plan y último resultado cacheado);
  // nada sale de la máquina hasta pulsar «Analizar» en la lista de lo que se leerá y de lo que se omite. Todo texto dinámico entra como nodo de texto.
  const ENC = encodeURIComponent;
  const ETIQUETA_ESTADO = { documentado: "Documentado", parcial: "Parcial", sin_documentar: "Sin documentar" };
  const nuevoAru = () => ({ plan: false, refrescar: false, analizando: false, error: "", errorTipo: "", previa: null, guardado: null, ocupado: false, aplicando: {} });
  const fechaHora = (iso) => { const m = /^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})/.exec(iso || ""); return m ? `${m[3]}/${m[2]}/${m[1]} ${m[4]}:${m[5]}` : ""; };
  const enFoco = (id) => { const e = document.getElementById(id); if (e) e.focus({ preventScroll: true }); };
  const idDoc = (rel) => { for (const t of (P.doc && P.doc.d && P.doc.d.tipos) || []) for (const f of t.ficheros) if (f.rel === rel) return f.id; return null; };
  async function recargarDocs(nombre) {
    const id = P.n;
    try { const d = await api("GET", `/api/proyectos/${ENC(nombre)}/documentos`); if (id === P.n) P.doc = { estado: "ok", d }; }
    catch (e) { if (id === P.n) P.doc = { estado: "error", msg: e.message }; }
  }
  async function recargarArchivero(nombre) {
    const id = P.n;
    try { const d = await api("GET", `/api/proyectos/${ENC(nombre)}/archivero`); if (id === P.n) P.arch = { estado: "ok", d }; }
    catch (e) { if (id === P.n) P.arch = { estado: "error", msg: e.message }; }
  }
  async function cambiarTipo(nombre, ident, valor) {
    const id = P.n, U = P.aru; if (!U) return;
    U.errorTipo = "";
    try { await api("PUT", `/api/proyectos/${ENC(nombre)}/documentos/${ident}/tipo`, { tipo: valor || null }); await Promise.all([recargarDocs(nombre), recargarArchivero(nombre)]); }
    catch (e) { U.errorTipo = e.message; }
    if (id === P.n) { pintarPanel(); enFoco("ar-tipo-" + ident); }
  }
  async function analizarArchivero(nombre) {
    const id = P.n, U = P.aru, refrescar = U.refrescar;
    U.analizando = true; U.error = ""; U.previa = null; U.guardado = null; pintarPanel(); enFoco("vp-arch");
    try {
      const r = await api("POST", `/api/proyectos/${ENC(nombre)}/archivero${refrescar ? "?refrescar=1" : ""}`);
      if (id !== P.n) return;
      P.arch = { estado: "ok", d: { plan: (P.arch && P.arch.d && P.arch.d.plan) || null, resultado: r } };
      U.plan = false;
    } catch (e) { if (id === P.n) U.error = e.message; }
    finally { if (id === P.n) { U.analizando = false; pintarPanel(); enFoco(U.plan ? "ar-plan-analizar" : "ar-reanalizar"); } }
  }
  async function aplicarPropuesta(nombre, p) {
    const id = P.n, U = P.aru, ident = idDoc(p.rel); if (!U || !ident) return;
    U.aplicando[p.rel] = true; U.error = ""; pintarPanel();
    try { await api("PUT", `/api/proyectos/${ENC(nombre)}/documentos/${ident}/tipo`, { tipo: p.tipo }); await Promise.all([recargarDocs(nombre), recargarArchivero(nombre)]); }
    catch (e) { U.error = e.message; }
    if (id === P.n) { delete U.aplicando[p.rel]; pintarPanel(); enFoco("vp-arch"); }
  }
  async function guardarArchivero(nombre, confirmar) {
    const id = P.n, U = P.aru; if (!U) return;
    U.error = ""; U.ocupado = true; pintarPanel();
    try {
      // La confirmación lleva la huella de la vista previa que se enseñó: si lo que se guardaría ya no es eso, el servidor no escribe (409) y manda la nueva.
      const d = await api("POST", `/api/proyectos/${ENC(nombre)}/archivero/guardar`, confirmar ? { confirmar, huella: (U.previa && U.previa.huella) || null } : { confirmar });
      if (id !== P.n) return;
      if (confirmar) { U.guardado = d; U.previa = null; } else { U.previa = d; U.guardado = null; }
    } catch (e) {
      if (id !== P.n) return;
      if (e.status === 409 && e.datos && e.datos.previa) { U.previa = e.datos.previa; U.guardado = null; U.error = "El resultado ha cambiado; revisa la vista previa antes de guardar."; }
      else U.error = e.message;
    }
    finally { if (id === P.n) { U.ocupado = false; pintarPanel(); enFoco(U.previa ? "ar-guardar-si" : "ar-guardar"); } }
  }
  function bloqueArchivero(nombre) {
    const s = P.arch, U = P.aru;
    if (!s || !U || s.estado === "cargando") return null;
    const cab = (extra) => h("div", { class: "vp-sub ar-cab" }, h("span", { class: "ar-tit" }, "Agente Archivero"), extra || null);
    const envoltura = (...hijos) => h("div", { class: "ar-bloque", id: "vp-arch", tabindex: "-1", "aria-busy": U.analizando ? "true" : "false" }, hijos.flat());
    if (s.estado === "error") return envoltura(cab(), h("p", { class: "t-meta", id: "ar-error-lectura" }, "No se pudo comprobar el Archivero: " + s.msg));
    if (!s.d || !s.d.plan) return null;   // un servidor sin Archivero: el mapa de documentos sigue como siempre
    const plan = s.d.plan, r = s.d.resultado, leer = plan.leer || [];
    const error = U.error ? h("div", { class: "error", id: "ar-error", role: "alert" }, U.error) : null;
    const boton = (id, texto, clase, onclick, extra) => h("button", { type: "button", class: "btn btn-mini " + clase, id, onclick, ...(extra || {}) }, texto);
    if (U.analizando) return envoltura(cab(), h("p", { class: "t-body", id: "ar-cargando", role: "status" },
      `Claude está leyendo ${leer.length} ${leer.length === 1 ? "documento" : "documentos"}… Puede tardar un minuto. Gasta tokens (modelo ${plan.modelo || "de Claude"}).`));
    if (U.plan) {
      const om = plan.omitidos || [], total = om.length + (plan.mas_omitidos || 0);
      return envoltura(cab(),
        h("p", { class: "t-body", id: "ar-plan-intro" }, "Esto es lo que leerá Claude. Nada sale de tu equipo hasta que pulses «Analizar»."),
        h("div", { class: "vp-gtit t-label" }, `Se va a leer · ${leer.length}`),
        leer.length ? h("ul", { class: "vp-lista", id: "ar-plan-leer" }, leer.map((f) => h("li", { class: "vp-fila ar-fila", "data-rel": f.rel },
          h("span", { class: "vp-n", title: f.rel }, f.nombre, h("span", { class: "t-meta soft" }, ` · ${f.tipo_titulo}`)), h("span", { class: "vp-tam t-meta" }, kb(f.tam)))))
          : h("p", { class: "t-meta", id: "ar-plan-vacio" }, "Ningún documento se puede leer desde la app: solo verás la cobertura local, sin leer."),
        leer.length ? h("p", { class: "t-meta soft", id: "ar-plan-chars" }, `Hasta unos ${(plan.chars || 0).toLocaleString("es-ES")} caracteres en total.`) : null,
        total ? h("div", { class: "vp-gtit t-label" }, `No se va a leer · ${total}`) : null,
        total ? h("ul", { class: "vp-lista", id: "ar-plan-omitidos" }, om.map((o) => h("li", { class: "vp-fila ar-fila", "data-rel": o.rel },
          h("span", { class: "vp-n", title: o.rel }, o.nombre), h("span", { class: "vp-marca ar-motivo", title: o.motivo }, o.motivo)))) : null,
        plan.mas_omitidos ? h("p", { class: "t-meta soft" }, `y ${plan.mas_omitidos} más`) : null,
        plan.sin_clasificar ? h("p", { class: "t-meta", id: "ar-plan-sin" }, `Claude verá también el nombre y la carpeta de ${plan.sin_clasificar} ${plan.sin_clasificar === 1 ? "fichero sin clasificar" : "ficheros sin clasificar"} para proponer su tipo (no se abren).`) : null,
        h("p", { class: "t-meta", id: "ar-plan-aviso" }, `De cada documento solo sale texto, sin correos, teléfonos, secciones de contactos ni líneas con pinta de secreto. Es UNA llamada con tu licencia de Claude (modelo ${plan.modelo || "de Claude"}) y gasta tokens.`),
        error,
        h("div", { class: "ar-acciones" },
          boton("ar-plan-analizar", "Analizar", "btn-primary", () => analizarArchivero(nombre)),
          boton("ar-plan-cancelar", "Cancelar", "btn-ghost", () => { U.plan = false; U.error = ""; pintarPanel(); enFoco(r ? "ar-reanalizar" : "ar-abrir"); })));
    }
    if (!r) return envoltura(cab(),
      h("p", { class: "t-body", id: "ar-intro" }, "Lee los documentos clave del proyecto y resume qué documentación hay: la solución tal como está, el modelo de datos, usuarios y roles, alcance y planificación, con el documento que lo dice. Lo lanzas tú, no se ejecuta solo, y gasta tokens."),
      error,
      h("div", { class: "ar-acciones" }, boton("ar-abrir", "Analizar con Claude", "btn-primary", () => { U.plan = true; U.refrescar = false; U.error = ""; pintarPanel(); enFoco("ar-plan-analizar"); })));
    const local = r.origen === "local", partes = [cab(h("span", { class: "t-meta soft", id: "ar-origen" }, local ? "Cobertura local, sin leer" : "Analizado con Claude"))];
    if (r.aviso) partes.push(h("p", { class: "t-meta vp-aviso", id: "ar-aviso", title: r.aviso_detalle || null }, r.aviso));
    if (r.desactualizado) partes.push(h("p", { class: "t-meta vp-aviso", id: "ar-desactualizado" }, "Los documentos o sus tipos han cambiado desde este análisis. Vuelve a analizar para ponerlo al día."));
    partes.push(h("ul", { class: "ar-facetas", id: "ar-facetas" }, (r.facetas || []).map((f) => {
      const clave = f.sin_leer ? "sin_leer" : f.estado;
      return h("li", { class: "ar-faceta", "data-faceta": f.clave, "data-estado": clave },
        h("div", { class: "ar-faceta-cab" }, h("span", { class: "t-body-m" }, f.titulo),
          h("span", { class: "ar-estado " + clave }, f.sin_leer ? (f.estado === "sin_documentar" ? "Sin documentos" : "Hay documentos, sin leer") : ETIQUETA_ESTADO[f.estado] || f.estado)),
        (f.sabemos || []).length ? h("ul", { class: "ar-lista ar-sabemos" }, f.sabemos.map((x) => h("li", { class: "t-body" }, x))) : null,
        (f.fuentes || []).length ? h("p", { class: "t-meta ar-fuentes" }, "Fuentes: ", f.fuentes.map((x, i) => [i ? ", " : null, h("span", { class: "ar-fuente", title: x.rel }, x.nombre)]).flat()) : null,
        (f.falta || []).length ? h("div", { class: "ar-falta" }, h("span", { class: "t-label" }, "Falta"), h("ul", { class: "ar-lista" }, f.falta.map((x) => h("li", { class: "t-body" }, x)))) : null);
    })));
    if ((r.documentos || []).length) partes.push(h("details", { class: "ar-det", id: "ar-docs", open: !!P.expandido["arch:docs"], ontoggle: (ev) => { P.expandido["arch:docs"] = ev.currentTarget.open; } },
      h("summary", { class: "dc-res" }, h("span", { class: "vp-n" }, "Qué hay en cada documento leído"), h("span", { class: "t-meta soft dc-n" }, String(r.documentos.length))),
      h("ul", { class: "vp-lista" }, r.documentos.map((d) => h("li", { class: "ar-doc", "data-rel": d.rel },
        h("span", { class: "t-body-m", title: d.rel }, d.nombre), h("span", { class: "t-meta soft" }, ` · ${d.tipo_titulo}`), d.resumen ? h("p", { class: "t-body" }, d.resumen) : null)))));
    if ((r.no_leidos || []).length) partes.push(h("p", { class: "t-meta vp-aviso", id: "ar-no-leidos" }, "No se pudo leer: " + r.no_leidos.map((o) => `${o.nombre} (${o.motivo})`).join("; ")));
    const props = r.propuestas || [];
    if (props.length) partes.push(h("div", { class: "ar-propuestas", id: "ar-propuestas" }, h("div", { class: "vp-gtit t-label" }, "Tipos propuestos para lo que no se pudo clasificar"),
      h("ul", { class: "vp-lista" }, props.map((p) => h("li", { class: "vp-fila ar-prop", "data-rel": p.rel },
        h("span", { class: "vp-n", title: p.rel }, p.nombre, p.carpeta ? h("span", { class: "t-meta soft" }, ` · ${p.carpeta}`) : null),
        h("span", { class: "t-meta soft ar-prop-tipo" }, "→ " + p.tipo_titulo),
        h("button", { type: "button", class: "btn btn-ghost btn-mini", "aria-label": `Aplicar el tipo ${p.tipo_titulo} a ${p.rel}`, disabled: !idDoc(p.rel) || !!U.aplicando[p.rel], onclick: () => aplicarPropuesta(nombre, p) }, "Aplicar"))))));
    if (U.previa) partes.push(h("div", { class: "ar-previa", id: "ar-previa", role: "group", "aria-label": "Vista previa de lo que se guardará" },
      h("p", { class: "t-body" }, U.previa.actualiza
        ? `Ya existe «${U.previa.fichero}» en «00. CONTEXTO (IA)»: se reescribirá con este resultado. Es el único caso en el que la app reescribe un fichero del contexto.`
        : `Se guardará como «${U.previa.fichero}» en «00. CONTEXTO (IA)» y se anotará en «10-registro-de-cambios.md».`),
      U.previa.carpeta_nueva ? h("p", { class: "t-meta vp-aviso" }, "La carpeta «00. CONTEXTO (IA)» no existe: se creará con las plantillas de siempre.") : null,
      h("pre", { class: "ar-previa-md", tabindex: "0", "aria-label": "Markdown que se guardará" }, U.previa.vista_previa),
      h("div", { class: "ar-acciones" },
        boton("ar-guardar-si", U.previa.actualiza ? "Guardar y reescribir" : "Guardar", "btn-primary", () => guardarArchivero(nombre, true), { disabled: U.ocupado }),
        boton("ar-guardar-no", "Cancelar", "btn-ghost", () => { U.previa = null; pintarPanel(); enFoco("ar-guardar"); }))));
    if (U.guardado) partes.push(h("p", { class: "t-body ar-guardado", id: "ar-guardado", role: "status" }, `Guardado como «${U.guardado.fichero}» en «00. CONTEXTO (IA)»${U.guardado.actualiza ? " (se ha actualizado el que ya había)" : ""}. Los agentes de la reunión lo leerán como el resto del contexto.`));
    if (error) partes.push(error);
    const datos = [fechaHora(r.generado) ? "Analizado el " + fechaHora(r.generado) : null, r.modelo ? "modelo " + r.modelo : null,
      local ? null : `${r.leidos} ${r.leidos === 1 ? "documento leído" : "documentos leídos"}`, r.tokens ? `${r.tokens.toLocaleString("es-ES")} tokens` : null].filter(Boolean);
    partes.push(h("div", { class: "ar-pie" }, h("span", { class: "t-meta soft", id: "ar-pie-datos" }, datos.join(" · ")),
      h("div", { class: "ar-acciones" },
        boton("ar-reanalizar", "Volver a analizar", "btn-ghost", () => { U.plan = true; U.refrescar = true; U.error = ""; pintarPanel(); enFoco("ar-plan-analizar"); }),
        local || U.previa ? null : boton("ar-guardar", "Guardar en el contexto del proyecto", "btn-ghost", () => guardarArchivero(nombre, false), { disabled: U.ocupado }))));
    return envoltura(partes);
  }
  function selectorTipo(nombre, f, actual, tipos) {
    return h("select", { class: "input dc-tipo-sel", id: "ar-tipo-" + f.id, "aria-label": `Tipo de documento de ${f.nombre}`, title: "Cambiar el tipo de documento (se guarda solo en esta app: el fichero no se toca)",
      onchange: (ev) => cambiarTipo(nombre, f.id, ev.currentTarget.value) },
      tipos.map((t) => h("option", { value: t.clave, selected: t.clave === actual }, t.titulo)),
      f.corregido ? h("option", { value: "" }, "Quitar la corrección (volver a las reglas)") : null);
  }
  function bloqueDocumentos(nombre) {
    const s = P.doc, cab = (extra) => h("div", { class: "vp-sub" }, h("span", { class: "caps" }, "Documentos del proyecto"), extra || null);
    if (!s || s.estado === "cargando") return h("div", { class: "vp-bloque", id: "vp-docs" }, cab(), h("p", { class: "t-meta", id: "vp-docs-cargando" }, "Leyendo los documentos… (si está en OneDrive puede tardar)"));
    if (s.estado === "error") return h("div", { class: "vp-bloque", id: "vp-docs" }, cab(), h("p", { class: "error", id: "vp-docs-error" }, "No se pudieron leer los documentos: " + s.msg));
    const d = s.d, tipos = d.tipos || [];
    if (!d.total) return h("div", { class: "vp-bloque", id: "vp-docs" }, cab(), h("p", { class: "t-meta", id: "vp-docs-vacio" }, "Esta carpeta no tiene documentos."));
    const resumen = `${d.total} ${d.total === 1 ? "documento" : "documentos"}${d.en_nube ? ` · ${d.en_nube} solo en la nube` : ""}`;
    const partes = [cab(h("span", { class: "t-meta soft", id: "vp-docs-resumen" }, resumen))];
    if (d.truncado) partes.push(h("p", { class: "t-meta vp-aviso", id: "vp-docs-truncado" }, "La carpeta es muy grande: el mapa es parcial."));
    const arch = bloqueArchivero(nombre); if (arch) partes.push(arch);
    if (P.aru && P.aru.errorTipo) partes.push(h("div", { class: "error", id: "vp-docs-error-tipo", role: "alert" }, "No se pudo cambiar el tipo: " + P.aru.errorTipo));
    for (const t of tipos) {
      if (!t.n) continue;
      const clave = "doc:" + t.clave, ult = t.ultimo ? hace(isoDe(t.ultimo.mtime)) : "";
      const det = h("details", { class: "dc-tipo", "data-tipo": t.clave, open: !!P.expandido[clave], ontoggle: (ev) => { P.expandido[clave] = ev.currentTarget.open; } },
        h("summary", { class: "dc-res" }, h("span", { class: "vp-n" }, t.titulo), h("span", { class: "t-meta soft dc-n" }, String(t.n)),
          t.ultimo ? h("span", { class: "t-meta soft dc-ult", title: t.ultimo.rel }, `último: ${t.ultimo.nombre}${ult ? " · " + ult : ""}`) : null),
        h("ul", { class: "vp-lista" }, t.ficheros.map((f) => h("li", { class: "vp-fila dc-fila", "data-id": f.id },
          h("span", { class: "vp-n", title: `${f.rel}
${f.motivo}` }, f.nombre, f.carpeta ? h("span", { class: "t-meta soft" }, ` · ${f.carpeta}`) : null),
          f.nube ? h("span", { class: "vp-marca", title: "Solo está en la nube: al abrirlo se descargará" }, "en la nube") : null,
          f.corregido ? h("span", { class: "vp-marca ar-corregido", title: "El tipo lo elegiste tú; las reglas ya no se aplican a este documento" }, "tipo corregido") : null,
          f.abrible ? null : h("span", { class: "vp-marca", title: "Este formato puede llevar macros: la app no lo abre desde aquí. Ábrelo desde el Explorador de archivos." }, "no se abre desde aquí"),
          h("span", { class: "t-meta soft dc-fecha" }, hace(isoDe(f.mtime))),
          selectorTipo(nombre, f, t.clave, tipos),
          f.abrible ? h("button", { type: "button", class: "btn btn-ghost btn-mini", "aria-label": "Abrir " + f.rel, onclick: (ev) => abrirDocumento(nombre, f.id, ev.currentTarget) }, "Abrir") : null))),
        t.mas ? h("p", { class: "t-meta soft" }, `y ${t.mas} más`) : null);
      partes.push(det);
    }
    if ((d.faltan || []).length) partes.push(h("div", { class: "dc-faltan", id: "vp-docs-faltan" }, h("div", { class: "vp-gtit t-label" }, "No he encontrado"),
      h("ul", { class: "vp-lista" }, d.faltan.map((x) => h("li", { class: "vp-fila dc-falta", "data-tipo": x.clave }, h("span", { class: "vp-n" }, x.titulo, h("span", { class: "t-meta soft" }, ` · ${x.pista}`)))))));
    return h("div", { class: "vp-bloque", id: "vp-docs" }, partes);
  }
  function bloqueSesiones() {
    const s = P.ses;
    const cab = h("div", { class: "vp-sub" }, h("span", { class: "caps" }, "Últimas sesiones"));
    if (!s || s.estado === "cargando") return h("div", { class: "vp-bloque" }, cab, h("p", { class: "t-meta" }, "Leyendo las sesiones…"));
    if (s.estado === "error") return h("div", { class: "vp-bloque" }, cab, h("p", { class: "t-meta" }, "No se pudieron leer las sesiones: " + s.msg));
    const l = s.d.sesiones || [];
    if (!l.length) return h("div", { class: "vp-bloque" }, cab, h("p", { class: "t-meta", id: "vp-sin-ses" }, "Todavía no hay sesiones de este proyecto. Aparecerán aquí cuando termines la primera reunión."));
    return h("div", { class: "vp-bloque" }, cab, h("ul", { class: "vp-lista", id: "vp-sesiones" }, l.map((x) => h("li", { class: "vp-fila" },
      h("button", { type: "button", class: "vp-ses", "data-sesion": x.id, title: "Abrir en «Sesiones»", onclick: () => { if (AP.backlog) { cerrarPanel(false); AP.backlog.abrir(); AP.backlog.abrirSesion(x.id); } } },
        h("span", { class: "t-meta", title: x.fecha || "" }, x.fecha || ""), h("span", { class: "vp-n" }, x.tema))))));
  }
  function bloquePendientes() {
    const s = P.pen;
    const cab = h("div", { class: "vp-sub" }, h("span", { class: "caps" }, "Pendientes abiertos"),
      s && s.estado === "ok" && typeof s.d.total === "number" ? h("span", { class: "t-meta soft", id: "vp-pend-n" }, s.d.total > 5 ? `5 de ${s.d.total}` : String(s.d.total)) : null);
    if (!s || s.estado === "cargando") return h("div", { class: "vp-bloque" }, cab, h("p", { class: "t-meta" }, "Leyendo los pendientes…"));
    if (s.estado === "error") return h("div", { class: "vp-bloque" }, cab, h("p", { class: "t-meta" }, "No se pudieron leer los pendientes: " + s.msg));
    const l = s.d.pendientes || [];
    if (s.d.total === null || s.d.total === undefined) return h("div", { class: "vp-bloque" }, cab, h("p", { class: "t-meta" }, (s.d.avisos || [])[0] || "Los pendientes aparecerán en cuanto se lean las sesiones."));
    if (!l.length) return h("div", { class: "vp-bloque" }, cab, h("p", { class: "t-meta", id: "vp-sin-pend" }, "No hay pendientes abiertos. Los que salgan en las reuniones aparecerán aquí."));
    return h("div", { class: "vp-bloque" }, cab, h("ul", { class: "vp-lista", id: "vp-pendientes" }, l.map((x) => h("li", { class: "vp-fila pend-fila" },
      h("span", { class: "vp-n", title: x.texto }, x.texto, x.responsable ? h("span", { class: "t-meta soft" }, ` (${x.responsable})`) : null),
      h("span", { class: "t-meta soft vp-tam", title: x.tema || "" }, (x.veces > 1 ? `${x.veces} sesiones · ` : "") + (x.fecha || ""))))),
      s.d.total > l.length ? h("button", { type: "button", class: "btn btn-ghost btn-mini vp-mas", onclick: () => { if (AP.backlog) { cerrarPanel(false); AP.backlog.abrir(); } } }, "Ver todos en «Sesiones»") : null);
  }
  function bloqueCalidad(p) {
    const c = calidadDe(p);
    if (!c) return null;
    const arreglo = c.nivel === 0 ? "Crea la carpeta «00. CONTEXTO (IA)» dentro de la carpeta del proyecto con una ficha (01-ficha-del-proyecto.md), o añade un CLAUDE.md o un README.md en la raíz."
      : c.nivel === 1 ? "Crea «00. CONTEXTO (IA)» con una ficha, el alcance y el plan: la app propondrá cambios ahí cuando termines una reunión. Si no, también vale un CLAUDE.md."
      : c.nivel === 2 ? "Añade o actualiza los ficheros de «00. CONTEXTO (IA)»: ficha, alcance y plan." : "";
    return h("div", { class: "vp-bloque pp-calidad", id: "pp-calidad" }, h("div", { class: "vp-sub" }, h("span", { class: "caps" }, "Calidad del contexto"), barraCalidad(p)),
      c.motivos && c.motivos.length ? h("ul", { class: "pp-motivos" }, c.motivos.map((m) => h("li", { class: "t-body" }, m))) : h("p", { class: "t-meta" }, "El contexto está completo: ficha y ficheros de contenido al día."),
      arreglo ? h("p", { class: "t-meta pp-arreglo" }, "Cómo arreglarlo: " + arreglo) : null);
  }
  function pintarPanel() {
    const caja = $("#i-panel"), p = porNombre(P.panel);
    if (!p) { caja.replaceChildren(); return; }
    const nombre = p.nombre, r = datos(p), sem = r.sesiones_por_semana;
    const tocarFoco = caja.contains(document.activeElement) ? document.activeElement.id || null : null;
    const cab = h("div", { class: "pp-cab cp" + colorDe(nombre) },
      monograma(nombre, true),
      h("div", { class: "pp-tit" }, h("h2", { id: "pp-titulo", class: "t-display", title: nombre }, nombre), h("div", { class: "pc-tipos" }, etiquetasTipo(p)),
        h("div", { class: "t-meta soft", title: p.ruta }, textoUltima(p))),
      botonFav(p),
      h("button", { type: "button", class: "btn btn-ghost btn-icono", id: "pp-cerrar", "aria-label": "Cerrar la ficha", title: "Cerrar (Esc)", onclick: () => cerrarPanel() }, AP.icono("cerrar")));
    const cuerpo = [descripcion(p, "pp-desc t-body")];
    if (P.confirmar) cuerpo.push(h("div", { class: "vp-confirma", id: "vp-confirma", role: "alertdialog", "aria-label": "Confirmar" },
      h("span", { class: "t-body" }, `¿Quitar «${nombre}» de la lista? No se borra nada de la carpeta.`),
      h("button", { type: "button", class: "btn btn-primary btn-mini", id: "vp-quitar-si", onclick: () => quitar(nombre) }, "Sí, quitar"),
      h("button", { type: "button", class: "btn btn-ghost btn-mini", onclick: () => { P.confirmar = false; pintarPanel(); } }, "Cancelar")));
    if (P.errorQuitar) cuerpo.push(h("div", { class: "error", id: "vp-error" }, P.errorQuitar));
    cuerpo.push(h("div", { class: "pp-cifras" },
      h("div", { class: "pp-cifra" }, h("span", { class: "caps" }, "Actividad"), sem ? [spark(sem, 160, 36), h("span", { class: "t-meta soft" }, `${sem.reduce((a, b) => a + b, 0)} sesiones en 8 semanas`)] : h("span", { class: "t-meta soft" }, "—")),
      h("div", { class: "pp-cifra" }, h("span", { class: "caps" }, "Pendientes"), chipPendientes(p) || h("span", { class: "t-meta soft" }, "—")),
      h("div", { class: "pp-cifra" }, h("span", { class: "caps" }, "Próximo hito"), chipHito(p) || h("span", { class: "t-meta soft" }, p.plan ? "Sin hitos pendientes" : "Sin plan"))));
    const q = bloqueCalidad(p); if (q) cuerpo.push(q);
    if (!(AP.olas34 && AP.olas34.haySeguimiento(nombre))) cuerpo.push(bloquePendientes());   // con seguimiento, los pendientes van solo allí (con sus acciones)
    if (AP.hooks.fichaBloques) cuerpo.push(...AP.hooks.fichaBloques(nombre));   // preparación sugerida, seguimiento y métricas del proyecto (olas34.js)
    const c = P.ctx;
    if (!c || c.estado === "cargando") cuerpo.push(h("p", { class: "t-meta", id: "vp-cargando" }, "Leyendo la carpeta del proyecto… (si está en OneDrive puede tardar)"));
    else if (c.estado === "error") cuerpo.push(h("p", { class: "error", id: "vp-error-ctx" }, c.msg === "No existe ese proyecto."
      ? "La carpeta de este proyecto ya no existe o no se puede abrir. " + (p.extra ? "Puedes quitarla de la lista." : "")
      : "No se pudo leer el contexto: " + c.msg));
    else cuerpo.push(bloqueFicheros(nombre, c.d));
    cuerpo.push(bloqueDocumentos(nombre));
    cuerpo.push(bloqueSesiones());
    if (p.plan) {
      const plan = h("div", { class: "contexto pp-plan", id: "pp-plan" });
      AP.pintarContexto(plan, { proyecto: nombre, plan: p.plan, sesion: null });
      cuerpo.push(h("div", { class: "vp-bloque" }, h("div", { class: "vp-sub" }, h("span", { class: "caps" }, "Plan de sesiones")), plan));
    } else cuerpo.push(h("div", { class: "vp-bloque" }, h("div", { class: "vp-sub" }, h("span", { class: "caps" }, "Plan de sesiones")),
      h("p", { class: "t-meta", id: "pp-sin-plan" }, "Este proyecto no tiene plan. Un plan (un .json en la carpeta planes) añade Gantt, hitos y objetivos para cada sesión.")));
    const pie = h("div", { class: "pp-pie" },
      h("button", { type: "button", class: "btn btn-ghost", id: "vp-abrir-carpeta", onclick: (ev) => abrirCarpeta(nombre, ev.currentTarget) }, AP.icono("carpeta"), "Abrir carpeta"),
      p.extra ? h("button", { type: "button", class: "btn btn-ghost", id: "vp-quitar", onclick: () => { P.confirmar = true; pintarPanel(); } }, "Quitar de la lista") : null,
      h("span", { class: "pp-sep" }),
      h("button", { type: "button", class: "btn btn-primary btn-grande", id: "pp-empezar", onclick: () => empezarEn(nombre) }, AP.icono("empezar"), "Empezar reunión"));
    const scroll = $(".pp-cuerpo", caja) ? $(".pp-cuerpo", caja).scrollTop : 0;
    caja.replaceChildren(cab, h("div", { class: "pp-cuerpo" }, cuerpo), pie);
    $(".pp-cuerpo", caja).scrollTop = scroll;
    if (tocarFoco) { const e = document.getElementById(tocarFoco); if (e) e.focus({ preventScroll: true }); }
  }

  AP.proyectos = { repintarPanel: (n) => { if (P.panel === n) pintarPanel(); }, hace, etiquetas, resaltar, colorDe, iniciales, recientes: () => [...P.rec], favoritos: () => [...P.fav], alternarFav, recordar, abrirPanel, cerrarPanel, empezarEn, etapa, cambiarProyecto,
    estado: () => ({ etapa: P.etapa, modo: P.modo, orden: P.orden, filtro: P.filtro, panel: P.panel }) };
})();
