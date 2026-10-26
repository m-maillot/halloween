# Spec 1 — Moteur d'exécution (Raspberry Pi)

Statut : brouillon v0.4 — 2026-10-26 (v0.4 : scripts parallèles façon Scratch, plusieurs runs simultanés, relais sans limite de durée, `active_low` à `false` ; v0.3 : verrouillage, `show`, images `builtin:`)
Spec suivante : spec 2 — Interface (configuration des composants + éditeur de blocs façon Scratch)

Changements v0.2 : composants configurables (relais à 2 modes, boutons, lights et switches HA avec capacités, images), pins réels, config éditable à chaud par l'API.

## 1. Contexte et objectif

Piloter la décoration d'Halloween par des **scénarios** (séquences d'actions enchaînées) :

- 4 relais pilotés par GPIO : fantôme, squelette, épouvantail, orage ;
- 1 bouton physique en entrée (GPIO 21) qui déclenche le scénario ;
- Home Assistant (HA) via son API REST : lumières (bandeau Hue, guirlande Twinkly…) et interrupteurs.

Le **moteur** tourne sur le Pi. Il gère :
1. un **catalogue de composants** (relais, boutons, lights, switches) configurable, chacun avec nom et image ;
2. des **programmes** (JSON produit par l'éditeur) qui utilisent ces composants ;
3. des **déclencheurs** (bouton, planning, API) qui lancent un programme ;
4. l'**exécution** et l'état temps réel.

Cette spec ne couvre pas l'UI (spec 2), mais définit tout ce dont elle a besoin : modèle de config, format de programme, API.

### Hors périmètre (v1)

Audio, capteurs de présence, multi-utilisateurs, cloud. Extensible via de nouveaux types de composants / blocs.

## 2. Décision d'architecture : programme déclaratif

L'UI produit un **document JSON** (arbre de blocs) que le moteur **interprète**. On ne génère pas de Python exécuté tel quel : pas d'exécution de code arbitraire, arrêt et simulation maîtrisés, validation avant run, correspondance 1 bloc ↔ 1 nœud.

## 3. Vue d'ensemble

```
 UI (spec 2) ──HTTP/WS──►  API (FastAPI)
                              │
   Boutons GPIO ──►  Bus d'événements ──►  Gestionnaire de déclencheurs
   Planning     ──►                              │
                                                 ▼
                                        Interpréteur (asyncio)
                                          │              │
                                   Driver relais     Client HA REST
                                     (GPIO)        (/api/services/…)
```

- **Python 3.11+**, `asyncio`, FastAPI, Pydantic, `httpx` pour HA.
- **GPIO** : `gpiozero` / `libgpiod` (pas `RPi.GPIO` si Pi 5). **Numérotation BCM** (GPIO18 = « PIN 18 »).
- **Service `systemd`** `halloween-engine`, redémarrage automatique.
- **Persistance** : `/var/lib/halloween/` — `config.json`, `programs/*.json`, `triggers.json`, `images/`, logs. Pas de base de données.

## 4. Catalogue de composants (configuration)

Toute la configuration est **stockée dans `config.json` et éditable via l'API** (donc depuis l'UI), sans toucher aux fichiers. Les programmes référencent les composants par `id`, jamais par pin ni entity_id.

Champs communs à tous les composants :

| champ | description |
|---|---|
| `id` | identifiant technique, généré (slug du nom), **immuable** après création |
| `name` | nom affiché (ex. « Fantôme ») |
| `image` | optionnel ; soit un fichier téléversé (nom sous `/images/`), soit une icône de la bibliothèque intégrée à l'UI (`builtin:<nom>`, ex. `builtin:ghost`) ; icône par défaut du type de composant sinon. Le moteur ne valide que le format (`builtin:` + slug, ou fichier existant) ; le catalogue d'icônes appartient à l'UI. |

### 4.1 Relais (GPIO sortie)

