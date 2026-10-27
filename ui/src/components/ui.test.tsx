import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import { Button, Card, Field, Pill, Progress } from "./ui";

test("un bouton est de type button par défaut et applique sa variante", async () => {
  const onClick = vi.fn();
  render(
    <Button variant="danger" onClick={onClick}>
      STOP
    </Button>,
  );
  const button = screen.getByRole("button", { name: "STOP" });
  expect(button).toHaveAttribute("type", "button");
  expect(button).toHaveClass("btn", "btn--danger");
  await userEvent.click(button);
  expect(onClick).toHaveBeenCalledOnce();
});

test("un bouton désactivé ne réagit pas", async () => {
  const onClick = vi.fn();
  render(
    <Button disabled onClick={onClick}>
      Lancer
    </Button>,
  );
  await userEvent.click(screen.getByRole("button"));
  expect(onClick).not.toHaveBeenCalled();
});

test("la pastille dit son état en texte, le point est décoratif", () => {
  const { container } = render(<Pill tone="ok">Moteur connecté</Pill>);
  expect(screen.getByText("Moteur connecté")).toBeInTheDocument();
  expect(container.querySelector(".dot")).toHaveAttribute("aria-hidden", "true");
});

test("un champ relie son libellé, son aide et son erreur", () => {
  render(<Field label="Broche" hint="GPIO 2 à 27" error="Déjà utilisée" />);
  const input = screen.getByLabelText("Broche");
  expect(input).toHaveAttribute("aria-invalid", "true");
  expect(input).toHaveAccessibleDescription("GPIO 2 à 27 Déjà utilisée");
  expect(screen.getByRole("alert")).toHaveTextContent("Déjà utilisée");
});

test("un champ sans erreur n'est pas marqué invalide", () => {
  render(<Field label="Nom" />);
  expect(screen.getByLabelText("Nom")).not.toHaveAttribute("aria-invalid");
});

test("une carte cliquable est un vrai bouton", async () => {
  const onClick = vi.fn();
  render(
    <Card onClick={onClick} label="Fantôme">
      contenu
    </Card>,
  );
  await userEvent.click(screen.getByRole("button", { name: "Fantôme" }));
  expect(onClick).toHaveBeenCalledOnce();
});

test("la progression est bornée et accessible ; sans ratio, c'est « en continu »", () => {
  const { rerender } = render(<Progress ratio={1.7} label="Scénario principal" />);
  expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "100");
  rerender(<Progress ratio={0.38} label="Scénario principal" />);
  expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "38");
  rerender(<Progress label="Ambiance" />);
  expect(screen.getByRole("img", { name: "Ambiance : en continu" })).toBeInTheDocument();
});
