"use strict";
/* WhisperMeet: editor del plan de sesiones dentro de la ficha del proyecto (ola C de HOJA-DE-RUTA.md; sin llamadas al modelo salvo «Proponer plan»).
   - Bloque «Plan de sesiones» de la ficha (proyectos.js lo pide con AP.planEditor.bloque): sin plan, «Crear plan» y «Proponer plan con Claude»; con plan, el Gantt de
     solo lectura de siempre y «Editar plan».
   - Editor: lista de sesiones; cada una se despliega para editar nombre, fecha (selector), hora, objetivos y checks (añadir, quitar, reordenar), dependencias
     (casillas con las demás sesiones) y fichero prioritario (desplegable con los ficheros de 00. CONTEXTO (IA) que cumplen el formato). Subir y bajar con botones
     (teclado). Los ids de sesión los pone el servidor: aquí una sesión nueva lleva un id provisional «nueva-N».
   - GET/PUT /api/proyectos/{n}/plan. El PUT lleva la marca `version` que se recibió: si el fichero cambió fuera de la app, 409 y no se guarda. Los errores de validación (422)
     salen junto a su campo. «Cambios sin guardar» siempre visible; «Guardar» y «Descartar»; aviso al salir de la ficha (proyectos.js) y de la ventana con cambios.
   - «Proponer plan con Claude»: GET .../plan/proponer enseña lo que se leerá (gratis); POST lanza UNA llamada y devuelve un BORRADOR que no se guarda: las sesiones
     propuestas se añaden al editor una a una o todas y solo se escriben si el usuario pulsa «Guardar».
   Todo texto dinámico entra como nodo de texto (nunca como HTML). */
