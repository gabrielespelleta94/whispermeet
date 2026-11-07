"use strict";
/* Apuntes: aviso de llamada de Teams. Cuando Teams empieza a usar el micro, la pantalla de inicio propone grabar. Nunca
   empieza sola: «Preparar grabación» solo lleva el foco al aviso a los asistentes; la grabación empieza cuando la persona
   marca ese aviso y pulsa Empezar. «Ahora no» oculta el aviso hasta la siguiente llamada.
   Con ventana nativa, el aviso principal es la ventana flotante (aviso.html): entonces el evento «llamada» lleva `flotante` y este banner no sale.
   Si la reunión la empieza esa ventana, esta pantalla pasa sola a la vista de reunión (aquí se limpia lo de la reunión anterior). */
(() => {
  const AP = window.AP;
  if (!AP) return;
  const { $ } = AP;
  const banner = $("#i-llamada");
  let llamadaActiva = false;   // Teams está usando el micro (evento «llamada» o snapshot)
  let estado = "inactivo";     // solo se propone con la app libre: con una reunión en curso o pendiente de revisar no se ofrece
  let ocultado = false;        // «Ahora no» o «Preparar grabación»: no vuelve a salir hasta el siguiente inicio de llamada
  let flotante = false;        // la ventana flotante atiende esta llamada: no se duplica con el banner

  function pintar() {
    banner.hidden = !(llamadaActiva && !flotante && estado === "inactivo" && !ocultado);
  }

  const previo = AP.hooks.evento;
  AP.hooks.evento = (d) => {
    if (previo) previo(d);
    if (d.tipo === "snapshot") {
      llamadaActiva = !!d.llamada;
      flotante = !!d.llamada_flotante;
      estado = d.estado || estado;
      pintar();
    } else if (d.tipo === "estado") {
      if (estado === "inactivo" && d.estado && d.estado !== "inactivo" && AP.reiniciarReunion) AP.reiniciarReunion();   // reunión empezada desde otra ventana (el aviso flotante)
      estado = d.estado || estado;
      pintar();
    } else if (d.tipo === "llamada") {
      llamadaActiva = !!d.activa;
      flotante = !!d.activa && !!d.flotante;
      if (llamadaActiva) ocultado = false;   // una llamada nueva vuelve a proponer
      pintar();
    }
  };

  $("#i-llamada-no").addEventListener("click", () => {
    ocultado = true;
    pintar();
  });

  $("#i-llamada-si").addEventListener("click", () => {
    ocultado = true;
    pintar();
    const aviso = $("#i-aviso");   // solo el aviso a los asistentes: no se marca ni se pulsa Empezar
    aviso.scrollIntoView({ block: "center" });
    aviso.focus({ preventScroll: true });
  });
})();
