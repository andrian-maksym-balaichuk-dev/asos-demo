# DEMO NÁVOD — ČO SPUSTIŤ A ČO HOVORIŤ

**40 min prezentácia · 4 živé dema po 1–2 minúty.** Implementácia: priečinok `TicketFlow-demo/`.
Na plátne je len panel s tlačidlami a výsledkami. Čo povedať a kedy kliknúť je iba tu, v tomto návode.
Formát každého dema: **Čo ukazujeme → Povedz → Klikni / Uvidíš / Povedz pri tom → Záver → Fallback.**

## A. Príprava (15 min pred prednáškou)

```bash
cd TicketFlow-demo
docker compose up --build -d
docker compose ps                  # 4 služby (healthy)
python3 scripts/preflight.py       # musí skončiť „VŠETKO PASS“ (zároveň resetuje dáta)
```

1. Otvor `http://localhost:8000/` (panel), `http://localhost:8000/code` (kód krok po kroku: `?tab=A` … `?tab=D`, šípky ← →) a `http://localhost:8000/docs` (Swagger UI).
2. Zoom 125–150 %. Pre Demo 4 klikni v karte D na **Otvoriť druhé okno ↗** a daj okná vedľa seba.
3. Funguje to aj bez internetu. Vypni notifikácie.
4. Každý si natrénuje svoje demo 3×. Čas meraj od otázky publiku po záverečnú vetu.
5. Nespúšťaj `pytest` počas prednášky, lebo resetuje dáta.

---

## B. Demo 1 — REST: retry vs. súbeh (slide 06, max. 1:55)

- **Čo to je:** REST sú zdroje cez HTTP (`GET /events/42`, `POST /reservations`). Kontrakt je v OpenAPI (Swagger na `/docs`).
- **Čo urobíme:** vytvoríme rezerváciu A7, zopakujeme presne ten istý request a potom pošleme dvoch kupujúcich naraz.
- **Prečo:** sieť zlyháva a klienti requesty opakujú. Retry nesmie kúpiť lístok dvakrát (rieši `Idempotency-Key`). Dvaja ľudia nesmú dostať to isté miesto (rieši unique index v databáze). Sú to dva rôzne problémy.
- **Kde sa používa:** verejné API webov a mobilných aplikácií, všade kde ide o zdroje (objednávky, používatelia, rezervácie).
- **Prečo REST a nie iné:** funguje cez obyčajné HTTP, z prehliadača aj z každého jazyka, bez špeciálneho klienta. Dá sa cacheovať a ľahko ladiť. gRPC prehliadač priamo nezavolá (len cez gRPC-Web). GraphQL je pri jednoduchých zdrojoch zbytočná zložitosť.
- **Kde to vidieť v reáli:** Stripe API používa presne `Idempotency-Key` pri platbách (retry nesmie strhnúť peniaze dvakrát). GitHub REST API: `curl https://api.github.com/repos/python/cpython`. Rezervačné systémy (lístky, letenky, hotely) riešia súbeh o posledné miesto.

**Povedz (20 s):** „Klient môže request po timeoute zopakovať. Dvaja klienti môžu chcieť to isté miesto naraz. Je to ten istý problém?“

| # | Klikni | Uvidíš | Povedz pri tom |
|---|---|---|---|
| 1 | **Reset** | A7 = **VOĽNÉ**, rezervácie v DB = 0 | „Miesto je voľné.“ |
| 2 | **Vytvoriť rezerváciu** | `201 Created`, `r-001`, A7 = PENDING | „Request má Idempotency-Key.“ |
| 3 | **Zopakovať request** | `201`, **to isté** `r-001`, `Idempotent-Replayed: true`, rezervácie v DB **1 → 1** | „Timeout, klient skúsi znova. Server vráti pôvodný výsledok, nový nákup nevznikne.“ |
| 4 | **Spustiť súbeh** | sám resetuje, potom Anna/Boris: jeden `201 Created`, druhý `409 Conflict` | „Teraz dvaja rôzni ľudia s rôznymi kľúčmi naraz. Kľúč tu nepomôže.“ |
| 5 | ukáž kartu **SQL** | presne 1 riadok | „Rozhodla databáza, unique index. Žiadny lock v kóde.“ |

Kto zo súbehu vyhrá, nie je dané vopred. Rozhoduje PostgreSQL.

**Záver (25 s):** „Idempotency-Key rieši opakovanie toho istého requestu. Unique constraint v DB chráni miesto pred dvoma kupujúcimi. Jedno nenahrádza druhé.“

**Fallback:** `python3 scripts/demo_rest.py --reset` · záznam `docs/SCREENSHOTS/demo_A_rest.png`

---

## C. Demo 2 — SOAP/WSDL a gRPC deadline (slide 12, max. 1:55)

