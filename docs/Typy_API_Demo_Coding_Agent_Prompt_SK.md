# PROMPT PRE CODING AGENTA — VYTVOR PLNÉ FUNKČNÉ API DEMO

**Tento dokument vlož celý do Cursor Agent / Claude Code / Codex alebo iného coding agenta.**

## Úloha a požadovaný výsledok

Si senior software engineer, backend architect a QA automation engineer. Vytvor kompletné, lokálne spustiteľné **TicketFlow API Showcase** pre 40-minútovú prezentáciu **„Typy API“ v slovenčine** pre študentov 2. ročníka Ing. štúdia informatiky. Nie mockup, nie pseudokód: naozaj spustiteľné služby, skutočné HTTP/gRPC/SOAP/GraphQL volania, databáza a automatizované testy. Demo musí byť zrozumiteľné za 1–2 minúty na osobu a všetky časti musia používať rovnaké doménové dáta (koncert 42, miesto A7, rezervácie a platby).

Konzultuj súbory `01_KOMPLETNY_TEXT_PREZENTACIE_SK.md`, `03_DEMO_NAVOD_SK.md` a PPTX. Zachovaj v nich pomenovania, doménový príklad a všetky uvádzané invarianty. **Nevytváraj falošné výsledky, hardcoded počítadlá SQL ani benchmarky bez merania.**

## Pravidlá kvality a správania

- Docker Compose: **jediný reprodukovateľný vstup** `docker compose up --build -d`, bez platených API, kľúčov či cloudovej registrácie.
- Backend Python 3.12. Doporučené: FastAPI, Uvicorn, PostgreSQL, SQLAlchemy alebo psycopg, Strawberry GraphQL, grpcio/protobuf, Spyne/Zeep (alebo iný podporovaný SOAP/WSDL stack), pytest, httpx, websockets. Verzie závislostí uzamkni podľa dostupnej stabilnej verzie a kompatibility.
- Jednoduchý responzívny **biely dashboard** v prehliadači s veľkým písmom a štyrmi kartami. Návrh musí byť v súlade s prezentáciou: Inter/System UI, navy, biela, modrý/teal/fialový/oranžový akcent. Žiadna prezdobená animácia.
- Zreteľne rozlišuj **reálne správanie** od modelových výpočtov. Ak zobrazuješ „101 vs 2 SQL queries“, vyčítaj číslo zo skutočného SQL loggingu / SQLAlchemy event hook; nikdy nepouži pevne nastavené číslo.
- Žiadne live coding. Všetky demo scenáre sa spúšťajú veľkými tlačidlami, doplnkový shell skript je fallback. Scenár musí byť resetovateľný a opakovateľný.
- V prípade neúspechu volania ukáž zrozumiteľný stav a dôvod. Každá udalosť nech má timestamp, trace/correlation ID a zobrazený stav pred/po.
- Chráň pred SQL injection, používaj parametrizované dotazy, nevypínaj bezpečnosť pri webhookoch. Secret len z lokálnej env konfigurácie; nikdy logovať secret.
- Nepotrebuješ reálnu platbu. Simulovaný provider však musí **naozaj podpisovať raw body**, a backend podpis verifikovať.
- Nikde netvrď „SOAP je vždy pomalý“, „gRPC vždy najrýchlejšie“, „GraphQL vždy lepšie“, „WebSocket zaručuje delivery“.

## Architektúra projektu

```text
TicketFlow-demo/
  docker-compose.yml
  .env.example
  README.md
  Makefile
  requirements*.txt / pyproject.toml
  app/
    main.py                    # FastAPI + static white dashboard
    routes/rest.py             # /events, /reservations
    graphql/schema.py          # query a DataLoader
    websocket/manager.py       # live updates, reconnect snapshot
    webhook/receiver.py        # raw body + HMAC + event dedup
    data/models.py             # PostgreSQL constraints
    data/seed.py               # concert 42, A7, 100 demo seats
  grpc_service/
    inventory.proto
    server.py
    client.py
  soap_service/
    server.py                 # valid WSDL, CheckSeat operation
    client.py
  provider_simulator/
    payment_provider.py      # sends signed webhooks
  frontend/
    index.html, app.js, style.css
  scripts/
    demo_rest.py
    demo_rpc.py
    demo_graphql.py
    demo_webhook.py
    reset_demo.py
    preflight.py
  tests/
    test_reservation_race.py
    test_idempotency.py
    test_grpc_deadline.py
    test_graphql_n_plus_one.py
    test_webhook_hmac.py
    test_webhook_duplicate.py
    test_websocket_reconnect.py
  docs/
    RUNBOOK.md
    ARCHITECTURE.md
    TROUBLESHOOTING.md
    SCREENSHOTS/
```

