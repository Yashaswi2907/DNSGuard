/* About DNS: interactive step-through of a recursive DNS lookup. */
(function () {
  "use strict";
  const { $, $$ } = DG;
  const STEPS = [
    { n: ["client"], l: [], title: "1. An application needs an address",
      body: "Your browser wants to open www.example.com. It asks the operating system's stub resolver, which first checks the local cache and hosts file. On a cache miss, it sends a query to the configured recursive resolver." },
    { n: ["client", "resolver"], l: [1], title: "2. Recursive query over UDP port 53",
      body: "The stub sends one UDP datagram to 8.8.8.8 or 1.1.1.1 asking for the A record of www.example.com, with the RD (recursion desired) flag set. DNSGuard sends exactly this kind of query and starts its timer here." },
    { n: ["resolver", "cache"], l: [], title: "3. The resolver checks its cache",
      body: "If a cached answer is still within its TTL, the resolver replies immediately. This is why repeated queries are usually faster than the first one. Otherwise it starts resolving iteratively." },
    { n: ["resolver", "root"], l: [2], title: "4. Ask a root server",
      body: "The resolver asks a root server. The root does not know www.example.com, but it returns a referral: the NS records of the .com top-level domain servers." },
    { n: ["resolver", "tld"], l: [3], title: "5. Ask the TLD server",
      body: "The .com server also returns a referral, this time to the authoritative name servers for example.com." },
    { n: ["resolver", "auth"], l: [4], title: "6. Ask the authoritative server",
      body: "The authoritative server holds the example.com zone. It returns the answer: an A record (or a CNAME to follow), or NXDOMAIN if the name does not exist, or an empty NOERROR answer if there is no A record." },
    { n: ["client", "resolver", "cache"], l: [1], title: "7. Answer returned and cached",
      body: "The resolver caches the answer for its TTL and returns it to the client with the RA flag and a response code. DNSGuard stops its timer, classifies the RCODE and records the latency." },
  ];
  let i = 0, timer = null;
  const dots = $("#flow-dots");
  dots.innerHTML = STEPS.map((_, k) => `<button role="tab" aria-label="Step ${k + 1}" data-k="${k}"></button>`).join("");

  function draw() {
    const s = STEPS[i];
    $$("#flow .net-node").forEach((n) => n.classList.toggle("active", s.n.includes(n.dataset.n)));
    $$("#flow .net-link").forEach((l) => l.classList.toggle("active", s.l.includes(Number(l.dataset.l))));
    $$("#flow .net-label").forEach((l) => l.classList.toggle("active", s.l.includes(Number(l.dataset.t))));
    $("#flow-title-text").textContent = s.title;
    $("#flow-body").textContent = s.body;
    $("#flow-count").textContent = `Step ${i + 1} of ${STEPS.length}`;
    $$("button", dots).forEach((b, k) => b.setAttribute("aria-current", String(k === i)));
    $("#flow-prev").disabled = i === 0;
    $("#flow-next").disabled = i === STEPS.length - 1;
  }
  function stop() { clearInterval(timer); timer = null; $("#flow-play").innerHTML = '<i data-lucide="play"></i>Auto-play'; DG.icons(); }
  $("#flow-prev").addEventListener("click", () => { stop(); i = Math.max(0, i - 1); draw(); });
  $("#flow-next").addEventListener("click", () => { stop(); i = Math.min(STEPS.length - 1, i + 1); draw(); });
  dots.addEventListener("click", (e) => { const b = e.target.closest("button"); if (b) { stop(); i = Number(b.dataset.k); draw(); } });
  $("#flow-play").addEventListener("click", () => {
    if (timer) { stop(); return; }
    if (i === STEPS.length - 1) i = 0;
    draw();
    $("#flow-play").innerHTML = '<i data-lucide="pause"></i>Pause'; DG.icons();
    timer = setInterval(() => { if (i >= STEPS.length - 1) { stop(); return; } i += 1; draw(); }, 2600);
  });
  document.addEventListener("keydown", (e) => {
    if (e.target.closest("input, textarea, select")) return;
    if (e.key === "ArrowRight") $("#flow-next").click();
    if (e.key === "ArrowLeft") $("#flow-prev").click();
  });
  draw();
})();
