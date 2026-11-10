"use strict";
/* WhisperMeet: «Copia de seguridad» en Ajustes, pestaña Privacidad (ola F, apuntes/copia.py y apuntes/api_copia.py).
   - «Crear copia» (POST /api/copia): mientras corre, el botón queda desactivado con el texto «Creando la copia». Al terminar: «Copia creada: <nombre> (N ficheros, X MB).»
     y, si hubo omitidos, «N ficheros no entraron en la copia.» con la lista desplegable. Si la copia se cortó por tamaño (`cortada`): «Copia incompleta: …» y, visible sin
     desplegar nada, «La copia se cortó al llegar al tope de tamaño: faltan ficheros.» (`#aj-copia-cortada`); la lista sigue dando el motivo del servidor.
   - «Última copia: 12 de marzo, 10:42.» o «Todavía no hay ninguna copia.» (GET /api/copia, que se repite al abrir Ajustes y tras crear una copia).
   - «Abrir la carpeta de copias» (POST /api/copia/abrir).
   - Los errores van junto al botón, en el hueco `#aj-copia-error` (el mismo patrón que el resto de Ajustes); nunca `alert`. Todo texto del servidor entra con textContent (h). */
(() => {
  const AP = window.AP;
  if (!AP) return;
  const { h, $, api } = AP;
  const raiz = $("#aj-copia");
  if (!raiz) return;
  const bCrear = $("#aj-copia-crear"), bAbrir = $("#aj-copia-abrir"), err = $("#aj-copia-error"), res = $("#aj-copia-resultado"), cortada = $("#aj-copia-cortada");
  const det = $("#aj-copia-omitidos"), detRes = $("#aj-copia-omitidos-res"), detLista = $("#aj-copia-omitidos-lista"), ultima = $("#aj-copia-ultima");
  const TEXTO_CREAR = bCrear.textContent;
  const est = { creando: false };

  const unidad = (n, uno, varios) => `${n.toLocaleString("es-ES")} ${n === 1 ? uno : varios}`;
  const mb = (bytes) => `${Math.max(0.1, Math.round(bytes / 104857.6) / 10).toLocaleString("es-ES", { maximumFractionDigits: 1 })} MB`;
  function cuando(iso) {
    const d = new Date(iso);
    if (isNaN(d)) return "";
    return `${d.toLocaleDateString("es-ES", { day: "numeric", month: "long" })}, ${d.toLocaleTimeString("es-ES", { hour: "2-digit", minute: "2-digit", hour12: false })}`;
  }

  function error(msg) { err.textContent = msg || ""; err.hidden = !msg; }

  function pintarUltima(d) {
    const primera = d && Array.isArray(d.copias) && d.copias[0];
    const c = primera ? cuando(primera.fecha) : "";
    ultima.textContent = c ? `Última copia: ${c}.` : "Todavía no hay ninguna copia.";
  }

  async function cargar() {
    try { pintarUltima(await api("GET", "/api/copia")); }
    catch (e) { ultima.textContent = ""; error("No se pudo leer la lista de copias: " + e.message); }
  }

  function pintarResultado(r) {
    res.textContent = `${r.cortada ? "Copia incompleta" : "Copia creada"}: ${r.nombre} (${unidad(r.ficheros, "fichero", "ficheros")}, ${mb(r.bytes)}).`;
    cortada.hidden = !r.cortada;
    const o = Array.isArray(r.omitidos) ? r.omitidos : [];
    det.hidden = !o.length;
    det.open = false;
    detRes.textContent = o.length === 1 ? "1 fichero no entró en la copia." : `${o.length.toLocaleString("es-ES")} ficheros no entraron en la copia.`;
    detLista.replaceChildren(...o.map((x) => h("li", {}, `${x.ruta}: ${x.motivo}`)));
  }

  async function crear() {
    if (est.creando) return;
    est.creando = true; error("");
    bCrear.disabled = true; bCrear.textContent = "Creando la copia"; bCrear.setAttribute("aria-busy", "true");
    try { pintarResultado(await api("POST", "/api/copia")); await cargar(); }
    catch (e) { res.textContent = ""; cortada.hidden = true; det.hidden = true; error(e.message); }
    finally { est.creando = false; bCrear.disabled = false; bCrear.textContent = TEXTO_CREAR; bCrear.removeAttribute("aria-busy");
      const a = document.activeElement;   // el foco vuelve al botón solo si no se ha ido a otro control
      if (!a || a === document.body || a === bCrear) bCrear.focus(); }
  }

  async function abrir() {
    error("");
    bAbrir.disabled = true;
    try { await api("POST", "/api/copia/abrir"); }
    catch (e) { error(e.message); }
    finally { bAbrir.disabled = false; }
  }

  bCrear.addEventListener("click", crear);
  bAbrir.addEventListener("click", abrir);

  const previo = AP.hooks.ajustesAbrir;
  AP.hooks.ajustesAbrir = (info, f) => { if (previo) previo(info, f); error(""); cargar(); };

  AP.copia = { cargar, crear, abrir, estado: est };
})();
