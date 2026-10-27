import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { App } from "./App";
import { setToken } from "./api/token";

const status = { version: "0.1.0", programs: 3, runs: [{}, {}] };

beforeEach(() => {
  localStorage.clear();
  setToken(null);
});
afterEach(() => vi.unstubAllGlobals());

function stubFetch(handler: (req: Request) => Response) {
  const fn = vi.fn(async (input: Request) => handler(input));
  vi.stubGlobal("fetch", fn);
  return fn;
}

test("sans jeton, l'écran de saisie s'affiche et aucun appel n'est fait", () => {
  const fetch = stubFetch(() => new Response("{}"));
  render(<App />);
  expect(screen.getByLabelText("Jeton du moteur")).toBeInTheDocument();
  expect(fetch).not.toHaveBeenCalled();
});

test("après saisie du jeton, /api/status est appelé avec l'en-tête Bearer", async () => {
  const fetch = stubFetch(() => Response.json(status));
  render(<App />);
  await userEvent.type(screen.getByLabelText("Jeton du moteur"), "secret-token");
  await userEvent.click(screen.getByRole("button", { name: "Se connecter" }));
  await screen.findByText(/3 scénario\(s\), 2 en cours/);
  const request = fetch.mock.calls[0][0];
  expect(new URL(request.url).pathname).toBe("/api/status");
  expect(request.headers.get("Authorization")).toBe("Bearer secret-token");
  expect(localStorage.getItem("halloween.token")).toBe("secret-token");
});

test("un jeton refusé (401) est oublié et la saisie réapparaît", async () => {
  setToken("mauvais");
  stubFetch(() => Response.json({ detail: "refusé" }, { status: 401 }));
  render(<App />);
  await waitFor(() => expect(screen.getByLabelText("Jeton du moteur")).toBeInTheDocument());
  expect(localStorage.getItem("halloween.token")).toBeNull();
});

test("un moteur injoignable affiche un message", async () => {
  setToken("ok");
  vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("fetch failed")));
  render(<App />);
  expect(await screen.findByRole("alert")).toHaveTextContent("Moteur injoignable");
});
