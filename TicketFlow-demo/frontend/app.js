/* TicketFlow dashboard — všetko sú skutočné HTTP / WebSocket volania. Žiadne predpripravené výsledky. */
"use strict";

const $ = (sel, root = document) => root.querySelector(sel);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const timeNow = () => new Date().toLocaleTimeString("sk-SK", { hour12: false }) + "." + String(new Date().getMilliseconds()).padStart(3, "0");
const rnd = () => Math.random().toString(36).slice(2, 10);
const params = new URLSearchParams(location.search);
const SEAT_LABEL = { FREE: "VOĽNÉ", PENDING: "PENDING", CONFIRMED: "CONFIRMED" };

/* ---------- HTTP ---------- */
async function api(method, path, { body, headers = {}, raw = false } = {}) {
  const h = { ...headers };
  if (body !== undefined) h["Content-Type"] = "application/json";
  const t0 = performance.now();
  let res;
  try {
    res = await fetch(path, { method, headers: h, body: body !== undefined ? JSON.stringify(body) : undefined });
  } catch (e) {
    showOffline(true);
    return { status: 0, ok: false, json: null, text: String(e), cid: "-", ms: 0, headers: new Headers() };
  }
  showOffline(false);
  const text = await res.text();
  let json = null;
  if (!raw) { try { json = JSON.parse(text); } catch { /* not json */ } }
  return { status: res.status, ok: res.ok, json, text, cid: res.headers.get("X-Correlation-ID") || "-",
           ms: Math.round(performance.now() - t0), headers: res.headers };
}

function showOffline(on) { $("#offline-banner").style.display = on ? "block" : "none"; }

function log(demo, { status, label, cid, before, after }) {
  const li = document.createElement("li");
  const cls = status >= 200 && status < 300 ? "ok" : (status ? "err" : "");
  const ba = before !== undefined || after !== undefined ? ` <span class="ba">${esc(before ?? "—")} → ${esc(after ?? "—")}</span>` : "";
  li.innerHTML = `<span class="t">${timeNow()}</span><span class="code ${cls}">${status || "—"}</span>` +
    `<span>${esc(label)}${ba}<br><span class="cid">${esc(cid || "-")}</span></span>`;
  $(`#log-${demo}`).prepend(li);
}

function badge(status, text) {
  const cls = status >= 200 && status < 300 ? "ok" : status === 409 || status === 422 ? "warn" : "err";
  return `<span class="badge ${cls}">${esc(text)}</span>`;
}
const httpText = (s) => ({ 200: "200 OK", 201: "201 Created", 400: "400 Bad Request", 401: "401 Unauthorized",
  404: "404 Not Found", 409: "409 Conflict", 422: "422 Unprocessable", 500: "500 Fault", 0: "Sieťová chyba" }[s] || String(s));

async function busy(btn, fn) {
  const all = btn.closest(".buttons")?.querySelectorAll("button") || [btn];
  all.forEach((b) => (b.disabled = true));
  try { await fn(); } catch (e) { console.error(e); alert("Chyba v demo paneli: " + e.message); }
  finally { all.forEach((b) => (b.disabled = false)); }
}

/* ---------- Health ---------- */
async function refreshHealth() {
  const r = await api("GET", "/health/deps");
  const d = r.json || {};
  const okv = { db: "ok", grpc: "SERVING", provider: "ok" };
  document.querySelectorAll("#health [data-dep]").forEach((el) => {
    const k = el.dataset.dep;
    const ok = d[k] === okv[k];
    el.className = "chip " + (ok ? "ok" : "bad");
    el.textContent = { db: "PostgreSQL", grpc: "gRPC :50051", provider: "Provider" }[k] + (ok ? " ✓" : " ✗");
  });
}

