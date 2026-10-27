import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { expect, test } from "vitest";

const css = readFileSync(resolve(process.cwd(), "src/styles/theme.css"), "utf8");
const colors = Object.fromEntries(
  [...css.matchAll(/--color-([a-z0-9-]+):\s*(#[0-9a-f]{6})/gi)].map((m) => [m[1], m[2]]),
);

function luminance(hex: string): number {
  const channel = (i: number) => {
    const v = parseInt(hex.slice(1 + 2 * i, 3 + 2 * i), 16) / 255;
    return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * channel(0) + 0.7152 * channel(1) + 0.0722 * channel(2);
}

function ratio(a: string, b: string): number {
  const [hi, lo] = [luminance(colors[a]), luminance(colors[b])].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

// Texte (≥ 4.5 : WCAG AA) sur le fond sur lequel il est réellement posé.
const TEXT_PAIRS: [string, string][] = [
  ["text", "bg"],
  ["text", "surface"],
  ["text", "surface-2"],
  ["text", "surface-active"],
  ["text", "sidebar"],
  ["text-muted", "bg"],
  ["text-muted", "surface"],
  ["text-muted", "sidebar"],
  ["on-accent", "accent"],
  ["on-accent", "accent-text"],
  ["on-danger", "danger"],
  ["danger-text", "surface"],
  ["danger-text", "bg"],
  ["accent-text", "surface"],
  ["accent", "bg"],
  ["success", "surface"],
  ["success", "bg"],
];

test.each(TEXT_PAIRS)("contraste texte %s sur %s ≥ 4,5", (fg, bg) => {
  expect(ratio(fg, bg)).toBeGreaterThanOrEqual(4.5);
});

// Éléments d'interface (≥ 3 : WCAG 1.4.11) : bordure des champs, anneau de focus.
test.each([
  ["field-border", "bg"],
  ["focus", "bg"],
  ["danger-border", "bg"],
])("contraste composant %s sur %s ≥ 3", (fg, bg) => {
  expect(ratio(fg, bg)).toBeGreaterThanOrEqual(3);
});

test("les cibles tactiles respectent 44 px (64 px en grand format)", () => {
  expect(css).toMatch(/--target:\s*44px/);
  expect(css).toMatch(/--target-large:\s*64px/);
  const components = readFileSync(resolve(process.cwd(), "src/styles/components.css"), "utf8");
  expect(components).toMatch(/\.btn \{[^}]*min-height: var\(--target\)/s);
  expect(components).toMatch(/\.input \{[^}]*min-height: var\(--target\)/s);
  expect(components).toMatch(/\.btn--large \{[^}]*min-height: var\(--target-large\)/s);
});
