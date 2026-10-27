import { expect, test } from "vitest";
import principal from "./fixtures/simulation-principal.json";
import { buildRows, formatSeconds, statusMessage, ticks, type SimulationOut } from "./timeline";

const result = (timeline: object[], extra: object = {}): SimulationOut =>
  ({ status: "completed", duration_s: 10, still_on: [], error: null, timeline, ...extra }) as unknown as SimulationOut;
const at = (t: number, component: string, action: string, data: object = {}) => ({ t, component, action, data });

test("le scénario principal de l'exemple (réponse réelle du moteur) donne exactement les bonnes périodes", () => {
  // Réponse capturée sur le vrai moteur pour `deploy/programs-example/scenario-principal.json`.
  const rows = buildRows(principal as unknown as SimulationOut);
  const view = Object.fromEntries(rows.map((r) => [r.component, r.periods.map((p) => [p.start, p.end, p.open])]));
  expect(view).toEqual({
    bandeau: [[0, 17, true]], // allumé à 0 s, jamais éteint
    orage: [[3, 11, false]],
    fantome: [[3, 11, false]],
    squelette: [[11, 17, false]],
    epouvantail: [[17, 17, true]], // allumé à la toute fin
  });
  expect(rows.map((r) => r.component)).toEqual(["bandeau", "orage", "fantome", "squelette", "epouvantail"]);
  expect(rows[0].periods[0].data).toMatchObject({ rgb_color: [255, 0, 0], brightness: 40 });
});

test("les composants encore allumés à la fin sont ceux que le moteur annonce (still_on)", () => {
  const rows = buildRows(principal as unknown as SimulationOut);
  const open = rows.filter((r) => r.periods.some((p) => p.open)).map((r) => r.component).sort();
  expect(open).toEqual([...(principal as { still_on: string[] }).still_on, "bandeau"].sort());
});

test("un composant rallumé avec une autre couleur donne deux périodes consécutives", () => {
  const rows = buildRows(result([at(0, "bandeau", "on", { rgb_color: [255, 0, 0] }), at(4, "bandeau", "on", { rgb_color: [0, 0, 255] }), at(6, "bandeau", "off")]));
  expect(rows[0].periods.map((p) => [p.start, p.end])).toEqual([[0, 4], [4, 6]]);
});

test("un « éteindre » sur un composant éteint est ignoré ; un aller-retour instantané reste une période vide", () => {
  const rows = buildRows(result([at(0, "orage", "off"), at(1, "orage", "on"), at(1, "orage", "off"), at(2, "orage", "off")]));
  expect(rows[0].periods.map((p) => [p.start, p.end, p.open])).toEqual([[1, 1, false]]);
});

test("les actions Home Assistant (light.turn_on / switch.turn_off) sont comprises", () => {
  const rows = buildRows(result([at(1, "prise", "switch.turn_on"), at(5, "prise", "switch.turn_off")]));
  expect(rows[0].periods).toMatchObject([{ start: 1, end: 5, open: false }]);
});

test("un composant allumé quand la simulation s'arrête (durée maximale) reste ouvert jusqu'à la fin", () => {
  const rows = buildRows(result([at(2, "orage", "on")], { status: "timeout", duration_s: 90 }));
  expect(rows[0].periods).toMatchObject([{ start: 2, end: 90, open: true }]);
});

test("aucune commande : aucune ligne", () => {
  expect(buildRows(result([]))).toEqual([]);
});

test("graduations rondes, au plus dix", () => {
  expect(ticks(17)).toEqual([0, 2, 4, 6, 8, 10, 12, 14, 16]);
  expect(ticks(90)).toEqual([0, 10, 20, 30, 40, 50, 60, 70, 80, 90]);
  expect(ticks(5)).toEqual([0, 0.5, 1, 1.5, 2, 2.5, 3, 3.5, 4, 4.5, 5]);
  expect(ticks(7200).length).toBeLessThanOrEqual(11);
});

test("durées lisibles", () => {
  expect(formatSeconds(3)).toBe("3 s");
  expect(formatSeconds(1.25)).toBe("1.3 s");
  expect(formatSeconds(125)).toBe("2 min 5 s");
});

test.each([
  ["completed", "ok", /Terminé en 10 s/],
  ["timeout", "warn", /durée maximale/],
  ["horizon", "warn", /boucle sans fin/],
  ["deadlock", "warn", /appui de bouton/],
  ["truncated", "warn", /tronquée/],
  ["failed", "error", /Échec de la simulation : panne/],
])("statut %s expliqué", (status, tone, text) => {
  expect(statusMessage(result([], { status, error: "panne" }))).toMatchObject({ tone, text: expect.stringMatching(text) });
});
