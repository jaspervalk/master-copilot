"use client";

import { DOC_KIND_LABELS, locationLabel, type AnswerCitation } from "@/lib/types";


export function CitationChip({
  citation,
  index,
  active,
  onSelect,
}: {
  citation: AnswerCitation;
  index: number;
  active: boolean;
  onSelect: (citation: AnswerCitation) => void;
}) {
  return (
    <button
      type="button"
      onClick={() => onSelect(citation)}
      title={`${citation.document_title} — ${citation.section_path ?? ""}`}
      className={`inline-flex max-w-full items-center gap-1.5 rounded-md border px-2 py-1 text-left text-xs transition ${
        active
          ? "border-primary-400 bg-primary-50 text-primary-600"
          : "border-ink-200 bg-card text-ink-600 hover:border-ink-300 hover:bg-ink-50"
      }`}
    >
      <span className="font-semibold tabular-nums">[{index}]</span>
      <span className="truncate">{citation.document_title}</span>
      <span className="shrink-0 text-ink-400">
        {DOC_KIND_LABELS[citation.doc_kind]} · {locationLabel(citation)}
      </span>
    </button>
  );
}
