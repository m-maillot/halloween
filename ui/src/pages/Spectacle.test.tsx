import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { App } from "../App";
import { setToken } from "../api/token";
import { FakeWebSocket, STATUS, stubEngine, WS, type Call } from "../test-engine";

type Json = Record<string, unknown>;
const NOW_MS = 2_000_000_000_000;
let calls: Call[];
let status: typeof STATUS & Json;
let programs: Json[];
let respond: (call: Call) => Response | object | undefined;

const program = (id: string, name: string, extra: Json = {}) => ({ id, name, revision: 1, show: true, show_order: null, scripts: 1, valid: true, max_duration_s: 60, ...extra });

beforeEach(() => {
  localStorage.clear();
  FakeWebSocket.instances = [];
  vi.spyOn(Date, "now").mockReturnValue(NOW_MS);
  status = structuredClone(STATUS);
  programs = [
    program("c", "Cinquième", { show: false }),
    program("b", "Brouillard", { show_order: 2 }),
    program("a", "Apparition", { show_order: 1 }),
    program("amb", "Ambiance", { show_order: 3, max_duration_s: null }),
  ];
  respond = () => undefined;
  window.history.replaceState(null, "", "/spectacle");
  calls = stubEngine((call) => {
    const custom = respond(call);
    if (custom !== undefined) return custom;
    const { path, method } = call;
    if (path === "/api/status") return status;
    if (path === "/api/devices") return { relays: [], buttons: [{ id: "bp", name: "Bouton d'entrée", pin: 21, pull: "up", debounce_ms: 50, long_press_ms: 800, double_press_ms: 400 }], lights: [], switches: [], rest_state: {} };
    if (path === "/api/programs") return programs;
    if (method === "POST" && path === "/api/runs") return { run_id: "r1", program_id: "a", state: "running" };
    if (method === "POST") return { stopped: 1 };
  });
  setToken("secret");
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  delete (navigator as { wakeLock?: unknown }).wakeLock;
});

async function open() {
  render(<App WebSocketImpl={WS} />);
  await screen.findByText("Moteur connecté");
  await screen.findAllByLabelText("Apparition");
  return userEvent.setup();
}
// (une barre de progression porte aussi le nom du scénario : on vise la tuile elle-même)
const tile = (name: string) => screen.getAllByLabelText(name).find((e) => e.classList.contains("show__tile"))!;
const posts = (path: string) => calls.filter((c) => c.method === "POST" && c.path === path);

test("seuls les scénarios cochés apparaissent, dans l'ordre choisi (sans rang : à la fin)", async () => {
  await open();
  expect(screen.queryByLabelText("Cinquième")).toBeNull();
  const names = screen.getAllByRole("listitem").map((li) => within(li).getByText(/Apparition|Brouillard|Ambiance/).textContent);
  expect(names).toEqual(["Apparition", "Brouillard", "Ambiance"]);
});

test("aucun lien, aucun menu : rien ne mène à la configuration, à l'éditeur ou à la suppression", async () => {
  await open();
  expect(screen.queryAllByRole("link")).toHaveLength(0);
  expect(screen.queryByRole("navigation")).toBeNull();
  for (const word of ["Composants", "Réglages", "Déclencheurs", "Scénarios", "Supprimer", "Modifier", "Ouvrir"]) {
    expect(screen.queryByText(word)).toBeNull();
  }
});

test("Lancer démarre le scénario sans confirmation ni code quand l'interface est déverrouillée", async () => {
  const user = await open();
  await user.click(within(tile("Apparition")).getByRole("button", { name: "Lancer" }));
  await waitFor(() => expect(posts("/api/runs")).toHaveLength(1));
  expect(posts("/api/runs")[0].body).toEqual({ program_id: "a", policy: "ignore" });
  expect(screen.queryByRole("dialog")).toBeNull();
});

test("un scénario déjà en cours (409) est annoncé calmement, sans alarme", async () => {
  respond = ({ method, path }) => (method === "POST" && path === "/api/runs" ? Response.json({ detail: { message: "tourne déjà", issues: [] } }, { status: 409 }) : undefined);
  const user = await open();
  await user.click(within(tile("Apparition")).getByRole("button", { name: "Lancer" }));
  expect(await screen.findByText("« Apparition » tourne déjà.")).toBeInTheDocument();
  expect(screen.queryByRole("alert")).toBeNull();
});

test("plusieurs scénarios tournent en même temps : progression, « en continu », arrêt individuel", async () => {
  const engine = NOW_MS / 1000;
  status.started_at = engine - 100;
  (status as Json).uptime_s = 100;
  status.runs = [
    { run_id: "r1", program_id: "a", state: "running", started_at: engine - 20 },
    { run_id: "r2", program_id: "amb", state: "running", started_at: engine - 7 },
  ];
  const user = await open();
  expect(within(tile("Apparition")).getByText("20 s / 60 s")).toBeInTheDocument();
  expect(within(tile("Apparition")).getByRole("progressbar")).toHaveAttribute("aria-valuenow", "33");
  expect(within(tile("Ambiance")).getByText("7 s · en continu")).toBeInTheDocument();
  expect(within(tile("Brouillard")).getByRole("button", { name: "Lancer" })).toBeEnabled(); // un autre se lance en parallèle
  await user.click(within(tile("Ambiance")).getByRole("button", { name: "Arrêter" }));
  expect(posts("/api/runs/r2/stop")).toHaveLength(1);
  expect(posts("/api/runs/r1/stop")).toHaveLength(0); // l'autre reste actif
});

