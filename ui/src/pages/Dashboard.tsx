import { Play, Square } from "lucide-react";
import { PRESS_TEXT } from "../triggers/model";
import { useMemo, useState } from "react";
import { api } from "../api/client";
import { unwrap } from "../api/errors";
import { useCatalog, type Devices } from "../catalog/CatalogProvider";
import { ComponentImage, type Kind } from "../catalog/icons";
import { TestPanel } from "../catalog/TestPanel";
import type { Existing } from "../catalog/draft";
import { useToasts } from "../components/Toasts";
import { Button, Card, Modal, Pill, Progress } from "../components/ui";
import { CodePrompt } from "../dashboard/CodePrompt";
import {
  useButtonPresses,
  useEngineClock,
  useLightStates,
  usePrograms,
  useTick,
  type LiveState,
} from "../dashboard/useLive";
import { useEngine } from "../engine/EngineProvider";


type Tile = { kind: Exclude<Kind, "buttons">; item: Existing };

function stateOf(tile: Tile, relays: Record<string, boolean>, live: Record<string, LiveState>): LiveState {
  if (tile.kind === "relays") {
    return { state: relays[tile.item.id] === undefined ? "unknown" : relays[tile.item.id] ? "on" : "off" };
  }
  return live[tile.item.id] ?? { state: "unknown" };
}

const STATE_TEXT = { on: "Allumé", off: "Éteint", unknown: "État inconnu" } as const;

function swatch([r, g, b]: [number, number, number]): string {
  return `rgb(${r}, ${g}, ${b})`;
}

function seconds(value: number): string {
  return value >= 120 ? `${Math.floor(value / 60)} min ${Math.round(value % 60)} s` : `${Math.round(value)} s`;
}

