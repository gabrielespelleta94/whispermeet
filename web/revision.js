"use strict";
/* Apuntes: pantalla de revisión (resumen, objetivos, cambios por fichero con diff, «Pulir con Opus» y publicación). */
(() => {
  const AP = window.AP;
  if (!AP) return;
  const { S, UI, h, $, $$, kfmt } = AP;
  const reducido = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  const tokensDe = (agente) => { const l = [...AP.O.tareas.values()].filter((t) => t.agente === agente && t.estado === "ok"); const t = l[l.length - 1]; return t || null; };

  // ---- diferencias palabra a palabra entre dos versiones del resumen (LCS), pintadas en acento suave
  function palabrasDeDOM(raiz) {
    const w = [], nodos = [];
    const it = document.createTreeWalker(raiz, NodeFilter.SHOW_TEXT);
    for (let n = it.nextNode(); n; n = it.nextNode()) nodos.push(n);
    nodos.forEach((n) => String(n.nodeValue).split(/(\s+)/).forEach((p) => { if (p && !/^\s+$/.test(p)) w.push({ nodo: n, txt: p }); }));
    return { w, nodos };
  }
  function lcsFlags(a, b) {
    const n = a.length, m = b.length;
    if (n * m > 4_000_000) return [a.map(() => false), b.map(() => false)];
    const t = Array.from({ length: n + 1 }, () => new Uint16Array(m + 1));
    for (let i = n - 1; i >= 0; i--) for (let j = m - 1; j >= 0; j--) t[i][j] = a[i] === b[j] ? t[i + 1][j + 1] + 1 : Math.max(t[i + 1][j], t[i][j + 1]);
    const fa = a.map(() => true), fb = b.map(() => true);
    let i = 0, j = 0;
    while (i < n && j < m) { if (a[i] === b[j]) { fa[i] = fb[j] = false; i++; j++; } else if (t[i + 1][j] >= t[i][j + 1]) i++; else j++; }
    return [fa, fb];
  }
  function marcar(raiz, flags) {
    const { w, nodos } = palabrasDeDOM(raiz);
    const porNodo = new Map(nodos.map((n) => [n, []]));
    w.forEach((x, k) => porNodo.get(x.nodo).push(flags[k]));
    for (const n of nodos) {
      const fl = porNodo.get(n);
      if (!fl.some(Boolean)) continue;
      const partes = String(n.nodeValue).split(/(\s+)/);
      const frag = document.createDocumentFragment();
      let k = 0;
      for (const p of partes) {
        if (!p) continue;
        if (/^\s+$/.test(p)) { frag.append(p); continue; }
        if (fl[k++]) frag.append(h("mark", { class: "dif" }, p)); else frag.append(p);
      }
      n.replaceWith(frag);
    }
  }
  function compararResumenes(a, b) {
    const pa = palabrasDeDOM(a).w.map((x) => x.txt), pb = palabrasDeDOM(b).w.map((x) => x.txt);
    const [fa, fb] = lcsFlags(pa, pb);
    marcar(a, fa); marcar(b, fb);
  }

  // ---- bloques de cambio por fichero
  const contar = (diff) => { let mas = 0, menos = 0; String(diff || "").split("\n").forEach((l) => { if (l.startsWith("+") && !l.startsWith("+++")) mas++; else if (l.startsWith("-") && !l.startsWith("---")) menos++; }); return [mas, menos]; };
  const claseLinea = (l) => (l.startsWith("+++") || l.startsWith("---") ? "file" : l.startsWith("+") ? "add" : l.startsWith("-") ? "del" : l.startsWith("@@") ? "hunk" : "");

  function bloque(c, bloqueado) {
    const [mas, menos] = contar(c.diff);
    const el = h("article", { class: "cambio" + (c.valido ? "" : " invalido"), "data-id": c.id });
    if (!c.valido) {
      el.append(h("div", { class: "cambio-h" }, h("span", { class: "f t-body-m" }, c.fichero), h("span", { class: "m t-meta" }, c.motivo || ""), h("span", { class: "t-meta soft" }, "No aplicable")),
        h("div", { class: "cambio-error t-meta" }, "Descartado automáticamente: " + c.error));
      return el;
    }
    const estado = h("span", { class: "decidido-t t-label" });
    const si = h("button", { type: "button", class: "btn btn-mini si", "aria-pressed": "false", disabled: bloqueado, onclick: () => fijar(c.id, "si") }, "Aceptar");
    const no = h("button", { type: "button", class: "btn btn-ghost btn-mini no", "aria-pressed": "false", disabled: bloqueado, onclick: () => fijar(c.id, "no") }, "Rechazar");
    const des = h("button", { type: "button", class: "btn btn-ghost btn-mini deshacer", disabled: bloqueado, onclick: () => fijar(c.id, undefined) }, "Deshacer");
    el.append(h("div", { class: "cambio-h" },
      h("span", { class: "f t-body-m" }, c.fichero), h("span", { class: "m t-meta" }, c.motivo + (c.minuto ? ` · minuto ${c.minuto}` : "")),
      h("span", { class: "cuenta t-meta" }, h("b", { class: "mas" }, "+" + mas), " ", h("b", { class: "menos" }, "−" + menos)),
      h("span", { class: "decide", role: "group", "aria-label": "Decisión sobre " + c.fichero }, si, no), estado, des),
    h("div", { class: "diff-wrap" }, h("div", { class: "diff", tabindex: "0" }, String(c.diff).split("\n").map((l) => h("div", { class: "dl t-body " + claseLinea(l) }, l || " ")))));
    el._p = { si, no, des, estado };
    pintarDecision(el, UI.decisiones[c.id], false);
    return el;
  }
  function pintarDecision(el, v, animar) {
    if (!el._p) return;
    const p = el._p;
    el.classList.toggle("decidido", v === "si" || v === "no");
    el.dataset.decision = v || "";
    p.si.setAttribute("aria-pressed", String(v === "si")); p.no.setAttribute("aria-pressed", String(v === "no"));
    p.estado.textContent = v === "si" ? "Aceptado" : v === "no" ? "Rechazado" : "";
  }
  function fijar(id, v) {
    if (v === undefined) delete UI.decisiones[id]; else UI.decisiones[id] = v;
    const el = $(`#v-rev-cuerpo .cambio[data-id="${CSS.escape(id)}"]`);
    if (el) pintarDecision(el, v, true);
    pie();
  }
  function fijarTodos(v) {
    const rev = S.revision; if (!rev || rev.aplicado) return;
    rev.cambios.filter((c) => c.valido).forEach((c) => { if (v === undefined) delete UI.decisiones[c.id]; else UI.decisiones[c.id] = v; const el = $(`#v-rev-cuerpo .cambio[data-id="${CSS.escape(c.id)}"]`); if (el) pintarDecision(el, v, true); });
    pie();
  }

  function pie() {
    const rev = S.revision, s = S.sesion; if (!rev || !s) return;
    const validos = rev.cambios.filter((c) => c.valido);
    const acept = validos.filter((c) => UI.decisiones[c.id] === "si").length;
    $("#v-rev-cuenta").textContent = s.proyecto ? `${acept} aceptado${acept === 1 ? "" : "s"} de ${validos.length} · el resto se descarta` : "";
    $("#v-rev-aplicar").hidden = !s.proyecto || !!rev.aplicado;
    $("#v-rev-aplicar").disabled = acept === 0;
    $("#v-rev-cerrar").textContent = rev.aplicado || !validos.length ? "Cerrar" : "Cerrar sin aplicar";
  }

  const seg = (ms) => AP.seg(ms);
  function cabVersion(nombre, t, elegida, onUsar, id) {
    const partes = [nombre, t && t.tokens != null ? `${kfmt(t.tokens)} tokens` : null, t && t.ms != null && nombre === "Opus" ? seg(t.ms) : null].filter(Boolean);
    return h("div", { class: "ver-h" }, h("span", { class: "t-title" }, partes.join(" · ")),
      elegida ? h("span", { class: "t-label en-uso" }, "En uso") : h("button", { type: "button", class: "btn btn-mini", id, onclick: onUsar }, "Usar esta"));
  }

  // ---- «Correo de cierre»: borrador en texto plano construido en local (apuntes/correo_cierre.py). Solo se copia; la app no envía nada
  // ni abre ningún cliente de correo.
  async function copiarTexto(texto) {
    try { await navigator.clipboard.writeText(texto); return true; } catch { /* sin permiso del portapapeles: se prueba el método clásico */ }
    const t = h("textarea", { style: "position:fixed;left:-9999px;top:0", "aria-hidden": "true" });
    t.value = texto; document.body.append(t); t.select();
    let ok = false;
    try { ok = document.execCommand("copy"); } catch { ok = false; }
    t.remove();
    return ok;
  }
  function seccionCorreo(texto) {
    const estado = h("span", { class: "t-meta soft", id: "v-rev-correo-estado", role: "status" });
    let reloj;
    const boton = h("button", { type: "button", class: "btn btn-mini", id: "v-rev-correo-copiar", onclick: async () => {
      const ok = await copiarTexto(texto);
      estado.textContent = ok ? "Copiado" : "No se pudo copiar; selecciona el texto a mano.";
      clearTimeout(reloj); reloj = setTimeout(() => { estado.textContent = ""; }, 2500);
    } }, "Copiar");
    return h("section", { class: "sec", id: "v-rev-correo" }, h("span", { class: "t-label" }, "Correo de cierre"),
      h("div", { class: "correo-txt t-body", id: "v-rev-correo-texto", tabindex: "0" }, texto),
      h("div", { class: "acciones correo-acc" }, boton, estado,
        h("span", { class: "t-meta soft" }, "Borrador local: no se envía nada.")));
  }

  AP.hooks.pintarRevision = () => {
    const rev = S.revision, s = S.sesion;
    if (!rev || !s) return;
    $("#v-rev-titulo").textContent = "Revisión: " + s.tema;
    $("#v-rev-meta").textContent = `${s.proyecto || "Bandeja"}${s.compartido ? " (carpeta compartida)" : ""} · ${s.compartido ? "copia local en" : "transcripción guardada en"} ${s.carpeta}\\${s.fichero}`;
    const cuerpo = $("#v-rev-cuerpo"), pieEl = $("#v-rev-pie");
    cuerpo.replaceChildren();
    if (rev.estado === "generando") {
      pieEl.hidden = true;
      cuerpo.append(h("div", { class: "cargando t-body" }, "Generando el resumen final y los cambios propuestos…"));
      return;
    }
    if (rev.estado === "error") {
      pieEl.hidden = false;
      $("#v-rev-cuenta").textContent = "La transcripción está guardada.";
      $("#v-rev-aplicar").hidden = true;
      $("#v-rev-cerrar").textContent = "Cerrar";
      cuerpo.append(h("div", { class: "error t-body" }, h("b", {}, "No se pudo generar el resumen final. "), rev.error),
        h("div", { class: "acciones" }, h("button", { class: "btn btn-primary", type: "button", onclick: () => AP.api("POST", "/api/revision/reintentar").catch(AP.alerta) }, "Reintentar")),
        AP.seccionPublicacion(rev));
      return;
    }
    $("#v-rev-aplicar").hidden = false;
    const pu = rev.pulido || { estado: "ninguno" };
    const elegir = (v) => AP.api("POST", "/api/revision/resumen", { version: v }).catch((e) => AP.avisarError(e));
    let comparacion = null;
    const izq = h("div", { class: "rev-izq" });
    const der = h("div", { class: "rev-der" });

    // ---- columna 1: resumen (56ch), objetivos, publicación e insights
    if ((rev.avisos || []).length) {   // comprobación local del resumen: falta de contenido afirmada o tramos sin cubrir, con sus minutos
      izq.append(h("section", { class: "sec aviso", id: "v-rev-avisos" }, h("span", { class: "t-label" }, "Aviso sobre el resumen"),
        h("ul", {}, rev.avisos.map((a) => h("li", { class: "t-body" }, a)))));
    }
    if (pu.estado === "listo") {
      const a = AP.md(rev.resumen_sonnet || "Sin resumen."), b = AP.md(pu.resumen || "");
      compararResumenes(a, b);
      comparacion = h("section", { class: "sec comparacion" }, h("span", { class: "t-label" }, "Resumen final: dos versiones, las diferencias van marcadas"),
        h("div", { class: "versiones" },
          h("div", { class: "version" + (pu.elegida === "sonnet" ? " elegida" : "") }, cabVersion("Sonnet", tokensDe("redactor"), pu.elegida === "sonnet", () => elegir("sonnet"), "v-rev-elegir-sonnet"), a),
          h("div", { class: "version" + (pu.elegida === "opus" ? " elegida" : "") }, cabVersion("Opus", tokensDe("pulidor"), pu.elegida === "opus", () => elegir("opus"), "v-rev-elegir-opus"), b)));
    } else {
      izq.append(h("section", { class: "sec" }, h("span", { class: "t-label" }, "Resumen final"), AP.md(rev.resumen || "Sin resumen."),
        pu.estado === "generando" ? h("p", { class: "t-meta soft" }, "Puliendo con opus…") : h("div", { class: "acciones pulir" },
          h("button", { class: "btn btn-ghost", type: "button", id: "v-rev-pulir", onclick: () => AP.api("POST", "/api/revision/pulir").catch((e) => AP.avisarError(e)) },
            pu.estado === "error" ? "Volver a pulir con Opus" : "Pulir con Opus"),
          h("span", { class: "t-meta soft" }, "Opcional: gasta bastante más de tu licencia que el resto del análisis. Solo se ejecuta si lo pulsas; se muestran las dos versiones y eliges."),
          pu.estado === "error" ? h("div", { class: "error", id: "v-rev-pulir-error" }, "No se pudo pulir: " + pu.error + " La revisión sigue con la versión de Sonnet.") : null)));
    }
    const objs = rev.objetivos || [];
    if (objs.length) {
      const cub = objs.filter((o) => o.estado === "cubierto"), pen = objs.filter((o) => o.estado !== "cubierto");
      const lista = (t, l) => (l.length ? h("div", { class: "obj-grupo" }, h("div", { class: "t-label" }, `${t} · ${l.length}`), h("ul", {}, l.map((o) => h("li", { class: "t-body" }, o.texto, o.minuto ? h("span", { class: "t-meta soft" }, " " + o.minuto) : null)))) : null);
      izq.append(h("section", { class: "sec" }, h("span", { class: "t-label" }, `Objetivos · ${cub.length}/${objs.length} cubiertos`), lista("Cumplidos", cub), lista("Pendientes", pen)));
    }
    if (rev.correo) izq.append(seccionCorreo(rev.correo));
    const pub = AP.seccionPublicacion(rev);
    if (pub) izq.append(pub);
    if (S.tarjetas.length) {
      izq.append(h("section", { class: "sec" }, h("span", { class: "t-label" }, "Insights de la reunión"),
        AP.GRUPOS.map(([cat, titulo]) => { const ts = S.tarjetas.filter((t) => t.categoria === cat); return ts.length
          ? h("div", { class: "md" }, h("h4", {}, titulo), h("ul", {}, ts.map((t) => h("li", {}, `[${t.minuto || "--:--"}] ${t.texto}${t.responsable ? " (" + t.responsable + ")" : ""}`)))) : null; })));
    }

    // ---- zona 2/3: cambios propuestos, uno por fichero
    const sec = h("section", { class: "sec cambios" });
    der.append(sec);
    if (!s.proyecto) {
      sec.append(h("span", { class: "t-label" }, "Cambios propuestos al contexto"), h("p", { class: "t-body soft" }, "Reunión sin proyecto: no hay ficheros de contexto que actualizar. La transcripción queda en la bandeja."));
    } else {
      const validos = rev.cambios.filter((c) => c.valido);
      const tot = validos.reduce((a, c) => { const [m, n] = contar(c.diff); return [a[0] + m, a[1] + n]; }, [0, 0]);
      sec.append(h("div", { class: "cambios-h" }, h("span", { class: "t-title" }, "Cambios propuestos al contexto"),
        validos.length ? h("span", { class: "cuenta t-meta" }, h("b", { class: "mas" }, "+" + tot[0]), " ", h("b", { class: "menos" }, "−" + tot[1])) : null,
        validos.length ? h("span", { class: "cambios-b" },
          h("button", { type: "button", class: "btn btn-mini", id: "v-rev-aceptar-todo", disabled: !!rev.aplicado, onclick: () => fijarTodos("si") }, "Aceptar todo"),
          h("button", { type: "button", class: "btn btn-ghost btn-mini", id: "v-rev-rechazar-todo", disabled: !!rev.aplicado, onclick: () => fijarTodos("no") }, "Rechazar todo")) : null));
      if (rev.compartido) sec.append(h("div", { class: "banner info t-meta", id: "v-rev-compartido" }, h("b", {}, "Se escribirá en una carpeta compartida. "),
        "Los cambios que aceptes se escribirán en «" + rev.destino_contexto + "», una carpeta compartida de otra persona, y se añadirá una entrada a 10-registro-de-cambios.md. Revisa cada diff antes de aceptar. La transcripción no se copia allí."));
      if (rev.carpeta_contexto === false) sec.append(h("div", { class: "banner info t-meta" }, "La carpeta «00. CONTEXTO (IA)» no existe en este proyecto. Si aceptas algún cambio se creará con las plantillas del kit."));
      if (!rev.cambios.length) sec.append(h("p", { class: "t-body soft" }, "Esta reunión no ha generado cambios para el contexto." + (rev.sin_cambios ? " Motivo: " + rev.sin_cambios : "")));
      rev.cambios.forEach((c) => sec.append(bloque(c, !!rev.aplicado)));
    }
    if (rev.aplicado) {
      const a = rev.aplicado;
      der.append(h("div", { class: "resultado t-body" }, a.aplicados.length
        ? `Aplicados ${a.aplicados.length} cambio(s) en ${a.ficheros.join(", ")}${a.carpeta_creada ? " (carpeta de contexto creada con las plantillas)" : ""}. Entrada añadida a 10-registro-de-cambios.md.`
        : "No se aplicó ningún cambio.", a.omitidos.length ? " No se pudieron aplicar: " + a.omitidos.map((o) => `${o.id} (${o.motivo})`).join("; ") + "." : ""));
    }
    if (comparacion) cuerpo.append(comparacion);
    if (AP.montarSesionRevision) AP.montarSesionRevision(cuerpo);   // el Gantt de la sesión completo
    cuerpo.append(h("div", { class: "rev-grid" }, izq, der));
    pieEl.hidden = false;
    pie();
  };
})();
