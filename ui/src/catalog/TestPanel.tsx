import { useEffect, useState } from "react";
import { api } from "../api/client";
import { unwrap } from "../api/errors";
import { Button, CheckField, Field, SelectField } from "../components/ui";
import { useToasts } from "../components/Toasts";
import { useEngine } from "../engine/EngineProvider";
import { PRESS_TEXT } from "../triggers/model";
import type { Existing } from "./draft";
import type { Kind } from "./icons";


function rgbOf(hex: string): [number, number, number] {
  const n = parseInt(hex.slice(1), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

/** Test manuel du composant enregistré (le formulaire non enregistré n'est pas pris en compte). */
export function TestPanel({ kind, item }: { kind: Kind; item: Existing }) {
  const toasts = useToasts();
  const { subscribe, status } = useEngine();
  const locked = status?.lock.locked ?? false; // le moteur refuse les tests manuels quand il est verrouillé
  const [result, setResult] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [listening, setListening] = useState(false);
  const [color, setColor] = useState("#ff8a2b");
  const [brightness, setBrightness] = useState("255");
  const [transition, setTransition] = useState("");
  const player = kind === "players" ? (item as { videos: { id: string; name: string }[]; rest_video?: string | null }) : null;
  const [video, setVideo] = useState(player?.videos[0]?.id ?? "");
  const [loop, setLoop] = useState(false);

  // Bouton physique : on écoute le prochain appui (vérification du câblage).
  useEffect(() => {
    if (!listening) return;
    return subscribe((event) => {
      if (event.type === "button_event" && event.button_id === item.id) {
        const text = PRESS_TEXT[event.event] ?? event.event;
        setResult(`${text.charAt(0).toUpperCase()}${text.slice(1)} reçu.`);
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
  const motion = kind === "buttons" && (item as { kind?: string }).kind === "motion";
  const relay = kind === "relays" ? (item as { mode: string }) : null;

  return (
    <section className="test-panel" aria-label="Test manuel">
      <h3>Tester</h3>
      <span className="field__hint">Teste la version enregistrée du composant.</span>
      {player ? (
        <>
          <SelectField label="Vidéo" value={video} onChange={(e) => setVideo(e.target.value)}>
            {player.videos.map((v) => (
              <option key={v.id} value={v.id}>
                {v.name}
              </option>
            ))}
          </SelectField>
          <CheckField label="En boucle" checked={loop} onChange={(e) => setLoop(e.target.checked)} />
          <div className="form-actions">
            <Button disabled={busy || locked || !video} onClick={() => void run({ action: "play", video, loop })}>
              Jouer
            </Button>
            {player.rest_video && (
              <Button disabled={busy || locked} onClick={() => void run({ action: "rest" })}>
                Écran noir
              </Button>
            )}
          </div>
        </>
      ) : kind === "buttons" ? (
        <>
          <Button onClick={() => { setResult(null); setListening(true); }} disabled={listening}>
            {listening ? (motion ? "Passez devant le capteur…" : "Appuyez sur le bouton…") : motion ? "Écouter un mouvement" : "Écouter un appui"}
          </Button>
          <span className="field__hint">
            {motion ? "Passez devant le capteur : la détection s'affiche ici (hors période de chauffe)." : "Appuyez sur le bouton physique : l'événement reçu s'affiche ici."}
          </span>
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
              <Button disabled={busy || locked} onClick={() => void run({ action: "trigger" })}>
                Déclencher
              </Button>
            ) : (
              <>
                <Button
                  disabled={busy || locked}
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
                <Button disabled={busy || locked} onClick={() => void run({ action: "off" })}>
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
