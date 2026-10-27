import { expect, test } from "vitest";
import { ApiError, describe, describeError, unwrap } from "./errors";

test("verrouillé : message du moteur conservé", () => {
  const d = describe(423, { detail: { message: "verrouillé : déverrouiller avec le code pour modifier", issues: [] } });
  expect(d.title).toBe("verrouillé : déverrouiller avec le code pour modifier");
  expect(d.details).toEqual([]);
});

test("les problèmes localisés deviennent des lignes avec le bloc ou le composant", () => {
  const d = describe(422, {
    detail: {
      message: "programme invalide",
      issues: [
        { message: "durée négative", node_id: "w" },
        { message: "GPIO 18 déjà utilisée", component_id: "fantome" },
        { message: "autre" },
      ],
    },
  });
  expect(d.details).toEqual(["bloc w : durée négative", "composant fantome : GPIO 18 déjà utilisée", "autre"]);
});

test("la validation FastAPI donne une ligne par champ", () => {
  const d = describe(422, { detail: [{ loc: ["body", "pin"], msg: "doit être ≤ 27" }, { loc: [], msg: "x" }] });
  expect(d.title).toBe("Les données sont invalides.");
  expect(d.details).toEqual(["pin : doit être ≤ 27", "x"]);
});

test("trop d'essais : le délai est repris", () => {
  const d = describe(429, { detail: { message: "trop d'essais : réessayer dans 30 s", issues: [], retry_after_s: 30 } });
  expect(d.retryAfter).toBe(30);
});

test("détail texte, corps absent ou statut inconnu", () => {
  expect(describe(401, { detail: "jeton d'API manquant ou invalide" }).title).toBe("jeton d'API manquant ou invalide");
  expect(describe(412, undefined).title).toMatch(/modifié ailleurs/);
  expect(describe(418, null).title).toBe("Le moteur a répondu une erreur (418).");
});

test("une coupure réseau est « Moteur injoignable »", () => {
  expect(describeError(new TypeError("fetch failed"))).toEqual({
    title: "Moteur injoignable.",
    details: ["fetch failed"],
  });
  expect(describeError(new ApiError(502, { detail: { message: "Home Assistant injoignable", issues: [] } })).title).toBe(
    "Home Assistant injoignable",
  );
});

test("unwrap rend les données ou lève ApiError", async () => {
  const ok = await unwrap(Promise.resolve({ data: { a: 1 }, response: new Response() }));
  expect(ok).toEqual({ a: 1 });
  await expect(
    unwrap(Promise.resolve({ error: { detail: "non" }, response: new Response(null, { status: 404 }) })),
  ).rejects.toMatchObject({ status: 404 });
});