/* ---------- Tabs ---------- */
function selectTab(t) {
  document.querySelectorAll("nav.tabs button").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.tab === t)));
  document.querySelectorAll("section.panel").forEach((p) => p.classList.toggle("active", p.dataset.demo === t));
  history.replaceState(null, "", `?tab=${t}${params.get("solo") ? "&solo=" + params.get("solo") : ""}`);
}
document.querySelectorAll("nav.tabs button").forEach((b) => b.addEventListener("click", () => selectTab(b.dataset.tab)));
document.querySelectorAll(".subtabs button").forEach((b) => b.addEventListener("click", () => {
  document.querySelectorAll(".subtabs button").forEach((x) => x.setAttribute("aria-selected", String(x === b)));
  $("#sub-soap").hidden = b.dataset.sub !== "soap";
  $("#sub-grpc").hidden = b.dataset.sub !== "grpc";
}));

/* =====================================================================
   DEMO A — REST
   ===================================================================== */
const A = { last: null };

async function seatState(seat = "A7") {
  const r = await api("GET", `/demo/state?seat=${seat}`);
  return r.json;
}
function renderSeat(st) {
  if (!st) return;
  $("#a-seat").textContent = SEAT_LABEL[st.seat.status] || st.seat.status;
  $("#a-count").textContent = st.active_count;
  $("#a-sql").textContent = "SELECT id, buyer_id, status FROM reservations\nWHERE seat_id = 'A7' AND status IN ('PENDING','CONFIRMED');\n\n" +
    (st.active_reservations.length ? st.active_reservations.map((r) => `${r.id} | ${r.buyer_id} | ${r.status}`).join("\n") : "(0 riadkov)");
}

function renderA(title, r, extra = "") {
  const j = r.json || {};
  const replay = r.headers.get("Idempotent-Replayed");
  $("#a-result").innerHTML = `<div class="status-line">${badge(r.status, httpText(r.status))}<span class="big">${esc(title)}</span></div>
    ${j.id ? `<div>reservation_id <b>${esc(j.id)}</b>${replay ? ` · Idempotent-Replayed: <b>${esc(replay)}</b>` : ""}</div>` : ""}
    ${j.code ? `<div><b>${esc(j.code)}</b></div>` : ""}${extra}
    <div class="small muted">${esc(r.cid)}</div>`;
  if (j.id) $("#a-rid").textContent = j.id;
}

async function aCreate() {
  const before = await seatState();
  A.last = { body: { event_id: "42", seat_id: "A7", buyer_id: "buyer-anna" }, key: "demo-" + rnd() };
  const r = await api("POST", "/reservations", { body: A.last.body, headers: { "Idempotency-Key": A.last.key } });
  const after = await seatState();
  renderA("Vytvorené", r);
  renderSeat(after);
  log("A", { status: r.status, label: `Vytvoriť (key ${A.last.key})`, cid: r.cid, before: SEAT_LABEL[before.seat.status], after: SEAT_LABEL[after.seat.status] });
}

async function aRetry() {
  if (!A.last) { await aCreate(); }
  const before = await seatState();
  const r = await api("POST", "/reservations", { body: A.last.body, headers: { "Idempotency-Key": A.last.key } });
  const after = await seatState();
  renderA("Retry: žiadny nový nákup", r, `<div>rezervácie v DB: <b>${before.active_count} → ${after.active_count}</b></div>`);
  renderSeat(after);
  log("A", { status: r.status, label: `Retry (key ${A.last.key}) → ${r.json?.id ?? r.json?.code}`, cid: r.cid, before: `${before.active_count} rez.`, after: `${after.active_count} rez.` });
}

async function aMismatch() {
  if (!A.last) { await aCreate(); }
  const before = await seatState();
  const r = await api("POST", "/reservations", { body: { ...A.last.body, buyer_id: "buyer-boris" }, headers: { "Idempotency-Key": A.last.key } });
  const after = await seatState();
  renderA("Rovnaký kľúč, iný payload", r);
  renderSeat(after);
  log("A", { status: r.status, label: `Iný payload, key ${A.last.key}`, cid: r.cid, before: `${before.active_count} rez.`, after: `${after.active_count} rez.` });
}

