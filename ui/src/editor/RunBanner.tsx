import { Pill } from "../components/ui";
import { OUTCOME_TEXT, isRunning, type RunView } from "./runView";
import { formatSeconds } from "./timeline";
import { Button } from "../components/ui";

/** Bandeau d'exécution : en cours, puis issue et durée ; les erreurs d'actions y sont listées. */
export function RunBanner({ view, onDismiss }: { view: RunView; onDismiss: () => void }) {
  if (!view.runId) return null;
  const running = isRunning(view);
  const outcome = view.ended?.outcome ? OUTCOME_TEXT[view.ended.outcome] : undefined;
  return (
    <div className="run-banner" role="status" aria-label="Exécution">
      {running ? (
        <Pill tone="active" emphasis>
          Scénario en cours…
        </Pill>
      ) : (
        <>
          <Pill tone={outcome?.tone ?? "neutral"} emphasis>
            {outcome?.text ?? "Terminé"}
            {view.ended?.durationS != null && ` · ${formatSeconds(view.ended.durationS)}`}
          </Pill>
          {view.ended?.error && <span className="muted">{view.ended.error}</span>}
          <Button variant="ghost" onClick={onDismiss}>
            Fermer
          </Button>
        </>
      )}
      {view.errors.length > 0 && (
        <ul className="run-banner__errors" aria-label="Erreurs pendant l'exécution">
          {view.errors.map((error, i) => (
            <li key={i}>{error.message}</li>
          ))}
        </ul>
      )}
    </div>
  );
}
