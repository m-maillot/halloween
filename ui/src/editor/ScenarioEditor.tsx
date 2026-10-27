import * as Blockly from "blockly/core";
import { useCallback, useEffect, useRef, useState } from "react";
import { Redo2, Undo2 } from "lucide-react";
import { useParams } from "react-router-dom";
import { api } from "../api/client";
import { ApiError, unwrap } from "../api/errors";
import { useCatalog } from "../catalog/CatalogProvider";
import { Button, Field, Modal } from "../components/ui";
import { CodePrompt } from "../dashboard/CodePrompt";
import { useEngine } from "../engine/EngineProvider";
import { useToasts } from "../components/Toasts";
import { BlocklyEditor } from "./BlocklyEditor";
import { clearDraft, readDraft, writeDraft, type Draft } from "./draft";
import { IssuePanel } from "./IssuePanel";
import { RunBanner } from "./RunBanner";
import { useRunView } from "./useRunView";
import { SimulationPanel, type Press } from "./SimulationPanel";
import type { SimulationOut } from "./timeline";
import { loadProgram, workspaceToProgram, type Program } from "./serialize";
import { useLiveValidation } from "./useLiveValidation";
import { summary } from "./validation";

/** Délai d'inactivité avant d'écrire le brouillon local. */
export const DRAFT_DELAY_MS = 1000;

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
  const [conflict, setConflict] = useState(false);
  const [draft, setDraft] = useState<Draft | null>(null);

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
      const stored = readDraft(id);
      if (stored) setDraft(stored); // proposé à l'utilisateur ; rien n'est restauré sans son accord
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

  /** Enregistre sur le moteur ; `revision` vient de la lecture du moteur quand l'utilisateur choisit d'écraser. */
  async function save(revision = program?.revision) {
    const body = build();
    if (!body || !program) return;
    setBusy(true);
    try {
      const saved = await unwrap<{ program: Program }>(
        api.PUT("/api/programs/{program_id}", {
          params: { path: { program_id: id } },
          headers: { "If-Match": `"${revision}"` },
          body,
        }),
      );
      setProgram(saved.program);
      setDirty(false);
      clearDraft(id);
      setDraft(null);
      setConflict(false);
      toasts.info("Scénario enregistré.");
    } catch (error) {
      if (error instanceof ApiError && error.status === 412) setConflict(true); // modifié ailleurs entre-temps
      else toasts.error(error);
    } finally {
      setBusy(false);
    }
  }

  /** Conflit : « écraser » reprend la révision actuelle du moteur et enregistre ce qui est à l'écran. */
  async function overwrite() {
    try {
      const current = await unwrap<Program>(api.GET("/api/programs/{program_id}", { params: { path: { program_id: id } } }));
      await save(current.revision);
    } catch (error) {
      toasts.error(error);
    }
  }

  /** Conflit : « recharger » abandonne ce qui est à l'écran au profit de la version du moteur. */
  async function reload() {
    try {
      const current = await unwrap<Program>(api.GET("/api/programs/{program_id}", { params: { path: { program_id: id } } }));
      if (workspace.current) loadProgram(workspace.current, current);
      setProgram(current);
      setName(current.name);
      setDirty(false);
      clearDraft(id);
      setDraft(null);
      setConflict(false);
      void runNow();
    } catch (error) {
      toasts.error(error);
    }
  }

  function restoreDraft() {
    if (!draft || !workspace.current) return;
    loadProgram(workspace.current, draft.program);
    setName(draft.program.name);
    setDirty(true);
    setDraft(null);
    void runNow();
  }

  function discardDraft() {
    clearDraft(id);
    setDraft(null);
  }

  // Brouillon automatique : ce qui est à l'écran, 1 s après la dernière modification.
  useEffect(() => {
    if (!dirty || !program || draft) return; // pas d'écrasement d'un brouillon proposé et pas encore tranché
    const timer = setTimeout(() => {
      const body = build();
      if (body) writeDraft(id, { baseRevision: program.revision, savedAt: Date.now(), program: body });
    }, DRAFT_DELAY_MS);
    return () => clearTimeout(timer);
  }, [dirty, program, draft, name, build, id]);

  // Ctrl+S enregistre (sans ouvrir la boîte « Enregistrer sous » du navigateur).
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") {
        event.preventDefault();
        if (!busy && !blocking && !running && program) void save();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  // Quitter la page avec des modifications non enregistrées : le navigateur demande confirmation.
  useEffect(() => {
    if (!dirty) return;
    const warn = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  return (
    <div className="editor-page">
      <div className="editor-bar">
        <Field
          label="Nom du scénario"
          value={name}
          onChange={(e) => {
            setName(e.target.value);
            setDirty(true);
          }}
        />
        <Button variant="ghost" aria-label="Annuler (Ctrl+Z)" title="Annuler (Ctrl+Z)" disabled={running} onClick={() => workspace.current?.undo(false)}>
          <Undo2 size={18} aria-hidden="true" />
        </Button>
        <Button variant="ghost" aria-label="Rétablir (Ctrl+Y)" title="Rétablir (Ctrl+Y)" disabled={running} onClick={() => workspace.current?.undo(true)}>
          <Redo2 size={18} aria-hidden="true" />
        </Button>
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
      {draft && (
        <div className="draft-banner" role="status">
          <span>
            Un brouillon non enregistré du {new Date(draft.savedAt).toLocaleString("fr-FR")} existe pour ce scénario
            {program && draft.baseRevision !== program.revision && " (le scénario a changé depuis : le restaurer remplacera ces changements)"}.
          </span>
          <Button onClick={restoreDraft}>Restaurer le brouillon</Button>
          <Button variant="ghost" onClick={discardDraft}>
            Supprimer
          </Button>
        </div>
      )}
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
      {conflict && (
        <Modal title="Ce scénario a été modifié ailleurs" onClose={() => setConflict(false)}>
          <p>
            Une autre session (ou la ligne de commande) a enregistré ce scénario depuis que vous l'avez ouvert. Écraser
            remplace sa version par ce qui est à l'écran ; recharger abandonne vos modifications non enregistrées.
          </p>
          <div className="form-actions">
            <Button variant="ghost" onClick={() => setConflict(false)}>
              Annuler
            </Button>
            <span className="form-actions__spacer" />
            <Button variant="outline-danger" onClick={() => void reload()}>
              Recharger la version du moteur
            </Button>
            <Button variant="primary" onClick={() => void overwrite()}>
              Écraser
            </Button>
          </div>
        </Modal>
      )}
      {askCode && <CodePrompt title="Code pour lancer ce scénario" onSubmit={(code) => launch(code)} onClose={() => setAskCode(false)} />}
      {simulation && (
        <SimulationPanel result={simulation} devices={devices} presses={presses} onPresses={setPresses} onClose={() => setSimulation(null)} />
      )}
    </div>
  );
}
