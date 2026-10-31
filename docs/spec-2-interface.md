# Spec 2 — Interface (configuration + éditeur de blocs)

Statut : brouillon v0.1 — 2026-10-26
Dépend de : [spec 1 — Moteur](spec-1-moteur.md) (API, catalogue de composants, format de programme)

## 1. Objectif

Une application web, servie par le Pi, qui permet de :

1. **Configurer** le matériel et Home Assistant : relais, boutons, lights, switches, avec nom et image.
2. **Composer des scénarios** en assemblant des blocs façon Scratch, où chaque composant configuré apparaît avec son nom et son image.
3. **Tester et lancer** un scénario, voir le bloc en cours d'exécution, arrêter à tout moment.
4. **Relier** un bouton physique (ou un planning) à un scénario.

L'interface ne contient aucune logique d'exécution : tout passe par l'API du moteur. Elle est un éditeur du JSON défini en spec 1 (section 5).

### Hors périmètre (v1)

Comptes utilisateurs, édition collaborative, historique de versions, application mobile native.

## 2. Choix techniques

| Sujet | Choix | Raison |
|---|---|---|
| Éditeur de blocs | **Blockly** | bibliothèque éprouvée, blocs personnalisables (champs image, menus), sérialisation intégrée |
| Application | SPA **React** + TypeScript (Vite) ; **intégration directe de Blockly** (`blockly/core`, rendu Zelos, thème sombre) dans un composant React mince, sans `react-blockly` *(décision du prototype, lot 9)* | build statique léger, compétence existante. L'intégration directe évite une dépendance qui suit mal les versions de Blockly ; la sérialisation, testée sans navigateur sur un espace de travail non affiché, ne dépend pas de React |
| Hébergement | fichiers statiques servis par le moteur FastAPI sur le même port | même origine, pas de CORS, un seul service à déployer |
| Temps réel | WebSocket `/api/events` du moteur | surlignage du bloc actif, état des composants |
| Authentification | jeton statique du moteur, saisi une fois et gardé dans le navigateur | usage réseau local |
| Langue | français uniquement | un seul utilisateur |
| Affichage | **tablette et ordinateur** (≥ 768 px) pour la configuration et l'éditeur ; le **mode spectacle** et le tableau de bord restent utilisables au téléphone (360 px). Pas de support mobile pour l'édition. | décision v0.2 |

## 3. Navigation

Barre latérale (menu inférieur sur mobile) avec 6 entrées, et un bandeau permanent.

| Entrée | Contenu |
|---|---|
| **Mode spectacle** | écran plein écran simplifié pour piloter la soirée (4.7) |
| **Tableau de bord** | état en direct, lancement rapide, test des composants |
| **Scénarios** | liste + éditeur de blocs |
| **Déclencheurs** | boutons/planning → scénarios |
| **Composants** | relais, boutons, lights, switches, lecteurs de vidéos |
| **Réglages** | connexion Home Assistant, jeton moteur, état de repos |

**Bandeau permanent** :
- bouton rouge **STOP** toujours visible : **stop global**, arrête tous les runs (appelle `POST /runs/stop`) ;
- pastille d'état du moteur (connecté / déconnecté), de Home Assistant, et nombre de scénarios en cours (clic : liste des runs, avec arrêt individuel) ;
- cadenas : état **verrouillé / déverrouillé** (4.8) ;
- si le moteur est injoignable, tout est désactivé sauf un message clair avec bouton « Réessayer ».

## 4. Écrans

### 4.1 Tableau de bord

- Une **tuile par composant** (image + nom + état : allumé/éteint, couleur de la light).
- Un clic sur une tuile ouvre un **test manuel** : relais on/off, light on/off avec sélecteur de couleur / luminosité / transition selon ses capacités, switch on/off, lecteur : choix de la vidéo (en boucle ou non) et retour à l'écran noir (`POST /components/{type}/{id}/test`). Une tuile de lecteur n'a pas d'état : « Écran noir » en un clic, « Vidéos… » pour choisir.
- Liste des scénarios avec bouton **Lancer** ; chaque scénario en cours affiche une barre de progression (durée écoulée / `max_duration_s`, ou « en continu » s'il n'a pas de limite) et un bouton d'arrêt individuel. Plusieurs scénarios peuvent tourner en même temps.
- Indicateur lorsque l'on appuie sur un bouton physique (`button_event`), utile pour vérifier le câblage.

