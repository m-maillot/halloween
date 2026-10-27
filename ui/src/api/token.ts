// Jeton d'API du moteur, saisi une fois et gardé dans le navigateur (spec 2 §2).
const KEY = "halloween.token";
const listeners = new Set<() => void>();

export function getToken(): string | null {
  try {
    return localStorage.getItem(KEY);
  } catch {
    return null; // stockage indisponible (navigation privée...)
  }
}

export function setToken(token: string | null): void {
  try {
    if (token) localStorage.setItem(KEY, token);
    else localStorage.removeItem(KEY);
  } catch {
    /* le jeton ne sera pas mémorisé, l'application reste utilisable jusqu'au rechargement */
  }
  memory = token;
  listeners.forEach((l) => l());
}

let memory: string | null = null;

/** Jeton courant : celui du navigateur, ou celui saisi cette session si le stockage est bloqué. */
export function currentToken(): string | null {
  return getToken() ?? memory;
}

export function onTokenChange(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}
