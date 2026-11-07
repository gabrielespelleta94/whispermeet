"use strict";
/* WhisperMeet: navegación de proyectos en la pantalla de inicio (sin llamadas al modelo).
   - Lista por secciones: Recientes (últimos 5 elegidos), Favoritos (estrella), Proyectos (raíz), Carpetas añadidas y Compartidas, cada una con su recuento.
     Recientes y favoritos viven en localStorage (con try/catch: puede no haber almacenamiento).
   - Buscador (#i-buscar, filtra en el servidor) con coincidencias resaltadas; ↑/↓ mueven, Intro elige, Ctrl+K o «/» enfocan el buscador.
   - Cada fila: nombre, icono de compartida y etiquetas (contexto · plan · N sesiones · última sesión «hace 3 días»).
   - Vista previa (#i-preview) del proyecto elegido: los .md que se usarán como contexto (agrupados, con tamaño y la marca de los que quedan fuera por los
     topes), «Abrir» cada fichero y «Abrir carpeta» (el servidor solo acepta ids opacos que él mismo dio), las 3 últimas sesiones (enlazan con «Sesiones»)
     y «Quitar de la lista» para las carpetas añadidas (con confirmación; reutiliza AP.carpetas.quitar).
   Todo el texto dinámico entra como nodo de texto (nunca como HTML). El respaldo antiguo de la lista sigue en app.js (pintarLista). */
