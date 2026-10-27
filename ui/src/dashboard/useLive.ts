import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api/client";
import type { components } from "../api/schema";
import { useEngine } from "../engine/EngineProvider";

export interface LiveState {
  state: "on" | "off" | "unknown";
  rgb?: [number, number, number];
  brightness?: number;
}

export type ProgramSummary = components["schemas"]["ProgramSummary"];

/** États des lumières et interrupteurs : lus une fois chez Home Assistant, puis suivis par événements. */
export function useLightStates(entityOf: Record<string, string>): Record<string, LiveState> {
  const { subscribe } = useEngine();
  const [states, setStates] = useState<Record<string, LiveState>>({});
  const key = JSON.stringify(entityOf);

  useEffect(() => {
    const byEntity = new Map(Object.entries(JSON.parse(key) as Record<string, string>).map(([id, e]) => [e, id]));
    if (byEntity.size === 0) return;
    let cancelled = false;
    // Un événement arrivé pendant la lecture est plus récent que la lecture : il l'emporte.
    const seenLive = new Set<string>();
    const stop = subscribe((event) => {
      if (event.type !== "component_changed" || !event.component_id || event.state === null) return;
      if (event.kind !== "light" && event.kind !== "switch") return;
      seenLive.add(event.component_id);
      const details = event.details as { rgb_color?: [number, number, number]; brightness?: number };
      setStates((all) => ({
        ...all,
        [event.component_id!]: { state: event.state!, rgb: details.rgb_color, brightness: details.brightness },
      }));
    });
    for (const domain of ["light", "switch"] as const) {
      api
        .GET("/api/ha/entities", { params: { query: { domain } } })
        .then(({ data }) => {
          if (cancelled || !data) return;
          setStates((all) => {
            const next = { ...all };
            for (const entity of data) {
              const id = byEntity.get(entity.entity_id);
              if (id && !seenLive.has(id)) {
                next[id] = { state: entity.state === "on" ? "on" : entity.state === "off" ? "off" : "unknown" };
              }
            }
            return next;
          });
        })
        .catch(() => undefined); // Home Assistant injoignable : les tuiles restent « inconnu »
    }
    return () => {
      cancelled = true;
      stop();
    };
  }, [key, subscribe]);

  return states;
}

/** Programmes (pour la durée maximale des barres de progression), relus à chaque début / fin de run. */
export function usePrograms(): ProgramSummary[] {
  const { subscribe } = useEngine();
  const [programs, setPrograms] = useState<ProgramSummary[]>([]);
  const loading = useRef(false);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      if (loading.current) return;
      loading.current = true;
      try {
        const { data } = await api.GET("/api/programs");
        if (data && !cancelled) setPrograms(data);
      } catch {
        // moteur injoignable : on garde la liste précédente
      } finally {
        loading.current = false;
      }
    };
    void load();
    const stop = subscribe((event) => {
      if (event.type === "run_started" || event.type === "run_ended" || event.type === "snapshot") void load();
    });
    return () => {
      cancelled = true;
      stop();
    };
  }, [subscribe]);

  return programs;
}

export interface ButtonPress {
  button_id: string;
  event: "short" | "long" | "double";
  at: number;
}

/** Derniers appuis de boutons physiques (câblage), le plus récent en premier. */
export function useButtonPresses(limit = 5): ButtonPress[] {
  const { subscribe } = useEngine();
  const [presses, setPresses] = useState<ButtonPress[]>([]);
  useEffect(
    () =>
      subscribe((event) => {
        if (event.type !== "button_event") return;
        const press = { button_id: event.button_id, event: event.event, at: Date.now() };
        setPresses((all) => [press, ...all].slice(0, limit));
      }),
    [subscribe, limit],
  );
  return presses;
}

/** Heure du moteur, en secondes : l'horloge locale corrigée de l'écart (tablette et Pi ne sont pas synchronisés). */
export function useEngineClock(): () => number {
  const { status } = useEngine();
  // L'écart se mesure quand un nouvel état arrive : `started_at + uptime_s` est l'heure du moteur à ce moment.
  const skew = useMemo(
    () => (status ? status.started_at + status.uptime_s - Date.now() / 1000 : 0),
    [status],
  );
  return () => Date.now() / 1000 + skew;
}

/** Re-rendu régulier (progression des runs). */
export function useTick(ms: number, active: boolean): void {
  const [, setTick] = useState(0);
  useEffect(() => {
    if (!active) return;
    const timer = setInterval(() => setTick((n) => n + 1), ms);
    return () => clearInterval(timer);
  }, [ms, active]);
}
