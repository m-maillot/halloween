import * as Blockly from "blockly/core";
import { useCallback, useEffect, useReducer } from "react";
import { useEngine } from "../engine/EngineProvider";
import { EMPTY, isRunning, markRun, reduce } from "./runView";

/** Suit le run du scénario ouvert : blocs en cours, terminés, en erreur, issue finale. */
export function useRunView(programId: string, workspace: { current: Blockly.Workspace | null }) {
  const { subscribe, status } = useEngine();
  const [view, dispatch] = useReducer(reduce, EMPTY);

  useEffect(() => dispatch({ type: "clear" }), [programId]);
  useEffect(() => subscribe((event) => dispatch({ type: "event", event, programId })), [subscribe, programId]);

  // Ouvert pendant un run déjà en cours : on s'y raccroche (les blocs se surlignent aux prochains événements).
  const live = status?.runs.find((r) => r.program_id === programId && r.state === "running");
  useEffect(() => {
    if (live && view.runId === null) dispatch({ type: "adopt", runId: live.run_id, startedTs: live.started_at ?? null });
  }, [live, view.runId]);

  useEffect(() => {
    if (workspace.current) markRun(workspace.current, view);
  }, [view, workspace]);

  return {
    view,
    running: isRunning(view),
    adopt: useCallback((runId: string) => dispatch({ type: "adopt", runId, startedTs: null }), []),
    clear: useCallback(() => dispatch({ type: "clear" }), []),
  };
}
