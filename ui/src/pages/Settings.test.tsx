import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { App } from "../App";
import { currentToken, setToken } from "../api/token";
import { FakeWebSocket, STATUS, stubEngine, WS, type Call } from "../test-engine";

type Json = Record<string, unknown>;
let status: typeof STATUS & Json;
let ha: Json;
let rest: Json;
let calls: Call[];
let respond: (call: Call) => Response | object | undefined;

const devices = {
  relays: [{ id: "orage", name: "Orage", pin: 22, mode: "latched", active_low: false }],
  buttons: [],
  lights: [{ id: "bandeau", name: "Bandeau", entity_id: "light.bandeau", supports_color: true, supports_brightness: true, supports_transition: true }],
  switches: [{ id: "guirlande", name: "Guirlande", entity_id: "switch.guirlande" }],
  rest_state: {},
};

beforeEach(() => {
  localStorage.clear();
  FakeWebSocket.instances = [];
  status = structuredClone(STATUS);
  ha = { configured: true, url: "http://ha.local:8123", timeout_s: 5, token_set: true, token_source: "config" };
  rest = { rest_state: { bandeau: { state: "on", rgb_color: [255, 0, 0], brightness: 40 } } };
  respond = () => undefined;
  window.history.replaceState(null, "", "/reglages");
  calls = stubEngine((call) => {
    const custom = respond(call);
    if (custom !== undefined) return custom;
    const { path, method } = call;
    if (path === "/api/status") return status;
    if (path === "/api/devices") return devices;
    if (path === "/api/config/home-assistant" && method === "GET") return ha;
    if (path === "/api/config/rest-state" && method === "GET") return rest;
    if (path === "/api/ha/entities") return [];
    if (method === "PUT" || method === "POST") return { issues: [], config: ha, rest_state: {}, ok: true, message: "ok" };
  });
  setToken("secret");
});
afterEach(() => vi.unstubAllGlobals());

async function openApp() {
  render(<App WebSocketImpl={WS} />);
  await screen.findByDisplayValue("http://ha.local:8123");
  return userEvent.setup();
}
const section = (name: string) => screen.getByRole("region", { name });
const sent = (method: string, path: string) => calls.filter((c) => c.method === method && c.path === path);

// ------------------------------------------------------------------ Home Assistant

test("la connexion Home Assistant existante est affichée, le jeton jamais", async () => {
  await openApp();
  const ha = section("Home Assistant");
  expect(within(ha).getByLabelText("Jeton d'accès")).toHaveValue("");
  expect(within(ha).getByLabelText("Jeton d'accès")).toHaveAttribute("placeholder", "inchangé");
  expect(within(ha).getByText(/Un jeton est enregistré/)).toBeInTheDocument();
});

test("tester la connexion utilise les valeurs saisies et dit le résultat", async () => {
  respond = ({ path }) => (path === "/api/config/home-assistant/test" ? { ok: true, message: "Home Assistant 2025.1", latency_ms: 42.4 } : undefined);
  const user = await openApp();
  const ha = section("Home Assistant");
  await user.clear(within(ha).getByLabelText("Adresse (URL)"));
  await user.type(within(ha).getByLabelText("Adresse (URL)"), "http://nouveau:8123");
  await user.type(within(ha).getByLabelText("Jeton d'accès"), "abc");
  await user.click(within(ha).getByRole("button", { name: "Tester la connexion" }));
  expect(await within(ha).findByText("Connexion réussie")).toBeInTheDocument();
  expect(within(ha).getByText(/Home Assistant 2025.1 \(42 ms\)/)).toBeInTheDocument();
  expect(sent("POST", "/api/config/home-assistant/test")[0].body).toEqual({ url: "http://nouveau:8123", token: "abc", timeout_s: 5 });
  expect(sent("PUT", "/api/config/home-assistant")).toHaveLength(0); // le test n'enregistre rien
});

test.each([
  ["HAUnreachable", "URL injoignable"],
  ["HAAuthError", "Jeton refusé"],
  ["HATimeout", "Délai dépassé"],
  [null, "Échec de la connexion"],
])("un échec « %s » est annoncé « %s »", async (error_type, title) => {
  respond = ({ path }) => (path === "/api/config/home-assistant/test" ? { ok: false, message: "détail du moteur", error_type } : undefined);
  const user = await openApp();
  await user.click(within(section("Home Assistant")).getByRole("button", { name: "Tester la connexion" }));
  const result = await within(section("Home Assistant")).findByRole("status");
  expect(result).toHaveTextContent(title);
  expect(result).toHaveTextContent("détail du moteur");
});

