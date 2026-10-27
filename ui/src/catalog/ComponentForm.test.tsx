import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { App } from "../App";
import { setToken } from "../api/token";
import { FakeWebSocket, STATUS, stubEngine, WS, type Call } from "../test-engine";

type Json = Record<string, unknown>;
let devices: { relays: Json[]; buttons: Json[]; lights: Json[]; switches: Json[]; rest_state: Json };
let calls: Call[];
let respond: (call: Call) => Response | object | undefined;
let entities: Response | object;

const rest = (status: number, detail: unknown) => Response.json({ detail }, { status });

beforeEach(() => {
  localStorage.clear();
  FakeWebSocket.instances = [];
  devices = {
    relays: [{ id: "orage", name: "Orage", pin: 22, mode: "latched", active_low: false, image: null, image_url: null }],
    buttons: [{ id: "bp", name: "Bouton principal", pin: 21, pull: "up", debounce_ms: 50, long_press_ms: 800, double_press_ms: 400 }],
    lights: [],
    switches: [],
    rest_state: {},
  };
  entities = [
    { entity_id: "light.bandeau", name: "Bandeau", state: "off", domain: "light", capabilities: { color: true, brightness: true, transition: false } },
    { entity_id: "light.lampe", name: "Lampe", state: "off", domain: "light", capabilities: null },
  ];
  respond = () => undefined;
  window.history.replaceState(null, "", "/composants");
  calls = stubEngine((call) => {
    const { path, method } = call;
    const custom = respond(call);
    if (custom !== undefined) return custom;
    if (path === "/api/status") return STATUS;
    if (path === "/api/devices") return devices;
    if (path === "/api/ha/entities") return entities;
    if (method === "POST" && path === "/api/components/relays") {
      const body = call.body as Json;
      const component = { id: "fantome", image_url: null, active_low: false, ...body };
      devices.relays.push(component);
      return Response.json({ component, issues: [] }, { status: 201 });
    }
    if (method === "POST" && path.endsWith("/test")) return { ok: true, message: "Orage : on" };
  });
  setToken("secret");
});
afterEach(() => vi.unstubAllGlobals());

async function openApp() {
  render(<App WebSocketImpl={WS} />);
  await screen.findByText("Orage");
  return userEvent.setup();
}

test("créer le relais « Fantôme » (broche 18) avec une icône, puis le tester", async () => {
  const user = await openApp();
  await user.click(screen.getByRole("button", { name: "Ajouter un relais" }));
  const dialog = screen.getByRole("dialog", { name: "Ajouter relais" });
  await user.type(within(dialog).getByLabelText("Nom"), "Fantôme");
  await user.click(within(dialog).getByRole("button", { name: "Fantôme" })); // icône de la bibliothèque
  await user.selectOptions(within(dialog).getByLabelText(/Broche/), "18");
  await user.click(within(dialog).getByRole("button", { name: "Enregistrer" }));

  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  const post = calls.find((c) => c.method === "POST" && c.path === "/api/components/relays")!;
  expect(post.body).toEqual({
    name: "Fantôme",
    image: "builtin:ghost",
    pin: 18,
    mode: "latched",
    active_low: false,
    max_on_seconds: null,
  });
  expect(post.headers.get("Authorization")).toBe("Bearer secret");
  expect(await screen.findByLabelText("Fantôme")).toBeInTheDocument();

  // test manuel du composant créé
  await user.click(screen.getByLabelText("Fantôme"));
  const edit = screen.getByRole("dialog", { name: "Modifier relais" });
  expect(within(edit).getByLabelText("Identifiant technique")).toHaveAttribute("readonly");
  await user.click(within(edit).getByRole("button", { name: "Allumer" }));
  expect(await within(edit).findByRole("status")).toHaveTextContent("Orage : on");
  const test = calls.find((c) => c.path === "/api/components/relays/fantome/test")!;
  expect(test.body).toEqual({ action: "on" });
});

