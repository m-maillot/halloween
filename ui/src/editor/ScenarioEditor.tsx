import * as Blockly from "blockly/core";
import { useCallback, useEffect, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import { api } from "../api/client";
import { unwrap } from "../api/errors";
import { useCatalog } from "../catalog/CatalogProvider";
import { Button, Field } from "../components/ui";
import { useToasts } from "../components/Toasts";
import { BlocklyEditor } from "./BlocklyEditor";
import { IssuePanel } from "./IssuePanel";
import { loadProgram, workspaceToProgram, type Program } from "./serialize";
import { useLiveValidation } from "./useLiveValidation";
import { summary } from "./validation";

export function ScenarioEditor() {
  const { id = "" } = useParams();
  const { devices } = useCatalog();
  const toasts = useToasts();
  const workspace = useRef<Blockly.Workspace | null>(null);
  const [program, setProgram] = useState<Program | null>(null);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);

  const view = () => {
    const ws = workspace.current;
    return ws instanceof Blockly.WorkspaceSvg ? { zoom: ws.getScale(), scroll: { x: Math.round(ws.scrollX), y: Math.round(ws.scrollY) } } : undefined;
  };
  const build = useCallback((): Program | null => {
    const ws = workspace.current;
    if (!ws || !program) return null;
    return workspaceToProgram(ws, { ...program, name: name.trim() || program.name }, view());
  }, [program, name]);
  const { issues, state, schedule, runNow } = useLiveValidation(workspace, build);
  const blocking = summary(issues).errors > 0;

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
          variant="primary"
          disabled={busy || !program || blocking}
          title={blocking ? "Corrigez les erreurs avant d'enregistrer" : undefined}
          onClick={() => void save()}
        >
          Enregistrer
        </Button>
      </div>
      <div className="editor-body">
        <BlocklyEditor devices={devices} onReady={ready} onChange={schedule} />
        <IssuePanel issues={issues} state={state} onSelect={select} />
      </div>
    </div>
  );
}