test("enregistrer sans toucher au jeton le laisse inchangé (token absent)", async () => {
  const user = await openApp();
  await user.click(within(section("Home Assistant")).getByRole("button", { name: "Enregistrer" }));
  await waitFor(() => expect(sent("PUT", "/api/config/home-assistant")).toHaveLength(1));
  expect(sent("PUT", "/api/config/home-assistant")[0].body).toEqual({ url: "http://ha.local:8123", token: null, timeout_s: 5 });
});

test("un jeton saisi est envoyé ; « supprimer le jeton » envoie une chaîne vide", async () => {
  const user = await openApp();
  const ha = section("Home Assistant");
  await user.type(within(ha).getByLabelText("Jeton d'accès"), "nouveau");
  await user.click(within(ha).getByRole("button", { name: "Enregistrer" }));
  await waitFor(() => expect(sent("PUT", "/api/config/home-assistant")).toHaveLength(1));
  expect(sent("PUT", "/api/config/home-assistant")[0].body).toMatchObject({ token: "nouveau" });
  await user.click(within(ha).getByLabelText("Supprimer le jeton enregistré"));
  expect(within(ha).getByLabelText("Jeton d'accès")).toBeDisabled();
  await user.click(within(ha).getByRole("button", { name: "Enregistrer" }));
  await waitFor(() => expect(sent("PUT", "/api/config/home-assistant")).toHaveLength(2));
  expect(sent("PUT", "/api/config/home-assistant")[1].body).toMatchObject({ token: "" });
});

test("jeton fourni par l'environnement : le dit, sans proposer de le supprimer", async () => {
  ha.token_source = "env";
  await openApp();
  expect(screen.getByText(/variable HALLOWEEN_HA_TOKEN/)).toBeInTheDocument();
  expect(screen.queryByLabelText("Supprimer le jeton enregistré")).toBeNull();
});

test("des scénarios en cours : confirmation avant d'appliquer la nouvelle connexion", async () => {
  respond = ({ method, path, search }) => {
    if (method === "PUT" && path === "/api/config/home-assistant" && !search.includes("stop_runs=true")) {
      return Response.json({ detail: { message: "des scénarios tournent (scene) : relancer avec stop_runs=true pour confirmer", issues: [] } }, { status: 409 });
    }
  };
  const user = await openApp();
  await user.click(within(section("Home Assistant")).getByRole("button", { name: "Enregistrer" }));
  await user.click(await screen.findByRole("button", { name: "Arrêter les scénarios et continuer" }));
  await waitFor(() => expect(sent("PUT", "/api/config/home-assistant").some((c) => c.search.includes("stop_runs=true"))).toBe(true));
});

test("une URL refusée par le moteur s'affiche sous le champ", async () => {
  respond = ({ method, path }) =>
    method === "PUT" && path === "/api/config/home-assistant"
      ? Response.json({ detail: [{ loc: ["body", "url"], msg: "URL invalide", type: "x" }] }, { status: 422 })
      : undefined;
  const user = await openApp();
  await user.click(within(section("Home Assistant")).getByRole("button", { name: "Enregistrer" }));
  expect(await screen.findByText("URL invalide")).toBeInTheDocument();
});

// ------------------------------------------------------------------ état de repos

test("l'état de repos existant est affiché, avec les champs selon les capacités", async () => {
  await openApp();
  const bandeau = await screen.findByRole("group", { name: "Bandeau" });
  expect(within(bandeau).getByLabelText("À l'état de repos")).toHaveValue("on");
  expect(within(bandeau).getByLabelText("Couleur de Bandeau")).toHaveValue("#ff0000");
  expect(within(bandeau).getByLabelText(/Luminosité de Bandeau/)).toHaveValue(40);
  expect(within(screen.getByRole("group", { name: "Guirlande" })).getByLabelText("À l'état de repos")).toHaveValue("");
  expect(screen.getByText(/Orage\) sont toujours éteints/)).toBeInTheDocument();
});

test("enregistrer l'état de repos envoie la table complète", async () => {
  const user = await openApp();
  const guirlande = await screen.findByRole("group", { name: "Guirlande" });
  await user.selectOptions(within(guirlande).getByLabelText("À l'état de repos"), "off");
  const bandeau = screen.getByRole("group", { name: "Bandeau" });
  await user.clear(within(bandeau).getByLabelText(/Luminosité/));
  await user.type(within(bandeau).getByLabelText(/Luminosité/), "100");
  await user.click(screen.getByRole("button", { name: "Enregistrer l'état de repos" }));
  await waitFor(() => expect(sent("PUT", "/api/config/rest-state")).toHaveLength(1));
  expect(sent("PUT", "/api/config/rest-state")[0].body).toEqual({
    rest_state: {
      bandeau: { state: "on", rgb_color: [255, 0, 0], brightness: 100 },
      guirlande: { state: "off" },
    },
  });
});

