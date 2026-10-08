/* Swap the header logo and favicon with the color scheme: dark ink on light, white ink on slate.
   Paths are derived from what the theme already rendered, so nested pages keep working. */
(function () {
  function isSlate() {
    return document.body.getAttribute("data-md-color-scheme") === "slate";
  }
  function swap(selector, attr, light, dark) {
    var el = document.querySelector(selector);
    if (!el) return;
    var cur = el.getAttribute(attr) || "";
    var next = cur.replace(/logo-(light|dark)\.png$/, isSlate() ? dark : light);
    if (next !== cur) el.setAttribute(attr, next);
  }
  function apply() {
    swap(".md-header__button.md-logo img", "src", "logo-light.png", "logo-dark.png");
    swap('link[rel="icon"], link[rel="shortcut icon"]', "href", "logo-light.png", "logo-dark.png");
  }
  new MutationObserver(apply).observe(document.body, { attributes: true, attributeFilter: ["data-md-color-scheme"] });
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", apply);
  else apply();
})();
