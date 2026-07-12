(() => {
  const el = document.createElement("div");
  el.id = "mqdm-scroll-progress";
  document.body.prepend(el);

  const update = () => {
    const h = document.documentElement;
    const max = h.scrollHeight - h.clientHeight;
    if (max <= 0) { el.style.transform = "scaleX(0)"; return; }
    el.style.transform = `scaleX(${h.scrollTop / max})`;
  };

  window.addEventListener("scroll", update, {passive: true});
  window.addEventListener("resize", update, {passive: true});
  update();
})();
