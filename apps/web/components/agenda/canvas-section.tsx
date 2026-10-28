"use client";

import { useState } from "react";

import { isNew } from "@/components/agenda/announcement-list";
import { CoursePanel } from "@/components/agenda/course-panel";
import type { AgendaCourse, AgendaMaterial, AgendaPage, DocKind } from "@/lib/types";


/** Alles wat de console met Canvas-materiaal kan. Als één prop, want negen
 * losse callbacks door twee lagen heen leest niemand meer. */
export type CanvasActions = {
  isPending: (key: string) => boolean;
  bulk: boolean;
  onHide: (course: AgendaCourse, hidden: boolean) => void;
  onFetchMaterial: (material: AgendaMaterial, choice: { doc_kind: DocKind; week: number | null }) => void;
  onFetchAllMaterials: (materials: AgendaMaterial[]) => void;
  onIgnoreMaterial: (material: AgendaMaterial, ignored: boolean) => void;
  onFetchSheetFile: (fileId: number) => void;
  onFetchSheetText: (itemId: string) => void;
  onFetchPage: (page: AgendaPage) => void;
  onIgnorePage: (page: AgendaPage, ignored: boolean) => void;
};

function plural(count: number, one: string, many: string): string | null {
  if (count === 0) return null;
  return `${count} ${count === 1 ? one : many}`;
}


/** Nieuw materiaal, pagina's en aankondigingen: nuttig, maar niet waar de
 * agenda over gaat. Eén dichte sectie met een telling in de kop — dat getal is
 * het signaal, de inhoud hoeft niet open te staan. */
export function CanvasSection({ courses, actions }: { courses: AgendaCourse[]; actions: CanvasActions }) {
  const [open, setOpen] = useState(false);

  const withContent = courses.filter(
    (course) => course.diffs.length > 0 || course.announcements.length > 0 || course.materials.length > 0 || course.pages.length > 0,
  );
  if (withContent.length === 0) return null;

  const files = withContent.reduce(
    (total, course) => total + course.materials.filter((material) => material.state === "new" || material.state === "unplaced").length,
    0,
  );
  const pages = withContent.reduce((total, course) => total + course.pages.filter((page) => page.state === "new").length, 0);
  // Dezelfde regel als de lijst zelf: ongelezen alléén is niet nieuw, want
  // Canvas noemt ook een bericht uit juli ongelezen.
  const now = Date.now();
  const fresh = withContent.reduce((total, course) => total + course.announcements.filter((item) => isNew(item, now)).length, 0);
  const summary =
    [plural(files, "bestand", "bestanden"), plural(pages, "pagina", "pagina's"), plural(fresh, "nieuwe aankondiging", "nieuwe aankondigingen")]
      .filter(Boolean)
      .join(", ") || "niets nieuws";

  return (
    <section className="mt-8 border-t border-ink-100 pt-4">
      <button
        type="button"
        onClick={() => setOpen((current) => !current)}
        aria-expanded={open}
        className="flex w-full items-baseline justify-between gap-4 text-left"
      >
        <span className="font-display text-base font-semibold text-ink-900">
          Uit Canvas <span className="ml-2 text-xs font-normal text-ink-500">{summary}</span>
        </span>
        <span className="shrink-0 text-xs text-primary-600 underline underline-offset-2">{open ? "verberg" : "toon"}</span>
      </button>

      {open &&
        withContent.map((course) => (
          <CoursePanel key={course.canvas_id ?? course.course_slug ?? course.name} course={course} actions={actions} />
        ))}
    </section>
  );
}
