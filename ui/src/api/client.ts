import createClient, { type Middleware } from "openapi-fetch";
import type { paths } from "./schema";
import { currentToken, setToken } from "./token";

const auth: Middleware = {
  onRequest({ request }) {
    const token = currentToken();
    if (token) request.headers.set("Authorization", `Bearer ${token}`);
    return request;
  },
  onResponse({ response }) {
    // Jeton refusé : on l'oublie, l'écran de saisie réapparaît. Un 401 « code incorrect » (lancement,
    // déverrouillage) n'est pas un jeton refusé : seul le refus du jeton porte `WWW-Authenticate`.
    if (response.status === 401 && response.headers.has("WWW-Authenticate")) setToken(null);
    return response;
  },
};

// Même origine que l'interface : le moteur sert les fichiers et l'API sur le même port.
export const api = createClient<paths>({
  baseUrl: globalThis.location?.origin ?? "",
  // `fetch` est résolu à chaque appel (et non à la création) : les tests peuvent le remplacer.
  fetch: (request) => globalThis.fetch(request),
});
api.use(auth);
