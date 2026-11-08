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
})();
