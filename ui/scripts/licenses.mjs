// Rassemble les licences des dépendances embarquées dans le build (dist/LICENSES.txt) : leurs textes
// exigent d'être livrés avec le logiciel. Échoue si un texte de licence manque.
import { existsSync, readdirSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";

const pkg = JSON.parse(readFileSync("package.json", "utf-8"));
const parts = [];
const missing = [];
for (const name of Object.keys(pkg.dependencies).sort()) {
  const dir = join("node_modules", name);
  const meta = JSON.parse(readFileSync(join(dir, "package.json"), "utf-8"));
  const file = readdirSync(dir).find((f) => /^(licen[cs]e|copying)(\.|$)/i.test(f));
  if (!file) {
    missing.push(name);
    continue;
  }
  parts.push(`${"=".repeat(78)}\n${name} ${meta.version} — ${typeof meta.license === "string" ? meta.license : "voir ci-dessous"}\n${"=".repeat(78)}\n\n${readFileSync(join(dir, file), "utf-8").trim()}\n`);
}
if (missing.length) {
  console.error(`Texte de licence introuvable pour : ${missing.join(", ")}`);
  process.exit(1);
}
if (!existsSync("dist")) throw new Error("dist/ absent : lancer vite build d'abord");
writeFileSync("dist/LICENSES.txt", `Licences des logiciels embarqués dans l'interface Déco Halloween\n\n${parts.join("\n")}`);
console.log(`dist/LICENSES.txt : ${parts.length} licences`);
