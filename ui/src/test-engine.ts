// Faux moteur partagé par les tests d'écrans : WebSocket factice et `fetch` routé à la main.
import { vi } from "vitest";

export class FakeWebSocket {
  static instances: FakeWebSocket[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((m: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  constructor(public url: string) {
    FakeWebSocket.instances.push(this);
  }
  close() {
    this.onclose?.();
  }
  /** Fait arriver un événement du moteur. */
  static emit(event: object) {
    FakeWebSocket.instances.at(-1)?.onmessage?.({ data: JSON.stringify(event) });
  }
}
export const WS = FakeWebSocket as unknown as typeof WebSocket;

export interface Call {
  method: string;
  path: string;
  search: string;
  body: unknown;
  headers: Headers;
}

export type Handler = (call: Call) => Response | object | Promise<Response | object> | undefined;

/** Installe un `fetch` factice ; `handler` répond (objet = JSON 200, `undefined` = 404). */
export function stubEngine(handler: Handler): Call[] {
  const calls: Call[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (req: Request) => {
      const url = new URL(req.url);
      const text = req.method === "GET" || req.method === "DELETE" ? "" : await req.clone().text();
      let body: unknown = text;
      try {
        body = text ? JSON.parse(text) : undefined;
      } catch {
        /* corps binaire ou texte : laissé tel quel */
      }
      const call: Call = {
        method: req.method,
        path: url.pathname,
        search: url.search,
        body,
        headers: req.headers,
      };
      calls.push(call);
      const result = await handler(call);
      if (result instanceof Response) return result;
      if (result === undefined) return Response.json({}, { status: 404 });
      return Response.json(result);
    }),
  );
  return calls;
}

export const STATUS = {
  version: "0.1.0",
  started_at: 1,
  uptime_s: 10,
  programs: 0,
  triggers: 0,
  runs: [] as object[],
  relays: {} as Record<string, boolean>,
  lock: { locked: false, has_code: false },
  home_assistant: { mode: "real", last_ok_at: 1, last_error: null },
  startup_issues: [],
  rest_pending: [],
  recent_problems: [],
};