## Demo A — REST, OpenAPI, idempotency a konkurencia

1. `GET /events/42` a `GET /events/42/seats` vracajú konzistentné dáta.
2. `POST /reservations` vyžaduje `event_id=42`, `seat_id=A7`, `buyer_id`; voliteľne `Idempotency-Key` (dokumentuj semantics).
3. Scenár retry: dvakrát presne ten istý logický request a key. Druhé volanie nesmie vytvoriť novú rezerváciu; výsledné `reservation_id` musí byť identické. Rozlišuj rovnaký key + iný payload → bezpečná chyba (napr. 409) podľa zdokumentovaného kontraktu.
4. Scenár race: dve **nezávislé** požiadavky s rôznymi keys na sedadlo A7. V databáze je presne jedna aktívna rezervácia; jeden klient uspeje, druhý dostane 409. Garancia vzniká **z PostgreSQL constraint/transakcie**, nie z Python globálneho locku.
5. Na `http://localhost:8000/docs` zobraziť automatickú OpenAPI/Swagger UI dokumentáciu; názorné statusy a schémy.
6. Dashboard: tlačidlá `Vytvoriť`, `Zopakovať request`, `Spustiť súbeh`, `Reset` a čitateľný výsledok.

## Demo B — SOAP/WSDL a gRPC/deadlines

1. Funkčná SOAP 1.1 alebo 1.2 služba `CheckSeat(eventId, seatId)` s korektnou zverejnenou WSDL a viditeľným request/response XML; demonštruj SOAP Fault pre neplatný request.
2. `.proto` definuje `Inventory.CheckSeat(SeatRequest)->SeatReply`, voliteľne server-streaming `WatchAvailability`, ale nevytváraj zbytočný stream ak presahuje čas.
3. Vygenerované stuby a funkčný Python gRPC server v samostatnom compose servise, napr. `localhost:50051`.
4. Normálny call vráti `available=true/false`. Druhý call umelo zdrží server (`artificial_delay_ms`) a klient nastaví deadline 200 ms: musí nastať `DEADLINE_EXCEEDED`; na paneli ukáž, že skutočný čas a timeout sú odlišné pojmy.
5. Panel prepína karty `SOAP` a `gRPC`, zobrazí kontrakt, payload a výstup. Ak robíš porovnanie veľkosti payload, meraj skutočné bajty a jasne uveď rozsah (request/response, bez/vrátane HTTP framing). Bez univerzálneho performance claims.

## Demo C — GraphQL N+1, batching a ochrana

1. GraphQL schéma `Event`, `Seat`, `Price`; query `event(id: "42") { seats(limit: 100) { id price } }`.
2. Semená databázy: 100 sedadiel a oddelená tabuľka cien. V naivnom resolvere jedna query načíta 100 sedadiel a 100 individuálnych queries ceny = **101** pre daný dátový model.
3. Optimalizovaný request-scoped DataLoader naraz načíta ceny `WHERE seat_id IN (...)`, teda **2** SQL queries pri identickom výsledku. Je zakázané falošne zobraziť 101/2 pri inej skutočnej sémantike: radšej oprav implementáciu a dôkaz v logoch.
4. Na jeden request vytvor nový loader; cache nesmie unikať medzi používateľmi. Pri cenách over autorizáciu, pri public poliach je možné zdieľanie podľa potreby.
5. Ukáž krátky, bezpečný neplatný/privilegovaný query a limit `max limit 100`, prípadne v produkčnom komentári vysvetli depth/complexity controls.
6. Dashboard: `Naivný resolver`, `Batching`, SQL log, porovnanie počtu query, rovnaký JSON, voliteľné trvanie s informáciou **orientačné lokálne meranie**.

## Demo D — webhook, signature, duplicates, WebSocket a reconnect

