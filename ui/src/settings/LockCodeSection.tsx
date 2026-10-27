import { useState } from "react";
import { api } from "../api/client";
import { describeError, unwrap } from "../api/errors";
import { Button, Field } from "../components/ui";
import { useToasts } from "../components/Toasts";
import { useEngine } from "../engine/EngineProvider";

const CODE = /^\d{4,8}$/;

/** Définition ou changement du code de verrouillage (l'empreinte reste dans le moteur). */
export function LockCodeSection({ disabled }: { disabled: boolean }) {
  const toasts = useToasts();
  const { status, refresh } = useEngine();
  const hasCode = status?.lock.has_code ?? false;
  const [oldCode, setOldCode] = useState("");
  const [newCode, setNewCode] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const mismatch = confirm !== "" && confirm !== newCode ? "Les deux codes sont différents." : undefined;
  const format = newCode !== "" && !CODE.test(newCode) ? "Le code comporte 4 à 8 chiffres." : undefined;
  const ready = CODE.test(newCode) && newCode === confirm && (!hasCode || oldCode !== "");

  async function submit() {
    setBusy(true);
    setError(null);
    try {
      await unwrap(
        api.PUT("/api/lock/code", { body: { new_code: newCode, old_code: hasCode ? oldCode : null } }),
      );
      setOldCode("");
      setNewCode("");
      setConfirm("");
      toasts.info(hasCode ? "Code modifié." : "Code défini. Vous pouvez maintenant verrouiller l'interface.");
      void refresh();
    } catch (failure) {
      const { title, retryAfter } = describeError(failure);
      setError(retryAfter !== undefined ? `${title} Réessayer dans ${retryAfter} s.` : title);
      setOldCode("");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="settings-section" aria-labelledby="set-lock">
      <h2 id="set-lock">Code de verrouillage</h2>
      <p className="muted">
        {hasCode ? "Un code est défini." : "Aucun code défini : l'interface ne peut pas être verrouillée."} Verrouillée, l'interface
        n'autorise que la consultation, STOP et le lancement de scénarios avec le code.
      </p>
      <form
        className="form"
        onSubmit={(e) => {
          e.preventDefault();
          void submit();
        }}
      >
        {hasCode && (
          <Field
            label="Code actuel"
            type="password"
            inputMode="numeric"
            autoComplete="off"
            value={oldCode}
            disabled={disabled}
            onChange={(e) => setOldCode(e.target.value)}
          />
        )}
        <Field
          label="Nouveau code"
          type="password"
          inputMode="numeric"
          autoComplete="off"
          value={newCode}
          disabled={disabled}
          error={format}
          hint="4 à 8 chiffres."
          onChange={(e) => setNewCode(e.target.value)}
        />
        <Field
          label="Confirmer le nouveau code"
          type="password"
          inputMode="numeric"
          autoComplete="off"
          value={confirm}
          disabled={disabled}
          error={mismatch}
          onChange={(e) => setConfirm(e.target.value)}
        />
        {error && (
          <div className="form-error" role="alert">
            {error}
          </div>
        )}
        <div className="form-actions">
          <span className="form-actions__spacer" />
          <Button variant="primary" type="submit" disabled={busy || disabled || !ready}>
            {hasCode ? "Changer le code" : "Définir le code"}
          </Button>
        </div>
        <span className="field__hint">Code perdu : sur le Pi, `halloween-cli unlock --reset`.</span>
      </form>
    </section>
  );
}
