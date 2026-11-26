// Before the page is drawn, so that it does not flash in the other theme.
(function () {
  var tema = "dark";
  try {
    if (localStorage.getItem("tema") === "light") tema = "light";
  } catch (e) {}
  document.documentElement.setAttribute("data-theme", tema);
})();
