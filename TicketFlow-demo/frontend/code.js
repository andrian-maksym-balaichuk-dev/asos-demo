/* Stránka /code — prechod skutočným kódom dema krok po kroku.
   Kód sa načíta živo z /demo/code (označené časti zdrojových súborov). */
"use strict";

const $ = (selector) => document.querySelector(selector);
const ESCAPES = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (ch) => ESCAPES[ch]);

/* ═══ 1. Kroky každého dema: kto, čo a prečo ═══ */
const STEPS = {
  A: [
    { who: "Prehliadač", code: ["A1"], title: "Klient pošle POST s Idempotency-Key",
      text: "Každý nákup má vlastný kľúč. Keď klient po timeoute request zopakuje, pošle ten istý kľúč." },
    { who: "Prehliadač", code: ["A2"], title: "Súbeh: dvaja kupujúci naraz",
      text: "Dve nezávislé požiadavky s rôznymi kľúčmi odídu súčasne (Promise.all). Kľúč tu nepomôže — sú to dva rôzne nákupy." },
    { who: "Server", code: ["A3"], title: "Endpoint POST /reservations",
      text: "Celý tok v jednej transakcii: zaber kľúč → vlož rezerváciu → ulož odpoveď → commit. Notifikácia ide až po commite." },
    { who: "Server", code: ["A4"], title: "Kľúč už existuje → replay alebo 422",
      text: "Rovnaký payload: vrátime uložené bajty pôvodnej odpovede, nový nákup nevznikne. Iný payload s tým istým kľúčom: 422." },
    { who: "Databáza", code: ["A5"], title: "Súbeh rozhodne unique index",
      text: "Najviac jedna aktívna rezervácia na sedadlo. Toto je celá ochrana pred súbehom — v Pythone nie je žiadny lock." },
    { who: "Server", code: ["A6"], title: "Chyba z databázy → 409 / 404",
      text: "Porušenie indexu preložíme na 409 SEAT_TAKEN. Neexistujúce sedadlo (foreign key) na 404." },
  ],
  B: [
    { who: "Kontrakt", code: ["B1"], title: "SOAP kontrakt: WSDL",
      text: "Operácia CheckSeat: čo príde dnu, čo ide von a že sa posiela ako SOAP cez HTTP. Z WSDL sa dá vygenerovať klient." },
    { who: "Server", code: ["B2"], title: "SOAP endpoint",
      text: "Bezpečne načíta XML (bez XXE), skontroluje obálku, vytiahne eventId a seatId. Odpovie XML obálkou alebo SOAP Fault." },
    { who: "Kontrakt", code: ["B3"], title: "gRPC kontrakt: .proto",
      text: "Tá istá otázka ako binárny protobuf. Z tohto súboru sa generuje kód klienta aj servera. Čísla polí sú súčasťou kontraktu." },
    { who: "Klient", code: ["B4"], title: "gRPC volanie s deadline",
      text: "timeout= je deadline klienta. Keď vyprší skôr než odpoveď, klient dostane DEADLINE_EXCEEDED a prestane čakať." },
    { who: "Server", code: ["B5"], title: "gRPC server a zrušenie práce",
      text: "Server umelo čaká (len demo). Keď klientovi vyprší deadline, gRPC zruší aj prácu servera — vznikne CancelledError." },
  ],
  C: [
    { who: "Schéma", code: ["C0"], title: "Najprv mapa: schéma, query a tok requestu",
      text: "Python triedy sa stanú GraphQL typmi. Každé pole v query naplní resolver — tu vidno, ktorý resolver robí koľko SQL dotazov a kadiaľ ide request." },
    { who: "Prehliadač", code: ["C1"], title: "Klient pošle iba text query",
      text: "Jeden POST /graphql. Prehliadač nemá SQL ani prístup k databáze — len opíše, aké polia chce." },
    { who: "Server", code: ["C2"], title: "Endpoint: nové spojenie a nový DataLoader na request",
      text: "Každý request má vlastné DB spojenie (na ňom počítame SQL) a vlastný DataLoader, takže cache neuniká medzi používateľmi." },
    { who: "Server", code: ["C3"], title: "Resolver price — tu je celý rozdiel",
      text: "Tento resolver sa zavolá pre každé zo 100 sedadiel. Podľa režimu ide naivne, alebo cez DataLoader." },
    { who: "Server", code: ["C4"], title: "Naivne vs. batching",
      text: "Naivne: každé sedadlo vlastný SQL dotaz → 100 dotazov. Batching: iba zapíše kľúč, SQL pobeží raz pre všetky." },
    { who: "Server", code: ["C5"], title: "DataLoader: jeden SQL pre všetky kľúče",
      text: "Dostane naraz všetkých 100 kľúčov, urobí jeden dotaz WHERE seat_id IN (…) a vráti výsledky v rovnakom poradí." },
    { who: "Databáza", code: ["C6", "C7"], title: "Ako počítame SQL dotazy",
      text: "Hook before_cursor_execute zapíše každý príkaz, ktorý naozaj odíde do PostgreSQL. Odtiaľ je 101 a 2 — nie je to napísané ručne." },
  ],
  D: [
    { who: "Provider", code: ["D1"], title: "Podpis: HMAC nad timestamp + raw body",
      text: "Podpisujú sa presné bajty tela spolu s časom. Zmena jediného bajtu alebo času podpis zneplatní." },
    { who: "Provider", code: ["D2", "D3"], title: "Provider pošle udalosť o platbe",
      text: "Vytvorí udalosť payment.succeeded, podpíše raw body a pošle POST na náš server s hlavičkou TicketFlow-Signature." },
    { who: "Server", code: ["D4"], title: "Príjemca: najprv overí podpis",
      text: "Podpis sa overí nad raw bajtmi skôr, než sa dotkneme JSONu alebo databázy. Zlý podpis → 400/401 a DB sa nezmení." },
    { who: "Server", code: ["D5"], title: "Overenie: čerstvosť a konštantné porovnanie",
      text: "Starý timestamp = možný replay. compare_digest porovnáva v konštantnom čase, takže čas odpovede nič neprezradí." },
    { who: "Databáza", code: ["D6", "D7"], title: "Dedupe a potvrdenie v jednej transakcii",
      text: "event_id je primárny kľúč. Druhé doručenie tej istej udalosti nič nevloží → duplicita, stav sa nezmení. Inak PENDING → CONFIRMED." },
    { who: "Server", code: ["D8", "D9"], title: "Po commite: push cez WebSocket",
      text: "Až keď je zmena v databáze, pošle sa všetkým pripojeným klientom. Odpojený klient správu jednoducho nedostane." },
    { who: "Prehliadač", code: ["D10", "D11"], title: "Klient pri pripojení načíta snapshot",
      text: "Po každom (re)connecte si klient stav načíta cez GET /reservations/{id}. Zdrojom pravdy je databáza, nie push správa." },
  ],
};

