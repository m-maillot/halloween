import { useEffect, useState } from "react";
import { api } from "../api/client";
import { unwrap } from "../api/errors";
import { useCatalog } from "../catalog/CatalogProvider";
import { Button, CheckField, Field, SelectField } from "../components/ui";
import { useToasts } from "../components/Toasts";

interface Rest {
  state: "on" | "off";
  rgb_color?: number[] | null;
  brightness?: number | null;
  transition?: number | null;
}
type RestMap = Record<string, Rest>;

const hex = ([r, g, b]: number[]) => `#${[r, g, b].map((v) => v.toString(16).padStart(2, "0")).join("")}`;
const rgb = (value: string): [number, number, number] => {
  const n = parseInt(value.slice(1), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
};

/** État appliqué au démarrage, à l'arrêt manuel et en fin de scénario (relais : toujours éteints). */
export function RestStateSection({ disabled }: { disabled: boolean }) {
  const { devices } = useCatalog();
  const toasts = useToasts();
  const [rest, setRest] = useState<RestMap | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;
    unwrap<{ rest_state: RestMap }>(api.GET("/api/config/rest-state"))
      .then((loaded) => !cancelled && setRest(loaded.rest_state))
      .catch((error) => !cancelled && toasts.error(error));
    return () => {
      cancelled = true;
    };
  }, []);

  if (!devices || !rest) return <section className="settings-section"><h2>État de repos</h2><p className="muted">Chargement…</p></section>;

  const set = (id: string, value: Rest | null) =>
    setRest((all) => {
      const next = { ...all! };
      if (value) next[id] = value;
      else delete next[id];
      return next;
    });
  const patch = (id: string, change: Partial<Rest>) => set(id, { ...rest[id], ...change });

  async function save() {
    setBusy(true);
    try {
      const saved = await unwrap<{ issues: { message: string }[] }>(
        api.PUT("/api/config/rest-state", { body: { rest_state: rest as never } }),
      );
      const warnings = saved.issues.map((i) => i.message);
      toasts.info(warnings.length ? `Enregistré. À vérifier : ${warnings.join(" ; ")}` : "État de repos enregistré.");
    } catch (error) {
      toasts.error(error);
    } finally {
      setBusy(false);
    }
  }

  const items = [
    ...devices.lights.map((item) => ({ item, light: item })),
    ...devices.switches.map((item) => ({ item, light: null })),
  ];

  return (
    <section className="settings-section" aria-labelledby="set-rest">
      <h2 id="set-rest">État de repos</h2>
      <p className="muted">
        L'état appliqué à chaque composant au démarrage, à l'arrêt manuel et en fin de scénario.
        {devices.relays.length > 0 && ` Les relais maintenus (${devices.relays.map((r) => r.name).join(", ")}) sont toujours éteints.`}
      </p>
      {items.length === 0 ? (
        <p className="muted">Aucune lumière ni interrupteur Home Assistant.</p>
      ) : (
        <ul className="rest-list">
          {items.map(({ item, light }) => {
            const current = rest[item.id];
            return (
              <li key={item.id}>
                <fieldset className="rest-item" disabled={disabled}>
                  <legend>{item.name}</legend>
                  <SelectField
                    label="À l'état de repos"
                    value={current?.state ?? ""}
                    onChange={(e) => {
                      const value = e.target.value;
                      set(item.id, value ? { ...current, state: value as "on" | "off" } : null);
                    }}
                  >
                    <option value="">Ne pas y toucher</option>
                    <option value="on">Allumé</option>
                    <option value="off">Éteint</option>
                  </SelectField>
                  {light && current?.state === "on" && (
                    <>
                      {light.supports_color && (
                        <>
                          <CheckField
                            label="Imposer une couleur"
                            checked={Boolean(current.rgb_color)}
                            onChange={(e) => patch(item.id, { rgb_color: e.target.checked ? [255, 138, 43] : null })}
                          />
                          {current.rgb_color && (
                            <label className="field__label">
                              Couleur de {item.name}{" "}
                              <input type="color" value={hex(current.rgb_color)} onChange={(e) => patch(item.id, { rgb_color: rgb(e.target.value) })} />
                            </label>
                          )}
                        </>
                      )}
                      {light.supports_brightness && (
                        <Field
                          label={`Luminosité de ${item.name} (0-255)`}
                          type="number"
                          min="0"
                          max="255"
                          value={current.brightness ?? ""}
                          hint="Vide : inchangée."
                          onChange={(e) => patch(item.id, { brightness: e.target.value === "" ? null : Number(e.target.value) })}
                        />
                      )}
                      {light.supports_transition && (
                        <Field
                          label={`Transition de ${item.name} (s)`}
                          type="number"
                          min="0"
                          step="any"
                          value={current.transition ?? ""}
                          hint="Vide : immédiate."
                          onChange={(e) => patch(item.id, { transition: e.target.value === "" ? null : Number(e.target.value) })}
                        />
                      )}
                    </>
                  )}
                </fieldset>
              </li>
            );
          })}
        </ul>
      )}
      <div className="form-actions">
        <span className="form-actions__spacer" />
        <Button variant="primary" disabled={busy || disabled || items.length === 0} onClick={() => void save()}>
          Enregistrer l'état de repos
        </Button>
      </div>
    </section>
  );
}
