"use strict";
/* WhisperMeet: requisitos del equipo (ola D, apuntes/requisitos.py).
   - Panel «Antes de la primera reunión» en el inicio (#i-requisitos): NO bloquea nada y no molesta si todo está bien. Sale si algo está en «falta»; si solo hay avisos,
     solo la primera vez (localStorage.apuntes_req_visto, que se marca al ocultarlo). «Ocultar» lo quita hasta la próxima vez que se abra la app.
   - En el inicio solo salen las filas que no están bien, y debajo una línea con el número de las que sí lo están (#req-ok): el panel ocupa lo justo y no empuja el resto.
   - La lista COMPLETA, en Ajustes (sección Audio, #aj-requisitos), con «Volver a comprobar».
   - GET /api/requisitos: sin tokens, sin abrir el micrófono, sin descargar ni escribir nada; por eso se puede repetir cuando se quiera.
   Todo texto del servidor entra con textContent (h). */
(() => {
  const AP = window.AP;
  if (!AP) return;
  const { h, $, api, safe } = AP;
  const ETIQUETA = { bien: "Bien", aviso: "Aviso", falta: "Falta" };
  const VISTO = "apuntes_req_visto";
  const est = { datos: null, error: "", oculto: false, fijo: false, cargando: null };

  const fila = (c) => h("li", { class: "req-fila", "data-estado": c.estado, "data-clave": c.clave },
    h("span", { class: "req-est t-label" }, ETIQUETA[c.estado] || c.estado),
    h("div", { class: "req-cuerpo" },
      h("span", { class: "req-tit t-body-m" }, c.titulo),
      h("p", { class: "req-det t-meta" }, c.detalle),
      c.estado !== "bien" && c.como_arreglarlo ? h("p", { class: "req-como t-meta" }, h("b", {}, "Qué hacer: "), c.como_arreglarlo) : null));

  function resumen(d) {
    if (!d) return "";
    const partes = [];
    if (d.faltan) partes.push(d.faltan === 1 ? "Falta 1 cosa" : `Faltan ${d.faltan} cosas`);
    if (d.avisos) partes.push(d.avisos === 1 ? "1 aviso" : `${d.avisos} avisos`);
    return partes.length ? partes.join(" · ") : "Todo en orden.";
  }

  /** La línea de las comprobaciones que están bien. `otras`: hay filas con problema encima. Nada si no hay ninguna. */
  function lineaBien(n, otras) {
    if (!n) return "";
    if (otras) return n === 1 ? "La otra comprobación está en orden." : `Las otras ${n} comprobaciones están en orden.`;
    return n === 1 ? "La comprobación está en orden." : `Las ${n} comprobaciones están en orden.`;
  }

  function visibleEnInicio() {
    const d = est.datos;
    if (!d || est.oculto) return false;
    if (est.fijo) return true;                                   // lo acaba de pedir el usuario: no desaparece bajo su cursor aunque ya esté todo bien
    if (d.faltan > 0) return true;
    return d.avisos > 0 && !safe(() => localStorage.getItem(VISTO), null);
  }

  function pintar() {
    const d = est.datos;
    const panel = $("#i-requisitos"), lista = $("#req-lista"), res = $("#req-res"), ok = $("#req-ok");
    if (panel && lista && res) {
      if (d) {
        const mal = d.comprobaciones.filter((c) => c.estado !== "bien");
        lista.replaceChildren(...mal.map(fila)); res.textContent = resumen(d);
        if (ok) { ok.textContent = lineaBien(d.comprobaciones.length - mal.length, mal.length > 0); ok.hidden = !ok.textContent; }
      }
      panel.dataset.estado = d ? d.estado : "";
      panel.hidden = !visibleEnInicio();
    }
    const aj = $("#aj-req-lista"), ajRes = $("#aj-req-res");
    if (aj && ajRes) {
      if (d) { aj.replaceChildren(...d.comprobaciones.map(fila)); ajRes.textContent = resumen(d); }
      else if (est.error) { aj.replaceChildren(); ajRes.textContent = "No se pudo comprobar: " + est.error; }
    }
  }

  /** Pide las comprobaciones (una a la vez). Devuelve la promesa; nunca lanza. */
  function comprobar() {
    if (est.cargando) return est.cargando;
    est.cargando = (async () => {
      try {
        const d = await api("GET", "/api/requisitos");
        if (!d || !Array.isArray(d.comprobaciones)) throw new Error("respuesta no válida");
        est.datos = d; est.error = "";
      } catch (e) { est.error = e.message; }
      finally { est.cargando = null; }
      pintar();
    })();
    return est.cargando;
  }

  async function volver(boton, res) {
    est.fijo = true; est.oculto = false;
    boton.disabled = true; boton.setAttribute("aria-busy", "true"); if (res) res.textContent = "Comprobando…";
    await comprobar();
    boton.disabled = false; boton.removeAttribute("aria-busy");
    boton.focus();
  }
  const bInicio = $("#req-recomprobar"), bAjustes = $("#aj-req-recomprobar");
  if (bInicio) bInicio.addEventListener("click", () => volver(bInicio, $("#req-res")));
  if (bAjustes) bAjustes.addEventListener("click", () => volver(bAjustes, $("#aj-req-res")));
  const bCerrar = $("#req-cerrar");
  if (bCerrar) bCerrar.addEventListener("click", () => {
    est.oculto = true;
    if (est.datos && !est.datos.faltan) safe(() => localStorage.setItem(VISTO, "1"), null);   // solo avisos: no vuelve a salir por sí solo
    pintar();
    const buscar = $("#i-buscar"); if (buscar) buscar.focus();
  });

  // Se vuelve a mirar al volver al inicio (por si el usuario ha arreglado algo) y al abrir Ajustes; es barato y sin efectos.
  const previoVolver = AP.hooks.alVolverAInicio;
  AP.hooks.alVolverAInicio = () => { if (previoVolver) previoVolver(); est.fijo = false; comprobar(); };
  const previoAbrir = AP.hooks.ajustesAbrir;
  AP.hooks.ajustesAbrir = (info, f) => { if (previoAbrir) previoAbrir(info, f); comprobar(); };

  AP.requisitos = { comprobar, datos: () => est.datos, visibleEnInicio, resumen };
  comprobar();
})();
