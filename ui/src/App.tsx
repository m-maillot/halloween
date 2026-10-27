import { useSyncExternalStore } from "react";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import { currentToken, onTokenChange, setToken } from "./api/token";
import { ToastProvider } from "./components/Toasts";
import { CatalogProvider } from "./catalog/CatalogProvider";
import { EngineProvider } from "./engine/EngineProvider";
import { Layout } from "./layout/Layout";
import { Components } from "./pages/Components";
import { Dashboard } from "./pages/Dashboard";
import { Scenarios } from "./pages/Scenarios";
import { Settings } from "./pages/Settings";
import { Spectacle } from "./pages/Spectacle";
import { Triggers } from "./pages/Triggers";
import { Styleguide } from "./Styleguide";
import { Button, Field } from "./components/ui";
import { useState } from "react";

export function useToken(): string | null {
  return useSyncExternalStore(onTokenChange, currentToken);
}

function TokenForm() {
  const [value, setValue] = useState("");
  return (
    <form
      className="token-form"
      onSubmit={(e) => {
        e.preventDefault();
        if (value.trim()) setToken(value.trim());
      }}
    >
      <h1>Déco Halloween</h1>
      <Field
        label="Jeton du moteur"
        type="password"
        value={value}
        onChange={(e) => setValue(e.target.value)}
        hint="Fichier api-token du dossier de données du moteur."
      />
      <Button variant="primary" type="submit">
        Se connecter
      </Button>
    </form>
  );
}

export function App({ WebSocketImpl }: { WebSocketImpl?: typeof WebSocket }) {
  const token = useToken();
  if (location.hash === "#styleguide") return <Styleguide />;
  if (!token) return <TokenForm />;
  return (
    <ToastProvider>
    <EngineProvider WebSocketImpl={WebSocketImpl}>
      <CatalogProvider>
      <BrowserRouter>
        <Routes>
          <Route element={<Layout />}>
            <Route index element={<Dashboard />} />
            <Route path="spectacle" element={<Spectacle />} />
            <Route path="scenarios/*" element={<Scenarios />} />
            <Route path="declencheurs" element={<Triggers />} />
            <Route path="composants/*" element={<Components />} />
            <Route path="reglages" element={<Settings />} />
          </Route>
        </Routes>
      </BrowserRouter>
      </CatalogProvider>
    </EngineProvider>
    </ToastProvider>
  );
}
