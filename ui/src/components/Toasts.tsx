import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";
import { X } from "lucide-react";
import { describeError, type Described } from "../api/errors";

interface Toast extends Described {
  id: number;
  kind: "error" | "info";
}

interface ToastApi {
  error: (error: unknown) => void;
  info: (title: string) => void;
}

const Ctx = createContext<ToastApi | null>(null);

export function useToasts(): ToastApi {
  const value = useContext(Ctx);
  if (!value) throw new Error("useToasts hors d'un ToastProvider");
  return value;
}

let nextId = 1;
const MAX = 4;

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const add = useCallback((toast: Omit<Toast, "id">) => {
    setToasts((all) => {
      const duplicate = all.some((t) => t.title === toast.title && t.details.join() === toast.details.join());
      return duplicate ? all : [...all, { ...toast, id: nextId++ }].slice(-MAX);
    });
  }, []);
  const remove = (id: number) => setToasts((all) => all.filter((t) => t.id !== id));

  const api = useMemo<ToastApi>(
    () => ({
      error: (error) => add({ ...describeError(error), kind: "error" }),
      info: (title) => add({ title, details: [], kind: "info" }),
    }),
    [add],
  );

  return (
    <Ctx.Provider value={api}>
      {children}
      {/* Les erreurs restent jusqu'à fermeture (pas de disparition automatique : on a le temps de lire). */}
      <div className="toasts" role="region" aria-label="Notifications" aria-live="polite">
        {toasts.map((toast) => (
          <div key={toast.id} className={`toast toast--${toast.kind}`} role={toast.kind === "error" ? "alert" : "status"}>
            <div className="toast__body">
              <strong>{toast.title}</strong>
              {toast.retryAfter !== undefined && <span> Réessayer dans {toast.retryAfter} s.</span>}
              {toast.details.length > 0 && (
                <details>
                  <summary>Détails ({toast.details.length})</summary>
                  <ul>
                    {toast.details.map((line, i) => (
                      <li key={i}>{line}</li>
                    ))}
                  </ul>
                </details>
              )}
            </div>
            <button type="button" className="toast__close" aria-label="Fermer la notification" onClick={() => remove(toast.id)}>
              <X size={18} aria-hidden="true" />
            </button>
          </div>
        ))}
      </div>
    </Ctx.Provider>
  );
}
