"use client";

import { useEffect, useRef, useState } from "react";

import {
  ExamSets,
  Overview,
  Patterns,
  Predictions,
  Standings,
  Tactics,
} from "@/components/exam/exam-blocks";
import { ExamPlan } from "@/components/exam/exam-plan";
import { Rules } from "@/components/exam/exam-rules";
import { Banner } from "@/components/ui/banner";
import { fetchCourses, fetchExamPrep } from "@/lib/api";
import type { CourseSummary, ExamPrep } from "@/lib/types";
import { useInitialParams } from "@/lib/use-initial-params";


type Entry = { course: CourseSummary; prep: ExamPrep };


/**
 * Alles voor het tentamen van één vak, in de volgorde waarin je het nodig
 * hebt: wat er komt, waar je punten liggen, wat je kunt oefenen, en dan de
 * analyse — wat steeds terugkomt, wat we verwachten, en hoe je de punten haalt.
 *
 * Vakken zonder tentamen en zonder opbouw vallen weg, en het vak met het
 * eerstvolgende tentamen staat vooraan: dat is het vak waarvoor je hier komt.
 */
export function ExamConsole() {
  const [entries, setEntries] = useState<Entry[] | null>(null);
  const [courseSlug, setCourseSlug] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  // /tentamen?course=sso, vanuit de agenda. Eén keer.
  const initial = useInitialParams();
  const consumed = useRef(false);

  useEffect(() => {
    fetchCourses()
      .then(async (courses) => {
        const loaded = await Promise.all(
          courses.map(async (course) => ({ course, prep: await fetchExamPrep(course.slug) })),
        );
        const relevant = loaded
          .filter(({ prep }) => prep.exam !== null || prep.groups.length > 0 || prep.has_file)
          .sort((a, b) => (a.prep.exam?.days_left ?? 999) - (b.prep.exam?.days_left ?? 999));
        setEntries(relevant);
        if (!consumed.current) {
          consumed.current = true;
          const wanted = initial.get("course");
          const start = relevant.find((entry) => entry.course.slug === wanted) ?? relevant[0];
          if (start) setCourseSlug(start.course.slug);
        }
      })
      .catch((cause) => setError(cause instanceof Error ? cause.message : String(cause)));
  }, [initial]);

  const current = entries?.find((entry) => entry.course.slug === courseSlug) ?? null;

  return (
    <div className="mx-auto max-w-5xl px-4 py-6 sm:px-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="font-display text-lg font-semibold text-ink-900">Tentamen</h1>
          <p className="mt-0.5 text-sm text-ink-500">
            Wat er komt, waar je punten liggen, en hoe je ze haalt.
          </p>
        </div>
        {entries && entries.length > 1 && (
          <nav aria-label="Vak" className="flex gap-1 rounded-lg border border-ink-100 bg-card p-1">
            {entries.map(({ course, prep }) => {
              const active = course.slug === courseSlug;
              return (
                <button
                  key={course.slug}
                  type="button"
                  onClick={() => setCourseSlug(course.slug)}
                  aria-pressed={active}
                  className={`rounded-md px-3 py-1.5 text-sm transition ${
                    active ? "bg-primary-600 text-on-fill" : "text-ink-600 hover:bg-ink-50"
                  }`}
                >
                  {course.name}
                  {prep.exam && (
                    <span className={`ml-1.5 text-xs tabular-nums ${active ? "opacity-80" : "text-ink-400"}`}>
                      {prep.exam.days_left === 0 ? "vandaag" : `${prep.exam.days_left} d`}
                    </span>
                  )}
                </button>
              );
            })}
          </nav>
        )}
      </header>

      {error && (
        <div className="mt-4">
          <Banner tone="danger">{error}</Banner>
        </div>
      )}

      {entries === null && !error && <p className="mt-8 text-sm text-ink-500">Laden…</p>}
      {entries?.length === 0 && (
        <p className="mt-8 text-sm text-ink-500">Geen vak met een tentamen of een opbouw in exams/.</p>
      )}

      {current && <CoursePrep key={current.course.slug} prep={current.prep} />}
    </div>
  );
}


function CoursePrep({ prep }: { prep: ExamPrep }) {
  const titles = new Map(prep.groups.map((group) => [group.number, group.title]));
  return (
    <div className="mt-6 space-y-10">
      {/* Eerst wat je nog moet doen: daarvoor kom je hier, de rest is waar het naartoe wijst. */}
      {prep.plan.length > 0 && <ExamPlan prep={prep} />}
      <Overview prep={prep} />
      {prep.groups.length > 0 && <Standings prep={prep} />}
      {prep.exam_sets.length > 0 && <ExamSets prep={prep} />}
      {prep.rules.length > 0 && (
        <div id="herkennen" className="scroll-mt-20">
          <Rules rules={prep.rules} groups={prep.groups} />
        </div>
      )}
      {prep.patterns.length > 0 && <Patterns courseSlug={prep.course_slug} patterns={prep.patterns} titles={titles} />}
      {/* Ankers: stappen in het plan wijzen hierheen. */}
      {prep.predictions.length > 0 && (
        <div id="voorspelde-vragen" className="scroll-mt-20">
          <Predictions predictions={prep.predictions} groups={prep.groups} />
        </div>
      )}
      {prep.tactics.length > 0 && (
        <div id="tactieken" className="scroll-mt-20">
          <Tactics tactics={prep.tactics} />
        </div>
      )}
      {!prep.has_file && (
        <p className="text-sm text-ink-500">
          Er is nog geen analyse voor dit vak (exams/voorbereiding.yml): patronen, voorspelde vragen en tactieken
          ontbreken.
        </p>
      )}
      {prep.problems.length > 0 && (
        <Banner tone="warning">
          <p className="font-medium">Wat er aan de voorbereiding niet klopt</p>
          <ul className="mt-1 list-disc pl-5">
            {prep.problems.map((problem) => (
              <li key={problem}>{problem}</li>
            ))}
          </ul>
        </Banner>
      )}
    </div>
  );
}
