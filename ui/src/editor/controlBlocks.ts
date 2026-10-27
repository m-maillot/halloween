import * as Blockly from "blockly/core";
import { Minus, Plus } from "lucide-react";
import { listButtons, listPrograms, listRelays } from "./catalog";
import { lucideSource } from "./icons";

export const CONTROL_HUE = 36;
export const CONDITION_HUE = 290;
export const MISC_HUE = 230;

// Pas d'arrondi (précision absente) : les valeurs du moteur doivent revenir telles quelles.
const num = (value: number, min: number, max?: number) => new Blockly.FieldNumber(value, min, max);

/** Options d'un menu qui garde la valeur courante même si le composant / scénario a disparu. */
function targetOptions(items: { id: string; name: string }[], current: string | null): [string, string][] {
  const options: [string, string][] = items.map((i) => [i.name, i.id]);
  if (current && !items.some((i) => i.id === current)) options.push([`${current} (introuvable)`, current]);
  return options.length ? options : [["(aucun)", ""]];
}

/** Pose la valeur d'un menu dynamique : son cache d'options est renouvelé d'abord (sinon la valeur est refusée). */
function setDynamicValue(block: Blockly.Block, name: string, value: string): void {
  const field = block.getField(name) as Blockly.FieldDropdown;
  field.getOptions(false);
  field.setValue(value);
}

interface DynamicBlock extends Blockly.Block {
  count_: number;
  setCount_(n: number): void;
}

/** Ajoute / retire les entrées « branche i » ; retirer n'est permis que pour une entrée vide. */
function defineDynamic(
  type: string,
  min: number,
  prefix: string,
  label: (i: number) => (string | [Blockly.Field, string])[],
  head: (block: Blockly.Block) => void,
): void {
  Blockly.Blocks[type] = {
    init(this: DynamicBlock) {
      this.setPreviousStatement(true);
      this.setNextStatement(true);
      this.setColour(CONTROL_HUE);
      head(this);
      this.count_ = 0;
      this.setCount_(min);
    },
    saveExtraState(this: DynamicBlock) {
      return { count: this.count_ };
    },
    loadExtraState(this: DynamicBlock, state: { count: number }) {
      this.setCount_(Math.max(min, state.count));
    },
    setCount_(this: DynamicBlock, n: number) {
      while (this.count_ < n) {
        const input = this.appendStatementInput(`${prefix}${this.count_}`);
        for (const part of label(this.count_)) {
          if (typeof part === "string") input.appendField(part);
          else input.appendField(part[0], part[1]);
        }
        this.count_++;
      }
      while (this.count_ > n) {
        this.count_--;
        this.removeInput(`${prefix}${this.count_}`);
      }
    },
    addBranch_(this: DynamicBlock) {
      this.setCount_(this.count_ + 1);
    },
    removeBranch_(this: DynamicBlock) {
      const last = this.getInput(`${prefix}${this.count_ - 1}`);
      if (this.count_ > min && last && !last.connection?.targetBlock()) this.setCount_(this.count_ - 1);
    },
  };
}

function plusMinus(block: Blockly.Block): [Blockly.Field, Blockly.Field] {
  const b = block as unknown as { addBranch_(): void; removeBranch_(): void };
  return [
    new Blockly.FieldImage(lucideSource(Plus, 16), 16, 16, "Ajouter une branche", () => b.addBranch_()),
    new Blockly.FieldImage(lucideSource(Minus, 16), 16, 16, "Retirer la dernière branche (vide)", () => b.removeBranch_()),
  ];
}

interface CallBlock extends Blockly.Block {
  callTarget_: string;
}
interface TargetBlock extends Blockly.Block {
  target_: string;
}

