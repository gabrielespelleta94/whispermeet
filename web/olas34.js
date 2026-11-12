"use strict";
/* WhisperMeet, olas 3 y 4 en la interfaz (contratos: demo/api-ola3.md y demo/api-ola4.md). Todo sale de datos reales del servidor y el texto dinámico entra por textContent.
   Ola 3: bandeja de acciones (reunión y revisión), autonomía por tipo, preparación sugerida (brief), seguimiento de pendientes.
   Ola 4: palabras dudosas y corrección, «Esto está mal» y avisos silenciados, modo solo local y registro de envíos, plantillas, cartera y métricas. */
(() => {
  const AP = window.AP;
  if (!AP) return;
  const { S, UI, h, $, $$, api } = AP;
  const O = { acciones: [], autonomia: null, local: null, plantilla: null, plantillas: null, plantillaSel: "", mal: new Map(), envios: [], briefs: new Map(), bloques: new Map(), segCorr: null };
  S.acciones = O.acciones;
  const reducido = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const aSeg = (m) => { const p = String(m || "").split(":").map(Number); return p.length === 2 && p.every((x) => !Number.isNaN(x)) ? p[0] * 60 + p[1] : null; };
  const k = (n) => (n >= 1000 ? (n / 1000).toFixed(1).replace(".", ",") + "k" : String(Math.round(n || 0)));
  const pct = (x) => (x == null ? "—" : Math.round(x * 100) + " %");
  const num1 = (x) => (x == null ? "—" : String(Math.round(x * 10) / 10).replace(".", ","));
  const aviso = (e) => AP.avisarError(e);
  const fil = (xs) => xs.filter((x) => x != null && x !== false);   // replaceChildren(null) escribiría «null»
  const ORIGEN = { "Capitán": "coordinador", Lupa: "funcional", Arquitecto: "constructor", Auditor: "revisor", Sherpa: "estratega", Monitor: "monitor", Asesor: "asesor" };
  const chipOrigen = (o) => (ORIGEN[o] ? AP.chipAgente(ORIGEN[o]) : h("span", { class: "ag ag-tu" }, AP.icono("tu", "ag-ic"), h("span", { class: "ag-n" }, o || "Tú")));
  const chipMin = (minuto) => (minuto ? h("button", { type: "button", class: "min", title: "Ir a ese momento de la transcripción", onclick: () => { const t = aSeg(minuto); if (t != null && AP.hooks.irAlMinuto) AP.hooks.irAlMinuto(t); } }, minuto) : null);
  const enReunion = () => S.estado === "grabando" || S.estado === "pausada";
  const copiar = async (texto) => { try { await navigator.clipboard.writeText(texto); return true; } catch { const t = h("textarea", { style: "position:fixed;left:-9999px", "aria-hidden": "true" }); t.value = texto; document.body.append(t); t.select(); let ok = false; try { ok = document.execCommand("copy"); } catch { ok = false; } t.remove(); return ok; } };

  // ============================================================ 1. BANDEJA DE ACCIONES
  const TIPO = { pendiente: ["Pendiente", "pendiente"], pregunta: ["Pregunta", "pregunta"], cambio_contexto: ["Cambio al contexto", "carpeta"], correo: ["Correo", "correo"], recordatorio: ["Recordatorio", "reloj"] };
  const post = (a, ruta, cuerpo) => api("POST", `/api/acciones/${a.id}/${ruta}`, cuerpo).catch(aviso);
  async function editar(a) {
    const t = await AP.pedirTexto({ titulo: "Editar la acción", texto: "Cambia el texto como quieras. No se aplica nada hasta que la aceptes.", valor: a.texto, aceptar: "Guardar" });
    if (t != null && t.trim()) api("PUT", `/api/acciones/${a.id}`, { texto: t.trim().slice(0, 300) }).catch(aviso);
  }
  function datosDe(a) {
    const d = a.datos || {}, p = [];
    if (a.tipo === "pendiente") { if (d.dueno) p.push("Responsable: " + d.dueno); if (d.fecha) p.push("Fecha: " + d.fecha); }
    if (a.tipo === "pregunta" && d.objetivo_texto) p.push("Para cerrar: " + d.objetivo_texto);
    if (a.tipo === "cambio_contexto" && d.fichero) p.push("Fichero: " + d.fichero);
    return p.join(" · ");
  }
  function accionEl(a) {
    const [etq, ico] = TIPO[a.tipo] || [a.tipo, "info"];
    const b = [];
    let estado = null;
    if (a.estado === "propuesta") {
      if (a.modo !== "avisar") b.push(h("button", { type: "button", class: "btn btn-mini", "data-accion": "aceptar", onclick: () => post(a, "aceptar") }, "Aceptar"),
        h("button", { type: "button", class: "btn btn-mini btn-ghost", "data-accion": "editar", onclick: () => editar(a) }, "Editar"),
        h("button", { type: "button", class: "btn btn-mini btn-ghost", "data-accion": "descartar", onclick: () => post(a, "descartar") }, "Descartar"));
      else estado = "Solo es un aviso";
    } else if (a.estado === "aceptada" && a.auto) {
      estado = "Lo hizo el equipo";
      b.push(h("button", { type: "button", class: "btn btn-mini btn-ghost", "data-accion": "deshacer", title: "Vuelve a ponerla como propuesta, sin aplicar", onclick: () => post(a, "reabrir") }, AP.icono("deshacer", "ic-s"), "Deshacer"));
    } else if (a.estado === "aceptada") {
      estado = "Aceptada";
      b.push(h("button", { type: "button", class: "btn btn-mini btn-ghost", "data-accion": "hecha", onclick: () => post(a, "hecha") }, "Marcar hecha"), h("button", { type: "button", class: "btn btn-mini btn-ghost", "data-accion": "reabrir", onclick: () => post(a, "reabrir") }, "Deshacer"));
    } else if (a.estado === "hecha") {
      estado = "Hecha";
      b.push(h("button", { type: "button", class: "btn btn-mini btn-ghost", "data-accion": "reabrir", onclick: () => post(a, "reabrir") }, "Reabrir"));
    } else if (a.estado === "descartada") {
      estado = "Descartada";
      b.push(h("button", { type: "button", class: "btn btn-mini btn-ghost", "data-accion": "reabrir", onclick: () => post(a, "reabrir") }, "Recuperar"));
    }
    const dt = datosDe(a);
    return h("li", { class: "acc-item acc-" + a.estado + (a.prioridad === "fijo" ? " acc-fija" : ""), "data-id": a.id, "data-estado": a.estado, "data-modo": a.modo, "data-auto": a.auto ? "1" : "0" },
      h("div", { class: "acc-tx" },
        h("div", { class: "acc-l1" }, chipOrigen(a.origen), h("span", { class: "acc-tipo t-label" }, AP.icono(ico, "ic-s"), etq), a.prioridad === "fijo" ? h("span", { class: "av-fijo-et t-label" }, AP.icono("fijar", "ic-s"), "Fijo") : null, chipMin(a.minuto),
          estado ? h("span", { class: "acc-estado t-label" }, estado) : null),
        h("span", { class: "acc-t t-body-m" }, a.texto, a.editada ? h("span", { class: "t-meta soft" }, " (editada)") : null),
        dt ? h("span", { class: "acc-d t-meta" }, dt) : null,
        a.cita && a.cita.texto ? h("blockquote", { class: "acc-cita t-meta" }, "«" + a.cita.texto + "»", a.cita.minuto ? h("span", { class: "soft" }, " · " + a.cita.minuto) : null) : null),
      b.length ? h("div", { class: "acc-bt" }, ...b) : null);
  }
  const orden = (a, b) => (a.prioridad === "fijo" ? 0 : 1) - (b.prioridad === "fijo" ? 0 : 1) || (a.estado === "propuesta" ? 0 : 1) - (b.estado === "propuesta" ? 0 : 1) || String(a.creada).localeCompare(String(b.creada));
  /** Pinta la lista de acciones en `cont`. Las descartadas van aparte, plegadas, con «Recuperar». */
  function pintarEn(cont, titulo, excluir) {
    const todas = excluir ? O.acciones.filter((a) => !excluir.includes(a.tipo)) : O.acciones;
    const vivas = todas.filter((a) => a.estado !== "descartada").sort(orden), desc = todas.filter((a) => a.estado === "descartada");
    const pend = vivas.filter((a) => a.estado === "propuesta" && a.modo !== "avisar").length;
    cont.hidden = !todas.length;
    if (!todas.length) { cont.replaceChildren(); return; }
    cont.replaceChildren(...fil([h("div", { class: "acc-cab" }, h("span", { class: "t-label" }, titulo || "Acciones propuestas"), h("span", { class: "n t-meta" }, pend ? `${pend} por decidir` : String(vivas.length))),
      vivas.length ? h("ul", { class: "acc-lista" }, ...vivas.map(accionEl)) : h("p", { class: "t-meta soft" }, "Todo descartado."),
      desc.length ? h("details", { class: "acc-desc" }, h("summary", { class: "t-meta" }, `Descartadas (${desc.length})`), h("ul", { class: "acc-lista" }, ...desc.map(accionEl))) : null]));
  }
  function pintarReunion() { const c = $("#ahora-acciones"); if (c) pintarEn(c, "Acciones propuestas"); }
  /** Sección «Acciones propuestas» de la revisión (revision.js la monta en el último paso). */
  /** Los `cambio_contexto` no salen aquí: ya se aceptan o rechazan en el paso 2 de la revisión (un solo sitio). */
  function seccionAcciones() { const s = h("section", { class: "sec rev-acciones", id: "rev-acciones", "aria-label": "Acciones propuestas" }); pintarEn(s, "Acciones propuestas", ["cambio_contexto"]); if (s.hidden) { s.hidden = false; s.append(h("p", { class: "t-meta soft" }, "Esta reunión no ha dejado acciones propuestas.")); } return s; }

  // ============================================================ MODO LOCAL: indicador, aviso y cierre
  function pintarLocal() {
    const l = O.local, activo = !!(l && l.activo) && (enReunion() || S.estado === "revision");
    const chip = $("#r-local"), aviso_ = $("#ahora-local");
    if (chip) chip.hidden = !activo;
    if (aviso_) aviso_.hidden = !activo || !enReunion();
    document.body.dataset.local = activo ? "1" : "0";
  }
  function bannerLocal(rev) {
    if (!rev || !rev.modo_local) return null;
    const hay = !!rev.agentes_pendientes;
    return h("section", { class: "sec rev-local", id: "rev-local", role: "status" },
      h("div", { class: "rev-local-t" }, AP.icono("candado", "ic-s"), h("b", {}, "Reunión en modo solo local")),
      h("p", { class: "t-body" }, hay ? "No se ha enviado nada a Claude: el resumen es local (objetivos, checks y tus notas) y no hay cambios al contexto que revisar." : "Los agentes del cierre ya se han lanzado con tu permiso."),
      hay ? h("button", { type: "button", class: "btn", id: "rev-agentes", onclick: lanzarAgentes }, "Analizar con el equipo") : null);
  }
  async function lanzarAgentes() {
    const ok = await AP.confirmar({ titulo: "Analizar con el equipo", texto: "Esta reunión se grabó en modo solo local y nada ha salido de este equipo.\n\nSi sigues, el texto de la transcripción, las notas y el contexto del proyecto se enviarán a Claude para hacer el resumen final y proponer cambios al contexto.\n\n¿Quieres enviarlo ahora?", aceptar: "Sí, enviar a Claude", cancelar: "No, seguir en local", peligro: true });
    if (!ok) return;
    try { await api("POST", "/api/revision/agentes"); } catch (e) { aviso(e); }
  }

  // ============================================================ MÉTRICAS de la sesión (revisión)
  function seccionMetricas(m) {
    if (!m) return null;
    const o = m.objetivos_resumen || {}, a = m.avisos || {}, t = m.tokens || {};
    const tile = (titulo, valor, detalle) => h("div", { class: "met-t" }, h("span", { class: "t-label" }, titulo), h("span", { class: "met-v" }, valor), detalle ? h("span", { class: "t-meta soft" }, detalle) : null);
    return h("section", { class: "sec rev-metricas", id: "rev-metricas", "aria-label": "Cómo ha ido la reunión" }, h("span", { class: "t-label" }, "Cómo ha ido la reunión"),
      h("div", { class: "met-grid" },
        tile("Objetivos cerrados", `${o.cerrados == null ? 0 : o.cerrados} de ${o.total == null ? 0 : o.total}`, o.ratio_cerrados == null ? "Sin objetivos" : pct(o.ratio_cerrados)),
        tile("Hasta cerrar", o.minutos_medio_hasta_cierre == null ? "—" : num1(o.minutos_medio_hasta_cierre) + " min", o.primer_cierre_min ? "Primer cierre: " + o.primer_cierre_min : "Sin cierres con tiempo"),
        tile("Avisos aceptados", `${a.aceptados || 0} de ${(a.aceptados || 0) + (a.descartados || 0)}`, `${a.descartados || 0} descartados` + (a.marcados_mal ? ` · ${a.marcados_mal} «mal»` : "")),
        tile("Tokens", k(t.total), `${t.llamadas || 0} llamadas · ${m.duracion || ""}`)));
  }

  // ============================================================ 2. AUTONOMÍA (Ajustes › Equipo) y AVISOS SILENCIADOS
  const NIVEL = { avisar: "Avisar", proponer: "Proponer", hacer: "Hacer" };
  const TIPO_AUT = { pregunta: "Preguntas al cliente", pendiente: "Pendientes detectados", cambio_contexto: "Cambios al contexto", correo: "Correos de cierre", recordatorio: "Recordatorios", consolidar_pendientes: "Cerrar pendientes del seguimiento" };
  let aut = null;
  async function cargarAutonomia() {
    const cont = $("#aj-aut-lista"); if (!cont) return;
    try {
      aut = await api("GET", "/api/autonomia"); O.autonomia = aut.autonomia;
      cont.replaceChildren(...aut.tipos.map((t) => {
        const ok = aut.hacer_admitido.includes(t);
        const sel = h("select", { class: "input", name: "aut_" + t, "data-tipo": t, "aria-label": TIPO_AUT[t] || t, "aria-describedby": "aut-n-" + t },
          ...aut.niveles.map((n) => h("option", { value: n, disabled: n === "hacer" && !ok ? true : null }, NIVEL[n] + (n === "hacer" && !ok ? " (no disponible)" : ""))));
        sel.value = aut.autonomia[t] || "proponer";
        return h("label", { class: "aj-aut-f" }, h("span", { class: "aj-aut-t" }, TIPO_AUT[t] || t), sel,
          h("span", { class: "t-meta soft", id: "aut-n-" + t }, ok ? "«Hacer» es posible: es local y se puede deshacer." : "«Hacer» no está disponible: sale de este equipo o no se puede deshacer."));
      }));
    } catch (e) { cont.replaceChildren(h("span", { class: "error t-meta" }, "No se pudo leer: " + e.message)); }
  }
  async function guardarAutonomia() {
    if (!aut) return;
    const cambios = {};
    $$("#aj-aut-lista select[data-tipo]").forEach((s) => { if (s.value !== aut.autonomia[s.dataset.tipo]) cambios[s.dataset.tipo] = s.value; });
    if (!Object.keys(cambios).length) return;
    try { aut = await api("PUT", "/api/autonomia", { autonomia: cambios }); O.autonomia = aut.autonomia; if (UI.info && UI.info.config) UI.info.config.autonomia = aut.autonomia; } catch (e) { aviso(e); }
  }
  async function cargarSilenciados() {
    const cont = $("#aj-sil-lista"); if (!cont) return;
    try {
      const r = await api("GET", "/api/reglas-silencio");
      cont.replaceChildren(...(r.reglas.length ? r.reglas.map((g) => h("div", { class: "aj-sil-f", "data-id": g.id },
        h("span", { class: "aj-sil-t" }, h("span", { class: "t-body-m" }, g.ejemplo || g.clave), h("span", { class: "t-meta soft" }, ` ${g.veces ? "· callado " + g.veces + (g.veces === 1 ? " vez" : " veces") : ""}`)),
        h("button", { type: "button", class: "btn btn-mini btn-ghost", "aria-label": "Volver a recibir avisos como: " + (g.ejemplo || g.clave), onclick: async (ev) => { ev.currentTarget.disabled = true; try { await api("DELETE", "/api/reglas-silencio/" + g.id); } catch (e) { aviso(e); } cargarSilenciados(); } }, "Borrar")))
        : [h("span", { class: "t-meta soft" }, "No has silenciado ningún aviso.")]));
    } catch (e) { cont.replaceChildren(h("span", { class: "error t-meta" }, "No se pudo leer: " + e.message)); }
  }

  // ============================================================ 3. PRIVACIDAD: modo local y registro de envíos
  async function cargarPrivacidad() {
    const caja = $("#aj-solo-local"), chk = $("#aj-modo-local"), est = $("#aj-local-estado");
    try {
      const l = await api("GET", "/api/modo-local");
      if (typeof l.activo === "boolean") { O.local = l; caja.hidden = false; chk.checked = !!(enReunion() ? l.sesion : l.config) || l.activo; est.textContent = enReunion() ? "Esta reunión ya está en curso: el cambio vale solo para ella." : ""; }
      else caja.hidden = true;
    } catch { caja.hidden = true; }
    const sec = $("#aj-registro-envios"), lista = $("#aj-registro-lista"), res = $("#aj-registro-res");
    try {
      const r = await api("GET", "/api/envios?limite=60");
      const filas = Array.isArray(r.envios) ? r.envios : [];
      sec.hidden = false;
      if (!Array.isArray(r.envios)) { sec.hidden = true; return; }
      const rs = r.resumen || {};
      const audioNube = minNube(rs.nube && rs.nube.audio_s);
      res.textContent = filas.length ? `${rs.llamadas || 0} llamadas en total · ${k((rs.entrada || 0) + (rs.salida || 0))} tokens · ${rs.bloqueadas || 0} bloqueadas por el modo local` + (audioNube ? ` · ${audioNube} min de audio a la nube` : "") : "Todavía no ha salido nada de este equipo.";
      lista.replaceChildren(...[...filas].reverse().map(filaEnvio));
    } catch { sec.hidden = true; }
  }
  const NOMBRE_ENVIO = { Coordinador: "Capitán", "Analista funcional": "Lupa", Constructor: "Arquitecto", Revisor: "Auditor", Estratega: "Sherpa" };
  const minNube = (s) => (s > 0 ? Math.max(1, Math.round(s / 60)) : 0);
  const esNube = (e) => !!e && (e.tipo === "transcripcion_nube" || e.tarea === "transcripcion_nube" || e.tarea === "nube_prueba");   // el evento `envio` del WebSocket pisa `tipo`: `tarea` también lo dice
  function filaNube(e) {
    const hora = String(e.ts || "").slice(11, 16), host = e.host ? " → " + e.host : "";
    const detalle = e.bloqueado ? "bloqueada por el modo solo local" : e.tarea === "nube_prueba" ? "prueba de conexión" + host
      : `${Math.round(e.audio_s || 0)} s de audio en ${e.trozos || 0} ${e.trozos === 1 ? "trozo" : "trozos"}${host}${e.ok === false ? " · con fallos" : ""}`;
    return h("div", { class: "aj-reg-f t-meta" + (e.bloqueado ? " bloqueado" : ""), "data-tipo": "transcripcion_nube" },
      h("span", { class: "aj-reg-h" }, hora), h("span", { class: "aj-reg-d" }, "Transcripción en la nube"), h("span", { class: "aj-reg-q" }, detalle));
  }
  function filaEnvio(e) {
    if (esNube(e)) return filaNube(e);
    const hora = String(e.ts || "").slice(11, 16);
    const estado = e.bloqueado ? "Bloqueado: modo local" : e.ok ? "Enviado" : "Con error";
    return h("div", { class: "aj-reg-f t-meta" + (e.bloqueado ? " bloqueado" : ""), title: e.extracto || "" },
      h("span", { class: "aj-reg-h" }, hora), h("span", { class: "aj-reg-d" }, NOMBRE_ENVIO[e.agente] || e.agente || "", e.modelo ? " · " + e.modelo : ""), h("span", { class: "aj-reg-q" }, `${estado}${e.bloqueado ? "" : " · " + k((e.entrada || 0) + (e.salida || 0)) + " tokens"}`));
  }
  // «Modo solo local» actúa al momento (no espera a «Guardar»): sin reunión cambia la configuración; con reunión, solo esa reunión
  document.addEventListener("change", async (ev) => {
    if (ev.target && ev.target.id === "aj-modo-local") {
      const chk = ev.target;
      try { O.local = await api("POST", "/api/modo-local", { activo: chk.checked }); $("#aj-local-estado").textContent = chk.checked ? "Activado: no se enviará nada a Claude." : "Desactivado."; pintarLocal(); } catch (e) { aviso(e); chk.checked = !chk.checked; }
    }
  });

  // ---- registro de envíos de ESTA reunión (pestaña Sesión)
  function pintarEnviosSesion() {
    let sec = $("#ses-envios");
    const tab = $("#tab-sesion");
    if (!tab) return;
    if (!sec) { sec = h("details", { class: "ses-envios", id: "ses-envios", open: true }, h("summary", { class: "t-label" }, "Lo que ha salido de este equipo en esta reunión"), h("div", { class: "ses-env-res t-meta", id: "ses-env-res" }), h("div", { class: "aj-reg-lista", id: "ses-env-lista" })); tab.append(sec); }
    const tot = O.envios.reduce((a, e) => esNube(e) ? { ...a, b: a.b + (e.bloqueado ? 1 : 0), s: a.s + (e.bloqueado ? 0 : e.audio_s || 0) }
      : ({ ...a, n: a.n + (e.bloqueado ? 0 : 1), b: a.b + (e.bloqueado ? 1 : 0), t: a.t + (e.entrada || 0) + (e.salida || 0) }), { n: 0, b: 0, t: 0, s: 0 });
    $("#ses-env-res").textContent = O.envios.length ? `${tot.n} llamadas a Claude · ${k(tot.t)} tokens` + (minNube(tot.s) ? ` · ${minNube(tot.s)} min de audio a la nube` : "") + (tot.b ? ` · ${tot.b} bloqueadas por el modo local` : "") : (O.local && O.local.activo ? "Modo solo local: no ha salido nada." : "Todavía no ha salido nada.");
    $("#ses-env-lista").replaceChildren(...[...O.envios].reverse().slice(0, 40).map(filaEnvio));
  }
  async function cargarEnviosSesion() {
    const id = S.sesion && S.sesion.id; if (!id) return;
    try { const r = await api("GET", "/api/envios?sesion=" + encodeURIComponent(id) + "&limite=200"); O.envios = r.envios || []; } catch { /* sin datos */ }
    pintarEnviosSesion();
  }

  // ============================================================ PREPARACIÓN SUGERIDA (brief)
  function textoBrief(b) {
    const l = (t, xs) => (xs && xs.length ? `${t}\n${xs.map((x) => "- " + x).join("\n")}\n\n` : "");
    return `Preparación de la reunión · ${b.proyecto}\n\n` + l("Objetivos propuestos", b.objetivos) + l("Preguntas para hacer", b.preguntas) + l("Datos que pedir", b.datos) + l("Pendientes abiertos", (b.pendientes || []).map((p) => p.texto + (p.responsable ? ` (${p.responsable})` : ""))) + l("Para retomar", (b.recordatorios || []).map((r) => r.texto));
  }
  /** Crea el bloque de preparación de un proyecto. Se carga al crearlo y con «Actualizar»; sin modelo muestra la versión local sin errores. */
  function crearBrief(nombre, opciones = {}) {
    const raiz = h("div", { class: "brief", "data-proyecto": nombre, "aria-live": "polite" });
    let estado = "cargando", dat = null, msg = "", copiado = "";
    const anadir = (t) => { UI.objetivosPropios = UI.objetivosPropios || []; if (UI.objetivosPropios.length >= 12 || UI.objetivosPropios.some((x) => x.toLowerCase() === t.toLowerCase())) return; UI.objetivosPropios.push(t.slice(0, 200)); if (AP.pintarObjInicio) AP.pintarObjInicio(); pintar(); };
    const lista = (titulo, xs, conAnadir) => (xs && xs.length ? h("div", { class: "brief-sec" }, h("span", { class: "t-label" }, titulo), h("ul", { class: "brief-lista" }, ...xs.map((x) => {
      const ya = conAnadir && (UI.objetivosPropios || []).some((o) => o.toLowerCase() === String(x).toLowerCase());
      return h("li", { class: "t-body" }, h("span", { class: "brief-t" }, x), conAnadir ? h("button", { type: "button", class: "btn btn-mini btn-ghost brief-anadir", disabled: ya ? true : null, "aria-label": (ya ? "Ya añadido: " : "Añadir a los objetivos de la reunión: ") + x, onclick: () => anadir(x) }, ya ? "Añadido" : "Añadir") : null);
    }))) : null);
    function pintar() {
      if (estado === "cargando") { raiz.replaceChildren(h("p", { class: "t-meta brief-carga", role: "status" }, "Preparando sugerencias a partir de las últimas sesiones…")); raiz.setAttribute("aria-busy", "true"); return; }
      raiz.removeAttribute("aria-busy");
      if (estado === "error") { raiz.replaceChildren(h("p", { class: "error t-meta" }, "No se pudo preparar la sugerencia: " + msg), h("button", { type: "button", class: "btn btn-mini", onclick: () => cargar(true) }, "Reintentar")); return; }
      const b = dat;
      const vacio = !(b.objetivos.length || b.preguntas.length || b.datos.length || (!opciones.sinPendientes && (b.pendientes || []).length) || (b.recordatorios || []).length);
      raiz.replaceChildren(...fil([
        h("div", { class: "brief-barra" }, h("span", { class: "t-meta soft" }, (b.origen === "local" ? "Versión local, sin Claude" : "Preparado con Claude") + (b.generado ? " · " + String(b.generado).slice(11, 16) : "")), h("span", { class: "brief-acc" },
          h("button", { type: "button", class: "btn btn-mini btn-ghost", "data-accion": "actualizar", onclick: () => cargar(true) }, "Actualizar"),
          h("button", { type: "button", class: "btn btn-mini btn-ghost", "data-accion": "copiar", disabled: vacio ? true : null, onclick: async () => { copiado = (await copiar(textoBrief(b))) ? "Copiado" : "No se pudo copiar"; pintar(); setTimeout(() => { copiado = ""; pintar(); }, 2000); } }, copiado || "Copiar"))),
        b.aviso ? h("p", { class: "t-meta brief-aviso", title: b.aviso_detalle ? "Detalle técnico: " + b.aviso_detalle : null }, b.aviso) : null,
        lista("Objetivos propuestos", b.objetivos, true), lista("Preguntas para hacer", b.preguntas), lista("Datos que pedir", b.datos),
        !opciones.sinPendientes && (b.pendientes || []).length ? lista("Pendientes abiertos", b.pendientes.slice(0, 4).map((p) => p.texto + (p.responsable ? ` (${p.responsable})` : ""))) : null,
        (b.recordatorios || []).length ? lista("Para retomar", b.recordatorios.slice(0, 3).map((r) => r.texto)) : null,
        vacio && !b.aviso ? h("p", { class: "t-meta soft" }, "Todavía no hay nada que sugerir.") : null]));
    }
    async function cargar(refrescar) {
      estado = "cargando"; pintar();
      try { dat = await api("GET", `/api/proyectos/${encodeURIComponent(nombre)}/brief${refrescar ? "?refrescar=1" : ""}`); dat.objetivos = dat.objetivos || []; dat.preguntas = dat.preguntas || []; dat.datos = dat.datos || []; estado = "ok"; O.briefs.set(nombre, dat); }
      catch (e) { estado = "error"; msg = e.message; }
      raiz._t = Date.now(); pintar();
    }
    raiz.recargar = () => cargar(false); raiz.repintar = pintar; raiz._t = 0;
    cargar(false);
    return raiz;
  }

  // «Preparar»: el bloque aparece al llegar a esa etapa con un proyecto elegido
  function prepararBrief() {
    const det = $("#i-brief"), cuerpo = $("#i-brief-cuerpo"); if (!det) return;
    const prep = document.body.dataset.inicio === "preparar" && document.body.dataset.vista === "inicio";
    const nombre = typeof UI.sel === "string" ? UI.sel : null;
    det.hidden = !(prep && nombre);
    if (det.hidden) return;
    if (cuerpo.dataset.proyecto !== nombre) { cuerpo.dataset.proyecto = nombre; cuerpo.replaceChildren(crearBrief(nombre)); }
    else { const b = cuerpo.firstElementChild; if (b && b.repintar) b.repintar(); }
  }

  // ============================================================ SEGUIMIENTO y MÉTRICAS del proyecto (ficha)
  function crearSeguimiento(nombre) {
    const raiz = h("div", { class: "vp-bloque seg-bloque", id: "pp-seguimiento" });
    let dat = null, estado = "cargando", msg = "";
    const ruta = (x) => `/api/proyectos/${encodeURIComponent(nombre)}/seguimiento${x || ""}`;
    async function accion(p, que, cuerpo) { try { await api("POST", ruta(`/${p.id}/${que}`), cuerpo); } catch (e) { aviso(e); } cargar(); }
    function fila(p) {
      const hecho = p.estado === "hecho";
      const resp = [p.responsable, p.plazo].filter(Boolean).join(" · ");
      return h("li", { class: "seg-f seg-" + p.estado, "data-id": p.id, "data-estado": p.estado },
        h("div", { class: "seg-l1" }, h("span", { class: "seg-t t-body" + (hecho ? " hecho" : "") }, p.texto),
          hecho ? h("button", { type: "button", class: "btn btn-mini btn-ghost", "data-accion": "reabrir", onclick: () => accion(p, "reabrir") }, "Reabrir")
            : h("button", { type: "button", class: "btn btn-mini btn-ghost", "data-accion": "hecho", onclick: () => accion(p, "hecho") }, "Marcar hecho")),
        h("div", { class: "seg-l2 t-meta soft" }, [hecho ? (p.auto ? "Cerrado por la app" : "Hecho") : "Abierto", resp, p.veces > 1 ? `dicho en ${p.veces} sesiones` : null, p.aceptado ? "aceptado en la bandeja" : null, p.tema ? `${p.fecha || ""} · ${p.tema}`.trim() : null].filter(Boolean).join(" · ")),
        hecho && p.cita ? h("blockquote", { class: "seg-cita t-meta" }, h("span", { class: "soft" }, (p.cita.sesion || "otra sesión") + ": "), "«" + p.cita.texto + "»") : null,
        !hecho && p.cierre_propuesto ? h("div", { class: "seg-prop t-meta" }, h("span", {}, "Parece cerrado en " + (p.cierre_propuesto.sesion || "una sesión posterior") + ": «" + p.cierre_propuesto.texto + "»"),
          h("button", { type: "button", class: "btn btn-mini", "data-accion": "aceptar-cierre", onclick: () => accion(p, "hecho", { cita: p.cierre_propuesto }) }, "Marcar hecho")) : null);
    }
    function pintar() {
      const cab = h("div", { class: "vp-sub" }, h("span", { class: "caps" }, "Seguimiento de pendientes"), dat ? h("span", { class: "t-meta soft" }, `${dat.abiertos} abiertos · ${dat.hechos} hechos`) : null);
      if (estado === "cargando") { raiz.replaceChildren(cab, h("p", { class: "t-meta", role: "status" }, "Reuniendo los pendientes de todas las sesiones…")); return; }
      if (estado === "error") { raiz.replaceChildren(cab, h("p", { class: "error t-meta" }, "No se pudo leer el seguimiento: " + msg)); return; }
      const ab = dat.pendientes.filter((p) => p.estado === "abierto"), he = dat.pendientes.filter((p) => p.estado === "hecho");
      raiz.replaceChildren(cab, ...(dat.avisos || []).map((a) => h("p", { class: "t-meta soft" }, a)),
        dat.pendientes.length ? h("ul", { class: "seg-lista" }, ...ab.map(fila), ...he.map(fila)) : h("p", { class: "t-meta soft" }, "Todavía no hay pendientes que seguir."));
    }
    async function cargar() { try { dat = await api("GET", ruta()); estado = "ok"; raiz.dataset.tiene = dat.pendientes && dat.pendientes.length ? "1" : "0"; } catch (e) { estado = "error"; msg = e.message; raiz.dataset.tiene = "0"; } raiz._t = Date.now(); pintar(); if (AP.proyectos && AP.proyectos.repintarPanel) AP.proyectos.repintarPanel(nombre); }
    raiz.recargar = cargar; pintar(); cargar();
    return raiz;
  }
  function crearMetricas(nombre) {
    const raiz = h("div", { class: "vp-bloque met-bloque", id: "pp-metricas" });
    const cab = () => h("div", { class: "vp-sub" }, h("span", { class: "caps" }, "Valor de las reuniones"));
    async function cargar() {
      raiz.replaceChildren(cab(), h("p", { class: "t-meta", role: "status" }, "Calculando…"));
      try {
        const m = await api("GET", `/api/proyectos/${encodeURIComponent(nombre)}/metricas`);
        if (!m.sesiones) { raiz.replaceChildren(cab(), h("p", { class: "t-meta soft" }, "Todavía no hay reuniones medidas de este proyecto.")); return; }
        const o = m.objetivos || {}, a = m.avisos || {}, t = m.tokens || {};
        const tile = (tt, v, d) => h("div", { class: "met-t" }, h("span", { class: "t-label" }, tt), h("span", { class: "met-v" }, v), d ? h("span", { class: "t-meta soft" }, d) : null);
        raiz.replaceChildren(cab(), h("div", { class: "met-grid" },
          tile("Reuniones medidas", String(m.sesiones), Math.round((m.duracion_total_s || 0) / 60) + " min en total"),
          tile("Objetivos cerrados", `${o.cerrados} de ${o.total}`, pct(o.ratio_cerrados) + (o.minutos_medio_hasta_cierre != null ? ` · ${num1(o.minutos_medio_hasta_cierre)} min hasta cerrar` : "")),
          tile("Avisos aceptados", pct(a.tasa_aceptacion), `${a.aceptados} sí · ${a.descartados} no` + (a.marcados_mal ? ` · ${a.marcados_mal} «mal»` : "")),
          tile("Tokens por reunión", k(t.por_sesion), t.por_objetivo_cerrado ? k(t.por_objetivo_cerrado) + " por objetivo cerrado" : "")),
          ...fil([(m.serie || []).length > 1 ? h("div", { class: "met-serie", role: "img", "aria-label": "Objetivos cerrados en cada reunión: " + m.serie.map((s) => `${s.fecha} ${pct(s.ratio_cerrados)}`).join(", ") },
            ...m.serie.map((s) => h("span", { class: "met-barra", title: `${s.fecha} · ${s.tema} · ${pct(s.ratio_cerrados)} cerrados` }, h("i", { style: `height:${Math.round((s.ratio_cerrados || 0) * 100)}%` })))) : null]));
      } catch (e) { raiz.replaceChildren(cab(), h("p", { class: "error t-meta" }, "No se pudieron leer las métricas: " + e.message)); }
    }
    raiz.recargar = cargar; raiz._t = Date.now(); cargar();
    return raiz;
  }
  /** ¿Hay seguimiento con pendientes? Entonces la ficha no repite la lista corta de pendientes de la galería. */
  const haySeguimiento = (nombre) => { const b = O.bloques.get(nombre); return !!(b && b.seg.dataset.tiene === "1"); };
  AP.hooks.fichaBloques = (nombre) => {
    let b = O.bloques.get(nombre);
    const detBrief = (el) => h("div", { class: "vp-bloque brief-ficha", id: "pp-brief" }, h("div", { class: "vp-sub" }, h("span", { class: "caps" }, "Preparación sugerida"), h("span", { class: "t-meta soft" }, "Al pulsar «Añadir» se suma a la reunión que empieces")), el);
    if (!b) { b = { brief: crearBrief(nombre, { sinPendientes: true }), seg: crearSeguimiento(nombre), met: crearMetricas(nombre) }; b.wrap = detBrief(b.brief); O.bloques.set(nombre, b); }
    else if (Date.now() - b.seg._t > 60000) { b.seg.recargar(); b.met.recargar(); b.brief.repintar(); }
    else b.brief.repintar();
    return [b.wrap, b.seg, b.met];
  };

  // ============================================================ PLANTILLAS (Preparar)
  const PESO = { 0: "no habla", 1: "normal", 2: "habla más" };
  async function cargarPlantillas() {
    const campo = $("#i-plantilla-campo"); if (!campo) return;
    if (!O.plantillas) { try { O.plantillas = (await api("GET", "/api/plantillas")).plantillas || []; } catch { O.plantillas = []; } }
    campo.hidden = !O.plantillas.length;
    pintarPlantillas();
  }
  function pintarPlantillas() {
    const cont = $("#i-plantillas"), det = $("#i-plantilla-detalle"); if (!cont) return;
    const opts = [...(O.plantillas || []), { id: "", nombre: "Ninguna" }];
    cont.replaceChildren(...opts.map((p) => h("button", { type: "button", role: "radio", class: "pl-chip", "data-plantilla": p.id, "aria-checked": String(O.plantillaSel === p.id), tabindex: O.plantillaSel === p.id ? "0" : "-1", title: p.descripcion || "Sin plantilla: objetivos y ritmo como siempre",
      onclick: () => { O.plantillaSel = p.id; pintarPlantillas(); },
      onkeydown: (ev) => { const i = opts.indexOf(p), d = ev.key === "ArrowRight" ? 1 : ev.key === "ArrowLeft" ? -1 : 0; if (!d) return; ev.preventDefault(); const n = opts[(i + d + opts.length) % opts.length]; O.plantillaSel = n.id; pintarPlantillas(); const b = $(`#i-plantillas [data-plantilla="${n.id}"]`); if (b) b.focus(); } }, p.nombre)));
    const p = (O.plantillas || []).find((x) => x.id === O.plantillaSel);
    det.hidden = !p;
    if (!p) { det.replaceChildren(); return; }
    const hablan = (v) => Object.entries(p.perfiles || {}).filter(([, x]) => x.peso === v).map(([id]) => AP.nombreAgente(id));
    const mas = hablan(2), no = hablan(0);
    det.replaceChildren(h("ul", { class: "pl-obj" }, ...p.objetivos.map((o) => h("li", { class: "t-meta" }, o))),
      h("p", { class: "t-meta soft" }, "Serán los objetivos si no añades los tuyos." + (p.ritmo && p.ritmo.duracion_min ? ` Unos ${p.ritmo.duracion_min} min.` : "") + (mas.length ? ` Hablan más: ${mas.join(", ")}.` : "") + (no.length ? ` No hablan: ${no.join(", ")}.` : "")));
  }
  AP.hooks.extraIniciar = () => {
    const chk = $("#i-local"), extra = {};
    if (O.plantillaSel) extra.plantilla = O.plantillaSel;
    if (chk) extra.modo_local = !!chk.checked;
    return extra;
  };
  async function prepararLocal() {
    const chk = $("#i-local"); if (!chk) return;
    try { const l = await api("GET", "/api/modo-local"); if (typeof l.config === "boolean") chk.checked = l.config; } catch { /* sin dato: desmarcado */ }
  }
  function alEtapa() {
    const prep = document.body.dataset.inicio === "preparar" && document.body.dataset.vista === "inicio";
    prepararBrief();
    if (prep && !alEtapa.hecho) { alEtapa.hecho = true; cargarPlantillas(); prepararLocal(); }
    if (!prep) alEtapa.hecho = false;
  }
  new MutationObserver(alEtapa).observe(document.body, { attributes: true, attributeFilter: ["data-inicio", "data-vista"] });
  const prevElegir = AP.hooks.alElegirProyecto;
  AP.hooks.alElegirProyecto = (c, p) => { if (prevElegir) prevElegir(c, p); setTimeout(prepararBrief, 0); };

  // ============================================================ CARTERA
  const mayus = (t) => (t ? t[0].toUpperCase() + t.slice(1) : t);
  const plural = (n, uno, varios) => `${n} ${n === 1 ? uno : varios}`;
  /** Microcopy del motivo: mayúscula inicial y, sin ningún objetivo cerrado, una frase que dice algo (un «0 %» no aporta). */
  const motivo = (m, p) => (/de los objetivos$/.test(m) && p.objetivos && !p.objetivos.cerrados ? "Aún no se ha cerrado ningún objetivo" : mayus(m));
  const NIVELES = { critico: ["Crítico", "riesgo", "cart-critico"], atencion: ["Atención", "aviso", "cart-atencion"], bien: ["Bien", "exito", "cart-bien"] };
  const C = { estado: "idle", dat: null, msg: "" };
  async function cargarCartera(refrescar) {
    C.estado = "cargando"; repintarCartera();
    try { C.dat = await api("GET", "/api/cartera" + (refrescar ? "?refrescar=true" : "")); C.estado = "ok"; } catch (e) { C.estado = "error"; C.msg = e.message; }
    repintarCartera();
  }
  function repintarCartera() { const c = $("#cartera"); if (c) c.replaceWith(pintarCartera(true)); }
  function pintarCartera(sinCargar) {
    const raiz = h("section", { class: "cartera", id: "cartera", "aria-label": "Cartera de proyectos" });
    if (C.estado === "idle" && !sinCargar) cargarCartera(false);
    if (C.estado === "idle" || C.estado === "cargando") { raiz.append(h("p", { class: "t-body soft", role: "status" }, "Revisando la salud de cada proyecto…")); return raiz; }
    if (C.estado === "error") { raiz.append(h("p", { class: "error" }, "No se pudo leer la cartera: " + C.msg), h("button", { type: "button", class: "btn btn-mini", onclick: () => cargarCartera(true) }, "Reintentar")); return raiz; }
    const d = C.dat, r = d.resumen || {};
    raiz.append(h("div", { class: "cart-cab" }, h("h2", { class: "t-title" }, "Cartera"),
      h("span", { class: "t-meta soft" }, `${plural(r.proyectos || 0, "proyecto", "proyectos")} · ${plural(r.critico || 0, "crítico", "críticos")} · ${r.atencion || 0} con atención · ${r.bien || 0} bien · últimos ${d.ventana_dias} días`),
      h("button", { type: "button", class: "btn btn-mini btn-ghost cart-act", onclick: () => cargarCartera(true) }, "Actualizar")));
    if (!d.proyectos.length) { raiz.append(h("p", { class: "t-body soft" }, "Todavía no hay sesiones de proyectos que valorar.")); return raiz; }
    raiz.append(h("div", { class: "cart-lista" }, ...d.proyectos.map((p) => {
      const [etq, ico, cls] = NIVELES[p.nivel] || [p.nivel, "info", ""];
      const existe = UI.proyectos && UI.proyectos.some((x) => x.nombre === p.proyecto);
      const s = p.sesiones || {}, pe = p.pendientes || {}, ob = p.objetivos || {};
      return h("article", { class: "cart-fila " + cls, "data-proyecto": p.proyecto, "data-nivel": p.nivel },
        h("div", { class: "cart-l1" }, h("span", { class: "cart-nivel t-label" }, AP.icono(ico, "ic-s"), etq),
          existe ? h("button", { type: "button", class: "btn btn-ghost cart-nom", onclick: (ev) => AP.proyectos.abrirPanel(p.proyecto, ev.currentTarget) }, p.proyecto) : h("span", { class: "t-body-m cart-nom" }, p.proyecto),
          h("span", { class: "t-meta soft" }, s.dias_desde_ultima != null ? `Última sesión hace ${s.dias_desde_ultima} ${s.dias_desde_ultima === 1 ? "día" : "días"}${s.ultima_tema ? " · " + s.ultima_tema : ""}` : "Sin sesiones")),
        p.motivos.length ? h("ul", { class: "cart-motivos" }, ...p.motivos.map((m) => h("li", { class: "t-body" }, motivo(m, p)))) : h("p", { class: "t-meta soft" }, "Nada que atender."),
        h("div", { class: "cart-datos t-meta" },
          h("span", {}, `Pendientes: ${pe.abiertos || 0} abiertos` + (pe.antiguos ? `, ${pe.antiguos} antiguos` : "")),
          h("span", {}, ob.total ? `Objetivos cerrados: ${ob.cerrados} de ${ob.total} (${pct(ob.ratio_cerrados)})` : "Sin objetivos medidos")),
        (pe.mas_antiguos || []).length ? h("ul", { class: "cart-ant t-meta" }, ...pe.mas_antiguos.slice(0, 2).map((x) => h("li", {}, `Hace ${x.dias} días: ${x.texto}`))) : null,
        (p.riesgos_repetidos || []).length ? h("ul", { class: "cart-riesgos t-meta" }, ...p.riesgos_repetidos.slice(0, 2).map((x) => h("li", {}, `Riesgo repetido en ${x.sesiones} sesiones: ${x.texto}`))) : null);
    })));
    return raiz;
  }
  AP.cartera = { pintar: () => pintarCartera(false), recargar: cargarCartera, estado: C };

  // ============================================================ PALABRAS DUDOSAS
  /** Nodos del texto de un segmento: las palabras dudosas (palabras[].d) van subrayadas y son botones (teclado y clic). Sin datos fiables, texto normal. */
  AP.textoSegmento = (s) => {
    const pal = s.palabras;
    if (!Array.isArray(pal) || !pal.length || pal.map((x) => x.w).join(" ") !== s.texto || !pal.some((x) => x.d)) return [s.texto];
    const out = [];
    pal.forEach((x, i) => {
      if (i) out.push(" ");
      out.push(x.d ? h("button", { type: "button", class: "pd", "data-i": String(i), "data-p": x.p, title: "Whisper duda de esta palabra. Pulsa para corregirla o añadirla al glosario", "aria-haspopup": "dialog", "aria-label": `Palabra dudosa: ${x.w}. Corregir o añadir al glosario`,
        onclick: (ev) => abrirCorreccion(s, i, ev.currentTarget) }, x.w) : x.w);
    });
    return out;
  };
  function cerrarCorreccion(devolver = true) {
    const c = O.segCorr; if (!c) return;
    O.segCorr = null; c.caja.remove(); document.removeEventListener("keydown", c.tecla, true); document.removeEventListener("mousedown", c.fuera, true);
    if (devolver && c.ancla && c.ancla.isConnected) c.ancla.focus();
  }
  function abrirCorreccion(s, i, ancla) {
    cerrarCorreccion(false);
    const w = s.palabras[i].w, limpia = w.replace(/^[^\p{L}\p{N}]+|[^\p{L}\p{N}]+$/gu, "");
    const campo = h("input", { class: "input", id: "corr-texto", type: "text", value: limpia, maxlength: "60", "aria-label": "Cómo debería poner", autocomplete: "off" });
    const gl = h("input", { type: "checkbox", id: "corr-gl" });
    const ambito = h("select", { class: "input", id: "corr-ambito", "aria-label": "Dónde guardar el término" }, h("option", { value: "proyecto" }, "Solo en este proyecto"), h("option", { value: "global" }, "En todos los proyectos"));
    if (!(S.sesion && S.sesion.proyecto)) { ambito.value = "global"; ambito.querySelector('[value="proyecto"]').disabled = true; }
    const estado = h("p", { class: "t-meta", id: "corr-estado", role: "status" });
    const nuevoTexto = () => s.palabras.map((x, j) => (j === i ? w.replace(limpia, campo.value.trim() || limpia) : x.w)).join(" ");
    const caja = h("div", { class: "corr", id: "corr", role: "dialog", "aria-modal": "false", "aria-labelledby": "corr-t" },
      h("div", { class: "corr-cab" }, h("span", { class: "t-body-m", id: "corr-t" }, `«${limpia}»`, h("span", { class: "t-meta soft" }, ` · ${s.mmss} · seguridad ${Math.round((s.palabras[i].p || 0) * 100)} %`)),
        h("button", { type: "button", class: "btn btn-ghost btn-mini", "aria-label": "Cerrar", onclick: () => cerrarCorreccion() }, AP.icono("cerrar"))),
      h("label", { class: "corr-f" }, h("span", { class: "t-label" }, "Poner"), campo),
      h("label", { class: "check corr-c" }, gl, h("span", {}, "Añadir al glosario"), ambito),
      h("div", { class: "corr-b" },
        h("button", { type: "button", class: "btn btn-primary btn-mini", id: "corr-ok", onclick: async (ev) => {
          ev.currentTarget.disabled = true;
          try {
            const r = await api("POST", `/api/sesion/segmento/${s.id}/corregir`, { texto: nuevoTexto(), glosario: gl.checked ? ambito.value : null, termino: gl.checked ? campo.value.trim() : null });
            const n = r.propagado ? Object.values(r.propagado).reduce((a, b) => a + b, 0) : 0;
            estado.textContent = `Corregido en este segmento${n ? ` y en ${n} ${n === 1 ? "sitio derivado" : "sitios derivados"}` : ""}.` + (r.glosario && r.glosario.length ? " Añadido al glosario." : "") + " Lo que ya se envió al modelo no cambia.";
            setTimeout(() => cerrarCorreccion(false), 2200);
          } catch (e) { estado.textContent = e.message; ev.currentTarget.disabled = false; }
        } }, "Corregir"),
        h("button", { type: "button", class: "btn btn-ghost btn-mini", id: "corr-glosario", onclick: async (ev) => {
          ev.currentTarget.disabled = true;
          try { const r = await api("POST", "/api/glosario", { termino: campo.value.trim() || limpia, proyecto: ambito.value === "proyecto" && S.sesion ? S.sesion.proyecto : null }); estado.textContent = r.nuevo ? "Añadido al glosario: se tendrá en cuenta desde ahora." : "Ya estaba en el glosario."; }
          catch (e) { estado.textContent = e.message; } ev.currentTarget.disabled = false;
        } }, "Añadir al glosario")),
      estado);
    const tecla = (ev) => { if (ev.key === "Escape") { ev.preventDefault(); ev.stopPropagation(); cerrarCorreccion(); } };
    const fuera = (ev) => { if (!caja.contains(ev.target) && !(ev.target.closest && ev.target.closest(".pd"))) cerrarCorreccion(false); };
    document.addEventListener("keydown", tecla, true); document.addEventListener("mousedown", fuera, true);
    document.body.append(caja);
    const r = ancla.getBoundingClientRect(), w2 = 320;
    caja.style.left = Math.max(8, Math.min(innerWidth - w2 - 8, r.left)) + "px";
    caja.style.top = Math.min(innerHeight - caja.offsetHeight - 8, r.bottom + 6) + "px";
    O.segCorr = { caja, ancla, tecla, fuera };
    campo.focus(); campo.select();
  }
  function repintarLinea(seg) {
    const el = $(`#r-trans [data-id="${seg.id}"] .x`); if (el) el.replaceChildren(...AP.textoSegmento(seg));
  }

  // ============================================================ «ESTO ESTÁ MAL»
  /** Botón para tarjetas de agente y avisos del Monitor. `id` = id del aviso; sin él no se puede silenciar. */
  AP.malBoton = (id, yaMal) => {
    if (!id) return null;
    const regla = O.mal.get(id);
    if (regla || yaMal) return h("span", { class: "mal-hecho t-meta" }, h("span", {}, "Silenciado: no se repetirá un aviso así."),
      regla ? h("button", { type: "button", class: "btn btn-mini btn-ghost", "data-accion": "deshacer-mal", onclick: async () => { try { await api("DELETE", "/api/reglas-silencio/" + regla.id); O.mal.delete(id); refrescarAvisos(); } catch (e) { aviso(e); } } }, AP.icono("deshacer", "ic-s"), "Deshacer") : null);
    return h("button", { type: "button", class: "btn btn-mini btn-ghost mal-b", "data-accion": "mal", title: "El aviso está equivocado o no sirve: el equipo no repetirá uno equivalente", onclick: async (ev) => {
      ev.currentTarget.disabled = true;
      try { const r = await api("POST", `/api/avisos/${encodeURIComponent(id)}/mal`, {}); O.mal.set(id, r.regla); refrescarAvisos(); } catch (e) { aviso(e); ev.currentTarget.disabled = false; }
    } }, "Esto está mal");
  };
  function refrescarAvisos() { if (AP.hooks.pintarInsights) AP.hooks.pintarInsights(); if (AP.equipo && AP.equipo.render) AP.equipo.render(); }

  // ============================================================ eventos
  let pend = false;
  const previo = AP.hooks.evento;
  AP.hooks.evento = (d) => {
    if (previo) previo(d);
    switch (d.tipo) {
      case "snapshot":
        O.acciones.splice(0, O.acciones.length, ...(d.acciones || [])); O.local = d.modo_local || null; O.plantilla = d.plantilla || null; O.mal.clear(); O.envios = [];
        setTimeout(cargarEnviosSesion, 0); break;
      case "acciones": O.acciones.splice(0, O.acciones.length, ...(d.acciones || [])); if (d.autonomia) O.autonomia = d.autonomia; break;
      case "estado": if ("modo_local" in d) O.local = d.modo_local; if ("plantilla" in d) O.plantilla = d.plantilla; break;
      case "envio": O.envios.push(d); pintarEnviosSesion(); break;
      case "segmento_corregido": { const seg = S.segmentos.find((x) => x.id === d.segmento.id); if (seg) { Object.assign(seg, d.segmento); delete seg.palabras; delete seg.dudosas; requestAnimationFrame(() => repintarLinea(seg)); } break; }
      case "segmento_eco": (d.cambios || []).forEach((c) => { const seg = S.segmentos.find((x) => x.id === c.id); if (seg && seg.palabras) { delete seg.palabras; delete seg.dudosas; } }); break;
      case "aviso_silenciado": if (d.regla) O.mal.set(d.id, d.regla); requestAnimationFrame(refrescarAvisos); break;
      case "regla_silencio_borrada": for (const [id, g] of O.mal) if (g.id === d.id) O.mal.delete(id); requestAnimationFrame(() => { refrescarAvisos(); cargarSilenciados(); }); break;
    }
    if (pend) return;
    pend = true;
    requestAnimationFrame(() => { pend = false; pintarReunion(); pintarLocal(); const sec = $("#rev-acciones"); if (sec && !sec.matches(":focus-within")) { const n = seccionAcciones(); sec.replaceWith(n); } });
  };
  const previoRei = AP.hooks.reiniciar;
  AP.hooks.reiniciar = () => { if (previoRei) previoRei(); O.acciones.splice(0); O.mal.clear(); O.envios = []; O.local = null; pintarReunion(); pintarEnviosSesion(); pintarLocal(); };

  // Ajustes: autonomía, silenciados y privacidad al abrir; la autonomía se guarda con «Guardar»
  const previoAbrir = AP.hooks.ajustesAbrir;
  AP.hooks.ajustesAbrir = (info, f) => { if (previoAbrir) previoAbrir(info, f); cargarAutonomia(); cargarSilenciados(); cargarPrivacidad(); };
  const formAj = $("#f-ajustes");
  if (formAj) formAj.addEventListener("submit", () => { guardarAutonomia(); });

  AP.olas34 = { haySeguimiento, seccionAcciones, seccionMetricas, bannerLocal, lanzarAgentes, estado: O, abrirCorreccion, cerrarCorreccion, pintarReunion, cargarPlantillas };
  const iniciar = () => { pintarReunion(); pintarLocal(); pintarEnviosSesion(); };
  if (document.readyState !== "loading") iniciar(); else document.addEventListener("DOMContentLoaded", iniciar);
})();
