"use client";

import { useEffect, useRef } from "react";

import { AnswerBody } from "@/components/chat/answer-body";
import { CitationChip } from "@/components/evidence/citation-chip";
import { ConfidenceChip } from "@/components/evidence/confidence-chip";
import type { AnswerCitation, ChatTurn } from "@/lib/types";


export function Thread({
  turns,
  activeCitationId,
  onSelectCitation,
  onReveal,
}: {
  turns: ChatTurn[];
  activeCitationId: string | null;
  onSelectCitation: (citation: AnswerCitation) => void;
  onReveal: (question: string) => void;
}) {
  const bottom = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: "smooth" });
  }, [turns]);

  if (turns.length === 0) {
    return (
      <div className="flex min-h-0 flex-1 items-center justify-center p-8">
        <div className="max-w-md text-center">
          <h1 className="font-display text-xl font-semibold text-ink-900">
            Vraag iets over je stof
          </h1>
          <p className="mt-2 text-sm text-ink-500">
            Antwoorden komen uit je eigen boeken, slides en opgaven, met een vindplaats die je kunt
            naslaan. Kies links een vak om binnen dat vak te zoeken.
          </p>
        </div>
      </div>
    );
  }

  // De reveal-knop stelt de vraag van de student opnieuw; die staat in de
  // gebruikersbeurt direct vóór het antwoord.
  function questionBefore(index: number): string | null {
    for (let i = index - 1; i >= 0; i -= 1) {
      if (turns[i].role === "user") return turns[i].content;
    }
    return null;
  }

  return (
    <div className="min-h-0 flex-1 overflow-y-auto px-6 py-6">
      <div className="mx-auto flex max-w-2xl flex-col gap-6">
        {turns.map((turn, index) =>
          turn.role === "user" ? (
            <div key={turn.id} className="flex justify-end">
              <p className="max-w-[80%] rounded-lg bg-primary-500 px-3 py-2 text-sm text-on-fill">
                {turn.content}
              </p>
            </div>
          ) : (
            <div key={turn.id} className="flex flex-col gap-2">
              <div>
                <AnswerBody
                  text={turn.content}
                  citations={turn.citations}
                  activeChunkId={activeCitationId}
                  onSelectCitation={onSelectCitation}
                />
                {turn.streaming && (
                  <span className="ml-0.5 inline-block h-4 w-1.5 animate-pulse bg-ink-400 align-text-bottom" />
                )}
              </div>

              {turn.rewrittenQuery && (
                <p className="text-xs text-ink-400">gezocht op: {turn.rewrittenQuery}</p>
              )}

              {turn.coach && !turn.streaming && (
                <div className="flex flex-wrap items-center gap-2 text-xs">
                  <span className="rounded bg-accent-50 px-1.5 py-0.5 text-accent-600">
                    coach · {turn.coach.document_title}
                    {turn.coach.policy === "reveal" ? " · uitwerking" : ""}
                  </span>
                  {/* De server negeert reveal op een beoordeelde opdracht en
                      geeft dan opnieuw hints; de UI hoeft de soort niet te kennen. */}
                  {turn.coach.policy === "hints" && questionBefore(index) && (
                    <button
                      type="button"
                      className="text-primary-600 underline underline-offset-2 hover:text-primary-500"
                      onClick={() => onReveal(questionBefore(index) ?? "")}
                    >
                      Laat de uitwerking zien
                    </button>
                  )}
                </div>
              )}

              {!turn.streaming && (
                <div className="flex flex-wrap items-center gap-1.5">
                  {turn.confidence && (
                    <ConfidenceChip confidence={turn.confidence} reasons={turn.confidenceReasons} />
                  )}
                  {turn.citations.map((citation, citationIndex) => (
                    <CitationChip
                      key={citation.chunk_id}
                      citation={citation}
                      index={citationIndex + 1}
                      active={activeCitationId === citation.chunk_id}
                      onSelect={onSelectCitation}
                    />
                  ))}
                </div>
              )}
            </div>
          ),
        )}
        <div ref={bottom} />
      </div>
    </div>
  );
}
