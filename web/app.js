"use strict";
/* Apuntes: interfaz sin paso de build. Todo el texto dinámico entra con textContent (nada de innerHTML). */
(() => {
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => [...r.querySelectorAll(s)];
  const h = (tag, attrs = {}, ...hijos) => {
    const e = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v === false || v == null) continue;
      if (k === "class") e.className = v;
      else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
      else e.setAttribute(k, v === true ? "" : v);
    }
    for (const c of hijos.flat()) if (c != null && c !== false) e.append(c.nodeType ? c : document.createTextNode(String(c)));
    return e;
  };
  const safe = (fn, def) => { try { return fn(); } catch { return def; } };

  // ------------------------------------------------------------ token y API
  const params = new URLSearchParams(location.search);
  let TOKEN = params.get("t") || safe(() => sessionStorage.getItem("apuntes_t"), "") || "";
  if (params.get("t")) { safe(() => sessionStorage.setItem("apuntes_t", TOKEN)); history.replaceState(null, "", location.pathname); }

  async function api(metodo, ruta, cuerpo) {
    const r = await fetch(ruta, { method: metodo, headers: { "X-Token": TOKEN, ...(cuerpo !== undefined ? { "Content-Type": "application/json" } : {}) },
      body: cuerpo !== undefined ? JSON.stringify(cuerpo) : undefined });
    let datos = null;
    try { datos = await r.json(); } catch { /* sin cuerpo */ }
    if (!r.ok) { const e = new Error((datos && (datos.detail || datos.error)) || `Error ${r.status}`); e.status = r.status; throw e; }
    return datos;
  }

  // ------------------------------------------------------------ estado
  const S = { estado: "inactivo", sesion: null, segmentos: [], tarjetas: [], notas: "", resumen_acumulado: "", analisis: {}, consumo: null,
    transcripcion: null, digest: {}, avisos: [], revision: null, simulacion: false, t: 0, objetivos: [], checks: [] };
  const AP = (window.AP = { hooks: {} });   // puente con agentes.js, reunion.js y revision.js (rediseño agéntico)
  const UI = { proyectos: [], sel: undefined, proy: null, sesionPlan: undefined, temaAuto: "", cad: 5, decisiones: {}, info: null, ultimoSeg: 0, seguir: true };

  // Movimiento reducido: las animaciones hechas con la Web Animations API (avisos que vuelan, trazos…) duran 0 ms; el CSS ya las desactiva por su lado.
  const mqReducido = matchMedia("(prefers-reduced-motion: reduce)");
  if (typeof Element.prototype.animate === "function") {
    const animar = Element.prototype.animate;
    Element.prototype.animate = function (claves, op) {
      if (!mqReducido.matches) return animar.call(this, claves, op);
      return animar.call(this, claves, { ...(typeof op === "number" ? { duration: op } : op || {}), duration: 0, delay: 0, endDelay: 0, iterations: 1 });
    };
  }

  // ------------------------------------------------------------ diálogo propio (sustituye a confirm / alert / prompt del navegador)
  // AP.confirmar({titulo, texto, aceptar, cancelar, peligro}) -> Promise<boolean>; AP.avisar({titulo, texto}) -> Promise<void> (un solo botón);
  // AP.pedirTexto({titulo, texto, valor, aceptar}) -> Promise<string|null>. Esc cancela, Intro acepta, el foco queda atrapado dentro y vuelve
  // al disparador al cerrar; el resto de la app queda `inert` mientras está abierto.
  let nDialogo = 0;
  function dialogoPropio(op) {
    return new Promise((resolve) => {
      const previo = document.activeElement;
      const id = "dp-" + (++nDialogo);
      const campo = op.campo ? h("input", { class: "input dp-campo", type: "text", value: op.valor || "", maxlength: "200", "aria-label": op.titulo || "Texto" }) : null;
      const bOk = h("button", { type: "button", class: "btn " + (op.peligro ? "btn-peligro" : "btn-primary"), "data-dp": "aceptar" }, op.aceptar || "Aceptar");
      const bNo = op.sinCancelar ? null : h("button", { type: "button", class: "btn btn-ghost", "data-dp": "cancelar" }, op.cancelar || "Cancelar");
      const caja = h("div", { class: "dp-caja" + (op.peligro ? " peligro" : ""), role: "alertdialog", "aria-modal": "true", "aria-labelledby": id + "-t", "aria-describedby": id + "-d" },
        h("h2", { class: "t-title dp-titulo", id: id + "-t" }, op.titulo || ""),
        h("p", { class: "t-body dp-texto", id: id + "-d" }, op.texto || ""), campo,
        h("div", { class: "dp-pie" }, ...[bNo, bOk].filter(Boolean)));
      const fondo = h("div", { class: "dp-fondo", "data-dp-fondo": "" }, caja);
      const bloqueados = [...document.body.children].filter((e) => e.tagName !== "SCRIPT").map((e) => [e, e.inert]);
      bloqueados.forEach(([e]) => { e.inert = true; });
      document.body.append(fondo);
      let cerrado = false;
      const cerrar = (valor) => {
        if (cerrado) return;
        cerrado = true;
        document.removeEventListener("keydown", tecla, true);
        fondo.remove();
        bloqueados.forEach(([e, v]) => { e.inert = v; });
        if (previo && previo.isConnected && typeof previo.focus === "function") previo.focus();
        resolve(valor);
      };
      const aceptar = () => cerrar(campo ? campo.value : true);
      const cancelar = () => cerrar(campo ? null : false);
      const tecla = (ev) => {
        if (ev.key === "Escape") { ev.preventDefault(); ev.stopPropagation(); if (bNo) cancelar(); else aceptar(); return; }
        if (ev.key === "Enter" && !ev.isComposing) {
          if (ev.target === bNo) return;          // Intro sobre «Cancelar» pulsa Cancelar (comportamiento nativo del botón)
          ev.preventDefault(); ev.stopPropagation(); aceptar(); return;
        }
        if (ev.key === "Tab") {
          const f = [...caja.querySelectorAll("button, input")].filter((e) => !e.disabled);
          const i = f.indexOf(document.activeElement);
          ev.preventDefault();
          f[(i + (ev.shiftKey ? -1 : 1) + f.length) % f.length].focus();
        }
      };
      document.addEventListener("keydown", tecla, true);
      bOk.addEventListener("click", aceptar);
      if (bNo) bNo.addEventListener("click", cancelar);
      fondo.addEventListener("mousedown", (ev) => { if (ev.target === fondo && bNo) cancelar(); });
      (campo || bOk).focus();
      if (campo) campo.select();
    });
  }
  AP.confirmar = (op) => dialogoPropio(op || {});
  AP.avisar = (op) => dialogoPropio({ aceptar: "Entendido", sinCancelar: true, ...(typeof op === "string" ? { titulo: "Aviso", texto: op } : op) });
  AP.pedirTexto = (op) => dialogoPropio({ campo: true, ...op });
  const avisarError = (e) => AP.avisar({ titulo: "No se pudo completar", texto: (e && e.message) || String(e) });
  AP.avisarError = avisarError;

  // ------------------------------------------------------------ tema
  function aplicarTema(t) {
    if (t === "claro" || t === "oscuro") document.documentElement.dataset.theme = t === "claro" ? "light" : "dark";
    else delete document.documentElement.dataset.theme;
    $("#b-tema").textContent = t === "claro" ? "Modo claro" : t === "oscuro" ? "Modo oscuro" : "Modo auto";
  }
  let tema = safe(() => localStorage.getItem("apuntes_tema"), "auto") || "auto";
  aplicarTema(tema);
  $("#b-tema").addEventListener("click", () => {
    tema = { auto: "claro", claro: "oscuro", oscuro: "auto" }[tema] || "auto";
    safe(() => localStorage.setItem("apuntes_tema", tema));
    aplicarTema(tema);
  });

  // ------------------------------------------------------------ utilidades
  const mmss = (s) => { s = Math.max(0, Math.floor(s || 0)); const m = Math.floor(s / 60); return `${String(m).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`; };
  const kfmt = (n) => (n >= 1000 ? (n / 1000).toFixed(1).replace(".", ",") + "k" : String(n));
  const sinAcentos = (s) => s.normalize("NFD").replace(/[̀-ͯ]/g, "");

  // Markdown mínimo y seguro: títulos, listas, negrita y párrafos.
  function md(texto) {
    const raiz = h("div", { class: "md" });
    let lista = null;
    const inline = (t) => {
      const frag = document.createDocumentFragment();
      t.split(/(\*\*[^*]+\*\*)/).forEach((p) => {
        if (/^\*\*[^*]+\*\*$/.test(p)) frag.append(h("b", {}, p.slice(2, -2))); else if (p) frag.append(p);
      });
      return frag;
    };
    for (const linea of String(texto || "").split("\n")) {
      const t = linea.trim();
      let m;
      if (!t) { lista = null; continue; }
      if ((m = t.match(/^(#{1,4})\s+(.*)/))) { lista = null; raiz.append(h(m[1].length <= 2 ? "h3" : "h4", {}, inline(m[2]))); }
      else if ((m = t.match(/^([-*]|\d+[.)])\s+(.*)/))) { if (!lista) { lista = h("ul"); raiz.append(lista); } lista.append(h("li", {}, inline(m[2]))); }
      else { lista = null; raiz.append(h("p", {}, inline(t))); }
    }
    return raiz;
  }

  // ------------------------------------------------------------ vistas
  function vista() {
    const e = S.estado;
    const v = e === "inactivo" ? "inicio" : e === "revision" ? "revision" : "reunion";
    const aplicar = () => {
      $$(".vista").forEach((s) => (s.hidden = s.id !== "v-" + v));
      document.body.dataset.vista = v;
      $("#r-cab").hidden = v !== "reunion";
      $("#orq").hidden = v === "inicio";
      $("#b-sim").hidden = !S.simulacion;
    };
    // Cambio de pantalla con View Transitions (DESIGN-visual.md §7): cross-fade de 260 ms con la cabecera fija; sin la API (o con movimiento reducido), como siempre
    const cambia = vistaAntes !== null && vistaAntes !== v && typeof document.startViewTransition === "function" && !matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (cambia) { try { document.startViewTransition(aplicar); } catch { aplicar(); } } else aplicar();
    return v;
  }

  // ------------------------------------------------------------ CONTEXTO: ficha, Gantt, hitos, sesiones y checks (sin LLM)
  const MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"];
  const fmtDia = (iso) => { const [, m, d] = iso.split("-").map(Number); return `${d} ${MESES[m - 1]}`; };
  const ESTADO_SES = { celebrada: "Celebrada", hoy: "Hoy", proxima: "Próxima", propuesta: "Propuesta", por_definir: "Por definir", por_confirmar: "Por confirmar" };
  const chipEstado = (e) => h("span", { class: "est " + e }, ESTADO_SES[e] || e);
  const textoFecha = (x) => (x.fecha_iso ? fmtDia(x.fecha_iso) + (x.fecha_estado === "propuesta" ? " (propuesta)" : "")
    : (x.semana ? x.semana + " · " : "") + (x.fecha_estado === "por_confirmar" ? "por confirmar" : "por definir"));

  function gantt(plan, selId) {
    const g = plan.gantt, n = g.semanas.length, DIA = 86400000;
    const t0 = Date.parse(g.semanas[0].inicio + "T00:00:00Z");
    const pct = (iso) => ((Date.parse(iso + "T12:00:00Z") - t0) / DIA) / (n * 7) * 100;
    const idx = (sid) => g.semanas.findIndex((s) => s.id === sid);
    const centro = (sid) => ((idx(sid) + 0.5) / n) * 100;
    const pos = (x) => (x.fecha_iso ? pct(x.fecha_iso) : x.semana ? centro(x.semana) : null);
    const fila = (cls, et, pista) => h("div", { class: "g-fila " + cls }, et, pista);
    const etiqueta = (b, s, titulo) => h("div", { class: "g-et", title: titulo || null }, h("b", {}, b), s ? h("span", {}, s) : null);
    const raiz = h("div", { class: "gantt", style: `--n:${n}`, role: "group", "aria-label": "Calendario del proyecto por semanas" });
    raiz.append(fila("g-cab", h("div", { class: "g-et" }),
      h("div", { class: "g-pista" }, g.semanas.map((s) => h("div", { class: "g-s" }, h("b", {}, s.id), h("span", {}, fmtDia(s.inicio)))))));
    g.fases.forEach((f, k) => {
      const i0 = idx(f.desde), i1 = idx(f.hasta);
      raiz.append(fila("g-fase", etiqueta(f.nombre, f.etiqueta, f.nota),
        h("div", { class: "g-pista" }, h("div", { class: "g-barra fase-" + (f.id || "x"), style: `left:${(i0 / n) * 100}%;width:${((i1 - i0 + 1) / n) * 100}%;animation-delay:${k * 35}ms`,
          title: `${f.nombre} · ${f.desde} a ${f.hasta}${f.nota ? ". " + f.nota : ""}` }, h("span", { class: "g-bt" }, f.nombre)))));
    });
    const conFecha = g.sesiones.filter((s) => pos(s) != null), sinFecha = g.sesiones.filter((s) => pos(s) == null);
    raiz.append(fila("g-ses", etiqueta("Sesiones", "TR"), h("div", { class: "g-pista" }, conFecha.map((s) => h("div", {
      class: `g-m ses ${s.estado}${s.id === selId ? " sel" : ""}`, style: `left:${pos(s)}%`,
      title: `${s.id} · ${s.nombre} · ${s.fecha_texto}${s.estado === "celebrada" ? " (celebrada)" : ""}` }, h("i"), h("span", {}, s.id))))));
    if (sinFecha.length) {
      const v = g.ventana_sesiones, i0 = v ? idx(v.desde) : 0, i1 = v ? idx(v.hasta) : n - 1;
      raiz.append(fila("g-sin", etiqueta("Sin fecha", "por definir"), h("div", { class: "g-pista" },
        h("div", { class: "g-ventana", style: `left:${(i0 / n) * 100}%;width:${((i1 - i0 + 1) / n) * 100}%`, title: "Sesiones sin fecha: se sabe en qué tramo caen, no el día" },
          sinFecha.map((s) => h("span", { class: "g-chip" + (s.id === selId ? " sel" : ""), title: `${s.id} · ${s.nombre}` },
            h("b", {}, s.id), h("span", {}, s.fecha_estado === "por_confirmar" ? "por confirmar" : "por definir")))))));
    }
    const hitos = g.hitos.filter((x) => pos(x) != null);
    // Etiqueta corta (sin paréntesis ni fecha: la fecha va en el tooltip y en «Próximos hitos»). El reparto en niveles se mide en ajustarHitos.
    raiz.append(fila("g-hito", etiqueta("Hitos", h("span", { class: "g-hito-e" }, AP.icono ? AP.icono("hito", "ic-s") : "", "aceptación en acta")), h("div", { class: "g-pista" }, hitos.map((x) => {
      const p = pos(x);
      return h("div", { class: `g-m hito ${x.tipo} ${x.estado} ${x.fecha_estado}`,
        style: `left:${p}%`, title: `${x.nombre} · ${x.fecha_texto}` },
      h("i"), h("div", { class: "l" }, x.nombre.replace(/\s*\([^)]*\)/g, "").trim()));
    }))));
    const ph = pct(plan.hoy);
    if (ph >= 0 && ph <= 100) raiz.append(h("div", { class: "g-capa", "aria-hidden": "true" }, h("div", { class: "g-hoy" + (ph < 6 ? " izq" : ph > 88 ? " der" : ""), style: `left:${ph}%` }, h("span", {}, "Hoy · " + fmtDia(plan.hoy)))));
    if (typeof ResizeObserver === "function") new ResizeObserver(() => ajustarGantt(raiz)).observe(raiz);
    return raiz;
  }

  // Ajuste medido del Gantt (se repite al cambiar el ancho): (1) hitos en niveles; una etiqueta que no cabe en ningún nivel pierde el
  // texto y queda solo el rombo (nombre y fecha en el tooltip); nunca se solapan. (2) Un nombre de fase que no cabe en su barra va fuera.
  const NIVEL_H = 20, HUECO_H = 8;
  function ajustarGantt(raiz) {
    if (!raiz.isConnected || !raiz.clientWidth) return;
    const pista = raiz.querySelector(".g-hito .g-pista");
    if (pista) {
      const ms = [...pista.querySelectorAll(".g-m.hito")];
      ms.forEach((m) => { m.classList.remove("sin-etiqueta", "ancla-d"); m.style.top = ""; });
      const base = pista.getBoundingClientRect();
      const caja = (m) => { const r = m.getBoundingClientRect(); return [r.left - base.left - HUECO_H / 2, r.right - base.left + HUECO_H / 2]; };
      const libre = (lista, i, d) => lista.every(([a, b]) => d <= a || i >= b);
      const datos = ms.map((m) => {
        let [i, d] = caja(m);
        if (d > base.width + HUECO_H / 2) { m.classList.add("ancla-d"); [i, d] = caja(m); }   // no cabe a la derecha: etiqueta a la izquierda del rombo
        return { m, i, d };
      }).sort((a, b) => a.i - b.i);
      const ocupado = [[], [], []];   // niveles con etiqueta (3 como máximo); el rombo suelto puede abrir más
      for (const x of datos) {
        let nivel = x.i < -HUECO_H / 2 || x.d > base.width + HUECO_H / 2 ? -1 : ocupado.findIndex((l) => libre(l, x.i, x.d));
        if (nivel >= 0) ocupado[nivel].push([x.i, x.d]);
        else {   // sin sitio: solo rombo, en el primer nivel donde quepa
          x.m.classList.add("sin-etiqueta");
          const [i, d] = caja(x.m);
          nivel = ocupado.findIndex((l) => libre(l, i, d));
          if (nivel < 0) { ocupado.push([]); nivel = ocupado.length - 1; }
          ocupado[nivel].push([i, d]);
        }
        x.m.style.top = nivel * NIVEL_H + "px";
      }
      const usados = ocupado.reduce((n, l, k) => (l.length ? k + 1 : n), 1);
      pista.style.height = pista.style.minHeight = Math.max(24, usados * NIVEL_H + 4) + "px";
    }
    raiz.querySelectorAll(".g-barra").forEach((b) => {
      const t = b.querySelector(".g-bt");
      b.classList.remove("fuera", "fuera-i");
      if (t.scrollWidth > t.clientWidth + 0.5) b.classList.add(parseFloat(b.style.left) > 55 ? "fuera-i" : "fuera");
    });
  }
  const leyenda = () => h("div", { class: "g-leyenda" },
    h("span", {}, h("i", { class: "ll" }), "sesión celebrada"), h("span", {}, h("i", { class: "pr" }), "propuesta o próxima"),
    h("span", {}, h("i", { class: "hi" }), "hito (relleno: aceptación; trazo discontinuo: sin fecha)"), h("span", {}, h("i", { class: "ho" }), "hoy"));

  function fichaEl(f) {
    return h("div", { class: "ctx-ficha" }, f.que_es.map((l) => h("p", {}, l)),
      f.fuente && f.fuente.fichero ? h("div", { class: "fuente" }, "Fuente: " + f.fuente.fichero + (f.fuente.version ? " · " + f.fuente.version : "")) : null);
  }

  function reunionEl(ses, plan) {
    const gs = plan.gantt ? plan.gantt.sesiones.find((x) => x.id === ses.id) : null;
    const estado = gs ? gs.estado : "";
    const fechaTxt = gs ? gs.fecha_texto : ses.fecha;
    const sinFecha = !fechaTxt || /por definir|por confirmar/i.test(fechaTxt);
    const dep = ses.depende_de.map((d) => {
      const x = plan.gantt ? plan.gantt.sesiones.find((y) => y.id === d) : null;
      return x ? `${d} (${(ESTADO_SES[x.estado] || "").toLowerCase()})` : d;
    });
    return h("div", { class: "ctx-reunion", id: "ctx-reunion" },
      h("div", { class: "tt" }, h("span", { class: "id" }, ses.id), h("b", {}, ses.nombre), estado ? chipEstado(estado) : null),
      h("div", { class: "meta" }, h("b", {}, "Fecha: "), sinFecha ? h("span", { class: "pordef" }, fechaTxt || "por definir") : fechaTxt,
        ses.hora ? " · " + ses.hora : ""),
      ses.participantes ? h("div", { class: "meta" }, h("b", {}, "Participantes: "), ses.participantes) : null,
      dep.length ? h("div", { class: "meta" }, h("b", {}, "Depende de: "), dep.join(", ")) : null,
      ses.objetivos.length ? h("div", { class: "ctx-sub", style: "margin-top:8px" }, h("span", { class: "caps" }, "Objetivos principales"),
        h("ol", { id: "ctx-objetivos" }, ses.objetivos.map((o) => h("li", {}, o)))) : null);
  }

  // Lista de checks: se marcan y desmarcan a mano (queda bloqueado), se añaden, editan y borran; los automáticos llevan minuto y cita.
  function crearChecks(ref, op = {}) {
    let lista = [];
    const cuenta = h("span", { class: "n" });
    const caja = h("div", { class: "chk-lista" });
    const nuevo = h("input", { class: "input", type: "text", maxlength: "140", placeholder: "Añadir un check…", "aria-label": "Texto del nuevo check", autocomplete: "off" });
    const err = h("div", { class: "chk-error", hidden: true, role: "alert" });
    const el = h("section", { class: "chk", "aria-label": "Checks de preparación" },
      h("div", { class: "grupo-h" }, h("span", { class: "caps" }, op.titulo || "Checks de preparación"), cuenta), caja,
      h("div", { class: "chk-add" }, nuevo, h("button", { class: "btn", type: "button", onclick: () => anadir() }, "Añadir")), err);
    const cuerpo = (extra = {}) => ({ ...ref(), ...extra });
    const llamar = async (m, ruta, datos) => {
      err.hidden = true;
      try { const r = await api(m, ruta, datos); set(r.checks); if (op.alCambiar) op.alCambiar(r.checks); }
      catch (e) { err.textContent = e.message; err.hidden = false; pintar(); }
    };
    const url = (c) => "/api/checks/" + encodeURIComponent(c.id);
    const anadir = () => { const t = nuevo.value.trim(); if (!t) return; nuevo.value = ""; llamar("POST", "/api/checks", cuerpo({ texto: t })); };
    nuevo.addEventListener("keydown", (ev) => { if (ev.key === "Enter") { ev.preventDefault(); anadir(); } });
    function fila(c) {
      const hecho = c.estado === "hecho";
      const sug = c.origen === "sugerido" && !hecho;
      // «Confirmar» acepta la sugerencia como check propio (editar sin cambiar el texto la pasa a manual)
      const marca = h("input", { type: "checkbox", checked: hecho, "aria-label": c.texto, onchange: (ev) => llamar("PUT", url(c), cuerpo({ hecho: ev.target.checked })) });
      const tx = h("span", { class: "chk-tx t-body-m" }, c.texto);
      const editar = () => {
        const ed = h("input", { class: "input chk-editar", type: "text", value: c.texto, maxlength: "140", "aria-label": "Editar el check" });
        ed.addEventListener("keydown", (ev) => {
          if (ev.key === "Enter") { ev.preventDefault(); const t = ed.value.trim(); if (t && t !== c.texto) llamar("PUT", url(c), cuerpo({ texto: t })); else pintar(); }
          if (ev.key === "Escape") pintar();
        });
        tx.replaceWith(ed); ed.focus(); ed.select();
      };
      // un automático acaba de cambiar: «Deshacer» visible 10 s; después solo con ratón o foco. La marca se traza una vez (400 ms).
      const visto = AP.vistoAuto || (AP.vistoAuto = new Map());
      let nuevoAuto = false, reciente = false;
      if (c.auto) {
        if (!visto.has(c.id)) { visto.set(c.id, Date.now()); nuevoAuto = true; }
        reciente = Date.now() - visto.get(c.id) < 10000;
        if (reciente) setTimeout(() => { const f = caja.querySelector(`[data-id="${CSS.escape(c.id)}"]`); if (f) f.classList.remove("reciente"); }, 10000 - (Date.now() - visto.get(c.id)));
      } else visto.delete(c.id);
      const acciones = [];
      if (sug) acciones.push(h("button", { type: "button", class: "chk-b confirmar", title: "Aceptar la sugerencia como check propio", onclick: () => llamar("PUT", url(c), cuerpo({ texto: c.texto })) }, "Confirmar"));
      if (c.auto) acciones.push(h("button", { type: "button", class: "chk-b deshacer", title: "Deshacer: vuelve a abierto y el análisis ya no lo toca", onclick: () => llamar("POST", url(c) + "/deshacer", cuerpo()) }, "Deshacer"));
      acciones.push(h("button", { type: "button", class: "chk-b menor", title: "Editar", "aria-label": "Editar " + c.texto, onclick: editar }, "Editar"),
        h("button", { type: "button", class: "chk-b menor", title: "Borrar", "aria-label": "Borrar " + c.texto, onclick: () => llamar("DELETE", url(c) + "?" + new URLSearchParams(Object.entries(ref()).filter(([, v]) => v != null)).toString()) }, "Borrar"));
      const chipMin = c.auto && c.minuto ? (op.enReunion ? h("button", { type: "button", class: "min t-meta", "data-t": c.t_seg, title: "Ir a ese momento de la transcripción", onclick: () => irAlMinuto(c.t_seg) }, c.minuto) : h("span", { class: "min t-meta" }, c.minuto)) : null;
      const cita = c.auto && c.cita ? (c.cita.length > 90 ? c.cita.slice(0, 89).trimEnd() + "…" : c.cita) : "";
      const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
      svg.setAttribute("viewBox", "0 0 16 16"); svg.setAttribute("aria-hidden", "true"); svg.setAttribute("class", "chk-svg");
      const tr = document.createElementNS("http://www.w3.org/2000/svg", "path");
      tr.setAttribute("d", "M4 8.4l2.7 2.7L12 5.6"); tr.setAttribute("pathLength", "100"); svg.append(tr);
      const cls = "chk-fila" + (hecho ? " hecho" : "") + (c.auto ? " auto" : "") + (sug ? " sug" : "") + (hecho && !c.auto ? " manual" : "") + (reciente ? " reciente" : "") + (nuevoAuto ? " traza" : "");
      return h("div", { class: cls, "data-id": c.id },
        h("label", { class: "chk-caja" }, marca, h("span", { class: "chk-marca" }, svg)), tx, chipMin,
        h("span", { class: "chk-acc" }, acciones),
        cita ? h("div", { class: "chk-cita t-meta" }, "«" + cita + "»") : null);
    }
    function pintar() {
      const hechos = lista.filter((c) => c.estado === "hecho").length;
      cuenta.textContent = lista.length ? `${hechos}/${lista.length} hechos` : "";
      caja.replaceChildren(...(lista.length ? lista.map(fila) : [h("div", { class: "chk-vacio" }, "Sin checks todavía. Añade los tuyos aquí.")]));
    }
    function set(l) { lista = l || []; pintar(); }
    async function cargar() {
      try {
        const r = ref();
        const q = new URLSearchParams(Object.entries(r).filter(([, v]) => v != null));
        set((await api("GET", "/api/checks?" + q.toString())).checks);
      } catch (e) { err.textContent = e.message; err.hidden = false; }
    }
    pintar();
    return { el, set, cargar };
  }

  // Panel de contexto: ficha y Gantt del plan, próximos hitos, sesiones y, con sesión elegida, objetivos y checks.
  function pintarContexto(cont, ctx) {
    const plan = ctx.plan, ses = plan && ctx.sesion ? plan.sesiones.find((s) => s.id === ctx.sesion) : null;
    const sinObjetivos = !!ses && !ses.objetivos.length;
    // En Preparar el nombre del proyecto ya está en la tarjeta de la izquierda: aquí solo se repite durante la reunión
    cont.replaceChildren(h("div", { class: "ctx-cab" }, h("span", { class: "caps" }, ctx.enReunion ? "Contexto de la reunión" : "Plan y checks del proyecto"),
      ctx.enReunion ? h("span", { class: "ctx-proy", title: ctx.proyecto || "Bandeja" }, ctx.proyecto || "Bandeja") : null));
    if (plan && !sinObjetivos) {
      if (plan.ficha) cont.append(fichaEl(plan.ficha));
      if (plan.gantt) {
        const g = plan.gantt, porId = Object.fromEntries(g.hitos.map((x) => [x.id, x]));
        cont.append(gantt(plan, ctx.sesion), leyenda());
        const proximos = (g.proximos_hitos || []).map((i) => porId[i]).filter(Boolean);
        cont.append(h("div", { class: "ctx-dos" },
          h("div", { class: "ctx-sub" }, h("span", { class: "caps" }, "Próximos hitos"),
            h("ul", { id: "ctx-hitos" }, proximos.length ? proximos.map((x) => h("li", { class: "hito-l" }, h("span", { class: "n" }, x.nombre),
              x.fecha_estado !== "confirmada" ? chipEstado(x.fecha_estado === "propuesta" ? "propuesta" : x.fecha_estado) : null,
              h("span", { class: "fecha" }, x.fecha_texto || textoFecha(x)))) : [h("li", {}, "Sin hitos pendientes.")])),
          h("div", { class: "ctx-sub" }, h("span", { class: "caps" }, "Sesiones"),
            h("ul", { id: "ctx-sesiones" }, g.sesiones.map((s) => {
              const sinF = s.estado === "por_definir" || s.estado === "por_confirmar";
              return h("li", { class: "ctx-ses" + (s.id === ctx.sesion ? " sel" : ""), "data-sesion": s.id },
                h("span", { class: "id" }, s.id), h("span", { class: "n" }, s.nombre), chipEstado(s.estado),
                sinF ? null : h("span", { class: "fecha" }, s.fecha_texto));
            })))));
      }
      if (ses) cont.append(reunionEl(ses, plan));
    } else {
      cont.append(h("p", { class: "ctx-nota" }, plan ? "Otra reunión: sin objetivos ni Gantt. Puedes llevar tus propios checks."
        : (ctx.proyecto ? "Este proyecto no tiene plan de sesiones: no hay Gantt ni objetivos. " : "La bandeja no tiene plan ni Gantt. ") + "Puedes llevar tus propios checks."));
    }
    if (plan && !ctx.sesion) return null;  // con plan, los checks dependen de la sesión elegida
    const chk = crearChecks(() => ({ proyecto: ctx.proyecto || null, sesion: ctx.sesion || null }), { enReunion: ctx.enReunion, alCambiar: ctx.alCambiar });
    cont.append(chk.el);
    if (ctx.checks) chk.set(ctx.checks); else chk.cargar();
    return chk;
  }

  function pintarContextoInicio() {
    const c = $("#i-contexto");
    if (UI.sel === undefined) { c.hidden = true; return; }
    c.hidden = false;
    const plan = (UI.proy && UI.proy.plan) || null;
    pintarContexto(c, { proyecto: UI.sel, plan, sesion: plan ? UI.sesionPlan : null });
  }

  // ------------------------------------------------------------ INICIO
  async function cargarProyectos() {
    try {
      const r = await api("GET", "/api/proyectos?q=" + encodeURIComponent($("#i-buscar").value.trim()));
      UI.proyectos = r.proyectos;
      UI.proy = typeof UI.sel === "string" ? (r.proyectos.find((p) => p.nombre === UI.sel) || null) : null;
      $("#i-raiz").textContent = "Raíz de proyectos: " + r.raiz + (r.proyectos.length ? "" : " (sin coincidencias)");
      pintarLista(); pintarSesiones(); validarInicio();
      if (AP.hooks.proyectosCargados) AP.hooks.proyectosCargados(r);   // proyectos.js: pide el resumen visual (descripción, actividad, calidad…)
    } catch (e) {
      $("#i-raiz").textContent = "No se pudieron cargar los proyectos: " + e.message;
      if (AP.hooks.errorLista) AP.hooks.errorLista(e);
    }
  }
  // Elegir un proyecto (o la Bandeja, con clave null): la lista nueva (proyectos.js) y la de respaldo comparten esta función
  function elegirProyecto(clave, proy = null) {
    if (UI.sel !== clave) { UI.sesionPlan = undefined; if (UI.temaAuto && $("#i-tema").value === UI.temaAuto) $("#i-tema").value = ""; UI.temaAuto = ""; }
    UI.sel = clave; UI.proy = proy;
    safe(() => localStorage.setItem("apuntes_proy", clave === null ? "__bandeja__" : clave));
    if (AP.hooks.alElegirProyecto) AP.hooks.alElegirProyecto(clave, proy);
    pintarLista(); pintarSesiones(); validarInicio();
  }
  function pintarLista() {
    if (AP.hooks.pintarLista) return AP.hooks.pintarLista();   // proyectos.js: secciones, favoritos, recientes, buscador y vista previa
    const l = $("#i-lista");
    l.replaceChildren();
    const fila = (clave, nombre, etiqueta, extra = "", proy = null) => h("button", { type: "button", role: "option", class: "item " + extra,
      "aria-selected": String(UI.sel === clave), "data-clave": clave, onclick: () => elegirProyecto(clave, proy) },
      h("span", { class: "n" }, nombre), proy && proy.compartido ? h("span", { class: "tag comp", title: proy.ruta }, "compartida") : null,
      h("span", { class: "tag" }, etiqueta));
    l.append(fila(null, "Bandeja (reunión sin proyecto)", "se guarda en apuntes\bandeja", "bandeja"));
    UI.proyectos.forEach((p) => l.append(fila(p.nombre, p.nombre,
      (p.compartido ? "se publica al terminar" : p.tiene_contexto ? "con contexto" : "sin contexto") + (p.plan ? " · con plan" : ""), "", p)));
  }
  // Aviso de carpeta compartida y selector de sesión del plan
  function pintarSesiones() {
    const p = UI.proy, plan = p && p.plan;
    const av = $("#i-compartido");
    av.hidden = !(p && p.compartido);
    if (p && p.compartido) av.replaceChildren(h("b", {}, "Carpeta compartida"),
      "Es una carpeta de otra persona: la transcripción se guarda solo en tu equipo y se publica al terminar, sin sobrescribir nada.");
    $("#i-sesion-campo").hidden = !plan;
    const l = $("#i-sesiones");
    l.replaceChildren();
    $("#i-ses-detalle").hidden = true;
    if (!plan) { pintarContextoInicio(); return; }
    plan.sesiones.forEach((s) => l.append(h("button", { type: "button", role: "option", class: "item", "aria-selected": String(UI.sesionPlan === s.id),
      "data-sesion": s.id, onclick: () => elegirSesion(s) },
      h("span", { class: "id" }, s.objetivos.length ? s.id : ""), h("span", { class: "n" }, s.nombre),
      h("span", { class: "tag" }, s.fecha || (s.objetivos.length ? "" : "sin objetivos")))));
    pintarContextoInicio();  // el detalle de la sesión (objetivos, participantes, dependencias) vive en el panel de contexto
  }
  function detalleSesion(s) {
    const d = $("#i-ses-detalle");
    d.hidden = false;
    d.replaceChildren(
      h("div", { class: "meta" }, [s.fecha ? "Fecha: " + s.fecha : null, s.participantes ? "Participantes: " + s.participantes : null,
        s.depende_de.length ? "Depende de: " + s.depende_de.join(", ") : null, s.fichero_prioritario ? "Fichero prioritario: " + s.fichero_prioritario : null].filter(Boolean).join(" · ")),
      s.objetivos.length ? h("ul", { id: "i-ses-objetivos" }, s.objetivos.map((o) => h("li", {}, o))) : h("div", { class: "meta" }, "Sin objetivos: no se vigila nada."));
  }
  function elegirSesion(s) {
    UI.sesionPlan = s.id;
    const t = $("#i-tema");
    if (!s.objetivos.length) { if (UI.temaAuto && t.value === UI.temaAuto) t.value = ""; UI.temaAuto = ""; }
    else if (!t.value.trim() || t.value === UI.temaAuto) { t.value = s.nombre; UI.temaAuto = s.nombre; }
    pintarSesiones(); validarInicio();
  }
  function validarInicio() {
    const plan = UI.proy && UI.proy.plan;
    const ok = $("#i-aviso").checked && UI.sel !== undefined && $("#i-tema").value.trim().length > 0 && (!plan || UI.sesionPlan !== undefined);
    $("#i-empezar").disabled = !ok;
    $("#i-ayuda").textContent = ok ? "" : !$("#i-aviso").checked ? "Confirma que has avisado a los asistentes."
      : UI.sel === undefined ? "Elige un proyecto o la bandeja." : plan && UI.sesionPlan === undefined ? "Elige la sesión del plan (o «Otra reunión»)." : "Escribe el tema de la reunión.";
  }
  let temporizadorBuscar;
  $("#i-buscar").addEventListener("input", () => { clearTimeout(temporizadorBuscar); temporizadorBuscar = setTimeout(cargarProyectos, 200); });
  ["#i-aviso", "#i-tema"].forEach((s) => $(s).addEventListener("input", validarInicio));
  // «Idioma de la reunión»: auto (por defecto) | es | ca | en. Se recuerda en localStorage (con try/catch: puede no haber almacenamiento) y viaja en
  // /api/sesion/iniciar; el dictado del contexto usa el mismo valor.
  const IDIOMAS = ["auto", "es", "ca", "en"];
  function idiomaGuardado() {
    try { const v = localStorage.getItem("apuntes_idioma"); return IDIOMAS.includes(v) ? v : "auto"; } catch { return "auto"; }
  }
  function fijarIdioma(v, guardar) {
    UI.idioma = IDIOMAS.includes(v) ? v : "auto";
    $$("[data-idioma]").forEach((x) => x.setAttribute("aria-checked", String(x.dataset.idioma === UI.idioma)));
    if (guardar) { try { localStorage.setItem("apuntes_idioma", UI.idioma); } catch { /* sin almacenamiento */ } }
  }
  fijarIdioma(idiomaGuardado(), false);
  $$("[data-idioma]").forEach((b) => b.addEventListener("click", () => fijarIdioma(b.dataset.idioma, true)));
  // «Ritmo del equipo» (antes «Cadencia»): equipo | 5 | 10 | manual. Se recuerda entre reuniones (localStorage con try/catch) y viaja como `cadencia`.
  const RITMOS = ["equipo", "5", "10", "manual"];
  const ETQ_RITMO = { equipo: "según lo que se diga", 5: "cada 5 min", 10: "cada 10 min", manual: "solo si lo pido" };
  function fijarRitmo(v, guardar) {
    UI.cad = RITMOS.includes(String(v)) ? String(v) : "equipo";
    $$("[data-cad]").forEach((x) => x.setAttribute("aria-checked", String(x.dataset.cad === UI.cad)));
    const est = $("#i-opciones-estado"); if (est) est.textContent = "Ritmo del equipo: " + ETQ_RITMO[UI.cad];
    if (guardar) { try { localStorage.setItem("apuntes_ritmo", UI.cad); } catch { /* sin almacenamiento */ } }
  }
  fijarRitmo(safe(() => localStorage.getItem("apuntes_ritmo"), "equipo"), false);
  $$("[data-cad]").forEach((b) => b.addEventListener("click", () => fijarRitmo(b.dataset.cad, true)));
  $("#i-empezar").addEventListener("click", async () => {
    $("#i-error").hidden = true;
    $("#i-empezar").disabled = true;
    try {
      if (AP.hooks.antesDeEmpezar) await AP.hooks.antesDeEmpezar();   // un dictado abierto se cierra antes: la reunión usa el micro
      const contexto_reunion = UI.contextoReunion || "";             // «Contexto de la reunión» aceptado (vacío = todo como siempre)
      reiniciarReunion();
      await api("POST", "/api/sesion/iniciar", { proyecto: UI.sel, tema: $("#i-tema").value.trim(), cadencia: UI.cad,
        sesion_plan: UI.proy && UI.proy.plan ? UI.sesionPlan : null, objetivos: UI.objetivosPropios || [], contexto_reunion, idioma: UI.idioma || "auto" });
    } catch (e) {
      $("#i-error").textContent = e.message;
      $("#i-error").hidden = false;
    }
    validarInicio();
  });

  // ------------------------------------------------------------ REUNIÓN
  function reiniciarReunion() {
    S.segmentos = []; S.tarjetas = []; S.notas = ""; S.resumen_acumulado = ""; S.objetivos = []; S.checks = []; UI.decisiones = {};
    chkReunion = null; $("#r-checks").replaceChildren(); $("#r-chk-cuenta").textContent = "";
    if (AP.hooks.reiniciar) AP.hooks.reiniciar();
    pintarTrans(); pintarInsights(); pintarObjetivos(); $("#r-notas").value = "";
    UI.seguir = true;
  }
  function lineaTrans(s) {
    return h("div", { class: "lin " + s.fuente, "data-t": s.t, "data-id": s.id },
      h("span", { class: "t" }, s.mmss), h("span", { class: "q" }, s.fuente === "yo" ? "Micro" : "Reunión"), h("span", { class: "x" }, s.texto));
  }
  function pintarTrans() {
    if (AP.hooks.pintarTrans) return AP.hooks.pintarTrans();
    const c = $("#r-trans");
    c.replaceChildren();
    if (!S.segmentos.length) c.append(h("div", { class: "trans-vacio" }, "Esperando a que alguien hable…"));
    S.segmentos.forEach((s) => c.append(lineaTrans(s)));
  }
  function añadirSegmento(s) {
    if (AP.hooks.anadirSegmento) return AP.hooks.anadirSegmento(s);
    const c = $("#r-trans");
    if (!S.segmentos.some((x) => x.id === s.id)) S.segmentos.push(s);
    const vacio = $(".trans-vacio", c); if (vacio) vacio.remove();
    c.append(lineaTrans(s));
    if (UI.seguir) c.scrollTop = c.scrollHeight; else $("#r-alfinal").hidden = false;
  }
  $("#r-trans").addEventListener("scroll", () => {
    const c = $("#r-trans");
    UI.seguir = c.scrollHeight - c.scrollTop - c.clientHeight < 40;
    $("#r-alfinal").hidden = UI.seguir;
  });
  $("#r-alfinal").addEventListener("click", () => { const c = $("#r-trans"); c.scrollTop = c.scrollHeight; });

  const GRUPOS = [["decisión", "Decisiones", "decision"], ["pendiente", "Pendientes", "pendiente"], ["contradicción", "Contradicciones", "contradiccion"],
    ["pregunta", "Preguntas que convendría hacer", "pregunta"], ["riesgo", "Riesgos", "riesgo"]];
  function irAlMinuto(seg) {
    if (AP.hooks.irAlMinuto) return AP.hooks.irAlMinuto(seg);
    if (seg == null) return;
    const lineas = $$("#r-trans .lin");
    let dest = null;
    for (const l of lineas) { if (Number(l.dataset.t) <= seg + 1) dest = l; else break; }
    dest = dest || lineas[0];
    if (!dest) return;
    UI.seguir = false;
    dest.scrollIntoView({ block: "center" });
    dest.classList.add("resalte");
    setTimeout(() => dest.classList.remove("resalte"), 2200);
  }
  function pintarInsights() {
    if (AP.hooks.pintarInsights) return AP.hooks.pintarInsights();
    const c = $("#r-insights");
    c.replaceChildren();
    if (!S.tarjetas.length) { c.append(h("div", { class: "vacio-i" }, "Aquí irán apareciendo las decisiones, los pendientes, los riesgos y las preguntas que salgan de la conversación.")); }
    GRUPOS.forEach(([cat, titulo, clase]) => {
      const ts = S.tarjetas.filter((t) => t.categoria === cat);
      if (!ts.length) return;
      c.append(h("section", { class: "grupo" },
        h("div", { class: "grupo-h" }, h("span", { class: "caps" }, titulo), h("span", { class: "n" }, ts.length)),
        ts.map((t) => h("article", { class: "tarj " + clase },
          h("div", { class: "tx" }, t.texto),
          t.estado === "posible" ? h("div", { class: "ref" }, "Posible contradicción: se confirmará al terminar la reunión") : null,
          t.referencia ? h("div", { class: "ref" }, "Contexto: «" + t.referencia + "»") : null,
          h("div", { class: "pie-t" },
            t.minuto ? h("button", { type: "button", class: "min", title: "Ir a ese momento de la transcripción", onclick: () => irAlMinuto(t.t_seg) }, t.minuto) : null,
            t.responsable ? h("span", {}, "Responsable: " + t.responsable) : null,
            t.nota ? h("span", {}, t.nota) : null)))));
    });
    const det = $("#r-resumen-det");
    det.hidden = !S.resumen_acumulado;
    $("#r-resumen").textContent = S.resumen_acumulado || "";
  }

  const ESTADO_OBJ = { sin_tratar: "Sin tratar", parcial: "Parcial", cubierto: "Cubierto" };
  function pintarObjetivos() {
    if (AP.hooks.pintarObjetivos) return AP.hooks.pintarObjetivos();
    const os = S.objetivos || [];
    $("#r-objetivos").hidden = !os.length;
    if (!os.length) return;
    $("#r-obj-cuenta").textContent = `${os.filter((o) => o.estado === "cubierto").length}/${os.length} cubiertos`;
    $("#r-obj-lista").replaceChildren(...os.map((o) => h("div", { class: "obj " + o.estado },
      h("span", { class: "estado" }, ESTADO_OBJ[o.estado] || o.estado), h("span", { class: "tx" }, o.texto),
      o.minuto ? h("button", { type: "button", class: "min", title: "Ir a ese momento de la transcripción", onclick: () => irAlMinuto(o.t_seg) }, o.minuto) : null)));
  }

  function pintarEstadoReunion() {
    const s = S.sesion;
    if (!s) return;
    $("#r-tema").textContent = s.tema;
    $("#r-meta").textContent = `${s.proyecto || "Bandeja"}${s.compartido ? " (compartida)" : ""}`;
    $("#r-meta").title = `${s.plan ? s.plan.id + " " + s.plan.nombre + " · " : ""}análisis ${({ equipo: 'el equipo', manual: 'solo a petición' })[s.cadencia] || 'cada ' + s.cadencia_min + ' min'} · ${s.carpeta}\\${s.fichero}`;
    pintarObjetivos();
    const pausada = S.estado === "pausada", terminando = S.estado === "terminando";
    $("#r-pausa").textContent = pausada ? "Reanudar" : "Pausa";
    $("#r-pausa").disabled = terminando;
    $("#r-analizar").disabled = terminando || !!S.analisis.en_curso;
    $("#r-terminar").disabled = terminando;
    $("#r-terminar").textContent = terminando ? "Terminando…" : "Terminar";
    $("#r-reloj").classList.toggle("pausa", pausada);
    // avisos de captura
    pintarAvisos();
    if (AP.hooks.linea) { AP.hooks.linea(); pie(); return; }
    // análisis (respaldo si el módulo de orquestación no carga)
    const a = S.analisis || {};
    let txt = "";
    if (a.en_curso) txt = "Analizando…";
    else if (a.bloqueo) txt = "Análisis en pausa";
    else if (a.proximo_en != null && !pausada) txt = "Próximo análisis en " + mmss(a.proximo_en);
    else if (pausada) txt = "En pausa";
    $("#r-analisis-estado").textContent = txt;
    const b = $("#r-banner");
    b.replaceChildren();
    if (a.bloqueo) b.append(h("div", { class: "banner" }, h("b", {}, a.bloqueo.tipo === "sesion" ? "Claude Code no tiene la sesión iniciada" : "Límite del plan alcanzado"), a.bloqueo.mensaje));
    else if (a.ultimo_error) b.append(h("div", { class: "banner" }, h("b", {}, "El último análisis falló"), a.ultimo_error.mensaje + " La grabación continúa; se reintentará con los datos acumulados."));
    if (a.ultimo_omitido && !a.en_curso) b.append(h("div", { class: "banner info" }, a.ultimo_omitido.motivo));
    // transcripción
    const tr = S.transcripcion;
    let t = "";
    if (S.simulacion) t = "Simulación sin audio";
    else if (tr) t = tr.estado === "cargando" ? "Cargando el modelo de transcripción…" : tr.estado === "error" ? tr.error
      : tr.pendiente_s > 3 ? `Transcripción con ${Math.round(tr.pendiente_s)} s de retraso` : "";
    $("#r-estado-trans").textContent = t;
    pie();
  }

  function pie() {
    if (AP.hooks.pie) return AP.hooks.pie();
    const tr = S.transcripcion;
    $("#p-trans").textContent = S.simulacion ? "Modo simulación" : tr ? "Transcripción: " + ({ cargando: "cargando modelo", listo: "lista", error: "con error", sin_cargar: "en espera" }[tr.estado] || tr.estado)
      + (tr.velocidad_x ? ` · ${tr.velocidad_x.toFixed(1).replace(".", ",")}× tiempo real` : "") : "Transcripción: en espera";
    const d = S.digest || {};
    $("#p-digest").textContent = d.origen ? "Contexto: " + ({ generado: "resumido ahora", cache: "ya preparado antes", vacio: "sin contenido útil en el proyecto", sin_proyecto: "sin proyecto", contexto_usuario: "el que aceptaste antes de empezar", error: "no disponible" }[d.origen] || d.origen) : "";
    const c = S.consumo;
    if (!c || !c.llamadas) { $("#p-consumo").textContent = "Consumo: sin llamadas"; return; }
    const ent = c.total.entrada + c.total.cache_creacion + c.total.cache_lectura;
    const modelos = Object.entries(c.por_modelo).map(([m, u]) => `${m.replace(/^claude-/, "").replace(/-\d+(-\d+)?$/, "")} ${u.llamadas}`).join(" · ");
    $("#p-consumo").textContent = `Consumo: ${kfmt(ent)} ent · ${kfmt(c.total.salida)} sal · ${modelos}`;
  }

  $("#r-pausa").addEventListener("click", () => api("POST", S.estado === "pausada" ? "/api/sesion/reanudar" : "/api/sesion/pausa").catch(alerta));
  $("#r-analizar").addEventListener("click", async () => {
    $("#r-analizar").disabled = true;
    try { await api("POST", "/api/sesion/analizar"); } catch (e) { alerta(e); }
  });
  $("#r-terminar").addEventListener("click", async () => {
    if (!(await AP.confirmar({ titulo: "¿Terminar la reunión?", texto: "Se generará el resumen final y la propuesta de cambios. Podrás revisarlos antes de aplicar nada.", aceptar: "Terminar", cancelar: "Seguir grabando" }))) return;
    try { await api("POST", "/api/sesion/terminar"); } catch (e) { alerta(e); }
  });
  let tNotas;
  $("#r-notas").addEventListener("input", () => {
    $("#r-notas-estado").textContent = "Guardando…";
    clearTimeout(tNotas);
    tNotas = setTimeout(async () => {
      try { await api("PUT", "/api/sesion/notas", { texto: $("#r-notas").value }); $("#r-notas-estado").textContent = "Guardadas"; }
      catch (e) { $("#r-notas-estado").textContent = "No se guardaron"; }
    }, 700);
  });
  // Avisos de la reunión (captura, fichero prioritario no disponible, errores): cada uno se puede cerrar y no vuelve en esa sesión.
  function pintarAvisos() {
    const av = $("#r-avisos"), sid = S.sesion ? S.sesion.id : "";
    const cerrados = UI.avisosCerrados || (UI.avisosCerrados = new Set());
    const lista = [...S.avisos, ...(UI.avisoExtra ? [UI.avisoExtra] : [])].filter((a) => !cerrados.has(sid + "|" + a));
    av.hidden = !lista.length;
    av.replaceChildren(...lista.map((a) => h("span", { class: "aviso-it" }, h("span", { class: "aviso-tx" }, a),
      h("button", { type: "button", class: "aviso-x", "aria-label": "Cerrar este aviso", title: "Cerrar este aviso",
        onclick: () => { cerrados.add(sid + "|" + a); if (UI.avisoExtra === a) UI.avisoExtra = ""; pintarAvisos(); } }, "×"))));
  }
  function alerta(e) { UI.avisoExtra = (e && e.message) || String(e); pintarAvisos(); }

  // medidores con caída suave
  const nivel = { yo: { v: 0, t: 0 }, reunion: { v: 0, t: 0 } };
  function ponerNivel(f, db) { nivel[f] = { v: Math.max(0, Math.min(100, ((db + 60) / 60) * 100)), t: performance.now() }; }
  setInterval(() => {
    for (const f of ["yo", "reunion"]) {
      const n = nivel[f];
      if (performance.now() - n.t > 500) n.v = Math.max(0, n.v - 12);
      if (AP.hooks.medidor) AP.hooks.medidor(f, n.v); else $("#vu-" + f).style.width = n.v + "%";
    }
  }, 100);

  // ------------------------------------------------------------ checks y cajón de contexto durante la reunión
  const refReunion = () => ({ proyecto: S.sesion ? S.sesion.proyecto : null, sesion: S.sesion && S.sesion.plan ? S.sesion.plan.id : null });
  let chkReunion = null, chkCajon = null, firmaChecks = "";
  function sincronizarChecks() {
    firmaChecks = JSON.stringify(S.checks) + "|" + (S.sesion ? S.sesion.id : "");
    if (chkReunion) chkReunion.set(S.checks);
    if (chkCajon) chkCajon.set(S.checks);
    const hechos = S.checks.filter((c) => c.estado === "hecho").length;
    $("#r-chk-cuenta").textContent = S.checks.length ? `${hechos}/${S.checks.length} hechos` : "";
  }
  function pintarChecksReunion() {
    const s = S.sesion;
    if (!s) return;
    if (!chkReunion || chkReunion.sid !== s.id) {
      chkReunion = crearChecks(refReunion, { enReunion: true, titulo: "Checks", alCambiar: (l) => { S.checks = l; sincronizarChecks(); } });
      chkReunion.sid = s.id;
      $("#r-checks").replaceChildren(chkReunion.el);
      firmaChecks = "";
    }
    if (firmaChecks !== JSON.stringify(S.checks) + "|" + s.id) sincronizarChecks();
  }
  async function abrirCajon() {
    const s = S.sesion;
    if (!s) return;
    $("#r-drawer").hidden = false;
    $("#r-contexto").setAttribute("aria-expanded", "true");
    const cont = $("#r-ctx");
    cont.replaceChildren(h("div", { class: "cargando" }, "Cargando el contexto"));
    let plan = null;
    try { const r = await api("GET", "/api/proyectos"); const p = r.proyectos.find((x) => x.nombre === s.proyecto); plan = p ? p.plan : null; } catch { /* sin plan */ }
    if ($("#r-drawer").hidden) return;
    const sec = h("section", { class: "contexto" });
    cont.replaceChildren(sec);
    chkCajon = pintarContexto(sec, { proyecto: s.proyecto, plan, sesion: s.plan ? s.plan.id : null, enReunion: true, checks: S.checks,
      alCambiar: (l) => { S.checks = l; sincronizarChecks(); } });
    $("#r-drawer-x").focus();
  }
  function cerrarCajon() {
    $("#r-drawer").hidden = true;
    $("#r-contexto").setAttribute("aria-expanded", "false");
    chkCajon = null;
    $("#r-ctx").replaceChildren();
  }
  $("#r-contexto").addEventListener("click", () => ($("#r-drawer").hidden ? abrirCajon() : cerrarCajon()));
  $("#r-drawer-x").addEventListener("click", cerrarCajon);
  document.addEventListener("keydown", (ev) => { if (ev.key === "Escape" && !$("#r-drawer").hidden) cerrarCajon(); });

  // ------------------------------------------------------------ REVISIÓN
  function pintarRevision() {
    if (AP.hooks.pintarRevision) return AP.hooks.pintarRevision();
    const rev = S.revision, s = S.sesion;
    if (!rev || !s) return;
    $("#v-rev-titulo").textContent = "Revisión: " + s.tema;
    $("#v-rev-meta").textContent = `${s.proyecto || "Bandeja"}${s.compartido ? " (carpeta compartida)" : ""} · ${s.compartido ? "copia local en" : "transcripción guardada en"} ${s.carpeta}\\${s.fichero}`;
    const cuerpo = $("#v-rev-cuerpo");
    cuerpo.replaceChildren();
    const pie = $("#v-rev-pie");
    if (rev.estado === "generando") {
      pie.hidden = true;
      cuerpo.append(h("div", { class: "cargando" }, "Generando el resumen final y los cambios propuestos"));
      return;
    }
    if (rev.estado === "error") {
      pie.hidden = false;
      $("#v-rev-cuenta").textContent = "La transcripción está guardada.";
      $("#v-rev-aplicar").hidden = true;
      $("#v-rev-cerrar").textContent = "Cerrar";
      cuerpo.append(h("div", { class: "error" }, h("b", {}, "No se pudo generar el resumen final. "), rev.error),
        h("div", { class: "acciones" }, h("button", { class: "btn btn-primary", type: "button", onclick: () => api("POST", "/api/revision/reintentar").catch(alerta) }, "Reintentar")),
        seccionPublicacion(rev));
      return;
    }
    $("#v-rev-aplicar").hidden = false;
    const pu = rev.pulido || { estado: "ninguno" };
    const elegir = (v) => api("POST", "/api/revision/resumen", { version: v }).catch((e) => avisarError(e));
    if ((rev.avisos || []).length) {
      cuerpo.append(h("section", { class: "sec aviso", id: "v-rev-avisos" }, h("span", { class: "caps" }, "Aviso sobre el resumen"),
        h("ul", {}, rev.avisos.map((a) => h("li", {}, a)))));
    }
    if (pu.estado === "listo") {
      cuerpo.append(
        h("section", { class: "sec" }, h("span", { class: "caps" }, "Resumen final: versión de Sonnet" + (pu.elegida === "sonnet" ? " (elegida)" : "")),
          md(rev.resumen_sonnet || "Sin resumen."),
          pu.elegida === "sonnet" ? null : h("button", { class: "btn", type: "button", onclick: () => elegir("sonnet") }, "Quedarme con la de Sonnet")),
        h("section", { class: "sec" }, h("span", { class: "caps" }, "Resumen final: versión pulida con Opus" + (pu.elegida === "opus" ? " (elegida)" : "")),
          md(pu.resumen || ""),
          pu.elegida === "opus" ? null : h("button", { class: "btn", type: "button", id: "v-rev-elegir-opus", onclick: () => elegir("opus") }, "Quedarme con la pulida")));
    } else {
      cuerpo.append(h("section", { class: "sec" }, h("span", { class: "caps" }, "Resumen final"), md(rev.resumen || "Sin resumen."),
        pu.estado === "generando" ? h("p", { class: "soft" }, "Puliendo con Opus…") : h("div", { class: "acciones" },
          h("button", { class: "btn", type: "button", id: "v-rev-pulir", onclick: () => api("POST", "/api/revision/pulir").catch((e) => avisarError(e)) },
            pu.estado === "error" ? "Volver a pulir con Opus" : "Pulir con Opus"),
          h("span", { class: "soft" }, " Opcional: gasta bastante más de tu licencia que el resto del análisis. Solo se ejecuta si lo pulsas; se muestran las dos versiones y eliges."),
          pu.estado === "error" ? h("div", { class: "error", id: "v-rev-pulir-error" }, "No se pudo pulir: " + pu.error + " La revisión sigue con la versión de Sonnet.") : null)));
    }
    const pub = seccionPublicacion(rev);
    if (pub) cuerpo.append(pub);
    if (S.tarjetas.length) {
      cuerpo.append(h("section", { class: "sec" }, h("span", { class: "caps" }, "Insights de la reunión"),
        GRUPOS.map(([cat, titulo]) => { const ts = S.tarjetas.filter((t) => t.categoria === cat); return ts.length
          ? h("div", { class: "md" }, h("h4", {}, titulo), h("ul", {}, ts.map((t) => h("li", {}, `[${t.minuto || "--:--"}] ${t.texto}${t.responsable ? " (" + t.responsable + ")" : ""}`)))) : null; })));
    }
    const sec = h("section", { class: "sec" }, h("span", { class: "caps" }, "Cambios propuestos al contexto"));
    cuerpo.append(sec);
    if (!s.proyecto) {
      sec.append(h("p", { class: "soft" }, "Reunión sin proyecto: no hay ficheros de contexto que actualizar. La transcripción queda en la bandeja."));
    } else {
      if (rev.compartido) sec.append(h("div", { class: "banner", id: "v-rev-compartido" }, h("b", {}, "Se escribirá en una carpeta compartida"),
        "Los cambios que aceptes se escribirán en «" + rev.destino_contexto + "», una carpeta compartida de otra persona, y se añadirá una entrada a 10-registro-de-cambios.md. Revisa cada diff antes de aceptar. La transcripción no se copia allí."));
      if (rev.carpeta_contexto === false) sec.append(h("div", { class: "banner info" }, "La carpeta «00. CONTEXTO (IA)» no existe en este proyecto. Si aceptas algún cambio se creará con las plantillas del kit."));
      if (!rev.cambios.length) sec.append(h("p", { class: "soft" }, "Esta reunión no ha generado cambios para el contexto." + (rev.sin_cambios ? " Motivo: " + rev.sin_cambios : "")));
      rev.cambios.forEach((c) => sec.append(tarjetaCambio(c, !!rev.aplicado)));
    }
    if (rev.aplicado) {
      const a = rev.aplicado;
      cuerpo.append(h("div", { class: "resultado" }, a.aplicados.length
        ? `Aplicados ${a.aplicados.length} cambio(s) en ${a.ficheros.join(", ")}${a.carpeta_creada ? " (carpeta de contexto creada con las plantillas)" : ""}. Entrada añadida a 10-registro-de-cambios.md.`
        : "No se aplicó ningún cambio.", a.omitidos.length ? " No se pudieron aplicar: " + a.omitidos.map((o) => `${o.id} (${o.motivo})`).join("; ") + "." : ""));
    }
    pie.hidden = false;
    const validos = rev.cambios.filter((c) => c.valido);
    const acept = validos.filter((c) => UI.decisiones[c.id] === "si").length;
    $("#v-rev-cuenta").textContent = s.proyecto ? `${acept} aceptado(s) de ${validos.length} · el resto se descarta` : "";
    $("#v-rev-aplicar").hidden = !s.proyecto || !!rev.aplicado;
    $("#v-rev-aplicar").disabled = acept === 0;
    $("#v-rev-cerrar").textContent = rev.aplicado || !validos.length ? "Cerrar" : "Cerrar sin aplicar";
  }
  // Proyectos compartidos: el documento final se publica en «02. Sesiones» de la carpeta compartida al cerrar (por defecto sí).
  function seccionPublicacion(rev) {
    const p = rev.publicacion;
    if (!p) return null;
    const bloqueado = p.estado === "publicada";
    const cls = p.estado === "publicada" ? "ok" : p.estado === "error" ? "err" : "";
    const caja = h("div", { class: "pub " + cls, id: "v-rev-pub" });
    if (p.estado === "publicada") {
      caja.append(h("b", {}, "Documento publicado"), h("span", { class: "ruta" }, p.ruta));
    } else {
      caja.append(...[h("b", {}, "Carpeta compartida: publicación del documento final"),
        h("p", {}, "Durante la reunión el documento ha vivido solo en local. Al cerrar la revisión se publica el documento final (transcripción, resumen, objetivos y checks) en:"),
        h("span", { class: "ruta" }, p.destino || p.carpeta),
        h("p", { class: "soft" }, (p.carpeta_existe ? "" : "La carpeta «02. Sesiones» no existe y se creará al publicar. ") + "Nunca se sobrescribe: si el nombre ya existe, se añade un sufijo. Es una carpeta compartida de otra persona."),
        h("label", { class: "check" }, h("input", { type: "checkbox", id: "v-rev-publicar", checked: p.publicar, disabled: bloqueado,
          onchange: (ev) => api("POST", "/api/revision/publicacion", { publicar: ev.target.checked }).catch((e) => { avisarError(e); ev.target.checked = p.publicar; }) }),
        "Publicar en la carpeta compartida"),
        !p.publicar ? h("p", { class: "soft" }, "No se publicará: la carpeta compartida no se toca y el documento solo queda en la copia local.") : null].filter(Boolean));
    }
    if (p.estado === "error") caja.append(h("div", { class: "error", id: "v-rev-pub-error" }, p.error),
      h("div", { class: "acciones" }, h("button", { class: "btn btn-primary", type: "button", id: "v-rev-reintentar-pub",
        onclick: () => api("POST", "/api/revision/publicar").catch((e) => avisarError(e)) }, "Reintentar publicación")));
    return h("section", { class: "sec" }, h("span", { class: "caps" }, "Publicación"), caja);
  }
  function tarjetaCambio(c, bloqueado) {
    const dec = UI.decisiones[c.id];
    const fijar = (v) => () => { UI.decisiones[c.id] = v; pintarRevision(); };
    return h("article", { class: "cambio" + (c.valido ? "" : " invalido") },
      h("div", { class: "cambio-h" },
        h("span", { class: "f" }, c.fichero), h("span", { class: "m" }, c.motivo + (c.minuto ? ` · minuto ${c.minuto}` : "")),
        c.valido ? h("div", { class: "decide", role: "group", "aria-label": "Decisión sobre " + c.fichero },
          h("button", { type: "button", class: "si", "aria-pressed": String(dec === "si"), disabled: bloqueado, onclick: fijar("si") }, "Aceptar"),
          h("button", { type: "button", class: "no", "aria-pressed": String(dec === "no"), disabled: bloqueado, onclick: fijar("no") }, "Rechazar")) : h("span", { class: "soft" }, "No aplicable")),
      c.valido ? h("div", { class: "diff" }, c.diff.split("\n").map((l) => h("span", { class: "dl " + (l.startsWith("+++") || l.startsWith("---") ? "file" : l.startsWith("+") ? "add" : l.startsWith("-") ? "del" : l.startsWith("@@") ? "hunk" : "") }, l || " ")))
        : h("div", { class: "cambio-error" }, "Descartado automáticamente: " + c.error));
  }
  $("#v-rev-aplicar").addEventListener("click", async () => {
    if (S.revision && S.revision.compartido && !(await AP.confirmar({ titulo: "Carpeta compartida", texto: "Vas a escribir en una carpeta compartida de otra persona:\n" + S.revision.destino_contexto + "\n\n¿Aplicar los cambios aceptados?", aceptar: "Aplicar cambios", peligro: true }))) return;
    const aceptados = Object.entries(UI.decisiones).filter(([, v]) => v === "si").map(([k]) => k);
    $("#v-rev-aplicar").disabled = true;
    try { await api("POST", "/api/revision/aplicar", { aceptados }); } catch (e) { avisarError(e); }
  });
  $("#v-rev-cerrar").addEventListener("click", async () => {
    const rev = S.revision;
    if (rev && !rev.aplicado && rev.estado === "lista" && Object.values(UI.decisiones).some((v) => v === "si") && !(await AP.confirmar({ titulo: "Cambios sin aplicar", texto: "Hay cambios aceptados que todavía no se han aplicado. ¿Cerrar y descartarlos?", aceptar: "Descartar y cerrar", cancelar: "Volver", peligro: true }))) return;
    try { const r = await api("POST", "/api/revision/cerrar", {}); if (r && r.ok === false) $("#v-rev-pub") && $("#v-rev-pub").scrollIntoView({ block: "center" }); } catch (e) { avisarError(e); }
  });

  // ------------------------------------------------------------ AJUSTES
  // Los modelos se eligen con un selector (Ligero = haiku, Potente = sonnet: los valores de siempre). Si la configuración trae otro valor (p. ej. opus), se conserva como opción.
  AP.fijarModelo = (sel, valor) => {
    if (!sel) return;
    const v = String(valor || "haiku");
    if (![...sel.options].some((o) => o.value === v)) sel.append(h("option", { value: v }, "Otro: " + v));
    sel.value = v;
  };
  const dlg = $("#d-ajustes");
  $("#b-ajustes").addEventListener("click", async () => {
    $("#s-error").hidden = true;
    const f = $("#f-ajustes");
    try {
      const [info, disp] = await Promise.all([api("GET", "/api/info"), api("GET", "/api/dispositivos")]);
      const c = info.config;
      f.raiz_proyectos.value = c.raiz_proyectos; f.whisper_modelo.value = c.whisper_modelo;
      f.min_palabras_analisis.value = c.min_palabras_analisis; f.esfuerzo.value = c.esfuerzo;
      f.excluir_captura.checked = c.excluir_captura; f.detectar_llamadas.checked = c.detectar_llamadas; f.filtrar_eco.checked = c.filtrar_eco !== false;
      ["digest", "periodico", "contradicciones_confirmar", "final"].forEach((k) => AP.fijarModelo(f["m_" + k], c.modelos[k]));
      if (AP.hooks.ajustesAbrir) AP.hooks.ajustesAbrir(info, f);   // ajustes.js: secciones, solo local y registro de envíos
      const llenar = (sel, lista, actual, defecto) => {
        sel.replaceChildren(h("option", { value: "" }, "Predeterminado del sistema"));
        lista.forEach((d) => sel.append(h("option", { value: d.indice }, d.nombre + (d.indice === defecto ? " (predeterminado)" : ""))));
        sel.value = actual == null ? "" : String(actual);
      };
      llenar($("#s-mic"), disp.entradas, c.dispositivo_mic, disp.mic_defecto);
      llenar($("#s-sis"), disp.salidas, c.dispositivo_sistema, disp.sistema_defecto);
      if (disp.error) { $("#s-error").textContent = disp.error; $("#s-error").hidden = false; }
    } catch (e) { $("#s-error").textContent = e.message; $("#s-error").hidden = false; }
    dlg.showModal();
  });
  $("#s-cancelar").addEventListener("click", () => dlg.close());
  $("#f-ajustes").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const f = $("#f-ajustes");
    const idx = (v) => (v === "" ? null : Number(v));
    const cambios = { raiz_proyectos: f.raiz_proyectos.value.trim(), whisper_modelo: f.whisper_modelo.value, esfuerzo: f.esfuerzo.value,
      min_palabras_analisis: Number(f.min_palabras_analisis.value), excluir_captura: f.excluir_captura.checked,
      detectar_llamadas: f.detectar_llamadas.checked, filtrar_eco: f.filtrar_eco.checked, dispositivo_mic: idx(f.dispositivo_mic.value), dispositivo_sistema: idx(f.dispositivo_sistema.value),
      modelos: { digest: f.m_digest.value, periodico: f.m_periodico.value, contradicciones_confirmar: f.m_contradicciones_confirmar.value, final: f.m_final.value } };
    if (AP.hooks.ajustesGuardar) Object.assign(cambios, AP.hooks.ajustesGuardar(f));
    try {
      const r = await api("PUT", "/api/config", cambios);
      pintarCaptura(r.config.excluir_captura);
      dlg.close();
      cargarProyectos();
    } catch (e) { $("#s-error").textContent = e.message; $("#s-error").hidden = false; }
  });
  function pintarCaptura(on) { const b = $("#b-captura"); b.hidden = false; b.setAttribute("aria-pressed", String(!!on)); b.classList.toggle("off", !on); b.textContent = on ? "Oculta al compartir" : "Visible al compartir"; if (UI.info) UI.info.config.excluir_captura = !!on; }
  $("#b-captura").addEventListener("click", async () => {
    const nuevo = $("#b-captura").getAttribute("aria-pressed") !== "true";
    try { const r = await api("PUT", "/api/config", { excluir_captura: nuevo }); pintarCaptura(r.config.excluir_captura); } catch (e) { alerta(e); }
  });

  // ------------------------------------------------------------ WebSocket
  let ws, reintento = 0;
  function conectar() {
    ws = new WebSocket(`ws://${location.host}/ws?t=${encodeURIComponent(TOKEN)}`);
    ws.onopen = () => { reintento = 0; };
    ws.onclose = () => { setTimeout(conectar, Math.min(5000, 500 * ++reintento)); };
    ws.onmessage = (m) => manejar(JSON.parse(m.data));
  }
  function mezclar(d) {
    for (const k of ["estado", "sesion", "t", "analisis", "transcripcion", "consumo", "digest", "avisos", "revision", "simulacion", "objetivos", "checks", "captura", "equipo"]) if (k in d) S[k] = d[k];
  }
  let vistaAntes = null;
  function repintar() {
    const v = vista();
    if (v === "reunion") { pintarEstadoReunion(); pintarChecksReunion(); }
    else if (!$("#r-drawer").hidden) cerrarCajon();
    if (v === "revision") pintarRevision();
    if (v === "inicio" && vistaAntes !== "inicio") { if (AP.hooks.alVolverAInicio) AP.hooks.alVolverAInicio(); validarInicio(); cargarProyectos(); }
    vistaAntes = v;
  }
  function manejar(d) {
    if (AP.normalizar) AP.normalizar(d);   // nombres de los agentes (nombres.js)
    if (AP.hooks.evento) AP.hooks.evento(d);   // tareas reales, traza y enlaces visuales (agentes.js)
    switch (d.tipo) {
      case "snapshot":
        mezclar(d);
        S.segmentos = d.segmentos || []; S.tarjetas = d.tarjetas || []; S.resumen_acumulado = d.resumen_acumulado || "";
        $("#r-notas").value = d.notas || "";
        pintarTrans(); pintarInsights(); pintarObjetivos(); pintarCaptura(UI.info ? UI.info.config.excluir_captura : true);
        repintar(); break;
      case "estado": mezclar(d); repintar(); break;
      case "tick": mezclar(d); if (S.estado === "grabando" || S.estado === "pausada") { $("#r-reloj").textContent = AP.hms ? AP.hms(S.t) : mmss(S.t); pintarEstadoReunion(); } break;
      case "segmento": añadirSegmento(d); break;
      case "segmento_eco": (d.cambios || []).forEach((c) => {   // un Micro al que la llegada de su pareja de Reunión le quita (más) eco
        const s = S.segmentos.find((x) => x.id === c.id); if (s) s.texto = c.texto;
        const el = $(`#r-trans [data-id="${c.id}"]`);
        if (el) { if (c.texto) { const x = $(".x", el); if (x) x.textContent = c.texto; } else el.remove(); }
      }); break;
      case "nivel": ponerNivel(d.fuente, d.db); break;
      case "tarjetas": if (d.todas) S.tarjetas = d.todas; else S.tarjetas.push(...d.nuevas); S.resumen_acumulado = d.resumen || S.resumen_acumulado; if (d.objetivos) S.objetivos = d.objetivos; if (d.checks) { S.checks = d.checks; pintarChecksReunion(); } pintarInsights(); pintarObjetivos(); break;
      case "checks": S.checks = d.checks || []; pintarChecksReunion(); break;
      case "consumo": S.consumo = d; pie(); break;
      case "analisis": if (d.fase === "ok" || d.fase === "error") $("#r-analizar").disabled = false; break;
      case "sim_fin": S.avisos = [...S.avisos.filter((a) => !a.startsWith("Fin de la simulación")), "Fin de la simulación: ya no llegan más líneas."]; pintarEstadoReunion(); break;
    }
  }

  Object.assign(AP, { S, UI, h, $, $$, api, safe, elegirProyecto, cargarProyectos, pintarContexto, mmss, kfmt, md, GRUPOS, crearChecks, tarjetaCambio, seccionPublicacion, alerta, reiniciarReunion,
    repintar: () => repintar(), pintarEstadoReunion: () => pintarEstadoReunion(), hms: (s) => { s = Math.max(0, Math.floor(s || 0)); return `${String(Math.floor(s / 3600)).padStart(2, "0")}:${mmss(s % 3600)}`; } });

  // ------------------------------------------------------------ arranque
  (async function init() {
    try {
      UI.info = await api("GET", "/api/info");
      S.simulacion = UI.info.simulacion;
      pintarCaptura(UI.info.config.excluir_captura);
      UI.sel = undefined;
      const guardado = safe(() => localStorage.getItem("apuntes_proy"), null);
      if (guardado) UI.sel = guardado === "__bandeja__" ? null : guardado;
    } catch (e) { document.body.prepend(h("div", { class: "error" }, "No se pudo conectar con el servidor local: " + e.message)); }
    vista();
    // El snapshot debe llegar con todos los módulos ya enganchados a AP.hooks.evento: /api/info puede responder antes de que carguen.
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", conectar);
    else conectar();
  })();
})();
