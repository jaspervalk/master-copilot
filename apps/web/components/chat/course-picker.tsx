"use client";

import type { CourseSummary } from "@/lib/types";


export function CoursePicker({
  courses,
  selected,
  onSelect,
  week,
  onWeekChange,
}: {
  courses: CourseSummary[];
  selected: string | null;
  onSelect: (slug: string | null) => void;
  week: number | null;
  onWeekChange: (week: number | null) => void;
}) {
  const activeCourse = courses.find((course) => course.slug === selected) ?? null;

  return (
    <aside className="flex w-64 shrink-0 flex-col gap-5 overflow-y-auto border-r border-ink-100 p-4">
      <div>
        <h2 className="text-xs font-semibold uppercase tracking-wide text-ink-400">Vak</h2>
        <ul className="mt-2 space-y-1">
          <li>
            <button
              type="button"
              onClick={() => onSelect(null)}
              className={`w-full rounded-md px-2 py-1.5 text-left text-sm transition ${
                selected === null ? "bg-ink-100 font-medium text-ink-900" : "text-ink-600 hover:bg-ink-50"
              }`}
            >
              Alle vakken
            </button>
          </li>
          {courses.map((course) => (
            <li key={course.slug}>
              <button
                type="button"
                onClick={() => onSelect(course.slug)}
                className={`w-full rounded-md px-2 py-1.5 text-left text-sm transition ${
                  selected === course.slug
                    ? "bg-ink-100 font-medium text-ink-900"
                    : "text-ink-600 hover:bg-ink-50"
                }`}
              >
                <span className="block truncate">{course.name}</span>
                <span className="block text-xs text-ink-400">
                  {course.document_count} documenten
                  {course.open_assignment_count > 0
                    ? ` · ${course.open_assignment_count} open opgaven`
                    : ""}
                </span>
              </button>
            </li>
          ))}
          {courses.length === 0 && (
            <li className="px-2 py-1.5 text-xs text-ink-400">
              Nog geen materiaal. Voeg iets toe op de corpuspagina.
            </li>
          )}
        </ul>
      </div>

      {activeCourse && activeCourse.weeks.length > 0 && (
        <div>
          <h2 className="text-xs font-semibold uppercase tracking-wide text-ink-400">Week</h2>
          <div className="mt-2 flex flex-wrap gap-1">
            <button
              type="button"
              onClick={() => onWeekChange(null)}
              className={`rounded-md px-2 py-1 text-xs transition ${
                week === null ? "bg-ink-100 font-medium text-ink-900" : "text-ink-500 hover:bg-ink-50"
              }`}
            >
              alle
            </button>
            {activeCourse.weeks.map((value) => (
              <button
                key={value}
                type="button"
                onClick={() => onWeekChange(value)}
                className={`rounded-md px-2 py-1 text-xs tabular-nums transition ${
                  week === value ? "bg-ink-100 font-medium text-ink-900" : "text-ink-500 hover:bg-ink-50"
                }`}
              >
                {value}
              </button>
            ))}
          </div>
        </div>
      )}
    </aside>
  );
}
