"use strict";
/* Apuntes: el asesor en directo. Carril «Ahora» arriba de la reunión (y arriba del panel derecho en Modo reunión) con la respuesta sugerida más reciente,
   grande y legible de un vistazo, y debajo los consejos del Estratega. Todo sale de datos reales del backend (evento `asesor`: respuestas, consejos y estado);
   «Profundizar» pide UNA llamada a sonnet y la casilla «Buscar también en la web» solo existe si `claude -p` lo permite y NUNCA viene marcada.
   Fijar y descartar no gastan nada. El texto siempre se ve entero (sin elipsis). Lo único que se mueve es el cronómetro de una llamada real. */
(() => {
  const AP = window.AP;
  if (!AP) return;
  const { S, h, $, api } = AP;
    const A = { respuestas: [], consejos: [], estado: null, web: new Map(), anteriores: false, plegado: false, crono: null };
  try { A.plegado = localStorage.getItem("apuntes_asesor_plegado") === "1"; } catch { /* sin almacenamiento */ }
    const kfmt = AP.kfmt || ((n) => String(n));
  const numId = (x) => Number(String(x.id).slice(1)) || 0;
  const irA = (seg) => AP.hooks.irAlMinuto && seg != null && AP.hooks.irAlMinuto(seg);
  const aSeg = (m) => { const p = String(m || "").split(":").map(Number); return p.length === 2 && p.every((x) => !Number.isNaN(x)) ? p[0] * 60 + p[1] : null; };
  const hoyMs = (hora) => { const [a, b, c] = String(hora || "").split(":").map(Number); if ([a, b, c].some(Number.isNaN)) return null; const d = new Date(); d.setHours(a, b, c, 0); return d.getTime(); };
  const crono = (ms) => { const s = Math.max(0, Math.floor(ms / 1000)); return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`; };
  const MODELO = { haiku: "Haiku", sonnet: "Sonnet", opus: "Opus", local: "Local, sin modelo" };
  const nombreModelo = (m) => { const k = Object.keys(MODELO).find((x) => String(m || "").toLowerCase().includes(x)); return k ? MODELO[k] : String(m || ""); };

  // icono + color + etiqueta, nunca solo color (el juego de iconos vive en iconos.js)
  const icono = (nombre, clase) => AP.icono(nombre, clase);

  // ------------------------------------------------------------ llamadas reales en curso (evento `tarea`)
  function enCurso(agentes) {
    const O = AP.O; if (!O) return null;
    for (const t of O.tareas.values()) if (agentes.includes(t.agente) && t.estado === "en_curso") return t;
    return null;
  }

  // ------------------------------------------------------------ piezas
  const chipMin = (minuto, t) => (minuto ? h("button", { type: "button", class: "min", "data-t": t == null ? aSeg(minuto) : t, title: "Ir a ese momento de la transcripción", onclick: () => irA(t == null ? aSeg(minuto) : t) }, minuto) : null);
  const CONF = { alta: "Confianza alta", media: "Confianza media", baja: "Confianza baja" };
  const chipConf = (c) => (c ? h("span", { class: "as-conf as-conf-" + c, title: "Cuánto se fía el modelo de que lo dicho es correcto según tus fuentes" }, CONF[c] || c) : null);

  function fuentes(citas) {
    if (!citas || !citas.length) return null;
    return h("div", { class: "as-fuentes t-meta" }, h("span", { class: "as-fuentes-t" }, "Fuentes"),
      ...citas.map((c) => {
        if (c.tipo === "reunion") return h("button", { type: "button", class: "min", title: "Lo dicho en esta reunión: ir a ese momento", onclick: () => irA(c.t_seg) }, "minuto " + c.minuto);
        return h("span", { class: "as-fuente" }, c.fuente, c.minuto ? ` · ${c.minuto}` : "");
      }));
  }

  function profundizado(e) {
    const p = e.profundizada;
    if (!p) return null;
    if (p.estado === "en_curso") return h("div", { class: "as-prof t-body", role: "status" }, `Profundizando con ${nombreModelo(p.modelo)}${p.web ? " y búsqueda web" : ""}…`);
    if (p.estado === "error") return h("div", { class: "as-prof as-error t-body", role: "alert" }, p.error || "No se pudo profundizar.");
    return h("div", { class: "as-prof" },
      h("div", { class: "t-label" }, `Profundizado · ${nombreModelo(p.modelo)} · ${p.web ? "con búsqueda web" : "sin web"}`, p.confianza ? ` · ${(CONF[p.confianza] || "").toLowerCase()}` : ""),
      h("ul", { class: "as-vin as-vin-prof" }, ...(p.vinetas || []).map((v) => h("li", {}, v))),
      fuentes(p.citas),
      p.web && p.web_urls && p.web_urls.length ? h("div", { class: "as-web t-meta" }, h("span", { class: "as-fuentes-t" }, "Web"), ...p.web_urls.map((w) => h("span", { class: "as-url", title: "Se muestra como texto: la aplicación no abre enlaces" }, (w.t ? w.t + " · " : "") + w.u))) : null);
  }

  function acciones(e, clase) {
    const fijado = clase === "respuesta" ? e.fijada : e.fijado;
    const p = e.profundizada, ocupado = p && p.estado === "en_curso";
    const web = A.estado && A.estado.web && A.estado.web.disponible === true;
    const caja = web ? h("label", { class: "as-web-caja t-meta", title: "Una búsqueda web con consultas genéricas: sin nombres del cliente, de personas ni importes. Nunca se hace sola" },
      h("input", { type: "checkbox", "data-accion": "web", "data-id": e.id, checked: A.web.get(e.id) ? true : null, disabled: ocupado ? true : null,
        onchange: (ev) => A.web.set(e.id, ev.target.checked) }), "Buscar también en la web") : null;
    return h("div", { class: "as-acc" },
      h("button", { type: "button", class: "btn btn-mini", "data-accion": "profundizar", "data-id": e.id, disabled: ocupado ? true : null,
        title: "UNA llamada a sonnet con más extractos de tus fuentes",
        onclick: () => api("POST", `/api/asesor/${e.id}/profundizar`, { web: !!A.web.get(e.id) }).catch(AP.alerta) }, ocupado ? "Profundizando…" : p && p.estado === "ok" ? "Profundizar de nuevo" : "Profundizar"),
      caja,
      h("span", { class: "as-acc-der" },
        h("button", { type: "button", class: "btn btn-mini btn-ghost", "data-accion": "fijar", "data-id": e.id, "aria-pressed": String(!!fijado),
          title: fijado ? "Quitar de lo fijado" : "Fijar: se queda visible aunque lleguen otras",
          onclick: () => api("POST", `/api/asesor/${e.id}/fijar`, { valor: !fijado }).catch(AP.alerta) }, fijado ? "Fijada" : "Fijar"),
        h("button", { type: "button", class: "btn btn-mini btn-ghost", "data-accion": "descartar", "data-id": e.id, title: "Descartar: sale del carril y del .md",
          onclick: () => api("POST", `/api/asesor/${e.id}/descartar`, { valor: true }).catch(AP.alerta) }, "Descartar")));
  }

  function notaEscalada(r) {
    if (r.escalada === "pendiente" || r.escalada === "en_curso") return h("div", { class: "as-nota t-meta", role: "status" }, `Toca ${(r.temas || []).join(", ")}: afinando con Sonnet…`);
    if (r.escalada === "hecha") return h("div", { class: "as-nota t-meta" }, `Toca ${(r.temas || []).join(", ")}: afinada con Sonnet.`);
    if (r.escalada === "limite") return h("div", { class: "as-nota t-meta" }, `Toca ${(r.temas || []).join(", ")}, pero no queda Sonnet esta hora (límite por hora o presupuesto del asesor): esta es la respuesta de Haiku.`);
    if (r.escalada === "error") return h("div", { class: "as-nota as-error t-meta" }, r.error_escalada || "No se pudo afinar con Sonnet.");
    return null;
  }

  function cuerpoRespuesta(r, grande) {
    if (r.estado === "en_curso") {
      const real = enCurso(["asesor"]);
      return h("div", { class: "as-espera t-body", role: "status" }, "Preparando la respuesta" + (real ? " · " + crono(Date.now() - (hoyMs(real.hora) || Date.now())) : "") + "…");
    }
    if (r.estado === "error") return h("div", { class: "as-error t-body", role: "alert" }, r.error || "No se pudo responder.");
    const sinBase = r.sin_base;
    return h("div", {},
      h("ul", { class: "as-vin" + (grande ? " grande" : "") + (sinBase ? " sin-base" : "") }, ...(r.vinetas || []).map((v) => h("li", {}, v))),
      !sinBase && r.sin_cita ? h("div", { class: "as-nota t-meta" }, "Sin una fuente citada que se pueda comprobar: tómalo con cautela.") : null,
      notaEscalada(r));
  }

  function tarjetaAhora(r) {
    const sinBase = r.sin_base && r.estado === "ok";
    return h("article", { class: "as-ahora" + (r.estado === "error" ? " error" : "") + (r.sin_base ? " sin-base" : ""), "data-id": r.id, "aria-label": `Ahora: respuesta sugerida a «${r.pregunta}»` },
      h("div", { class: "as-cab" }, icono(sinBase ? "info" : r.estado === "error" ? "error" : "respuesta", "as-ic"), h("span", { class: "t-label as-etq" }, "Ahora"), chipMin(r.minuto, r.t_seg), h("span", { class: "t-meta" }, r.canal),
        h("span", { class: "as-cab-der" }, r.estado === "ok" ? chipConf(r.confianza) : null, r.estado === "ok" ? h("span", { class: "as-modelo t-meta", title: "Modelo que ha respondido" }, nombreModelo(r.modelo)) : null)),
      h("p", { class: "as-preg" }, r.pregunta),
      cuerpoRespuesta(r, true),
      r.estado === "ok" ? profundizado(r) : null,
      r.estado === "ok" ? h("div", { class: "as-pie" }, r.sin_base ? null : fuentes(r.citas), acciones(r, "respuesta")) : h("div", { class: "as-acc" }, h("span", { class: "as-acc-der" },
        h("button", { type: "button", class: "btn btn-mini btn-ghost", "data-accion": "descartar", "data-id": r.id, onclick: () => api("POST", `/api/asesor/${r.id}/descartar`, { valor: true }).catch(AP.alerta) }, "Descartar"))));
  }

  // una pregunta que no tuvo base en las fuentes: una línea atenuada, nunca el carril grande
  function lineaSinBase(r) {
    return h("div", { class: "as-nobase", "data-id": r.id, role: "status" }, icono("info", "as-ic"), chipMin(r.minuto, r.t_seg),
      h("span", { class: "as-nobase-t" }, h("span", { class: "as-nobase-q" }, r.pregunta), " · sin base en tus fuentes"),
      h("button", { type: "button", class: "btn btn-mini btn-ghost", "data-accion": "descartar", "data-id": r.id, onclick: () => api("POST", `/api/asesor/${r.id}/descartar`, { valor: true }).catch(AP.alerta) }, "Descartar"));
  }

  function tarjetaCompacta(r) {
    const primera = (r.vinetas || [])[0] || (r.estado === "error" ? r.error : "");
    return h("article", { class: "as-comp" + (r.fijada ? " fijada" : ""), "data-id": r.id },
      h("div", { class: "as-cab" }, chipMin(r.minuto, r.t_seg), h("span", { class: "t-meta" }, r.canal), r.estado === "ok" ? chipConf(r.confianza) : null),
      h("p", { class: "as-preg t-body-m" }, r.pregunta), h("p", { class: "as-comp-v t-body" }, primera),
      r.estado === "ok" ? acciones(r, "respuesta") : null);
  }

  function tarjetaConsejo(c) {
    return h("article", { class: "as-cons" + (c.fijado ? " fijada" : ""), "data-id": c.id, "data-tipo": c.tipo, "aria-label": `Consejo: ${c.etiqueta}. ${c.accion}` },
      h("div", { class: "as-cab" }, icono("consejo", "as-ic"), h("span", { class: "t-label as-etq-c" }, c.etiqueta), chipMin(c.minuto, c.t_seg), h("span", { class: "as-cab-der t-meta" }, nombreModelo(c.modelo))),
      h("p", { class: "as-accion" }, c.accion),
      h("p", { class: "as-porque" }, h("span", { class: "as-porque-t" }, "Por qué: "), c.porque),
      profundizado(c), acciones(c, "consejo"));
  }

  // ------------------------------------------------------------ carril
  function cabeceraCarril() {
    const e = A.estado || {};
    const pr = e.presupuesto, so = e.sonnet;
    const meta = pr ? `${kfmt(pr.usado)} / ${kfmt(pr.limite)} tokens esta hora${so ? ` · sonnet ${so.usados} de ${so.limite}` : ""}` : "";
    const nivel = pr && pr.nivel;
    const aviso = nivel === "agotado" ? "Sin presupuesto del asesor esta hora: no responde solo, «Profundizar» sigue disponible."
      : nivel === "ahorro" ? "Ahorro: sin Sonnet automático y consejos más espaciados." : "";
    return h("div", { class: "as-h" },
      h("span", { class: "t-label as-titulo" }, "Asesor"),
      h("span", { class: "t-meta as-meta", title: "Presupuesto propio del asesor (ventana de 60 minutos de reunión), aparte del del equipo" }, meta),
      h("button", { type: "button", class: "btn btn-mini btn-ghost as-plegar", "aria-expanded": String(!A.plegado), "aria-controls": "as-cuerpo", onclick: () => {
        A.plegado = !A.plegado; try { localStorage.setItem("apuntes_asesor_plegado", A.plegado ? "1" : "0"); } catch { /* sin almacenamiento */ }
        render();
      } }, A.plegado ? "Mostrar" : "Plegar"),
      aviso ? h("div", { class: "as-aviso t-meta" }, aviso) : null);
  }

  // Los consejos viven en la pestaña «Consejos» (#as-consejos); el carril «Ahora» queda fijo arriba de la columna derecha
  function pintarConsejos(cons) {
    const cont = $("#as-consejos");
    const n = $("#tab-n-consejos");
    if (n) n.textContent = cons.length ? String(cons.length) : "";
    if (!cont) return;
    const f = document.activeElement && cont.contains(document.activeElement) ? document.activeElement : null;
    const foco = f ? { id: f.dataset.id, accion: f.dataset.accion } : null;
    const orden = [...cons.filter((c) => c.fijado), ...cons.filter((c) => !c.fijado).sort((a, b) => numId(b) - numId(a))];
    cont.replaceChildren(...(orden.length ? orden.map(tarjetaConsejo) : [h("div", { class: "as-vacio t-body" }, "Todavía no hay consejos. El Estratega los propone cuando detecta una señal en la conversación.")]));
    if (foco && foco.id) {
      const nuevo = cont.querySelector(`[data-id="${foco.id}"][data-accion="${foco.accion}"]`);
      if (nuevo && !nuevo.disabled) nuevo.focus({ preventScroll: true });
    }
  }

  function pintar() {
    const lane = $("#as-carril");
    if (!lane) return;
    const resp = A.respuestas.filter((r) => !r.descartada).sort((a, b) => (a.t_seg - b.t_seg) || (numId(a) - numId(b)));
    const cons = A.consejos.filter((c) => !c.descartado);
    const activa = !!(S.sesion && S.estado !== "inactivo");
    pintarConsejos(activa ? cons : []);
    const hay = !!(activa && resp.length);
    lane.hidden = !hay;
    if (!hay) { lane.replaceChildren(); pararCrono(); return; }
    // conserva el foco del teclado si el usuario estaba en uno de los mandos
    const f = document.activeElement && lane.contains(document.activeElement) ? document.activeElement : null;
    const foco = f ? { id: f.dataset.id, accion: f.dataset.accion } : null;
    // «Ahora» = la respuesta más reciente CON base; una pregunta sin base posterior se queda en una línea atenuada (nunca ocupa el carril grande)
    const ultima = resp[resp.length - 1] || null;
    const conBase = resp.filter((r) => !r.sin_base);
    const ahora = conBase[conBase.length - 1] || ultima;
    const sinBaseNueva = ultima && ultima !== ahora && ultima.sin_base && !ultima.fijada ? ultima : null;
    const fijadas = resp.filter((r) => r.fijada && r !== ahora);
    const anteriores = resp.filter((r) => r !== ahora && r !== sinBaseNueva && !r.fijada).reverse();
    const partes = [cabeceraCarril()];
    if (!A.plegado) {
      const cuerpo = h("div", { class: "as-cuerpo", id: "as-cuerpo" });
      if (ahora) cuerpo.append(h("div", { class: "as-ahora-caja", "aria-live": "polite" }, tarjetaAhora(ahora)));
      if (sinBaseNueva) cuerpo.append(lineaSinBase(sinBaseNueva));
      if (fijadas.length) cuerpo.append(h("div", { class: "as-grupo" }, h("div", { class: "grupo-h" }, h("span", { class: "t-label" }, "Fijadas"), h("span", { class: "n t-meta" }, String(fijadas.length))), h("div", { class: "as-fila" }, ...fijadas.map(tarjetaCompacta))));
      if (anteriores.length) {
        cuerpo.append(h("details", { class: "as-ant", open: A.anteriores ? true : null, ontoggle: (ev) => { A.anteriores = ev.target.open; } },
          h("summary", { class: "t-label" }, `Respuestas anteriores (${anteriores.length})`), h("div", { class: "as-fila" }, ...anteriores.map(tarjetaCompacta))));
      }
      partes.push(cuerpo);
    }
    lane.replaceChildren(...partes);
    if (foco && foco.id) {
      const nuevo = lane.querySelector(`[data-id="${foco.id}"][data-accion="${foco.accion}"]`);
      if (nuevo && !nuevo.disabled) nuevo.focus({ preventScroll: true });
    }
    // el cronómetro de una llamada real se refresca cada segundo SOLO mientras haya una
    const real = enCurso(["asesor"]) && resp.some((r) => r.estado === "en_curso");
    if (real && !A.crono) A.crono = setInterval(pintar, 1000);
    if (!real) pararCrono();
  }
  function pararCrono() { if (A.crono) { clearInterval(A.crono); A.crono = null; } }
  let pendiente = false;
  function render() { if (pendiente) return; pendiente = true; requestAnimationFrame(() => { pendiente = false; pintar(); }); }

  // ------------------------------------------------------------ datos
  function recibir(d, conListas) {
    if (!d) return;
    if (conListas || d.respuestas) { A.respuestas = d.respuestas || []; A.consejos = d.consejos || []; }
    const { respuestas, consejos, tipo, ...estado } = d;
    A.estado = estado;
    S.asesor = estado;
  }
  const previoEvento = AP.hooks.evento;
  AP.hooks.evento = (d) => {
    if (previoEvento) previoEvento(d);
    switch (d.tipo) {
      case "snapshot": A.respuestas = []; A.consejos = []; recibir(d.asesor, true); render(); break;
      case "asesor": recibir(d, true); render(); break;
      case "estado": case "tick": if (d.asesor) { A.estado = d.asesor; S.asesor = d.asesor; if (d.tipo === "estado") render(); } break;
      case "tarea": render(); break;
    }
  };
  const previoReinicio = AP.hooks.reiniciar;
  AP.hooks.reiniciar = () => { if (previoReinicio) previoReinicio(); A.respuestas = []; A.consejos = []; A.estado = null; A.web.clear(); pararCrono(); render(); };

  AP.asesor = { render, estado: () => A };
})();
