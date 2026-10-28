"use client";

import Link from "next/link";

import { points } from "@/components/agenda/format";
import { formatDay } from "@/lib/dates";
import type { AgendaCourse, AgendaExam } from "@/lib/types";


function countdown(exam: AgendaExam): { number: string; label: string } {
  if (exam.days_left === null) return { number: "?", label: `${exam.name}, datum onbekend` };
  if (exam.days_left === 0) return { number: "0", label: `${exam.name} is vandaag` };
  if (exam.days_left < 0) return { number: String(-exam.days_left), label: `dagen sinds ${exam.name.toLowerCase()}` };
  return { number: String(exam.days_left), label: `dagen tot ${exam.name.toLowerCase()}` };
}


/** Per vak de aftelling naar het tentamen, en wat de copilot ervoor heeft:
 * de (oefen)tentamens met je laatste score, de herhaalronde, de weken
 * zonder samenvatting. Het getal is het enige grote ding op de pagina. */
export function ExamCards({ courses }: { courses: AgendaCourse[] }) {
  // Eén kaart per vak, niet per tentamen: FDS heeft een tentamen én een
  // herkansing, en die kregen allebei de volledige lijst met oefententamens,
  // herhaalronde en weekkaarten eronder. Dezelfde acht regels twee keer.
  const entries = courses
    .filter((course) => !course.hidden)
    .map((course) => ({
      course,
      // Een tentamen van weken geleden hoeft niet meer af te tellen.
      exams: course.exams.filter((exam) => exam.days_left === null || exam.days_left >= -7),
    }))
    .filter((entry) => entry.exams.length > 0);
  if (entries.length === 0) return null;

  return (
    <section className="mt-8">
      <h2 className="font-display text-base font-semibold text-ink-900">Tentamens</h2>
      <div className="mt-3 grid gap-4 md:grid-cols-2">
        {entries.map(({ course, exams }) => {
          const slug = course.course_slug;
          const copilot = course.copilot;
          const [first, ...rest] = exams;
          const shown = countdown(first);
          return (
            <article key={course.canvas_id ?? slug ?? course.name} className="rounded-lg border border-ink-100 bg-card p-5">
              <p className="text-sm text-ink-500">{course.name}</p>
              <div className="mt-1 flex items-baseline gap-3">
                <span className="font-display text-5xl font-semibold tabular-nums text-ink-900">{shown.number}</span>
                <span className="text-sm text-ink-600">
                  {shown.label}
                  {first.date && <span className="text-ink-400">, {formatDay(first.date)}</span>}
                </span>
              </div>
              {first.source === "yaml" && (
                <p className="mt-1 text-[11px] text-ink-400">Datum uit course.yml; Canvas kent dit tentamen niet.</p>
              )}
              {/* De herkansing hoort erbij, maar hoeft geen eigen kaart. */}
              {rest.map((exam) => (
                <p key={exam.name} className="mt-1 text-xs text-ink-500">
                  {exam.name}
                  {exam.date && <span className="text-ink-400">, {formatDay(exam.date)}</span>}
                  {exam.days_left !== null && <span className="text-ink-400"> — over {exam.days_left} dagen</span>}
                </p>
              ))}
              {slug && (
                <Link
                  href={`/tentamen?course=${encodeURIComponent(slug)}`}
                  className="mt-3 inline-block text-sm font-medium text-primary-600 underline underline-offset-2 hover:text-primary-500"
                >
                  Voorbereiding: opbouw, je punten, voorspelde vragen →
                </Link>
              )}
              {copilot && slug && (
                <ul className="mt-4 space-y-1.5 text-sm">
                  {copilot.exam_sets.map((set) => (
                    <li key={set.origin} className="flex items-baseline justify-between gap-3">
                      <Link
                        href={`/oefenen?course=${encodeURIComponent(slug)}&exam=${encodeURIComponent(set.origin)}`}
                        className="text-primary-600 underline underline-offset-2 hover:text-primary-500"
                      >
                        {set.title}
                      </Link>
                      <span className="shrink-0 text-xs tabular-nums text-ink-500">
                        {set.answered > 0
                          ? `${points(set.last_score)} van ${points(set.answered_points)} punten`
                          : `${set.question_count} vragen, nog niet gemaakt`}
                      </span>
                    </li>
                  ))}
                  <li className="flex items-baseline justify-between gap-3">
                    <Link
                      href={`/oefenen?course=${encodeURIComponent(slug)}&review=1`}
                      className="text-primary-600 underline underline-offset-2 hover:text-primary-500"
                    >
                      Herhalen
                    </Link>
                    <span className="shrink-0 text-xs tabular-nums text-ink-500">
                      {copilot.due_count === 0 ? "niets aan de beurt" : `${copilot.due_count} kaarten aan de beurt`}
                    </span>
                  </li>
                  {copilot.stale_summaries.length > 0 && (
                    <li className="flex flex-wrap items-baseline gap-x-2 text-xs text-ink-500">
                      <span>Weekkaart verouderd door nieuwe stof:</span>
                      {copilot.stale_summaries.map((week) => (
                        <Link
                          key={week}
                          href={`/weken?course=${encodeURIComponent(slug)}&week=${week}`}
                          className="text-accent-600 underline underline-offset-2 hover:text-accent-500"
                        >
                          week {week}
                        </Link>
                      ))}
                    </li>
                  )}
                  {copilot.weeks_without_summary.length > 0 && (
                    <li className="flex flex-wrap items-baseline gap-x-2 text-xs text-ink-500">
                      <span>Nog geen weekkaart van</span>
                      {copilot.weeks_without_summary.map((week) => (
                        <Link
                          key={week}
                          href={`/weken?course=${encodeURIComponent(slug)}&week=${week}`}
                          className="text-primary-600 underline underline-offset-2 hover:text-primary-500"
                        >
                          week {week}
                        </Link>
                      ))}
                    </li>
                  )}
                </ul>
              )}
            </article>
          );
        })}
      </div>
    </section>
  );
}
