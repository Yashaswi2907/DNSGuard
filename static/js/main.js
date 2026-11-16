/* =========================================================================
   DNSGuard — shared front-end library (window.DG)
   API client with CSRF, formatting, toasts, confirm dialogs, tooltips,
   theme, clock, system status, and renderers shared by several pages.
   All dynamic text is escaped with DG.esc() before it reaches innerHTML.
   ========================================================================= */
(function () {
  "use strict";

  const DG = (window.DG = {});
  DG.config = JSON.parse(document.getElementById("app-config")?.textContent || "{}");
  DG.resolverMap = Object.fromEntries((DG.config.resolvers || []).map((r) => [r.key, r]));

  /* ------------------------------------------------------------ utilities */
  const ESC = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
  DG.esc = (v) => (v === null || v === undefined ? "" : String(v).replace(/[&<>"']/g, (c) => ESC[c]));
  DG.$ = (sel, root = document) => root.querySelector(sel);
  DG.$$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
  DG.icons = () => { if (window.lucide) window.lucide.createIcons({ attrs: { "aria-hidden": "true" } }); };
  DG.param = (name) => new URLSearchParams(location.search).get(name);
  DG.sleep = (ms) => new Promise((r) => setTimeout(r, ms));

  DG.fmt = {
    ms(v, digits) {
      if (v === null || v === undefined || Number.isNaN(v)) return "—";
      const d = digits ?? (v < 10 ? 2 : v < 100 ? 1 : 0);
      return `${Number(v).toFixed(d)} ms`;
    },
    msParts(v) {
      if (v === null || v === undefined) return { v: "—", u: "" };
      const d = v < 10 ? 2 : v < 100 ? 1 : 0;
      return { v: Number(v).toFixed(d), u: "ms" };
    },
    pct(v, digits = 1) {
      if (v === null || v === undefined || Number.isNaN(v)) return "—";
      return `${Number(v).toFixed(digits)}%`;
    },
    int(v) { return v === null || v === undefined ? "—" : Number(v).toLocaleString(); },
    dateTime(iso) {
      if (!iso) return "—";
      const d = new Date(iso);
      return d.toLocaleString(undefined, { year: "numeric", month: "short", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit" });
    },
    short(iso) {
      if (!iso) return "—";
      return new Date(iso).toLocaleString(undefined, { month: "short", day: "2-digit", hour: "2-digit", minute: "2-digit" });
    },
    date(iso) { return iso ? new Date(iso).toLocaleDateString(undefined, { month: "short", day: "2-digit" }) : "—"; },
    relative(iso) {
      if (!iso) return "—";
      const s = Math.round((Date.now() - new Date(iso).getTime()) / 1000);
      if (s < 45) return "just now";
      if (s < 3600) return `${Math.round(s / 60)} min ago`;
      if (s < 86400) return `${Math.round(s / 3600)} h ago`;
      return `${Math.round(s / 86400)} d ago`;
    },
  };

  /* ------------------------------------------------------------ API client */
  const csrf = () => document.querySelector('meta[name="csrf-token"]')?.content || "";

  DG.api = async function (path, { method = "GET", body } = {}) {
    const opts = { method, headers: { Accept: "application/json" }, credentials: "same-origin" };
    if (method !== "GET") opts.headers["X-CSRF-Token"] = csrf();
    if (body !== undefined) {
      opts.headers["Content-Type"] = "application/json";
      opts.body = JSON.stringify(body);
    }
    let res;
    try {
      res = await fetch(path, opts);
    } catch (e) {
      const err = new Error("Could not reach the DNSGuard server. Check that it is running.");
      err.code = "offline";
      throw err;
    }
    let payload = null;
    try { payload = await res.json(); } catch (e) { /* non-JSON */ }
    if (!res.ok || !payload || payload.ok === false) {
      const info = payload?.error || {};
      const err = new Error(info.message || `Request failed (${res.status}).`);
      err.code = info.code || "http_error";
      err.field = info.field;
      err.status = res.status;
      throw err;
    }
    return payload.data;
  };

  /* -------------------------------------------------------------- toasts */
  const TOAST_ICON = { ok: "circle-check", err: "circle-x", info: "info", warn: "triangle-alert" };
  DG.toast = function (type, title, body, ms = 4200) {
    const box = document.getElementById("toasts");
    if (!box) return;
    const el = document.createElement("div");
    el.className = `toast ${type}`;
    el.innerHTML = `<i data-lucide="${TOAST_ICON[type] || "info"}"></i><div><div class="t-title">${DG.esc(title)}</div>${body ? `<div class="t-body">${DG.esc(body)}</div>` : ""}</div>`;
    box.appendChild(el);
    DG.icons();
    setTimeout(() => { el.classList.add("leaving"); setTimeout(() => el.remove(), 220); }, ms);
  };

  /* ------------------------------------------------------- confirm dialog */
  DG.confirm = function ({ title, body, confirmText = "Confirm", danger = false }) {
    return new Promise((resolve) => {
      const prev = document.activeElement;
      const wrap = document.createElement("div");
      wrap.className = "modal-backdrop";
      wrap.innerHTML = `
        <div class="modal" role="alertdialog" aria-modal="true" aria-labelledby="m-title" aria-describedby="m-body">
          <h3 id="m-title"><i data-lucide="${danger ? "triangle-alert" : "circle-help"}"></i>${DG.esc(title)}</h3>
          <p id="m-body">${DG.esc(body)}</p>
          <div class="modal-actions">
            <button class="btn" data-act="cancel">Cancel</button>
            <button class="btn ${danger ? "btn-danger-solid" : "btn-primary"}" data-act="ok">${DG.esc(confirmText)}</button>
          </div>
        </div>`;
      document.body.appendChild(wrap);
      DG.icons();
      const close = (val) => { wrap.remove(); document.removeEventListener("keydown", onKey); prev?.focus?.(); resolve(val); };
      const onKey = (e) => {
        if (e.key === "Escape") close(false);
        if (e.key === "Tab") { // simple focus trap
          const btns = DG.$$("button", wrap); const i = btns.indexOf(document.activeElement);
          if (e.shiftKey && i <= 0) { btns[btns.length - 1].focus(); e.preventDefault(); }
          else if (!e.shiftKey && i === btns.length - 1) { btns[0].focus(); e.preventDefault(); }
        }
      };
      document.addEventListener("keydown", onKey);
      wrap.addEventListener("click", (e) => {
        if (e.target === wrap) close(false);
        const act = e.target.closest("[data-act]")?.dataset.act;
        if (act) close(act === "ok");
      });
      DG.$('[data-act="cancel"]', wrap).focus();
    });
  };

  /* ------------------------------------------------------------- tooltips */
  let tipEl;
  function showTip(target) {
    const text = target.getAttribute("data-tip");
    if (!text) return;
    if (!tipEl) { tipEl = document.createElement("div"); tipEl.className = "tip"; tipEl.setAttribute("role", "tooltip"); document.body.appendChild(tipEl); }
    tipEl.textContent = text;
    const r = target.getBoundingClientRect();
    tipEl.style.left = "0px"; tipEl.style.top = "0px";
    tipEl.classList.add("show");
    const tw = tipEl.offsetWidth, th = tipEl.offsetHeight;
    let left = Math.min(Math.max(8, r.left + r.width / 2 - tw / 2), window.innerWidth - tw - 8);
    let top = r.bottom + 8;
    if (top + th > window.innerHeight - 8) top = r.top - th - 8;
    tipEl.style.left = `${left}px`; tipEl.style.top = `${top}px`;
  }
  const hideTip = () => tipEl?.classList.remove("show");
  document.addEventListener("mouseover", (e) => { const t = e.target.closest("[data-tip]"); if (t) showTip(t); });
  document.addEventListener("mouseout", (e) => { if (e.target.closest("[data-tip]")) hideTip(); });
  document.addEventListener("focusin", (e) => { const t = e.target.closest("[data-tip]"); if (t) showTip(t); });
  document.addEventListener("focusout", hideTip);
  window.addEventListener("scroll", hideTip, { passive: true });

  /* ---------------------------------------------------------------- theme */
  DG.theme = () => document.documentElement.getAttribute("data-theme") || "dark";
  function setTheme(t) {
    document.documentElement.setAttribute("data-theme", t);
    try { localStorage.setItem("dnsguard-theme", t); } catch (e) { /* ignore */ }
    if (window.Chart) applyChartDefaults();
    document.dispatchEvent(new CustomEvent("dg:theme", { detail: t }));
  }
  DG.cssVar = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  DG.colors = () => ({
    google: DG.cssVar("--google"), cloudflare: DG.cssVar("--cloudflare"),
    ok: DG.cssVar("--ok"), info: DG.cssVar("--info"), err: DG.cssVar("--err"), warn: DG.cssVar("--warn"),
    accent: DG.cssVar("--accent"), cyan: DG.cssVar("--cyan"), violet: DG.cssVar("--violet"),
    text: DG.cssVar("--text"), text2: DG.cssVar("--text-2"), muted: DG.cssVar("--muted"),
    grid: DG.cssVar("--grid"), line: DG.cssVar("--line"), surface: DG.cssVar("--surface"),
  });
  DG.resolverColor = (key) => DG.colors()[key] || DG.colors().accent;

  /* ------------------------------------------------------------- charts */
  DG.charts = {};
  function applyChartDefaults() {
    const c = DG.colors();
    const C = window.Chart;
    C.defaults.font.family = getComputedStyle(document.body).fontFamily;
    C.defaults.font.size = 12;
    C.defaults.color = c.muted;
    C.defaults.borderColor = c.grid;
    C.defaults.animation.duration = 450;
    C.defaults.maintainAspectRatio = false;
    C.defaults.plugins.legend.display = false;
    const tt = C.defaults.plugins.tooltip;
    tt.backgroundColor = "#1A2540"; tt.borderColor = "#2A3959"; tt.borderWidth = 1;
    tt.titleColor = "#E7ECF7"; tt.bodyColor = "#C9D3E8"; tt.padding = 10; tt.cornerRadius = 8;
    tt.boxPadding = 4; tt.usePointStyle = true;
    C.defaults.elements.line.borderWidth = 2;
    C.defaults.elements.point.radius = 3.5;
    C.defaults.elements.point.hoverRadius = 6;
    C.defaults.elements.bar.borderRadius = 4;
  }
  DG.makeChart = function (id, canvas, config) {
    if (DG.charts[id]) DG.charts[id].destroy();
    if (!canvas) return null;
    DG.charts[id] = new window.Chart(canvas, config);
    return DG.charts[id];
  };
  DG.chartEmpty = function (box, message, icon = "chart-no-axes-column") {
    if (!box) return;
    DG.$$(".chart-empty", box).forEach((e) => e.remove());
    const canvas = DG.$("canvas", box);
    if (message) {
      if (canvas) canvas.style.visibility = "hidden";
      const el = document.createElement("div");
      el.className = "chart-empty";
      el.innerHTML = `<i data-lucide="${icon}"></i><div>${DG.esc(message)}</div>`;
      box.appendChild(el);
      DG.icons();
    } else if (canvas) {
      canvas.style.visibility = "";
    }
  };
  DG.axis = (title, extra = {}) => ({
    grid: { color: DG.colors().grid, drawTicks: false }, border: { display: false },
    ticks: { padding: 8 }, title: title ? { display: true, text: title, color: DG.colors().muted } : undefined, ...extra,
  });

  /* ------------------------------------------------------- status badges */
  const CAT = {
    SUCCESS: ["ok", "circle-check", "NOERROR"],
    NOERROR_NODATA: ["info", "circle-dashed", "NOERROR, no record"],
    NXDOMAIN: ["err", "circle-x", "NXDOMAIN"],
    SERVFAIL: ["err", "server-crash", "SERVFAIL"],
    REFUSED: ["err", "ban", "REFUSED"],
    TIMEOUT: ["err", "timer-off", "Timeout"],
    NETWORK_ERROR: ["err", "wifi-off", "Network error"],
    OTHER_ERROR: ["warn", "circle-alert", "Other error"],
    INTERMITTENT: ["warn", "activity", "Intermittent"],
    PARTIAL: ["warn", "contrast", "Partial"],
    FAILED: ["err", "circle-x", "Failed"],
  };
  DG.catInfo = (cat) => CAT[cat] || ["neutral", "circle", cat || "—"];
  DG.badge = function (cat, labelOverride) {
    const [cls, icon, label] = DG.catInfo(cat);
    return `<span class="badge ${cls}"><i data-lucide="${icon}"></i>${DG.esc(labelOverride || label)}</span>`;
  };
  DG.sevBadge = function (sev, text) {
    const map = { ok: ["ok", "circle-check"], info: ["info", "info"], warning: ["warn", "triangle-alert"], error: ["err", "circle-x"] };
    const [cls, icon] = map[sev] || ["neutral", "circle"];
    return `<span class="badge ${cls}"><i data-lucide="${icon}"></i>${DG.esc(text)}</span>`;
  };
  DG.outcomeClass = (cat) => (cat === "SUCCESS" ? "ok" : cat === "NOERROR_NODATA" ? "info" : "err");
  DG.resolverTag = function (key) {
    const r = DG.resolverMap[key] || { short: key, ip: "" };
    return `<span class="nowrap" style="display:inline-flex;align-items:center;gap:7px"><span class="swatch ${DG.esc(key)}"></span>${DG.esc(r.short)}</span>`;
  };

  /* ------------------------------------------------------- shared renders */
  DG.render = {};

  DG.render.chain = function (chain) {
    if (!chain || !chain.length) return "";
    const hops = [chain[0].name].concat(chain.map((h) => h.target));
    return `<div class="chain">${hops.map((h, i) => `${i ? '<i data-lucide="arrow-right"></i>' : ""}<span class="hop" data-tip="${i === 0 ? "Queried name (alias)" : `CNAME target, TTL ${DG.esc(chain[i - 1].ttl)} s`}">${DG.esc(h)}</span>`).join("")}</div>`;
  };

  DG.render.records = function (records, highlight) {
    if (!records || !records.length) return '<span class="muted">No usable records</span>';
    return records.map((r) => `<span class="addr ${highlight && highlight.has(r) ? "only" : ""}">${DG.esc(r)}</span>`).join("");
  };

  DG.render.resolverCard = function (key, meta, s, recordType, onlySet) {
    const med = DG.fmt.msParts(s.median_latency_ms);
    const dom = s.dominant_category;
    return `
      <article class="panel res-card ${DG.esc(key)}">
        <div class="res-head">
          <div class="res-name"><span class="swatch ${DG.esc(key)}"></span>${DG.esc(meta.name)} <span class="res-ip">${DG.esc(meta.ip)}</span></div>
          ${s.mixed_outcomes && s.successful ? DG.badge("INTERMITTENT", "Mixed outcomes") : DG.badge(dom)}
        </div>
        <div class="metrics">
          <div class="metric"><div class="m-label">Median latency <span class="help" data-tip="Median of successful attempts only. Timeouts and errors are excluded."><i data-lucide="info"></i></span></div><div class="m-value">${med.v} <small>${med.u}</small></div></div>
          <div class="metric"><div class="m-label">Successful</div><div class="m-value">${s.successful}<small> / ${s.total}</small></div></div>
          <div class="metric"><div class="m-label">Failure rate <span class="help" data-tip="(failed attempts ÷ total attempts) × 100. NOERROR answers without a record are counted separately, not as failures."><i data-lucide="info"></i></span></div><div class="m-value">${DG.fmt.pct(s.failure_rate)}</div></div>
          <div class="metric"><div class="m-label">No-record answers</div><div class="m-value">${s.no_data}</div></div>
        </div>
        <div class="rec-block"><h4>${DG.esc(recordType)} records${s.ttl_min !== null && s.ttl_min !== undefined ? ` <span class="muted">(TTL ${s.ttl_min === s.ttl_max ? s.ttl_min : `${s.ttl_min}–${s.ttl_max}`} s)</span>` : ""}</h4>${DG.render.records(s.records, onlySet)}</div>
        ${s.cname_chain && s.cname_chain.length ? `<div class="rec-block"><h4>CNAME chain</h4>${DG.render.chain(s.cname_chain)}</div>` : ""}
        <div class="rec-block"><h4>Latency spread (successful)</h4><span class="text-2 num">min ${DG.fmt.ms(s.min_latency_ms)}, mean ${DG.fmt.ms(s.mean_latency_ms)}, max ${DG.fmt.ms(s.max_latency_ms)}${s.stdev_latency_ms !== null ? `, σ ${DG.fmt.ms(s.stdev_latency_ms)}` : ""}</span></div>
      </article>`;
  };

  DG.render.diagnosis = function (diag, resolverMeta) {
    if (!diag) return "";
    const parts = [];
    for (const [key, d] of Object.entries(diag.resolvers || {})) {
      const meta = (resolverMeta || {})[key] || DG.resolverMap[key] || { name: key };
      parts.push(`
        <section class="diag sev-${DG.esc(d.severity)}">
          <div class="diag-head"><h3>${DG.resolverTag(key)} &nbsp;${DG.esc(d.title)}</h3>${DG.sevBadge(d.severity, d.status)}</div>
          <p class="simple">${DG.esc(d.simple)}</p>
          ${d.technical ? `<p class="technical">${DG.esc(d.technical)}</p>` : ""}
          ${d.evidence && d.evidence.length ? `<div class="sec-title">Evidence observed</div><ul>${d.evidence.map((e) => `<li>${DG.esc(e)}</li>`).join("")}</ul>` : ""}
          ${d.notes && d.notes.length ? `<div class="sec-title">Observations</div><ul>${d.notes.map((e) => `<li>${DG.esc(e)}</li>`).join("")}</ul>` : ""}
          ${d.checks && d.checks.length ? `<div class="sec-title">Suggested follow-up checks</div><ul>${d.checks.map((e) => `<li>${DG.esc(e)}</li>`).join("")}</ul>` : ""}
          <div class="sec-title">Resolver</div><p class="technical">${DG.esc(meta.name)} (${DG.esc(meta.ip)}${meta.ipv6 ? `, IPv6 ${DG.esc(meta.ipv6)}` : ""}) — operated by ${DG.esc((meta.operator || "—").replace(/\.$/, ""))}.</p>
        </section>`);
    }
    for (const x of diag.cross_resolver || []) {
      parts.push(`
        <section class="diag sev-${DG.esc(x.severity)}">
          <div class="diag-head"><h3>${DG.esc(x.title)}</h3>${DG.sevBadge(x.severity, "Both resolvers")}</div>
          <p class="simple">${DG.esc(x.text)}</p>
          ${x.checks && x.checks.length ? `<div class="sec-title">Suggested follow-up checks</div><ul>${x.checks.map((e) => `<li>${DG.esc(e)}</li>`).join("")}</ul>` : ""}
        </section>`);
    }
    parts.push(`<div class="disclaimer"><i data-lucide="shield-check"></i><span>${DG.esc(diag.disclaimer)}</span></div>`);
    return `<div class="diag-stack">${parts.join("")}</div>`;
  };

  /** Expandable, sortable attempts table. attemptsByResolver: {key: [attempt...]}. */
  DG.render.attemptsTable = function (container, attemptsByResolver) {
    const rows = [];
    for (const list of Object.values(attemptsByResolver || {})) rows.push(...list);
    let sortKey = "attempt", dir = 1;
    const getters = {
      attempt: (a) => a.attempt, resolver: (a) => a.resolver_key, category: (a) => a.category,
      latency: (a) => (a.latency_ms ?? Infinity), records: (a) => (a.records || []).length, time: (a) => a.timestamp,
    };
    const head = [
      ["attempt", "#"], ["resolver", "Resolver"], ["category", "Response"], ["latency", "Latency", "r"],
      ["records", "Records"], ["time", "Time"],
    ];
    function draw() {
      const sorted = rows.slice().sort((a, b) => {
        const x = getters[sortKey](a), y = getters[sortKey](b);
        if (x < y) return -dir; if (x > y) return dir;
        return a.resolver_key < b.resolver_key ? -1 : 1;
      });
      container.innerHTML = `
        <div class="table-wrap"><table class="data">
          <thead><tr><th style="width:36px"><span class="sr-only">Expand</span></th>${head.map(([k, label, cls]) => `<th class="sortable ${cls || ""}" data-sort="${k}" aria-sort="${k === sortKey ? (dir > 0 ? "ascending" : "descending") : "none"}" tabindex="0">${label}<span class="sort-ind">${k === sortKey ? (dir > 0 ? "▲" : "▼") : "▲"}</span></th>`).join("")}</tr></thead>
          <tbody>${sorted.map((a, i) => `
            <tr class="row expandable" data-i="${i}" tabindex="0" aria-expanded="false">
              <td><i data-lucide="chevron-right" class="expander"></i></td>
              <td class="num">${a.attempt}</td>
              <td>${DG.resolverTag(a.resolver_key)}</td>
              <td>${DG.badge(a.category)}</td>
              <td class="r num ${a.category === "SUCCESS" ? "" : "muted"}" ${a.category === "SUCCESS" ? "" : 'data-tip="Not a successful sample — excluded from median latency"'}>${DG.fmt.ms(a.latency_ms)}</td>
              <td>${a.records && a.records.length ? `<span class="mono">${DG.esc(a.records[0])}</span>${a.records.length > 1 ? ` <span class="muted">+${a.records.length - 1}</span>` : ""}` : '<span class="muted">—</span>'}</td>
              <td class="muted nowrap">${DG.esc(new Date(a.timestamp).toLocaleTimeString())}</td>
            </tr>
            <tr class="detail-row hidden" data-for="${i}"><td colspan="7">
              <dl class="detail-grid">
                <div><dt>Domain</dt><dd class="mono">${DG.esc(a.domain)}</dd></div>
                <div><dt>Resolver</dt><dd>${DG.esc(a.resolver_name)} <span class="mono muted">${DG.esc(a.resolver_ip)}</span></dd></div>
                <div><dt>Record type</dt><dd>${DG.esc(a.record_type)}</dd></div>
                <div><dt>Response code</dt><dd class="mono">${DG.esc(a.rcode || "none (no response)")}</dd></div>
                <div><dt>Classification</dt><dd>${DG.esc(a.category_label || a.category)}</dd></div>
                <div><dt>Latency</dt><dd class="num">${DG.fmt.ms(a.latency_ms, 3)}${a.category === "SUCCESS" ? "" : " <span class='muted'>(not counted)</span>"}</dd></div>
                <div><dt>Transport</dt><dd>${DG.esc(a.transport)}${a.tcp_fallback ? " (UDP truncated → TCP retry)" : ""}</dd></div>
                <div><dt>Header flags</dt><dd class="mono">${DG.esc((a.flags || []).join(" ") || "—")}</dd></div>
                <div><dt>TTL</dt><dd>${a.ttl !== null && a.ttl !== undefined ? `${DG.esc(a.ttl)} s` : "—"}</dd></div>
                <div><dt>Timestamp</dt><dd>${DG.esc(DG.fmt.dateTime(a.timestamp))}</dd></div>
                <div class="wide"><dt>Returned records</dt><dd>${DG.render.records(a.records)}</dd></div>
                ${a.cname_chain && a.cname_chain.length ? `<div class="wide"><dt>CNAME chain</dt><dd>${DG.render.chain(a.cname_chain)}</dd></div>` : ""}
                ${a.error ? `<div class="wide"><dt>Error details</dt><dd>${DG.esc(a.error)}</dd></div>` : ""}
              </dl>
            </td></tr>`).join("")}
          </tbody>
        </table></div>`;
      DG.icons();
    }
    function toggle(tr) {
      const i = tr.dataset.i;
      const detail = container.querySelector(`tr[data-for="${i}"]`);
      const open = !tr.classList.contains("open");
      tr.classList.toggle("open", open);
      tr.setAttribute("aria-expanded", String(open));
      detail.classList.toggle("hidden", !open);
    }
    container.onclick = (e) => {
      const th = e.target.closest("th.sortable");
      if (th) { const k = th.dataset.sort; dir = k === sortKey ? -dir : 1; sortKey = k; draw(); return; }
      const tr = e.target.closest("tr.expandable");
      if (tr) toggle(tr);
    };
    container.onkeydown = (e) => {
      if (e.key !== "Enter" && e.key !== " ") return;
      const th = e.target.closest("th.sortable");
      if (th) { e.preventDefault(); th.click(); return; }
      const tr = e.target.closest("tr.expandable");
      if (tr) { e.preventDefault(); toggle(tr); }
    };
    draw();
  };

  /** Per-attempt latency line chart (successful samples only, median as dashed line). */
  DG.latencyChart = function (id, box, attemptsByResolver) {
    const canvas = DG.$("canvas", box);
    const keys = Object.keys(attemptsByResolver || {});
    const maxN = Math.max(0, ...keys.map((k) => attemptsByResolver[k].length));
    const anySuccess = keys.some((k) => attemptsByResolver[k].some((a) => a.category === "SUCCESS"));
    if (!maxN || !anySuccess) {
      if (DG.charts[id]) { DG.charts[id].destroy(); delete DG.charts[id]; }
      DG.chartEmpty(box, maxN ? "No successful measurements — latency is only plotted for attempts that returned records." : "Run a test to see per-query latency.");
      return;
    }
    DG.chartEmpty(box, null);
    const labels = Array.from({ length: maxN }, (_, i) => `#${i + 1}`);
    const datasets = [];
    for (const k of keys) {
      const color = DG.resolverColor(k);
      const list = attemptsByResolver[k];
      const data = labels.map((_, i) => (list[i] && list[i].category === "SUCCESS" ? list[i].latency_ms : null));
      const samples = data.filter((v) => v !== null).sort((a, b) => a - b);
      const n = samples.length;
      const med = n ? (n % 2 ? samples[(n - 1) / 2] : (samples[n / 2 - 1] + samples[n / 2]) / 2) : null;
      const name = DG.resolverMap[k]?.short || k;
      datasets.push({ label: name, data, borderColor: color, backgroundColor: color, pointBackgroundColor: color, pointBorderColor: DG.colors().surface, pointBorderWidth: 2, pointRadius: 4.5, tension: 0.25, spanGaps: false, _attempts: list });
      if (med !== null) datasets.push({ label: `${name} median`, data: labels.map(() => med), borderColor: color, borderDash: [5, 5], borderWidth: 1.5, pointRadius: 0, pointHoverRadius: 0, _median: true });
    }
    DG.makeChart(id, canvas, {
      type: "line",
      data: { labels, datasets },
      options: {
        interaction: { mode: "index", intersect: false },
        scales: { x: DG.axis("Attempt"), y: DG.axis("Latency (ms)", { beginAtZero: true }) },
        plugins: {
          tooltip: {
            filter: (item) => !item.dataset._median,
            callbacks: {
              label(ctx) {
                const a = ctx.dataset._attempts?.[ctx.dataIndex];
                if (!a) return "";
                return a.category === "SUCCESS" ? ` ${ctx.dataset.label}: ${DG.fmt.ms(a.latency_ms)}` : ` ${ctx.dataset.label}: ${DG.catInfo(a.category)[2]} (excluded)`;
              },
            },
          },
        },
      },
    });
  };

  /** Renders the legend markup for resolvers. */
  DG.legendHTML = (keys, extra = []) =>
    `<div class="legend">${keys.map((k) => `<span><i style="background:var(--${DG.esc(k)})"></i>${DG.esc(DG.resolverMap[k]?.name || k)}</span>`).join("")}${extra.map((x) => `<span>${x}</span>`).join("")}</div>`;

  /* ---------------------------------------------------- page chrome boot */
  function initChrome() {
    DG.icons();
    if (window.Chart) applyChartDefaults();

    const toggle = document.getElementById("theme-toggle");
    toggle?.addEventListener("click", () => {
      const next = DG.theme() === "dark" ? "light" : "dark";
      setTheme(next);
      DG.toast("info", next === "dark" ? "Dark theme on" : "Light theme on", null, 1800);
    });

    const clock = document.getElementById("clock");
    if (clock) {
      const tick = () => {
        const d = new Date();
        clock.textContent = d.toLocaleString(undefined, { weekday: "short", day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit", second: "2-digit" });
        clock.setAttribute("datetime", d.toISOString());
      };
      tick(); setInterval(tick, 1000);
    }

    const menuBtn = document.getElementById("menu-btn");
    menuBtn?.addEventListener("click", () => {
      const open = !document.body.classList.contains("nav-open");
      document.body.classList.toggle("nav-open", open);
      menuBtn.setAttribute("aria-expanded", String(open));
    });
    document.addEventListener("click", (e) => {
      if (document.body.classList.contains("nav-open") && !e.target.closest("#sidebar") && !e.target.closest("#menu-btn")) {
        document.body.classList.remove("nav-open"); menuBtn?.setAttribute("aria-expanded", "false");
      }
    });

    const pulse = document.getElementById("sys-pulse"), label = document.getElementById("sys-label");
    if (pulse && label) {
      const check = async () => {
        try {
          const s = await DG.api("/api/status");
          const good = s.database === "ok";
          pulse.className = `pulse ${good ? "ok" : "warn"}`;
          label.textContent = good ? "System online" : "Database issue";
        } catch (e) {
          pulse.className = "pulse err"; label.textContent = "Server unreachable";
        }
      };
      check(); setInterval(check, 30000);
    }
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", initChrome);
  else initChrome();
})();
