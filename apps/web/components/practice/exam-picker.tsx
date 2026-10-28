"use client";

import { useEffect, useState } from "react";

import type { ExamSet } from "@/lib/types";


function points(value: number): string {
  return Number.isInteger(value) ? String(value) : value.toFixed(1);
}


/** De (proef- en oefen)tentamens met hun secties, en per sectie wat je bij je
 * laatste poging haalde. Niet één eindcijfer: je wil zien wáár de punten
 * weglekken. Eén tentamen tegelijk uitgeklapt, anders wordt de lijst met drie
 * tentamens van vijf secties langer dan het scherm. */
export function ExamPicker({
  exams,
  active,
  onOpen,
  onGenerate,
  onGenerateSection,
  generating,
}: {
  exams: ExamSet[];
  /** "origin" voor het hele tentamen, "origin:3" voor sectie 3. */
  active: string | null;
  onOpen: (origin: string, section: number | null) => void;
  /** Ontbreekt als er geen proeftentamen is om de opbouw van over te nemen. */
  onGenerate?: () => void;
  /** Een sectie die bij een oefententamen nog ontbreekt alsnog maken. */
  onGenerateSection?: (origin: string, section: number) => void;
  /** Voortgang van een oefententamen dat nu gemaakt wordt. */
  generating: string | null;
}) {
  const [expanded, setExpanded] = useState<string | null>(null);

  // Het tentamen waar je in bezig bent klapt vanzelf open.
  useEffect(() => {
    if (active) setExpanded(active.split(":")[0]);
  }, [active]);

  if (exams.length === 0) return null;
  const open = expanded ?? exams[0].origin;
  // De opbouw komt van het proeftentamen; een oefententamen kan secties missen
  // waar nog geen stof voor is.
  const blueprint = exams.find((exam) => !exam.origin.startsWith("oefententamen-")) ?? null;

  return (
    <div className="border-b border-ink-100 pb-2">
      {exams.map((exam) => {
        const isOpen = open === exam.origin;
        return (
          <div key={exam.origin}>
            <button
              type="button"
              onClick={() => setExpanded(isOpen ? "" : exam.origin)}
              className="flex w-full items-baseline justify-between gap-2 px-4 pb-1 pt-3 text-left transition hover:bg-ink-50"
            >
              <span className="flex items-baseline gap-1.5 text-sm font-medium text-ink-900">
                <span className="text-[10px] text-ink-400">{isOpen ? "▾" : "▸"}</span>
                {exam.title}
              </span>
              <span className="text-[11px] tabular-nums text-ink-500">
                {exam.answered > 0
                  ? `${points(exam.last_score)}/${points(exam.answered_points)} p · ${exam.answered}/${exam.question_count}`
                  : `${exam.question_count} vragen · ${points(exam.points)} p`}
              </span>
            </button>

            {isOpen && (
              <ul className="pb-1">
                <li>
                  <button
                    type="button"
                    onClick={() => onOpen(exam.origin, null)}
                    className={`w-full px-4 py-1 pl-8 text-left text-xs transition ${
                      active === exam.origin ? "bg-primary-50 text-ink-900" : "text-primary-600 hover:bg-ink-50"
                    }`}
                  >
                    Hele tentamen maken
                  </button>
                </li>
                {exam.sections.map((section) => {
                  const key = `${exam.origin}:${section.number}`;
                  const share = section.answered_points > 0 ? section.last_score / section.answered_points : null;
                  // Een oefententamen kan plekken missen: vragen die als kopie of
                  // zonder stof werden afgekeurd. Die zijn later aan te vullen.
                  const gepland = blueprint?.sections.find((own) => own.number === section.number)?.points ?? 0;
                  const aanvulbaar = exam.origin.startsWith("oefententamen-") && section.points < gepland;
                  return (
                    <li key={key} className="flex items-baseline">
                      <button
                        type="button"
                        onClick={() => onOpen(exam.origin, section.number)}
                        className={`flex min-w-0 flex-1 items-baseline justify-between gap-2 px-4 py-1 pl-8 text-left transition ${
                          active === key ? "bg-primary-50" : "hover:bg-ink-50"
                        }`}
                      >
                        <span className="min-w-0 truncate text-xs text-ink-700">
                          {section.number}. {section.title}
                        </span>
                        <span
                          className={`shrink-0 text-[11px] tabular-nums ${
                            share === null
                              ? "text-ink-400"
                              : share >= 0.75
                                ? "text-primary-600"
                                : share >= 0.5
                                  ? "text-ink-600"
                                  : "text-accent-600"
                          }`}
                        >
                          {section.answered > 0
                            ? `${points(section.last_score)}/${points(section.answered_points)}`
                            : `${section.question_count}× · ${points(section.points)}${aanvulbaar ? `/${points(gepland)}` : ""} p`}
                        </span>
                      </button>
                      {aanvulbaar && onGenerateSection && !generating && (
                        <button
                          type="button"
                          onClick={() => onGenerateSection(exam.origin, section.number)}
                          title={`Nog ${points(gepland - section.points)} punten leeg`}
                          className="shrink-0 pr-4 text-[11px] text-primary-600 underline"
                        >
                          vul aan
                        </button>
                      )}
                    </li>
                  );
                })}
                {exam.origin.startsWith("oefententamen-") &&
                  blueprint?.sections
                    .filter((section) => !exam.sections.some((own) => own.number === section.number))
                    .map((section) => (
                      <li key={`${exam.origin}:${section.number}:ontbreekt`} className="flex items-baseline justify-between gap-2 px-4 py-1 pl-8">
                        <span className="min-w-0 truncate text-xs text-ink-400">
                          {section.number}. {section.title} — nog geen stof
                        </span>
                        {onGenerateSection && !generating && (
                          <button
                            type="button"
                            onClick={() => onGenerateSection(exam.origin, section.number)}
                            className="shrink-0 text-[11px] text-primary-600 underline"
                          >
                            probeer
                          </button>
                        )}
                      </li>
                    ))}
              </ul>
            )}
          </div>
        );
      })}

      {onGenerate && (
        <div className="px-4 pt-2">
          {generating ? (
            <p className="text-xs text-ink-500">{generating}</p>
          ) : (
            <button type="button" onClick={onGenerate} className="text-xs text-primary-600 underline">
              Maak een nieuw oefententamen
            </button>
          )}
        </div>
      )}
    </div>
  );
}
