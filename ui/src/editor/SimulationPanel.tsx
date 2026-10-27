import { X } from "lucide-react";
import { useState } from "react";
import type { Devices } from "../catalog/CatalogProvider";
import { Button, Field, SelectField } from "../components/ui";
import { Frise } from "./Frise";
import type { SimulationOut } from "./timeline";

export interface Press {
  t: number;
  button: string;
  event: "short" | "long" | "double";
}

const EVENT_LABEL = { short: "court", long: "long", double: "double" } as const;

/** Frise du dernier résultat + appuis de boutons à rejouer (un « attendre un bouton » sans appui reste bloqué). */
export function SimulationPanel({
  result,
  devices,
  presses,
  onPresses,
  onClose,
}: {
  result: SimulationOut;
  devices: Devices | null;
  presses: Press[];
  onPresses: (next: Press[]) => void;
  onClose: () => void;
}) {
  const buttons = devices?.buttons ?? [];
  const [button, setButton] = useState(buttons[0]?.id ?? "");
  const [event, setEvent] = useState<Press["event"]>("short");
  const [t, setT] = useState("5");

  return (
    <section className="simulation" aria-label="Simulation">
      <div className="simulation__head">
        <h2>Simulation</h2>
        <Button variant="ghost" onClick={onClose} aria-label="Fermer la simulation">
          <X size={18} aria-hidden="true" />
        </Button>
      </div>
      <Frise result={result} devices={devices} />
      {buttons.length > 0 && (
        <div className="simulation__presses">
          <h3>Appuis de boutons simulés</h3>
          {presses.length > 0 && (
            <ul className="press-list">
              {presses.map((press, i) => (
                <li key={i}>
                  <span className="pill">
                    {buttons.find((b) => b.id === press.button)?.name ?? press.button} : appui {EVENT_LABEL[press.event]} à {press.t} s
                    <button type="button" className="pill__close" aria-label="Retirer cet appui" onClick={() => onPresses(presses.filter((_, j) => j !== i))}>
                      ×
                    </button>
                  </span>
                </li>
              ))}
            </ul>
          )}
          <form
            className="simulation__form"
            onSubmit={(e) => {
              e.preventDefault();
              const at = Number(t);
              if (button && Number.isFinite(at) && at >= 0) onPresses([...presses, { t: at, button, event }]);
            }}
          >
            <SelectField label="Bouton" value={button} onChange={(e) => setButton(e.target.value)}>
              {buttons.map((b) => (
                <option key={b.id} value={b.id}>
                  {b.name}
                </option>
              ))}
            </SelectField>
            <SelectField label="Appui" value={event} onChange={(e) => setEvent(e.target.value as Press["event"])}>
              <option value="short">court</option>
              <option value="long">long</option>
              <option value="double">double</option>
            </SelectField>
            <Field label="À (s)" type="number" min="0" step="any" value={t} onChange={(e) => setT(e.target.value)} />
            <Button type="submit">Ajouter l'appui</Button>
          </form>
          <span className="field__hint">Relancez « Simuler » pour tenir compte des appuis.</span>
        </div>
      )}
    </section>
  );
}
