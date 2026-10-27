import { useEffect, useState } from "react";
import { api } from "../api/client";
import { unwrap } from "../api/errors";
import { Button, Field } from "../components/ui";
import { useToasts } from "../components/Toasts";
import { useEngine } from "../engine/EngineProvider";
import type { Existing } from "./draft";
import type { Kind } from "./icons";

const PRESS: Record<string, string> = { short: "court", long: "long", double: "double" };

function rgbOf(hex: string): [number, number, number] {
  const n = parseInt(hex.slice(1), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

/** Test manuel du composant enregistré (le formulaire non enregistré n'est pas pris en compte). */
export function TestPanel({ kind, item }: { kind: Kind; item: Existing }) {
  const toasts = useToasts();
  const { subscribe } = useEngine();
  const [result, setResult] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [listening, setListening] = useState(false);
  const [color, setColor] = useState("#ff8a2b");
  const [brightness, setBrightness] = useState("255");
  const [transition, setTransition] = useState("");

  // Bouton physique : on écoute le prochain appui (vérification du câblage).
  useEffect(() => {
    if (!listening) return;
    return subscribe((event) => {
      if (event.type === "button_event" && event.button_id === item.id) {
        setResult(`Appui ${PRESS[event.event] ?? event.event} reçu.`);
        setListening(false);
      }
    });
  }, [listening, subscribe, item.id]);

  async function run(body: object) {
    setBusy(true);
    try {
      const { message } = await unwrap<{ message: string }>(
        api.POST("/api/components/{kind}/{component_id}/test", {
          params: { path: { kind, component_id: item.id } },
          body: body as never,
        }),
      );
      setResult(message);
    } catch (error) {
      setResult(null);
      toasts.error(error);
    } finally {
      setBusy(false);
    }
  }

  const light = kind === "lights" ? (item as { supports_color: boolean; supports_brightness: boolean; supports_transition: boolean }) : null;
  const relay = kind === "relays" ? (item as { mode: string }) : null;

  return (
    <section className="test-panel" aria-label="Test manuel">
      <h3>Tester</h3>
      <span className="field__hint">Teste la version enregistrée du composant.</span>
      {kind === "buttons" ? (
        <>
          <Button onClick={() => { setResult(null); setListening(true); }} disabled={listening}>
            {listening ? "Appuyez sur le bouton…" : "Écouter un appui"}
          </Button>
          <span className="field__hint">Appuyez sur le bouton physique : l'événement reçu s'affiche ici.</span>
        </>
      ) : (
        <>
          {light?.supports_color && (
            <label className="field__label">
              Couleur <input type="color" value={color} onChange={(e) => setColor(e.target.value)} />
            </label>
          )}
          {light?.supports_brightness && (
            <Field label="Luminosité (0-255)" type="number" min="0" max="255" value={brightness} onChange={(e) => setBrightness(e.target.value)} />
          )}
          {light?.supports_transition && (
            <Field label="Transition (s)" type="number" min="0" step="any" value={transition} onChange={(e) => setTransition(e.target.value)} />
          )}
          <div className="form-actions">
            {relay?.mode === "push" ? (
              <Button disabled={busy} onClick={() => void run({ action: "trigger" })}>
                Déclencher
              </Button>
            ) : (
              <>
                <Button
                  disabled={busy}
                  onClick={() =>
                    void run({
                      action: "on",
                      ...(light?.supports_color && { rgb_color: rgbOf(color) }),
                      ...(light?.supports_brightness && brightness !== "" && { brightness: Number(brightness) }),
                      ...(light?.supports_transition && transition !== "" && { transition: Number(transition) }),
                    })
                  }
                >
                  Allumer
                </Button>
                <Button disabled={busy} onClick={() => void run({ action: "off" })}>
                  Éteindre
                </Button>
              </>
            )}
          </div>
        </>
      )}
      {result && <p role="status">{result}</p>}
    </section>
  );
}
