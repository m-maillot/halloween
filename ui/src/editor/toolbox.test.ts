import { expect, test } from "vitest";
import type { Devices } from "../catalog/CatalogProvider";
import { buildToolbox } from "./toolbox";

const base = { relays: [{ id: "orage" }], buttons: [], lights: [{ id: "bandeau" }], switches: [], rest_state: {} } as unknown as Devices;
type Category = { name: string; contents: { type: string; extraState: { target: string } }[] };
const categories = (devices: Devices | null) => (buildToolbox(devices).contents as Category[]);

test("un bloc par composant, rangé dans sa catégorie", () => {
  const byName = Object.fromEntries(categories(base).filter((c) => c.name !== "Contrôle").map((c) => [c.name, c.contents.map((b) => `${b.type}:${b.extraState.target}`)]));
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
  expect(categories(null).every((c) => c.contents.length === 0 || c.name === "Contrôle")).toBe(true);
});