- **Čo to je:** SOAP sú XML správy podľa kontraktu WSDL (typicky B2B integrácie). gRPC sú binárne volania podľa `.proto` (interné služby).
- **Čo urobíme:** tú istú otázku „je A7 voľné?“ položíme cez SOAP aj gRPC. Potom server spomalíme na 800 ms, kým klient čaká najviac 200 ms.
- **Prečo:** kontrakt presne určuje, čo sa smie poslať a čo príde späť. Deadline chráni klienta, aby nečakal donekonečna, keď služba zlyhá. Deadline je rozpočet klienta, nie rýchlosť servera.
- **Kde sa používa:** SOAP v bankách, poisťovniach, štátnej správe, leteckých rezerváciách a starších ERP (SAP). gRPC medzi mikroslužbami vo vnútri firmy.
- **Prečo tieto a nie REST:** SOAP sa drží tam, kde už roky beží prísny B2B kontrakt (WSDL, WS-Security) a nikto ho nechce meniť. Nové projekty ho zvyčajne nevyberajú. gRPC má typovaný kontrakt, generovaný kód, HTTP/2, streaming a deadliny, čo sa hodí na veľa interných volaní. Na verejné API pre prehliadač sa nehodí.
- **Kde to vidieť v reáli:** SOAP: overenie DIČ v EÚ cez službu VIES (verejná WSDL `checkVatService`). gRPC: Kubernetes (kubelet ↔ container runtime cez CRI), etcd, klientske knižnice Google Cloud (napr. Pub/Sub).

**Povedz (20 s):** „Tú istú otázku, či je miesto voľné, rieši B2B SOAP kontrakt aj interná gRPC služba. Dôležitá nie je len veľkosť správy, ale aj to, čo sa stane pri zlyhaní.“

| # | Klikni | Uvidíš | Povedz pri tom |
|---|---|---|---|
| 1 | **SOAP** → **Zobraziť WSDL** | zvýraznená operácia `CheckSeat` | „Kontrakt je strojovo čitateľný. Klient sa z neho dá vygenerovať.“ |
| 2 | **CheckSeat(42, A7)** | `HTTP 200`, `available = true`, XML Envelope request/response | „Celá správa je XML obálka.“ (nečítaj XML) |
| 3 | **gRPC** → **CheckSeat(42, A7)** | `OK`, `available = true (FREE)` | „To isté cez binárny protobuf, typovaná odpoveď.“ |
| 4 | **Pomalý server 800 ms · deadline 200 ms** | `DEADLINE_EXCEEDED`, klient čakal ~200 ms | „Server by robil 800 ms, klient si dal limit 200 ms.“ |
| 5 | ukáž **Čas ≠ timeout** | časová os: práca servera 800 ms, čiara deadline na 200 ms | „Klient prestal čakať. gRPC zrušil prácu aj na serveri.“ |

Bajty v karte **Bajty** sú len veľkosti týchto konkrétnych správ, **nie je to benchmark**.

**Záver (30 s):** „SOAP sedí na existujúce B2B kontrakty, gRPC na interné volania. Ani jedno nezaručí úspech, keď zlyhá sieť alebo downstream.“

**Fallback:**
```bash
python3 scripts/demo_rpc.py --show-wsdl --check-seat A7
python3 scripts/demo_rpc.py --grpc-delay-ms 800 --deadline-ms 200
```
Záznam `docs/SCREENSHOTS/demo_B_soap.png`, `demo_B_grpc_deadline.png`

---

## D. Demo 3 — GraphQL N+1 (slide 18, max. 1:45)

- **Čo to je:** v GraphQL si klient jednou query vyberie presne tie dáta, ktoré potrebuje.
- **Čo urobíme:** tú istú query (100 sedadiel a ich ceny) spustíme raz s naivným resolverom a raz s DataLoaderom a spočítame skutočné SQL dotazy.
- **Prečo:** jeden request z klienta môže na serveri znamenať 101 dotazov do databázy (problém N+1). JSON je rovnaký, ale práca databázy nie. Server to musí riešiť dávkovaním.
- **Kde sa používa:** frontendy a mobilné aplikácie, ktoré potrebujú pre rôzne obrazovky rôzne dáta, často z viacerých zdrojov naraz.
- **Prečo GraphQL a nie REST:** jedna query namiesto viacerých REST requestov a klient dostane presne tie polia, ktoré chce (nič navyše, nič nechýba). Cenou je zložitejšia cache, autorizácia po poliach a N+1 na serveri, čo ukazujeme.
- **Kde to vidieť v reáli:** GitHub GraphQL API (Explorer v dokumentácii GitHubu), Shopify Admin/Storefront API. GraphQL vznikol vo Facebooku.

