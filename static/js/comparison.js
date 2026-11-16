/* Resolver Comparison: run a two-resolver test or load one from history, then compare side by side. */
(function () {
  "use strict";
  const { $, esc, fmt } = DG;
  let current = null;
  const KEYS = Object.keys(DG.resolverMap);

  function normalizeFromHistory(t) {
    return { id: t.id, domain: t.domain, record_type: t.record_type, resolver_keys: t.resolvers, resolver_meta: t.resolver_meta,
      attempts: t.attempts_by_resolver, comparison: t.comparison, created_at: t.created_at, attempts_per_resolver: t.attempts, timeout: t.timeout };
  }

  /* ---------------------------------------------------------- render */
  function render(r) {
    current = r;
    $("#cmp-empty").classList.add("hidden");
    $("#cmp-body").classList.remove("hidden");
    $("#cmp-body").style.display = "flex";
    const [a, b] = r.resolver_keys;
    const cmp = r.comparison;
    const S = (k) => cmp.resolvers[k].summary;
    const M = (k) => r.resolver_meta[k];
    $("#cmp-title").innerHTML = `<span class="mono">${esc(r.domain)}</span> ${esc(r.record_type)}`;
    $("#cmp-sub").textContent = `${r.attempts_per_resolver} attempts per resolver, ${r.timeout} s timeout, ${fmt.dateTime(r.created_at || new Date().toISOString())}`;
    $("#cmp-report").href = `/reports?id=${r.id}`;
    $("#cmp-csv").href = `/api/history/export/csv?test_id=${r.id}`;

    // Faster-resolver callout (measured median only, with the caveat).
    const f = cmp.faster;
    let callout;
    if (f && !f.tie) {
      callout = `<div class="callout ok"><i data-lucide="zap"></i><div><b>${esc(f.name)}</b> had the lower median latency in this test, by ${fmt.ms(f.margin_ms)}${f.margin_pct !== null ? ` (${f.margin_pct}%)` : ""}. ${esc(cmp.latency_caveat || "")}</div></div>`;
    } else {
      callout = `<div class="callout"><i data-lucide="info"></i><div>${esc(cmp.latency_note || "")}</div></div>`;
    }
    $("#cmp-callout").innerHTML = callout;

    // Side-by-side grid.
    const fastKey = f && !f.tie ? f.key : null;
    const rec = cmp.record_consistency;
    const onlyFor = { [a]: new Set(rec.only_a), [b]: new Set(rec.only_b) };
    const codes = (k) => Object.entries(S(k).category_counts).map(([c, n]) => `${DG.badge(c)} <span class="muted num">×${n}</span>`).join(" ");
    const row = (label, fn, tip, last) => `
      <div class="vs-label ${last ? "last" : ""}">${esc(label)}${tip ? ` <span class="help" data-tip="${esc(tip)}"><i data-lucide="info"></i></span>` : ""}</div>
      <div class="${last ? "last" : ""}">${fn(a)}</div><div class="${last ? "last" : ""}">${fn(b)}</div>`;
    const consistencyLabel = { identical: ["ok", "Identical record sets"], overlap: ["warn", "Partial overlap"], different: ["warn", "Different records"], not_comparable: ["neutral", "Not comparable"] }[rec.status];
    $("#vs").innerHTML = `
      <div class="vs-label" style="padding-top:16px">Metric</div>
      ${[a, b].map((k) => `<div class="vs-head ${esc(k)}"><span class="swatch ${esc(k)}"></span>${esc(M(k).name)}</div>`).join("")}
      ${row("Resolver IP", (k) => `<span class="mono">${esc(M(k).ip)}</span>`)}
      ${row("DNS response codes", codes)}
      ${row("Returned records", (k) => DG.render.records(S(k).records, onlyFor[k]), "Addresses outlined in amber were returned by only this resolver.")}
      ${row("Median query latency", (k) => `<b class="num">${fmt.ms(S(k).median_latency_ms)}</b>${k === fastKey ? '<span class="win"><i data-lucide="zap" class="icon-sm"></i>lower in this test</span>' : ""}`, "Median of successful attempts only.")}
      ${row("Successful queries", (k) => `<span class="num">${S(k).successful} of ${S(k).total}</span>`)}
      ${row("Failed queries", (k) => `<span class="num">${S(k).failed}</span>${S(k).timeouts ? ` <span class="muted">(${S(k).timeouts} timeout${S(k).timeouts > 1 ? "s" : ""})</span>` : ""}`)}
      ${row("Failure percentage", (k) => `<span class="num">${fmt.pct(S(k).failure_rate)}</span>`, "(failed ÷ total) × 100")}
      ${row("No-record answers", (k) => `<span class="num">${S(k).no_data}</span>`, "NOERROR responses without the requested record type. Not counted as failures.")}
      ${row("Answer TTL", (k) => (S(k).ttl_min !== null ? `<span class="num">${S(k).ttl_min === S(k).ttl_max ? S(k).ttl_min : `${S(k).ttl_min}–${S(k).ttl_max}`} s</span>` : '<span class="muted">—</span>'), "Resolvers report the remaining cache lifetime, so TTLs often differ between them.")}
      <div class="vs-label last">Record consistency</div>
      <div class="last" style="grid-column: span 2"><span class="badge ${consistencyLabel[0]}"><i data-lucide="${rec.status === "identical" ? "equal" : "diff"}"></i>${consistencyLabel[1]}</span> <span class="text-2" style="font-size:13px;margin-left:6px">${esc(rec.note)}</span></div>`;

    // Charts
    $("#lat-legend").innerHTML = DG.legendHTML([a, b]);
    DG.latencyChart("cmp-lat", $("#lat-box"), r.attempts);
    const c = DG.colors();
    const names = [a, b].map((k) => DG.resolverMap[k].short);
    const ds = (label, key, color) => ({ label, data: [a, b].map((k) => S(k)[key]), backgroundColor: color, borderColor: c.surface, borderWidth: 2, borderRadius: 4, maxBarThickness: 36 });
    DG.makeChart("cmp-out", $("#out-chart"), {
      type: "bar",
      data: { labels: names, datasets: [ds("Successful", "successful", c.ok), ds("No record", "no_data", c.info), ds("Failed", "failed", c.err)] },
      options: { scales: { x: { ...DG.axis(), grid: { display: false } }, y: DG.axis("Attempts", { beginAtZero: true, ticks: { precision: 0 } }) }, interaction: { mode: "index", intersect: false } },
    });

    const cats = Array.from(new Set([a, b].flatMap((k) => Object.keys(S(k).category_counts))));
    $("#cls-legend").innerHTML = DG.legendHTML([a, b]);
    DG.makeChart("cmp-cls", $("#cls-chart"), {
      type: "bar",
      data: { labels: cats.map((x) => DG.catInfo(x)[2]), datasets: [a, b].map((k) => ({ label: DG.resolverMap[k].short, data: cats.map((x) => S(k).category_counts[x] || 0), backgroundColor: DG.resolverColor(k), borderColor: c.surface, borderWidth: 2, borderRadius: 4, maxBarThickness: 36 })) },
      options: { scales: { x: { ...DG.axis(), grid: { display: false } }, y: DG.axis("Attempts", { beginAtZero: true, ticks: { precision: 0 } }) }, interaction: { mode: "index", intersect: false } },
    });

    // Record differences as three columns: only A / common / only B.
    $("#rec-sub").textContent = consistencyLabel[1];
    const col = (title, list, swatchKey) => `<div style="min-width:0"><div class="field-label" style="margin-bottom:8px">${swatchKey ? `<span class="swatch ${esc(swatchKey)}"></span>` : '<i data-lucide="equal" class="icon-sm"></i>'}${esc(title)} <span class="muted">(${list.length})</span></div>${list.length ? list.map((x) => `<span class="addr">${esc(x)}</span>`).join("") : '<span class="muted" style="font-size:13px">None</span>'}</div>`;
    $("#rec-diff").innerHTML = rec.status === "not_comparable"
      ? `<div class="callout warn"><i data-lucide="triangle-alert"></i><div>${esc(rec.note)}</div></div>`
      : `<div style="display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px">${col(`Only ${DG.resolverMap[a].short}`, rec.only_a, a)}${col("Returned by both", rec.common)}${col(`Only ${DG.resolverMap[b].short}`, rec.only_b, b)}</div><p class="muted" style="font-size:12.5px;margin-top:14px">${esc(rec.note)}</p>`;

    const obs = cmp.observations || [];
    $("#obs").innerHTML = obs.length
      ? `<ul style="margin:0;padding-left:18px;color:var(--text-2);display:flex;flex-direction:column;gap:6px">${obs.map((o) => `<li>${esc(o)}</li>`).join("")}</ul>`
      : '<p class="text-2">Both resolvers gave the same kind of answer on every attempt and returned the same records. No differences to report.</p>';
    DG.icons();
  }

  /* ------------------------------------------------------ data loading */
  async function loadPicker(selectId) {
    const pick = $("#c-pick");
    try {
      const list = await DG.api("/api/history?limit=100");
      const both = list.items.filter((t) => t.resolvers.length === 2);
      if (!both.length) {
        $("#cmp-source").classList.add("hidden");
        return null;
      }
      $("#cmp-source").classList.remove("hidden");
      pick.innerHTML = both.map((t) => `<option value="${t.id}">#${t.id}  ${esc(t.domain)}  ${esc(t.record_type)}  (${esc(fmt.dateTime(t.created_at))})</option>`).join("");
      $("#c-pick-note").textContent = `${both.length} two-resolver test${both.length > 1 ? "s" : ""} in history`;
      const target = selectId && both.some((t) => String(t.id) === String(selectId)) ? selectId : both[0].id;
      pick.value = String(target);
      return target;
    } catch (e) {
      DG.toast("err", "Could not load history", e.message);
      return null;
    }
  }

  async function loadTest(id) {
    try {
      const t = await DG.api(`/api/history/${encodeURIComponent(id)}`);
      if (t.resolvers.length < 2) {
        DG.toast("warn", "Single-resolver test", "This test only queried one resolver. Showing the latest two-resolver test instead.");
        const other = await loadPicker(null);
        if (other && String(other) !== String(id)) return loadTest(other);
        return;
      }
      render(normalizeFromHistory(t));
      const url = new URL(location.href); url.searchParams.set("id", t.id); history.replaceState(null, "", url);
    } catch (e) {
      DG.toast("err", "Could not load test", e.message);
    }
  }

  $("#c-pick").addEventListener("change", (e) => loadTest(e.target.value));

  /* -------------------------------------------------------- run test */
  $("#cmp-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const domain = $("#c-domain").value.trim();
    const fieldErr = (m) => { $("#f-domain").classList.toggle("invalid", !!m); $("#c-domain-error").textContent = m || ""; };
    if (!domain) { fieldErr("Enter a domain name, for example example.com."); $("#c-domain").focus(); return; }
    fieldErr(null);
    const body = { domain, record_type: $("#c-type").value, attempts: Number($("#c-att").value), timeout: Number($("#c-timeout").value), async: true };
    const btn = $("#c-run");
    btn.disabled = true;
    $("#c-progress").classList.remove("hidden");
    try {
      const start = await DG.api("/api/dns/compare", { method: "POST", body });
      let job;
      for (;;) {
        await DG.sleep(250);
        job = await DG.api(`/api/dns/jobs/${encodeURIComponent(start.job_id)}`);
        const pct = Math.round((job.completed / start.total) * 100);
        $("#c-bar").style.width = `${pct}%`; $("#c-ppct").textContent = `${pct}%`;
        $("#c-ptext").textContent = `${job.completed} of ${start.total} queries completed`;
        if (job.state !== "running") break;
      }
      if (job.state === "error") throw new Error(job.error);
      await loadPicker(job.result.id);
      await loadTest(job.result.id);
      DG.toast("ok", "Comparison complete", job.result.diagnosis.headline);
    } catch (err) {
      if (err.field === "domain") fieldErr(err.message);
      DG.toast("err", "Comparison failed", err.message);
    } finally {
      btn.disabled = false;
      setTimeout(() => $("#c-progress").classList.add("hidden"), 600);
    }
  });

  document.addEventListener("dg:theme", () => { if (current) render(current); });

  (async function init() {
    const id = await loadPicker(DG.param("id"));
    if (id) await loadTest(id);
    else { $("#cmp-empty").classList.remove("hidden"); }
  })();
})();