async function aReset() {
  const r = await api("POST", "/demo/reset");
  A.last = null;
  $("#a-rid").textContent = "—";
  const st = await seatState();
  renderSeat(st);
  $("#a-result").innerHTML = `<div class="status-line">${badge(r.status, httpText(r.status))}<span class="big">A7 je VOĽNÉ</span></div>`;
  log("A", { status: r.status, label: "Reset demo dát", cid: r.cid, after: SEAT_LABEL[st.seat.status] });
}

async function aRace() {
  await aReset();
  const before = await seatState();
  const mk = (buyer) => api("POST", "/reservations", {
    body: { event_id: "42", seat_id: "A7", buyer_id: buyer }, headers: { "Idempotency-Key": `race-${buyer}-${rnd()}` } });
  // dve nezávislé HTTP požiadavky odoslané súčasne
  const [r1, r2] = await Promise.all([mk("buyer-anna"), mk("buyer-boris")]);
  const after = await seatState();
  const row = (name, r) => `<div class="tile ${r.status === 201 ? "accent" : ""}"><div class="label">${name}</div>
    ${badge(r.status, httpText(r.status))}<div class="small" style="margin-top:8px">${esc(r.json?.id || r.json?.code || "")}</div>
    <div class="small muted">${esc(r.cid)} · ${r.ms} ms</div></div>`;
  $("#a-result").innerHTML = `<div class="status-line"><span class="big">Súbeh: ${[r1, r2].filter((r) => r.status === 201).length} víťaz</span></div>
    <div class="tiles">${row("Kupujúci Anna", r1)}${row("Kupujúci Boris", r2)}</div>
    <div class="small muted">Rozhodla PostgreSQL: unique index one_active_reservation_per_seat</div>`;
  renderSeat(after);
  const win = r1.status === 201 ? r1 : r2;
  if (win.json?.id) $("#a-rid").textContent = win.json.id;
  log("A", { status: r1.status, label: "Súbeh — Anna", cid: r1.cid });
  log("A", { status: r2.status, label: "Súbeh — Boris", cid: r2.cid, before: `${before.active_count} rez.`, after: `${after.active_count} rez.` });
}

/* =====================================================================
   DEMO B — SOAP & gRPC
   ===================================================================== */
const B = { soapBytes: null, grpcBytes: null };

function highlight(xml, word) {
  return esc(xml).replaceAll(esc(word), `<mark>${esc(word)}</mark>`);
}

async function bWsdl() {
  const r = await api("GET", "/soap?wsdl", { raw: true });
  $("#b-left-title").textContent = "WSDL (výrez — operácia)";
  $("#b-right-title").textContent = "WSDL (celé)";
  const opStart = r.text.indexOf("<wsdl:portType");
  const opEnd = r.text.indexOf("</wsdl:binding>") + "</wsdl:binding>".length;
  $("#b-left").innerHTML = highlight(r.text.slice(opStart, opEnd), "CheckSeat");
  $("#b-right").innerHTML = highlight(r.text, "CheckSeat");
  $("#b-soap-result").innerHTML = `<div class="status-line">${badge(r.status, httpText(r.status))}<span class="big">WSDL obsahuje operáciu CheckSeat</span></div>
    <div class="small muted">${esc(r.cid)}</div>`;
  log("B", { status: r.status, label: "SOAP: GET /soap?wsdl", cid: r.cid });
}

async function bSoap(invalid) {
  const r = await api("GET", `/demo/rpc/soap?seat=A7${invalid ? "&invalid=true" : ""}`);
  const j = r.json;
  $("#b-left-title").textContent = "Request XML";
  $("#b-right-title").textContent = j.is_fault ? "Response XML — SOAP Fault" : "Response XML";
  $("#b-left").innerHTML = highlight(j.request_xml, "CheckSeat");
  $("#b-right").innerHTML = highlight(j.response_xml, j.is_fault ? "Fault" : "available");
  const avail = /<tns:available>(\w+)<\/tns:available>/.exec(j.response_xml)?.[1];
  const fault = /<faultstring>([^<]*)<\/faultstring>/.exec(j.response_xml)?.[1];
  $("#b-soap-result").innerHTML = `<div class="status-line">${badge(j.http_status, j.is_fault ? "SOAP Fault (HTTP 500)" : "HTTP 200")}
      <span class="big">${j.is_fault ? esc(fault) : `available = ${esc(avail)}`}</span></div>
    <div class="small muted">body ${j.request_body_bytes} B → ${j.response_body_bytes} B · ${esc(j.correlation_id)}</div>`;
  if (!invalid) { B.soapBytes = j; renderBytes(); }
  log("B", { status: j.http_status, label: invalid ? "SOAP: neplatný request → Fault" : `SOAP CheckSeat → available=${avail}`, cid: j.correlation_id });
}

