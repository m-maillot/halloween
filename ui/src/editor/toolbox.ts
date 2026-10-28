import type { Devices } from "../catalog/CatalogProvider";

type Entry = { kind: "block"; type: string; extraState?: object };

type LightItem = { id: string; supports_color?: boolean; supports_brightness?: boolean; supports_transition?: boolean };

/** Second bloc par lumière : déjà réglé, avec les paramètres que la lumière gère cochés et visibles. */
function tunedLights(lights: LightItem[] | undefined): Entry[] {
  return (lights ?? [])
    .filter((light) => light.supports_color || light.supports_brightness || light.supports_transition)
    .map((light) => ({ kind: "block", type: "hw_light", extraState: { target: light.id, tuned: true } }));
}

/** Palette : catégories colorées ; les blocs de composants viennent du catalogue du moteur. */
export function buildToolbox(devices: Devices | null) {
  const entries = (type: string, items: { id: string }[] | undefined): Entry[] =>
    (items ?? []).map((item) => ({ kind: "block", type, extraState: { target: item.id } }));
  return {
    kind: "categoryToolbox",
    contents: [
      {
        kind: "category",
        name: "Contrôle",
        colour: "36",
        contents: ["hw_start", "hw_parallel", "hw_repeat", "hw_repeat_forever", "hw_wait", "hw_wait_random", "hw_if", "hw_wait_until", "hw_random_choice", "hw_call"].map(
          (type) => ({ kind: "block", type }),
        ),
      },
      {
        kind: "category",
        name: "Conditions",
        colour: "290",
        contents: [
          ...(devices?.buttons ?? []).map((b) => ({ kind: "block", type: "hw_cond_button", extraState: { button: b.id } })),
          ...(devices?.relays ?? []).map((r) => ({ kind: "block", type: "hw_cond_relay_is", extraState: { relay: r.id } })),
          { kind: "block", type: "hw_cond_random" },
        ],
      },
      { kind: "category", name: "Relais", colour: "0", contents: entries("hw_relay", devices?.relays) },
      { kind: "category", name: "Lumières", colour: "48", contents: [...entries("hw_light", devices?.lights), ...tunedLights(devices?.lights)] },
      { kind: "category", name: "Interrupteurs", colour: "200", contents: entries("hw_switch", devices?.switches) },
      { kind: "category", name: "Divers", colour: "230", contents: [{ kind: "block", type: "hw_log" }] },
    ],
  };
}
