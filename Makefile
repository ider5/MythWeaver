.PHONY: up down package dist config
up:
	docker compose up --build -d --wait
down:
	docker compose down
config:
	docker compose config
package:
	./scripts/package.sh docker
dist:
	./scripts/package.sh dist