test("verrouillé : chaque lancement demande le code, jamais d'ouverture de session", async () => {
  status.lock = { locked: true, has_code: true } as never;
  respond = ({ method, path, body }) =>
    method === "POST" && path === "/api/runs" ? ((body as { code?: string }).code === "1234" ? { run_id: "r1", program_id: "a", state: "running" } : Response.json({ detail: { message: "code incorrect", issues: [] } }, { status: 401 })) : undefined;
  const user = await open();
  await user.click(within(tile("Apparition")).getByRole("button", { name: "Lancer" }));
  expect(posts("/api/runs")).toHaveLength(0);
  const dialog = screen.getByRole("dialog", { name: /Code pour lancer « Apparition »/ });
  await user.type(within(dialog).getByLabelText("Code"), "1234");
  await user.click(within(dialog).getByRole("button", { name: "Valider" }));
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  // le suivant redemande le code
  await user.click(within(tile("Brouillard")).getByRole("button", { name: "Lancer" }));
  expect(screen.getByRole("dialog", { name: /Code pour lancer « Brouillard »/ })).toBeInTheDocument();
});

test("STOP arrête tout, sans code, même verrouillé", async () => {
  status.lock = { locked: true, has_code: true } as never;
  const user = await open();
  await user.click(screen.getByRole("button", { name: /STOP/ }));
  await waitFor(() => expect(posts("/api/runs/stop")).toHaveLength(1));
  expect(screen.queryByRole("dialog")).toBeNull();
});

test("moteur injoignable : message clair, Lancer désactivé, mais STOP tente quand même l'appel", async () => {
  respond = ({ path }) => (path === "/api/status" ? Response.json({ detail: "ko" }, { status: 503 }) : undefined);
  render(<App WebSocketImpl={WS} />);
  expect(await screen.findByText(/Moteur injoignable : les boutons physiques/)).toBeInTheDocument();
  const user = userEvent.setup();
  await user.click(screen.getByRole("button", { name: /STOP/ }));
  await waitFor(() => expect(posts("/api/runs/stop")).toHaveLength(1));
});

test("quitter : direct si déverrouillé", async () => {
  const user = await open();
  await user.click(screen.getByRole("button", { name: "Quitter le mode spectacle" }));
  expect(window.location.pathname).toBe("/");
});

test("quitter : le code est demandé si verrouillé (et déverrouille)", async () => {
  status.lock = { locked: true, has_code: true } as never;
  respond = ({ method, path }) => (method === "POST" && path === "/api/unlock" ? { locked: false, has_code: true } : undefined);
  const user = await open();
  await user.click(screen.getByRole("button", { name: "Quitter le mode spectacle" }));
  expect(window.location.pathname).toBe("/spectacle"); // pas encore
  const dialog = screen.getByRole("dialog", { name: /Quitter le mode spectacle/ });
  await user.type(within(dialog).getByLabelText("Code"), "2468");
  await user.click(within(dialog).getByRole("button", { name: "Valider" }));
  await waitFor(() => expect(window.location.pathname).toBe("/"));
  expect(posts("/api/unlock")[0].body).toEqual({ code: "2468" });
});

test("les appuis de boutons physiques se reflètent", async () => {
  await open();
  expect(screen.getByText(/En attente d'un appui/)).toBeInTheDocument();
  act(() => FakeWebSocket.emit({ type: "button_event", button_id: "bp", event: "long" }));
  expect(await screen.findByText("Bouton d'entrée : appui long")).toBeInTheDocument();
});

test("aucun scénario affiché : l'écran explique comment en afficher", async () => {
  programs = [program("c", "Cinquième", { show: false })];
  render(<App WebSocketImpl={WS} />);
  expect(await screen.findByText(/Aucun scénario n'est affiché en mode spectacle/)).toBeInTheDocument();
});

// ------------------------------------------------------------------ écran maintenu allumé

function stubWakeLock() {
  const sentinel = { release: vi.fn(async () => undefined), addEventListener: vi.fn() };
  const request = vi.fn(async () => sentinel);
  Object.defineProperty(navigator, "wakeLock", { value: { request }, configurable: true });
  return { sentinel, request };
}

test("l'écran est maintenu allumé, puis relâché en quittant", async () => {
  const { sentinel, request } = stubWakeLock();
  const { unmount } = render(<App WebSocketImpl={WS} />);
  expect(await screen.findByText("Écran maintenu allumé")).toBeInTheDocument();
  expect(request).toHaveBeenCalledWith("screen");
  unmount();
  expect(sentinel.release).toHaveBeenCalled();
});

test("le verrou perdu quand l'onglet est masqué est repris au retour", async () => {
  const { request } = stubWakeLock();
  render(<App WebSocketImpl={WS} />);
  await screen.findByText("Écran maintenu allumé");
  const before = request.mock.calls.length;
  document.dispatchEvent(new Event("visibilitychange")); // jsdom : l'onglet est « visible »
  await waitFor(() => expect(request.mock.calls.length).toBeGreaterThan(before));
});

test("navigateur sans Wake Lock, ou refusé : le dit, sans bloquer", async () => {
  render(<App WebSocketImpl={WS} />);
  expect(await screen.findByText("Écran non maintenu allumé")).toBeInTheDocument();
});
