window.renderMqdmCast = function renderMqdmCast(id, src, options = {}) {
  const el = document.getElementById(id);
  if (!el || typeof AsciinemaPlayer === "undefined") return;
  AsciinemaPlayer.create(
    src,
    el,
    Object.assign(
      {
        autoPlay: true,
        loop: true,
        fit: "width",
        rows: 18,
        cols: 120,
        terminalFontSize: "14px",
        theme: "asciinema",
      },
      options,
    ),
  );
};

document.addEventListener("DOMContentLoaded", () => {
  for (const el of document.querySelectorAll(".mqdm-cast[data-cast-src]")) {
    const id = el.getAttribute("id");
    const src = el.getAttribute("data-cast-src");
    if (!id || !src) continue;
    window.renderMqdmCast(id, src);
  }
});
