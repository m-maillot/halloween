import { BUILTIN_ICONS, sourceOf, type IconSource } from "../catalog/icons";
import { GAME_ICON_AUTHORS } from "../catalog/gameIconsData";

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
  "game-icons": {
    name: "game-icons.net",
    license: "CC BY 3.0",
    author: "voir la liste des auteurs ci-dessous",
    note: "https://game-icons.net, fond retiré et couleur du thème",
  },
};

/** Nombre d'icônes de la bibliothèque par origine. */
export function iconCounts(): Record<IconSource, number> {
  const counts: Record<IconSource, number> = { lucide: 0, feather: 0, "game-icons": 0 };
  for (const name of Object.keys(BUILTIN_ICONS)) counts[sourceOf(name)] += 1;
  return counts;
}

export interface AuthorCredit {
  key: string;
  name: string;
  url?: string;
  icons: string[];
}

/** Auteurs des icônes game-icons.net utilisées, avec leurs icônes (la licence CC BY exige de les nommer). */
export function gameIconAuthors(): AuthorCredit[] {
  const byAuthor = new Map<string, string[]>();
  for (const icon of Object.values(BUILTIN_ICONS)) {
    if (!icon.author) continue;
    byAuthor.set(icon.author, [...(byAuthor.get(icon.author) ?? []), icon.label]);
  }
  return [...byAuthor.entries()]
    .map(([key, icons]) => ({ key, ...GAME_ICON_AUTHORS[key], icons: icons.sort((a, b) => a.localeCompare(b, "fr")) }))
    .sort((a, b) => b.icons.length - a.icons.length || a.name.localeCompare(b.name));
}
