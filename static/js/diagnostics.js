/* DNS Diagnostics page: validates input, starts a background test, polls real progress, renders the result. */
(function () {
  "use strict";
  const { $, $$, esc, fmt } = DG;
  const form = $("#dns-form");
  const domainInput = $("#domain");
  const states = ["idle", "running", "error", "done"];
  let lastResult = null;
  let running = false;

  const show = (name) => states.forEach((s) => $(`#state-${s}`).classList.toggle("hidden", s !== name));

  /* ------------------------------------------------- client validation */
  const LABEL = /^(?!-)[a-z0-9_-]{1,63}(?<!-)$/i;
  function cleanDomain(raw) {
    let v = (raw || "").trim();
    if (v.includes("://")) { try { v = new URL(v).hostname; } catch (e) { /* keep */ } }
    v = v.split("/")[0].replace(/\.$/, "").toLowerCase();
    return v;
  }
  function validateDomain(v) {
    if (!v) return "Enter a domain name, for example example.com.";
    if (/^[\d.]+$/.test(v) || v.includes(":")) return "That looks like an IP address. Enter a domain name instead.";
    if (v.length > 253) return "Domain name exceeds 253 characters.";
    const labels = v.split(".");
    if (labels.length < 2) return "Enter a fully qualified domain name, for example example.com.";
    // Allow Unicode (IDN) labels; the server converts them with IDNA.
    for (const l of labels) {
      if (!l) return "Domain name contains an empty label (two dots in a row).";
      if (/^[\x00-\x7F]*$/.test(l) && !LABEL.test(l)) return `Invalid label "${l}": use letters, digits and hyphens, not starting or ending with a hyphen.`;
    }
    return null;
  }
  function setFieldError(msg) {
    $("#f-domain").classList.toggle("invalid", !!msg);
    $("#domain-error").textContent = msg || "";
    domainInput.setAttribute("aria-invalid", msg ? "true" : "false");
  }
  domainInput.addEventListener("input", () => { if ($("#f-domain").classList.contains("invalid")) setFieldError(validateDomain(cleanDomain(domainInput.value))); });

  /* ----------------------------------------------------------- inputs */
  const timeout = $("#timeout");
  const syncTimeout = () => { $("#timeout-out").textContent = `${Number(timeout.value).toFixed(1)} s`; };
  timeout.addEventListener("input", syncTimeout);
  $$(".example").forEach((b) => b.addEventListener("click", () => { domainInput.value = b.dataset.domain; setFieldError(null); domainInput.focus(); }));

  function readForm() {
    const fd = new FormData(form);
    return {
      domain: cleanDomain(fd.get("domain")),
      record_type: fd.get("record_type"),
      resolvers: fd.get("resolvers"),
      attempts: Number(fd.get("attempts")),
      timeout: Number(fd.get("timeout")),
    };
  }

  function setRunning(on) {
    running = on;
    $("#run-btn").disabled = on;
    $("#run-btn").innerHTML = on ? '<i data-lucide="loader-circle"></i>Running…' : '<i data-lucide="play"></i>Run DNS Diagnostic';
    $$("input, button", form).forEach((el) => { if (el.id !== "run-btn") el.disabled = on; });
    DG.icons();
    if (on) $("#run-btn svg")?.animate([{ transform: "rotate(0deg)" }, { transform: "rotate(360deg)" }], { duration: 900, iterations: Infinity });
  }

  /* -------------------------------------------------------- progress */
  function renderProgress(job, total, payload) {
    const pct = total ? Math.round((job.completed / total) * 100) : 0;
    $("#progress-bar").style.width = `${pct}%`;
    $("#progress").setAttribute("aria-valuenow", String(pct));
    $("#progress-text").textContent = `${job.completed} of ${total} queries completed`;
    $("#progress-pct").textContent = `${pct}%`;
    const keys = payload.resolvers === "both" ? Object.keys(DG.resolverMap) : [payload.resolvers];
    $("#ticks").innerHTML = keys.map((k) => {
      const done = (job.latest || []).filter((a) => a.resolver_key === k);
      const cells = Array.from({ length: payload.attempts }, (_, i) => {
        const a = done.find((x) => x.attempt === i + 1);
        const cls = a ? DG.outcomeClass(a.category) : "";
        const tip = a ? `Attempt ${a.attempt}: ${DG.catInfo(a.category)[2]}${a.category === "SUCCESS" ? `, ${fmt.ms(a.latency_ms)}` : ""}` : `Attempt ${i + 1}: pending`;
        return `<span class="tick ${cls}" data-tip="${esc(tip)}"></span>`;
      }).join("");
      return `<div style="display:flex;align-items:center;gap:12px;margin-top:14px"><span style="width:110px">${DG.resolverTag(k)}</span><div class="ticks" style="margin:0">${cells}</div></div>`;
    }).join("");
  }

  /* --------------------------------------------------------- results */
  function renderResult(r) {
    lastResult = r;
    const diag = r.diagnosis;
    const sevIcon = { ok: "circle-check", info: "info", warning: "triangle-alert", error: "circle-x" }[diag.severity] || "info";
    const sevColor = { ok: "var(--ok)", info: "var(--info)", warning: "var(--warn)", error: "var(--err)" }[diag.severity];
    $("#sum-headline").innerHTML = `<i data-lucide="${sevIcon}" style="color:${sevColor};width:22px;height:22px"></i><span>${esc(diag.headline)}</span>`;
    const o = r.overall;
    $("#sum-facts").innerHTML = [
      `<span><b class="mono">${esc(r.domain)}</b> ${esc(r.record_type)}</span>`,
      `<span><b>${o.total}</b> queries</span>`,
      `<span><b>${o.successful}</b> successful</span>`,
      `<span>failure rate <b>${fmt.pct(o.failure_rate)}</b></span>`,
      `<span>finished in <b>${fmt.ms(r.duration_ms, 0)}</b></span>`,
      r.id ? `<span>test <b>#${r.id}</b></span>` : "",
    ].join("");
    const id = r.id;
    $("#act-compare").href = id ? `/comparison?id=${id}` : "/comparison";
    $("#act-report").href = id ? `/reports?id=${id}` : "/reports";
    $("#act-csv").href = id ? `/api/history/export/csv?test_id=${id}` : "#";
    $("#act-json").href = id ? `/api/history/export/json?test_id=${id}` : "#";
    $("#act-compare").classList.toggle("hidden", r.resolver_keys.length < 2);

    const keys = r.resolver_keys;
    const rec = r.comparison.record_consistency;
    const onlyA = new Set(rec ? rec.only_a : []), onlyB = new Set(rec ? rec.only_b : []);
    $("#res-cards").innerHTML = keys.map((k, i) => DG.render.resolverCard(k, r.resolver_meta[k], r.comparison.resolvers[k].summary, r.record_type, i === 0 ? onlyA : onlyB)).join("");
    $("#res-cards").className = `grid ${keys.length > 1 ? "cols-2" : ""}`;

    $("#lat-legend").innerHTML = DG.legendHTML(keys);
    DG.latencyChart("diag-latency", $("#lat-box"), r.attempts);
    $("#diagnosis").innerHTML = DG.render.diagnosis(diag, r.resolver_meta);
    DG.render.attemptsTable($("#attempts"), r.attempts);
    show("done");
    $("#state-done").style.display = "flex";
    DG.icons();
  }

  /* ------------------------------------------------------------- run */
  async function run(payload) {
    setRunning(true);
    $("#state-done").style.display = "";
    show("running");
    const nRes = payload.resolvers === "both" ? 2 : 1;
    const total = payload.attempts * nRes;
    $("#run-title").textContent = `Querying ${payload.domain}`;
    $("#run-sub").textContent = `${payload.record_type} record, ${payload.attempts} attempt${payload.attempts > 1 ? "s" : ""} per resolver, ${payload.timeout.toFixed(1)} s timeout`;
    renderProgress({ completed: 0, latest: [] }, total, payload);
    try {
      const start = await DG.api("/api/dns/resolve", { method: "POST", body: { ...payload, async: true } });
      let job;
      for (;;) {
        await DG.sleep(250);
        job = await DG.api(`/api/dns/jobs/${encodeURIComponent(start.job_id)}`);
        renderProgress(job, start.total, payload);
        if (job.state !== "running") break;
      }
      if (job.state === "error") throw new Error(job.error || "The test could not be completed.");
      renderResult(job.result);
      const sev = job.result.diagnosis.severity;
      DG.toast(sev === "ok" ? "ok" : sev === "error" ? "err" : "warn", "Diagnostic complete", job.result.diagnosis.headline);
      const url = new URL(location.href); url.searchParams.set("id", job.result.id); history.replaceState(null, "", url);
    } catch (e) {
      if (e.field === "domain") setFieldError(e.message);
      $("#error-text").textContent = e.message;
      show("error");
      DG.toast("err", "Test failed", e.message);
    } finally {
      setRunning(false);
    }
  }

  form.addEventListener("submit", (e) => {
    e.preventDefault();
    if (running) return;
    const payload = readForm();
    const err = validateDomain(payload.domain);
    setFieldError(err);
    if (err) { domainInput.focus(); return; }
    domainInput.value = payload.domain;
    run(payload);
  });
  $("#retry-btn").addEventListener("click", () => form.requestSubmit());
  $("#reset-btn").addEventListener("click", () => {
    form.reset(); syncTimeout(); setFieldError(null);
    lastResult = null; $("#state-done").style.display = ""; show("idle");
    history.replaceState(null, "", location.pathname);
    domainInput.focus();
    DG.toast("info", "Form reset", null, 1600);
  });
  document.addEventListener("dg:theme", () => { if (lastResult) DG.latencyChart("diag-latency", $("#lat-box"), lastResult.attempts); });

  /* ------------------------------------------- deep links (?id= / ?domain=) */
  (async function init() {
    syncTimeout();
    const id = DG.param("id");
    const d = DG.param("domain");
    if (d) domainInput.value = d;
    const t = DG.param("type");
    if (t === "AAAA") $("#rt-aaaa").checked = true;
    if (!id) return;
    try {
      const test = await DG.api(`/api/history/${encodeURIComponent(id)}`);
      renderResult({
        id: test.id, domain: test.domain, record_type: test.record_type, resolver_keys: test.resolvers,
        resolver_meta: test.resolver_meta, attempts: test.attempts_by_resolver, comparison: test.comparison,
        diagnosis: test.diagnosis, duration_ms: test.duration_ms,
        overall: { total: test.total_queries, successful: test.successful, failure_rate: test.failure_rate },
      });
      domainInput.value = test.domain;
      $(test.record_type === "AAAA" ? "#rt-aaaa" : "#rt-a").checked = true;
    } catch (e) {
      DG.toast("warn", "Could not open that test", e.message);
    }
  })();
})();
