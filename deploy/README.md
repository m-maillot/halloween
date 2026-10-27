# Déploiement

Unité `systemd`, script d'installation sur le Raspberry Pi et configuration d'exemple.

Voir la spec : [docs/spec-1-moteur.md](../docs/spec-1-moteur.md) (§3, §6.3).

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

## Installer le service sur le Pi

```bash
git clone https://github.com/m-maillot/halloween.git && cd halloween
sudo deploy/install.sh            # ou --dry-run pour voir ce qui serait fait
```

Le script (relançable sans risque, il ne touche ni la configuration ni les données existantes) :

| Étape | Résultat |
|---|---|
| Compte système `halloween` | membre du groupe `gpio` (accès aux relais et au bouton), sans shell |
| Python | `venv` dans `/opt/halloween/venv`, moteur installé avec l'extra `pi` (gpiozero, lgpio) |
| Données | `/var/lib/halloween` (config, programmes, images, code de verrouillage, `api-token`), config d'exemple copiée si absente |
| Surcharges | `/etc/halloween/halloween.env` (`HALLOWEEN_UI_DIR`, `HALLOWEEN_HA_TOKEN`…), vide par défaut |
| Service | [`halloween-engine.service`](halloween-engine.service) activé au démarrage et lancé |

Le jeton d'API se lit avec `sudo cat /var/lib/halloween/api-token`. Mettre à jour : `git pull && sudo deploy/install.sh`. Retirer : `sudo deploy/install.sh --uninstall` (les données sont conservées).

### Reprise après incident

| Incident | Réaction |
|---|---|
| Plantage du processus | `Restart=always` : relancé en 2 s ; tous les relais sont éteints au démarrage, avant toute autre action |
| Gel de la boucle d'exécution | le moteur envoie un signal de vie à `systemd` toutes les `WatchdogSec / 2` (10 s) ; sans signal pendant `WatchdogSec` (20 s), `systemd` tue le processus puis le relance |
| Arrêt (`systemctl stop`, extinction) | SIGTERM : scénarios arrêtés, relais éteints, broches libérées (15 s au plus avant SIGKILL) |

Pas de watchdog matériel du Pi (voir la spec). Pendant les quelques secondes d'un gel, les relais gardent leur dernier état : le STOP du bouton physique ne fonctionne pas non plus tant que le moteur est gelé.
