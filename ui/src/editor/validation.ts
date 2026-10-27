// Problèmes d'un programme : ceux du moteur (`POST /programs/validate`) et les contrôles locaux
// immédiats de la spec §5.5. Tout est localisé par identifiant de nœud, donc par bloc.
import * as Blockly from "blockly/core";
import { findRelay } from "./catalog";
import { nodeId, orphanStacks, type Node, type Program } from "./serialize";

export interface EditorIssue {
  severity: "error" | "warning";
  code: string;
  message: string;
  node_id?: string | null;
  component_id?: string | null;
}

/** Parcourt un nœud et tous ses descendants (enfants, branches, choix). */
export function* walkNodes(node: Node): Generator<Node> {
  yield node;
  const kids: Node[] = [];
  const o = node as Record<string, unknown>;
  if (Array.isArray(o.children)) kids.push(...(o.children as Node[]));
  if (o.child) kids.push(o.child as Node);
  if (o.then) kids.push(o.then as Node);
  if (o.else) kids.push(o.else as Node);
  if (Array.isArray(o.choices)) kids.push(...(o.choices as { child: Node }[]).map((c) => c.child));
  for (const kid of kids) yield* walkNodes(kid);
}

/**
 * Contrôles qui n'ont pas besoin du moteur, donc immédiats et sans réseau. Les conflits de composant
 * entre scripts et les boucles sans attente sont déjà signalés par le moteur : pas redoublés ici.
 */
export function localIssues(program: Program): EditorIssue[] {
  const issues: EditorIssue[] = [];
  const nodes = program.scripts.flatMap((s) => [...walkNodes(s.root as unknown as Node)]);

  // Un relais maintenu allumé et jamais éteint : l'état de repos s'en chargera, mais c'est rarement voulu.
  const turnedOff = new Set(nodes.filter((n) => n.type === "relay" && n.state === "off").map((n) => n.target as string));
  const reported = new Set<string>();
  for (const node of nodes) {
    if (node.type !== "relay" || node.state !== "on") continue;
    const target = node.target as string;
    if (turnedOff.has(target) || reported.has(target)) continue;
    const relay = findRelay(target);
    if (relay && relay.mode !== "latched") continue;
    reported.add(target);
    issues.push({
      severity: "warning",
      code: "local_never_off",
      message: `« ${relay?.name ?? target} » est allumé mais jamais éteint dans ce scénario (l'état de repos l'éteindra à la fin).`,
      node_id: node.id,
      component_id: target,
    });
  }

  // « si » et « attendre jusqu'à » sans condition branchée : le moteur répond par un message technique.
  for (const node of nodes) {
    if ((node.type === "if" || node.type === "wait_until") && !node.condition) {
      issues.push({
        severity: "error",
        code: "local_missing_condition",
        message: node.type === "if" ? "Branchez une condition sur ce « si »." : "Branchez une condition sur ce « attendre jusqu'à ».",
        node_id: node.id,
      });
    }
  }

  // Une boucle sans fin sans durée maximale ne se termine que par STOP.
  if (program.max_duration_s == null) {
    for (const node of nodes) {
      if (node.type === "repeat" && node.forever) {
        issues.push({
          severity: "warning",
          code: "local_endless",
          message: "Boucle sans fin et aucune durée maximale : le scénario ne s'arrêtera qu'avec STOP.",
          node_id: node.id,
        });
      }
    }
  }
  return issues;
}

const CONTAINER = /^(.*)_(root|b\d+|c\d+|do|then|else|cond)$/;

/** Bloc d'un identifiant de nœud ; les conteneurs implicites (pile, branche) renvoient leur propriétaire. */
export function resolveBlock(workspace: Blockly.Workspace, id: string): Blockly.Block | null {
  const byNode = new Map<string, Blockly.Block>();
  for (const block of workspace.getAllBlocks(false)) byNode.set(nodeId(block), block);
  const direct = byNode.get(id);
  if (direct) return direct;
  const match = CONTAINER.exec(id);
  return match ? (byNode.get(match[1]) ?? null) : null;
}

