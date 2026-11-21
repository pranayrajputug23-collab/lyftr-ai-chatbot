.PHONY: up down logs rebuild clean

up:
	docker compose up --build -d

down:
	docker compose down

logs:
	docker compose logs -f

rebuild:
	docker compose build --no-cache

# Removes local Compose images and containers, but keeps the SQLite volume.
clean:
	docker compose down --rmi local
