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
  lights: [
    { id: "bandeau", name: "Bandeau", entity_id: "light.b", supports_color: true, supports_brightness: true, supports_transition: true },
    { id: "guirlande", name: "Guirlande", entity_id: "light.g", supports_color: false, supports_brightness: true, supports_transition: false },
  ],
  switches: [{ id: "prise", name: "Prise", entity_id: "switch.p" }],
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

// ------------------------------------------------------------------ lumières, interrupteurs, options

/** Le moteur renvoie les valeurs par défaut explicitement ; l'éditeur ne les écrit pas. */
function withoutDefaults(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(withoutDefaults);
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>)
        .filter(([k, v]) => !((k === "fire_and_forget" && v === false) || (k === "on_error" && v === "continue") || (k === "wait_for_end" && v === false) || ((k === "action" || k === "rgb_color" || k === "brightness" || k === "transition") && v === null)))
        .map(([k, v]) => [k, withoutDefaults(v)]),
    );
  }
  return value;
}

const roundTrip = (children: object[]) => {
  const source = program(children);
  loadProgram(ws, source);
  return { source, back: workspaceToProgram(ws, meta) };
};

test("une lumière avec couleur, luminosité et transition fait l'aller-retour", () => {
  const { source, back } = roundTrip([{ id: "l1", type: "light", target: "bandeau", state: "on", rgb_color: [255, 0, 0], brightness: 102, transition: 2.5 }]);
  expect(back.scripts).toEqual(source.scripts);
});

test("les paramètres non cochés ne sont pas envoyés", () => {
  const { back } = roundTrip([{ id: "l1", type: "light", target: "bandeau", state: "off" }]);
  expect(back.scripts[0].root).toMatchObject({ children: [{ id: "l1", type: "light", target: "bandeau", state: "off" }] });
  const node = (back.scripts[0].root as unknown as { children: object[] }).children[0];
  expect(Object.keys(node).sort()).toEqual(["id", "state", "target", "type"]);
});

test("la luminosité 0-255 du moteur survit à l'affichage en pourcentage, pour toutes les valeurs", () => {
  for (let value = 0; value <= 255; value++) {
    const { back } = roundTrip([{ id: "l1", type: "light", target: "bandeau", state: "on", brightness: value }]);
    const node = (back.scripts[0].root as unknown as { children: { brightness: number }[] }).children[0];
    expect(node.brightness).toBe(value);
  }
});

test("un interrupteur et les options fire_and_forget / on_error font l'aller-retour", () => {
  const { source, back } = roundTrip([
    { id: "a", type: "switch", target: "prise", state: "on", fire_and_forget: true },
    { id: "b", type: "relay", target: "orage", state: "on", on_error: "abort" },
    { id: "c", type: "light", target: "bandeau", state: "on", fire_and_forget: true, on_error: "abort" },
  ]);
  expect(back.scripts).toEqual(source.scripts);
});

test("les valeurs par défaut renvoyées par le moteur sont comprises, puis non réécrites", () => {
  const { source, back } = roundTrip([
    { id: "a", type: "relay", target: "orage", state: "on", action: null, fire_and_forget: false, on_error: "continue", wait_for_end: false },
    { id: "l", type: "light", target: "bandeau", state: "on", rgb_color: null, brightness: null, transition: null, fire_and_forget: false, on_error: "continue" },
  ]);
  expect(back.scripts).toEqual(withoutDefaults(source.scripts));
});

test("un paramètre que la lumière ne gère pas est conservé (la validation le signalera sur ce bloc)", () => {
  const { source, back } = roundTrip([{ id: "g", type: "light", target: "guirlande", state: "on", rgb_color: [1, 2, 3], transition: 4 }]);
  expect(back.scripts).toEqual(source.scripts);
});

test("une lumière inconnue garde ses paramètres", () => {
  const { source, back } = roundTrip([{ id: "x", type: "light", target: "disparue", state: "on", brightness: 50 }]);
  expect(back.scripts).toEqual(source.scripts);
  expect(ws.getBlockById("x")!.getColour()).toBe("#a02626"); // rouge : composant introuvable
});

test("le catalogue modifié met les blocs à jour (relais devenu impulsion)", async () => {
  const { refreshComponentBlocks } = await import("./blocks");
  loadProgram(ws, program([relay("n2", "orage", "on")]));
  expect(ws.getBlockById("n2")!.getField("STATE")).not.toBeNull();
  setCatalog({ ...devices, relays: [{ id: "orage", name: "Orage", pin: 22, mode: "push", pulse_ms: 100, active_low: false }] } as unknown as Devices);
  refreshComponentBlocks(ws);
  expect(ws.getBlockById("n2")!.getField("STATE")).toBeNull();
});