test("« Ne pas y toucher » retire le composant de la table", async () => {
  const user = await openApp();
  const bandeau = await screen.findByRole("group", { name: "Bandeau" });
  await user.selectOptions(within(bandeau).getByLabelText("À l'état de repos"), "");
  await user.click(screen.getByRole("button", { name: "Enregistrer l'état de repos" }));
  await waitFor(() => expect(sent("PUT", "/api/config/rest-state")).toHaveLength(1));
  expect(sent("PUT", "/api/config/rest-state")[0].body).toEqual({ rest_state: {} });
});

// ------------------------------------------------------------------ code de verrouillage

test("définir un premier code : confirmation et format contrôlés avant l'envoi", async () => {
  const user = await openApp();
  const lock = section("Code de verrouillage");
  expect(within(lock).queryByLabelText("Code actuel")).toBeNull();
  const submit = within(lock).getByRole("button", { name: "Définir le code" });
  await user.type(within(lock).getByLabelText("Nouveau code"), "12");
  expect(within(lock).getByText("Le code comporte 4 à 8 chiffres.")).toBeInTheDocument();
  await user.type(within(lock).getByLabelText("Nouveau code"), "34");
  await user.type(within(lock).getByLabelText("Confirmer le nouveau code"), "1235");
  expect(within(lock).getByText("Les deux codes sont différents.")).toBeInTheDocument();
  expect(submit).toBeDisabled();
  await user.clear(within(lock).getByLabelText("Confirmer le nouveau code"));
  await user.type(within(lock).getByLabelText("Confirmer le nouveau code"), "1234");
  await user.click(submit);
  await waitFor(() => expect(sent("PUT", "/api/lock/code")).toHaveLength(1));
  expect(sent("PUT", "/api/lock/code")[0].body).toEqual({ new_code: "1234", old_code: null });
});

test("changer le code exige l'ancien ; un ancien code faux est signalé avec le délai", async () => {
  status.lock = { locked: false, has_code: true } as never;
  respond = ({ method, path }) =>
    method === "PUT" && path === "/api/lock/code"
      ? Response.json({ detail: { message: "trop d'essais.", issues: [], retry_after_s: 30 } }, { status: 429 })
      : undefined;
  const user = await openApp();
  const lock = section("Code de verrouillage");
  await user.type(within(lock).getByLabelText("Nouveau code"), "5678");
  await user.type(within(lock).getByLabelText("Confirmer le nouveau code"), "5678");
  expect(within(lock).getByRole("button", { name: "Changer le code" })).toBeDisabled(); // ancien code manquant
  await user.type(within(lock).getByLabelText("Code actuel"), "0000");
  await user.click(within(lock).getByRole("button", { name: "Changer le code" }));
  expect(await within(lock).findByRole("alert")).toHaveTextContent("Réessayer dans 30 s");
  expect(sent("PUT", "/api/lock/code")[0].body).toEqual({ new_code: "5678", old_code: "0000" });
  expect(localStorage.getItem("halloween.token")).toBe("secret");
});

// ------------------------------------------------------------------ jeton du moteur et verrou

test("le jeton du moteur se remplace ou s'oublie dans ce navigateur", async () => {
  const user = await openApp();
  const token = section("Jeton du moteur");
  await user.type(within(token).getByLabelText("Jeton d'accès à l'API"), "autre");
  await user.click(within(token).getByRole("button", { name: "Enregistrer" }));
  expect(currentToken()).toBe("autre");
  await user.click(within(token).getByRole("button", { name: "Oublier le jeton" }));
  expect(currentToken()).toBeNull();
  expect(await screen.findByLabelText("Jeton du moteur")).toBeInTheDocument(); // retour à la saisie
});

test("verrouillé : les réglages sont en lecture seule", async () => {
  status.lock = { locked: true, has_code: true } as never;
  await openApp();
  expect(screen.getByText(/les réglages sont en lecture seule/)).toBeInTheDocument();
  expect(within(section("Home Assistant")).getByLabelText("Adresse (URL)")).toBeDisabled();
  expect(within(section("Home Assistant")).getByRole("button", { name: "Enregistrer" })).toBeDisabled();
  expect(within(section("Home Assistant")).getByRole("button", { name: "Tester la connexion" })).toBeDisabled(); // le moteur refuse aussi le test (423)
  expect(within(await screen.findByRole("group", { name: "Guirlande" })).getByLabelText("À l'état de repos")).toBeDisabled();
  expect(within(section("Code de verrouillage")).getByLabelText("Nouveau code")).toBeDisabled();
});
