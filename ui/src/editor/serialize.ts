// Blocs Blockly <-> JSON de programme (spec 1). Fonctions pures sur un espace de travail, qu'il
// soit affiché ou non : les tests tournent sans navigateur.
import * as Blockly from "blockly/core";
import type { components } from "../api/schema";

export type Program = components["schemas"]["Program"];
export type Node = { id: string; type: string; [key: string]: unknown };

export interface EditorLayout {
  /** Position de chaque bloc début (les autres blocs suivent leur pile). */
  blocks: Record<string, { x: number; y: number }>;
  /** Identifiants des blocs repliés. */
  collapsed?: string[];
  zoom?: number;
  scroll?: { x: number; y: number };
}

/** Les identifiants Blockly contiennent des caractères que le moteur refuse dans un `id`. */
export function nodeId(block: Blockly.Block): string {
  const safe = block.id.replace(/[^A-Za-z0-9_-]/g, "_").slice(0, 60);
  return /^[A-Za-z0-9]/.test(safe) ? safe : `b${safe}`; // le moteur exige un premier caractère alphanumérique
}

/** Identifiant d'un nœud conteneur (séquence implicite d'une pile), dérivé de son propriétaire. */
export function containerId(owner: string, slot: string): string {
  return `${owner}_${slot}`;
}

// ---------------------------------------------------------------- blocs -> JSON

const checked = (block: Blockly.Block, name: string) => block.getFieldValue(name) === "TRUE";
const targetOf = (block: Blockly.Block) => (block as unknown as { target_: string }).target_;

/** `fire_and_forget` et `on_error` : écrits seulement quand ils ne sont pas à leur valeur par défaut. */
function withOptions(block: Blockly.Block, node: Node): Node {
  if (checked(block, "FF")) node.fire_and_forget = true;
  if (block.getFieldValue("ONERR") === "abort") node.on_error = "abort";
  return node;
}

