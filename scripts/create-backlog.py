#!/usr/bin/env python3
"""Crée sur GitHub les labels, les jalons (lots) et les issues du plan d'implémentation.

Prérequis : `gh` authentifié avec un jeton pouvant écrire les issues (et les projets pour --project).
Idempotent : les labels, jalons et issues déjà présents (même titre) sont ignorés.

    python3 scripts/create-backlog.py --dry-run
    python3 scripts/create-backlog.py
    python3 scripts/create-backlog.py --project     # crée aussi un projet GitHub et y ajoute les issues
"""
import argparse
import json
import subprocess
import sys

REPO = "m-maillot/halloween"
OWNER = "m-maillot"
PROJECT_TITLE = "Déco Halloween"

LABELS = {
    "moteur": ("1f6feb", "Moteur Python (Raspberry Pi)"),
    "interface": ("ff8a2b", "Interface React / Blockly"),
    "materiel": ("8b5cf6", "Matériel : GPIO, relais, bouton, Raspberry Pi"),
    "home-assistant": ("18a999", "Intégration Home Assistant"),
    "securite": ("d12b2b", "Sécurité, verrouillage, reprise"),
    "tests": ("0e8a16", "Tests et recette"),
    "docs": ("0075ca", "Documentation"),
    "risque": ("fbca04", "Point à risque à traiter tôt"),
}

S1 = "docs/spec-1-moteur.md"
S2 = "docs/spec-2-interface.md"
PL = "docs/plan-implementation.md"

MILESTONES = [
    ("Lot 0 — Socle du projet", "Phase 0 du plan. Dépôt, outillage, configuration d'exemple."),
    ("Lot 1 — Cœur du moteur (sans matériel)", "Phase 1 du plan. Modèles, validation, interpréteur, simulation, runs concurrents."),
    ("Lot 2 — Matériel : relais et bouton", "Phase 2 du plan. GPIO réels sur le Raspberry Pi, CLI, tests sans charge."),
    ("Lot 3 — Home Assistant", "Phase 3 du plan. Lumières et interrupteurs via l'API REST."),
    ("Lot 4 — Déclencheurs et reprise", "Phase 4 du plan. Bouton, planning, reprise au démarrage."),
    ("Lot 5 — API HTTP et temps réel", "Phase 5 du plan. Routes, WebSocket, authentification, OpenAPI."),
    ("Lot 6 — Verrouillage et déploiement (jalon A)", "Phase 6 du plan. Jalon A : moteur complet, pilotable en ligne de commande."),
    ("Lot 7 — Socle de l'interface", "Phase 7 du plan. Projet React, client d'API, thème, bandeau."),
    ("Lot 8 — Composants, tableau de bord, réglages", "Phase 8 du plan."),
    ("Lot 9 — Éditeur de blocs", "Phase 9 du plan. Partie la plus risquée de l'interface."),
    ("Lot 10 — Déclencheurs, mode spectacle, verrouillage (UI)", "Phase 10 du plan."),
    ("Lot 11 — Finitions et recette (jalon B)", "Phase 11 du plan. Jalon B : application complète."),
]

