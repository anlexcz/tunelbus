(() => {
  const button = document.querySelector(".site-menu-button");
  const navigation = document.querySelector("#site-navigation");
  if (!button || !navigation) return;

  const mobileQuery = window.matchMedia("(max-width: 760px)");
  const close = ({ returnFocus = false } = {}) => {
    button.setAttribute("aria-expanded", "false");
    button.setAttribute("aria-label", "Otevřít navigaci");
    navigation.classList.remove("site-nav--open");
    if (returnFocus) button.focus();
  };
  const open = () => {
    button.setAttribute("aria-expanded", "true");
    button.setAttribute("aria-label", "Zavřít navigaci");
    navigation.classList.add("site-nav--open");
  };

  button.addEventListener("click", () => {
    button.getAttribute("aria-expanded") === "true" ? close() : open();
  });
  navigation.addEventListener("click", event => {
    if (event.target.closest("a")) close();
  });
  document.addEventListener("keydown", event => {
    if (event.key === "Escape" && button.getAttribute("aria-expanded") === "true") close({ returnFocus: true });
  });
  mobileQuery.addEventListener("change", event => {
    if (!event.matches) close();
  });
})();
