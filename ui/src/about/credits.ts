import { BUILTIN_ICONS, sourceOf, type IconSource } from "../catalog/icons";

export interface Credit {
  name: string;
  version?: string;
  license: string;
  author: string;
  note?: string;
}

/** Composants tiers embarqués dans l'interface (versions et licences lues dans les `package.json` à l'installation). */
export const SOFTWARE: Credit[] = [
  { name: "React", license: "MIT", author: "Meta Platforms, Inc. et contributeurs" },
  { name: "React Router", license: "MIT", author: "Remix Software, Inc. et contributeurs" },
  { name: "Blockly", license: "Apache-2.0", author: "Google LLC et contributeurs", note: "éditeur de blocs, avec son champ de couleur" },
  { name: "openapi-fetch", license: "MIT", author: "Drew Powers et contributeurs" },
  { name: "Fraunces (police des titres)", license: "SIL OFL 1.1", author: "Undercase Type" },
  { name: "Inter (police du texte)", license: "SIL OFL 1.1", author: "Rasmus Andersson" },
];

export const ICON_SOURCES: Record<IconSource, Credit> = {
  lucide: { name: "Lucide", license: "ISC", author: "Lucide Icons and Contributors", note: "https://lucide.dev" },
  feather: { name: "Feather (via Lucide)", license: "MIT", author: "Cole Bemis", note: "https://feathericons.com" },
  project: { name: "Icônes du projet", license: "propriété du projet", author: "dessinées pour ce projet", note: "citrouille, chauve-souris, araignée, épouvantail, chaudron, pierre tombale" },
};

/** Nombre d'icônes de la bibliothèque par origine. */
export function iconCounts(): Record<IconSource, number> {
  const counts: Record<IconSource, number> = { lucide: 0, feather: 0, project: 0 };
  for (const name of Object.keys(BUILTIN_ICONS)) counts[sourceOf(name)] += 1;
  return counts;
}
