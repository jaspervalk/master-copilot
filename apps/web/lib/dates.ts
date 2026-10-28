/** Datums voor de agenda. Alles in Europe/Amsterdam en in het Nederlands;
 * de API levert UTC met een Z, en een dag zonder tijd als "JJJJ-MM-DD". */

const TZ = "Europe/Amsterdam";

const dayFormat = new Intl.DateTimeFormat("nl-NL", { timeZone: TZ, weekday: "short", day: "numeric", month: "short" });
const longDayFormat = new Intl.DateTimeFormat("nl-NL", { timeZone: TZ, weekday: "long", day: "numeric", month: "long" });
const timeFormat = new Intl.DateTimeFormat("nl-NL", { timeZone: TZ, hour: "2-digit", minute: "2-digit" });

/** "2026-10-21" als lokale dag om 12:00: `new Date("2026-10-21")` is UTC-
 * middernacht en valt in de winter op de dag ervoor. */
export function parseDay(value: string): Date {
  const [year, month, day] = value.split("-").map(Number);
  return new Date(year, month - 1, day, 12);
}

function toDate(value: string | Date): Date {
  if (value instanceof Date) return value;
  return value.length === 10 ? parseDay(value) : new Date(value);
}

/** "wo 21 okt" */
export function formatDay(value: string | Date): string {
  return dayFormat.format(toDate(value)).replace(".", "");
}

/** "ma 28 sep, 23:59" */
export function formatDateTime(iso: string): string {
  const date = new Date(iso);
  return `${formatDay(date)}, ${timeFormat.format(date)}`;
}

/** "donderdag 17 september" */
export function formatToday(now: Date = new Date()): string {
  return longDayFormat.format(now);
}

/** "over 11 dagen", "vandaag", "morgen", "3 dagen geleden" */
export function formatRelativeDays(days: number | null): string {
  if (days === null) return "";
  if (days === 0) return "vandaag";
  if (days === 1) return "morgen";
  if (days === -1) return "gisteren";
  if (days > 0) return `over ${days} dagen`;
  return `${-days} dagen geleden`;
}

/** "zojuist", "12 min geleden", "2 uur geleden", "gisteren", "3 dagen geleden" */
export function formatAgo(iso: string, now: Date = new Date()): string {
  const minutes = Math.round((now.getTime() - new Date(iso).getTime()) / 60_000);
  if (minutes < 1) return "zojuist";
  if (minutes < 60) return `${minutes} min geleden`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} uur geleden`;
  const days = Math.round(hours / 24);
  return days === 1 ? "gisteren" : `${days} dagen geleden`;
}

/** Vandaag als "JJJJ-MM-DD" in de lokale tijd, voor een datumveld. */
export function todayValue(now: Date = new Date()): string {
  const offset = now.getTimezoneOffset() * 60_000;
  return new Date(now.getTime() - offset).toISOString().slice(0, 10);
}
