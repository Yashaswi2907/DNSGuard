/* Overview dashboard: every number comes from /api/dashboard/stats (stored real queries). */
(function () {
  "use strict";
  const { $, esc, fmt } = DG;
  let stats = null;

  const setKpi = (id, html, note) => {
    $(`#${id}`).innerHTML = html;
    $(`#${id}-note`).innerHTML = note || "&nbsp;";
  };

  function renderKpis(s) {
    const has = s.total_queries > 0;
    setKpi("k-total", fmt.int(s.total_queries), `${fmt.int(s.tests)} test${s.tests === 1 ? "" : "s"}`);
    setKpi("k-success", fmt.int(s.successful), has ? `${fmt.pct((s.successful / s.total_queries) * 100)} of queries` : "No data yet");
    setKpi("k-failed", fmt.int(s.failed), has ? `+${fmt.int(s.no_data)} no-record, not failures` : "No data yet");
    const m = fmt.msParts(s.median_latency_ms);
    setKpi("k-median", `${m.v}<small>${m.u}</small>`, s.mean_latency_ms !== null ? `mean ${fmt.ms(s.mean_latency_ms)}` : "No successful samples");
    const states = Object.values(s.resolver_health).map((h) => h.status);
    let label = "No data", cls = "neutral";
    if (states.every((x) => x === "operational")) { label = "Responding"; cls = "ok"; }
    else if (states.some((x) => x === "unresponsive")) { label = "Issue seen"; cls = "err"; }
    else if (states.some((x) => x === "degraded")) { label = "Degraded"; cls = "warn"; }
    else if (states.some((x) => x === "operational")) { label = "Partly measured"; cls = "info"; }
    const dot = { ok: "ok", warn: "warn", err: "err" }[cls] || "";
    setKpi("k-status", `<span style="display:inline-flex;align-items:center;gap:10px;font-size:20px"><span class="pulse ${dot}"></span>${esc(label)}</span>`,
      s.last_observation ? `last query ${fmt.relative(s.last_observation)}` : "Run a test to observe");
    setKpi("k-rate", fmt.pct(s.failure_rate), has ? `${fmt.int(s.failed)} of ${fmt.int(s.total_queries)} attempts` : "No data yet");
  }

  function renderActivity(s) {
    const box = $("#activity-box");
    const total = s.activity.reduce((n, d) => n + d.successful + d.no_data + d.failed, 0);
    if (!total) {
      if (DG.charts.activity) { DG.charts.activity.destroy(); delete DG.charts.activity; }
      DG.chartEmpty(box, "No queries in the last 14 days.");
      return;
    }
    DG.chartEmpty(box, null);
    const c = DG.colors();
    const ds = (label, key, color) => ({ label, data: s.activity.map((d) => d[key]), backgroundColor: color, borderColor: c.surface, borderWidth: { top: 2 }, borderSkipped: "bottom", borderRadius: 3, maxBarThickness: 26, stack: "q" });
    DG.makeChart("activity", $("#activity-chart"), {
      type: "bar",
      data: { labels: s.activity.map((d) => fmt.date(d.day + "T12:00:00Z")), datasets: [ds("Successful", "successful", c.ok), ds("No record", "no_data", c.info), ds("Failed", "failed", c.err)] },
      options: { interaction: { mode: "index", intersect: false }, scales: { x: { ...DG.axis(), stacked: true, grid: { display: false } }, y: { ...DG.axis("Queries"), stacked: true, beginAtZero: true, ticks: { precision: 0 } } } },
    });
  }

  function renderOutcome(s) {
    const box = $("#outcome-box");
    const c = DG.colors();
    const vals = [s.successful, s.no_data, s.failed];
    const labels = ["Successful", "No record", "Failed"];
    const colors = [c.ok, c.info, c.err];
    if (!s.total_queries) {
      if (DG.charts.outcome) { DG.charts.outcome.destroy(); delete DG.charts.outcome; }
      DG.chartEmpty(box, "No stored attempts.", "chart-pie");
      $("#outcome-legend").innerHTML = "";
      return;
    }
    DG.chartEmpty(box, null);
    DG.makeChart("outcome", $("#outcome-chart"), {
      type: "doughnut",
      data: { labels, datasets: [{ data: vals, backgroundColor: colors, borderColor: c.surface, borderWidth: 2, hoverOffset: 4 }] },
      options: { cutout: "68%", plugins: { tooltip: { callbacks: { label: (ctx) => ` ${ctx.label}: ${fmt.int(ctx.raw)} (${fmt.pct((ctx.raw / s.total_queries) * 100)})` } } } },
    });
    $("#outcome-legend").innerHTML = `<div class="legend" style="justify-content:center">${labels.map((l, i) => `<span><i style="background:${colors[i]}"></i>${l} <b class="num">${fmt.int(vals[i])}</b></span>`).join("")}</div>`;
  }

  function renderPerf(s) {
    const box = $("#perf-box");
    const keys = Object.keys(s.per_resolver);
    const vals = keys.map((k) => s.per_resolver[k].median_latency_ms);
    $("#perf-legend").innerHTML = "";
    if (vals.every((v) => v === null)) {
      if (DG.charts.perf) { DG.charts.perf.destroy(); delete DG.charts.perf; }
      DG.chartEmpty(box, "No successful measurements yet.");
      return;
    }
    DG.chartEmpty(box, null);
    DG.makeChart("perf", $("#perf-chart"), {
      type: "bar",
      data: { labels: keys.map((k) => `${s.per_resolver[k].short} ${s.per_resolver[k].ip}`), datasets: [{ label: "Median latency", data: vals, backgroundColor: keys.map(DG.resolverColor), borderRadius: 4, maxBarThickness: 30 }] },
      options: {
        indexAxis: "y",
        scales: { x: DG.axis("Median latency (ms)", { beginAtZero: true }), y: { ...DG.axis(), grid: { display: false } } },
        plugins: { tooltip: { callbacks: { label: (ctx) => {
          const r = s.per_resolver[keys[ctx.dataIndex]];
          return [` Median ${fmt.ms(ctx.raw)}`, ` ${fmt.int(r.successful)} successful of ${fmt.int(r.total)}`, ` Failure rate ${fmt.pct(r.failure_rate)}`];
        } } } },
      },
    });
  }

  function renderHealth(s) {
    $("#health-sub").textContent = `From each resolver's last ${s.health_window} observed attempts — not a live probe`;
    const html = Object.entries(s.resolver_health).map(([k, h]) => {
      const sevCls = { operational: "ok", degraded: "warn", unresponsive: "err", unknown: "neutral" }[h.status];
      const icon = { operational: "circle-check", degraded: "triangle-alert", unresponsive: "circle-x", unknown: "circle-dashed" }[h.status];
      return `
        <div class="health-row">
          <span class="swatch ${esc(k)}" style="width:12px;height:12px"></span>
          <div><div class="h-name">${esc(h.name)} <span class="mono muted" style="font-size:12px">${esc(h.ip)}</span></div>
            <div class="h-sub">${h.observations ? `${fmt.pct(h.answered_pct)} of ${h.observations} answered, median ${fmt.ms(h.median_latency_ms)}, ${fmt.relative(h.last_seen)}` : "No queries sent to this resolver yet"}</div></div>
          <span class="badge ${sevCls}" data-tip="${esc(h.label)}"><i data-lucide="${icon}"></i>${esc(h.status_short)}</span>
        </div>`;
    }).join("");
    $("#health").innerHTML = html + '<p class="muted" style="font-size:12.5px">"Answered" counts any DNS response, including NXDOMAIN and no-record answers, because those are valid replies about the name. Timeouts, network errors, SERVFAIL and REFUSED count against the resolver.</p>';
  }

  function renderRecent(s) {
    const box = $("#recent");
    if (!s.recent_tests.length) {
      box.innerHTML = '<div class="empty"><div class="empty-icon"><i data-lucide="history"></i></div><h3>No tests yet</h3><p>Tests you run appear here with their outcome, median latency and failure rate.</p></div>';
      return;
    }
    box.innerHTML = `<div class="table-wrap"><table class="data"><thead><tr><th>Domain</th><th>Type</th><th>Resolvers</th><th class="r">Attempts</th><th class="r">Median</th><th class="r">Failure rate</th><th>Outcome</th><th>When</th><th></th></tr></thead><tbody>
      ${s.recent_tests.map((t) => `<tr class="row">
        <td class="mono">${esc(t.domain)}</td><td>${esc(t.record_type)}</td>
        <td>${t.resolvers.map(DG.resolverTag).join("&nbsp;&nbsp;")}</td>
        <td class="r num">${t.attempts}×${t.resolvers.length}</td>
        <td class="r num">${fmt.ms(t.median_latency_ms)}</td><td class="r num">${fmt.pct(t.failure_rate)}</td>
        <td>${DG.badge(t.outcome)}</td>
        <td class="muted nowrap" data-tip="${esc(fmt.dateTime(t.created_at))}">${esc(fmt.relative(t.created_at))}</td>
        <td class="r"><a class="btn btn-ghost btn-sm" href="/reports?id=${t.id}">Report</a></td></tr>`).join("")}
      </tbody></table></div>`;
  }

  function renderAll() {
    if (!stats) return;
    $("#dash-empty").classList.toggle("hidden", stats.total_queries > 0);
    $("#dash-sub").textContent = stats.first_observation
      ? `Calculated from ${fmt.int(stats.total_queries)} stored queries, ${fmt.dateTime(stats.first_observation)} to ${fmt.dateTime(stats.last_observation)}.`
      : "Totals and resolver health calculated from every query stored on this installation.";
    renderKpis(stats); renderActivity(stats); renderOutcome(stats); renderPerf(stats); renderHealth(stats); renderRecent(stats);
    DG.icons();
  }

  async function load(showToast) {
    try {
      stats = await DG.api("/api/dashboard/stats");
      renderAll();
      if (showToast) DG.toast("ok", "Dashboard refreshed", null, 1800);
    } catch (e) {
      $("#recent").innerHTML = `<div class="empty error"><div class="empty-icon"><i data-lucide="triangle-alert"></i></div><h3>Could not load statistics</h3><p>${esc(e.message)}</p><button class="btn" id="retry">Try again</button></div>`;
      DG.icons();
      $("#retry")?.addEventListener("click", () => load(true));
      DG.toast("err", "Could not load statistics", e.message);
    }
  }

  $("#refresh").addEventListener("click", () => load(true));
  document.addEventListener("dg:theme", renderAll);
  load(false);
})();