/* ═══ 2. Stav stránky ═══ */
const state = { tab: "A", step: 0, snippets: {} };

/* ═══ 3. Vykreslenie ═══ */
function renderStepList() {
  $("#step-list").innerHTML = STEPS[state.tab].map((step, index) => `
    <li class="${index === state.step ? "active" : ""}" data-index="${index}">
      <span class="num">${index + 1}</span>
      <span><span class="who">${esc(step.who)}</span>${esc(step.title)}</span>
    </li>`).join("");
  document.querySelectorAll("#step-list li").forEach((item) =>
    item.addEventListener("click", () => goTo(Number(item.dataset.index))));
}

function renderStep() {
  const steps = STEPS[state.tab];
  const step = steps[state.step];
  $("#step-side").textContent = step.who;
  $("#step-counter").textContent = `krok ${state.step + 1} / ${steps.length}`;
  $("#step-title").textContent = step.title;
  $("#step-text").textContent = step.text;
  $("#step-code").innerHTML = step.code.map(renderSnippet).join("");
  $("#prev").disabled = state.step === 0;
  $("#next").textContent = state.step === steps.length - 1 ? "Ďalšie demo ▶" : "Ďalej ▶";
  $("#next").disabled = state.step === steps.length - 1 && state.tab === "D";
}

