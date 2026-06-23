.PHONY: init up down logs ps config

init:
	cp -n .env.example .env || true
	mkdir -p data
	cp -n www/index.html data/index.html || true

up:
	docker compose up -d --build

down:
	docker compose down

logs:
	docker compose logs -f --tail=100

ps:
	docker compose ps

config:
	docker compose config
