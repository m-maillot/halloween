# Recette du jalon B (interface complète, utilisable le soir d'Halloween)

Référence : [spec 2 §8](spec-2-interface.md), complétée par les critères du moteur ([recette du jalon A](recette-jalon-a.md)). Chaque critère est rattaché aux tests qui le démontrent (moteur et matériel simulés, navigateur Chromium automatisé) et à l'**essai réel** qui reste à faire. Un test (`ui/src/recette.test.ts`) vérifie que chaque test cité ici existe encore.

Légende : ✅ démontré automatiquement · ⏳ à valider sur le matériel ou sur un appareil réel (**non fait**).

**Jalon B : fonctions validées sur moteur simulé ; installation sur un Pi vierge, câblage, Home Assistant, tablette et téléphone réels non validés.**

## Avant tout : installation sur un Pi vierge (issue #58)

⏳ Suivre [exploitation.md §1](exploitation.md) sur un Raspberry Pi OS neuf, sans autre aide, jusqu'à l'interface ouverte depuis une tablette. Noter tout écart entre la doc et la réalité et corriger la doc. Tant que ce n'est pas fait, #58 reste ouverte.

## Résultat

| # | Critère (résumé) | Automatique | Essai réel |
|---|---|---|---|
| 1 | Créer « Fantôme » (broche 18), icône puis image téléversée, tester, tuile | ✅ | ⏳ tablette, vraie photo non carrée |
| 2 | Light en ne cochant que « luminosité » : le bloc ne propose ni couleur ni transition | ✅ | ⏳ capacités réelles Hue / Twinkly |
| 3 | URL + jeton HA, test explicite, choix d'une light dans la liste | ✅ | ⏳ votre Home Assistant |
| 4 | Scénario avec `parallel`, boucle, attente aléatoire par glisser-déposer ; mise en page identique après rechargement | ✅ | ⏳ au doigt sur tablette |
| 5 | Scénario invalide signalé sur le bon bloc, non lançable | ✅ | n/a |
| 6 | Lancer : bloc actif surligné, STOP, relais éteints en moins d'une seconde | ✅ (hors « < 1 s » mesuré) | ⏳ relais réels |
| 6b | Deux scripts surlignés ensemble ; ambiance + scénario ; STOP global ; arrêt individuel | ✅ | ⏳ relais réels |
| 7 | Règle « bouton d'entrée, appui court → scénario » ; appui long arrête | ✅ (appui simulé) | ⏳ bouton physique |
| 8 | Perte de connexion : « hors ligne », reconnexion, resynchronisation | ✅ | ⏳ coupure Wi-Fi réelle |
| 9 | Spectacle et tableau de bord à 360 px ; configuration et éditeur à partir de 768 px | ✅ (360 px) | ⏳ téléphone réel |
| 10 | Spectacle : cochés seulement, Lancer, STOP, écran sans veille, aucune route de modification | ✅ (veille simulée) | ⏳ veille sur la tablette |
| 11 | Verrouillage : 423, STOP libre, lancement avec code, déverrouillage avec code, délai après 5 faux | ✅ | ⏳ verrou après redémarrage du Pi |

## Détail par critère

### 1. Composants
- `ui/src/catalog/ComponentForm.test.tsx::créer le relais « Fantôme » (broche 18) avec une icône, puis le tester`
- `ui/src/catalog/ComponentForm.test.tsx::une image personnelle est téléversée en corps brut puis référencée`
- `ui/src/pages/Dashboard.test.tsx::les tuiles reflètent l'état réel : relais du moteur, lumières et interrupteurs de Home Assistant`
- `ui/e2e/parcours.spec.ts::composants : créer « Fantôme » (broche 18) avec une icône, le tester, le voir en tuile`

### 2. Capacités des lumières
- `ui/src/catalog/ComponentForm.test.tsx::une lumière créée en ne cochant que « luminosité » n'annonce ni couleur ni transition`
- `ui/src/editor/serialize.test.ts::une lumière sans couleur ni transition (guirlande) ne propose que la luminosité dans ses options`
- `ui/e2e/parcours.spec.ts::lumière à capacités limitées : le bloc ne propose que la luminosité`
- Défaut trouvé pendant cette recette : avant correction, le bloc de la guirlande affichait quand même couleur et transition (Blockly rétablit la visibilité d'un champ d'après celle de sa ligne) ; chaque paramètre a désormais sa ligne.

### 3. Home Assistant
- `ui/src/pages/Settings.test.tsx::tester la connexion utilise les valeurs saisies et dit le résultat`
- `ui/src/catalog/ComponentForm.test.tsx::une lumière : entités en liste, capacités préremplies, test avec couleur`
- `ui/src/catalog/ComponentForm.test.tsx::Home Assistant injoignable : l'entité se saisit à la main`

