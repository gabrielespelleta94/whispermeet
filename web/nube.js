"use strict";
/* WhisperMeet: transcripción en la nube en Ajustes › Audio (contrato: apuntes/servidor.py, /api/info › nube, PUT|DELETE /api/nube/clave, POST /api/nube/probar).
   Encadena los hooks de ajustes.js. Reglas: la clave NO se guarda en localStorage ni sessionStorage, no se pinta, no va en PUT /api/config y el campo no lleva `name`;
   se vacía tras guardar. Con un servidor anterior (sin `info.nube`) el bloque queda oculto. Todo texto dinámico entra por textContent. Sin dependencias de red. */
(() => {
  const AP = window.AP;
  if (!AP) return;
  const { $, api } = AP;
  const dlg = $("#d-ajustes"), fs = $("#aj-nube"), f = $("#f-ajustes");
  if (!dlg || !fs || !f) return;

  const CLAVES = ["transcripcion_motor", "nube_url_base", "nube_modelo", "nube_autenticacion", "nube_dialecto"];
  const ERRORES = {
    transcripcion_motor: "#aj-nube-motor-error", nube_url_base: "#aj-nube-url-error", nube_modelo: "#aj-nube-modelo-error",
    nube_autenticacion: "#aj-nube-auth-error", nube_dialecto: "#aj-nube-dialecto-error", nube_clave: "#aj-nube-clave-error",
  };
  const AVANZADOS = ["nube_autenticacion", "nube_dialecto"];
  const FRASE_ACEPTO = "Marca «Entiendo que el audio sale del equipo» para activar la nube.";
  let activo = false;
  const inicial = { transcripcion_motor: "local", nube_url_base: "", nube_modelo: "", nube_autenticacion: "bearer", nube_dialecto: "auto" };
  let claveEstado = { puesta: false, origen: "ninguna", error: "" };

  const motorElegido = () => { const r = $("input[name=transcripcion_motor]:checked", dlg); return r ? r.value : "local"; };
  const entradaDe = (campo) => {
    if (campo === "transcripcion_motor") return $("input[name=transcripcion_motor]:checked", dlg) || $("input[name=transcripcion_motor]", dlg);
    if (campo === "nube_clave") return $("#aj-nube-clave");
    return f.elements[campo];
  };

  function limpiarError(campo) {
    const e = $(ERRORES[campo], dlg), i = entradaDe(campo);
    if (e) { e.hidden = true; e.textContent = ""; }
    if (i) i.removeAttribute("aria-invalid");
  }
  const limpiarTodos = () => Object.keys(ERRORES).forEach(limpiarError);
  function pintarError(campo, mensaje) {
    const e = $(ERRORES[campo], dlg), i = entradaDe(campo);
    $("#s-error").hidden = true;
    if (AVANZADOS.includes(campo)) $("#aj-nube-avanzado").open = true;
    e.textContent = mensaje; e.hidden = false;
    if (i) { i.setAttribute("aria-invalid", "true"); i.focus(); }
    if (AP.ajustes) AP.ajustes.ir("audio");
  }

  // Los campos del servicio solo valen con la nube elegida; la clave se puede poner de antemano.
  function sincronizar() {
    const nube = motorElegido() === "nube";
    ["nube_url_base", "nube_modelo", "nube_autenticacion", "nube_dialecto"].forEach((c) => { f.elements[c].disabled = !nube; });
    $("#aj-nube-probar").disabled = !nube;
    $("#aj-nube-campos").dataset.activo = String(nube);
    const pide = nube && inicial.transcripcion_motor !== "nube";
    $("#aj-nube-acepto-fila").hidden = !pide;
    if (!pide) $("#aj-nube-acepto").checked = false;
  }

  function textoClave(c) {
    if (c.error) return c.error;
    if (c.puesta && c.origen === "entorno") return "Clave de la variable de entorno WHISPERMEET_CLAVE_NUBE";
    if (c.puesta) return "Clave guardada cifrada en este equipo";
    return "Sin clave";
  }
  function pintarClave(c, nota) {
    claveEstado = c || { puesta: false, origen: "ninguna", error: "" };
    $("#aj-nube-clave-estado").textContent = textoClave(claveEstado) + (nota ? ". " + nota : "");
    $("#aj-nube-clave-quitar").disabled = !claveEstado.puesta && !claveEstado.error;
  }

  // ------------------------------------------------------------ hooks de Ajustes
  const previoAbrir = AP.hooks.ajustesAbrir;
  AP.hooks.ajustesAbrir = (info, formulario) => {
    if (previoAbrir) previoAbrir(info, formulario);
    const c = (info && info.config) || {};
    activo = !!(info && info.nube) || c.transcripcion_motor !== undefined;
    fs.hidden = !activo;
    if (!activo) return;
    inicial.transcripcion_motor = c.transcripcion_motor === "nube" ? "nube" : "local";
    inicial.nube_url_base = c.nube_url_base || "";
    inicial.nube_modelo = c.nube_modelo || "";
    inicial.nube_autenticacion = c.nube_autenticacion || "bearer";
    inicial.nube_dialecto = c.nube_dialecto || "auto";
    marcarMotor(inicial.transcripcion_motor);
    f.elements.nube_url_base.value = inicial.nube_url_base;
    f.elements.nube_modelo.value = inicial.nube_modelo;
    f.elements.nube_autenticacion.value = inicial.nube_autenticacion;
    f.elements.nube_dialecto.value = inicial.nube_dialecto;
    $("#aj-nube-clave").value = "";
    $("#aj-nube-acepto").checked = false;
    const res = $("#aj-nube-probar-res"); res.textContent = ""; res.removeAttribute("data-estado");
    limpiarTodos();
    pintarClave((info.nube && info.nube.clave) || null);
    sincronizar();
  };
  function marcarMotor(v) { dlg.querySelectorAll("input[name=transcripcion_motor]").forEach((r) => { r.checked = r.value === v; }); }

  const previoGuardar = AP.hooks.ajustesGuardar;
  AP.hooks.ajustesGuardar = (formulario) => {
    const cambios = previoGuardar ? previoGuardar(formulario) : {};
    if (!activo) return cambios;
    limpiarTodos();
    const actual = {
      transcripcion_motor: motorElegido(), nube_url_base: f.elements.nube_url_base.value.trim(), nube_modelo: f.elements.nube_modelo.value.trim(),
      nube_autenticacion: f.elements.nube_autenticacion.value, nube_dialecto: f.elements.nube_dialecto.value,
    };
    CLAVES.forEach((k) => {
      if (actual[k] === inicial[k]) return;
      // pasar a la nube exige confirmar que el audio sale del equipo (el envío ya se frena antes, en `submit`; esto es la segunda barrera)
      if (k === "transcripcion_motor" && actual[k] === "nube" && !$("#aj-nube-acepto").checked) return;
      cambios[k] = actual[k];
    });
    return cambios;
  };

  const previoError = AP.hooks.ajustesError;
  AP.hooks.ajustesError = (e) => {
    const campo = e && e.datos && e.datos.campo;
    if (activo && campo && ERRORES[campo]) { pintarError(campo, e.message); return true; }
    return previoError ? previoError(e) : false;
  };

  // Primera barrera: sin la casilla de confirmación no se envía nada y el diálogo sigue abierto con el error a la vista.
  dlg.addEventListener("submit", (ev) => {
    if (!activo || motorElegido() !== "nube" || inicial.transcripcion_motor === "nube" || $("#aj-nube-acepto").checked) return;
    ev.preventDefault(); ev.stopImmediatePropagation();
    limpiarTodos();
    const e = $(ERRORES.transcripcion_motor, dlg), a = $("#aj-nube-acepto");
    $("#s-error").hidden = true;
    e.textContent = FRASE_ACEPTO; e.hidden = false;
    a.setAttribute("aria-invalid", "true");
    if (AP.ajustes) AP.ajustes.ir("audio");
    a.focus();
  }, true);

  dlg.querySelectorAll("input[name=transcripcion_motor]").forEach((r) => r.addEventListener("change", () => { limpiarError("transcripcion_motor"); $("#aj-nube-acepto").removeAttribute("aria-invalid"); sincronizar(); }));
  $("#aj-nube-acepto").addEventListener("change", (ev) => { if (ev.target.checked) { limpiarError("transcripcion_motor"); ev.target.removeAttribute("aria-invalid"); } });
  CLAVES.slice(1).forEach((k) => f.elements[k].addEventListener("input", () => limpiarError(k)));
  f.elements.nube_autenticacion.addEventListener("change", () => limpiarError("nube_autenticacion"));
  f.elements.nube_dialecto.addEventListener("change", () => limpiarError("nube_dialecto"));
  $("#aj-nube-clave").addEventListener("input", () => limpiarError("nube_clave"));

  // ------------------------------------------------------------ clave y prueba (actúan al momento, no esperan a «Guardar»)
  async function guardarClave() {
    const campo = $("#aj-nube-clave"), b = $("#aj-nube-clave-guardar"), v = campo.value.trim();
    limpiarError("nube_clave");
    if (!v) { pintarError("nube_clave", "Escribe la clave antes de guardarla."); return; }
    b.disabled = true;
    try {
      const r = await api("PUT", "/api/nube/clave", { clave: v });
      campo.value = "";
      pintarClave(r.clave, r.nota);
    } catch (e) { pintarError("nube_clave", e.message); }
    finally { b.disabled = false; }
  }
  async function quitarClave() {
    const b = $("#aj-nube-clave-quitar");
    limpiarError("nube_clave");
    b.disabled = true;
    try { const r = await api("DELETE", "/api/nube/clave"); $("#aj-nube-clave").value = ""; pintarClave(r.clave); }
    catch (e) { pintarError("nube_clave", e.message); pintarClave(claveEstado); }
  }
  async function probar() {
    const b = $("#aj-nube-probar"), res = $("#aj-nube-probar-res"), clave = $("#aj-nube-clave").value.trim();
    const cuerpo = { nube_url_base: f.elements.nube_url_base.value.trim(), nube_modelo: f.elements.nube_modelo.value.trim(),
      nube_autenticacion: f.elements.nube_autenticacion.value, nube_dialecto: f.elements.nube_dialecto.value };
    if (clave) cuerpo.clave = clave;
    limpiarTodos();
    b.disabled = true; b.textContent = "Probando…"; res.textContent = ""; res.removeAttribute("data-estado");
    try {
      const r = await api("POST", "/api/nube/probar", cuerpo);
      if (r.ok) { res.textContent = `Funciona: «${r.modelo}» en ${r.host} (${r.ms} ms).`; res.dataset.estado = "ok"; }
      else { res.textContent = r.mensaje || "La prueba no ha funcionado."; res.dataset.estado = "error"; }
    } catch (e) {
      if (e.datos && e.datos.campo && ERRORES[e.datos.campo]) pintarError(e.datos.campo, e.message);
      else { res.textContent = e.message; res.dataset.estado = "error"; }
    } finally { b.textContent = "Probar conexión"; sincronizar(); }
  }
  $("#aj-nube-clave-guardar").addEventListener("click", guardarClave);
  $("#aj-nube-clave-quitar").addEventListener("click", quitarClave);
  $("#aj-nube-probar").addEventListener("click", probar);
  $("#aj-nube-clave").addEventListener("keydown", (ev) => { if (ev.key === "Enter") { ev.preventDefault(); guardarClave(); } });   // Intro guarda la clave, no todo el diálogo

  // ------------------------------------------------------------ consentimiento: portada («He avisado a los asistentes»)
  // Con el motor `nube` la portada lo dice a la vista (no solo en un title); con `local` queda el texto de siempre.
  const TITLE_LOCAL = "La app no guarda audio, pero sí el texto, y la transcripción se enviará a Claude para analizarla.";
  const NOTA_LOCAL = "Sin audio guardado; el texto se envía a Claude.";
  const fraseNube = (host) => `La transcripción se hace en la nube: el audio se envía a ${host || "el servicio configurado"}.`;
  function pintarPortada(info) {
    const aviso = $("#i-nube"), etiqueta = document.querySelector("label.ini-aviso"), nota = document.querySelector(".ini-aviso-nota");
    if (!aviso) return;
    const nube = !!(info && info.config && info.config.transcripcion_motor === "nube");
    const host = (info && info.nube && info.nube.host) || "";
    aviso.hidden = !nube;
    aviso.textContent = nube ? fraseNube(host) : "";
    if (etiqueta) etiqueta.title = nube ? `La app no guarda audio en disco. ${fraseNube(host)} El texto, además, se envía a Claude para analizarlo.` : TITLE_LOCAL;
    if (nota) nota.textContent = nube ? `Sin audio guardado; el audio va a ${host || "la nube"} y el texto a Claude.` : NOTA_LOCAL;
  }
  async function refrescarPortada() {
    try { pintarPortada(await api("GET", "/api/info")); } catch { /* sin datos: queda el texto de siempre */ }
  }
  dlg.addEventListener("close", refrescarPortada);
  const previoVolver = AP.hooks.alVolverAInicio;
  AP.hooks.alVolverAInicio = () => { if (previoVolver) previoVolver(); refrescarPortada(); };
  refrescarPortada();

  AP.nube = { refrescarPortada, pintarPortada, fraseNube, estadoClave: () => ({ ...claveEstado }) };
})();
