"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";
import { uploadDocument } from "@/lib/api";
import {
  DOC_KINDS,
  DOC_KIND_LABELS,
  KINDS_WITHOUT_WEEK,
  type CourseSummary,
  type DocKind,
} from "@/lib/types";


// De backend eist ^[a-z0-9][a-z0-9-]*$ voor een vaknaam, want die string wordt
// een mapnaam in corpus/. Hier wordt de getypte naam omgezet in plaats van hem
// af te wijzen: "Fundamentals of DS" → "fundamentals-of-ds". De leesbare naam
// hoort in course.yml.
export function slugifyCourse(value: string): string {
  return value
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}


const FOLDER_FOR_KIND: Record<DocKind, string> = {
  book: "books",
  paper: "papers",
  slides: "slides",
  assignment: "assignments",
  exercise: "exercises",
  submission: "submissions",
  solution: "solutions",
  note: "notes",
  exam: "exams",
};


export function UploadModal({
  courses,
  onClose,
  onUploaded,
}: {
  courses: CourseSummary[];
  onClose: () => void;
  onUploaded: () => void;
}) {
  const [file, setFile] = useState<File | null>(null);
  // De ruwe invoer blijft staan zoals getypt; de slug wordt eruit afgeleid.
  // Direct in het veld slugificeren zou een spatie meteen opeten en verder
  // typen onmogelijk maken.
  const [courseInput, setCourseInput] = useState(courses[0]?.slug ?? "");
  const [docKind, setDocKind] = useState<DocKind>("slides");
  const [week, setWeek] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [conflict, setConflict] = useState(false);

  const courseSlug = slugifyCourse(courseInput);
  const weekApplies = !KINDS_WITHOUT_WEEK.includes(docKind);
  const weekFolder = weekApplies && week ? `week-${week.padStart(2, "0")}/` : "";
  const preview = `corpus/${courseSlug || "<vak>"}/${FOLDER_FOR_KIND[docKind]}/${weekFolder}${file?.name ?? "<bestand>"}`;

  async function submit(overwrite = false) {
    if (!file || !courseSlug) return;
    setBusy(true);
    setError(null);
    try {
      await uploadDocument({
        file,
        courseSlug,
        docKind,
        week: weekApplies && week ? Number(week) : null,
        overwrite,
      });
      onUploaded();
      onClose();
    } catch (cause) {
      const message = cause instanceof Error ? cause.message : String(cause);
      setError(message);
      setConflict(message.includes("bestaat al"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center bg-scrim p-4">
      <div className="w-full max-w-lg rounded-lg border border-ink-200 bg-card p-5 shadow-lift">
        <h2 className="font-display text-base font-semibold text-ink-900">Materiaal toevoegen</h2>

        <div className="mt-4 space-y-3">
          <label className="block">
            <span className="text-xs font-medium text-ink-600">Bestand (.pdf, .pptx, .md, .ipynb of .py)</span>
            <input
              type="file"
              accept=".pdf,.pptx,.md,.ipynb,.py"
              onChange={(event) => setFile(event.target.files?.[0] ?? null)}
              className="mt-1 block w-full text-sm text-ink-700"
            />
          </label>

          <label className="block">
            <span className="text-xs font-medium text-ink-600">Vak</span>
            <input
              list="course-slugs"
              value={courseInput}
              onChange={(event) => setCourseInput(event.target.value)}
              placeholder="Statistical Learning"
              className="mt-1 block w-full rounded-md border border-ink-200 px-2 py-1.5 text-sm"
            />
            <datalist id="course-slugs">
              {courses.map((course) => (
                <option key={course.slug} value={course.slug}>
                  {course.name}
                </option>
              ))}
            </datalist>
            {courseSlug && courseSlug !== courseInput && (
              <span className="mt-1 block text-[11px] text-ink-500">
                Map: <span className="font-mono">{courseSlug}</span> — zet de leesbare naam in{" "}
                <span className="font-mono">corpus/{courseSlug}/course.yml</span>.
              </span>
            )}
          </label>

          <div className="flex gap-3">
            <label className="flex-1">
              <span className="text-xs font-medium text-ink-600">Soort</span>
              <select
                value={docKind}
                onChange={(event) => setDocKind(event.target.value as DocKind)}
                className="mt-1 block w-full rounded-md border border-ink-200 px-2 py-1.5 text-sm"
              >
                {DOC_KINDS.map((kind) => (
                  <option key={kind} value={kind}>
                    {DOC_KIND_LABELS[kind]}
                  </option>
                ))}
              </select>
            </label>

            {weekApplies && (
              <label className="w-28">
                <span className="text-xs font-medium text-ink-600">Week</span>
                <input
                  type="number"
                  min={1}
                  max={52}
                  value={week}
                  onChange={(event) => setWeek(event.target.value)}
                  className="mt-1 block w-full rounded-md border border-ink-200 px-2 py-1.5 text-sm"
                />
              </label>
            )}
          </div>

          <p className="break-all rounded-md bg-ink-50 px-2 py-1.5 font-mono text-[11px] text-ink-500">
            {preview}
          </p>

          {error && <p className="text-xs text-rose-700">{error}</p>}
        </div>

        <div className="mt-5 flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose} disabled={busy}>
            Annuleren
          </Button>
          {conflict && (
            <Button variant="danger" onClick={() => submit(true)} disabled={busy}>
              Vervangen
            </Button>
          )}
          <Button onClick={() => submit(false)} disabled={busy || !file || !courseSlug}>
            {busy ? "Bezig…" : "Toevoegen"}
          </Button>
        </div>
      </div>
    </div>
  );
}
