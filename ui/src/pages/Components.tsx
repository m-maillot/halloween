import { Plus } from "lucide-react";
import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useCatalog, type Devices } from "../catalog/CatalogProvider";
import { ComponentForm } from "../catalog/ComponentForm";
import type { Existing } from "../catalog/draft";
import { ComponentImage, KIND_LABEL, type Kind } from "../catalog/icons";
import { Button, Card, Pill } from "../components/ui";
import { useEngine } from "../engine/EngineProvider";

type Relay = Devices["relays"][number];
type Button_ = Devices["buttons"][number];
type Light = Devices["lights"][number];
type Switch_ = Devices["switches"][number];
type Item = Relay | Button_ | Light | Switch_;

const KINDS: Kind[] = ["relays", "buttons", "lights", "switches"];

const SINGULAR: Record<Kind, string> = {
  relays: "un relais",
  buttons: "un bouton ou un détecteur",
  lights: "une lumière",
  switches: "un interrupteur",
};

const EMPTY: Record<Kind, string> = {
  relays: "Aucun relais. Ajoutez le premier pour piloter une décoration branchée sur le Pi.",
  buttons: "Aucun bouton ni détecteur de mouvement.",
  lights: "Aucune lumière Home Assistant.",
  switches: "Aucun interrupteur Home Assistant.",
};

export function summary(kind: Kind, item: Item): string[] {
  switch (kind) {
    case "relays": {
      const relay = item as Relay;
      const mode = relay.mode === "push" ? "impulsion" : "maintenu";
      return [`GPIO ${relay.pin}`, mode];
    }
    case "buttons": {
      const button = item as Button_;
      return [`GPIO ${button.pin}`, button.kind === "motion" ? "détecteur de mouvement" : button.pull === "down" ? "pull-down" : "pull-up"];
    }
    case "lights": {
      const light = item as Light;
      const features = [
        light.supports_color && "couleur",
        light.supports_brightness && "luminosité",
        light.supports_transition && "transition",
      ].filter((f): f is string => Boolean(f));
      return [light.entity_id, features.length ? features.join(", ") : "marche / arrêt"];
    }
    case "switches":
      return [(item as Switch_).entity_id];
  }
}

function isKind(value: string | null): value is Kind {
  return KINDS.includes(value as Kind);
}

export function Components() {
  const { devices } = useCatalog();
  const { status } = useEngine();
  const locked = status?.lock.locked ?? false;
  const [params, setParams] = useSearchParams();
  const requested = params.get("type");
  const kind: Kind = isKind(requested) ? requested : "relays";
  // `null` : fermé ; `"new"` : création ; sinon le composant en modification.
  const [editing, setEditing] = useState<Existing | "new" | null>(null);

  return (
    <>
      <div className="page-head">
        <h1>Composants</h1>
        <Button variant="primary" disabled={!devices || locked} onClick={() => setEditing("new")}>
          <Plus size={18} aria-hidden="true" /> Ajouter {SINGULAR[kind]}
        </Button>
      </div>

      <div className="tabs" role="tablist" aria-label="Type de composant">
        {KINDS.map((k) => (
          <button
            key={k}
            type="button"
            role="tab"
            id={`tab-${k}`}
            aria-selected={k === kind}
            aria-controls="components-panel"
            className={k === kind ? "tab tab--active" : "tab"}
            onClick={() => {
              setEditing(null);
              setParams({ type: k }, { replace: true });
            }}
          >
            {KIND_LABEL[k]}
            {devices && <span className="tab__count">{devices[k].length}</span>}
          </button>
        ))}
      </div>

      <div id="components-panel" role="tabpanel" aria-labelledby={`tab-${kind}`}>
        {!devices ? (
          <p className="muted">Chargement…</p>
        ) : devices[kind].length === 0 ? (
          <p className="muted">{EMPTY[kind]}</p>
        ) : (
          <ul className="grid">
            {(devices[kind] as Item[]).map((item) => (
              <li key={item.id}>
                <Card label={item.name} onClick={() => setEditing(item)}>
                  <div className="component-card">
                    <ComponentImage kind={kind} image={item.image} imageUrl={item.image_url} size={44} />
                    <div className="component-card__text">
                      <strong>{item.name}</strong>
                      <span className="muted">{summary(kind, item)[0]}</span>
                      {summary(kind, item)
                        .slice(1)
                        .map((extra) => (
                          <Pill key={extra}>{extra}</Pill>
                        ))}
                    </div>
                  </div>
                </Card>
              </li>
            ))}
          </ul>
        )}
      </div>

      {editing && (
        <ComponentForm
          key={editing === "new" ? "new" : editing.id}
          kind={kind}
          existing={editing === "new" ? undefined : editing}
          onClose={() => setEditing(null)}
        />
      )}
    </>
  );
}
