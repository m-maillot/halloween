import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { App } from "./App";
import { setToken } from "./api/token";

class FakeWebSocket {
  static instances: FakeWebSocket[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((m: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  constructor(public url: string) {
    FakeWebSocket.instances.push(this);
  }
  close() {
    this.onclose?.();
  }
}
const WS = FakeWebSocket as unknown as typeof WebSocket;
const lastSocket = () => FakeWebSocket.instances.at(-1)!;

const baseStatus = {
  version: "0.1.0",
  programs: 3,
  runs: [] as object[],
  lock: { locked: false, has_code: false },
  home_assistant: { mode: "real", last_ok_at: 1, last_error: null as string | null },
};
let status: typeof baseStatus;
let calls: { method: string; path: string; auth: string | null }[];
let down: boolean;

beforeEach(() => {
  localStorage.clear();
  setToken(null);
  FakeWebSocket.instances = [];
  status = structuredClone(baseStatus);
  calls = [];
  down = false;
  window.history.replaceState(null, "", "/");
  vi.stubGlobal(
    "fetch",
    vi.fn(async (req: Request) => {
      const path = new URL(req.url).pathname;
      calls.push({ method: req.method, path, auth: req.headers.get("Authorization") });
      if (down) throw new TypeError("fetch failed");
      if (path === "/api/status") return Response.json(status);
      if (path.endsWith("/stop")) return Response.json({ stopped: 1 });
      return Response.json({}, { status: 404 });
    }),
  );
});
afterEach(() => vi.unstubAllGlobals());

async function connect() {
  setToken("secret");
  render(<App WebSocketImpl={WS} />);
  await screen.findByText("Moteur connecté");
}

test("sans jeton : saisie, aucun appel", () => {
  render(<App WebSocketImpl={WS} />);
  expect(screen.getByLabelText("Jeton du moteur")).toBeInTheDocument();
  expect(calls).toHaveLength(0);
});

test("la saisie du jeton ouvre l'interface avec /api/status et le WebSocket authentifié", async () => {
  render(<App WebSocketImpl={WS} />);
  await userEvent.type(screen.getByLabelText("Jeton du moteur"), "secret");
  await userEvent.click(screen.getByRole("button", { name: "Se connecter" }));
  await screen.findByText("Moteur connecté");
  expect(calls.find((c) => c.path === "/api/status")).toMatchObject({ auth: "Bearer secret" });
  expect(lastSocket().url).toMatch(/\/api\/events\?token=secret$/);
});

test("la navigation propose les six entrées", async () => {
  await connect();
  const nav = screen.getByRole("navigation", { name: "Navigation" });
  for (const name of ["Mode spectacle", "Tableau de bord", "Scénarios", "Déclencheurs", "Composants", "Réglages"]) {
    expect(within(nav).getByRole("link", { name })).toBeInTheDocument();
  }
});

test("le bandeau montre Home Assistant, le verrou et les scénarios en cours", async () => {
  status.runs = [{ run_id: "r1", program_id: "scene" }, { run_id: "r2", program_id: "ambiance" }];
  status.lock.locked = true;
  await connect();
  expect(screen.getByText("Home Assistant connecté")).toBeInTheDocument();
  expect(screen.getByText("Verrouillé")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "2 scénarios en cours" })).toBeInTheDocument();
});

test("Home Assistant en erreur ou simulé est signalé", async () => {
  status.home_assistant = { mode: "real", last_ok_at: 1, last_error: "connexion refusée" };
  await connect();
  expect(screen.getByText("Home Assistant injoignable")).toBeInTheDocument();
});

test("STOP appelle l'arrêt global, même verrouillé", async () => {
  status.lock.locked = true;
  await connect();
  await userEvent.click(screen.getByRole("button", { name: "Arrêt d'urgence : tout arrêter" }));
  expect(calls.some((c) => c.method === "POST" && c.path === "/api/runs/stop")).toBe(true);
});

test("la liste des runs permet d'arrêter un scénario seul", async () => {
  status.runs = [{ run_id: "r1", program_id: "ambiance" }];
  await connect();
  await userEvent.click(screen.getByRole("button", { name: "1 scénario en cours" }));
  await userEvent.click(screen.getByRole("button", { name: "Arrêter ambiance" }));
  expect(calls.some((c) => c.path === "/api/runs/r1/stop")).toBe(true);
});

test("un événement du moteur met le bandeau à jour sans recharger", async () => {
  await connect();
  expect(screen.getByRole("button", { name: "Aucun scénario en cours" })).toBeInTheDocument();
  status.runs = [{ run_id: "r1", program_id: "scene" }];
  act(() => lastSocket().onmessage?.({ data: JSON.stringify({ type: "run_started", run_id: "r1" }) }));
  await screen.findByRole("button", { name: "1 scénario en cours" });
  status.lock.locked = true;
  act(() => lastSocket().onmessage?.({ data: JSON.stringify({ type: "lock_changed", locked: true }) }));
  await screen.findByText("Verrouillé");
});

test("la perte du WebSocket est signalée, puis résorbée à la reconnexion avec resynchronisation", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  try {
    await connect();
    down = true;
    act(() => lastSocket().onclose?.());
    await screen.findByText("Moteur déconnecté");
    // Pendant la coupure, l'état a changé côté moteur.
    down = false;
    status.runs = [{ run_id: "r9", program_id: "scene" }];
    await act(async () => {
      await vi.advanceTimersByTimeAsync(600); // premier délai de reconnexion
    });
    act(() => lastSocket().onopen?.());
    await screen.findByText("Moteur connecté");
    await screen.findByRole("button", { name: "1 scénario en cours" });
  } finally {
    vi.useRealTimers();
  }
});

