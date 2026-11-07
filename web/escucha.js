"use strict";
/* Apuntes: escucha activa. Anotaciones propias (comentario, pregunta, idea) con el minuto actual, «Pregúntale» (una llamada por
   pregunta, solo si la lanzas), objetivos propios y sugeridos, cadencia adaptativa en el inicio, Ajustes del disparo y
   «Añadir carpeta de proyecto». Todo el texto dinámico entra con textContent. */
(() => {
  const AP = window.AP;
  if (!AP) return;
  const { S, UI, h, $, $$, api, mmss } = AP;
  const reducido = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const enReunion = () => ["grabando", "pausada"].includes(S.estado);
  const aviso = (e) => (AP.alerta ? AP.alerta(e) : console.error(e));
  const irA = (seg) => AP.hooks.irAlMinuto && AP.hooks.irAlMinuto(seg);
  const chipMin = (minuto, t) => (minuto ? h("button", { type: "button", class: "min t-meta", "data-t": t == null ? null : t, title: "Ir a ese momento de la transcripción", onclick: () => irA(t) }, minuto) : null);

  // ------------------------------------------------------------ cadencia en el inicio (Adaptativo por defecto)
  UI.cad = "equipo";
  $$("[data-cad]").forEach((b) => b.addEventListener("click", () => {
    UI.cad = b.dataset.cad;                               // app.js lo convierte en número; aquí es el modo
    $$("[data-cad]").forEach((x) => x.setAttribute("aria-checked", String(x === b)));
  }));
  api("GET", "/api/info").then((i) => {
    const d = (i.config && i.config.cadencia_defecto) || "equipo";
    UI.cad = d;
    $$("[data-cad]").forEach((x) => x.setAttribute("aria-checked", String(x.dataset.cad === d)));
  }).catch(() => {});

  // ------------------------------------------------------------ objetivos propios antes de empezar (proyecto sin plan u «Otra reunión»)
  UI.objetivosPropios = [];
  function planSesion() {
    const plan = UI.proy && UI.proy.plan;
    return plan && UI.sesionPlan ? plan.sesiones.find((s) => s.id === UI.sesionPlan) : null;
  }
  function pintarObjInicio() {
    const campo = $("#i-obj-campo");
    const ses = planSesion();
    const aplica = typeof UI.sel === "string" && !(ses && ses.objetivos && ses.objetivos.length);
    campo.hidden = !aplica;
    if (!aplica) return;
    const ul = $("#i-obj-lista");
    ul.replaceChildren(...UI.objetivosPropios.map((t, i) => h("li", {}, h("span", { class: "t-body" }, t),
      h("button", { type: "button", class: "btn btn-ghost btn-mini", "aria-label": "Quitar el objetivo: " + t, onclick: () => { UI.objetivosPropios.splice(i, 1); pintarObjInicio(); } }, "Quitar"))));
  }
  function sumarObjInicio() {
    const i = $("#i-obj-nuevo"), t = i.value.trim().slice(0, 200);
    if (!t || UI.objetivosPropios.length >= 12) return;
    UI.objetivosPropios.push(t); i.value = ""; pintarObjInicio(); i.focus();
  }
  $("#i-obj-add").addEventListener("click", sumarObjInicio);
  $("#i-obj-nuevo").addEventListener("keydown", (ev) => { if (ev.key === "Enter") { ev.preventDefault(); sumarObjInicio(); } });
  for (const sel of ["#i-lista", "#i-sesiones"]) new MutationObserver(pintarObjInicio).observe($(sel), { childList: true, attributes: true, subtree: true, attributeFilter: ["aria-selected"] });
  pintarObjInicio();
  AP.pintarObjInicio = pintarObjInicio;   // «Contexto de la reunión» (contexto-reunion.js) suma aquí los objetivos que el usuario acepta

  // ------------------------------------------------------------ añadir carpeta de proyecto (inicio y Ajustes)
  const fa = $("#f-add-carpeta");
  fa.addEventListener("submit", (ev) => {
    ev.preventDefault();
    AP.carpetas.anadir(() => ({ nombre: fa.nombre.value.trim(), ruta: fa.ruta.value.trim(), compartido: fa.compartido.checked }),
      $("[data-estado]", fa), $("[data-error]", fa), (r) => { fa.reset(); AP.carpetas.seleccionar(r.proyecto.nombre); });
  });
  const sa = $("#s-add-carpeta");
  function extrasAjustes(lista) {
    const c = $("#s-extras", sa);
    c.replaceChildren(...(lista || []).map((e) => h("div", { class: "fila-b" }, h("span", { title: e.ruta }, `${e.nombre}${e.compartido ? " (compartida)" : ""} · ${e.ruta}`),
      h("button", { type: "button", class: "btn btn-ghost btn-mini", onclick: async () => {
        try { const r = await AP.carpetas.quitar(e.nombre); extrasAjustes(r.proyectos_extra); AP.cargarProyectos(); } catch (x) { $("[data-error]", sa).textContent = x.message; $("[data-error]", sa).hidden = false; }
      } }, "Quitar"))));
  }
  $("[data-accion=add]", sa).addEventListener("click", () => {
    const f = (n) => $(`[data-f=${n}]`, sa);
    AP.carpetas.anadir(() => ({ nombre: f("nombre").value.trim(), ruta: f("ruta").value.trim(), compartido: f("compartido").checked }),
      $("[data-estado]", sa), $("[data-error]", sa), (r) => { f("nombre").value = f("ruta").value = ""; f("compartido").checked = false; extrasAjustes(r.proyectos_extra); AP.cargarProyectos(); });
  });
  // Ajustes: se rellenan al abrir (después del manejador de app.js) y se guardan en la misma petición de «Guardar»
  const CAMPOS_ADAPT = ["adaptativo_comprobar_s", "equipo_puntuacion_min", "equipo_enfriamiento_global_s", "equipo_enfriamiento_perfil_s", "equipo_rotacion_s",
    "equipo_palabras_min", "equipo_objetivo_sin_tratar_min", "presupuesto_tokens_hora"];
  $("#b-ajustes").addEventListener("click", async () => {
    try {
      const c = (await api("GET", "/api/info")).config, f = $("#f-ajustes");
      f.cadencia_defecto.value = c.cadencia_defecto || "equipo";
      CAMPOS_ADAPT.forEach((k) => { f[k].value = c[k]; });
      f.m_consulta.value = c.modelos.consulta || "haiku";
      extrasAjustes(c.proyectos_extra);
    } catch { /* app.js ya muestra el error de conexión */ }
  });
  $("#f-ajustes").addEventListener("submit", async () => {
    const f = $("#f-ajustes");
    const cambios = { cadencia_defecto: f.cadencia_defecto.value, modelos: { consulta: f.m_consulta.value } };
    CAMPOS_ADAPT.forEach((k) => { const v = Number(f[k].value); if (Number.isFinite(v) && f[k].value !== "") cambios[k] = Math.round(v); });
    try { const r = await api("PUT", "/api/config", cambios); if (UI.info) UI.info.config = r.config; } catch (e) { aviso(e); }
  });

  // ------------------------------------------------------------ anotaciones propias: comentario, pregunta, idea
  const ETQ = { comentario: "Comentario", pregunta: "Pregunta", idea: "Idea" };
  async function guardarEntrada(tipo) {
    const i = $("#r-rapida-t"), texto = i.value.trim();
    if (!texto || !enReunion()) return;
    try { await api("POST", "/api/sesion/entradas", { tipo, texto }); i.value = ""; i.focus(); } catch (e) { aviso(e); }
  }
  $$("#r-rapida [data-tipo]").forEach((b) => b.addEventListener("click", () => guardarEntrada(b.dataset.tipo)));
  $("#r-rapida-t").addEventListener("keydown", (ev) => { if (ev.key === "Enter") { ev.preventDefault(); guardarEntrada("comentario"); } });

  const T = { filas: new Map(), editando: null };
  function filaTuya(e) {
    let el = T.filas.get(e.id);
    if (!el) {
      el = h("article", { class: "tuya", "data-id": e.id });
      el._p = { c: h("div", { class: "tuya-c" }), tx: h("div", { class: "tx t-body" }) };
      el.append(el._p.c, el._p.tx);
      T.filas.set(e.id, el);
    }
    const p = el._p;
    if (T.editando === e.id) {
      const ta = h("textarea", { "aria-label": "Editar la anotación", maxlength: "500" }); ta.value = e.texto;
      const guardar = async () => { try { await api("PUT", "/api/sesion/entradas/" + e.id, { texto: ta.value }); T.editando = null; pintarTuyas(); } catch (x) { aviso(x); } };
      ta.addEventListener("keydown", (ev) => { if (ev.key === "Escape") { T.editando = null; pintarTuyas(); } else if (ev.key === "Enter" && (ev.ctrlKey || ev.metaKey)) { ev.preventDefault(); guardar(); } });
      p.tx.replaceChildren(ta, h("div", { class: "acciones-t" }, h("button", { type: "button", class: "btn btn-mini", onclick: guardar }, "Guardar"),
        h("button", { type: "button", class: "btn btn-ghost btn-mini", onclick: () => { T.editando = null; pintarTuyas(); } }, "Cancelar")));
      requestAnimationFrame(() => ta.focus());
    } else if (p.tx.textContent !== e.texto || p.tx.firstChild === null || p.tx.firstChild.nodeType !== 3) {
      p.tx.replaceChildren(document.createTextNode(e.texto));
    }
    const acc = h("span", { class: "acciones-t" });
    if (e.tipo === "pregunta") acc.append(h("button", { type: "button", class: "btn btn-ghost btn-mini", title: "Lanza esta pregunta a «Pregúntale» (una llamada)", onclick: () => preguntar(e.texto, "haiku") }, "Preguntar a la IA"));
    acc.append(h("button", { type: "button", class: "btn btn-ghost btn-mini", onclick: () => { T.editando = e.id; pintarTuyas(); } }, "Editar"),
      h("button", { type: "button", class: "btn btn-ghost btn-mini", onclick: async () => { try { await api("DELETE", "/api/sesion/entradas/" + e.id); } catch (x) { aviso(x); } } }, "Borrar"));
    p.c.replaceChildren(h("span", { class: "t-label cat" }, ETQ[e.tipo] || e.tipo), h("span", { class: "yo", title: "Anotación tuya" }, "tú"), chipMin(e.minuto, e.t_seg), ...(enReunion() ? [acc] : []));
    el.className = "tuya" + (el.classList.contains("barra") ? " barra" : "") + (el.classList.contains("barra-fuera") ? " barra-fuera" : "");
    el.dataset.tipo = e.tipo;
    return el;
  }
  function pintarTuyas() {
    const c = $("#r-tuyas");
    const lista = [...(S.entradas || [])].sort((a, b) => b.t_seg - a.t_seg);
    const nodos = lista.map(filaTuya);
    for (const k of [...T.filas.keys()]) if (!lista.some((e) => e.id === k)) T.filas.delete(k);
    if (nodos.length) nodos.unshift(h("div", { class: "grupo-h" }, h("span", { class: "t-label" }, "Tus anotaciones"), h("span", { class: "n t-meta" }, String(lista.length))));
    let ref = c.firstChild;
    for (const n of nodos) { if (n === ref) ref = ref.nextSibling; else c.insertBefore(n, ref); }
    while (ref) { const s = ref.nextSibling; ref.remove(); ref = s; }
  }

  // ------------------------------------------------------------ Pregúntale
  let enCurso = false;
  async function preguntar(texto, modelo) {
    texto = String(texto || "").trim();
    if (!texto || !enReunion() || enCurso) return;
    const det = $("#r-pregunta"); if (det) det.open = true;
    enCurso = true; actualizarBotonPregunta();
    try { await api("POST", "/api/sesion/consultar", { pregunta: texto, modelo }); } catch (e) { aviso(e); } finally { enCurso = false; actualizarBotonPregunta(); }
  }
  function actualizarBotonPregunta() {
    const b = $("#f-pregunta button[type=submit]");
    b.disabled = enCurso || !enReunion();
    b.textContent = enCurso ? "Preguntando…" : "Preguntar";
    $("#r-preg-estado").textContent = enCurso ? "Consultando…" : "Una llamada por pregunta, solo si la lanzas";
  }
  $("#f-pregunta").addEventListener("submit", (ev) => {
    ev.preventDefault();
    const f = ev.target, t = f.pregunta.value;
    if (!t.trim()) return;
    f.pregunta.value = "";
    preguntar(t, f.modelo.value);
  });
  function abrirContexto(fichero) {
    const b = $("#r-contexto");
    if (b && $("#r-drawer").hidden) b.click();
    setTimeout(() => {
      const hit = [...document.querySelectorAll("#r-ctx *")].find((n) => n.children.length === 0 && n.textContent.includes(fichero));
      if (hit) { hit.scrollIntoView({ block: "center", behavior: reducido() ? "auto" : "smooth" }); hit.classList.add("destino"); setTimeout(() => hit.classList.remove("destino"), 1600); }
    }, 300);
  }
  function pintarConsultas() {
    const c = $("#r-preguntas");
    const lista = [...(S.consultas || [])].reverse();
    const filas = lista.map((q) => {
      const r = h("div", { class: "consulta-r t-body" + (q.estado === "ok" && q.base === false ? " sin-base" : "") });
      r.textContent = q.estado === "en_curso" ? "Consultando…" : q.estado === "error" ? "No se pudo responder: " + q.error : q.respuesta;
      const meta = h("div", { class: "consulta-meta t-meta" }, chipMin(q.minuto, q.t_seg), h("span", {}, q.modelo + (q.tokens ? ` · ${AP.kfmt(q.tokens)} tokens` : "")));
      for (const ci of q.citas || []) {
        if (ci.minuto) meta.append(chipMin(ci.minuto, ci.t_seg));
        if (ci.fichero) meta.append(h("button", { type: "button", class: "fichero", title: "Abrir el contexto del proyecto", onclick: () => abrirContexto(ci.fichero) }, ci.fichero));
      }
      if (q.estado === "ok" && q.base === false) meta.append(h("span", {}, "sin base en los datos"));
      return h("article", { class: "consulta " + (q.estado === "en_curso" ? "en-curso" : q.estado === "error" ? "error" : ""), "data-id": q.id },
        h("div", { class: "consulta-p t-body" }, q.pregunta), r, meta);
    });
    const abiertaAntes = !!c.querySelector(".consulta-ant[open]");
    c.replaceChildren(...filas.slice(0, 1), ...(filas.length > 1 ? [h("details", Object.assign({ class: "consulta-ant" }, abiertaAntes ? { open: "" } : {}), h("summary", { class: "t-meta" }, `Anteriores (${filas.length - 1})`), ...filas.slice(1))] : []));
    if (!lista.length) c.append(h("div", { class: "t-meta soft" }, "Aún no has preguntado nada."));
    if ((S.consultas || []).some((q) => q.estado === "en_curso") !== enCurso) { enCurso = (S.consultas || []).some((q) => q.estado === "en_curso"); actualizarBotonPregunta(); }
  }

  // ------------------------------------------------------------ objetivos propios y sugeridos durante la reunión
  async function opObjetivo(operacion, n, texto) {
    try { await api("POST", "/api/sesion/objetivos", { operacion, n: n == null ? null : n, texto: texto || "" }); } catch (e) { aviso(e); }
  }
  function sumarObjetivo() {
    const i = $("#r-obj-nuevo"), t = i.value.trim();
    if (!t || !enReunion()) return;
    i.value = ""; opObjetivo("anadir", null, t);
  }
  $("#r-obj-add").addEventListener("click", sumarObjetivo);
  $("#r-obj-nuevo").addEventListener("keydown", (ev) => { if (ev.key === "Enter") { ev.preventDefault(); sumarObjetivo(); } });
  // Chip de progreso en la cabecera (y en la barra del Modo reunión): «3 de 4 objetivos · 12:40». El minuto es el del último objetivo
  // cubierto (el dato real del estado); sin objetivos confirmados no se muestra.
  function pintarProgresoObjetivos(activos) {
    const chip = $("#r-obj-prog");
    if (!chip) return;
    chip.hidden = !activos.length;
    if (!activos.length) { chip.replaceChildren(); chip.dataset.k = ""; return; }
    const cub = activos.filter((o) => o.estado === "cubierto");
    const ult = cub.filter((o) => o.minuto).sort((a, b) => (a.t_seg ?? 0) - (b.t_seg ?? 0)).pop();
    const clave = `${cub.length}/${activos.length}/${ult ? ult.minuto : ""}`;
    if (chip.dataset.k === clave) return;
    chip.dataset.k = clave;
    chip.classList.toggle("completo", cub.length === activos.length);
    chip.replaceChildren(...[h("span", { class: "op-n" }, `${cub.length} de ${activos.length}`), h("span", { class: "op-pal" }, " objetivos"),
      ult ? h("span", { class: "op-min" }, ` · ${ult.minuto}`) : null].filter(Boolean));   // replaceChildren(null) escribiría «null»
    chip.title = `${cub.length} de ${activos.length} objetivos cubiertos` + (ult ? `; el último, en el minuto ${ult.minuto}` : "");
  }
  function decorarObjetivos() {
    const os = S.objetivos || [];
    pintarProgresoObjetivos(os.filter((o) => !o.sugerido));
    $("#r-objetivos").hidden = !(S.sesion && enReunion()) && !os.length;
    $("#r-obj-edit").hidden = !enReunion();
    const activos = os.filter((o) => !o.sugerido);
    $("#r-obj-cuenta").textContent = activos.length ? `${activos.filter((o) => o.estado === "cubierto").length}/${activos.length} cubiertos` : "";
    for (const o of os) {
      const fila = document.querySelector(`#r-obj-lista .obj[data-n="${o.n}"]`);
      if (!fila) continue;
      fila.classList.toggle("sugerido", !!o.sugerido);
      let acc = fila.querySelector(".obj-sug");
      if (!acc) { acc = h("span", { class: "obj-sug" }); fila.append(acc); }
      const botones = [];
      if (o.sugerido) {
        botones.push(h("button", { type: "button", class: "btn btn-mini", title: "Confirma el objetivo: desde ahora se evalúa en cada análisis", onclick: () => opObjetivo("confirmar", o.n) }, "Confirmar"),
          h("button", { type: "button", class: "btn btn-ghost btn-mini", onclick: () => opObjetivo("descartar", o.n) }, "Descartar"));
      } else if (o.origen !== "plan" && enReunion()) {
        botones.push(h("button", { type: "button", class: "btn btn-ghost btn-mini", onclick: async () => {
          const nuevo = await AP.pedirTexto({ titulo: "Editar el objetivo", texto: "Escribe cómo debe quedar.", valor: o.texto, aceptar: "Guardar" });
          if (nuevo != null && nuevo.trim()) opObjetivo("editar", o.n, nuevo);
        } }, "Editar"), h("button", { type: "button", class: "btn btn-ghost btn-mini", onclick: () => opObjetivo("borrar", o.n) }, "Quitar"));
      }
      acc.replaceChildren(...botones);
      const tx = fila.querySelector(".obj-tx");
      let et = fila.querySelector(".etq-sug");
      if (o.sugerido && !et) tx.after(h("span", { class: "etq-sug", title: "Sugerido a partir del contexto y del tema: no se evalúa hasta que lo confirmes" }, "sugerido"));
      else if (!o.sugerido && et) et.remove();
    }
  }
  const previoObj = AP.hooks.pintarObjetivos;
  AP.hooks.pintarObjetivos = () => { if (previoObj) previoObj(); decorarObjetivos(); };

  // ------------------------------------------------------------ eventos
  const previo = AP.hooks.evento;
  AP.hooks.evento = (d) => {
    if (previo) previo(d);
    if (d.tipo === "estado" && d.estado === "grabando" && UI.objetivosPropios.length) { UI.objetivosPropios = []; pintarObjInicio(); }
    switch (d.tipo) {
      case "snapshot": case "estado":
        if ("entradas" in d) S.entradas = d.entradas;
        if ("consultas" in d) S.consultas = d.consultas;
        requestAnimationFrame(() => { pintarTuyas(); pintarConsultas(); actualizarBotonPregunta(); decorarObjetivos(); });
        break;
      case "entradas": S.entradas = d.entradas || []; requestAnimationFrame(pintarTuyas); break;
      case "consultas": S.consultas = d.consultas || []; requestAnimationFrame(pintarConsultas); break;
      case "objetivos": S.objetivos = d.objetivos || []; requestAnimationFrame(() => { AP.hooks.pintarObjetivos(); }); break;
    }
  };
  const reiniciar = AP.hooks.reiniciar;
  AP.hooks.reiniciar = () => {
    if (reiniciar) reiniciar();
    S.entradas = []; S.consultas = []; T.filas.clear(); T.editando = null; enCurso = false;
    $("#r-tuyas").replaceChildren(); $("#r-preguntas").replaceChildren(); $("#r-rapida-t").value = "";
  };
  actualizarBotonPregunta();
  pintarConsultas();
})();
