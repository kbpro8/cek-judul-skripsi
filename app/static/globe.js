/* 3D "thesis globe": every dot is a thesis, coloured by faculty in proportion to the real
   collection. The gold node is the student's proposal, linked to its nearest neighbours.
   Plain canvas with a small perspective projection, no libraries. */
(function () {
  const canvas = document.getElementById("globe");
  if (!canvas) return;
  const ctx = canvas.getContext("2d");
  const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;

  const css = getComputedStyle(document.documentElement);
  const palette = Array.from({ length: 10 }, (_, i) => css.getPropertyValue(`--f${i}`).trim() || "#1a9a66");
  const weights = (canvas.dataset.weights || "1").split(",").map(Number).filter((n) => n > 0);
  const totalW = weights.reduce((a, b) => a + b, 0);

  // Points on a Fibonacci sphere; faculty assigned by cumulative share.
  const N = innerWidth < 700 ? 420 : 680;
  const pts = [];
  const golden = Math.PI * (3 - Math.sqrt(5));
  let cum = 0, fi = 0, bound = weights[0] / totalW;
  for (let i = 0; i < N; i++) {
    const y = 1 - (i / (N - 1)) * 2;
    const r = Math.sqrt(1 - y * y);
    const th = golden * i;
    const jitter = 0.94 + Math.random() * 0.1;
    pts.push({ x: Math.cos(th) * r * jitter, y: y * jitter, z: Math.sin(th) * r * jitter, f: 0, s: 0.7 + Math.random() * 0.9 });
  }
  // Shuffle faculty assignment so colours form soft clusters rather than stripes.
  const order = pts.map((p, i) => i).sort((a, b) => (pts[a].x + pts[a].z * 0.6) - (pts[b].x + pts[b].z * 0.6));
  order.forEach((idx, k) => {
    cum = (k + 1) / N;
    while (cum > bound && fi < weights.length - 1) { fi++; bound += weights[fi] / totalW; }
    pts[idx].f = fi;
  });

  // Short edges between close neighbours.
  const edges = [];
  for (let i = 0; i < N; i++) {
    for (let j = i + 1; j < N; j++) {
      const dx = pts[i].x - pts[j].x, dy = pts[i].y - pts[j].y, dz = pts[i].z - pts[j].z;
      if (dx * dx + dy * dy + dz * dz < 0.018 && Math.random() < 0.55) edges.push([i, j]);
    }
  }

  // The proposal: a node just above the surface, linked to its nearest theses.
  const prop = { x: 0.36, y: -0.22, z: 0.9 };
  const pl = Math.hypot(prop.x, prop.y, prop.z);
  prop.x *= 1.12 / pl; prop.y *= 1.12 / pl; prop.z *= 1.12 / pl;
  const near = pts
    .map((p, i) => [i, (p.x - prop.x) ** 2 + (p.y - prop.y) ** 2 + (p.z - prop.z) ** 2])
    .sort((a, b) => a[1] - b[1]).slice(0, 6).map((a) => a[0]);

  let W = 0, H = 0, R = 0, dpr = 1;
  function resize() {
    const rect = canvas.getBoundingClientRect();
    dpr = Math.min(devicePixelRatio || 1, 2);
    W = rect.width; H = rect.height; R = Math.min(W, H) * 0.36;
    canvas.width = W * dpr; canvas.height = H * dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  }
  resize();
  addEventListener("resize", resize);

  let mx = 0, my = 0, tx = 0, ty = 0;
  addEventListener("pointermove", (e) => {
    tx = (e.clientX / innerWidth - 0.5) * 0.5;
    ty = (e.clientY / innerHeight - 0.5) * 0.35;
  });

  const tilt = 0.32;
  function project(p, rotY, rotX) {
    let x = p.x * Math.cos(rotY) - p.z * Math.sin(rotY);
    let z = p.x * Math.sin(rotY) + p.z * Math.cos(rotY);
    let y = p.y * Math.cos(rotX) - z * Math.sin(rotX);
    z = p.y * Math.sin(rotX) + z * Math.cos(rotX);
    const persp = 2.6 / (2.6 - z);
    return { X: W / 2 + x * R * persp, Y: H / 2 + y * R * persp, z, k: persp };
  }

  function hexA(hex, a) {
    const h = hex.replace("#", "");
    const n = parseInt(h.length === 3 ? h.split("").map((c) => c + c).join("") : h, 16);
    return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`;
  }

  let t0 = performance.now(), visible = true;
  function frame(now) {
    const t = (now - t0) / 1000;
    mx += (tx - mx) * 0.05; my += (ty - my) * 0.05;
    const rotY = (reduce ? 0.6 : t * 0.12) + mx;
    const rotX = tilt + my;
    ctx.clearRect(0, 0, W, H);

    // atmosphere
    const g = ctx.createRadialGradient(W / 2, H / 2, R * 0.2, W / 2, H / 2, R * 1.35);
    g.addColorStop(0, "rgba(26,154,102,0.10)");
    g.addColorStop(0.75, "rgba(26,154,102,0.05)");
    g.addColorStop(1, "rgba(26,154,102,0)");
    ctx.fillStyle = g;
    ctx.beginPath(); ctx.arc(W / 2, H / 2, R * 1.35, 0, Math.PI * 2); ctx.fill();

    // orbit ring
    ctx.save();
    ctx.translate(W / 2, H / 2); ctx.rotate(-0.35);
    ctx.strokeStyle = "rgba(241,207,122,0.22)"; ctx.lineWidth = 1;
    ctx.setLineDash([2, 6]);
    ctx.beginPath(); ctx.ellipse(0, 0, R * 1.42, R * 0.38, 0, 0, Math.PI * 2); ctx.stroke();
    ctx.restore(); ctx.setLineDash([]);

    const P = pts.map((p) => project(p, rotY, rotX));

    ctx.lineWidth = 0.6;
    for (const [a, b] of edges) {
      const pa = P[a], pb = P[b];
      const depth = (pa.z + pb.z) / 2;
      if (depth < -0.2) continue;
      ctx.strokeStyle = `rgba(255,255,255,${0.04 + (depth + 0.2) * 0.1})`;
      ctx.beginPath(); ctx.moveTo(pa.X, pa.Y); ctx.lineTo(pb.X, pb.Y); ctx.stroke();
    }

    const idx = P.map((p, i) => i).sort((a, b) => P[a].z - P[b].z);
    for (const i of idx) {
      const p = P[i], d = (p.z + 1) / 2;
      ctx.fillStyle = hexA(palette[pts[i].f % palette.length], 0.18 + d * 0.82);
      ctx.beginPath(); ctx.arc(p.X, p.Y, (0.6 + d * 1.9) * pts[i].s * p.k, 0, Math.PI * 2); ctx.fill();
    }

    // proposal node + links
    const pp = project(prop, rotY, rotX);
    const front = pp.z > -0.1;
    const pulse = reduce ? 0.5 : (Math.sin(t * 2.4) + 1) / 2;
    for (const i of near) {
      const q = P[i];
      ctx.strokeStyle = `rgba(241,207,122,${front ? 0.55 : 0.15})`;
      ctx.lineWidth = 1.2;
      ctx.beginPath(); ctx.moveTo(pp.X, pp.Y); ctx.lineTo(q.X, q.Y); ctx.stroke();
      ctx.fillStyle = `rgba(241,207,122,${front ? 0.9 : 0.3})`;
      ctx.beginPath(); ctx.arc(q.X, q.Y, 2.6 * q.k, 0, Math.PI * 2); ctx.fill();
    }
    ctx.fillStyle = `rgba(241,207,122,${(front ? 0.25 : 0.08) * (1 - pulse)})`;
    ctx.beginPath(); ctx.arc(pp.X, pp.Y, 8 + pulse * 22, 0, Math.PI * 2); ctx.fill();
    const core = ctx.createRadialGradient(pp.X - 2, pp.Y - 2, 0, pp.X, pp.Y, 8);
    core.addColorStop(0, "#fff"); core.addColorStop(0.5, "#f1cf7a"); core.addColorStop(1, "#d6a740");
    ctx.fillStyle = core; ctx.globalAlpha = front ? 1 : 0.35;
    ctx.beginPath(); ctx.arc(pp.X, pp.Y, 6.5 * pp.k, 0, Math.PI * 2); ctx.fill();
    ctx.globalAlpha = 1;

    if (!reduce && visible) requestAnimationFrame(frame);
  }

  new IntersectionObserver(([e]) => {
    const was = visible; visible = e.isIntersecting;
    if (visible && !was && !reduce) requestAnimationFrame(frame);
  }).observe(canvas);
  requestAnimationFrame(frame);
})();
