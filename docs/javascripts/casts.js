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
        cols: 100,
        terminalFontSize: "14px",
        theme: "asciinema",
        cursorMode: "steady",
      },
      options,
    ),
  );
};

const OPTION_KEYS = {
  cols: 'cols',
  rows: 'rows',
  terminalFontSize: 'terminal-font-size',
  theme: 'theme',
}

document.addEventListener("DOMContentLoaded", () => {
  for (const el of document.querySelectorAll(".mqdm-cast[data-cast-src]")) {
    const id = el.getAttribute("id");
    const src = el.getAttribute("data-cast-src");
    if (!id || !src) continue;
    const options = {};
    for(const [key, attr] of Object.entries(OPTION_KEYS)) {
      const value = el.getAttribute(`data-${attr}`);
      if (value !== null) options[key] = value;
    }
    // options.cursorMode = "hidden";
    window.renderMqdmCast(id, src, options);
  }
});