### 4.2 Composants

Quatre onglets : Relais, Boutons, Lights, Switches. Chacun affiche une grille de cartes (image, nom, résumé) et un bouton **Ajouter**.

**Formulaire commun** : nom, image, bouton **Tester**.

**Choix de l'image** : deux sources, au choix dans un sélecteur à deux onglets.
- **Bibliothèque intégrée** : une trentaine d'icônes Halloween livrées avec l'application (fantôme, squelette, épouvantail, citrouille, éclair / orage, araignée, chauve-souris, bougie, lumière, prise…), recherchables. Stockées comme `image: "builtin:<nom>"`. *Jeu retenu (lot 11) : 64 icônes. 32 de **game-icons.net** (CC BY 3.0, Lorc, Delapouite, Carl Olsen, Cathelineau, DarkZaitzev : fond retiré, couleur du thème) pour l'ambiance Halloween, 32 de Lucide (ISC) / Feather (MIT) pour l'usage courant (lumière, prise, bouton…) ; attributions par auteur dans Réglages › À propos et dans `GAME-ICONS-LICENSE.txt` livré avec le build.*
- **Image personnelle** : téléversement avec aperçu, recadrage carré, formats png/jpg/webp. Stockée comme nom de fichier sous `/images/`.

Une icône par défaut est attribuée selon le type de composant tant qu'aucune image n'est choisie.

| Type | Champs spécifiques | Aides |
|---|---|---|
| Relais | pin, mode (`latched` / `push`), `active_low`, durée max d'allumage facultative (latched, vide = aucune limite) ou durée d'impulsion + durée d'animation (push) | pins déjà utilisées grisées ; texte d'aide expliquant les deux modes |
| Bouton | pin, `pull`, anti-rebond, seuil d'appui long | bouton **Tester** : « appuyez sur le bouton », affiche l'événement reçu |
| Light | entité HA, cases *couleur*, *luminosité*, *transition* | entité choisie dans une liste issue de `GET /ha/entities?domain=light` |
| Switch | entité HA | liste issue de `GET /ha/entities?domain=switch` |
| Lecteur vidéo | script HA, liste de vidéos (nom, fichier, durée facultative), vidéo de repos | script choisi dans `GET /ha/entities?domain=script` ; bouton **Tester** : jouer une vidéo (en boucle ou non), écran noir |

Règles :
- l'`id` technique est affiché en lecture seule après création ;
- la suppression d'un composant utilisé affiche la liste des scénarios / déclencheurs concernés et reste bloquée tant qu'ils existent ;
- les erreurs de validation du moteur sont affichées sous le champ concerné.

### 4.3 Réglages

- **Home Assistant** : URL, jeton (champ masqué, « inchangé » si non modifié), bouton **Tester la connexion** avec résultat explicite (OK / URL injoignable / jeton refusé).
- **Jeton du moteur** : saisie du jeton d'accès à l'API, mémorisé dans le navigateur.
- **État de repos** : pour chaque composant, l'état à appliquer en fin de scénario / à l'arrêt (relais off ; light on/off + couleur + luminosité ; switch on/off).

### 4.4 Déclencheurs

