// Suivi d'un run dans l'éditeur : état pur (réducteur) + marquage des blocs.
import * as Blockly from "blockly/core";
import type { EngineEvent } from "../engine/socket";
import { resolveBlock } from "./validation";

export interface RunView {
  runId: string | null;
  startedTs: number | null;
  /** Nœuds en cours : démarrés moins terminés (une boucle redémarre un même nœud). */
  running: Record<string, number>;
  finished: Record<string, true>;
  /** Nœuds en cours par script : le chapeau d'un script reste « en cours » tant que l'un de ses nœuds tourne. */
  scripts: Record<string, number>;
  errors: { nodeId: string | null; message: string }[];
  ended: { outcome: string | null; error: string | null; durationS: number | null } | null;
}

export const EMPTY: RunView = { runId: null, startedTs: null, running: {}, finished: {}, scripts: {}, errors: [], ended: null };

export type RunAction =
  | { type: "event"; event: EngineEvent; programId: string }
  | { type: "adopt"; runId: string; startedTs: number | null }
  | { type: "clear" };

export function reduce(state: RunView, action: RunAction): RunView {
  if (action.type === "clear") return EMPTY;
  if (action.type === "adopt") {
    return state.runId === action.runId ? state : { ...EMPTY, runId: action.runId, startedTs: action.startedTs };
  }
  const { event, programId } = action;
  switch (event.type) {
    case "run_started":
      // un nouveau run de CE scénario remplace l'affichage précédent
      return event.program_id === programId ? { ...EMPTY, runId: event.run_id, startedTs: event.ts ?? null } : state;
    case "node_started":
      if (event.run_id !== state.runId) return state;
      return {
        ...state,
        running: { ...state.running, [event.node_id]: (state.running[event.node_id] ?? 0) + 1 },
        scripts: { ...state.scripts, [event.script_id]: (state.scripts[event.script_id] ?? 0) + 1 },
        finished: Object.fromEntries(Object.entries(state.finished).filter(([id]) => id !== event.node_id)) as Record<string, true>,
      };
    case "node_finished": {
      if (event.run_id !== state.runId) return state;
      const left = Math.max(0, (state.running[event.node_id] ?? 0) - 1);
      const running = { ...state.running };
      if (left === 0) delete running[event.node_id];
      else running[event.node_id] = left;
      return {
        ...state,
        running,
        scripts: { ...state.scripts, [event.script_id]: Math.max(0, (state.scripts[event.script_id] ?? 0) - 1) },
        finished: { ...state.finished, [event.node_id]: true },
      };
    }
    case "error":
      if (!event.run_id || event.run_id !== state.runId) return state;
      return { ...state, errors: [...state.errors, { nodeId: event.node_id ?? null, message: event.message }] };
    case "run_ended":
      if (event.run_id !== state.runId) return state;
      return {
        ...state,
        running: {},
        scripts: Object.fromEntries(Object.keys(state.scripts).map((id) => [id, 0])),
        ended: {
          outcome: event.outcome ?? null,
          error: event.error ?? null,
          durationS: state.startedTs != null && event.ts != null ? Math.max(0, event.ts - state.startedTs) : null,
        },
      };
    default:
      return state;
  }
}

export const isRunning = (view: RunView) => view.runId !== null && view.ended === null;

export const ACTIVE = "hw-block-active";
export const DONE = "hw-block-done";
export const RUN_ERROR = "hw-block-run-error";

export type BlockRunState = "active" | "done" | "error" | undefined;

/** État de chaque bloc : les nœuds conteneurs (pile, branche) comptent pour leur bloc propriétaire. */
export function blockStates(workspace: Blockly.Workspace, view: RunView): Map<string, BlockRunState> {
  const states = new Map<string, BlockRunState>();
  const rank = { error: 3, active: 2, done: 1 } as const;
  const put = (nodeId: string, state: "active" | "done" | "error") => {
    const block = resolveBlock(workspace, nodeId);
    if (!block) return;
    const known = states.get(block.id);
    if (!known || rank[state] > rank[known]) states.set(block.id, state);
  };
  for (const id of Object.keys(view.finished)) put(id, "done");
  // chapeau d'un script : en cours tant qu'un de ses nœuds tourne, terminé ensuite (l'identifiant du chapeau est celui du script)
  for (const [scriptId, count] of Object.entries(view.scripts)) put(scriptId, count > 0 ? "active" : "done");
  for (const id of Object.keys(view.running)) put(id, "active"); // un nœud actif l'emporte sur « terminé » d'un autre passage
  for (const error of view.errors) if (error.nodeId) put(error.nodeId, "error");
  return states;
}

/** Surligne les blocs en cours, estompe les terminés, entoure ceux en erreur. */
export function markRun(workspace: Blockly.Workspace, view: RunView): void {
  if (!(workspace instanceof Blockly.WorkspaceSvg)) return;
  const states = blockStates(workspace, view);
  for (const block of workspace.getAllBlocks(false) as Blockly.BlockSvg[]) {
    const root = block.getSvgRoot();
    if (!root) continue;
    const state = states.get(block.id);
    root.classList.toggle(ACTIVE, state === "active");
    root.classList.toggle(DONE, state === "done");
    root.classList.toggle(RUN_ERROR, state === "error");
  }
}

export const OUTCOME_TEXT: Record<string, { tone: "ok" | "warn" | "error"; text: string }> = {
  completed: { tone: "ok", text: "Terminé" },
  stopped: { tone: "warn", text: "Arrêté" },
  failed: { tone: "error", text: "Échoué" },
  timeout: { tone: "warn", text: "Délai dépassé (durée maximale atteinte)" },
};