test("un jeton refusé ramène à la saisie", async () => {
  setToken("mauvais");
  vi.stubGlobal("fetch", vi.fn(async () => Response.json({}, { status: 401 })));
  render(<App WebSocketImpl={WS} />);
  await waitFor(() => expect(screen.getByLabelText("Jeton du moteur")).toBeInTheDocument());
  expect(localStorage.getItem("halloween.token")).toBeNull();
});

test("un événement arrivé pendant une relecture en cours déclenche une nouvelle relecture", async () => {
  await connect();
  const before = calls.filter((c) => c.path === "/api/status").length;
  status.runs = [{ run_id: "r1", program_id: "scene" }];
  // Deux événements coup sur coup : la seconde relecture ne doit pas être perdue.
  act(() => {
    lastSocket().onmessage?.({ data: JSON.stringify({ type: "run_started", run_id: "r1" }) });
    lastSocket().onmessage?.({ data: JSON.stringify({ type: "run_ended", run_id: "r0" }) });
  });
  await screen.findByRole("button", { name: "1 scénario en cours" });
  expect(calls.filter((c) => c.path === "/api/status").length).toBeGreaterThanOrEqual(before + 2);
});

test("moteur injoignable : écran dédié, navigation inerte, STOP désactivé, puis reprise avec Réessayer", async () => {
  await connect();
  down = true;
  act(() => lastSocket().onclose?.());
  await screen.findByRole("heading", { name: "Moteur injoignable" });
  expect(screen.getByRole("navigation", { name: "Navigation" })).toHaveAttribute("inert");
  expect(screen.getByRole("button", { name: "Arrêt d'urgence : tout arrêter" })).toBeDisabled();

  down = false;
  await userEvent.click(screen.getByRole("button", { name: "Réessayer" }));
  await screen.findByText("Moteur connecté");
  expect(screen.queryByRole("heading", { name: "Moteur injoignable" })).toBeNull();
  expect(screen.getByRole("button", { name: "Arrêt d'urgence : tout arrêter" })).toBeEnabled();
});

test("un échec de STOP affiche une notification lisible avec détails dépliables", async () => {
  await connect();
  (fetch as ReturnType<typeof vi.fn>).mockImplementation(async (req: Request) => {
    const path = new URL(req.url).pathname;
    if (path === "/api/runs/stop")
      return Response.json(
        { detail: { message: "le périphérique ne répond pas", issues: [{ message: "relais fantome bloqué", component_id: "fantome" }] } },
        { status: 502 },
      );
    return Response.json(status);
  });
  await userEvent.click(screen.getByRole("button", { name: "Arrêt d'urgence : tout arrêter" }));
  const toast = await screen.findByRole("alert");
  expect(toast).toHaveTextContent("le périphérique ne répond pas");
  await userEvent.click(within(toast).getByText(/Détails \(1\)/));
  expect(within(toast).getByText("composant fantome : relais fantome bloqué")).toBeVisible();
  await userEvent.click(within(toast).getByRole("button", { name: "Fermer la notification" }));
  expect(screen.queryByRole("alert")).toBeNull();
});

test("la même erreur répétée n'empile pas les notifications", async () => {
  await connect();
  (fetch as ReturnType<typeof vi.fn>).mockImplementation(async (req: Request) =>
    new URL(req.url).pathname === "/api/runs/stop"
      ? Response.json({ detail: "non" }, { status: 500 })
      : Response.json(status),
  );
  const stop = screen.getByRole("button", { name: "Arrêt d'urgence : tout arrêter" });
  await userEvent.click(stop);
  await userEvent.click(stop);
  await screen.findAllByRole("alert");
  expect(screen.getAllByRole("alert")).toHaveLength(1);
});