test("les broches déjà utilisées sont grisées, avec leur propriétaire", async () => {
  const user = await openApp();
  await user.click(screen.getByRole("button", { name: "Ajouter un relais" }));
  const pin22 = screen.getByRole("option", { name: /GPIO 22/ });
  expect(pin22).toBeDisabled();
  expect(pin22).toHaveTextContent("utilisée par Orage");
  expect(screen.getByRole("option", { name: /GPIO 21.*Bouton principal/ })).toBeDisabled();
  expect(screen.getByRole("option", { name: "GPIO 18" })).toBeEnabled();
});

test("modifier un composant garde sa propre broche disponible", async () => {
  const user = await openApp();
  await user.click(screen.getByLabelText("Orage"));
  expect(screen.getByRole("option", { name: "GPIO 22" })).toBeEnabled();
});

test("une image personnelle est téléversée en corps brut puis référencée", async () => {
  respond = ({ path }) =>
    path === "/api/images" ? Response.json({ image: "abc123.webp", url: "/api/images/abc123.webp", width: 8, height: 8 }, { status: 201 }) : undefined;
  const user = await openApp();
  await user.click(screen.getByRole("button", { name: "Ajouter un relais" }));
  await user.click(screen.getByRole("tab", { name: "Image personnelle" }));
  const file = new File(["png!"], "photo.png", { type: "image/png" });
  await user.upload(screen.getByLabelText("Téléverser une image"), file);
  await waitFor(() => expect(calls.some((c) => c.path === "/api/images")).toBe(true));
  const upload = calls.find((c) => c.path === "/api/images")!;
  expect(upload.headers.get("Content-Type")).toBe("image/png");
  expect(upload.body).toBe("png!");
  await waitFor(() =>
    expect(screen.getByRole("dialog").querySelector("img")).toHaveAttribute("src", "/api/images/abc123.webp"),
  );
  await user.type(screen.getByLabelText("Nom"), "Photo");
  await user.selectOptions(screen.getByLabelText(/Broche/), "18");
  await user.click(screen.getByRole("button", { name: "Enregistrer" }));
  await waitFor(() => expect(calls.some((c) => c.method === "POST" && c.path === "/api/components/relays")).toBe(true));
  expect(calls.find((c) => c.path === "/api/components/relays")!.body).toMatchObject({ image: "abc123.webp" });
});

test("un format d'image non pris en charge est refusé sans appel au moteur", async () => {
  const user = await openApp();
  await user.click(screen.getByRole("button", { name: "Ajouter un relais" }));
  await user.click(screen.getByRole("tab", { name: "Image personnelle" }));
  const input = screen.getByLabelText("Téléverser une image");
  // `applyAccept: false` : on simule un fichier choisi malgré le filtre du sélecteur
  await userEvent.setup({ applyAccept: false }).upload(input, new File(["x"], "a.gif", { type: "image/gif" }));
  expect(await screen.findByText(/Format non pris en charge/)).toBeInTheDocument();
  expect(calls.some((c) => c.path === "/api/images")).toBe(false);
});

