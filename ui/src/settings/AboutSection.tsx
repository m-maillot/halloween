import { ICON_SOURCES, SOFTWARE, gameIconAuthors, iconCounts } from "../about/credits";
import { BUILTIN_ICONS } from "../catalog/icons";
import { useEngine } from "../engine/EngineProvider";

/** Version et attributions : les licences de ce qui est embarqué exigent d'en nommer les auteurs. */
export function AboutSection() {
  const { status } = useEngine();
  const counts = iconCounts();
  const authors = gameIconAuthors();
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

      <h4>Icônes made by… (game-icons.net, CC BY 3.0)</h4>
      <ul className="credits" aria-label="Auteurs des icônes game-icons.net">
        {authors.map((a) => (
          <li key={a.key}>
            Icons made by{" "}
            {a.url ? (
              <a href={a.url} target="_blank" rel="noreferrer">
                {a.name}
              </a>
            ) : (
              <strong>{a.name}</strong>
            )}{" "}
            — {a.icons.join(", ")}.
          </li>
        ))}
      </ul>
      <p>
        Licence :{" "}
        <a href="https://creativecommons.org/licenses/by/3.0/" target="_blank" rel="noreferrer">
          Creative Commons BY 3.0
        </a>
        , liste détaillée : <a href="/GAME-ICONS-LICENSE.txt" target="_blank" rel="noreferrer">GAME-ICONS-LICENSE.txt</a>.
      </p>

      <p>
        Textes complets des licences : <a href="/LICENSES.txt" target="_blank" rel="noreferrer">LICENSES.txt</a> (livré avec l'interface).
      </p>

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