async function bGrpc(delay, deadline) {
  const q = `/demo/rpc/grpc?seat=A7&delay_ms=${delay}${deadline ? `&deadline_ms=${deadline}` : ""}`;
  const r = await api("GET", q);
  const j = r.json;
  const okCall = j.ok;
  $("#b-grpc-result").innerHTML = `<div class="status-line">${badge(okCall ? 200 : 500, j.code)}
      <span class="big">${okCall ? `available = ${j.reply.available} (${esc(j.reply.status)})` : esc(j.details)}</span></div>
    <div>deadline <b>${deadline ? deadline + " ms" : "—"}</b> · klient čakal <b>${j.client_elapsed_ms} ms</b>${okCall ? ` · server ${j.reply.server_elapsed_ms} ms` : ""}</div>
    <div class="small muted">${esc(j.correlation_id)}</div>`;
  renderTimeline(delay, deadline, j);
  if (okCall && !delay) { B.grpcBytes = j; renderBytes(); }
  log("B", { status: okCall ? 200 : 504, label: `gRPC CheckSeat delay=${delay} deadline=${deadline ?? "—"} → ${j.code}`, cid: j.correlation_id });
}

function renderTimeline(delay, deadline, j) {
  const scale = Math.max(delay, deadline || 0, j.client_elapsed_ms, 100) * 1.15;
  const pct = (ms) => Math.min(100, (ms / scale) * 100).toFixed(1) + "%";
  const serverWanted = delay + (j.reply?.server_elapsed_ms ? j.reply.server_elapsed_ms - delay : 0);
  $("#b-timeline").innerHTML = `
    <div class="timeline">
      <span class="tlabel tl-srv">Server: umelá práca ~${Math.round(serverWanted)} ms</span>
      <div class="track srv"><div class="bar srv" style="width:${pct(Math.max(serverWanted, 2))}"></div></div>
      <span class="tlabel tl-cli">Klient: ${j.client_elapsed_ms} ms → ${esc(j.code)}</span>
      <div class="track cli"><div class="bar cli ${j.ok ? "" : "err"}" style="width:${pct(j.client_elapsed_ms)}"></div></div>
      ${deadline ? `<div class="deadline" style="left:${pct(deadline)}"><span>deadline ${deadline} ms</span></div>` : ""}
    </div>
    <p class="small" style="margin-top:8px">${j.ok ? "Stihlo sa pred deadline." : "Klient prestal čakať pri deadline, gRPC zrušil prácu aj na serveri."}</p>`;
}

function renderBytes() {
  const s = B.soapBytes, g = B.grpcBytes;
  $("#b-bytes").innerHTML = `SOAP XML body: <b>${s ? `${s.request_body_bytes} / ${s.response_body_bytes} B` : "—"}</b> ·
    gRPC protobuf: <b>${g ? `${g.request_protobuf_bytes} / ${g.response_protobuf_bytes} B` : "—"}</b>
    <div class="muted">request / response, bez hlavičiek. Platí len pre tieto správy, nie je to benchmark.</div>`;
}

/* =====================================================================
   DEMO C — GraphQL
   ===================================================================== */
const DEMO_QUERY = '{ event(id: "42") { seats(limit: 100) { id price { amount currency } } } }';
const C = { naive: null, batch: null };

