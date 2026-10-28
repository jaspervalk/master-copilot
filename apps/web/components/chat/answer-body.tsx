"use client";

import type { ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import rehypeKatex from "rehype-katex";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";

import { toDollarDelimiters } from "@/lib/answer-format";
import type { AnswerCitation } from "@/lib/types";


const CITATION_MARKER = /(\[\d+\])/g;


/** Maak van de `[1]`-verwijzingen in de lopende tekst knopjes naar de bron.
 *
 * De markers stonden er al, maar je kon er niet op klikken: de enige ingang
 * naar het bronpaneel was een aparte rij chips onder het antwoord. Terwijl de
 * verwijzing in de zin nu juist precies zegt wélke bewering je wil naslaan.
 */
function withCitationLinks(
  children: ReactNode,
  citations: AnswerCitation[],
  activeChunkId: string | null,
  onSelect: (citation: AnswerCitation) => void,
): ReactNode {
  if (typeof children !== "string" || citations.length === 0) return children;

  return children.split(CITATION_MARKER).map((part, index) => {
    const match = /^\[(\d+)\]$/.exec(part);
    if (!match) return part;

    const citation = citations[Number(match[1]) - 1];
    if (!citation) return part;

    const active = citation.chunk_id === activeChunkId;
    return (
      <button
        key={`${part}-${index}`}
        type="button"
        onClick={() => onSelect(citation)}
        title={`${citation.document_title}${
          citation.section_path ? ` — ${citation.section_path}` : ""
        }`}
        className={`mx-0.5 inline-flex items-center rounded px-1 align-baseline text-[11px] font-semibold tabular-nums transition ${
          active
            ? "bg-primary-500 text-on-fill"
            : "bg-primary-50 text-primary-600 hover:bg-primary-100"
        }`}
      >
        {match[1]}
      </button>
    );
  });
}


export function AnswerBody({
  text,
  citations = [],
  activeChunkId = null,
  onSelectCitation,
}: {
  text: string;
  citations?: AnswerCitation[];
  activeChunkId?: string | null;
  onSelectCitation?: (citation: AnswerCitation) => void;
}) {
  const link = (children: ReactNode) =>
    onSelectCitation
      ? withCitationLinks(children, citations, activeChunkId, onSelectCitation)
      : children;

  return (
    <div className="answer-body text-sm leading-relaxed text-ink-800">
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkMath]}
        // Tijdens het streamen is een formule soms nog niet afgesloten. Een
        // rode foutmelding laten staan is dan rustiger dan de render laten
        // klappen; zodra het sluitteken binnenkomt herstelt hij zich vanzelf.
        // De kleur is een variabele, zodat hij in donker leesbaar blijft.
        rehypePlugins={[[rehypeKatex, { throwOnError: false, errorColor: "rgb(var(--rose-700))" }]]}
        components={{
          // Alleen losse tekstknopen krijgen knopjes: binnen een formule of een
          // codeblok is "[1]" gewoon notatie.
          p: ({ children }) => <p>{Array.isArray(children) ? children.map(link) : link(children)}</p>,
          li: ({ children }) => (
            <li>{Array.isArray(children) ? children.map(link) : link(children)}</li>
          ),
        }}
      >
        {toDollarDelimiters(text)}
      </ReactMarkdown>
    </div>
  );
}
