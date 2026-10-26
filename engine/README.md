# Moteur

Service Python qui tourne sur le Raspberry Pi : catalogue de composants, interprétation des scénarios, déclencheurs, API HTTP/WebSocket.

Spécification : [docs/spec-1-moteur.md](../docs/spec-1-moteur.md).

Arborescence cible (créée au fil des lots) :

```
src/halloween/
  config/     modèles et stockage (composants, HA, état de repos)
  program/    modèle de programme, validation, interpréteur
  drivers/    interfaces + implémentations réelle / fictive (relais, boutons, HA)
  triggers/   boutons, planning
  api/        FastAPI, WebSocket, verrouillage, images
  cli.py      halloween-cli
tests/
```

## Développement

Prérequis : Python 3.11+ et [uv](https://docs.astral.sh/uv/).

```bash
make test     # lance les tests (depuis la racine du dépôt)
make check    # lint + tests
make format   # formate le code
```

Sur le Raspberry Pi, installer aussi les pilotes GPIO : `uv sync --extra pi`. Si la compilation de `lgpio` échoue, installer le paquet système (`sudo apt install python3-lgpio`) ou ses dépendances de build (`swig`, `python3-dev`) ; la compatibilité GPIO du Pi utilisé est vérifiée à part (issue du lot 2).

## Essayer sans Home Assistant

Un faux serveur Home Assistant (entités d'exemple, journal des requêtes) permet d'essayer le moteur sans installation :

```bash
uv run python -m halloween.testing.fake_ha --port 8123 --token mon-jeton
```

Puis, dans `config.json`, `"home_assistant": {"url": "http://localhost:8123", "token": "mon-jeton"}` (ou `HALLOWEEN_HA_TOKEN=mon-jeton`). Les entités et leurs capacités sont des valeurs d'exemple.
