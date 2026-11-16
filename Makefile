.PHONY: up down package dist
up:
	docker compose up --build -d
down:
	docker compose down
package:
	./scripts/package.sh docker
dist:
	./scripts/package.sh dist
