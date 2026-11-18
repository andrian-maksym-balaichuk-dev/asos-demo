# ARCHITECTURE

## Diagram

```text
                    ┌──────────────────────── prehliadač (2 okná) ─────────────────────────┐
                    │  dashboard  ── HTTP (fetch) ──┐          ┌── WebSocket /ws (Klient A, B) │
                    └───────────────────────────────┼──────────┼──────────────────────────────┘
                                                    ▼          ▼
┌──────────────────────────── api :8000 (FastAPI, 1 Uvicorn proces) ───────────────────────────┐
│  REST /events /reservations   SOAP /soap (+?wsdl)   GraphQL /graphql, /graphql/naive          │
│  Webhook /webhooks/payment    WebSocket /ws         Demo /demo/*   Swagger /docs              │
│        │                         │                        │                  ▲                 │
│        │ SQLAlchemy (psycopg 3)  │ gRPC klient (deadline)  │ httpx            │ podpísaný POST │
└────────┼─────────────────────────┼────────────────────────┼──────────────────┼─────────────────┘
         ▼                         ▼                        ▼                  │
┌──────────────────┐     ┌──────────────────────┐   ┌───────────────────────────┴──┐
│ db :5432         │◄────│ grpc :50051          │   │ provider :8002               │
│ PostgreSQL 16    │     │ Inventory.CheckSeat  │   │ simulovaný payment provider  │
│ (zdroj pravdy)   │     │ grpc.aio + health    │   │ HMAC-SHA256(t + "." + raw)   │
└──────────────────┘     └──────────────────────┘   └──────────────────────────────┘
```

Všetky služby používajú rovnakú schému a rovnaké doménové dotazy (`app/data/queries.py`).
REST, SOAP aj gRPC teda vracajú pre A7 ten istý stav.

## Dátový model a invarianty

| Tabuľka | Invariant | Prečo |
|---|---|---|
| `seats` | PK `(event_id, seat_id)`, CHECK formátu `A1–J10` | 100 sedadiel |
| `prices` | samostatná tabuľka, FK na `seats` | aby GraphQL mohol ukázať N+1 |
| `reservations` | **`one_active_reservation_per_seat`**: `UNIQUE (event_id, seat_id) WHERE status IN ('PENDING','CONFIRMED')` | súbeh dvoch kupujúcich, rozhoduje DB |
| `idempotency_keys` | PK `key`, `request_hash`, uložené presné bajty odpovede | retry tej istej logickej operácie |
| `processed_webhook_events` | PK `event_id` | deduplikácia webhookov |

ID rezervácií sú zo sekvencie (`r-001`, `r-002`…). Reset ju reštartuje, takže demo je opakovateľné.

## Demo A — idempotencia vs. súbeh

`POST /reservations` v jednej transakcii:
1. ak je `Idempotency-Key`: `INSERT … ON CONFLICT (key) DO NOTHING`. Ak kľúč existuje, porovná `request_hash`. Pri zhode vráti **uložené bajty** pôvodnej odpovede (`Idempotent-Replayed: true`), pri inom payloade vráti `422`. Súbežný request s tým istým kľúčom počká na zámok riadku.
2. `INSERT INTO reservations … 'PENDING'`. Porušenie `one_active_reservation_per_seat` (SQLSTATE 23505) vráti `409 SEAT_TAKEN`, celá transakcia sa vráti a kľúč ostane nepoužitý.
3. Commit a až potom WebSocket `reservation.created`.

V Python kóde **nie je žiadny lock**. Test `test_twenty_buyers_exactly_one_winner` pošle 20 súbežných kupujúcich a očakáva presne 1× 201.

## Demo B — SOAP a gRPC