### 4. Éditeur de blocs
- `ui/e2e/parcours.spec.ts::éditeur : construire un scénario par glisser-déposer, l'enregistrer, le recharger, le simuler`
- `ui/src/editor/programs.test.ts::la mise en page (positions, blocs repliés, zoom, défilement) est restituée à l'identique`
- `ui/src/editor/serialize.test.ts::tous les types de nœuds font l'aller-retour, boucle sans fin comprise`

### 5. Scénario invalide
- `ui/src/editor/ScenarioEditor.test.tsx::une erreur du moteur est posée sur le bon bloc et bloque l'enregistrement`
- `ui/src/pages/Dashboard.test.tsx::Lancer démarre le scénario ; un scénario invalide ne se lance pas`

### 6. Lancer, surligner, STOP
- `ui/e2e/parcours.spec.ts::exécution : surlignage du bloc actif dans chaque script, puis STOP`
- `ui/src/editor/runView.test.ts::les blocs démarrent, puis se terminent : en cours puis estompés`
- `ui/src/App.test.tsx::STOP appelle l'arrêt global, même verrouillé`

### 6b. Parallélisme
- `ui/e2e/parcours.spec.ts::exécution : surlignage du bloc actif dans chaque script, puis STOP`
- `ui/src/editor/runView.test.ts::deux scripts d'un même run sont surlignés en même temps ; les blocs terminés sont estompés`
- `ui/src/pages/Spectacle.test.tsx::plusieurs scénarios tournent en même temps : progression, « en continu », arrêt individuel`
- `ui/src/pages/Dashboard.test.tsx::chaque scénario en cours s'arrête individuellement`

### 7. Déclencheurs
- `ui/e2e/parcours.spec.ts::déclencheur : « bouton d'entrée, appui court → scénario » puis appui du bouton`
- `ui/src/pages/Triggers.test.tsx::créer « bouton d'entrée, appui court → scénario principal »`
- `ui/src/pages/Triggers.test.tsx::un bouton sans règle d'appui long se voit proposer « appui long → Arrêter »`
- Côté moteur (appui long = arrêt global) : voir la recette du jalon A, critère 5.

### 8. Perte de connexion
- `ui/src/App.test.tsx::la perte du WebSocket est signalée, puis résorbée à la reconnexion avec resynchronisation`
- `ui/src/App.test.tsx::moteur injoignable : écran dédié, navigation inerte, STOP désactivé, puis reprise avec Réessayer`
- `ui/src/engine/socket.test.ts::après une coupure, se reconnecte avec des délais croissants puis plafonnés`

### 9. Petits écrans
- `ui/e2e/parcours.spec.ts::téléphone (360 px) : le tableau de bord et le mode spectacle ne débordent pas`

### 10. Mode spectacle
- `ui/e2e/parcours.spec.ts::mode spectacle : seuls les scénarios cochés, Lancer, STOP, aucun lien de modification`
- `ui/src/pages/Spectacle.test.tsx::aucun lien, aucun menu : rien ne mène à la configuration, à l'éditeur ou à la suppression`
- `ui/src/pages/Spectacle.test.tsx::l'écran est maintenu allumé, puis relâché en quittant`

### 11. Verrouillage
- `ui/e2e/parcours.spec.ts::verrouillage : code défini, écritures refusées (423), STOP libre, lancement avec code, déverrouillage`
- `ui/src/lock/Lock.test.tsx::trop d'essais : le délai imposé s'affiche, décompte, et réactive Valider à la fin`
- `ui/src/lock/Lock.test.tsx::le verrouillage décidé ailleurs (lock_changed) rend l'écran en lecture seule aussitôt`
- `engine/tests/test_api_lock.py` (423 sur toute écriture, empreinte, délai, persistance) : voir la recette du jalon A, critère 10.

## Essais réels à dérouler (dans l'ordre)

Cocher ici, et dans l'issue de suivi [#82](https://github.com/m-maillot/halloween/issues/82), au fur et à mesure :

- [ ] **Installation sur un Pi vierge** par la doc seule (#58)
- [ ] Recette du jalon A ([recette-jalon-a.md](recette-jalon-a.md)) : câblage, Home Assistant, redémarrage, verrou après reboot
- [ ] Critères 1 à 11 ci-dessus, sur **la tablette** puis sur **un téléphone**, contre le Pi réel
- [ ] Critère 10 : l'écran de la tablette reste allumé 10 minutes en mode spectacle
- [ ] Critère 6 : mesurer l'arrêt au STOP (relais réels) : moins d'une seconde
- [ ] Une **répétition complète** de la soirée : scénario principal, ambiance en parallèle, appui court / long, verrouillage, STOP, redémarrage du Pi en cours de route

Quand tout est coché : fermer #58, #59 et #82 ; le jalon B est atteint.
