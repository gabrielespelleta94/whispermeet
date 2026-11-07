"use strict";
/* Apuntes: disposición de la pantalla de reunión (DESIGN-visual.md §9). La columna derecha lleva el carril «Ahora» fijo arriba y, debajo, pestañas: lo importante
   primero (Consejos, Insights) y lo secundario detrás (Objetivos, Equipo, Pregúntale, Sesión). Aquí vive el control de pestañas con teclado (flechas, Inicio y Fin),
   los recuentos (solo datos reales) y la preferencia de plegado de las Notas. No toca la sesión ni el análisis: solo muestra u oculta paneles que ya existen. */
(() => {
  const AP = window.AP;
  if (!AP) return;
  const { S, $, $$ } = AP;
  const vista = $("#v-reunion"), barra = $("#r-tabs");
  if (!vista || !barra) return;
  const ORDEN = ["consejos", "insights", "objetivos", "equipo", "pregunta", "sesion"];
  const leer = (k, d) => { try { const v = localStorage.getItem(k); return v == null ? d : v; } catch { return d; } };
  const guardar = (k, v) => { try { localStorage.setItem(k, v); } catch { /* sin almacenamiento */ } };
  let elegida = ORDEN.includes(leer("apuntes_pestana", "")) ? leer("apuntes_pestana", "") : null;   // la que eligió el usuario; sin elección, la principal según haya consejos o no
  let actual = null;
  const vistos = {};

  function activar(nombre, opciones = {}) {
    if (!ORDEN.includes(nombre)) return;
    if (opciones.usuario || opciones.fijar) elegida = nombre;   // una elección (del usuario o de «Ver» en un aviso) deja de ser automática
    if (opciones.usuario) guardar("apuntes_pestana", nombre);
    actual = nombre;
    vista.dataset.tab = nombre;
    $$(".r-tab", barra).forEach((b) => { const on = b.dataset.tab === nombre; b.setAttribute("aria-selected", String(on)); b.tabIndex = on ? 0 : -1; });
    vistos[nombre] = cuentas()[nombre];
    pintarCuentas();
    if (nombre === "sesion" && AP.refrescarSesion) requestAnimationFrame(AP.refrescarSesion);   // la línea de tiempo mide su ancho: solo puede hacerlo con la pestaña a la vista
    if (nombre === "insights" && AP.hooks.pintarInsights) { /* ya pintado: las tarjetas existen aunque la pestaña estuviera oculta */ }
  }
  AP.pestana = (nombre) => activar(nombre, { fijar: true });

  // recuentos: solo lo que ya existe en el estado real
  function cuentas() {
    const a = AP.asesor && AP.asesor.estado ? AP.asesor.estado() : null;
    const consejos = a ? (a.consejos || []).filter((c) => !c.descartado).length : 0;
    const os = S.objetivos || [];
    return { consejos, insights: (S.tarjetas || []).length, objetivos: os.length ? os.filter((o) => o.estado === "cubierto").length + "/" + os.length : 0,
      equipo: S.equipo && S.equipo.turnos ? S.equipo.turnos : 0, pregunta: (S.consultas || []).length, sesion: 0 };
  }
  function pintarCuentas() {
    const c = cuentas();
    for (const k of ORDEN) {
      const n = $("#tab-n-" + k); if (!n) continue;
      const v = c[k] ? String(c[k]) : "";
      if (n.textContent !== v) n.textContent = v;
      // «nuevo»: la pestaña no está a la vista y hay más que la última vez que se miró
      const sinVer = (k === "consejos" || k === "insights") && actual !== k && typeof c[k] === "number" && c[k] > (typeof vistos[k] === "number" ? vistos[k] : 0);
      n.classList.toggle("nuevo", !!sinVer);
    }
    // sin elección del usuario: Consejos si los hay (lo que hay que hacer ahora); si no, Insights (lo que se ha captado)
    if (!elegida) { const auto = c.consejos ? "consejos" : "insights"; if (actual !== auto) activar(auto); }
  }

  barra.addEventListener("click", (ev) => { const b = ev.target.closest(".r-tab"); if (b) activar(b.dataset.tab, { usuario: true }); });
  barra.addEventListener("keydown", (ev) => {
    const i = ORDEN.indexOf(actual);
    const sig = { ArrowRight: ORDEN[(i + 1) % ORDEN.length], ArrowLeft: ORDEN[(i + ORDEN.length - 1) % ORDEN.length], Home: ORDEN[0], End: ORDEN[ORDEN.length - 1] }[ev.key];
    if (!sig) return;
    ev.preventDefault();
    activar(sig, { usuario: true });
    const b = $(`.r-tab[data-tab="${sig}"]`, barra); if (b) b.focus();
  });

  // Notas: plegadas por defecto (la transcripción manda); se recuerda lo que elija el usuario
  const notas = $("#r-notas-det");
  if (notas) {
    notas.open = leer("apuntes_notas_abiertas", "0") === "1";
    notas.addEventListener("toggle", () => guardar("apuntes_notas_abiertas", notas.open ? "1" : "0"));
  }

  const previo = AP.hooks.evento;
  let pendiente = false;
  AP.hooks.evento = (d) => {
    if (previo) previo(d);
    if (pendiente) return;
    pendiente = true;
    requestAnimationFrame(() => { pendiente = false; pintarCuentas(); });
  };
  const reiniciar = AP.hooks.reiniciar;
  AP.hooks.reiniciar = () => { if (reiniciar) reiniciar(); for (const k of ORDEN) delete vistos[k]; pintarCuentas(); };
  pintarCuentas();   // sin elección del usuario decide la primera pasada: Insights hasta que haya consejos
  if (!actual) activar(elegida || "insights");

  // ------------------------------------------------------------ cabecera: en pantallas de menos de 1620 px los ajustes poco usados (Efectos, Modo, Ajustes) pasan a «Más»
  // Son los MISMOS botones (mismos ids y mismos manejadores): solo cambian de sitio, así la cabecera sigue siendo de una sola fila.
  const derecha = $(".top-r");
  const poco = ["#b-efectos", "#b-tema", "#b-ajustes"].map((s) => $(s)).filter(Boolean);
  if (derecha && poco.length === 3 && AP.h) {
    const { h } = AP;
    const panel = h("div", { class: "top-mas-panel", id: "top-mas-panel", hidden: true, role: "group", "aria-label": "Menú: efectos, modo y ajustes" });
    const boton = h("button", { type: "button", class: "btn btn-ghost", id: "b-mas", "aria-haspopup": "true", "aria-expanded": "false", "aria-controls": "top-mas-panel", title: "Efectos, modo claro u oscuro y ajustes" }, "Menú", AP.icono("abajo", "ic-mas"));
    const caja = h("div", { class: "top-mas", id: "top-mas", hidden: true }, boton, panel);
    derecha.append(caja);
    const mq = window.matchMedia("(max-width: 1620px)");
    const abrir = (on) => { panel.hidden = !on; boton.setAttribute("aria-expanded", String(on)); };
    const colocar = () => {
      if (mq.matches) { poco.forEach((b) => panel.append(b)); caja.hidden = false; }
      else { poco.forEach((b) => derecha.insertBefore(b, caja)); caja.hidden = true; abrir(false); }
    };
    boton.addEventListener("click", (ev) => { ev.stopPropagation(); abrir(panel.hidden); });
    document.addEventListener("click", (ev) => { if (!panel.hidden && !ev.target.closest("#top-mas")) abrir(false); });
    document.addEventListener("keydown", (ev) => { if (ev.key === "Escape" && !panel.hidden) { abrir(false); boton.focus(); } });
    panel.addEventListener("click", (ev) => { if (ev.target.closest("#b-ajustes, #b-tema")) abrir(false); });
    mq.addEventListener("change", colocar);
    colocar();
  }
  // ------------------------------------------------------------ cabecera de la reunión: una sola acción principal («Terminar») y el resto en «Más»
  // Menú accesible por teclado: el botón abre con clic, Intro, Espacio o flecha abajo; dentro, flechas arriba y abajo, Inicio y Fin; Esc cierra y devuelve el foco
  // al botón; Tab cierra. Son los MISMOS botones de siempre (mismos ids y manejadores): solo viven dentro del panel, así que Modo reunión, avisos y pruebas no cambian.
  const masBtn = $("#r-mas"), masPanel = $("#r-mas-panel");
  if (masBtn && masPanel) {
    const items = () => $$('[role="menuitem"]', masPanel).filter((b) => !b.disabled && !b.hidden && b.offsetParent !== null);
    const abierto = () => !masPanel.hidden;
    const cerrar = (devolverFoco) => { if (!abierto()) return; masPanel.hidden = true; masBtn.setAttribute("aria-expanded", "false"); if (devolverFoco) masBtn.focus(); };
    const abrir = (foco) => {
      masPanel.hidden = false; masBtn.setAttribute("aria-expanded", "true");
      const l = items();
      if (foco === "ultimo") { if (l.length) l[l.length - 1].focus(); } else if (foco && l.length) l[0].focus();
    };
    masBtn.addEventListener("click", (ev) => { ev.stopPropagation(); if (abierto()) cerrar(false); else abrir(ev.detail === 0 ? "primero" : null); });
    masBtn.addEventListener("keydown", (ev) => {
      if (ev.key === "ArrowDown") { ev.preventDefault(); abrir("primero"); }
      else if (ev.key === "ArrowUp") { ev.preventDefault(); abrir("ultimo"); }
    });
    masPanel.addEventListener("keydown", (ev) => {
      const l = items(), i = l.indexOf(document.activeElement);
      const ir = l.length ? { ArrowDown: l[(i + 1) % l.length], ArrowUp: l[(i - 1 + l.length) % l.length], Home: l[0], End: l[l.length - 1] }[ev.key] : null;
      if (ir) { ev.preventDefault(); ir.focus(); }
      else if (ev.key === "Escape") { ev.preventDefault(); ev.stopPropagation(); cerrar(true); }
      else if (ev.key === "Tab") cerrar(false);
    });
    // elegir una acción cierra el menú (el foco vuelve al botón, salvo que la acción abra su propio panel)
    masPanel.addEventListener("click", (ev) => { if (ev.target.closest('[role="menuitem"]')) cerrar(false); });
    document.addEventListener("click", (ev) => { if (abierto() && !ev.target.closest("#r-mas-caja")) cerrar(false); });
    // «Hallazgos N»: con el botón dentro del menú, el recuento se ve también en «Más»
    const hall = $("#r-bandeja-btn"), nMas = $("#r-mas-n");
    const sincronizarMas = () => {
      const m = hall && /\d+/.exec(hall.textContent || ""), n = m ? Number(m[0]) : 0;
      if (nMas) { nMas.hidden = !n; nMas.textContent = n ? String(n) : ""; }
      masBtn.title = "Analizar ahora, pausa, contexto del proyecto y hallazgos" + (n ? ` (${n} hallazgos)` : "");
    };
    if (hall && typeof MutationObserver === "function") new MutationObserver(sincronizarMas).observe(hall, { childList: true, characterData: true, subtree: true });
    sincronizarMas();
  }
})();