- **SOAP**: ručne napísaná WSDL (`soap_service/inventory.wsdl`, SOAP 1.1 document/literal) a malý lxml endpoint. Je zámerne čitateľný. Správnosť kontraktu overuje test cez nezávislý SOAP stack **zeep** (načíta WSDL, zavolá `CheckSeat`). Chyby vracajú SOAP Fault s HTTP 500 podľa SOAP 1.1 HTTP binding. Parser má vypnuté entity, DTD aj sieť (XXE test).
- **gRPC**: `grpc_service/inventory.proto`. Stuby sa generujú pri `docker build`. Server beží samostatne (`grpc.aio`) a má gRPC health service. `artificial_delay_ms` (max 5000) je demo-only. Klient (v API kontajneri) nastaví `timeout=deadline` a pri prekročení dostane `DEADLINE_EXCEEDED`; runtime zruší RPC aj na serveri (log `RPC zrušené po … ms`).
- **Bajty**: SOAP = dĺžka HTTP body; gRPC = `len(message.SerializeToString())`, bez HTTP/2 rámcov, 5 B prefixu a hlavičiek. Platí len pre tieto konkrétne správy, nie je to výkonnostný záver.

## Demo C — ako sa počítajú SQL dotazy

`app/data/db.py`: listener `before_cursor_execute` na engine zapisuje príkazy do `conn.info["ticketflow_query_log"]`.
Každý GraphQL request dostane **vlastné** spojenie v režime AUTOCOMMIT (žiadny implicitný BEGIN), vlastný log a vlastný DataLoader.
Do meraného scope teda patrí presne to, čo GraphQL execution poslal do PostgreSQL.

| Resolver | Dotazy pre `seats(limit: 100) { id price { amount currency } }` |
|---|---|
| `event(id)` | 0, vracia len referenciu; `name`/`venue` sa načítajú iba ak sú v query (1 dotaz, uvidíš ho v logu) |
| `seats(limit)` | 1 |
| `price` naivne | 1 na sedadlo, teda 100 |
| `price` DataLoader | 1 (`WHERE event_id = … AND seat_id IN (…)`) |
| **spolu** | **101** vs **2** |

Testy overujú aj škálovanie (`limit: 10`: 11 vs 2), takže číslo nie je napevno zadané.
Ochrany: `limit` 1–100, `QueryDepthLimiter(max_depth=6)`, pole `internalCost` vyžaduje rolu `admin`.
V produkcii by rola prišla z overeného tokenu, nie z demo hlavičky `X-Demo-Role`; pribudli by aj limity komplexity a persisted queries.

## Demo D — webhook → DB → WebSocket

1. Provider zostaví JSON, serializuje ho na **raw bajty**, podpíše `HMAC-SHA256(secret, f"{t}." + raw)` a pošle hlavičku `TicketFlow-Signature: t=…,v1=…`.
2. Príjemca: limit veľkosti, potom `hmac.compare_digest` a okno čerstvosti ±300 s. Pri neúspechu vráti `400`/`401` a databázy sa nedotkne (odmietnutia sú len v pamäti).
3. Až potom parsuje JSON a v jednej transakcii urobí `INSERT processed_webhook_events … ON CONFLICT DO NOTHING`. Ak riadok už existuje, ide o duplicitu: `200 DUPLICATE_IGNORED` a nič sa nemení. Inak `SELECT … FOR UPDATE` a `UPDATE … SET status='CONFIRMED' WHERE status='PENDING'`.
4. Po commite broadcast `reservation.confirmed` všetkým WebSocket klientom.
5. Klient pri každom (re)connecte načíta snapshot `GET /reservations/{id}`. Server **nerobí replay**.

**Vedomé obmedzenia MVP**

- Bez transactional outboxu: ak proces spadne medzi commitom a broadcastom, klienti zmenu uvidia až po reconnecte cez snapshot. Produkčné riešenie je outbox tabuľka plus worker.
- WebSocket spojenia sú v pamäti jedného procesu, preto API beží s `--workers 1`. Pri viacerých procesoch treba Redis pub/sub alebo broker.
- WebSocket nezaručuje doručenie a webhook nezaručuje exactly-once. Preto existuje dedupe a snapshot.

## Čo je reálne a čo simulované

| Reálne | Simulované / demo-only |
|---|---|
| PostgreSQL constrainty, transakcie, súbeh | platba (žiadny skutočný provider) |
| HTTP, SOAP, gRPC (HTTP/2), WebSocket spojenia | `artificial_delay_ms` v gRPC |
| HMAC podpis a overenie raw body | rola cez hlavičku `X-Demo-Role` |
| počty SQL dotazov z event hooku | `/demo/*` endpointy (reset, proxy na providera) |
| merané bajty a časy (orientačne) | — |
