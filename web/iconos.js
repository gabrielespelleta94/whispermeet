"use strict";
/* Apuntes: juego de iconos en SVG en línea (sin red, sin librería). Una sola caja de 24×24, trazo redondeado de grosor fijo en píxeles de pantalla
   (`vector-effect: non-scaling-stroke`, ver app.css) y color por `currentColor`: el color lo pone la clase del tipo (decisión, riesgo…), nunca el icono.
   Los trazados de los iconos genéricos están tomados de Lucide (https://lucide.dev, licencia ISC, compatible con el uso interno de esta app);
   los demás siguen la misma rejilla y el mismo trazo. Un icono por tipo: decisión, pendiente, pregunta, riesgo, contradicción, regla, idea, definición,
   objetivo, consejo, respuesta, aviso, error, éxito, información, anotación propia. */
(() => {
  const AP = (window.AP = window.AP || { hooks: {} });
  const NS = "http://www.w3.org/2000/svg";
  // cada icono: lista de trazados (d) o formas [tag, atributos]
  const D = {
    decision: ["M4 15s1-1 4-1 5 2 8 2 4-1 4-1V3s-1 1-4 1-5-2-8-2-4 1-4 1z", "M4 22v-7"],                                           // bandera: punto de acuerdo
    pendiente: [["rect", { x: 3, y: 5, width: 6, height: 6, rx: 1 }], "m3 17 2 2 4-4", "M13 6h8", "M13 12h8", "M13 18h8"],             // lista de tareas
    pregunta: [["circle", { cx: 12, cy: 12, r: 10 }], "M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3", "M12 17h.01"],
    riesgo: ["m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3", "M12 9v4", "M12 17h.01"],
    contradiccion: ["m16 3 4 4-4 4", "M20 7H4", "m8 21-4-4 4-4", "M4 17h16"],                                                         // dos sentidos opuestos
    regla: ["M8 3H7a2 2 0 0 0-2 2v5a2 2 0 0 1-2 2 2 2 0 0 1 2 2v5c0 1.1.9 2 2 2h1", "M16 21h1a2 2 0 0 0 2-2v-5c0-1.1.9-2 2-2a2 2 0 0 1-2-2V5a2 2 0 0 0-2-2h-1"],   // llaves: la lógica de una regla
    idea: ["M15 14c.2-1 .7-1.7 1.5-2.5 1-.9 1.5-2.2 1.5-3.5A6 6 0 0 0 6 8c0 1 .2 2.2 1.5 3.5.7.7 1.3 1.5 1.5 2.5", "M9 18h6", "M10 22h4"],
    definicion: ["M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H19a1 1 0 0 1 1 1v18a1 1 0 0 1-1 1H6.5a1 1 0 0 1 0-5H20"],
    objetivo: [["circle", { cx: 12, cy: 12, r: 10 }], ["circle", { cx: 12, cy: 12, r: 6 }], ["circle", { cx: 12, cy: 12, r: 2 }]],
    consejo: [["circle", { cx: 12, cy: 12, r: 10 }], "m16.24 7.76-1.804 5.411a2 2 0 0 1-1.265 1.265L7.76 16.24l1.804-5.411a2 2 0 0 1 1.265-1.265z"],   // brújula
    respuesta: ["M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z", "M13 8H7", "M17 12H7"],
    aviso: [["circle", { cx: 12, cy: 12, r: 10 }], "M12 8v4", "M12 16h.01"],
    error: [["circle", { cx: 12, cy: 12, r: 10 }], "m15 9-6 6", "m9 9 6 6"],
    exito: [["circle", { cx: 12, cy: 12, r: 10 }], "m9 12 2 2 4-4"],
    info: [["circle", { cx: 12, cy: 12, r: 10 }], "M12 16v-4", "M12 8h.01"],
    tu: ["M12 20h9", "M16.376 3.622a1 1 0 0 1 3.002 3.002L7.368 18.635a2 2 0 0 1-.855.506l-2.872.838a.5.5 0 0 1-.62-.62l.838-2.872a2 2 0 0 1 .506-.854z"],   // anotación propia
    hito: ["M2.7 10.3a2.41 2.41 0 0 0 0 3.41l7.59 7.59a2.41 2.41 0 0 0 3.41 0l7.59-7.59a2.41 2.41 0 0 0 0-3.41l-7.59-7.59a2.41 2.41 0 0 0-3.41 0Z"],
    cerrar: ["M18 6 6 18", "m6 6 12 12"],
    check: ["M20 6 9 17l-5-5"],
    abajo: ["m6 9 6 6 6-6"],
    derecha: ["m9 18 6-6-6-6"],
    arriba: ["m18 15-6-6-6 6"],
    favorito: ["M11.525 2.295a.53.53 0 0 1 .95 0l2.31 4.679a2.123 2.123 0 0 0 1.595 1.16l5.166.756a.53.53 0 0 1 .294.904l-3.736 3.638a2.123 2.123 0 0 0-.611 1.878l.882 5.14a.53.53 0 0 1-.771.56l-4.618-2.428a2.122 2.122 0 0 0-1.973 0L6.396 21.01a.53.53 0 0 1-.77-.56l.881-5.139a2.122 2.122 0 0 0-.611-1.879L2.16 9.795a.53.53 0 0 1 .294-.906l5.165-.755a2.122 2.122 0 0 0 1.597-1.16z"],   // estrella
    compartida: ["M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2", ["circle", { cx: 9, cy: 7, r: 4 }], "M22 21v-2a4 4 0 0 0-3-3.87", "M16 3.13a4 4 0 0 1 0 7.75"],   // dos personas
    rejilla: [["rect", { width: 7, height: 7, x: 3, y: 3, rx: 1 }], ["rect", { width: 7, height: 7, x: 14, y: 3, rx: 1 }], ["rect", { width: 7, height: 7, x: 14, y: 14, rx: 1 }], ["rect", { width: 7, height: 7, x: 3, y: 14, rx: 1 }]],
    lista: ["M3 12h.01", "M3 18h.01", "M3 6h.01", "M8 12h13", "M8 18h13", "M8 6h13"],
    empezar: ["M6 3 20 12 6 21 6 3"],
    mas: ["M5 12h14", "M12 5v14"],
    buscar: [["circle", { cx: 11, cy: 11, r: 8 }], "m21 21-4.3-4.3"],
    carpeta: ["M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z"],
    // los siete agentes con nombre (mapa único en nombres.js): Capitán, Lupa, Arquitecto, Auditor, Sherpa, Monitor y Asesor
    capitan: ["M12 22V8", "M5 12H2a10 10 0 0 0 20 0h-3", ["circle", { cx: 12, cy: 5, r: 3 }]],                                          // ancla: lleva el rumbo
    lupa: [["circle", { cx: 11, cy: 11, r: 8 }], "m21 21-4.3-4.3", "M8 11h6"],                                                         // lupa: lo que se define con precisión
    arquitecto: ["m12.99 6.74 1.93 3.44", "M19.136 12a10 10 0 0 1-14.271 0", "m21 21-2.16-3.84", "m3 21 8.02-14.26", ["circle", { cx: 12, cy: 5, r: 2 }]],   // compás de dibujo
    auditor: ["M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z", "m9 12 2 2 4-4"],   // escudo con tic
    sherpa: ["m8 3 4 8 5-5 5 15H2L8 3z"],                                                                                               // montaña: guía de la ascensión
    monitor: ["M22 12h-2.48a2 2 0 0 0-1.93 1.46l-2.35 8.36a.25.25 0 0 1-.48 0L9.24 2.18a.25.25 0 0 0-.48 0l-2.35 8.36A2 2 0 0 1 4.49 12H2"],   // pulso
    asesor: ["M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z", "M9.5 9.5a2.5 2.5 0 0 1 5 0c0 1.5-2.5 2-2.5 3.5", "M12 15.5h.01"],   // bocadillo con interrogación
    ajustes: ["M21 4h-7", "M10 4H3", "M21 12h-9", "M8 12H3", "M21 20h-5", "M12 20H3", "M14 2v4", "M8 10v4", "M16 18v4"],
    comando: ["M15 6v12a3 3 0 1 0 3-3H6a3 3 0 1 0 3 3V6a3 3 0 1 0-3 3h12a3 3 0 1 0-3-3"],
    correo: [["rect", { width: 20, height: 16, x: 2, y: 4, rx: 2 }], "m22 7-8.97 5.7a1.94 1.94 0 0 1-2.06 0L2 7"],
    tema: [["circle", { cx: 12, cy: 12, r: 9 }], "M12 3a9 9 0 0 0 0 18z"],
    pausa: [["rect", { x: 14, y: 4, width: 4, height: 16, rx: 1 }], ["rect", { x: 6, y: 4, width: 4, height: 16, rx: 1 }]],
    parar: [["rect", { width: 14, height: 14, x: 5, y: 5, rx: 2 }]],
    rayo: ["M4 14a1 1 0 0 1-.78-1.63l9.9-10.2a.5.5 0 0 1 .86.46l-1.92 6.02A1 1 0 0 0 13 10h7a1 1 0 0 1 .78 1.63l-9.9 10.2a.5.5 0 0 1-.86-.46l1.92-6.02A1 1 0 0 0 11 14z"],
    reloj: [["circle", { cx: 12, cy: 12, r: 10 }], "M12 6v6l4 2"],
    pantalla: [["rect", { width: 20, height: 14, x: 2, y: 3, rx: 2 }], "M8 21h8", "M12 17v4"],
    fijar: ["M12 17v5", "M9 10.76a2 2 0 0 1-1.11 1.79l-1.78.9A2 2 0 0 0 5 15.24V16a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-.76a2 2 0 0 0-1.11-1.79l-1.78-.9A2 2 0 0 1 15 10.76V7a1 1 0 0 1 1-1 2 2 0 0 0 0-4H8a2 2 0 0 0 0 4 1 1 0 0 1 1 1z"],
  };
  // tipos de tarjeta, hallazgo y consejo que comparten icono (los del asesor usan sus cinco etiquetas)
  const ALIAS = { valor: "idea", oportunidad: "idea", cierre: "decision", comentario: "respuesta", "posible": "contradiccion" };

  /** Devuelve un <svg> nuevo del icono `nombre`. `clase` se suma a «ic ic-<nombre>»; el tamaño lo da el CSS (16 px por defecto). */
  function icono(nombre, clase) {
    const k = D[nombre] ? nombre : ALIAS[nombre] || "info";
    const s = document.createElementNS(NS, "svg");
    s.setAttribute("viewBox", "0 0 24 24");
    s.setAttribute("class", "ic ic-" + k + (clase ? " " + clase : ""));
    s.setAttribute("aria-hidden", "true");
    s.setAttribute("focusable", "false");
    for (const f of D[k]) {
      const e = document.createElementNS(NS, Array.isArray(f) ? f[0] : "path");
      if (Array.isArray(f)) for (const [a, v] of Object.entries(f[1])) e.setAttribute(a, v); else e.setAttribute("d", f);
      s.append(e);
    }
    return s;
  }
  AP.icono = icono;
  AP.ICONOS = Object.keys(D);
})();
