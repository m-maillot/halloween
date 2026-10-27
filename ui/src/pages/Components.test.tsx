import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { App } from "../App";
import { setToken } from "../api/token";
import { FakeWebSocket, STATUS, stubEngine, WS } from "../test-engine";

const devices = {
  relays: [
    { id: "fantome", name: "Fantôme", pin: 18, mode: "latched", active_low: false, image: "builtin:ghost", image_url: null },
    { id: "eclair", name: "Éclair", pin: 22, mode: "push", pulse_ms: 500, active_low: false, image: "a.png", image_url: "/api/images/a.png" },
  ],
  buttons: [{ id: "bouton_principal", name: "Bouton principal", pin: 21, pull: "up", debounce_ms: 50, long_press_ms: 800, double_press_ms: 300 }],
  lights: [{ id: "bandeau", name: "Bandeau", entity_id: "light.bandeau", supports_color: true, supports_brightness: true, supports_transition: false }],
  switches: [],
  rest_state: {},
};
let current: typeof devices;

beforeEach(() => {
  localStorage.clear();
  FakeWebSocket.instances = [];
  current = structuredClone(devices);
  window.history.replaceState(null, "", "/composants");
  stubEngine(({ path }) => {
    if (path === "/api/status") return STATUS;
    if (path === "/api/devices") return current;
  });
  setToken("secret");
});
afterEach(() => vi.unstubAllGlobals());

async function open() {
  render(<App WebSocketImpl={WS} />);
  await screen.findByText("Fantôme");
}

test("affiche les relais existants avec leur résumé", async () => {
  await open();
  const card = screen.getByLabelText("Fantôme");
  expect(within(card).getByText("GPIO 18")).toBeInTheDocument();
  expect(within(card).getByText("maintenu")).toBeInTheDocument();
  expect(within(screen.getByLabelText("Éclair")).getByText("impulsion")).toBeInTheDocument();
  // image téléversée : <img> ; icône intégrée : pas d'image
  expect(screen.getByLabelText("Éclair").querySelector("img")).toHaveAttribute("src", "/api/images/a.png");
  expect(screen.getByLabelText("Fantôme").querySelector("img")).toBeNull();
});

test("les onglets montrent chaque type avec son effectif", async () => {
  await open();
  const user = userEvent.setup();
  expect(screen.getByRole("tab", { name: /Relais/ })).toHaveTextContent("2");
  expect(screen.getByRole("tab", { name: /Interrupteurs/ })).toHaveTextContent("0");
  await user.click(screen.getByRole("tab", { name: /Lumières/ }));
  const card = screen.getByLabelText("Bandeau");
  expect(within(card).getByText("light.bandeau")).toBeInTheDocument();
  expect(within(card).getByText("couleur, luminosité")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Ajouter une lumière" })).toBeInTheDocument();
  await user.click(screen.getByRole("tab", { name: /Interrupteurs/ }));
  expect(screen.getByText("Aucun interrupteur Home Assistant.")).toBeInTheDocument();
  expect(window.location.search).toBe("?type=switches");
});

test("l'onglet demandé dans l'adresse est ouvert, un onglet inconnu retombe sur les relais", async () => {
  window.history.replaceState(null, "", "/composants?type=buttons");
  render(<App WebSocketImpl={WS} />);
  expect(await screen.findByText("Bouton principal")).toBeInTheDocument();
  expect(screen.getByRole("tab", { name: /Boutons/ })).toHaveAttribute("aria-selected", "true");
});

test("le catalogue est relu quand le moteur annonce un changement", async () => {
  await open();
  current.relays.push({ id: "orage", name: "Orage", pin: 27, mode: "latched", active_low: false, image: "builtin:storm", image_url: null } as never);
  act(() => FakeWebSocket.emit({ type: "component_changed", kind: "catalog", component_id: null, state: null, details: {} }));
  await waitFor(() => expect(screen.getByLabelText("Orage")).toBeInTheDocument());
});

test("un simple changement d'état de relais ne relit pas le catalogue", async () => {
  const calls = stubEngine(({ path }) => {
    if (path === "/api/status") return STATUS;
    if (path === "/api/devices") return current;
  });
  await open();
  const before = calls.filter((c) => c.path === "/api/devices").length;
  act(() => FakeWebSocket.emit({ type: "component_changed", kind: "relay", component_id: "fantome", state: "on", details: {} }));
  await screen.findByText("Fantôme");
  expect(calls.filter((c) => c.path === "/api/devices").length).toBe(before);
});
