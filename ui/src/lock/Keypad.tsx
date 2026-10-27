import { Delete } from "lucide-react";
import { useId } from "react";

const KEYS = ["1", "2", "3", "4", "5", "6", "7", "8", "9"];

/** Saisie d'un code : champ masqué (le clavier physique fonctionne aussi) et pavé numérique tactile. */
export function Keypad({
  value,
  onChange,
  disabled,
  error,
  max = 8,
}: {
  value: string;
  onChange: (next: string) => void;
  disabled?: boolean;
  error?: string;
  max?: number;
}) {
  const id = useId();
  const add = (digit: string) => value.length < max && onChange(value + digit);
  return (
    <div className="keypad">
      <label className="field__label" htmlFor={id}>
        Code
      </label>
      <input
        id={id}
        className="input keypad__input"
        type="password"
        inputMode="numeric"
        autoComplete="off"
        value={value}
        maxLength={max}
        disabled={disabled}
        aria-invalid={error ? true : undefined}
        aria-describedby={error ? `${id}-error` : undefined}
        onChange={(e) => onChange(e.target.value.replace(/\D/g, "").slice(0, max))}
      />
      {error && (
        <span id={`${id}-error`} className="field__error" role="alert">
          {error}
        </span>
      )}
      <div className="keypad__grid" role="group" aria-label="Pavé numérique">
        {KEYS.map((digit) => (
          <button key={digit} type="button" className="keypad__key" disabled={disabled} onClick={() => add(digit)}>
            {digit}
          </button>
        ))}
        <button type="button" className="keypad__key keypad__key--ghost" disabled={disabled || value === ""} aria-label="Effacer le dernier chiffre" onClick={() => onChange(value.slice(0, -1))}>
          <Delete size={22} aria-hidden="true" />
        </button>
        <button type="button" className="keypad__key" disabled={disabled} onClick={() => add("0")}>
          0
        </button>
        <span aria-hidden="true" />
      </div>
    </div>
  );
}