function renderSql(stmt) {
  const p = stmt.params || {};
  let sql = stmt.sql.replace(/%\((\w+)\)s/g, (_, k) => (typeof p[k] === "number" ? p[k] : `'${p[k] ?? "…"}'`));
  // dlhý IN zoznam skrátime: IN ('A1', 'A2', 'A3', … 100 hodnôt)
  sql = sql.replace(/IN \(([^)]*)\)/, (m, inner) => {
    const parts = inner.split(", ");
    return parts.length > 4 ? `IN (${parts.slice(0, 3).join(", ")}, … ${parts.length} hodnôt)` : m;
  });
  return sql.replace("SELECT seat_id, amount_cents, currency, internal_cost_cents", "SELECT …")
            .replace("SELECT seat_id, row_label, seat_number", "SELECT …");
}

function sqlPreview(stmts) {
  const shown = stmts.slice(0, 3).map((s, i) => `${i + 1}. ${renderSql(s)}`);
  if (stmts.length > 3) shown.push(`… +${stmts.length - 3} ďalších`);
  return shown.join("\n") + `\n\n= ${stmts.length} SQL`;
}

async function cRun(mode, query = DEMO_QUERY, headers = {}) {
  const path = mode === "naive" ? "/graphql/naive" : "/graphql";
  const r = await api("POST", path, { body: { query }, headers });
  const j = r.json;
  const ext = j.extensions;
  if (query === DEMO_QUERY && !j.errors) {
    C[mode] = j;
    $(`#c-${mode}-count`).textContent = ext.sql.count;
    $(`#c-${mode}-ms`).textContent = `${ext.durationMs} ms (orientačne)`;
    $(`#c-${mode}-log`).textContent = sqlPreview(ext.sql.statements);
  }
  log("C", { status: j.errors ? 400 : r.status, label: `${mode === "naive" ? "Naivne" : "Batching"}: ${ext.sql.count} SQL${j.errors ? " · " + j.errors[0].message : ""}`, cid: r.cid });
  return j;
}

function cSame() {
  if (C.naive && C.batch) {
    const same = JSON.stringify(C.naive.data) === JSON.stringify(C.batch.data);
    $("#c-same").innerHTML = same ? '<span class="badge ok">ÁNO</span>' : '<span class="badge err">NIE</span>';
  }
  $("#c-result").hidden = true;
}

async function cError(kind) {
  const q = kind === "limit"
    ? '{ event(id: "42") { seats(limit: 500) { id } } }'
    : '{ event(id: "42") { seats(limit: 1) { id price { internalCost } } } }';
  $("#c-query").textContent = q;
  const j = await cRun("batch", q);
  $("#c-result").hidden = false;
  $("#c-result").innerHTML = `<div class="status-line">${badge(400, "Zamietnuté")}<span class="big">${esc(j.errors?.[0]?.message || "bez chyby")}</span></div>
    <div class="small muted">SQL dotazov: ${j.extensions.sql.count}</div>`;
}

/* =====================================================================
   DEMO D — Webhook & WebSocket
   ===================================================================== */
const D = { rid: params.get("rid") || null, clients: {} };

function wsUrl(name) {
  return `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws?client=${encodeURIComponent(name)}`;
}

function makeClient(name) {
  const el = document.createElement("div");
  el.className = "client";
  el.innerHTML = `<header><b>Klient ${esc(name)}</b><button class="btn ghost" style="padding:6px 12px;font-size:.85rem">Odpojiť</button></header>
    <div class="small"><span class="conn">ODPOJENÝ</span> · rezervácia <b class="rid">—</b></div>
    <div class="rstatus">—</div><div class="note"></div>`;
  $("#d-clients").append(el);
  const c = { name, el, ws: null, wantConnected: true };
  el.querySelector("button").addEventListener("click", () => {
    if (c.ws && c.ws.readyState <= 1) { c.wantConnected = false; c.ws.close(); }
    else { c.wantConnected = true; connect(c); }
  });
  D.clients[name] = c;
  connect(c);
}

