import { NavLink, Outlet } from "react-router-dom";
import { Cable, LayoutGrid, Play, Settings, Shapes, Zap } from "lucide-react";
import { useEngine } from "../engine/EngineProvider";
import { Banner } from "./Banner";
import { OfflineScreen } from "./OfflineScreen";
import "./layout.css";

const ENTRIES = [
  { to: "/spectacle", label: "Mode spectacle", icon: Play },
  { to: "/", label: "Tableau de bord", icon: LayoutGrid, end: true },
  { to: "/scenarios", label: "Scénarios", icon: Shapes },
  { to: "/declencheurs", label: "Déclencheurs", icon: Zap },
  { to: "/composants", label: "Composants", icon: Cable },
  { to: "/reglages", label: "Réglages", icon: Settings },
];

export function Layout() {
  const { connection, status } = useEngine();
  // Hors ligne (ou pas encore de première réponse) : rien n'est actionnable, sauf « Réessayer ».
  const blocked = connection === "offline" || (connection === "connecting" && !status);
  return (
    <div className="shell">
      <nav className="sidebar" aria-label="Navigation" inert={blocked || undefined}>
        <div className="sidebar__brand">Déco Halloween</div>
        {ENTRIES.map(({ to, label, icon: Icon, end }) => (
          <NavLink key={to} to={to} end={end} className="sidebar__link">
            <Icon size={20} aria-hidden="true" />
            <span>{label}</span>
          </NavLink>
        ))}
      </nav>
      <div className="shell__main">
        <Banner />
        <main className="shell__content">
          {blocked ? <OfflineScreen /> : <Outlet />}
        </main>
      </div>
    </div>
  );
}
