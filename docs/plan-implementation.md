# Plan d'implémentation

Statut : brouillon v0.1 — 2026-10-26
Références : [spec 1 — Moteur](spec-1-moteur.md), [spec 2 — Interface](spec-2-interface.md), maquettes (canvas « Maquettes Halloween »)

Les durées sont des ordres de grandeur en jours de travail effectif pour une personne, à réviser après la phase 1.

## 1. Principes

- **Sans matériel d'abord.** Tout le cœur (format, validation, interpréteur, déclencheurs, API) est développé et testé avec des drivers fictifs et une horloge virtuelle, sur le poste de développement. Le Pi n'intervient qu'à partir de la phase 2.
- **Tranches verticales.** Chaque phase se termine par quelque chose d'utilisable et de testé, pas par une couche technique isolée.
- **Test matériel tôt, sans charge.** Les relais sont validés seuls (sans objet branché) avant tout scénario.
- **Contrat d'abord.** L'API est décrite par l'OpenAPI générée par FastAPI ; l'interface s'appuie sur elle (client TypeScript généré) et sur le moteur en mode simulation.
- **Deux jalons utilisables** : A (fin phase 6) moteur complet, pilotable en ligne de commande ; B (fin phase 11) application complète.

## 2. Structure du dépôt

```
halloween/
  docs/                  specs, plan, maquettes
  engine/                moteur Python
    src/halloween/
      config/            modèles et stockage (composants, HA, état de repos)
      program/           modèle de programme, validation, interpréteur
      drivers/           interfaces + implémentations réelle / fictive (relais, boutons, HA)
      triggers/          boutons, planning
      api/               FastAPI, WebSocket, verrouillage, images
      cli.py             halloween-cli
    tests/
  ui/                    React + Vite + Blockly
  deploy/                unité systemd, script d'installation, config d'exemple
```

Outils proposés : Python 3.11+, `uv`, `pytest` + `pytest-asyncio`, `ruff`, Pydantic v2, FastAPI, `httpx`, `gpiozero` avec le pilote `lgpio` (compatible Pi 5), `APScheduler` ou boucle `cron` maison pour le planning. Côté interface : Vite, React, TypeScript, Blockly, Vitest, Playwright.

## 3. Phases du moteur

### Phase 0 — Socle du projet (≈ 1 j)
- Dépôt git, structure ci-dessus, `pyproject.toml`, `ruff`, `pytest`, commande unique de test.
- Journalisation JSON lines avec `run_id` / `node_id`.
- Fichier d'exemple `config.json` avec vos 4 relais (18, 17, 27, 22, `active_low: false`, `latched`) et le bouton (21).

**Terminé quand** : `pytest` s'exécute (même vide) et le projet s'installe proprement sur un poste neuf.