export function registerControlBlocks(): void {
  defineDynamic(
    "hw_parallel",
    2,
    "BRANCH",
    (i) => [`branche ${i + 1}`],
    (block) => {
      const input = block.appendDummyInput("HEAD").appendField("en parallèle, attendre");
      input.appendField(new Blockly.FieldDropdown([["toutes les branches", "all"], ["la première branche", "first"]]), "UNTIL");
      const [plus, minus] = plusMinus(block);
      input.appendField(plus).appendField(minus);
    },
  );

  defineDynamic(
    "hw_random_choice",
    2,
    "CHOICE",
    (i) => ["choix de poids", [num(1, 0.01, 1000), `WEIGHT${i}`] as [Blockly.Field, string]],
    (block) => {
      const input = block.appendDummyInput("HEAD").appendField("faire au hasard l'un de");
      const [plus, minus] = plusMinus(block);
      input.appendField(plus).appendField(minus);
    },
  );

  Blockly.Blocks["hw_repeat"] = {
    init(this: Blockly.Block) {
      this.appendStatementInput("DO").appendField("répéter").appendField(new Blockly.FieldNumber(3, 1, 10000, 1), "TIMES").appendField("fois");
      this.setPreviousStatement(true);
      this.setNextStatement(true);
      this.setColour(CONTROL_HUE);
    },
  };
  Blockly.Blocks["hw_repeat_forever"] = {
    init(this: Blockly.Block) {
      this.appendStatementInput("DO").appendField("répéter indéfiniment");
      this.setPreviousStatement(true);
      this.setNextStatement(false); // rien ne s'exécute après une boucle sans fin
      this.setColour(CONTROL_HUE);
      this.setTooltip("Ne s'arrête qu'avec la durée maximale du scénario ou le bouton STOP.");
    },
  };
  Blockly.Blocks["hw_wait"] = {
    init(this: Blockly.Block) {
      this.appendDummyInput().appendField("attendre").appendField(num(1, 0, 86400), "SECONDS").appendField("s");
      this.setPreviousStatement(true);
      this.setNextStatement(true);
      this.setColour(CONTROL_HUE);
    },
  };
  Blockly.Blocks["hw_wait_random"] = {
    init(this: Blockly.Block) {
      this.appendDummyInput()
        .appendField("attendre entre")
        .appendField(num(1, 0, 86400), "MIN")
        .appendField("et")
        .appendField(num(3, 0, 86400), "MAX")
        .appendField("s");
      this.setPreviousStatement(true);
      this.setNextStatement(true);
      this.setColour(CONTROL_HUE);
    },
  };
  Blockly.Blocks["hw_if"] = {
    init(this: Blockly.Block) {
      this.appendValueInput("COND").setCheck("Boolean").appendField("si");
      this.appendStatementInput("THEN").appendField("alors");
      this.appendStatementInput("ELSE").appendField("sinon");
      this.setPreviousStatement(true);
      this.setNextStatement(true);
      this.setColour(CONTROL_HUE);
    },
  };
  Blockly.Blocks["hw_wait_until"] = {
    init(this: Blockly.Block) {
      this.appendValueInput("COND").setCheck("Boolean").appendField("attendre jusqu'à");
      this.appendDummyInput().appendField("délai maximal").appendField(num(0, 0, 86400), "TIMEOUT").appendField("s (0 : sans limite)");
      this.setInputsInline(true);
      this.setPreviousStatement(true);
      this.setNextStatement(true);
      this.setColour(CONTROL_HUE);
    },
  };
  Blockly.Blocks["hw_call"] = {
    init(this: CallBlock) {
      this.callTarget_ = "";
      this.appendDummyInput().appendField("appeler le scénario").appendField(
        new Blockly.FieldDropdown(() => targetOptions(listPrograms(), this.callTarget_ || null)),
        "PROGRAM",
      );
      this.setPreviousStatement(true);
      this.setNextStatement(true);
      this.setColour(CONTROL_HUE);
    },
    saveExtraState(this: CallBlock) {
      return { program_id: this.getFieldValue("PROGRAM") ?? this.callTarget_ };
    },
    loadExtraState(this: CallBlock, state: { program_id: string }) {
      this.callTarget_ = state.program_id;
      setDynamicValue(this, "PROGRAM", state.program_id);
    },
  };
  Blockly.Blocks["hw_log"] = {
    init(this: Blockly.Block) {
      this.appendDummyInput().appendField("journaliser").appendField(new Blockly.FieldTextInput("message"), "MESSAGE");
      this.setPreviousStatement(true);
      this.setNextStatement(true);
      this.setColour(MISC_HUE);
    },
  };

  // ------------------------------------------------------------ conditions
  Blockly.Blocks["hw_cond_button"] = {
    init(this: TargetBlock) {
      this.target_ = "";
      this.appendDummyInput()
        .appendField("bouton")
        .appendField(new Blockly.FieldDropdown(() => targetOptions(listButtons(), this.target_ || null)), "BUTTON")
        .appendField("a reçu")
        .appendField(new Blockly.FieldDropdown([["un appui court", "short"], ["un appui long", "long"], ["un double appui", "double"]]), "EVENT");
      this.setOutput(true, "Boolean");
      this.setColour(CONDITION_HUE);
    },
    saveExtraState(this: TargetBlock) {
      return { button: this.getFieldValue("BUTTON") ?? this.target_ };
    },
    loadExtraState(this: TargetBlock, state: { button: string }) {
      this.target_ = state.button;
      setDynamicValue(this, "BUTTON", state.button);
    },
  };
  Blockly.Blocks["hw_cond_relay_is"] = {
    init(this: TargetBlock) {
      this.target_ = "";
      this.appendDummyInput()
        .appendField("le relais")
        .appendField(new Blockly.FieldDropdown(() => targetOptions(listRelays(), this.target_ || null)), "RELAY")
        .appendField("est")
        .appendField(new Blockly.FieldDropdown([["allumé", "on"], ["éteint", "off"]]), "STATE");
      this.setOutput(true, "Boolean");
      this.setColour(CONDITION_HUE);
    },
    saveExtraState(this: TargetBlock) {
      return { relay: this.getFieldValue("RELAY") ?? this.target_ };
    },
    loadExtraState(this: TargetBlock, state: { relay: string }) {
      this.target_ = state.relay;
      setDynamicValue(this, "RELAY", state.relay);
    },
  };
  Blockly.Blocks["hw_cond_random"] = {
    init(this: Blockly.Block) {
      this.appendDummyInput().appendField("au hasard, une fois sur").appendField(num(50, 0, 100), "PERCENT").appendField("% des cas");
      this.setOutput(true, "Boolean");
      this.setColour(CONDITION_HUE);
    },
  };
}
