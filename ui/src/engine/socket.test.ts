import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { createEventSocket, type SocketState } from "./socket";

class FakeWebSocket {
  static instances: FakeWebSocket[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((m: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  closed = false;
  constructor(public url: string) {
    FakeWebSocket.instances.push(this);
  }
  close() {
    this.closed = true;
    this.onclose?.();
  }
  open() {
    this.onopen?.();
  }
  receive(event: object) {
    this.onmessage?.({ data: JSON.stringify(event) });
  }
  drop() {
    this.onclose?.();
  }
}

beforeEach(() => {
  FakeWebSocket.instances = [];
  vi.useFakeTimers();
});
afterEach(() => vi.useRealTimers());

function setup() {
  const states: SocketState[] = [];
  const events: unknown[] = [];
  const onOpen = vi.fn();
  const socket = createEventSocket({
    url: () => "ws://moteur/api/events?token=t",
    onEvent: (e) => events.push(e),
    onState: (s) => states.push(s),
    onOpen,
    WebSocketImpl: FakeWebSocket as unknown as typeof WebSocket,
    delays: [100, 200, 400],
  });
  return { socket, states, events, onOpen };
}

test("se connecte, signale l'ouverture et transmet les événements", () => {
  const { states, events, onOpen } = setup();
  const ws = FakeWebSocket.instances[0];
  expect(ws.url).toBe("ws://moteur/api/events?token=t");
  ws.open();
  ws.receive({ type: "run_started", run_id: "r1" });
  expect(states).toEqual(["connecting", "open"]);
  expect(onOpen).toHaveBeenCalledOnce();
  expect(events).toEqual([{ type: "run_started", run_id: "r1" }]);
});

test("un message illisible est ignoré sans couper la connexion", () => {
  const { events } = setup();
  const ws = FakeWebSocket.instances[0];
  ws.open();
  ws.onmessage?.({ data: "pas du json" });
  ws.receive({ type: "lock_changed", locked: true });
  expect(events).toHaveLength(1);
  expect(ws.closed).toBe(false);
});

test("après une coupure, se reconnecte avec des délais croissants puis plafonnés", () => {
  const { states } = setup();
  FakeWebSocket.instances[0].drop();
  expect(states.at(-1)).toBe("closed");
  vi.advanceTimersByTime(99);
  expect(FakeWebSocket.instances).toHaveLength(1);
  vi.advanceTimersByTime(1);
  expect(FakeWebSocket.instances).toHaveLength(2); // après 100 ms
  FakeWebSocket.instances[1].drop();
  vi.advanceTimersByTime(200);
  expect(FakeWebSocket.instances).toHaveLength(3);
  FakeWebSocket.instances[2].drop();
  vi.advanceTimersByTime(400);
  expect(FakeWebSocket.instances).toHaveLength(4);
  FakeWebSocket.instances[3].drop();
  vi.advanceTimersByTime(400); // plafonné à 400
  expect(FakeWebSocket.instances).toHaveLength(5);
});

test("une reconnexion réussie relance onOpen (resynchronisation) et remet les délais à zéro", () => {
  const { onOpen } = setup();
  FakeWebSocket.instances[0].open();
  FakeWebSocket.instances[0].drop();
  vi.advanceTimersByTime(100);
  FakeWebSocket.instances[1].open();
  expect(onOpen).toHaveBeenCalledTimes(2);
  FakeWebSocket.instances[1].drop();
  vi.advanceTimersByTime(100); // repart du premier délai
  expect(FakeWebSocket.instances).toHaveLength(3);
});

test("une erreur ferme la connexion et déclenche la reconnexion", () => {
  setup();
  FakeWebSocket.instances[0].onerror?.();
  vi.advanceTimersByTime(100);
  expect(FakeWebSocket.instances).toHaveLength(2);
});

test("retry reconnecte tout de suite", () => {
  const { socket } = setup();
  FakeWebSocket.instances[0].drop();
  socket.retry();
  expect(FakeWebSocket.instances).toHaveLength(2);
  vi.advanceTimersByTime(1000);
  expect(FakeWebSocket.instances).toHaveLength(2); // l'ancien délai est annulé
});

test("close arrête définitivement les reconnexions", () => {
  const { socket } = setup();
  FakeWebSocket.instances[0].open();
  socket.close();
  vi.advanceTimersByTime(10_000);
  expect(FakeWebSocket.instances).toHaveLength(1);
});
