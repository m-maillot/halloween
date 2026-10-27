// Brouillon local : ce qui est à l'écran, gardé dans le navigateur tant que ce n'est pas enregistré.
import type { Program } from "./serialize";

const key = (programId: string) => `halloween.draft.${programId}`;

export interface Draft {
  /** Révision du programme sur laquelle le brouillon a été commencé. */
  baseRevision: number;
  savedAt: number;
  program: Program;
}

export function readDraft(programId: string): Draft | null {
  try {
    const raw = localStorage.getItem(key(programId));
    return raw ? (JSON.parse(raw) as Draft) : null;
  } catch {
    return null; // stockage indisponible ou contenu illisible : comme s'il n'y en avait pas
  }
}

export function writeDraft(programId: string, draft: Draft): void {
  try {
    localStorage.setItem(key(programId), JSON.stringify(draft));
  } catch {
    // quota dépassé ou navigation privée : le brouillon est un confort, pas une garantie
  }
}

export function clearDraft(programId: string): void {
  try {
    localStorage.removeItem(key(programId));
  } catch {
    // rien à faire
  }
}
