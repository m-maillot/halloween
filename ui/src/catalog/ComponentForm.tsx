import { useEffect, useState } from "react";
import { api } from "../api/client";
import { ApiError, formErrors, type FormErrors } from "../api/errors";
import { Button, CheckField, Field, Modal, SelectField } from "../components/ui";
import { useToasts } from "../components/Toasts";
import { useEngine } from "../engine/EngineProvider";
import { useCatalog } from "./CatalogProvider";
import { bodyOf, draftOf, usedPins, type Draft, type Existing } from "./draft";
import { ImagePicker } from "./ImagePicker";
import { KIND_LABEL, type Kind } from "./icons";
import { TestPanel } from "./TestPanel";
import { deleteComponent, saveComponent } from "./write";

const TITLE: Record<Kind, string> = {
  relays: "relais",
  buttons: "bouton",
  lights: "lumière",
  switches: "interrupteur",
};

const GPIO_PINS = Array.from({ length: 26 }, (_, i) => i + 2); // BCM 2 à 27

interface Entity {
  entity_id: string;
  name: string;
  capabilities?: { color: boolean; brightness: boolean; transition: boolean } | null;
}

/** Entités Home Assistant du domaine ; `failed` si le moteur n'a pas pu les lister. */
function useEntities(domain: "light" | "switch" | null) {
  const [state, setState] = useState<{ list: Entity[]; failed: boolean; loading: boolean }>({
    list: [],
    failed: false,
    loading: domain !== null,
  });
  useEffect(() => {
    if (!domain) return;
    let cancelled = false;
    api
      .GET("/api/ha/entities", { params: { query: { domain } } })
      .then(({ data }) => {
        if (!cancelled) setState({ list: (data ?? []) as Entity[], failed: !data, loading: false });
      })
      .catch(() => !cancelled && setState({ list: [], failed: true, loading: false }));
    return () => {
      cancelled = true;
    };
  }, [domain]);
  return state;
}

/** Détail d'un refus : « relais utilisé : A ; B » donne les lignes A et B. */
function usageLines(message: string): string[] {
  const after = message.includes(" : ") ? message.slice(message.indexOf(" : ") + 3) : message;
  return after.split(" ; ").filter(Boolean);
}

type Pending = { action: "save" | "delete"; text: string } | null;