(() => {
  const AP = window.AP;
  if (!AP) return;
  const { h, $, api } = AP;
  const ENC = encodeURIComponent;
  const kb = (n) => (n >= 1000 ? `${Math.round(n / 1000)} kB` : `${n} B`);
  const enFoco = (id) => { const e = document.getElementById(id); if (e) e.focus({ preventScroll: false }); };
  const clon = (x) => JSON.parse(JSON.stringify(x));
  const SIN_NOMBRE = "Sesión sin nombre";
  /** Aviso de las sesiones del fichero que la app no lee (se conservan al guardar). Sale al editar y al crear. */
  function avisoDescartadas() {
    const n = (E.d && E.d.descartadas) || 0; if (!n) return null;
    return h("p", { class: "t-meta vp-aviso", id: "pe-descartadas" }, n === 1
      ? "El fichero del plan tiene 1 sesión que la app no puede leer (sin id, con id repetido o por encima del máximo). No se enseña aquí; al guardar se conserva en el fichero tal como está."
      : `El fichero del plan tiene ${n} sesiones que la app no puede leer (sin id, con id repetido o por encima del máximo). No se enseñan aquí; al guardar se conservan en el fichero tal como están.`);
  }
  /** Aviso de los .json de la carpeta de planes que no se pueden leer: solo junto a «Crear plan» (de un fichero ilegible no se sabe de qué proyecto es). */
  function avisoIlegibles() {
    const n = (E.d && E.d.ilegibles_total) || 0, nombres = (E.d && E.d.ilegibles) || []; if (!n) return null;
    const lista = nombres.join(", ") + (n > nombres.length ? ` y ${n - nombres.length} más` : "");
    return h("p", { class: "t-meta vp-aviso", id: "pe-ilegibles" }, n === 1
      ? `En la carpeta de planes hay 1 fichero que no se puede leer (${lista}). Si es el plan de este proyecto, arréglalo antes de crear uno nuevo.`
      : `En la carpeta de planes hay ${n} ficheros que no se pueden leer (${lista}). Si alguno es el plan de este proyecto, arréglalo antes de crear uno nuevo.`);
  }

  const nuevoEstado = () => ({ nombre: null, estado: "cargando", msg: "", d: null, editando: false, ses: [], base: "[]", version: "", abiertas: {}, errores: [], errorGeneral: "",
    conflicto: false, guardando: false, guardado: false, quitar: null, descartar: false, salir: null, contador: 0, ro: null, prop: null, enfoque: null });
  const NODO = h("div", { class: "vp-bloque pe", id: "pe" });   // el mismo nodo siempre: la ficha se repinta entera cuando llegan otras cargas y el editor no pierde su estado
  let E = nuevoEstado();

  // ------------------------------------------------------------ utilidades
  const sesionesDe = (d) => (d && d.plan ? clon(d.plan.sesiones) : []);
  const LIMITES = { max_sesiones: 20, max_objetivos: 12, max_checks: 12, max_dependencias: 6, max_nombre: 120, max_fecha: 80, max_objetivo: 200, max_check: 140 };
  const lim = () => ({ ...LIMITES, ...((E.d && E.d.limites) || {}) });
  const firma = (ses) => JSON.stringify(ses.map((s) => ({ id: s.id, nombre: s.nombre, fecha: s.fecha, fecha_iso: s.fecha_iso, hora: s.hora, objetivos: s.objetivos, checks: s.checks,
    fichero_prioritario: s.fichero_prioritario, depende_de: s.depende_de })));
  const sucio = () => E.editando && firma(E.ses) !== E.base;
  const fechaLarga = (iso) => { try { return new Date(iso + "T12:00:00").toLocaleDateString("es-ES", { weekday: "long", day: "numeric", month: "long", year: "numeric" }); } catch { return iso; } };
  const nombreDe = (s) => (s.nombre || "").trim() || SIN_NOMBRE;
  function idNuevo() {
    const usados = new Set(E.ses.map((s) => s.id.toLowerCase()));
    do { E.contador++; } while (usados.has("nueva-" + E.contador));
    return "nueva-" + E.contador;
  }
  const sesionVacia = () => ({ id: idNuevo(), nombre: "", fecha: "", fecha_iso: "", hora: "", participantes: "", objetivos: [], checks: [], fichero_prioritario: "", depende_de: [] });
  const erroresDe = (i, campo) => E.errores.filter((e) => e.indice === i && e.campo === campo).map((e) => e.mensaje);
  function limpiarError(i, campo) {
    const antes = E.errores.length;
    E.errores = E.errores.filter((e) => !(e.indice === i && e.campo === campo));
    if (E.errores.length !== antes) {
      document.querySelectorAll(`[data-err="${i}:${campo}"]`).forEach((p) => p.remove());
      document.querySelectorAll(`[data-campo="${i}:${campo}"]`).forEach((c) => { c.removeAttribute("aria-invalid"); c.removeAttribute("aria-describedby"); });
      resumen();
    }
  }

  // ------------------------------------------------------------ carga
  async function cargar(nombre) {
    const t = E.n = (E.n || 0) + 1;
    E.estado = "cargando"; E.msg = ""; render();
    try {
      const d = await api("GET", `/api/proyectos/${ENC(nombre)}/plan`);
      if (E.nombre !== nombre || E.n !== t) return;
      E.d = d; E.version = d.version; E.estado = "ok";
    } catch (e) {
      if (E.nombre !== nombre || E.n !== t) return;
      E.estado = "error"; E.msg = e.message;
    }
    render(); repintarFicha();
  }
  function repintarFicha() { if (AP.proyectos && AP.proyectos.repintarPanel) AP.proyectos.repintarPanel(E.nombre); }

  function abrir(nombre) { const n = E.n || 0; E = nuevoEstado(); E.n = n; E.nombre = nombre; NODO.replaceChildren(); cargar(nombre); }
  function cerrar() { const n = (E.n || 0) + 1; E = nuevoEstado(); E.n = n; NODO.replaceChildren(); }

  // ------------------------------------------------------------ edición
  function empezarEdicion(crear) {
    E.editando = true; E.guardado = false; E.errores = []; E.errorGeneral = ""; E.conflicto = false; E.quitar = null; E.descartar = false;
    E.ses = sesionesDe(E.d); E.abiertas = {};
    E.base = firma(E.ses);
    if (!E.ses.length && crear) { const s = sesionVacia(); E.ses.push(s); E.abiertas[s.id] = true; }
    if (E.ses.length === 1) E.abiertas[E.ses[0].id] = true;
    E.enfoque = E.ses.length ? "pe-nombre-" + E.ses[0].id : "pe-anadir";
    render();
  }
  function salirDeEdicion() { E.editando = false; E.ses = []; E.errores = []; E.errorGeneral = ""; E.conflicto = false; E.quitar = null; E.descartar = false; E.salir = null; render(); }
  function descartar() { E.descartar = false; salirDeEdicion(); enFoco(E.d && E.d.plan ? "pe-editar" : "pe-crear"); repintarFicha(); }

  async function guardar() {
    const nombre = E.nombre, t = E.n;
    E.guardando = true; E.errorGeneral = ""; E.errores = []; E.conflicto = false; E.guardado = false; render();
    try {
      const sesiones = E.ses.map((s) => ({ id: s.id, nombre: s.nombre, fecha: s.fecha, fecha_iso: s.fecha_iso, hora: s.hora, objetivos: s.objetivos.filter((x) => x.trim()),
        checks: s.checks.filter((x) => x.trim()), fichero_prioritario: s.fichero_prioritario, depende_de: s.depende_de }));
      const d = await api("PUT", `/api/proyectos/${ENC(nombre)}/plan`, { version: E.version, sesiones });
      if (E.nombre !== nombre || E.n !== t) return;
      E.d = d; E.version = d.version; E.guardando = false;
      salirDeEdicion(); E.guardado = true; E.prop = null; render();
      enFoco("pe-editar");
      if (AP.cargarProyectos) AP.cargarProyectos();   // la lista y el Gantt de la ficha se leen otra vez
    } catch (e) {
      if (E.nombre !== nombre || E.n !== t) return;
      E.guardando = false;
      if (e.status === 409) { E.conflicto = true; }
      else if (e.status === 422 && e.datos && Array.isArray(e.datos.errores)) {
        E.errores = e.datos.errores;
        for (const er of E.errores) if (er.indice != null && E.ses[er.indice]) E.abiertas[E.ses[er.indice].id] = true;
        const primero = E.errores.find((er) => er.indice != null && E.ses[er.indice]);
        E.enfoque = primero ? campoId(E.ses[primero.indice], primero.campo) : null;
        E.errorGeneral = E.errores.some((er) => er.indice == null) ? E.errores.find((er) => er.indice == null).mensaje : "";
      } else E.errorGeneral = e.message;
      render();
      if (E.conflicto) enFoco("pe-recargar");
    }
  }
  const campoId = (s, campo) => ({ nombre: "pe-nombre-" + s.id, fecha_iso: "pe-fecha-" + s.id, fecha: "pe-fecha-" + s.id, hora: "pe-hora-" + s.id, objetivos: "pe-objetivos-" + s.id + "-0",
    checks: "pe-checks-" + s.id + "-0", fichero_prioritario: "pe-fichero-" + s.id, depende_de: "pe-deps-" + s.id }[campo] || "pe-nombre-" + s.id);

  function mover(arr, j, dir) { const k = j + dir; if (k < 0 || k >= arr.length) return false; [arr[j], arr[k]] = [arr[k], arr[j]]; return true; }
  function moverSesion(i, dir) {
    if (!mover(E.ses, i, dir)) return;
    E.errores = []; const s = E.ses[i + dir];
    E.enfoque = (dir < 0 ? (i + dir > 0 ? "pe-sub-" : "pe-baj-") : (i + dir < E.ses.length - 1 ? "pe-baj-" : "pe-sub-")) + s.id;
    render();
  }
  function quitarSesion(i) {
    const s = E.ses[i]; E.ses.splice(i, 1); E.quitar = null; E.errores = [];
    for (const o of E.ses) o.depende_de = o.depende_de.filter((d) => d !== s.id);
    if (E.prop && E.prop.anadidas) for (const k of Object.keys(E.prop.anadidas)) if (E.prop.anadidas[k] === s.id) delete E.prop.anadidas[k];   // la propuesta quitada vuelve a poder añadirse
    delete E.abiertas[s.id];
    E.enfoque = E.ses.length ? "pe-toggle-" + E.ses[Math.min(i, E.ses.length - 1)].id : "pe-anadir";
    render();
  }
  function anadirSesion() {
    const s = sesionVacia(); E.ses.push(s); E.abiertas[s.id] = true; E.errores = []; E.enfoque = "pe-nombre-" + s.id; render();
  }

  // ------------------------------------------------------------ propuesta de Claude (borrador)
  async function verPrevia() {
    const nombre = E.nombre, t = E.n;
    E.prop = { fase: "previa", cargando: true, plan: null, error: "" }; render();
    try {
      const d = await api("GET", `/api/proyectos/${ENC(nombre)}/plan/proponer`);
      if (E.nombre !== nombre || E.n !== t) return;
      E.prop = { fase: "previa", plan: d.plan, error: "" };
    } catch (e) { if (E.nombre !== nombre || E.n !== t) return; E.prop = { fase: "previa", plan: null, error: e.message }; }
    render(); enFoco(E.prop.plan && E.prop.plan.leer.length ? "pe-prop-lanzar" : "pe-prop-cancelar");
  }
  async function proponer() {
    const nombre = E.nombre, t = E.n, previa = E.prop && E.prop.plan;
    E.prop = { fase: "esperando", plan: previa, error: "" }; render(); enFoco("pe-prop");
    try {
      const d = await api("POST", `/api/proyectos/${ENC(nombre)}/plan/proponer`, { nombres: E.editando ? E.ses.map((s) => s.nombre).filter((x) => x.trim()) : [] });
      if (E.nombre !== nombre || E.n !== t) return;
      E.prop = { fase: "resultado", plan: previa, r: d, anadidas: {}, error: "" };
    } catch (e) { if (E.nombre !== nombre || E.n !== t) return; E.prop = { fase: "previa", plan: previa, error: e.message }; }
    render(); enFoco(E.prop.fase === "resultado" ? "pe-prop" : "pe-prop-lanzar");
  }
  function anadirPropuesta(j, enBloque) {
    const r = E.prop && E.prop.r; if (!r || E.prop.anadidas[j]) return;
    if (!E.editando) empezarEdicion(false);
    const x = r.sesiones[j], l = lim();
    if (E.ses.length >= l.max_sesiones) { E.errorGeneral = `Un plan admite como máximo ${l.max_sesiones} sesiones.`; render(); return; }
    const s = sesionVacia();
    Object.assign(s, { nombre: x.nombre, objetivos: [...x.objetivos], checks: [...x.checks], fecha_iso: x.fecha_iso || "", hora: x.hora || "", fecha: x.fecha_iso ? fechaLarga(x.fecha_iso) : "",
      depende_de: (x.depende_de || []).map((n) => E.prop.anadidas[n - 1]).filter((id) => id && E.ses.some((o) => o.id === id)) });
    E.ses.push(s); E.prop.anadidas[j] = s.id; E.abiertas[s.id] = true; E.guardado = false;
    if (!enBloque) { E.enfoque = "pe-nombre-" + s.id; render(); }
  }
  function anadirTodas() {
    const r = E.prop && E.prop.r; if (!r) return;
    for (let j = 0; j < r.sesiones.length; j++) anadirPropuesta(j, true);
    E.enfoque = "pe-toggle-" + E.ses[E.ses.length - 1].id; render();
  }

  // ------------------------------------------------------------ vista
  const boton = (id, texto, clase, onclick, extra) => h("button", { type: "button", class: "btn btn-mini " + clase, id, onclick, ...(extra || {}) }, texto);
  function etiquetaCampo(id, texto) { return h("label", { class: "t-label", for: id }, texto); }
  function errorP(i, campo, id) {
    const m = erroresDe(i, campo);
    return m.length ? m.map((t, k) => h("p", { class: "pe-err t-meta", id: `pe-err-${id}${k ? "-" + k : ""}`, "data-err": `${i}:${campo}` }, t)) : [];
  }
  const marca = (i, campo) => (erroresDe(i, campo).length ? { "aria-invalid": "true", "data-campo": `${i}:${campo}` } : { "data-campo": `${i}:${campo}` });
  const describe = (i, campo, id) => (erroresDe(i, campo).length ? { "aria-describedby": "pe-err-" + id } : {});

  function resumen() {
    const el = document.getElementById("pe-estado"); if (!el) return;
    const n = E.errores.length;
    if (E.guardando) { el.textContent = "Guardando…"; el.className = "pe-estado t-meta"; }
    else if (n) { el.textContent = `Hay ${n} ${n === 1 ? "error" : "errores"} que corregir antes de guardar.`; el.className = "pe-estado t-meta pe-err"; }
    else if (sucio()) { el.textContent = "Cambios sin guardar"; el.className = "pe-estado t-meta pe-sucio"; }
    else { el.textContent = E.guardado ? "Plan guardado." : "Sin cambios"; el.className = "pe-estado t-meta soft"; }
    const g = document.getElementById("pe-guardar"); if (g) g.disabled = E.guardando || !sucio();
  }

  function itemsLista(s, i, tipo, etiqueta, plural, max, maxlen) {
    const items = s[tipo], clave = tipo === "objetivos" ? "objetivo" : "check";
    const filas = items.map((txt, j) => {
      const id = `pe-${tipo}-${s.id}-${j}`;
      return h("li", { class: "pe-item" },
        h("input", { type: "text", class: "input", id, value: txt, maxlength: maxlen, "aria-label": `${etiqueta} ${j + 1} de la sesión ${nombreDe(s)}`, ...marca(i, tipo), ...describe(i, tipo, `${s.id}-${tipo}`),
          oninput: (ev) => { s[tipo][j] = ev.currentTarget.value; limpiarError(i, tipo); resumen(); },
          onkeydown: (ev) => { if (ev.key === "Enter" && !ev.shiftKey && !ev.isComposing) { ev.preventDefault(); if (items.length < max) { items.splice(j + 1, 0, ""); E.enfoque = `pe-${tipo}-${s.id}-${j + 1}`; render(); } } } }),
        boton(`pe-${tipo}-sub-${s.id}-${j}`, AP.icono("arriba"), "btn-ghost btn-icono", () => { if (mover(items, j, -1)) { E.enfoque = `pe-${tipo}-${j > 1 ? "sub" : "baj"}-${s.id}-${j - 1}`; render(); } },
          { "aria-label": `Subir ${clave} ${j + 1}`, title: "Subir", disabled: j === 0 }),
        boton(`pe-${tipo}-baj-${s.id}-${j}`, AP.icono("abajo"), "btn-ghost btn-icono", () => { if (mover(items, j, 1)) { E.enfoque = `pe-${tipo}-${j < items.length - 2 ? "baj" : "sub"}-${s.id}-${j + 1}`; render(); } },
          { "aria-label": `Bajar ${clave} ${j + 1}`, title: "Bajar", disabled: j === items.length - 1 }),
        boton(`pe-${tipo}-del-${s.id}-${j}`, AP.icono("cerrar"), "btn-ghost btn-icono", () => { items.splice(j, 1); E.enfoque = items.length ? `pe-${tipo}-${s.id}-${Math.min(j, items.length - 1)}` : `pe-${tipo}-mas-${s.id}`; render(); },
          { "aria-label": `Quitar ${clave} ${j + 1}`, title: "Quitar" }));
    });
    return h("div", { class: "pe-campo" }, h("div", { class: "t-label", id: `pe-${tipo}-t-${s.id}` }, `${plural} · ${items.length}`),
      filas.length ? h("ul", { class: "pe-items", "aria-labelledby": `pe-${tipo}-t-${s.id}` }, filas) : null,
      errorP(i, tipo, `${s.id}-${tipo}`),
      boton(`pe-${tipo}-mas-${s.id}`, `Añadir ${clave}`, "btn-ghost", () => { items.push(""); E.enfoque = `pe-${tipo}-${s.id}-${items.length - 1}`; render(); }, { disabled: items.length >= max }));
  }

  function cuerpoSesion(s, i) {
    const l = lim(), otros = E.ses.filter((o) => o.id !== s.id), ficheros = (E.d && E.d.ficheros_contexto) || [];
    const opciones = [...ficheros]; if (s.fichero_prioritario && !opciones.includes(s.fichero_prioritario)) opciones.push(s.fichero_prioritario);
    const idN = "pe-nombre-" + s.id, idF = "pe-fecha-" + s.id, idH = "pe-hora-" + s.id, idP = "pe-fichero-" + s.id;
    const sel = h("select", { class: "input", id: idP, ...marca(i, "fichero_prioritario"), ...describe(i, "fichero_prioritario", `${s.id}-fichero_prioritario`), disabled: !opciones.length,
      onchange: (ev) => { s.fichero_prioritario = ev.currentTarget.value; limpiarError(i, "fichero_prioritario"); resumen(); } },
      h("option", { value: "" }, opciones.length ? "Ninguno" : "No hay ficheros NN-nombre.md en 00. CONTEXTO (IA)"),
      opciones.map((f) => h("option", { value: f }, ficheros.includes(f) ? f : `${f} (no está en la carpeta)`)));
    sel.value = s.fichero_prioritario || "";
    return h("div", { class: "pe-cuerpo", id: "pe-cuerpo-" + s.id, hidden: !E.abiertas[s.id] },
      h("div", { class: "pe-campo" }, etiquetaCampo(idN, "Nombre"),
        h("input", { type: "text", class: "input", id: idN, value: s.nombre, maxlength: l.max_nombre, required: true, ...marca(i, "nombre"), ...describe(i, "nombre", `${s.id}-nombre`),
          oninput: (ev) => { s.nombre = ev.currentTarget.value; limpiarError(i, "nombre"); const t = document.getElementById("pe-nom-" + s.id); if (t) t.textContent = nombreDe(s); resumen(); } }),
        errorP(i, "nombre", `${s.id}-nombre`)),
      h("div", { class: "pe-fila2" },
        h("div", { class: "pe-campo" }, etiquetaCampo(idF, "Fecha"),
          h("input", { type: "date", class: "input", id: idF, value: s.fecha_iso, ...marca(i, "fecha_iso"), ...describe(i, "fecha_iso", `${s.id}-fecha_iso`),
            onchange: (ev) => { s.fecha_iso = ev.currentTarget.value; s.fecha = s.fecha_iso ? fechaLarga(s.fecha_iso) : ""; limpiarError(i, "fecha_iso"); limpiarError(i, "fecha"); resumen(); } }),
          s.fecha && !s.fecha_iso ? h("p", { class: "t-meta soft" }, `En el plan: «${s.fecha}» (sin fecha exacta). Al elegir una fecha se sustituye.`) : null,
          errorP(i, "fecha_iso", `${s.id}-fecha_iso`), errorP(i, "fecha", `${s.id}-fecha`)),
        h("div", { class: "pe-campo" }, etiquetaCampo(idH, "Hora"),
          h("input", { type: "time", class: "input", id: idH, value: s.hora, step: "60", ...marca(i, "hora"), ...describe(i, "hora", `${s.id}-hora`),
            onchange: (ev) => { s.hora = ev.currentTarget.value; limpiarError(i, "hora"); resumen(); } }),
          errorP(i, "hora", `${s.id}-hora`))),
      itemsLista(s, i, "objetivos", "Objetivo", "Objetivos", l.max_objetivos, l.max_objetivo),
      itemsLista(s, i, "checks", "Check", "Checks de preparación", l.max_checks, l.max_check),
      h("fieldset", { class: "pe-campo pe-deps", id: "pe-deps-" + s.id, tabindex: "-1", ...marca(i, "depende_de"), ...describe(i, "depende_de", `${s.id}-depende_de`) },
        h("legend", { class: "t-label" }, "Depende de"),
        otros.length ? otros.map((o) => h("label", { class: "pe-check" },
          h("input", { type: "checkbox", checked: s.depende_de.includes(o.id), "data-dep": o.id,
            onchange: (ev) => { s.depende_de = ev.currentTarget.checked ? [...s.depende_de, o.id] : s.depende_de.filter((d) => d !== o.id); limpiarError(i, "depende_de"); resumen(); } }),
          h("span", { class: "t-body" }, `${E.ses.indexOf(o) + 1}. ${nombreDe(o)}`)))
          : h("p", { class: "t-meta soft" }, "No hay otras sesiones en el plan."),
        errorP(i, "depende_de", `${s.id}-depende_de`)),
      h("div", { class: "pe-campo" }, etiquetaCampo(idP, "Fichero prioritario"), sel,
        h("p", { class: "t-meta soft" }, "Entra el primero en el contexto de la reunión. Solo valen ficheros de 00. CONTEXTO (IA) con el formato NN-nombre.md."),
        errorP(i, "fichero_prioritario", `${s.id}-fichero_prioritario`)));
  }

  function filaSesion(s, i) {
    const abierta = !!E.abiertas[s.id];
    const meta = [s.fecha_iso ? s.fecha_iso.split("-").reverse().join("/") : s.fecha || "", s.hora, `${s.objetivos.filter((x) => x.trim()).length} obj.`].filter(Boolean).join(" · ");
    const quitando = E.quitar === s.id;
    return h("li", { class: "pe-ses", "data-id": s.id },
      h("div", { class: "pe-cab" },
        h("button", { type: "button", class: "pe-toggle", id: "pe-toggle-" + s.id, "aria-expanded": abierta ? "true" : "false", "aria-controls": "pe-cuerpo-" + s.id,
          onclick: () => { E.abiertas[s.id] = !E.abiertas[s.id]; E.enfoque = "pe-toggle-" + s.id; render(); } },
          h("span", { class: "pe-num t-meta" }, String(i + 1)), h("span", { class: "pe-nom t-body-m", id: "pe-nom-" + s.id }, nombreDe(s)), h("span", { class: "pe-meta t-meta soft" }, meta)),
        h("div", { class: "pe-mov" },
          boton("pe-sub-" + s.id, AP.icono("arriba"), "btn-ghost btn-icono", () => moverSesion(i, -1), { "aria-label": `Subir la sesión ${nombreDe(s)}`, title: "Subir", disabled: i === 0 }),
          boton("pe-baj-" + s.id, AP.icono("abajo"), "btn-ghost btn-icono", () => moverSesion(i, 1), { "aria-label": `Bajar la sesión ${nombreDe(s)}`, title: "Bajar", disabled: i === E.ses.length - 1 }),
          boton("pe-del-" + s.id, "Quitar", "btn-ghost", () => { E.quitar = s.id; E.enfoque = "pe-quitar-si-" + s.id; render(); }, { "aria-label": `Quitar la sesión ${nombreDe(s)}` }))),
      quitando ? h("div", { class: "vp-confirma pe-confirma", role: "alertdialog", "aria-label": "Confirmar" },
        h("span", { class: "t-body" }, `¿Quitar «${nombreDe(s)}»? Se pierden sus objetivos y checks al guardar; las sesiones que dependían de ella dejan de depender.`),
        boton("pe-quitar-si-" + s.id, "Sí, quitar", "btn-primary", () => quitarSesion(i)),
        boton("pe-quitar-no-" + s.id, "Cancelar", "btn-ghost", () => { E.quitar = null; E.enfoque = "pe-del-" + s.id; render(); })) : null,
      cuerpoSesion(s, i));
  }

  function bloquePropuesta() {
    const p = E.prop; if (!p) return null;
    const caja = (...hijos) => h("div", { class: "ar-bloque pe-prop", id: "pe-prop", tabindex: "-1", "aria-busy": p.fase === "esperando" ? "true" : "false" }, hijos.flat());
    const cab = h("div", { class: "vp-sub ar-cab" }, h("span", { class: "ar-tit" }, "Proponer plan con Claude"));
    const err = p.error ? h("div", { class: "error", id: "pe-prop-error", role: "alert" }, p.error) : null;
    if (p.fase === "esperando") {
      const n = (p.plan && p.plan.leer.length) || 0;
      return caja(cab, h("p", { class: "t-body", id: "pe-prop-cargando", role: "status" }, `Claude está leyendo ${n} ${n === 1 ? "documento" : "documentos"}… Puede tardar un minuto. Gasta tokens${p.plan && p.plan.modelo ? ` (modelo ${p.plan.modelo})` : ""}.`));
    }
    if (p.fase === "previa") {
      if (p.cargando) return caja(cab, h("p", { class: "t-meta", role: "status" }, "Mirando qué documentos hay…"));
      const pl = p.plan, leer = pl ? pl.leer : [], om = pl ? pl.omitidos : [], total = om.length + (pl ? pl.mas_omitidos || 0 : 0);
      return caja(cab,
        h("p", { class: "t-body", id: "pe-prop-intro" }, "Esto es lo que leerá Claude: los documentos de arranque, alcance, planificación y funcionales del proyecto. Nada sale de tu equipo hasta que pulses «Proponer»."),
        pl ? [h("div", { class: "vp-gtit t-label" }, `Se va a leer · ${leer.length}`),
          leer.length ? h("ul", { class: "vp-lista", id: "pe-prop-leer" }, leer.map((f) => h("li", { class: "vp-fila ar-fila", "data-rel": f.rel },
            h("span", { class: "vp-n", title: f.rel }, f.nombre, h("span", { class: "t-meta soft" }, ` · ${f.tipo_titulo}`)), h("span", { class: "vp-tam t-meta" }, kb(f.tam)))))
            : h("p", { class: "t-meta", id: "pe-prop-vacio" }, "No hay documentos de arranque, alcance o planificación que la app pueda leer. Puedes crear las sesiones a mano."),
          leer.length ? h("p", { class: "t-meta soft" }, `Hasta unos ${(pl.chars || 0).toLocaleString("es-ES")} caracteres en total.`) : null,
          total ? h("div", { class: "vp-gtit t-label" }, `No se va a leer · ${total}`) : null,
          total ? h("ul", { class: "vp-lista", id: "pe-prop-omitidos" }, om.map((o) => h("li", { class: "vp-fila ar-fila", "data-rel": o.rel },
            h("span", { class: "vp-n", title: o.rel }, o.nombre), h("span", { class: "vp-marca ar-motivo", title: o.motivo }, o.motivo)))) : null,
          h("p", { class: "t-meta", id: "pe-prop-aviso" }, `De cada documento solo sale texto, sin correos, teléfonos, secciones de contactos ni líneas con pinta de secreto. Es UNA llamada con tu licencia de Claude (modelo ${pl.modelo || "de Claude"}) y gasta tokens. La propuesta es un borrador: no se guarda nada hasta que pulses «Guardar».`)] : null,
        err,
        h("div", { class: "ar-acciones" },
          leer.length ? boton("pe-prop-lanzar", "Proponer", "btn-primary", proponer) : null,
          boton("pe-prop-cancelar", "Cancelar", "btn-ghost", () => { E.prop = null; render(); enFoco(E.editando ? "pe-anadir" : E.d && E.d.plan || E.ro ? "pe-editar" : "pe-proponer"); })));
    }
    const r = p.r, lista = r.sesiones || [], todas = lista.length && lista.every((_, j) => p.anadidas[j]);
    return caja(cab,
      h("p", { class: "t-meta soft", id: "pe-prop-datos" }, [r.modelo ? "modelo " + r.modelo : null, r.leidos ? `${r.leidos} ${r.leidos === 1 ? "documento leído" : "documentos leídos"}` : null, r.tokens ? `${r.tokens.toLocaleString("es-ES")} tokens` : null].filter(Boolean).join(" · ")),
      r.aviso ? h("p", { class: "t-meta vp-aviso", id: "pe-prop-aviso-r", role: "alert", title: r.aviso_detalle || null }, r.aviso + (r.aviso_detalle ? " (" + r.aviso_detalle + ")" : "")) : null,
      (r.no_leidos || []).length ? h("p", { class: "t-meta vp-aviso", id: "pe-prop-no-leidos" }, "No se pudo leer: " + r.no_leidos.map((o) => `${o.nombre} (${o.motivo})`).join("; ")) : null,
      lista.length ? [h("p", { class: "t-body" }, "Esto es un borrador. Añade las sesiones que te sirvan al editor y revísalas: no se guarda nada hasta que pulses «Guardar»."),
        h("ul", { class: "pe-props", id: "pe-props" }, lista.map((x, j) => h("li", { class: "pe-propuesta", "data-j": j },
          h("div", { class: "pe-propuesta-cab" }, h("span", { class: "t-body-m" }, `${j + 1}. ${x.nombre}`),
            boton("pe-prop-add-" + j, p.anadidas[j] ? "Añadida" : "Añadir", "btn-ghost", () => anadirPropuesta(j), { disabled: !!p.anadidas[j], "aria-label": `Añadir la sesión propuesta ${x.nombre}` })),
          h("ul", { class: "ar-lista" }, x.objetivos.map((o) => h("li", { class: "t-body" }, o))),
          h("p", { class: "t-meta soft" }, [x.fecha_iso ? "Fecha: " + x.fecha_iso.split("-").reverse().join("/") + (x.hora ? " " + x.hora : "") : "Sin fecha en los documentos",
            x.depende_de.length ? "Después de " + x.depende_de.join(", ") : null, x.fuente ? "Sale de: " + x.fuente.nombre : "Sin documento de origen indicado"].filter(Boolean).join(" · ")))))] : null,
      h("div", { class: "ar-acciones" },
        lista.length ? boton("pe-prop-todas", "Añadir todas", "btn-primary", anadirTodas, { disabled: !!todas }) : null,
        boton("pe-prop-cerrar", lista.length ? "Descartar la propuesta" : "Cerrar", "btn-ghost", () => { E.prop = null; render(); enFoco(E.editando ? "pe-anadir" : E.d && E.d.plan || E.ro ? "pe-editar" : "pe-proponer"); })));
  }

  function cabecera() {
    let extra = null;
    if (E.estado === "ok" && E.editando) extra = h("span", { class: "pe-estado t-meta", id: "pe-estado", role: "status", "aria-live": "polite" });
    else if (E.guardado) extra = h("span", { class: "pe-estado t-meta soft", id: "pe-estado", role: "status" }, "Plan guardado.");
    return h("div", { class: "vp-sub" }, h("span", { class: "caps" }, "Plan de sesiones"), extra);
  }

  function render() {
    const nodo = NODO, scroll = nodo.parentElement ? nodo.parentElement.scrollTop : 0;
    const partes = [cabecera()];
    if (E.estado === "cargando") partes.push(E.ro, h("p", { class: "t-meta", id: "pe-cargando" }, "Leyendo el plan…"));
    else if (E.estado === "error") partes.push(E.ro, h("p", { class: "error", id: "pe-error-lectura", role: "alert" }, "No se pudo leer el plan: " + E.msg), boton("pe-reintentar", "Reintentar", "btn-ghost", () => cargar(E.nombre)));
    else if (!E.editando) partes.push(vistaLectura());
    else partes.push(vistaEditor());
    nodo.replaceChildren(...partes.flat().filter(Boolean));
    if (E.editando) resumen();
    if (E.enfoque) { const id = E.enfoque; E.enfoque = null; const e = document.getElementById(id); if (e) e.focus({ preventScroll: false }); }
    if (nodo.parentElement) nodo.parentElement.scrollTop = scroll;
  }

  function vistaLectura() {
    const tiene = !!(E.d && E.d.plan) || !!E.ro, pr = E.prop;   // la lista de proyectos ya sabe que hay plan aunque el editor no lo pueda leer: se enseña el Gantt
    const partes = [];
    if (tiene) {
      if (E.ro) partes.push(E.ro);
      partes.push(h("div", { class: "ar-acciones" },
        boton("pe-editar", "Editar plan", "btn-ghost", () => empezarEdicion(false)),
        boton("pe-proponer", "Proponer más sesiones con Claude", "btn-ghost", verPrevia, { disabled: !!pr })));
    } else {
      partes.push(h("p", { class: "t-meta", id: "pp-sin-plan" }, "Este proyecto no tiene plan de sesiones. Un plan añade objetivos y checks a cada reunión (se elige al empezarla) y el Gantt de la ficha. Puedes crearlo aquí, sin tocar ningún fichero."),
        h("p", { class: "t-meta soft", id: "pe-aviso-tokens" }, "«Proponer plan con Claude» lee los documentos de arranque, alcance y planificación del proyecto y propone las sesiones. Lo lanzas tú, no se ejecuta solo, y gasta tokens; lo que propone es un borrador que revisas antes de guardar."),
        avisoDescartadas(), avisoIlegibles(),
        h("div", { class: "ar-acciones" },
          boton("pe-crear", "Crear plan", "btn-primary", () => empezarEdicion(true)),
          boton("pe-proponer", "Proponer plan con Claude", "btn-ghost", verPrevia, { disabled: !!pr })));
    }
    const bp = bloquePropuesta(); if (bp) partes.push(bp);
    return partes;
  }

  function vistaEditor() {
    const l = lim(), partes = [];
    partes.push(avisoDescartadas());
    if (E.d && E.d.plan && (E.d.plan.con_gantt || E.d.plan.con_ficha)) partes.push(h("p", { class: "t-meta soft", id: "pe-conserva" }, "El Gantt y la ficha del plan no se editan aquí y se conservan tal cual al guardar."));
    if (E.conflicto) partes.push(h("div", { class: "error", id: "pe-conflicto", role: "alert" }, "El plan ha cambiado fuera de la app desde que lo abriste. No se ha guardado nada. Recarga para ver la versión actual (tus cambios de esta pantalla se pierden). ",
      boton("pe-recargar", "Recargar el plan", "btn-ghost", () => { salirDeEdicion(); cargar(E.nombre); })));
    if (E.errorGeneral) partes.push(h("div", { class: "error", id: "pe-error", role: "alert" }, E.errorGeneral));
    const bp = bloquePropuesta(); if (bp) partes.push(bp);
    partes.push(h("ol", { class: "pe-lista", id: "pe-lista", "aria-label": "Sesiones del plan" }, E.ses.map(filaSesion)));
    if (!E.ses.length) partes.push(h("p", { class: "t-meta", id: "pe-vacio" }, "El plan no tiene sesiones. Añade la primera."));
    if (E.salir) partes.push(h("div", { class: "vp-confirma", id: "pe-salir", role: "alertdialog", "aria-label": "Confirmar" },
      h("span", { class: "t-body" }, "Hay cambios sin guardar en el plan. Si sales de la ficha se pierden."),
      boton("pe-salir-no", "Seguir editando", "btn-primary", () => { E.salir = null; render(); enFoco("pe-guardar"); }),
      boton("pe-salir-si", "Descartar y salir", "btn-ghost", () => { const f = E.salir; E.salir = null; salirDeEdicion(); f(); })));
    if (E.descartar) partes.push(h("div", { class: "vp-confirma", id: "pe-descartar-aviso", role: "alertdialog", "aria-label": "Confirmar" },
      h("span", { class: "t-body" }, "¿Descartar los cambios sin guardar?"),
      boton("pe-descartar-si", "Sí, descartar", "btn-primary", descartar),
      boton("pe-descartar-no", "Seguir editando", "btn-ghost", () => { E.descartar = false; render(); enFoco("pe-descartar"); })));
    partes.push(h("div", { class: "ar-acciones pe-pie" },
      boton("pe-anadir", "Añadir sesión", "btn-ghost", anadirSesion, { disabled: E.ses.length >= l.max_sesiones }),
      boton("pe-proponer", "Proponer sesiones con Claude", "btn-ghost", verPrevia, { disabled: !!E.prop }),
      h("span", { class: "pp-sep" }),
      boton("pe-descartar", "Descartar", "btn-ghost", () => { if (sucio()) { E.descartar = true; E.enfoque = "pe-descartar-si"; render(); } else descartar(); }),
      boton("pe-guardar", E.guardando ? "Guardando…" : "Guardar", "btn-primary", guardar, { disabled: true })));
    return partes;
  }

  // ------------------------------------------------------------ API para proyectos.js
  window.addEventListener("beforeunload", (ev) => { if (sucio()) { ev.preventDefault(); ev.returnValue = ""; } });
  AP.planEditor = {
    abrir, cerrar, sucio,
    /** El bloque «Plan de sesiones» de la ficha. `ro`: el Gantt de solo lectura de siempre (o null sin plan), que se enseña mientras no se edita. */
    bloque(nombre, ro) {
      if (E.nombre !== nombre) abrir(nombre);
      if (!E.editando) { E.ro = ro || null; render(); }
      return NODO;
    },
    /** Con cambios sin guardar, enseña la confirmación y devuelve true (quien llama NO sigue); `seguir` se ejecuta si el usuario descarta. */
    pedirSalir(seguir) {
      if (!sucio()) return false;
      E.salir = seguir; E.enfoque = "pe-salir-no"; render();
      const s = document.getElementById("pe-salir"); if (s) s.scrollIntoView({ block: "center" });
      return true;
    },
    estado: () => ({ nombre: E.nombre, estado: E.estado, editando: E.editando, sucio: sucio(), sesiones: E.ses.length, version: E.version }),
  };
})();
