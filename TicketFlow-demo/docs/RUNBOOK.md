# RUNBOOK — TicketFlow demo počas prezentácie

## 0. Príprava (15 min pred prednáškou)

```bash
cd TicketFlow-demo
cp .env.example .env                 # vlastný lokálny secret, nie produkčný kľúč
docker compose up --build -d
docker compose ps                    # db, api, grpc, provider → (healthy)
python3 scripts/preflight.py         # očakávaj: „VŠETKO PASS — môžeš prezentovať.“
```

Preflight na konci resetuje dáta (A7 VOĽNÉ, ďalšia rezervácia bude `r-001`) a zapíše
`docs/SCREENSHOTS/preflight_last_run.json` + `docs/SCREENSHOTS/fallback.html`.

- Otvor `http://localhost:8000/` (panel) a `http://localhost:8000/docs` (Swagger UI).
- Zoom prehliadača 125–150 %. Pre Demo D otvor druhé okno: odkaz **„Otvoriť klienta v novom okne ↗“** (`/?tab=D&solo=B`) a daj okná vedľa seba.
- Funguje to bez internetu (Swagger UI assets sú lokálne). Po builde môžeš Wi-Fi vypnúť.
- Pred každým demom stlač **Reset** (alebo `python3 scripts/reset_demo.py`).
- **Nespúšťaj `pytest` počas prezentácie**, lebo resetuje dáta.

Na každom výsledku je HTTP status, **correlation ID** (rovnaké ako hlavička `X-Correlation-ID` a riadok v `docker compose logs api`), čas a stav **pred → po**.

---

## Demo A — REST retry vs. súbeh (max. 1:55)

| Klik | Očakávaný výsledok |
|---|---|
| **Reset** | `200`, dlaždica *Miesto A7* = **VOĽNÉ**, aktívne rezervácie = 0 |
| **Vytvoriť rezerváciu** | `201 Created`, `reservation_id = r-001`, `Idempotent-Replayed: false`, A7 = PENDING |
| **Zopakovať request** | `201`, **rovnaké** `r-001`, `Idempotent-Replayed: true`, aktívne rezervácie stále **1** |
| *(voliteľne)* **Rovnaký kľúč, iný payload** | `422 IDEMPOTENCY_KEY_REUSED`, nič sa nezmenilo |
| **Spustiť súbeh** | Panel sám resetuje a pošle 2 nezávislé requesty s rôznymi kľúčmi → jeden `201 Created`, druhý `409 Conflict SEAT_TAKEN` |
| pozri kartu **SQL** | `SELECT … WHERE seat_id = 'A7' AND status IN ('PENDING','CONFIRMED')` → presne **1** riadok |

Kto vyhrá súbeh (Anna/Boris), nie je dané vopred, rozhoduje PostgreSQL.
Swagger UI: `POST /reservations` ukazuje odpovede 201/404/409/422 a popis kontraktu `Idempotency-Key`.

**Fallback:** `python3 scripts/demo_rest.py --reset` · záznam: `docs/SCREENSHOTS/demo_A_rest.png`

---

## Demo B — SOAP/WSDL + gRPC deadline (max. 1:55)

Prepínač **SOAP | gRPC** hore v karte.

| Klik | Očakávaný výsledok |
|---|---|
| SOAP → **Zobraziť WSDL** | vľavo výrez `portType`/`binding` so zvýrazneným `CheckSeat`, vpravo celá WSDL |
| SOAP → **CheckSeat(42, A7)** | `HTTP 200`, `available = true` (po resete), request/response XML Envelope, veľkosť body v bajtoch |
| SOAP → **Neplatný request** | `SOAP Fault (HTTP 500)`, `faultcode soap:Client`, „Chýba povinný element seatId.“ |
| gRPC → **CheckSeat(42, A7)** | `OK`, `available = true (FREE)`, protobuf request/response bajty |
| gRPC → **Pomalý server 800 ms + deadline 200 ms** | `DEADLINE_EXCEEDED` po ~200 ms; časová os ukazuje 800 ms práce servera vs. deadline 200 ms |

Pointa: deadline je rozpočet **klienta**. Server dostane zrušenie, čo vidno v `docker compose logs grpc`
(„RPC zrušené po … ms … práca servera nedokončená“).
Bajty: SOAP = HTTP body bez hlavičiek; gRPC = serializovaná protobuf správa bez HTTP/2 rámcov. **Nie je to benchmark.**

