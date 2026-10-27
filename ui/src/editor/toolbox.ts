import type { Devices } from "../catalog/CatalogProvider";

type Entry = { kind: "block"; type: string; extraState?: object };

/** Palette : catégories colorées ; les blocs de composants viennent du catalogue du moteur. */
export function buildToolbox(devices: Devices | null) {
  const entries = (type: string, items: { id: string }[] | undefined): Entry[] =>
    (items ?? []).map((item) => ({ kind: "block", type, extraState: { target: item.id } }));
  return {
    kind: "categoryToolbox",
    contents: [
      { kind: "category", name: "Contrôle", colour: "36", contents: [{ kind: "block", type: "hw_start" }] },
      { kind: "category", name: "Relais", colour: "0", contents: entries("hw_relay", devices?.relays) },
      { kind: "category", name: "Lumières", colour: "48", contents: entries("hw_light", devices?.lights) },
      { kind: "category", name: "Interrupteurs", colour: "200", contents: entries("hw_switch", devices?.switches) },
    ],
  };
}
