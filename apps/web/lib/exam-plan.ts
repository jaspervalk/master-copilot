/** Het blok "Tot het tentamen": welke stappen af zijn en hoe ze over de dagen
 * vallen. Los van de component, zodat het met node --test na te lopen is. */

export type PlanStepLike = { id: string; day: string; minutes: number | null; exam: string | null };
export type ExamSetLike = { origin: string; question_count: number; answered: number };

/** Voortgang van een stap die een oefententamen is; null voor de andere. */
export function stepProgress(step: PlanStepLike, sets: ExamSetLike[]): { answered: number; total: number } | null {
  if (!step.exam) return null;
  const set = sets.find((item) => item.origin === step.exam);
  return set ? { answered: set.answered, total: set.question_count } : null;
}

/** Af: een oefententamen als elke vraag een poging heeft, de rest met je eigen
 * vinkje. Een tentamenstap telt nooit op een vinkje: hij zegt zelf hoe ver je bent. */
export function stepDone(step: PlanStepLike, sets: ExamSetLike[], ticked: ReadonlySet<string>): boolean {
  const progress = stepProgress(step, sets);
  if (step.exam) return progress !== null && progress.total > 0 && progress.answered >= progress.total;
  return ticked.has(step.id);
}

/** De stappen per dag, in de volgorde van het bestand. */
export function planDays<T extends PlanStepLike>(steps: T[]): { day: string; steps: T[] }[] {
  const days: { day: string; steps: T[] }[] = [];
  for (const step of steps) {
    const last = days[days.length - 1];
    if (last && last.day === step.day) last.steps.push(step);
    else days.push({ day: step.day, steps: [step] });
  }
  return days;
}

/** Hoeveel minuten er nog openstaan. */
export function minutesLeft(steps: PlanStepLike[], sets: ExamSetLike[], ticked: ReadonlySet<string>): number {
  return steps.filter((step) => !stepDone(step, sets, ticked)).reduce((sum, step) => sum + (step.minutes ?? 0), 0);
}

/** Wat er boven een (oefen)tentamen staat als je het opent. Er stond altijd "twee
 * uur", ook boven een set van 27 punten; wie op tijd oefent, trainde dan met vier
 * keer te veel tijd. Nu het tempo van het echte tentamen (minuten per punt),
 * afgerond op vijf minuten. */
export function examSetNotice(count: number, points: number, minutesPerPoint: number | null): string {
  const shown = String(Math.round(points * 100) / 100).replace(".", ",");
  const base = `${count} vragen, ${shown} punten`;
  if (!minutesPerPoint) return `${base}.`;
  const minutes = Math.max(5, Math.round((points * minutesPerPoint) / 5) * 5);
  return `${base}: in het tempo van het tentamen ongeveer ${minutes} minuten.`;
}
