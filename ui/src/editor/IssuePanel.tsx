import { AlertTriangle, CircleCheck, OctagonAlert } from "lucide-react";
import type { ValidationState } from "./useLiveValidation";
import { summary, type Located } from "./validation";

/** Panneau latéral : erreurs puis avertissements ; un clic sélectionne le bloc fautif. */
export function IssuePanel({
  issues,
  state,
  onSelect,
}: {
  issues: Located[];
  state: ValidationState;
  onSelect: (blockId: string) => void;
}) {
  const { errors, warnings } = summary(issues);
  const ordered = [...issues].sort((a, b) => Number(b.severity === "error") - Number(a.severity === "error"));
  return (
    <aside className="issue-panel" aria-label="Validation">
      <h2>Validation</h2>
      <p role="status" className="issue-panel__status">
        {state === "unavailable"
          ? "Validation indisponible : le moteur ne répond pas."
          : state === "checking"
            ? "Vérification…"
            : errors > 0
              ? `${errors} erreur${errors > 1 ? "s" : ""}${warnings ? `, ${warnings} avertissement${warnings > 1 ? "s" : ""}` : ""}`
              : warnings > 0
                ? `Valide, ${warnings} avertissement${warnings > 1 ? "s" : ""}`
                : state === "done"
                  ? "Scénario valide"
                  : ""}
      </p>
      {ordered.length === 0 && state === "done" && (
        <p className="muted">
          <CircleCheck size={16} aria-hidden="true" /> Aucun problème.
        </p>
      )}
      <ul className="issue-list">
        {ordered.map((issue, i) => (
          <li key={`${issue.code}-${issue.node_id}-${i}`}>
            <button
              type="button"
              className={`issue issue--${issue.severity}`}
              disabled={!issue.blockId}
              onClick={() => issue.blockId && onSelect(issue.blockId)}
            >
              {issue.severity === "error" ? <OctagonAlert size={16} aria-hidden="true" /> : <AlertTriangle size={16} aria-hidden="true" />}
              <span>
                <strong>{issue.severity === "error" ? "Erreur" : "Avertissement"}</strong> {issue.message}
              </span>
            </button>
          </li>
        ))}
      </ul>
    </aside>
  );
}
