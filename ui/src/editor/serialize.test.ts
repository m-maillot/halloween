import * as Blockly from "blockly/core";
import { beforeAll, beforeEach, expect, test } from "vitest";
import type { Devices } from "../catalog/CatalogProvider";
import { registerBlocks } from "./blocks";
import { setCatalog } from "./catalog";
import { loadProgram, orphanStacks, workspaceToProgram, type Program } from "./serialize";

const devices = {
  relays: [
    { id: "orage", name: "Orage", pin: 22, mode: "latched", active_low: false },
    { id: "fantome", name: "Fantôme", pin: 18, mode: "latched", active_low: false },
    { id: "fumee", name: "Fumée", pin: 5, mode: "push", pulse_ms: 500, animation_s: 4, active_low: false },
    { id: "flash", name: "Flash", pin: 6, mode: "push", pulse_ms: 100, active_low: false },
  ],
  buttons: [],
  lights: [],
  switches: [],
  rest_state: {},
} as unknown as Devices;

beforeAll(registerBlocks);
let ws: Blockly.Workspace;
beforeEach(() => {
  setCatalog(devices);
  ws = new Blockly.Workspace();
});

const meta = { id: "scene", name: "Scène" };
const relay = (id: string, target: string, state: string) => ({ id, type: "relay", target, state });
const program = (children: object[]): Program =>
  ({
    schema: 1,
    id: "scene",
    name: "Scène",
    max_duration_s: null,
    on_end: "reset",
    show: false,
    show_order: null,
    revision: 0,
    scripts: [{ id: "s1", hat: { type: "start" }, root: { id: "s1_root", type: "sequence", children } }],
    editor: null,
  }) as unknown as Program;

test("un script de relais fait l'aller-retour sans perte, identifiants compris", () => {
  const source = program([relay("n2", "orage", "on"), relay("n3", "fantome", "off")]);
  loadProgram(ws, source);
  const back = workspaceToProgram(ws, meta);
  expect(back.scripts).toEqual(source.scripts);
});

test("les identifiants de blocs sont ceux des nœuds, pour que erreurs et progression retombent juste", () => {
  loadProgram(ws, program([relay("n2", "orage", "on")]));
  expect(ws.getBlockById("n2")?.type).toBe("hw_relay");
  expect(ws.getBlockById("s1")?.type).toBe("hw_start");
});

test("relais à impulsion : déclencher, avec « attendre la fin » seulement s'il a une animation", () => {
  const source = program([
    { id: "a", type: "relay", target: "fumee", action: "trigger", wait_for_end: true },
    { id: "b", type: "relay", target: "flash", action: "trigger" },
  ]);
  loadProgram(ws, source);
  expect(ws.getBlockById("b")!.getField("WAIT_END")).toBeNull();
  expect(workspaceToProgram(ws, meta).scripts).toEqual(source.scripts);
});

test("les identifiants Blockly générés sont rendus valides pour le moteur (essais répétés : ils sont aléatoires)", () => {
  loadProgram(ws, program([]));
  for (let i = 0; i < 200; i++) {
    const block = ws.newBlock("hw_relay");
    (block as unknown as { loadExtraState(s: object): void }).loadExtraState({ target: "orage" });
    block.setFieldValue("on", "STATE");
    ws.getBlockById("s1")!.nextConnection!.connect(block.previousConnection!);
  }
  const root = workspaceToProgram(ws, meta).scripts[0].root as unknown as { children: { id: string }[] };
  const ids = root.children.map((c) => c.id);
  expect(ids.every((id) => /^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$/.test(id))).toBe(true);
  expect(new Set(ids).size).toBe(200);
});

test("deux scripts : chacun garde sa pile et sa position, la disposition est rendue à l'identique", () => {
  const source = program([relay("n2", "orage", "on")]);
  source.scripts.push({ id: "s2", hat: { type: "start" }, root: { id: "s2_root", type: "sequence", children: [relay("m1", "fantome", "on")] } } as never);
  source.editor = { blocks: { s1: { x: 40, y: 30 }, s2: { x: 400, y: 90 } } } as never;
  loadProgram(ws, source);
  const back = workspaceToProgram(ws, meta);
  expect(back.scripts).toEqual(source.scripts);
  expect((back.editor as { blocks: object }).blocks).toEqual({ s1: { x: 40, y: 30 }, s2: { x: 400, y: 90 } });
});

test("sans disposition enregistrée (programme créé par API), les scripts sont rangés sans se recouvrir", () => {
  const source = program([relay("n2", "orage", "on"), relay("n3", "orage", "off")]);
  source.scripts.push({ id: "s2", hat: { type: "start" }, root: { id: "r", type: "sequence", children: [relay("m1", "fantome", "on")] } } as never);
  loadProgram(ws, source);
  const [a, b] = ["s1", "s2"].map((id) => ws.getBlockById(id)!.getRelativeToSurfaceXY());
  expect(b.y).toBeGreaterThan(a.y + 3 * 40);
  expect(a.x).toBe(b.x);
});

test("un bloc posé hors d'un script n'est pas exporté et est repéré", () => {
  loadProgram(ws, program([relay("n2", "orage", "on")]));
  const stray = ws.newBlock("hw_relay", "stray");
  (stray as unknown as { loadExtraState(s: object): void }).loadExtraState({ target: "orage" });
  expect(orphanStacks(ws).map((b) => b.id)).toEqual(["stray"]);
  expect(JSON.stringify(workspaceToProgram(ws, meta))).not.toContain("stray");
});

test("un composant inconnu garde son bloc (marqué introuvable) et son identifiant", () => {
  const source = program([relay("n2", "disparu", "on")]);
  loadProgram(ws, source);
  expect(workspaceToProgram(ws, meta).scripts).toEqual(source.scripts);
});

test("les paramètres du programme sont conservés", () => {
  const back = workspaceToProgram(ws, { id: "x", name: "Un nom", max_duration_s: 90, on_end: "keep", show: true, show_order: 2, revision: 5 });
  expect(back).toMatchObject({ id: "x", name: "Un nom", max_duration_s: 90, on_end: "keep", show: true, show_order: 2, revision: 5 });
});
