// Brouillon de formulaire : les nombres restent du texte tant que la saisie n'est pas validée.
import type { Devices } from "./CatalogProvider";
import type { Kind } from "./icons";

export type Existing =
  | Devices["relays"][number]
  | Devices["buttons"][number]
  | Devices["lights"][number]
  | Devices["switches"][number]
  | Devices["players"][number];

export interface VideoDraft {
  id: string;
  name: string;
  source: string;
  duration_s: string;
}

export interface Draft {
  kind: "button" | "motion";
  name: string;
  image: string | null;
  pin: string;
  mode: "latched" | "push";
  active_low: boolean;
  max_on_seconds: string;
  pulse_ms: string;
  animation_s: string;
  pull: "up" | "down";
  debounce_ms: string;
  long_press_ms: string;
  double_press_ms: string;
  warmup_s: string;
  entity_id: string;
  supports_color: boolean;
  supports_brightness: boolean;
  supports_transition: boolean;
  videos: VideoDraft[];
  rest_video: string;
}

const text = (value: number | null | undefined, fallback = "") => (value == null ? fallback : String(value));

export function draftOf(existing?: Existing): Draft {
  const e = (existing ?? {}) as Partial<Record<keyof Draft | "script", unknown>>;
  return {
    kind: (e.kind as Draft["kind"]) ?? "button",
    name: (e.name as string) ?? "",
    image: (e.image as string | null | undefined) ?? null,
    pin: text(e.pin as number | undefined),
    mode: (e.mode as Draft["mode"]) ?? "latched",
    active_low: Boolean(e.active_low),
    max_on_seconds: text(e.max_on_seconds as number | null | undefined),
    pulse_ms: text(e.pulse_ms as number | null | undefined),
    animation_s: text(e.animation_s as number | null | undefined),
    pull: (e.pull as Draft["pull"]) ?? "up",
    debounce_ms: text(e.debounce_ms as number | undefined, "50"),
    long_press_ms: text(e.long_press_ms as number | undefined, "800"),
    double_press_ms: text(e.double_press_ms as number | undefined, "400"),
    warmup_s: text(e.warmup_s as number | undefined, "60"),
    // Un lecteur désigne un script Home Assistant : même champ de saisie qu'une entité.
    entity_id: (e.entity_id as string) ?? (e.script as string) ?? "",
    supports_color: Boolean(e.supports_color),
    supports_brightness: Boolean(e.supports_brightness),
    supports_transition: Boolean(e.supports_transition),
    videos: ((e.videos as Devices["players"][number]["videos"] | undefined) ?? []).map((v) => ({
      id: v.id,
      name: v.name,
      source: v.source,
      duration_s: text(v.duration_s),
    })),
    rest_video: (e.rest_video as string | null | undefined) ?? "",
  };
}

const num = (value: string): number | null => (value.trim() === "" ? null : Number(value.replace(",", ".")));

/** Corps de requête du type de composant ; les champs qui ne le concernent pas sont omis. */
export function bodyOf(kind: Kind, draft: Draft): object {
  const common = { name: draft.name.trim(), image: draft.image };
  switch (kind) {
    case "relays":
      return {
        ...common,
        pin: num(draft.pin),
        mode: draft.mode,
        active_low: draft.active_low,
        ...(draft.mode === "latched"
          ? { max_on_seconds: num(draft.max_on_seconds) }
          : { pulse_ms: num(draft.pulse_ms), animation_s: num(draft.animation_s) }),
      };
    case "buttons":
      return {
        ...common,
        kind: draft.kind,
        pin: num(draft.pin),
        pull: draft.pull,
        debounce_ms: num(draft.debounce_ms),
        ...(draft.kind === "motion"
          ? { warmup_s: num(draft.warmup_s) }
          : { long_press_ms: num(draft.long_press_ms), double_press_ms: num(draft.double_press_ms) }),
      };
    case "lights":
      return {
        ...common,
        entity_id: draft.entity_id.trim(),
        supports_color: draft.supports_color,
        supports_brightness: draft.supports_brightness,
        supports_transition: draft.supports_transition,
      };
    case "switches":
      return { ...common, entity_id: draft.entity_id.trim() };
    case "players": {
      const taken = new Set(draft.videos.map((v) => v.id).filter(Boolean));
      // Un identifiant ne change jamais une fois attribué (les scénarios s'y réfèrent).
      const ids = draft.videos.map((video) => {
        const id = video.id || uniqueId(video.name, taken);
        taken.add(id);
        return id;
      });
      return {
        ...common,
        script: draft.entity_id.trim(),
        videos: draft.videos.map((video, i) => ({
          id: ids[i],
          name: video.name.trim(),
          source: video.source.trim(),
          duration_s: num(video.duration_s),
        })),
        rest_video: restKey(draft.rest_video, ids) || null,
      };
    }
  }
}

/** Vidéo de repos : un identifiant, ou `#<rang>` tant que la vidéo n'est pas enregistrée. */
export const pendingKey = (index: number) => `#${index}`;
function restKey(value: string, ids: string[]): string {
  return value.startsWith("#") ? (ids[Number(value.slice(1))] ?? "") : value;
}

/** Identifiant technique tiré du nom : minuscules sans accents, tirets, unique parmi `taken`. */
export function uniqueId(name: string, taken: Set<string>): string {
  const base =
    name
      .normalize("NFD")
      .replace(/[\u0300-\u036f]/g, "")
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "")
      .slice(0, 56) || "video";
  let candidate = base;
  for (let n = 2; taken.has(candidate); n++) candidate = `${base}-${n}`;
  return candidate;
}

/** Broches BCM déjà prises par un autre composant (relais ou bouton) : nom du propriétaire. */
export function usedPins(devices: Devices, ignoreId?: string): Map<number, string> {
  const used = new Map<number, string>();
  for (const item of [...devices.relays, ...devices.buttons]) {
    if (item.id !== ignoreId) used.set(item.pin, item.name);
  }
  return used;
}
