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
    if (path === "/api/devices") return { relays: [], buttons: [], lights: [], switches: [], rest_state: {} };
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
