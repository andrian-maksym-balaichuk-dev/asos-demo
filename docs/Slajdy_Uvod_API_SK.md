---
marp: true
paginate: true
style: |
  section { font-size: 22px; padding: 40px 56px; }
  h1 { margin-bottom: 6px; }
  ul { margin: 4px 0; }
  table { font-size: 0.78em; }
  th, td { padding: 4px 8px; vertical-align: top; }
---

<!--
Úvodné slajdy k technológiám — 1 slajd na začiatok každej sekcie.
Formát: Marp (každý slajd oddelený čiarou ---). Dá sa skopírovať aj do PowerPointu / Google Slides.
Na slajde je len krátka info. Viac povie prezentujúci (poznámky sú v komentároch pod slajdom).

Kam vložiť:
  REST        → na začiatok sekcie A (pred demo slajd 06)
  SOAP vs. gRPC (1 slajd)   → na začiatok sekcie B (pred demo slajd 12)
  GraphQL     → na začiatok sekcie C (pred demo slajd 18)
  Webhook + WebSocket (1 slajd) → na začiatok sekcie D (pred demo slajd 23)
-->

# REST

**Architektonický štýl pre API nad HTTP: zdroje majú URL a pracuje sa s nimi cez GET, POST, PUT, DELETE.**

**Vznik:** 2000, Roy Fielding (jeden z autorov HTTP), dizertačná práca na UC Irvine

**Ako to funguje:** `GET /events/42` prečíta koncert, `POST /reservations` vytvorí rezerváciu, výsledok povie HTTP status (200, 201, 404, 409)

**Prečo sa používa**
- jednoduché: funguje cez obyčajné HTTP, z prehliadača aj z každého jazyka
- dá sa cacheovať a ľahko ladiť (curl, prehliadač)
- kontrakt sa dá opísať v **OpenAPI** (Swagger) a vygenerovať z neho dokumentáciu aj klienta

**Kde ho stretneš:** GitHub, Stripe, Twilio, verejné API väčšiny webov a mobilných aplikácií
**Supabase / Firebase:** Supabase z každej tabuľky automaticky vytvorí REST API (PostgREST), Firebase Realtime Database má REST API

**Kedy nie:** keď obrazovka potrebuje veľa rôznych dát naraz (veľa requestov) alebo živé zmeny

<!--
Povedz: „REST nie je protokol ani knižnica, je to štýl. Zdroj = vec s adresou, napr. /events/42.
Dnes je to predvolená voľba pre verejné API, lebo ho zvládne každý klient.“
Pozor: OpenAPI je opis REST API, nie samostatný typ API.
-->

---

# SOAP vs. gRPC

**Dva formálne kontrakty na tú istú otázku: „je miesto A7 voľné?“**

| | **SOAP** | **gRPC** |
|---|---|---|
| Čo to je | výmena **XML správ** s kontraktom **WSDL** | volanie funkcií cez **Protocol Buffers** a **HTTP/2** |
| Vznik | 1998, Microsoft a partneri · W3C: SOAP 1.1 (2000), 1.2 (2003) | Google „Stubby“ (od ~2001) → open source 2015 · dnes CNCF |
| Ako to funguje | XML „obálka“ `<soap:Envelope>` → XML odpoveď alebo `SOAP Fault` | `.proto` → vygenerovaný kód; klient volá `CheckSeat()` ako funkciu s **deadline** |
| Prečo | presný kontrakt, WS-Security, integrácie na roky | typované, malé binárne správy, streaming, deadliny |
| Kde | banky, poisťovne, štát, Amadeus, Sabre, SAP, Salesforce, EÚ VIES | Google Cloud, Netflix, Square, Kubernetes, etcd · **Firestore** klient |
| Kedy nie | nové web/mobil projekty (veľké XML, zložité nástroje) | verejné API pre prehliadač (treba gRPC-Web + proxy) |

**Spoločné:** obidva majú kontrakt dopredu. **Rozdiel:** SOAP = stabilita medzi firmami, gRPC = rýchlosť medzi vlastnými službami.

<!--
Povedz: „SOAP je úradný list v obálke — ťažkopádny, ale banky a štát ho majú roky a nemenia ho.
gRPC je od Googlu: zavoláš funkciu na inom serveri, akoby bola tvoja, a povieš, ako dlho najviac čakáš — deadline.“
Pozor: nehovor „SOAP je mŕtvy“, „SOAP je vždy pomalý“ ani „gRPC je vždy rýchlejšie“.
Firebase ani Supabase SOAP neponúkajú; klientske knižnice Firestore používajú gRPC.
Prechod: → demo B (WSDL, potom gRPC deadline 200 ms)
-->

---

# GraphQL

**Dotazovací jazyk pre API: klient si v jednej query vyberie presne tie dáta, ktoré potrebuje.**

**Vznik:** 2012 vo Facebooku pre mobilnú aplikáciu (news feed), verejne od 2015, dnes GraphQL Foundation

**Ako to funguje:** jeden endpoint `POST /graphql`; server má **schému** (typy a polia), klient pošle query a dostane JSON presne v tvare query; každé pole naplní **resolver** na serveri

