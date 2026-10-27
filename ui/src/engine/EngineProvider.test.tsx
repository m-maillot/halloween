import { act, render, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { setToken } from "../api/token";
import { FakeWebSocket, STATUS, stubEngine, WS } from "../test-engine";
import { EngineProvider, useEngine } from "./EngineProvider";

beforeEach(() => {
  localStorage.clear();
  FakeWebSocket.instances = [];
  setToken("secret");
});
afterEach(() => vi.unstubAllGlobals());

test("`subscribe` garde la même identité quand l'état change (les écrans abonnés ne se réabonnent pas)", async () => {
  let status = { ...STATUS };
  stubEngine(({ path }) => (path === "/api/status" ? status : undefined));
  const seen: { subscribe: unknown; uptime?: number }[] = [];
  function Probe() {
    const { subscribe, status } = useEngine();
    seen.push({ subscribe, uptime: status?.uptime_s });
    return null;
  }
  render(
    <EngineProvider WebSocketImpl={WS}>
      <Probe />
    </EngineProvider>,
  );
  await waitFor(() => expect(seen.some((s) => s.uptime === 10)).toBe(true));
  status = { ...STATUS, uptime_s: 99 };
  act(() => FakeWebSocket.emit({ type: "run_started", run_id: "r", program_id: "p", ts: 1 }));
  await waitFor(() => expect(seen.some((s) => s.uptime === 99)).toBe(true));
  expect(new Set(seen.map((s) => s.subscribe)).size).toBe(1);
});
