// Icônes dessinées pour ce projet (trait de 2 px sur grille 24 px, comme Lucide) : Lucide n'a ni
// citrouille, ni chauve-souris, ni araignée, ni épouvantail. Elles appartiennent au projet : aucune attribution tierce.
import { createLucideIcon } from "lucide-react";

export const Pumpkin = createLucideIcon("Pumpkin", [
  ["path", { d: "M12 7.5C9.5 5.5 4 6.5 4 12.8 4 17.8 7.5 20 12 20s8-2.2 8-7.2C20 6.5 14.5 5.5 12 7.5z", key: "body" }],
  ["path", { d: "M12 7.5V20", key: "rib0" }],
  ["path", { d: "M8.2 8.2C6.6 10.5 6.6 16.5 8.8 19.5", key: "rib1" }],
  ["path", { d: "M15.8 8.2c1.6 2.3 1.6 8.3-.6 11.3", key: "rib2" }],
  ["path", { d: "M12 7.5c0-2 .8-3.2 2.4-4", key: "stem" }],
]);

export const Bat = createLucideIcon("Bat", [
  ["path", { d: "M12 8 10.6 5.5 9.6 8.4C7.2 7.4 4.6 7.6 2.5 9.4c1.4.2 2.1 1.1 2.3 2.6 1-.8 2.2-.9 3.2-.3.6 1.2 1.6 1.9 2.6 1.9L12 17l1.4-3.4c1 0 2-.7 2.6-1.9 1-.6 2.2-.5 3.2.3.2-1.5.9-2.4 2.3-2.6-2.1-1.8-4.7-2-7.1-1L14.4 5.5 13 8z", key: "bat" }],
]);

export const Spider = createLucideIcon("Spider", [
  ["circle", { cx: "12", cy: "13.5", r: "3.2", key: "abdomen" }],
  ["circle", { cx: "12", cy: "9.2", r: "1.6", key: "head" }],
  ["path", { d: "M12 2v5.6", key: "thread" }],
  ["path", { d: "M9 12.5 4.5 9.5M9 13.8 3 14M9.4 15.4 5 19.5M10.2 16.4 8.4 21", key: "left" }],
  ["path", { d: "M15 12.5l4.5-3M15 13.8l6 .2M14.6 15.4l4.4 4.1M13.8 16.4 15.6 21", key: "right" }],
]);

export const Scarecrow = createLucideIcon("Scarecrow", [
  ["path", { d: "M8.2 7.2h7.6M9.6 7.2 10 3.8h4l.4 3.4", key: "hat" }],
  ["circle", { cx: "12", cy: "10.4", r: "2.2", key: "head" }],
  ["path", { d: "M3 14h18", key: "arms" }],
  ["path", { d: "M12 12.6V21", key: "body" }],
  ["path", { d: "M3 14v2M21 14v2", key: "hands" }],
]);

export const Cauldron = createLucideIcon("Cauldron", [
  ["path", { d: "M4.5 9.5h15", key: "rim" }],
  ["path", { d: "M5.6 9.5c-.8 4 .3 8.5 6.4 8.5s7.2-4.5 6.4-8.5", key: "pot" }],
  ["path", { d: "M8.2 18.2 7 21M15.8 18.2 17 21", key: "legs" }],
  ["circle", { cx: "10", cy: "6", r: "1.1", key: "b1" }],
  ["circle", { cx: "14.2", cy: "4.8", r: ".8", key: "b2" }],
]);

export const Tombstone = createLucideIcon("Tombstone", [
  ["path", { d: "M7 21V9.5a5 5 0 0 1 10 0V21", key: "stone" }],
  ["path", { d: "M4 21h16", key: "ground" }],
  ["path", { d: "M12 8v5.5M9.8 10.2h4.4", key: "cross" }],
]);