**Fallback:**
```bash
python3 scripts/demo_rpc.py --show-wsdl --check-seat A7
python3 scripts/demo_rpc.py --grpc-delay-ms 800 --deadline-ms 200
```
Záznam: `docs/SCREENSHOTS/demo_B_soap.png`, `demo_B_grpc_deadline.png`

---

## Demo C — GraphQL N+1 (max. 1:45)

| Klik | Očakávaný výsledok |
|---|---|
| **Naivný resolver** | dlaždica *naivne* = **101**, SQL log: 1× `FROM seats` + 100× `FROM prices WHERE … seat_id = …` |
| **Batching (DataLoader)** | dlaždica *batching* = **2**, druhý dotaz `… seat_id IN (…)` |
| (alebo **Porovnať obe**) | *JSON odpovede zhodný?* = **ÁNO** |
| *(voliteľne)* **Neplatný limit 500** | chyba „limit musí byť 1–100“, 0 SQL dotazov |
| *(voliteľne)* **Privilegované pole bez roly** | „Prístup zamietnutý: pole internalCost vyžaduje rolu admin.“ |

Čísla pochádzajú z `extensions.sql.count`, teda zo SQLAlchemy hooku `before_cursor_execute` na DB spojení daného requestu.
Ak by panel ukázal iné číslo, **povedz to skutočné**, nie 101/2. Trvanie v ms je len orientačné lokálne meranie.

**Fallback:** `python3 scripts/demo_graphql.py --seats 100 --compare` · záznam: `docs/SCREENSHOTS/demo_C_graphql.png`

---

## Demo D — webhook → DB → WebSocket (max. 2:00)

Dve okná: hlavné (Klient A + B) a druhé okno `/?tab=D&solo=B`.

| Klik | Očakávaný výsledok |
|---|---|
| **Vytvoriť PENDING** | reset + `201`, `r-001` = PENDING; všetci klienti ukazujú PENDING |
| *(odporúčané)* **Pokaziť podpis** | príjemca `401 INVALID_SIGNATURE`, log `PENDING → PENDING` (DB nezmenená) |
| **Odoslať platbu** | `200 Spracované: CONFIRMED`, log `PENDING → CONFIRMED`, **oba klienti** (aj druhé okno) ukážu CONFIRMED cez WebSocket |
| **Zopakovať webhook** | `200 Duplicita — prijatá bezpečne, bez zmeny`, rovnaké `event id`, `CONFIRMED → CONFIRMED` |
| *(voliteľne)* **Bez podpisu** | `400 MISSING_SIGNATURE` |
| **Reconnect:** **Vytvoriť PENDING** → pri Klientovi B **Odpojiť** → **Odoslať platbu** → pri Klientovi B **Pripojiť** | Klient A ukáže CONFIRMED hneď. Klient B ostane na PENDING (správu nedostal). Po pripojení ukáže „stav obnovený zo snapshotu GET /reservations/r-001“ = **CONFIRMED** |

Karta *Odoslané providerom* ukazuje hlavičku `TicketFlow-Signature: t=…,v1=…` a presné raw body.
Server **nerobí** replay zmeškaných správ, zdrojom pravdy je databáza.

**Fallback:** `python3 scripts/demo_webhook.py --all-cases` · záznam: `docs/SCREENSHOTS/demo_D_webhook_ws.png`

---

## Keď niečo zlyhá

1. Max. 15 s debugovania naživo. Potom použi CLI fallback zo sekcie dema.
2. Ak nejde ani to: otvor `docs/SCREENSHOTS/fallback.html` (záznam z posledného preflightu, je na ňom žltý banner **NÁHRADNÁ UKÁŽKA**) a **povedz publiku, že ide o záznam**.
3. Rýchla diagnostika: `docker compose ps`, `curl -s localhost:8000/health/deps`, `docker compose logs --tail=50 api`.
4. Všetko ostatné je v [TROUBLESHOOTING.md](TROUBLESHOOTING.md).

## Po prednáške

```bash
docker compose down        # zachová DB volume
docker compose down -v     # zmaže aj dáta
```
