// Catalogue des composants vu par les blocs : les blocs sont enregistrés une fois pour toutes,
// leur forme dépend de ce catalogue, mis à jour quand le moteur annonce un changement.
import type { Devices } from "../catalog/CatalogProvider";

export type ComponentKind = "relay" | "light" | "switch" | "button";

let devices: Devices | null = null;
let programs: { id: string; name: string }[] = [];

export function setCatalog(next: Devices | null): void {
  devices = next;
}

export function setPrograms(next: { id: string; name: string }[]): void {
  programs = next;
}

export function listPrograms(): { id: string; name: string }[] {
  return programs;
}

export function findRelay(id: string) {
  return devices?.relays.find((c) => c.id === id);
}
export function findLight(id: string) {
  return devices?.lights.find((c) => c.id === id);
}
export function findSwitch(id: string) {
  return devices?.switches.find((c) => c.id === id);
}
export function listButtons() {
  return devices?.buttons ?? [];
}
export function listRelays() {
  return devices?.relays ?? [];
}
