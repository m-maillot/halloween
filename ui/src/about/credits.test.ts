import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { expect, test } from "vitest";
import { BUILTIN_ICONS, sourceOf } from "../catalog/icons";
import { GAME_ICONS } from "../catalog/gameIconsData";
import { ICON_SOURCES, SOFTWARE, gameIconAuthors, iconCounts } from "./credits";

const pkg = (name: string) => JSON.parse(readFileSync(resolve(__dirname, "../../node_modules", name, "package.json"), "utf-8"));

test("la bibliothèque compte une trentaine d'icônes au moins, chacune avec une origine déclarée", () => {
  const names = Object.keys(BUILTIN_ICONS);
  expect(names.length).toBeGreaterThanOrEqual(30);
  for (const name of names) expect(Object.keys(ICON_SOURCES)).toContain(sourceOf(name));
  const counts = iconCounts();
  expect(counts.lucide + counts.feather + counts["game-icons"]).toBe(names.length);
  expect(counts["game-icons"]).toBeGreaterThanOrEqual(30);
});

test("les noms des icônes sont acceptés par le moteur (`builtin:<nom>`)", () => {
  for (const name of Object.keys(BUILTIN_ICONS)) expect(`builtin:${name}`).toMatch(/^builtin:[a-z0-9][a-z0-9-]{0,63}$/);
});

test("les icônes issues de Feather sont bien celles que Lucide déclare dérivées (licence MIT à citer)", () => {
  const license = readFileSync(resolve(__dirname, "../../node_modules/lucide-react/LICENSE"), "utf-8");
  const derived = license.split("The following Lucide icons are derived from the Feather project:")[1].split("The MIT License")[0];
  const names = derived.split(",").map((n) => n.trim());
  for (const [name, icon] of Object.entries(BUILTIN_ICONS)) {
    if (icon.source === "feather") expect(names).toContain(icon.icon.displayName?.replace(/([a-z])([A-Z])/g, "$1-$2").toLowerCase());
    void name;
  }
});

test("les licences déclarées correspondent à celles des paquets embarqués", () => {
  const expected: Record<string, string> = { React: "react", Blockly: "blockly", "openapi-fetch": "openapi-fetch", "React Router": "react-router-dom" };
  for (const [label, name] of Object.entries(expected)) {
    const declared = SOFTWARE.find((c) => c.name === label)!.license;
    expect(declared.replace("SIL OFL 1.1", "OFL-1.1")).toBe(pkg(name).license);
  }
  expect(pkg("lucide-react").license).toBe("ISC");
  expect(pkg("@fontsource-variable/fraunces").license).toBe("OFL-1.1");
  expect(pkg("@fontsource-variable/inter").license).toBe("OFL-1.1");
});

test("chaque icône game-icons.net a un auteur déclaré, nommé dans les crédits, et une source dans le fichier de licence livré", () => {
  const licence = readFileSync(resolve(__dirname, "../../public/GAME-ICONS-LICENSE.txt"), "utf-8");
  const credited = gameIconAuthors();
  const named = new Set(credited.map((a) => a.key));
  for (const [name, icon] of Object.entries(BUILTIN_ICONS)) {
    if (icon.source !== "game-icons") continue;
    expect(icon.author, name).toBeTruthy();
    expect(named.has(icon.author!), `${name} : auteur ${icon.author} absent des crédits`).toBe(true);
    expect(licence, name).toContain(`- ${name} (`);
  }
  expect(credited.reduce((n, a) => n + a.icons.length, 0)).toBe(iconCounts()["game-icons"]);
  expect(licence).toContain("Creative Commons Attribution 3.0");
  expect(licence).toContain("Icons made by {author}");
});

test("les tracés game-icons.net sont de vrais tracés sur la grille 512", () => {
  for (const [name, icon] of Object.entries(GAME_ICONS)) {
    expect(icon.d, name).toMatch(/^M[\d.\s-]/);
    expect(icon.d.length, name).toBeGreaterThan(200);
    expect(icon.d, name).not.toContain("M0 0h512v512H0z"); // le fond noir d'origine n'est pas reproduit
  }
});