1. Simulovaný payment provider vytvorí JSON event `payment.succeeded`, s jedinečným `event_id`, identifikátorom rezervácie, časom a podpísanými raw body (`HMAC-SHA256(secret, timestamp + '.' + raw_body)` alebo štandardným konzistentným protokolom).
2. Receiver **najprv** overí podpis konštantným časovým porovnaním a freshness oknom, **potom** kontroluje deduplikáciu event ID v PostgreSQL, až potom transakčne zmení PENDING → CONFIRMED.
3. Overená opakovaná udalosť sa prijme bezpečne bez druhej zmeny stavu. Neplatný podpis musí vrátiť 401/400 a nesmie meniť databázu.
4. Zmena stavu až po commite oznámená cez WebSocket dvom otvoreným browser tabom. Event nepredstieraj, skutočne používaj socket.
5. Jedna odpojená karta musí po reconnecte obnoviť stav cez `GET /reservations/{id}`. Nesľubuj automatické serverové replay bez implementácie.
6. Zváž transactional outbox, ale nerozširuj MVP o plnohodnotný message broker, ak by to ohrozilo stabilitu. Ak worker má viac procesov, zaveď Redis/pubsub alebo jasne obmedz demo na jeden proces.
7. Dashboard: `Vytvoriť PENDING`, `Odoslať platbu`, `Zopakovať webhook`, `Pokaziť podpis`, `Odpojiť / pripojiť klienta`.

## Testovateľné akceptačné podmienky — MUST PASS

- `docker compose up --build -d` spustí všetko na čistom počítači s Dockerom bez zásahu do kódu.
- `docker compose ps` ukáže zdravé služby; healthchecks vrátia úspech.
- `pytest -q` / `docker compose exec api pytest -q`: testy pre 4 dema a chyby prejdú.
- Demo A: 1 reservation po retry a 1 winner z 2 konkurenčných kupujúcich.
- Demo B: WSDL obsahuje `CheckSeat`, gRPC stub reálne funguje, pri 200 ms deadline a 800 ms delay vznikne správna chyba.
- Demo C: **reálne** 101 a 2 SQL queries pri 100 sedadlách (bez pomocných SQL dotazov mimo meraného scope) a rovnaké dáta.
- Demo D: webhook bez podpisu odmietnutý; validný mení stav presne raz; duplicate spracovaný idempotentne; dva WebSocket klienty dostanú potvrdenie; reconnect načíta snapshot.
- `preflight.py` resetuje dáta a vysvetlí PASS/FAIL pre všetky scénare.
- Užívateľsky prívetivá slovenčina vo všetkých textoch, statusoch a tlačidlách.
- V každom demoscenári sú pripravené screenshoty a lokálne offline fallback (statické HTML/PNG/video podľa dostupnosti), jasne označené ako náhradná ukážka.
- Žiadne tajné údaje v gite, žiadne platené SDK, žiadne externé volania potrebné na demo.

## Povinný spôsob práce agenta

1. Najprv napíš krátky implementačný plán a vytvor štruktúru repo.
2. Implementuj jednu stabilnú spoločnú doménu a databázu; až potom endpointy, gRPC, SOAP, GraphQL a realtime.
3. Píš testy paralelne s implementáciou. **Neskracuj implementáciu na nefunkčné dekoratívne UI.**
4. Reálne spusti Docker Compose, otestuj všetky cesty, over konzistentnosť a zrob screenshoty.
5. Sprav `docs/RUNBOOK.md`: presné príkazy, kliky, očakávané výstupy a fallbacky. Sprav `docs/ARCHITECTURE.md` s diagramom, `docs/TROUBLESHOOTING.md` so sieťovými a portovými problémami.
6. Posledná odpoveď musí obsahovať: čo funguje, aké testy prešli, ako systém spustiť, ktoré kroky nemožno overiť a odkazy na vytvorené súbory. Nikdy netvrď „hotové“ bez reálnych testov.

## Čo má divák vidieť

Demo A: **rovnaký retry ≠ nový nákup**; súbeh **len 1 víťaz**.  
Demo B: **formálny kontrakt a reálny deadline**.  
Demo C: **rovnaký JSON, ale 101 vs 2 skutočné SQL dotazy**.  
Demo D: **podpísaná udalosť, dedupe, potvrdenie v dvoch oknách, reconnect**.

## Primárne zdroje pre správnosť

- https://www.rfc-editor.org/rfc/rfc9110.html
- https://spec.openapis.org/oas/latest.html
- https://www.w3.org/TR/soap12/
- https://www.w3.org/TR/wsdl/
- https://grpc.io/docs/what-is-grpc/core-concepts/
- https://grpc.io/docs/guides/deadlines/
- https://protobuf.dev/programming-guides/encoding/
- https://graphql.org/learn/performance/
- https://graphql.org/learn/security/
- https://cheatsheetseries.owasp.org/cheatsheets/Webhook_Security_Cheat_Sheet.html
- https://docs.stripe.com/webhooks
