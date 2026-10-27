import { useEffect, useState } from "react";
import { api } from "../api/client";
import { ApiError, formErrors, unwrap, type FormErrors } from "../api/errors";
import type { components } from "../api/schema";
import { Button, CheckField, Field } from "../components/ui";
import { useToasts } from "../components/Toasts";
import { useEngine } from "../engine/EngineProvider";

type HaConfig = components["schemas"]["HaConfigOut"];
type TestOut = components["schemas"]["HaTestOut"];

/** Intitulé de l'échec d'après la classe d'erreur renvoyée par le moteur. */
const FAILURE_TITLE: Record<string, string> = {
  HAUnreachable: "URL injoignable",
  HATimeout: "Délai dépassé",
  HAAuthError: "Jeton refusé",
  HANotFound: "Adresse inconnue de Home Assistant",
  HAServerError: "Erreur de Home Assistant",
};

export function HomeAssistantSection({ disabled }: { disabled: boolean }) {
  const toasts = useToasts();
  const { refresh } = useEngine();
  const [config, setConfig] = useState<HaConfig | null>(null);
  const [url, setUrl] = useState("");
  const [token, setToken] = useState("");
  const [timeout, setTimeout_] = useState("5");
  const [clearToken, setClearToken] = useState(false);
  const [errors, setErrors] = useState<FormErrors>({ fields: {} });
  const [result, setResult] = useState<TestOut | null>(null);
  const [needsStop, setNeedsStop] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;
    unwrap<HaConfig>(api.GET("/api/config/home-assistant"))
      .then((loaded) => {
        if (cancelled) return;
        setConfig(loaded);
        setUrl(loaded.url ?? "");
        setTimeout_(String(loaded.timeout_s));
      })
      .catch((error) => !cancelled && toasts.error(error));
    return () => {
      cancelled = true;
    };
    // Le chargement n'a lieu qu'à l'ouverture.
  }, []);

  async function test() {
    setBusy(true);
    setResult(null);
    try {
      setResult(
        await unwrap<TestOut>(
          api.POST("/api/config/home-assistant/test", {
            body: { url: url.trim() || null, token: token || null, timeout_s: Number(timeout) || null },
          }),
        ),
      );
    } catch (error) {
      toasts.error(error);
    } finally {
      setBusy(false);
    }
  }

  async function save(stopRuns = false) {
    setBusy(true);
    setErrors({ fields: {} });
    setNeedsStop(null);
    try {
      await unwrap(
        api.PUT("/api/config/home-assistant", {
          params: { query: { stop_runs: stopRuns } },
          // absent : jeton inchangé ; chaîne vide : le supprimer
          body: { url: url.trim(), token: clearToken ? "" : token || null, timeout_s: Number(timeout) || 5 },
        }),
      );
      const fresh = await unwrap<HaConfig>(api.GET("/api/config/home-assistant"));
      setConfig(fresh);
      setToken("");
      setClearToken(false);
      toasts.info("Connexion Home Assistant enregistrée.");
      void refresh();
    } catch (error) {
      if (error instanceof ApiError && error.status === 409 && JSON.stringify(error.body).includes("stop_runs")) {
        setNeedsStop(formErrors(error).general?.title ?? "Des scénarios tournent.");
      } else {
        setErrors(formErrors(error));
      }
    } finally {
      setBusy(false);
    }
  }

  const fromEnv = config?.token_source === "env";

  return (
    <section className="settings-section" aria-labelledby="set-ha">
      <h2 id="set-ha">Home Assistant</h2>
      <form
        className="form"
        onSubmit={(e) => {
          e.preventDefault();
          void save();
        }}
      >
        <Field
          label="Adresse (URL)"
          value={url}
          placeholder="http://homeassistant.local:8123"
          disabled={disabled}
          error={errors.fields.url}
          onChange={(e) => setUrl(e.target.value)}
        />
        <Field
          label="Jeton d'accès"
          type="password"
          autoComplete="off"
          value={token}
          disabled={disabled || clearToken}
          placeholder={config?.token_set ? "inchangé" : ""}
          hint={
            fromEnv
              ? "Le jeton vient de la variable HALLOWEEN_HA_TOKEN du service : il remplace celui saisi ici."
              : config?.token_set
                ? "Un jeton est enregistré. Laissez vide pour le conserver."
                : "Aucun jeton enregistré. À créer dans Home Assistant (profil, jetons d'accès de longue durée)."
          }
          onChange={(e) => setToken(e.target.value)}
        />
        {config?.token_source === "config" && (
          <CheckField
            label="Supprimer le jeton enregistré"
            checked={clearToken}
            disabled={disabled}
            onChange={(e) => setClearToken(e.target.checked)}
          />
        )}
        <Field
          label="Délai maximal d'un appel (s)"
          type="number"
          min="1"
          max="60"
          value={timeout}
          disabled={disabled}
          error={errors.fields.timeout_s}
          onChange={(e) => setTimeout_(e.target.value)}
        />

        {result && (
          <div className={result.ok ? "form-ok" : "form-error"} role="status">
            <strong>{result.ok ? "Connexion réussie" : (result.error_type && FAILURE_TITLE[result.error_type]) || "Échec de la connexion"}</strong>
            <span>
              {result.message}
              {result.ok && result.latency_ms != null && ` (${Math.round(result.latency_ms)} ms)`}
            </span>
          </div>
        )}
        {errors.general && (
          <div className="form-error" role="alert">
            <strong>{errors.general.title}</strong>
            {errors.general.details.length > 0 && (
              <ul>
                {errors.general.details.map((line, i) => (
                  <li key={i}>{line}</li>
                ))}
              </ul>
            )}
          </div>
        )}
        {needsStop && (
          <div className="form-error" role="alert">
            <strong>{needsStop}</strong>
            <Button variant="danger" onClick={() => void save(true)}>
              Arrêter les scénarios et continuer
            </Button>
          </div>
        )}
        <div className="form-actions">
          <Button disabled={busy || disabled || !url.trim()} onClick={() => void test()}>
            Tester la connexion
          </Button>
          <span className="form-actions__spacer" />
          <Button variant="primary" type="submit" disabled={busy || disabled || !url.trim()}>
            Enregistrer
          </Button>
        </div>
        <span className="field__hint">
          Le test utilise les valeurs saisies, même non enregistrées. Un champ jeton vide teste le jeton actuel.
        </span>
      </form>
    </section>
  );
}
