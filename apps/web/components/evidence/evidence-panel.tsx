"use client";

import { SourceBreadcrumb } from "@/components/evidence/source-breadcrumb";
import {
  DOC_KIND_LABELS,
  locationLabel,
  type AnswerCitation,
  type QueryChunkResult,
} from "@/lib/types";


/** Markeer het geciteerde fragment binnen de volledige chunktekst. */
function renderHighlighted(text: string, quote: string) {
  const needle = quote.replace(/…$/, "").trim();
  if (!needle) return text;
  const position = text.toLowerCase().indexOf(needle.toLowerCase());
  if (position === -1) return text;
  return (
    <>
      {text.slice(0, position)}
      <mark className="rounded bg-primary-100 px-0.5 text-ink-900">
        {text.slice(position, position + needle.length)}
      </mark>
      {text.slice(position + needle.length)}
    </>
  );
}


function SourceTab({
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
      title={citation.document_title}
      className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-md border text-[11px] font-semibold tabular-nums transition ${
        active
          ? "border-primary-400 bg-primary-500 text-on-fill"
          : "border-ink-200 bg-card text-ink-500 hover:border-ink-300 hover:bg-ink-50"
      }`}
    >
      {index}
    </button>
  );
}


export function EvidencePanel({
  citation,
  citations,
  chunks,
  onSelectCitation,
}: {
  citation: AnswerCitation | null;
  citations: AnswerCitation[];
  chunks: QueryChunkResult[];
  onSelectCitation: (citation: AnswerCitation) => void;
}) {
  if (!citation) {
    return (
      <aside className="w-96 shrink-0 border-l border-ink-100 p-6">
        <p className="text-sm text-ink-400">
          Klik op een verwijzing in het antwoord om te zien waar het op steunt.
        </p>
      </aside>
    );
  }

  const chunk = chunks.find((item) => item.chunk_id === citation.chunk_id);
  const activeIndex = citations.findIndex((item) => item.chunk_id === citation.chunk_id);

  return (
    <aside className="flex w-96 shrink-0 flex-col border-l border-ink-100">
      <div className="border-b border-ink-100 p-4">
        {citations.length > 1 && (
          <div className="mb-3 flex flex-wrap items-center gap-1">
            <span className="mr-1 text-[11px] text-ink-400">bronnen</span>
            {citations.map((item, index) => (
              <SourceTab
                key={item.chunk_id}
                citation={item}
                index={index + 1}
                active={item.chunk_id === citation.chunk_id}
                onSelect={onSelectCitation}
              />
            ))}
          </div>
        )}

        <div className="flex items-baseline gap-2">
          {activeIndex >= 0 && (
            <span className="shrink-0 text-xs font-semibold tabular-nums text-primary-500">
              [{activeIndex + 1}]
            </span>
          )}
          <h2 className="font-display text-sm font-semibold leading-snug text-ink-900">
            {citation.document_title}
          </h2>
        </div>
        <p className="mt-0.5 text-xs text-ink-500">
          {DOC_KIND_LABELS[citation.doc_kind]}
          {citation.week !== null ? ` · week ${citation.week}` : ""} · {locationLabel(citation)}
        </p>

        <SourceBreadcrumb path={citation.section_path} />
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto">
        {/* Het fragment dat de bewering draagt staat bovenaan; de rest van de
            passage is context die je erbij kunt lezen, niet andersom. */}
        <div className="border-b border-ink-100 bg-primary-50/40 p-4">
          <p className="text-[11px] font-medium uppercase tracking-wide text-primary-600">
            Waar het antwoord op steunt
          </p>
          <p className="mt-1.5 text-sm leading-relaxed text-ink-800">{citation.quote}</p>
        </div>

        {chunk && (
          <div className="p-4">
            <p className="text-[11px] font-medium uppercase tracking-wide text-ink-400">
              Volledige passage
            </p>
            <p className="mt-1.5 whitespace-pre-wrap text-sm leading-relaxed text-ink-600">
              {renderHighlighted(chunk.text, citation.quote)}
            </p>
          </div>
        )}
      </div>

      <p className="shrink-0 break-all border-t border-ink-100 px-4 py-2 font-mono text-[10px] text-ink-300">
        {citation.source_path}
      </p>
    </aside>
  );
}
