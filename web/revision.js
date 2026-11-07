"use strict";
/* Apuntes: pantalla de revisión (resumen, objetivos, cambios por fichero con diff, «Pulir con Opus» y publicación). */
(() => {
  const AP = window.AP;
  if (!AP) return;
  const { S, UI, h, $, $$, kfmt } = AP;
  const reducido = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  // ---- la revisión es una lista de cierre en CUATRO pasos (stepper accesible). El paso actual sobrevive a los repintados; una reunión nueva empieza en el 1.
  const PASOS = [["Decisiones y resumen", "decisiones"], ["Cambios al contexto", "cambios"], ["Correo de cierre", "correo"], ["Publicar o guardar", "publicar"]];
  const R = { paso: 1, visitados: new Set([1]), sesion: null, premarcados: new Set(), ganttAbierto: false, outlook: null, correoEstado: "" };
  const anuncio = () => $("#rev-anuncio");
  function irAPaso(n, enfocar) {
    n = Math.max(1, Math.min(PASOS.length, Number(n) || 1));
    R.paso = n; R.visitados.add(n);
    $$("#v-rev-cuerpo .rev-paso").forEach((p) => { p.hidden = Number(p.dataset.paso) !== n; });
    $$("#rev-stepper .rev-st").forEach((b) => { const on = Number(b.dataset.paso) === n; if (on) b.setAttribute("aria-current", "step"); else b.removeAttribute("aria-current"); b.closest("li").classList.toggle("visto", R.visitados.has(Number(b.dataset.paso)) && !on); });
    const atras = $("#rev-atras"), sig = $("#rev-siguiente");
    if (atras) atras.disabled = n === 1;
    if (sig) sig.hidden = n === PASOS.length;
    if (anuncio()) anuncio().textContent = `Paso ${n} de ${PASOS.length}: ${PASOS[n - 1][0]}`;
    if (n === 1 && R.ganttAbierto && AP.refrescarSesion) requestAnimationFrame(AP.refrescarSesion);
    if (n === 3) comprobarOutlook();
    if (enfocar) { const t = $(`#rev-paso-${n} .rev-p-t`); if (t) t.focus(); }
  }
  const atras = $("#rev-atras"), siguiente = $("#rev-siguiente");
  if (atras) atras.addEventListener("click", () => irAPaso(R.paso - 1, true));
  if (siguiente) siguiente.addEventListener("click", () => irAPaso(R.paso + 1, true));
  AP.revision = { irAPaso: (n) => { if (document.body.dataset.vista !== "revision") return false; irAPaso(n, true); return true; }, paso: () => R.paso, pasos: PASOS.map((p) => p[0]) };

  // «Abrir en Outlook»: POST /api/correo/outlook {asunto, cuerpo}. Si el servidor no lo tiene (404), el botón desaparece; no se envía nada: Outlook abre el borrador y el usuario lo manda.
  function partirCorreo(texto) {
    const t = String(texto || "").replace(/\r\n/g, "\n");
    const m = /^Asunto:[ \t]*(.*)\n+/.exec(t);
    return m ? { asunto: m[1].trim(), cuerpo: t.slice(m[0].length).trim() } : { asunto: "", cuerpo: t.trim() };
  }
  async function comprobarOutlook() {
    const b = $("#v-rev-correo-outlook");
    if (!b || R.outlook !== null) { if (b) b.hidden = R.outlook === false; return; }
    R.outlook = true;   // se supone disponible hasta que el servidor diga que no
    try { await AP.api("OPTIONS", "/api/correo/outlook"); } catch (e) { if (e && e.status === 404) R.outlook = false; }
    const b2 = $("#v-rev-correo-outlook"); if (b2) b2.hidden = R.outlook === false;
  }

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
    if (c.preaceptado === true) {   // el backend ya lo da por bueno: va marcado y con la cita que lo justifica
      el.classList.add("preaceptado");
      const cita = c.cita || c.evidencia || "";
      el.querySelector(".cambio-h .f").after(h("span", { class: "pre-et t-label" }, AP.icono("check", "ic-s"), "Preaceptado"));
      el.insertBefore(h("blockquote", { class: "pre-cita t-body" }, h("span", { class: "t-meta soft" }, "Cita de la reunión" + (c.minuto ? ` · ${c.minuto}` : "") + ": "), cita ? "«" + cita + "»" : "sin cita registrada"), el.querySelector(".diff-wrap"));
    }
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
    const e2 = $("#rev-st-e-2"); if (e2) e2.textContent = !s.proyecto ? "Sin proyecto" : rev.aplicado ? "Aplicados" : validos.length ? `${acept} de ${validos.length} aceptados` : "Sin cambios";
    const e3 = $("#rev-st-e-3"); if (e3) e3.textContent = rev.correo ? "Borrador listo" : "Sin borrador";
    const e4 = $("#rev-st-e-4"); if (e4) e4.textContent = rev.publicacion ? ({ publicada: "Publicado", error: "Con error" }[rev.publicacion.estado] || (rev.publicacion.publicar ? "Se publicará" : "No se publicará")) : "Todo guardado";
    const c = $("#rev-cierre-cambios"); if (c) c.textContent = rev.aplicado ? "Los cambios aceptados ya se han aplicado al contexto." : acept ? `${acept} de ${validos.length} cambios aceptados: se aplicarán al contexto del proyecto al pulsar «Aplicar cambios aceptados».` : "No has aceptado ningún cambio: el contexto del proyecto no se toca.";
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
    const outlook = h("button", { type: "button", class: "btn btn-mini", id: "v-rev-correo-outlook", hidden: R.outlook === false ? true : null, title: "Abre el borrador en Outlook. No se envía nada: lo revisas y lo mandas tú", onclick: async () => {
      const { asunto, cuerpo } = partirCorreo(texto);
      outlook.disabled = true; estado.textContent = "Abriendo Outlook…";
      try {
        const r = await AP.api("POST", "/api/correo/outlook", { asunto, cuerpo });
        estado.textContent = r && r.ok === false ? "No se pudo abrir Outlook: " + (r.error || "error desconocido") + ". Puedes copiar el texto." : "Borrador abierto en Outlook. Revísalo y envíalo tú.";
      } catch (e) {
        if (e && e.status === 404) { R.outlook = false; outlook.hidden = true; estado.textContent = ""; } else estado.textContent = "No se pudo abrir Outlook: " + ((e && e.message) || "error") + ". Puedes copiar el texto.";
      } finally { outlook.disabled = false; clearTimeout(reloj); reloj = setTimeout(() => { estado.textContent = ""; }, 6000); }
    } }, AP.icono("correo", "ic-s"), "Abrir en Outlook");
    return h("section", { class: "sec", id: "v-rev-correo" }, h("span", { class: "t-label" }, "Correo de cierre"),
      h("div", { class: "correo-txt t-body", id: "v-rev-correo-texto", tabindex: "0" }, texto),
      h("div", { class: "acciones correo-acc" }, boton, outlook, estado,
        h("span", { class: "t-meta soft" }, "Borrador local: la app no envía nada.")));
  }

  AP.hooks.pintarRevision = () => {
    const rev = S.revision, s = S.sesion;
    if (!rev || !s) return;
    $("#v-rev-titulo").textContent = "Revisión: " + s.tema;
    $("#v-rev-meta").textContent = `${s.proyecto || "Bandeja"}${s.compartido ? " (carpeta compartida)" : ""} · ${s.compartido ? "copia local en" : "transcripción guardada en"} ${s.carpeta}\\${s.fichero}`;
    const cuerpo = $("#v-rev-cuerpo"), pieEl = $("#v-rev-pie");
    cuerpo.replaceChildren();
    const navB = $("#rev-nav-b"); if (navB) navB.hidden = true;
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
    if (R.sesion !== s.id) { R.sesion = s.id; R.paso = 1; R.visitados = new Set([1]); R.premarcados = new Set(); R.ganttAbierto = false; R.correoEstado = ""; }
    // cambios que el backend ya da por buenos (`preaceptado: true`): salen marcados, con su cita; el usuario puede deshacerlos. Sin el campo, todo igual que antes.
    for (const c of rev.cambios || []) if (c.valido && c.preaceptado === true && !R.premarcados.has(c.id)) { R.premarcados.add(c.id); if (UI.decisiones[c.id] === undefined && !rev.aplicado) UI.decisiones[c.id] = "si"; }
    const pu = rev.pulido || { estado: "ninguno" };
    const elegir = (v) => AP.api("POST", "/api/revision/resumen", { version: v }).catch((e) => AP.avisarError(e));
    const validos = (rev.cambios || []).filter((c) => c.valido);
    const objs = rev.objetivos || [];
    const tarj = (cat) => S.tarjetas.filter((t) => t.categoria === cat);
    const lis = (ts) => h("ul", { class: "rev-lista" }, ts.map((t) => h("li", { class: "t-body" }, h("span", { class: "t-meta soft rev-min" }, t.minuto || "--:--"), " " + t.texto, t.responsable ? h("span", { class: "t-meta soft" }, " (" + t.responsable + ")") : null)));
    const panel = (n, ...hijos) => h("section", { class: "rev-paso", id: "rev-paso-" + n, "data-paso": String(n), "aria-labelledby": "rev-paso-t-" + n, hidden: R.paso !== n },
      h("h2", { class: "t-title rev-p-t", id: "rev-paso-t-" + n, tabindex: "-1" }, `${n}. ${PASOS[n - 1][0]}`), ...hijos);

    // ---- paso 1: decisiones y resumen (con «Pulir» como opción aquí)
    let comparacion = null;
    const colResumen = h("div", { class: "rev-col" });
    if ((rev.avisos || []).length) {   // comprobación local del resumen: falta de contenido afirmada o tramos sin cubrir, con sus minutos
      colResumen.append(h("section", { class: "sec aviso", id: "v-rev-avisos" }, h("span", { class: "t-label" }, "Aviso sobre el resumen"),
        h("ul", {}, rev.avisos.map((a) => h("li", { class: "t-body" }, a)))));
    }
    if (pu.estado === "listo") {
      const a = AP.md(rev.resumen_sonnet || "Sin resumen."), b = AP.md(pu.resumen || "");
      compararResumenes(a, b);
      comparacion = h("section", { class: "sec comparacion" }, h("span", { class: "t-label" }, "Resumen final: dos versiones, las diferencias van marcadas"),
        h("div", { class: "versiones" },
          h("div", { class: "version" + (pu.elegida === "sonnet" ? " elegida" : "") }, cabVersion("Versión estándar", tokensDe("redactor"), pu.elegida === "sonnet", () => elegir("sonnet"), "v-rev-elegir-sonnet"), a),
          h("div", { class: "version" + (pu.elegida === "opus" ? " elegida" : "") }, cabVersion("Versión pulida", tokensDe("pulidor"), pu.elegida === "opus", () => elegir("opus"), "v-rev-elegir-opus"), b)));
      colResumen.append(comparacion);
    } else {
      colResumen.append(h("section", { class: "sec" }, h("span", { class: "t-label" }, "Resumen final"), h("div", { class: "rev-resumen" }, AP.md(rev.resumen || "Sin resumen.")),
        pu.estado === "generando" ? h("p", { class: "t-meta soft" }, "Puliendo el texto…") : h("div", { class: "acciones pulir" },
          h("button", { class: "btn btn-ghost", type: "button", id: "v-rev-pulir", onclick: () => AP.api("POST", "/api/revision/pulir").catch((e) => AP.avisarError(e)) },
            pu.estado === "error" ? "Volver a pulir con Opus" : "Pulir con Opus"),
          h("span", { class: "t-meta soft" }, "Opcional: gasta bastante más de tu licencia que el resto. Solo se hace si lo pulsas; verás las dos versiones y eliges."),
          pu.estado === "error" ? h("div", { class: "error", id: "v-rev-pulir-error" }, "No se pudo pulir: " + pu.error + " Sigues con la versión estándar.") : null)));
    }
    const colDec = h("div", { class: "rev-col" });
    const decs = tarj("decisión"), pens = tarj("pendiente");
    colDec.append(h("section", { class: "sec" }, h("span", { class: "t-label" }, `Decisiones · ${decs.length}`), decs.length ? lis(decs) : h("p", { class: "t-body soft" }, "No se tomó ninguna decisión cerrada.")));
    if (pens.length) colDec.append(h("section", { class: "sec" }, h("span", { class: "t-label" }, `Pendientes · ${pens.length}`), lis(pens)));
    if (objs.length) {
      const cub = objs.filter((o) => o.estado === "cubierto"), pen = objs.filter((o) => o.estado !== "cubierto");
      const lista = (t, l) => (l.length ? h("div", { class: "obj-grupo" }, h("div", { class: "t-label" }, `${t} · ${l.length}`), h("ul", {}, l.map((o) => h("li", { class: "t-body" }, o.texto, o.minuto ? h("span", { class: "t-meta soft" }, " " + o.minuto) : null)))) : null);
      colDec.append(h("section", { class: "sec" }, h("span", { class: "t-label" }, `Objetivos · ${cub.length} de ${objs.length} cubiertos`), h("div", { class: "obj-dos" }, lista("Cumplidos", cub), lista("Pendientes", pen))));
    }
    if (S.tarjetas.length) {
      colDec.append(h("details", { class: "sec rev-todo" }, h("summary", { class: "t-label" }, "Todo lo que salió de la reunión"),
        AP.GRUPOS.map(([cat, titulo]) => { const ts = tarj(cat); return ts.length ? h("div", { class: "md" }, h("h4", {}, titulo), lis(ts)) : null; })));
    }
    // la línea de tiempo (Gantt de la sesión) va plegada: se monta al abrirla, porque mide su ancho
    const gantt = h("details", { class: "rev-gantt", id: "rev-gantt", open: R.ganttAbierto ? true : null, ontoggle: (ev) => { R.ganttAbierto = ev.target.open; if (R.ganttAbierto && AP.refrescarSesion) requestAnimationFrame(AP.refrescarSesion); } },
      h("summary", { class: "t-label" }, "Línea de tiempo de la sesión"));
    const p1 = panel(1, h("div", { class: "rev-p-cols" + (comparacion ? " ancho" : "") }, colResumen, colDec), gantt);

    // ---- paso 2: cambios al contexto
    const sec = h("section", { class: "sec cambios" });
    if (!s.proyecto) {
      sec.append(h("p", { class: "t-body soft" }, "Reunión sin proyecto: no hay ficheros de contexto que actualizar. La transcripción queda en la bandeja."));
    } else {
      const tot = validos.reduce((a, c) => { const [m, n] = contar(c.diff); return [a[0] + m, a[1] + n]; }, [0, 0]);
      sec.append(h("div", { class: "cambios-h" }, h("span", { class: "t-body-m" }, validos.length ? `${validos.length} fichero${validos.length === 1 ? "" : "s"} con cambios propuestos` : "Sin cambios propuestos"),
        validos.length ? h("span", { class: "cuenta t-meta" }, h("b", { class: "mas" }, "+" + tot[0]), " ", h("b", { class: "menos" }, "−" + tot[1])) : null,
        validos.length ? h("span", { class: "cambios-b" },
          h("button", { type: "button", class: "btn btn-mini", id: "v-rev-aceptar-todo", disabled: !!rev.aplicado, onclick: () => fijarTodos("si") }, "Aceptar todo"),
          h("button", { type: "button", class: "btn btn-ghost btn-mini", id: "v-rev-rechazar-todo", disabled: !!rev.aplicado, onclick: () => fijarTodos("no") }, "Rechazar todo")) : null));
      if (rev.compartido) sec.append(h("div", { class: "banner info t-meta", id: "v-rev-compartido" }, h("b", {}, "Se escribirá en una carpeta compartida. "),
        "Los cambios que aceptes se escribirán en «" + rev.destino_contexto + "», una carpeta compartida de otra persona, y se añadirá una entrada a 10-registro-de-cambios.md. Revisa cada cambio antes de aceptar. La transcripción no se copia allí."));
      if (rev.carpeta_contexto === false) sec.append(h("div", { class: "banner info t-meta" }, "La carpeta «00. CONTEXTO (IA)» no existe en este proyecto. Si aceptas algún cambio se creará con las plantillas del kit."));
      if (!rev.cambios.length) sec.append(h("p", { class: "t-body soft" }, "Esta reunión no ha generado cambios para el contexto." + (rev.sin_cambios ? " Motivo: " + rev.sin_cambios : "")));
      rev.cambios.forEach((c) => sec.append(bloque(c, !!rev.aplicado)));
    }
    const p2 = panel(2, sec);
    if (rev.aplicado) {
      const a = rev.aplicado;
      p2.append(h("div", { class: "resultado t-body" }, a.aplicados.length
        ? `Aplicados ${a.aplicados.length} cambio(s) en ${a.ficheros.join(", ")}${a.carpeta_creada ? " (carpeta de contexto creada con las plantillas)" : ""}. Entrada añadida a 10-registro-de-cambios.md.`
        : "No se aplicó ningún cambio.", a.omitidos.length ? " No se pudieron aplicar: " + a.omitidos.map((o) => `${o.id} (${o.motivo})`).join("; ") + "." : ""));
    }

    // ---- paso 3: correo de cierre (Copiar y Abrir en Outlook)
    const p3 = panel(3, rev.correo ? seccionCorreo(rev.correo) : h("p", { class: "t-body soft", id: "v-rev-sin-correo" }, "Esta reunión no deja nada cerrado ni abierto que contar, así que no hay borrador de correo."));

    // ---- paso 4: publicar o guardar
    const pub = AP.seccionPublicacion(rev);
    const aceptados = validos.filter((c) => UI.decisiones[c.id] === "si").length;
    const resumenCierre = h("section", { class: "sec rev-cierre", id: "rev-cierre" }, h("span", { class: "t-label" }, "Lo que queda al cerrar"),
      h("ul", { class: "rev-lista" },
        h("li", { class: "t-body" }, `La transcripción y el resumen ya están guardados en ${s.compartido ? "una copia local" : "«" + s.carpeta + "»"}.`),
        s.proyecto ? h("li", { class: "t-body", id: "rev-cierre-cambios" }, rev.aplicado ? "Los cambios aceptados ya se han aplicado al contexto." : aceptados ? `${aceptados} de ${validos.length} cambios aceptados: se aplicarán al contexto del proyecto al pulsar «Aplicar cambios aceptados».` : "No has aceptado ningún cambio: el contexto del proyecto no se toca.") : h("li", { class: "t-body" }, "Sin proyecto, no hay contexto que actualizar."),
        rev.correo ? h("li", { class: "t-body" }, "El correo de cierre es un borrador: la app no envía nada.") : null));
    const p4 = panel(4, resumenCierre, pub);

    const stepper = h("nav", { class: "rev-nav-pasos", "aria-label": "Pasos de la revisión" },
      h("ol", { class: "rev-stepper", id: "rev-stepper" }, PASOS.map(([t], i) => h("li", { class: R.visitados.has(i + 1) && R.paso !== i + 1 ? "visto" : "" },
        h("button", { type: "button", class: "rev-st", "data-paso": String(i + 1), "aria-controls": "rev-paso-" + (i + 1), "aria-current": R.paso === i + 1 ? "step" : null, onclick: () => irAPaso(i + 1, true),
          onkeydown: (ev) => { const d = ev.key === "ArrowRight" ? 1 : ev.key === "ArrowLeft" ? -1 : 0; if (!d) return; const b = $(`#rev-stepper .rev-st[data-paso="${i + 1 + d}"]`); if (b) { ev.preventDefault(); b.focus(); } } },
        h("span", { class: "rev-num", "aria-hidden": "true" }, String(i + 1)), h("span", { class: "rev-st-t" }, h("span", { class: "rev-st-n t-body-m" }, t), h("span", { class: "rev-st-e t-meta", id: "rev-st-e-" + (i + 1) })))))));
    cuerpo.append(stepper, h("div", { class: "rev-paneles" }, p1, p2, p3, p4), h("div", { class: "sr", id: "rev-anuncio", role: "status", "aria-live": "polite" }));
    const nav = $("#rev-nav-b"); if (nav) nav.hidden = false;
    if (AP.montarSesionRevision) AP.montarSesionRevision(gantt);   // el Gantt de la sesión completo, plegado por defecto
    pieEl.hidden = false;
    pie();
    irAPaso(R.paso, false);
  };
})();
