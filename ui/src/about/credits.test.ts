import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { expect, test } from "vitest";
import { BUILTIN_ICONS, sourceOf } from "../catalog/icons";
import { ICON_SOURCES, SOFTWARE, iconCounts } from "./credits";

const pkg = (name: string) => JSON.parse(readFileSync(resolve(__dirname, "../../node_modules", name, "package.json"), "utf-8"));

test("la bibliothèque compte une trentaine d'icônes au moins, chacune avec une origine déclarée", () => {
  const names = Object.keys(BUILTIN_ICONS);
  expect(names.length).toBeGreaterThanOrEqual(30);
  for (const name of names) expect(Object.keys(ICON_SOURCES)).toContain(sourceOf(name));
  const counts = iconCounts();
  expect(counts.lucide + counts.feather + counts.project).toBe(names.length);
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
