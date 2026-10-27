// Constructeur de planning : un cron à 5 champs que l'on sait écrire, relire et dire en français.
// Tout ce que le constructeur ne sait pas relire devient une « expression avancée » laissée telle quelle.

export type Time = { hour: number; minute: number };

export type Schedule =
  | ({ mode: "daily" } & Time)
  | ({ mode: "weekdays"; days: number[] } & Time) // 1 = lundi … 7 = dimanche
  | ({ mode: "date"; day: number; month: number } & Time)
  | { mode: "advanced"; cron: string };

export const DAY_LABELS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"];
export const MONTH_LABELS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre"];

const DAY_NAMES = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]; // index 0 = lundi
const DAYS_IN_MONTH = [31, 29, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]; // février : 29, l'année n'est pas connue

const pad = (n: number) => String(n).padStart(2, "0");

export function toCron(schedule: Schedule): string {
  if (schedule.mode === "advanced") return schedule.cron.trim();
  const { minute, hour } = schedule;
  switch (schedule.mode) {
    case "daily":
      return `${minute} ${hour} * * *`;
    case "weekdays": {
      const days = [...new Set(schedule.days)].sort((a, b) => a - b).map((d) => DAY_NAMES[d - 1]);
      return `${minute} ${hour} * * ${days.join(",")}`;
    }
    case "date":
      return `${minute} ${hour} ${schedule.day} ${schedule.month} *`;
  }
}

const INT = /^\d+$/;

function dayNumber(token: string): number | null {
  const named = DAY_NAMES.indexOf(token.toLowerCase());
  if (named >= 0) return named + 1;
  if (INT.test(token)) {
    const n = Number(token);
    if (n >= 0 && n <= 7) return n === 0 ? 7 : n; // 0 et 7 : dimanche
  }
  return null;
}

/** Relit un cron produit par le constructeur ; tout le reste est une expression avancée. */
export function parseCron(cron: string): Schedule {
  const advanced: Schedule = { mode: "advanced", cron };
  const fields = cron.trim().split(/\s+/);
  if (fields.length !== 5) return advanced;
  const [m, h, dom, mon, dow] = fields;
  if (!INT.test(m) || !INT.test(h) || Number(m) > 59 || Number(h) > 23) return advanced;
  const time = { minute: Number(m), hour: Number(h) };
  if (dom === "*" && mon === "*" && dow === "*") return { mode: "daily", ...time };
  if (dom === "*" && mon === "*" && dow !== "*") {
    const days = dow.split(",").map(dayNumber);
    if (days.some((d) => d === null)) return advanced;
    return { mode: "weekdays", days: [...new Set(days as number[])].sort((a, b) => a - b), ...time };
  }
  if (INT.test(dom) && INT.test(mon) && dow === "*") {
    const day = Number(dom);
    const month = Number(mon);
    if (day >= 1 && day <= 31 && month >= 1 && month <= 12) return { mode: "date", day, month, ...time };
  }
  return advanced;
}

/** Problème de saisie du constructeur, en clair ; `null` si le planning est utilisable. */
export function scheduleProblem(schedule: Schedule): string | null {
  if (schedule.mode === "advanced") return schedule.cron.trim().split(/\s+/).length === 5 ? null : "Une expression cron comporte 5 champs (minute heure jour mois jour-de-semaine).";
  if (!Number.isInteger(schedule.hour) || schedule.hour < 0 || schedule.hour > 23) return "L'heure doit être comprise entre 0 et 23.";
  if (!Number.isInteger(schedule.minute) || schedule.minute < 0 || schedule.minute > 59) return "Les minutes doivent être comprises entre 0 et 59.";
  if (schedule.mode === "weekdays" && schedule.days.length === 0) return "Choisissez au moins un jour.";
  if (schedule.mode === "date") {
    if (!Number.isInteger(schedule.month) || schedule.month < 1 || schedule.month > 12) return "Choisissez un mois.";
    if (!Number.isInteger(schedule.day) || schedule.day < 1 || schedule.day > DAYS_IN_MONTH[schedule.month - 1]) {
      return `Le ${schedule.day} ${MONTH_LABELS[schedule.month - 1]} n'existe pas.`;
    }
  }
  return null;
}

function list(items: string[]): string {
  return items.length < 2 ? items.join("") : `${items.slice(0, -1).join(", ")} et ${items.at(-1)}`;
}

/** Prévisualisation en clair : « tous les 31 octobre à 18:00 ». */
export function describe(schedule: Schedule): string {
  if (schedule.mode === "advanced") return `expression avancée « ${schedule.cron.trim()} »`;
  const at = `à ${pad(schedule.hour)}:${pad(schedule.minute)}`;
  switch (schedule.mode) {
    case "daily":
      return `tous les jours ${at}`;
    case "date":
      return `tous les ${schedule.day === 1 ? "1er" : schedule.day} ${MONTH_LABELS[schedule.month - 1]} ${at}`;
    case "weekdays": {
      const days = [...new Set(schedule.days)].sort((a, b) => a - b);
      if (days.length === 7) return `tous les jours ${at}`;
      if (days.length === 5 && days.join() === "1,2,3,4,5") return `du lundi au vendredi ${at}`;
      if (days.length === 2 && days.join() === "6,7") return `le samedi et le dimanche ${at}`;
      if (days.length === 1) return `tous les ${DAY_LABELS[days[0] - 1]}s ${at}`;
      return `le ${list(days.map((d) => DAY_LABELS[d - 1]))} ${at}`;
    }
  }
}
