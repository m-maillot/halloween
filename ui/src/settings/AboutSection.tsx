import { ICON_SOURCES, SOFTWARE, iconCounts } from "../about/credits";
import { BUILTIN_ICONS } from "../catalog/icons";
import { useEngine } from "../engine/EngineProvider";

/** Version et attributions : les licences de ce qui est embarqué exigent d'en nommer les auteurs. */
export function AboutSection() {
  const { status } = useEngine();
  const counts = iconCounts();
  return (
    <section className="settings-section" aria-labelledby="set-about">
      <h2 id="set-about">À propos</h2>
      <p>
        Déco Halloween · moteur {status?.version ? `version ${status.version}` : "(version inconnue)"}. Interface sans service externe : polices
        et icônes sont embarquées.
      </p>

      <h3>Icônes ({Object.keys(BUILTIN_ICONS).length})</h3>
      <ul className="credits" aria-label="Origine des icônes">
        {(Object.keys(ICON_SOURCES) as (keyof typeof ICON_SOURCES)[]).map((key) => {
          const credit = ICON_SOURCES[key];
          return (
            <li key={key}>
              <strong>{credit.name}</strong> — {counts[key]} icône{counts[key] > 1 ? "s" : ""}, licence {credit.license}, {credit.author}
              {credit.note ? ` (${credit.note})` : ""}.
            </li>
          );
        })}
      </ul>

      <h3>Logiciels</h3>
      <ul className="credits" aria-label="Logiciels embarqués">
        {SOFTWARE.map((credit) => (
          <li key={credit.name}>
            <strong>{credit.name}</strong> — licence {credit.license}, {credit.author}
            {credit.note ? ` (${credit.note})` : ""}.
          </li>
        ))}
      </ul>
    </section>
  );
}
