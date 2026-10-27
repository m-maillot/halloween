import { useEffect, useState } from "react";

export type WakeState = "pending" | "active" | "unsupported" | "denied";

type Sentinel = { release(): Promise<void>; addEventListener(type: "release", cb: () => void): void };
type WakeNavigator = Navigator & { wakeLock?: { request(type: "screen"): Promise<Sentinel> } };

/** Garde l'écran allumé (Screen Wake Lock API) tant que l'écran est monté et visible. */
export function useWakeLock(): WakeState {
  const [state, setState] = useState<WakeState>("pending");
  useEffect(() => {
    const wakeLock = (navigator as WakeNavigator).wakeLock;
    if (!wakeLock) {
      setState("unsupported");
      return;
    }
    let sentinel: Sentinel | null = null;
    let cancelled = false;
    const acquire = async () => {
      try {
        const lock = await wakeLock.request("screen");
        if (cancelled) {
          void lock.release();
          return;
        }
        sentinel = lock;
        lock.addEventListener("release", () => !cancelled && setState("pending"));
        setState("active");
      } catch {
        if (!cancelled) setState("denied"); // économie d'énergie, onglet masqué, permission refusée
      }
    };
    void acquire();
    // Le navigateur relâche le verrou quand l'onglet est masqué : on le reprend au retour.
    const onVisible = () => document.visibilityState === "visible" && void acquire();
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      cancelled = true;
      document.removeEventListener("visibilitychange", onVisible);
      void sentinel?.release();
    };
  }, []);
  return state;
}