test("la recherche filtre la bibliothèque d'icônes", async () => {
  const user = await openApp();
  await user.click(screen.getByRole("button", { name: "Ajouter un relais" }));
  await user.type(screen.getByLabelText("Rechercher une icône"), "eclair");
  expect(screen.getByRole("button", { name: "Éclair" })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Fantôme" })).toBeNull();
});

test("le mode impulsion montre ses champs et un test « Déclencher »", async () => {
  devices.relays.push({ id: "fumee", name: "Fumée", pin: 5, mode: "push", pulse_ms: 500, active_low: false, image: null, image_url: null });
  const user = await openApp();
  await user.click(screen.getByLabelText("Fumée"));
  expect(screen.getByLabelText("Durée de l'impulsion (ms)")).toHaveValue(500);
  expect(screen.queryByLabelText(/Durée maximale d'allumage/)).toBeNull();
  await user.click(screen.getByRole("button", { name: "Déclencher" }));
  expect(calls.find((c) => c.path === "/api/components/relays/fumee/test")!.body).toEqual({ action: "trigger" });
});

test("une lumière : entités en liste, capacités préremplies, test avec couleur", async () => {
  const user = await openApp();
  await user.click(screen.getByRole("tab", { name: /Lumières/ }));
  await user.click(screen.getByRole("button", { name: "Ajouter une lumière" }));
  await waitFor(() => expect(screen.getByRole("option", { name: "Bandeau (light.bandeau)" })).toBeInTheDocument());
  expect(calls.find((c) => c.path === "/api/ha/entities")!.search).toBe("?domain=light");
  await user.selectOptions(screen.getByLabelText("Entité Home Assistant"), "light.bandeau");
  expect(screen.getByLabelText("Couleur")).toBeChecked();
  expect(screen.getByLabelText("Luminosité")).toBeChecked();
  expect(screen.getByLabelText("Transition")).not.toBeChecked();
});

test("Home Assistant injoignable : l'entité se saisit à la main", async () => {
  entities = rest(502, { message: "Home Assistant injoignable", issues: [] });
  respond = ({ path }) => (path === "/api/ha/entities" ? (entities as Response) : undefined);
  const user = await openApp();
  await user.click(screen.getByRole("tab", { name: /Interrupteurs/ }));
  await user.click(screen.getByRole("button", { name: "Ajouter un interrupteur" }));
  const input = await screen.findByPlaceholderText("switch.nom_de_l_entite");
  expect(input.tagName).toBe("INPUT");
  expect(screen.getByText(/n'a pas pu être lue/)).toBeInTheDocument();
});

test("une erreur de validation s'affiche sous le champ concerné", async () => {
  respond = ({ method, path }) =>
    method === "POST" && path === "/api/components/relays"
      ? rest(422, [{ loc: ["body", "pin"], msg: "Input should be less than or equal to 27", type: "x" }])
      : undefined;
  const user = await openApp();
  await user.click(screen.getByRole("button", { name: "Ajouter un relais" }));
  await user.type(screen.getByLabelText("Nom"), "X");
  await user.selectOptions(screen.getByLabelText(/Broche/), "18");
  await user.click(screen.getByRole("button", { name: "Enregistrer" }));
  const alert = await screen.findByText("Input should be less than or equal to 27");
  expect(screen.getByLabelText(/Broche/)).toHaveAccessibleDescription(/less than or equal/);
  expect(alert).toHaveAttribute("role", "alert");
  expect(screen.getByRole("dialog")).toBeInTheDocument(); // le formulaire reste ouvert
});

test("une règle de configuration refusée est affichée dans le formulaire", async () => {
  respond = ({ method, path }) =>
    method === "POST" && path === "/api/components/relays"
      ? rest(422, { message: "configuration invalide", issues: [{ message: "broche 18 utilisée deux fois", component_id: "fantome" }] })
      : undefined;
  const user = await openApp();
  await user.click(screen.getByRole("button", { name: "Ajouter un relais" }));
  await user.type(screen.getByLabelText("Nom"), "X");
  await user.selectOptions(screen.getByLabelText(/Broche/), "18");
  await user.click(screen.getByRole("button", { name: "Enregistrer" }));
  expect(await screen.findByText("configuration invalide")).toBeInTheDocument();
  expect(screen.getByText("composant fantome : broche 18 utilisée deux fois")).toBeInTheDocument();
});

test("supprimer un composant utilisé est refusé en listant les usages", async () => {
  respond = ({ method }) =>
    method === "DELETE"
      ? rest(409, { message: "relais utilisé : programme « Scène » (bloc a) ; déclencheur `t1`", issues: [] })
      : undefined;
  const user = await openApp();
  await user.click(screen.getByLabelText("Orage"));
  await user.click(screen.getByRole("button", { name: "Supprimer" }));
  await user.click(screen.getByRole("button", { name: "Confirmer la suppression" }));
  expect(await screen.findByText(/Suppression impossible/)).toBeInTheDocument();
  expect(screen.getByText("programme « Scène » (bloc a)")).toBeInTheDocument();
  expect(screen.getByText("déclencheur `t1`")).toBeInTheDocument();
  expect(screen.getByRole("dialog")).toBeInTheDocument(); // rien n'est supprimé
});

test("la suppression demande une confirmation, puis retire le composant", async () => {
  respond = ({ method, path }) => {
    if (method === "DELETE" && path === "/api/components/relays/orage") {
      devices.relays = [];
      return new Response(null, { status: 204 });
    }
  };
  const user = await openApp();
  await user.click(screen.getByLabelText("Orage"));
  await user.click(screen.getByRole("button", { name: "Supprimer" }));
  expect(calls.some((c) => c.method === "DELETE")).toBe(false); // pas encore
  await user.click(screen.getByRole("button", { name: "Confirmer la suppression" }));
  await waitFor(() => expect(screen.queryByLabelText("Orage")).toBeNull());
  expect(calls.find((c) => c.method === "DELETE")!.search).toBe("?stop_runs=false");
});

test("des scénarios en cours : confirmation avant de les arrêter, puis nouvel essai", async () => {
  let attempts = 0;
  respond = ({ method, path, search }) => {
    if (method === "PUT" && path === "/api/components/relays/orage") {
      attempts += 1;
      if (search.includes("stop_runs=true")) return { component: { id: "orage" }, issues: [] };
      return rest(409, { message: "des scénarios tournent (scene) : relancer avec stop_runs=true pour confirmer", issues: [] });
    }
  };
  const user = await openApp();
  await user.click(screen.getByLabelText("Orage"));
  await user.click(screen.getByRole("button", { name: "Enregistrer" }));
  await user.click(await screen.findByRole("button", { name: "Arrêter les scénarios et continuer" }));
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  expect(attempts).toBe(2);
});

test("un bouton physique : l'appui reçu s'affiche", async () => {
  const user = await openApp();
  await user.click(screen.getByRole("tab", { name: /Boutons/ }));
  await user.click(screen.getByLabelText("Bouton principal"));
  await user.click(screen.getByRole("button", { name: "Écouter un appui" }));
  expect(screen.getByRole("button", { name: "Appuyez sur le bouton…" })).toBeDisabled();
  act(() => FakeWebSocket.emit({ type: "button_event", button_id: "autre", event: "short" }));
  expect(screen.queryByRole("status")).toBeNull(); // un autre bouton ne compte pas
  act(() => FakeWebSocket.emit({ type: "button_event", button_id: "bp", event: "long" }));
  expect(await screen.findByRole("status")).toHaveTextContent("Appui long reçu.");
});

test("Échap et Annuler ferment le formulaire sans rien enregistrer", async () => {
  const user = await openApp();
  await user.click(screen.getByRole("button", { name: "Ajouter un relais" }));
  await user.keyboard("{Escape}");
  expect(screen.queryByRole("dialog")).toBeNull();
  await user.click(screen.getByRole("button", { name: "Ajouter un relais" }));
  await user.click(screen.getByRole("button", { name: "Annuler" }));
  expect(screen.queryByRole("dialog")).toBeNull();
  expect(calls.some((c) => c.method === "POST")).toBe(false);
});


test("une lumière créée en ne cochant que « luminosité » n'annonce ni couleur ni transition", async () => {
  respond = ({ method, path }) =>
    method === "POST" && path === "/api/components/lights" ? Response.json({ component: { id: "guirlande" }, issues: [] }, { status: 201 }) : undefined;
  const user = await openApp();
  await user.click(screen.getByRole("tab", { name: /Lumières/ }));
  await user.click(screen.getByRole("button", { name: "Ajouter une lumière" }));
  await waitFor(() => expect(screen.getByRole("option", { name: "Lampe (light.lampe)" })).toBeInTheDocument());
  const dialog = screen.getByRole("dialog");
  await user.type(within(dialog).getByLabelText("Nom", { exact: true }), "Guirlande");
  await user.selectOptions(within(dialog).getByLabelText("Entité Home Assistant"), "light.lampe");
  await user.click(within(dialog).getByLabelText("Luminosité"));
  await user.click(within(dialog).getByRole("button", { name: "Enregistrer" }));
  await waitFor(() => expect(calls.some((c) => c.method === "POST" && c.path === "/api/components/lights")).toBe(true));
  expect(calls.find((c) => c.method === "POST" && c.path === "/api/components/lights")!.body).toMatchObject({
    entity_id: "light.lampe",
    supports_brightness: true,
    supports_color: false,
    supports_transition: false,
  });
});
