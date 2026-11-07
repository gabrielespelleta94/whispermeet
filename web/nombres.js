"use strict";
/* WhisperMeet: mapa ÚNICO de los agentes con nombre, color e icono. Los cinco del equipo se llaman Capitán, Lupa, Arquitecto, Auditor y Sherpa;
   además hay Monitor (la escucha local) y Asesor (la respuesta al cliente). La clave es la interna del backend (`apuntes/equipo/perfiles.py`):
   coordinador → Capitán, funcional → Lupa, constructor → Arquitecto, revisor → Auditor, estratega → Sherpa. Los textos y las pruebas internas
   no cambian: solo lo que se ve. El color es un token CSS (--ag-*, en app.css, con contraste AA en los dos temas); el icono, uno de iconos.js. */
(() => {
  const AP = (window.AP = window.AP || { hooks: {} });
  const A = {
    coordinador: { id: "capitan", nombre: "Capitán", mono: "CA", icono: "capitan", rol: "Fechas, responsables y decisiones cerradas" },
    funcional: { id: "lupa", nombre: "Lupa", mono: "LU", icono: "lupa", rol: "Reglas de negocio, definiciones y alcance" },
    constructor: { id: "arquitecto", nombre: "Arquitecto", mono: "AR", icono: "arquitecto", rol: "Datos, sistemas, integraciones y cifras" },
    revisor: { id: "auditor", nombre: "Auditor", mono: "AU", icono: "auditor", rol: "Contrasta lo dicho con el contexto y los objetivos" },
    estratega: { id: "sherpa", nombre: "Sherpa", mono: "SH", icono: "sherpa", rol: "Consejos: qué aportar, qué preguntar y cuándo cerrar" },
    monitor: { id: "monitor", nombre: "Monitor", mono: "MO", icono: "monitor", rol: "Escucha local: detecta señales y definiciones" },
    asesor: { id: "asesor", nombre: "Asesor", mono: "AS", icono: "asesor", rol: "Respuestas sugeridas a las preguntas del cliente" },
    analista: { id: "analista", nombre: "Analista", mono: "AN", icono: "info", rol: "Análisis general periódico" },
  };
  for (const [k, a] of Object.entries(A)) { a.clave = k; a.color = `var(--ag-${a.id})`; A[a.id] = a; }   // se busca por clave interna o por nombre nuevo
  const ORDEN = ["coordinador", "funcional", "constructor", "revisor", "estratega", "monitor", "asesor"];
  const cap = (t) => (t ? String(t)[0].toUpperCase() + String(t).slice(1) : "");
  /** Entrada del agente (clave interna, p. ej. «coordinador», o su nombre, «capitan»); sin coincidencia, una genérica con el texto que llegue. */
  function agente(clave) {
    const k = String(clave || "").toLowerCase();
    return (Object.prototype.hasOwnProperty.call(A, k) && A[k]) || { id: "monitor", clave: k, nombre: cap(clave), mono: cap(clave).slice(0, 2).toUpperCase(), icono: "info", rol: "", color: "var(--ag-monitor)" };
  }
  /** Chip de agente: icono + nombre, con su color (nunca solo color). `solo` = solo el icono (con el nombre como etiqueta accesible). */
  function chip(clave, opciones = {}) {
    const a = agente(clave);
    const e = document.createElement("span");
    e.className = "ag ag-" + a.id + (opciones.solo ? " ag-solo" : "") + (opciones.clase ? " " + opciones.clase : "");
    e.dataset.agente = a.clave;
    if (opciones.solo) { e.setAttribute("role", "img"); e.setAttribute("aria-label", a.nombre); e.title = a.nombre + " · " + a.rol; }
    if (AP.icono) e.append(AP.icono(a.icono, "ag-ic"));
    if (!opciones.solo) { const t = document.createElement("span"); t.className = "ag-n"; t.textContent = a.nombre; e.append(t); }
    return e;
  }
  // El backend manda sus propios nombres («Coordinador», «Analista funcional»…): se sustituyen al llegar el evento, antes de que nadie los lea.
  const CLAVES_EQUIPO = new Set(["coordinador", "funcional", "constructor", "revisor", "estratega", "monitor", "asesor", "analista"]);
  function renombrar(o) { if (o && typeof o === "object" && CLAVES_EQUIPO.has(o.agente)) o.nombre = A[o.agente].nombre; }
  AP.normalizar = (d) => {
    if (!d || typeof d !== "object") return d;
    if (d.equipo && Array.isArray(d.equipo.perfiles)) d.equipo.perfiles.forEach((p) => { if (p && CLAVES_EQUIPO.has(p.id)) p.nombre = A[p.id].nombre; });
    if (Array.isArray(d.tareas)) d.tareas.forEach(renombrar);
    if (d.tipo === "tarea") renombrar(d);
    return d;
  };
  AP.agentes = A;
  AP.AGENTES_ORDEN = ORDEN;
  AP.agente = agente;
  AP.chipAgente = chip;
  AP.nombreAgente = (clave) => agente(clave).nombre;
})();
