import { useState } from "react";
import { currentToken, setToken } from "../api/token";
import { Button, Field } from "../components/ui";
import { useToasts } from "../components/Toasts";
import { useEngine } from "../engine/EngineProvider";

/** Jeton d'accès à l'API du moteur, mémorisé dans ce navigateur uniquement. */
export function EngineTokenSection() {
  const toasts = useToasts();
  const { retry } = useEngine();
  const [value, setValue] = useState("");
  const saved = currentToken() !== null;

  return (
    <section className="settings-section" aria-labelledby="set-token">
      <h2 id="set-token">Jeton du moteur</h2>
      <form
        className="form"
        onSubmit={(e) => {
          e.preventDefault();
          if (!value.trim()) return;
          setToken(value.trim());
          setValue("");
          retry(); // la connexion temps réel repart avec le nouveau jeton
          toasts.info("Jeton enregistré dans ce navigateur.");
        }}
      >
        <Field
          label="Jeton d'accès à l'API"
          type="password"
          autoComplete="off"
          value={value}
          placeholder={saved ? "enregistré" : ""}
          hint="Contenu du fichier api-token du moteur. Il n'est mémorisé que dans ce navigateur."
          onChange={(e) => setValue(e.target.value)}
        />
        <div className="form-actions">
          <Button variant="outline-danger" onClick={() => setToken(null)} disabled={!saved}>
            Oublier le jeton
          </Button>
          <span className="form-actions__spacer" />
          <Button variant="primary" type="submit" disabled={!value.trim()}>
            Enregistrer
          </Button>
        </div>
      </form>
    </section>
  );
}
