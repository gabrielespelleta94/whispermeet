"use strict";
/* WhisperMeet: paleta de comandos (Ctrl+K, o Cmd+K, en TODA la app). Un diálogo modal accesible (role combobox + listbox; Esc cierra y devuelve el foco), búsqueda difusa sin
   acentos ni mayúsculas, flechas para moverse e Intro para ejecutar. Los comandos son los MISMOS mandos de siempre (se pulsan sus botones): la paleta no hace nada que la
   interfaz no pueda hacer, y solo ofrece lo que tiene sentido ahora (según la vista: inicio, reunión o revisión). «/» sigue enfocando el buscador de la galería. */
(() => {
  const AP = window.AP;
  if (!AP) return;
  const { S, UI, h, $ } = AP;
  const vista = () => document.body.dataset.vista || "inicio";
  const norm = (t) => String(t || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
  const visible = (el) => !!el && !el.hidden && !el.disabled && el.getBoundingClientRect !== undefined;
  const pulsar = (sel) => () => { const b = $(sel); if (b) b.click(); };
  const hayBoton = (sel) => () => { const b = $(sel); return !!b && !b.hidden && !b.disabled; };
  const leerTema = () => { try { return localStorage.getItem("apuntes_tema") || "auto"; } catch { return "auto"; } };
  const NOMBRE_TEMA = { auto: "automático", claro: "claro", oscuro: "oscuro" };
  function ponerTema(t) {   // el botón del tema da una vuelta: auto, claro, oscuro. Se pulsa hasta llegar (como mucho 3 veces)
    for (let i = 0; i < 3 && leerTema() !== t; i++) $("#b-tema").click();
  }
  const enReunion = () => vista() === "reunion";

  // ------------------------------------------------------------ catálogo de comandos (se vuelve a calcular al abrir: lo disponible depende del momento)
  function comandos() {
    const v = vista();
    const L = [];
    const add = (c) => { if (c.si === undefined || c.si()) L.push(c); };
    // --- empezar y terminar
    if (v === "inicio") {
      const etapa = AP.proyectos && AP.proyectos.estado ? AP.proyectos.estado().etapa : "galeria";
      if (etapa === "preparar") add({ id: "empezar", titulo: "Empezar la reunión", grupo: "Reunión", icono: "empezar", palabras: "grabar transcribir iniciar comenzar", si: hayBoton("#i-empezar"), accion: pulsar("#i-empezar") });
      else if (typeof UI.sel === "string" && AP.proyectos) add({ id: "empezar", titulo: `Empezar una reunión en ${UI.sel}`, grupo: "Reunión", icono: "empezar", palabras: "grabar transcribir iniciar comenzar preparar", accion: () => AP.proyectos.empezarEn(UI.sel) });
      add({ id: "empezar-bandeja", titulo: "Empezar una reunión sin proyecto", grupo: "Reunión", icono: "empezar", palabras: "bandeja grabar transcribir iniciar", si: () => !!AP.elegirProyecto && !!AP.proyectos,
        accion: () => { AP.elegirProyecto(null, null); AP.proyectos.etapa("preparar"); const t = $("#i-tema"); if (t) t.focus({ preventScroll: true }); } });
      add({ id: "cartera", titulo: "Ver la cartera de proyectos", grupo: "Ir a", icono: "cartera", palabras: "salud riesgos pendientes antiguos atención", si: () => !!$('#i-modo [data-modo="cartera"]'), accion: () => { if (AP.proyectos) AP.proyectos.etapa("galeria"); const b = $('#i-modo [data-modo="cartera"]'); if (b) b.click(); } });
      add({ id: "galeria", titulo: "Ir a la galería de proyectos", grupo: "Ir a", icono: "rejilla", palabras: "inicio proyectos cambiar elegir", si: () => !!AP.proyectos && AP.proyectos.estado().etapa !== "galeria", accion: () => AP.proyectos.etapa("galeria") });
      add({ id: "buscar-proyecto", titulo: "Buscar entre los proyectos", grupo: "Ir a", icono: "buscar", palabras: "filtrar galeria", si: () => !!AP.proyectos, accion: () => { AP.proyectos.etapa("galeria"); const b = $("#i-buscar"); if (b) { b.focus(); b.select(); } } });
    }
    if (v === "reunion") {
      const pausada = S.estado === "pausada";
      add({ id: "terminar", titulo: "Terminar la reunión", grupo: "Reunión", icono: "parar", palabras: "acabar cerrar finalizar revisión", si: hayBoton("#r-terminar"), accion: pulsar("#r-terminar") });
      add({ id: "pausa", titulo: pausada ? "Reanudar la grabación" : "Pausar la grabación", grupo: "Reunión", icono: pausada ? "empezar" : "pausa", palabras: "pausa reanudar continuar parar", si: hayBoton("#r-pausa"), accion: pulsar("#r-pausa") });
      add({ id: "analizar", titulo: "Analizar ahora", grupo: "Reunión", icono: "rayo", palabras: "análisis pedir equipo avisos ya", si: hayBoton("#r-analizar"), accion: pulsar("#r-analizar") });
      add({ id: "modo-reunion", titulo: "Modo reunión (paneles compactos)", grupo: "Reunión", icono: "pantalla", palabras: "compacto teams paneles laterales", si: hayBoton("#mr-entrar"), accion: pulsar("#mr-entrar") });
      add({ id: "t-avisos", titulo: "Ver los avisos", grupo: "Ir a", icono: "aviso", palabras: "consejos insights tarjetas", si: () => !!AP.pestana, accion: () => AP.pestana("avisos") });
      add({ id: "t-pregunta", titulo: "Preguntar al asistente (Pregúntale)", grupo: "Ir a", icono: "pregunta", palabras: "consulta pregunta duda", si: () => !!AP.pestana,
        accion: () => { AP.pestana("pregunta"); const i = $('#f-pregunta input[name="pregunta"]'); if (i) setTimeout(() => i.focus(), 0); } });
      add({ id: "t-sesion", titulo: "Ver la línea de tiempo de la sesión", grupo: "Ir a", icono: "reloj", palabras: "gantt cronología sesión", si: () => !!AP.pestana, accion: () => AP.pestana("sesion") });
      add({ id: "objetivos", titulo: "Añadir un objetivo propio", grupo: "Reunión", icono: "objetivo", palabras: "objetivo meta", accion: () => { const i = $("#r-obj-nuevo"); if (i) i.focus(); } });
      add({ id: "nota", titulo: "Anotar algo con el minuto actual", grupo: "Reunión", icono: "tu", palabras: "nota comentario idea anotación", accion: () => { const d = $("#r-notas-det"); if (d) d.open = true; const i = $("#r-rapida-t"); if (i) i.focus(); } });
      add({ id: "hallazgos", titulo: "Abrir Hallazgos", grupo: "Ir a", icono: "lista", palabras: "todo decisiones pendientes riesgos preguntas", si: hayBoton("#r-bandeja-btn"), accion: pulsar("#r-bandeja-btn") });
      add({ id: "contexto", titulo: "Ver el contexto del proyecto", grupo: "Ir a", icono: "carpeta", palabras: "ficheros gantt checks drawer", si: hayBoton("#r-contexto"), accion: pulsar("#r-contexto") });
    }
    if (v === "revision") {
      const R = AP.revision;
      (R ? R.pasos : []).forEach((t, i) => add({ id: "paso-" + (i + 1), titulo: `Revisión, paso ${i + 1}: ${t}`, grupo: "Revisión", icono: "check", palabras: "ir revisión paso " + t, accion: () => R.irAPaso(i + 1) }));
      add({ id: "aplicar", titulo: "Aplicar los cambios aceptados al contexto", grupo: "Revisión", icono: "carpeta", palabras: "guardar escribir contexto", si: () => { const b = $("#v-rev-aplicar"); return !!b && !b.hidden && !b.disabled; }, accion: pulsar("#v-rev-aplicar") });
      add({ id: "copiar-correo", titulo: "Copiar el correo de cierre", grupo: "Revisión", icono: "correo", palabras: "mail email portapapeles", si: () => !!$("#v-rev-correo-copiar"), accion: () => { R.irAPaso(3); setTimeout(() => { const b = $("#v-rev-correo-copiar"); if (b) b.click(); }, 0); } });
      add({ id: "outlook", titulo: "Abrir el correo de cierre en Outlook", grupo: "Revisión", icono: "correo", palabras: "mail email borrador", si: () => { const b = $("#v-rev-correo-outlook"); return !!b && !b.hidden; }, accion: () => { R.irAPaso(3); setTimeout(() => { const b = $("#v-rev-correo-outlook"); if (b && !b.hidden) b.focus(); }, 0); } });
      add({ id: "cerrar-rev", titulo: "Cerrar la revisión", grupo: "Revisión", icono: "cerrar", palabras: "salir terminar volver", si: hayBoton("#v-rev-cerrar"), accion: pulsar("#v-rev-cerrar") });
    }
    // --- proyectos (no con una reunión en curso ni en la revisión: primero hay que cerrarlas)
    if (v === "inicio" && AP.proyectos) {
      for (const p of UI.proyectos || []) add({ id: "p:" + p.nombre, titulo: `Abrir el proyecto ${p.nombre}`, grupo: "Proyecto", icono: "carpeta", palabras: "proyecto ficha " + (p.descripcion || ""), accion: () => { AP.proyectos.etapa("galeria"); AP.proyectos.abrirPanel(p.nombre, document.activeElement); } });
    }
    // --- siempre
    add({ id: "sesiones", titulo: "Sesiones y pendientes", grupo: "Ir a", icono: "lista", palabras: "backlog historial pasadas pendientes ideas decisiones", si: hayBoton("#b-sesiones"), accion: pulsar("#b-sesiones") });
    add({ id: "ajustes", titulo: "Ajustes", grupo: "Ir a", icono: "ajustes", palabras: "configuración opciones audio equipo privacidad modelos", si: hayBoton("#b-ajustes"), accion: pulsar("#b-ajustes") });
    add({ id: "registro", titulo: "Registro de las llamadas del equipo", grupo: "Ir a", icono: "lista", palabras: "orquestación llamadas tokens", si: () => !!AP.abrirRegistro && !!$("#orq") && !$("#orq").hidden, accion: () => AP.abrirRegistro() });
    add({ id: "detalle", titulo: "Abrir u ocultar el detalle del equipo", grupo: "Ir a", icono: "monitor", palabras: "orquestación agentes capitán lupa arquitecto auditor sherpa", si: () => !!AP.detalleEquipo && !!$("#orq") && !$("#orq").hidden && document.body.dataset.vista === "reunion", accion: () => AP.detalleEquipo() });
    add({ id: "flujo", titulo: "Plegar o desplegar el flujo de agentes", grupo: "Ir a", icono: "monitor", palabras: "orquestación flujo banda agentes", si: () => !!$("#orq-plegar") && !!$("#orq") && !$("#orq").hidden, accion: pulsar("#orq-plegar") });
    add({ id: "tema", titulo: `Cambiar el tema (ahora ${NOMBRE_TEMA[leerTema()] || "automático"})`, grupo: "Aspecto", icono: "tema", palabras: "claro oscuro modo color", accion: pulsar("#b-tema") });
    for (const [k, n] of [["claro", "Tema claro"], ["oscuro", "Tema oscuro"], ["auto", "Tema automático"]]) add({ id: "tema-" + k, titulo: n, grupo: "Aspecto", icono: "tema", palabras: "modo color apariencia", si: () => leerTema() !== k, accion: () => ponerTema(k) });
    add({ id: "modo-local", titulo: "Modo solo local: activar o desactivar", grupo: "Privacidad", icono: "candado", palabras: "privacidad claude enviar nada local", si: () => !!(AP.olas34),
      accion: async () => { const l = AP.olas34.estado.local; try { await AP.api("POST", "/api/modo-local", { activo: !(l && l.activo) }); } catch (e) { AP.avisarError(e); } } });
    add({ id: "captura", titulo: "Ocultar o mostrar la ventana al compartir pantalla", grupo: "Privacidad", icono: "pantalla", palabras: "captura compartir excluir privacidad", si: hayBoton("#b-captura"), accion: pulsar("#b-captura") });
    return L;
  }

  // ------------------------------------------------------------ búsqueda difusa
  /** Cada palabra de la consulta tiene que aparecer: como trozo seguido del título (mejor si empieza una palabra), como letras en orden dentro del título o en las palabras clave. */
  function puntuar(consulta, c) {
    const t = norm(c.titulo), clave = norm(c.palabras || "") + " " + norm(c.grupo);
    const marcas = new Set();
    let total = 0;
    for (const w of norm(consulta).split(/\s+/).filter(Boolean)) {
      const i = t.indexOf(w);
      if (i >= 0) { total += 100 - Math.min(i, 60) + (i === 0 || t[i - 1] === " " ? 40 : 0) + w.length; for (let k = 0; k < w.length; k++) marcas.add(i + k); continue; }
      let j = 0, racha = 0, mejor = 0; const m = [];
      for (let k = 0; k < t.length && j < w.length; k++) if (t[k] === w[j]) { m.push(k); racha = j && m[j - 1] === k - 1 ? racha + 1 : 0; mejor += 3 + racha * 4 + (k === 0 || t[k - 1] === " " ? 6 : 0); j++; }
      if (j === w.length) { total += 20 + mejor; m.forEach((k) => marcas.add(k)); continue; }
      if (clave.includes(w)) { total += 25; continue; }
      return null;
    }
    return { total, marcas };
  }
  const resaltar = (texto, marcas) => {
    if (!marcas || !marcas.size) return [texto];
    const out = []; let buf = "", on = false;
    const norma = [...String(texto)];   // el índice de las marcas va sobre el título sin acentos, que conserva la longitud carácter a carácter
    norma.forEach((ch, i) => { const m = marcas.has(i); if (m !== on) { if (buf) out.push(on ? h("mark", {}, buf) : buf); buf = ""; on = m; } buf += ch; });
    if (buf) out.push(on ? h("mark", {}, buf) : buf);
    return out;
  };

  // ------------------------------------------------------------ el diálogo
  const P = { dlg: null, q: null, lista: null, estado: null, items: [], sel: 0, previo: null, todos: [] };
  function construir() {
    if (P.dlg) return;
    P.q = h("input", { id: "paleta-q", class: "pal-q", type: "text", role: "combobox", "aria-expanded": "true", "aria-controls": "paleta-lista", "aria-autocomplete": "list", "aria-activedescendant": "", "aria-label": "Buscar una acción o un proyecto",
      placeholder: "Escribe lo que quieres hacer…", autocomplete: "off", spellcheck: "false" });
    P.lista = h("ul", { id: "paleta-lista", class: "pal-lista", role: "listbox", "aria-label": "Acciones disponibles" });
    P.estado = h("div", { id: "paleta-estado", class: "pal-pie t-meta", role: "status", "aria-live": "polite" });
    P.dlg = h("dialog", { id: "paleta", class: "paleta", "aria-label": "Paleta de comandos" },
      h("div", { class: "pal-cab" }, AP.icono("buscar", "pal-ic"), P.q, h("span", { class: "pal-esc t-meta" }, "Esc")), P.lista, P.estado);
    document.body.append(P.dlg);
    P.q.addEventListener("input", () => { P.sel = 0; pintar(); });
    P.q.addEventListener("keydown", (ev) => {
      if (ev.key === "ArrowDown") { ev.preventDefault(); mover(1); }
      else if (ev.key === "ArrowUp") { ev.preventDefault(); mover(-1); }
      else if (ev.key === "Home" && ev.ctrlKey) { ev.preventDefault(); P.sel = 0; marcar(); }
      else if (ev.key === "PageDown") { ev.preventDefault(); mover(5); }
      else if (ev.key === "PageUp") { ev.preventDefault(); mover(-5); }
      else if (ev.key === "Enter" && !ev.isComposing) { ev.preventDefault(); ejecutar(P.items[P.sel]); }
    });
    P.dlg.addEventListener("keydown", (ev) => {
      if (ev.key === "Tab") { ev.preventDefault(); P.q.focus(); }   // el foco no sale del campo: la lista se maneja con las flechas
      else if (ev.key === "Escape") { ev.preventDefault(); ev.stopPropagation(); cerrar(); }
    });
    P.dlg.addEventListener("cancel", (ev) => { ev.preventDefault(); cerrar(); });
    P.dlg.addEventListener("mousedown", (ev) => { if (ev.target === P.dlg) cerrar(); });   // clic fuera
    P.lista.addEventListener("mousemove", (ev) => { const li = ev.target.closest("[role=option]"); if (li && Number(li.dataset.i) !== P.sel) { P.sel = Number(li.dataset.i); marcar(); } });
    P.lista.addEventListener("click", (ev) => { const li = ev.target.closest("[role=option]"); if (li) ejecutar(P.items[Number(li.dataset.i)]); });
  }
  function filtrar() {
    const q = P.q.value.trim();
    if (!q) { const orden = [...new Set(P.todos.map((c) => c.grupo))]; return P.todos.map((c, i) => ({ c, i })).sort((a, b) => orden.indexOf(a.c.grupo) - orden.indexOf(b.c.grupo) || a.i - b.i).map(({ c }) => ({ c, marcas: null })); }   // sin búsqueda, agrupado: cada grupo con su etiqueta
    return P.todos.map((c, i) => ({ c, i, r: puntuar(q, c) })).filter((x) => x.r).sort((a, b) => b.r.total - a.r.total || a.i - b.i).map((x) => ({ c: x.c, marcas: x.r.marcas }));
  }
  function pintar() {
    P.items = filtrar().slice(0, 60);
    P.sel = Math.min(P.sel, Math.max(0, P.items.length - 1));
    const sinConsulta = !P.q.value.trim();
    let grupoPrevio = null;
    P.lista.replaceChildren(...(P.items.length ? P.items.flatMap(({ c, marcas }, i) => [
      sinConsulta && c.grupo !== grupoPrevio ? (grupoPrevio = c.grupo, h("li", { class: "pal-grupo", role: "presentation" }, c.grupo)) : null,
      h("li", { role: "option", id: "pal-o-" + i, class: "pal-op", "data-i": String(i), "data-id": c.id, "aria-selected": String(i === P.sel) },
        AP.icono(c.icono || "info", "pal-ic"), h("span", { class: "pal-t" }, ...resaltar(c.titulo, marcas)), sinConsulta ? null : h("span", { class: "pal-g t-meta" }, c.grupo)),
    ].filter(Boolean))
      : [h("li", { class: "pal-vacio t-body", role: "presentation" }, "Nada coincide con lo que has escrito.")]));
    P.estado.textContent = P.items.length ? `${P.items.length} resultado${P.items.length === 1 ? "" : "s"}. Flechas para moverte, Intro para ejecutar, Esc para cerrar.` : "Sin resultados.";
    marcar();
  }
  function marcar() {
    const ops = [...P.lista.querySelectorAll("[role=option]")];
    ops.forEach((o, i) => o.setAttribute("aria-selected", String(i === P.sel)));
    const a = ops[P.sel];
    P.q.setAttribute("aria-activedescendant", a ? a.id : "");
    if (a) a.scrollIntoView({ block: "nearest" });
  }
  function mover(d) { if (!P.items.length) return; P.sel = (P.sel + d + P.items.length) % P.items.length; marcar(); }
  function abrir() {
    if (document.querySelector(".dp-fondo")) return;   // un diálogo de confirmación tiene la palabra
    construir();
    if (P.dlg.open) return;
    P.previo = document.activeElement;
    P.todos = comandos();
    P.q.value = ""; P.sel = 0;
    pintar();
    P.dlg.showModal();
    P.q.focus();
  }
  function cerrar(devolverFoco = true) {
    if (!P.dlg || !P.dlg.open) return;
    P.dlg.close();
    if (devolverFoco && P.previo && P.previo.isConnected && typeof P.previo.focus === "function") P.previo.focus();
  }
  function ejecutar(it) {
    if (!it) return;
    cerrar(false);
    // se ejecuta con el diálogo ya cerrado y el foco en su sitio: así lo que la acción abra (un panel, el diálogo de ajustes) recibe el foco con normalidad
    if (P.previo && P.previo.isConnected && typeof P.previo.focus === "function") P.previo.focus({ preventScroll: true });
    setTimeout(() => { try { it.c.accion(); } catch (e) { if (AP.alerta) AP.alerta(e); } }, 0);
  }

  // Ctrl+K (o Cmd+K) en toda la app, también con el foco en un campo de texto. En fase de captura para ser la primera en verlo.
  document.addEventListener("keydown", (ev) => {
    if ((ev.ctrlKey || ev.metaKey) && !ev.altKey && !ev.shiftKey && ev.key && ev.key.toLowerCase() === "k") {
      ev.preventDefault(); ev.stopPropagation();
      if (P.dlg && P.dlg.open) cerrar(); else abrir();
    }
  }, true);
  const boton = $("#b-paleta");
  if (boton) { boton.append(AP.icono("comando")); boton.addEventListener("click", () => abrir()); }
  AP.paleta = { abrir, cerrar, abierta: () => !!(P.dlg && P.dlg.open), comandos: () => comandos().map((c) => ({ id: c.id, titulo: c.titulo, grupo: c.grupo })), puntuar: (q, titulo) => { const r = puntuar(q, { titulo, palabras: "", grupo: "" }); return r ? r.total : null; } };
})();
