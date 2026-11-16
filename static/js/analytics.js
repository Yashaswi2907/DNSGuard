/* Performance Analytics: per-test measurements with worked calculations + historical aggregates. */
(function () {
  "use strict";
  const { $, esc, fmt } = DG;
  const KEYS = Object.keys(DG.resolverMap);
  let agg = null, test = null;

  const median = (arr) => {
    const s = arr.slice().sort((a, b) => a - b), n = s.length;
    if (!n) return null;
    return n % 2 ? s[(n - 1) / 2] : (s[n / 2 - 1] + s[n / 2]) / 2;
  };
  const r2 = (v) => (v < 10 ? v.toFixed(2) : v.toFixed(1));

  /* --------------------------------------------- selected-test section */
  function renderCalc(t) {
    const blocks = t.resolvers.map((k) => {
      const atts = t.attempts_by_resolver[k] || [];
      const succ = atts.filter((a) => a.category === "SUCCESS").map((a) => a.latency_ms).sort((a, b) => a - b);
      const failed = atts.filter((a) => !["SUCCESS", "NOERROR_NODATA"].includes(a.category)).length;
      const nodata = atts.filter((a) => a.category === "NOERROR_NODATA").length;
      const total = atts.length;
      const med = median(succ);
      let medLine;
      if (!succ.length) medLine = '<span class="muted">No successful measurements, so the median latency is undefined for this resolver.</span>';
      else {
        const n = succ.length;
        const shown = succ.map((v, i) => {
          const mid = n % 2 ? i === (n - 1) / 2 : i === n / 2 - 1 || i === n / 2;
          return mid ? `<b style="color:var(--text)">${r2(v)}</b>` : r2(v);
        }).join(", ");
        medLine = `Sorted samples (ms): ${shown}<br>n = ${n} ${n % 2 ? `(odd) → middle value` : `(even) → mean of the two middle values`} = <b class="num" style="color:var(--text)">${fmt.ms(med)}</b>`;
      }
      const rate = total ? (failed / total) * 100 : null;
      return `
        <div style="padding:14px 0;border-top:1px solid var(--line)">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">${DG.resolverTag(k)}<span class="muted" style="font-size:12.5px">${total} attempts</span></div>
          <dl class="kv" style="font-size:13px">
            <dt>Median latency</dt><dd class="text-2" style="font-size:12.5px;line-height:1.6">${medLine}</dd>
            <dt>Successful</dt><dd class="num">${succ.length} <span class="muted">of ${total}</span></dd>
            <dt>Failure rate</dt><dd class="num">(${failed} ÷ ${total}) × 100 = <b>${fmt.pct(rate, 2)}</b></dd>
            ${nodata ? `<dt>No-record</dt><dd class="num">${nodata} <span class="muted">(valid answers, neither success nor failure)</span></dd>` : ""}
          </dl>
        </div>`;
    }).join("");
    $("#an-calc").innerHTML = `
      <div class="field-label" style="margin-bottom:4px">How the numbers are calculated</div>
      <p class="muted" style="font-size:12.5px;margin-bottom:6px"><span class="mono">${esc(t.domain)}</span> ${esc(t.record_type)}, test #${t.id}. Only successful attempts are latency samples; timeouts are never included.</p>
      ${blocks}`;
  }

  async function loadTest(id) {
    try {
      test = await DG.api(`/api/history/${encodeURIComponent(id)}`);
      $("#an-lat-legend").innerHTML = DG.legendHTML(test.resolvers);
      DG.latencyChart("an-lat", $("#an-lat-box"), test.attempts_by_resolver);
      renderCalc(test);
      DG.icons();
    } catch (e) { DG.toast("err", "Could not load test", e.message); }
  }

  /* ---------------------------------------------- aggregate section */
  function renderAgg() {
    const c = DG.colors();
    // Resolver comparison
    const byType = agg.by_record_type;
    // Overall per-resolver figures come from /api/dashboard/stats.
    const perRes = agg._per_resolver;
    const resBox = $("#an-res-box");
    const meds = KEYS.map((k) => perRes[k].median_latency_ms);
    if (meds.every((v) => v === null)) DG.chartEmpty(resBox, "No successful measurements yet.");
    else {
      DG.chartEmpty(resBox, null);
      DG.makeChart("an-res", $("#an-res"), {
        type: "bar",
        data: { labels: KEYS.map((k) => `${DG.resolverMap[k].short} ${DG.resolverMap[k].ip}`), datasets: [{ label: "Median latency", data: meds, backgroundColor: KEYS.map(DG.resolverColor), borderRadius: 4, maxBarThickness: 34 }] },
        options: { indexAxis: "y", scales: { x: DG.axis("Median latency (ms)", { beginAtZero: true }), y: { ...DG.axis(), grid: { display: false } } },
          plugins: { tooltip: { callbacks: { label: (ctx) => ` ${fmt.ms(ctx.raw)}` } } } },
      });
    }
    $("#an-res-table").innerHTML = `<table class="data"><thead><tr><th>Resolver</th><th class="r">Queries</th><th class="r">Successful</th><th class="r">Failure rate</th><th class="r">Median</th></tr></thead><tbody>${KEYS.map((k) => `<tr><td>${DG.resolverTag(k)}</td><td class="r num">${fmt.int(perRes[k].total)}</td><td class="r num">${fmt.int(perRes[k].successful)}</td><td class="r num">${fmt.pct(perRes[k].failure_rate)}</td><td class="r num">${fmt.ms(perRes[k].median_latency_ms)}</td></tr>`).join("")}</tbody></table>`;

    // Distribution doughnut by category
    const cats = Object.entries(agg.categories).sort((a, b) => b[1] - a[1]);
    const colorFor = (cat) => ({ ok: c.ok, info: c.info, err: c.err, warn: c.warn }[DG.catInfo(cat)[0]] || c.muted);
    // Several failure categories share the "err" status colour, so give them distinct tints by opacity step.
    const errCats = cats.filter(([k]) => DG.catInfo(k)[0] === "err").map(([k]) => k);
    const tint = (hex, i) => { const a = [1, 0.72, 0.5, 0.34][i] ?? 0.3; return hex + Math.round(a * 255).toString(16).padStart(2, "0"); };
    const colors = cats.map(([k]) => (DG.catInfo(k)[0] === "err" ? tint(c.err, errCats.indexOf(k)) : colorFor(k)));
    DG.makeChart("an-dist", $("#an-dist"), {
      type: "doughnut",
      data: { labels: cats.map(([k]) => DG.catInfo(k)[2]), datasets: [{ data: cats.map(([, n]) => n), backgroundColor: colors, borderColor: c.surface, borderWidth: 2 }] },
      options: { cutout: "64%", plugins: { tooltip: { callbacks: { label: (ctx) => ` ${ctx.label}: ${ctx.raw} (${fmt.pct((ctx.raw / agg.total_queries) * 100)})` } } } },
    });
    $("#an-dist-legend").innerHTML = `<div class="legend" style="justify-content:center">${cats.map(([k, n], i) => `<span><i style="background:${colors[i]}"></i>${esc(DG.catInfo(k)[2])} <b class="num">${n}</b></span>`).join("")}</div>`;

    // A vs AAAA
    const typeBox = $("#an-type-box");
    const labels = ["A (IPv4)", "AAAA (IPv6)"];
    const hasType = ["A", "AAAA"].some((t) => KEYS.some((k) => byType[t][k].median_latency_ms !== null));
    $("#an-type-legend").innerHTML = DG.legendHTML(KEYS);
    if (!hasType) DG.chartEmpty(typeBox, "No successful A or AAAA measurements yet.");
    else {
      DG.chartEmpty(typeBox, null);
      DG.makeChart("an-type", $("#an-type"), {
        type: "bar",
        data: { labels, datasets: KEYS.map((k) => ({ label: DG.resolverMap[k].short, data: ["A", "AAAA"].map((t) => byType[t][k].median_latency_ms), backgroundColor: DG.resolverColor(k), borderColor: c.surface, borderWidth: 2, borderRadius: 4, maxBarThickness: 40 })) },
        options: { interaction: { mode: "index", intersect: false }, scales: { x: { ...DG.axis(), grid: { display: false } }, y: DG.axis("Median latency (ms)", { beginAtZero: true }) },
          plugins: { tooltip: { callbacks: { label: (ctx) => { const t = ["A", "AAAA"][ctx.dataIndex]; const s = byType[t][KEYS[ctx.datasetIndex]]; return ` ${ctx.dataset.label}: ${fmt.ms(ctx.raw)} (${s.successful}/${s.total} ok, failure ${fmt.pct(s.failure_rate)})`; } } } } },
      });
    }
    $("#an-type-table").innerHTML = `<table class="data"><thead><tr><th>Type</th><th>Resolver</th><th class="r">Queries</th><th class="r">Successful</th><th class="r">No record</th><th class="r">Failure rate</th></tr></thead><tbody>${["A", "AAAA"].flatMap((t) => KEYS.map((k) => { const s = byType[t][k]; return `<tr><td>${t}</td><td>${DG.resolverTag(k)}</td><td class="r num">${s.total}</td><td class="r num">${s.successful}</td><td class="r num">${s.no_data}</td><td class="r num">${fmt.pct(s.failure_rate)}</td></tr>`; })).join("")}</tbody></table>`;

    // Histogram
    const histBox = $("#an-hist-box");
    $("#an-hist-legend").innerHTML = DG.legendHTML(KEYS);
    const any = KEYS.some((k) => agg.distribution.series[k].some((n) => n > 0));
    if (!any) DG.chartEmpty(histBox, "No successful measurements yet.");
    else {
      DG.chartEmpty(histBox, null);
      DG.makeChart("an-hist", $("#an-hist"), {
        type: "bar",
        data: { labels: agg.distribution.labels, datasets: KEYS.map((k) => ({ label: DG.resolverMap[k].short, data: agg.distribution.series[k], backgroundColor: DG.resolverColor(k), borderColor: c.surface, borderWidth: 2, borderRadius: 3, maxBarThickness: 28 })) },
        options: { interaction: { mode: "index", intersect: false }, scales: { x: { ...DG.axis("Latency band"), grid: { display: false } }, y: DG.axis("Successful queries", { beginAtZero: true, ticks: { precision: 0 } }) } },
      });
    }

    // Trend
    const trendBox = $("#an-trend-box");
    $("#an-trend-legend").innerHTML = DG.legendHTML(KEYS);
    const tr = agg.trend;
    if (!tr.some((p) => KEYS.some((k) => p[k] !== null))) DG.chartEmpty(trendBox, "No successful measurements yet.");
    else {
      DG.chartEmpty(trendBox, null);
      DG.makeChart("an-trend", $("#an-trend"), {
        type: "line",
        data: { labels: tr.map((p) => `#${p.id}`), datasets: KEYS.map((k) => ({ label: DG.resolverMap[k].short, data: tr.map((p) => p[k]), borderColor: DG.resolverColor(k), backgroundColor: DG.resolverColor(k), pointBorderColor: c.surface, pointBorderWidth: 2, tension: 0.2, spanGaps: false })) },
        options: { interaction: { mode: "index", intersect: false }, scales: { x: DG.axis("Test"), y: DG.axis("Median latency (ms)", { beginAtZero: true }) },
          plugins: { tooltip: { callbacks: { title: (items) => { const p = tr[items[0].dataIndex]; return `Test #${p.id}: ${p.domain} ${p.record_type}`; }, label: (ctx) => ` ${ctx.dataset.label}: ${ctx.raw === null ? "no successful sample" : fmt.ms(ctx.raw)}` } } } },
      });
    }
  }

  async function init() {
    try {
      const [a, stats, list] = await Promise.all([DG.api("/api/analytics"), DG.api("/api/dashboard/stats"), DG.api("/api/history?limit=100")]);
      agg = a; agg._per_resolver = stats.per_resolver;
      if (!list.items.length) { $("#an-empty").classList.remove("hidden"); return; }
      $("#an-body").classList.remove("hidden"); $("#an-body").style.display = "flex";
      const pick = $("#an-pick");
      pick.innerHTML = list.items.map((t) => `<option value="${t.id}">#${t.id}  ${esc(t.domain)}  ${esc(t.record_type)}  (${esc(fmt.dateTime(t.created_at))})</option>`).join("");
      const want = DG.param("id");
      if (want && list.items.some((t) => String(t.id) === want)) pick.value = want;
      pick.addEventListener("change", () => loadTest(pick.value));
      renderAgg();
      await loadTest(pick.value);
    } catch (e) {
      $("#an-empty").classList.remove("hidden");
      $("#an-empty").innerHTML = `<div class="empty error"><div class="empty-icon"><i data-lucide="triangle-alert"></i></div><h3>Could not load analytics</h3><p>${esc(e.message)}</p></div>`;
      DG.icons();
    }
  }
  document.addEventListener("dg:theme", () => { if (agg) renderAgg(); if (test) DG.latencyChart("an-lat", $("#an-lat-box"), test.attempts_by_resolver); });
  init();
})();
