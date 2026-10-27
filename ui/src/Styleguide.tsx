import { Button, Card, Field, Pill, Progress } from "./components/ui";

/** Catalogue des composants de base (ouvert par `#styleguide`) : sert de contrôle visuel. */
export function Styleguide() {
  return (
    <main style={{ padding: 28, display: "grid", gap: 24, maxWidth: 960 }}>
      <h1>Composants de base</h1>
      <section style={{ display: "flex", gap: 10, flexWrap: "wrap" }} aria-label="Pastilles">
        <Pill tone="ok">Moteur connecté</Pill>
        <Pill tone="ok">Home Assistant connecté</Pill>
        <Pill tone="warn">Home Assistant lent</Pill>
        <Pill tone="error">Moteur déconnecté</Pill>
        <Pill emphasis>2 scénarios en cours</Pill>
      </section>
      <section style={{ display: "flex", gap: 12, flexWrap: "wrap" }} aria-label="Boutons">
        <Button variant="primary">Lancer</Button>
        <Button>Annuler</Button>
        <Button variant="outline-danger">Arrêter</Button>
        <Button variant="danger">STOP</Button>
        <Button variant="ghost">Plus tard</Button>
        <Button disabled>Indisponible</Button>
        <Button variant="primary" large>
          Lancer (spectacle)
        </Button>
      </section>
      <section style={{ display: "flex", gap: 16 }} aria-label="Tuiles">
        <Card active>
          <div style={{ display: "grid", gap: 12 }}>
            <strong>Scénario principal</strong>
            <Progress ratio={0.38} label="Scénario principal" />
            <span style={{ color: "var(--color-text-muted)" }}>00:34 / 01:30</span>
          </div>
        </Card>
        <Card>
          <div style={{ display: "grid", gap: 12 }}>
            <strong>Ambiance du soir</strong>
            <Progress label="Ambiance du soir" />
            <span style={{ color: "var(--color-text-muted)" }}>Sans limite de durée.</span>
          </div>
        </Card>
      </section>
      <section style={{ display: "grid", gap: 16, maxWidth: 380 }} aria-label="Formulaire">
        <Field label="Nom" defaultValue="Fantôme" />
        <Field label="Broche" hint="GPIO 2 à 27" defaultValue="18" />
        <Field label="Broche en double" defaultValue="18" error="Déjà utilisée par Squelette" />
      </section>
    </main>
  );
}
