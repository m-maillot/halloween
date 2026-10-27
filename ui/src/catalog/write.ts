// Écritures du catalogue. Les chemins `/api/components/{kind}` existent en quatre exemplaires dans
// le contrat ; un seul point les assemble, plutôt que douze appels quasi identiques.
import { api } from "../api/client";
import { unwrap } from "../api/errors";
import type { Kind } from "./icons";

type Raw = <T>(path: string, init?: object) => Promise<{ data?: T; error?: unknown; response: Response }>;
const raw = api as unknown as { POST: Raw; PUT: Raw; DELETE: Raw };

export interface Saved {
  component: { id: string };
  issues: { message: string }[];
}

export function saveComponent(kind: Kind, id: string | null, body: object, stopRuns: boolean): Promise<Saved> {
  const query = { stop_runs: stopRuns };
  return unwrap<Saved>(
    id === null
      ? raw.POST(`/api/components/${kind}`, { body, params: { query } })
      : raw.PUT(`/api/components/${kind}/{component_id}`, { body, params: { path: { component_id: id }, query } }),
  );
}

export async function deleteComponent(kind: Kind, id: string, stopRuns: boolean): Promise<void> {
  await unwrap<unknown>(
    raw.DELETE(`/api/components/${kind}/{component_id}`, {
      params: { path: { component_id: id }, query: { stop_runs: stopRuns } },
    }),
  );
}

export interface Uploaded {
  image: string;
  url: string;
}

/** Recadre au carré, centré (sans interaction) ; l'image d'origine est renvoyée si le navigateur ne sait pas. */
export async function cropSquare(file: File): Promise<Blob> {
  try {
    const bitmap = await createImageBitmap(file);
    const side = Math.min(bitmap.width, bitmap.height);
    if (bitmap.width === bitmap.height) return file;
    const canvas = document.createElement("canvas");
    canvas.width = canvas.height = side;
    const context = canvas.getContext("2d");
    if (!context) return file;
    context.drawImage(bitmap, (bitmap.width - side) / 2, (bitmap.height - side) / 2, side, side, 0, 0, side, side);
    const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, file.type));
    return blob ?? file;
  } catch {
    return file;
  }
}

export async function uploadImage(file: File): Promise<Uploaded> {
  const blob = await cropSquare(file);
  return unwrap<Uploaded>(
    raw.POST("/api/images", {
      body: blob,
      bodySerializer: (body: unknown) => body,
      headers: { "Content-Type": file.type },
    }),
  );
}
