"""Centrálna konfigurácia z prostredia (docker-compose / .env). Secret sa nikdy neloguje."""
import os

# ═══ 1. Pripojenia ═══
DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql+psycopg://ticketflow:ticketflow@localhost:5432/ticketflow"
)
GRPC_TARGET = os.getenv("GRPC_TARGET", "localhost:50051")
PROVIDER_URL = os.getenv("PROVIDER_URL", "http://localhost:8002")
SOAP_ADDRESS = os.getenv("SOAP_ADDRESS", "http://localhost:8000/soap")   # adresa zapísaná do WSDL
SELF_URL = os.getenv("SELF_URL", "http://127.0.0.1:8000")

# ═══ 2. Webhooky (Demo D) ═══
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "")          # zdieľaný HMAC secret — NIKDY nelogovať
WEBHOOK_TOLERANCE_SECONDS = int(os.getenv("WEBHOOK_TOLERANCE_SECONDS", "300"))   # okno proti replayu

# ═══ 3. Demo ═══
DEMO_MODE = os.getenv("DEMO_MODE", "true").lower() == "true"   # false → vypne zapisujúce /demo endpointy
DEMO_EVENT_ID = "42"
DEMO_SEAT_ID = "A7"
GRAPHQL_MAX_LIMIT = 100
