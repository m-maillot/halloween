import type { components } from "../api/schema";

export type EngineEvent = components["schemas"]["Event"];
export type SocketState = "connecting" | "open" | "closed";

export interface SocketOptions {
  url: () => string;
  onEvent: (event: EngineEvent) => void;
  onState: (state: SocketState) => void;
  /** Appelé à chaque (re)connexion : on relit l'état complet pour rattraper ce qui a été manqué. */
  onOpen: () => void;
  WebSocketImpl?: typeof WebSocket;
  /** Délais de reconnexion (ms) : croissants puis plafonnés au dernier. */
  delays?: number[];
}

export const RECONNECT_DELAYS = [500, 1000, 2000, 5000, 10000];

/** WebSocket `/api/events` qui se reconnecte seul tant qu'il n'est pas fermé par `close()`. */
export function createEventSocket(options: SocketOptions) {
  const Impl = options.WebSocketImpl ?? WebSocket;
  const delays = options.delays ?? RECONNECT_DELAYS;
  let socket: WebSocket | null = null;
  let timer: ReturnType<typeof setTimeout> | undefined;
  let attempt = 0;
  let stopped = false;

  function connect() {
    if (stopped) return;
    options.onState("connecting");
    const ws = new Impl(options.url());
    socket = ws;
    ws.onopen = () => {
      attempt = 0;
      options.onState("open");
      options.onOpen();
    };
    ws.onmessage = (message) => {
      try {
        options.onEvent(JSON.parse(String(message.data)) as EngineEvent);
      } catch {
        /* message illisible : ignoré, la connexion continue */
      }
    };
    ws.onclose = () => {
      if (socket !== ws) return;
      socket = null;
      if (stopped) return;
      options.onState("closed");
      const delay = delays[Math.min(attempt, delays.length - 1)];
      attempt += 1;
      timer = setTimeout(connect, delay);
    };
    ws.onerror = () => ws.close();
  }

  connect();
  return {
    /** Reconnexion immédiate (bouton « Réessayer »). */
    retry() {
      clearTimeout(timer);
      if (socket) {
        const old = socket;
        socket = null;
        old.close();
      }
      attempt = 0;
      connect();
    },
    close() {
      stopped = true;
      clearTimeout(timer);
      socket?.close();
      socket = null;
    },
  };
}
