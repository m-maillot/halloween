import { useState } from "react";
import { Lock, LockOpen, Square } from "lucide-react";
import { api } from "../api/client";
import { ApiError, unwrap } from "../api/errors";
import { useToasts } from "../components/Toasts";
import { Button, Pill, type Tone } from "../components/ui";
import { CodePrompt } from "../dashboard/CodePrompt";
import { useEngine, type Status } from "../engine/EngineProvider";

export function haPill(status: Status | null): { tone: Tone; text: string } {
  if (!status) return { tone: "neutral", text: "Home Assistant : inconnu" };
  const ha = status.home_assistant;
  if (ha.mode === "dry-run") return { tone: "warn", text: "Home Assistant simulé" };
  if (ha.last_error) return { tone: "error", text: "Home Assistant injoignable" };
  if (ha.last_ok_at) return { tone: "ok", text: "Home Assistant connecté" };
  return { tone: "neutral", text: "Home Assistant : pas encore contacté" };
}

function RunsPanel({ onClose }: { onClose: () => void }) {
  const { status, refresh } = useEngine();
  const toasts = useToasts();
  const runs = status?.runs ?? [];
  return (
    <div className="runs-panel" role="dialog" aria-label="Scénarios en cours">
      {runs.length === 0 && <p>Aucun scénario en cours.</p>}
      <ul>
        {runs.map((run) => (
          <li key={run.run_id}>
            <span>{run.program_id}</span>
            <Button
              variant="outline-danger"
              aria-label={`Arrêter ${run.program_id}`}
              onClick={async () => {
                try {
                  await unwrap(api.POST("/api/runs/{run_id}/stop", { params: { path: { run_id: run.run_id } } }));
                } catch (error) {
                  toasts.error(error);
                }
                await refresh();
              }}
            >
              Arrêter
            </Button>
          </li>
        ))}
      </ul>
      <Button variant="ghost" onClick={onClose}>
        Fermer
      </Button>
    </div>
  );
}

export function Banner() {
  const { status, connection, refresh } = useEngine();
  const [panel, setPanel] = useState(false);
  const [unlocking, setUnlocking] = useState(false);
  const [wait, setWait] = useState(0);
  const toasts = useToasts();
  const online = connection === "online";
  const ha = haPill(status);
  const count = status?.runs.length ?? 0;
  const locked = status?.lock.locked ?? false;
  const engineTone: Tone = online ? "ok" : connection === "connecting" ? "warn" : "error";
  const engineText = online
    ? "Moteur connecté"
    : connection === "connecting"
      ? "Connexion au moteur…"
      : "Moteur déconnecté";

  return (
    <header className="banner">
      <div className="banner__status">
        <Pill tone={engineTone}>{engineText}</Pill>
        <Pill tone={online ? ha.tone : "neutral"}>{online ? ha.text : "Home Assistant : inconnu"}</Pill>
        <span className="banner__runs">
          <button
            type="button"
            className="pill pill--emphasis"
            aria-expanded={panel}
            onClick={() => setPanel((open) => !open)}
          >
            {count === 0 ? "Aucun scénario en cours" : `${count} scénario${count > 1 ? "s" : ""} en cours`}
          </button>
          {panel && <RunsPanel onClose={() => setPanel(false)} />}
        </span>
      </div>
      <div className="banner__actions">
        <button
          type="button"
          className="pill pill--emphasis"
          disabled={!online}
          aria-label={locked ? "Verrouillé : saisir le code pour déverrouiller" : "Déverrouillé : verrouiller l'interface"}
          onClick={async () => {
            if (locked) {
              // Le délai imposé après trop d'essais n'est pas annoncé par un événement : on le relit à l'ouverture.
              const fresh = await unwrap<{ retry_after_s?: number | null }>(api.GET("/api/lock")).catch(() => null);
              setWait(fresh?.retry_after_s ?? 0);
              setUnlocking(true);
              return;
            }
            try {
              await unwrap(api.POST("/api/lock")); // verrouiller ne demande pas le code
            } catch (error) {
              // 409 : aucun code défini (c'est le moteur qui sait, l'état affiché peut dater de quelques secondes)
              if (error instanceof ApiError && error.status === 409) {
                toasts.info("Définissez d'abord un code dans Réglages, section « Code de verrouillage ».");
              } else {
                toasts.error(error);
              }
            }
            await refresh();
          }}
        >
          {locked ? <Lock size={16} aria-hidden="true" /> : <LockOpen size={16} aria-hidden="true" />}
          {locked ? "Verrouillé" : "Déverrouillé"}
        </button>
        {/* STOP n'est jamais soumis au code ni désactivé par le verrou (spec 1 §6.4). */}
        <Button
          variant="danger"
          aria-label="Arrêt d'urgence : tout arrêter"
          disabled={!online}
          onClick={async () => {
            try {
              await unwrap(api.POST("/api/runs/stop"));
            } catch (error) {
              toasts.error(error);
            }
            await refresh();
          }}
        >
          <Square size={16} fill="currentColor" aria-hidden="true" />
          STOP
        </Button>
      </div>
      {unlocking && (
        <CodePrompt
          title="Déverrouiller l'interface"
          initialWait={wait}
          onSubmit={async (code) => {
            await unwrap(api.POST("/api/unlock", { body: { code } }));
            await refresh();
          }}
          onClose={() => setUnlocking(false)}
        />
      )}
    </header>
  );
}
