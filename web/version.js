"use strict";
/* WhisperMeet: aviso «hay una versión nueva en disco» (apuntes/huella.py, `codigo_cambiado` de GET /api/info).
   La app se deja abierta días y el código puede actualizarse en disco sin que esta ventana lo sepa: el servidor compara la huella del código con la del
   arranque y aquí solo se muestra el resultado. En la portada, el aviso #i-actualizado (sin botones: la app NO se reinicia sola). Durante una reunión no se
   molesta con el banner: como mucho UNA nota por ventana en los avisos cerrables de la reunión (`AP.alerta`, #r-avisos).
   Se pregunta al cargar, al volver la ventana a primer plano (visibilitychange y focus; mínimo 30 s entre peticiones) y cada 5 minutos. Un fallo de red se ignora. */
(() => {
  const AP = window.AP;
  if (!AP) return;
  const { $, api } = AP;
  const MINIMO_MS = 30000, CADA_MS = 5 * 60 * 1000;
  const EN_REUNION = ["preparando", "grabando", "pausada", "terminando"];
  const NOTA = "Hay una versión nueva del programa. Al acabar la reunión, ciérralo y vuelve a abrirlo.";
  let ultima = -Infinity;      // última petición (performance.now)
  let notaDada = false;        // la nota de reunión sale una sola vez por ventana

  function mostrar(cambiado) {
    const banner = $("#i-actualizado");
    if (banner) banner.hidden = !cambiado;
    if (cambiado && !notaDada && EN_REUNION.includes(AP.S.estado) && !AP.UI.avisoExtra) {
      notaDada = true;
      AP.alerta(NOTA);
    }
  }

  async function comprobar(forzar) {   // `forzar` (solo pruebas): salta el mínimo entre peticiones
    const ahora = performance.now();
    if (forzar !== true && ahora - ultima < MINIMO_MS) return;
    ultima = ahora;
    try { mostrar(!!(await api("GET", "/api/info")).codigo_cambiado); } catch { /* sin red o servidor parado: se ignora */ }
  }

  document.addEventListener("visibilitychange", () => { if (document.visibilityState === "visible") comprobar(); });
  window.addEventListener("focus", () => comprobar());
  setInterval(() => comprobar(), CADA_MS);
  AP.version = { comprobar };
  comprobar();
})();
