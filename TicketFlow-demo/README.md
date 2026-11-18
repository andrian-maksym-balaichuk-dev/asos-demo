# TicketFlow API Showcase

Lokálne spustiteľné demo k prezentácii **„Typy API“**. Jedna doména (koncert **42**, miesto **A7**, 100 sedadiel, rezervácie a platby) a štyri skutočné API štýly:

| Demo | Čo divák uvidí | Technológia |
|---|---|---|
| **A** | rovnaký retry ≠ nový nákup · súbeh = len 1 víťaz | REST + OpenAPI, `Idempotency-Key`, PostgreSQL partial UNIQUE index |
| **B** | formálny kontrakt a reálny deadline | SOAP 1.1 / WSDL, gRPC + protobuf, `DEADLINE_EXCEEDED` |
| **C** | rovnaký JSON, ale **101 vs 2** skutočné SQL dotazy | GraphQL (Strawberry), request-scoped DataLoader |
| **D** | podpísaná udalosť, dedupe, potvrdenie v dvoch oknách, reconnect | HMAC-SHA256 webhook, PostgreSQL dedupe, WebSocket |

Nič nie je predpripravené: počty SQL dotazov pochádzajú zo SQLAlchemy event hooku, súbeh rozhoduje databáza, webhooky sú naozaj podpísané a overené.

## Rýchly štart

Potrebuješ len Docker (Desktop) a voliteľne Python 3 na hoste pre skripty (iba štandardná knižnica).

```bash
cp .env.example .env              # voliteľné — bez .env sa použijú lokálne demo hodnoty
docker compose up --build -d
docker compose ps                 # 4 služby (healthy)
python3 scripts/preflight.py      # PASS/FAIL pre všetky scenáre + reset
```

| URL | Čo |
|---|---|
| http://localhost:8000/ | demo panel (4 karty) |
| http://localhost:8000/code | **kód dema krok po kroku** (skutočný kód zo súborov, ◀ Späť / Ďalej ▶, šípky ← →) |
| http://localhost:8000/docs | Swagger UI (OpenAPI), funguje offline |
| http://localhost:8000/soap?wsdl | WSDL |
| `localhost:50051` | gRPC `ticketflow.inventory.v1.Inventory` |
| http://localhost:8002/docs | simulovaný payment provider |

## Testy

```bash
docker compose exec api pytest -q      # 29 integračných testov proti bežiacim službám
```

Testy resetujú demo dáta, nespúšťaj ich počas prezentácie.

## Skripty (fallback cez terminál)

```bash
python3 scripts/reset_demo.py
python3 scripts/demo_rest.py --reset
python3 scripts/demo_rpc.py --show-wsdl --check-seat A7
python3 scripts/demo_rpc.py --grpc-delay-ms 800 --deadline-ms 200
python3 scripts/demo_graphql.py --seats 100 --compare
python3 scripts/demo_webhook.py --all-cases
python3 scripts/screenshots.py          # docs/SCREENSHOTS/*.png cez headless Chrome
```

Alebo `make up | test | preflight | reset | demo-rest | demo-rpc | demo-graphql | demo-webhook | screenshots`.

## Dokumentácia

- [docs/RUNBOOK.md](docs/RUNBOOK.md) — presné kliky, očakávané výstupy, fallbacky pre každé demo
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — diagram, invarianty, čo je reálne a čo nie
- [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) — porty, sieť, Docker
- [docs/SCREENSHOTS/](docs/SCREENSHOTS/) — screenshoty a `fallback.html` (náhradná ukážka zo skutočného behu)

## Štruktúra

```text
app/                FastAPI: REST, GraphQL, webhook, WebSocket, demo endpointy, dashboard
  data/             schéma (constrainty), seed, spoločné dotazy
grpc_service/       inventory.proto, server (samostatná služba), klient
soap_service/       WSDL, SOAP endpoint (lxml), klienti (httpx, zeep)
provider_simulator/ payment provider, ktorý podpisuje raw body
frontend/           index.html, app.js, style.css (+ lokálne Swagger UI assets)
scripts/            demo skripty, reset, preflight, screenshoty (len stdlib)
tests/              pytest integračné testy
```

## Bezpečnosť

- Secret pre webhooky ide len z prostredia (`WEBHOOK_SECRET`), nikdy sa neloguje. `.env` je v `.gitignore`.
- Všetky SQL dotazy sú parametrizované. SOAP parser má vypnuté entity/DTD/sieť (XXE).
- Demo endpointy (`/demo/*`) sú len pre lokálne demo; vypneš ich cez `DEMO_MODE=false`.
