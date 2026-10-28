import * as Blockly from "blockly/core";
import { FieldColour } from "@blockly/field-colour";
import { Settings } from "lucide-react";
import { findLight, findRelay, findSwitch } from "./catalog";
import { registerControlBlocks } from "./controlBlocks";
import { iconSource, lucideSource } from "./icons";

export const HUE = { control: 36, relay: 0, light: 48, switch: 200, button: 290, misc: 230 };
const KIND_OF = { relay: "relays", light: "lights", switch: "switches" } as const;
const NOT_FOUND_COLOUR = "#a02626";

const STATE_OPTIONS: [string, string][] = [
  ["allumer", "on"],
  ["éteindre", "off"],
];
const ERROR_OPTIONS: [string, string][] = [
  ["continuer", "continue"],
  ["arrêter le scénario", "abort"],
];

/** État d'un bloc de composant, tel que Blockly le copie / annule (`saveExtraState`). */
export interface ComponentState {
  target: string;
  /** Composant introuvable : on retient que le nœud était une impulsion, faute de pouvoir le lire dans le catalogue. */
  trigger?: boolean;
  fire_and_forget?: boolean;
  on_error?: "continue" | "abort";
  /** Bloc de la palette « lumière réglée » : couleur, luminosité et transition posées d'emblée (jamais sauvegardé). */
  tuned?: boolean;
}

export type ComponentKindName = "relay" | "light" | "switch";

export interface ComponentBlock extends Blockly.Block {
  kind_: ComponentKindName;
  target_: string;
  fallbackTrigger_?: boolean;
  tunedPending_?: boolean;
  optionsOpen_: boolean;
  updateShape_(): void;
  toggleOptions_(): void;
  caps_?: Record<string, boolean>;
}

const FIELDS = ["STATE", "WAIT_END", "USE_COLOR", "COLOR", "USE_BRIGHT", "BRIGHT", "USE_TRANS", "TRANS", "FF", "ONERR"];

function lookup(block: ComponentBlock) {
  return block.kind_ === "relay" ? findRelay(block.target_) : block.kind_ === "light" ? findLight(block.target_) : findSwitch(block.target_);
}

const PARAM_ROWS: [row: string, use: string][] = [
  ["P_COLOR", "USE_COLOR"],
  ["P_BRIGHT", "USE_BRIGHT"],
  ["P_TRANS", "USE_TRANS"],
];

/**
 * Affiche ou masque les paramètres facultatifs selon l'engrenage et les cases cochées. Chaque
 * paramètre a sa propre ligne : Blockly rétablit la visibilité des champs d'après celle de leur
 * ligne, masquer un champ isolé est sans effet.
 */
export function refreshVisibility(block: Blockly.Block): void {
  const target = block as ComponentBlock;
  if (block.isDeadOrDying()) return;
  const open = target.optionsOpen_;
  for (const [row, use] of PARAM_ROWS) {
    const input = block.getInput(row);
    if (!input) continue;
    const on = block.getFieldValue(use) === "TRUE";
    const supported = target.caps_?.[use] ?? true;
    // posé : toujours visible (même non géré par la lumière, pour que la validation le signale) ; sinon seulement
    // quand l'engrenage est ouvert ET que la lumière gère ce paramètre
    input.setVisible(on || (open && supported));
  }
  block.getInput("OPTS")?.setVisible(open);
  if (block instanceof Blockly.BlockSvg) block.queueRender();
}

