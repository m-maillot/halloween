// Image d'un composant pour un champ de bloc Blockly (qui attend une URL, pas un composant React).
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import type { LucideIcon } from "lucide-react";
import { BUILTIN_ICONS, DEFAULT_ICON, type Kind } from "../catalog/icons";

export function iconSource(image: string | null | undefined, imageUrl: string | null | undefined, kind: Kind = "relays"): string {
  if (imageUrl) return imageUrl;
  const fallback = DEFAULT_ICON[kind];
  const name = image?.startsWith("builtin:") ? image.slice("builtin:".length) : fallback;
  const Icon = (BUILTIN_ICONS[name] ?? BUILTIN_ICONS[fallback]).icon;
  const svg = renderToStaticMarkup(createElement(Icon, { size: 24, color: "#ffffff", strokeWidth: 2 }));
  return `data:image/svg+xml;utf8,${encodeURIComponent(svg)}`;
}

/** Icône Lucide quelconque en URL de données (ex. l'engrenage des options d'un bloc). */
export function lucideSource(Icon: LucideIcon, size = 16, color = "#ffffff"): string {
  const svg = renderToStaticMarkup(createElement(Icon, { size, color, strokeWidth: 2 }));
  return `data:image/svg+xml;utf8,${encodeURIComponent(svg)}`;
}
