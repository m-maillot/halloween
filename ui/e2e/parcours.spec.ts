import { expect, test } from "@playwright/test";
import { api, blockCount, createRelay, dragFromToolbox, lastBlock, open, saveProgram } from "./helpers";

// Les parcours s'enchaînent sur le même moteur : chacun part de ce que le précédent a laissé,
// ou le prépare par l'API quand il n'en dépend pas.
test.describe.configure({ mode: "serial" });

test("composants : créer « Fantôme » (broche 18) avec une icône, le tester, le voir en tuile", async ({ page }) => {
  await open(page, "/composants");
  await page.getByRole("button", { name: "Ajouter un relais" }).click();
  const dialog = page.getByRole("dialog", { name: "Ajouter relais" });
  await dialog.getByLabel("Nom", { exact: true }).fill("Fantôme");
  await dialog.getByRole("button", { name: "Fantôme", exact: true }).click(); // icône « Fantôme » de la bibliothèque
  await dialog.getByLabel(/Broche/).selectOption("18");
  await dialog.getByRole("button", { name: "Enregistrer" }).click();
  await expect(dialog).toBeHidden();
  await expect(page.getByLabel("Fantôme")).toBeVisible();

  // test manuel depuis la fenêtre du composant
  await page.getByLabel("Fantôme").click();
  const edit = page.getByRole("dialog", { name: "Modifier relais" });
  await edit.getByRole("button", { name: "Allumer" }).click();
  await expect(edit.getByRole("status")).toContainText("Fantôme : on");
  await edit.getByRole("button", { name: "Annuler" }).click();

  // la tuile du tableau de bord suit l'état réel
  await page.getByRole("link", { name: "Tableau de bord" }).click();
  const tile = page.getByLabel("Fantôme");
  await expect(tile.getByText("Allumé")).toBeVisible();
  await tile.getByRole("button", { name: "Éteindre" }).click();
  await expect(tile.getByText("Éteint")).toBeVisible();
});

