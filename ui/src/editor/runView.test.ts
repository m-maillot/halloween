import * as Blockly from "blockly/core";
import { beforeAll, expect, test } from "vitest";
import type { Devices } from "../catalog/CatalogProvider";
import type { EngineEvent } from "../engine/socket";
import { registerBlocks } from "./blocks";
import { setCatalog } from "./catalog";
import { EMPTY, blockStates, isRunning, reduce, type RunView } from "./runView";
import { loadProgram, type Program } from "./serialize";

const ev = (event: object): EngineEvent => event as EngineEvent;
const step = (state: RunView, event: object, programId = "scene") => reduce(state, { type: "event", event: ev(event), programId });
const started = (nodeId: string, runId = "r1", script = "s") => ({ type: "node_started", run_id: runId, program_id: "scene", script_id: script, node_id: nodeId });
const finished = (nodeId: string, runId = "r1", script = "s") => ({ type: "node_finished", run_id: runId, program_id: "scene", script_id: script, node_id: nodeId });
const begin = () => step(EMPTY, { type: "run_started", run_id: "r1", program_id: "scene", ts: 100 });

test("un run d'un autre scénario est ignoré", () => {
  expect(step(EMPTY, { type: "run_started", run_id: "x", program_id: "autre", ts: 1 })).toBe(EMPTY);
});

test("les blocs démarrent, puis se terminent : en cours puis estompés", () => {
  let state = begin();
  state = step(state, started("a"));
  expect(state.running).toEqual({ a: 1 });
  state = step(state, finished("a"));
  expect(state.running).toEqual({});
  expect(state.finished).toEqual({ a: true });
  expect(isRunning(state)).toBe(true);
});

test("une boucle qui redémarre un bloc le remet « en cours » (il n'est plus estompé)", () => {
  let state = begin();
  state = step(step(state, started("a")), finished("a"));
  state = step(state, started("a"));
  expect(state.running).toEqual({ a: 1 });
  expect(state.finished).toEqual({});
});

test("les événements d'un autre run sont ignorés", () => {
  const state = begin();
  expect(step(state, started("a", "autre-run"))).toBe(state);
  expect(step(state, { type: "error", run_id: "autre-run", message: "x", node_id: "a" })).toBe(state);
});

test("une erreur d'action est gardée avec son bloc, le run continue", () => {
  const state = step(begin(), { type: "error", run_id: "r1", source: "action", message: "Home Assistant injoignable", node_id: "l", component_id: "bandeau" });
  expect(state.errors).toEqual([{ nodeId: "l", message: "Home Assistant injoignable" }]);
  expect(isRunning(state)).toBe(true);
});

test("la fin du run donne l'issue et la durée mesurée entre les événements", () => {
  const state = step(step(begin(), started("a")), { type: "run_ended", run_id: "r1", program_id: "scene", outcome: "completed", ts: 117.5 });
  expect(state.ended).toEqual({ outcome: "completed", error: null, durationS: 17.5 });
  expect(state.running).toEqual({});
  expect(isRunning(state)).toBe(false);
});

test("on se raccroche à un run déjà en cours, une seule fois", () => {
  const state = reduce(EMPTY, { type: "adopt", runId: "r9", startedTs: 5 });
  expect(state).toMatchObject({ runId: "r9", startedTs: 5 });
  expect(reduce(state, { type: "adopt", runId: "r9", startedTs: 5 })).toBe(state);
});

test("un nouveau run du même scénario remplace l'affichage du précédent", () => {
  let state = step(step(begin(), started("a")), { type: "run_ended", run_id: "r1", program_id: "scene", outcome: "completed", ts: 110 });
  state = step(state, { type: "run_started", run_id: "r2", program_id: "scene", ts: 200 });
  expect(state).toMatchObject({ runId: "r2", ended: null, finished: {}, running: {} });
});

// ------------------------------------------------------------------ blocs

const devices = { relays: [{ id: "orage", name: "Orage", pin: 22, mode: "latched" }, { id: "fantome", name: "Fantôme", pin: 18, mode: "latched" }], buttons: [], lights: [], switches: [], rest_state: {} } as unknown as Devices;
const two: Program = {
  schema: 1, id: "scene", name: "S", scripts: [
    { id: "s1", hat: { type: "start" }, root: { id: "r1", type: "sequence", children: [{ id: "a", type: "relay", target: "orage", state: "on" }, { id: "b", type: "relay", target: "orage", state: "off" }] } },
    { id: "s2", hat: { type: "start" }, root: { id: "r2", type: "sequence", children: [{ id: "c", type: "relay", target: "fantome", state: "on" }] } },
  ],
} as never;

beforeAll(() => {
  registerBlocks();
  setCatalog(devices);
});

test("deux scripts d'un même run sont surlignés en même temps ; les blocs terminés sont estompés", () => {
  const ws = new Blockly.Workspace();
  loadProgram(ws, two);
  let state = begin();
  for (const id of ["r1", "s1", "a", "r2", "s2", "c"]) state = step(state, started(id));
  state = step(state, finished("a"));
  const states = blockStates(ws, state);
  expect(states.get("c")).toBe("active"); // script 2 : bloc en cours
  expect(states.get("s1")).toBe("active"); // script 1 : sa pile (r1) tourne encore, le chapeau est surligné
  expect(states.get("a")).toBe("done");
  expect(states.get("b")).toBeUndefined(); // pas encore atteint
});

test("la pile implicite d'un script est rattachée à son chapeau", () => {
  const ws = new Blockly.Workspace();
  loadProgram(ws, two);
  const state = step(begin(), started("s1_root"));
  expect(blockStates(ws, state).get("s1")).toBe("active");
});

test("un bloc en erreur l'emporte sur « terminé » et « en cours »", () => {
  const ws = new Blockly.Workspace();
  loadProgram(ws, two);
  let state = step(step(begin(), started("a")), { type: "error", run_id: "r1", message: "ko", node_id: "a" });
  expect(blockStates(ws, state).get("a")).toBe("error");
  state = step(state, finished("a"));
  expect(blockStates(ws, state).get("a")).toBe("error");
});

test("un identifiant de nœud inconnu de l'éditeur est ignoré sans erreur", () => {
  const ws = new Blockly.Workspace();
  loadProgram(ws, two);
  expect(() => blockStates(ws, step(begin(), started("fantôme-inconnu")))).not.toThrow();
});

test("le chapeau d'un script s'allume avec ses nœuds, même si la racine du script a un identifiant libre (programme créé par API)", () => {
  const ws = new Blockly.Workspace();
  loadProgram(ws, two);
  let state = begin();
  state = step(state, started("r1", "r1", "s1")); // la racine « r1 » n'est pas dérivée du script : aucun bloc ne porte cet identifiant
  state = step(state, started("a", "r1", "s1"));
  state = step(state, started("c", "r1", "s2"));
  expect(blockStates(ws, state).get("s1")).toBe("active");
  expect(blockStates(ws, state).get("s2")).toBe("active");
  // le script 1 s'achève, le script 2 continue
  state = step(step(state, finished("a", "r1", "s1")), finished("r1", "r1", "s1"));
  expect(blockStates(ws, state).get("s1")).toBe("done");
  expect(blockStates(ws, state).get("s2")).toBe("active");
});
