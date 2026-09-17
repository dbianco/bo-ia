(function () {
  function botonPara(input) {
    return document.querySelector('.borrar-fecha[data-target="' + input.id + '"]');
  }

  function actualizarBoton(input) {
    var boton = botonPara(input);
    if (boton) boton.hidden = !input.value;
  }

  function conectar(idPropio, idOtro, esDesde) {
    var propio = document.getElementById(idPropio);
    var otro = document.getElementById(idOtro);
    var boton = botonPara(propio);
    if (!propio || !otro || !boton) return;

    actualizarBoton(propio);

    propio.addEventListener("click", function () {
      if (typeof propio.showPicker === "function") {
        try {
          propio.showPicker();
        } catch (e) {}
      }
    });

    propio.addEventListener("input", function () {
      actualizarBoton(propio);
      if (!propio.value || !otro.value) return;
      var fueraDeRango = esDesde ? propio.value > otro.value : propio.value < otro.value;
      if (fueraDeRango) {
        otro.value = propio.value;
        actualizarBoton(otro);
      }
    });

    boton.addEventListener("click", function () {
      propio.value = "";
      actualizarBoton(propio);
      propio.focus();
    });
  }

  conectar("date_from", "date_to", true);
  conectar("date_to", "date_from", false);
})();
