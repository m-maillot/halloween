import * as Blockly from "blockly/core";
import { useCallback, useEffect, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import { api } from "../api/client";
import { unwrap } from "../api/errors";
import { useCatalog } from "../catalog/CatalogProvider";
import { Button, Field } from "../components/ui";
import { CodePrompt } from "../dashboard/CodePrompt";
import { useEngine } from "../engine/EngineProvider";
import { useToasts } from "../components/Toasts";
import { BlocklyEditor } from "./BlocklyEditor";
import { IssuePanel } from "./IssuePanel";
import { RunBanner } from "./RunBanner";
import { useRunView } from "./useRunView";
import { SimulationPanel, type Press } from "./SimulationPanel";
import type { SimulationOut } from "./timeline";
import { loadProgram, workspaceToProgram, type Program } from "./serialize";
import { useLiveValidation } from "./useLiveValidation";
import { summary } from "./validation";

export function ScenarioEditor() {
  const { id = "" } = useParams();
  const { devices } = useCatalog();
  const { status } = useEngine();
  const toasts = useToasts();
  const workspace = useRef<Blockly.Workspace | null>(null);
  const [program, setProgram] = useState<Program | null>(null);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [simulation, setSimulation] = useState<SimulationOut | null>(null);
  const [presses, setPresses] = useState<Press[]>([]);
  const [simulating, setSimulating] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [askCode, setAskCode] = useState(false);

  const viewState = () => {
    const ws = workspace.current;
    return ws instanceof Blockly.WorkspaceSvg ? { zoom: ws.getScale(), scroll: { x: Math.round(ws.scrollX), y: Math.round(ws.scrollY) } } : undefined;
  };
  const build = useCallback((): Program | null => {
    const ws = workspace.current;
    if (!ws || !program) return null;
    return workspaceToProgram(ws, { ...program, name: name.trim() || program.name }, viewState());
  }, [program, name]);
  const { issues, state, schedule, runNow } = useLiveValidation(workspace, build);
  const blocking = summary(issues).errors > 0;
  const { view, running, adopt, clear } = useRunView(id, workspace);
  const locked = status?.lock.locked ?? false;

  useEffect(() => {
    let cancelled = false;
    unwrap<Program>(api.GET("/api/programs/{program_id}", { params: { path: { program_id: id } } }))
      .then((loaded) => {
        if (cancelled) return;
        setProgram(loaded);
        setName(loaded.name);
      })
      .catch((error) => !cancelled && toasts.error(error));
    return () => {
      cancelled = true;
    };
  }, [id, toasts]);

  const ready = useCallback((ws: Blockly.Workspace) => {
    workspace.current = ws;
    return () => {
      workspace.current = null;
    };
  }, []);

  const loadedFor = useRef<string | null>(null);
  useEffect(() => {
    // Une seule fois par scénario : après un enregistrement, les blocs à l'écran font foi
    // (recharger effacerait l'historique annuler / rétablir et recentrerait la vue).
    const ws = workspace.current;
    if (program && devices && ws && loadedFor.current !== id) {
      loadedFor.current = id;
      loadProgram(ws, program);
      if (ws instanceof Blockly.WorkspaceSvg) {
        const editor = program.editor as { zoom?: number; scroll?: { x: number; y: number } } | null;
        if (editor?.zoom) ws.setScale(editor.zoom);
        if (editor?.scroll) ws.scroll(editor.scroll.x, editor.scroll.y);
        else ws.scrollCenter();
      }
      setDirty(false);
      void runNow(); // première validation sans attendre
    }
  }, [program, id, !devices]);

  // Un composant ajouté, modifié ou supprimé peut rendre un bloc invalide.
  useEffect(() => {
    if (loadedFor.current === id) schedule();
  }, [devices]);

  function select(blockId: string) {
    const ws = workspace.current;
    const block = ws?.getBlockById(blockId);
    if (!ws || !block) return;
    if (ws instanceof Blockly.WorkspaceSvg && block instanceof Blockly.BlockSvg) {
      ws.centerOnBlock(blockId, true);
      block.select();
    }
  }

  async function simulate() {
    const body = build();
    if (!body) return;
    setSimulating(true);
    try {
      setSimulation(
        await unwrap<SimulationOut>(
          api.POST("/api/simulate", { body: { program: body as never, button_presses: presses, horizon_s: 600, seed: 0 } }),
        ),
      );
    } catch (error) {
      toasts.error(error);
    } finally {
      setSimulating(false);
    }
  }

  async function launch(code?: string) {
    const started = await unwrap<{ run_id: string }>(api.POST("/api/runs", { body: { program_id: id, policy: "ignore", code } }));
    adopt(started.run_id);
  }

  async function stop() {
    if (!view.runId) return;
    try {
      await unwrap(api.POST("/api/runs/{run_id}/stop", { params: { path: { run_id: view.runId } } }));
    } catch (error) {
      toasts.error(error);
    }
  }

  async function save() {
    const body = build();
    if (!body || !program) return;
    setBusy(true);
    try {
      const saved = await unwrap<{ program: Program }>(
        api.PUT("/api/programs/{program_id}", {
          params: { path: { program_id: id } },
          headers: { "If-Match": `"${program.revision}"` },
          body,
        }),
      );
      setProgram(saved.program);
      setDirty(false);
      toasts.info("Scénario enregistré.");
    } catch (error) {
      toasts.error(error);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="editor-page">
      <div className="editor-bar">
        <Field label="Nom du scénario" value={name} onChange={(e) => setName(e.target.value)} />
        <Button
          disabled={simulating || !program || blocking}
          title={blocking ? "Corrigez les erreurs avant de simuler" : "Joue le scénario en temps virtuel, sans rien actionner"}
          onClick={() => void simulate()}
        >
          Simuler
        </Button>
        {running ? (
          <Button variant="outline-danger" onClick={() => void stop()}>
            Arrêter ce scénario
          </Button>
        ) : (
          <Button
            disabled={!program || blocking || dirty}
            title={dirty ? "Enregistrez avant de lancer : c'est la version enregistrée qui est lancée" : blocking ? "Corrigez les erreurs avant de lancer" : undefined}
            onClick={() => {
              if (locked) setAskCode(true);
              else void launch().catch((error) => toasts.error(error));
            }}
          >
            Lancer
          </Button>
        )}
        <Button
          variant="primary"
          disabled={busy || !program || blocking || running}
          title={blocking ? "Corrigez les erreurs avant d'enregistrer" : undefined}
          onClick={() => void save()}
        >
          Enregistrer
        </Button>
      </div>
      <RunBanner view={view} onDismiss={clear} />
      <div className="editor-body">
        <BlocklyEditor
          devices={devices}
          onReady={ready}
          readOnly={running}
          onChange={() => {
            setDirty(true);
            schedule();
          }}
        />
        <IssuePanel issues={issues} state={state} onSelect={select} />
      </div>
      {askCode && <CodePrompt title="Code pour lancer ce scénario" onSubmit={(code) => launch(code)} onClose={() => setAskCode(false)} />}
      {simulation && (
        <SimulationPanel result={simulation} devices={devices} presses={presses} onPresses={setPresses} onClose={() => setSimulation(null)} />
      )}
    </div>
  );
}
