import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { expect, type APIRequestContext, type Page } from "@playwright/test";

/** Jeton généré par le moteur au premier démarrage (fichier du dossier de données de test). */
export const token = () => readFileSync(resolve(process.cwd(), ".e2e-data/api-token"), "utf-8").trim();
export const auth = () => ({ Authorization: `Bearer ${token()}` });

/** Ouvre l'interface déjà connectée (jeton mémorisé dans le navigateur, comme après la première saisie). */
export async function open(page: Page, path: string) {
  await page.addInitScript((t) => localStorage.setItem("halloween.token", t), token());
  await page.goto(path);
  await expect(page.getByText("Moteur connecté")).toBeVisible();
}

export async function api(request: APIRequestContext, method: "get" | "post" | "put" | "delete", path: string, data?: unknown, headers: Record<string, string> = {}) {
  return request[method](`/api${path}`, { headers: { ...auth(), ...headers }, data });
}

export async function createRelay(request: APIRequestContext, name: string, pin: number, image = "builtin:ghost") {
  const response = await api(request, "post", "/components/relays", { name, pin, mode: "latched", image });
  expect(response.status()).toBe(201);
  return ((await response.json()) as { component: { id: string } }).component.id;
}

/** Programme à un script : début, puis les nœuds donnés. */
export async function saveProgram(request: APIRequestContext, id: string, name: string, children: object[], extra: object = {}) {
  const response = await api(request, "put", `/programs/${id}`, {
    schema: 1,
    id,
    name,
    scripts: [{ id: "s1", hat: { type: "start" }, root: { id: "r", type: "sequence", children } }],
    ...extra,
  });
  expect(response.status()).toBeLessThan(300);
}

/** Tire un bloc de la palette (catégorie `category`, 1re colonne) vers `target` (coin haut-gauche + décalage). */
export async function dragFromToolbox(page: Page, category: string, blockType: string, target: { x: number; y: number }, match?: RegExp) {
  await page.locator(".blocklyToolboxCategory", { hasText: category }).click();
  const flyout = page.locator(`.blocklyFlyout .${blockType}`);
  await expect(flyout.first()).toBeVisible();
  const blocks = await flyout.evaluateAll((els) => els.map((e) => ({ text: e.textContent ?? "", ...(({ x, y }) => ({ x, y }))(e.getBoundingClientRect()) })));
  const hit = match ? blocks.find((b) => match.test(b.text)) : blocks[0];
  if (!hit) throw new Error(`bloc introuvable dans la palette : ${blockType} ${match ?? ""}`);
  await page.mouse.move(hit.x + 14, hit.y + 14);
  await page.mouse.down();
  await page.mouse.move(target.x, target.y, { steps: 15 });
  await page.mouse.up();
}

/** Position écran du dernier bloc de ce type dans la zone de montage (hors palette). */
export async function lastBlock(page: Page, blockType: string) {
  const blocks = await page.locator(`.${blockType}`).evaluateAll((els) =>
    els.filter((e) => !e.closest(".blocklyFlyout")).map((e) => {
      const r = e.getBoundingClientRect();
      return { x: r.x, y: r.y, h: r.height };
    }),
  );
  return blocks.sort((a, b) => b.y - a.y)[0];
}

/** Nombre de blocs de ce type dans la zone de montage (la palette en contient aussi une copie). */
export const blockCount = (page: Page, blockType: string) =>
  page.locator(`.${blockType}`).evaluateAll((els) => els.filter((e) => !e.closest(".blocklyFlyout")).length);
