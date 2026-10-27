import { useEffect, useState, useSyncExternalStore } from "react";
import { api } from "./api/client";
import { currentToken, onTokenChange, setToken } from "./api/token";
import type { components } from "./api/schema";
import { Styleguide } from "./Styleguide";

type Status = components["schemas"]["Status"];

export function useToken(): string | null {
  return useSyncExternalStore(onTokenChange, currentToken);
}

function TokenForm() {
  const [value, setValue] = useState("");
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        if (value.trim()) setToken(value.trim());
      }}
    >
      <h1>Déco Halloween</h1>
      <label>
        Jeton du moteur
        <input type="password" value={value} onChange={(e) => setValue(e.target.value)} />
      </label>
      <button type="submit">Se connecter</button>
    </form>
  );
}

function StatusView() {
  const [status, setStatus] = useState<Status | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let cancelled = false;
    api
      .GET("/api/status")
      .then(({ data, error: apiError }) => {
        if (cancelled) return;
        if (data) setStatus(data);
        else if (apiError) setError("Le moteur a refusé la requête.");
      })
      .catch(() => !cancelled && setError("Moteur injoignable."));
    return () => {
      cancelled = true;
    };
  }, []);
  if (error) return <p role="alert">{error}</p>;
  if (!status) return <p>Chargement…</p>;
  return (
    <main>
      <h1>Déco Halloween</h1>
      <p>
        Moteur v{status.version}, {status.programs} scénario(s), {status.runs.length} en cours.
      </p>
    </main>
  );
}

export function App() {
  const token = useToken();
  if (location.hash === "#styleguide") return <Styleguide />;
  return token ? <StatusView /> : <TokenForm />;
}
