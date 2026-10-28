"use client";

import { useCallback, useEffect, useState } from "react";

import { UploadModal } from "@/components/corpus/upload-modal";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { deleteDocument, fetchCourses, fetchDocuments, reindexDocument } from "@/lib/api";
import { DOC_KIND_LABELS, type CourseSummary, type DocumentRead } from "@/lib/types";


export function CorpusConsole() {
  const [documents, setDocuments] = useState<DocumentRead[]>([]);
  const [courses, setCourses] = useState<CourseSummary[]>([]);
  const [courseFilter, setCourseFilter] = useState<string>("");
  const [showUpload, setShowUpload] = useState(false);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [pendingDelete, setPendingDelete] = useState<DocumentRead | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    try {
      const [nextDocuments, nextCourses] = await Promise.all([
        fetchDocuments(courseFilter ? { courseSlug: courseFilter } : {}),
        fetchCourses(),
      ]);
      setDocuments(nextDocuments);
      setCourses(nextCourses);
      setError(null);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    }
  }, [courseFilter]);

  useEffect(() => {
    void reload();
  }, [reload]);

  async function runAction(document: DocumentRead, action: "reindex" | "delete") {
    setBusyId(document.id);
    setError(null);
    try {
      if (action === "reindex") await reindexDocument(document.id);
      else await deleteDocument(document.id);
      await reload();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusyId(null);
      setPendingDelete(null);
    }
  }

  return (
    <div className="mx-auto max-w-6xl p-6">
      <div className="flex items-center justify-between gap-4">
        <div>
          <h1 className="font-display text-lg font-semibold text-ink-900">Corpus</h1>
          <p className="mt-1 text-sm text-ink-500">
            Wat er geïndexeerd is. Bestanden landen in je mapstructuur onder <code>corpus/</code>.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <select
            value={courseFilter}
            onChange={(event) => setCourseFilter(event.target.value)}
            className="rounded-md border border-ink-200 px-2 py-1.5 text-sm text-ink-700"
            aria-label="Filter op vak"
          >
            <option value="">Alle vakken</option>
            {courses.map((course) => (
              <option key={course.slug} value={course.slug}>
                {course.name}
              </option>
            ))}
          </select>
          <Button onClick={() => setShowUpload(true)}>Toevoegen</Button>
        </div>
      </div>

      {error && (
        <div className="mt-4 rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-800">
          {error}
        </div>
      )}

      <div className="mt-5 overflow-hidden rounded-lg border border-ink-100 bg-card">
        <table className="w-full text-sm">
          <thead className="bg-ink-50 text-left text-xs uppercase tracking-wide text-ink-500">
            <tr>
              <th className="px-3 py-2 font-medium">Titel</th>
              <th className="px-3 py-2 font-medium">Vak</th>
              <th className="px-3 py-2 font-medium">Soort</th>
              <th className="px-3 py-2 font-medium">Week</th>
              <th className="px-3 py-2 font-medium">Status</th>
              <th className="px-3 py-2 text-right font-medium">Pagina&apos;s</th>
              <th className="px-3 py-2 text-right font-medium">Chunks</th>
              <th className="px-3 py-2" />
            </tr>
          </thead>
          <tbody className="divide-y divide-ink-100">
            {documents.map((document) => (
              <tr key={document.id} className="align-top">
                <td className="px-3 py-2">
                  <span className="block text-ink-800">{document.title}</span>
                  <span className="block break-all font-mono text-[11px] text-ink-400">
                    {document.source_path}
                  </span>
                  {document.ingestion_status === "failed" && document.parse_error && (
                    <>
                      <button
                        type="button"
                        onClick={() => setExpanded(expanded === document.id ? null : document.id)}
                        className="mt-1 text-xs text-rose-700 underline"
                      >
                        {expanded === document.id ? "verberg fout" : "toon fout"}
                      </button>
                      {expanded === document.id && (
                        <p className="mt-1 rounded-md bg-rose-50 p-2 text-xs text-rose-800">
                          {document.parse_error}
                        </p>
                      )}
                    </>
                  )}
                </td>
                <td className="px-3 py-2 text-ink-600">{document.course_slug}</td>
                <td className="px-3 py-2 text-ink-600">{DOC_KIND_LABELS[document.doc_kind]}</td>
                <td className="px-3 py-2 tabular-nums text-ink-600">{document.week ?? "—"}</td>
                <td className="px-3 py-2">
                  <div className="flex flex-wrap gap-1">
                    <Badge
                      tone={
                        document.ingestion_status === "indexed"
                          ? "success"
                          : document.ingestion_status === "failed"
                            ? "danger"
                            : "neutral"
                      }
                    >
                      {document.ingestion_status}
                    </Badge>
                    {document.assignment_status && (
                      <Badge tone={document.assignment_status === "open" ? "warning" : "neutral"}>
                        {document.assignment_status === "open" ? "open" : "ingeleverd"}
                      </Badge>
                    )}
                  </div>
                </td>
                <td className="px-3 py-2 text-right tabular-nums text-ink-600">{document.page_count}</td>
                <td className="px-3 py-2 text-right tabular-nums text-ink-600">{document.chunk_count}</td>
                <td className="px-3 py-2">
                  <div className="flex justify-end gap-1">
                    <Button
                      size="sm"
                      variant="secondary"
                      disabled={busyId === document.id}
                      onClick={() => runAction(document, "reindex")}
                    >
                      Herindexeer
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      disabled={busyId === document.id}
                      onClick={() => setPendingDelete(document)}
                    >
                      Verwijder
                    </Button>
                  </div>
                </td>
              </tr>
            ))}
            {documents.length === 0 && (
              <tr>
                <td colSpan={8} className="px-3 py-8 text-center text-sm text-ink-400">
                  Nog niets geïndexeerd. Voeg een boek, slidedeck of opgavenblad toe.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {showUpload && (
        <UploadModal courses={courses} onClose={() => setShowUpload(false)} onUploaded={reload} />
      )}

      {pendingDelete && (
        <div className="fixed inset-0 z-40 flex items-center justify-center bg-scrim p-4">
          <div className="w-full max-w-md rounded-lg border border-ink-200 bg-card p-5 shadow-lift">
            <h2 className="font-display text-base font-semibold text-ink-900">Verwijderen?</h2>
            <p className="mt-2 text-sm text-ink-600">
              <span className="font-medium">{pendingDelete.title}</span> wordt uit de index gehaald.
              Het bestand verhuist naar <code>corpus/.trash/</code>, dus je kunt het terugzetten.
            </p>
            <div className="mt-5 flex justify-end gap-2">
              <Button variant="ghost" onClick={() => setPendingDelete(null)}>
                Annuleren
              </Button>
              <Button
                variant="danger"
                disabled={busyId === pendingDelete.id}
                onClick={() => runAction(pendingDelete, "delete")}
              >
                Verwijderen
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
