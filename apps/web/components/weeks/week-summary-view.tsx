"use client";

import { AnswerBody } from "@/components/chat/answer-body";
import { WorkedExampleBlock } from "@/components/practice/worked-example";
import type { WeekFormula, WeekSummary, WorkedExample } from "@/lib/types";


function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="mt-6">
      <h2 className="font-display text-sm font-semibold text-ink-900">{title}</h2>
      <div className="mt-2">{children}</div>
    </section>
  );
}


// De lijsten hieronder komen uit tekst van het model, en die kan dubbel zijn:
// een formuleblad legde `x_i` twee keer uit, met twee betekenissen. Ze worden
// nooit herschikt of aangevuld, dus de positie is een geldige sleutel; de tekst
// is dat niet.
export function WeekSummaryView({
  summary,
  examples,
}: {
  summary: WeekSummary;
  examples: WorkedExample[];
}) {
  return (
    <div>
      {summary.stale && (
        <p className="mt-4 rounded-md border border-accent-100 bg-accent-50 px-4 py-2 text-xs text-accent-600">
          Het materiaal is veranderd sinds deze samenvatting is gemaakt.
        </p>
      )}

      <Section title="De rode draad">
        <AnswerBody text={summary.thread} />
      </Section>

      {summary.topics.length > 0 && (
        <Section title="Wat er behandeld wordt">
          <ul className="space-y-3">
            {summary.topics.map((topic, index) => (
              <li key={index} className="border-l-2 border-ink-100 pl-3">
                <p className="text-sm font-medium text-ink-900">{topic.label}</p>
                <AnswerBody text={topic.covers} />
                <p className="mt-0.5 text-[11px] text-ink-400">{topic.where}</p>
              </li>
            ))}
          </ul>
        </Section>
      )}

      {summary.formulas.length > 0 && (
        <Section title="Formuleblad">
          <ul className="space-y-4">
            {summary.formulas.map((formula, index) => (
              <FormulaRow key={index} formula={formula} />
            ))}
          </ul>
          {summary.problems.length > 0 && (
            <p className="mt-3 text-[11px] text-ink-400">
              Niet opgenomen: {summary.problems.join("; ")}.
            </p>
          )}
        </Section>
      )}

      {examples.length > 0 && (
        <Section title="Uitgewerkte voorbeelden">
          <p className="-mt-1 mb-2 text-xs text-ink-500">
            Eén situatie met echte getallen, helemaal doorgerekend. Lees hem vóór je gaat oefenen; zodra
            je het onderwerp kunt, levert nog een uitwerking weinig meer op.
          </p>
          {examples.map((example) => (
            <WorkedExampleBlock key={example.id} example={example} mastered={false} />
          ))}
        </Section>
      )}

      {summary.skills.length > 0 && (
        <Section title="Wat je moet kunnen">
          <ul className="space-y-1.5">
            {summary.skills.map((skill, index) => (
              <li key={index} className="flex gap-2 text-sm text-ink-800">
                <span className="text-ink-300">—</span>
                <AnswerBody text={skill} />
              </li>
            ))}
          </ul>
        </Section>
      )}

      {summary.concepts.length > 0 && (
        <Section title="Begrippen">
          <dl className="space-y-2">
            {summary.concepts.map((concept, index) => (
              <div key={index}>
                <dt className="text-sm font-medium text-ink-900">{concept.term}</dt>
                <dd className="text-sm text-ink-600">
                  <AnswerBody text={concept.meaning} />
                </dd>
              </div>
            ))}
          </dl>
        </Section>
      )}

      <p className="mt-8 border-t border-ink-100 pt-3 text-[11px] text-ink-400">
        Gemaakt uit {summary.chunks_used} van de {summary.chunks_total} stukken materiaal
        {summary.chunks_used < summary.chunks_total && " — de rest paste niet in één keer"}.
      </p>
    </div>
  );
}


/** Een formule staat groot, met eronder waarvoor elk teken staat — dat laatste
 *  is op een schriftelijk tentamen het halve werk. */
function FormulaRow({ formula }: { formula: WeekFormula }) {
  return (
    <li className="rounded-md border border-ink-100 bg-card p-3">
      <p className="text-sm font-medium text-ink-900">{formula.name}</p>
      <div className="mt-1 overflow-x-auto">
        <AnswerBody text={`$$${formula.latex}$$`} />
      </div>
      {formula.when && <p className="mt-1 text-xs text-ink-500">{formula.when}</p>}
      {formula.symbols.length > 0 && (
        <dl className="mt-2 flex flex-wrap gap-x-4 gap-y-1">
          {formula.symbols.map((symbol, index) => (
            <div key={index} className="flex items-baseline gap-1.5 text-xs">
              <dt className="text-ink-800">
                <AnswerBody text={`$${symbol.symbol}$`} />
              </dt>
              <dd className="text-ink-500">{symbol.meaning}</dd>
            </div>
          ))}
        </dl>
      )}
    </li>
  );
}
