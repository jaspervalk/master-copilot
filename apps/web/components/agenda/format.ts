/** Wat een agendarij aan tekst nodig heeft. Stond gekopieerd in deadline-row
 * en exam-cards. */
import { formatDateTime, formatDay } from "@/lib/dates";
import { KIND_LABELS, type AgendaItem } from "@/lib/types";


export function points(value: number): string {
  return Number.isInteger(value) ? String(value) : value.toFixed(1).replace(".", ",");
}

export function scoreLabel(item: AgendaItem): string | null {
  if (item.score !== null && item.points_possible) return `${points(item.score)} van ${points(item.points_possible)} punten`;
  if (item.score !== null) return `${points(item.score)} punten`;
  if (item.grade) return `cijfer ${item.grade}`;
  if (item.points_possible) return `${points(item.points_possible)} punten`;
  return null;
}

/** De regels die niet in de rij zelf passen. Ze verdwijnen niet, ze gaan
 * achter "meer": een rij met vijf stukjes tekst naast elkaar leest niemand. */
export function detailLines(item: AgendaItem): string[] {
  const lines = [scoreLabel(item), KIND_LABELS[item.kind]];
  if (item.kind === "quiz" && item.quiz?.answers_at && item.status === "graded") {
    lines.push(`antwoorden zichtbaar sinds ${formatDay(item.quiz.answers_at)}`);
  }
  if (item.unlock_at && item.status === "locked") lines.push(`opent ${formatDateTime(item.unlock_at)}`);
  if (item.lock_at && item.lock_at !== item.deadline_at) lines.push(`sluit ${formatDateTime(item.lock_at)}`);
  if (item.yaml && !item.yaml.same_day) lines.push(`course.yml zegt ${formatDay(item.yaml.due_date)}`);
  return lines.filter((line): line is string => Boolean(line));
}