**Povedz (15 s):** „Obe implementácie vrátia na jednu query tú istú odpoveď. Koľko práce však robia pod povrchom?“

| # | Klikni | Uvidíš | Povedz pri tom |
|---|---|---|---|
| 1 | **Naivný resolver** | **101** SQL | „1 dotaz na sedadlá plus 1 dotaz na cenu za každé zo 100 sedadiel.“ |
| 2 | **Batching (DataLoader)** | **2** SQL | „Ceny sa načítajú naraz jedným dotazom.“ |
| 3 | ukáž **JSON zhodný: ÁNO** | ÁNO | „Klient nevidí rozdiel. Databáza áno.“ |
| 4 | ukáž **SQL log** | naivne `seat_id = 'A1'`, `'A2'` … +98; batching jeden `IN ('A1', 'A2', …)` | „Toto je skutočný log z databázového spojenia.“ |

Voliteľne pri otázke o bezpečnosti: **limit: 500 → zamietnuté**, **internalCost bez roly** (prístup zamietnutý).
Ak by counter ukázal iné číslo, povedz to skutočné, nie 101/2.

**Záver (25 s):** „GraphQL znižuje počet requestov z klienta, nie automaticky počet dotazov do DB. Batching, autorizáciu a zložitosť query musí riešiť server.“

**Fallback:** `python3 scripts/demo_graphql.py --seats 100 --compare` · záznam `docs/SCREENSHOTS/demo_C_graphql.png`

---

## E. Demo 4 — podpísaný webhook → DB → WebSocket (slide 23, max. 2:00)

- **Čo to je:** webhook znamená, že iný systém (platobná brána) zavolá náš server, keď sa niečo stane. WebSocket je otvorené spojenie, cez ktoré server pošle zmenu do prehliadača.
- **Čo urobíme:** provider pošle podpísanú správu o platbe, my ju uložíme do databázy a klienti ju hneď uvidia. Skúsime aj falošný podpis, odpojeného klienta a duplicitu.
- **Prečo:** falošný webhook môže poslať ktokoľvek, preto overujeme podpis. Provider môže poslať správu dvakrát, preto deduplikácia. Klient môže byť offline, preto si stav načíta z databázy.
- **Kde sa používa:** webhooky pri platbách, pri `git push` → CI/CD a pri notifikáciách medzi službami. WebSocket pri chate, živých notifikáciách, burzových kurzoch a online hrách.
- **Prečo toto a nie iné:** bez webhooku by sme sa providera museli stále pýtať „už je zaplatené?“ (polling), čo je pomalé a zbytočné. WebSocket je obojsmerné spojenie s nízkou latenciou. Ak posiela iba server klientovi, stačí aj SSE. V každom prípade ostáva zdrojom pravdy databáza, nie push správa.
- **Kde to vidieť v reáli:** Stripe webhooky (hlavička `Stripe-Signature: t=…,v1=…`, náš formát je podľa nej). GitHub webhooky (`X-Hub-Signature-256`). WebSocket: Discord Gateway, Slack, živé kurzy na burzách (Binance streams). Sám si to pozrieš v DevTools → Network → filter **WS** na stránke Slacku alebo Discordu.

**Povedz (15 s):** „Platba sa dokončí mimo nášho requestu. Kto je zdroj pravdy? A čo keď provider pošle tú istú udalosť dvakrát?“

| # | Klikni | Uvidíš | Povedz pri tom |
|---|---|---|---|
| 1 | **Vytvoriť PENDING** | `r-001`, všetci klienti (aj druhé okno) PENDING | „Rezervácia čaká na platbu.“ |
| 2 | **Pokaziť podpis** | `401`, „Zlý podpis — odmietnuté“, stav **PENDING → PENDING** | „Niekto zmenil sumu po podpise. Server to odmietne skôr, než sa dotkne DB.“ |
| 3 | Klient B → **Odpojiť** | Klient B: ODPOJENÝ | „Jeden klient stratí spojenie.“ |
| 4 | **Odoslať platbu** | `200`, **PENDING → CONFIRMED**, Klient A a druhé okno CONFIRMED, **Klient B ostal PENDING** | „Platný HMAC podpis, stav sa zmenil a ide push do UI. Odpojený klient o tom nevie.“ |
| 5 | Klient B → **Pripojiť** | Klient B: CONFIRMED „→ snapshot GET /reservations/r-001“ | „Po reconnecte si stav načíta z DB. Server nič nepreposiela znova.“ |
| 6 | **Zopakovať webhook** | `200`, „Duplicita — prijatá bezpečne, bez zmeny“, rovnaké event id | „Provider pošle tú istú udalosť znova. Prijmeme ju, ale nič sa nezmení.“ |

