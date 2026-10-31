import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { App } from "../App";
import { setToken } from "../api/token";
import { FakeWebSocket, STATUS, stubEngine, WS, type Call } from "../test-engine";

type Json = Record<string, unknown>;
const NOW_MS = 2_000_000_000_000; // heure locale figée de la tablette
let status: typeof STATUS & Json;
let devices: Json;
let programs: Json[];
let entities: Json[];
let calls: Call[];
let respond: (call: Call) => Response | object | undefined;

beforeEach(() => {
  localStorage.clear();
  FakeWebSocket.instances = [];
  vi.spyOn(Date, "now").mockReturnValue(NOW_MS);
  status = { ...structuredClone(STATUS), relays: { orage: false, fumee: false } };
  devices = {
    relays: [
      { id: "orage", name: "Orage", pin: 22, mode: "latched", active_low: false, image: null, image_url: null },
      { id: "fumee", name: "Fumée", pin: 5, mode: "push", pulse_ms: 500, active_low: false, image: null, image_url: null },
    ],
    buttons: [{ id: "bp", name: "Bouton principal", pin: 21, pull: "up", debounce_ms: 50, long_press_ms: 800, double_press_ms: 400 }],
    lights: [{ id: "bandeau", name: "Bandeau", entity_id: "light.bandeau", supports_color: true, supports_brightness: true, supports_transition: false }],
    switches: [{ id: "guirlande", name: "Guirlande", entity_id: "switch.guirlande" }], players: [],
    rest_state: {},
  };
  programs = [
    { id: "scene", name: "Scène du soir", revision: 1, show: true, scripts: 1, valid: true, max_duration_s: 60, running: false },
    { id: "boucle", name: "Ambiance", revision: 1, show: false, scripts: 1, valid: true, max_duration_s: null, running: false },
    { id: "casse", name: "Cassé", revision: 1, show: false, scripts: 1, valid: false, max_duration_s: null, running: false },
  ];
  entities = [
    { entity_id: "light.bandeau", name: "Bandeau", state: "on", domain: "light", capabilities: null },
    { entity_id: "switch.guirlande", name: "Guirlande", state: "off", domain: "switch", capabilities: null },
  ];
  respond = () => undefined;
  window.history.replaceState(null, "", "/");
  calls = stubEngine((call) => {
    const custom = respond(call);
    if (custom !== undefined) return custom;
    const { path, method, search } = call;
    if (path === "/api/status") return status;
    if (path === "/api/devices") return devices;
    if (path === "/api/programs") return programs;
    if (path === "/api/ha/entities") return entities.filter((e) => search.includes(`domain=${e.domain}`));
    if (method === "POST") return { ok: true, message: "ok" };
  });
  setToken("secret");
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

async function openApp() {
  render(<App WebSocketImpl={WS} />);
  await screen.findByText("Orage");
  await screen.findAllByRole("button", { name: "Lancer" }); // programmes chargés
  return userEvent.setup();
}

const tile = (name: string) => screen.getByLabelText(name);

test("les tuiles reflètent l'état réel : relais du moteur, lumières et interrupteurs de Home Assistant", async () => {
  status.relays.orage = true;
  await openApp();
  expect(within(tile("Orage")).getByText("Allumé")).toBeInTheDocument();
  await waitFor(() => expect(within(tile("Bandeau")).getByText("Allumé")).toBeInTheDocument());
  expect(within(tile("Guirlande")).getByText("Éteint")).toBeInTheDocument();
  expect(within(tile("Fumée")).queryByText(/Allumé|Éteint/)).toBeNull(); // impulsion : pas d'état durable
});

test("l'état suit les événements en temps réel", async () => {
  await openApp();
  await waitFor(() => expect(within(tile("Guirlande")).getByText("Éteint")).toBeInTheDocument());
  act(() => FakeWebSocket.emit({ type: "component_changed", kind: "switch", component_id: "guirlande", state: "on", details: {} }));
  expect(within(tile("Guirlande")).getByText("Allumé")).toBeInTheDocument();
  expect(within(tile("Guirlande")).getByRole("button", { name: "Éteindre" })).toBeInTheDocument();
  act(() =>
    FakeWebSocket.emit({ type: "component_changed", kind: "light", component_id: "bandeau", state: "off", details: {} }),
  );
  expect(within(tile("Bandeau")).getByText("Éteint")).toBeInTheDocument();
  // un relais : l'état agrégé est relu après l'événement
  status.relays.orage = true;
  act(() => FakeWebSocket.emit({ type: "component_changed", kind: "relay", component_id: "orage", state: "on", details: {} }));
  await waitFor(() => expect(within(tile("Orage")).getByText("Allumé")).toBeInTheDocument());
});

test("sans réponse de Home Assistant, l'état d'une lumière reste « inconnu »", async () => {
  respond = ({ path }) => (path === "/api/ha/entities" ? Response.json({ detail: "ko" }, { status: 502 }) : undefined);
  await openApp();
  await waitFor(() => expect(within(tile("Bandeau")).getByText("État inconnu")).toBeInTheDocument());
});

test("l'interrupteur de test commande le composant", async () => {
  const user = await openApp();
  await user.click(within(tile("Orage")).getByRole("button", { name: "Allumer" }));
  await user.click(within(tile("Fumée")).getByRole("button", { name: "Déclencher" }));
  const sent = calls.filter((c) => c.path.endsWith("/test")).map((c) => [c.path, (c.body as Json).action]);
  expect(sent).toEqual([
    ["/api/components/relays/orage/test", "on"],
    ["/api/components/relays/fumee/test", "trigger"],
  ]);
});

test("une lumière à capacités ouvre ses réglages (couleur, luminosité)", async () => {
  const user = await openApp();
  await user.click(within(tile("Bandeau")).getByRole("button", { name: "Réglages…" }));
  const dialog = screen.getByRole("dialog", { name: "Réglages de Bandeau" });
  await user.click(within(dialog).getByRole("button", { name: "Allumer" }));
  const test = calls.find((c) => c.path === "/api/components/lights/bandeau/test")!;
  expect(test.body).toMatchObject({ action: "on", rgb_color: [255, 138, 43], brightness: 255 });
  expect(within(tile("Orage")).queryByRole("button", { name: "Réglages…" })).toBeNull();
});

test("un scénario en cours montre sa progression d'après l'heure du moteur, pas celle de la tablette", async () => {
  // le moteur est 10 000 s en avance sur la tablette : seule l'heure du moteur compte
  const engineNow = NOW_MS / 1000 + 10_000;
  status.started_at = engineNow - 100;
  (status as Json).uptime_s = 100;
  status.runs = [{ run_id: "r1", program_id: "scene", state: "running", started_at: engineNow - 20 }];
  await openApp();
  const runs = screen.getByRole("list", { name: "Scénarios en cours" });
  expect(within(runs).getByText("Scène du soir")).toBeInTheDocument();
  expect(within(runs).getByText("20 s / 60 s")).toBeInTheDocument();
  expect(within(runs).getByRole("progressbar")).toHaveAttribute("aria-valuenow", "33");
});

test("la progression avance avec le temps sans nouvel événement", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true, now: NOW_MS });
  const engineNow = NOW_MS / 1000;
  status.started_at = engineNow - 100;
  (status as Json).uptime_s = 100;
  status.runs = [{ run_id: "r1", program_id: "scene", state: "running", started_at: engineNow - 20 }];
  await openApp();
  expect(await screen.findByText("20 s / 60 s")).toBeInTheDocument();
  await act(async () => {
    await vi.advanceTimersByTimeAsync(10_000);
  });
  expect(screen.getByText("30 s / 60 s")).toBeInTheDocument();
  vi.useRealTimers();
});

