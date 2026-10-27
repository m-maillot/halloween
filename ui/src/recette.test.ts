// Traçabilité de la recette : chaque test cité dans docs/recette-jalon-b.md existe encore, sous ce nom.
import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import { expect, test } from "vitest";

const root = resolve(__dirname, "../..");
const doc = readFileSync(resolve(root, "docs/recette-jalon-b.md"), "utf-8");
const references = [...doc.matchAll(/`((?:ui|engine)\/[^`:]+)(?:::([^`]+))?`/g)].map((m) => ({ file: m[1], title: m[2] }));

test("la recette cite des tests", () => {
  expect(references.filter((r) => r.title).length).toBeGreaterThanOrEqual(30);
});

test.each(references.map((r) => [`${r.file}${r.title ? "::" + r.title : ""}`, r] as const))("%s existe", (_label, ref) => {
  const path = resolve(root, ref.file);
  expect(existsSync(path), `fichier introuvable : ${ref.file}`).toBe(true);
  if (ref.title) expect(readFileSync(path, "utf-8")).toContain(`"${ref.title}"`);
});

test("chaque critère de la spec 2 (1 à 11, avec 6b) figure dans le tableau de la recette", () => {
  for (const id of ["1", "2", "3", "4", "5", "6", "6b", "7", "8", "9", "10", "11"]) {
    expect(doc, `critère ${id}`).toMatch(new RegExp(`^\\| ${id} \\|`, "m"));
  }
});
