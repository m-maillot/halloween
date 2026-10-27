import { Plus } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { Link, Route, Routes, useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { unwrap } from "../api/errors";
import type { components } from "../api/schema";
import { ArrowDown, ArrowUp } from "lucide-react";
import { Button, Card, CheckField, Field, Modal } from "../components/ui";
import { showOrder } from "../show/order";
import { useToasts } from "../components/Toasts";
import { ScenarioEditor } from "../editor/ScenarioEditor";
import { useEngine } from "../engine/EngineProvider";

type Summary = components["schemas"]["ProgramSummary"];
type Program = components["schemas"]["Program"];

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
  const [deleting, setDeleting] = useState<Summary | null>(null);

  const load = useCallback(() => {
    unwrap<Summary[]>(api.GET("/api/programs")).then(setPrograms).catch((error) => toasts.error(error));
  }, [toasts]);
  useEffect(load, [load]);

  const fetchProgram = (id: string) => unwrap<Program>(api.GET("/api/programs/{program_id}", { params: { path: { program_id: id } } }));
  const putProgram = (program: Program, create = false) =>
    unwrap(
      api.PUT("/api/programs/{program_id}", {
        params: { path: { program_id: program.id } },
        headers: create ? {} : { "If-Match": `"${program.revision}"` },
        body: program as never,
      }),
    );

  /** Coche / décoche « afficher en mode spectacle » : un décoché perd son rang, un coché passe en dernier. */
  async function setShow(summary: Summary, show: boolean) {
    try {
      const last = Math.max(0, ...showOrder(programs ?? []).map((p) => p.show_order ?? 0));
      await putProgram({ ...(await fetchProgram(summary.id)), show, show_order: show ? last + 1 : null });
      load();
    } catch (error) {
      toasts.error(error);
    }
  }

  /** Échange la place de deux scénarios affichés ; les rangs sont renumérotés de 1 à n. */
  async function move(summary: Summary, delta: -1 | 1) {
    const shown = showOrder(programs ?? []);
    const from = shown.findIndex((p) => p.id === summary.id);
    const to = from + delta;
    if (from < 0 || to < 0 || to >= shown.length) return;
    const next = [...shown];
    [next[from], next[to]] = [next[to], next[from]];
    try {
      for (const [index, p] of next.entries()) {
        if (p.show_order === index + 1) continue;
        await putProgram({ ...(await fetchProgram(p.id)), show_order: index + 1 });
      }
    } catch (error) {
      toasts.error(error);
    }
    load();
  }

  async function duplicate(summary: Summary) {
    const taken = new Set((programs ?? []).map((p) => p.id));
    const name = `${summary.name} (copie)`.slice(0, 80);
    let id = slug(name);
    for (let n = 2; taken.has(id); n++) id = `${slug(name)}-${n}`;
    try {
      // Une copie est un scénario neuf : révision 0, jamais affichée en mode spectacle d'office.
      await putProgram({ ...(await fetchProgram(summary.id)), id, name, revision: 0, show: false, show_order: null }, true);
      navigate(`/scenarios/${id}`);
    } catch (error) {
      toasts.error(error);
    }
  }

  async function remove(summary: Summary) {
    try {
      await unwrap(api.DELETE("/api/programs/{program_id}", { params: { path: { program_id: summary.id } } }));
      setDeleting(null);
      load();
    } catch (error) {
      toasts.error(error);
    }
  }

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
          {programs.map((p) => {
            const shown = showOrder(programs);
            const rank = shown.findIndex((x) => x.id === p.id);
            return (
              <li key={p.id}>
                <Card label={p.name}>
                  <div className="run-row">
                    <div className="run-row__text">
                      <strong>{p.name}</strong>
                      <span className="muted">
                        {p.scripts} script{p.scripts > 1 ? "s" : ""}
                        {p.max_duration_s ? ` · ${p.max_duration_s} s max` : ""}
                        {p.valid ? "" : " · invalide"}
                      </span>
                    </div>
                    <Link className="btn" to={`/scenarios/${p.id}`}>
                      Ouvrir
                    </Link>
                  </div>
                  <CheckField label="Afficher en mode spectacle" checked={p.show} disabled={locked} onChange={(e) => void setShow(p, e.target.checked)} />
                  <div className="form-actions">
                    {p.show && (
                      <>
                        <Button variant="ghost" aria-label={`Monter ${p.name} dans le mode spectacle`} disabled={locked || rank <= 0} onClick={() => void move(p, -1)}>
                          <ArrowUp size={18} aria-hidden="true" />
                        </Button>
                        <Button variant="ghost" aria-label={`Descendre ${p.name} dans le mode spectacle`} disabled={locked || rank < 0 || rank >= shown.length - 1} onClick={() => void move(p, 1)}>
                          <ArrowDown size={18} aria-hidden="true" />
                        </Button>
                      </>
                    )}
                    <span className="form-actions__spacer" />
                    <Button variant="ghost" disabled={locked} onClick={() => void duplicate(p)}>
                      Dupliquer
                    </Button>
                    <Button variant="outline-danger" disabled={locked} onClick={() => setDeleting(p)}>
                      Supprimer
                    </Button>
                  </div>
                </Card>
              </li>
            );
          })}
        </ul>
      )}
      {deleting && (
        <Modal title="Supprimer ce scénario ?" onClose={() => setDeleting(null)}>
          <p>« {deleting.name} » sera supprimé définitivement. Les règles de déclenchement qui le lancent devront être modifiées.</p>
          <div className="form-actions">
            <span className="form-actions__spacer" />
            <Button variant="ghost" onClick={() => setDeleting(null)}>
              Garder
            </Button>
            <Button variant="danger" onClick={() => void remove(deleting)}>
              Supprimer
            </Button>
          </div>
        </Modal>
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
