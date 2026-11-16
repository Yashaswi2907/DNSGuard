/* Landing page: animated recursive-resolution trace + resolver preview from real stored data. */
(function () {
  "use strict";
  const { $, $$, esc, fmt } = DG;

  // Theme toggle on the landing nav (main.js wires #theme-toggle too).

  /* ----------------------------------------------- resolution trace */
  const SEG = {
    0: [[120, 135], [205, 135]],
    1: [[355, 135], [420, 50]],
    2: [[355, 135], [420, 135]],
    3: [[355, 135], [420, 220]],
  };
  // Illustrative protocol steps (no timings are shown: this is a diagram, not a measurement).
  const STEPS = [
    { seg: 0, dir: 1, from: "client", to: "resolver", log: '<b>query</b>  www.example.com IN A  <span class="muted">RD=1, UDP/53</span>' },
    { seg: 1, dir: 1, from: "resolver", to: "root", log: '<b>resolver → root</b>  who serves .com?' },
    { seg: 1, dir: -1, reply: true, from: "root", to: "resolver", log: "root → referral to .com NS" },
    { seg: 2, dir: 1, from: "resolver", to: "tld", log: '<b>resolver → .com</b>  who serves example.com?' },
    { seg: 2, dir: -1, reply: true, from: "tld", to: "resolver", log: ".com → referral to example.com NS" },
    { seg: 3, dir: 1, from: "resolver", to: "auth", log: '<b>resolver → authoritative</b>  www.example.com A?' },
    { seg: 3, dir: -1, reply: true, from: "auth", to: "resolver", log: "authoritative → A record + TTL" },
    { seg: 0, dir: -1, reply: true, from: "resolver", to: "client", log: '<em>NOERROR</em>  answer returned, cached for its TTL' },
    { seg: 0, dir: 1, from: "client", to: "resolver", log: '<b>repeat query</b>  www.example.com IN A' },
    { seg: 0, dir: -1, reply: true, from: "resolver", to: "client", log: '<em>NOERROR</em>  served from resolver cache' },
  ];
  const packet = $("#packet");
  const log = $("#trace-log");
  const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  function setActive(step) {
    $$(".net-node").forEach((n) => n.classList.toggle("active", step && (n.dataset.node === step.from || n.dataset.node === step.to)));
    $$(".net-link").forEach((l) => l.classList.toggle("active", step && Number(l.dataset.seg) === step.seg));
  }
  function addLog(html) {
    const ln = document.createElement("div");
    ln.className = "ln"; ln.innerHTML = html; // static strings defined above
    log.appendChild(ln);
    while (log.children.length > 5) log.removeChild(log.firstChild);
  }
  function animate(step) {
    return new Promise((resolve) => {
      const [a, b] = SEG[step.seg];
      const [p0, p1] = step.dir > 0 ? [a, b] : [b, a];
      packet.classList.toggle("reply", !!step.reply);
      const dur = 650; const t0 = performance.now();
      function frame(t) {
        const k = Math.min(1, (t - t0) / dur);
        const e = k < 0.5 ? 2 * k * k : 1 - Math.pow(-2 * k + 2, 2) / 2;
        packet.setAttribute("cx", p0[0] + (p1[0] - p0[0]) * e);
        packet.setAttribute("cy", p0[1] + (p1[1] - p0[1]) * e);
        if (k < 1) requestAnimationFrame(frame); else resolve();
      }
      requestAnimationFrame(frame);
    });
  }
  async function loop() {
    if (reduce) { STEPS.slice(4).forEach((s) => addLog(s.log)); return; }
    let visible = true;
    document.addEventListener("visibilitychange", () => { visible = !document.hidden; });
    for (;;) {
      log.innerHTML = "";
      for (const step of STEPS) {
        while (!visible) await DG.sleep(400);
        setActive(step); addLog(step.log);
        await animate(step);
        await DG.sleep(260);
      }
      setActive(null);
      packet.setAttribute("cx", -20);
      await DG.sleep(2200);
    }
  }
  if (packet && log) loop();

  /* --------------------------------------------- resolver preview */
  async function preview() {
    const box = $("#preview-cards");
    if (!box) return;
    let stats = null;
    try { stats = await DG.api("/api/dashboard/stats"); } catch (e) { /* show static info below */ }
    const per = stats?.per_resolver || {};
    box.innerHTML = DG.config.resolvers.map((r) => {
      const s = per[r.key];
      const has = s && s.total > 0;
      const med = fmt.msParts(has ? s.median_latency_ms : null);
      return `
        <article class="panel res-card ${esc(r.key)}">
          <div class="res-head"><div class="res-name"><span class="swatch ${esc(r.key)}"></span>${esc(r.name)} <span class="res-ip">${esc(r.ip)}</span></div>
            ${has ? `<span class="badge neutral"><i data-lucide="database"></i>${fmt.int(s.total)} recorded queries</span>` : '<span class="badge neutral"><i data-lucide="circle-dashed"></i>Not measured yet</span>'}</div>
          <div class="metrics">
            <div class="metric"><div class="m-label">Median latency</div><div class="m-value">${med.v} <small>${med.u}</small></div></div>
            <div class="metric"><div class="m-label">Successful</div><div class="m-value">${has ? fmt.int(s.successful) : "—"}</div></div>
            <div class="metric"><div class="m-label">Failure rate</div><div class="m-value">${has ? fmt.pct(s.failure_rate) : "—"}</div></div>
          </div>
          <p class="muted" style="margin-top:12px;font-size:13px">IPv6 ${esc(r.ipv6)}, operated by ${esc(r.operator)}.</p>
        </article>`;
    }).join("");
    const lede = $("#preview-lede");
    if (stats && stats.total_queries > 0) {
      lede.textContent = `Measured on this installation across ${stats.total_queries.toLocaleString()} queries in ${stats.tests} test(s). These numbers describe your network and time of testing, not the resolvers in general.`;
    } else {
      lede.innerHTML = 'No tests have been run on this installation yet, so there are no measurements to show. <a href="/comparison">Run a comparison</a> to fill these in with real numbers.';
    }
    DG.icons();
  }
  preview();
})();
