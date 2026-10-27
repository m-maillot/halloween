import { expect, test } from "vitest";
import { friendly, localIssues, walkNodes } from "./validation";
import type { Program } from "./serialize";

test.each([
  ["scripts.0.root.sequence.children.0.wait.seconds : Input should be greater than or equal to 0", "seconds : doit être supérieur ou égal à 0"],
  ["scripts.0.root.sequence.children.1.log.message : String should have at least 1 character", "message : ne peut pas être vide"],
  ["scripts.0.root.sequence.children.1.relay.target : Field required", "target : champ obligatoire"],
  ["scripts.0.root.sequence.children.1.wait.seconds : Input should be a valid number, unable to parse string as a number", "seconds : doit être un nombre"],
  ["scripts.0.truc : Une formulation inconnue", "truc : Une formulation inconnue"],
])("message technique « %s » rendu lisible", (raw, expected) => {
  expect(friendly({ severity: "error", code: "invalid", message: raw }).message).toBe(expected);
});

test("les autres erreurs du moteur ne sont pas retouchées", () => {
  const issue = { severity: "error" as const, code: "unknown_component", message: "relais inconnu(e) : `x`", node_id: "a" };
  expect(friendly(issue)).toEqual(issue);
});

const base = (children: object[], extra: object = {}) =>
  ({ schema: 1, id: "p", name: "P", scripts: [{ id: "s", root: { id: "r", type: "sequence", children } }], ...extra }) as unknown as Program;

test("walkNodes parcourt tous les descendants (enfants, branches, choix)", () => {
  const program = base([{ id: "if", type: "if", condition: { type: "random", probability: 0.5 }, then: { id: "t", type: "wait", seconds: 1 }, else: { id: "e", type: "wait", seconds: 2 } }, { id: "rc", type: "random_choice", choices: [{ weight: 1, child: { id: "c", type: "log", message: "x" } }] }]);
  const ids = [...walkNodes(program.scripts[0].root as never)].map((n) => n.id);
  expect(ids).toEqual(["r", "if", "t", "e", "rc", "c"]);
});

test("boucle sans fin : avertie sans durée maximale, silencieuse avec une durée", () => {
  const loop = [{ id: "l", type: "repeat", forever: true, child: { id: "w", type: "wait", seconds: 1 } }];
  expect(localIssues(base(loop)).map((i) => i.code)).toEqual(["local_endless"]);
  expect(localIssues(base(loop, { max_duration_s: 60 }))).toEqual([]);
});

test("un relais maintenu allumé puis éteint ailleurs (autre script) n'est pas signalé", () => {
  const program = base([{ id: "a", type: "relay", target: "inconnu", state: "on" }]);
  program.scripts.push({ id: "s2", root: { id: "r2", type: "sequence", children: [{ id: "b", type: "relay", target: "inconnu", state: "off" }] } } as never);
  expect(localIssues(program)).toEqual([]);
});

test("« attendre jusqu'à » sans condition est une erreur locale", () => {
  const issues = localIssues(base([{ id: "wu", type: "wait_until", condition: null }]));
  expect(issues).toMatchObject([{ severity: "error", code: "local_missing_condition", node_id: "wu" }]);
});