test("un scénario sans limite se dit « en continu » ; la file d'attente est signalée", async () => {
  const engineNow = NOW_MS / 1000;
  status.started_at = engineNow - 100;
  (status as Json).uptime_s = 100;
  status.runs = [
    { run_id: "r1", program_id: "boucle", state: "running", started_at: engineNow - 7 },
    { run_id: "r2", program_id: "scene", state: "queued", started_at: null },
  ];
  await openApp();
  const runs = screen.getByRole("list", { name: "Scénarios en cours" });
  expect(within(runs).getByText("7 s · en continu")).toBeInTheDocument();
  expect(within(runs).getByText("En file d'attente")).toBeInTheDocument();
});

test("chaque scénario en cours s'arrête individuellement", async () => {
  status.runs = [
    { run_id: "r1", program_id: "boucle", state: "running", started_at: 1 },
    { run_id: "r2", program_id: "scene", state: "running", started_at: 1 },
  ];
  const user = await openApp();
  const runs = screen.getByRole("list", { name: "Scénarios en cours" });
  await user.click(within(within(runs).getAllByRole("listitem")[1]).getByRole("button", { name: "Arrêter" }));
  expect(calls.filter((c) => c.path.endsWith("/stop")).map((c) => c.path)).toEqual(["/api/runs/r2/stop"]);
});

