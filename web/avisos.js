"use strict";
/* WhisperMeet: las tres zonas de la reunión (Transcripción | Ahora | Objetivos) y los Avisos unificados.
   - «Ahora»: la respuesta grande del asesor (asesor.js), el SIGUIENTE PASO propuesto (el consejo más reciente del Sherpa; sin consejos, lo primero que falta por tratar)
     y un contenedor reservado para la bandeja de acciones (#ahora-acciones; `AP.avisos.pintarAcciones` lo rellena cuando llegue esa fase).
   - Avisos = Consejos + Insights en UNA lista, con chips de filtro por agente. Los insights los pinta reunion.js (`AP.hooks.pintarInsights`) y mete aquí los consejos
     del Sherpa por `extras()`. Tres prioridades (reunion.js, `AP.prioridad`): fijo (arriba hasta cerrarlo), normal (en la lista) y discreto (se aparta solo a «ya vistos»).
   - Objetivos: zona fija con barra de progreso y lo que falta.
   Todo sale de datos reales del backend; el texto dinámico entra siempre por textContent. */
(() => {
  const AP = window.AP;
  if (!AP) return;
  const { S, h, $, $$, api } = AP;
  const ESTADO_ACTIVO = () => !!(S.sesion && S.estado !== "inactivo");
  const F = { agente: "", sigChips: "", cache: new Map(), sigPaso: "" };
  const aSeg = (m) => { const p = String(m || "").split(":").map(Number); return p.length === 2 && p.every((x) => !Number.isNaN(x)) ? p[0] * 60 + p[1] : null; };
  const numId = (x) => Number(String(x.id).slice(1)) || 0;
  const A = () => (AP.asesor && AP.asesor.estado ? AP.asesor.estado() : null);
  const consejos = () => { const a = A(); return ESTADO_ACTIVO() && a ? (a.consejos || []).filter((c) => !c.descartado) : []; };
  const repintarLista = () => { if (AP.hooks.pintarInsights) AP.hooks.pintarInsights(); };

  // ------------------------------------------------------------ consejos dentro de la lista de avisos
  function elConsejo(c) {
    const sig = JSON.stringify([c.accion, c.porque, c.etiqueta, c.fijado, c.profundizada && c.profundizada.estado, c.modelo, c.minuto]);
    const previo = F.cache.get(c.id);
    if (previo && previo.sig === sig) return previo.el;
    const el = AP.asesor.tarjetaConsejo(c);
    el.dataset.ag = "estratega"; el.dataset.prio = "normal"; el.classList.add("av-consejo", "prio-normal");
    F.cache.set(c.id, { sig, el });
    return el;
  }
  function extras() {
    if (!AP.asesor || !AP.asesor.tarjetaConsejo) return [];
    const lista = consejos();
    const vivos = new Set(lista.map((c) => c.id));
    for (const k of [...F.cache.keys()]) if (!vivos.has(k)) F.cache.delete(k);
    return [...lista].sort((a, b) => numId(b) - numId(a)).map((c) => ({ t: c.t_seg == null ? aSeg(c.minuto) || 0 : c.t_seg, el: elConsejo(c) }));   // a igual minuto, el más reciente (id mayor) primero
  }

  // ------------------------------------------------------------ filtro por agente
  function conteos() {
    const n = Object.create(null);   // sin prototipo: «constructor» es un agente (Arquitecto) y no puede chocar con Object.prototype.constructor
    for (const t of S.tarjetas || []) { const k = t.perfil || "analista"; n[k] = (n[k] || 0) + 1; }
    const c = consejos().length;
    if (c) n.estratega = (n.estratega || 0) + c;
    return n;
  }
  function pintarFiltros() {
    const cont = $("#av-filtros");
    if (!cont) return;
    const n = conteos();
    const orden = [...AP.AGENTES_ORDEN, "analista"].filter((k) => n[k] || F.agente === k);
    const total = Object.values(n).reduce((a, b) => a + b, 0);
    const sig = JSON.stringify([F.agente, total, orden.map((k) => [k, n[k] || 0])]);
    cont.hidden = orden.length < 2 && !F.agente;
    if (sig === F.sigChips) return;
    F.sigChips = sig;
    const chips = [h("button", { type: "button", class: "av-chip av-chip-todos", "data-f": "", "aria-pressed": String(!F.agente), onclick: () => elegir("") }, "Todos", h("span", { class: "av-n" }, String(total)))];
    for (const k of orden) {
      const a = AP.agente(k);
      chips.push(h("button", { type: "button", class: "av-chip ag ag-" + a.id, "data-f": k, "aria-pressed": String(F.agente === k), title: `${a.nombre}: ${a.rol}`, onclick: () => elegir(F.agente === k ? "" : k) },
        AP.icono(a.icono, "ag-ic"), h("span", { class: "ag-n" }, a.nombre), h("span", { class: "av-n" }, String(n[k] || 0))));
    }
    const foco = document.activeElement && cont.contains(document.activeElement) ? document.activeElement.dataset.f : null;
    cont.replaceChildren(...chips);
    if (foco != null) { const b = cont.querySelector(`[data-f="${CSS.escape(foco)}"]`); if (b) b.focus({ preventScroll: true }); }
  }
  function elegir(k) { F.agente = k; F.sigChips = ""; pintarFiltros(); repintarLista(); }

  // ------------------------------------------------------------ «Ahora»: siguiente paso propuesto
  function pasoDeConsejo(c) {
    const a = AP.agente("estratega");
    return h("div", { class: "paso-c", "data-id": c.id },
      h("div", { class: "paso-cab" }, AP.icono("rayo", "ic-paso"), h("span", { class: "t-label paso-et" }, "Siguiente paso"), AP.chipAgente("estratega"),
        c.minuto ? h("button", { type: "button", class: "min", "data-t": c.t_seg == null ? aSeg(c.minuto) : c.t_seg, title: "Ir a ese momento de la transcripción", onclick: () => AP.hooks.irAlMinuto && AP.hooks.irAlMinuto(c.t_seg == null ? aSeg(c.minuto) : c.t_seg) }, c.minuto) : null,
        h("button", { type: "button", class: "btn btn-mini btn-ghost paso-descartar", "data-accion": "descartar-paso", title: `Descartar: ${a.nombre} no vuelve a proponerlo`,
          onclick: () => api("POST", `/api/asesor/${c.id}/descartar`, { valor: true }).catch(AP.alerta) }, "Descartar")),
      h("p", { class: "paso-accion" }, c.accion),
      c.porque ? h("p", { class: "paso-porque" }, h("span", { class: "paso-porque-t" }, "Por qué: "), c.porque) : null);
  }
  function pasoDeObjetivo(o, faltan) {
    return h("div", { class: "paso-c paso-obj" },
      h("div", { class: "paso-cab" }, AP.icono("objetivo", "ic-paso"), h("span", { class: "t-label paso-et" }, "Falta por tratar")),
      h("p", { class: "paso-accion" }, o.texto),
      faltan > 1 ? h("p", { class: "paso-porque" }, `Y ${faltan - 1} objetivo${faltan === 2 ? "" : "s"} más.`) : null);
  }
  function pintarPaso() {
    const caja = $("#ahora-paso");
    if (!caja) return;
    const activa = ESTADO_ACTIVO() && (S.estado === "grabando" || S.estado === "pausada");
    const est = $("#ahora-estado"); if (est) est.textContent = S.estado === "pausada" ? "En pausa" : "";
    caja.hidden = !activa;
    if (!activa) { caja.replaceChildren(); F.sigPaso = ""; return; }
    const cons = consejos();
    const fijado = cons.find((c) => c.fijado), elegido = fijado || [...cons].sort((a, b) => numId(b) - numId(a))[0];
    const falta = (S.objetivos || []).filter((o) => !o.sugerido && o.estado !== "cubierto");
    const sig = elegido ? JSON.stringify(["c", elegido.id, elegido.accion, elegido.porque]) : falta.length ? JSON.stringify(["o", falta[0].texto, falta.length]) : "vacio";
    if (sig === F.sigPaso) return;
    F.sigPaso = sig;
    caja.classList.toggle("vacio", sig === "vacio");
    caja.replaceChildren(elegido ? pasoDeConsejo(elegido) : falta.length ? pasoDeObjetivo(falta[0], falta.length)
      : h("p", { class: "paso-vacio t-meta" }, "Todo en calma. Aquí verás el siguiente paso que proponga el Sherpa y la respuesta sugerida cuando el cliente pregunte algo."));
  }
  AP.avisos = { extras, filtro: () => F.agente, pintarFiltros, pintarPaso, elegir, consejosCambian: () => { pintarPaso(); pintarFiltros(); repintarLista(); } };

  // ------------------------------------------------------------ bandeja de acciones propuestas (se rellena en otra fase)
  /** Pinta la lista de acciones propuestas. `lista` = [{id, texto, detalle?, agente?}]. Aceptar, Editar y Descartar no hacen nada por su cuenta: avisan con el evento
   *  `accion` del contenedor (detail = {id, accion}) para que la fase que las conecte decida. Sin acciones, el contenedor queda oculto. */
  AP.avisos.pintarAcciones = (lista) => {
    const caja = $("#ahora-acciones");
    if (!caja) return;
    const l = (lista || []).filter((x) => x && x.texto);
    caja.hidden = !l.length;
    const dispara = (id, accion) => caja.dispatchEvent(new CustomEvent("accion", { detail: { id, accion }, bubbles: true }));
    caja.replaceChildren(...(l.length ? [h("div", { class: "acc-cab" }, h("span", { class: "t-label" }, "Acciones propuestas"), h("span", { class: "n t-meta" }, String(l.length))),
      h("ul", { class: "acc-lista" }, ...l.map((x) => h("li", { class: "acc-item", "data-id": x.id },
        h("div", { class: "acc-tx" }, x.agente ? AP.chipAgente(x.agente, { solo: true }) : null, h("span", { class: "acc-t t-body-m" }, x.texto), x.detalle ? h("span", { class: "acc-d t-meta" }, x.detalle) : null),
        h("div", { class: "acc-bt" },
          h("button", { type: "button", class: "btn btn-mini", "data-accion": "aceptar", onclick: () => dispara(x.id, "aceptar") }, "Aceptar"),
          h("button", { type: "button", class: "btn btn-mini btn-ghost", "data-accion": "editar", onclick: () => dispara(x.id, "editar") }, "Editar"),
          h("button", { type: "button", class: "btn btn-mini btn-ghost", "data-accion": "descartar", onclick: () => dispara(x.id, "descartar") }, "Descartar")))))] : []));
  };

  // ------------------------------------------------------------ zona fija de Objetivos: progreso y lo que falta
  function decorarObjetivos() {
    const os = (S.objetivos || []).filter((o) => !o.sugerido);
    const todos = S.objetivos || [];
    const barra = $("#r-obj-barra i"), falta = $("#r-obj-falta"), vacio = $("#r-obj-vacio");
    const cub = os.filter((o) => o.estado === "cubierto").length;
    if (barra) barra.style.width = os.length ? Math.round((cub / os.length) * 100) + "%" : "0%";
    const pen = os.filter((o) => o.estado !== "cubierto");
    if (falta) { const t = os.length ? (pen.length ? "Falta: " + pen.map((o) => o.texto).join(" · ") : "Todos los objetivos están cubiertos.") : ""; if (falta.textContent !== t) falta.textContent = t; falta.hidden = !t; }
    if (vacio) vacio.hidden = !!todos.length || !(S.sesion && (S.estado === "grabando" || S.estado === "pausada"));
    const ob = $("#r-objetivos"); if (ob && !todos.length && (S.estado === "grabando" || S.estado === "pausada")) ob.hidden = false;   // el cuadro de «añadir un objetivo» vive dentro
    const cuenta = $("#r-obj-cuenta"); if (cuenta) cuenta.textContent = os.length ? `${cub}/${os.length}` : "";
  }
  const previoObj = AP.hooks.pintarObjetivos;
  AP.hooks.pintarObjetivos = () => { if (previoObj) previoObj(); decorarObjetivos(); };

  // ------------------------------------------------------------ eventos
  let pendiente = false;
  const previo = AP.hooks.evento;
  AP.hooks.evento = (d) => {
    if (previo) previo(d);
    if (pendiente) return;
    pendiente = true;
    requestAnimationFrame(() => { pendiente = false; pintarPaso(); pintarFiltros(); decorarObjetivos(); });
  };
  const reiniciar = AP.hooks.reiniciar;
  AP.hooks.reiniciar = () => { if (reiniciar) reiniciar(); F.agente = ""; F.sigChips = ""; F.sigPaso = ""; F.cache.clear(); pintarFiltros(); pintarPaso(); if ($("#ahora-acciones")) AP.avisos.pintarAcciones([]); };
  const iniciar = () => { pintarPaso(); pintarFiltros(); decorarObjetivos(); };
  if (document.readyState !== "loading") iniciar(); else document.addEventListener("DOMContentLoaded", iniciar);
})();
