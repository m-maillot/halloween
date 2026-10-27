import { Plus } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { api } from "../api/client";
import { unwrap } from "../api/errors";
import type { components } from "../api/schema";
import { useCatalog } from "../catalog/CatalogProvider";
import { useToasts } from "../components/Toasts";
import { Button, Card, Pill } from "../components/ui";
import { useEngine } from "../engine/EngineProvider";
import { describe, parseCron } from "../triggers/cron";
import { buttonName, duplicates, EVENT_LABEL, POLICY_LABEL, type Trigger } from "../triggers/model";
import { TriggerForm } from "../triggers/TriggerForm";

type Issue = components["schemas"]["IssueOut"];
type Program = { id: string; name: string };

export function Triggers() {
  const { devices } = useCatalog();
  const { status } = useEngine();
  const toasts = useToasts();
  const [triggers, setTriggers] = useState<Trigger[] | null>(null);
  const [issues, setIssues] = useState<Issue[]>([]);
  const [programs, setPrograms] = useState<Program[]>([]);
  const [editing, setEditing] = useState<Trigger | "new" | null>(null);
  const locked = status?.lock.locked ?? false;

  const load = useCallback(() => {
    unwrap<{ triggers: Trigger[]; issues: Issue[] }>(api.GET("/api/triggers"))
      .then((out) => {
        setTriggers(out.triggers);
        setIssues(out.issues);
      })
      .catch((error) => toasts.error(error));
    unwrap<Program[]>(api.GET("/api/programs")).then(setPrograms).catch(() => undefined);
  }, [toasts]);
  useEffect(load, [load]);

  /** Le moteur remplace toute la liste d'un coup ; sa réponse (avertissements compris) fait foi. */
  async function persist(next: Trigger[]) {
    const out = await unwrap<{ triggers: Trigger[]; issues: Issue[] }>(api.PUT("/api/triggers", { body: next as never }));
    setTriggers(out.triggers);
    setIssues(out.issues);
  }

  async function run(next: Trigger[]) {
    try {
      await persist(next);
    } catch (error) {
      toasts.error(error);
    }
  }

  const list = triggers ?? [];
  const clash = duplicates(list);
  const programName = (id: string) => programs.find((p) => p.id === id)?.name ?? id;
  const missingLong = (devices?.buttons ?? []).filter((b) => !list.some((t) => t.source === "button" && t.button === b.id && t.event === "long"));

  return (
    <>
      <div className="page-head">
        <h1>Déclencheurs</h1>
        <Button variant="primary" disabled={locked || !triggers} onClick={() => setEditing("new")}>
          <Plus size={18} aria-hidden="true" /> Nouvelle règle
        </Button>
      </div>
      {locked && <p className="muted">Interface verrouillée : les règles sont en lecture seule.</p>}

      {issues.filter((i) => i.severity === "error").length > 0 && (
        <div className="form-error" role="alert">
          <strong>Des règles sont écartées par le moteur :</strong>
          <ul>
            {issues
              .filter((i) => i.severity === "error")
              .map((i, n) => (
                <li key={n}>{i.message}</li>
              ))}
          </ul>
        </div>
      )}

      {triggers === null ? (
        <p className="muted">Chargement…</p>
      ) : list.length === 0 ? (
        <p className="muted">Aucune règle. Créez la première : par exemple, un appui court sur le bouton d'entrée lance le scénario principal.</p>
      ) : (
        <ul className="rule-list">
          {list.map((t) => {
            const label = t.source === "button" ? `Quand ${buttonName(devices, t.button)} reçoit ${EVENT_LABEL[t.event]}` : `Quand c'est ${describe(parseCron(t.cron))}`;
            const action = t.source === "button" && t.action === "stop" ? "Arrêter tout" : `Lancer : ${programName(t.program ?? "")}`;
            const warning = issues.find((i) => i.severity === "warning" && i.component_id === t.id);
            return (
              <li key={t.id}>
                <Card label={`${label} → ${action}`}>
                  <p className="rule">
                    <strong>{label}</strong> → {action}
                  </p>
                  <div className="form-actions">
                    <Pill tone={t.enabled ? "ok" : "neutral"}>{t.enabled ? "Active" : "Désactivée"}</Pill>
                    {!(t.source === "button" && t.action === "stop") && <Pill>{POLICY_LABEL[t.policy]}</Pill>}
                    <span className="form-actions__spacer" />
                    <Button variant="ghost" disabled={locked} onClick={() => void run(list.map((x) => (x.id === t.id ? { ...x, enabled: !x.enabled } : x)))}>
                      {t.enabled ? "Désactiver" : "Activer"}
                    </Button>
                    <Button disabled={locked} onClick={() => setEditing(t)}>
                      Modifier
                    </Button>
                    <Button variant="outline-danger" disabled={locked} onClick={() => void run(list.filter((x) => x.id !== t.id))}>
                      Supprimer
                    </Button>
                  </div>
                  {(clash.has(t.id) || warning) && (
                    <p className="field__error" role="alert">
                      {clash.has(t.id) ? `Même bouton et même événement que : ${clash.get(t.id)!.join(", ")}.` : warning!.message}
                    </p>
                  )}
                </Card>
              </li>
            );
          })}
        </ul>
      )}

      {triggers !== null && missingLong.length > 0 && !locked && (
        <section aria-label="Suggestions" className="settings-section">
          <h2>Suggestion</h2>
          {missingLong.map((b) => (
            <div key={b.id} className="form-actions">
              <span>« {b.name} » n'a pas de règle d'appui long. Un appui long sert d'ordinaire d'arrêt d'urgence.</span>
              <span className="form-actions__spacer" />
              <Button
                onClick={() => {
                  const id = `regle-${b.id}-long`.slice(0, 60);
                  void run([...list, { id: list.some((t) => t.id === id) ? `${id}-2` : id, source: "button", button: b.id, event: "long", action: "stop", policy: "ignore", enabled: true }]);
                }}
              >
                Ajouter « appui long → Arrêter »
              </Button>
            </div>
          ))}
        </section>
      )}

      {editing && (
        <TriggerForm
          key={editing === "new" ? "new" : editing.id}
          existing={editing === "new" ? undefined : editing}
          all={list}
          devices={devices}
          programs={programs}
          onClose={() => setEditing(null)}
          onSave={async (trigger) => {
            const next = editing === "new" ? [...list, trigger] : list.map((t) => (t.id === trigger.id ? trigger : t));
            await persist(next);
            setEditing(null);
            toasts.info("Règle enregistrée.");
          }}
        />
      )}
    </>
  );
}
