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
import { currentToken } from "../api/token";
import { createEventSocket, type EngineEvent } from "./socket";

export type Status = components["schemas"]["Status"];
export type Connection = "connecting" | "online" | "offline";

interface EngineContext {
  status: Status | null;
  connection: Connection;
  /** Relit l'état et relance la connexion temps réel (bouton « Réessayer »). */
  retry: () => void;
  refresh: () => Promise<void>;
  /** Abonnement aux événements bruts (surlignage de bloc, appuis de bouton...). */
  subscribe: (listener: (event: EngineEvent) => void) => () => void;
}

const Ctx = createContext<EngineContext | null>(null);

export function useEngine(): EngineContext {
  const value = useContext(Ctx);
  if (!value) throw new Error("useEngine hors d'un EngineProvider");
  return value;
}

/** Événements après lesquels l'état agrégé (`/status`) est relu. */
const REFRESH_ON = new Set(["run_started", "run_ended", "lock_changed", "component_changed", "snapshot"]);
const POLL_MS = 30_000;

export function EngineProvider({
  children,
  WebSocketImpl,
}: {
  children: ReactNode;
  WebSocketImpl?: typeof WebSocket;
}) {
  const [status, setStatus] = useState<Status | null>(null);
  const [connection, setConnection] = useState<Connection>("connecting");
  const listeners = useRef(new Set<(event: EngineEvent) => void>());
  const socket = useRef<ReturnType<typeof createEventSocket> | null>(null);
  const refreshing = useRef<Promise<void> | null>(null);

  const again = useRef(false);

  const refresh = useCallback((): Promise<void> => {
    if (refreshing.current) {
      // Une lecture est déjà en vol, partie avant ce nouvel événement : on en refait une après.
      again.current = true;
      return refreshing.current;
    }
    const run = async (): Promise<void> => {
      do {
        again.current = false;
        try {
          const { data } = await api.GET("/api/status");
          if (data) {
            setStatus(data);
            setConnection("online");
          } else {
            setConnection("offline"); // réponse d'erreur (503 pendant une reconfiguration, 5xx...)
          }
        } catch {
          setConnection("offline");
        }
      } while (again.current);
      refreshing.current = null;
    };
    refreshing.current = run();
    return refreshing.current;
  }, []);

  useEffect(() => {
    const protocol = location.protocol === "https:" ? "wss:" : "ws:";
    const ws = createEventSocket({
      url: () =>
        `${protocol}//${location.host}/api/events?token=${encodeURIComponent(currentToken() ?? "")}`,
      WebSocketImpl,
      onState: (state) => {
        if (state === "closed") setConnection("offline");
      },
      onOpen: () => void refresh(),
      onEvent: (event) => {
        listeners.current.forEach((listener) => listener(event));
        if (REFRESH_ON.has(event.type)) void refresh();
      },
    });
    socket.current = ws;
    void refresh();
    const poll = setInterval(() => void refresh(), POLL_MS);
    return () => {
      clearInterval(poll);
      ws.close();
    };
  }, [refresh, WebSocketImpl]);

  // Identité stable : les écrans qui s'abonnent (tableau de bord, éditeur) ne se réabonnent pas, et ne
  // relancent pas leurs lectures, à chaque nouvel état reçu.
  const subscribe = useCallback((listener: (event: EngineEvent) => void) => {
    listeners.current.add(listener);
    return () => listeners.current.delete(listener);
  }, []);

  const value = useMemo<EngineContext>(
    () => ({
      status,
      connection,
      refresh,
      retry: () => {
        setConnection("connecting");
        socket.current?.retry();
        void refresh();
      },
      subscribe,
    }),
    [status, connection, refresh, subscribe],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}
