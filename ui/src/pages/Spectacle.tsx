import { Play, Sparkles, Square, LogOut, Wifi } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { ApiError, unwrap } from "../api/errors";
import { useToasts } from "../components/Toasts";
import { Button, Pill, Progress, type Tone } from "../components/ui";
import { CodePrompt } from "../dashboard/CodePrompt";
import { useButtonPresses, useEngineClock, usePrograms, useTick, type ProgramSummary } from "../dashboard/useLive";
import { useEngine } from "../engine/EngineProvider";
import { haPill } from "../layout/Banner";
import { showOrder } from "../show/order";
import { useWakeLock } from "../show/useWakeLock";
import { useCatalog } from "../catalog/CatalogProvider";
import "../show/show.css";

const PRESS = { short: "court", long: "long", double: "double" } as const;

function seconds(value: number): string {
  return value >= 120 ? `${Math.floor(value / 60)} min ${Math.round(value % 60)} s` : `${Math.round(value)} s`;
}

/**
 * Écran de pilotage de la soirée : aucun lien vers la configuration, l'éditeur ou la suppression.
 * Il est rendu hors de la mise en page habituelle (pas de menu), avec sa propre barre.
 */
export function Spectacle() {
  const { status, connection, retry } = useEngine();
  const { devices } = useCatalog();
  const toasts = useToasts();
  const navigate = useNavigate();
  const programs = usePrograms();
  const presses = useButtonPresses(1);
  const clock = useEngineClock();
  const wake = useWakeLock();
  const [asking, setAsking] = useState<{ title: string; action: (code: string) => Promise<void> } | null>(null);

  const online = connection === "online";
  const locked = status?.lock.locked ?? false;
  const runs = (status?.runs ?? []).filter((r) => r.state !== "ended");
  useTick(1000, runs.length > 0);
  const tiles = showOrder(programs);
  const ha = haPill(status);
  const tone = (t: Tone) => (online ? t : "neutral");

  async function start(program: ProgramSummary, code?: string) {
    await unwrap(api.POST("/api/runs", { body: { program_id: program.id, policy: "ignore", code } }));
  }

  async function launch(program: ProgramSummary) {
    if (locked) {
      // Verrouillé : le code est demandé à chaque lancement (il n'ouvre aucune session).
      setAsking({ title: `Code pour lancer « ${program.name} »`, action: (code) => start(program, code) });
      return;
    }
    try {
      await start(program);
    } catch (error) {
      if (error instanceof ApiError && error.status === 409) toasts.info(`« ${program.name} » tourne déjà.`);
      else toasts.error(error);
    }
  }

  async function stop(runId: string) {
    try {
      await unwrap(api.POST("/api/runs/{run_id}/stop", { params: { path: { run_id: runId } } }));
    } catch (error) {
      toasts.error(error);
    }
  }

  async function stopAll() {
    try {
      await unwrap(api.POST("/api/runs/stop")); // jamais soumis au code
    } catch (error) {
      toasts.error(error);
    }
  }

  function leave() {
    if (!locked) {
      navigate("/");
      return;
    }
    // Quitter une interface verrouillée demande le code ; le moteur ne sait que « déverrouiller »,
    // quitter déverrouille donc l'interface (on peut ensuite la reverrouiller par le cadenas).
    setAsking({
      title: "Quitter le mode spectacle (déverrouille l'interface)",
      action: async (code) => {
        await unwrap(api.POST("/api/unlock", { body: { code } }));
        navigate("/");
      },
    });
  }

  const press = presses[0];
  const buttonName = (id: string) => devices?.buttons.find((b) => b.id === id)?.name ?? id;

  return (
    <div className="show">
      <header className="show__bar">
        <div className="show__status">
          <Pill tone={tone(online ? "ok" : "error")}>{online ? "Moteur connecté" : "Moteur injoignable"}</Pill>
          <Pill tone={tone(ha.tone)}>{online ? ha.text : "Home Assistant : inconnu"}</Pill>
          {wake === "active" ? <Pill tone="ok">Écran maintenu allumé</Pill> : wake !== "pending" && <Pill tone="warn">Écran non maintenu allumé</Pill>}
        </div>
        <Button variant="ghost" className="show__exit" onClick={leave} aria-label="Quitter le mode spectacle">
          <LogOut size={18} aria-hidden="true" /> Quitter
        </Button>
      </header>

      {/* Hors ligne, STOP tente tout de même l'appel : si le moteur répond, il arrête tout. */}
      <button type="button" className="show__stop" onClick={() => void stopAll()}>
        <Square size={28} fill="currentColor" aria-hidden="true" /> STOP
      </button>

      {!online && (
        <div className="show__offline" role="alert">
          <Wifi size={20} aria-hidden="true" /> Moteur injoignable : les boutons physiques et les plannings continuent.
          <Button onClick={retry}>Réessayer</Button>
        </div>
      )}

      {tiles.length === 0 ? (
        <p className="show__empty">Aucun scénario n'est affiché en mode spectacle. Cochez « Afficher en mode spectacle » dans la liste des scénarios.</p>
      ) : (
        <ul className="show__tiles">
          {tiles.map((program) => {
            const run = runs.find((r) => r.program_id === program.id);
            const max = program.max_duration_s ?? undefined;
            const elapsed = run?.started_at == null ? 0 : Math.max(0, clock() - run.started_at);
            const continuous = !max;
            return (
              <li key={program.id}>
                <div className={run ? "show__tile show__tile--running" : "show__tile"} aria-label={program.name}>
                  <Sparkles className="show__icon" size={36} aria-hidden="true" />
                  <strong className="show__name">{program.name}</strong>
                  {run ? (
                    <>
                      <span className="show__meta">
                        {run.state === "queued" ? "En file d'attente" : continuous ? `${seconds(elapsed)} · en continu` : `${seconds(Math.min(elapsed, max))} / ${seconds(max)}`}
                      </span>
                      {run.state !== "queued" && <Progress label={program.name} ratio={continuous ? undefined : elapsed / max} />}
                      <button type="button" className="show__action show__action--stop" onClick={() => void stop(run.run_id)}>
                        <Square size={22} aria-hidden="true" /> Arrêter
                      </button>
                    </>
                  ) : (
                    <>
                      <span className="show__meta">{continuous ? "en continu" : seconds(max)}</span>
                      <button type="button" className="show__action" disabled={!program.valid || !online} onClick={() => void launch(program)}>
                        <Play size={22} aria-hidden="true" /> Lancer
                      </button>
                    </>
                  )}
                </div>
              </li>
            );
          })}
        </ul>
      )}

      <footer className="show__foot" aria-live="polite">
        {press ? <Pill tone="active">{buttonName(press.button_id)} : appui {PRESS[press.event]}</Pill> : <span className="muted">En attente d'un appui de bouton…</span>}
      </footer>

      {asking && <CodePrompt title={asking.title} onSubmit={asking.action} onClose={() => setAsking(null)} initialWait={0} />}
    </div>
  );
}
