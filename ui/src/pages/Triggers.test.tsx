import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { App } from "../App";
import { setToken } from "../api/token";
import { FakeWebSocket, STATUS, stubEngine, WS, type Call } from "../test-engine";

type Json = Record<string, unknown>;
let calls: Call[];
let triggers: Json[];
let issues: Json[];
let status: typeof STATUS & Json;
let respond: (call: Call) => Response | object | undefined;

const devices = {
  relays: [], lights: [], switches: [], players: [], rest_state: {},
  buttons: [{ id: "bouton_principal", name: "Bouton d'entrée", pin: 21, pull: "up", debounce_ms: 50, long_press_ms: 800, double_press_ms: 400 }],
};
const programs = [
  { id: "scenario-principal", name: "Scénario principal", revision: 1, show: true, scripts: 1, valid: true },
  { id: "ambiance", name: "Ambiance", revision: 1, show: false, scripts: 1, valid: true },
];

beforeEach(() => {
  localStorage.clear();
  FakeWebSocket.instances = [];
  triggers = [];
  issues = [];
  status = structuredClone(STATUS);
  respond = () => undefined;
  window.history.replaceState(null, "", "/declencheurs");
  calls = stubEngine((call) => {
    const custom = respond(call);
    if (custom !== undefined) return custom;
    const { path, method, body } = call;
    if (path === "/api/status") return status;
    if (path === "/api/devices") return devices;
    if (path === "/api/programs") return programs;
    if (path === "/api/triggers" && method === "GET") return { triggers, issues };
    if (path === "/api/triggers" && method === "PUT") {
      triggers = body as Json[];
      return { triggers, issues };
    }
  });
  setToken("secret");
});
afterEach(() => vi.unstubAllGlobals());

const puts = () => calls.filter((c) => c.method === "PUT" && c.path === "/api/triggers");
async function open() {
  render(<App WebSocketImpl={WS} />);
  await screen.findByRole("heading", { name: "Déclencheurs" });
  await waitFor(() => expect(screen.queryByText("Chargement…")).toBeNull());
  return userEvent.setup();
}

test("créer « bouton d'entrée, appui court → scénario principal »", async () => {
  const user = await open();
  await user.click(screen.getByRole("button", { name: "Nouvelle règle" }));
  const dialog = screen.getByRole("dialog", { name: "Nouvelle règle" });
  // valeurs par défaut : le seul bouton, appui court, lancer le premier scénario
  await user.selectOptions(within(dialog).getByLabelText("Scénario à lancer"), "scenario-principal");
  await user.click(within(dialog).getByRole("button", { name: "Enregistrer" }));
  await waitFor(() => expect(puts()).toHaveLength(1));
  expect(puts()[0].body).toEqual([
    { id: "regle-bouton-1", source: "button", button: "bouton_principal", event: "short", program: "scenario-principal", policy: "ignore", enabled: true },
  ]);
  expect(await screen.findByText("Quand Bouton d'entrée reçoit un appui court")).toBeInTheDocument();
  expect(screen.getByText(/Lancer : Scénario principal/)).toBeInTheDocument();
  expect(screen.queryByRole("dialog")).toBeNull();
});

test("choisir l'appui long propose l'arrêt d'urgence, modifiable", async () => {
  const user = await open();
  await user.click(screen.getByRole("button", { name: "Nouvelle règle" }));
  const dialog = screen.getByRole("dialog");
  await user.selectOptions(within(dialog).getByLabelText("Événement"), "long");
  expect(within(dialog).getByLabelText("Action")).toHaveValue("stop");
  expect(within(dialog).getByText(/proposé ici/)).toBeInTheDocument();
  expect(within(dialog).queryByLabelText("Scénario à lancer")).toBeNull();
  await user.selectOptions(within(dialog).getByLabelText("Action"), "run"); // l'utilisateur garde la main
  expect(within(dialog).getByLabelText("Scénario à lancer")).toBeInTheDocument();
});

test("une règle d'arrêt est enregistrée sans scénario", async () => {
  const user = await open();
  await user.click(screen.getByRole("button", { name: "Nouvelle règle" }));
  const dialog = screen.getByRole("dialog");
  await user.selectOptions(within(dialog).getByLabelText("Événement"), "long");
  await user.click(within(dialog).getByRole("button", { name: "Enregistrer" }));
  await waitFor(() => expect(puts()).toHaveLength(1));
  expect(puts()[0].body).toEqual([{ id: "regle-bouton-1", source: "button", button: "bouton_principal", event: "long", action: "stop", policy: "ignore", enabled: true }]);
  expect(await screen.findByText(/→ Arrêter tout/)).toBeInTheDocument();
});

