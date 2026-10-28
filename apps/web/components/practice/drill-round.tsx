"use client";

import { useEffect, useMemo, useState } from "react";

import { AnswerBody } from "@/components/chat/answer-body";
import { Button } from "@/components/ui/button";
import { discardCard, submitAttempt } from "@/lib/api";
import { shuffledOrder } from "@/lib/shuffle";
import type { AttemptResult, PracticeCard } from "@/lib/types";


const LETTERS = "abcdefgh";

/** Tentamenvragen tellen in punten, de rest in goed of fout.
 *
 *  Op de soort alleen kan dat niet: een keuzekaart is óók `mc`, maar hoort bij
 *  een week en niet bij een tentamen. `exam_section` staat alleen op vragen die
 *  uit een (proef)tentamen komen. */
function isExamCard(card: PracticeCard): boolean {
  return (card.kind === "mc" || card.kind === "open") && card.exam_section !== null;
}

function points(value: number): string {
  return Number.isInteger(value) ? String(value) : value.toFixed(1);
}


export function DrillRound({
  roundKey,
  cards,
  onDiscarded,
  onGenerate,
  onFinished,
  busy,
}: {
  /** Verandert dit, dan begint er een nieuwe ronde. */
  roundKey: string;
  cards: PracticeCard[];
  onDiscarded: (cardId: string) => void;
  /** Ontbreekt bij een herhaal- of tentamenronde: die put uit wat er al is. */
  onGenerate?: () => void;
  /** De ronde is uit; de tellers in de lijst kloppen nu niet meer. */
  onFinished?: () => void;
  busy: boolean;
}) {
  const [index, setIndex] = useState(0);
  const [answer, setAnswer] = useState("");
  const [choice, setChoice] = useState<number[]>([]);
  const [result, setResult] = useState<AttemptResult | null>(null);
  const [checking, setChecking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [score, setScore] = useState({ good: 0, total: 0, earned: 0, possible: 0 });

  // Een ander deck begint een nieuwe ronde.
  useEffect(() => {
    setIndex(0);
    setAnswer("");
    setChoice([]);
    setResult(null);
    setScore({ good: 0, total: 0, earned: 0, possible: 0 });
  }, [roundKey]);

  const card = cards[Math.min(index, cards.length - 1)];
  const done = index >= cards.length;

  // Elke keer dat een meerkeuzevraag op het scherm komt een nieuwe volgorde,
  // zodat je het antwoord leert en niet zijn plek. De keuze blijft in de
  // oorspronkelijke indexen: nakijken en de uitleg ("Goed: b") gaan daarover.
  const optionCount = card?.kind === "mc" ? card.options.length : 0;
  const order = useMemo(() => shuffledOrder(optionCount), [card?.id, optionCount, index, roundKey]);

  const ready = card
    ? card.kind === "mc"
      ? choice.length > 0
      : answer.trim().length > 0
    : false;

  async function check() {
    if (!card || !ready || checking) return;
    setChecking(true);
    setError(null);
    try {
      const given = card.kind === "mc" ? choice.map((option) => LETTERS[option]).join(", ") : answer.trim();
      const outcome = await submitAttempt(card.id, given);
      setResult(outcome);
      setScore((current) => ({
        good: current.good + (outcome.correct ? 1 : 0),
        total: current.total + 1,
        earned: current.earned + (outcome.score ?? 0),
        possible: current.possible + (outcome.max_score ?? 0),
      }));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setChecking(false);
    }
  }

  function reset() {
    setResult(null);
    setAnswer("");
    setChoice([]);
  }

  function next() {
    reset();
    setIndex((current) => current + 1);
    if (index + 1 >= cards.length) onFinished?.();
  }

  function toggle(option: number) {
    if (result || !card) return;
    setChoice((current) =>
      card.multi
        ? current.includes(option)
          ? current.filter((item) => item !== option)
          : [...current, option].sort()
        : [option],
    );
  }

  async function discard() {
    if (!card) return;
    try {
      await discardCard(card.id);
      onDiscarded(card.id);
      reset();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    }
  }

  if (done || !card) {
    return (
      <div className="flex flex-1 items-center justify-center p-8">
        <div className="max-w-md text-center">
          <h2 className="font-display text-lg font-semibold text-ink-900">Ronde klaar</h2>
          <p className="mt-2 text-sm text-ink-600">
            {score.good} van {score.total} goed
            {score.possible > 0 && (
              <>
                {" "}· {points(score.earned)} van {points(score.possible)} punten
              </>
            )}
            .
          </p>
          <div className="mt-4 flex justify-center gap-2">
            <Button variant="ghost" onClick={() => setIndex(0)}>
              Opnieuw
            </Button>
            {onGenerate && (
              <Button onClick={onGenerate} disabled={busy}>
                {busy ? "Bezig…" : "Meer kaarten"}
              </Button>
            )}
          </div>
        </div>
      </div>
    );
  }

  const exam = isExamCard(card);

  return (
    <div className="min-h-0 flex-1 overflow-y-auto px-6 py-6">
      <div className="mx-auto flex max-w-2xl flex-col gap-4">
        <div className="flex items-baseline justify-between text-xs text-ink-400">
          <span>
            {card.exam_section ? `${card.exam_section} · ` : ""}vraag {index + 1} van {cards.length}
          </span>
          <span>
            {score.possible > 0
              ? `${points(score.earned)}/${points(score.possible)} punten`
              : `${score.good}/${score.total} goed`}
          </span>
        </div>

        <div className="flex items-start gap-3">
          <div className="min-w-0 flex-1">
            <AnswerBody text={card.question} />
          </div>
          {exam && card.points !== null && (
            <span className="shrink-0 rounded bg-ink-100 px-1.5 py-0.5 text-[11px] font-medium tabular-nums text-ink-600">
              {points(card.points)}p
            </span>
          )}
        </div>

        {card.figure && (
          <pre className="overflow-x-auto whitespace-pre-wrap rounded-md border border-ink-200 bg-ink-50 px-3 py-2 font-mono text-[13px] text-ink-700">
            {card.figure}
          </pre>
        )}

        {card.setup && (
          <pre className="overflow-x-auto rounded-md border border-ink-200 bg-ink-50 px-3 py-2 font-mono text-[13px] text-ink-700">
            {card.setup}
          </pre>
        )}

        {card.kind === "mc" ? (
          <div className="flex flex-col gap-2">
            {card.multi && (
              <p className="text-xs text-ink-500">Meerdere antwoorden kunnen goed zijn — kies ze allemaal.</p>
            )}
            {order.map((optionIndex) => {
              const option = card.options[optionIndex];
              const chosen = (result?.selected ?? choice).includes(optionIndex);
              const right = result?.correct_options.includes(optionIndex) ?? false;
              // Na je poging: groen wat goed was, oranje wat je koos en fout was.
              const tone = result
                ? right
                  ? "border-primary-300 bg-primary-50"
                  : chosen
                    ? "border-accent-300 bg-accent-50"
                    : "border-ink-100 opacity-70"
                : chosen
                  ? "border-primary-400 bg-primary-50"
                  : "border-ink-200 hover:bg-ink-50";
              return (
                <button
                  key={optionIndex}
                  type="button"
                  onClick={() => toggle(optionIndex)}
                  disabled={Boolean(result)}
                  className={`flex items-start gap-3 rounded-md border px-3 py-2 text-left text-sm text-ink-800 transition ${tone}`}
                >
                  <span
                    className={`mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center border text-[11px] font-medium ${
                      card.multi ? "rounded" : "rounded-full"
                    } ${chosen ? "border-primary-500 bg-primary-500 text-on-fill" : "border-ink-300 text-ink-500"}`}
                  >
                    {/* Geen letter tijdens het kiezen: dan onthoud je "b" in
                        plaats van het antwoord. Erna de oorspronkelijke letter,
                        want daar spreekt de uitleg over ("Optie a valt af"). */}
                    {result ? LETTERS[optionIndex] : chosen ? "✓" : ""}
                  </span>
                  <span className="min-w-0">{option}</span>
                </button>
              );
            })}
          </div>
        ) : (
          <textarea
            value={answer}
            onChange={(event) => setAnswer(event.target.value)}
            onKeyDown={(event) => {
              // Bij een open vraag en bij een voorspelde uitvoer is Enter een
              // nieuwe regel — een uitvoer is vaak meer dan één regel.
              // Cmd/Ctrl+Enter controleert. Bij code en toets controleert Enter meteen.
              const multiline = card.kind === "open" || card.kind === "output";
              const submit = multiline ? event.key === "Enter" && (event.metaKey || event.ctrlKey) : event.key === "Enter" && !event.shiftKey;
              if (submit) {
                event.preventDefault();
                if (result) next();
                else check();
              }
            }}
            rows={card.kind === "open" ? 7 : card.kind === "output" ? 4 : 2}
            spellCheck={card.kind === "open"}
            disabled={Boolean(result) && card.kind === "open"}
            placeholder={
              card.kind === "open"
                ? `Schrijf je antwoord zoals op het tentamen${card.max_items ? ` — alleen de eerste ${card.max_items} tellen` : ""}. Cmd+Enter om te controleren.`
                : card.kind === "stats"
                  ? "Typ het getal…"
                  : card.kind === "output"
                    ? "Wat print dit? Typ de uitvoer, regel voor regel. 4 of 4.0 maakt niet uit. Cmd+Enter om te controleren."
                    : "Typ één uitdrukking…"
            }
            className={`w-full resize-y rounded-md border border-ink-200 p-3 text-sm text-ink-800 outline-none focus:border-primary-400 ${
              card.kind === "open" ? "leading-relaxed" : "font-mono"
            }`}
          />
        )}

        {error && <p className="text-xs text-rose-700">{error}</p>}

        {!result ? (
          <div className="flex items-center justify-between">
            <button type="button" onClick={discard} className="text-xs text-ink-400 underline">
              Kaart deugt niet
            </button>
            <Button onClick={check} disabled={checking || !ready}>
              {checking ? (card.kind === "open" ? "Nakijken…" : "Bezig…") : "Controleer"}
            </Button>
          </div>
        ) : (
          <div
            className={`rounded-md border p-4 ${
              result.correct ? "border-primary-200 bg-primary-50" : "border-accent-100 bg-accent-50"
            }`}
          >
            <p className={`text-sm font-medium ${result.correct ? "text-primary-600" : "text-accent-600"}`}>
              {result.max_score !== null && result.score !== null
                ? `${points(result.score)} van ${points(result.max_score)} punten`
                : result.correct
                  ? "Goed"
                  : "Niet goed"}
            </p>

            {card.kind === "open" && result.criteria.length > 0 && (
              <ul className="mt-3 space-y-2">
                {result.criteria.map((item, itemIndex) => (
                  <li key={itemIndex} className="rounded border border-ink-100 bg-card/60 px-3 py-2">
                    <div className="flex items-baseline justify-between gap-3">
                      <span className="text-[13px] text-ink-800">{item.criterion}</span>
                      <span
                        className={`shrink-0 text-xs font-medium tabular-nums ${
                          item.awarded >= item.points ? "text-primary-600" : item.awarded > 0 ? "text-ink-600" : "text-accent-600"
                        }`}
                      >
                        {points(item.awarded)}/{points(item.points)}
                      </span>
                    </div>
                    {item.evidence && !item.withdrawn && (
                      <p className="mt-1 text-xs italic text-ink-500">“{item.evidence}”</p>
                    )}
                    {item.comment && <p className="mt-1 text-xs text-ink-600">{item.comment}</p>}
                  </li>
                ))}
              </ul>
            )}

            {result.feedback && <p className="mt-3 text-sm text-ink-700">{result.feedback}</p>}

            {card.kind === "output" ? (
              <OutputComparison given={answer} printed={result.reference_answer} correct={result.correct} />
            ) : result.error ? (
              <pre className="mt-2 overflow-x-auto font-mono text-[13px] text-rose-700">{result.error}</pre>
            ) : (
              !exam &&
              !result.correct && (
                <dl className="mt-2 space-y-1 font-mono text-[13px]">
                  <div>
                    <dt className="inline text-ink-500">jouw uitkomst: </dt>
                    <dd className="inline text-ink-800">{result.given_repr}</dd>
                  </div>
                  <div>
                    <dt className="inline text-ink-500">verwacht: </dt>
                    <dd className="inline text-ink-800">{result.expected_repr}</dd>
                  </div>
                </dl>
              )
            )}

            {!exam && !result.correct && card.kind !== "output" && (
              <p className="mt-3 font-mono text-[13px] text-ink-700">{result.reference_answer}</p>
            )}

            {/* Het modelantwoord staat er ook bij volle punten: zo zie je hoe
                beknopt het kan, en dat is op een tentamen van twee uur tijd. */}
            {card.kind === "open" && (
              <div className="mt-3 border-t border-ink-100 pt-3">
                <p className="text-[11px] font-medium uppercase tracking-wide text-ink-400">Modelantwoord</p>
                <div className="mt-1">
                  <AnswerBody text={result.reference_answer} />
                </div>
              </div>
            )}

            {/* Bij een toetskaart is de uitwerking de kaart: die hoort er ook
                te staan als je het goed had, want je leert van de route. */}
            {result.explanation && (
              <div className="mt-3 border-t border-ink-100 pt-3">
                <AnswerBody text={result.explanation} />
              </div>
            )}

            <p className="mt-3 text-[11px] text-ink-400">
              {result.material || result.section_path || "onbekende sectie"}
              {!result.material && (
                <>
                  {" "}· p. {result.page_start}
                  {result.page_end !== result.page_start ? `-${result.page_end}` : ""}
                </>
              )}
            </p>

            <div className="mt-3 flex items-center justify-between">
              <button type="button" onClick={discard} className="text-xs text-ink-400 underline">
                Kaart deugt niet
              </button>
              <Button onClick={next}>Volgende</Button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}


/**
 * Wat je voorspelde naast wat het fragment echt printte.
 *
 * Een uitvoer is vaak meer dan één regel; op één regel achter "verwacht:" zie
 * je niet waar het verschil zit. Het rechterblok komt van het uitvoeren van de
 * code, niet van een model.
 */
function OutputComparison({ given, printed, correct }: { given: string; printed: string; correct: boolean }) {
  return (
    <div className="mt-3 grid gap-3 sm:grid-cols-2">
      <div>
        <p className="text-[11px] font-medium uppercase tracking-wide text-ink-400">Jij voorspelde</p>
        <pre
          className={`mt-1 overflow-x-auto rounded-md border px-3 py-2 font-mono text-[13px] ${
            correct ? "border-primary-200 bg-card text-ink-800" : "border-accent-400/40 bg-card text-ink-800"
          }`}
        >
          {given.trim() || "—"}
        </pre>
      </div>
      <div>
        <p className="text-[11px] font-medium uppercase tracking-wide text-ink-400">Het printte</p>
        <pre className="mt-1 overflow-x-auto rounded-md border border-ink-200 bg-ink-50 px-3 py-2 font-mono text-[13px] text-ink-800">
          {printed}
        </pre>
      </div>
    </div>
  );
}
