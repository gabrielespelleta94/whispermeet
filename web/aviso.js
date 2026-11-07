"use strict";
/* Aviso flotante de llamada de Teams (ventana propia, sin foco; apuntes/aviso.py y VentanaAviso).
   La grabación empieza SOLO con el clic en «Empezar a transcribir» y solo con la casilla marcada: el botón está desactivado sin ella y el servidor
   rechaza la petición si no llega `avisado: true`. «Ahora no», Esc o AVISO_CADUCA_S sin tocarlo cierran el aviso, que no vuelve en esta llamada.
   El tiempo se pausa con el ratón encima y mientras se escribe en el tema. Sin dependencias de red. */
(() => {
  const $ = (s) => document.querySelector(s);
  const safe = (f, d) => { try { return f(); } catch { return d; } };
  const params = new URLSearchParams(location.search);
  const TOKEN = params.get("t") || safe(() => sessionStorage.getItem("apuntes_t"), "") || "";
  if (params.get("t")) { safe(() => sessionStorage.setItem("apuntes_t", TOKEN)); history.replaceState(null, "", location.pathname); }

  async function api(metodo, ruta, cuerpo) {
    const r = await fetch(ruta, { method: metodo, headers: { "X-Token": TOKEN, "Content-Type": "application/json" }, body: cuerpo === undefined ? undefined : JSON.stringify(cuerpo) });
    let datos = null;
    try { datos = await r.json(); } catch { /* sin cuerpo */ }
    if (!r.ok) throw new Error((datos && (datos.detail || datos.error)) || `Error ${r.status}`);
    return datos;
  }

  const el = { av: $("#av"), tema: $("#av-tema"), temaInput: $("#av-tema-input"), avisado: $("#av-avisado"), empezar: $("#av-empezar"), no: $("#av-no"),
    mas: $("#av-mas"), detalle: $("#av-detalle"), proyecto: $("#av-proyecto"), idioma: $("#av-idioma"), ayuda: $("#av-ayuda"), error: $("#av-error"),
    tiempo: document.querySelector(".av-tiempo"), barra: $("#av-barra") };
  el.mas.replaceChildren(window.AP.icono("abajo"));   // el mismo juego de iconos que la ventana principal (iconos.js)

  // Tema claro/oscuro: el mismo que eligió la persona en la ventana principal (si lo guardó en este origen); si no, el del sistema.
  const tema = safe(() => localStorage.getItem("apuntes_tema"), "auto");
  if (tema === "claro") document.documentElement.dataset.theme = "light";
  else if (tema === "oscuro") document.documentElement.dataset.theme = "dark";

  let activo = true, ocupado = false;
  let caducaMs = 45000, restante = 45000, ultimo = 0, encima = false, escribiendo = false;

  function pintarEstado() {
    const ok = el.avisado.checked;
    el.empezar.disabled = !ok || ocupado;
    el.ayuda.textContent = ok ? "No se graba nada hasta que pulses «Empezar a transcribir»." : "Marca la casilla para poder empezar.";
  }

  function mostrarError(msg) {
    el.error.replaceChildren(...(msg ? [window.AP.icono("error", "av-ic"), document.createTextNode(msg)] : []));
    el.error.hidden = !msg;
  }

  function opcion(valor, texto) {
    const o = document.createElement("option");
    o.value = valor; o.textContent = texto;
    return o;
  }

  // El alto de la ventana nativa sigue al del contenido (sin cortar nada): se avisa al servidor cuando cambia.
  let altoEnviado = 0, temporizadorAlto = 0;
  function enviarAlto() {
    const alto = Math.ceil(el.av.getBoundingClientRect().height);
    if (!alto || Math.abs(alto - altoEnviado) < 1) return;
    altoEnviado = alto;
    api("POST", "/api/aviso/tamano", { alto }).catch(() => { altoEnviado = 0; });
  }
  new ResizeObserver(() => { clearTimeout(temporizadorAlto); temporizadorAlto = setTimeout(enviarAlto, 30); }).observe(el.av);
  setInterval(enviarAlto, 250);   // además del observador: si el motor deja de entregarlo (ventana sin foco), el alto se sigue ajustando

  async function descartar() {
    if (!activo) return;
    activo = false;
    try { await api("POST", "/api/aviso/descartar"); } catch { /* la ventana se cierra igualmente */ }
  }

  async function empezar() {
    if (!activo || ocupado || !el.avisado.checked) return;
    ocupado = true; mostrarError(""); pintarEstado();
    try {
      await api("POST", "/api/aviso/empezar", { proyecto: el.proyecto.value || null, tema: el.temaInput.value, idioma: el.idioma.value, avisado: el.avisado.checked });
      activo = false;   // el servidor cierra la ventana
    } catch (e) {
      ocupado = false; mostrarError(e.message); pintarEstado();
    }
  }

  // ---------------------------------------------------------------- tiempo hasta que se cierra solo
  let reloj = 0;
  function paso() {
    if (!activo) { clearInterval(reloj); return; }
    const ahora = Date.now();
    const dt = ahora - (ultimo || ahora);
    ultimo = ahora;
    const pausa = encima || escribiendo || ocupado;
    el.tiempo.classList.toggle("pausa", pausa);
    if (!pausa) restante = Math.max(0, restante - dt);
    el.barra.style.transform = `scaleX(${(restante / caducaMs).toFixed(4)})`;
    if (restante <= 0) { clearInterval(reloj); descartar(); }
  }
  el.av.addEventListener("mouseenter", () => { encima = true; });
  el.av.addEventListener("mouseleave", () => { encima = false; });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") descartar(); });

  // ---------------------------------------------------------------- eventos
  el.avisado.addEventListener("change", pintarEstado);
  el.empezar.addEventListener("click", empezar);
  el.no.addEventListener("click", descartar);
  el.mas.addEventListener("click", () => {
    const abrir = el.detalle.hidden;
    el.detalle.hidden = !abrir;
    el.mas.setAttribute("aria-expanded", String(abrir));
  });
  el.temaInput.addEventListener("input", () => { el.tema.textContent = el.temaInput.value.trim() || el.temaInput.placeholder; });
  // Para escribir hace falta teclado: solo al hacer clic en el campo del tema la ventana deja que Windows la active; al salir, vuelve a no hacerlo.
  el.temaInput.addEventListener("focus", () => { escribiendo = true; api("POST", "/api/aviso/teclado", { activo: true }).catch(() => {}); });
  el.temaInput.addEventListener("blur", () => { escribiendo = false; api("POST", "/api/aviso/teclado", { activo: false }).catch(() => {}); });

  // Para diagnóstico y pruebas (solo lectura): lo que va contando el aviso.
  window.__aviso = { estado: () => ({ restante, caducaMs, encima, escribiendo, ocupado, activo }) };

  (async function init() {
    try {
      const d = await api("GET", "/api/aviso");
      el.tema.textContent = d.tema;
      el.temaInput.value = d.tema;
      el.temaInput.placeholder = d.tema;
      el.proyecto.append(opcion("", "Bandeja (reunión sin proyecto)"));
      (d.proyectos || []).forEach((n) => el.proyecto.append(opcion(n, n)));
      el.proyecto.value = d.proyecto || "";
      el.idioma.value = d.idioma || "auto";
      caducaMs = restante = Math.max(1, (d.caduca_s || 45)) * 1000;
      pintarEstado();
      ultimo = Date.now();
      reloj = setInterval(paso, 100);   // setInterval y no requestAnimationFrame: sigue contando aunque el motor deje de pintar
      window.__avisoListo = true;
    } catch (e) {
      mostrarError("No se pudo preparar el aviso: " + e.message);
    }
  })();
})();
