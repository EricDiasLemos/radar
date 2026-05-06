.PHONY: up down scan apply logs dashboard open

# Sobe tudo
up:
	docker compose up -d --build
	@echo ""
	@echo "Dashboard: http://localhost:8080"

# Para tudo
down:
	docker compose down

# Scan manual (roda agora, não espera o horário agendado)
scan:
	docker compose exec scanner python scripts/main.py scan

# Candidatura manual: make apply JOB_ID=abc123
apply:
	@test -n "$(JOB_ID)" || (echo "Uso: make apply JOB_ID=<id>" && exit 1)
	docker compose exec scanner python scripts/main.py apply $(JOB_ID)

# Logs do scanner em tempo real
logs:
	docker compose logs -f scanner

# Abre o dashboard no browser (Linux/Mac)
open:
	xdg-open http://localhost:8080 2>/dev/null || open http://localhost:8080 2>/dev/null || \
	echo "Abra manualmente: http://localhost:8080"

# Rebuild sem cache
rebuild:
	docker compose build --no-cache
	docker compose up -d

# Status dos containers
ps:
	docker compose ps
