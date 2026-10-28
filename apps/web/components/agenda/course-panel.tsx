"use client";

import { keyFor } from "@/components/agenda/agenda-state";
import { AnnouncementList } from "@/components/agenda/announcement-list";
import { MaterialsList } from "@/components/agenda/materials-list";
import { PagesList } from "@/components/agenda/pages-list";
import { Banner } from "@/components/ui/banner";
import type { CanvasActions } from "@/components/agenda/canvas-section";
import type { AgendaCourse, AgendaDiffKind } from "@/lib/types";


type Tone = "info" | "success" | "warning" | "danger";

/** Aanwijzingen met een knop ernaast; die horen bij het vak te staan. De rest
 * raakt de spoilerfilter en gaat als waarschuwing naar de strook bovenaan, waar
 * hij niet achter een dichte sectie kan verdwijnen. */
export const INFO_DIFFS: AgendaDiffKind[] = ["canvas_id_missing", "assignment_sheet_missing"];

const DIFF_TONE: Record<AgendaDiffKind, Tone> = {
  due_date_differs: "warning",
  yaml_only: "warning",
  canvas_only: "warning",
  exam_date_differs: "warning",
  exam_missing_in_yaml: "warning",
  canvas_id_missing: "info",
  assignment_sheet_missing: "info",
};


export function CoursePanel({ course, actions }: { course: AgendaCourse; actions: CanvasActions }) {
  const {
    isPending,
    bulk,
    onHide,
    onFetchMaterial,
    onFetchAllMaterials,
    onIgnoreMaterial,
    onFetchSheetFile,
    onFetchSheetText,
    onFetchPage,
    onIgnorePage,
  } = actions;
  const subtitle = [course.course_code, course.term].filter(Boolean).join(", ");
  // De waarschuwingen staan bovenaan de pagina: ze sturen de spoilerfilter en
  // mogen niet achter een dichte sectie verdwijnen.
  const infoDiffs = course.diffs.filter((diff) => INFO_DIFFS.includes(diff.kind));
  return (
    <section className="mt-6 border-t border-ink-50 pt-5">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <div className="flex items-baseline gap-3">
          <h2 className="font-display text-base font-semibold text-ink-900">{course.name}</h2>
          {subtitle && <span className="text-xs text-ink-400">{subtitle}</span>}
        </div>
        <div className="flex items-baseline gap-3 text-xs text-ink-400">
          <span>{course.item_count === 1 ? "1 item" : `${course.item_count} items`}</span>
          {course.canvas_id !== null && (
            <button
              type="button"
              disabled={course.canvas_id !== null && isPending(keyFor.course(course.canvas_id))}
              onClick={() => onHide(course, true)}
              className="underline underline-offset-2 hover:text-ink-700"
            >
              verberg
            </button>
          )}
        </div>
      </div>

      {infoDiffs.length > 0 && (
        <ul className="mt-3 space-y-2">
          {infoDiffs.map((diff, index) => (
            <li key={`${diff.kind}:${index}`}>
              <Banner tone={DIFF_TONE[diff.kind]}>
                <span className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
                  <span>{diff.message}</span>
                  {diff.kind === "assignment_sheet_missing" && diff.file_id !== null && (
                    <button
                      type="button"
                      disabled={bulk || isPending(keyFor.material(diff.file_id as number))}
                      onClick={() => onFetchSheetFile(diff.file_id as number)}
                      className="shrink-0 text-xs text-primary-600 underline underline-offset-2 hover:text-primary-500"
                    >
                      Haal het opgavenblad op
                    </button>
                  )}
                  {diff.kind === "assignment_sheet_missing" && diff.can_fetch_text && diff.item_id && (
                    <button
                      type="button"
                      disabled={bulk || isPending(keyFor.item(diff.item_id as string))}
                      onClick={() => onFetchSheetText(diff.item_id as string)}
                      className="shrink-0 text-xs text-primary-600 underline underline-offset-2 hover:text-primary-500"
                    >
                      Zet de opgave uit Canvas in het corpus
                    </button>
                  )}
                </span>
              </Banner>
            </li>
          ))}
        </ul>
      )}

      <MaterialsList
        materials={course.materials}
        isPending={isPending}
        bulk={bulk}
        onFetch={onFetchMaterial}
        onFetchAll={onFetchAllMaterials}
        onIgnore={onIgnoreMaterial}
      />
      <PagesList pages={course.pages} isPending={isPending} bulk={bulk} onFetch={onFetchPage} onIgnore={onIgnorePage} />
      <AnnouncementList announcements={course.announcements} />
    </section>
  );
}