function shape(this: ComponentBlock) {
  const keep: Record<string, unknown> = {};
  for (const name of FIELDS) if (this.getField(name)) keep[name] = this.getFieldValue(name);
  for (const name of ["HEAD", "P_COLOR", "P_BRIGHT", "P_TRANS", "OPTS"]) if (this.getInput(name)) this.removeInput(name);

  const found = lookup(this);
  this.setColour(found ? HUE[this.kind_] : NOT_FOUND_COLOUR);
  this.setWarningText(found ? null : `Composant introuvable : ${this.target_}`);

  const head = this.appendDummyInput("HEAD");
  head.appendField(new Blockly.FieldImage(lucideSource(Settings, 16), 16, 16, "Options", () => this.toggleOptions_()));
  if (found) {
    head.appendField(new Blockly.FieldImage(iconSource(found.image, found.image_url, KIND_OF[this.kind_]), 24, 24, found.name));
    head.appendField(found.name);
  } else {
    head.appendField(`introuvable : ${this.target_}`);
  }

  const push = this.kind_ === "relay" && (found ? (found as { mode?: string }).mode === "push" : Boolean(this.fallbackTrigger_));
  if (push) {
    head.appendField("déclencher");
    if (found ? (found as { animation_s?: number | null }).animation_s : this.fallbackTrigger_) {
      head.appendField(new Blockly.FieldCheckbox(false), "WAIT_END").appendField("attendre la fin");
    }
  } else {
    head.appendField(new Blockly.FieldDropdown(STATE_OPTIONS), "STATE");
  }

  if (this.kind_ === "light") {
    const light = found as { supports_color?: boolean; supports_brightness?: boolean; supports_transition?: boolean } | undefined;
    // Les trois paramètres existent toujours : un programme qui en pose un que la lumière ne gère pas
    // doit le garder (la validation le signale sur ce bloc) ; seul le menu ne le propose pas.
    this.caps_ = { USE_COLOR: Boolean(light?.supports_color), USE_BRIGHT: Boolean(light?.supports_brightness), USE_TRANS: Boolean(light?.supports_transition) };
    const refresh = () => setTimeout(() => refreshVisibility(this), 0);
    const checkbox = () =>
      new Blockly.FieldCheckbox(false, (value) => {
        refresh(); // le validateur s'exécute avant l'écriture de la valeur
        return value;
      });
    this.appendDummyInput("P_COLOR").appendField(checkbox(), "USE_COLOR").appendField("couleur").appendField(new FieldColour("#ff8a2b"), "COLOR");
    this.appendDummyInput("P_BRIGHT").appendField(checkbox(), "USE_BRIGHT").appendField("luminosité").appendField(new Blockly.FieldNumber(100, 0, 100, 0.01), "BRIGHT").appendField("%");
    this.appendDummyInput("P_TRANS").appendField(checkbox(), "USE_TRANS").appendField("transition").appendField(new Blockly.FieldNumber(1, 0, 3600, 0.1), "TRANS").appendField("s");
  }

  const options = this.appendDummyInput("OPTS");
  options.appendField(new Blockly.FieldCheckbox(false), "FF").appendField("sans attendre Home Assistant");
  options.appendField("en cas d'erreur :").appendField(new Blockly.FieldDropdown(ERROR_OPTIONS), "ONERR");

  for (const [name, value] of Object.entries(keep)) {
    if (this.getField(name)) this.setFieldValue(value as string, name);
  }
  if (this.tunedPending_) {
    // Posé ici, avant le premier rendu : la hauteur du bloc est alors juste dans la palette.
    this.tunedPending_ = false;
    for (const [, use] of PARAM_ROWS) if (this.caps_?.[use]) this.setFieldValue("TRUE", use);
  }
  refreshVisibility(this);
}

function defineComponentBlock(type: string, kind: ComponentKindName): void {
  Blockly.Blocks[type] = {
    init(this: ComponentBlock) {
      this.kind_ = kind;
      this.target_ = "";
      this.optionsOpen_ = false;
      this.setPreviousStatement(true);
      this.setNextStatement(true);
      this.setColour(HUE[kind]);
    },
    // Seule l'identité du composant est dans l'état supplémentaire : les valeurs des champs sont
    // sauvegardées par Blockly lui-même (copier / coller, annuler) et par notre sérialiseur.
    saveExtraState(this: ComponentBlock): ComponentState {
      return this.fallbackTrigger_ ? { target: this.target_, trigger: true } : { target: this.target_ };
    },
    loadExtraState(this: ComponentBlock, state: ComponentState) {
      this.target_ = state.target;
      this.fallbackTrigger_ = state.trigger;
      this.tunedPending_ = state.tuned;
      this.updateShape_();
    },
    toggleOptions_(this: ComponentBlock) {
      this.optionsOpen_ = !this.optionsOpen_;
      refreshVisibility(this);
    },
    updateShape_: shape,
  };
}

let registered = false;

/** Enregistre les types de blocs (une seule fois). */
export function registerBlocks(): void {
  if (registered) return;
  registered = true;

  Blockly.Blocks["hw_start"] = {
    init(this: Blockly.Block) {
      this.appendDummyInput().appendField("quand le scénario démarre");
      this.setNextStatement(true);
      this.setColour(HUE.control);
      (this as unknown as { hat: string }).hat = "cap"; // chapeau (rendu Zelos)
      this.setTooltip("Début d'un script. Plusieurs scripts s'exécutent en parallèle.");
    },
  };
  registerControlBlocks();
  defineComponentBlock("hw_relay", "relay");
  defineComponentBlock("hw_light", "light");
  defineComponentBlock("hw_switch", "switch");
}

/** Recalcule la forme des blocs de composants (catalogue modifié). */
export function refreshComponentBlocks(workspace: Blockly.Workspace): void {
  for (const block of workspace.getAllBlocks(false)) {
    const shaped = block as unknown as Partial<ComponentBlock>;
    if (shaped.updateShape_) shaped.updateShape_();
  }
}