# (lot, titre, labels, description, terminé quand, références)
ISSUES = [
    (0, "Initialiser le dépôt et la structure engine / ui / deploy", ["moteur", "docs"],
     "Créer l'arborescence `engine/`, `ui/`, `deploy/` du plan, un `.gitignore`, et le README de chaque partie.",
     "La structure est en place et un poste neuf peut cloner et s'orienter.", PL + " §2"),
    (0, "Outillage Python : pyproject, uv, ruff, pytest-asyncio", ["moteur", "tests"],
     "Python 3.11+, dépendances (Pydantic v2, FastAPI, httpx), `ruff`, `pytest` + `pytest-asyncio`, une commande unique de test.",
     "`pytest` s'exécute (même vide) et le projet s'installe proprement sur un poste neuf.", PL + " §3 phase 0"),
    (0, "Journalisation JSON lines avec run_id et node_id", ["moteur"],
     "Journal structuré, chaque ligne porte `run_id` et `node_id` quand ils existent.",
     "Les logs d'un run sont filtrables par `run_id`.", S1 + " §10"),
    (0, "Configuration d'exemple : 4 relais et le bouton", ["moteur", "materiel"],
     "`config.json` d'exemple : fantôme 18, squelette 17, épouvantail 27, orage 22 (`latched`, `active_low: false`, sans `max_on_seconds`), bouton 21 (pull-up).",
     "Le fichier d'exemple est chargé et validé par le modèle de config.", S1 + " §4, §13"),

    (1, "Modèles Pydantic des composants", ["moteur"],
     "Relais (`latched` / `push`), bouton, light (capacités couleur / luminosité / transition), switch, connexion HA, image (`builtin:` ou fichier), champs communs.",
     "Les exemples de config de la spec sont chargés ; les champs invalides sont rejetés avec un message clair.", S1 + " §4"),
    (1, "Modèle de programme : scripts, blocs début, blocs de contrôle et d'action", ["moteur"],
     "`scripts[]` avec `hat` (`start`), tous les blocs des §5.1 et §5.2, champs `show`, `show_order`, `editor`, `revision`, `max_duration_s` optionnel.",
     "L'exemple d'annexe de la spec se charge et se sérialise sans perte.", S1 + " §5"),
    (1, "Validation de la configuration et des programmes", ["moteur", "tests"],
     "Pins en double ou entrée/sortie en conflit, références inconnues, paramètre non supporté par une light, bloc `relay` incompatible avec le mode, profondeur et cycles de `call`, avertissement de conflit entre scripts. Erreurs localisées par `node_id`.",
     "Chaque règle a un test ; une erreur pointe le bon nœud.", S1 + " §4.6, §5.2, §6.1"),
    (1, "Interfaces de drivers et implémentations fictives", ["moteur", "tests"],
     "`RelayDriver`, `ButtonDriver`, `HAClient` abstraits ; versions fictives qui enregistrent les appels.",
     "L'interpréteur tourne entièrement sur les drivers fictifs.", S1 + " §9"),
    (1, "Interpréteur : blocs de contrôle", ["moteur"],
     "`sequence`, `parallel` (`all` / `first`), `repeat` (fois / indéfiniment), `wait` (fixe et aléatoire), `if`, `wait_until`, `random_choice`, `call`, `log`.",
     "Tests de chaque bloc, dont un stop en plein `parallel` et un `repeat` infini arrêté.", S1 + " §5.1"),
    (1, "Interpréteur : actions relais, light, switch et gestion d'erreurs", ["moteur"],
     "Actions `relay` (selon le mode), `light`, `switch`, `fire_and_forget`, `on_error` (continuer par défaut / arrêter).",
     "Les appels attendus sont enregistrés par les drivers fictifs ; une erreur HA n'arrête pas le run par défaut.", S1 + " §5.2, §6.2"),
    (1, "Horloge injectable et mode simulation", ["moteur", "tests"],
     "Horloge virtuelle ; `simulate` renvoie une timeline `[(t, composant, action)]` sans attendre.",
     "Le scénario d'exemple se simule en quelques millisecondes avec une timeline exacte.", S1 + " §9"),
    (1, "Gestionnaire de runs : concurrence, politiques, stop, reset", ["moteur"],
     "Plusieurs runs simultanés, un seul par programme (`ignore` / `restart` / `queue`), stop individuel et global (< 1 s), `on_end: reset` limité aux composants dont le run est le dernier écrivain, timeout par run.",
     "Une ambiance en boucle tourne pendant un scénario ; arrêter le scénario seul laisse l'ambiance intacte ; le stop global éteint tout.", S1 + " §5.3, §6.1"),
    (1, "Persistance en fichiers avec écriture atomique et révisions", ["moteur"],
     "`config.json`, `programs/*.json`, `triggers.json` ; écriture atomique ; `revision` incrémentée et contrôlée (`If-Match`).",
     "Un enregistrement concurrent obsolète est refusé ; aucune corruption après arrêt brutal simulé.", S1 + " §3, §5"),

    (2, "Driver relais GPIO réel", ["materiel", "moteur"],
     "`gpiozero` + `lgpio`. `high()` active le relais (`active_low` configurable). Sorties initialisées à OFF avant toute autre action ; OFF à l'arrêt et sur exception ; `max_on_seconds` imposé si renseigné.",
     "Les 4 relais s'enclenchent et se coupent ; OFF garanti au démarrage et à `SIGTERM`.", S1 + " §4.1, §6.3"),
    (2, "Driver bouton GPIO réel", ["materiel", "moteur"],
     "Pull-up, anti-rebond 50 ms, événements appui court / long (800 ms) / double.",
     "Les trois événements sont détectés de façon fiable sur le bouton 21.", S1 + " §4.2"),
    (2, "CLI halloween-cli", ["moteur", "materiel"],
     "`relay <id> on|off`, `button watch`, `run <id>`, plus tard `unlock --reset`.",
     "Chaque commande fonctionne sur le Pi.", S1 + " §9"),
    (2, "Procédure de test matériel sans charge, puis scénario réel", ["materiel", "docs", "tests"],
     "Documenter : test de chaque relais sans objet branché (clic audible), branchement un par un, puis scénario complet.",
     "Le scénario exemple tourne sur le Pi avec les vrais relais ; `Ctrl+C` laisse tout éteint.", PL + " §3 phase 2"),
    (2, "Vérifier la compatibilité GPIO sur le modèle de Pi utilisé", ["materiel", "risque"],
     "Confirmer tôt que `gpiozero` + `lgpio` pilotent les broches 17, 18, 22, 27 et 21 sur votre Pi (notamment s'il s'agit d'un Pi 5).",
     "Un test minimal fait basculer chaque broche.", PL + " §6"),

    (3, "Client Home Assistant : lumières et interrupteurs", ["home-assistant", "moteur"],
     "`httpx` : `light/turn_on|turn_off` (`rgb_color`, `brightness` 0-255, `transition`), `switch/turn_on|turn_off`, test de connexion (`GET /api/`), liste des entités `light` et `switch`. Jeton jamais renvoyé en clair.",
     "Les corps JSON envoyés correspondent aux specs.", S1 + " §4.3 à §4.5"),
    (3, "Erreurs Home Assistant : délai d'attente, injoignable, jeton refusé", ["home-assistant", "moteur"],
     "Messages distincts, délai d'attente configurable, le run continue par défaut, `fire_and_forget`.",
     "La coupure de HA en plein run n'arrête pas les relais ; l'erreur est tracée.", S1 + " §6.2"),
    (3, "Tests contre un faux serveur HTTP Home Assistant", ["home-assistant", "tests"],
     "Faux serveur qui vérifie URL, jeton et corps JSON exacts.",
     "Les tests passent sans Home Assistant.", S1 + " §9"),
    (3, "Valider sur l'installation réelle : Hue, Twinkly et capacités", ["home-assistant", "risque"],
     "Relever les `entity_id` réels, tester couleur / luminosité / transition sur le bandeau Hue et la guirlande Twinkly, fixer les capacités de chaque light, mesurer la latence.",
     "Les capacités sont renseignées dans la config ; un scénario mêlant relais et lumières tourne sur le Pi.", PL + " §3 phase 3"),

    (4, "Déclencheurs bouton", ["moteur"],
     "Bouton + événement → lancer un programme ou arrêter, avec politique ; appui long = arrêt d'urgence par défaut ; vérification (programme existant, doublons).",
     "L'appui court lance le scénario ; l'appui long l'arrête en moins d'une seconde.", S1 + " §7"),
    (4, "Déclencheurs planifiés (cron)", ["moteur"],
     "Expressions cron, fuseau horaire, rechargement à chaud.",
     "Un déclencheur planifié lance le bon programme à l'heure prévue (test avec horloge virtuelle).", S1 + " §7"),
    (4, "Reprise au démarrage", ["moteur", "securite"],
     "Au démarrage : relais OFF, état de repos appliqué, config et déclencheurs rechargés.",
     "Après redémarrage du Pi, tout est au repos et les déclencheurs fonctionnent.", S1 + " §5.3, §6.3"),

    (5, "API : composants, appareils, entités HA, images", ["moteur"],
     "CRUD des composants (suppression refusée si utilisé), `GET /devices`, `GET /ha/entities`, test manuel, téléversement et service des images (redimensionnement, formats limités).",
     "Toute la configuration se pilote avec `curl`.", S1 + " §8"),
    (5, "API : programmes, validation, simulation", ["moteur"],
     "`GET/PUT/DELETE /programs`, `POST /programs/validate`, `POST /simulate`, contrôle de révision.",
     "Un programme invalide est refusé avec des erreurs par `node_id`.", S1 + " §8"),
    (5, "API : runs, statut, déclencheurs", ["moteur"],
     "`GET/POST /runs`, `POST /runs/{id}/stop`, `POST /runs/stop`, `GET /status`, `GET/PUT /triggers`.",
     "Plusieurs runs se lancent et s'arrêtent individuellement ou globalement.", S1 + " §8"),
    (5, "WebSocket /events", ["moteur"],
     "`run_started`, `node_started`, `node_finished` (avec `run_id`, `script_id`, `node_id`), `component_changed`, `button_event`, `lock_changed`, `run_ended`, `error`.",
     "Un client WebSocket suit un scénario en direct.", S1 + " §8"),
    (5, "Authentification par jeton et service de l'interface", ["moteur", "securite"],
     "Jeton statique `Authorization: Bearer`, API sous `/api`, build statique servi sur `/` avec repli `index.html`.",
     "Une requête sans jeton valide est refusée ; `/spectacle` se charge.", S1 + " §8"),
    (5, "Exporter et figer l'OpenAPI", ["moteur", "docs"],
     "Générer l'OpenAPI, la versionner, la tester contre les routes réelles.",
     "L'interface peut générer son client à partir du fichier.", S2 + " §11"),

    (6, "Verrouillage par code", ["securite", "moteur"],
     "Empreinte salée du code, état persistant, `423` sur toutes les écritures, `POST /runs` exige le code, STOP libre, déclencheurs physiques inchangés, événement `lock_changed`.",
     "Le critère d'acceptation 10 de la spec 1 passe, y compris par appel API direct.", S1 + " §6.4"),
    (6, "Limitation des essais et réinitialisation du code", ["securite", "moteur"],
     "Délai croissant après 5 codes faux (commun à `unlock` et aux lancements), comparaison à temps constant, `halloween-cli unlock --reset`.",
     "Après 5 essais ratés un délai s'applique ; la réinitialisation fonctionne depuis le Pi.", S1 + " §6.4"),
    (6, "Service systemd : reprise, signal de vie, installation", ["securite", "materiel"],
     "Unité `systemd` avec `Restart=always` et `WatchdogSec`, signal de vie de la boucle d'exécution, arrêt propre, script d'installation.",
     "Un gel simulé de la boucle redémarre le processus et éteint les relais.", S1 + " §6.3, §12"),
    (6, "Journal avec rotation et GET /status complet", ["moteur"],
     "Rotation des logs ; `/status` : runs, relais, connexion HA, verrouillage.",
     "Un diagnostic rapide est possible depuis `/status`.", S1 + " §10"),
    (6, "Recette du jalon A", ["tests"],
     "Dérouler tous les critères d'acceptation de la spec 1 (tests automatiques et essais réels).",
     "Jalon A validé : le moteur est complet et pilotable en ligne de commande.", S1 + " §11"),

    (7, "Projet Vite React TypeScript et client d'API généré", ["interface"],
     "Initialiser `ui/`, générer le client depuis l'OpenAPI, gestion du jeton.",
     "L'application s'affiche et appelle `/status` sur le moteur en simulation.", S2 + " §2"),
    (7, "Thème sombre et composants de base d'après les maquettes", ["interface"],
     "Jetons de couleur et de typographie (fond violet-noir, accent orange, Fraunces / Inter), boutons, pastilles d'état, tuiles, formulaires.",
     "Les composants de base reproduisent les maquettes, avec un contraste suffisant et des cibles ≥ 44 px.", S2 + " §6"),
    (7, "Mise en page, bandeau permanent et WebSocket", ["interface"],
     "Barre latérale, bandeau (état moteur et HA, runs en cours, cadenas, STOP), WebSocket avec reconnexion et resynchronisation.",
     "Le STOP global est toujours visible ; la perte de connexion est signalée puis résorbée.", S2 + " §3, §6"),
    (7, "Gestion des erreurs d'API et état hors ligne", ["interface"],
     "Toasts lisibles, détails dépliables, écran « moteur injoignable » avec Réessayer.",
     "Une coupure du moteur désactive l'interface proprement.", S2 + " §6"),

    (8, "Écran Composants : liste et onglets", ["interface"],
     "Onglets Relais, Boutons, Lumières, Interrupteurs ; cartes avec usages ; ajout.",
     "Les composants existants s'affichent comme sur la maquette.", S2 + " §4.2"),
    (8, "Formulaires de composants", ["interface"],
     "Champs par type, pins déjà utilisées grisées, choix d'image (bibliothèque / téléversement), entités HA en liste, test manuel, refus de suppression d'un composant utilisé.",
     "Créer le relais « Fantôme » (pin 18) depuis une tablette et le tester.", S2 + " §4.2"),
    (8, "Tableau de bord", ["interface"],
     "Tuiles en direct avec interrupteurs de test, runs en cours (progression, arrêt individuel), événements des boutons.",
     "L'état affiché suit la réalité en temps réel.", S2 + " §4.1"),
    (8, "Réglages : Home Assistant, jeton, état de repos, code", ["interface"],
     "URL et jeton HA avec test de connexion, jeton du moteur, état de repos par composant, définition du code de verrouillage.",
     "La connexion HA se configure et se teste depuis l'interface.", S2 + " §4.3"),

    (9, "Prototype : un bloc relais avec sérialisation", ["interface", "risque"],
     "Prototype Blockly minimal (bloc début + bloc relais) avec sérialisation vers le JSON et rechargement.",
     "L'aller-retour est sans perte ; décision confirmée sur la bibliothèque d'intégration React.", PL + " §6"),
    (9, "Blocs générés depuis /devices", ["interface"],
     "Un bloc par composant avec image et nom, paramètres facultatifs selon les capacités (couleur, luminosité, transition), options `fire_and_forget` et `on_error`.",
     "Ajouter un composant le fait apparaître dans la palette.", S2 + " §5.2, §5.3"),
    (9, "Blocs de contrôle et blocs début multiples", ["interface"],
     "Début, parallèle, répéter (N / indéfiniment), attendre (fixe / aléatoire), si / sinon, attendre jusqu'à, choix aléatoire, appeler un scénario. Plusieurs blocs début par scénario.",
     "Un scénario à deux scripts parallèles se construit par glisser-déposer.", S2 + " §5.1, §5.2"),
    (9, "Sérialisation blocs ↔ JSON et tests d'aller-retour", ["interface", "tests"],
     "Correspondance du §5.4, `id` de nœud stables, mise en page dans `editor`, mise en page automatique des programmes créés par API.",
     "Aller-retour sans perte sur un jeu de programmes types, dont l'annexe de la spec 1.", S2 + " §5.4"),
    (9, "Validation en direct et avertissements de conflit", ["interface"],
     "`POST /programs/validate` après 500 ms d'inactivité, bloc fautif en rouge, panneau des erreurs, avertissement quand deux scripts commandent le même composant.",
     "Un composant supprimé ou un paramètre non supporté est signalé sur le bon bloc.", S2 + " §5.5, §5.6"),
    (9, "Simulation : frise temporelle", ["interface"],
     "`POST /simulate` et affichage d'une ligne par composant avec les périodes d'activation.",
     "La frise d'un scénario d'exemple est lisible et exacte.", S2 + " §5.7"),
    (9, "Exécution : surlignage du bloc actif dans chaque script", ["interface"],
     "Lancer, surligner les blocs en cours dans tous les scripts, estomper les blocs terminés, éditeur en lecture seule pendant le run, stop du run, bandeau de fin.",
     "Deux scripts s'affichent surlignés en même temps ; l'arrêt d'un run laisse l'autre actif.", S2 + " §5.7"),
    (9, "Enregistrement, brouillon et conflit de révision", ["interface"],
     "Brouillon dans le navigateur, enregistrement explicite (`Ctrl+S`), avertissement avant de quitter, conflit « écraser / recharger », annuler / rétablir.",
     "Recharger la page restitue la mise en page à l'identique.", S2 + " §5.8"),

    (10, "Écran Déclencheurs", ["interface"],
     "Règles lisibles, sélecteurs source / bouton / événement / action / politique, constructeur de planning avec prévisualisation, alerte de doublons, appui long proposé en arrêt.",
     "Créer « bouton d'entrée, appui court → scénario principal » et le vérifier avec le bouton physique.", S2 + " §4.4"),
    (10, "Mode spectacle", ["interface"],
     "Plein écran, tuiles Lancer pour les scénarios cochés, ordre d'affichage, scénarios en continu en bascule, STOP, écran maintenu allumé, route `/spectacle`, utilisable à 360 px.",
     "Aucune route de modification n'est accessible depuis cet écran.", S2 + " §4.7"),
    (10, "Verrouillage côté interface", ["interface", "securite"],
     "Cadenas, pavé numérique, code demandé à chaque lancement quand c'est verrouillé, STOP libre, lecture seule, réaction à `lock_changed`.",
     "Les critères 10 et 11 de la spec 2 passent.", S2 + " §4.8"),

    (11, "Bibliothèque d'icônes et page À propos", ["interface", "docs"],
     "Intégrer une trentaine d'icônes (game-icons.net pour Halloween, Lucide pour l'interface), vérifier la licence de chaque icône, lister les auteurs dans Réglages › À propos.",
     "Les icônes sont proposées dans le sélecteur d'image ; les attributions sont affichées.", S2 + " §4.2, §10"),
    (11, "Tests de bout en bout Playwright", ["tests", "interface"],
     "Parcours : créer des composants, construire un scénario, le lancer en simulation, voir le surlignage, STOP, verrouillage.",
     "Les parcours passent contre le moteur en mode simulation.", S2 + " §9"),
    (11, "Build, déploiement sur le Pi et documentation d'exploitation", ["docs", "materiel"],
     "Build statique servi par le moteur, déploiement, sauvegarde du dossier de données, réinitialisation du code, dépannage.",
     "Une installation neuve sur un Pi se fait en suivant la doc.", PL + " §3 phase 11"),
    (11, "Recette finale du jalon B", ["tests"],
     "Dérouler les critères d'acceptation des deux specs sur le matériel réel, avec essai sur tablette et téléphone.",
     "Application complète, utilisable le soir d'Halloween.", S2 + " §8"),
]


