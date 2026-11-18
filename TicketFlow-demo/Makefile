.PHONY: up down ps test preflight reset logs demo-rest demo-rpc demo-graphql demo-webhook screenshots

up:
	docker compose up --build -d
	docker compose ps
down:
	docker compose down
ps:
	docker compose ps
test:
	docker compose exec api pytest -q
preflight:
	python3 scripts/preflight.py
reset:
	python3 scripts/reset_demo.py
logs:
	docker compose logs -f --tail=100
demo-rest:
	python3 scripts/demo_rest.py --reset
demo-rpc:
	python3 scripts/demo_rpc.py --show-wsdl --check-seat A7
	python3 scripts/demo_rpc.py --grpc-delay-ms 800 --deadline-ms 200
demo-graphql:
	python3 scripts/demo_graphql.py --seats 100 --compare
demo-webhook:
	python3 scripts/demo_webhook.py --all-cases
screenshots:
	python3 scripts/screenshots.py
