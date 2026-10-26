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
