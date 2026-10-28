"use client";

import { AnswerBody } from "@/components/chat/answer-body";
import type { WorkedExample } from "@/lib/types";


/**
 * Een uitgewerkt voorbeeld: situatie, stappen, wat je meeneemt, en een vraag.
 *
 * Twee dingen zitten er met opzet in. De figuur is geen plaatje dat een model
 * beschreef maar code die is uitgevoerd — kwam er niets uit, dan staat er ook
 * niets. En de vraag onderaan wordt niet nagekeken: het formuleren is het
 * werkzame deel, en een nagekeken vraag zou er weer een toets van maken.
 *
 * Het voorbeeld staat dichtgeklapt. Bij een onderwerp dat je al beheerst gaat
 * er een zin bij: dan levert nog een uitwerking lezen weinig meer op.
 */
export function WorkedExampleBlock({ example, mastered }: { example: WorkedExample; mastered: boolean }) {
  return (
    <details className="mt-2 rounded-md border border-ink-100 bg-surface">
      <summary className="cursor-pointer px-3 py-2 text-xs text-ink-600">
        Uitgewerkt voorbeeld — <span className="text-ink-800">{example.title}</span>
        {example.figure_svg && <span className="ml-2 text-ink-400">met figuur</span>}
      </summary>

      <div className="border-t border-ink-100 px-3 py-3">
        {mastered && (
          <p className="mb-3 text-[11px] text-ink-400">
            Je hebt dit onderwerp al onder de knie. Nog een uitwerking lezen levert dan weinig meer
            op — oefenen wel.
          </p>
        )}

        <div className="text-sm text-ink-700">
          <AnswerBody text={example.situation} />
        </div>

        {example.figure_svg && (
          <figure className="my-3">
            <div
              className="overflow-x-auto dark:w-fit dark:max-w-full dark:rounded-md dark:bg-ink-800 dark:p-2 [&_svg]:h-auto [&_svg]:max-w-full"
              // De svg komt van matplotlib in een eigen proces, niet van het
              // model: wat niet tekende, staat hier niet. Hij is doorzichtig met
              // zwarte lijnen en tekst, dus in donker ligt hij op een vel zo
              // licht als de lopende tekst: puur wit is daar het felste vlak van
              // de pagina. Omkeren kan niet, dan liegen de kleurschalen.
              dangerouslySetInnerHTML={{ __html: example.figure_svg }}
            />
            {example.figure_caption && (
              <figcaption className="mt-1 text-[11px] text-ink-400">{example.figure_caption}</figcaption>
            )}
          </figure>
        )}

        <ol className="mt-3 space-y-3">
          {example.steps.map((step, index) => (
            <li key={index} className="border-l-2 border-primary-100 pl-3">
              <p className="text-[11px] uppercase tracking-wide text-ink-400">{step.label}</p>
              <div className="text-sm text-ink-700">
                <AnswerBody text={step.body} />
              </div>
            </li>
          ))}
        </ol>

        {example.takeaway && (
          <p className="mt-3 rounded-md bg-primary-50 px-3 py-2 text-sm text-ink-800">{example.takeaway}</p>
        )}

        {example.prompt && (
          <p className="mt-3 text-sm text-ink-600">
            <span className="font-medium text-ink-800">Beantwoord voor jezelf:</span> {example.prompt}
          </p>
        )}

        <p className="mt-3 text-[11px] text-ink-400">
          p. {example.page_start}
          {example.page_end !== example.page_start && `-${example.page_end}`}
        </p>
      </div>
    </details>
  );
}
