"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";
import {
  DOC_KIND_LABELS,
  type AnswerLanguage,
  type AnswerStyle,
  type CoachOptions,
  type DocumentRead,
  type RetrievalMode,
} from "@/lib/types";


export function Composer({
  onSubmit,
  isStreaming,
  style,
  onStyleChange,
  mode,
  onModeChange,
  language,
  onLanguageChange,
  coach,
  coachChoices,
  onCoachChange,
}: {
  onSubmit: (question: string) => void;
  isStreaming: boolean;
  style: AnswerStyle;
  onStyleChange: (style: AnswerStyle) => void;
  mode: RetrievalMode;
  onModeChange: (mode: RetrievalMode) => void;
  language: AnswerLanguage;
  onLanguageChange: (language: AnswerLanguage) => void;
  coach: CoachOptions | null;
  coachChoices: DocumentRead[];
  onCoachChange: (coach: CoachOptions | null) => void;
}) {
  const [question, setQuestion] = useState("");
  const canSubmit = question.trim().length >= 3 && !isStreaming;

  function submit() {
    if (!canSubmit) return;
    onSubmit(question.trim());
    setQuestion("");
  }

  return (
    <div className="border-t border-ink-100 bg-card p-4">
      <textarea
        value={question}
        onChange={(event) => setQuestion(event.target.value)}
        onKeyDown={(event) => {
          // Enter verstuurt, shift+enter maakt een nieuwe regel.
          if (event.key === "Enter" && !event.shiftKey) {
            event.preventDefault();
            submit();
          }
        }}
        rows={3}
        placeholder={
          coach
            ? "Waar loop je vast? De coach geeft hints, geen antwoorden."
            : "Stel een vraag over je materiaal…"
        }
        className="w-full resize-none rounded-md border border-ink-200 p-3 text-sm text-ink-800 outline-none focus:border-primary-400"
      />
      <div className="mt-2 flex items-center justify-between gap-2">
        {/* Elke knop krijgt een zichtbaar kopje. Zonder dat zijn het vier
            naamloze vakjes waar je overheen kijkt — precies wat er gebeurde. */}
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2 text-xs">
          <label className="flex items-center gap-1.5 text-ink-500">
            Stijl
            <select
              value={style}
              onChange={(event) => onStyleChange(event.target.value as AnswerStyle)}
              className="rounded-md border border-ink-200 px-2 py-1.5 text-ink-700"
            >
              <option value="explain">Uitleg</option>
              <option value="short">Kort</option>
            </select>
          </label>
          <label className="flex items-center gap-1.5 text-ink-500">
            Taal
            <select
              value={language}
              onChange={(event) => onLanguageChange(event.target.value as AnswerLanguage)}
              className="rounded-md border border-ink-200 px-2 py-1.5 text-ink-700"
              title="Automatisch volgt de taal van je vraag"
            >
              <option value="auto">Automatisch</option>
              <option value="nl">Nederlands</option>
              <option value="en">Engels</option>
            </select>
          </label>
          <label className="flex items-center gap-1.5 text-ink-500">
            Zoeken
            <select
              value={mode}
              onChange={(event) => onModeChange(event.target.value as RetrievalMode)}
              className="rounded-md border border-ink-200 px-2 py-1.5 text-ink-700"
            >
              <option value="hybrid">Hybride</option>
              <option value="dense">Alleen dense</option>
            </select>
          </label>

          {/* Zonder open opdrachten of oefenmateriaal in het gekozen vak valt er
              niets te coachen; dan is de schakelaar uit én uitgeschakeld. */}
          <label
            className={`flex items-center gap-1.5 ${
              coachChoices.length === 0 ? "text-ink-300" : "text-ink-700"
            }`}
            title={coachChoices.length === 0 ? "Geen open opdrachten of oefenopgaven in dit vak" : undefined}
          >
            <input
              type="checkbox"
              checked={coach !== null}
              disabled={coachChoices.length === 0}
              onChange={(event) =>
                onCoachChange(event.target.checked ? { document_id: coachChoices[0].id } : null)
              }
            />
            Coach
          </label>
          {coach && (
            <select
              value={coach.document_id}
              onChange={(event) => onCoachChange({ document_id: event.target.value })}
              className="max-w-[16rem] rounded-md border border-ink-200 px-2 py-1.5 text-ink-700"
              aria-label="Opdracht"
            >
              {coachChoices.map((doc) => (
                <option key={doc.id} value={doc.id}>
                  {DOC_KIND_LABELS[doc.doc_kind]}
                  {doc.week !== null ? ` · week ${doc.week}` : ""} · {doc.title}
                </option>
              ))}
            </select>
          )}
        </div>
        <Button onClick={submit} disabled={!canSubmit}>
          {isStreaming ? "Bezig…" : "Vraag"}
        </Button>
      </div>
    </div>
  );
}
