import * as Blockly from "blockly/core";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { App } from "../App";
import { setToken } from "../api/token";
import { FakeWebSocket, STATUS, stubEngine, WS, type Call } from "../test-engine";

// Blockly a besoin d'un vrai navigateur pour s'afficher : on branche un espace de travail sans affichage,
// qui émet les mêmes événements de modification.
const shared = vi.hoisted(() => ({ ws: null as unknown, readOnly: false }));
vi.mock("./BlocklyEditor", async () => {
  const React = await import("react");
  const { registerBlocks } = await import("./blocks");
  const { setCatalog } = await import("./catalog");
  return {
    BlocklyEditor: ({ devices, onReady, onChange, readOnly }: { devices: never; onReady: (ws: unknown) => void; onChange?: (e: unknown) => void; readOnly?: boolean }) => {
      shared.readOnly = Boolean(readOnly);
      React.useEffect(() => {
        registerBlocks();
        setCatalog(devices);
        const ws = new Blockly.Workspace();
        shared.ws = ws;
        ws.addChangeListener((event) => !event.isUiEvent && onChange?.(event));
        return onReady(ws) as unknown as () => void;
      }, []);
      return null;
    },
  };
});

const ws = () => shared.ws as Blockly.Workspace;
const devices = {
  relays: [{ id: "orage", name: "Orage", pin: 22, mode: "latched", active_low: false }],
  buttons: [], lights: [], switches: [], rest_state: {},
};
const relay = (id: string, state: string) => ({ id, type: "relay", target: "orage", state });
const program = (children: object[], extra: object = {}) => ({
  schema: 1, id: "scene", name: "Scène", revision: 3, max_duration_s: null, on_end: "reset", show: false, show_order: null, editor: null,
  scripts: [{ id: "s1", hat: { type: "start" }, root: { id: "r", type: "sequence", children } }], ...extra,
});

let calls: Call[];
let report: () => Response | object;

