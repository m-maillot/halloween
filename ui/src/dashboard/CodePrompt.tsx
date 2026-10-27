import { useState } from "react";
import { describeError } from "../api/errors";
import { Button, Field, Modal } from "../components/ui";

/** Demande le code de verrouillage (exigé à chaque lancement quand le moteur est verrouillé). */
export function CodePrompt({
  title,
  onSubmit,
  onClose,
}: {
  title: string;
  onSubmit: (code: string) => Promise<void>;
  onClose: () => void;
}) {
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  return (
    <Modal title={title} onClose={onClose}>
      <form
        className="form"
        onSubmit={async (e) => {
          e.preventDefault();
          setBusy(true);
          setError(null);
          try {
            await onSubmit(code);
            onClose();
          } catch (failure) {
            const { title: message, retryAfter } = describeError(failure);
            setError(retryAfter !== undefined ? `${message} Réessayer dans ${retryAfter} s.` : message);
            setCode("");
          } finally {
            setBusy(false);
          }
        }}
      >
        <Field
          label="Code"
          type="password"
          inputMode="numeric"
          autoComplete="off"
          autoFocus
          value={code}
          error={error ?? undefined}
          onChange={(e) => setCode(e.target.value)}
        />
        <div className="form-actions">
          <span className="form-actions__spacer" />
          <Button variant="ghost" onClick={onClose}>
            Annuler
          </Button>
          <Button variant="primary" type="submit" disabled={busy || code.length < 4}>
            Valider
          </Button>
        </div>
      </form>
    </Modal>
  );
}
