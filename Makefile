.PHONY: help up down up-p1 down-p1 analysis-p1 up-p2 down-p2 test test-p1 test-p2 ingest api lint

help:
	@echo "Atalhos disponiveis:"
	@echo "  make up          - sobe os dois projetos (part1 + part2) via docker compose"
	@echo "  make down        - derruba os containers dos dois projetos"
	@echo "  make up-p1       - roda o pipeline completo da Parte 1 (ingest->transform->quality->analysis)"
	@echo "                     e imprime as 3 respostas (executa o notebook via papermill)"
	@echo "  make analysis-p1 - alias de 'make up-p1' (nome usado no mini-spec da Parte 1)"
	@echo "  make up-p2       - sobe so a Parte 2 (api + redis)"
	@echo "  make test        - roda os testes de part1 e part2"
	@echo "  make test-p1     - roda so os testes da Parte 1"
	@echo "  make test-p2     - roda so os testes da Parte 2"
	@echo "  make ingest      - roda so a ingestao da Parte 1 (PokeAPI), sem o resto do pipeline"
	@echo "  make api         - sobe a API de NER da Parte 2 (modo dev, sem docker)"
	@echo "  make lint        - roda lint (ruff/black) nos dois projetos"

up: up-p1 up-p2

down: down-p1 down-p2

# Roda em foreground (sem -d): a Parte 1 e um job batch, nao um servidor - o
# criterio de pronto e ver as 3 respostas impressas no terminal (nao faz sentido
# rodar destacado).
up-p1:
	docker compose -f part1-pokeapi-analytics/docker-compose.yml up

analysis-p1: up-p1

down-p1:
	docker compose -f part1-pokeapi-analytics/docker-compose.yml down

up-p2:
	docker compose -f part2-ner-serving/docker-compose.yml up -d

down-p2:
	docker compose -f part2-ner-serving/docker-compose.yml down

test: test-p1 test-p2

test-p1:
	cd part1-pokeapi-analytics && pytest

test-p2:
	cd part2-ner-serving && pytest

ingest:
	cd part1-pokeapi-analytics && python -m src.ingest

api:
	cd part2-ner-serving && uvicorn src.api.main:app --reload

lint:
	cd part1-pokeapi-analytics && ruff check . && black --check .
	cd part2-ner-serving && ruff check . && black --check .
