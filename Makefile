.PHONY: test lint format check openapi

test:  ## Lance les tests du moteur
	cd engine && uv run pytest

lint:  ## Vérifie le style (ruff)
	cd engine && uv run ruff check . && uv run ruff format --check .

format:  ## Formate le code
	cd engine && uv run ruff check --fix . && uv run ruff format .

check: lint test  ## Lint + tests

openapi:  ## Régénère le contrat OpenAPI versionné (docs/openapi.json)
	cd engine && uv run python -m halloween.api.openapi --output ../docs/openapi.json