**Prečo sa používa**
- jedna query namiesto viacerých REST requestov (menej čakania na mobile)
- žiadne dáta navyše, nič nechýba — tvar odpovede určuje klient
- typovaná schéma, nástroje s automatickým dopĺňaním (GraphiQL, Apollo)

**Najznámejšie použitia a prečo práve GraphQL**

| Kto | Na čo | Prečo GraphQL |
|---|---|---|
| **Meta (Facebook)** | news feed v mobilných appkách | tu vznikol: jedna query namiesto desiatok volaní na pomalej mobilnej sieti |
| **GitHub** | verejné API v4 (od 2016) | prvé veľké verejné GraphQL API: vývojár si vyberie len polia, ktoré potrebuje |
| **Shopify** | Admin a Storefront API pre e-shopy | tisíce rôznych e-shopov a appiek, každá potrebuje iné dáta o produktoch |
| **Netflix** | jedno API nad mnohými službami (federácia) | frontend vidí jednu schému, za ňou sú desiatky mikroslužieb |
| **Airbnb, PayPal** | webové a mobilné aplikácie | rôzne obrazovky a zariadenia čerpajú z jedného API |

**Nástroje:** Apollo (najpoužívanejší klient a server), Hasura a Supabase (GraphQL automaticky nad databázou)

**Kedy nie:** jednoduché CRUD API, keď je dôležitá HTTP cache, alebo keď tím nezvládne batching a limity query

<!--
Povedz: „Facebook mal problém: mobilná aplikácia na pomalej sieti potrebovala veľa rôznych dát naraz.
GraphQL to rieši jednou query. Cenou je viac práce na serveri — to presne ukážeme v deme (101 vs 2 SQL).“
Spoločný dôvod popularity: VEĽA rôznych klientov (web, iOS, Android, partneri) nad JEDNÝMI dátami.
Každý klient si vyberie, čo potrebuje, a backend nemusí robiť nový endpoint pre každú obrazovku.
Nástroje: „Dnes nemusíte GraphQL server ani písať — Hasura alebo Supabase ho vytvoria nad databázou
(Firebase má podobné Data Connect). Ale problém N+1 a limity query riešiť treba stále.“
-->

---

# Webhook + WebSocket

**Ako sa výsledok platby dostane až na obrazovku:**
`platobná brána ──Webhook──► náš server ──► databáza ──WebSocket──► prehliadače`

| | **Webhook** | **WebSocket** |
|---|---|---|
| Čo to je | cudzí systém **zavolá náš server** (HTTP POST), keď sa niečo stane | **trvalé obojsmerné spojenie**, server pošle správu sám |
| Vznik | 2007, pojem zaviedol Jeff Lindsay („HTTP callback“) | 2011, štandard IETF RFC 6455 |
| Ako to funguje | zaregistrujeme URL; pri udalosti príde POST s JSON a **podpisom** | HTTP `Upgrade: websocket` → `101 Switching Protocols` → spojenie ostane otvorené |
| Prečo | netreba sa stále pýtať „už je zaplatené?“ (polling) | zmena je v prehliadači hneď, bez obnovovania stránky |
| Kde | Stripe, PayPal, GitHub (push → CI/CD), Slack, Shopify · **Supabase** Database Webhooks | Slack, Discord, burzy, online hry · **Supabase** Realtime, **Firebase** Realtime DB |
| Na čo pozor | overiť **podpis**, rátať s **duplicitami** | po výpadku správy neprídu → stav znova z **databázy** |

**Zapamätaj si:** webhook prinesie výsledok k nám, WebSocket ho pošle ďalej — zdrojom pravdy je databáza.

<!--
Povedz: „Platobná brána nám zazvoní — to je webhook. Kto zvoní? Overíme podpis. Zazvoní dvakrát? Deduplikácia.
Potom to chceme ukázať fanúšikovi hneď — WebSocket je telefonát, ktorý ostane otvorený.
Keď hovor spadne, zmeškané nikto nezopakuje, preto snapshot z databázy.“
Ukážka v reáli: Slack alebo Discord → DevTools → Network → filter WS.
Prechod: → demo D
-->

---

<!-- Voliteľný súhrnný slajd na koniec prezentácie -->

# Kedy čo použiť

| API | Najlepšie na | Typický príklad | Supabase / Firebase |
|---|---|---|---|
| **REST** | verejné API, jednoduché zdroje | GitHub, Stripe | Supabase REST (PostgREST) |
| **SOAP** | existujúce B2B kontrakty | banky, SAP | — |
| **gRPC** | rýchle volania medzi vlastnými službami | Google, Kubernetes | Firestore klient |
| **GraphQL** | frontend s rôznymi potrebami dát | Meta, Shopify | Supabase `pg_graphql`, Firebase Data Connect |
| **Webhook** | udalosti z cudzieho systému k nám | Stripe, GitHub | Supabase Database Webhooks |
| **WebSocket** | živé aktualizácie v prehliadači | Slack, Discord | Supabase Realtime, Firebase Realtime DB |

**Výber API = rozhodnutie o kontrakte, dátach, smere komunikácie a tolerancii zlyhaní.**
