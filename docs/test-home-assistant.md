# Validation sur votre installation Home Assistant

À dérouler une fois, après la [procédure matériel](test-materiel.md) (ou en parallèle : cette étape n'a pas besoin des relais). Elle sert à :

1. relever les `entity_id` réels du bandeau Hue et de la guirlande Twinkly ;
2. fixer les **capacités** de chaque lumière dans `config.json` (couleur, luminosité, transition) ;
3. mesurer la latence des appels ;
4. vérifier qu'un scénario mêlant relais et lumières tourne.

Tout se fait avec `halloween-cli` (depuis `engine/`, voir la procédure matériel pour l'installation).

## 1. Créer un jeton d'accès

Dans Home Assistant : votre profil (en bas à gauche) → **Sécurité** → **Jetons d'accès longue durée** → *Créer un jeton*. Copier la valeur (elle n'est affichée qu'une fois).

Deux façons de la fournir au moteur :

```bash
export HALLOWEEN_HA_TOKEN='le-jeton'          # sans l'écrire sur le disque (prioritaire)
```

ou dans `~/halloween-data/config.json` : `"home_assistant": { "url": "http://homeassistant.local:8123", "token": "le-jeton" }` (fichier en permissions 600, ne pas le versionner).

## 2. Vérification en lecture seule

```bash
uv run halloween-cli ha-check
```

La commande **ne commande rien**. À observer :

- [ ] `OK … connexion (… ms)` : l'URL et le jeton sont bons. Sinon un message dit pourquoi : *jeton refusé*, *connexion refusée*, *nom d'hôte introuvable*, *n'a pas répondu*…
- [ ] La liste « Entités lumière / interrupteur disponibles » contient vos équipements. **Noter les `entity_id`** du bandeau Hue et de la guirlande Twinkly.
- [ ] Si un composant de `config.json` est en `ÉCHEC … introuvable`, corriger son `entity_id` (des entités proches sont suggérées).
- [ ] Pour chaque lumière, la ligne **couleur / luminosité / transition** compare ce que dit `config.json` et ce que déclare Home Assistant :
  - `OK` : cohérent ;
  - `ATTENTION … disponible mais non utilisée` : la lumière sait le faire, mettez `true` dans la config pour pouvoir l'utiliser dans les scénarios ;
  - `ÉCHEC … la config demande une capacité que la lumière n'a pas` : mettez `false`.

Reporter le résultat dans `config.json` (exemple, **à adapter** aux valeurs affichées) :

```json
{ "id": "bandeau", "entity_id": "light.…", "supports_color": true, "supports_brightness": true, "supports_transition": true }
```

> Les capacités sont déduites des attributs `supported_color_modes` et `supported_features` de Home Assistant. Une intégration peut les annoncer de façon incomplète : le test actif ci-dessous est la vérification réelle.

## 3. Test actif (les lumières vont bouger)

```bash
uv run halloween-cli ha-check --active
```

Chaque lumière configurée est allumée, passée à 50 % de luminosité, en rouge puis en vert, avec une transition de 2 s (seulement ce que la config déclare), avec une pause d'une seconde entre chaque essai (`--pause`). **Leur état d'avant est restauré** à la fin, ainsi que celui des interrupteurs.

- [ ] Vous **voyez** bien chaque changement sur le bandeau et la guirlande.
- [ ] Aucune ligne `ÉCHEC … refusé`. Si un paramètre est refusé (ex. la transition), mettez `false` pour cette capacité.
- [ ] La ligne **Latence des appels** : noter la moyenne et le maximum. C'est le temps de réponse de l'API ; la réaction visible d'une ampoule Hue peut s'y ajouter. Si la latence dépasse quelques centaines de ms, préférez `fire_and_forget` dans les blocs lumière d'un scénario rythmé.
- [ ] Ce qui est restauré : l'éclairage revient à son état de départ.

## 4. Scénario mêlant relais et lumières

```bash
uv run halloween-cli simulate scenario-principal
uv run halloween-cli run scenario-principal
```

Avec un jeton configuré, `run` envoie maintenant de **vrais appels** (`Home Assistant : appels réels vers …`). Sans jeton, ou avec `--ha-dry-run`, les appels sont seulement affichés.

- [ ] Le bandeau passe en rouge à 40 % avec une transition de 2 s au début, puis les relais suivent.
- [ ] À la fin, la remise au repos (`rest_state` dans `config.json`) est appliquée : bandeau orange faible et guirlande, par défaut. **Ajustez ces valeurs à votre goût.**
- [ ] **Coupez Home Assistant (ou le Wi-Fi du Pi)** pendant un scénario : les relais doivent continuer, avec des erreurs journalisées (`halloween-cli -v run …` pour les voir).

## 5. Essayer sans Home Assistant

Pour vérifier le câblage du moteur sans rien commander (ou avant d'avoir un jeton) :

```bash
uv run python -m halloween.testing.fake_ha --port 8123 --token essai
```

puis mettre `http://localhost:8123` et le jeton `essai` dans la configuration. Les entités de ce faux serveur sont des **exemples**, pas votre installation.

## 6. Ce qu'il faut me renvoyer

- la sortie de `halloween-cli ha-check --active` (sans le jeton) ;
- la latence moyenne / maximale relevée ;
- les capacités finalement retenues pour chaque lumière ;
- tout comportement inattendu de la guirlande Twinkly (c'est elle qui est la moins standard).

## Dépannage

| Message | Piste |
|---|---|
| `jeton refusé` | jeton recréé / mal copié ; vérifier `HALLOWEEN_HA_TOKEN` qui prime sur le fichier |
| `connexion refusée` | mauvais port (8123 par défaut), Home Assistant éteint, pare-feu |
| `nom d'hôte introuvable` | `homeassistant.local` non résolu depuis le Pi : utiliser l'adresse IP |
| `introuvable (HTTP 404)` | l'URL n'est pas la racine de Home Assistant (préfixe, mauvais port) |
| `n'a pas répondu en 5 s` | Home Assistant lent ou bloqué ; augmenter `timeout_s` (max 60) |
| Scénario décalé quand HA est coupé | normal au premier appel (délai) puis court-circuité pendant 10 s ; voir spec 1 §6.2 |