test("Lancer démarre le scénario ; un scénario invalide ne se lance pas", async () => {
  const user = await openApp();
  await user.click(within(tile("Scène du soir")).getByRole("button", { name: "Lancer" }));
  expect(calls.find((c) => c.method === "POST" && c.path === "/api/runs")!.body).toEqual({
    program_id: "scene",
    policy: "ignore",
  });
  expect(within(tile("Cassé")).getByRole("button", { name: "Lancer" })).toBeDisabled();
});

test("verrouillé : le code est demandé pour lancer, les tests manuels sont désactivés", async () => {
  status.lock = { locked: true, has_code: true } as never;
  respond = ({ method, path, body }) =>
    method === "POST" && path === "/api/runs"
      ? (body as Json).code === "1234"
        ? Response.json({ run_id: "r9", program_id: "scene", state: "running" }, { status: 201 })
        : Response.json({ detail: { message: "code incorrect", issues: [] } }, { status: 401 })
      : undefined;
  const user = await openApp();
  expect(within(tile("Orage")).getByRole("button", { name: "Allumer" })).toBeDisabled();
  await user.click(within(tile("Scène du soir")).getByRole("button", { name: "Lancer" }));
  expect(calls.some((c) => c.path === "/api/runs")).toBe(false); // pas d'appel sans code
  const dialog = screen.getByRole("dialog", { name: /Code pour lancer/ });
  await user.type(within(dialog).getByLabelText("Code"), "9999");
  await user.click(within(dialog).getByRole("button", { name: "Valider" }));
  expect(await within(dialog).findByText("code incorrect")).toBeInTheDocument();
  await user.type(within(dialog).getByLabelText("Code"), "1234");
  await user.click(within(dialog).getByRole("button", { name: "Valider" }));
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  expect(calls.filter((c) => c.path === "/api/runs").map((c) => (c.body as Json).code)).toEqual(["9999", "1234"]);
});

test("les appuis de boutons physiques s'affichent, le plus récent en premier", async () => {
  await openApp();
  expect(screen.getByText(/Aucun appui reçu/)).toBeInTheDocument();
  act(() => FakeWebSocket.emit({ type: "button_event", button_id: "bp", event: "short" }));
  act(() => FakeWebSocket.emit({ type: "button_event", button_id: "bp", event: "double" }));
  const items = screen.getAllByText(/Bouton principal : appui/);
  expect(items[0]).toHaveTextContent("appui double");
  expect(items[1]).toHaveTextContent("appui court");
});

test("un changement de scénarios en cours relit la liste des programmes", async () => {
  await openApp();
  const before = calls.filter((c) => c.path === "/api/programs").length;
  programs.push({ id: "neuf", name: "Nouveau", revision: 1, show: false, scripts: 1, valid: true, max_duration_s: null, running: false });
  act(() => FakeWebSocket.emit({ type: "run_ended", run_id: "x", program_id: "scene", outcome: "completed" }));
  await waitFor(() => expect(screen.getByLabelText("Nouveau")).toBeInTheDocument());
  expect(calls.filter((c) => c.path === "/api/programs").length).toBeGreaterThan(before);
});

test("un lecteur vidéo : « Écran noir » en un clic, « Vidéos… » ouvre le choix de la vidéo", async () => {
  (devices.players as Json[]).push({
    id: "retro",
    name: "Rétroprojecteur",
    image: null,
    image_url: null,
    script: "script.lire_video_shield",
    rest_video: "noir",
    videos: [
      { id: "noir", name: "Écran noir", source: "black_screen.mp4", duration_s: 10 },
      { id: "fete", name: "Fête", source: "halloween_video.mp4", duration_s: 21 },
    ],
  });
  const user = await openApp();
  expect(within(tile("Rétroprojecteur")).queryByText(/Allumé|Éteint|État inconnu/)).toBeNull();
  await user.click(within(tile("Rétroprojecteur")).getByRole("button", { name: "Écran noir" }));
  await user.click(within(tile("Rétroprojecteur")).getByRole("button", { name: "Vidéos…" }));
  const dialog = screen.getByRole("dialog", { name: "Réglages de Rétroprojecteur" });
  await user.selectOptions(within(dialog).getByLabelText("Vidéo"), "Fête");
  await user.click(within(dialog).getByRole("button", { name: "Jouer" }));
  const sent = calls.filter((c) => c.path === "/api/components/players/retro/test").map((c) => (c.body as Json).action);
  expect(sent).toEqual(["rest", "play"]);
});