test("éditeur : construire un scénario par glisser-déposer, l'enregistrer, le recharger, le simuler", async ({ page, request }) => {
  await createRelay(request, "Orage", 22, "builtin:storm");
  await open(page, "/scenarios");
  await page.getByRole("button", { name: "Nouveau scénario" }).click();
  await page.getByRole("dialog").getByLabel("Nom").fill("Mon scénario");
  await page.getByRole("button", { name: "Créer" }).click();
  await expect(page.getByRole("heading", { name: "Validation" })).toBeVisible();

  // un début est déjà posé : on lui accroche le fantôme, une attente, puis l'orage, chacun sous le précédent
  const append = async (category: string, type: string, below: string, match?: RegExp) => {
    const anchor = await lastBlock(page, below);
    // le bloc est saisi à 14 px de son coin : on le lâche juste sous le précédent, bord gauche aligné
    await dragFromToolbox(page, category, type, { x: anchor.x + 14, y: anchor.y + anchor.h + 14 }, match);
    await page.waitForTimeout(300);
  };
  await append("Relais", "hw_relay", "hw_start", /Fantôme/);
  await append("Contrôle", "hw_wait", "hw_relay");
  await append("Relais", "hw_relay", "hw_wait", /Orage/);
  await expect.poll(() => blockCount(page, "hw_relay")).toBe(2);
  await expect(page.getByText(/aucun bloc « quand le scénario démarre »|n'est rattaché à aucun bloc/)).toHaveCount(0); // tout est bien accroché
  // valide (le « jamais éteint » est un simple avertissement) : l'enregistrement n'est pas bloqué
  await expect(page.getByText(/^(Scénario valide|Valide, \d+ avertissements?)$/)).toBeVisible();

  await page.keyboard.press("Control+s");
  await expect(page.getByText("Scénario enregistré.")).toBeVisible();

  // blocs de contrôle posés dans les entrées d'instructions : en parallèle, répéter, attente aléatoire
  const inside = async (category: string, type: string, parent: string, dx: number, dy: number) => {
    const anchor = await lastBlock(page, parent);
    await dragFromToolbox(page, category, type, { x: anchor.x + dx, y: anchor.y + dy });
    await page.waitForTimeout(300);
  };
  await append("Contrôle", "hw_repeat", "hw_relay");
  await inside("Contrôle", "hw_wait_random", "hw_repeat", 150, 26);
  await append("Contrôle", "hw_parallel", "hw_repeat");
  await inside("Relais", "hw_relay", "hw_parallel", 80, 56);
  await expect.poll(() => blockCount(page, "hw_wait_random")).toBe(1);
  await expect(page.getByText(/n'est rattaché à aucun bloc/)).toHaveCount(0);
  await expect(page.getByText(/^(Scénario valide|Valide, \d+ avertissements?)$/)).toBeVisible();
  await page.keyboard.press("Control+s");
  await expect(page.getByText("Scénario enregistré.").last()).toBeVisible();
  const saved = await (await api(request, "get", "/programs/mon-scenario")).json();
  const types = JSON.stringify(saved.scripts);
  expect(types).toContain('"type":"parallel"');
  expect(types).toContain('"type":"repeat"');
  expect(types).toContain('"min"'); // attente aléatoire

  // la mise en page et les blocs survivent au rechargement
  const before = await blockCount(page, "hw_relay");
  const hatBefore = await lastBlock(page, "hw_start");
  await page.reload();
  await expect(page.getByRole("heading", { name: "Validation" })).toBeVisible();
  await expect.poll(() => blockCount(page, "hw_relay")).toBe(before);
  await expect.poll(() => blockCount(page, "hw_parallel")).toBe(1);
  // mise en page restituée à l'identique (le début au même endroit à l'écran)
  await expect.poll(async () => (await lastBlock(page, "hw_start")).y, { timeout: 3000 }).toBeCloseTo(hatBefore.y, -1);

  // simulation : une ligne par composant dans la frise
  await page.getByRole("button", { name: "Simuler" }).click();
  const frise = page.getByRole("region", { name: "Frise temporelle" });
  await expect(frise.getByText(/Terminé en/)).toBeVisible();
  await expect(frise.getByRole("img", { name: /Fantôme : allumé/ }).first()).toBeVisible();
  await expect(frise.getByRole("img", { name: /Orage : allumé/ }).first()).toBeVisible();
});

test("exécution : surlignage du bloc actif dans chaque script, puis STOP", async ({ page, request }) => {
  await saveProgram(request, "deux-scripts", "Deux scripts", [{ id: "a", type: "relay", target: "orage", state: "on" }, { id: "w", type: "wait", seconds: 30 }]);
  const current = await (await api(request, "get", "/programs/deux-scripts")).json();
  current.scripts.push({ id: "s2", hat: { type: "start" }, root: { id: "r2", type: "sequence", children: [{ id: "b", type: "relay", target: "fantome", state: "on" }, { id: "w2", type: "wait", seconds: 30 }] } });
  await api(request, "put", "/programs/deux-scripts", current, { "If-Match": `"${current.revision}"` });

  await open(page, "/scenarios/deux-scripts");
  await expect(page.getByText(/^(Scénario valide|Valide, \d+ avertissements?)$/)).toBeVisible();
  await page.getByRole("button", { name: "Lancer" }).click();
  await expect(page.getByText("Scénario en cours…")).toBeVisible();
  // deux scripts : les deux attentes sont surlignées en même temps (plus les deux chapeaux)
  await expect.poll(() => page.locator(".hw-block-active").count()).toBeGreaterThanOrEqual(4);
  await expect(page.getByRole("button", { name: "Enregistrer" })).toBeDisabled(); // lecture seule pendant le run

  await page.getByRole("button", { name: "Arrêt d'urgence : tout arrêter" }).click();
  await expect(page.getByText(/Arrêté/)).toBeVisible();
  await expect(page.getByText("Aucun scénario en cours")).toBeVisible();
  // l'état de repos est revenu : les relais sont éteints
  const status = await (await api(request, "get", "/status")).json();
  expect(Object.values(status.relays).every((on) => on === false)).toBe(true);
});

test("déclencheur : « bouton d'entrée, appui court → scénario » puis appui du bouton", async ({ page, request }) => {
  const response = await api(request, "post", "/components/buttons", { name: "Bouton d'entrée", pin: 21 });
  expect(response.status()).toBe(201);
  await open(page, "/declencheurs");
  await page.getByRole("button", { name: "Nouvelle règle" }).click();
  const dialog = page.getByRole("dialog", { name: "Nouvelle règle" });
  await dialog.getByLabel("Scénario à lancer").selectOption("deux-scripts");
  await dialog.getByRole("button", { name: "Enregistrer" }).click();
  await expect(page.getByText("Quand Bouton d'entrée reçoit un appui court")).toBeVisible();

  // appui simulé sur le bouton : le scénario démarre
  await api(request, "post", "/components/buttons/bouton-d-entree/test", { action: "press", event: "short" });
  await expect.poll(async () => (await (await api(request, "get", "/runs")).json()).map((r: { program_id: string }) => r.program_id)).toContain("deux-scripts");
  await api(request, "post", "/runs/stop");
});

test("mode spectacle : seuls les scénarios cochés, Lancer, STOP, aucun lien de modification", async ({ page, request }) => {
  const current = await (await api(request, "get", "/programs/deux-scripts")).json();
  await api(request, "put", "/programs/deux-scripts", { ...current, show: true, show_order: 1 }, { "If-Match": `"${current.revision}"` });
  await saveProgram(request, "cache", "Pas affiché", [{ id: "x", type: "wait", seconds: 1 }]);
  await open(page, "/spectacle");
  await expect(page.getByLabel("Deux scripts").first()).toBeVisible();
  await expect(page.getByLabel("Pas affiché")).toHaveCount(0);
  await expect(page.getByRole("link")).toHaveCount(0);
  await page.getByLabel("Deux scripts").first().getByRole("button", { name: "Lancer" }).click();
  await expect(page.getByLabel("Deux scripts").first().getByRole("button", { name: "Arrêter" })).toBeVisible();
  await page.getByRole("button", { name: /STOP/ }).click();
  await expect(page.getByLabel("Deux scripts").first().getByRole("button", { name: "Lancer" })).toBeVisible();
});

test("verrouillage : code défini, écritures refusées (423), STOP libre, lancement avec code, déverrouillage", async ({ page, request }) => {
  await open(page, "/reglages");
  const lock = page.getByRole("region", { name: "Code de verrouillage" });
  await lock.getByLabel("Nouveau code", { exact: true }).fill("2468");
  await lock.getByLabel("Confirmer le nouveau code").fill("2468");
  await lock.getByRole("button", { name: "Définir le code" }).click();
  await expect(page.getByText(/Code défini/)).toBeVisible();

  await page.getByRole("button", { name: /Déverrouillé : verrouiller/ }).click();
  await expect(page.getByRole("button", { name: /Verrouillé : saisir le code/ })).toBeVisible();

  // le moteur refuse les écritures, même par l'API directe
  expect((await api(request, "post", "/components/switches", { name: "X", entity_id: "switch.x" })).status()).toBe(423);
  // lancement : sans code ou avec un faux, refusé ; STOP toujours libre
  expect((await api(request, "post", "/runs", { program_id: "deux-scripts" })).status()).toBe(423);
  expect((await api(request, "post", "/runs", { program_id: "deux-scripts", code: "0000" })).status()).toBe(401);
  expect((await api(request, "post", "/runs/stop")).status()).toBe(200);

  // au pavé : un lancement avec le bon code démarre, le déverrouillage exige le code
  await open(page, "/");
  const card = page.getByLabel("Deux scripts", { exact: true }).first();
  await card.getByRole("button", { name: "Lancer" }).click();
  const pad = page.getByRole("dialog", { name: /Code pour lancer/ });
  await pad.getByLabel("Code").fill("2468");
  await pad.getByRole("button", { name: "Valider" }).click();
  await expect(page.getByText("1 scénario en cours")).toBeVisible();
  await api(request, "post", "/runs/stop");

  await page.getByRole("button", { name: /Verrouillé : saisir le code/ }).click();
  await page.getByRole("dialog", { name: "Déverrouiller l'interface" }).getByLabel("Code").fill("2468");
  await page.getByRole("button", { name: "Valider" }).click();
  await expect(page.getByRole("button", { name: /Déverrouillé : verrouiller/ })).toBeVisible();
});

test("téléphone (360 px) : le tableau de bord et le mode spectacle ne débordent pas", async ({ page }) => {
  await page.setViewportSize({ width: 360, height: 740 });
  for (const path of ["/", "/spectacle"]) {
    await open(page, path);
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
    expect(overflow, `défilement horizontal sur ${path}`).toBe(false);
  }
  // les actions principales du mode spectacle sont des cibles de 64 px au moins
  const heights = await page.locator(".show__stop, .show__action").evaluateAll((els) => els.map((e) => e.getBoundingClientRect().height));
  expect(heights.length).toBeGreaterThan(0);
  expect(Math.min(...heights)).toBeGreaterThanOrEqual(64);
});

test("lumière à capacités limitées : le bloc ne propose que la luminosité", async ({ page, request }) => {
  const created = await api(request, "post", "/components/lights", { name: "Guirlande Twinkly", entity_id: "light.twinkly", supports_brightness: true });
  expect(created.status()).toBe(201);
  await saveProgram(request, "guirlande", "Guirlande", [{ id: "g", type: "light", target: "guirlande-twinkly", state: "on" }]);
  await open(page, "/scenarios/guirlande");
  await expect(page.getByText(/^(Scénario valide|Valide, \d+ avertissements?)$/)).toBeVisible();
  const gear = page.locator(".hw_light image").first();
  await gear.click();
  const block = page.locator(".hw_light").first();
  await expect(block.getByText("luminosité")).toBeVisible();
  await expect(block.getByText("couleur")).toBeHidden();
  await expect(block.getByText("transition")).toBeHidden();
});
