(function () {
  var campo = document.getElementById("q");
  if (!campo) return;

  var ALTURA_MAXIMA_PX = 136; // coincide con max-height de textarea#q en style.css

  function autoCrecer() {
    campo.style.height = "auto";
    campo.style.height = Math.min(campo.scrollHeight, ALTURA_MAXIMA_PX) + "px";
  }

  campo.addEventListener("input", autoCrecer);
  autoCrecer();

  campo.addEventListener("keydown", function (evento) {
    if (evento.key === "Enter" && !evento.shiftKey) {
      evento.preventDefault();
      var formulario = campo.closest("form");
      if (formulario && campo.value.trim()) {
        formulario.requestSubmit();
      }
    }
  });
})();
