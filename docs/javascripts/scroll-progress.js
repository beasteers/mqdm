(() => {
  const el = document.createElement("div");
  el.id = "mqdm-scroll-progress";
  document.body.prepend(el);

  const update = () => {
    const h = document.documentElement;
    const pct = h.scrollHeight <= h.clientHeight
      ? 1
      : h.scrollTop / (h.scrollHeight - h.clientHeight);
    el.style.transform = `scaleX(${pct})`;
  };

  window.addEventListener("scroll", update, {passive: true});
  window.addEventListener("resize", update, {passive: true});
  update();
})();
