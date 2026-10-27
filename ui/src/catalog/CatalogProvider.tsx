import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { api } from "../api/client";
import type { components } from "../api/schema";
import { useEngine } from "../engine/EngineProvider";

export type Devices = components["schemas"]["Devices"];

interface CatalogContext {
  /** `null` tant que le premier chargement n'est pas revenu. */
  devices: Devices | null;
  reload: () => Promise<void>;
}

const Ctx = createContext<CatalogContext | null>(null);

export function useCatalog(): CatalogContext {
  const value = useContext(Ctx);
  if (!value) throw new Error("useCatalog hors d'un CatalogProvider");
  return value;
}

/** Catalogue des composants (`GET /devices`), relu à chaque changement du catalogue et à chaque reconnexion. */
export function CatalogProvider({ children }: { children: ReactNode }) {
  const { subscribe } = useEngine();
  const [devices, setDevices] = useState<Devices | null>(null);
  const loading = useRef<Promise<void> | null>(null);
  const again = useRef(false);

  const reload = useCallback((): Promise<void> => {
    if (loading.current) {
      again.current = true; // la lecture en vol est partie avant ce changement
      return loading.current;
    }
    const run = async (): Promise<void> => {
      do {
        again.current = false;
        try {
          const { data } = await api.GET("/api/devices");
          // openapi-fetch élargit les tuples `rgb_color` en `number[]` : même donnée, type plus lâche.
          if (data) setDevices(data as Devices);
        } catch {
          // moteur injoignable : l'écran hors ligne le dit déjà, on garde le dernier catalogue
        }
      } while (again.current);
      loading.current = null;
    };
    loading.current = run();
    return loading.current;
  }, []);

  useEffect(() => {
    void reload();
    return subscribe((event) => {
      // Les changements d'état d'un relais ou d'une lumière ne touchent pas le catalogue.
      if (event.type === "snapshot" || (event.type === "component_changed" && event.kind === "catalog")) {
        void reload();
      }
    });
  }, [reload, subscribe]);

  const value = useMemo(() => ({ devices, reload }), [devices, reload]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}