### Phase 1 — Cœur sans matériel (≈ 5 j)
- Modèles Pydantic : composants (relais, bouton, light, switch, image `builtin:`), programme (`scripts`, `hat`, blocs de contrôle et d'action), validation complète (pins en double, paramètres non supportés par les capacités, mode de relais incompatible, références inconnues, profondeur de `call`).
- Interfaces `RelayDriver`, `ButtonDriver`, `HAClient` et leurs versions fictives qui enregistrent les appels.
- Interpréteur `asyncio` : `sequence`, `parallel`, `repeat`, `wait` (fixe et aléatoire), `if`, `wait_until`, `random_choice`, `call`, `log` ; actions `relay`, `light`, `switch` ; erreurs par bloc (`on_error`, continuer par défaut) ; `max_duration_s` optionnel.
- Horloge injectable et **mode simulation** : timeline `[(t, composant, action)]`.
- Gestionnaire de runs : plusieurs runs simultanés, un seul par programme avec politique `ignore` / `restart` / `queue`, stop individuel et global (< 1 s), reset d'état de repos selon « dernier à avoir écrit » (spec 1, 5.3).
- Persistance fichiers (`config.json`, `programs/*.json`, `triggers.json`) avec écriture atomique et révisions de programme.

**Terminé quand** : les critères 4, 6, 8, 9 et 12 de la spec 1 passent en tests automatiques, dont le test de l'exemple « scénario principal » et d'un programme à deux scripts en parallèle.

### Phase 2 — Matériel réel : relais et bouton (≈ 2 j, sur le Pi)
- Drivers GPIO réels : relais (`high()` = actif, sorties initialisées à OFF avant tout), bouton (pull-up, anti-rebond, appui court / long / double).
- `halloween-cli relay <id> on|off`, `halloween-cli button watch`, `halloween-cli run <id>`.
- Procédure de test matériel documentée, **sans charge branchée** : chaque relais s'enclenche (clic audible) puis s'éteint ; le bouton émet les bons événements ; relais OFF au démarrage et à l'arrêt.
- Premier test avec les objets, un par un, ensuite le scénario complet.

**Terminé quand** : le scénario exemple tourne sur le Pi avec les vrais relais lancé en ligne de commande, et un `Ctrl+C` / `SIGTERM` laisse tout éteint.

### Phase 3 — Home Assistant (≈ 2 j)
- Client `httpx` : `light/turn_on|turn_off` (corps `rgb_color`, `brightness`, `transition`), `switch/turn_on|turn_off`, `GET /api/` pour tester la connexion, liste des entités `light` / `switch`.
- Gestion des erreurs : délai d'attente, injoignable, jeton refusé ; le run continue (spec 1, 6.2).
- Tests contre un faux serveur HTTP (corps JSON exacts) ; puis essai réel sur le bandeau Hue et la guirlande Twinkly.
- **À vérifier sur votre instance** : les entités `light.*` exactes et ce que Twinkly accepte (couleur, luminosité, transition), pour fixer les capacités de chaque light.

**Terminé quand** : un scénario mêlant relais et lumières tourne sur le Pi, et la coupure de Home Assistant en cours de run n'arrête pas les relais (critère 6).

### Phase 4 — Déclencheurs et reprise (≈ 2 j)
- Déclencheurs : bouton + événement → programme ou arrêt, avec politique ; planning cron ; vérifications (programme existant, doublons).
- Appui long = arrêt d'urgence par défaut.
- Reprise : relais OFF et état de repos au démarrage, rechargement de la config et des déclencheurs.

**Terminé quand** : l'appui sur le bouton physique lance le scénario, l'appui long l'arrête en < 1 s, un redémarrage du Pi remet tout au repos (critères 5 et 7).

### Phase 5 — API HTTP et temps réel (≈ 4 j)
- Routes de la spec 1 (section 8) : composants, appareils, entités HA, images (redimensionnement), programmes + validation, runs, simulation, déclencheurs, statut.
- WebSocket `/events` : `run_started`, `node_started`, `node_finished`, `component_changed`, `button_event`, `lock_changed`, `run_ended`, `error`.
- Authentification par jeton ; service des fichiers statiques de l'interface sur `/`.
- Contrat OpenAPI exporté et figé pour l'interface.

**Terminé quand** : toute la configuration et un scénario complet se pilotent avec `curl` / un client WebSocket, et l'OpenAPI est publiée.

### Phase 6 — Verrouillage, durcissement, déploiement (≈ 3 j)
- Verrouillage (spec 1, 6.4) : empreinte du code, `423` sur les écritures, code exigé à chaque lancement, STOP libre, limitation des essais, persistance, réinitialisation CLI.
- Unité `systemd` : `Restart=always`, `WatchdogSec`, signal de vie, arrêt propre ; script d'installation sur le Pi.
- Journal avec rotation ; `GET /status` complet.

**Jalon A** : tous les critères d'acceptation de la spec 1 sont validés (suite de tests + essais réels).

## 4. Phases de l'interface

La phase 7 peut démarrer dès la fin de la phase 5 (contrat figé), en parallèle des phases 4 et 6, en utilisant le moteur en mode simulation.

### Phase 7 — Socle de l'interface (≈ 2 j)
- Projet Vite + React + TypeScript, client d'API généré depuis l'OpenAPI, gestion du jeton, WebSocket avec reconnexion et resynchronisation.
- Thème sombre et composants de base d'après les maquettes (boutons, pastilles d'état, tuiles, formulaires), mise en page de l'application (barre latérale, bandeau avec STOP et cadenas).
- Gestion des erreurs d'API (toasts), état « moteur hors ligne ».

