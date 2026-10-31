import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { App } from "../App";
import { setToken } from "../api/token";
import { FakeWebSocket, STATUS, stubEngine, WS, type Call } from "../test-engine";

// Blockly a besoin d'un vrai navigateur pour s'afficher : ici on ne teste que la page.
vi.mock("../editor/BlocklyEditor", () => ({ BlocklyEditor: () => null }));

let calls: Call[];
beforeEach(() => {
  localStorage.clear();
  FakeWebSocket.instances = [];
  window.history.replaceState(null, "", "/scenarios");
  calls = stubEngine(({ path, method }) => {
    if (path === "/api/status") return STATUS;
    if (path === "/api/devices") return { relays: [], buttons: [], lights: [], switches: [], players: [], rest_state: {} };
    if (path === "/api/programs" && method === "GET")
      return [{ id: "scene", name: "Scène", revision: 1, show: false, scripts: 2, valid: true }];
    if (method === "PUT") return { program: {}, warnings: [] };
  });
  setToken("secret");
});
afterEach(() => vi.unstubAllGlobals());

test("la liste montre les scénarios et leur nombre de scripts", async () => {
  render(<App WebSocketImpl={WS} />);
  expect(await screen.findByText("2 scripts")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Ouvrir" })).toHaveAttribute("href", "/scenarios/scene");
});

test("un nouveau scénario naît avec un bloc début et un identifiant libre", async () => {
  render(<App WebSocketImpl={WS} />);
  const user = userEvent.setup();
  await user.click(await screen.findByRole("button", { name: "Nouveau scénario" }));
  await user.type(screen.getByLabelText("Nom"), "Scène");
  await user.click(screen.getByRole("button", { name: "Créer" }));
  await waitFor(() => expect(calls.some((c) => c.method === "PUT")).toBe(true));
  const put = calls.find((c) => c.method === "PUT")!;
  expect(put.path).toBe("/api/programs/scene-2"); // « scene » est déjà pris
  expect(put.body).toMatchObject({ name: "Scène", scripts: [{ id: "s1", hat: { type: "start" } }] });
});


// ------------------------------------------------------------------ mode spectacle, duplication, suppression

import { within } from "@testing-library/react";

type Json = Record<string, unknown>;
const full = (id: string, extra: Json = {}) => ({ schema: 1, id, name: id.toUpperCase(), revision: 4, on_end: "reset", show: false, show_order: null, max_duration_s: null, scripts: [{ id: "s1", root: { id: "r", type: "sequence", children: [] } }], editor: null, ...extra });

function withPrograms(summaries: Json[]) {
  vi.unstubAllGlobals();
  const store: Record<string, Json> = Object.fromEntries(summaries.map((s) => [s.id as string, full(s.id as string, { name: s.name, show: s.show, show_order: s.show_order })]));
  calls = stubEngine(({ path, method, body }) => {
    if (path === "/api/status") return STATUS;
    if (path === "/api/devices") return { relays: [], buttons: [], lights: [], switches: [], players: [], rest_state: {} };
    if (path === "/api/programs" && method === "GET") return Object.values(store).map((p) => ({ id: p.id, name: p.name, revision: p.revision, show: p.show, show_order: p.show_order, scripts: 1, valid: true }));
    const match = /^\/api\/programs\/(.+)$/.exec(path);
    if (match && method === "GET") return store[match[1]];
    if (match && method === "PUT") {
      store[match[1]] = body as Json;
      return { program: body, warnings: [] };
    }
    if (match && method === "DELETE") {
      delete store[match[1]];
      return new Response(null, { status: 204 });
    }
  });
  return store;
}
const puts = () => calls.filter((c) => c.method === "PUT");

test("cocher « afficher en mode spectacle » passe le scénario en dernier rang, décocher le retire", async () => {
  withPrograms([{ id: "a", name: "A", show: true, show_order: 1 }, { id: "b", name: "B", show: false, show_order: null }]);
  render(<App WebSocketImpl={WS} />);
  const user = userEvent.setup();
  const card = await screen.findByLabelText("B");
  await user.click(within(card).getByLabelText("Afficher en mode spectacle"));
  await waitFor(() => expect(puts()).toHaveLength(1));
  expect(puts()[0].path).toBe("/api/programs/b");
  expect(puts()[0].headers.get("If-Match")).toBe('"4"');
  expect(puts()[0].body).toMatchObject({ show: true, show_order: 2 });
  await user.click(within(screen.getByLabelText("A")).getByLabelText("Afficher en mode spectacle"));
  await waitFor(() => expect(puts()).toHaveLength(2));
  expect(puts()[1].body).toMatchObject({ show: false, show_order: null });
});

test("monter / descendre échange les rangs et les renumérote de 1 à n", async () => {
  withPrograms([{ id: "a", name: "A", show: true, show_order: 1 }, { id: "b", name: "B", show: true, show_order: 5 }, { id: "c", name: "C", show: true, show_order: 9 }]);
  render(<App WebSocketImpl={WS} />);
  const user = userEvent.setup();
  await screen.findByLabelText("C");
  expect(screen.getByRole("button", { name: "Monter A dans le mode spectacle" })).toBeDisabled(); // déjà premier
  await user.click(screen.getByRole("button", { name: "Monter C dans le mode spectacle" }));
  await waitFor(() => expect(puts().length).toBeGreaterThanOrEqual(2));
  const orders = Object.fromEntries(puts().map((c) => [c.path.split("/").pop(), (c.body as Json).show_order]));
  expect(orders).toEqual({ b: 3, c: 2 }); // A reste 1 ; B et C sont renumérotés après l'échange
});

test("dupliquer crée une copie neuve (révision 0, non affichée en spectacle) et l'ouvre", async () => {
  withPrograms([{ id: "a", name: "A", show: true, show_order: 1 }]);
  render(<App WebSocketImpl={WS} />);
  const user = userEvent.setup();
  await user.click(within(await screen.findByLabelText("A")).getByRole("button", { name: "Dupliquer" }));
  await waitFor(() => expect(puts()).toHaveLength(1));
  expect(puts()[0].path).toBe("/api/programs/a-copie");
  expect(puts()[0].headers.get("If-Match")).toBeNull(); // création : pas de précondition
  expect(puts()[0].body).toMatchObject({ id: "a-copie", name: "A (copie)", revision: 0, show: false, show_order: null });
  await waitFor(() => expect(window.location.pathname).toBe("/scenarios/a-copie"));
});

test("supprimer demande confirmation, puis retire le scénario", async () => {
  withPrograms([{ id: "a", name: "A", show: false, show_order: null }]);
  render(<App WebSocketImpl={WS} />);
  const user = userEvent.setup();
  await user.click(within(await screen.findByLabelText("A")).getByRole("button", { name: "Supprimer" }));
  expect(calls.some((c) => c.method === "DELETE")).toBe(false);
  await user.click(within(screen.getByRole("dialog", { name: "Supprimer ce scénario ?" })).getByRole("button", { name: "Supprimer" }));
  await waitFor(() => expect(calls.some((c) => c.method === "DELETE" && c.path === "/api/programs/a")).toBe(true));
  await waitFor(() => expect(screen.queryByLabelText("A")).toBeNull());
});
