# Déco Halloween

Application pour enchaîner des actions (façon Scratch) sur une décoration d'Halloween : relais pilotés par GPIO sur un Raspberry Pi, bouton physique, et appareils Home Assistant (lumières Hue, guirlande Twinkly).

Deux parties :

1. **Moteur** (Python, sur le Raspberry Pi) : catalogue de composants, interprétation des scénarios, déclencheurs, API.
2. **Interface** (React + Blockly) : configuration, éditeur de blocs, mode spectacle, verrouillage par code.

## Documents

- [Spec 1 — Moteur d'exécution](docs/spec-1-moteur.md)
- [Spec 2 — Interface](docs/spec-2-interface.md)
- [Plan d'implémentation](docs/plan-implementation.md)

Le suivi se fait par **jalons** (un par phase du plan) et **issues** : voir l'onglet *Milestones* du dépôt. Le backlog est défini dans [`scripts/create-backlog.py`](scripts/create-backlog.py) (labels, jalons, issues ; `--dry-run` pour prévisualiser).

## Statut

Phase de spécification terminée, développement non commencé.