beforeEach(() => {
  localStorage.clear();
  FakeWebSocket.instances = [];
  report = () => ({ valid: true, issues: [] });
  window.history.replaceState(null, "", "/scenarios/scene");
  calls = stubEngine(({ path, method }) => {
    if (path === "/api/status") return STATUS;
    if (path === "/api/devices") return devices;
    if (path === "/api/programs" && method === "GET") return [];
    if (path === "/api/programs/scene" && method === "GET") return program([relay("a", "on"), relay("b", "off")]);
    if (path === "/api/programs/validate") return report();
    if (path === "/api/programs/scene" && method === "PUT") return { program: program([]), warnings: [] };
  });
  setToken("secret");
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

const validations = () => calls.filter((c) => c.path === "/api/programs/validate");
async function open() {
  render(<App WebSocketImpl={WS} />);
  await screen.findByRole("heading", { name: "Validation" });
  await waitFor(() => expect(validations().length).toBe(1)); // première validation sans attendre
}
const panel = () => screen.getByRole("complementary", { name: "Validation" });
const save = () => screen.getByRole("button", { name: "Enregistrer" });

test("le programme chargé est validé aussitôt, sans attendre 500 ms", async () => {
  await open();
  const body = validations()[0].body as { id: string; scripts: { id: string }[] };
  expect(body.id).toBe("scene");
  expect(body.scripts[0].id).toBe("s1");
  expect(await within(panel()).findByText("Scénario valide")).toBeInTheDocument();
});

test("une erreur du moteur est posée sur le bon bloc et bloque l'enregistrement", async () => {
  report = () => ({ valid: false, issues: [{ severity: "error", code: "unknown_component", message: "relais inconnu : orage", node_id: "b", component_id: "orage" }] });
  await open();
  const item = await within(panel()).findByRole("button", { name: /relais inconnu : orage/ });
  expect(item).toBeEnabled(); // le bloc « b » a été retrouvé
  expect(within(panel()).getByText("1 erreur")).toBeInTheDocument();
  expect(save()).toBeDisabled();
  expect(screen.getByRole("button", { name: "Lancer" })).toBeDisabled(); // un scénario invalide ne se lance pas
});

test("l'erreur d'une pile implicite est rattachée à son bloc propriétaire", async () => {
  report = () => ({ valid: false, issues: [{ severity: "error", code: "x", message: "séquence vide", node_id: "s1_root" }] });
  await open();
  expect(await within(panel()).findByRole("button", { name: /séquence vide/ })).toBeEnabled();
});

test("une erreur sans bloc identifiable reste listée, sans lien", async () => {
  report = () => ({ valid: false, issues: [{ severity: "error", code: "x", message: "programme incohérent", node_id: "inconnu" }] });
  await open();
  expect(await within(panel()).findByRole("button", { name: /programme incohérent/ })).toBeDisabled();
});

test("un simple avertissement n'empêche pas d'enregistrer", async () => {
  report = () => ({ valid: true, issues: [{ severity: "warning", code: "parallel_conflict", message: "orage commandé deux fois", node_id: "a" }] });
  await open();
  expect(await within(panel()).findByText("Valide, 1 avertissement")).toBeInTheDocument();
  expect(save()).toBeEnabled();
});

test("une rafale de modifications ne produit qu'une validation, 500 ms après la dernière", async () => {
  await open();
  vi.useFakeTimers({ shouldAdvanceTime: true });
  const before = validations().length;
  const add = (id: string) => {
    const block = ws().newBlock("hw_relay", id);
    (block as unknown as { loadExtraState(s: object): void }).loadExtraState({ target: "orage" });
    ws().getBlockById("s1")!.nextConnection!.connect(block.previousConnection!);
  };
  await act(async () => {
    add("x1");
    await vi.advanceTimersByTimeAsync(300);
    add("x2");
    await vi.advanceTimersByTimeAsync(300); // 300 ms après la 2e : pas encore
  });
  expect(validations().length).toBe(before);
  await act(async () => {
    await vi.advanceTimersByTimeAsync(300);
  });
  await waitFor(() => expect(validations().length).toBe(before + 1));
  const last = validations().at(-1)!.body as { scripts: { root: { children: { id: string }[] } }[] };
  // les deux ajouts figurent dans la validation unique : 2 blocs d'origine + 2 nouveaux
  expect(last.scripts[0].root.children.length).toBe(4);
});

test("une réponse périmée n'écrase pas la plus récente", async () => {
  let release!: (r: Response) => void;
  let n = 0;
  report = () => {
    n += 1;
    if (n === 2) return new Promise<Response>((resolve) => (release = resolve)) as unknown as Response; // la 2e traîne
    return n === 3 ? { valid: true, issues: [] } : { valid: false, issues: [{ severity: "error", code: "x", message: "vieille erreur", node_id: "a" }] };
  };
  await open(); // 1re : erreur « vieille erreur »
  await within(panel()).findByText(/vieille erreur/);
  // 2e validation (en attente), puis 3e qui répond valide
  vi.useFakeTimers({ shouldAdvanceTime: true });
  const touch = (id: string) => {
    const block = ws().newBlock("hw_relay", id);
    (block as unknown as { loadExtraState(s: object): void }).loadExtraState({ target: "orage" });
    ws().getBlockById("s1")!.nextConnection!.connect(block.previousConnection!);
  };
  await act(async () => { touch("y1"); await vi.advanceTimersByTimeAsync(600); });
  await act(async () => { touch("y2"); await vi.advanceTimersByTimeAsync(600); });
  await waitFor(() => expect(validations().length).toBe(3));
  await act(async () => { release(Response.json({ valid: false, issues: [{ severity: "error", code: "x", message: "réponse périmée", node_id: "a" }] })); });
  expect(within(panel()).queryByText(/réponse périmée/)).toBeNull();
  expect(await within(panel()).findByText("Scénario valide")).toBeInTheDocument();
});

test("moteur injoignable : la validation est déclarée indisponible, sans bloquer", async () => {
  report = () => Response.json({ detail: "ko" }, { status: 503 });
  await open();
  expect(await within(panel()).findByText(/Validation indisponible/)).toBeInTheDocument();
  expect(save()).toBeEnabled();
});

test("un bloc posé hors d'un début est signalé comme ignoré", async () => {
  await open();
  vi.useFakeTimers({ shouldAdvanceTime: true });
  await act(async () => {
    const stray = ws().newBlock("hw_relay", "stray");
    (stray as unknown as { loadExtraState(s: object): void }).loadExtraState({ target: "orage" });
    await vi.advanceTimersByTimeAsync(700);
  });
  expect(await within(panel()).findByText(/aucun bloc « quand le scénario démarre »|n'est rattaché à aucun bloc/)).toBeInTheDocument();
});

test("un relais allumé et jamais éteint est signalé localement, sans appel supplémentaire au moteur", async () => {
  await open();
  vi.useFakeTimers({ shouldAdvanceTime: true });
  await act(async () => {
    // retire le « éteindre » : l'orage reste allumé
    ws().getBlockById("b")!.dispose(true);
    await vi.advanceTimersByTimeAsync(700);
  });
  expect(await within(panel()).findByText(/« Orage » est allumé mais jamais éteint/)).toBeInTheDocument();
  expect(save()).toBeEnabled(); // avertissement : non bloquant
});

test("un « si » sans condition reçoit un message clair, pas le message technique du moteur", async () => {
  report = () => ({ valid: false, issues: [{ severity: "error", code: "invalid", message: "scripts.0.root.sequence.children.2.if.condition : Input should be a valid dictionary or object to extract fields from", node_id: "i" }] });
  await open();
  vi.useFakeTimers({ shouldAdvanceTime: true });
  await act(async () => {
    const block = ws().newBlock("hw_if", "i");
    ws().getBlockById("s1")!.nextConnection!.connect(block.previousConnection!);
    await vi.advanceTimersByTimeAsync(700);
  });
  expect(await within(panel()).findByText("Branchez une condition sur ce « si ».")).toBeInTheDocument();
  expect(within(panel()).queryByText(/valid dictionary/)).toBeNull();
  expect(save()).toBeDisabled();
});

// ------------------------------------------------------------------ simulation

import userEvent from "@testing-library/user-event";

const principal = (await import("./fixtures/simulation-principal.json")).default;

test("Simuler envoie le programme à l'écran (même non enregistré) et affiche la frise", async () => {
  let received: unknown = null;
  report = () => ({ valid: true, issues: [] });
  // le moteur simulé répond avec la capture réelle
  vi.unstubAllGlobals();
  calls = stubEngine(({ path, method, body }) => {
    if (path === "/api/status") return STATUS;
    if (path === "/api/devices") return { ...devices, relays: [...devices.relays, { id: "fantome", name: "Fantôme", pin: 1, mode: "latched" }] };
    if (path === "/api/programs" && method === "GET") return [];
    if (path === "/api/programs/scene" && method === "GET") return program([relay("a", "on"), relay("b", "off")]);
    if (path === "/api/programs/validate") return { valid: true, issues: [] };
    if (path === "/api/simulate") {
      received = body;
      return principal;
    }
  });
  await open();
  const user = userEvent.setup();
  const block = ws().newBlock("hw_log", "extra"); // modification non enregistrée
  ws().getBlockById("s1")!.nextConnection!.connect(block.previousConnection!);
  await user.click(screen.getByRole("button", { name: "Simuler" }));
  const frise = await screen.findByRole("region", { name: "Frise temporelle" });
  const sent = received as { program: { scripts: { root: { children: { id: string }[] } }[] }; horizon_s: number; button_presses: unknown[] };
  expect(sent.program.scripts[0].root.children.map((c) => c.id)).toContain("extra");
  expect(sent.button_presses).toEqual([]);
  expect(within(frise).getByText("Terminé en 17 s.")).toBeInTheDocument();
  // une ligne par composant, chaque période décrite pour les lecteurs d'écran
  expect(within(frise).getByRole("img", { name: "Orage : allumé de 3 s à 11 s" })).toBeInTheDocument();
  expect(within(frise).getByRole("img", { name: "epouvantail : allumé de 17 s jusqu'à la fin (jamais éteint)" })).toBeInTheDocument();
  expect(within(frise).getAllByRole("listitem")).toHaveLength(5);
  expect(calls.some((c) => c.path === "/api/components/relays/orage/test")).toBe(false); // rien n'est actionné
});

test("Simuler est désactivé tant qu'une erreur subsiste", async () => {
  report = () => ({ valid: false, issues: [{ severity: "error", code: "x", message: "faux", node_id: "a" }] });
  await open();
  expect(screen.getByRole("button", { name: "Simuler" })).toBeDisabled();
});

test("les appuis simulés sont envoyés avec la simulation", async () => {
  let received: { button_presses: unknown[] } | null = null;
  vi.unstubAllGlobals();
  calls = stubEngine(({ path, method, body }) => {
    if (path === "/api/status") return STATUS;
    if (path === "/api/devices") return { ...devices, buttons: [{ id: "bp", name: "Bouton principal", pin: 21, pull: "up", debounce_ms: 50, long_press_ms: 800, double_press_ms: 400 }] };
    if (path === "/api/programs" && method === "GET") return [];
    if (path === "/api/programs/scene" && method === "GET") return program([relay("a", "on")]);
    if (path === "/api/programs/validate") return { valid: true, issues: [] };
    if (path === "/api/simulate") {
      received = body as { button_presses: unknown[] };
      return { ...principal, status: "deadlock" };
    }
  });
  await open();
  const user = userEvent.setup();
  await user.click(screen.getByRole("button", { name: "Simuler" }));
  const section = await screen.findByRole("region", { name: "Simulation" });
  expect(within(section).getByText(/attend un appui de bouton/)).toBeInTheDocument();
  await user.selectOptions(within(section).getByLabelText("Appui"), "double");
  await user.clear(within(section).getByLabelText("À (s)"));
  await user.type(within(section).getByLabelText("À (s)"), "7");
  await user.click(within(section).getByRole("button", { name: "Ajouter l'appui" }));
  expect(within(section).getByText(/Bouton principal : appui double à 7 s/)).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Simuler" }));
  await waitFor(() => expect((received as { button_presses: unknown[] } | null)?.button_presses).toEqual([{ t: 7, button: "bp", event: "double" }]));
});


// ------------------------------------------------------------------ exécution

const emit = (event: object) => act(() => FakeWebSocket.emit(event));
const start = (runId = "r1", programId = "scene") => emit({ type: "run_started", run_id: runId, program_id: programId, ts: 100 });
const node = (type: "node_started" | "node_finished", id: string, runId = "r1") => emit({ type, run_id: runId, program_id: "scene", script_id: "s1", node_id: id });
const banner = () => screen.queryByRole("status", { name: "Exécution" });

test("Lancer démarre le scénario enregistré ; l'éditeur passe en lecture seule et propose Arrêter", async () => {
  let launched: unknown = null;
  vi.unstubAllGlobals();
  calls = stubEngine(({ path, method, body }) => {
    if (path === "/api/status") return STATUS;
    if (path === "/api/devices") return devices;
    if (path === "/api/programs" && method === "GET") return [];
    if (path === "/api/programs/scene" && method === "GET") return program([relay("a", "on")]);
    if (path === "/api/programs/validate") return { valid: true, issues: [] };
    if (path === "/api/runs" && method === "POST") {
      launched = body;
      return { run_id: "r1", program_id: "scene", state: "running" };
    }
    if (path === "/api/runs/r1/stop") return { stopped: 1 };
  });
  await open();
  const user = userEvent.setup();
  expect(shared.readOnly).toBe(false);
  await user.click(screen.getByRole("button", { name: "Lancer" }));
  await waitFor(() => expect(launched).toEqual({ program_id: "scene", policy: "ignore" }));
  expect(await screen.findByText("Scénario en cours…")).toBeInTheDocument();
  expect(shared.readOnly).toBe(true);
  expect(screen.queryByRole("button", { name: "Lancer" })).toBeNull();
  expect(save()).toBeDisabled(); // pas d'enregistrement pendant un run
  await user.click(screen.getByRole("button", { name: "Arrêter ce scénario" }));
  await waitFor(() => expect(calls.some((c) => c.path === "/api/runs/r1/stop")).toBe(true));
});

test("Lancer est désactivé tant que le scénario a des modifications non enregistrées", async () => {
  await open();
  expect(screen.getByRole("button", { name: "Lancer" })).toBeEnabled();
  await act(async () => {
    const block = ws().newBlock("hw_log", "nouveau");
    ws().getBlockById("s1")!.nextConnection!.connect(block.previousConnection!);
  });
  await waitFor(() => expect(screen.getByRole("button", { name: "Lancer" })).toBeDisabled());
  expect(screen.getByRole("button", { name: "Lancer" })).toHaveAttribute("title", expect.stringContaining("Enregistrez avant de lancer"));
});

test("la fin du run affiche l'issue et la durée, l'éditeur redevient modifiable", async () => {
  await open();
  await start();
  expect(shared.readOnly).toBe(true);
  await emit({ type: "run_ended", run_id: "r1", program_id: "scene", outcome: "completed", ts: 117.5 });
  expect(within(banner()!).getByText("Terminé · 17.5 s")).toBeInTheDocument();
  expect(shared.readOnly).toBe(false);
  await userEvent.setup().click(within(banner()!).getByRole("button", { name: "Fermer" }));
  expect(banner()).toBeNull();
});

test.each([
  ["stopped", "Arrêté"],
  ["failed", "Échoué"],
  ["timeout", /Délai dépassé/],
])("issue « %s » annoncée", async (outcome, text) => {
  await open();
  await start();
  await emit({ type: "run_ended", run_id: "r1", program_id: "scene", outcome, error: outcome === "failed" ? "relais bloqué" : null, ts: 105 });
  expect(within(banner()!).getByText(text, { exact: false })).toBeInTheDocument();
  if (outcome === "failed") expect(within(banner()!).getByText("relais bloqué")).toBeInTheDocument();
});

test("une erreur d'action est listée, le run continue", async () => {
  await open();
  await start();
  await emit({ type: "error", source: "action", run_id: "r1", node_id: "a", message: "Home Assistant injoignable" });
  expect(within(banner()!).getByRole("list", { name: "Erreurs pendant l'exécution" })).toHaveTextContent("Home Assistant injoignable");
  expect(within(banner()!).getByText("Scénario en cours…")).toBeInTheDocument();
});

test("l'éditeur ne suit que le run de son scénario : l'arrêt d'un autre run n'y change rien", async () => {
  await open();
  await start("r1", "scene");
  await start("r2", "autre"); // un autre scénario démarre
  await node("node_started", "a", "r1");
  await emit({ type: "run_ended", run_id: "r2", program_id: "autre", outcome: "stopped", ts: 150 }); // et s'arrête
  expect(within(banner()!).getByText("Scénario en cours…")).toBeInTheDocument();
  expect(shared.readOnly).toBe(true);
});

test("ouvert pendant un run déjà en cours, l'éditeur s'y raccroche", async () => {
  vi.unstubAllGlobals();
  calls = stubEngine(({ path, method }) => {
    if (path === "/api/status") return { ...STATUS, runs: [{ run_id: "r7", program_id: "scene", state: "running", started_at: 1 }] };
    if (path === "/api/devices") return devices;
    if (path === "/api/programs" && method === "GET") return [];
    if (path === "/api/programs/scene" && method === "GET") return program([relay("a", "on")]);
    if (path === "/api/programs/validate") return { valid: true, issues: [] };
  });
  render(<App WebSocketImpl={WS} />);
  expect(await screen.findByText("Scénario en cours…")).toBeInTheDocument();
  expect(shared.readOnly).toBe(true);
});

test("verrouillé : le code est demandé pour lancer", async () => {
  let code: unknown = null;
  vi.unstubAllGlobals();
  calls = stubEngine(({ path, method, body }) => {
    if (path === "/api/status") return { ...STATUS, lock: { locked: true, has_code: true } };
    if (path === "/api/devices") return devices;
    if (path === "/api/programs" && method === "GET") return [];
    if (path === "/api/programs/scene" && method === "GET") return program([relay("a", "on")]);
    if (path === "/api/programs/validate") return { valid: true, issues: [] };
    if (path === "/api/runs" && method === "POST") {
      code = (body as { code?: string }).code;
      return { run_id: "r1", program_id: "scene", state: "running" };
    }
  });
  await open();
  const user = userEvent.setup();
  await user.click(screen.getByRole("button", { name: "Lancer" }));
  expect(calls.some((c) => c.path === "/api/runs")).toBe(false);
  await user.type(screen.getByLabelText("Code"), "1234");
  await user.click(screen.getByRole("button", { name: "Valider" }));
  await waitFor(() => expect(code).toBe("1234"));
});

// ------------------------------------------------------------------ enregistrement, brouillon, conflit

const puts = () => calls.filter((c) => c.method === "PUT" && c.path === "/api/programs/scene");
const addBlock = (id: string) => {
  const block = ws().newBlock("hw_log", id);
  ws().getBlockById("s1")!.nextConnection!.connect(block.previousConnection!);
};
const draftKey = "halloween.draft.scene";

test("Ctrl+S enregistre avec la révision connue (If-Match) et efface le brouillon", async () => {
  await open();
  localStorage.setItem(draftKey, JSON.stringify({ baseRevision: 3, savedAt: 1, program: program([]) }));
  const user = userEvent.setup();
  await act(async () => addBlock("n1"));
  await waitFor(() => expect(screen.getByRole("button", { name: "Lancer" })).toBeDisabled()); // modifié
  await user.keyboard("{Control>}s{/Control}");
  await waitFor(() => expect(puts().length).toBe(1));
  expect(puts()[0].headers.get("If-Match")).toBe('"3"');
  expect(localStorage.getItem(draftKey)).toBeNull();
  await waitFor(() => expect(screen.getByRole("button", { name: "Lancer" })).toBeEnabled()); // à jour
});

test("Ctrl+S ne fait rien tant qu'une erreur bloque l'enregistrement", async () => {
  report = () => ({ valid: false, issues: [{ severity: "error", code: "x", message: "faux", node_id: "a" }] });
  await open();
  await userEvent.setup().keyboard("{Control>}s{/Control}");
  expect(puts()).toHaveLength(0);
});

test("un brouillon est écrit 1 s après la dernière modification, puis proposé à la réouverture", async () => {
  await open();
  vi.useFakeTimers({ shouldAdvanceTime: true });
  await act(async () => {
    addBlock("n1");
    await vi.advanceTimersByTimeAsync(50);
  });
  expect(localStorage.getItem(draftKey)).toBeNull();
  await act(async () => {
    await vi.advanceTimersByTimeAsync(900); // 950 ms après la modification : pas encore
  });
  expect(localStorage.getItem(draftKey)).toBeNull();
  await act(async () => {
    await vi.advanceTimersByTimeAsync(200);
  });
  const stored = JSON.parse(localStorage.getItem(draftKey)!);
  expect(stored.baseRevision).toBe(3);
  expect(JSON.stringify(stored.program)).toContain("n1");
  vi.useRealTimers();
});

test("réouverture : le brouillon est proposé ; Restaurer remet les blocs et marque le scénario modifié", async () => {
  const withExtra = program([relay("a", "on"), relay("b", "off"), { id: "n1", type: "log", message: "brouillon" }]);
  localStorage.setItem(draftKey, JSON.stringify({ baseRevision: 3, savedAt: Date.parse("2026-10-27T10:00:00Z"), program: withExtra }));
  await open();
  const user = userEvent.setup();
  expect(await screen.findByText(/Un brouillon non enregistré du/)).toBeInTheDocument();
  expect(ws().getBlockById("n1")).toBeNull(); // rien n'est restauré sans accord
  await user.click(screen.getByRole("button", { name: "Restaurer le brouillon" }));
  expect(ws().getBlockById("n1")).not.toBeNull();
  expect(screen.queryByText(/Un brouillon non enregistré/)).toBeNull();
  expect(screen.getByRole("button", { name: "Lancer" })).toBeDisabled(); // modifié, pas enregistré
});

test("Supprimer le brouillon l'efface sans toucher aux blocs", async () => {
  localStorage.setItem(draftKey, JSON.stringify({ baseRevision: 3, savedAt: 1, program: program([]) }));
  await open();
  await userEvent.setup().click(await screen.findByRole("button", { name: "Supprimer" }));
  expect(localStorage.getItem(draftKey)).toBeNull();
  expect(ws().getBlockById("a")).not.toBeNull();
});

test("un brouillon commencé sur une autre révision le dit", async () => {
  localStorage.setItem(draftKey, JSON.stringify({ baseRevision: 1, savedAt: 1, program: program([]) }));
  await open();
  expect(await screen.findByText(/le scénario a changé depuis/)).toBeInTheDocument();
});

test("tant qu'un brouillon est proposé, il n'est pas écrasé par de nouvelles modifications", async () => {
  const kept = { baseRevision: 3, savedAt: 42, program: program([]) };
  localStorage.setItem(draftKey, JSON.stringify(kept));
  await open();
  await screen.findByText(/Un brouillon non enregistré/);
  vi.useFakeTimers({ shouldAdvanceTime: true });
  await act(async () => {
    addBlock("n1");
    await vi.advanceTimersByTimeAsync(2500);
  });
  expect(JSON.parse(localStorage.getItem(draftKey)!).savedAt).toBe(42);
  vi.useRealTimers();
});

test("un stockage local indisponible n'empêche rien", async () => {
  const spy = vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
    throw new Error("bloqué");
  });
  await open();
  expect(screen.queryByText(/Un brouillon non enregistré/)).toBeNull();
  spy.mockRestore();
});

test("quitter la page avec des modifications non enregistrées demande confirmation", async () => {
  await open();
  const propre = new Event("beforeunload", { cancelable: true });
  window.dispatchEvent(propre);
  expect(propre.defaultPrevented).toBe(false);
  await act(async () => addBlock("n1"));
  await waitFor(() => {
    const sale = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(sale);
    expect(sale.defaultPrevented).toBe(true);
  });
});

test("Annuler et Rétablir passent par l'historique de Blockly", async () => {
  await open();
  const user = userEvent.setup();
  await act(async () => {
    Blockly.Events.setGroup(true); // un geste de l'utilisateur = un groupe annulable d'un coup
    addBlock("n1");
    Blockly.Events.setGroup(false);
  });
  await new Promise((resolve) => setTimeout(resolve, 20)); // Blockly enregistre l'historique en différé
  expect(ws().getBlockById("n1")).not.toBeNull();
  await user.click(screen.getByRole("button", { name: "Annuler (Ctrl+Z)" }));
  expect(ws().getBlockById("n1")).toBeNull();
  await user.click(screen.getByRole("button", { name: "Rétablir (Ctrl+Y)" }));
  expect(ws().getBlockById("n1")).not.toBeNull();
});

function conflictEngine(onPut: (call: Call) => Response | object) {
  vi.unstubAllGlobals();
  let reads = 0;
  calls = stubEngine((call) => {
    const { path, method } = call;
    if (path === "/api/status") return STATUS;
    if (path === "/api/devices") return devices;
    if (path === "/api/programs" && method === "GET") return [];
    if (path === "/api/programs/scene" && method === "GET") {
      reads += 1;
      return reads === 1 ? program([relay("a", "on")]) : { ...program([relay("z", "off")]), revision: 8, name: "Version du moteur" };
    }
    if (path === "/api/programs/validate") return { valid: true, issues: [] };
    if (path === "/api/programs/scene" && method === "PUT") return onPut(call);
  });
}
const precondition = () => Response.json({ detail: { message: "révision périmée", issues: [] } }, { status: 412 });

test("conflit : Écraser relit la révision du moteur et réenregistre ce qui est à l'écran", async () => {
  let attempt = 0;
  conflictEngine(() => (++attempt === 1 ? precondition() : { program: { ...program([]), revision: 9 }, warnings: [] }));
  await open();
  const user = userEvent.setup();
  await act(async () => addBlock("n1"));
  await user.click(screen.getByRole("button", { name: "Enregistrer" }));
  const dialog = await screen.findByRole("dialog", { name: "Ce scénario a été modifié ailleurs" });
  await user.click(within(dialog).getByRole("button", { name: "Écraser" }));
  await waitFor(() => expect(puts().length).toBe(2));
  expect(puts()[0].headers.get("If-Match")).toBe('"3"');
  expect(puts()[1].headers.get("If-Match")).toBe('"8"'); // la révision actuelle du moteur
  expect(JSON.stringify(puts()[1].body)).toContain("n1"); // ce qui est à l'écran
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
});

test("conflit : Recharger abandonne l'écran au profit de la version du moteur", async () => {
  conflictEngine(() => precondition());
  await open();
  const user = userEvent.setup();
  await act(async () => addBlock("n1"));
  await user.click(screen.getByRole("button", { name: "Enregistrer" }));
  const dialog = await screen.findByRole("dialog", { name: "Ce scénario a été modifié ailleurs" });
  await user.click(within(dialog).getByRole("button", { name: "Recharger la version du moteur" }));
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  expect(ws().getBlockById("n1")).toBeNull();
  expect(ws().getBlockById("z")).not.toBeNull();
  expect(screen.getByLabelText("Nom du scénario")).toHaveValue("Version du moteur");
  expect(puts()).toHaveLength(1); // pas de second enregistrement
});

test("une autre erreur d'enregistrement est une notification, pas un conflit", async () => {
  conflictEngine(() => Response.json({ detail: { message: "disque plein", issues: [] } }, { status: 500 }));
  await open();
  await act(async () => addBlock("n1"));
  await userEvent.setup().click(screen.getByRole("button", { name: "Enregistrer" }));
  expect(await screen.findByText("disque plein")).toBeInTheDocument();
  expect(screen.queryByRole("dialog")).toBeNull();
});

test("verrouillé : l'éditeur est en lecture seule et n'enregistre pas (Ctrl+S compris)", async () => {
  vi.unstubAllGlobals();
  calls = stubEngine(({ path, method }) => {
    if (path === "/api/status") return { ...STATUS, lock: { locked: true, has_code: true } };
    if (path === "/api/devices") return devices;
    if (path === "/api/programs" && method === "GET") return [];
    if (path === "/api/programs/scene" && method === "GET") return program([relay("a", "on")]);
    if (path === "/api/programs/validate") return { valid: true, issues: [] };
  });
  await open();
  expect(shared.readOnly).toBe(true);
  expect(save()).toBeDisabled();
  await userEvent.setup().keyboard("{Control>}s{/Control}");
  expect(puts()).toHaveLength(0);
});
