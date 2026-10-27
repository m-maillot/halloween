import {
  Axe,
  Bell,
  Biohazard,
  Bone,
  Bug,
  Candy,
  Cat,
  Castle,
  Church,
  CircleDot,
  Cloud,
  CloudLightning,
  Eye,
  Fan,
  Flame,
  Footprints,
  Ghost,
  Hammer,
  Hand,
  Lamp,
  Lightbulb,
  type LucideIcon,
  Moon,
  Music,
  Plug,
  Power,
  Siren,
  Skull,
  Sparkles,
  TreePine,
  Volume2,
  WandSparkles,
  Wind,
  Zap,
} from "lucide-react";

export type Kind = "relays" | "buttons" | "lights" | "switches";

/** Bibliothèque intégrée : `image: "builtin:<nom>"`. Icônes Lucide (licence ISC, sans attribution). */
export const BUILTIN_ICONS: Record<string, { label: string; icon: LucideIcon }> = {
  ghost: { label: "Fantôme", icon: Ghost },
  skull: { label: "Squelette crâne", icon: Skull },
  bone: { label: "Os", icon: Bone },
  cat: { label: "Chat noir", icon: Cat },
  eye: { label: "Œil", icon: Eye },
  spider: { label: "Araignée", icon: Bug },
  moon: { label: "Lune", icon: Moon },
  tree: { label: "Arbre épouvantail", icon: TreePine },
  lightning: { label: "Éclair", icon: Zap },
  storm: { label: "Orage", icon: CloudLightning },
  fog: { label: "Brouillard", icon: Cloud },
  wind: { label: "Vent", icon: Wind },
  candle: { label: "Bougie flamme", icon: Flame },
  light: { label: "Lumière", icon: Lightbulb },
  lamp: { label: "Lampe", icon: Lamp },
  plug: { label: "Prise", icon: Plug },
  power: { label: "Alimentation", icon: Power },
  button: { label: "Bouton", icon: CircleDot },
  sparkles: { label: "Étincelles magie", icon: Sparkles },
  wand: { label: "Baguette", icon: WandSparkles },
  candy: { label: "Bonbon", icon: Candy },
  siren: { label: "Sirène", icon: Siren },
  bell: { label: "Cloche", icon: Bell },
  music: { label: "Musique", icon: Music },
  sound: { label: "Son", icon: Volume2 },
  fan: { label: "Ventilateur", icon: Fan },
  castle: { label: "Château", icon: Castle },
  church: { label: "Chapelle", icon: Church },
  footprints: { label: "Pas", icon: Footprints },
  hand: { label: "Main", icon: Hand },
  axe: { label: "Hache", icon: Axe },
  hammer: { label: "Marteau", icon: Hammer },
  biohazard: { label: "Danger", icon: Biohazard },
};

/** Icône attribuée tant qu'aucune image n'est choisie. */
export const DEFAULT_ICON: Record<Kind, string> = {
  relays: "power",
  buttons: "button",
  lights: "light",
  switches: "plug",
};

export const KIND_LABEL: Record<Kind, string> = {
  relays: "Relais",
  buttons: "Boutons",
  lights: "Lumières",
  switches: "Interrupteurs",
};

/** Image d'un composant : fichier téléversé, icône intégrée, sinon icône par défaut du type. */
export function ComponentImage({
  kind,
  image,
  imageUrl,
  size = 40,
}: {
  kind: Kind;
  image?: string | null;
  imageUrl?: string | null;
  size?: number;
}) {
  if (imageUrl) {
    return <img className="thumb" src={imageUrl} alt="" width={size} height={size} />;
  }
  const name = image?.startsWith("builtin:") ? image.slice("builtin:".length) : undefined;
  const Icon = (name && BUILTIN_ICONS[name]?.icon) || BUILTIN_ICONS[DEFAULT_ICON[kind]].icon;
  return <Icon className="thumb thumb--icon" size={size} aria-hidden="true" />;
}
