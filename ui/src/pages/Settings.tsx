import { useEngine } from "../engine/EngineProvider";
import { AboutSection } from "../settings/AboutSection";
import { EngineTokenSection } from "../settings/EngineTokenSection";
import { HomeAssistantSection } from "../settings/HomeAssistantSection";
import { LockCodeSection } from "../settings/LockCodeSection";
import { RestStateSection } from "../settings/RestStateSection";

export function Settings() {
  const { status } = useEngine();
  const locked = status?.lock.locked ?? false;
  return (
    <>
      <h1>Réglages</h1>
      {locked && (
        <p className="form-error" role="status">
          Interface verrouillée : les réglages sont en lecture seule. Déverrouillez pour les modifier.
        </p>
      )}
      <HomeAssistantSection disabled={locked} />
      <RestStateSection disabled={locked} />
      <LockCodeSection disabled={locked} />
      <EngineTokenSection />
      <AboutSection />
    </>
  );
}