const toPercent = (value255: number) => Math.round((value255 / 255) * 10000) / 100;
const toByte = (percent: number) => Math.round((percent * 255) / 100);
const hexOf = ([r, g, b]: number[]) => `#${[r, g, b].map((v) => v.toString(16).padStart(2, "0")).join("")}`;
const rgbOf = (hex: string): [number, number, number] => {
  const n = parseInt(hex.slice(1), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
};

function leaf(block: Blockly.Block): Node {
  const id = nodeId(block);
  switch (block.type) {
    case "hw_relay": {
      const target = targetOf(block);
      if (!block.getField("STATE")) {
        const node: Node = { id, type: "relay", target, action: "trigger" }; // impulsion
        if (checked(block, "WAIT_END")) node.wait_for_end = true;
        return withOptions(block, node);
      }
      return withOptions(block, { id, type: "relay", target, state: block.getFieldValue("STATE") });
    }
    case "hw_light": {
      const node: Node = { id, type: "light", target: targetOf(block), state: block.getFieldValue("STATE") };
      // Les paramètres ne sont envoyés que cochés : « non coché = pas envoyé » (spec §5.3).
      if (checked(block, "USE_COLOR")) node.rgb_color = rgbOf(block.getFieldValue("COLOR"));
      if (checked(block, "USE_BRIGHT")) node.brightness = toByte(block.getFieldValue("BRIGHT"));
      if (checked(block, "USE_TRANS")) node.transition = Number(block.getFieldValue("TRANS"));
      return withOptions(block, node);
    }
    case "hw_switch":
      return withOptions(block, { id, type: "switch", target: targetOf(block), state: block.getFieldValue("STATE") });
    default:
      throw new Error(`bloc inconnu : ${block.type}`);
  }
}

/** Pile de blocs (à partir du premier) -> un nœud ; plusieurs blocs forment une séquence. */
export function stackToNode(first: Blockly.Block | null, container: string): Node | null {
  const nodes: Node[] = [];
  for (let b = first; b; b = b.getNextBlock()) nodes.push(blockToNode(b));
  if (nodes.length === 0) return null;
  return nodes.length === 1 ? nodes[0] : { id: container, type: "sequence", children: nodes };
}

/** Contenu d'une entrée « instructions » : un nœud, ou une séquence vide (jamais `null`, le moteur l'exige). */
function inputNode(block: Blockly.Block, input: string, slot: string): Node {
  const first = block.getInputTargetBlock(input);
  return stackToNode(first, containerId(nodeId(block), slot)) ?? { id: containerId(nodeId(block), slot), type: "sequence", children: [] };
}

const round = (value: number, digits: number) => Math.round(value * 10 ** digits) / 10 ** digits;
const numberField = (block: Blockly.Block, name: string) => Number(block.getFieldValue(name));

function conditionNode(block: Blockly.Block | null): Node | null {
  if (!block) return null;
  switch (block.type) {
    case "hw_cond_button":
      return { id: block.getFieldValue("BUTTON"), type: "button", event: block.getFieldValue("EVENT") };
    case "hw_cond_relay_is":
      return { id: block.getFieldValue("RELAY"), type: "relay_is", state: block.getFieldValue("STATE") };
    case "hw_cond_random":
      return { type: "random", probability: round(numberField(block, "PERCENT") / 100, 6) } as unknown as Node;
    default:
      throw new Error(`condition inconnue : ${block.type}`);
  }
}

export function blockToNode(block: Blockly.Block): Node {
  const id = nodeId(block);
  switch (block.type) {
    case "hw_parallel": {
      const count = (block as unknown as { count_: number }).count_;
      const children: Node[] = [];
      for (let i = 0; i < count; i++) {
        const child = stackToNode(block.getInputTargetBlock(`BRANCH${i}`), containerId(id, `b${i}`));
        if (child) children.push(child); // une branche vide n'exécute rien : elle n'est pas écrite
      }
      const node: Node = { id, type: "parallel", children };
      if (block.getFieldValue("UNTIL") === "first") node.until = "first";
      return node;
    }
    case "hw_random_choice": {
      const count = (block as unknown as { count_: number }).count_;
      const choices: { weight: number; child: Node }[] = [];
      for (let i = 0; i < count; i++) {
        const child = stackToNode(block.getInputTargetBlock(`CHOICE${i}`), containerId(id, `c${i}`));
        if (child) choices.push({ weight: numberField(block, `WEIGHT${i}`), child });
      }
      return { id, type: "random_choice", choices };
    }
    case "hw_repeat":
      return { id, type: "repeat", times: numberField(block, "TIMES"), child: inputNode(block, "DO", "do") };
    case "hw_repeat_forever":
      return { id, type: "repeat", forever: true, child: inputNode(block, "DO", "do") };
    case "hw_wait":
      return { id, type: "wait", seconds: numberField(block, "SECONDS") };
    case "hw_wait_random":
      return { id, type: "wait", min: numberField(block, "MIN"), max: numberField(block, "MAX") };
    case "hw_if": {
      const node: Node = { id, type: "if", condition: conditionNode(block.getInputTargetBlock("COND")), then: inputNode(block, "THEN", "then") };
      if (block.getInputTargetBlock("ELSE")) node.else = inputNode(block, "ELSE", "else");
      return node;
    }
    case "hw_wait_until": {
      const node: Node = { id, type: "wait_until", condition: conditionNode(block.getInputTargetBlock("COND")) };
      const timeout = numberField(block, "TIMEOUT");
      if (timeout > 0) node.timeout_s = timeout;
      return node;
    }
    case "hw_call":
      return { id, type: "call", program_id: block.getFieldValue("PROGRAM") };
    case "hw_log":
      return { id, type: "log", message: block.getFieldValue("MESSAGE") };
    default:
      return leaf(block);
  }
}

export interface ProgramMeta {
  id: string;
  name: string;
  max_duration_s?: number | null;
  on_end?: "reset" | "keep";
  show?: boolean;
  show_order?: number | null;
  revision?: number;
}

export function topScripts(workspace: Blockly.Workspace): Blockly.Block[] {
  return workspace.getTopBlocks(true).filter((b) => b.type === "hw_start");
}

/** Blocs de tête de pile qui ne sont pas un bloc début : ignorés par le moteur, signalés à l'écran. */
export function orphanStacks(workspace: Blockly.Workspace): Blockly.Block[] {
  return workspace.getTopBlocks(true).filter((b) => b.type !== "hw_start");
}

export function workspaceToProgram(workspace: Blockly.Workspace, meta: ProgramMeta, view?: { zoom?: number; scroll?: { x: number; y: number } }): Program {
  const scripts = topScripts(workspace).map((hat) => {
    const id = nodeId(hat);
    const children = stackToNode(hat.getNextBlock(), containerId(id, "root"));
    const root: Node =
      children?.type === "sequence" ? children : { id: containerId(id, "root"), type: "sequence", children: children ? [children] : [] };
    return { id, hat: { type: "start" as const }, root: root as never };
  });
  const layout: EditorLayout = { blocks: {}, ...view };
  for (const hat of topScripts(workspace)) {
    const { x, y } = hat.getRelativeToSurfaceXY();
    layout.blocks[nodeId(hat)] = { x: Math.round(x), y: Math.round(y) };
  }
  const collapsed = workspace
    .getAllBlocks(false)
    .filter((b) => b.isCollapsed())
    .map(nodeId);
  if (collapsed.length) layout.collapsed = collapsed;
  return {
    schema: 1,
    id: meta.id,
    name: meta.name,
    max_duration_s: meta.max_duration_s ?? null,
    on_end: meta.on_end ?? "reset",
    show: meta.show ?? false,
    show_order: meta.show_order ?? null,
    revision: meta.revision ?? 0,
    scripts,
    editor: layout as never,
  };
}

// ---------------------------------------------------------------- JSON -> blocs

function create(workspace: Blockly.Workspace, type: string, id: string, state?: object): Blockly.Block {
  const block = workspace.newBlock(type, id);
  if (state) (block as unknown as { loadExtraState(s: object): void }).loadExtraState(state);
  return block;
}

function attach(workspace: Blockly.Workspace, node: Node, previous: Blockly.Block | null, parentInput: Blockly.Input | null): Blockly.Block | null {
  const place = (block: Blockly.Block, last: Blockly.Block | null) => {
    if (last) last.nextConnection!.connect(block.previousConnection!);
    else if (parentInput) parentInput.connection!.connect(block.previousConnection!);
  };
  if (node.type === "sequence") {
    let last = previous;
    for (const child of (node.children as Node[]) ?? []) last = attach(workspace, child, last, last ? null : parentInput);
    return last;
  }
  const block = nodeToBlock(workspace, node);
  place(block, previous);
  return block;
}

function plugCondition(workspace: Blockly.Workspace, parent: Blockly.Block, condition: Node | null): void {
  if (!condition) return;
  let block: Blockly.Block;
  switch (condition.type) {
    case "button":
      block = create(workspace, "hw_cond_button", `${parent.id}_cond`, { button: condition.id });
      block.setFieldValue(String(condition.event), "EVENT");
      break;
    case "relay_is":
      block = create(workspace, "hw_cond_relay_is", `${parent.id}_cond`, { relay: condition.id });
      block.setFieldValue(String(condition.state), "STATE");
      break;
    case "random":
      block = create(workspace, "hw_cond_random", `${parent.id}_cond`);
      block.setFieldValue(String(round((condition.probability as number) * 100, 4)), "PERCENT");
      break;
    default:
      throw new Error(`condition non prise en charge : ${String(condition.type)}`);
  }
  parent.getInput("COND")!.connection!.connect(block.outputConnection!);
}

function nodeToBlock(workspace: Blockly.Workspace, node: Node): Blockly.Block {
  switch (node.type) {
    case "relay":
    case "light":
    case "switch": {
      const block = create(workspace, `hw_${node.type}`, node.id, node.type === "relay" && node.action === "trigger" ? { target: node.target, trigger: true } : { target: node.target });
      // Un champ absent (paramètre qu'un composant ne porte pas) est ignoré sans lever d'erreur : la
      // validation du moteur, pas le chargement, dit ce qui ne va pas.
      const set = (name: string, value: string) => block.getField(name) && block.setFieldValue(value, name);
      if (node.type === "relay" && node.action === "trigger") {
        if (node.wait_for_end) set("WAIT_END", "TRUE");
      } else if (node.state) {
        set("STATE", node.state as string);
      }
      if (node.fire_and_forget) set("FF", "TRUE");
      if (node.on_error === "abort") set("ONERR", "abort");
      if (node.type === "light") {
        if (node.rgb_color) {
          set("USE_COLOR", "TRUE");
          set("COLOR", hexOf(node.rgb_color as number[]));
        }
        if (node.brightness != null) {
          set("USE_BRIGHT", "TRUE");
          set("BRIGHT", String(toPercent(node.brightness as number)));
        }
        if (node.transition != null) {
          set("USE_TRANS", "TRUE");
          set("TRANS", String(node.transition));
        }
      }
      return block;
    }
    case "parallel": {
      const children = (node.children as Node[]) ?? [];
      const block = create(workspace, "hw_parallel", node.id, { count: children.length });
      if (node.until === "first") block.setFieldValue("first", "UNTIL");
      children.forEach((child, i) => attach(workspace, child, null, block.getInput(`BRANCH${i}`)));
      return block;
    }
    case "random_choice": {
      const choices = (node.choices as { weight?: number; child: Node }[]) ?? [];
      const block = create(workspace, "hw_random_choice", node.id, { count: choices.length });
      choices.forEach((choice, i) => {
        block.setFieldValue(String(choice.weight ?? 1), `WEIGHT${i}`);
        attach(workspace, choice.child, null, block.getInput(`CHOICE${i}`));
      });
      return block;
    }
    case "repeat": {
      const block = create(workspace, node.forever ? "hw_repeat_forever" : "hw_repeat", node.id);
      if (!node.forever && node.times != null) block.setFieldValue(String(node.times), "TIMES");
      attach(workspace, node.child as Node, null, block.getInput("DO"));
      return block;
    }
    case "wait": {
      if (node.seconds != null) {
        const block = create(workspace, "hw_wait", node.id);
        block.setFieldValue(String(node.seconds), "SECONDS");
        return block;
      }
      const block = create(workspace, "hw_wait_random", node.id);
      block.setFieldValue(String(node.min ?? 0), "MIN");
      block.setFieldValue(String(node.max ?? 0), "MAX");
      return block;
    }
    case "if": {
      const block = create(workspace, "hw_if", node.id);
      plugCondition(workspace, block, node.condition as Node | null);
      attach(workspace, node.then as Node, null, block.getInput("THEN"));
      if (node.else) attach(workspace, node.else as Node, null, block.getInput("ELSE"));
      return block;
    }
    case "wait_until": {
      const block = create(workspace, "hw_wait_until", node.id);
      plugCondition(workspace, block, node.condition as Node | null);
      if (node.timeout_s != null) block.setFieldValue(String(node.timeout_s), "TIMEOUT");
      return block;
    }
    case "call":
      return create(workspace, "hw_call", node.id, { program_id: node.program_id });
    case "log": {
      const block = create(workspace, "hw_log", node.id);
      block.setFieldValue(String(node.message ?? ""), "MESSAGE");
      return block;
    }
    default:
      throw new Error(`nœud non pris en charge par l'éditeur : ${node.type}`);
  }
}

/** Hauteur approximative d'une pile, pour ranger les scripts sans mise en page enregistrée. */
function estimatedHeight(hat: Blockly.Block): number {
  return 70 + 48 * hat.getDescendants(false).length;
}

export function loadProgram(workspace: Blockly.Workspace, program: Program): void {
  Blockly.Events.disable();
  try {
    workspace.clear();
    const layout = (program.editor ?? undefined) as EditorLayout | undefined;
    let nextY = 20;
    for (const script of program.scripts) {
      const hat = create(workspace, "hw_start", script.id);
      attach(workspace, script.root as unknown as Node, hat, null);
      const saved = layout?.blocks?.[script.id];
      if (saved) {
        hat.moveBy(saved.x, saved.y);
      } else {
        hat.moveBy(20, nextY); // mise en page automatique : une pile sous l'autre
        nextY += estimatedHeight(hat) + 30;
      }
    }
    for (const id of layout?.collapsed ?? []) workspace.getBlockById(id)?.setCollapsed(true);
    renderAll(workspace);
  } finally {
    Blockly.Events.enable();
  }
}

/** Dans un espace affiché, les blocs créés par code doivent recevoir leur SVG puis être dessinés. */
export function renderAll(workspace: Blockly.Workspace): void {
  if (!(workspace instanceof Blockly.WorkspaceSvg)) return;
  for (const block of workspace.getAllBlocks(true) as Blockly.BlockSvg[]) block.initSvg();
  for (const block of workspace.getTopBlocks(false) as Blockly.BlockSvg[]) block.render();
}
