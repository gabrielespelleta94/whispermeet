"use strict";
/* Apuntes: Modo reunión (DESIGN-agentico.md). La ventana nativa pasa a ocupar el área de trabajo, siempre encima, y el backend
   (`apuntes/ventana.py`, `SetWindowRgn`) deja solo los paneles: el hueco central es de lo que haya debajo (Teams) y recibe los clics.
   Aquí solo está la interfaz: el cálculo de medidas y de región es del backend (`apuntes/modo_reunion.py`); la página pide,
   aplica lo que devuelve y recuerda las medidas. No corta la grabación ni el análisis: no toca la sesión. */
(() => {
  const AP = window.AP;
  if (!AP) return;
  const { h, $, $$, api } = AP;
  const body = document.body, raiz = document.documentElement;
  const MIN_LATERAL = 280;
  const MOVER = ["r-rec", "r-reloj", "r-obj-prog", "r-analizar", "r-bandeja-btn"];   // los mandos esenciales de la cabecera viajan a la barra del panel y vuelven al salir

  const M = { nativa: false, activo: false, ocupado: false, layout: null, prefs: {}, deseo: { izq: null, der: null, uno: null }, tocado: {},
    lugares: new Map(), enviando: false, pendiente: null, arrastre: null, opacidadOk: true, pctOpacidad: 100, tab: "trans" };
  AP.modoReunion = M;

  const err = (e) => { if (AP.alerta) AP.alerta(e); else console.error(e); };

  // Sin opacidad soportada se oculta solo su control: el botón «Hallazgos N» comparte la fila
  const ocultarOpacidad = (v) => $$("#mr-opac-campo > :not(#r-bandeja-btn)").forEach((e) => { e.hidden = v; });

  // ------------------------------------------------------------ DOM del modo
  function montarDom(on) {
    if (on) {
      body.dataset.modo = "reunion";
      const f1 = $("#mr-f1");
      for (const id of MOVER) {
        const e = $("#" + id);
        if (!e || M.lugares.has(id)) continue;
        const marca = document.createComment("mr-" + id);
        e.replaceWith(marca);
        M.lugares.set(id, marca);
        (id === "r-bandeja-btn" ? $("#mr-opac-campo") : f1).append(e);   // «Hallazgos N» va en la segunda fila de la barra, junto a la opacidad
      }
      f1.append($("#mr-salir"));
      $("#mr-barra").hidden = false;
    } else {
      for (const [id, marca] of M.lugares) { const e = $("#" + id); if (e && marca.parentNode) marca.replaceWith(e); }
      M.lugares.clear();
      $("#mr-barra").hidden = true;
      $("#mr-div-izq").hidden = $("#mr-div-der").hidden = true;
      delete body.dataset.modo; delete body.dataset.mr;
      raiz.style.removeProperty("--mr-izq"); raiz.style.removeProperty("--mr-der");
    }
    if (AP.aplicarPliegueOrq) AP.aplicarPliegueOrq();   // la orquestación va plegada a su línea de 32 px mientras dura el modo
  }

  function aplicarLayout(l) {
    M.layout = l;
    raiz.style.setProperty("--mr-izq", l.izq + "px");
    raiz.style.setProperty("--mr-der", l.der + "px");
    body.dataset.mr = l.modo;
    $("#mr-div-izq").hidden = l.modo !== "dos";
    $("#mr-div-der").hidden = false;
    $("#mr-tabs").hidden = l.modo !== "uno";
    if (l.modo === "uno") mostrarTab(M.tab); else delete body.dataset.mrTab;
    $("#mr-div-izq").setAttribute("aria-valuenow", String(l.izq));
    $("#mr-div-der").setAttribute("aria-valuenow", String(l.der));
    $("#mr-div-der").setAttribute("aria-label", l.modo === "uno" ? "Ancho del panel" : "Ancho del panel de avisos");
  }

  function mostrarTab(t) {
    M.tab = t;
    body.dataset.mrTab = t;
    $$("#mr-tabs button").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.tab === t)));
  }

  function aplicarEstado(r) {
    if (r.layout) aplicarLayout(r.layout);
    if (r.opacidad != null) { M.pctOpacidad = r.opacidad; $("#mr-opac").value = String(r.opacidad); $("#mr-opac-v").textContent = r.opacidad + " %"; }
    M.opacidadOk = r.opacidad_soportada !== false;
    ocultarOpacidad(!M.opacidadOk);
  }

  // ------------------------------------------------------------ comunicación con el backend (una petición en vuelo; gana la última)
  const cuerpo = (activo, guardar) => {
    const c = { activo, izq: M.deseo.izq, der: M.deseo.der, uno: M.deseo.uno, dpr: window.devicePixelRatio, guardar: !!guardar, solo_actualizar: activo && M.activo };
    if (guardar) for (const k of ["izq", "der", "uno"]) if (!M.tocado[k]) c[k] = null;   // solo se recuerda lo que el usuario ha movido
    return c;
  };
  function enviar(guardar) {
    if (!M.activo) return;
    M.pendiente = { guardar: !!guardar || !!(M.pendiente && M.pendiente.guardar) };
    if (!M.enviando) bucle();
  }
  async function bucle() {
    M.enviando = true;
    while (M.pendiente && M.activo) {
      const p = M.pendiente; M.pendiente = null;
      try { aplicarEstado(await api("POST", "/api/ventana/modo-reunion", cuerpo(true, p.guardar))); } catch (e) { err(e); }
    }
    M.enviando = false;
  }

  async function entrar() {
    if (M.activo || M.ocupado || !M.nativa) return;
    M.ocupado = true;
    try {
      montarDom(true);
      const r = await api("POST", "/api/ventana/modo-reunion", { ...cuerpo(true, false), izq: M.prefs.izq ?? null, der: M.prefs.der ?? null, uno: M.prefs.uno ?? null });
      M.activo = true;
      for (const k of ["izq", "der", "uno"]) M.deseo[k] = M.prefs[k] ?? null;
      aplicarEstado(r);
      $("#mr-entrar").setAttribute("aria-pressed", "true");
      $("#mr-salir").focus();
    } catch (e) { montarDom(false); err(e); }
    M.ocupado = false;
  }

  async function salir() {
    if (!M.activo || M.ocupado) return;
    M.ocupado = true; M.activo = false; M.pendiente = null;
    try { await api("POST", "/api/ventana/modo-reunion", { activo: false }); } catch (e) { err(e); }
    montarDom(false);
    $("#mr-entrar").setAttribute("aria-pressed", "false");
    $("#mr-entrar").focus();
    M.ocupado = false;
  }

  // ------------------------------------------------------------ divisores (ratón y teclado)
  function ponerAncho(lado, px) {
    const l = M.layout; if (!l) return;
    const clave = l.modo === "uno" ? "uno" : lado;
    M.deseo[clave] = Math.round(px); M.tocado[clave] = true;
    // vista previa inmediata; el backend devuelve la medida acotada de verdad
    const max = Math.max(MIN_LATERAL, window.innerWidth - (l.modo === "uno" ? 0 : lado === "izq" ? l.der : l.izq) - (l.modo === "uno" ? 0 : 320));
    const v = Math.max(MIN_LATERAL, Math.min(max, Math.round(px)));
    raiz.style.setProperty(lado === "izq" ? "--mr-izq" : "--mr-der", v + "px");
    enviar(false);
  }
  function divisor(el, lado) {
    let agarre = 0;   // dónde se agarró el divisor respecto a su borde, para que el panel no salte al empezar
    const borde = () => (lado === "izq" ? M.layout.izq : window.innerWidth - M.layout.der);
    el.addEventListener("pointerdown", (e) => { M.arrastre = lado; agarre = e.clientX - borde(); el.setPointerCapture(e.pointerId); el.classList.add("arrastrando"); e.preventDefault(); });
    el.addEventListener("pointermove", (e) => {
      if (M.arrastre !== lado) return;
      const x = e.clientX - agarre;
      ponerAncho(lado, lado === "izq" ? x : window.innerWidth - x);
    });
    const soltar = () => { if (M.arrastre !== lado) return; M.arrastre = null; el.classList.remove("arrastrando"); enviar(true); };
    el.addEventListener("pointerup", soltar);
    el.addEventListener("pointercancel", soltar);
    el.addEventListener("keydown", (e) => {
      const paso = e.shiftKey ? 64 : 16;
      if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
      e.preventDefault();
      const l = M.layout, actual = lado === "izq" ? l.izq : l.der;
      const crece = (e.key === "ArrowRight") === (lado === "izq");
      ponerAncho(lado, actual + (crece ? paso : -paso));
      enviar(true);
    });
  }

  // ------------------------------------------------------------ opacidad
  let opacEnVuelo = false, opacPend = null;
  async function enviarOpacidad(pct, guardar) {
    opacPend = { pct, guardar: guardar || (opacPend && opacPend.guardar) };
    if (opacEnVuelo) return;
    opacEnVuelo = true;
    while (opacPend) {
      const p = opacPend; opacPend = null;
      try { const r = await api("POST", "/api/ventana/opacidad", p); if (r.opacidad_soportada === false) { M.opacidadOk = false; ocultarOpacidad(true); } } catch (e) { err(e); }
    }
    opacEnVuelo = false;
  }

  // ------------------------------------------------------------ arranque
  function arrancar() {
    $("#mr-entrar").addEventListener("click", entrar);
    $("#mr-salir").addEventListener("click", salir);
    divisor($("#mr-div-izq"), "izq");
    divisor($("#mr-div-der"), "der");
    $$("#mr-tabs button").forEach((b) => b.addEventListener("click", () => mostrarTab(b.dataset.tab)));
    const opac = $("#mr-opac");
    opac.addEventListener("input", () => { $("#mr-opac-v").textContent = opac.value + " %"; enviarOpacidad(Number(opac.value), false); });
    opac.addEventListener("change", () => enviarOpacidad(Number(opac.value), true));
    // al cambiar el tamaño de la ventana o la escala de Windows se recalcula la región
    window.addEventListener("resize", () => enviar(false));
    const vigilarDpr = () => {
      const mq = window.matchMedia(`(resolution: ${window.devicePixelRatio}dppx)`);
      mq.addEventListener("change", () => { enviar(false); vigilarDpr(); }, { once: true });
    };
    vigilarDpr();
    // al terminar la reunión (o salir de la vista) el modo se cierra solo y la ventana vuelve a como estaba
    new MutationObserver(() => { if (M.activo && body.dataset.vista !== "reunion") salir(); }).observe(body, { attributes: true, attributeFilter: ["data-vista"] });
    // desde un chip de minuto del panel de insights con un solo panel hay que ver la transcripción
    const previo = AP.hooks.irAlMinuto;
    AP.hooks.irAlMinuto = (seg) => { if (M.activo && M.layout && M.layout.modo === "uno") mostrarTab("trans"); if (previo) previo(seg); };
  }

  async function iniciar() {
    arrancar();
    try {
      const r = await api("GET", "/api/ventana");
      M.nativa = !!r.nativa;
      M.prefs = r.prefs || {};
      M.opacidadOk = r.opacidad_soportada !== false;
      if (r.activo) { M.activo = true; montarDom(true); aplicarEstado(r); }
    } catch { M.nativa = false; }
    $("#mr-entrar").hidden = !M.nativa;   // sin ventana nativa (--sin-ventana) el botón no existe
  }
  iniciar();
})();