export function ComponentForm({
  kind,
  existing,
  onClose,
}: {
  kind: Kind;
  existing?: Existing;
  onClose: () => void;
}) {
  const { devices, reload } = useCatalog();
  const toasts = useToasts();
  const locked = useEngine().status?.lock.locked ?? false;
  const [draft, setDraft] = useState<Draft>(() => draftOf(existing));
  const [errors, setErrors] = useState<FormErrors>({ fields: {} });
  const [busy, setBusy] = useState(false);
  const [pending, setPending] = useState<Pending>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [blockedBy, setBlockedBy] = useState<string[] | null>(null);

  const domain = kind === "lights" ? "light" : kind === "switches" ? "switch" : null;
  const entities = useEntities(domain);
  const pins = devices ? usedPins(devices, existing?.id) : new Map<number, string>();
  const set = <K extends keyof Draft>(key: K, value: Draft[K]) => setDraft((d) => ({ ...d, [key]: value }));
  const field = (name: string) => errors.fields[name];

  async function save(stopRuns = false) {
    setBusy(true);
    setErrors({ fields: {} });
    setPending(null);
    try {
      const saved = await saveComponent(kind, existing?.id ?? null, bodyOf(kind, draft), stopRuns);
      await reload();
      const warnings = saved.issues.map((i) => i.message);
      toasts.info(warnings.length ? `Enregistré. À vérifier : ${warnings.join(" ; ")}` : "Enregistré.");
      onClose();
    } catch (error) {
      if (error instanceof ApiError && error.status === 409 && JSON.stringify(error.body).includes("stop_runs")) {
        setPending({ action: "save", text: formErrors(error).general?.title ?? "Des scénarios tournent." });
      } else {
        setErrors(formErrors(error));
      }
    } finally {
      setBusy(false);
    }
  }

  async function remove(stopRuns = false) {
    if (!existing) return;
    setBusy(true);
    setErrors({ fields: {} });
    setPending(null);
    try {
      await deleteComponent(kind, existing.id, stopRuns);
      await reload();
      toasts.info("Supprimé.");
      onClose();
    } catch (error) {
      const title = formErrors(error).general?.title ?? "";
      if (error instanceof ApiError && error.status === 409 && JSON.stringify(error.body).includes("stop_runs")) {
        setPending({ action: "delete", text: title });
      } else if (error instanceof ApiError && error.status === 409) {
        setBlockedBy(usageLines(title)); // composant utilisé : on dit où, la suppression reste bloquée
      } else {
        setErrors(formErrors(error));
      }
    } finally {
      setBusy(false);
      setConfirmDelete(false);
    }
  }

  function pickEntity(entityId: string) {
    const known = entities.list.find((e) => e.entity_id === entityId);
    setDraft((d) => ({
      ...d,
      entity_id: entityId,
      ...(kind === "lights" && known?.capabilities
        ? {
            supports_color: known.capabilities.color,
            supports_brightness: known.capabilities.brightness,
            supports_transition: known.capabilities.transition,
          }
        : {}),
    }));
  }

  const entityChoices = entities.list.some((e) => e.entity_id === draft.entity_id) || !draft.entity_id
    ? entities.list
    : [{ entity_id: draft.entity_id, name: draft.entity_id } as Entity, ...entities.list];

  return (
    <Modal title={existing ? `Modifier ${TITLE[kind]}` : `Ajouter ${KIND_LABEL[kind].toLowerCase()}`} onClose={onClose}>
      <form
        className="form"
        onSubmit={(e) => {
          e.preventDefault();
          void save();
        }}
      >
        {locked && <p className="muted">Interface verrouillée : lecture seule.</p>}
        {existing && (
          <Field label="Identifiant technique" value={existing.id} readOnly hint="Utilisé dans les scénarios ; ne change pas." />
        )}
        <Field
          label="Nom"
          value={draft.name}
          maxLength={60}
          required
          error={field("name")}
          onChange={(e) => set("name", e.target.value)}
        />
        <ImagePicker kind={kind} value={draft.image} onChange={(image) => set("image", image)} />

        {(kind === "relays" || kind === "buttons") && (
          <SelectField
            label="Broche (GPIO, numérotation BCM)"
            value={draft.pin}
            required
            error={field("pin")}
            onChange={(e) => set("pin", e.target.value)}
          >
            <option value="">Choisir une broche</option>
            {GPIO_PINS.map((pin) => {
              const owner = pins.get(pin);
              return (
                <option key={pin} value={pin} disabled={owner !== undefined}>
                  {owner ? `GPIO ${pin} — utilisée par ${owner}` : `GPIO ${pin}`}
                </option>
              );
            })}
          </SelectField>
        )}

        {kind === "relays" && (
          <>
            <SelectField
              label="Mode"
              value={draft.mode}
              error={field("mode")}
              hint={
                draft.mode === "latched"
                  ? "Maintenu : le relais reste fermé jusqu'à l'extinction (lumière, ventilateur…)."
                  : "Impulsion : un bref contact déclenche un objet qui joue sa propre animation."
              }
              onChange={(e) => set("mode", e.target.value as Draft["mode"])}
            >
              <option value="latched">Maintenu</option>
              <option value="push">Impulsion</option>
            </SelectField>
            <CheckField
              label="Module actif à l'état bas"
              hint="À cocher si le module de relais s'enclenche quand la broche est à 0 V."
              checked={draft.active_low}
              onChange={(e) => set("active_low", e.target.checked)}
            />
            {draft.mode === "latched" ? (
              <Field
                label="Durée maximale d'allumage (s)"
                type="number"
                min="0"
                step="any"
                value={draft.max_on_seconds}
                error={field("max_on_seconds")}
                hint="Vide : aucune limite."
                onChange={(e) => set("max_on_seconds", e.target.value)}
              />
            ) : (
              <>
                <Field
                  label="Durée de l'impulsion (ms)"
                  type="number"
                  min="1"
                  max="10000"
                  value={draft.pulse_ms}
                  error={field("pulse_ms")}
                  hint="Vide : 500 ms."
                  onChange={(e) => set("pulse_ms", e.target.value)}
                />
                <Field
                  label="Durée de l'animation (s)"
                  type="number"
                  min="0"
                  step="any"
                  value={draft.animation_s}
                  error={field("animation_s")}
                  hint="Temps pendant lequel l'objet joue son animation après l'impulsion."
                  onChange={(e) => set("animation_s", e.target.value)}
                />
              </>
            )}
          </>
        )}

        {kind === "buttons" && (
          <>
            <SelectField
              label="Type"
              value={draft.kind}
              disabled={Boolean(existing)}
              hint={existing ? "Le type ne change pas : créez un autre composant." : undefined}
              onChange={(e) => {
                const next = e.target.value as Draft["kind"];
                // Sortie de PIR : niveau haut sur un mouvement, donc résistance vers le bas.
                setDraft((d) => ({ ...d, kind: next, pull: next === "motion" ? "down" : "up" }));
              }}
            >
              <option value="button">Bouton</option>
              <option value="motion">Détecteur de mouvement (PIR)</option>
            </SelectField>
            <SelectField label="Résistance (pull)" value={draft.pull} error={field("pull")} onChange={(e) => set("pull", e.target.value as Draft["pull"])}>
              <option value="up">Pull-up (bouton vers la masse)</option>
              <option value="down">Pull-down (bouton vers le 3,3 V, sortie de détecteur)</option>
            </SelectField>
            <Field label="Anti-rebond (ms)" type="number" min="0" max="1000" value={draft.debounce_ms} error={field("debounce_ms")} onChange={(e) => set("debounce_ms", e.target.value)} />
            {draft.kind === "motion" ? (
              <Field
                label="Chauffe du capteur (s)"
                type="number"
                min="0"
                max="600"
                value={draft.warmup_s}
                error={field("warmup_s")}
                hint="Détections ignorées après le démarrage du moteur, le temps que le PIR se stabilise (0 : aucune)."
                onChange={(e) => set("warmup_s", e.target.value)}
              />
            ) : (
              <>
                <Field label="Seuil d'appui long (ms)" type="number" min="100" max="10000" value={draft.long_press_ms} error={field("long_press_ms")} onChange={(e) => set("long_press_ms", e.target.value)} />
                <Field label="Délai du double appui (ms)" type="number" min="100" max="2000" value={draft.double_press_ms} error={field("double_press_ms")} onChange={(e) => set("double_press_ms", e.target.value)} />
              </>
            )}
          </>
        )}

        {domain && (
          <>
            {entities.failed || (!entities.loading && entities.list.length === 0) ? (
              <Field
                label="Entité Home Assistant"
                value={draft.entity_id}
                required
                placeholder={`${domain}.nom_de_l_entite`}
                error={field("entity_id")}
                hint="La liste n'a pas pu être lue (Home Assistant injoignable ou sans entité de ce type) : saisissez l'identifiant."
                onChange={(e) => pickEntity(e.target.value)}
              />
            ) : (
              <SelectField
                label="Entité Home Assistant"
                value={draft.entity_id}
                required
                disabled={entities.loading}
                error={field("entity_id")}
                onChange={(e) => pickEntity(e.target.value)}
              >
                <option value="">{entities.loading ? "Chargement…" : "Choisir une entité"}</option>
                {entityChoices.map((e) => (
                  <option key={e.entity_id} value={e.entity_id}>
                    {e.name === e.entity_id ? e.entity_id : `${e.name} (${e.entity_id})`}
                  </option>
                ))}
              </SelectField>
            )}
          </>
        )}

        {kind === "lights" && (
          <fieldset className="field-group">
            <legend className="field__label">Capacités de la lumière</legend>
            <CheckField label="Couleur" checked={draft.supports_color} onChange={(e) => set("supports_color", e.target.checked)} />
            <CheckField label="Luminosité" checked={draft.supports_brightness} onChange={(e) => set("supports_brightness", e.target.checked)} />
            <CheckField label="Transition" checked={draft.supports_transition} onChange={(e) => set("supports_transition", e.target.checked)} />
          </fieldset>
        )}

        {existing ? (
          <TestPanel kind={kind} item={existing} />
        ) : (
          <p className="muted">Enregistrez le composant pour pouvoir le tester.</p>
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
        {blockedBy && (
          <div className="form-error" role="alert">
            <strong>Suppression impossible : ce composant est encore utilisé.</strong>
            <ul>
              {blockedBy.map((line) => (
                <li key={line}>{line}</li>
              ))}
            </ul>
            <span>Retirez-le de ces endroits d'abord.</span>
          </div>
        )}
        {pending && (
          <div className="form-error" role="alert">
            <strong>{pending.text}</strong>
            <Button
              variant="danger"
              onClick={() => void (pending.action === "save" ? save(true) : remove(true))}
            >
              Arrêter les scénarios et continuer
            </Button>
          </div>
        )}

        <div className="form-actions">
          {existing &&
            (confirmDelete ? (
              <>
                <Button variant="danger" disabled={busy || locked} onClick={() => void remove()}>
                  Confirmer la suppression
                </Button>
                <Button variant="ghost" onClick={() => setConfirmDelete(false)}>
                  Garder
                </Button>
              </>
            ) : (
              <Button variant="outline-danger" disabled={busy || locked} onClick={() => setConfirmDelete(true)}>
                Supprimer
              </Button>
            ))}
          <span className="form-actions__spacer" />
          <Button variant="ghost" onClick={onClose}>
            Annuler
          </Button>
          <Button variant="primary" type="submit" disabled={busy || locked}>
            Enregistrer
          </Button>
        </div>
      </form>
    </Modal>
  );
}
