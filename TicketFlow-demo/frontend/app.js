/* TicketFlow dashboard — všetko sú skutočné HTTP / WebSocket volania. Žiadne predpripravené výsledky.
   Poradie v súbore: pomocné funkcie → Demo A (REST) → Demo B (SOAP + gRPC)
                     → Demo C (GraphQL) → Demo D (webhook + WebSocket) → tlačidlá a štart. */
"use strict";

/* =====================================================================
   POMOCNÉ FUNKCIE
   ===================================================================== */
const $ = (selector, root = document) => root.querySelector(selector);

// Escapovanie všetkého, čo ide do innerHTML (dáta zo servera / od používateľa) — ochrana pred XSS
const HTML_ESCAPES = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => HTML_ESCAPES[char]);

// Čas s milisekundami — v logu je vidieť poradie udalostí
const timeNow = () => {
  const now = new Date();
  return now.toLocaleTimeString("sk-SK", { hour12: false }) + "." + String(now.getMilliseconds()).padStart(3, "0");
};
const randomId = () => Math.random().toString(36).slice(2, 10);
const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

const params = new URLSearchParams(location.search);
const SEAT_LABEL = { FREE: "VOĽNÉ", PENDING: "PENDING", CONFIRMED: "CONFIRMED" };

/* ---------- HTTP ---------- */
// Jediné miesto, kde dashboard volá API. Vráti stav, telo, correlation ID a trvanie.
async function api(method, path, { body, headers = {}, raw = false } = {}) {
  const requestHeaders = { ...headers };
  if (body !== undefined) requestHeaders["Content-Type"] = "application/json";
  const startedAt = performance.now();

  let response;
  try {
    response = await fetch(path, {
      method,
      headers: requestHeaders,
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  } catch (error) {
    showOffline(true);                                   // API nebeží → červený banner
    return { status: 0, ok: false, json: null, text: String(error), cid: "-", ms: 0, headers: new Headers() };
  }
  showOffline(false);

  const text = await response.text();
  let json = null;
  if (!raw) {
    try { json = JSON.parse(text); } catch { /* nie je JSON */ }
  }
  return {
    status: response.status,
    ok: response.ok,
    json,
    text,
    cid: response.headers.get("X-Correlation-ID") || "-",
    ms: Math.round(performance.now() - startedAt),
    headers: response.headers,
  };
}

function showOffline(isOffline) {
  $("#offline-banner").style.display = isOffline ? "block" : "none";
}

/* ---------- Log udalostí (spodok každej karty) ---------- */
function log(demo, { status, label, cid, before, after }) {
  const statusClass = status >= 200 && status < 300 ? "ok" : (status ? "err" : "");
  const hasChange = before !== undefined || after !== undefined;
  const change = hasChange
    ? ` <span class="ba">${esc(before ?? "—")} → ${esc(after ?? "—")}</span>`
    : "";

  const item = document.createElement("li");
  item.innerHTML =
    `<span class="t">${timeNow()}</span>` +
    `<span class="code ${statusClass}">${status || "—"}</span>` +
    `<span>${esc(label)}${change}<br><span class="cid">${esc(cid || "-")}</span></span>`;
  $(`#log-${demo}`).prepend(item);                    // najnovšie hore
}

/* ---------- Farebný odznak so stavom HTTP ---------- */
function badge(status, text) {
  const badgeClass = status >= 200 && status < 300 ? "ok"
    : status === 409 || status === 422 ? "warn"
    : "err";
  return `<span class="badge ${badgeClass}">${esc(text)}</span>`;
}

const HTTP_TEXT = {
  200: "200 OK", 201: "201 Created", 400: "400 Bad Request", 401: "401 Unauthorized",
  404: "404 Not Found", 409: "409 Conflict", 422: "422 Unprocessable", 500: "500 Fault", 0: "Sieťová chyba",
};
const httpText = (status) => HTTP_TEXT[status] || String(status);

// Počas behu akcie zablokuje všetky tlačidlá v skupine (aby sa nedalo klikať dvakrát)
async function busy(button, action) {
  const group = button.closest(".buttons")?.querySelectorAll("button") || [button];
  group.forEach((other) => (other.disabled = true));
  try {
    await action();
  } catch (error) {
    console.error(error);
    alert("Chyba v demo paneli: " + error.message);
  } finally {
    group.forEach((other) => (other.disabled = false));
  }
}

/* ---------- Health čipy v hlavičke ---------- */
const HEALTHY_VALUE = { db: "ok", grpc: "SERVING", provider: "ok" };
const DEPENDENCY_NAME = { db: "PostgreSQL", grpc: "gRPC :50051", provider: "Provider" };

async function refreshHealth() {
  const response = await api("GET", "/health/deps");
  const deps = response.json || {};
  document.querySelectorAll("#health [data-dep]").forEach((chip) => {
    const dep = chip.dataset.dep;
    const healthy = deps[dep] === HEALTHY_VALUE[dep];
    chip.className = "chip " + (healthy ? "ok" : "bad");
    chip.textContent = DEPENDENCY_NAME[dep] + (healthy ? " ✓" : " ✗");
  });
}

/* ---------- Karty A–D a podkarty SOAP / gRPC ---------- */
function selectTab(tab) {
  document.querySelectorAll("nav.tabs button").forEach((button) =>
    button.setAttribute("aria-selected", String(button.dataset.tab === tab)));
  document.querySelectorAll("section.panel").forEach((panel) =>
    panel.classList.toggle("active", panel.dataset.demo === tab));

  const solo = params.get("solo");
  history.replaceState(null, "", `?tab=${tab}${solo ? "&solo=" + solo : ""}`);
}

function selectSubtab(clicked) {
  document.querySelectorAll(".subtabs button").forEach((button) =>
    button.setAttribute("aria-selected", String(button === clicked)));
  $("#sub-soap").hidden = clicked.dataset.sub !== "soap";
  $("#sub-grpc").hidden = clicked.dataset.sub !== "grpc";
}

/* =====================================================================
   DEMO A — REST
   Retry s rovnakým Idempotency-Key ≠ nový nákup. Súbeh dvoch kupujúcich = 1 víťaz.
   ===================================================================== */
const A = { last: null };            // posledný request { body, key } — na retry / mismatch

// Stav miesta priamo z DB (aby publikum videlo, čo sa naozaj zapísalo)
async function seatState(seat = "A7") {
  const response = await api("GET", `/demo/state?seat=${seat}`);
  return response.json;
}

// ── ukážka A1 ──
function createReservation(body, idempotencyKey) {
  return api("POST", "/reservations", { body, headers: { "Idempotency-Key": idempotencyKey } });
}
// ── /ukážka A1 ──

// Dlaždice „A7“, „Rezervácie v DB“ + SQL výpis
function renderSeat(state) {
  if (!state) return;
  $("#a-seat").textContent = SEAT_LABEL[state.seat.status] || state.seat.status;
  $("#a-count").textContent = state.active_count;

  const rows = state.active_reservations.length
    ? state.active_reservations.map((row) => `${row.id} | ${row.buyer_id} | ${row.status}`).join("\n")
    : "(0 riadkov)";
  $("#a-sql").textContent =
    "SELECT id, buyer_id, status FROM reservations\n" +
    "WHERE seat_id = 'A7' AND status IN ('PENDING','CONFIRMED');\n\n" +
    rows;
}

// Výsledková karta: HTTP stav, reservation_id, prípadne Idempotent-Replayed
function renderA(title, response, extraHtml = "") {
  const data = response.json || {};
  const replayed = response.headers.get("Idempotent-Replayed");
  const replayedHtml = replayed ? ` · Idempotent-Replayed: <b>${esc(replayed)}</b>` : "";

  $("#a-result").innerHTML = `
    <div class="status-line">${badge(response.status, httpText(response.status))}<span class="big">${esc(title)}</span></div>
    ${data.id ? `<div>reservation_id <b>${esc(data.id)}</b>${replayedHtml}</div>` : ""}
    ${data.code ? `<div><b>${esc(data.code)}</b></div>` : ""}${extraHtml}
    <div class="small muted">${esc(response.cid)}</div>`;
  if (data.id) $("#a-rid").textContent = data.id;
}

// Prvý nákup: nový Idempotency-Key
async function aCreate() {
  const before = await seatState();
  A.last = { body: { event_id: "42", seat_id: "A7", buyer_id: "buyer-anna" }, key: "demo-" + randomId() };
  const response = await createReservation(A.last.body, A.last.key);
  const after = await seatState();

  renderA("Vytvorené", response);
  renderSeat(after);
  log("A", {
    status: response.status, label: `Vytvoriť (key ${A.last.key})`, cid: response.cid,
    before: SEAT_LABEL[before.seat.status], after: SEAT_LABEL[after.seat.status],
  });
}

// Retry: presne ten istý request aj kľúč → server vráti pôvodnú odpoveď, počet v DB sa nezmení
async function aRetry() {
  if (!A.last) await aCreate();
  const before = await seatState();
  const response = await createReservation(A.last.body, A.last.key);
  const after = await seatState();

  renderA("Retry: žiadny nový nákup", response,
    `<div>rezervácie v DB: <b>${before.active_count} → ${after.active_count}</b></div>`);
  renderSeat(after);
  log("A", {
    status: response.status, label: `Retry (key ${A.last.key}) → ${response.json?.id ?? response.json?.code}`, cid: response.cid,
    before: `${before.active_count} rez.`, after: `${after.active_count} rez.`,
  });
}

// Rovnaký kľúč, ale iný kupujúci → server to odmietne (kľúč nie je možné zneužiť)
async function aMismatch() {
  if (!A.last) await aCreate();
  const before = await seatState();
  const response = await createReservation({ ...A.last.body, buyer_id: "buyer-boris" }, A.last.key);
  const after = await seatState();

  renderA("Rovnaký kľúč, iný payload", response);
  renderSeat(after);
  log("A", {
    status: response.status, label: `Iný payload, key ${A.last.key}`, cid: response.cid,
    before: `${before.active_count} rez.`, after: `${after.active_count} rez.`,
  });
}

async function aReset() {
  const response = await api("POST", "/demo/reset");
  A.last = null;
  $("#a-rid").textContent = "—";
  const state = await seatState();

  renderSeat(state);
  $("#a-result").innerHTML =
    `<div class="status-line">${badge(response.status, httpText(response.status))}<span class="big">A7 je VOĽNÉ</span></div>`;
  log("A", { status: response.status, label: "Reset demo dát", cid: response.cid, after: SEAT_LABEL[state.seat.status] });
}

// Jedna dlaždica súbehu (víťaz má zvýraznený okraj)
function raceTile(buyerName, response) {
  return `
    <div class="tile ${response.status === 201 ? "accent" : ""}">
      <div class="label">${buyerName}</div>
      ${badge(response.status, httpText(response.status))}
      <div class="small" style="margin-top:8px">${esc(response.json?.id || response.json?.code || "")}</div>
      <div class="small muted">${esc(response.cid)} · ${response.ms} ms</div>
    </div>`;
}

function renderRace(anna, boris) {
  const winners = [anna, boris].filter((response) => response.status === 201).length;
  $("#a-result").innerHTML = `
    <div class="status-line"><span class="big">Súbeh: ${winners} víťaz</span></div>
    <div class="tiles">${raceTile("Kupujúci Anna", anna)}${raceTile("Kupujúci Boris", boris)}</div>
    <div class="small muted">Rozhodla PostgreSQL: unique index one_active_reservation_per_seat</div>`;
}

// Súbeh: Anna a Boris chcú to isté miesto v tom istom okamihu
// ── ukážka A2 ──
async function aRace() {
  // 1) čistý štart
  await aReset();
  const before = await seatState();

  // 2) dve nezávislé HTTP požiadavky naraz (každá s vlastným kľúčom) — rozhodne databáza
  const buy = (buyer) => createReservation(
    { event_id: "42", seat_id: "A7", buyer_id: buyer }, `race-${buyer}-${randomId()}`);
  const [anna, boris] = await Promise.all([buy("buyer-anna"), buy("buyer-boris")]);
// ── /ukážka A2 ──
  const after = await seatState();

  // 3) zobraz obe odpovede: jedna 201, druhá 409
  renderRace(anna, boris);
  renderSeat(after);
  const winner = anna.status === 201 ? anna : boris;
  if (winner.json?.id) $("#a-rid").textContent = winner.json.id;

  // 4) log
  log("A", { status: anna.status, label: "Súbeh — Anna", cid: anna.cid });
  log("A", {
    status: boris.status, label: "Súbeh — Boris", cid: boris.cid,
    before: `${before.active_count} rez.`, after: `${after.active_count} rez.`,
  });
}

/* =====================================================================
   DEMO B — SOAP & gRPC
   SOAP: formálny kontrakt (WSDL) a Fault. gRPC: deadline naozaj zruší volanie.
   ===================================================================== */
const B = { soapBytes: null, grpcBytes: null };   // veľkosti správ pre porovnanie bajtov

// Zvýrazní slovo v (už escapovanom) XML
function highlight(xml, word) {
  return esc(xml).replaceAll(esc(word), `<mark>${esc(word)}</mark>`);
}

function setSoapPanes(leftTitle, leftHtml, rightTitle, rightHtml) {
  $("#b-left-title").textContent = leftTitle;
  $("#b-right-title").textContent = rightTitle;
  $("#b-left").innerHTML = leftHtml;
  $("#b-right").innerHTML = rightHtml;
}

// WSDL: vľavo len výrez s operáciou CheckSeat, vpravo celý dokument
async function bWsdl() {
  const response = await api("GET", "/soap?wsdl", { raw: true });
  const wsdl = response.text;
  const operationStart = wsdl.indexOf("<wsdl:portType");
  const operationEnd = wsdl.indexOf("</wsdl:binding>") + "</wsdl:binding>".length;

  setSoapPanes(
    "WSDL (výrez — operácia)", highlight(wsdl.slice(operationStart, operationEnd), "CheckSeat"),
    "WSDL (celé)", highlight(wsdl, "CheckSeat"));
  $("#b-soap-result").innerHTML = `
    <div class="status-line">${badge(response.status, httpText(response.status))}<span class="big">WSDL obsahuje operáciu CheckSeat</span></div>
    <div class="small muted">${esc(response.cid)}</div>`;
  log("B", { status: response.status, label: "SOAP: GET /soap?wsdl", cid: response.cid });
}

// SOAP volanie CheckSeat; s invalid=true server vráti SOAP Fault (HTTP 500)
async function bSoap(invalid) {
  // 1) server zavolá SOAP službu a vráti nám request aj response XML
  const response = await api("GET", `/demo/rpc/soap?seat=A7${invalid ? "&invalid=true" : ""}`);
  const call = response.json;

  // 2) obe XML vedľa seba
  setSoapPanes(
    "Request XML", highlight(call.request_xml, "CheckSeat"),
    call.is_fault ? "Response XML — SOAP Fault" : "Response XML",
    highlight(call.response_xml, call.is_fault ? "Fault" : "available"));

  // 3) vytiahni výsledok z XML odpovede
  const available = /<tns:available>(\w+)<\/tns:available>/.exec(call.response_xml)?.[1];
  const faultString = /<faultstring>([^<]*)<\/faultstring>/.exec(call.response_xml)?.[1];
  $("#b-soap-result").innerHTML = `
    <div class="status-line">
      ${badge(call.http_status, call.is_fault ? "SOAP Fault (HTTP 500)" : "HTTP 200")}
      <span class="big">${call.is_fault ? esc(faultString) : `available = ${esc(available)}`}</span>
    </div>
    <div class="small muted">body ${call.request_body_bytes} B → ${call.response_body_bytes} B · ${esc(call.correlation_id)}</div>`;

  // 4) veľkosť platnej správy si zapamätáme na porovnanie s gRPC
  if (!invalid) { B.soapBytes = call; renderBytes(); }
  log("B", {
    status: call.http_status,
    label: invalid ? "SOAP: neplatný request → Fault" : `SOAP CheckSeat → available=${available}`,
    cid: call.correlation_id,
  });
}

function grpcUrl(delayMs, deadlineMs) {
  return `/demo/rpc/grpc?seat=A7&delay_ms=${delayMs}${deadlineMs ? `&deadline_ms=${deadlineMs}` : ""}`;
}

function renderGrpcResult(call, deadlineMs) {
  const answer = call.ok ? `available = ${call.reply.available} (${esc(call.reply.status)})` : esc(call.details);
  const serverTime = call.ok ? ` · server ${call.reply.server_elapsed_ms} ms` : "";
  $("#b-grpc-result").innerHTML = `
    <div class="status-line">
      ${badge(call.ok ? 200 : 500, call.code)}
      <span class="big">${answer}</span>
    </div>
    <div>deadline <b>${deadlineMs ? deadlineMs + " ms" : "—"}</b> · klient čakal <b>${call.client_elapsed_ms} ms</b>${serverTime}</div>
    <div class="small muted">${esc(call.correlation_id)}</div>`;
}

// gRPC CheckSeat: server umelo spomalíme (delay) a klientovi dáme deadline
async function bGrpc(delayMs, deadlineMs) {
  // 1) volanie cez backend (gRPC klient beží na serveri)
  const response = await api("GET", grpcUrl(delayMs, deadlineMs));
  const call = response.json;

  // 2) výsledok + časová os „server pracuje vs. klient čaká“
  renderGrpcResult(call, deadlineMs);
  renderTimeline(delayMs, deadlineMs, call);

  // 3) bajty berieme len z rýchleho úspešného volania
  if (call.ok && !delayMs) { B.grpcBytes = call; renderBytes(); }
  log("B", {
    status: call.ok ? 200 : 504,
    label: `gRPC CheckSeat delay=${delayMs} deadline=${deadlineMs ?? "—"} → ${call.code}`,
    cid: call.correlation_id,
  });
}

// Časová os: horný pruh = práca servera, dolný = čakanie klienta, čiarkovaná čiara = deadline
function renderTimeline(delayMs, deadlineMs, call) {
  const scaleMs = Math.max(delayMs, deadlineMs || 0, call.client_elapsed_ms, 100) * 1.15;
  const pct = (ms) => Math.min(100, (ms / scaleMs) * 100).toFixed(1) + "%";
  const serverWorkMs = call.reply?.server_elapsed_ms || delayMs;   // ak server nestihol odpovedať, ukážeme zadaný delay

  const deadlineLine = deadlineMs
    ? `<div class="deadline" style="left:${pct(deadlineMs)}"><span>deadline ${deadlineMs} ms</span></div>`
    : "";
  const verdict = call.ok
    ? "Stihlo sa pred deadline."
    : "Klient prestal čakať pri deadline, gRPC zrušil prácu aj na serveri.";

  $("#b-timeline").innerHTML = `
    <div class="timeline">
      <span class="tlabel tl-srv">Server: umelá práca ~${Math.round(serverWorkMs)} ms</span>
      <div class="track srv">
        <div class="bar srv" style="width:${pct(Math.max(serverWorkMs, 2))}"></div>
      </div>
      <span class="tlabel tl-cli">Klient: ${call.client_elapsed_ms} ms → ${esc(call.code)}</span>
      <div class="track cli">
        <div class="bar cli ${call.ok ? "" : "err"}" style="width:${pct(call.client_elapsed_ms)}"></div>
      </div>
      ${deadlineLine}
    </div>
    <p class="small" style="margin-top:8px">${verdict}</p>`;
}

// SOAP XML vs. protobuf — len pre tieto konkrétne správy
function renderBytes() {
  const soap = B.soapBytes;
  const grpc = B.grpcBytes;
  const soapSizes = soap ? `${soap.request_body_bytes} / ${soap.response_body_bytes} B` : "—";
  const grpcSizes = grpc ? `${grpc.request_protobuf_bytes} / ${grpc.response_protobuf_bytes} B` : "—";
  $("#b-bytes").innerHTML = `
    SOAP XML body: <b>${soapSizes}</b> ·
    gRPC protobuf: <b>${grpcSizes}</b>
    <div class="muted">request / response, bez hlavičiek. Platí len pre tieto správy, nie je to benchmark.</div>`;
}

/* =====================================================================
   DEMO C — GraphQL
   Prehliadač posiela iba TEXT query. SQL robí výhradne server.
   ===================================================================== */
const DEMO_QUERY = '{ event(id: "42") { seats(limit: 100) { id price { amount currency } } } }';
const lastResult = { naive: null, batch: null };      // na porovnanie JSON-u

// 1) Pošli query na server: POST /graphql (batching) alebo /graphql/naive
// ── ukážka C1 ──
async function sendGraphQL(mode, query, headers = {}) {
  const url = mode === "naive" ? "/graphql/naive" : "/graphql";
  const response = await api("POST", url, { body: { query }, headers });
  return { ...response.json, correlationId: response.cid };
}
// ── /ukážka C1 ──

// 2) Tlačidlá „Naivný resolver“ / „Batching“
async function cRun(mode, query = DEMO_QUERY, headers = {}) {
  const result = await sendGraphQL(mode, query, headers);
  const sql = result.extensions.sql;           // skutočné SQL príkazy, ktoré server poslal do DB

  if (query === DEMO_QUERY && !result.errors) {
    lastResult[mode] = result;
    $(`#c-${mode}-count`).textContent = sql.count;                       // veľké číslo 101 / 2
    $(`#c-${mode}-ms`).textContent = `${result.extensions.durationMs} ms (orientačne)`;
    $(`#c-${mode}-log`).textContent = sqlPreview(sql.statements);        // výpis SQL logu
  }

  const name = mode === "naive" ? "Naivne" : "Batching";
  const error = result.errors ? ` · ${result.errors[0].message}` : "";
  log("C", { status: result.errors ? 400 : 200, label: `${name}: ${sql.count} SQL${error}`, cid: result.correlationId });
  return result;
}

// 3) Rovnaký JSON? Porovnáme odpovede oboch režimov
function cSame() {
  const { naive, batch } = lastResult;
  if (naive && batch) {
    const same = JSON.stringify(naive.data) === JSON.stringify(batch.data);
    $("#c-same").innerHTML = same ? '<span class="badge ok">ÁNO</span>' : '<span class="badge err">NIE</span>';
  }
  $("#c-result").hidden = true;
}

// 4) Ukážky ochrany: príliš veľký limit, pole bez oprávnenia
async function cError(kind) {
  const query = kind === "limit"
    ? '{ event(id: "42") { seats(limit: 500) { id } } }'
    : '{ event(id: "42") { seats(limit: 1) { id price { internalCost } } } }';
  $("#c-query").textContent = query;

  const result = await cRun("batch", query);
  const message = result.errors?.[0]?.message || "bez chyby";
  $("#c-result").hidden = false;
  $("#c-result").innerHTML = `
    <div class="status-line">${badge(400, "Zamietnuté")}<span class="big">${esc(message)}</span></div>
    <div class="small muted">SQL dotazov: ${result.extensions.sql.count}</div>`;
}

// Tlačidlá naivne / batching vždy pracujú s ukážkovou query
function showDemoQuery() {
  $("#c-query").textContent = DEMO_QUERY;
}

// SQL log čitateľne: dosadí hodnoty parametrov a skráti dlhý IN (…) zoznam
function renderSql(statement) {
  const values = statement.params || {};
  let sql = statement.sql.replace(/%\((\w+)\)s/g, (_, key) =>
    typeof values[key] === "number" ? values[key] : `'${values[key] ?? "…"}'`);
  sql = sql.replace(/IN \(([^)]*)\)/, (match, inner) => {
    const items = inner.split(", ");
    return items.length > 4 ? `IN (${items.slice(0, 3).join(", ")}, … ${items.length} hodnôt)` : match;
  });
  return sql.replace(/SELECT seat_id, [a-z_, ]+? FROM/, "SELECT … FROM");
}

function sqlPreview(statements) {
  const lines = statements.slice(0, 3).map((statement, i) => `${i + 1}. ${renderSql(statement)}`);
  if (statements.length > 3) lines.push(`… +${statements.length - 3} ďalších`);
  return lines.join("\n") + `\n\n= ${statements.length} SQL`;
}

/* =====================================================================
   DEMO D — Webhook & WebSocket
   Provider pošle podpísaný webhook → DB zmení stav → server to pushne cez WebSocket
   všetkým pripojeným klientom. Po (opätovnom) pripojení si klient stiahne snapshot.
   ===================================================================== */
const D = { rid: params.get("rid") || null, clients: {} };

function wsUrl(clientName) {
  const scheme = location.protocol === "https:" ? "wss" : "ws";
  return `${scheme}://${location.host}/ws?client=${encodeURIComponent(clientName)}`;
}

/* ---------- WebSocket klient (karta „Klient A / B“) ---------- */
function clientCardHtml(name) {
  return `
    <header>
      <b>Klient ${esc(name)}</b>
      <button class="btn ghost" style="padding:6px 12px;font-size:.85rem">Odpojiť</button>
    </header>
    <div class="small"><span class="conn">ODPOJENÝ</span> · rezervácia <b class="rid">—</b></div>
    <div class="rstatus">—</div>
    <div class="note"></div>`;
}

function makeClient(name) {
  // 1) karta klienta v DOM
  const el = document.createElement("div");
  el.className = "client";
  el.innerHTML = clientCardHtml(name);
  $("#d-clients").append(el);

  // 2) tlačidlo Odpojiť / Pripojiť — ukážka, že odpojený klient správy nedostáva
  const client = { name, el, ws: null, wantConnected: true };
  el.querySelector("button").addEventListener("click", () => toggleConnection(client));

  // 3) zaregistruj a pripoj
  D.clients[name] = client;
  connect(client);
}

function toggleConnection(client) {
  const isOpenOrConnecting = client.ws && client.ws.readyState <= 1;
  if (isOpenOrConnecting) {
    client.wantConnected = false;
    client.ws.close();
  } else {
    client.wantConnected = true;
    connect(client);
  }
}

// Aktualizuje veľký stav, poznámku s časom a reservation_id na karte klienta
function setClient(client, status, note) {
  if (status) client.el.querySelector(".rstatus").textContent = status;
  if (note) client.el.querySelector(".note").textContent = `${timeNow()} — ${note}`;
  client.el.querySelector(".rid").textContent = D.rid || "—";
}

function setConnectedUi(client, connected) {
  client.el.classList.toggle("connected", connected);
  client.el.querySelector(".conn").textContent = connected ? "PRIPOJENÝ" : "ODPOJENÝ";
  client.el.querySelector("header button").textContent = connected ? "Odpojiť" : "Pripojiť";
}

// Snapshot po pripojení: WebSocket nedoručí, čo sa stalo počas výpadku → stav si dotiahneme cez REST
// ── ukážka D11 ──
async function snapshot(client, reason) {
  if (!D.rid) {
    const state = await seatState();
    D.rid = state?.active_reservations?.[0]?.id || null;
  }
  if (!D.rid) {
    setClient(client, "—", `${reason}: žiadna aktívna rezervácia`);
    return;
  }
  const response = await api("GET", `/reservations/${D.rid}`);
  setClient(client, response.json?.status || "?", `${reason} → snapshot GET /reservations/${D.rid}`);
  log("D", { status: response.status, label: `Klient ${client.name}: snapshot po pripojení → ${response.json?.status}`, cid: response.cid });
}
// ── /ukážka D11 ──

// Správy, ktoré server pushuje cez WebSocket
function handleMessage(client, message) {
  if (message.type === "reservation.created" || message.type === "reservation.confirmed") {
    if (message.reservation.seat_id === "A7") D.rid = message.reservation.id;
    setClient(client, message.reservation.status, `WebSocket: ${message.type}`);
  } else if (message.type === "demo.reset") {
    D.rid = null;
    setClient(client, "—", "WebSocket: demo.reset");
  }
  // ostatné typy (napr. hello) iba ignorujeme
}

// ── ukážka D10 ──
function connect(client) {
  const ws = new WebSocket(wsUrl(client.name));
  client.ws = ws;

  ws.onopen = () => {
    setConnectedUi(client, true);
    snapshot(client, "Pripojený");
  };
  ws.onmessage = (event) => handleMessage(client, JSON.parse(event.data));
  ws.onclose = () => {
    setConnectedUi(client, false);
    setClient(client, null, client.wantConnected ? "Spojenie stratené" : "Odpojený — správy nedostáva");
  };
}
// ── /ukážka D10 ──

/* ---------- Webhook: čo provider poslal a čo príjemca odpovedal ---------- */
const RECEIVER_FIELDS = ["result", "outcome", "code", "event_id", "status_before", "status_after", "detail"];

// Ľavý panel: HTTP request od providera (podpis skrátený, telo naformátované)
function formatSentRequest(sent, fallbackText) {
  if (!sent) return fallbackText;
  const signature = sent.headers?.["TicketFlow-Signature"];
  const signatureText = signature ? signature.slice(0, 32) + "…" : "(chýba)";
  return `POST /webhooks/payment\nTicketFlow-Signature: ${signatureText}\n\n` +
    JSON.stringify(JSON.parse(sent.raw_body), null, 1);
}

// Pravý panel: odpoveď príjemcu, len zaujímavé polia
function formatReceiverReply(received) {
  const fields = Object.entries(received.body || {}).filter(([key]) => RECEIVER_FIELDS.includes(key));
  return `HTTP ${received.status}\n\n` + JSON.stringify(Object.fromEntries(fields), null, 1);
}

// Ľudská veta k výsledku: spracované / duplicita / zlý podpis / bez podpisu
function webhookOutcome(body) {
  if (body.result === "DUPLICATE_IGNORED") return "Duplicita — prijatá bezpečne, bez zmeny";
  if (body.result === "PROCESSED") return `Spracované: ${body.outcome}`;
  if (body.code === "INVALID_SIGNATURE") return "Zlý podpis — odmietnuté, DB bez zmeny";
  if (body.code === "MISSING_SIGNATURE") return "Bez podpisu — odmietnuté";
  return body.code || body.detail || "—";
}

function renderWebhook(title, response) {
  const data = response.json || {};
  const received = data.received || {};
  const body = received.body || {};
  const status = received.status ?? response.status;

  // 1) request a odpoveď vedľa seba
  $("#d-sent").textContent = formatSentRequest(data.sent, response.text);
  $("#d-recv").textContent = formatReceiverReply(received);

  // 2) zmena stavu v DB a počet doručení cez WebSocket
  const stateChange = body.status_before
    ? ` · stav <b>${esc(body.status_before)} → ${esc(body.status_after)}</b>`
    : "";
  const deliveries = body.websocket_deliveries != null
    ? ` · WebSocket doručenia: <b>${body.websocket_deliveries}</b>`
    : "";

  // 3) výsledková karta
  $("#d-result").innerHTML = `
    <div class="status-line">${badge(status, httpText(status))}<span class="big">${esc(webhookOutcome(body))}</span></div>
    <div>${esc(title)}${stateChange}${deliveries}</div>
    <div class="small muted">${esc(data.correlation_id || response.cid)}</div>`;
}

// Aktuálny stav rezervácie cez REST (alebo undefined, ak žiadna nie je)
async function reservationStatus(reservationId) {
  if (!reservationId) return undefined;
  const response = await api("GET", `/reservations/${reservationId}`);
  return response.json?.status;
}

// Čistý štart: reset + nová PENDING rezervácia
async function dCreate() {
  await api("POST", "/demo/reset");
  const response = await createReservation(
    { event_id: "42", seat_id: "A7", buyer_id: "buyer-demo-d" }, "d-" + randomId());
  D.rid = response.json?.id || null;
  Object.values(D.clients).forEach((client) => setClient(client));

  $("#d-result").innerHTML = `
    <div class="status-line">${badge(response.status, httpText(response.status))}<span class="big">${esc(D.rid)} je PENDING</span></div>
    <div class="small muted">${esc(response.cid)}</div>`;
  log("D", { status: response.status, label: `Vytvorená rezervácia ${D.rid}`, cid: response.cid, before: "VOĽNÉ", after: "PENDING" });
}

// Požiada simulovaného providera o webhook (platný / replay / zlý podpis / bez podpisu)
async function dAction(action, title) {
  // 1) bez rezervácie nie je čo zaplatiť (replay posiela už odoslaný event)
  if (!D.rid && action !== "replay") await dCreate();

  // 2) stav pred → webhook → stav po
  const before = await reservationStatus(D.rid);
  const response = await api("POST", `/demo/provider/${action}`, { body: { reservation_id: D.rid } });
  const after = await reservationStatus(D.rid);

  // 3) zobraz a zaloguj
  renderWebhook(title, response);
  log("D", {
    status: response.json?.received?.status ?? response.status, label: title,
    cid: response.json?.correlation_id || response.cid, before, after,
  });
}

/* =====================================================================
   TLAČIDLÁ — data-action v index.html → funkcia
   ===================================================================== */
const ACTIONS = {
  // A — REST
  "a-create": aCreate,
  "a-retry": aRetry,
  "a-mismatch": aMismatch,
  "a-race": aRace,
  "a-reset": aReset,

  // B — SOAP & gRPC  (gRPC: delay servera, deadline klienta)
  "b-wsdl": bWsdl,
  "b-soap": () => bSoap(false),
  "b-soap-fault": () => bSoap(true),
  "b-grpc": () => bGrpc(0, null),
  "b-grpc-slow": () => bGrpc(800, 200),
  "b-grpc-ok-slow": () => bGrpc(100, 2000),

  // C — GraphQL
  "c-naive": async () => { showDemoQuery(); await cRun("naive"); cSame(); },
  "c-batch": async () => { showDemoQuery(); await cRun("batch"); cSame(); },
  "c-compare": async () => { showDemoQuery(); await cRun("naive"); await cRun("batch"); cSame(); },
  "c-limit": () => cError("limit"),
  "c-priv": () => cError("priv"),

  // D — Webhook & WebSocket
  "d-create": dCreate,
  "d-pay": () => dAction("payment", "Odoslať platbu (platný podpis)"),
  "d-replay": () => dAction("replay", "Zopakovať webhook (rovnaké event id)"),
  "d-bad": () => dAction("bad-signature", "Pokaziť podpis"),
  "d-unsigned": () => dAction("unsigned", "Bez podpisu"),
};

document.querySelectorAll("[data-action]").forEach((button) =>
  button.addEventListener("click", () => busy(button, () => ACTIONS[button.dataset.action]())));

document.querySelectorAll("nav.tabs button").forEach((button) =>
  button.addEventListener("click", () => selectTab(button.dataset.tab)));

document.querySelectorAll(".subtabs button").forEach((button) =>
  button.addEventListener("click", () => selectSubtab(button)));

/* =====================================================================
   ŠTART + AUTORUN
   ?autorun=1 prehrá scenár danej karty (screenshoty a nácvik), na konci title = AUTORUN_DONE
   ===================================================================== */
const AUTORUN_PLANS = {
  A: ["a-reset", "a-create", "a-retry", "a-race"],
  B: params.get("sub") === "grpc" ? ["a-reset", "b-grpc", "b-grpc-slow"] : ["a-reset", "b-soap"],
  C: ["a-reset", "c-naive", "c-batch"],
  D: ["d-create", "d-bad", "d-pay", "d-replay"],
};

async function autorun(tab) {
  if (tab === "B" && params.get("sub") === "grpc") document.querySelector('.subtabs [data-sub="grpc"]').click();
  await wait(500);
  for (const actionId of AUTORUN_PLANS[tab]) {
    await ACTIONS[actionId]();
    await wait(150);
  }
  document.title = "AUTORUN_DONE";
}

(async function init() {
  // 1) karta z URL, health čipy (každých 10 s), počiatočný stav miesta A7
  selectTab(params.get("tab") || "A");
  refreshHealth();
  setInterval(refreshHealth, 10000);
  renderSeat(await seatState());

  // 2) Demo B: .proto kontrakt a prázdne porovnanie bajtov
  api("GET", "/demo/contracts/proto", { raw: true }).then((response) => ($("#b-proto").textContent = response.text));
  renderBytes();

  // 3) Demo D: dvaja WebSocket klienti, alebo jeden v „druhom okne“ (?solo=C)
  const solo = params.get("solo");
  if (solo) {
    makeClient(solo);
    $("#d-open-second").style.display = "none";
  } else {
    makeClient("A");
    makeClient("B");
  }

  // 4) voliteľne prehraj scenár
  if (params.get("autorun")) await autorun(params.get("tab") || "A");
})();
