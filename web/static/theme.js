(function () {
  var boton = document.getElementById("theme-toggle");
  if (!boton) return;

  function actualizarBoton(tema) {
    var esClaro = tema === "light";
    boton.textContent = esClaro ? "☀️" : "🌙";
    boton.setAttribute("aria-pressed", String(esClaro));
    boton.setAttribute(
      "aria-label",
      esClaro ? "Cambiar a tema oscuro" : "Cambiar a tema claro"
    );
  }

  actualizarBoton(document.documentElement.getAttribute("data-theme"));

  boton.addEventListener("click", function () {
    var actual = document.documentElement.getAttribute("data-theme");
    var nuevo = actual === "light" ? "dark" : "light";
    document.documentElement.setAttribute("data-theme", nuevo);
    try {
      localStorage.setItem("tema", nuevo);
    } catch (e) {}
    actualizarBoton(nuevo);
  });
})();
