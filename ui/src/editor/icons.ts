// Image d'un composant pour un champ de bloc Blockly (qui attend une URL, pas un composant React).
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { BUILTIN_ICONS } from "../catalog/icons";

const FALLBACK = "power";

export function iconSource(image: string | null | undefined, imageUrl: string | null | undefined): string {
  if (imageUrl) return imageUrl;
  const name = image?.startsWith("builtin:") ? image.slice("builtin:".length) : FALLBACK;
  const Icon = (BUILTIN_ICONS[name] ?? BUILTIN_ICONS[FALLBACK]).icon;
  const svg = renderToStaticMarkup(createElement(Icon, { size: 24, color: "#ffffff", strokeWidth: 2 }));
  return `data:image/svg+xml;utf8,${encodeURIComponent(svg)}`;
}
