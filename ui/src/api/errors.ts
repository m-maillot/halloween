// Traduit les erreurs du moteur (`detail: {message, issues[]}`, validation FastAPI, réseau)
// en un message lisible et des détails dépliables.

export interface Described {
  title: string;
  details: string[];
  /** Secondes avant de pouvoir réessayer (code faux répété), si le moteur l'indique. */
  retryAfter?: number;
}

export class ApiError extends Error {
  constructor(
    public status: number,
    public body: unknown,
  ) {
    super(describe(status, body).title);
  }
}

interface Issue {
  message?: string;
  node_id?: string | null;
  component_id?: string | null;
}

const BY_STATUS: Record<number, string> = {
  401: "Jeton ou code refusé.",
  403: "Action interdite.",
  404: "Élément introuvable.",
  409: "Conflit avec l'état actuel.",
  412: "Le scénario a été modifié ailleurs : rechargez-le avant d'enregistrer.",
  422: "Les données sont invalides.",
  423: "Interface verrouillée : déverrouillez-la pour modifier.",
  428: "Version du scénario manquante : rechargez-le.",
  429: "Trop de requêtes ou d'essais.",
  502: "Le périphérique ne répond pas.",
  503: "Le moteur redémarre, réessayez dans un instant.",
};

function validationLine(entry: unknown): string | null {
  if (typeof entry !== "object" || entry === null) return null;
  const { loc, msg } = entry as { loc?: unknown[]; msg?: string };
  if (!msg) return null;
  const field = Array.isArray(loc) ? loc.filter((p) => p !== "body").join(" › ") : "";
  return field ? `${field} : ${msg}` : msg;
}

function issueLine(issue: Issue): string {
  const where = issue.node_id ? `bloc ${issue.node_id}` : issue.component_id ? `composant ${issue.component_id}` : "";
  const text = issue.message ?? "problème non précisé";
  return where ? `${where} : ${text}` : text;
}

export function describe(status: number, body: unknown): Described {
  const fallback = BY_STATUS[status] ?? `Le moteur a répondu une erreur (${status}).`;
  const detail = (body as { detail?: unknown } | null)?.detail;
  if (Array.isArray(detail)) {
    // Validation FastAPI : une ligne par champ.
    const lines = detail.map(validationLine).filter((l): l is string => l !== null);
    return { title: fallback, details: lines };
  }
  if (typeof detail === "string") return { title: detail, details: [] };
  if (typeof detail === "object" && detail !== null) {
    const { message, issues, retry_after_s } = detail as {
      message?: string;
      issues?: Issue[];
      retry_after_s?: number;
    };
    return {
      title: message ?? fallback,
      details: (issues ?? []).map(issueLine),
      retryAfter: typeof retry_after_s === "number" ? retry_after_s : undefined,
    };
  }
  return { title: fallback, details: [] };
}

/** Message pour une exception quelconque (réseau coupé, ApiError...). */
export function describeError(error: unknown): Described {
  if (error instanceof ApiError) return describe(error.status, error.body);
  if (error instanceof TypeError) {
    return { title: "Moteur injoignable.", details: [error.message] };
  }
  return { title: "Erreur inattendue.", details: [String(error)] };
}

/** Déballe un résultat `openapi-fetch` : les données, ou une `ApiError`. */
export async function unwrap<T>(
  // `data` volontairement non typé : les types récursifs du contrat (blocs imbriqués) ne se
  // laissent pas comparer ; l'appelant nomme le type attendu.
  result: Promise<{ data?: unknown; error?: unknown; response: Response }>,
): Promise<T> {
  const { data, error, response } = await result;
  if (!response.ok) throw new ApiError(response.status, error);
  return data as T;
}

export interface FormErrors {
  /** Message par champ (dernier élément du chemin FastAPI : `body › pin` donne `pin`). */
  fields: Record<string, string>;
  /** Ce qui ne se rattache à aucun champ (règle de configuration, conflit...). */
  general?: Described;
}

/** Répartit une erreur d'enregistrement entre champs du formulaire et message général. */
export function formErrors(error: unknown): FormErrors {
  if (error instanceof ApiError) {
    const detail = (error.body as { detail?: unknown } | null)?.detail;
    if (Array.isArray(detail)) {
      const fields: Record<string, string> = {};
      const rest: string[] = [];
      for (const entry of detail as { loc?: unknown[]; msg?: string }[]) {
        const name = Array.isArray(entry.loc) ? entry.loc.filter((p) => p !== "body").at(-1) : undefined;
        if (typeof name === "string" && entry.msg) fields[name] ??= entry.msg;
        else if (entry.msg) rest.push(entry.msg);
      }
      return { fields, general: rest.length ? { title: BY_STATUS[422], details: rest } : undefined };
    }
  }
  return { fields: {}, general: describeError(error) };
}
