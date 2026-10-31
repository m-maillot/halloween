// Programmes réels du dépôt (exemple livré, jeux de test du moteur) : l'éditeur doit les relire
// et les réécrire sans en changer le sens.
import * as Blockly from "blockly/core";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { beforeAll, expect, test } from "vitest";
import type { Devices } from "../catalog/CatalogProvider";
import { registerBlocks } from "./blocks";
import { setCatalog, setPrograms } from "./catalog";
import { loadProgram, workspaceToProgram, type Program } from "./serialize";

const root = resolve(__dirname, "../../..");
const read = (path: string): Program => JSON.parse(readFileSync(resolve(root, path), "utf-8"));
const config = JSON.parse(readFileSync(resolve(root, "deploy/config.example.json"), "utf-8"));

beforeAll(() => {
  registerBlocks();
  setCatalog({ relays: config.relays, buttons: config.buttons, lights: config.lights, switches: config.switches ?? [], players: [], rest_state: {} } as unknown as Devices);
  setPrograms([{ id: "scenario-principal", name: "Scénario principal" }, { id: "ambiance", name: "Ambiance" }]);
});

/** Séquence d'un seul nœud = ce nœud ; valeurs par défaut explicites retirées ; identifiants de séquences ignorés. */
function canonical(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(canonical);
  if (value && typeof value === "object") {
    const o = value as Record<string, unknown>;
    if (o.type === "sequence" && Array.isArray(o.children) && o.children.length === 1) return canonical(o.children[0]);
    return Object.fromEntries(
      Object.entries(o)
        .filter(([k, v]) => !(k === "id" && o.type === "sequence") && !(k === "hat") && !(k === "weight" && v === 1) && !(k === "fire_and_forget" && v === false) && !(k === "on_error" && v === "continue") && v !== null)
        .map(([k, v]) => [k, canonical(v)]),
    );
  }
  return value;
}

const FILES = ["deploy/programs-example/scenario-principal.json", "engine/tests/data/scenario_principal.json", "engine/tests/data/ambiance.json"];

test.each(FILES)("%s fait l'aller-retour sans perte", (file) => {
  const source = read(file);
  const ws = new Blockly.Workspace();
  loadProgram(ws, source);
  const back = workspaceToProgram(ws, { id: source.id, name: source.name, max_duration_s: source.max_duration_s, on_end: source.on_end, show: source.show, show_order: source.show_order });
  expect(canonical(back.scripts)).toEqual(canonical(source.scripts));
  expect(back).toMatchObject({ id: source.id, name: source.name, max_duration_s: source.max_duration_s ?? null });
});

test("la mise en page (positions, blocs repliés, zoom, défilement) est restituée à l'identique", () => {
  const source = read(FILES[0]);
  const ws = new Blockly.Workspace();
  loadProgram(ws, source);
  const folded = ws.getAllBlocks(false).find((b) => b.type === "hw_parallel")!;
  folded.setCollapsed(true);
  ws.getBlockById(source.scripts[0].id)!.moveBy(120, 80);
  const saved = workspaceToProgram(ws, { id: source.id, name: source.name }, { zoom: 1.2, scroll: { x: 10, y: -20 } });
  const again = new Blockly.Workspace();
  loadProgram(again, JSON.parse(JSON.stringify(saved))); // passage par du vrai JSON, comme le moteur
  const reread = workspaceToProgram(again, { id: source.id, name: source.name }, { zoom: 1.2, scroll: { x: 10, y: -20 } });
  expect(reread.editor).toEqual(saved.editor);
  expect(again.getBlockById(folded.id)!.isCollapsed()).toBe(true);
});

test("la mise en page reste petite devant la limite de 256 Ko du moteur, même pour de grands programmes", () => {
  const children = Array.from({ length: 400 }, (_, i) => ({ id: `n${i}`, type: "relay", target: "fantome", state: i % 2 ? "on" : "off" }));
  const scripts = Array.from({ length: 40 }, (_, s) => ({ id: `s${s}`, hat: { type: "start" }, root: { id: `r${s}`, type: "sequence", children: children.slice(0, 10) } }));
  const ws = new Blockly.Workspace();
  loadProgram(ws, { schema: 1, id: "grand", name: "Grand", scripts } as unknown as Program);
  const saved = workspaceToProgram(ws, { id: "grand", name: "Grand" });
  expect(JSON.stringify(saved.editor).length).toBeLessThan(20_000);
});
