# Interface

Application React + TypeScript (Vite) : configuration des composants, scénarios (éditeur de blocs Blockly), déclencheurs, mode spectacle, verrouillage.

Spécification : [docs/spec-2-interface.md](../docs/spec-2-interface.md).

## Développer

```bash
make ui-install                       # une fois (npm ci)
cd engine && uv run halloween-cli --data-dir /tmp/halloween api --ha-dry-run   # moteur (sur le Pi ; GPIO requis)
cd ui && npm run dev                  # http://localhost:5173, /api relayé vers le moteur
```

`HALLOWEEN_ENGINE=http://<ip-du-pi>:8080 npm run dev` pointe vers un moteur distant. Au premier lancement l'écran demande le jeton (`/var/lib/halloween/api-token`), mémorisé dans le navigateur.

## Client d'API

`src/api/schema.d.ts` est **généré** depuis [docs/openapi.json](../docs/openapi.json) (`make ui-api`) et versionné : un changement d'API du moteur apparaît dans le diff. `make ui-check` échoue si le fichier n'est pas à jour.

## Vérifier et déployer

`make ui-check` (types, tests, build). Le build (`ui/dist`) est servi par le moteur : `halloween-cli api --ui-dir ui/dist` ou `HALLOWEEN_UI_DIR`.

## Tests de bout en bout

`make ui-e2e` (ou `cd ui && npm run e2e`) construit l'interface, démarre le **vrai moteur en simulation** (`halloween-cli api --simulate` : pilotes fictifs, dossier de données neuf `ui/.e2e-data`) puis joue six parcours dans Chromium : composants, éditeur (glisser-déposer, enregistrement, rechargement, simulation), exécution (surlignage de deux scripts, STOP), déclencheur, mode spectacle, verrouillage.

Navigateur : `npx playwright install chromium` la première fois, ou un Chromium déjà installé désigné par `E2E_CHROMIUM=/chemin/vers/chrome`. Les parcours s'enchaînent sur le même moteur (ordre du fichier) ; en cas d'échec, la trace est dans `ui/test-results/`.