def gh(*args, check=True):
    return subprocess.run(["gh", *args], capture_output=True, text=True, check=check)


def body(desc, done, ref):
    return f"{desc}\n\n**Terminé quand** : {done}\n\nRéférence : `{ref}`"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--project", action="store_true", help="crée aussi un projet GitHub (jeton avec le droit « project »)")
    a = ap.parse_args()

    if a.dry_run:
        for i, (t, _) in enumerate(MILESTONES):
            print(f"\n## {t}")
            for lot, title, labels, *_ in ISSUES:
                if lot == i:
                    print(f"  - {title}  [{', '.join(labels)}]")
        print(f"\n{len(MILESTONES)} jalons, {len(ISSUES)} issues, {len(LABELS)} labels")
        return

    for name, (color, desc) in LABELS.items():
        gh("label", "create", name, "-R", REPO, "--color", color, "--description", desc, "--force")
    print("labels OK")

    existing_ms = {m["title"]: m["number"] for m in json.loads(gh("api", f"repos/{REPO}/milestones?state=all&per_page=100").stdout)}
    for title, desc in MILESTONES:
        if title in existing_ms:
            continue
        r = gh("api", "-X", "POST", f"repos/{REPO}/milestones", "-f", f"title={title}", "-f", f"description={desc}")
        existing_ms[title] = json.loads(r.stdout)["number"]
    print("jalons OK")

    existing = {i["title"] for i in json.loads(gh("issue", "list", "-R", REPO, "--state", "all", "--limit", "500", "--json", "title").stdout)}
    urls = []
    for lot, title, labels, desc, done, ref in ISSUES:
        if title in existing:
            continue
        r = gh("issue", "create", "-R", REPO, "-t", title, "-b", body(desc, done, ref),
               "-l", ",".join(labels), "-m", MILESTONES[lot][0])
        url = r.stdout.strip()
        urls.append(url)
        print(url)

    if a.project:
        p = json.loads(gh("project", "create", "--owner", OWNER, "--title", PROJECT_TITLE, "--format", "json").stdout)
        for u in json.loads(gh("issue", "list", "-R", REPO, "--state", "all", "--limit", "500", "--json", "url").stdout):
            gh("project", "item-add", str(p["number"]), "--owner", OWNER, "--url", u["url"])
        print("projet :", p["url"])
    print(f"{len(urls)} issues créées")


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as e:
        sys.exit(f"Erreur gh : {e.stderr.strip() or e.stdout.strip()}")
