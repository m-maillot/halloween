import { useEffect, useState } from "react";
import { describeError } from "../api/errors";
import { Keypad } from "../lock/Keypad";
import { Button, Modal } from "../components/ui";

/** Demande le code (à chaque lancement, au déverrouillage) ; respecte le délai imposé après trop d'essais. */
export function CodePrompt({
  title,
  onSubmit,
  onClose,
  initialWait = 0,
}: {
  title: string;
  onSubmit: (code: string) => Promise<void>;
  onClose: () => void;
  /** Secondes d'attente déjà imposées par le moteur à l'ouverture. */
  initialWait?: number;
}) {
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [wait, setWait] = useState(initialWait);

  // Compte à rebours : le bouton Valider se réactive tout seul à la fin du délai.
  useEffect(() => {
    if (wait <= 0) return;
    const timer = setTimeout(() => setWait((w) => w - 1), 1000);
    return () => clearTimeout(timer);
  }, [wait]);

  async function submit() {
    setBusy(true);
    setError(null);
    try {
      await onSubmit(code);
      onClose();
    } catch (failure) {
      const { title: message, retryAfter } = describeError(failure);
      if (retryAfter !== undefined) setWait(retryAfter);
      setError(retryAfter !== undefined ? `${message} Réessayer dans ${retryAfter} s.` : message);
      setCode("");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal title={title} onClose={onClose}>
      <form
        className="form"
        onSubmit={(e) => {
          e.preventDefault();
          if (wait <= 0 && code.length >= 4) void submit();
        }}
      >
        <Keypad value={code} onChange={setCode} disabled={busy} error={wait > 0 ? `Trop d'essais : réessayez dans ${wait} s.` : (error ?? undefined)} />
        <div className="form-actions">
          <span className="form-actions__spacer" />
          <Button variant="ghost" onClick={onClose}>
            Annuler
          </Button>
          <Button variant="primary" type="submit" disabled={busy || code.length < 4 || wait > 0}>
            Valider
          </Button>
        </div>
      </form>
    </Modal>
  );
}
