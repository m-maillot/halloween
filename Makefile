.PHONY: test lint format check openapi ui-install ui-api ui-check

test:  ## Lance les tests du moteur
	cd engine && uv run pytest

lint:  ## Vérifie le style (ruff)
	cd engine && uv run ruff check . && uv run ruff format --check .

format:  ## Formate le code
	cd engine && uv run ruff check --fix . && uv run ruff format .

check: lint test  ## Lint + tests

openapi:  ## Régénère le contrat OpenAPI versionné (docs/openapi.json)
	cd engine && uv run python -m halloween.api.openapi --output ../docs/openapi.json

ui-install:  ## Installe les dépendances de l'interface
	cd ui && npm ci

ui-api:  ## Régénère les types du client d'API depuis docs/openapi.json
	cd ui && npm run gen:api

ui-check:  ## Interface : types à jour, typage, tests, build
	cd ui && npm run gen:api && git diff --exit-code src/api/schema.d.ts
	cd ui && npm run typecheck && npm test && npm run build
