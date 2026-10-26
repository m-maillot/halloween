# Procédure de test matériel (Raspberry Pi)

À dérouler **une fois sur votre Raspberry Pi**, dans l'ordre, avant de brancher les objets de la déco. Elle valide le câblage, les niveaux des relais et le bouton, puis un scénario complet.

> **Sécurité.** Les premières étapes se font **sans aucune charge** sur les relais. Si les relais commutent du 230 V, faites vérifier le montage (isolation, boîtier, fusible) par une personne compétente : ce logiciel ne remplace pas la protection électrique.

Chaque étape indique quoi lancer, ce qu'il faut observer, et quoi faire si ça ne correspond pas. Cochez la case quand c'est bon.

## 0. Installation

- [ ] Raspberry Pi OS avec Python ≥ 3.11 (`python3 --version`), `git` et [uv](https://docs.astral.sh/uv/).
- [ ] Récupérer le code et installer le moteur avec les pilotes GPIO :

```bash
git clone git@github.com:m-maillot/halloween.git && cd halloween/engine
uv sync --extra pi
```

Si l'installation de `lgpio` échoue : `sudo apt install swig python3-dev python3-lgpio`, puis relancer. Sur un Pi 5, `lgpio` est obligatoire.

- [ ] Préparer un dossier de données (sans `sudo` pour les essais) à partir de la configuration d'exemple :

```bash
mkdir -p ~/halloween-data/programs
cp ../deploy/config.example.json ~/halloween-data/config.json
cp ../deploy/programs-example/scenario-principal.json ~/halloween-data/programs/
export HALLOWEEN_DATA_DIR=~/halloween-data
```

Les commandes suivantes utilisent ce dossier (sinon, ajouter `--data-dir ~/halloween-data` avant la sous-commande). Les modifications de la configuration (`active_low`, broches…) se font dans `~/halloween-data/config.json`.

## 1. Câblage à vide

Pi **hors tension** pour câbler.

| Élément | Connexion |
|---|---|
| Module 4 relais, alimentation | 5 V et GND du Pi |
| Entrée Fantôme | GPIO 18 |
| Entrée Squelette | GPIO 17 |
| Entrée Épouvantail | GPIO 27 |
| Entrée Orage | GPIO 22 |
| Bouton | GPIO 21 ↔ GND (résistance de rappel interne activée : `pull: up`) |

(Numérotation **BCM** : « GPIO 18 » et non « broche physique 18 ».)

- [ ] Aucun objet branché sur les contacts des relais.
- [ ] Mise sous tension du Pi.

## 2. Vérification de l'environnement GPIO

```bash
uv run halloween-cli gpio-check
```

À observer :

- [ ] « Matériel : Raspberry Pi … » affiche bien votre modèle.
- [ ] « Bibliothèque de broches : **LGPIOFactory** » (sur un Pi 5, c'est obligatoire ; un avertissement est affiché sinon).
- [ ] Une ligne `OK … au repos` par relais, aucun `ÉCHEC`.

Si un relais est en `ÉCHEC` au repos, ou si un relais **clique dès la mise sous tension du Pi / du script** : votre module est probablement **actif à l'état bas** → mettre `"active_low": true` pour les 4 relais dans `config.json` puis relancer. Noter que, avant le démarrage du logiciel, une broche non pilotée est « flottante » et peut faire cliquer un module actif-bas au moment du démarrage du Pi : c'est une limite du matériel, pas du logiciel.

## 3. Test actif des relais et du bouton

```bash
uv run halloween-cli gpio-check --active
```

Les relais vont **cliquer l'un après l'autre**, puis il vous est demandé d'appuyer sur le bouton.

- [ ] Vous entendez 4 « clic » (un par relais, dans l'ordre fantôme, squelette, épouvantail, orage), puis 4 « clac » de retour au repos.
- [ ] Chaque relais affiche `OK … actif`.
- [ ] L'appui sur le bouton est détecté (`appui short détecté`).
- [ ] Après la commande, aucun relais ne reste collé.

Un relais qui ne clique pas alors que la ligne est `OK` : vérifier son alimentation 5 V et le câble du signal. Si **tous** les relais font l'inverse de ce qui est attendu : `active_low`.

## 4. Relais un par un

```bash
uv run halloween-cli relay list
uv run halloween-cli relay fantome on --for 3
uv run halloween-cli relay squelette on --for 3
uv run halloween-cli relay epouvantail on --for 3
uv run halloween-cli relay orage on --for 3
```

- [ ] Chaque commande fait coller le bon relais pendant 3 s puis le relâche.
- [ ] `relay <id> on` sans `--for` reste allumé jusqu'à **Ctrl+C**, qui éteint le relais.
- [ ] Bon relais pour le bon nom (sinon, corriger les `pin` dans `config.json`).

## 5. Bouton

```bash
uv run halloween-cli button watch
```

Faire : un appui court, un appui long (> 0,8 s), un double appui rapide.

- [ ] Les trois événements `short`, `long`, `double` sont reconnus correctement.
- [ ] Un seul appui ne produit **pas** plusieurs événements (sinon augmenter `debounce_ms`, ex. 80, dans `config.json`).
- [ ] L'appui court est confirmé environ 0,4 s après le relâchement (c'est normal : c'est le délai d'attente d'un éventuel second appui, réglable par `double_press_ms`).

## 6. Branchement des objets

Pi **hors tension** (ou module relais débranché) pour chaque branchement.

- [ ] Brancher **un seul objet à la fois** sur son relais, puis le tester avec `relay <id> on --for 2`.
- [ ] Répéter pour les quatre objets.
- [ ] Vérifier qu'aucun objet ne reste alimenté une fois la commande terminée.

## 7. Scénario complet

D'abord à blanc (rien n'est actionné) :

```bash
uv run halloween-cli simulate scenario-principal
```

- [ ] La liste des commandes est cohérente (bandeau rouge à 0 s, orage et fantôme à 3 s, squelette à 11 s, épouvantail à 17 s).

Puis pour de vrai :

```bash
uv run halloween-cli run scenario-principal
```

> Pour l'instant **Home Assistant est simulé** : les commandes du bandeau et de la guirlande sont seulement affichées (`[Home Assistant simulé] …`), pas envoyées. Les relais, eux, sont réels. L'intégration réelle arrive au lot 3.

- [ ] Les relais s'enclenchent aux bons moments (≈ 17 s au total) puis tout revient au repos à la fin.
- [ ] **Ctrl+C en plein scénario** : tous les relais retombent immédiatement et la commande se termine.
- [ ] `kill -TERM <pid>` (ou arrêt du service) a le même effet.

## 8. Ce qu'il faut me renvoyer

Si quelque chose ne correspond pas, copier-coller :

- la sortie complète de `halloween-cli gpio-check --active` ;
- le modèle de Pi (`cat /proc/device-tree/model`) et la version de Raspberry Pi OS ;
- la référence exacte du module relais (actif haut ou bas, alimentation) ;
- ce que vous avez observé (quel relais, quel bruit, quel moment).

## Dépannage rapide

| Symptôme | Piste |
|---|---|
| `matériel inutilisable : BadPinFactory` | `lgpio` absent : `uv sync --extra pi`, ou paquet `python3-lgpio` |
| `Permission denied` sur les GPIO | être dans le groupe `gpio` : `sudo usermod -aG gpio $USER`, puis se reconnecter |
| Relais inversés (collé au repos, relâché en marche) | `active_low: true` pour les 4 relais |
| Un relais clique à chaque mise sous tension du Pi | broche flottante avant le démarrage du logiciel (module actif-bas) : limite matérielle, voir §2 |
| Plusieurs événements pour un seul appui | augmenter `debounce_ms` du bouton |
| Rien ne se passe sans erreur | vérifier le dossier de données (`--data-dir` / `HALLOWEEN_DATA_DIR`) |
