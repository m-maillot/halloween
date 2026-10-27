import { Plus } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { Link, Route, Routes, useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { unwrap } from "../api/errors";
import type { components } from "../api/schema";
import { Button, Card, Field, Modal } from "../components/ui";
import { useToasts } from "../components/Toasts";
import { ScenarioEditor } from "../editor/ScenarioEditor";
import { useEngine } from "../engine/EngineProvider";

type Summary = components["schemas"]["ProgramSummary"];

function slug(name: string): string {
  const base = name.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");
  return (base || "scenario").slice(0, 56);
}

function List() {
  const toasts = useToasts();
  const navigate = useNavigate();
  const [programs, setPrograms] = useState<Summary[] | null>(null);
  const { status } = useEngine();
  const locked = status?.lock.locked ?? false;
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");

  const load = useCallback(() => {
    unwrap<Summary[]>(api.GET("/api/programs")).then(setPrograms).catch((error) => toasts.error(error));
  }, [toasts]);
  useEffect(load, [load]);

  async function create() {
    const taken = new Set((programs ?? []).map((p) => p.id));
    let id = slug(name);
    for (let n = 2; taken.has(id); n++) id = `${slug(name)}-${n}`;
    try {
      await unwrap(
        api.PUT("/api/programs/{program_id}", {
          params: { path: { program_id: id } },
          body: {
            schema: 1,
            id,
            name: name.trim(),
            on_end: "reset",
            revision: 0,
            show: false,
            scripts: [{ id: "s1", hat: { type: "start" }, root: { id: "s1_root", type: "sequence", children: [] } }],
          },
        }),
      );
      navigate(`/scenarios/${id}`);
    } catch (error) {
      toasts.error(error);
    }
  }

  return (
    <>
      <div className="page-head">
        <h1>Scénarios</h1>
        <Button variant="primary" disabled={locked} onClick={() => setCreating(true)}>
          <Plus size={18} aria-hidden="true" /> Nouveau scénario
        </Button>
      </div>
      {!programs ? (
        <p className="muted">Chargement…</p>
      ) : programs.length === 0 ? (
        <p className="muted">Aucun scénario. Créez le premier.</p>
      ) : (
        <ul className="grid">
          {programs.map((p) => (
            <li key={p.id}>
              <Card label={p.name}>
                <div className="run-row">
                  <div className="run-row__text">
                    <strong>{p.name}</strong>
                    <span className="muted">
                      {p.scripts} script{p.scripts > 1 ? "s" : ""}
                      {p.valid ? "" : " · invalide"}
                    </span>
                  </div>
                  <Link className="btn" to={`/scenarios/${p.id}`}>
                    Ouvrir
                  </Link>
                </div>
              </Card>
            </li>
          ))}
        </ul>
      )}
      {creating && (
        <Modal title="Nouveau scénario" onClose={() => setCreating(false)}>
          <form
            className="form"
            onSubmit={(e) => {
              e.preventDefault();
              void create();
            }}
          >
            <Field label="Nom" value={name} maxLength={80} autoFocus onChange={(e) => setName(e.target.value)} />
            <div className="form-actions">
              <span className="form-actions__spacer" />
              <Button variant="ghost" onClick={() => setCreating(false)}>
                Annuler
              </Button>
              <Button variant="primary" type="submit" disabled={!name.trim()}>
                Créer
              </Button>
            </div>
          </form>
        </Modal>
      )}
    </>
  );
}

export function Scenarios() {
  return (
    <Routes>
      <Route index element={<List />} />
      <Route path=":id" element={<ScenarioEditor />} />
    </Routes>
  );
}