function setClient(c, status, note) {
  if (status) c.el.querySelector(".rstatus").textContent = status;
  if (note) c.el.querySelector(".note").textContent = `${timeNow()} — ${note}`;
  c.el.querySelector(".rid").textContent = D.rid || "—";
}

async function snapshot(c, why) {
  if (!D.rid) {
    const st = await seatState();
    D.rid = st?.active_reservations?.[0]?.id || null;
  }
  if (!D.rid) { setClient(c, "—", `${why}: žiadna aktívna rezervácia`); return; }
  const r = await api("GET", `/reservations/${D.rid}`);
  setClient(c, r.json?.status || "?", `${why} → snapshot GET /reservations/${D.rid}`);
  log("D", { status: r.status, label: `Klient ${c.name}: snapshot po pripojení → ${r.json?.status}`, cid: r.cid });
}

function connect(c) {
  const ws = new WebSocket(wsUrl(c.name));
  c.ws = ws;
  ws.onopen = () => {
    c.el.classList.add("connected");
    c.el.querySelector(".conn").textContent = "PRIPOJENÝ";
    c.el.querySelector("header button").textContent = "Odpojiť";
    snapshot(c, "Pripojený");
  };
  ws.onmessage = (ev) => {
    const m = JSON.parse(ev.data);
    if (m.type === "reservation.created" || m.type === "reservation.confirmed") {
      if (m.reservation.seat_id === "A7") D.rid = m.reservation.id;
      setClient(c, m.reservation.status, `WebSocket: ${m.type}`);
    } else if (m.type === "demo.reset") {
      D.rid = null;
      setClient(c, "—", "WebSocket: demo.reset");
    }
  };
  ws.onclose = () => {
    c.el.classList.remove("connected");
    c.el.querySelector(".conn").textContent = "ODPOJENÝ";
    c.el.querySelector("header button").textContent = "Pripojiť";
    setClient(c, null, c.wantConnected ? "Spojenie stratené" : "Odpojený — správy nedostáva");
  };
}

function renderWebhook(title, r) {
  const j = r.json || {};
  const recv = j.received || {};
  const b = recv.body || {};
  const sig = j.sent?.headers?.["TicketFlow-Signature"];
  $("#d-sent").textContent = j.sent
    ? `POST /webhooks/payment\nTicketFlow-Signature: ${sig ? sig.slice(0, 32) + "…" : "(chýba)"}\n\n${JSON.stringify(JSON.parse(j.sent.raw_body), null, 1)}`
    : r.text;
  $("#d-recv").textContent = `HTTP ${recv.status}\n\n` + JSON.stringify(
    Object.fromEntries(Object.entries(recv.body || {}).filter(([k]) => ["result", "outcome", "code", "event_id", "status_before", "status_after", "detail"].includes(k))), null, 1);
  const st = recv.status ?? r.status;
  const resultText = b.result === "DUPLICATE_IGNORED" ? "Duplicita — prijatá bezpečne, bez zmeny"
    : b.result === "PROCESSED" ? `Spracované: ${b.outcome}` : b.code === "INVALID_SIGNATURE" ? "Zlý podpis — odmietnuté, DB bez zmeny"
    : b.code === "MISSING_SIGNATURE" ? "Bez podpisu — odmietnuté" : b.code || b.detail || "—";
  $("#d-result").innerHTML = `<div class="status-line">${badge(st, httpText(st))}<span class="big">${esc(resultText)}</span></div>
    <div>${esc(title)}${b.status_before ? ` · stav <b>${esc(b.status_before)} → ${esc(b.status_after)}</b>` : ""}${b.websocket_deliveries != null ? ` · WebSocket doručenia: <b>${b.websocket_deliveries}</b>` : ""}</div>
    <div class="small muted">${esc(j.correlation_id || r.cid)}</div>`;
}

