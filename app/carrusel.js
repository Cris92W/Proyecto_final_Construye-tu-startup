// Carrusel del resultado: deslizar con el dedo (celular) o usar las flechas del teclado (computadora)
// equivale a pulsar «Atrás» o «Siguiente». Se instala una sola vez por página.
(() => {
  const pulsar = (texto) => {
    const boton = [...document.querySelectorAll(".st-key-nav button")].find((b) => b.innerText.includes(texto));
    if (boton && !boton.disabled) boton.click();
  };
  if (!window.__pillaoCarrusel) {
    window.__pillaoCarrusel = true;
    let x0 = null, y0 = null;
    document.addEventListener("touchstart", (e) => {
      x0 = e.touches[0].clientX; y0 = e.touches[0].clientY;
    }, { passive: true });
    document.addEventListener("touchend", (e) => {
      if (x0 === null) return;
      const dx = e.changedTouches[0].clientX - x0, dy = e.changedTouches[0].clientY - y0;
      x0 = null;
      if (Math.abs(dx) < 70 || Math.abs(dx) < 2 * Math.abs(dy)) return;  // fue un desplazamiento vertical
      pulsar(dx < 0 ? "Siguiente" : "Atrás");
    }, { passive: true });
    document.addEventListener("keydown", (e) => {
      if (["INPUT", "TEXTAREA"].includes(document.activeElement?.tagName)) return;
      if (e.key === "ArrowRight") pulsar("Siguiente");
      if (e.key === "ArrowLeft") pulsar("Atrás");
    });
  }
  // Cada cambio de diapositiva empieza arriba, sin tener que volver a subir.
  const principal = document.querySelector('[data-testid="stMain"]');
  (principal || window).scrollTo({ top: 0, behavior: "instant" });
})();
