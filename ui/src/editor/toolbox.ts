import type { Devices } from "../catalog/CatalogProvider";

type Entry = { kind: "block"; type: string; extraState?: object };

/** Palette : catégories colorées ; les blocs de composants viennent du catalogue du moteur. */
export function buildToolbox(devices: Devices | null) {
  const relays: Entry[] = (devices?.relays ?? []).map((r) => ({ kind: "block", type: "hw_relay", extraState: { target: r.id } }));
  return {
    kind: "categoryToolbox",
    contents: [
      { kind: "category", name: "Contrôle", colour: "36", contents: [{ kind: "block", type: "hw_start" }] },
      { kind: "category", name: "Relais", colour: "0", contents: relays },
    ],
  };
}
