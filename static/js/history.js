/* Test History: search, date filter, server-side sorting, pagination, delete, clear, export. */
(function () {
  "use strict";
  const { $, esc, fmt } = DG;
  const PAGE = 20;
  const state = { offset: 0, sort: "created_at", order: "desc", total: 0 };
  let timer = null;

  // Local calendar day -> UTC ISO bounds, so "today" means today in the user's time zone.
  const dayStart = (d) => (d ? new Date(`${d}T00:00:00`).toISOString() : "");
  const dayEnd = (d) => { if (!d) return ""; const x = new Date(`${d}T00:00:00`); x.setDate(x.getDate() + 1); return x.toISOString(); };

  function query() {
    const p = new URLSearchParams();
    const q = $("#h-q").value.trim(); if (q) p.set("q", q);
    const f = $("#h-from").value, t = $("#h-to").value;
    if (f) p.set("from", dayStart(f));
    if (t) p.set("to", dayEnd(t));
    if ($("#h-type").value) p.set("record_type", $("#h-type").value);
    if ($("#h-outcome").value) p.set("outcome", $("#h-outcome").value);
    p.set("limit", PAGE); p.set("offset", state.offset); p.set("sort", state.sort); p.set("order", state.order);
    return p;
  }

  const COLS = [
    ["id", "Test", "r"], ["domain", "Domain"], ["record_type", "Type"], [null, "Resolvers"], [null, "Attempts", "r"],
    ["median", "Median", "r"], ["failure_rate", "Failure rate", "r"], [null, "Outcome"], ["created_at", "Date"], [null, ""],
  ];

  function render(data) {
    state.total = data.total;
    const box = $("#h-table");
    const filtered = [...query().keys()].some((k) => ["q", "from", "to", "record_type", "outcome"].includes(k));
    if (!data.items.length) {
      box.innerHTML = filtered
        ? '<div class="empty"><div class="empty-icon"><i data-lucide="search-x"></i></div><h3>No tests match these filters</h3><p>Try a shorter search term or a wider date range.</p></div>'
        : '<div class="empty"><div class="empty-icon"><i data-lucide="history"></i></div><h3>No tests stored</h3><p>Tests appear here as soon as you run a diagnostic or a comparison.</p><a class="btn btn-primary" href="/diagnostics"><i data-lucide="radar"></i>Run diagnostic</a></div>';
    } else {
      box.innerHTML = `<div class="table-wrap"><table class="data"><thead><tr>${COLS.map(([k, label, cls]) => k
        ? `<th class="sortable ${cls || ""}" data-sort="${k}" tabindex="0" aria-sort="${state.sort === k ? (state.order === "asc" ? "ascending" : "descending") : "none"}">${label}<span class="sort-ind">${state.sort === k ? (state.order === "asc" ? "▲" : "▼") : "▲"}</span></th>`
        : `<th class="${cls || ""}">${label}</th>`).join("")}</tr></thead><tbody>
        ${data.items.map((t) => `<tr class="row">
          <td class="r num muted">#${t.id}</td>
          <td class="mono">${esc(t.domain)}</td>
          <td>${esc(t.record_type)}</td>
          <td class="nowrap">${t.resolvers.length === 2 ? `<span style="display:inline-flex;gap:3px;align-items:center" data-tip="Google Public DNS and Cloudflare DNS"><span class="swatch google"></span><span class="swatch cloudflare"></span>&nbsp;Both</span>` : DG.resolverTag(t.resolvers[0])}</td>
          <td class="r num">${t.attempts}×${t.resolvers.length}</td>
          <td class="r num">${fmt.ms(t.median_latency_ms)}</td>
          <td class="r num">${fmt.pct(t.failure_rate)}</td>
          <td>${DG.badge(t.outcome)}</td>
          <td class="nowrap muted" data-tip="${esc(fmt.dateTime(t.created_at))}">${esc(fmt.short(t.created_at))}</td>
          <td class="r nowrap">
            <a class="btn btn-ghost icon-btn sm" href="/reports?id=${t.id}" aria-label="View report for test ${t.id}" data-tip="View detailed report"><i data-lucide="file-search"></i></a>
            <a class="btn btn-ghost icon-btn sm" href="/diagnostics?domain=${encodeURIComponent(t.domain)}&type=${t.record_type}" aria-label="Run again" data-tip="Run this test again"><i data-lucide="rotate-ccw"></i></a>
            <button class="btn btn-ghost icon-btn sm" data-del="${t.id}" data-domain="${esc(t.domain)}" aria-label="Delete test ${t.id}" data-tip="Delete this test"><i data-lucide="trash-2"></i></button>
          </td></tr>`).join("")}
        </tbody></table></div>`;
    }
    const from = data.total ? state.offset + 1 : 0, to = Math.min(state.offset + PAGE, data.total);
    $("#h-count").textContent = data.total ? `Showing ${from}–${to} of ${data.total} test${data.total === 1 ? "" : "s"}` : "";
    $("#h-prev").disabled = state.offset === 0;
    $("#h-next").disabled = state.offset + PAGE >= data.total;
    $("#clear-all").disabled = !data.total && !filtered;
    DG.icons();
  }

  async function load() {
    try { render(await DG.api(`/api/history?${query()}`)); }
    catch (e) {
      $("#h-table").innerHTML = `<div class="empty error"><div class="empty-icon"><i data-lucide="triangle-alert"></i></div><h3>Could not load history</h3><p>${esc(e.message)}</p></div>`;
      DG.icons(); DG.toast("err", "Could not load history", e.message);
    }
  }
  const reload = () => { state.offset = 0; load(); };

  $("#h-q").addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(reload, 250); });
  ["#h-from", "#h-to", "#h-type", "#h-outcome"].forEach((s) => $(s).addEventListener("change", () => {
    if ($("#h-from").value && $("#h-to").value && $("#h-from").value > $("#h-to").value) { DG.toast("warn", "Check the dates", "The start date is after the end date."); return; }
    reload();
  }));
  $("#filters").addEventListener("submit", (e) => { e.preventDefault(); reload(); });
  $("#h-clear").addEventListener("click", () => { $("#filters").reset(); reload(); });
  $("#h-prev").addEventListener("click", () => { state.offset = Math.max(0, state.offset - PAGE); load(); });
  $("#h-next").addEventListener("click", () => { state.offset += PAGE; load(); });

  $("#h-table").addEventListener("click", async (e) => {
    const th = e.target.closest("th.sortable");
    if (th) {
      const k = th.dataset.sort;
      state.order = state.sort === k && state.order === "desc" ? "asc" : "desc";
      state.sort = k; reload(); return;
    }
    const del = e.target.closest("[data-del]");
    if (del) {
      const ok = await DG.confirm({ title: `Delete test #${del.dataset.del}?`, body: `The test for ${del.dataset.domain} and all of its query attempts will be removed permanently.`, confirmText: "Delete test", danger: true });
      if (!ok) return;
      try {
        await DG.api(`/api/history/${del.dataset.del}`, { method: "DELETE" });
        DG.toast("ok", "Test deleted", `Test #${del.dataset.del} was removed.`);
        if (state.offset && state.offset >= state.total - 1) state.offset = Math.max(0, state.offset - PAGE);
        load();
      } catch (err) { DG.toast("err", "Could not delete", err.message); }
    }
  });
  $("#h-table").addEventListener("keydown", (e) => { if ((e.key === "Enter" || e.key === " ") && e.target.closest("th.sortable")) { e.preventDefault(); e.target.click(); } });

  $("#clear-all").addEventListener("click", async () => {
    const ok = await DG.confirm({ title: "Clear the entire history?", body: "Every stored test and query attempt will be deleted. Dashboard and analytics figures will reset to empty. This cannot be undone.", confirmText: "Clear history", danger: true });
    if (!ok) return;
    try {
      const r = await DG.api("/api/history", { method: "DELETE", body: { confirm: true } });
      DG.toast("ok", "History cleared", `${r.deleted} test${r.deleted === 1 ? "" : "s"} deleted.`);
      $("#filters").reset(); reload();
    } catch (err) { DG.toast("err", "Could not clear history", err.message); }
  });

  load();
})();