async function dCreate() {
  await api("POST", "/demo/reset");
  const r = await api("POST", "/reservations", { body: { event_id: "42", seat_id: "A7", buyer_id: "buyer-demo-d" }, headers: { "Idempotency-Key": "d-" + rnd() } });
  D.rid = r.json?.id || null;
  Object.values(D.clients).forEach((c) => setClient(c));
  $("#d-result").innerHTML = `<div class="status-line">${badge(r.status, httpText(r.status))}<span class="big">${esc(D.rid)} je PENDING</span></div><div class="small muted">${esc(r.cid)}</div>`;
  log("D", { status: r.status, label: `Vytvorená rezervácia ${D.rid}`, cid: r.cid, before: "VOĽNÉ", after: "PENDING" });
}

async function dAction(action, title) {
  if (!D.rid && action !== "replay") await dCreate();
  const before = D.rid ? (await api("GET", `/reservations/${D.rid}`)).json?.status : undefined;
  const r = await api("POST", `/demo/provider/${action}`, { body: { reservation_id: D.rid } });
  const after = D.rid ? (await api("GET", `/reservations/${D.rid}`)).json?.status : undefined;
  renderWebhook(title, r);
  log("D", { status: r.json?.received?.status ?? r.status, label: title, cid: r.json?.correlation_id || r.cid, before, after });
}

/* ---------- wiring ---------- */
const ACTIONS = {
  "a-create": aCreate, "a-retry": aRetry, "a-mismatch": aMismatch, "a-race": aRace, "a-reset": aReset,
  "b-wsdl": bWsdl, "b-soap": () => bSoap(false), "b-soap-fault": () => bSoap(true),
  "b-grpc": () => bGrpc(0, null), "b-grpc-slow": () => bGrpc(800, 200), "b-grpc-ok-slow": () => bGrpc(100, 2000),
  "c-naive": async () => { $("#c-query").textContent = DEMO_QUERY; await cRun("naive"); cSame(); },
  "c-batch": async () => { $("#c-query").textContent = DEMO_QUERY; await cRun("batch"); cSame(); },
  "c-compare": async () => { $("#c-query").textContent = DEMO_QUERY; await cRun("naive"); await cRun("batch"); cSame(); },
  "c-limit": () => cError("limit"), "c-priv": () => cError("priv"),
  "d-create": dCreate,
  "d-pay": () => dAction("payment", "Odoslať platbu (platný podpis)"),
  "d-replay": () => dAction("replay", "Zopakovať webhook (rovnaké event id)"),
  "d-bad": () => dAction("bad-signature", "Pokaziť podpis"),
  "d-unsigned": () => dAction("unsigned", "Bez podpisu"),
};
document.querySelectorAll("[data-action]").forEach((btn) =>
  btn.addEventListener("click", () => busy(btn, async () => {
    const id = btn.dataset.action;
    await ACTIONS[id]();
  })));


/* ---------- init ---------- */
(async function init() {
  selectTab(params.get("tab") || "A");
  refreshHealth();
  setInterval(refreshHealth, 10000);
  renderSeat(await seatState());
  api("GET", "/demo/contracts/proto", { raw: true }).then((r) => ($("#b-proto").textContent = r.text));
  renderBytes();
  const solo = params.get("solo");
  if (solo) makeClient(solo); else { makeClient("A"); makeClient("B"); }
  if (solo) $("#d-open-second").style.display = "none";

  // ?autorun=1 — prehrá scenár danej karty (na screenshoty a nácvik)
  if (params.get("autorun")) {
    const tab = params.get("tab") || "A";
    const wait = (ms) => new Promise((r) => setTimeout(r, ms));
    const run = async (id) => { await ACTIONS[id](); await wait(150); };
    const plans = {
      A: ["a-reset", "a-create", "a-retry", "a-race"],
      B: params.get("sub") === "grpc" ? ["a-reset", "b-grpc", "b-grpc-slow"] : ["a-reset", "b-soap"],
      C: ["a-reset", "c-naive", "c-batch"],
      D: ["d-create", "d-bad", "d-pay", "d-replay"],
    };
    if (tab === "B" && params.get("sub") === "grpc") document.querySelector('.subtabs [data-sub="grpc"]').click();
    await wait(500);
    for (const id of plans[tab]) await run(id);
    document.title = "AUTORUN_DONE";
  }
})();