export function Dashboard() {
  const { status } = useEngine();
  const { devices } = useCatalog();
  const toasts = useToasts();
  const programs = usePrograms();
  const presses = useButtonPresses();
  const clock = useEngineClock();
  const [testing, setTesting] = useState<Tile | null>(null);
  const [asking, setAsking] = useState<string | null>(null);

  const entityOf = useMemo(() => {
    const map: Record<string, string> = {};
    for (const item of [...(devices?.lights ?? []), ...(devices?.switches ?? [])]) map[item.id] = item.entity_id;
    return map;
  }, [devices]);
  const live = useLightStates(entityOf);

  const locked = status?.lock.locked ?? false;
  const runs = (status?.runs ?? []).filter((run) => run.state !== "ended");
  useTick(1000, runs.length > 0); // la progression avance seule entre deux événements
  const tiles: Tile[] = devices
    ? [
        ...devices.relays.map((item) => ({ kind: "relays" as const, item })),
        ...devices.lights.map((item) => ({ kind: "lights" as const, item })),
        ...devices.switches.map((item) => ({ kind: "switches" as const, item })),
      ]
    : [];
  const buttonName = (id: string) => devices?.buttons.find((b) => b.id === id)?.name ?? id;

  async function toggle(tile: Tile, current: LiveState) {
    const push = tile.kind === "relays" && (tile.item as Devices["relays"][number]).mode === "push";
    const action = push ? "trigger" : current.state === "on" ? "off" : "on";
    try {
      await unwrap(
        api.POST("/api/components/{kind}/{component_id}/test", {
          params: { path: { kind: tile.kind, component_id: tile.item.id } },
          body: { action, event: "short" }, // `event` ne sert qu'aux boutons (le contrat le déclare obligatoire)
        }),
      );
    } catch (error) {
      toasts.error(error);
    }
  }

  async function start(programId: string, code?: string) {
    await unwrap(api.POST("/api/runs", { body: { program_id: programId, policy: "ignore", code } }));
  }

  async function launch(programId: string) {
    if (locked) {
      setAsking(programId); // verrouillé : le code est exigé à chaque lancement
      return;
    }
    try {
      await start(programId);
    } catch (error) {
      toasts.error(error);
    }
  }

  async function stop(runId: string) {
    try {
      await unwrap(api.POST("/api/runs/{run_id}/stop", { params: { path: { run_id: runId } } }));
    } catch (error) {
      toasts.error(error);
    }
  }

  const programName = (id: string) => programs.find((p) => p.id === id)?.name ?? id;

  return (
    <>
      <h1>Tableau de bord</h1>

      <section aria-labelledby="dash-runs">
        <h2 id="dash-runs">Scénarios</h2>
        {runs.length > 0 && (
          <ul className="run-list" aria-label="Scénarios en cours">
            {runs.map((run) => {
              const max = programs.find((p) => p.id === run.program_id)?.max_duration_s ?? undefined;
              const elapsed = run.started_at == null ? 0 : Math.max(0, clock() - run.started_at);
              return (
                <li key={run.run_id}>
                  <Card>
                    <div className="run-row">
                      <div className="run-row__text">
                        <strong>{programName(run.program_id)}</strong>
                        <span className="muted">
                          {run.state === "queued"
                            ? "En file d'attente"
                            : max
                              ? `${seconds(Math.min(elapsed, max))} / ${seconds(max)}`
                              : `${seconds(elapsed)} · en continu`}
                        </span>
                      </div>
                      <Button variant="outline-danger" onClick={() => void stop(run.run_id)}>
                        <Square size={16} aria-hidden="true" /> Arrêter
                      </Button>
                    </div>
                    {run.state !== "queued" && (
                      <Progress label={programName(run.program_id)} ratio={max ? elapsed / max : undefined} />
                    )}
                  </Card>
                </li>
              );
            })}
          </ul>
        )}
        {programs.length === 0 ? (
          <p className="muted">Aucun scénario pour le moment.</p>
        ) : (
          <ul className="grid">
            {programs.map((program) => (
              <li key={program.id}>
                <Card label={program.name}>
                  <div className="run-row">
                    <div className="run-row__text">
                      <strong>{program.name}</strong>
                      <span className="muted">
                        {program.valid ? (program.max_duration_s ? seconds(program.max_duration_s) : "en continu") : "invalide"}
                      </span>
                    </div>
                    <Button variant="primary" disabled={!program.valid} onClick={() => void launch(program.id)}>
                      <Play size={16} aria-hidden="true" /> Lancer
                    </Button>
                  </div>
                </Card>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section aria-labelledby="dash-components">
        <h2 id="dash-components">Composants</h2>
        {locked && <p className="muted">Interface verrouillée : les tests manuels sont indisponibles.</p>}
        {!devices ? (
          <p className="muted">Chargement…</p>
        ) : tiles.length === 0 ? (
          <p className="muted">Aucun composant. Ajoutez-en depuis l'écran Composants.</p>
        ) : (
          <ul className="grid">
            {tiles.map((tile) => {
              const current = stateOf(tile, status?.relays ?? {}, live);
              const push = tile.kind === "relays" && (tile.item as Devices["relays"][number]).mode === "push";
              const light = tile.kind === "lights" ? (tile.item as Devices["lights"][number]) : null;
              const richer = light && (light.supports_color || light.supports_brightness || light.supports_transition);
              return (
                <li key={tile.item.id}>
                  <Card label={tile.item.name}>
                    <div className="component-card">
                      <ComponentImage kind={tile.kind} image={tile.item.image} imageUrl={tile.item.image_url} size={44} />
                      <div className="component-card__text">
                        <strong>{tile.item.name}</strong>
                        {!push && (
                          <Pill tone={current.state === "on" ? "active" : "neutral"} emphasis={current.state === "on"}>
                            {STATE_TEXT[current.state]}
                            {current.rgb && current.state === "on" && (
                              <span className="swatch" style={{ background: swatch(current.rgb) }} aria-hidden="true" />
                            )}
                          </Pill>
                        )}
                        <div className="form-actions">
                          <Button disabled={locked} onClick={() => void toggle(tile, current)}>
                            {push ? "Déclencher" : current.state === "on" ? "Éteindre" : "Allumer"}
                          </Button>
                          {richer && (
                            <Button variant="ghost" disabled={locked} onClick={() => setTesting(tile)}>
                              Réglages…
                            </Button>
                          )}
                        </div>
                      </div>
                    </div>
                  </Card>
                </li>
              );
            })}
          </ul>
        )}
      </section>

      <section aria-labelledby="dash-buttons">
        <h2 id="dash-buttons">Boutons physiques</h2>
        {presses.length === 0 ? (
          <p className="muted">Aucun appui reçu. Appuyez sur un bouton pour vérifier le câblage.</p>
        ) : (
          <ul className="press-list" aria-live="polite">
            {presses.map((press, i) => (
              <li key={`${press.at}-${i}`}>
                <Pill tone={i === 0 ? "active" : "neutral"} emphasis={i === 0}>
                  {buttonName(press.button_id)} : {PRESS_TEXT[press.event]} à{" "}
                  {new Date(press.at).toLocaleTimeString("fr-FR")}
                </Pill>
              </li>
            ))}
          </ul>
        )}
      </section>

      {testing && (
        <Modal title={`Réglages de ${testing.item.name}`} onClose={() => setTesting(null)}>
          <TestPanel kind={testing.kind} item={testing.item} />
          <div className="form-actions">
            <span className="form-actions__spacer" />
            <Button onClick={() => setTesting(null)}>Fermer</Button>
          </div>
        </Modal>
      )}
      {asking && (
        <CodePrompt
          title={`Code pour lancer « ${programName(asking)} »`}
          onSubmit={(code) => start(asking, code)}
          onClose={() => setAsking(null)}
        />
      )}
    </>
  );
}
