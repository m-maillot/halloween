# Déploiement

Unité `systemd`, script d'installation sur le Raspberry Pi et configuration d'exemple.

Voir la spec : [docs/spec-1-moteur.md](../docs/spec-1-moteur.md) (§3, §6.3). Le contenu est ajouté aux lots 0 et 6.

## Configuration d'exemple

[`config.example.json`](config.example.json) décrit l'installation actuelle :

| Composant | Broche (BCM) | Mode |
|---|---|---|
| Fantôme | 18 | maintenu (`latched`) |
| Squelette | 17 | maintenu |
| Épouvantail | 27 | maintenu |
| Orage | 22 | maintenu |
| Bouton d'entrée | 21 | entrée, pull-up |

Les relais sont actifs à l'état haut (`active_low: false`, `high()` active le relais) et n'ont pas de durée maximale d'allumage. Le **jeton Home Assistant est vide** : il se renseigne depuis l'interface, jamais dans ce fichier versionné. Les `entity_id` des lumières et leurs capacités sont des valeurs à confirmer sur l'installation réelle (lot 3). Les noms `builtin:` désignent la future bibliothèque d'icônes.

## Programme d'exemple et test sur le Pi

[`programs-example/scenario-principal.json`](programs-example/scenario-principal.json) est un scénario complet utilisant les composants de la configuration d'exemple (copié dans `programs/` du dossier de données). La procédure pas à pas pour valider le matériel est dans [docs/test-materiel.md](../docs/test-materiel.md).
