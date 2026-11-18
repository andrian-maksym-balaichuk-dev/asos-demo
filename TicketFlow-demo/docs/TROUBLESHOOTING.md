# TROUBLESHOOTING

## Rýchla diagnostika

```bash
docker compose ps                         # všetky 4 služby (healthy)?
curl -s localhost:8000/health/deps        # {"ok":true,"db":"ok","grpc":"SERVING","provider":"ok"}
docker compose logs --tail=50 api         # riadky obsahujú [correlation-id]
docker compose logs --tail=50 grpc
python3 scripts/preflight.py              # vysvetlí, čo presne zlyhalo
```

## Porty sú obsadené

Chyba typu `Bind for 0.0.0.0:8000 failed: port is already allocated`.

```bash
lsof -nP -iTCP:8000 -sTCP:LISTEN          # kto drží port (macOS/Linux)
```

Porty na hoste zmeníš v `.env` (vnútri Docker siete sa nič nemení):

```env
API_PORT=8080
GRPC_PORT=50052
PROVIDER_PORT=8003
DB_HOST_PORT=5433        # častý konflikt s lokálnym PostgreSQL
```

Potom `docker compose up -d` a skripty spúšťaj s `BASE_URL=http://localhost:8080 python3 scripts/preflight.py`.
Pozor: WSDL ohlasuje adresu `SOAP_ADDRESS` (default `http://localhost:8000/soap`). Pri inom porte uprav aj ju v `docker-compose.yml`.

## Docker nebeží / „Cannot connect to the Docker daemon“

Spusti Docker Desktop a počkaj, kým ikona ukáže *running*. Over to cez `docker info`.

## Build zlyhá na sieti (pip)

Build potrebuje internet raz (pip balíky, `postgres:16-alpine`). Potom všetko beží offline.
Ak `pip` pri builde opakuje `Retrying … NewConnectionError` (prerušovaná sieť v BuildKite), zopakuj build
alebo použi `docker build --network=host -t ticketflow-api:local .` a potom `docker compose up --build -d` (vrstva s balíkmi sa vezme z cache).
Verzie všetkých balíkov sú zamknuté v `requirements.lock` (pip constraints).
Za firemným proxy nastav proxy v Docker Desktop → Settings → Resources → Proxies.
Swagger UI assets sú v repozitári (`frontend/vendor/`), takže na ne sieť netreba.

## Služba nie je healthy

- `api` čaká na `db` (healthcheck `pg_isready`). Ak DB štartuje pomaly, `docker compose up -d` stačí zopakovať.
- `api` hlási `WEBHOOK_SECRET nie je nastavený`: v `.env` je prázdna hodnota. Vymaž riadok alebo doplň hodnotu.
- Po zmene schémy (napr. po aktualizácii kódu) zmaž volume: `docker compose down -v && docker compose up --build -d`.

## Panel ukazuje „API je nedostupné“

API nebeží alebo je na inom porte. Pozri `docker compose ps`. Na prezentácii prejdi na CLI fallback alebo na `docs/SCREENSHOTS/fallback.html`.

## WebSocket sa nepripája

- Proxy, VPN alebo rozšírenie prehliadača môže blokovať `ws://localhost`. Skús okno bez rozšírení.
- Klient ukazuje „ODPOJENÝ“: klikni **Pripojiť**. Stav sa obnoví zo snapshotu.
- API musí bežať s 1 workerom (je tak nastavené). S viacerými workermi by broadcast nedošiel všetkým klientom.

## gRPC: `UNAVAILABLE`

`docker compose logs grpc`. Služba musí ukázať „gRPC Inventory počúva na porte 50051“. API sa pripája na `grpc:50051` cez Docker sieť. Port na hoste je len pre externých klientov. Server nemá reflection, takže `grpcurl` potrebuje kontrakt:
`grpcurl -plaintext -proto grpc_service/inventory.proto -d '{"event_id":"42","seat_id":"A7"}' localhost:50051 ticketflow.inventory.v1.Inventory/CheckSeat`.
Kontrola zvnútra: `docker compose exec grpc python -m grpc_service.client --target 127.0.0.1:50051 --seat A7 --delay-ms 800 --deadline-ms 200`.

## GraphQL ukazuje iný počet ako 101/2

Nezatajuj to. Pozri SQL log v paneli: každý riadok je skutočný príkaz. Napríklad pridanie poľa `name` do query pridá 1 dotaz.
`python3 scripts/demo_graphql.py --seats 100 --compare` vypíše prvé príkazy.

## Webhook vždy 401

- Provider a API musia mať rovnaký `WEBHOOK_SECRET` (oba ho berú z rovnakej premennej v `docker-compose.yml`).
- `STALE_TIMESTAMP`: hodiny kontajnera sa líšia o viac ako 300 s. Reštartuj Docker Desktop (synchronizuje čas VM).

## Testy

```bash
docker compose exec api pytest -q
docker compose exec api pytest -q tests/test_graphql_n_plus_one.py -vv
```

Testy bežia proti živým službám a resetujú dáta.

## Screenshoty

`python3 scripts/screenshots.py` hľadá Google Chrome/Chromium. Inú cestu nastavíš cez `CHROME=/cesta/k/chrome`.
