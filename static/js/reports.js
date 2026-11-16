/* Diagnostic Reports: list of stored tests and the full rule-based report for the selected one. */
(function () {
  "use strict";
  const { $, $$, esc, fmt } = DG;
  let items = [], currentId = null, searchTimer = null;

  function renderList() {
    const box = $("#rp-list");
    if (!items.length) { box.innerHTML = '<p class="muted" style="padding:18px">No tests match that filter.</p>'; return; }
    box.innerHTML = items.map((t) => `
      <button class="report-item" role="listitem" data-id="${t.id}" aria-current="${String(t.id) === String(currentId)}">
        <div class="ri-top"><span class="ri-domain">${esc(t.domain)}</span>${DG.badge(t.outcome)}</div>
        <div class="ri-sub">#${t.id}, ${esc(t.record_type)}, ${t.resolvers.length === 2 ? "both resolvers" : esc(DG.resolverMap[t.resolvers[0]]?.short)}, ${esc(fmt.relative(t.created_at))}</div>
      </button>`).join("");
    DG.icons();
  }

  async function loadList(q) {
    const data = await DG.api(`/api/history?limit=200${q ? `&q=${encodeURIComponent(q)}` : ""}`);
    items = data.items;
    renderList();
    return data;
  }

  async function show(id) {
    currentId = id;
    $$(".report-item").forEach((b) => b.setAttribute("aria-current", String(b.dataset.id === String(id))));
    const box = $("#rp-detail");
    try {
      const t = await DG.api(`/api/history/${encodeURIComponent(id)}`);
      const d = t.diagnosis;
      const sevIcon = { ok: "circle-check", info: "info", warning: "triangle-alert", error: "circle-x" }[d.severity] || "info";
      const sevColor = { ok: "var(--ok)", info: "var(--info)", warning: "var(--warn)", error: "var(--err)" }[d.severity];
      box.innerHTML = `
        <div class="panel-head" style="padding-bottom:4px">
          <div><div class="sub">Report for test #${t.id}</div><h2 style="font-size:19px;display:flex;align-items:center;gap:10px;margin-top:4px"><i data-lucide="${sevIcon}" style="color:${sevColor};width:22px;height:22px"></i>${esc(d.headline)}</h2></div>
          <div class="page-actions no-print">
            <a class="btn btn-sm" href="/diagnostics?id=${t.id}"><i data-lucide="radar"></i>Open in diagnostics</a>
            ${t.resolvers.length === 2 ? `<a class="btn btn-sm" href="/comparison?id=${t.id}"><i data-lucide="git-compare-arrows"></i>Compare</a>` : ""}
            <a class="btn btn-sm btn-ghost" href="/api/history/export/json?test_id=${t.id}"><i data-lucide="file-json"></i>JSON</a>
            <button class="btn btn-sm btn-ghost" id="rp-print"><i data-lucide="printer"></i>Print</button>
          </div>
        </div>
        <div class="panel-body" style="display:flex;flex-direction:column;gap:18px">
          <dl class="kv">
            <dt>Domain</dt><dd class="mono">${esc(t.domain)}</dd>
            <dt>Record type</dt><dd>${esc(t.record_type)} (${t.record_type === "AAAA" ? "IPv6" : "IPv4"} address)</dd>
            <dt>Resolvers</dt><dd>${t.resolvers.map((k) => `${DG.resolverTag(k)} <span class="mono muted">${esc(t.resolver_meta[k].ip)}</span>`).join("&nbsp;&nbsp;&nbsp;")}</dd>
            <dt>Attempts</dt><dd>${t.attempts} per resolver, ${t.total_queries} in total, timeout ${t.timeout} s</dd>
            <dt>Run at</dt><dd>${esc(fmt.dateTime(t.created_at))}, took ${fmt.ms(t.duration_ms, 0)}</dd>
            <dt>Results</dt><dd>${t.successful} successful, ${t.no_data} no-record, ${t.failed} failed; failure rate ${fmt.pct(t.failure_rate)}; median latency ${fmt.ms(t.median_latency_ms)}</dd>
          </dl>
          <div class="grid ${t.resolvers.length > 1 ? "cols-2" : ""}">${t.resolvers.map((k) => DG.render.resolverCard(k, t.resolver_meta[k], t.comparison.resolvers[k].summary, t.record_type)).join("")}</div>
          <div><h3 style="font-size:15px;margin-bottom:12px">Diagnosis</h3>${DG.render.diagnosis(d, t.resolver_meta)}</div>
          <div><h3 style="font-size:15px;margin-bottom:8px">Query attempts</h3><div class="panel" id="rp-attempts" style="box-shadow:none"></div></div>
        </div>`;
      DG.render.attemptsTable($("#rp-attempts"), t.attempts_by_resolver);
      $("#rp-print").addEventListener("click", () => window.print());
      DG.icons();
      const url = new URL(location.href); url.searchParams.set("id", t.id); history.replaceState(null, "", url);
    } catch (e) {
      box.innerHTML = `<div class="empty error"><div class="empty-icon"><i data-lucide="triangle-alert"></i></div><h3>Report unavailable</h3><p>${esc(e.message)}</p></div>`;
      DG.icons();
    }
  }

  $("#rp-list").addEventListener("click", (e) => { const b = e.target.closest(".report-item"); if (b) show(b.dataset.id); });
  $("#rp-search").addEventListener("input", (e) => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => loadList(e.target.value.trim()).catch((err) => DG.toast("err", "Search failed", err.message)), 250);
  });

  (async function init() {
    try {
      const data = await loadList("");
      if (!data.total) { $("#rp-empty").classList.remove("hidden"); return; }
      $("#rp-body").classList.remove("hidden");
      const want = DG.param("id");
      await show(want || items[0].id);
    } catch (e) {
      $("#rp-empty").classList.remove("hidden");
      $("#rp-empty").innerHTML = `<div class="empty error"><div class="empty-icon"><i data-lucide="triangle-alert"></i></div><h3>Could not load reports</h3><p>${esc(e.message)}</p></div>`;
      DG.icons();
    }
  })();
})();
