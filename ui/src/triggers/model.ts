import type { Devices } from "../catalog/CatalogProvider";

export type Policy = "ignore" | "restart" | "queue";
export type PressEvent = "short" | "long" | "double" | "motion";

export interface ButtonTrigger {
  id: string;
  source: "button";
  button: string;
  event: PressEvent;
  program?: string | null;
  action?: "stop" | null;
  policy: Policy;
  enabled: boolean;
}
export interface ScheduleTrigger {
  id: string;
  source: "schedule";
  cron: string;
  timezone?: string | null;
  program: string;
  policy: Policy;
  enabled: boolean;
}
export type Trigger = ButtonTrigger | ScheduleTrigger;

export const EVENT_LABEL: Record<PressEvent, string> = {
  short: "un appui court",
  long: "un appui long",
  double: "un double appui",
  motion: "un mouvement détecté",
};
/** Pour les journaux et listes : « appui court », « mouvement »… */
export const PRESS_TEXT: Record<PressEvent, string> = { short: "appui court", long: "appui long", double: "appui double", motion: "mouvement" };
/** Événements qu'une entrée peut produire : un détecteur ne détecte que le mouvement, un bouton jamais. */
export const eventsFor = (kind: string | undefined): PressEvent[] => (kind === "motion" ? ["motion"] : ["short", "long", "double"]);
export const POLICY_LABEL: Record<Policy, string> = {
  ignore: "ignorer s'il tourne déjà",
  restart: "le redémarrer s'il tourne déjà",
  queue: "le mettre en file s'il tourne déjà",
};

const slug = (text: string) =>
  text.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 40);

/** Identifiant libre pour une nouvelle règle (`regle-bouton-1`, `regle-planning-2`…). */
export function newId(triggers: Trigger[], source: Trigger["source"]): string {
  const taken = new Set(triggers.map((t) => t.id));
  const base = `regle-${slug(source === "button" ? "bouton" : "planning")}`;
  for (let n = 1; ; n++) if (!taken.has(`${base}-${n}`)) return `${base}-${n}`;
}

/** Les règles actives visant le même bouton et le même événement : le moteur les lancerait toutes. */
export function duplicates(triggers: Trigger[]): Map<string, string[]> {
  const byKey = new Map<string, string[]>();
  for (const t of triggers) {
    if (t.source !== "button" || !t.enabled) continue;
    const key = `${t.button}/${t.event}`;
    byKey.set(key, [...(byKey.get(key) ?? []), t.id]);
  }
  const clash = new Map<string, string[]>();
  for (const ids of byKey.values()) if (ids.length > 1) for (const id of ids) clash.set(id, ids.filter((other) => other !== id));
  return clash;
}

export function buttonName(devices: Devices | null, id: string): string {
  return devices?.buttons.find((b) => b.id === id)?.name ?? id;
}
