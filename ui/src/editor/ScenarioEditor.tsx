import * as Blockly from "blockly/core";
import { useCallback, useEffect, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import { api } from "../api/client";
import { unwrap } from "../api/errors";
import { useCatalog } from "../catalog/CatalogProvider";
import { Button, Field } from "../components/ui";
import { useToasts } from "../components/Toasts";
import { BlocklyEditor } from "./BlocklyEditor";
import { loadProgram, workspaceToProgram, type Program } from "./serialize";

export function ScenarioEditor() {
  const { id = "" } = useParams();
  const { devices } = useCatalog();
  const toasts = useToasts();
  const workspace = useRef<Blockly.WorkspaceSvg | null>(null);
  const [program, setProgram] = useState<Program | null>(null);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);

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

  // Les blocs ne se chargent qu'une fois le programme ET l'espace de travail prêts.
  const ready = useCallback(
    (ws: Blockly.WorkspaceSvg) => {
      workspace.current = ws;
      return () => {
        workspace.current = null;
      };
    },
    [],
  );
  useEffect(() => {
    if (program && devices && workspace.current) {
      loadProgram(workspace.current, program);
      const editor = program.editor as { zoom?: number; scroll?: { x: number; y: number } } | null;
      if (editor?.zoom) workspace.current.setScale(editor.zoom);
      workspace.current.scrollCenter();
    }
    // Le catalogue ne doit pas recharger le programme : seul un changement de programme le fait.
  }, [program, !devices]);

  async function save() {
    const ws = workspace.current;
    if (!ws || !program) return;
    setBusy(true);
    try {
      const body = workspaceToProgram(ws, { ...program, name: name.trim() }, { zoom: ws.getScale() });
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
        <Button variant="primary" disabled={busy || !program} onClick={() => void save()}>
          Enregistrer
        </Button>
      </div>
      <BlocklyEditor devices={devices} onReady={ready} />
    </div>
  );
}