| champ | description |
|---|---|
| `pin` | GPIO BCM (sortie) |
| `mode` | `latched` ou `push` (voir ci-dessous) |
| `active_low` | `true` si le module relais s'active à l'état bas (défaut `false` : `high()` active le relais, confirmé sur l'installation actuelle) |
| `pulse_ms` | *(push)* durée de l'impulsion, défaut 500 ms |
| `animation_s` | *(push, optionnel)* durée de l'animation lancée par l'impulsion |
| `max_on_seconds` | *(latched, optionnel)* garde-fou : coupure forcée au-delà. **Absent par défaut = aucune limite** (les objets peuvent rester alimentés en permanence) |

**Mode `latched`** (maintenu) : `on` ferme le relais et il le reste jusqu'à `off`. Pour une lumière, un moteur, une machine qui tourne tant qu'elle est alimentée.

**Mode `push`** (impulsion) : l'action `trigger` ferme le relais `pulse_ms` puis le rouvre ; l'objet joue alors **sa propre animation** (fantôme qui apparaît, squelette qui bouge…). Si `animation_s` est renseigné, le moteur :
- sait combien de temps l'objet est occupé : un nouveau `trigger` pendant ce délai est ignoré (pas de double impulsion) ;
- permet à l'option `wait_for_end` d'un bloc d'attendre la fin de l'animation avant d'enchaîner.

Configuration initiale :

| id | nom | pin | mode |
|---|---|---|---|
| `fantome` | Fantôme | 18 | `latched` |
| `squelette` | Squelette | 17 | `latched` |
| `epouvantail` | Épouvantail | 27 | `latched` |
| `orage` | Orage | 22 | `latched` |

Les quatre sont actuellement en `latched` : l'objet est actif tant que le relais est fermé. Le mode `push` reste disponible pour de futurs équipements.

### 4.2 Boutons (GPIO entrée)

| champ | description |
|---|---|
| `pin` | GPIO BCM (entrée) |
| `pull` | `up` (défaut, bouton vers GND) ou `down` |
| `debounce_ms` | anti-rebond, défaut 50 |
| `long_press_ms` | seuil d'appui long, défaut 800 |
| `double_press_ms` | délai maximal entre deux appuis pour un appui double, défaut 400 (voir ci-dessous) |

Reconnaissance des appuis : **long** dès que le bouton reste enfoncé `long_press_ms` (sans attendre le relâchement) ; **double** si un second appui suit un appui court dans les `double_press_ms` ; **court** sinon. Conséquence : un appui court n'est confirmé qu'après `double_press_ms` (400 ms par défaut), le temps de s'assurer qu'il n'y a pas de second appui.

Configuration initiale : `bouton_principal`, pin 21. L'utilisateur peut en ajouter d'autres. Un bouton **émet des événements** (`short`, `long`, `double`) ; ce qu'ils déclenchent est défini par les déclencheurs (section 7).

### 4.3 Home Assistant (connexion)

```json
{ "url": "http://homeassistant.local:8123", "token": "<jeton longue durée>", "timeout_s": 5 }
```

- Le jeton est stocké côté Pi (fichier en permissions 600), **jamais renvoyé en clair** par l'API (masqué).
- Test de connexion à la saisie (`GET /api/`), état affiché en permanence.
- `timeout_s` (défaut 5 s) : délai maximal d'un appel ; au-delà l'action échoue (et le run continue par défaut, §6.2).
- La variable d'environnement `HALLOWEEN_HA_TOKEN`, si elle est définie, remplace le jeton du fichier (utile en ligne de commande et pour ne pas écrire le jeton sur disque).

### 4.4 Lights HA

Appel HA : `POST /api/services/light/turn_on` ou `turn_off`.

| champ | description |
|---|---|
| `entity_id` | ex. `light.bandeau_hue` |
| `supports_color` | autorise `rgb_color` |
| `supports_brightness` | autorise `brightness` (0-255, valeur native HA) |
| `supports_transition` | autorise `transition` (secondes) |

Les blocs de l'éditeur n'exposent que les paramètres autorisés ; la validation rejette un bloc qui utilise un paramètre non supporté.

Corps envoyé, par exemple :
```json
{ "entity_id": "light.bandeau_hue", "rgb_color": [255, 80, 0], "brightness": 120, "transition": 2 }
```

### 4.5 Switches HA

Appel HA : `POST /api/services/switch/turn_on` ou `turn_off`. Champs : `entity_id` uniquement (en plus des champs communs).

### 4.6 Validation de la configuration

- Pins : chaque GPIO n'est utilisé qu'une fois, dans la liste des GPIO utilisables du Pi ; une pin ne peut pas être à la fois entrée et sortie.
- `entity_id` : doit exister dans HA (vérifié à la création, avec avertissement non bloquant si HA est injoignable).
- Suppression d'un composant utilisé par un programme ou un déclencheur : refusée, avec la liste des usages.
- Changement de pin ou de mode d'un relais : applicable à chaud, les programmes en cours sont arrêtés d'abord.

## 5. Format du programme

```json
{
  "schema": 1,
  "id": "scenario-principal",
  "name": "Scénario principal",
  "max_duration_s": null,
  "on_end": "reset",
  "scripts": [
    { "id": "s1", "hat": { "type": "start" }, "root": { "id": "n1", "type": "sequence", "children": [ ... ] } },
    { "id": "s2", "hat": { "type": "start" }, "root": { "id": "n20", "type": "repeat", "forever": true, "child": { ... } } }
  ]
}
```

- `show` *(booléen, défaut `false`)* : le programme est proposé dans le **mode spectacle** de l'UI ; `show_order` *(entier, optionnel)* : position d'affichage (croissant).
- `editor` *(optionnel)* : métadonnées de mise en page de l'interface (spec 2), ignorées par le moteur, taille limitée (ex. 256 Ko).
- `revision` : numéro incrémenté par le moteur à chaque enregistrement ; `PUT` exige la révision attendue (`If-Match`) pour détecter les conflits.
- `on_end` : `reset` (état de repos, 5.3) ou `keep`.
- `max_duration_s` : arrêt forcé au-delà ; `null` ou absent = aucune limite (nécessaire pour un programme d'ambiance en boucle infinie). Valeur proposée par défaut à la création dans l'UI : aucune.
- `scripts` : **un ou plusieurs scripts**, chacun commençant par un bloc **début** (`hat`). Comme dans Scratch, plusieurs blocs début dans un même programme s'exécutent **en parallèle** dès le lancement. En v1 un seul type de début existe (`start` : au lancement du programme) ; le format prévoit d'autres types (`on_button`, `on_schedule`) sans changement de schéma. Un programme est terminé quand **tous** ses scripts sont terminés.
- Chaque nœud a un `id` unique pour relier erreurs et progression aux blocs de l'UI.

### 5.1 Blocs de contrôle

| type | paramètres | comportement |
|---|---|---|
| `sequence` | `children[]` | l'un après l'autre |
| `parallel` | `children[]`, `until?` (`all` défaut, `first`) | en même temps |
| `repeat` | `times` ou `forever`, `child` | boucle ; `forever` borné par stop / timeout |
| `wait` | `seconds` ou `min`/`max` (aléa) | pause |
| `if` | `condition`, `then`, `else?` | condition évaluée à l'instant T |
| `wait_until` | `condition`, `timeout_s?` | attend une condition |
| `random_choice` | `choices[]` (`weight?`) | tire une branche |
| `call` | `program_id` | sous-programme (profondeur max 5, pas de cycle) |

Conditions v1 : `button` (`id`, `event`), `relay_is` (`id`, `on`/`off`, relais `latched` seulement), `random` (`probability`).

### 5.2 Blocs d'action

| type | composant | paramètres |
|---|---|---|
| `relay` | relais `latched` | `target`, `state`: `on` / `off` |
| `relay` | relais `push` | `target`, `action: "trigger"`, `wait_for_end?` (nécessite `animation_s`) |
| `light` | light | `target`, `state`: `on` / `off`, puis selon capacités : `rgb_color`, `brightness`, `transition` |
| `switch` | switch | `target`, `state`: `on` / `off` |
| `log` | — | `message` |

Règles :
- le bloc `relay` est validé selon le **mode** du relais cible (`on`/`off` interdit sur un `push`, `trigger` interdit sur un `latched`) ;
- par défaut une action HA **attend la réponse** de HA avant de continuer ; `fire_and_forget: true` évite de bloquer le rythme sur la latence ;
- un bloc `light` en `off` ignore couleur / luminosité.

### 5.3 État de repos

Défini dans la config (`rest_state`) : relais `latched` sur OFF, lights / switches dans un état nominal (par composant : on/off + couleur/luminosité). Appliqué au démarrage du moteur, à l'arrêt manuel global et en fin de programme (`on_end: reset`). Les relais `push` ne reçoivent aucune impulsion à ce moment.

Avec plusieurs programmes simultanés, un `reset` de fin de programme ne remet à l'état de repos **que les composants que ce programme a lui-même commandés et dont il est le dernier à avoir modifié l'état** ; un composant repris depuis par un autre programme encore actif n'est pas touché.

## 6. Exécution

### 6.1 Cycle de vie d'un run

Un **run** est une exécution d'un programme ; il contient une tâche asyncio par script. États : `running → (stopping) → ended`, issues : `completed` (tous les scripts terminés), `stopped`, `failed`, `timeout`.

- **Plusieurs runs simultanés** : programmes différents en parallèle (ex. une ambiance de fond en boucle + un scénario déclenché par le bouton), et plusieurs scripts dans un même programme. Pas de limite fixe (garde-fou technique à 20 runs actifs).
- **Un programme n'a qu'un run actif à la fois.** Politique du déclencheur si le programme tourne déjà : `ignore` (défaut), `restart`, `queue`.
- **Conflits d'accès** : comme dans Scratch, aucun verrou sur les composants ; si deux scripts commandent le même composant, **la dernière commande l'emporte**. La validation signale un **avertissement** lorsque deux scripts exécutables en parallèle commandent le même composant. Un `wait` dans un script n'a aucun effet sur les autres.
- **Stop d'un run** : annule ses tâches ; `on_end: reset` s'applique selon 5.3. **Stop global** (`POST /runs/stop`, appui long, STOP de l'UI) : annule **tous** les runs puis applique l'état de repos complet ; effectif en < 1 s.
- **Timeout** (`max_duration_s`) : traité comme un stop de ce run seulement.

### 6.2 Gestion d'erreurs

| Situation | Comportement |
|---|---|
| HA injoignable / `4xx` / `5xx` | l'action échoue, tracée ; par défaut le run **continue** (les relais ne doivent pas se figer) ; `on_error: abort` possible par bloc |
| Composant inconnu, paramètre non supporté | rejeté à la **validation**, avant tout run |
| Exception inattendue dans un script | arrêt du **run** concerné (tous ses scripts), reset selon 5.3, issue `failed` ; les autres runs continuent |

### 6.3 Sécurité

- Relais `latched` **OFF** au démarrage, à l'arrêt du service (`SIGTERM`) et sur toute exception non gérée.
- Si `max_on_seconds` est renseigné pour un relais, il est imposé au niveau du driver, indépendamment des programmes. Sans valeur (cas par défaut), aucune coupure automatique : seuls un `off`, un stop ou l'état de repos éteignent le relais.
- **Reprise après plantage ou gel** : `systemd` relance le service (`Restart=always`) et le moteur éteint tous les relais au démarrage ; un signal de vie périodique à `systemd` (`WatchdogSec`) détecte un gel de la boucle d'exécution. Pas de watchdog matériel.
- Les programmes ne manipulent jamais de GPIO bruts.
- **Verrouillage** (section 6.4) : protège la configuration et les programmes contre toute modification, sans jamais empêcher un STOP.
- ⚠ Si un relais commute du 230 V : isolation et boîtier relèvent du montage, pas du logiciel.

### 6.4 Verrouillage par code

Mode lecture seule protégé par un code, pour éviter les modifications pendant la soirée.

- **Code** : 4 à 8 chiffres. Seule l'empreinte (hachage salé, `argon2` ou `scrypt`) est stockée, dans `/var/lib/halloween/lock.json` (permissions 600), jamais en clair, jamais renvoyée par l'API.
- **État** : `locked` / `unlocked`, persistant au redémarrage. Au premier démarrage, aucun code n'existe : l'état est `unlocked` et le verrouillage n'est possible qu'après définition d'un code.
- **Verrouillé**, sont **refusées avec `423 Locked`** toutes les écritures : composants (création, modification, suppression, **test manuel**), connexion HA, état de repos, programmes, déclencheurs, téléversement d'images, changement du code.
- **Lancement d'un programme** (`POST /runs`) : refusé sans code quand verrouillé. La requête doit alors contenir le code (`{program_id, code}`), vérifié à chaque lancement ; sans code ou code faux : `423` / `401`. Le code n'ouvre pas de session : il ne vaut que pour ce lancement.
- **Restent autorisés sans code**, même verrouillé : toutes les lectures, **`POST /runs/stop` et les arrêts individuels (STOP n'est jamais soumis au code, par sécurité)**, `POST /unlock`, et l'exécution normale des déclencheurs (bouton physique, planning), qui ne passent pas par l'API.
- L'application du verrou est faite **côté moteur**, pour toutes les routes et quel que soit le jeton d'API utilisé.
- **Limitation des essais** : après 5 codes faux consécutifs, délai de 30 s qui double à chaque nouvelle série (plafond 15 min) ; compteur persistant, comparaison à temps constant.
- **Pas de verrouillage automatique** : le verrou est posé et levé uniquement à la demande (le cadenas ou `POST /lock`). Il est conservé au redémarrage.
- **Réinitialisation** (code perdu) : `halloween-cli unlock --reset` sur le Pi, qui supprime le code et déverrouille ; exige un accès shell, c'est donc la preuve de possession.
- Un événement `lock_changed` est émis sur le WebSocket (les écrans de plusieurs appareils se mettent à jour).

## 7. Déclencheurs

Stockés dans `triggers.json`, gérés par l'API :

```json
[
  { "id": "t1", "source": "button", "button": "bouton_principal", "event": "short", "program": "scenario-principal", "policy": "ignore" },
  { "id": "t2", "source": "button", "button": "bouton_principal", "event": "long", "action": "stop" },
  { "id": "t3", "source": "schedule", "cron": "0 18 31 10 *", "program": "ambiance-soir" }
]
```

- **Bouton** : cible un bouton du catalogue + un événement (`short`, `long`, `double`). Plusieurs déclencheurs possibles par bouton (un par événement).
- **Appui long = arrêt d'urgence** proposé par défaut à la création d'un bouton.
- **Planning** : cron. **API** : lancement manuel.
- Un déclencheur ne peut viser qu'un programme existant, validé.

## 8. API

Base `http://<pi>:8080/api`, jeton statique `Authorization: Bearer`, réseau local uniquement.

**Configuration**

| Méthode | Route | Rôle |
|---|---|---|
| GET / PUT | `/config/home-assistant` | URL + jeton (jeton masqué en lecture) |
| POST | `/config/home-assistant/test` | teste la connexion |
| GET | `/ha/entities?domain=light\|switch` | liste les entités HA pour les proposer dans l'UI |
| GET / POST | `/components/{relays\|buttons\|lights\|switches}` | lister / créer |
| GET / PUT / DELETE | `/components/{type}/{id}` | lire / modifier / supprimer (suppression refusée si utilisé) |
| POST | `/components/{type}/{id}/test` | test manuel : impulsion, on/off, appui simulé |
| POST | `/images` | téléversement (png/jpg/webp, taille limitée, redimensionné) |
| GET | `/images/{fichier}` | image servie |
| GET | `/devices` | catalogue complet (tous composants avec capacités), pour construire l'éditeur |

**Programmes et exécution**

| Méthode | Route | Rôle |
|---|---|---|
| GET | `/programs` | liste |
| GET / PUT / DELETE | `/programs/{id}` | lire, créer / remplacer (validé), supprimer |
| POST | `/programs/validate` | valide, erreurs par `node_id` |
| GET | `/runs` | runs actifs (`run_id`, `program_id`, début, scripts en cours) |
| POST | `/runs` | `{program_id, code?}` lance (`code` obligatoire si verrouillé) ; `409` si le programme tourne déjà et que la politique est `ignore` |
| POST | `/runs/{run_id}/stop` | arrête un run |
| POST | `/runs/stop` | **stop global** : arrête tous les runs, état de repos |
| POST | `/simulate` | simulation, renvoie la timeline |
| GET | `/status` | runs actifs, état des relais, connexion HA, état de verrouillage |
| GET / PUT | `/triggers` | gérer les déclencheurs |
| WS | `/events` | `run_started` (avec `run_id`), `node_started` / `node_finished` (avec `run_id`, `script_id`, `node_id`), `component_changed`, `button_event`, `lock_changed`, `run_ended`, `error` |

**Verrouillage** (voir 6.4)

| Méthode | Route | Rôle |
|---|---|---|
| GET | `/lock` | `{locked, has_code, retry_after_s?}` |
| POST | `/lock` | verrouille (sans code ; exige qu'un code existe) |
| POST | `/unlock` | `{code}` déverrouille ; `401` si faux, `429` + `retry_after_s` si limité |
| PUT | `/lock/code` | `{new_code, old_code?}` définit ou change le code (`old_code` obligatoire s'il existe ; refusé si verrouillé) |

**Service de l'interface** : le moteur sert le build statique de l'UI sur `/` (repli `index.html` pour les routes de l'application, y compris `/spectacle`) ; l'API est sous `/api`.

Le **test manuel d'un composant** (`/components/.../test`) est important : il permet de configurer et vérifier un relais ou une light depuis l'UI sans écrire de programme.

## 9. Mode simulation et tests

- Drivers abstraits (`RelayDriver`, `ButtonDriver`, `HAClient`) avec implémentations réelle et fictive ; horloge injectable.
- En simulation, `wait` n'attend pas ; la sortie est une timeline `[(t, composant, action)]`.
- Tests unitaires : interpréteur (séquence, parallèle, boucle, stop en plein `parallel`, timeout), validation de config et de programme (pins en double, paramètre non supporté, mode relais incompatible), politique de déclencheur, modes `latched` / `push` (impulsion, verrouillage pendant `animation_s`).
- Appels HA testés contre un faux serveur HTTP (corps JSON attendus).
- Verrouillage : toute route d'écriture renvoie `423` quand verrouillé (test paramétré sur la liste des routes), `runs/stop` reste permis sans code, `runs` exige le code valide, limitation des essais (commune à `unlock` et aux lancements) et délai croissant, persistance au redémarrage, empreinte jamais renvoyée ni journalisée.
- CLI : `halloween-cli relay fantome on|off`, `halloween-cli run <id>`, `halloween-cli unlock --reset`.

## 10. Observabilité

Journal JSON lines avec rotation (`run_id`, `node_id`) ; `GET /status` pour le diagnostic.

## 11. Critères d'acceptation v1

1. Les 4 relais (pins 18, 17, 27, 22) et le bouton (pin 21) sont créés depuis l'API avec nom + image, et testables manuellement.
2. Un relais `latched` reste fermé jusqu'à `off` ; un relais `push` émet une impulsion de `pulse_ms` et ignore un second `trigger` pendant `animation_s`.
3. Une light HA reçoit le bon corps JSON (`rgb_color`, `brightness`, `transition`) uniquement pour les paramètres autorisés ; un switch est commuté via `switch/turn_on|off`.
4. Un `parallel` pilote un relais et une light simultanément.
5. Appui court sur le bouton lance le scénario associé ; appui long l'arrête et applique l'état de repos en < 1 s.
6. Coupure de HA pendant un run : relais OK, erreur tracée, run terminé.
7. Redémarrage du Pi : relais OFF, config et déclencheurs rechargés.
8. Programme ou config invalide rejeté avec erreur localisée (`node_id` / champ).
9. Suite de tests entièrement exécutable sans matériel.
10. Verrouillé : toute écriture (même par appel API direct avec jeton valide) répond `423` ; lancer exige le code (`POST /runs` sans code ou avec un code faux est refusé), arrêter (STOP) reste possible sans code, et les déclencheurs (bouton physique, planning) continuent de fonctionner ; le bon code déverrouille ; 5 codes faux déclenchent un délai ; le verrou survit à un redémarrage.
11. Un programme avec `show: true` est listé avec son `show_order` ; un composant avec `image: "builtin:ghost"` est accepté et restitué tel quel.
12. **Parallélisme** : un programme avec deux blocs début exécute ses deux scripts simultanément ; un programme d'ambiance (boucle infinie, sans `max_duration_s`) tourne pendant qu'un scénario est déclenché par le bouton ; le STOP global les arrête tous en moins d'une seconde ; l'arrêt du scénario seul laisse l'ambiance active et ne réinitialise pas ses composants.

## 12. Décisions et questions ouvertes

Décisions prises :
- Les 4 relais sont `latched`, **sans limite de durée** d'allumage (`max_on_seconds` absent) ; pas de temps de recharge.
- `active_low = false` : `high()` active le relais.
- **Plusieurs programmes en parallèle** et plusieurs blocs début par programme (section 5 et 6.1).
- L'UI est servie par le moteur sur `/`.
- Effets / thèmes Twinkly : hors v1 (plus tard).
- **Moteur en Python** (asyncio, FastAPI), même si les relais sont aujourd'hui pilotés en Java avec Pi4J : le code existant n'est pas réutilisé, seuls le câblage et la logique (`high()` = actif) sont repris.
- **Arrêt ou plantage du moteur** : pas de watchdog matériel. Le service `systemd` (`Restart=always`) relance le moteur, qui remet tous les relais `latched` à OFF au démarrage avant toute autre action. Pour un gel sans plantage, le moteur envoie un signal de vie à `systemd` (`WatchdogSec`) : si la boucle `asyncio` ne répond plus, le processus est tué puis relancé, ce qui éteint les relais.
- **Blocs début déclenchés par un bouton** (`hat.type: on_button`) : reportés en v2. Le format les permet déjà ; en v1 les déclencheurs de la section 7 suffisent (un bouton + un événement → un scénario).

Questions ouvertes : aucune sur le moteur.

## 13. Annexe — exemples

### Config

```json
{
  "home_assistant": { "url": "http://homeassistant.local:8123", "token": "***" },
  "relays": [
    { "id": "fantome", "name": "Fantôme", "image": "fantome.png", "pin": 18, "mode": "latched", "active_low": false },
    { "id": "squelette", "name": "Squelette", "image": "squelette.png", "pin": 17, "mode": "latched", "active_low": false },
    { "id": "epouvantail", "name": "Épouvantail", "image": "epouvantail.png", "pin": 27, "mode": "latched", "active_low": false },
    { "id": "orage", "name": "Orage", "image": "orage.png", "pin": 22, "mode": "latched", "active_low": false }
  ],
  "buttons": [
    { "id": "bouton_principal", "name": "Bouton d'entrée", "image": "bouton.png", "pin": 21, "pull": "up" }
  ],
  "lights": [
    { "id": "bandeau", "name": "Bandeau Hue", "image": "bandeau.png", "entity_id": "light.bandeau_hue", "supports_color": true, "supports_brightness": true, "supports_transition": true },
    { "id": "guirlande", "name": "Guirlande Twinkly", "image": "guirlande.png", "entity_id": "light.twinkly_halloween", "supports_color": false, "supports_brightness": true, "supports_transition": false }
  ],
  "switches": []
}
```

### Programme

```json
{
  "schema": 1,
  "id": "scenario-principal",
  "name": "Scénario principal",
  "max_duration_s": 90,
  "on_end": "reset",
  "scripts": [{ "id": "s1", "hat": { "type": "start" }, "root": { "id": "n1", "type": "sequence", "children": [
    { "id": "n2", "type": "light", "target": "bandeau", "state": "on", "rgb_color": [255, 0, 0], "brightness": 40, "transition": 2 },
    { "id": "n3", "type": "wait", "seconds": 3 },
    { "id": "n4", "type": "parallel", "children": [
      { "id": "n5", "type": "relay", "target": "orage", "state": "on" },
      { "id": "n6", "type": "relay", "target": "fantome", "state": "on" }
    ] },
    { "id": "n7", "type": "wait", "seconds": 8 },
    { "id": "n7b", "type": "relay", "target": "fantome", "state": "off" },
    { "id": "n7c", "type": "relay", "target": "orage", "state": "off" },
    { "id": "n8", "type": "relay", "target": "squelette", "state": "on" },
    { "id": "n8b", "type": "wait", "seconds": 6 },
    { "id": "n8c", "type": "relay", "target": "squelette", "state": "off" },
    { "id": "n9", "type": "relay", "target": "epouvantail", "state": "on" }
  ] } }]
}
```

---

## Aperçu de la spec 2 (interface)

Voir [spec-2-interface.md](spec-2-interface.md) pour la spécification complète. Deux zones : **Configuration** (formulaires pour HA, relais, boutons, lights, switches avec image, test manuel de chaque composant, sélection d'entités HA) et **Éditeur de blocs** (Blockly ou équivalent) où les composants configurés apparaissent comme blocs avec leur nom et leur image, validation en direct, simulation, lancement, surlignage du bloc actif via le WebSocket, gestion des déclencheurs.
