"use strict";
/* WhisperMeet: Ajustes en tres secciones (Audio, Equipo y Privacidad) con pestañas accesibles (flechas, Inicio y Fin), y los dos huecos de Privacidad que conectará otra fase:
   «Modo solo local» (aparece si el servidor manda `config.modo_solo_local`, un booleano) y «Registro de envíos» (aparece si manda `registro_envios` con datos). Sin esos
   datos, quedan ocultos. Los campos y sus nombres no cambian: los lee y los guarda app.js / escucha.js como siempre. */
(() => {
  const AP = window.AP;
  if (!AP) return;
  const { h, $, $$ } = AP;
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
  AP.ajustes = { ir, seccion: () => actual, secciones: () => tabs.map((t) => t.dataset.aj) };

  // Privacidad: los dos huecos. Solo se enseñan con datos reales del servidor.
  let hayLocal = false;
  AP.hooks.ajustesAbrir = (info, f) => {
    ir("audio");
    const c = (info && info.config) || {};
    const caja = $("#aj-solo-local");
    hayLocal = typeof c.modo_solo_local === "boolean";
    if (caja) { caja.hidden = !hayLocal; if (hayLocal && f.modo_solo_local) f.modo_solo_local.checked = c.modo_solo_local; }
    const reg = (info && info.registro_envios) || c.registro_envios;
    const sec = $("#aj-registro-envios"), lista = $("#aj-registro-lista");
    const filas = Array.isArray(reg) ? reg : [];
    if (sec) sec.hidden = !filas.length;
    if (lista) lista.replaceChildren(...filas.slice(-50).reverse().map((e) => h("div", { class: "aj-reg-f t-meta" },
      h("span", { class: "aj-reg-h" }, e.hora || e.t || ""), h("span", { class: "aj-reg-d" }, e.destino || e.para || ""), h("span", { class: "aj-reg-q" }, e.que || e.tipo || e.texto || ""))));
  };
  AP.hooks.ajustesGuardar = (f) => (hayLocal && f.modo_solo_local ? { modo_solo_local: f.modo_solo_local.checked } : {});
})();