### Phase 8 — Composants, tableau de bord, réglages (≈ 5 j)
- Écran **Composants** : quatre onglets, formulaires (pins grisées, modes, capacités des lights, liste des entités HA), téléversement d'image, test manuel, refus de suppression d'un composant utilisé.
- **Tableau de bord** : tuiles en direct, interrupteurs de test, runs en cours avec progression et arrêt individuel.
- **Réglages** : connexion Home Assistant avec test, jeton du moteur, état de repos, code de verrouillage.

### Phase 9 — Éditeur de blocs (≈ 8 j) — la partie la plus risquée
- Intégration Blockly : zone de montage, thème, barre d'outils (nom, Valider, Simuler, Enregistrer, Lancer).
- Blocs générés depuis `/devices` (image + nom, menus et paramètres selon les capacités) ; blocs de contrôle dont le bloc **début** (plusieurs par scénario).
- Sérialisation blocs ↔ JSON de la spec 1, avec champ `editor` pour la mise en page ; tests d'aller-retour sans perte.
- Validation en direct (bloc fautif en rouge, avertissement de conflit entre scripts), simulation en frise temporelle, exécution avec **surlignage du bloc actif** dans chaque script, enregistrement avec gestion de conflit de révision.
- Brouillon dans le navigateur, avertissement avant de quitter.

### Phase 10 — Déclencheurs, mode spectacle, verrouillage (≈ 4 j)
- Écran **Déclencheurs** (règles lisibles, constructeur de planning, alerte de doublons).
- **Mode spectacle** : grandes tuiles, scénarios cochés seulement, STOP, écran maintenu allumé, route `/spectacle`.
- **Verrouillage** : cadenas, pavé numérique, code demandé à chaque lancement quand c'est verrouillé, états en lecture seule, réaction à `lock_changed`.

### Phase 11 — Finitions et recette (≈ 4 j)
- Bibliothèque d'icônes (game-icons.net + Lucide) avec page « À propos » pour les attributions ; vérification des licences.
- Tests de bout en bout Playwright sur le moteur en simulation ; essai visuel sur tablette et téléphone.
- Build statique servi par le moteur, déploiement sur le Pi, documentation d'exploitation (installation, sauvegarde du dossier de données, réinitialisation du code, dépannage).
- Recette complète à partir des critères d'acceptation des deux specs.

**Jalon B** : application complète, utilisable le soir d'Halloween.

## 5. Ordre et parallélisme

```
Phase 0 → 1 → 2 → 3 → 4 → 6          (moteur, en séquence)
              └→ 5 ─┬→ 7 → 8 → 9 → 10 → 11   (API puis interface)
                    └→ 6
```

Pour une seule personne, l'ordre proposé est : 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11. Si un temps limité impose de choisir, le **chemin minimal pour une soirée** est : phases 0 à 4 (scénario écrit à la main en JSON, déclenché par le bouton), puis 5 et 6 pour sécuriser, puis l'interface.

Durée indicative totale : ≈ 17 j pour le moteur et ≈ 23 j pour l'interface, soit ≈ 40 j de travail effectif.

## 6. Risques et parades

| Risque | Parade |
|---|---|
| Bibliothèque GPIO incompatible avec le Pi (Pi 5 notamment) | `gpiozero` + `lgpio` ; test du pilote dès la phase 2, avant d'écrire du code qui en dépend |
| Éditeur de blocs plus long que prévu (blocs dynamiques, aller-retour sans perte) | prototype d'un bloc relais + sérialisation en début de phase 9 ; sérialisation testée avant l'habillage |
| Home Assistant : entités Twinkly qui n'acceptent pas toutes les options | capacités par light dans la config, validées dès la phase 3 sur l'installation réelle |
| Relais ou objets qui restent allumés après un incident | OFF au démarrage, reprise `systemd`, signal de vie, STOP global testé à chaque jalon |
| Latence Home Assistant qui déphase les séquences | `fire_and_forget` par bloc, mesure du décalage en phase 3 |
| Perte du code de verrouillage | réinitialisation par la ligne de commande sur le Pi (phase 6) |

## 7. Première étape concrète

Phases 0 et 1 : créer la structure du dépôt, les modèles de config et de programme avec leurs validations, les drivers fictifs et l'interpréteur avec son mode simulation. Elles peuvent démarrer immédiatement, sans matériel, et fixent le cœur dont tout le reste dépend.
