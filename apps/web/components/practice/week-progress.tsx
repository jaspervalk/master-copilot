"use client";

import Link from "next/link";

import { WorkedExampleBlock } from "@/components/practice/worked-example";
import { Badge } from "@/components/ui/badge";
import type { StudyWeek } from "@/lib/types";


/**
 * Per week: hoeveel stof, hoeveel je ervan kent, en wat er ontbreekt.
 *
 * De balk toont beheersing, niet hoeveel je hebt gelezen. Dat is een bewuste
 * keuze: een teller op gelezen bladzijden of bestede tijd voedt precies het
 * gevoel dat het onderzoek als dé valkuil aanwijst — het lijkt te lukken omdat
 * het bekend voelt. Alleen wat je drie keer op afstand goed hebt gehad telt.
 */
export function WeekProgress({
  weeks,
  courseSlug,
  onPractise,
  onFill,
  onExamples,
  busyWeek,
}: {
  weeks: StudyWeek[];
  courseSlug: string;
  onPractise: (week: number) => void;
  onFill: (week: number) => void;
  onExamples: (week: number) => void;
  busyWeek: number | null;
}) {
  if (weeks.length === 0) return null;

  return (
    <section className="mt-8">
      <h2 className="font-display text-base font-semibold text-ink-900">Per week</h2>
      <ul className="mt-3 space-y-2">
        {weeks.map((week) => (
          <li key={week.week} className="rounded-lg border border-ink-100 bg-card p-4">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <h3 className="font-display text-sm font-semibold text-ink-900">
                Week {week.week}
                {week.lectures.length > 0 && (
                  <span className="ml-2 text-xs font-normal text-ink-400">
                    college {week.lectures.join(" en ")}
                  </span>
                )}
              </h3>
              <div className="flex items-center gap-2">
                {week.due > 0 && <Badge tone="accent">{week.due} aan de beurt</Badge>}
                {week.cards === 0 && week.material_chunks > 0 && <Badge>geen kaarten</Badge>}
                {week.material_chunks === 0 && <Badge>geen stof</Badge>}
              </div>
            </div>

            {week.cards > 0 && (
              <>
                <Balk week={week} />
                <p className="mt-1 text-xs text-ink-500">
                  {week.mastered} van de {week.cards} beheerst
                  {week.weak > 0 && <span className="text-accent-600"> · {week.weak} zwak</span>}
                  {week.new > 0 && <span> · {week.new} nog nooit gedaan</span>}
                </p>
              </>
            )}

            {week.examples.map((example) => (
              <WorkedExampleBlock
                key={example.id}
                example={example}
                mastered={week.cards > 0 && week.mastered / week.cards >= 0.7}
              />
            ))}

            {week.topics_without_cards.length > 0 && (
              <p className="mt-2 text-xs text-ink-500">
                Nog geen kaarten over:{" "}
                <span className="text-ink-700">{week.topics_without_cards.join(", ")}</span>
              </p>
            )}

            <div className="mt-3 flex flex-wrap items-center gap-3 text-xs">
              {week.cards > 0 && (
                <button
                  type="button"
                  onClick={() => onPractise(week.week)}
                  className="text-primary-600 underline underline-offset-2 hover:text-primary-500"
                >
                  Oefen deze week
                </button>
              )}
              {week.topics_without_cards.length > 0 && week.material_chunks > 0 && (
                <button
                  type="button"
                  onClick={() => onFill(week.week)}
                  disabled={busyWeek !== null}
                  className="text-primary-600 underline underline-offset-2 hover:text-primary-500 disabled:text-ink-300 disabled:no-underline"
                >
                  {busyWeek === week.week ? "Kaarten maken…" : "Maak de ontbrekende kaarten"}
                </button>
              )}
              {week.material_chunks > 0 && week.examples.length < week.topics.length && (
                <button
                  type="button"
                  onClick={() => onExamples(week.week)}
                  disabled={busyWeek !== null}
                  className="text-primary-600 underline underline-offset-2 hover:text-primary-500 disabled:text-ink-300 disabled:no-underline"
                >
                  {busyWeek === week.week ? "Bezig…" : "Maak uitgewerkte voorbeelden"}
                </button>
              )}
              <Link
                href={`/weken?course=${courseSlug}&week=${week.week}`}
                className="text-ink-500 underline underline-offset-2 hover:text-ink-800"
              >
                {week.has_summary ? (week.summary_stale ? "Weekkaart (verouderd)" : "Weekkaart") : "Nog geen weekkaart"}
              </Link>
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}


function Balk({ week }: { week: StudyWeek }) {
  const deel = (aantal: number) => (week.cards > 0 ? (aantal / week.cards) * 100 : 0);
  return (
    <div className="mt-2 flex h-1.5 w-full overflow-hidden rounded-full bg-ink-100">
      <span className="bg-primary-500" style={{ width: `${deel(week.mastered)}%` }} />
      <span className="bg-primary-200" style={{ width: `${deel(week.learning)}%` }} />
      <span className="bg-accent-400" style={{ width: `${deel(week.weak)}%` }} />
    </div>
  );
}
