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

// ------------------------------------------------------------------ blocs de contrôle

import { setPrograms } from "./catalog";

/** Programme de l'annexe de la spec 1 (§13), tel qu'écrit dans la spec. */
const ANNEX: Program = {
  schema: 1,
  id: "scenario-principal",
  name: "Scénario principal",
  max_duration_s: 90,
  on_end: "reset",
  scripts: [
    {
      id: "s1",
      hat: { type: "start" },
      root: {
        id: "n1",
        type: "sequence",
        children: [
          { id: "n2", type: "light", target: "bandeau", state: "on", rgb_color: [255, 0, 0], brightness: 40, transition: 2 },
          { id: "n3", type: "wait", seconds: 3 },
          { id: "n4", type: "parallel", children: [relay("n5", "orage", "on"), relay("n6", "fantome", "on")] },
          { id: "n7", type: "wait", seconds: 8 },
          relay("n7b", "fantome", "off"),
          relay("n7c", "orage", "off"),
          relay("n8", "squelette", "on"),
          { id: "n8b", type: "wait", seconds: 6 },
          relay("n8c", "squelette", "off"),
          relay("n9", "epouvantail", "on"),
        ],
      },
    },
  ],
} as never;

/** Les séquences-conteneurs prennent un identifiant dérivé : on les compare sans leur identifiant. */
function shape(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(shape);
  if (value && typeof value === "object") {
    const object = value as Record<string, unknown>;
    // une séquence d'un seul nœud équivaut à ce nœud : l'éditeur ne l'écrit pas autrement
    if (object.type === "sequence" && Array.isArray(object.children) && object.children.length === 1 && object !== undefined) {
      return shape(object.children[0]);
    }
    return Object.fromEntries(
      Object.entries(object)
        .filter(([k]) => !(k === "id" && object.type === "sequence"))
        .map(([k, v]) => [k, shape(v)]),
    );
  }
  return value;
}

test("l'annexe de la spec 1 fait l'aller-retour (identifiants des séquences mis à part)", () => {
  loadProgram(ws, ANNEX);
  const back = workspaceToProgram(ws, { id: ANNEX.id, name: ANNEX.name, max_duration_s: 90 });
  expect(shape(back.scripts)).toEqual(shape(ANNEX.scripts));
  expect(back.max_duration_s).toBe(90);
});

const everything = (): Program =>
  ({
    schema: 1,
    id: "tout",
    name: "Tout",
    scripts: [
      {
        id: "s1",
        hat: { type: "start" },
        root: {
          id: "r",
          type: "sequence",
          children: [
            { id: "p", type: "parallel", until: "first", children: [relay("a", "orage", "on"), { id: "q", type: "sequence", children: [relay("b", "fantome", "on"), { id: "w", type: "wait", seconds: 1.25 }] }, { id: "l", type: "log", message: "trois branches" }] },
            { id: "rep", type: "repeat", times: 4, child: { id: "rs", type: "sequence", children: [relay("c", "orage", "off"), { id: "wr", type: "wait", min: 0.5, max: 2 }] } },
            { id: "if1", type: "if", condition: { type: "relay_is", id: "orage", state: "on" }, then: relay("t", "fantome", "on"), else: { id: "es", type: "sequence", children: [relay("e1", "fantome", "off"), relay("e2", "orage", "off")] } },
            { id: "if2", type: "if", condition: { type: "random", probability: 0.35 }, then: { id: "ts", type: "sequence", children: [] } },
            { id: "wu", type: "wait_until", condition: { type: "button", id: "bouton", event: "double" }, timeout_s: 30 },
            { id: "wu2", type: "wait_until", condition: { type: "button", id: "bouton", event: "long" } },
            { id: "rc", type: "random_choice", choices: [{ weight: 1, child: relay("x1", "orage", "on") }, { weight: 2.5, child: { id: "xs", type: "sequence", children: [relay("x2", "fantome", "on"), relay("x3", "fantome", "off")] } }, { weight: 1, child: { id: "xl", type: "log", message: "rien" } }] },
            { id: "call1", type: "call", program_id: "autre" },
            { id: "loop", type: "repeat", forever: true, child: { id: "ls", type: "sequence", children: [{ id: "lw", type: "wait", seconds: 5 }] } },
          ],
        },
      },
    ],
  }) as never;

test("tous les types de nœuds font l'aller-retour, boucle sans fin comprise", () => {
  setCatalog({ ...devices, buttons: [{ id: "bouton", name: "Bouton", pin: 21 }] } as unknown as Devices);
  setPrograms([{ id: "autre", name: "Autre" }]);
  const source = everything();
  loadProgram(ws, source);
  const back = workspaceToProgram(ws, { id: "tout", name: "Tout" });
  expect(shape(back.scripts)).toEqual(shape(source.scripts));
});

test("sérialiser deux fois donne exactement le même JSON (point fixe, identifiants de conteneurs compris)", () => {
  setCatalog({ ...devices, buttons: [{ id: "bouton", name: "Bouton", pin: 21 }] } as unknown as Devices);
  setPrograms([{ id: "autre", name: "Autre" }]);
  loadProgram(ws, everything());
  const first = workspaceToProgram(ws, { id: "tout", name: "Tout" });
  const other = new Blockly.Workspace();
  loadProgram(other, first);
  expect(workspaceToProgram(other, { id: "tout", name: "Tout" }).scripts).toEqual(first.scripts);
});

test("un scénario appelé qui n'existe plus est conservé, marqué introuvable dans le menu", () => {
  setPrograms([]);
  loadProgram(ws, program([{ id: "c", type: "call", program_id: "disparu" }]));
  expect(workspaceToProgram(ws, meta).scripts[0].root).toMatchObject({ children: [{ type: "call", program_id: "disparu" }] });
  const options = (ws.getBlockById("c")!.getField("PROGRAM") as Blockly.FieldDropdown).getOptions(false);
  expect(options).toContainEqual(["disparu (introuvable)", "disparu"]);
});

test("une branche vide d'un « en parallèle » n'est pas écrite, un « si » sans condition garde sa place", () => {
  loadProgram(ws, program([{ id: "p", type: "parallel", children: [relay("a", "orage", "on")] }]));
  const root = workspaceToProgram(ws, meta).scripts[0].root as unknown as { children: { children: object[] }[] };
  expect(root.children[0].children).toHaveLength(1); // 2 branches affichées, 1 écrite
  const block = ws.newBlock("hw_if", "i");
  ws.getBlockById("s1")!.nextConnection!.connect(block.previousConnection!);
  const node = (workspaceToProgram(ws, meta).scripts[0].root as unknown as { children: { id: string; condition: unknown }[] }).children.find((c) => c.id === "i");
  expect(node!.condition).toBeNull(); // le moteur le refusera : l'erreur sera posée sur ce bloc (#49)
});
