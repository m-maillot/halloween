import { expect, test } from "vitest";
import { describe as say, parseCron, scheduleProblem, toCron, type Schedule } from "./cron";

test("l'exemple de la spec : tous les 31 octobre à 18:00", () => {
  const schedule: Schedule = { mode: "date", day: 31, month: 10, hour: 18, minute: 0 };
  expect(toCron(schedule)).toBe("0 18 31 10 *"); // le cron de l'annexe de la spec 1
  expect(say(schedule)).toBe("tous les 31 octobre à 18:00");
});

test.each<[Schedule, string, string]>([
  [{ mode: "daily", hour: 9, minute: 5 }, "5 9 * * *", "tous les jours à 09:05"],
  [{ mode: "weekdays", days: [1], hour: 18, minute: 30 }, "30 18 * * mon", "tous les lundis à 18:30"],
  [{ mode: "weekdays", days: [5, 3, 1], hour: 18, minute: 0 }, "0 18 * * mon,wed,fri", "le lundi, mercredi et vendredi à 18:00"],
  [{ mode: "weekdays", days: [1, 2, 3, 4, 5], hour: 7, minute: 0 }, "0 7 * * mon,tue,wed,thu,fri", "du lundi au vendredi à 07:00"],
  [{ mode: "weekdays", days: [6, 7], hour: 20, minute: 0 }, "0 20 * * sat,sun", "le samedi et le dimanche à 20:00"],
  [{ mode: "weekdays", days: [1, 2, 3, 4, 5, 6, 7], hour: 1, minute: 0 }, "0 1 * * mon,tue,wed,thu,fri,sat,sun", "tous les jours à 01:00"],
  [{ mode: "date", day: 1, month: 11, hour: 0, minute: 0 }, "0 0 1 11 *", "tous les 1er novembre à 00:00"],
])("%o s'écrit « %s » et se dit « %s »", (schedule, cron, text) => {
  expect(toCron(schedule)).toBe(cron);
  expect(say(schedule)).toBe(text);
});

test("un cron du constructeur se relit identique (aller-retour)", () => {
  const schedules: Schedule[] = [
    { mode: "daily", hour: 18, minute: 0 },
    { mode: "weekdays", days: [2, 4], hour: 21, minute: 15 },
    { mode: "date", day: 31, month: 10, hour: 18, minute: 0 },
  ];
  for (const schedule of schedules) expect(parseCron(toCron(schedule))).toEqual(schedule);
});

test("les chiffres de jours (0 ou 7 = dimanche) sont compris", () => {
  expect(parseCron("0 18 * * 0,6")).toEqual({ mode: "weekdays", days: [6, 7], hour: 18, minute: 0 });
  expect(parseCron("0 18 * * 7")).toEqual({ mode: "weekdays", days: [7], hour: 18, minute: 0 });
});

test.each(["*/5 * * * *", "0 18 31 10 mon", "0 8-20 * * *", "@daily", "0 18 * *", "0 18 * * funday", "61 18 * * *", "0 25 * * *"])(
  "« %s » reste une expression avancée, conservée telle quelle",
  (cron) => {
    expect(parseCron(cron)).toEqual({ mode: "advanced", cron });
    expect(toCron({ mode: "advanced", cron })).toBe(cron);
  },
);

test("les saisies impossibles sont dites en clair", () => {
  expect(scheduleProblem({ mode: "date", day: 31, month: 4, hour: 1, minute: 0 })).toBe("Le 31 avril n'existe pas.");
  expect(scheduleProblem({ mode: "date", day: 29, month: 2, hour: 1, minute: 0 })).toBeNull(); // années bissextiles
  expect(scheduleProblem({ mode: "date", day: 30, month: 2, hour: 1, minute: 0 })).toBe("Le 30 février n'existe pas.");
  expect(scheduleProblem({ mode: "weekdays", days: [], hour: 1, minute: 0 })).toBe("Choisissez au moins un jour.");
  expect(scheduleProblem({ mode: "daily", hour: 24, minute: 0 })).toMatch(/entre 0 et 23/);
  expect(scheduleProblem({ mode: "daily", hour: 1, minute: 60 })).toMatch(/entre 0 et 59/);
  expect(scheduleProblem({ mode: "advanced", cron: "0 18 *" })).toMatch(/5 champs/);
  expect(scheduleProblem({ mode: "daily", hour: 18, minute: 0 })).toBeNull();
});