**Záver (25 s):** „Webhook oznámi výsledok backendu, databáza ho uchová a WebSocket ho pošle do UI. Samotná push správa nie je zdroj pravdy.“

**Fallback:** `python3 scripts/demo_webhook.py --all-cases` · záznam `docs/SCREENSHOTS/demo_D_webhook_ws.png`

---

## Ak niečo zlyhá (platí pre všetky dema)

Najviac 15 s debugovania naživo. Potom CLI fallback. Ak nejde ani ten, otvor `docs/SCREENSHOTS/fallback.html`
(záznam z posledného preflightu) a **povedz publiku, že ide o záznam**. Nevymýšľaj stav.

## F. Spoločné prechody medzi hovoriacimi

- **01 → 02:** „Verejné API sme zvládli. Čo však pri komunikácii medzi samotnými backendovými službami?“
- **02 → 03:** „Interné volania už fungujú. Frontend však stále potrebuje rôzne dáta pre rôzne obrazovky.“
- **03 → 04:** „Dáta vieme načítať. Čo ak sa zmenia až po tom, ako pôvodný request skončil?“
- **04 → záver:** „Výber API je rozhodnutie o kontrakte, dátach, životnom cykle komunikácie a tolerancii zlyhaní.“

## G. Otázky publika, na ktoré sa pripraviť

**Je REST vždy nad HTTP?** REST ako štýl nie je závislý od HTTP; v praxi sa najčastejšie implementuje nad HTTP.  
**Je OpenAPI alebo Swagger typ API?** Nie; OpenAPI je opis rozhrania a Swagger UI nástroj na jeho zobrazenie.  
**Prečo idempotency key nezabráni dvom kupujúcim?** Sú to dve rôzne logické operácie s rôznymi kľúčmi. Potrebujeme databázový invariant.  
**Je SOAP zastaraný?** Nie, existujú stabilné B2B integrácie; nevýhody sú hlavne ekosystém a komplexita v nových projektoch.  
**Je gRPC vždy rýchlejšie než REST?** Nie. Výsledok závisí od payloadu, infraštruktúry, serializácie a workloadu.  
**Prečo nemôžem cacheovať GraphQL?** Môžeš; typ a spôsob cacheovania je len zložitejší podľa konkrétnej query a transportu.  
**Prečo WebSocket nestačí pre platbu?** Je to transport aktualizácie; po odpojení môže byť stav neúplný, preto treba databázový snapshot/replay.  
**Prečo webhook nemá garanciu exactly once?** Delivery aj retries závisia od poskytovateľa; príjemca musí počítať s duplicitami a pravidlami poradia.

## H. Posledná kontrola v deň vystúpenia

- [ ] `python3 scripts/preflight.py` → „VŠETKO PASS“ (a `docker compose exec api pytest -q` deň vopred).
- [ ] Docker Compose štartuje na čistom stroji.
- [ ] 4 scenáre majú úspešné preflight PASS.
- [ ] Stav A7 je pri dema vždy resetovaný.
- [ ] Používajú sa ilustračné, nie osobné dáta.
- [ ] Žiadne externé API kľúče ani internetová závislosť.
- [ ] Oba browser taby sú otvorené na správnej rezervácii.
- [ ] Záloha snímok obrazovky a statický/PDF export prezentácie.
- [ ] Každý moderátor vie, kedy má prevziať ovládanie.
- [ ] Celkový čas 40:00; skrátiť iba diskusiu, nie vysvetlenie technických záväzkov.

## I. Otázky na skúšku — čo MUSÍ zaznieť nahlas

Každý člen tímu odovzdá jednu otázku (`docs/otazky/`). Odpoveď musí byť na slajde **a** povedaná nahlas, aby otázka bola férová.

| Otázka | Kto | Slajd | Veta, ktorú treba povedať |
|---|---|---|---|
| 1 · REST: dvaja kupujúci naraz | Demo 1 | 05 | „Idempotency-Key nepomôže — sú to dva rôzne nákupy. Jedno miesto zaručí iba unikátne obmedzenie alebo atomický zápis v databáze.“ |
| 2 · gRPC: deadline 200 ms, server 800 ms | Demo 2 | 12 | „Klient dostane DEADLINE_EXCEEDED, ale server mohol operáciu už vykonať. Zrušenie ju automaticky nevráti späť.“ |
| 3 · GraphQL: limit hĺbky | Demo 3 | 17 | „Limit hĺbky nestačí — neobmedzí šírku. Pri rozvetvení 10× na úroveň sú tri úrovne už 1 000 položiek. Preto aj paginácia a query cost.“ |
| 4 · Webhook: rovnaká udalosť druhýkrát | Demo 4 | 23–24 | „Najprv overíme podpis, potom podľa event ID zistíme, že sme udalosť už spracovali — stav druhýkrát nezmeníme.“ |
