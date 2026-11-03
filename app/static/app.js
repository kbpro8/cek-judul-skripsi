/* Small UI behaviours: loading overlay, word counter, 3D tilt, count-up, reveal animations. */
(function () {
  const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const fmt = (n) => Math.round(n).toLocaleString("id-ID");

  // Loading overlay while the server compares the proposal.
  const overlay = document.querySelector(".loading");
  document.querySelectorAll("form[data-check]").forEach((form) => {
    form.addEventListener("submit", () => {
      if (!overlay || !form.checkValidity()) return;
      const msg = overlay.querySelector("p");
      const steps = JSON.parse(overlay.dataset.steps || "[]");
      let i = 0;
      overlay.classList.add("show");
      if (msg && steps.length) {
        msg.textContent = steps[0];
        setInterval(() => { i = (i + 1) % steps.length; msg.textContent = steps[i]; }, 900);
      }
    });
  });
  addEventListener("pageshow", () => overlay && overlay.classList.remove("show"));

  // Live word counter on the title field.
  document.querySelectorAll("[data-words]").forEach((input) => {
    const out = document.getElementById(input.dataset.words);
    const update = () => {
      const n = input.value.trim() ? input.value.trim().split(/\s+/).length : 0;
      out.textContent = n ? `${n} kata` : "minimal 3 kata";
      out.classList.toggle("ok", n >= 3);
    };
    input.addEventListener("input", update); update();
  });

  // Gentle 3D tilt on cards.
  if (!reduce && matchMedia("(hover: hover)").matches) {
    document.querySelectorAll("[data-tilt]").forEach((el) => {
      const max = Number(el.dataset.tilt) || 6;
      el.addEventListener("pointermove", (e) => {
        const r = el.getBoundingClientRect();
        const x = (e.clientX - r.left) / r.width - 0.5, y = (e.clientY - r.top) / r.height - 0.5;
        el.style.transform = `perspective(900px) rotateX(${-y * max}deg) rotateY(${x * max}deg) translateY(-3px)`;
      });
      el.addEventListener("pointerleave", () => { el.style.transform = ""; });
    });
  }

  // Count-up numbers and reveal-on-scroll.
  const io = new IntersectionObserver((entries) => {
    for (const e of entries) {
      if (!e.isIntersecting) continue;
      const el = e.target;
      io.unobserve(el);
      if (el.dataset.count !== undefined) {
        const end = Number(el.dataset.count);
        if (reduce) { el.textContent = fmt(end); continue; }
        const t0 = performance.now(), dur = 1400;
        const tick = (now) => {
          const p = Math.min(1, (now - t0) / dur);
          el.textContent = fmt(end * (1 - Math.pow(1 - p, 3)));
          if (p < 1) requestAnimationFrame(tick);
        };
        requestAnimationFrame(tick);
      } else {
        el.classList.remove("pending");
      }
    }
  }, { threshold: 0.3 });
  document.querySelectorAll("[data-count]").forEach((el) => io.observe(el));
  if (!reduce) {
    document.querySelectorAll(".fac-bars").forEach((el) => {
      el.classList.add("pending");
      io.observe(el);
      // Never leave the chart empty if the scroll trigger does not fire (e.g. background tab).
      setTimeout(() => el.classList.remove("pending"), 3000);
    });
  }

  // Admin upload drop zone.
  document.querySelectorAll(".dropzone").forEach((zone) => {
    const input = zone.querySelector("input[type=file]");
    const label = zone.querySelector("[data-file]");
    const show = () => { if (input.files[0]) label.textContent = input.files[0].name; };
    input.addEventListener("change", show);
    ["dragenter", "dragover"].forEach((ev) => zone.addEventListener(ev, (e) => { e.preventDefault(); zone.classList.add("drag"); }));
    ["dragleave", "drop"].forEach((ev) => zone.addEventListener(ev, () => zone.classList.remove("drag")));
    zone.addEventListener("drop", (e) => { e.preventDefault(); input.files = e.dataTransfer.files; show(); });
  });
})();
