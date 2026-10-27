import * as Blockly from "blockly/core";
import { findRelay } from "./catalog";
import { iconSource } from "./icons";

export const HUE = { control: 36, relay: 0, light: 48, switch: 200, button: 290, misc: 230 };

const STATE_OPTIONS: [string, string][] = [
  ["allumer", "on"],
  ["éteindre", "off"],
];

/** Bloc commun aux composants : porte l'identifiant du composant dans son état supplémentaire. */
interface ComponentBlock extends Blockly.Block {
  target_: string;
  updateShape_(): void;
}

function relayShape(this: ComponentBlock) {
  const keep = {
    STATE: this.getFieldValue("STATE") as string | null,
    WAIT_END: this.getFieldValue("WAIT_END") as string | null,
  };
  if (this.getInput("HEAD")) this.removeInput("HEAD");
  const relay = findRelay(this.target_);
  const input = this.appendDummyInput("HEAD");
  if (relay) {
    input.appendField(new Blockly.FieldImage(iconSource(relay.image, relay.image_url), 24, 24, relay.name));
    input.appendField(relay.name);
  } else {
    input.appendField(`composant introuvable : ${this.target_}`);
  }
  if (relay?.mode === "push") {
    input.appendField("déclencher");
    if (relay.animation_s) {
      input.appendField(new Blockly.FieldCheckbox(keep.WAIT_END === "TRUE"), "WAIT_END");
      input.appendField("attendre la fin");
    }
  } else {
    input.appendField(new Blockly.FieldDropdown(STATE_OPTIONS), "STATE");
    if (keep.STATE) this.setFieldValue(keep.STATE, "STATE");
  }
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

  Blockly.Blocks["hw_relay"] = {
    init(this: ComponentBlock) {
      this.target_ = "";
      this.setPreviousStatement(true);
      this.setNextStatement(true);
      this.setColour(HUE.relay);
    },
    saveExtraState(this: ComponentBlock) {
      return { target: this.target_ };
    },
    loadExtraState(this: ComponentBlock, state: { target: string }) {
      this.target_ = state.target;
      this.updateShape_();
    },
    updateShape_: relayShape,
  };
}

/** Recalcule la forme des blocs de composants (catalogue modifié). */
export function refreshComponentBlocks(workspace: Blockly.Workspace): void {
  for (const block of workspace.getAllBlocks(false)) {
    const shaped = block as unknown as Partial<ComponentBlock>;
    if (shaped.updateShape_) shaped.updateShape_();
  }
}
