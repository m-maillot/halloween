import { expect, test } from "vitest";
import type { Devices } from "../catalog/CatalogProvider";
import { buildToolbox } from "./toolbox";

const base = { relays: [{ id: "orage" }], buttons: [], lights: [{ id: "bandeau" }], switches: [], rest_state: {} } as unknown as Devices;
type Category = { name: string; contents: { type: string; extraState: { target: string } }[] };
const categories = (devices: Devices | null) => (buildToolbox(devices).contents as unknown as Category[]);

test("un bloc par composant, rangé dans sa catégorie", () => {
  const byName = Object.fromEntries(categories(base).filter((c) => ["Relais", "Lumières", "Interrupteurs"].includes(c.name)).map((c) => [c.name, c.contents.map((b) => `${b.type}:${b.extraState.target}`)]));
  expect(byName["Relais"]).toEqual(["hw_relay:orage"]);
  expect(byName["Lumières"]).toEqual(["hw_light:bandeau"]);
  expect(byName["Interrupteurs"]).toEqual([]);
});

test("ajouter un composant le fait apparaître dans la palette", () => {
  const next = { ...base, switches: [{ id: "prise" }] } as unknown as Devices;
  const names = categories(next).find((c) => c.name === "Interrupteurs")!.contents.map((b) => b.extraState.target);
  expect(names).toEqual(["prise"]);
});

test("sans catalogue, la palette est vide mais valide", () => {
  expect(categories(null).filter((c) => ["Relais", "Lumières", "Interrupteurs"].includes(c.name)).every((c) => c.contents.length === 0)).toBe(true);
});

test("les blocs de contrôle sont tous proposés, et les conditions suivent les boutons et relais du catalogue", () => {
  const all = categories(base) as unknown as { name: string; contents: { type: string }[] }[];
  const control = all.find((c) => c.name === "Contrôle")!.contents.map((b) => b.type);
  for (const type of ["hw_start", "hw_parallel", "hw_repeat", "hw_repeat_forever", "hw_wait", "hw_wait_random", "hw_if", "hw_wait_until", "hw_random_choice", "hw_call"]) {
    expect(control).toContain(type);
  }
  const conditions = all.find((c) => c.name === "Conditions")!.contents.map((b) => b.type);
  expect(conditions).toEqual(["hw_cond_relay_is", "hw_cond_random"]); // aucun bouton dans ce catalogue
});

test("chaque lumière gérant un paramètre a aussi un bloc déjà réglé", () => {
  const devices = {
    ...base,
    lights: [
      { id: "bandeau", supports_color: true, supports_brightness: true, supports_transition: true },
      { id: "guirlande", supports_color: false, supports_brightness: true, supports_transition: false },
      { id: "simple", supports_color: false, supports_brightness: false, supports_transition: false },
    ],
  } as unknown as Devices;
  const lights = categories(devices).find((c) => c.name === "Lumières")!.contents as unknown as { extraState: { target: string; tuned?: boolean } }[];
  expect(lights.filter((b) => !b.extraState.tuned).map((b) => b.extraState.target)).toEqual(["bandeau", "guirlande", "simple"]);
  expect(lights.filter((b) => b.extraState.tuned).map((b) => b.extraState.target)).toEqual(["bandeau", "guirlande"]); // « simple » n'a rien à régler
});