function renderSnippet(id) {
  const snippet = state.snippets[id];
  if (!snippet) return `<div class="snippet"><pre>Ukážka ${esc(id)} sa nenašla.</pre></div>`;
  const lines = highlight(snippet.code, snippet.language).split("\n");
  const numbered = lines.map((line, i) => `<span class="ln">${snippet.line_start + i}</span>${line}`).join("\n");
  return `<div class="snippet">
    <span class="file">${esc(snippet.file)} : ${snippet.line_start}–${snippet.line_end}</span>
    <pre>${numbered}</pre>
  </div>`;
}

/* ═══ 4. Navigácia ═══ */
function goTo(index) {
  state.step = Math.max(0, Math.min(index, STEPS[state.tab].length - 1));
  renderStepList();
  renderStep();
  history.replaceState(null, "", `?tab=${state.tab}&step=${state.step + 1}`);
}

function selectTab(tab, step = 0) {
  state.tab = tab;
  $("#code-page").dataset.demo = tab;
  document.querySelectorAll("nav.tabs button").forEach((button) =>
    button.setAttribute("aria-selected", String(button.dataset.tab === tab)));
  goTo(step);
}

function next() {
  const tabs = Object.keys(STEPS);
  if (state.step < STEPS[state.tab].length - 1) goTo(state.step + 1);
  else if (state.tab !== "D") selectTab(tabs[tabs.indexOf(state.tab) + 1]);
}

/* ═══ 5. Jednoduché zvýraznenie syntaxe (offline, bez knižníc) ═══ */
const KEYWORDS = {
  python: "async await def return if elif else for in not and or is None True False try except raise with as import from class global pass",
  javascript: "async await function return if else const let new for of typeof null true false",
  proto: "syntax package service rpc returns message string uint32 bool",
  xml: "",
  text: "",
};
const PATTERNS = {
  python: /(#[^\n]*)|("""[\s\S]*?"""|f?"(?:\\.|[^"\\\n])*"|'(?:\\.|[^'\\\n])*')|\b(\d+)\b|\b([A-Za-z_]\w*)\b/g,
  javascript: /(\/\/[^\n]*)|(`(?:\\.|[^`\\])*`|"(?:\\.|[^"\\\n])*"|'(?:\\.|[^'\\\n])*')|\b(\d+)\b|\b([A-Za-z_]\w*)\b/g,
  proto: /(\/\/[^\n]*)|("(?:\\.|[^"\\\n])*")|\b(\d+)\b|\b([A-Za-z_]\w*)\b/g,
  xml: /(<!--[\s\S]*?-->)|("[^"\n]*")|((?!))|(<\/?[\w:]+|\/?>)/g,
  text: /((?!))((?!))((?!))((?!))/g,   // diagram: bez zvýraznenia
};

function highlight(code, language) {
  const keywords = new Set(KEYWORDS[language].split(" "));
  const pattern = PATTERNS[language];
  let html = "";
  let last = 0;
  for (const match of code.matchAll(pattern)) {
    html += esc(code.slice(last, match.index));
    const [token, comment, string, number, word] = match;
    if (comment) html += `<span class="tok-com">${esc(token)}</span>`;
    else if (string) html += `<span class="tok-str">${esc(token)}</span>`;
    else if (number) html += `<span class="tok-num">${esc(token)}</span>`;
    else if (language === "xml" && word) html += `<span class="tok-tag">${esc(token)}</span>`;
    else if (word && keywords.has(word)) html += `<span class="tok-kw">${esc(token)}</span>`;
    else html += esc(token);
    last = match.index + token.length;
  }
  return html + esc(code.slice(last));
}

/* ═══ 6. Štart ═══ */
document.querySelectorAll("nav.tabs button").forEach((button) =>
  button.addEventListener("click", () => selectTab(button.dataset.tab)));
$("#prev").addEventListener("click", () => goTo(state.step - 1));
$("#next").addEventListener("click", next);
document.addEventListener("keydown", (event) => {
  if (event.key === "ArrowRight") next();
  if (event.key === "ArrowLeft") goTo(state.step - 1);
});

(async function init() {
  const response = await fetch("/demo/code");
  state.snippets = await response.json();
  const params = new URLSearchParams(location.search);
  const tab = STEPS[params.get("tab")] ? params.get("tab") : "A";
  selectTab(tab, Number(params.get("step") || 1) - 1);
  document.title = "TicketFlow Kód";
})();
