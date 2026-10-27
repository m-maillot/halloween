import { WifiOff } from "lucide-react";
import { Button, Card } from "../components/ui";
import { useEngine } from "../engine/EngineProvider";

/** Remplace l'écran courant quand le moteur ne répond pas : rien d'autre n'est actionnable. */
export function OfflineScreen() {
  const { retry, connection } = useEngine();
  const trying = connection === "connecting";
  return (
    <div className="offline">
      <Card>
        <div style={{ display: "grid", gap: 14, justifyItems: "start" }}>
          <WifiOff size={32} aria-hidden="true" color="var(--color-accent)" />
          <h1 style={{ fontSize: 24 }}>Moteur injoignable</h1>
          <p>
            L'interface ne peut pas joindre le moteur du Raspberry Pi. Les relais et les déclencheurs continuent
            de fonctionner s'il est allumé ; l'interface reprendra toute seule dès que la connexion revient.
          </p>
          <Button variant="primary" onClick={retry} disabled={trying}>
            {trying ? "Connexion…" : "Réessayer"}
          </Button>
        </div>
      </Card>
    </div>
  );
}
