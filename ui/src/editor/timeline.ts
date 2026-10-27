// Frise temporelle : transforme la liste de commandes de `POST /simulate` en périodes d'activation.
import type { components } from "../api/schema";

export type SimulationOut = components["schemas"]["SimulationOut"];

export interface Period {
  start: number;
  end: number;
  /** Encore allumé à la fin de la simulation (jamais éteint). */
  open: boolean;
  data: Record<string, unknown>;
}

export interface Row {
  component: string;
  periods: Period[];
}

const ON = new Set(["on", "light.turn_on", "switch.turn_on"]);
const OFF = new Set(["off", "light.turn_off", "switch.turn_off"]);

/**
 * Une ligne par composant (dans l'ordre de première commande), une période par activation. Un
 * second « allumer » sur un composant déjà allumé (changement de couleur) ferme la période en cours
 * et en ouvre une autre : la frise montre le changement. Un « éteindre » sur un composant éteint est ignoré.
 */
export function buildRows(result: SimulationOut): Row[] {
  const rows = new Map<string, Row>();
  const current = new Map<string, Period>();
  const events = [...result.timeline].sort((a, b) => a.t - b.t); // tri stable : l'ordre d'émission est gardé à égalité
  for (const event of events) {
    let row = rows.get(event.component);
    if (!row) rows.set(event.component, (row = { component: event.component, periods: [] }));
    const open = current.get(event.component);
    if (ON.has(event.action)) {
      if (open) open.end = event.t;
      const period: Period = { start: event.t, end: event.t, open: false, data: event.data ?? {} };
      row.periods.push(period);
      current.set(event.component, period);
    } else if (OFF.has(event.action) && open) {
      open.end = event.t;
      current.delete(event.component);
    }
  }
  for (const period of current.values()) {
    period.end = Math.max(period.end, result.duration_s);
    period.open = true;
  }
  return [...rows.values()];
}

const STEPS = [0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 1800, 3600];

/** Graduations « rondes » de l'axe : au plus `max` repères. */
export function ticks(duration: number, max = 10): number[] {
  const step = STEPS.find((s) => duration / s <= max) ?? STEPS[STEPS.length - 1];
  const result: number[] = [];
  for (let t = 0; t <= duration + 1e-9; t += step) result.push(Math.round(t * 1000) / 1000);
  return result;
}

export function formatSeconds(value: number): string {
  const rounded = Math.round(value * 10) / 10;
  return rounded >= 120 ? `${Math.floor(rounded / 60)} min ${Math.round(rounded % 60)} s` : `${rounded} s`;
}

export function statusMessage(result: SimulationOut): { tone: "ok" | "warn" | "error"; text: string } {
  const length = formatSeconds(result.duration_s);
  switch (result.status) {
    case "completed":
      return { tone: "ok", text: `Terminé en ${length}.` };
    case "timeout":
      return { tone: "warn", text: `Arrêté par la durée maximale du scénario (${length}).` };
    case "horizon":
      return { tone: "warn", text: `Simulation interrompue à ${length} : le scénario ne s'arrête pas de lui-même (boucle sans fin ?).` };
    case "deadlock":
      return { tone: "warn", text: "Bloqué : un « attendre jusqu'à » attend un appui de bouton qui n'arrive jamais. Ajoutez un appui simulé." };
    case "truncated":
      return { tone: "warn", text: "Simulation tronquée : trop de blocs exécutés (boucle sans attente ?)." };
    case "failed":
      return { tone: "error", text: `Échec de la simulation : ${result.error ?? "erreur inconnue"}.` };
  }
}
