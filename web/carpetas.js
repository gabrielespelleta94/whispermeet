"use strict";
/* WhisperMeet: elegir una carpeta con el selector nativo de Windows («Elegir carpeta…») y crear una carpeta nueva desde la app.
   - El botón solo aparece con ventana nativa (/api/ventana → nativa); sin ella se escribe la ruta a mano, como siempre.
   - Elegir NO registra nada: rellena la ruta (y el nombre, si está vacío) y el alta sigue yendo por «Añadir» (POST /api/proyectos/extra).
   - Solo carpetas visibles en disco (OneDrive o Google Drive sincronizados): no hay integración con ninguna nube.
   - ÚNICO sitio de la lógica de carpetas añadidas (inicio, Ajustes y la vista previa de proyectos.js): AP.carpetas.anadir / quitar / seleccionar.
   Todo el texto dinámico entra con textContent. */
(() => {
  const AP = window.AP;
  if (!AP) return;
  const { UI, $, $$, api } = AP;

  // ------------------------------------------------------------ lógica compartida (inicio y Ajustes)
  const sincronizarConfig = (lista) => { if (UI.info && UI.info.config && lista) UI.info.config.proyectos_extra = lista; };
  /** Añade una carpeta (POST /api/proyectos/extra → Guardian.validar_extra). `campos()` da {nombre, ruta, compartido}; `alOk(r)` recibe la respuesta. */
  async function anadir(campos, estado, error, alOk) {
    error.hidden = true; estado.textContent = "Comprobando…";
    try {
      const r = await api("POST", "/api/proyectos/extra", campos());
      estado.textContent = `Añadida: ${r.proyecto.nombre}`;
      sincronizarConfig(r.proyectos_extra);
      alOk(r);
    } catch (e) { estado.textContent = ""; error.textContent = e.message; error.hidden = false; }
  }
  /** Quita una carpeta de la lista (DELETE /api/proyectos/extra/{nombre}): no borra nada del disco. Devuelve la respuesta o lanza el error. */
  async function quitar(nombre) {
    const r = await api("DELETE", "/api/proyectos/extra/" + encodeURIComponent(nombre));
    sincronizarConfig(r.proyectos_extra);
    return r;
  }
  /** Deja `nombre` elegido en la lista de inicio (y visible aunque hubiera un filtro escrito). */
  function seleccionar(nombre) {
    UI.sel = nombre; UI.sesionPlan = undefined;
    try { localStorage.setItem("apuntes_proy", nombre); } catch { /* sin almacenamiento */ }
    $("#i-buscar").value = "";
    $("#i-buscar").dispatchEvent(new Event("input"));
    const ver = setInterval(() => {
      const fila = $("#i-lista [aria-selected=true]");
      if (fila && fila.dataset.clave === nombre) { clearInterval(ver); fila.scrollIntoView({ block: "nearest" }); if (AP.proyectos && AP.proyectos.abrirPanel) AP.proyectos.abrirPanel(nombre, fila); }
    }, 150);
    setTimeout(() => clearInterval(ver), 3000);
  }
  AP.carpetas = { anadir, quitar, seleccionar };

  // ------------------------------------------------------------ el botón solo existe con ventana nativa
  const botones = () => $$("[data-elegir-carpeta]");
  api("GET", "/api/ventana").then((v) => { if (v && v.nativa) botones().forEach((b) => { b.hidden = false; }); }).catch(() => { /* sin ventana nativa: ruta a mano */ });

  // Los campos de cada formulario se localizan por su contenedor: inicio (añadir y crear) y Ajustes
  function campos(boton) {
    const caja = boton.closest("form") || boton.closest("[data-add]") || boton.parentElement;
    const q = (sel) => caja.querySelector(sel);
    return {
      caja,
      ruta: q("[name=ruta], [name=ubicacion], [data-f=ruta]"),
      nombre: q("[name=nombre], [data-f=nombre]"),
      compartido: q("[name=compartido], [data-f=compartido]"),
      pista: q("[data-pista-compartida]"),
      error: q("[data-error]"),
      estado: q("[data-estado]"),
    };
  }

  async function elegir(boton) {
    const c = campos(boton);
    if (!c.ruta) return;
    const etiqueta = boton.textContent;
    boton.disabled = true; boton.textContent = "Abriendo el selector…";
    if (c.error) c.error.hidden = true;
    try {
      const r = await api("POST", "/api/ventana/elegir-carpeta");
      if (r.cancelado) return;
      c.ruta.value = r.ruta;
      // el nombre del proyecto se propone solo al AÑADIR una carpeta existente; en «Nueva carpeta» la elegida es la ubicación
      if (c.nombre && c.ruta.name !== "ubicacion" && !c.nombre.value.trim()) c.nombre.value = r.nombre;
      if (c.compartido && r.compartida_sugerida) c.compartido.checked = true;   // solo una propuesta: el usuario lo puede desmarcar
      if (c.pista) c.pista.hidden = !r.compartida_sugerida;
      c.ruta.dispatchEvent(new Event("input", { bubbles: true }));
    } catch (e) {
      if (c.error) { c.error.textContent = e.message; c.error.hidden = false; }
    } finally {
      boton.disabled = false; boton.textContent = etiqueta;
    }
  }
  botones().forEach((b) => b.addEventListener("click", () => elegir(b)));

  // La propuesta de «compartida» se retira si el usuario cambia la ruta a mano o desmarca la casilla
  $$("[data-pista-compartida]").forEach((p) => {
    const caja = p.closest("form") || p.closest("[data-add]");
    if (!caja) return;
    const casilla = caja.querySelector("[name=compartido], [data-f=compartido]");
    if (casilla) casilla.addEventListener("change", () => { if (!casilla.checked) p.hidden = true; });
  });

  // ------------------------------------------------------------ Nueva carpeta (inicio)
  const nc = $("#f-nueva-carpeta");
  if (!nc) return;
  const estado = $("[data-estado]", nc), error = $("[data-error]", nc);
  nc.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    error.hidden = true; estado.textContent = "Creando…";
    const boton = $("button[type=submit]", nc);
    boton.disabled = true;
    try {
      const ubic = nc.ubicacion.value.trim();
      const r = await api("POST", "/api/proyectos/carpeta", { nombre: nc.nombre.value.trim(), ubicacion: ubic || null, compartido: nc.compartido.checked });
      estado.textContent = r.registrada_como_extra ? `Creada y añadida como proyecto: ${r.proyecto.nombre}` : `Creada en la raíz de proyectos: ${r.proyecto.nombre}`;
      sincronizarConfig(r.proyectos_extra);
      nc.nombre.value = ""; nc.ubicacion.value = ""; nc.compartido.checked = false;
      $$("[data-pista-compartida]", nc).forEach((p) => { p.hidden = true; });
      seleccionar(r.proyecto.nombre);   // el proyecto queda seleccionado en la lista
    } catch (e) {
      estado.textContent = ""; error.textContent = e.message; error.hidden = false;
    } finally {
      boton.disabled = false;
    }
  });
})();