test("le planning se construit et se lit en clair ; il est écrit en cron", async () => {
  const user = await open();
  await user.click(screen.getByRole("button", { name: "Nouvelle règle" }));
  const dialog = screen.getByRole("dialog");
  await user.selectOptions(within(dialog).getByLabelText("Déclenché par"), "schedule");
  expect(within(dialog).getByText("Se déclenchera tous les 31 octobre à 18:00.")).toBeInTheDocument();
  await user.selectOptions(within(dialog).getByLabelText("Répétition"), "weekdays");
  expect(within(dialog).getByText("Se déclenchera le samedi et le dimanche à 18:00.")).toBeInTheDocument();
  await user.click(within(dialog).getByLabelText("lundi"));
  expect(within(dialog).getByText("Se déclenchera le lundi, samedi et dimanche à 18:00.")).toBeInTheDocument();
  await user.selectOptions(within(dialog).getByLabelText("Répétition"), "date");
  await user.selectOptions(within(dialog).getByLabelText("Mois"), "10");
  await user.selectOptions(within(dialog).getByLabelText("Scénario à lancer"), "ambiance");
  await user.click(within(dialog).getByRole("button", { name: "Enregistrer" }));
  await waitFor(() => expect(puts()).toHaveLength(1));
  expect(puts()[0].body).toEqual([{ id: "regle-planning-1", source: "schedule", cron: "0 18 31 10 *", program: "ambiance", policy: "ignore", enabled: true }]);
  expect(await screen.findByText("Quand c'est tous les 31 octobre à 18:00")).toBeInTheDocument();
});

test("une date impossible empêche l'enregistrement, en le disant", async () => {
  const user = await open();
  await user.click(screen.getByRole("button", { name: "Nouvelle règle" }));
  const dialog = screen.getByRole("dialog");
  await user.selectOptions(within(dialog).getByLabelText("Déclenché par"), "schedule");
  await user.selectOptions(within(dialog).getByLabelText("Mois"), "4"); // avril : 30 jours, la date par défaut est le 31
  expect(within(dialog).getByText("Le 31 avril n'existe pas.")).toBeInTheDocument();
  expect(within(dialog).getByRole("button", { name: "Enregistrer" })).toBeDisabled();
});

