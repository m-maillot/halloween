import type { ProgramSummary } from "../dashboard/useLive";

/** Les scénarios cochés « afficher en mode spectacle », dans l'ordre choisi (sans ordre : à la fin, par nom). */
export function showOrder(programs: ProgramSummary[]): ProgramSummary[] {
  return programs
    .filter((p) => p.show)
    .sort((a, b) => (a.show_order ?? Infinity) - (b.show_order ?? Infinity) || a.name.localeCompare(b.name, "fr"));
}
