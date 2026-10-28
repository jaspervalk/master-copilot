"use client";

import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { WeekSummaryView } from "@/components/weeks/week-summary-view";
import {
  buildWeekSummary,
  fetchCourses,
  fetchWeekExamples,
  fetchWeekSummary,
  fetchWeeks,
} from "@/lib/api";
import type { CourseSummary, WeekRead, WeekSummary, WorkedExample } from "@/lib/types";
import { useInitialParams } from "@/lib/use-initial-params";


export function WeekConsole() {
  const [courses, setCourses] = useState<CourseSummary[]>([]);
  const [courseSlug, setCourseSlug] = useState<string | null>(null);
  const [weeks, setWeeks] = useState<WeekRead[]>([]);
  const [week, setWeek] = useState<WeekRead | null>(null);
  const [summary, setSummary] = useState<WeekSummary | null>(null);
  const [examples, setExamples] = useState<WorkedExample[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // /weken?course=sso&week=2, vanuit de agenda. Eén keer.
  const initial = useInitialParams();
  const consumedInitial = useRef(false);

  useEffect(() => {
    fetchCourses()
      .then((list) => {
        setCourses(list);
        const wanted = initial.get("course");
        const start = wanted && list.some((course) => course.slug === wanted) ? wanted : list[0]?.slug;
        if (start) setCourseSlug((current) => current ?? start);
      })
      .catch((cause) => setError(cause instanceof Error ? cause.message : String(cause)));
  }, [initial]);

  useEffect(() => {
    if (!courseSlug) return;
    setWeek(null);
    setSummary(null);
    setExamples([]);
    fetchWeeks(courseSlug)
      .then((list) => {
        setWeeks(list);
        if (!consumedInitial.current) {
          consumedInitial.current = true;
          const wanted = Number(initial.get("week"));
          const chosen = initial.get("course") === courseSlug ? list.find((item) => item.week === wanted) : undefined;
          if (chosen) void openWeek(chosen);
        }
      })
      .catch((cause) => setError(cause instanceof Error ? cause.message : String(cause)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [courseSlug]);

  async function openWeek(chosen: WeekRead) {
    if (!courseSlug) return;
    setWeek(chosen);
    setSummary(null);
    setExamples([]);
    setError(null);
    // De voorbeelden staan los van de samenvatting: ze bestaan ook als er nog
    // geen weekkaart is gemaakt.
    fetchWeekExamples(courseSlug, chosen.week).then(setExamples).catch(() => setExamples([]));
    try {
      setSummary(await fetchWeekSummary(courseSlug, chosen.week));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    }
  }

  async function summarise() {
    if (!courseSlug || !week) return;
    setBusy(true);
    setError(null);
    try {
      setSummary(await buildWeekSummary(courseSlug, week.week));
      setWeeks(await fetchWeeks(courseSlug));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex h-full min-h-0">
      <aside className="flex w-80 shrink-0 flex-col border-r border-ink-100">
        <div className="border-b border-ink-100 p-4">
          <label className="block">
            <span className="text-xs font-medium text-ink-600">Vak</span>
            <select
              value={courseSlug ?? ""}
              onChange={(event) => setCourseSlug(event.target.value || null)}
              className="mt-1 block w-full rounded-md border border-ink-200 px-2 py-1.5 text-sm"
            >
              {courses.map((course) => (
                <option key={course.slug} value={course.slug}>
                  {course.name}
                </option>
              ))}
            </select>
          </label>
        </div>

        <ul className="min-h-0 flex-1 overflow-y-auto">
          {weeks.map((item) => {
            const active = week?.week === item.week;
            return (
              <li key={item.week}>
                <button
                  type="button"
                  onClick={() => openWeek(item)}
                  className={`block w-full border-b border-ink-50 px-4 py-3 text-left transition ${
                    active ? "bg-primary-50" : "hover:bg-ink-50"
                  }`}
                >
                  <span className="flex items-baseline justify-between">
                    <span className="text-sm text-ink-800">Week {item.week}</span>
                    {item.has_summary && <span className="text-[11px] text-primary-600">samengevat</span>}
                  </span>
                  <span className="mt-0.5 block truncate text-[11px] text-ink-400">
                    {item.topics.length > 0 ? item.topics.join(" · ") : "geen onderwerpen in course.yml"}
                  </span>
                  <span className="mt-0.5 block text-[11px] text-ink-400">
                    {item.chunk_count} stukken materiaal
                    {item.unresolved.length > 0 && (
                      <span className="ml-1.5 text-accent-600">{item.unresolved.length} onopgelost</span>
                    )}
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      </aside>

      <section className="min-h-0 min-w-0 flex-1 overflow-y-auto">
        {error && (
          <div className="border-b border-rose-200 bg-rose-50 px-6 py-2 text-sm text-rose-800">{error}</div>
        )}

        {!week ? (
          <div className="flex h-full items-center justify-center p-8">
            <div className="max-w-md text-center">
              <h1 className="font-display text-xl font-semibold text-ink-900">Weet waar een week over gaat</h1>
              <p className="mt-2 text-sm text-ink-500">
                Kies links een week. De samenvatting wordt gemaakt uit álle stof van die week — de
                colleges plus de hoofdstukken uit het leesplan — en niet uit de fragmenten die een
                zoekvraag toevallig bovenaan zet.
              </p>
            </div>
          </div>
        ) : (
          <div className="mx-auto max-w-3xl px-6 py-6">
            <header className="flex items-baseline justify-between gap-4">
              <div className="min-w-0">
                <h1 className="font-display text-xl font-semibold text-ink-900">Week {week.week}</h1>
                {week.lectures.length > 0 && (
                  <p className="text-xs text-ink-400">
                    college {week.lectures.join(" en ")} · {week.chunk_count} stukken materiaal
                  </p>
                )}
              </div>
              <Button onClick={summarise} disabled={busy || week.chunk_count === 0}>
                {busy ? "Bezig…" : summary ? "Opnieuw samenvatten" : "Samenvatten"}
              </Button>
            </header>

            {week.unresolved.length > 0 && (
              <div className="mt-4 rounded-md border border-accent-100 bg-accent-50 px-4 py-3">
                <p className="text-xs font-medium text-accent-600">Niet gevonden in het corpus</p>
                <ul className="mt-1 space-y-0.5 text-xs text-ink-600">
                  {week.unresolved.map((line) => (
                    <li key={line}>{line}</li>
                  ))}
                </ul>
              </div>
            )}

            {summary ? (
              <WeekSummaryView summary={summary} examples={examples} />
            ) : (
              <p className="mt-6 text-sm text-ink-500">
                {week.chunk_count === 0
                  ? "Er staat nog geen materiaal van deze week in het corpus."
                  : "Nog niet samengevat."}
              </p>
            )}
          </div>
        )}
      </section>
    </div>
  );
}