test("une expression cron déjà écrite est reconnue, ou conservée comme expression avancée", async () => {
  triggers = [
    { id: "t3", source: "schedule", cron: "0 18 31 10 *", program: "ambiance", policy: "ignore", enabled: true },
    { id: "t4", source: "schedule", cron: "*/10 * * * *", program: "ambiance", policy: "queue", enabled: true },
  ];
  const user = await open();
  expect(screen.getByText("Quand c'est tous les 31 octobre à 18:00")).toBeInTheDocument();
  expect(screen.getByText(/Quand c'est expression avancée « \*\/10 \* \* \* \* »/)).toBeInTheDocument();
  await user.click(within(screen.getByLabelText(/10 \* \* \* \*/)).getByRole("button", { name: "Modifier" }));
  expect(screen.getByLabelText("Expression cron")).toHaveValue("*/10 * * * *");
});

test("deux règles actives sur le même bouton et le même événement : alerte, avant et après enregistrement", async () => {
  triggers = [{ id: "a", source: "button", button: "bouton_principal", event: "short", program: "ambiance", policy: "ignore", enabled: true }];
  const user = await open();
  await user.click(screen.getByRole("button", { name: "Nouvelle règle" }));
  const dialog = screen.getByRole("dialog");
  expect(within(dialog).getByRole("alert")).toHaveTextContent("Les deux se déclencheront");
  await user.click(within(dialog).getByRole("button", { name: "Enregistrer" }));
  await waitFor(() => expect(puts()).toHaveLength(1));
  const rules = await screen.findAllByText(/Même bouton et même événement que/);
  expect(rules).toHaveLength(2); // chaque règle désigne l'autre
});

test("une règle désactivée ne déclenche pas d'alerte de doublon", async () => {
  triggers = [
    { id: "a", source: "button", button: "bouton_principal", event: "short", program: "ambiance", policy: "ignore", enabled: false },
    { id: "b", source: "button", button: "bouton_principal", event: "short", program: "ambiance", policy: "ignore", enabled: true },
  ];
  await open();
  expect(screen.queryByText(/Même bouton et même événement/)).toBeNull();
});

test("activer / désactiver et supprimer réécrivent la liste complète", async () => {
  triggers = [
    { id: "a", source: "button", button: "bouton_principal", event: "short", program: "ambiance", policy: "ignore", enabled: true },
    { id: "b", source: "button", button: "bouton_principal", event: "double", program: "scenario-principal", policy: "restart", enabled: true },
  ];
  const user = await open();
  const first = screen.getByLabelText(/appui court → Lancer : Ambiance/);
  await user.click(within(first).getByRole("button", { name: "Désactiver" }));
  await waitFor(() => expect(puts()).toHaveLength(1));
  expect((puts()[0].body as Json[]).map((t) => [t.id, t.enabled])).toEqual([["a", false], ["b", true]]);
  const second = screen.getByLabelText(/double appui/);
  expect(within(second).getByText("le redémarrer s'il tourne déjà")).toBeInTheDocument();
  await user.click(within(second).getByRole("button", { name: "Supprimer" }));
  await waitFor(() => expect(puts()).toHaveLength(2));
  expect((puts()[1].body as Json[]).map((t) => t.id)).toEqual(["a"]);
});

test("un refus du moteur est expliqué dans la fenêtre, qui reste ouverte", async () => {
  respond = ({ method, path }) =>
    method === "PUT" && path === "/api/triggers"
      ? Response.json({ detail: { message: "déclencheur invalide", issues: [{ message: "programme inconnu : `x`", component_id: "regle-bouton-1" }] } }, { status: 422 })
      : undefined;
  const user = await open();
  await user.click(screen.getByRole("button", { name: "Nouvelle règle" }));
  await user.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Enregistrer" }));
  expect(await screen.findByText("déclencheur invalide")).toBeInTheDocument();
  expect(screen.getByText(/programme inconnu/)).toBeInTheDocument();
  expect(screen.getByRole("dialog")).toBeInTheDocument();
});

test("les règles écartées par le moteur sont listées", async () => {
  issues = [{ severity: "error", code: "unknown_button", message: "bouton inconnu : `disparu`", component_id: "z" }];
  await open();
  expect(screen.getByText("Des règles sont écartées par le moteur :")).toBeInTheDocument();
  expect(screen.getByText("bouton inconnu : `disparu`")).toBeInTheDocument();
});

test("un bouton sans règle d'appui long se voit proposer « appui long → Arrêter »", async () => {
  const user = await open();
  expect(screen.getByText(/n'a pas de règle d'appui long/)).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Ajouter « appui long → Arrêter »" }));
  await waitFor(() => expect(puts()).toHaveLength(1));
  expect(puts()[0].body).toEqual([{ id: "regle-bouton_principal-long", source: "button", button: "bouton_principal", event: "long", action: "stop", policy: "ignore", enabled: true }]);
  await waitFor(() => expect(screen.queryByText(/n'a pas de règle d'appui long/)).toBeNull());
});

test("verrouillé : lecture seule, sans suggestion", async () => {
  status.lock = { locked: true, has_code: true } as never;
  triggers = [{ id: "a", source: "button", button: "bouton_principal", event: "short", program: "ambiance", policy: "ignore", enabled: true }];
  await open();
  expect(screen.getByRole("button", { name: "Nouvelle règle" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Modifier" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Supprimer" })).toBeDisabled();
  expect(screen.queryByText(/n'a pas de règle d'appui long/)).toBeNull();
});

test("un détecteur de mouvement ne propose que « mouvement détecté » et l'enregistre", async () => {
  devices.buttons.push({ id: "pir", name: "Couloir", kind: "motion", pin: 26, pull: "down", debounce_ms: 50, warmup_s: 60 } as never);
  const user = await open();
  await user.click(screen.getByRole("button", { name: "Nouvelle règle" }));
  const dialog = screen.getByRole("dialog", { name: "Nouvelle règle" });
  expect(within(dialog).getAllByRole("option", { name: /appui/ })).toHaveLength(3); // le bouton, d'abord
  await user.selectOptions(within(dialog).getByLabelText("Bouton"), "pir");
  const events = within(dialog).getByLabelText("Événement");
  expect(within(events).getAllByRole("option").map((o) => o.textContent)).toEqual(["un mouvement détecté"]);
  expect(events).toHaveValue("motion");
  await user.selectOptions(within(dialog).getByLabelText("Scénario à lancer"), "scenario-principal");
  await user.click(within(dialog).getByRole("button", { name: "Enregistrer" }));
  await waitFor(() => expect(puts()).toHaveLength(1));
  expect(puts()[0].body).toEqual([
    { id: "regle-bouton-1", source: "button", button: "pir", event: "motion", program: "scenario-principal", policy: "ignore", enabled: true },
  ]);
  expect(await screen.findByText("Quand Couloir détecte un mouvement")).toBeInTheDocument();
});
