FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /srv

COPY requirements.txt requirements-dev.txt requirements.lock ./
RUN pip install --no-cache-dir -c requirements.lock -r requirements.txt -r requirements-dev.txt

COPY . .
# gRPC stuby generujeme pri builde z kontraktu
RUN python -m grpc_tools.protoc -I . --python_out=. --grpc_python_out=. --pyi_out=. grpc_service/inventory.proto \
 && python scripts/fetch_swagger_assets.py \
 && useradd --create-home --uid 10001 app && chown -R app /srv
USER app

EXPOSE 8000 50051 8002
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
