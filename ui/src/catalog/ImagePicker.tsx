import { useState } from "react";
import { useToasts } from "../components/Toasts";
import { Button, Field } from "../components/ui";
import { BUILTIN_ICONS, ComponentImage, type Kind } from "./icons";
import { uploadImage } from "./write";

const ACCEPTED = ["image/png", "image/jpeg", "image/webp"];
type Source = "library" | "upload";

function normalize(text: string): string {
  return text.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
}

/** Deux sources : icônes intégrées (`builtin:<nom>`) ou image personnelle téléversée. */
export function ImagePicker({
  kind,
  value,
  onChange,
}: {
  kind: Kind;
  value: string | null;
  onChange: (image: string | null) => void;
}) {
  const toasts = useToasts();
  const [source, setSource] = useState<Source>(value && !value.startsWith("builtin:") ? "upload" : "library");
  const [query, setQuery] = useState("");
  const [busy, setBusy] = useState(false);

  const uploaded = value && !value.startsWith("builtin:") ? value : null;
  const needle = normalize(query);
  const icons = Object.entries(BUILTIN_ICONS).filter(
    ([name, { label }]) => !needle || normalize(`${name} ${label}`).includes(needle),
  );

  async function pick(file: File | undefined) {
    if (!file) return;
    if (!ACCEPTED.includes(file.type)) {
      toasts.error(new Error("Format non pris en charge : png, jpg ou webp."));
      return;
    }
    setBusy(true);
    try {
      onChange((await uploadImage(file)).image);
    } catch (error) {
      toasts.error(error);
    } finally {
      setBusy(false);
    }
  }

  return (
    <fieldset className="image-picker">
      <legend className="field__label">Image</legend>
      <div className="image-picker__current">
        <ComponentImage
          kind={kind}
          image={value}
          imageUrl={uploaded ? `/api/images/${uploaded}` : null}
          size={48}
        />
        {value && (
          <Button variant="ghost" onClick={() => onChange(null)}>
            Retirer l'image
          </Button>
        )}
      </div>
      <div className="tabs" role="tablist" aria-label="Source de l'image">
        {(["library", "upload"] as const).map((s) => (
          <button
            key={s}
            type="button"
            role="tab"
            aria-selected={source === s}
            className={source === s ? "tab tab--active" : "tab"}
            onClick={() => setSource(s)}
          >
            {s === "library" ? "Bibliothèque" : "Image personnelle"}
          </button>
        ))}
      </div>
      {source === "library" ? (
        <>
          <Field label="Rechercher une icône" value={query} onChange={(e) => setQuery(e.target.value)} />
          <ul className="icon-grid">
            {icons.map(([name, { label, icon: Icon }]) => (
              <li key={name}>
                <button
                  type="button"
                  className="icon-choice"
                  aria-pressed={value === `builtin:${name}`}
                  aria-label={label}
                  title={label}
                  onClick={() => onChange(`builtin:${name}`)}
                >
                  <Icon size={26} aria-hidden="true" />
                </button>
              </li>
            ))}
          </ul>
          {icons.length === 0 && <p className="muted">Aucune icône ne correspond.</p>}
        </>
      ) : (
        <div className="field">
          <label className="field__label" htmlFor="image-file">
            Téléverser une image
          </label>
          <input
            id="image-file"
            type="file"
            accept={ACCEPTED.join(",")}
            disabled={busy}
            onChange={(e) => void pick(e.target.files?.[0])}
          />
          <span className="field__hint">
            png, jpg ou webp, 5 Mo au plus. L'image est recadrée au carré (centre) puis réduite par le moteur.
          </span>
          {busy && <span role="status">Téléversement…</span>}
        </div>
      )}
    </fieldset>
  );
}