(() => {
  const AP = window.AP;
  if (!AP) return;
  const { UI, h, $, $$, api } = AP;
  const K_REC = "apuntes_recientes", K_FAV = "apuntes_favoritos", MAX_REC = 5, VISIBLES = 8;

  const leer = (k) => { try { const v = JSON.parse(localStorage.getItem(k) || "[]"); return Array.isArray(v) ? v.filter((x) => typeof x === "string") : []; } catch { return []; } };
  const guardar = (k, v) => { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* sin almacenamiento */ } };
  const P = { rec: leer(K_REC).slice(0, MAX_REC), fav: leer(K_FAV), n: 0, prev: undefined, ctx: null, ses: null, confirmar: false, expandido: {}, errorQuitar: "" };

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

  // ------------------------------------------------------------ recientes y favoritos
  function recordar(nombre) {
    P.rec = [nombre, ...P.rec.filter((x) => x !== nombre)].slice(0, MAX_REC);
    guardar(K_REC, P.rec);
  }
  function alternarFav(nombre) {
    P.fav = P.fav.includes(nombre) ? P.fav.filter((x) => x !== nombre) : [...P.fav, nombre];
    guardar(K_FAV, P.fav);
    pintarLista();
  }
  function olvidar(nombre) {
    P.rec = P.rec.filter((x) => x !== nombre); P.fav = P.fav.filter((x) => x !== nombre);
    guardar(K_REC, P.rec); guardar(K_FAV, P.fav);
  }

  // ------------------------------------------------------------ lista
  const consulta = () => $("#i-buscar").value.trim();
  function fila(clave, p, q, clase = "") {
    const nombre = p ? p.nombre : "Bandeja (reunión sin proyecto)";
    const btn = h("button", { type: "button", role: "option", class: "item " + clase, "aria-selected": String(UI.sel === clave), "data-clave": clave,
      onclick: () => AP.elegirProyecto(clave, p) },
      p && p.compartido ? AP.icono("compartida", "ic-comp") : null,
      h("span", { class: "n", title: p ? p.ruta : "" }, resaltar(nombre, q)),
      h("span", { class: "tag" }, p ? etiquetas(p) : "se guarda en apuntes\\bandeja"));
    if (!p) return btn;
    const es = P.fav.includes(p.nombre);
    return h("div", { class: "fila-proy" }, btn,
      h("button", { type: "button", class: "fav", "aria-pressed": String(es), "data-fav": p.nombre,
        "aria-label": (es ? "Quitar de favoritos: " : "Marcar como favorito: ") + p.nombre, title: es ? "Quitar de favoritos" : "Favorito",
        onclick: (ev) => { ev.stopPropagation(); alternarFav(p.nombre); } }, AP.icono("favorito")));
  }
  function pintarLista() {
    const l = $("#i-lista"), q = consulta(), act = document.activeElement;
    let foco = null;
    if (act && l.contains(act)) foco = act.dataset.fav ? { fav: act.dataset.fav } : { clave: act.dataset.clave, bandeja: act.classList.contains("bandeja") };
    l.replaceChildren();
    const todos = UI.proyectos || [];
    const cab = (t, n) => l.append(h("div", { class: "lista-cab", role: "presentation" }, `${t} · ${n}`));
    if (!q || sinAcentos("bandeja").includes(sinAcentos(q))) l.append(fila(null, null, "", "bandeja"));
    if (!todos.length) {
      l.append(h("div", { class: "lista-vacio t-meta", id: "i-vacio" }, q ? `Ningún proyecto coincide con «${q}».`
        : "Todavía no hay proyectos: la raíz no tiene subcarpetas y no has añadido ninguna carpeta. Añade una abajo o cambia la raíz en Ajustes. Mientras, puedes grabar en la Bandeja."));
    } else {
      const por = new Map(todos.map((p) => [p.nombre, p]));
      const seccion = (t, lista) => { if (lista.length) { cab(t, lista.length); lista.forEach((p) => l.append(fila(p.nombre, p, q))); } };
      if (!q) {
        seccion("Recientes", P.rec.map((n) => por.get(n)).filter(Boolean));
        seccion("Favoritos", P.fav.map((n) => por.get(n)).filter(Boolean));
      }
      seccion("Proyectos", todos.filter((p) => !p.extra && !p.compartido));
      seccion("Carpetas añadidas", todos.filter((p) => p.extra && !p.compartido));
      seccion("Compartidas", todos.filter((p) => p.compartido));
    }
    if (foco) {
      const el = foco.fav ? l.querySelector(`[data-fav="${CSS.escape(foco.fav)}"]`) : foco.bandeja ? l.querySelector(".bandeja") : l.querySelector(`.item[data-clave="${CSS.escape(foco.clave || "")}"]`);
      if (el) el.focus({ preventScroll: true });
    }
    sincronizarPreview();
  }
  AP.hooks.pintarLista = pintarLista;
  AP.hooks.alElegirProyecto = (clave) => { if (typeof clave === "string") recordar(clave); P.confirmar = false; P.errorQuitar = ""; };
  AP.hooks.errorLista = (e) => {
    const l = $("#i-lista");
    l.replaceChildren(h("div", { class: "lista-vacio t-meta", id: "i-vacio" }, "No se pudieron leer los proyectos (¿carpeta lenta o sin conexión?): " + e.message + " ",
      h("button", { type: "button", class: "btn btn-ghost btn-mini", onclick: () => AP.cargarProyectos() }, "Reintentar")));
  };

  // ------------------------------------------------------------ teclado
  const filas = () => $$("#i-lista .item");
  const enVistaInicio = () => document.body.dataset.vista === "inicio";
  function mover(desde, d) {
    const fs = filas();
    if (!fs.length) return;
    let i = desde === -1 ? (d > 0 ? 0 : fs.length - 1) : desde + d;
    if (i < 0) { $("#i-buscar").focus(); return; }
    fs[Math.min(i, fs.length - 1)].focus();
  }
  $("#i-buscar").addEventListener("keydown", (ev) => {
    if (ev.key === "ArrowDown") { ev.preventDefault(); const fs = filas(); (consulta() ? fs[Math.min(1, fs.length - 1)] || fs[0] : fs.find((f) => f.getAttribute("aria-selected") === "true") || fs[0])?.focus(); }
    else if (ev.key === "Enter") { const fs = filas(); const primero = consulta() ? (fs.find((f) => !f.classList.contains("bandeja")) || fs[0]) : null; if (primero) { ev.preventDefault(); primero.click(); } }
    else if (ev.key === "Escape" && consulta()) { ev.preventDefault(); $("#i-buscar").value = ""; $("#i-buscar").dispatchEvent(new Event("input")); }
  });
  $("#i-lista").addEventListener("keydown", (ev) => {
    const el = ev.target.closest(".item");
    if (!el || !["ArrowDown", "ArrowUp"].includes(ev.key)) return;
    ev.preventDefault();
    mover(filas().indexOf(el), ev.key === "ArrowDown" ? 1 : -1);
  });
  document.addEventListener("keydown", (ev) => {
    if (!enVistaInicio() || document.body.dataset.backlog) return;
    const t = ev.target, escribiendo = t && (t.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(t.tagName));
    if ((ev.ctrlKey || ev.metaKey) && ev.key.toLowerCase() === "k") { ev.preventDefault(); $("#i-buscar").focus(); $("#i-buscar").select(); }
    else if (ev.key === "/" && !escribiendo && !ev.ctrlKey && !ev.metaKey && !ev.altKey) { ev.preventDefault(); $("#i-buscar").focus(); $("#i-buscar").select(); }
  });

  // ------------------------------------------------------------ vista previa
  function sincronizarPreview() {
    const caja = $("#i-preview");
    const clave = typeof UI.sel === "string" && UI.proy ? UI.sel : null;
    if (clave !== P.prev) {
      P.prev = clave; P.confirmar = false; P.errorQuitar = "";
      if (clave) cargarPreview(clave); else { P.n++; P.ctx = null; P.ses = null; }
    }
    if (!clave) { caja.hidden = true; caja.replaceChildren(); return; }
    pintarPreview();
  }
  async function cargarPreview(nombre) {
    const id = ++P.n;
    P.ctx = { estado: "cargando" }; P.ses = { estado: "cargando" };
    pintarPreview();
    const pedir = async (ruta, campo) => {
      try { const d = await api("GET", `/api/proyectos/${encodeURIComponent(nombre)}/${ruta}`); if (id === P.n) P[campo] = { estado: "ok", d }; }
      catch (e) { if (id === P.n) P[campo] = { estado: "error", msg: e.message }; }
      if (id === P.n) pintarPreview();
    };
    pedir("contexto", "ctx"); pedir("sesiones-recientes", "ses");
  }
  async function abrirMd(nombre, ident, boton) {
    boton.disabled = true;
    try { await api("POST", `/api/proyectos/${encodeURIComponent(nombre)}/contexto/${ident}/abrir`); } catch (e) { boton.title = "No se pudo abrir: " + e.message; boton.textContent = "No se pudo"; }
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
      UI.sel = undefined; UI.proy = null; P.confirmar = false;
      try { localStorage.removeItem("apuntes_proy"); } catch { /* sin almacenamiento */ }
      await AP.cargarProyectos();
    } catch (e) { P.errorQuitar = e.message; P.confirmar = false; pintarPreview(); }
  }
  function bloqueFicheros(nombre, d) {
    const total = d.total, fuera = d.fuera;
    const cab = h("div", { class: "vp-sub" }, h("span", { class: "caps" }, "Contexto que se usará"),
      h("span", { class: "t-meta soft", id: "vp-resumen" }, total ? `${total} ${total === 1 ? "fichero" : "ficheros"}${fuera ? ` · ${fuera} fuera por los topes` : ""}` : ""));
    if (!total) return h("div", { class: "vp-bloque" }, cab, h("p", { class: "t-meta", id: "vp-sin-md" },
      "Este proyecto no tiene ningún .md, así que la reunión no tendrá contexto previo. Puedes escribir o dictar el contexto de la reunión más abajo."));
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
          h("span", { class: "vp-tam t-meta" }, kb(f.tam)),
          f.dejado ? h("span", { class: "vp-marca", title: MOTIVOS[f.dejado] || f.dejado }, MOTIVOS[f.dejado] || "fuera") : null,
          h("button", { type: "button", class: "btn btn-ghost btn-mini", "aria-label": "Abrir " + f.rel, onclick: (ev) => abrirMd(nombre, f.id, ev.currentTarget) }, "Abrir")))),
        g.ficheros.length > VISIBLES ? h("button", { type: "button", class: "btn btn-ghost btn-mini vp-mas", onclick: () => { P.expandido[g.clave] = !abierto; pintarPreview(); } },
          abierto ? "Ver menos" : `Ver los ${g.ficheros.length}`) : null));
    }
    return h("div", { class: "vp-bloque" }, partes);
  }
  function bloqueSesiones() {
    const s = P.ses;
    const cab = h("div", { class: "vp-sub" }, h("span", { class: "caps" }, "Últimas sesiones"));
    if (!s || s.estado === "cargando") return h("div", { class: "vp-bloque" }, cab, h("p", { class: "t-meta" }, "Leyendo las sesiones…"));
    if (s.estado === "error") return h("div", { class: "vp-bloque" }, cab, h("p", { class: "t-meta" }, "No se pudieron leer las sesiones: " + s.msg));
    const l = s.d.sesiones;
    if (!l.length) return h("div", { class: "vp-bloque" }, cab, h("p", { class: "t-meta", id: "vp-sin-ses" }, "Todavía no hay sesiones de este proyecto."));
    return h("div", { class: "vp-bloque" }, cab, h("ul", { class: "vp-lista", id: "vp-sesiones" }, l.map((x) => h("li", { class: "vp-fila" },
      h("button", { type: "button", class: "vp-ses", "data-sesion": x.id, title: "Abrir en «Sesiones»", onclick: () => { if (AP.backlog) { AP.backlog.abrir(); AP.backlog.abrirSesion(x.id); } } },
        h("span", { class: "t-meta" }, x.fecha || ""), h("span", { class: "vp-n" }, x.tema))))));
  }
  function pintarPreview() {
    const caja = $("#i-preview"), p = UI.proy;
    if (!p || typeof UI.sel !== "string") { caja.hidden = true; return; }
    caja.hidden = false;
    const nombre = p.nombre;
    const acciones = h("div", { class: "vp-acciones" },
      h("button", { type: "button", class: "btn btn-ghost btn-mini", id: "vp-abrir-carpeta", onclick: (ev) => abrirCarpeta(nombre, ev.currentTarget) }, AP.icono("carpeta"), "Abrir carpeta"),
      p.extra ? h("button", { type: "button", class: "btn btn-ghost btn-mini", id: "vp-quitar", onclick: () => { P.confirmar = true; pintarPreview(); } }, "Quitar de la lista") : null);
    const hijos = [h("div", { class: "vp-cab" }, h("h2", { class: "vp-titulo" }, nombre), acciones)];
    if (P.confirmar) hijos.push(h("div", { class: "vp-confirma", id: "vp-confirma", role: "alertdialog", "aria-label": "Confirmar" },
      h("span", { class: "t-body" }, `¿Quitar «${nombre}» de la lista? No se borra nada de la carpeta.`),
      h("button", { type: "button", class: "btn btn-primary btn-mini", id: "vp-quitar-si", onclick: () => quitar(nombre) }, "Sí, quitar"),
      h("button", { type: "button", class: "btn btn-ghost btn-mini", onclick: () => { P.confirmar = false; pintarPreview(); } }, "Cancelar")));
    if (P.errorQuitar) hijos.push(h("div", { class: "error", id: "vp-error" }, P.errorQuitar));
    const c = P.ctx;
    if (!c || c.estado === "cargando") hijos.push(h("p", { class: "t-meta", id: "vp-cargando" }, "Leyendo la carpeta del proyecto… (si está en OneDrive puede tardar)"));
    else if (c.estado === "error") hijos.push(h("p", { class: "error", id: "vp-error-ctx" }, c.msg === "No existe ese proyecto."
      ? "La carpeta de este proyecto ya no existe o no se puede abrir. " + (p.extra ? "Puedes quitarla de la lista." : "")
      : "No se pudo leer el contexto: " + c.msg));
    else hijos.push(bloqueFicheros(nombre, c.d));
    hijos.push(bloqueSesiones());
    caja.replaceChildren(...hijos);
  }

  AP.proyectos = { hace, etiquetas, resaltar, recientes: () => [...P.rec], favoritos: () => [...P.fav], alternarFav, recordar };
})();
