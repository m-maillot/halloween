import { useState } from "react";
import { formErrors, type FormErrors } from "../api/errors";
import type { Devices } from "../catalog/CatalogProvider";
import { Button, CheckField, Field, Modal, SelectField } from "../components/ui";
import { describe, parseCron, scheduleProblem, toCron, DAY_LABELS, MONTH_LABELS, type Schedule } from "./cron";
import { EVENT_LABEL, POLICY_LABEL, duplicates, newId, type ButtonTrigger, type PressEvent, type Policy, type ScheduleTrigger, type Trigger } from "./model";

type Mode = Schedule["mode"];
const MODE_LABEL: Record<Mode, string> = {
  daily: "Tous les jours",
  weekdays: "Certains jours de la semaine",
  date: "Une date précise chaque année",
  advanced: "Expression cron avancée",
};

/** Création / modification d'une règle ; `onSave` reçoit la règle et peut refuser (le moteur a le dernier mot). */
export function TriggerForm({
  existing,
  all,
  devices,
  programs,
  onSave,
  onClose,
}: {
  existing?: Trigger;
  all: Trigger[];
  devices: Devices | null;
  programs: { id: string; name: string }[];
  onSave: (trigger: Trigger) => Promise<void>;
  onClose: () => void;
}) {
  const buttons = devices?.buttons ?? [];
  const [source, setSource] = useState<Trigger["source"]>(existing?.source ?? "button");
  const [button, setButton] = useState(existing?.source === "button" ? existing.button : (buttons[0]?.id ?? ""));
  const [event, setEvent] = useState<PressEvent>(existing?.source === "button" ? existing.event : "short");
  const [stop, setStop] = useState(existing?.source === "button" && existing.action === "stop");
  const [program, setProgram] = useState(existing?.program ?? programs[0]?.id ?? "");
  const [policy, setPolicy] = useState<Policy>(existing?.policy ?? "ignore");
  const [enabled, setEnabled] = useState(existing?.enabled ?? true);
  const [timezone, setTimezone] = useState(existing?.source === "schedule" ? (existing.timezone ?? "") : "");
  const [schedule, setSchedule] = useState<Schedule>(
    existing?.source === "schedule" ? parseCron(existing.cron) : { mode: "date", day: 31, month: 10, hour: 18, minute: 0 },
  );
  const [errors, setErrors] = useState<FormErrors>({ fields: {} });
  const [busy, setBusy] = useState(false);
  const [suggested, setSuggested] = useState(false);

  const problem = source === "schedule" ? scheduleProblem(schedule) : null;
  const candidate: Trigger | null =
    source === "button"
      ? { id: existing?.id ?? newId(all, "button"), source: "button", button, event, ...(stop ? { action: "stop" as const } : { program }), policy: stop ? "ignore" : policy, enabled }
      : { id: existing?.id ?? newId(all, "schedule"), source: "schedule", cron: toCron(schedule), ...(timezone.trim() ? { timezone: timezone.trim() } : {}), program, policy, enabled };
  const clash = candidate ? duplicates([...all.filter((t) => t.id !== candidate.id), candidate]).get(candidate.id) : undefined;
  const complete = source === "button" ? Boolean(button) && (stop || Boolean(program)) : Boolean(program);

  function chooseEvent(next: PressEvent) {
    setEvent(next);
    // Un appui long sert d'ordinaire d'arrêt : on le propose, sans l'imposer.
    if (next === "long" && !stop && !suggested && !existing) {
      setStop(true);
      setSuggested(true);
    }
  }

  const time = schedule.mode === "advanced" ? null : schedule;
  const weekdays = schedule.mode === "weekdays" ? schedule : null;
  const setTime = (patch: Partial<{ hour: number; minute: number }>) => setSchedule((s) => (s.mode === "advanced" ? s : { ...s, ...patch }));

  return (
    <Modal title={existing ? "Modifier la règle" : "Nouvelle règle"} onClose={onClose}>
      <form
        className="form"
        onSubmit={async (e) => {
          e.preventDefault();
          if (!candidate) return;
          setBusy(true);
          setErrors({ fields: {} });
          try {
            await onSave(candidate);
          } catch (error) {
            setErrors(formErrors(error));
          } finally {
            setBusy(false);
          }
        }}
      >
        <SelectField label="Déclenché par" value={source} disabled={Boolean(existing)} onChange={(e) => setSource(e.target.value as Trigger["source"])}>
          <option value="button">Un bouton physique</option>
          <option value="schedule">Un planning</option>
        </SelectField>

        {source === "button" ? (
          <>
            <SelectField label="Bouton" value={button} onChange={(e) => setButton(e.target.value)} error={errors.fields.button}>
              {buttons.length === 0 && <option value="">Aucun bouton : créez-en un dans Composants</option>}
              {buttons.map((b) => (
                <option key={b.id} value={b.id}>
                  {b.name}
                </option>
              ))}
            </SelectField>
            <SelectField label="Événement" value={event} onChange={(e) => chooseEvent(e.target.value as PressEvent)}>
              {(Object.keys(EVENT_LABEL) as PressEvent[]).map((k) => (
                <option key={k} value={k}>
                  {EVENT_LABEL[k]}
                </option>
              ))}
            </SelectField>
            <SelectField label="Action" value={stop ? "stop" : "run"} onChange={(e) => setStop(e.target.value === "stop")}>
              <option value="run">Lancer un scénario</option>
              <option value="stop">Arrêter tout (arrêt d'urgence)</option>
            </SelectField>
            {suggested && stop && <p className="muted">Un appui long arrête d'ordinaire tout : proposé ici, vous pouvez le changer.</p>}
          </>
        ) : (
          <fieldset className="field-group">
            <legend className="field__label">Quand</legend>
            <SelectField
              label="Répétition"
              value={schedule.mode}
              onChange={(e) => {
                const mode = e.target.value as Mode;
                const base = { hour: time?.hour ?? 18, minute: time?.minute ?? 0 };
                setSchedule(
                  mode === "advanced"
                    ? { mode, cron: toCron(schedule) }
                    : mode === "weekdays"
                      ? { mode, days: [6, 7], ...base }
                      : mode === "date"
                        ? { mode, day: 31, month: 10, ...base }
                        : { mode, ...base },
                );
              }}
            >
              {(Object.keys(MODE_LABEL) as Mode[]).map((m) => (
                <option key={m} value={m}>
                  {MODE_LABEL[m]}
                </option>
              ))}
            </SelectField>
            {weekdays && (
              <div role="group" aria-label="Jours">
                {DAY_LABELS.map((label, i) => (
                  <CheckField
                    key={label}
                    label={label}
                    checked={weekdays.days.includes(i + 1)}
                    onChange={(e) =>
                      setSchedule({ ...weekdays, days: e.target.checked ? [...weekdays.days, i + 1] : weekdays.days.filter((d) => d !== i + 1) })
                    }
                  />
                ))}
              </div>
            )}
            {schedule.mode === "date" && (
              <div className="simulation__form">
                <Field label="Jour" type="number" min="1" max="31" value={schedule.day} onChange={(e) => setSchedule({ ...schedule, day: Number(e.target.value) })} />
                <SelectField label="Mois" value={schedule.month} onChange={(e) => setSchedule({ ...schedule, month: Number(e.target.value) })}>
                  {MONTH_LABELS.map((label, i) => (
                    <option key={label} value={i + 1}>
                      {label}
                    </option>
                  ))}
                </SelectField>
              </div>
            )}
            {schedule.mode === "advanced" ? (
              <Field
                label="Expression cron"
                value={schedule.cron}
                hint="Minute, heure, jour du mois, mois, jour de la semaine (ex. 0 18 31 10 *)."
                error={errors.fields.cron}
                onChange={(e) => setSchedule({ mode: "advanced", cron: e.target.value })}
              />
            ) : (
              <div className="simulation__form">
                <Field label="Heure" type="number" min="0" max="23" value={schedule.hour} onChange={(e) => setTime({ hour: Number(e.target.value) })} />
                <Field label="Minute" type="number" min="0" max="59" value={schedule.minute} onChange={(e) => setTime({ minute: Number(e.target.value) })} />
              </div>
            )}
            <Field label="Fuseau horaire" value={timezone} placeholder="celui du Raspberry Pi" hint="Facultatif, ex. Europe/Paris." onChange={(e) => setTimezone(e.target.value)} />
            <p role="status" className={problem ? "field__error" : "pill pill--emphasis"}>
              {problem ?? `Se déclenchera ${describe(schedule)}.`}
            </p>
          </fieldset>
        )}

        {!(source === "button" && stop) && (
          <>
            <SelectField label="Scénario à lancer" value={program} onChange={(e) => setProgram(e.target.value)} error={errors.fields.program}>
              {programs.length === 0 && <option value="">Aucun scénario</option>}
              {programs.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </SelectField>
            <SelectField label="S'il tourne déjà" value={policy} onChange={(e) => setPolicy(e.target.value as Policy)}>
              {(Object.keys(POLICY_LABEL) as Policy[]).map((p) => (
                <option key={p} value={p}>
                  {p === "ignore" ? "L'ignorer (défaut)" : p === "restart" ? "Le redémarrer" : "Le mettre en file"}
                </option>
              ))}
            </SelectField>
          </>
        )}
        <CheckField label="Règle active" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} />

        {clash && (
          <p className="form-error" role="alert">
            Attention : une autre règle active vise déjà ce bouton avec cet événement ({clash.join(", ")}). Les deux se déclencheront.
          </p>
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
        <div className="form-actions">
          <span className="form-actions__spacer" />
          <Button variant="ghost" onClick={onClose}>
            Annuler
          </Button>
          <Button variant="primary" type="submit" disabled={busy || Boolean(problem) || !complete}>
            Enregistrer
          </Button>
        </div>
      </form>
    </Modal>
  );
}

export type { ButtonTrigger, ScheduleTrigger };
