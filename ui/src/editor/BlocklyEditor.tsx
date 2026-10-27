import * as Blockly from "blockly/core";
import * as French from "blockly/msg/fr";
import { useEffect, useRef } from "react";
import type { Devices } from "../catalog/CatalogProvider";
import { refreshComponentBlocks, registerBlocks } from "./blocks";
import { setCatalog } from "./catalog";
import { buildToolbox } from "./toolbox";

Blockly.setLocale(French as unknown as Record<string, string>);

const THEME = Blockly.Theme.defineTheme("halloween", {
  name: "halloween",
  base: Blockly.Themes.Zelos,
  componentStyles: {
    workspaceBackgroundColour: "#120e18",
    toolboxBackgroundColour: "#1b1523",
    toolboxForegroundColour: "#f1eaf7",
    flyoutBackgroundColour: "#1b1523",
    flyoutForegroundColour: "#f1eaf7",
    flyoutOpacity: 0.96,
    scrollbarColour: "#4a3d5c",
    insertionMarkerColour: "#ff8a2b",
    insertionMarkerOpacity: 0.4,
    cursorColour: "#ff8a2b",
  },
  fontStyle: { family: "Inter Variable, sans-serif", size: 11 },
});

export interface BlocklyEditorProps {
  devices: Devices | null;
  readOnly?: boolean;
  /** Appelé une fois l'espace de travail créé ; renvoie un nettoyage éventuel. */
  onReady: (workspace: Blockly.WorkspaceSvg) => void | (() => void);
  /** Modification utilisateur des blocs (hors chargement). */
  onChange?: (event: Blockly.Events.Abstract) => void;
}

/** Zone de montage Blockly. L'espace de travail vit tant que le composant est monté. */
export function BlocklyEditor({ devices, readOnly, onReady, onChange }: BlocklyEditorProps) {
  const host = useRef<HTMLDivElement>(null);
  const workspace = useRef<Blockly.WorkspaceSvg | null>(null);
  const change = useRef(onChange);
  change.current = onChange;
  const latest = useRef({ devices, onReady });
  latest.current = { devices, onReady };

  useEffect(() => {
    registerBlocks();
    setCatalog(latest.current.devices);
    const ws = Blockly.inject(host.current!, {
      renderer: "zelos",
      theme: THEME,
      toolbox: buildToolbox(latest.current.devices),
      zoom: { controls: true, wheel: true, startScale: 0.9, minScale: 0.3, maxScale: 1.6 },
      trashcan: true,
      move: { scrollbars: true, drag: true, wheel: false },
      sounds: false,
    });
    workspace.current = ws;
    ws.addChangeListener((event) => {
      if (event.isUiEvent) return;
      change.current?.(event);
    });
    const cleanup = latest.current.onReady(ws);
    const resize = new ResizeObserver(() => Blockly.svgResize(ws));
    resize.observe(host.current!);
    return () => {
      resize.disconnect();
      if (typeof cleanup === "function") cleanup();
      ws.dispose();
      workspace.current = null;
    };
  }, []);

  useEffect(() => {
    const ws = workspace.current;
    if (!ws) return;
    setCatalog(devices);
    ws.updateToolbox(buildToolbox(devices));
    refreshComponentBlocks(ws);
  }, [devices]);

  // Lecture seule pendant un run : on ne modifie pas des blocs en train de s'exécuter.
  useEffect(() => {
    workspace.current?.setIsReadOnly(Boolean(readOnly));
  }, [readOnly]);

  return <div className="blockly-host" ref={host} />;
}
