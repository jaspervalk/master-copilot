"use client";

import { useEffect, useState } from "react";

import { LinkChips } from "@/components/ui/link-chips";
import { minutesLeft, planDays, stepDone, stepProgress } from "@/lib/exam-plan";
import type { ExamPrep, PrepPlanStep } from "@/lib/types";


function duration(minutes: number): string {
  if (minutes < 60) return `${minutes} min`;
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  return rest === 0 ? `${hours} u` : `${hours} u ${rest} min`;
}

// Je vinkjes zijn een gemak voor jou op dit apparaat, geen administratie: wat
// echt telt (je pogingen) staat in de database, en een oefententamen vinkt
// zichzelf af. Zonder opslag (privévenster) werkt het blok gewoon, alleen
// zonder geheugen.
function storageKey(courseSlug: string) {
  return `tentamen-plan:${courseSlug}`;
}

function readTicked(courseSlug: string): Set<string> {
  try {
    const raw = window.localStorage.getItem(storageKey(courseSlug));
    return new Set(raw ? (JSON.parse(raw) as string[]) : []);
  } catch {
    return new Set();
  }
}

function writeTicked(courseSlug: string, ticked: Set<string>) {
  try {
    window.localStorage.setItem(storageKey(courseSlug), JSON.stringify([...ticked]));
  } catch {
    // Geen opslag: het vinkje geldt dan alleen tot je de pagina verlaat.
  }
}


/** Wat je nog doet tot het tentamen, per dag en in volgorde, met bij elke stap
 * een knop naar de stof. Bovenaan de pagina, want dit is waarvoor je hier komt;
 * de rest van de pagina is waar de stappen naartoe wijzen. */
export function ExamPlan({ prep }: { prep: ExamPrep }) {
  const [ticked, setTicked] = useState<Set<string>>(new Set());
  // Na het laden lezen, niet tijdens de render: de server kent je vinkjes niet.
  useEffect(() => setTicked(readTicked(prep.course_slug)), [prep.course_slug]);

  function toggle(step: PrepPlanStep) {
    setTicked((current) => {
      const next = new Set(current);
      if (next.has(step.id)) next.delete(step.id);
      else next.add(step.id);
      writeTicked(prep.course_slug, next);
      return next;
    });
  }

  const left = minutesLeft(prep.plan, prep.exam_sets, ticked);
  const done = prep.plan.filter((step) => stepDone(step, prep.exam_sets, ticked)).length;
  let number = 0;

  return (
    <section>
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <h2 className="font-display text-base font-semibold text-ink-900">Tot het tentamen</h2>
        <p className="text-sm tabular-nums text-ink-500">
          {done} van {prep.plan.length} gedaan
          {left > 0 && <span> · nog {duration(left)}</span>}
        </p>
      </div>
      <p className="mt-0.5 max-w-3xl text-sm text-ink-500">
        In deze volgorde. Vink af wat je gedaan hebt; een oefententamen vinkt zichzelf af zodra elke vraag een poging
        heeft.
      </p>

      <div className="mt-3 space-y-5">
        {planDays(prep.plan).map(({ day, steps }) => (
          <div key={day || "plan"}>
            {day && (
              <h3 className="flex items-baseline gap-2 text-xs font-medium uppercase tracking-wide text-ink-500">
                {day}
                <span className="font-normal normal-case tracking-normal text-ink-400">
                  {duration(steps.reduce((sum, step) => sum + (step.minutes ?? 0), 0))}
                </span>
              </h3>
            )}
            <ol className="mt-2 divide-y divide-ink-100 overflow-hidden rounded-lg border border-ink-100 bg-card">
              {steps.map((step) => {
                number += 1;
                const isDone = stepDone(step, prep.exam_sets, ticked);
                const progress = stepProgress(step, prep.exam_sets);
                return (
                  <li key={step.id} className="flex gap-3 px-4 py-3">
                    <div className="pt-0.5">
                      {step.exam ? (
                        <span
                          aria-label={isDone ? "af" : "nog niet af"}
                          className={`flex h-5 w-5 items-center justify-center rounded-full border text-[11px] ${
                            isDone ? "border-primary-600 bg-primary-600 text-on-fill" : "border-ink-200 text-ink-400"
                          }`}
                        >
                          {isDone ? "✓" : number}
                        </span>
                      ) : (
                        <input
                          type="checkbox"
                          checked={isDone}
                          onChange={() => toggle(step)}
                          aria-label={`${step.title} afvinken`}
                          className="h-5 w-5 cursor-pointer accent-primary-600"
                        />
                      )}
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-baseline justify-between gap-x-3">
                        <p className={`text-sm font-medium ${isDone ? "text-ink-400 line-through" : "text-ink-900"}`}>
                          {step.title}
                        </p>
                        {step.minutes !== null && (
                          <span className="text-xs tabular-nums text-ink-400">{duration(step.minutes)}</span>
                        )}
                      </div>
                      {step.detail && !isDone && <p className="mt-1 text-sm text-ink-600">{step.detail}</p>}
                      {progress && (
                        <div className="mt-1.5 flex items-center gap-2">
                          <div className="h-1.5 w-40 rounded-full bg-ink-100" aria-hidden>
                            <div
                              className="h-full rounded-full bg-primary-600"
                              style={{ width: `${progress.total ? (progress.answered / progress.total) * 100 : 0}%` }}
                            />
                          </div>
                          <span className="text-xs tabular-nums text-ink-500">
                            {progress.answered} van {progress.total} vragen gemaakt
                          </span>
                        </div>
                      )}
                      {!isDone && <LinkChips links={step.links} className="mt-2" />}
                      {!isDone && step.slides.length > 0 && (
                        <div className="mt-2 flex flex-wrap items-baseline gap-x-2 gap-y-1">
                          <span className="text-[11px] font-medium uppercase tracking-wide text-ink-400">Slides</span>
                          <LinkChips links={step.slides} className="" />
                        </div>
                      )}
                    </div>
                  </li>
                );
              })}
            </ol>
          </div>
        ))}
      </div>
    </section>
  );
}