Liste de règles lisibles : « Quand **[Bouton d'entrée]** est **[appui court]** → **[Lancer : Scénario principal]** ». Pour un détecteur de mouvement (PIR), le seul événement proposé est « mouvement détecté » : « Quand **[Couloir]** détecte un mouvement → **[Lancer : …]** ».

- Sélecteurs : source (bouton / planning), bouton du catalogue, événement (court / long / double), action (lancer un scénario / arrêter).
- Pour le planning : constructeur de cron simple (jours, heure) avec prévisualisation en clair (« tous les 31 octobre à 18:00 »). Pas de déclencheurs liés au soleil en v1.
- Politique si un scénario tourne déjà : ignorer (défaut) / redémarrer / mettre en file.
- Alerte si deux règles visent le même bouton + événement.
- Un appui long est proposé en **Arrêt** à la création d'un bouton.

### 4.5 Scénarios

- Liste : nom, durée max, dernière modification ; actions Nouveau, Dupliquer, Supprimer.
- Case **« Afficher en mode spectacle »** par scénario (champ `show` du programme) et ordre d'affichage par glisser-déposer.
- **Éditeur** (5) plein écran sur l'espace restant.

### 4.7 Mode spectacle

Écran plein écran pensé pour piloter la soirée sans risque de modifier quoi que ce soit.

- Accessible par la première entrée du menu et par l'adresse directe `/spectacle` (favori sur le téléphone / la tablette).
- Affiche, en grand : une tuile **Lancer** par scénario marqué « afficher en mode spectacle » (image du scénario ou icône, nom), un bouton **STOP** très visible, les scénarios en cours avec leur progression (plusieurs possibles), l'état de Home Assistant et du moteur.
- **Aucun accès** à la configuration, à l'éditeur ou à la suppression depuis cet écran. Quand l'interface est déverrouillée, un lancement ne demande ni confirmation ni code ; **quand elle est verrouillée, chaque lancement demande le code** (pavé numérique, écran Verrouillage) ; un lancement d'un scénario déjà en cours applique la politique de la règle (par défaut : ignoré, avec message) ; un scénario différent se lance en parallèle des autres (ex. ambiance de fond + scénario). Les scénarios « en continu » (ambiance) affichent un bouton Lancer / Arrêter à bascule.
- Boutons physiques : l'écran reflète leurs appuis (`button_event`).
- Écran maintenu allumé (`Screen Wake Lock API`), grand format tactile (cibles ≥ 64 px), contraste élevé pour le noir de la nuit (thème sombre).
- Quitter le mode spectacle : bouton discret ; si l'interface est verrouillée (4.8), le code est demandé.

### 4.8 Verrouillage par code

Un mode **lecture seule protégé par un code** pour éviter toute modification pendant la soirée (invités sur le réseau).

- Code à 4-8 chiffres, défini dans Réglages ; **le moteur** en stocke l'empreinte (hachage salé), jamais la valeur.
- **Verrouillé** : seuls sont autorisés la **lecture** (tableau de bord, scénarios, configuration en consultation) et **STOP** (sans code, toujours). **Lancer un scénario exige le code**, saisi à chaque lancement et vérifié par le moteur ; le code n'ouvre pas de session. Les déclencheurs physiques (bouton) et planifiés continuent de fonctionner normalement. Toute écriture (composants, réglages, programmes, déclencheurs, tests manuels de composants) est refusée **par le moteur** (`423 Locked`), pas seulement masquée dans l'interface ; passer par l'API directe ne contourne donc pas le verrou.
- Le cadenas du bandeau permet de verrouiller en un clic (sans code) et de déverrouiller en saisissant le code.
- Protection contre les essais répétés : délai croissant après plusieurs codes faux (ex. 5 essais puis 30 s), compteur côté moteur.
- **Pas de verrouillage automatique** : on verrouille et déverrouille uniquement à la demande, et l'état est conservé au redémarrage.
- Pour enchaîner plusieurs lancements pendant la soirée, on déverrouille l'interface (la modification redevient alors possible) ; un verrouillage avec lancement libre n'est pas prévu.
- Si le code est perdu : réinitialisation par la ligne de commande sur le Pi (`halloween-cli unlock --reset`), documentée dans le README.

## 5. Éditeur de blocs

### 5.1 Disposition

```
┌───────────────────────────────────────────────────────────────┐
│ Nom du scénario   [Valider ✓] [Simuler] [▶ Lancer] [Enregistrer] │
├────────────┬──────────────────────────────────────┬───────────┤
│ Palette    │          Zone de montage             │ Panneau   │
│ (catégories│          (Blockly)                   │ latéral   │
│  + blocs)  │                                      │ erreurs / │
│            │                                      │ timeline  │
└────────────┴──────────────────────────────────────┴───────────┘
```

- Le panneau latéral affiche les **erreurs de validation** (clic → sélectionne le bloc fautif) puis, après simulation, la **timeline**.
- Paramètres du scénario (durée maximale, `on_end`) dans un panneau repliable.
- **Plusieurs scripts** par scénario, comme dans Scratch : chaque pile commence par un bloc **début** (chapeau) ; plusieurs blocs début coexistent dans la zone de montage et s'exécutent **en parallèle** au lancement. Les blocs qui ne sont rattachés à aucun bloc début sont signalés par un avertissement et ignorés.
- Au moins un bloc début est requis ; un scénario neuf est créé avec un bloc début déjà posé.
- Avertissement (non bloquant) lorsque deux scripts commandent le même composant : la dernière commande l'emporte.

### 5.2 Palette

Catégories colorées. Les blocs de composants sont **générés à partir de `GET /devices`** : ajouter un composant dans la config le fait apparaître dans la palette au prochain chargement (ou immédiatement via l'événement `component_changed`).

| Catégorie | Blocs |
|---|---|
| **Contrôle** | **début** (« quand le scénario démarre », chapeau, plusieurs possibles), séquence (implicite : empilement), en parallèle, répéter N fois, répéter indéfiniment, attendre, attendre aléatoire, si / sinon, attendre jusqu'à, choix aléatoire, appeler un scénario |
| **Relais** | un bloc par relais (image + nom) |
| **Lumières** | un bloc par light |
| **Interrupteurs** | un bloc par switch |
| **Vidéos** | deux blocs par lecteur : « jouer une vidéo » et « revenir à l'écran noir » (si le lecteur a une vidéo de repos) |
| **Boutons** | condition « bouton [x] a reçu [événement] » |
| **Divers** | journaliser un message |

### 5.3 Blocs de composants

- **Relais `latched`** : `[image] Fantôme  ▾ allumer | éteindre`.
- **Relais `push`** : `[image] Fantôme  déclencher` + case « attendre la fin » (visible seulement si `animation_s` est défini).
- **Light** : `[image] Bandeau  ▾ allumer | éteindre`, puis champs facultatifs affichés **uniquement selon les capacités** : sélecteur de couleur, curseur de luminosité (0-100 %, converti en 0-255), durée de transition. Un bouton ⚙ ajoute/retire les paramètres facultatifs (non cochés = pas envoyés).
- **Switch** : `[image] Prise  ▾ allumer | éteindre`.
- **Lecteur** : `[image] Rétroprojecteur  ▾ jouer | revenir à l'écran noir`, puis pour « jouer » : vidéo, cases « en boucle » et « attendre la fin ».
- Option « sans attendre HA » (`fire_and_forget`) et « en cas d'erreur : continuer / arrêter » dans un menu ⚙ du bloc, masqué par défaut.
- Les blocs affichent l'image du composant en petit (24 px) et ont la couleur de leur catégorie.

### 5.4 Sérialisation (blocs ↔ JSON de la spec 1)

| Bloc | Nœud JSON |
|---|---|
| Bloc début + pile qui le suit | un élément de `scripts[]` : `hat` (`start`) + `root` de type `sequence` |
| Blocs placés dans « en parallèle » (une pile par branche) | `parallel` |
| Répéter N fois / indéfiniment | `repeat` (`times` / `forever`) |
| Attendre / attendre aléatoire | `wait` (`seconds` / `min`+`max`) |
| Si / sinon | `if` |
| Attendre jusqu'à | `wait_until` |
| Choix aléatoire | `random_choice` |
| Appeler un scénario | `call` |
| Bloc relais / light / switch / lecteur | `relay` / `light` / `switch` / `player` |
| Journaliser | `log` |

Règles :
- chaque nœud reçoit un `id` stable (celui du bloc Blockly) pour que les erreurs et la progression retombent sur le bon bloc ;
- les `target` sont des `id` de composants, jamais des noms ;
- **Disposition de l'éditeur** (positions, blocs repliés, zoom) : conservée dans un champ `editor` du JSON du programme, ignoré par le moteur. *Ajout nécessaire au schéma de la spec 1* (champ `editor` libre, taille limitée) ; le programme se recharge donc exactement comme enregistré.
- Conversion d'un programme sans champ `editor` (créé par API) : mise en page automatique.

### 5.5 Validation en direct

- À chaque modification (avec délai d'attente de 500 ms), appel de `POST /programs/validate`.
- Les erreurs du moteur (par `node_id`) sont affichées : bloc entouré de rouge + message dans le panneau.
- Contrôles locaux immédiats complémentaires : relais `latched` sans extinction dans le scénario (avertissement, non bloquant : l'état de repos s'en charge), boucle infinie sans arrêt possible (avertissement), `wait` négatif.
- **Lancer** et **Enregistrer** sont désactivés tant qu'il reste une erreur ; un scénario invalide ne peut pas être enregistré, mais un brouillon est gardé dans le navigateur.

### 5.6 Composant supprimé / modifié

- Un bloc dont le composant n'existe plus s'affiche en rouge avec « composant introuvable » (ne devrait pas arriver, la suppression étant bloquée).
- Si un relais change de mode, les blocs incompatibles sont signalés par la validation.

### 5.7 Simulation et exécution

- **Simuler** : `POST /simulate`, résultat affiché en frise temporelle (une ligne par composant, une barre par période d'activation). Aucun matériel actionné.
- **Lancer** : `POST /runs` ; l'interface passe en mode exécution :
  - le **bloc en cours est surligné** (`node_started` / `node_finished`) **dans chaque script en cours** (plusieurs blocs surlignés en même temps), les blocs terminés s'estompent ;
  - l'éditeur est en lecture seule pendant le run ;
  - les erreurs (`error`) apparaissent sur le bloc concerné, sans interrompre l'affichage ;
  - fin de run : bandeau avec l'issue (terminé / arrêté / échoué / délai dépassé) et la durée.
- **Stop** (bandeau) disponible partout : global, ou arrêt du seul run affiché depuis l'éditeur.
- Un autre scénario peut être lancé pendant ce temps ; l'éditeur ne suit que le run du scénario ouvert.

### 5.8 Enregistrement

- Brouillon automatique dans le navigateur ; l'enregistrement sur le moteur est explicite (bouton ou `Ctrl+S`).
- Avertissement si l'on quitte la page avec des modifications non enregistrées.
- Si le programme a changé côté moteur entre-temps, message de conflit avec choix « écraser / recharger ».
- Annuler / rétablir (`Ctrl+Z` / `Ctrl+Y`) fournis par Blockly.

## 6. Comportement transverse

- **Temps réel** : un unique WebSocket ouvert à la connexion, reconnexion automatique avec resynchronisation (`GET /status`). Indicateur « hors ligne » en cas de coupure ; pendant ce temps le STOP tente l'appel HTTP.
- **Erreurs d'API** : toast lisible, pas de message technique brut, détails dépliables.
- **Confirmations** : suppression, écrasement ; jamais pour STOP.
- **Accessibilité** : navigation clavier dans les formulaires, contraste suffisant, couleurs jamais seul porteur d'information (une icône accompagne chaque état).
- **Images** : redimensionnées côté moteur ; cache navigateur avec nom de fichier versionné.

## 7. Modèle d'état côté client

```
catalogue    ← GET /devices (+ événements component_changed)
programmes   ← GET /programs, GET /programs/{id}
déclencheurs ← GET /triggers
statut       ← GET /status + WebSocket /events
```

Aucune vérité côté client : en cas de doute, la donnée du moteur gagne. Seuls les brouillons non enregistrés vivent dans le navigateur.

## 8. Critères d'acceptation v1

1. Depuis une tablette sur le réseau local, créer le relais « Fantôme » (pin 18) avec une icône de la bibliothèque, puis avec une image téléversée, le tester, et le voir apparaître en tuile.
2. Créer une light Hue en ne cochant que *luminosité* : le bloc n'offre pas de couleur ni de transition.
3. Saisir URL + jeton HA, voir un test de connexion explicite, et choisir une light dans la liste des entités HA.
4. Construire par glisser-déposer un scénario avec un `parallel`, une boucle et une attente aléatoire ; l'enregistrer, recharger la page, retrouver la mise en page à l'identique.
5. Un scénario invalide (relais supprimé, paramètre non supporté) est signalé sur le bon bloc et ne peut pas être lancé.
6. Lancer un scénario : le bloc actif est surligné, STOP l'arrête et le tableau de bord montre les relais éteints en moins d'une seconde.
6b. **Parallélisme** : un scénario avec deux blocs début voit ses deux scripts surlignés en même temps ; un scénario d'ambiance en boucle infinie tourne pendant qu'un scénario est lancé par le bouton ; STOP global arrête les deux ; l'arrêt individuel d'un seul laisse l'autre actif.
7. Créer un déclencheur « bouton d'entrée, appui court → scénario principal » et le vérifier avec le bouton physique ; l'appui long arrête le scénario.
8. Perte de connexion au moteur : bandeau « hors ligne », reconnexion automatique, état resynchronisé.
9. Le mode spectacle et le tableau de bord sont utilisables en 360 px de large ; la configuration et l'éditeur à partir de 768 px.
10. Mode spectacle : seuls les scénarios cochés apparaissent ; Lancer et STOP fonctionnent ; l'écran ne se met pas en veille ; aucune route de modification n'est accessible.
11. Verrouillage : une fois verrouillé, toute écriture (y compris par appel API direct) est refusée avec `423`, STOP fonctionne sans code, un lancement sans code (ou avec un code faux) est refusé, un lancement avec le bon code démarre le scénario ; le déverrouillage exige le bon code ; après 5 codes faux, un délai s'applique.

## 9. Tests

- Composants : tests unitaires de la sérialisation blocs ↔ JSON (aller-retour sans perte sur un jeu de programmes types, dont celui de l'annexe de la spec 1).
- Génération des blocs à partir d'un catalogue fictif (capacités variées).
- Tests de bout en bout (Playwright) contre un moteur en **mode simulation** : création de composants, construction d'un scénario, lancement, surlignage, STOP.
- Test visuel manuel sur téléphone et tablette.

## 10. Questions ouvertes

Décisions prises : React ; images personnelles + bibliothèque d'icônes intégrée ; édition sur tablette / ordinateur uniquement ; mode spectacle ; verrouillage par code **sans verrouillage automatique** ; **lancer un scénario exige le code quand l'interface est verrouillée** (STOP jamais) ; planification cron simple.

**Jeu d'icônes (recommandation)** :
- **Icônes d'objets Halloween** (fantôme, squelette, épouvantail, citrouille, chauve-souris, araignée, éclair, chaudron, maison hantée, bougie…) : **game-icons.net** (licence **CC BY 3.0**, attribution obligatoire), jeu monochrome au style cohérent avec beaucoup de sujets Halloween ; à recolorer au thème sombre. Ajouter la liste des auteurs dans Réglages › À propos.
- **Icônes d'interface** (navigation, cadenas, lecture, etc.) : **Lucide** (licence **ISC**, sans attribution obligatoire), déjà proche du style en traits des maquettes.
- Avant d'intégrer : vérifier la licence exacte de chaque icône retenue (les auteurs diffèrent) et que les sujets voulus existent (non vérifié ici). Plan de repli : Phosphor (MIT) pour les icônes génériques.

Aucune question ouverte.

## Contrat d'API (`docs/openapi.json`)

Le contrat OpenAPI de l'API est **versionné** dans [`docs/openapi.json`](openapi.json) (régénéré par `make openapi`, vérifié par un test). L'interface en génère son client TypeScript, par exemple :

```bash
npx openapi-typescript docs/openapi.json -o ui/src/api/schema.d.ts
```

Il décrit toutes les routes, le schéma `Program` (blocs, conditions, scripts), les erreurs structurées et, sous `x-websocket` et `components.schemas.Event`, les messages du WebSocket `/api/events` (union discriminée sur `type`). L'authentification est un jeton Bearer, sauf `health` et `get_image`.

## 11. Impacts sur la spec 1

- Ajouter le champ `editor` (libre, limité en taille) au schéma de programme.
- Champ `show` (booléen) et ordre d'affichage sur les programmes, pour le mode spectacle.
- **Verrouillage** : `GET /lock` (état), `POST /lock` (verrouiller), `POST /unlock {code}`, `PUT /lock/code` (définir / changer, exige l'ancien code) ; `423 Locked` sur toute écriture quand verrouillé ; `POST /runs` exige `code` dans le corps ; `POST /runs/stop` reste libre ; limitation des essais ; `/status` expose l'état de verrouillage ; commande CLI de réinitialisation.
- Champ `image` des composants : accepte `builtin:<nom>` en plus d'un nom de fichier téléversé.
- Routes déjà prévues et utilisées ici : `/devices`, `/ha/entities`, `/components/*`, `/images`, `/programs/validate`, `/simulate`, `/runs` (liste, lancement), `/runs/{run_id}/stop`, `/runs/stop`, `/triggers`, WebSocket `/events` avec `component_changed` et `button_event`.
- À prévoir : le moteur sert les fichiers statiques de l'interface (`/` → build de la SPA).
- À prévoir : détection de conflit à l'enregistrement d'un programme (`ETag` / `If-Match` ou numéro de révision).
