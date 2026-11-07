"use strict";
/* Apuntes: «Sesión», la línea de tiempo de la propia reunión (distinta del Gantt del proyecto).
   Eje desde 00:00 hasta el minuto actual (se reescala con la reunión) y carriles: Temas (barras por tramo), Objetivos (una barra
   por objetivo, de su primera a su última evidencia), Insights (decisión, pendiente, pregunta, riesgo, contradicción, idea) y Tú
   (comentarios, preguntas e ideas propios). Solo pinta datos reales: sin dato no hay marca. Los marcadores que caen en el mismo
   sitio se apilan en dos filas y, si no caben, se agrupan con contador: nunca se solapan (se mide con getBoundingClientRect).
   El componente (`window.GanttSesion`) no depende de la app; al final se engancha a la pantalla de reunión y a la de revisión. */
(() => {
  const SVGNS = "http://www.w3.org/2000/svg";
  const sv = (tag, attrs = {}, ...hijos) => { const e = document.createElementNS(SVGNS, tag); for (const [k, v] of Object.entries(attrs)) if (v != null && v !== false) e.setAttribute(k, v); hijos.forEach((c) => c && e.append(c)); return e; };
  const el = (tag, attrs = {}, ...hijos) => {
    const e = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (v == null || v === false) continue;
      if (k.startsWith("on") && typeof v === "function") e.addEventListener(k.slice(2), v);
      else if (k === "class") e.className = v;
      else e.setAttribute(k, v === true ? "" : v);
    }
    hijos.flat().forEach((c) => c != null && c !== false && e.append(c.nodeType ? c : document.createTextNode(String(c))));
    return e;
  };
  const reducido = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const mmss = (s) => { s = Math.max(0, Math.floor(s || 0)); const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), x = s % 60; return (h ? h + ":" + String(m).padStart(2, "0") : String(m).padStart(2, "0")) + ":" + String(x).padStart(2, "0"); };

  // Tipos de marcador: etiqueta, icono (iconos.js, 16×16) y lane. Cada tipo lleva su color (app.css, --t-*) además de su icono y su etiqueta
  const TIPOS = {
    decision:      { etq: "Decisión", forma: "decision", lane: "ins" },
    pendiente:     { etq: "Pendiente", forma: "pendiente", lane: "ins" },
    pregunta:      { etq: "Pregunta", forma: "pregunta", lane: "ins" },
    riesgo:        { etq: "Riesgo", forma: "riesgo", lane: "ins" },
    contradiccion: { etq: "Contradicción", forma: "contradiccion", lane: "ins" },
    regla:         { etq: "Regla", forma: "regla", lane: "ins" },
    idea:          { etq: "Idea", forma: "idea", lane: "ins" },
    tu:            { etq: "Tú", forma: "tu", lane: "tu" },
  };
  const ORDEN_FILTRO = ["decision", "pendiente", "pregunta", "riesgo", "contradiccion", "regla", "idea", "tu"];
  const CAT_A_TIPO = { "decisión": "decision", "pendiente": "pendiente", "pregunta": "pregunta", "riesgo": "riesgo", "contradicción": "contradiccion", "regla": "regla", "idea": "idea" };
  const TU_ETQ = { comentario: "Comentario", pregunta: "Pregunta", idea: "Idea" };
  const TU_FORMA = { comentario: "respuesta", pregunta: "pregunta", idea: "idea" };

  // el icono viene de iconos.js; la página de prueba del Gantt (sin la app) usa una caja vacía del mismo tamaño para que las medidas sean las reales
  function forma(nombre) {
    if (window.AP && window.AP.icono) return window.AP.icono(nombre, "sb-ic");
    const s = sv("svg", { viewBox: "0 0 24 24", "aria-hidden": "true", focusable: "false", class: "ic sb-ic" });
    return s;
  }

  // ---------------------------------------------------------------- medidas (px)
  const M = { marca: 16, gap: 2, grupo: 24, filasIns: 2, relleno_der: 24, etiqueta: 72, paso_min: 56 };

  /** Reparte marcadores ordenados por x en `filas` filas sin solapes: si no caben, se agrupan (grupo = {items, left, fila}). */
  function disponerMarcadores(items, filas) {
    const fin = new Array(filas).fill(-Infinity);
    const ult = new Array(filas).fill(null);
    const salida = [];
    for (const it of items) {
      const left = Math.max(0, it.x - M.marca / 2);
      let f = -1;
      for (let r = 0; r < filas; r++) if (left >= fin[r] + M.gap) { f = r; break; }
      if (f >= 0) {
        const g = { items: [it], left, fila: f, ancho: M.marca };
        salida.push(g); fin[f] = left + M.marca; ult[f] = g;
        continue;
      }
      // no cabe: se une al último grupo de la fila que antes termina (el que más cerca queda)
      let mejor = 0;
      for (let r = 1; r < filas; r++) if (fin[r] < fin[mejor]) mejor = r;
      const g = ult[mejor];
      g.items.push(it);
      g.ancho = M.grupo;
      fin[mejor] = g.left + g.ancho;
    }
    return salida;
  }

  /** Reparte intervalos (barras de objetivos) en filas sin solapes. */
  function disponerBarras(barras) {
    const fin = [];
    for (const b of barras) {
      let f = fin.findIndex((e) => b.left >= e + M.gap);
      if (f < 0) { f = fin.length; fin.push(-Infinity); }
      b.fila = f; fin[f] = b.left + b.ancho;
    }
    return fin.length;
  }

  const PASOS = [30, 60, 120, 300, 600, 900, 1800, 3600, 7200];

  function montar(raiz, op = {}) {
    const estado = { datos: { t: 0, vivo: true, temas: [], objetivos: [], tarjetas: [], entradas: [], marcas: [] }, filtros: new Set(ORDEN_FILTRO),
      plegado: !!op.plegado, pool: new Map(), primera: true, pendiente: false, tipAnc: null };
    raiz.classList.add("sesion-banda");
    if (op.estatica) raiz.classList.add("sin-mov");

    // ---- cabecera
    const btnPlegar = el("button", { type: "button", class: "sb-plegar", "aria-expanded": String(!estado.plegado), onclick: () => ponerPlegado(!estado.plegado) },
      el("span", { class: "t-label" }, "Sesión"));
    const rango = el("span", { class: "sb-rango t-meta" }, "00:00");
    const filtros = el("div", { class: "sb-filtros", role: "group", "aria-label": "Mostrar por tipo" },
      ORDEN_FILTRO.map((k) => {
        const b = el("button", { type: "button", class: "sb-filtro t-meta", "data-tipo": k, "aria-pressed": "true", title: "Mostrar u ocultar: " + TIPOS[k].etq,
          onclick: () => { if (estado.filtros.has(k)) estado.filtros.delete(k); else estado.filtros.add(k); b.setAttribute("aria-pressed", String(estado.filtros.has(k))); programar(); op.alFiltrar && op.alFiltrar([...estado.filtros]); } },
          forma(TIPOS[k].forma), el("span", { class: "sb-f-t" }, TIPOS[k].etq));
        return b;
      }));
    const cab = el("div", { class: "sb-cab" }, btnPlegar, rango, filtros);

    // ---- carriles
    const lane = (id, etq, extra = "") => {
      const plot = el("div", { class: "sb-plot", "data-lane": id });
      const fila = el("div", { class: "sb-lane sb-lane-" + id + " " + extra, "data-lane": id }, el("div", { class: "sb-etq t-label" }, etq), plot);
      return { fila, plot };
    };
    const L = { eje: lane("eje", ""), temas: lane("temas", "Temas"), obj: lane("obj", "Objetivos"), ins: lane("ins", "Avisos"), tu: lane("tu", "Tú") };
    const sobre = el("div", { class: "sb-sobre", "aria-hidden": "true" });
    const ahora = el("div", { class: "sb-ahora" }, el("span", { class: "sb-ahora-t t-label" }, "ahora"));
    sobre.append(ahora);
    const cuerpo = el("div", { class: "sb-cuerpo" }, L.eje.fila, L.temas.fila, L.obj.fila, L.ins.fila, L.tu.fila, sobre);
    const tip = el("div", { class: "sb-tip t-meta", role: "tooltip", hidden: true });
    raiz.replaceChildren(cab, cuerpo, tip);
    cuerpo.hidden = estado.plegado;
    raiz.dataset.plegado = String(estado.plegado);

    function ponerPlegado(p) {
      estado.plegado = p;
      cuerpo.hidden = p;
      raiz.dataset.plegado = String(p);
      btnPlegar.setAttribute("aria-expanded", String(!p));
      op.alPlegar && op.alPlegar(p);
      if (!p) programar();
    }

    // ---- tooltip (hover y foco): el texto completo
    function mostrarTip(nodo, texto) {
      tip.textContent = texto; tip.hidden = false;
      const R = raiz.getBoundingClientRect(), n = nodo.getBoundingClientRect();
      tip.style.left = "0px"; tip.style.top = "0px";
      const w = tip.offsetWidth, h = tip.offsetHeight;
      let x = n.left + n.width / 2 - R.left - w / 2;
      x = Math.max(4, Math.min(x, R.width - w - 4));
      let y = n.top - R.top - h - 6;
      if (y < 0) y = n.bottom - R.top + 6;
      tip.style.left = Math.round(x) + "px"; tip.style.top = Math.round(y) + "px";
      estado.tipAnc = nodo;
    }
    function ocultarTip(nodo) { if (!nodo || estado.tipAnc === nodo) { tip.hidden = true; estado.tipAnc = null; } }

    // ---- elementos con clave (se reutilizan; los nuevos entran con un fundido corto)
    function obtener(clave, crear) {
      let e = estado.pool.get(clave);
      if (!e) { e = crear(); e._nuevo = true; estado.pool.set(clave, e); }
      e._visto = true;
      return e;
    }

    function tiempoMax(d) {
      if (d.vivo) return Math.max(d.t || 0, 120);
      const fin = Math.max(d.t || 0, ...d.tarjetas.map((x) => x.t_seg || 0), ...d.entradas.map((x) => x.t_seg || 0), ...d.temas.map((x) => x.hasta_t || 0), 60);
      return fin;
    }

    function fusionarTemas(temas) {
      const out = [];
      for (const t of [...temas].filter((x) => x.titulo).sort((a, b) => a.desde_t - b.desde_t)) {
        const u = out[out.length - 1];
        if (u && u.titulo.trim().toLowerCase() === t.titulo.trim().toLowerCase()) { u.hasta_t = Math.max(u.hasta_t, t.hasta_t); continue; }
        out.push({ titulo: t.titulo, desde_t: t.desde_t, hasta_t: t.hasta_t });
      }
      return out;
    }
    // Los temas no se solapan nunca: cada uno empieza, como pronto, donde acaba el anterior (los tramos de varios perfiles empiezan a la vez, p. ej. en 00:05).
    // Si alguno queda con ancho casi nulo, la barra la ocupa el más reciente y el anterior pasa a su tooltip: no se pierde ningún dato.
    function disponerTemas(temas, X) {
      const items = []; let cursor = 0;
      for (const t of temas) {
        const ini = Math.max(t.desde_t, cursor), fin = Math.max(t.hasta_t, ini);
        items.push({ titulo: t.titulo, desde_t: ini, hasta_t: fin, ocultos: [] });
        cursor = fin;
      }
      items.forEach((a, i) => { const b = items[i + 1]; if (b) a.hasta_t = b.desde_t; });   // sin huecos entre barras
      const out = []; let pend = [];
      items.forEach((it, i) => {
        if (X(it.hasta_t) - X(it.desde_t) < 28 && i < items.length - 1) { pend.push(it); return; }
        if (pend.length) { it.ocultos = pend; it.desde_t = pend[0].desde_t; pend = []; }
        out.push(it);
      });
      return out;
    }

    function itemsMarcadores(d) {
      const ins = [], tu = [];
      for (const t of d.tarjetas) {
        if (t.t_seg == null) continue;
        let tipo = CAT_A_TIPO[t.categoria];
        if (!tipo) continue;
        if (!estado.filtros.has(tipo)) continue;
        const etq = t.estado === "posible" ? "Posible contradicción" : TIPOS[tipo].etq;
        ins.push({ clave: "t:" + t.id, t: t.t_seg, tipo, etq, texto: t.texto, ref: { t: t.t_seg, tarjeta: t.id }, forma: TIPOS[tipo].forma, posible: t.estado === "posible" });
      }
      if (estado.filtros.has("tu")) for (const e of d.entradas) {
        if (e.t_seg == null) continue;
        tu.push({ clave: "u:" + e.id, t: e.t_seg, tipo: "tu", sub: e.tipo, etq: TU_ETQ[e.tipo] + " (tú)", texto: e.texto, ref: { t: e.t_seg, entrada: e.id }, forma: TU_FORMA[e.tipo] });
      }
      const ord = (a, b) => a.t - b.t || String(a.clave).localeCompare(String(b.clave));
      return { ins: ins.sort(ord), tu: tu.sort(ord) };
    }

    function pintar() {
      estado.pendiente = false;
      const d = estado.datos;
      rango.textContent = d.vivo ? `00:00 – ${mmss(d.t)}` : `00:00 – ${mmss(tiempoMax(d))}`;
      if (estado.plegado) return;
      const plot = L.temas.plot;
      const W = plot.clientWidth - M.relleno_der;
      if (W <= 40) return;
      const tmax = tiempoMax(d);
      const X = (t) => Math.max(0, Math.min(1, t / tmax)) * W;
      estado.pool.forEach((e) => { e._visto = false; });
      const animar = !estado.primera && !reducido() && !raiz.classList.contains("sin-mov");

      // eje: marcas de tiempo y análisis
      const paso = PASOS.find((p) => (p / tmax) * W >= M.paso_min) || PASOS[PASOS.length - 1];
      const ejeNodos = [];
      for (let t = 0; t <= tmax + 0.001; t += paso) {
        const n = obtener("e:" + t, () => el("span", { class: "sb-tick t-label" }, mmss(t)));
        n.style.left = X(t) + "px"; ejeNodos.push(n);
      }
      for (const m of d.marcas || []) {
        if (m.t == null) continue;
        const txt = `Análisis ${m.n}${m.motivo ? " · " + m.motivo : ""} · ${mmss(m.t)}`;
        const n = obtener("a:" + m.n, () => el("i", { class: "sb-analisis" }));
        n.style.left = X(m.t) + "px"; n.title = txt; n.setAttribute("aria-hidden", "true");
        ejeNodos.push(n);
      }
      // temas
      const temas = disponerTemas(fusionarTemas(d.temas || []), X);
      const temasNodos = temas.map((t, i) => {
        const n = obtener("m:" + i, () => el("div", { class: "sb-tema" }, el("span", { class: "sb-tema-t t-meta" })));
        const l = X(t.desde_t), a = Math.max(4, X(t.hasta_t) - l - 1);
        n.style.left = l + "px"; n.style.width = a + "px"; n.dataset.alt = String(i % 2);
        n.firstChild.textContent = t.titulo; n.title = [...t.ocultos, t].map((x) => `${mmss(x.desde_t)}–${mmss(x.hasta_t)} · ${x.titulo}`).join("\n");
        n._ref = { t: t.desde_t };
        return n;
      });
      // objetivos: una barra por objetivo con evidencia, de la primera a la última
      const objs = (d.objetivos || []).filter((o) => !o.sugerido);
      const barras = objs.filter((o) => o.t_seg != null && o.estado !== "sin_tratar").map((o) => {
        const t0 = o.t_primero != null ? o.t_primero : o.t_seg;
        const l = X(Math.min(t0, o.t_seg)), a = Math.max(6, X(Math.max(t0, o.t_seg)) - l);
        return { o, left: l, ancho: a, t0: Math.min(t0, o.t_seg) };
      }).sort((a, b) => a.left - b.left || a.o.n - b.o.n);
      const filasObj = disponerBarras(barras);
      const nFilasObj = Math.max(1, objs.length);
      const pitch = nFilasObj <= 4 ? 8 : nFilasObj <= 8 ? 7 : 4;
      L.obj.fila.style.setProperty("--filas", String(Math.max(1, Math.min(nFilasObj, 20))));
      L.obj.fila.style.setProperty("--pitch", pitch + "px");
      const objNodos = barras.map((b) => {
        const n = obtener("o:" + b.o.n, () => el("button", { type: "button", class: "sb-obj" }));
        n.style.left = b.left + "px"; n.style.width = b.ancho + "px"; n.style.top = (b.fila * pitch + 1) + "px"; n.style.height = (pitch - 2) + "px";
        n.dataset.estado = b.o.estado;
        const txt = `Objetivo ${b.o.n}: ${b.o.texto} · ${b.o.estado === "cubierto" ? "cubierto" : "parcial"} · de ${mmss(b.t0)} a ${mmss(b.o.t_seg)}`;
        n.dataset.tip = txt; n.setAttribute("aria-label", txt);
        n._ref = { t: b.o.t_seg, objetivo: b.o.n };
        return n;
      });
      // marcadores
      const mk = itemsMarcadores(d);
      const colocar = (lista, filas, cont, rowTop) => {
        const g = disponerMarcadores(lista.map((it) => ({ ...it, x: X(it.t) })), filas);
        return g.map((grupo) => {
          const primero = grupo.items[0];
          const clave = "g:" + primero.clave;
          const n = obtener(clave, () => el("button", { type: "button", class: "sb-m" }));
          n.style.left = grupo.left + "px"; n.style.top = (grupo.fila * (M.marca + M.gap) + rowTop) + "px";
          n.style.width = grupo.ancho + "px";
          const grupal = grupo.items.length > 1;
          n.classList.toggle("grupo", grupal);
          n.dataset.tipo = primero.tipo; n.dataset.sub = primero.sub || "";
          n.classList.toggle("posible", !!primero.posible);
          n._items = grupo.items;
          const firma = grupo.items.map((x) => x.clave).join("|");
          if (n._firma !== firma) {
            n._firma = firma;
            if (grupal) {
              n.replaceChildren(el("span", { class: "sb-n" }, grupo.items.length > 99 ? "99+" : String(grupo.items.length)));
              const a = grupo.items[0].t, b = grupo.items[grupo.items.length - 1].t;
              n.setAttribute("aria-label", `${grupo.items.length} marcas entre ${mmss(a)} y ${mmss(b)}`);
              n.dataset.tip = grupo.items.slice(0, 6).map((x) => `[${mmss(x.t)}] ${x.etq}: ${x.texto}`).join("\n") + (grupo.items.length > 6 ? `\n… y ${grupo.items.length - 6} más` : "");
            } else {
              n.replaceChildren(forma(primero.forma));
              n.setAttribute("aria-label", `${primero.etq} ${mmss(primero.t)}: ${primero.texto}`);
              n.dataset.tip = `[${mmss(primero.t)}] ${primero.etq}: ${primero.texto}`;
            }
          }
          n._ref = { ...primero.ref };
          return n;
        });
      };
      const insNodos = colocar(mk.ins, M.filasIns, L.ins.plot, 1);
      const tuNodos = colocar(mk.tu, 1, L.tu.plot, 1);

      // ahora
      ahora.style.left = (M.etiqueta + X(d.t || 0)) + "px";
      ahora.hidden = !d.vivo;

      // montar nodos en su carril y retirar los que ya no están
      const ponerEn = (plot, nodos) => { let ref = plot.firstChild; for (const n of nodos) { if (n === ref) ref = ref.nextSibling; else plot.insertBefore(n, ref); } while (ref) { const s = ref.nextSibling; ref.remove(); ref = s; } };
      ponerEn(L.eje.plot, ejeNodos); ponerEn(L.temas.plot, temasNodos); ponerEn(L.obj.plot, objNodos);
      ponerEn(L.ins.plot, insNodos); ponerEn(L.tu.plot, tuNodos);
      estado.pool.forEach((e, k) => { if (!e._visto) estado.pool.delete(k); });
      for (const n of [...temasNodos, ...objNodos, ...insNodos, ...tuNodos]) {
        if (n._nuevo) {
          n._nuevo = false;
          if (animar) n.animate([{ opacity: 0 }, { opacity: 1 }], { duration: 180, easing: "cubic-bezier(.16,1,.3,1)" });
        }
      }
      // tabindex de recorrido: uno por carril
      for (const lista of [objNodos, insNodos, tuNodos, temasNodos]) lista.forEach((n, i) => { n.tabIndex = i === (n.parentNode._foco || 0) ? 0 : -1; if (!n.matches("button")) n.tabIndex = -1; });
      estado.primera = false;
    }

    function programar() { if (estado.pendiente) return; estado.pendiente = true; requestAnimationFrame(pintar); }
    const ro = new ResizeObserver(() => programar());
    ro.observe(cuerpo);

    // ---- interacción: hover, foco, clic o Enter y flechas dentro del carril
    const nodoDe = (ev) => ev.target.closest && ev.target.closest(".sb-m, .sb-obj, .sb-tema");
    raiz.addEventListener("mouseover", (ev) => { const n = nodoDe(ev); if (n && n.dataset.tip) mostrarTip(n, n.dataset.tip); });
    raiz.addEventListener("mouseout", (ev) => { const n = nodoDe(ev); if (n) ocultarTip(n); });
    raiz.addEventListener("focusin", (ev) => { const n = nodoDe(ev); if (n && n.dataset.tip) mostrarTip(n, n.dataset.tip); });
    raiz.addEventListener("focusout", (ev) => { const n = nodoDe(ev); if (n) ocultarTip(n); });
    raiz.addEventListener("click", (ev) => {
      const n = nodoDe(ev);
      if (!n || !op.alIr) return;
      if (n.classList.contains("sb-m") && n._items) op.alIr({ ...n._items[0].ref, grupo: n._items.length > 1 });
      else if (n._ref) op.alIr({ ...n._ref });
    });
    raiz.addEventListener("keydown", (ev) => {
      if (ev.key === "Escape") { tip.hidden = true; return; }
      const n = nodoDe(ev);
      if (!n || !n.matches("button")) return;
      const plot = n.parentNode, hermanos = [...plot.querySelectorAll("button")];
      let i = hermanos.indexOf(n);
      if (ev.key === "ArrowRight") i = Math.min(hermanos.length - 1, i + 1);
      else if (ev.key === "ArrowLeft") i = Math.max(0, i - 1);
      else if (ev.key === "Home") i = 0;
      else if (ev.key === "End") i = hermanos.length - 1;
      else return;
      ev.preventDefault();
      hermanos.forEach((h) => { h.tabIndex = -1; });
      hermanos[i].tabIndex = 0; plot._foco = i; hermanos[i].focus();
    });

    return {
      actualizar(datos) { Object.assign(estado.datos, datos); programar(); },
      pintarYa: pintar,
      plegar: ponerPlegado,
      get plegado() { return estado.plegado; },
      filtros: () => [...estado.filtros],
      ponerFiltros(lista) {
        estado.filtros = new Set(lista.filter((k) => TIPOS[k]));
        filtros.querySelectorAll(".sb-filtro").forEach((b) => b.setAttribute("aria-pressed", String(estado.filtros.has(b.dataset.tipo))));
        programar();
      },
      raiz, medir: () => ({ plegado: estado.plegado }),
    };
  }

  window.GanttSesion = { montar, disponerMarcadores, disponerBarras, M, TIPOS };

  // ---------------------------------------------------------------- enganche con la app (reunión y revisión)
  const AP = window.AP;
  if (!AP) return;
  const { S, $, $$ } = AP;
  const guardar = (k, v) => { try { localStorage.setItem(k, v); } catch { /* sin almacenamiento */ } };
  const leer = (k, d) => { try { const v = localStorage.getItem(k); return v == null ? d : v; } catch { return d; } };

  function desdeApp(vivo) {
    const trz = (AP.traza || []).filter((x) => x.fila === "analisis" && x.hasta_t != null);
    const t = vivo ? (S.t || 0) : ((S.sesion && S.sesion.duracion_s) || S.t || 0);
    return { t, vivo, temas: S.temas || [], objetivos: S.objetivos || [], tarjetas: S.tarjetas || [], entradas: S.entradas || [],
      marcas: trz.map((x) => ({ n: x.n, t: x.hasta_t, motivo: x.motivo || "" })) };
  }

  /** Lleva a la tarjeta (o fila de objetivo / anotación) y a la línea de transcripción, igual que el chip de minuto. */
  function ir(ref) {
    if (ref.t != null && AP.hooks.irAlMinuto) AP.hooks.irAlMinuto(ref.t);
    let destino = null;
    if (ref.tarjeta) destino = document.querySelector(`#r-insights .tarj[data-id="${CSS.escape(ref.tarjeta)}"], #av-fijos .tarj[data-id="${CSS.escape(ref.tarjeta)}"], #av-discretos .tarj[data-id="${CSS.escape(ref.tarjeta)}"]`);
    else if (ref.entrada) destino = document.querySelector(`#r-tuyas [data-id="${CSS.escape(ref.entrada)}"]`);
    else if (ref.objetivo != null) destino = document.querySelector(`#r-obj-lista .obj[data-n="${ref.objetivo}"]`);
    if (!destino) return;
    const pn = destino.closest(".tab-panel");   // el destino puede estar en otra pestaña de la columna derecha: se muestra antes de llevar la vista a él
    if (pn && pn.dataset.panel && AP.pestana) AP.pestana(pn.dataset.panel);
    destino.scrollIntoView({ block: "nearest", behavior: reducido() ? "auto" : "smooth" });
    destino.classList.add("barra");
    setTimeout(() => { destino.classList.add("barra-fuera"); setTimeout(() => destino.classList.remove("barra", "barra-fuera"), 400); }, 1600);
    const foco = destino.querySelector("button");
    if (foco && document.activeElement && document.activeElement.closest(".sesion-banda")) { /* el foco se queda en la banda */ }
  }

  let banda = null, ctl = null, rev = null;
  function asegurar() {
    if (ctl) return;
    const vista = $("#v-reunion");
    if (!vista) return;
    banda = el("section", { id: "sesion-banda", "aria-label": "Sesión: línea de tiempo de la reunión" });
    const pestana = $("#tab-sesion");
    if (pestana) pestana.append(banda); else vista.insertBefore(banda, vista.querySelector(".reunion-grid"));   // la pestaña «Sesión» de la columna derecha
    ctl = montar(banda, { plegado: leer("apuntes_sesion_plegado", "0") === "1", alIr: ir,
      alPlegar: (p) => guardar("apuntes_sesion_plegado", p ? "1" : "0"),
      alFiltrar: (f) => guardar("apuntes_sesion_filtros", f.join(",")) });
    const f = leer("apuntes_sesion_filtros", "");
    if (f) ctl.ponerFiltros(f.split(","));
    AP.sesionBanda = ctl;
  }
  const refrescar = () => { asegurar(); if (ctl) ctl.actualizar(desdeApp(true)); if (rev && rev.raiz.isConnected) rev.actualizar(desdeApp(false)); };
  AP.refrescarSesion = refrescar;

  // Revisión: el Gantt de la sesión completo, junto al resumen
  AP.montarSesionRevision = (cont) => {
    const sec = el("section", { id: "sesion-revision", "aria-label": "Sesión: línea de tiempo completa" });
    cont.append(sec);
    rev = montar(sec, { plegado: false, alIr: () => {} });
    rev.actualizar(desdeApp(false));
    return rev;
  };

  const previo = AP.hooks.evento;
  AP.hooks.evento = (d) => {
    if (previo) previo(d);
    switch (d.tipo) {
      case "snapshot": case "estado":
        for (const k of ["temas", "entradas", "consultas"]) if (k in d) S[k] = d[k];
        requestAnimationFrame(refrescar); break;
      case "tick": requestAnimationFrame(refrescar); break;
      case "tarjetas": if (d.temas) S.temas = d.temas; requestAnimationFrame(refrescar); break;
      case "entradas": S.entradas = d.entradas || []; requestAnimationFrame(refrescar); break;
      case "objetivos": S.objetivos = d.objetivos || []; requestAnimationFrame(refrescar); break;
      case "traza": requestAnimationFrame(refrescar); break;
    }
  };
  const reiniciar = AP.hooks.reiniciar;
  AP.hooks.reiniciar = () => { if (reiniciar) reiniciar(); S.temas = []; S.entradas = []; S.consultas = []; if (ctl) { ctl.actualizar({ t: 0, temas: [], objetivos: [], tarjetas: [], entradas: [], marcas: [] }); } };
  if (document.readyState !== "loading") asegurar(); else document.addEventListener("DOMContentLoaded", asegurar);
})();
