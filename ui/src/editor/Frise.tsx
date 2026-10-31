import { useMemo } from "react";
import type { Devices } from "../catalog/CatalogProvider";
import { ComponentImage, type Kind } from "../catalog/icons";
import { Pill } from "../components/ui";
import { buildRows, formatSeconds, statusMessage, ticks, type Period, type SimulationOut } from "./timeline";

interface Known {
  name: string;
  kind: Kind;
  image?: string | null;
  imageUrl?: string | null;
}

function lookup(devices: Devices | null, id: string): Known {
  const sources: [Kind, { id: string; name: string; image?: string | null; image_url?: string | null }[] | undefined][] = [
    ["relays", devices?.relays],
    ["lights", devices?.lights],
    ["switches", devices?.switches],
    ["players", devices?.players],
  ];
  for (const [kind, items] of sources) {
    const hit = items?.find((i) => i.id === id);
    if (hit) return { name: hit.name, kind, image: hit.image, imageUrl: hit.image_url };
  }
  return { name: id, kind: "relays" };
}

function barColour(known: Known, period: Period): string {
  const rgb = period.data.rgb_color as number[] | undefined;
  if (known.kind === "lights" && rgb) return `rgb(${rgb[0]}, ${rgb[1]}, ${rgb[2]})`;
  if (known.kind === "players") return "#5fb48a";
  return known.kind === "lights" ? "#f2b84b" : known.kind === "switches" ? "#5aa9c6" : "#d9726f";
}

function label(name: string, period: Period, kind: Kind): string {
  const span = period.open
    ? `de ${formatSeconds(period.start)} jusqu'à la fin (jamais éteint)`
    : `de ${formatSeconds(period.start)} à ${formatSeconds(period.end)}`;
  return kind === "players" ? `${name} : en lecture ${span}` : `${name} : allumé ${span}`;
}

/** Frise : une ligne par composant, une barre par période d'activation, axe en secondes. */
export function Frise({ result, devices }: { result: SimulationOut; devices: Devices | null }) {
  const rows = useMemo(() => buildRows(result), [result]);
  const duration = Math.max(result.duration_s, 0.001);
  const status = statusMessage(result);
  const pct = (t: number) => `${(Math.min(t, duration) / duration) * 100}%`;
  return (
    <section className="frise" aria-label="Frise temporelle">
      <p role="status" className={`frise__status frise__status--${status.tone}`}>
        <Pill tone={status.tone === "ok" ? "ok" : status.tone === "warn" ? "warn" : "error"}>{status.text}</Pill>
      </p>
      {rows.length === 0 ? (
        <p className="muted">Aucune commande n'est envoyée pendant la simulation.</p>
      ) : (
        <>
          <ul className="frise__rows">
            {rows.map((row) => {
              const known = lookup(devices, row.component);
              return (
                <li key={row.component} className="frise__row" aria-label={known.name}>
                  <span className="frise__label">
                    <ComponentImage kind={known.kind} image={known.image} imageUrl={known.imageUrl} size={20} />
                    {known.name}
                  </span>
                  <span className="frise__track">
                    {row.periods.map((period, i) => (
                      <span
                        key={i}
                        role="img"
                        aria-label={label(known.name, period, known.kind)}
                        title={label(known.name, period, known.kind)}
                        className={period.open ? "frise__bar frise__bar--open" : "frise__bar"}
                        style={{ left: pct(period.start), width: `max(${((period.end - period.start) / duration) * 100}%, 3px)`, background: barColour(known, period) }}
                      />
                    ))}
                  </span>
                </li>
              );
            })}
          </ul>
          <div className="frise__axis" aria-hidden="true">
            <span className="frise__label" />
            <span className="frise__track">
              {ticks(duration).map((t) => (
                <span key={t} className="frise__tick" style={{ left: pct(t) }}>
                  {formatSeconds(t)}
                </span>
              ))}
            </span>
          </div>
        </>
      )}
    </section>
  );
}
