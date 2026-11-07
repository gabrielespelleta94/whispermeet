"use strict";
/* WhisperMeet: «Contexto de la reunión» en la pantalla de inicio.
   - Se escribe en la caja de texto o se dicta con el micro («Dictar»: captura de micro y faster-whisper locales, solo en memoria; el texto
     se añade a la caja). Con una reunión en marcha el dictado queda desactivado.
   - «Generar con Claude»: UNA llamada (haiku), solo al pulsarlo, sin reintentos. Devuelve un resumen de contexto y hasta 5 objetivos que
     se muestran editables; NADA se aplica hasta «Aceptar».
   - Al aceptar: el texto viaja en /api/sesion/iniciar (contexto_reunion), los objetivos se suman a UI.objetivosPropios y, si se marcó
     «Guardar en el contexto del proyecto», se escribe NN-contexto-reunion-<tema>.md con su entrada en 10-registro-de-cambios.md.
   - Un fallo se muestra aquí y no impide empezar la reunión. Todo el texto dinámico entra con textContent o .value. */
(() => {
  const AP = window.AP;
  if (!AP) return;
  const { S, UI, h, $, api } = AP;
  const MAX_OBJ = 12;

  UI.contextoReunion = "";
  const C = { dictando: false, fase: "parado", ultimoN: 0, generando: false, objs: [], propuesta: null };

  const caja = $("#i-ctxr"), texto = $("#i-ctxr-texto"), btnDictar = $("#i-ctxr-dictar"), btnGenerar = $("#i-ctxr-generar");
  const estadoDictado = $("#i-ctxr-dictado"), errorEl = $("#i-ctxr-error"), prop = $("#i-ctxr-prop"), res = $("#i-ctxr-res");
  const lista = $("#i-ctxr-obj"), chkGuardar = $("#i-ctxr-guardar"), notaGuardar = $("#i-ctxr-guardar-nota"), meta = $("#i-ctxr-meta");
  const ok = $("#i-ctxr-ok"), okT = $("#i-ctxr-ok-t"), etq = $("#i-ctxr-estado");
  if (!caja) return;

  const palabras = (t) => (t.match(/\S+/g) || []).length;
  const enReunion = () => S.estado !== "inactivo";
  const mostrarError = (m) => { errorEl.textContent = m || ""; errorEl.hidden = !m; };

  function refrescar() {
    const bloqueadoDictar = enReunion() || C.generando;
    btnDictar.disabled = bloqueadoDictar && !C.dictando;
    btnDictar.title = enReunion() ? "Hay una reunión grabando: el dictado no está disponible" : "Dicta con el micrófono: se transcribe en tu equipo y el audio no se guarda";
    btnDictar.setAttribute("aria-pressed", String(C.dictando));
    btnDictar.textContent = C.fase === "iniciando" ? "Abriendo el micro…" : C.fase === "cerrando" ? "Cerrando…" : C.dictando ? "Parar dictado" : "Dictar";
    if (C.fase === "iniciando" || C.fase === "cerrando") btnDictar.disabled = true;
    btnGenerar.disabled = C.generando || C.dictando || palabras(texto.value) < 3;
    btnGenerar.textContent = C.generando ? "Generando…" : "Generar con Claude";
    texto.readOnly = C.generando;
    etq.textContent = UI.contextoReunion ? "Aceptado" : !prop.hidden ? "Propuesta lista" : C.generando ? "Generando…" : C.dictando ? "Dictando…" : "Opcional";
  }

  // ------------------------------------------------------------ dictado
  function anadir(fragmento) {
    const f = String(fragmento || "").trim();
    if (!f) return;
    const sep = texto.value && !/\s$/.test(texto.value) ? " " : "";
    texto.value = (texto.value + sep + f).slice(0, 6000);
    texto.scrollTop = texto.scrollHeight;
    refrescar();
  }
  function recoger(fragmentos) { for (const f of fragmentos || []) if (f.n > C.ultimoN) { C.ultimoN = f.n; anadir(f.texto); } }
  const TEXTO_FASE = { iniciando: "Abriendo el micrófono y preparando la transcripción…", dictando: "Escuchando: habla con normalidad", cerrando: "Transcribiendo lo último…" };
  function fijarFase(fase, error) {
    C.fase = fase;
    C.dictando = fase === "dictando" || fase === "iniciando" || fase === "cerrando";
    estadoDictado.textContent = TEXTO_FASE[fase] || "";
    if (error) mostrarError(error); else if (fase === "dictando" || fase === "iniciando") mostrarError("");
    refrescar();
  }
  async function alternarDictado() {
    if (C.fase === "iniciando" || C.fase === "cerrando") return;
    mostrarError("");
    caja.open = true;
    try {
      if (!C.dictando) {
        C.ultimoN = 0;
        fijarFase("iniciando");
        const r = await api("POST", "/api/contexto-reunion/dictado/iniciar", { idioma: UI.idioma || "auto" });   // el mismo «Idioma de la reunión» del inicio
        fijarFase(r.estado === "dictando" ? "dictando" : r.estado);
      } else {
        fijarFase("cerrando");
        const r = await api("POST", "/api/contexto-reunion/dictado/parar");
        recoger(r.fragmentos);
        fijarFase("parado", r.error);
      }
    } catch (e) {
      fijarFase("parado", e.message);
    }
  }
  btnDictar.addEventListener("click", alternarDictado);
  texto.addEventListener("input", refrescar);

  // ------------------------------------------------------------ guardar en el contexto del proyecto: cuándo se puede
  function disponibilidadGuardar() {
    if (typeof UI.sel !== "string") return { ok: false, nota: UI.sel === null ? "La Bandeja no tiene contexto de proyecto donde guardar." : "Elige un proyecto para poder guardarlo en su contexto." };
    const p = UI.proy;
    if (p && p.compartido && !p.tiene_contexto) return { ok: false, nota: "Es una carpeta compartida sin «00. CONTEXTO (IA)»: WhisperMeet no la crea ahí, así que no se puede guardar." };
    if (p && p.compartido) return { ok: true, nota: "Se escribirá en la carpeta compartida de otra persona: un fichero nuevo NN-contexto-reunion-… y una entrada en 10-registro-de-cambios.md." };
    if (p && !p.tiene_contexto) return { ok: true, nota: "El proyecto no tiene «00. CONTEXTO (IA)»: se creará con las plantillas y se añadirá un fichero NN-contexto-reunion-…." };
    return { ok: true, nota: "Se escribe un fichero nuevo NN-contexto-reunion-… y una entrada en 10-registro-de-cambios.md. No toca nada más." };
  }
  function actualizarGuardar() {
    const d = disponibilidadGuardar();
    chkGuardar.disabled = !d.ok;
    if (!d.ok) chkGuardar.checked = false;
    notaGuardar.textContent = d.nota;
  }
  new MutationObserver(actualizarGuardar).observe($("#i-lista"), { childList: true, attributes: true, subtree: true, attributeFilter: ["aria-selected"] });

  // ------------------------------------------------------------ propuesta de Claude (editable; no se aplica nada hasta «Aceptar»)
  function pintarObjetivos() {
    lista.replaceChildren(...C.objs.map((t, i) => h("li", {},
      h("textarea", { class: "input obj-ed", rows: "1", maxlength: "120", "aria-label": `Objetivo ${i + 1}`,
        oninput: (ev) => { const v = ev.target.value.replace(/\s*[\r\n]+\s*/g, " "); if (v !== ev.target.value) ev.target.value = v; C.objs[i] = v; } }, t),
      h("button", { type: "button", class: "btn btn-ghost btn-mini", "aria-label": "Quitar el objetivo: " + t, onclick: () => { C.objs.splice(i, 1); pintarObjetivos(); } }, "Quitar"))));
    if (!C.objs.length) lista.append(h("li", { class: "t-meta" }, "Claude no ha propuesto objetivos con este texto."));
  }
  function mostrarPropuesta(r) {
    C.propuesta = r;
    res.value = r.contexto || "";
    C.objs = (r.objetivos || []).slice();
    pintarObjetivos();
    meta.textContent = [r.modelo, r.tokens ? `${AP.kfmt(r.tokens)} tokens` : ""].filter(Boolean).join(" · ");
    actualizarGuardar();
    prop.hidden = false;
    refrescar();
  }
  btnGenerar.addEventListener("click", async () => {
    const t = texto.value.trim();
    if (palabras(t) < 3 || C.generando) return;
    mostrarError("");
    C.generando = true; refrescar();
    try {
      mostrarPropuesta(await api("POST", "/api/contexto-reunion/generar", { texto: t, tema: $("#i-tema").value.trim() }));
    } catch (e) {
      mostrarError("No se pudo generar el contexto: " + e.message + " Puedes empezar la reunión igualmente o volver a intentarlo.");
    } finally { C.generando = false; refrescar(); }
  });
  $("#i-ctxr-descartar").addEventListener("click", () => { prop.hidden = true; C.propuesta = null; mostrarError(""); refrescar(); });

  $("#i-ctxr-aceptar").addEventListener("click", async () => {
    const aceptado = res.value.trim();
    const objetivos = C.objs.map((o) => o.trim()).filter(Boolean);
    if (!aceptado) { mostrarError("La propuesta está vacía: escribe el contexto o descártala."); return; }
    mostrarError("");
    let guardado = "";
    if (chkGuardar.checked && !chkGuardar.disabled) {
      try {
        const g = await api("POST", "/api/contexto-reunion/guardar", { proyecto: UI.sel, tema: $("#i-tema").value.trim(), texto: aceptado, objetivos });
        guardado = g.fichero;
      } catch (e) { mostrarError("No se pudo guardar en el contexto del proyecto: " + e.message + " Desmarca la casilla para aceptarlo sin guardar."); return; }
    }
    UI.contextoReunion = aceptado;
    let nuevos = 0;
    for (const o of objetivos) {
      if (UI.objetivosPropios.length >= MAX_OBJ) break;
      if (UI.objetivosPropios.some((x) => x.toLowerCase() === o.toLowerCase())) continue;
      UI.objetivosPropios.push(o.slice(0, 200)); nuevos++;
    }
    if (AP.pintarObjInicio) AP.pintarObjInicio();
    const visibles = !$("#i-obj-campo").hidden;
    okT.textContent = `Contexto aceptado (${aceptado.length} caracteres): se usará para analizar la reunión.`
      + (objetivos.length ? (visibles ? ` ${nuevos} objetivo(s) añadido(s) a los de esta reunión.` : " Los objetivos no se usarán con esta selección (Bandeja o sesión del plan con objetivos propios).") : "")
      + (guardado ? ` Guardado en ${guardado}.` : "");
    ok.hidden = false; prop.hidden = true; C.propuesta = null;
    refrescar();
  });
  $("#i-ctxr-quitar").addEventListener("click", () => { UI.contextoReunion = ""; ok.hidden = true; refrescar(); });

  // ------------------------------------------------------------ eventos del servidor (dictado en directo) y reinicio al empezar
  const previo = AP.hooks.evento;
  AP.hooks.evento = (d) => {
    if (previo) previo(d);
    if (d.tipo === "dictado") {
      if (d.fase === "texto" && d.n > C.ultimoN) { C.ultimoN = d.n; anadir(d.texto); }
      else if (d.fase === "estado") {
        // el estado «parado» lo fija la respuesta de «Parar»; aquí solo se sigue a quien lo inició y se limpia si el servidor lo cancela
        if (d.estado === "parado" && C.dictando && C.fase !== "cerrando") fijarFase("parado", d.error);
        else if (d.estado === "dictando" && d.error) mostrarError(d.error);
      }
    }
    if (d.tipo === "estado" || d.tipo === "snapshot") {
      if (d.estado === "grabando" && (UI.contextoReunion || texto.value)) reiniciar();
      refrescar();
    }
  };
  function reiniciar() {
    UI.contextoReunion = ""; texto.value = ""; res.value = ""; C.objs = []; C.propuesta = null;
    prop.hidden = true; ok.hidden = true; mostrarError(""); estadoDictado.textContent = "";
    caja.open = false;
  }
  AP.hooks.antesDeEmpezar = async () => { if (C.dictando) await alternarDictado(); };

  actualizarGuardar();
  refrescar();
})();
