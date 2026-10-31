import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { App } from "../App";
import { setToken } from "../api/token";
import { FakeWebSocket, STATUS, stubEngine, WS, type Call } from "../test-engine";
import { Keypad } from "./Keypad";

type Json = Record<string, unknown>;
let calls: Call[];
let status: typeof STATUS & Json;
let respond: (call: Call) => Response | object | undefined;

const devices = { relays: [], buttons: [], lights: [], switches: [], players: [], rest_state: {} };

beforeEach(() => {
  localStorage.clear();
  FakeWebSocket.instances = [];
  status = structuredClone(STATUS);
  respond = () => undefined;
  window.history.replaceState(null, "", "/composants");
  calls = stubEngine((call) => {
    const custom = respond(call);
    if (custom !== undefined) return custom;
    const { path, method } = call;
    if (path === "/api/status") return status;
    if (path === "/api/devices") return devices;
    if (path === "/api/programs") return [];
    if (method === "POST" && path === "/api/lock") {
      status.lock = { locked: true, has_code: true } as never;
      return status.lock;
    }
    if (method === "POST" && path === "/api/runs/stop") return { stopped: 0 };
  });
  setToken("secret");
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

const cadenas = () => screen.getByRole("button", { name: /verrouill/i });
async function open() {
  render(<App WebSocketImpl={WS} />);
  await screen.findByText("Moteur connecté");
  return userEvent.setup();
}
const posts = (path: string) => calls.filter((c) => c.method === "POST" && c.path === path);

// ------------------------------------------------------------------ pavé numérique

function Harness({ max }: { max?: number }) {
  const [value, setValue] = useState("");
  return (
    <>
      <Keypad value={value} onChange={setValue} max={max} />
      <output aria-label="valeur">{value}</output>
    </>
  );
}

test("le pavé numérique saisit, efface et plafonne la longueur", async () => {
  const user = userEvent.setup();
  render(<Harness max={4} />);
  const pad = screen.getByRole("group", { name: "Pavé numérique" });
  for (const digit of ["1", "2", "3", "4", "5"]) await user.click(within(pad).getByRole("button", { name: digit }));
  expect(screen.getByLabelText("valeur")).toHaveTextContent("1234"); // le 5e chiffre est refusé
  await user.click(within(pad).getByRole("button", { name: "Effacer le dernier chiffre" }));
  expect(screen.getByLabelText("valeur")).toHaveTextContent("123");
  expect(within(pad).getByRole("button", { name: "0" })).toBeInTheDocument();
});

test("le clavier physique marche aussi et ne garde que les chiffres", async () => {
  const user = userEvent.setup();
  render(<Harness />);
  await user.type(screen.getByLabelText("Code"), "12ab34-5");
  expect(screen.getByLabelText("valeur")).toHaveTextContent("12345");
  expect(screen.getByLabelText("Code")).toHaveAttribute("type", "password"); // le code ne s'affiche pas
});

// ------------------------------------------------------------------ cadenas

test("déverrouillé avec un code défini : un clic verrouille, sans demander le code", async () => {
  status.lock = { locked: false, has_code: true } as never;
  const user = await open();
  await user.click(cadenas());
  await waitFor(() => expect(posts("/api/lock")).toHaveLength(1));
  expect(posts("/api/lock")[0].body).toBeUndefined();
  expect(await screen.findByRole("button", { name: /Verrouillé : saisir le code/ })).toBeInTheDocument();
});

test("sans code défini, le moteur refuse (409) et le cadenas dit où en définir un", async () => {
  respond = ({ method, path }) =>
    method === "POST" && path === "/api/lock" ? Response.json({ detail: { message: "aucun code défini", issues: [] } }, { status: 409 }) : undefined;
  const user = await open();
  await user.click(cadenas());
  expect(await screen.findByText(/Définissez d'abord un code dans Réglages/)).toBeInTheDocument();
  expect(screen.queryByText("aucun code défini")).toBeNull(); // message du moteur remplacé par un conseil
});

test("verrouillé : le code est demandé ; faux code refusé, bon code déverrouille", async () => {
  status.lock = { locked: true, has_code: true } as never;
  respond = ({ method, path, body }) => {
    if (method === "POST" && path === "/api/unlock") {
      if ((body as { code: string }).code === "1234") {
        status.lock = { locked: false, has_code: true } as never;
        return status.lock;
      }
      return Response.json({ detail: { message: "code incorrect", issues: [] } }, { status: 401 });
    }
  };
  const user = await open();
  await user.click(cadenas());
  const dialog = screen.getByRole("dialog", { name: "Déverrouiller l'interface" });
  const pad = within(dialog).getByRole("group", { name: "Pavé numérique" });
  for (const d of "9999") await user.click(within(pad).getByRole("button", { name: d }));
  await user.click(within(dialog).getByRole("button", { name: "Valider" }));
  expect(await within(dialog).findByText("code incorrect")).toBeInTheDocument();
  expect(screen.queryByLabelText("Jeton du moteur")).toBeNull(); // un faux code n'efface pas le jeton
  for (const d of "1234") await user.click(within(pad).getByRole("button", { name: d }));
  await user.click(within(dialog).getByRole("button", { name: "Valider" }));
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  expect(posts("/api/unlock").map((c) => (c.body as { code: string }).code)).toEqual(["9999", "1234"]);
  expect(await screen.findByRole("button", { name: /Déverrouillé : verrouiller/ })).toBeInTheDocument();
});

test("trop d'essais : le délai imposé s'affiche, décompte, et réactive Valider à la fin", async () => {
  status.lock = { locked: true, has_code: true } as never;
  respond = ({ method, path }) =>
    method === "POST" && path === "/api/unlock"
      ? Response.json({ detail: { message: "trop d'essais.", issues: [], retry_after_s: 3 } }, { status: 429 })
      : undefined;
  const user = await open();
  await user.click(cadenas());
  const dialog = screen.getByRole("dialog");
  await user.type(within(dialog).getByLabelText("Code"), "1234");
  vi.useFakeTimers({ shouldAdvanceTime: true });
  await user.click(within(dialog).getByRole("button", { name: "Valider" }));
  expect(await within(dialog).findByText("Trop d'essais : réessayez dans 3 s.")).toBeInTheDocument();
  await act(async () => {
    await vi.advanceTimersByTimeAsync(1000);
  });
  expect(within(dialog).getByText("Trop d'essais : réessayez dans 2 s.")).toBeInTheDocument();
  vi.useRealTimers();
  const typed = userEvent.setup();
  await typed.type(within(dialog).getByLabelText("Code"), "1234");
  expect(within(dialog).getByRole("button", { name: "Valider" })).toBeDisabled(); // délai en cours
});

test("un délai déjà imposé par le moteur à l'ouverture est repris", async () => {
  status.lock = { locked: true, has_code: true } as never;
  // le délai n'est pas dans l'état affiché (aucun événement ne l'annonce) : il est relu à l'ouverture
  respond = ({ method, path }) => (method === "GET" && path === "/api/lock" ? { locked: true, has_code: true, retry_after_s: 25 } : undefined);
  const user = await open();
  await user.click(cadenas());
  expect(within(screen.getByRole("dialog")).getByText("Trop d'essais : réessayez dans 25 s.")).toBeInTheDocument();
});

// ------------------------------------------------------------------ STOP libre, lecture seule, temps réel

test("verrouillé : STOP arrête tout sans demander de code", async () => {
  status.lock = { locked: true, has_code: true } as never;
  const user = await open();
  await user.click(screen.getByRole("button", { name: "Arrêt d'urgence : tout arrêter" }));
  await waitFor(() => expect(posts("/api/runs/stop")).toHaveLength(1));
  expect(posts("/api/runs/stop")[0].body).toBeUndefined();
  expect(screen.queryByRole("dialog")).toBeNull();
});

test("le verrouillage décidé ailleurs (lock_changed) rend l'écran en lecture seule aussitôt", async () => {
  await open();
  await screen.findByRole("button", { name: "Ajouter un relais" });
  expect(screen.getByRole("button", { name: "Ajouter un relais" })).toBeEnabled();
  status.lock = { locked: true, has_code: true } as never;
  act(() => FakeWebSocket.emit({ type: "lock_changed", locked: true, ts: 1 }));
  await waitFor(() => expect(screen.getByRole("button", { name: "Ajouter un relais" })).toBeDisabled());
  expect(screen.getByRole("button", { name: /Verrouillé/ })).toBeInTheDocument();
  status.lock = { locked: false, has_code: true } as never;
  act(() => FakeWebSocket.emit({ type: "lock_changed", locked: false, ts: 2 }));
  await waitFor(() => expect(screen.getByRole("button", { name: "Ajouter un relais" })).toBeEnabled());
});

test("verrouillé : la liste des scénarios ne permet pas d'en créer", async () => {
  status.lock = { locked: true, has_code: true } as never;
  window.history.replaceState(null, "", "/scenarios");
  await open();
  expect(await screen.findByRole("button", { name: "Nouveau scénario" })).toBeDisabled();
});

test("verrouillé : un composant s'ouvre en consultation, sans pouvoir l'enregistrer ni le supprimer", async () => {
  status.lock = { locked: true, has_code: true } as never;
  respond = ({ path }) =>
    path === "/api/devices"
      ? { ...devices, relays: [{ id: "orage", name: "Orage", pin: 22, mode: "latched", active_low: false, image: null, image_url: null }] }
      : undefined;
  const user = await open();
  await user.click(await screen.findByLabelText("Orage"));
  const dialog = screen.getByRole("dialog");
  expect(within(dialog).getByText("Interface verrouillée : lecture seule.")).toBeInTheDocument();
  expect(within(dialog).getByRole("button", { name: "Enregistrer" })).toBeDisabled();
  expect(within(dialog).getByRole("button", { name: "Supprimer" })).toBeDisabled();
  expect(within(dialog).getByRole("button", { name: "Allumer" })).toBeDisabled();
});