export interface Located extends EditorIssue {
  /** Identifiant Blockly du bloc concerné, si on l'a retrouvé. */
  blockId: string | null;
}

export function locate(workspace: Blockly.Workspace, issues: EditorIssue[]): Located[] {
  return issues.map((issue) => ({
    ...issue,
    blockId: issue.node_id ? (resolveBlock(workspace, issue.node_id)?.id ?? null) : null,
  }));
}

/** Blocs de tête de pile hors d'un bloc début : ignorés par le moteur, signalés. */
export function orphanIssues(workspace: Blockly.Workspace): Located[] {
  return orphanStacks(workspace).map((block) => ({
    severity: "warning" as const,
    code: "local_orphan",
    message: "Ce bloc n'est rattaché à aucun bloc « quand le scénario démarre » : il est ignoré.",
    node_id: nodeId(block),
    blockId: block.id,
  }));
}

export const ERROR_CLASS = "hw-block-error";
export const WARNING_CLASS = "hw-block-warning";

/** Entoure en rouge (erreur) ou orange (avertissement) les blocs fautifs ; efface le marquage précédent. */
export function markBlocks(workspace: Blockly.Workspace, issues: Located[]): void {
  if (!(workspace instanceof Blockly.WorkspaceSvg)) return;
  const severity = new Map<string, "error" | "warning">();
  for (const issue of issues) {
    if (!issue.blockId) continue;
    if (severity.get(issue.blockId) !== "error") severity.set(issue.blockId, issue.severity);
  }
  for (const block of workspace.getAllBlocks(false) as Blockly.BlockSvg[]) {
    const root = block.getSvgRoot();
    if (!root) continue;
    const level = severity.get(block.id);
    root.classList.toggle(ERROR_CLASS, level === "error");
    root.classList.toggle(WARNING_CLASS, level === "warning");
  }
}

export function summary(issues: EditorIssue[]): { errors: number; warnings: number } {
  return {
    errors: issues.filter((i) => i.severity === "error").length,
    warnings: issues.filter((i) => i.severity === "warning").length,
  };
}


const PHRASES: [RegExp, (m: RegExpExecArray) => string][] = [
  [/^Field required$/, () => "champ obligatoire"],
  [/^Input should be a valid (dictionary|object).*$/, () => "valeur manquante ou invalide"],
  [/^Input should be greater than or equal to (.+)$/, (m) => `doit être supérieur ou égal à ${m[1]}`],
  [/^Input should be greater than (.+)$/, (m) => `doit être supérieur à ${m[1]}`],
  [/^Input should be less than or equal to (.+)$/, (m) => `doit être inférieur ou égal à ${m[1]}`],
  [/^Input should be less than (.+)$/, (m) => `doit être inférieur à ${m[1]}`],
  [/^Input should be a valid (number|integer).*$/, () => "doit être un nombre"],
  [/^String should have at least (\d+) character.*$/, () => "ne peut pas être vide"],
  [/^Input should be (.+)$/, (m) => `valeur attendue : ${m[1]}`],
];

/**
 * Les erreurs de forme (`invalid`) du moteur citent un chemin et un message de bibliothèque en anglais.
 * On en garde le nom du champ et on traduit les formulations courantes ; le reste est laissé tel quel.
 */
export function friendly(issue: EditorIssue): EditorIssue {
  if (issue.code !== "invalid") return issue;
  const split = issue.message.indexOf(" : ");
  const path = split >= 0 ? issue.message.slice(0, split) : "";
  const raw = split >= 0 ? issue.message.slice(split + 3) : issue.message;
  const field = path.split(".").filter((p) => !/^\d+$/.test(p)).at(-1);
  const hit = PHRASES.map(([re, f]) => ({ m: re.exec(raw), f })).find((x) => x.m);
  const text = hit ? hit.f(hit.m!) : raw;
  return { ...issue, message: field ? `${field} : ${text}` : text };
}
