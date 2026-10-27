import * as Blockly from "blockly/core";
import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import { unwrap } from "../api/errors";
import type { Program } from "./serialize";
import { friendly, localIssues, locate, markBlocks, orphanIssues, type EditorIssue, type Located } from "./validation";

/** Délai d'inactivité avant d'interroger le moteur (spec §5.5). */
export const VALIDATE_DELAY_MS = 500;

export type ValidationState = "idle" | "checking" | "done" | "unavailable";

/**
 * Valide le programme en direct : après 500 ms sans modification, le moteur le contrôle ; les
 * contrôles locaux (relais jamais éteint, boucle sans fin, blocs orphelins) s'y ajoutent.
 */
export function useLiveValidation(
  workspace: { current: Blockly.Workspace | null },
  buildProgram: () => Program | null,
) {
  const [issues, setIssues] = useState<Located[]>([]);
  const [state, setState] = useState<ValidationState>("idle");
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const generation = useRef(0);
  const build = useRef(buildProgram);
  build.current = buildProgram;

  const run = useCallback(async () => {
    const ws = workspace.current;
    const program = build.current();
    if (!ws || !program) return;
    const mine = ++generation.current; // une réponse arrivée après une modification plus récente est ignorée
    setState("checking");
    let engine: EditorIssue[] = [];
    let reachable = true;
    try {
      const report = await unwrap<{ issues: EditorIssue[] }>(api.POST("/api/programs/validate", { body: program as never }));
      engine = report.issues;
    } catch {
      reachable = false;
    }
    if (mine !== generation.current || workspace.current !== ws) return;
    const local = localIssues(program);
    // Le message local d'une condition manquante remplace le message technique du moteur sur le même bloc.
    const explained = new Set(local.filter((i) => i.code === "local_missing_condition").map((i) => i.node_id));
    const fromEngine = engine.filter((i) => !(i.code === "invalid" && explained.has(i.node_id))).map(friendly);
    const located = locate(ws, [...fromEngine, ...local]).concat(orphanIssues(ws));
    setIssues(located);
    markBlocks(ws, located);
    setState(reachable ? "done" : "unavailable");
  }, [workspace]);

  /** À appeler à chaque modification : relance la minuterie. */
  const schedule = useCallback(() => {
    clearTimeout(timer.current);
    setState("checking");
    timer.current = setTimeout(() => void run(), VALIDATE_DELAY_MS);
  }, [run]);

  useEffect(() => () => clearTimeout(timer.current), []);

  return { issues, state, schedule, runNow: run };
}
