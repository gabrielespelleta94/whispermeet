"use strict";
/* WhisperMeet: Ajustes en tres secciones (Audio, Equipo y Privacidad) con pestañas accesibles (flechas, Inicio y Fin), y los dos huecos de Privacidad que conectará otra fase:
   «Modo solo local» (aparece si el servidor manda `config.modo_solo_local`, un booleano) y «Registro de envíos» (aparece si manda `registro_envios` con datos). Sin esos
   datos, quedan ocultos. Los campos y sus nombres no cambian: los lee y los guarda app.js / escucha.js como siempre. */
(() => {
  const AP = window.AP;
  if (!AP) return;
  const { h, $, $$, api } = AP;
  const dlg = $("#d-ajustes");
  if (!dlg) return;
  const tabs = $$(".aj-tab", dlg), secs = $$(".aj-sec", dlg);
  let actual = "audio";

  function ir(nombre, foco) {
    actual = nombre;
    tabs.forEach((t) => { const on = t.dataset.aj === nombre; t.setAttribute("aria-selected", String(on)); t.tabIndex = on ? 0 : -1; if (on && foco) t.focus(); });
    secs.forEach((s) => { s.hidden = s.dataset.aj !== nombre; });
  }
  tabs.forEach((t, i) => {
    t.addEventListener("click", () => ir(t.dataset.aj));
    t.addEventListener("keydown", (ev) => {
      const j = { ArrowRight: (i + 1) % tabs.length, ArrowLeft: (i + tabs.length - 1) % tabs.length, Home: 0, End: tabs.length - 1 }[ev.key];
      if (j == null) return;
      ev.preventDefault();
      ir(tabs[j].dataset.aj, true);
    });
  });
  // Ligero / Potente como control segmentado: el selector sigue siendo el que se guarda (oculto) y los botones lo espejan
  const segmentados = new Map();
  $$("select.sel-modelo", dlg).forEach((sel) => {
    const op = [...sel.options].slice(0, 2);
    const grupo = h("div", { class: "seg-mod", role: "radiogroup", "aria-label": (sel.closest("label") && sel.closest("label").firstChild.textContent.trim()) || "Modelo" },
      op.map((o) => h("button", { type: "button", role: "radio", "data-v": o.value, "aria-checked": "false", onclick: () => { sel.value = o.value; sel.dispatchEvent(new Event("change", { bubbles: true })); sync(sel); } }, o.textContent)));
    sel.hidden = true;
    sel.after(grupo);
    segmentados.set(sel, grupo);
  });
  function sync(sel) { const g = segmentados.get(sel); if (g) [...g.children].forEach((b) => b.setAttribute("aria-checked", String(b.dataset.v === sel.value))); }
  const fijar0 = AP.fijarModelo;
  if (fijar0) AP.fijarModelo = (sel, v) => { fijar0(sel, v); sync(sel); };
  dlg.addEventListener("close", () => segmentados.forEach((_, s) => sync(s)));
  segmentados.forEach((_, s) => sync(s));
  AP.ajustes = { ir, seccion: () => actual, secciones: () => tabs.map((t) => t.dataset.aj) };

  // «Modo solo local» y «Registro de envíos»: los pinta olas34.js con /api/modo-local y /api/envios. Aquí solo se vuelve a la primera sección al abrir.
  const previoAbrir = AP.hooks.ajustesAbrir;
  AP.hooks.ajustesAbrir = (info, f) => { ir("audio"); if (previoAbrir) previoAbrir(info, f); };

  // ------------------------------------------------------------ ola D: ajustes que antes solo estaban en el fichero
  // Carpeta de Knowledge, vocabulario de transcripción y ancho de búsqueda de Whisper. Solo se envía lo que ha cambiado; el servidor valida (tipos, topes, que la carpeta
  // exista y no sea de secretos) y contesta con el CAMPO del error (`datos.campo`): se pinta junto a ese campo, en su sección, y el foco va a él.
  const NUEVOS = {
    whisper_beam: { sec: "audio", entrada: "[name=whisper_beam]", error: "#aj-beam-error" },
    vocabulario_transcripcion: { sec: "audio", entrada: "#aj-vocab", error: "#aj-vocab-error" },
    knowledge: { sec: "privacidad", entrada: "#aj-knowledge", error: "#aj-knowledge-error" },
    // la raíz y el modelo no son nuevos, pero durante una reunión el servidor rechaza su CAMBIO con el campo: se pinta junto a ellos
    raiz_proyectos: { sec: "privacidad", entrada: "[name=raiz_proyectos]", error: "#aj-raiz-error" },
    whisper_modelo: { sec: "audio", entrada: "[name=whisper_modelo]", error: "#aj-modelo-error" },
  };
  const inicial = { beam: null, vocab: "[]", knowledge: "" };
  const terminos = () => $("#aj-vocab").value.split(/\r?\n/).map((s) => s.trim()).filter(Boolean);
  function limpiarErroresNuevos() {
    Object.values(NUEVOS).forEach((d) => { const e = $(d.error, dlg), i = $(d.entrada, dlg); if (e) { e.hidden = true; e.textContent = ""; } if (i) i.removeAttribute("aria-invalid"); });
  }
  function cuentaVocab() { const n = terminos().length; $("#aj-vocab-cuenta").textContent = `${n} de 60 términos.`; }
  const entradasNuevas = [$("#aj-vocab"), $("[name=whisper_beam]", dlg), $("#aj-knowledge"), $("[name=raiz_proyectos]", dlg), $("[name=whisper_modelo]", dlg)];
  entradasNuevas.forEach((i) => i && i.addEventListener("input", () => {
    const def = Object.values(NUEVOS).find((d) => $(d.entrada, dlg) === i);
    if (def) { const e = $(def.error, dlg); e.hidden = true; i.removeAttribute("aria-invalid"); }
    if (i.id === "aj-vocab") cuentaVocab();
  }));
  const abrirPrevio = AP.hooks.ajustesAbrir;
  AP.hooks.ajustesAbrir = (info, f) => {
    if (abrirPrevio) abrirPrevio(info, f);
    const c = (info && info.config) || {};
    f.whisper_beam.value = c.whisper_beam == null ? "" : c.whisper_beam;
    const lista = Array.isArray(c.vocabulario_transcripcion) ? c.vocabulario_transcripcion : [];
    $("#aj-vocab").value = lista.join("\n");
    f.knowledge.value = c.knowledge || "";
    inicial.beam = c.whisper_beam == null ? null : c.whisper_beam; inicial.vocab = JSON.stringify(lista); inicial.knowledge = c.knowledge || "";
    limpiarErroresNuevos(); cuentaVocab();
  };
  const guardarPrevio = AP.hooks.ajustesGuardar;
  AP.hooks.ajustesGuardar = (f) => {
    const cambios = guardarPrevio ? guardarPrevio(f) : {};
    limpiarErroresNuevos();
    const crudo = f.whisper_beam.value.trim();
    const beam = crudo === "" ? null : Number(crudo);
    if (beam !== inicial.beam) cambios.whisper_beam = beam;
    const lista = terminos();
    if (JSON.stringify(lista) !== inicial.vocab) cambios.vocabulario_transcripcion = lista;
    const k = f.knowledge.value.trim();
    if (k !== inicial.knowledge) cambios.knowledge = k;
    return cambios;
  };
  AP.hooks.ajustesError = (e) => {
    const d = NUEVOS[e && e.datos && e.datos.campo];
    if (!d) return false;
    const msg = $(d.error, dlg), entrada = $(d.entrada, dlg);
    $("#s-error").hidden = true;
    msg.textContent = e.message; msg.hidden = false;
    entrada.setAttribute("aria-invalid", "true");
    ir(d.sec);
    entrada.focus();
    return true;
  };
  // «Elegir carpeta…» para Knowledge: el mismo selector nativo que las carpetas de proyecto (solo con ventana nativa); solo rellena la ruta, no guarda nada
  const elegirK = $("#aj-knowledge-elegir");
  if (elegirK) {
    api("GET", "/api/ventana").then((v) => { if (v && v.nativa) elegirK.hidden = false; }).catch(() => { /* sin ventana nativa: ruta a mano */ });
    elegirK.addEventListener("click", async () => {
      const texto = elegirK.textContent;
      elegirK.disabled = true; elegirK.textContent = "Abriendo el selector…";
      try {
        const r = await api("POST", "/api/ventana/elegir-carpeta");
        if (!r.cancelado) { $("#aj-knowledge").value = r.ruta; $("#aj-knowledge").dispatchEvent(new Event("input", { bubbles: true })); }
      } catch (e) { AP.hooks.ajustesError({ message: e.message, datos: { campo: "knowledge" } }); }
      finally { elegirK.disabled = false; elegirK.textContent = texto; }
    });
  }
})();
