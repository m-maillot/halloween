# Déco Halloween

Application pour enchaîner des actions (façon Scratch) sur une décoration d'Halloween : relais pilotés par GPIO sur un Raspberry Pi, bouton physique, et appareils Home Assistant (lumières Hue, guirlande Twinkly).

Deux parties :

1. **Moteur** (Python, sur le Raspberry Pi) : catalogue de composants, interprétation des scénarios, déclencheurs, API.
2. **Interface** (React + Blockly) : configuration, éditeur de blocs, mode spectacle, verrouillage par code.

## Documents

- [Spec 1 — Moteur d'exécution](docs/spec-1-moteur.md)
- [Spec 2 — Interface](docs/spec-2-interface.md)
- [Plan d'implémentation](docs/plan-implementation.md)
- [Exploitation : installer, sauvegarder, dépanner](docs/exploitation.md)
- [Recette du jalon A (moteur)](docs/recette-jalon-a.md) · [Recette du jalon B (interface)](docs/recette-jalon-b.md)
- [Procédure de test matériel (Raspberry Pi)](docs/test-materiel.md)
- [Validation sur votre Home Assistant](docs/test-home-assistant.md)

Le suivi se fait par **jalons** (un par phase du plan) et **issues** : voir l'onglet *Milestones* du dépôt. Le backlog est défini dans [`scripts/create-backlog.py`](scripts/create-backlog.py) (labels, jalons, issues ; `--dry-run` pour prévisualiser).

## Statut

Moteur et interface réalisés (lots 0 à 11) ; **validés avec du matériel simulé** (broches fictives, faux Home Assistant, navigateur automatisé). Reste la recette sur le matériel réel : voir [docs/recette-jalon-b.md](docs/recette-jalon-b.md) et l'issue de suivi.

## Démarrage rapide

- **Essayer sans matériel** : `cd engine && uv run halloween-cli --data-dir /tmp/demo api --simulate` (après `mkdir /tmp/demo && echo '{}' > /tmp/demo/config.json`), puis l'interface en développement : `make ui-install && cd ui && HALLOWEEN_ENGINE=http://127.0.0.1:8080 npm run dev`.
- **Vérifier le code** : `make check` (moteur) · `make ui-check` (interface) · `make ui-e2e` (parcours Playwright).
- **Installer sur le Pi** : [docs/exploitation.md](docs/exploitation.md) (installation, sauvegarde, code perdu, dépannage, liste de contrôle du soir).
