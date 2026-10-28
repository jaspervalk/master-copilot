"use client";

import Link from "next/link";
import { useId, useState, type ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { formatDay } from "@/lib/dates";
import { examPoints as points, questionBlocks, scenarioCount, scenarioProgress, scenarioResult } from "@/lib/exam-text";
import type {
  ExamPrep,
  ExamSet,
  GroupStanding,
  PrepPattern,
  PrepPrediction,
  PrepScenario,
  PrepSource,
  PrepTactic,
} from "@/lib/types";


function Block({ title, intro, children }: { title: string; intro?: ReactNode; children: ReactNode }) {
  return (
    <section>
      <h2 className="font-display text-base font-semibold text-ink-900">{title}</h2>
      {intro && <p className="mt-0.5 max-w-3xl text-sm text-ink-500">{intro}</p>}
      <div className="mt-3">{children}</div>
    </section>
  );
}


function examHref(courseSlug: string, origin: string, section?: number): string {
  const query = new URLSearchParams({ course: courseSlug, exam: origin });
  if (section !== undefined) query.set("section", String(section));
  return `/oefenen?${query}`;
}


// --- het tentamen in één blik ------------------------------------------------


export function Overview({ prep }: { prep: ExamPrep }) {
  const { exam, facts } = prep;
  return (
    <div className="grid gap-4 rounded-lg border border-ink-100 bg-card p-5 md:grid-cols-[auto_1fr]">
      <div className="md:border-r md:border-ink-100 md:pr-8">
        {exam ? (
          <>
            <span className="font-display text-5xl font-semibold tabular-nums text-ink-900">{exam.days_left}</span>
            <p className="text-sm text-ink-600">
              {exam.days_left === 1 ? "dag" : "dagen"} tot het tentamen
              <span className="block text-ink-400">{formatDay(exam.date)}</span>
            </p>
          </>
        ) : (
          <p className="text-sm text-ink-500">Geen tentamendatum bekend.</p>
        )}
      </div>
      <dl className="grid content-start gap-x-8 gap-y-3 text-sm sm:grid-cols-2">
        {facts?.duration_minutes && (
          <Fact label="Duur">
            {facts.duration_minutes} minuten
            {prep.total_points && <span className="text-ink-400"> voor {points(prep.total_points)} punten</span>}
          </Fact>
        )}
        {prep.minutes_per_point !== null && (
          <Fact label="Tempo">{pace(prep.minutes_per_point, prep.groups)}</Fact>
        )}
        {facts && (
          <Fact label="Mee te nemen">{facts.aids.length > 0 ? facts.aids.join(", ") : "niets"}</Fact>
        )}
        {prep.groups.length > 0 && (
          <Fact label="Opbouw">{structure(prep.groups)}</Fact>
        )}
        {facts && facts.notes.length > 0 && (
          <div className="sm:col-span-2">
            <dt className="text-xs font-medium text-ink-500">Goed om te weten</dt>
            <dd className="mt-1">
              <ul className="list-disc space-y-0.5 pl-5 text-ink-700">
                {facts.notes.map((note, index) => (
                  <li key={index}>{note}</li>
                ))}
              </ul>
            </dd>
          </div>
        )}
      </dl>
    </div>
  );
}

function structure(groups: GroupStanding[]): string {
  const mc = groups.reduce((sum, group) => sum + group.mc, 0);
  const open = groups.reduce((sum, group) => sum + group.open, 0);
  // SSO heeft geen meerkeuze: vier vragen met deelvragen.
  return mc === 0
    ? `${groups.length} vragen met samen ${open} deelvragen`
    : `${groups.length} groepen, ${mc} meerkeuze en ${open} open`;
}

/** "1 minuut per punt" zegt weinig; "een open vraag van 4 punten: 5 minuten"
 * wel. Het voorbeeld is de meest voorkomende waarde van een open vraag in de
 * opbouw, zodat het bij SSO een deelvraag van 0,5 is en geen vraag die niet
 * bestaat. */
function pace(minutesPerPoint: number, groups: GroupStanding[]): string {
  const minutes = (value: number) => {
    const rounded = Math.round(value * minutesPerPoint);
    return rounded <= 1 ? "1 minuut" : `${rounded} minuten`;
  };
  const counts = new Map<number, number>();
  for (const value of groups.flatMap((group) => group.open_points)) counts.set(value, (counts.get(value) ?? 0) + 1);
  const typical = [...counts.entries()].sort((a, b) => b[1] - a[1] || b[0] - a[0])[0]?.[0];
  const parts = [`${points(Math.round(minutesPerPoint * 10) / 10)} minuut per punt`];
  if (typical !== undefined) parts.push(`een open vraag van ${points(typical)} ${typical > 1 ? "punten" : "punt"}: ${minutes(typical)}`);
  const mc = groups.find((group) => group.mc > 0);
  if (mc) parts.push(`meerkeuze (${points(mc.mc_points)} punt): ${minutes(mc.mc_points)}`);
  return parts.join(" · ");
}

function Fact({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div>
      <dt className="text-xs font-medium text-ink-500">{label}</dt>
      <dd className="mt-0.5 text-ink-800">{children}</dd>
    </div>
  );
}


// --- waar liggen je punten ---------------------------------------------------


/** Of een (oefen)tentamen elke groep van de opbouw heeft: dan oefent het het
 * echte tentamen. Het proeftentamen en de eerste oefententamens volgen de
 * opbouw van vorig jaar (vijf secties, netwerken zonder eigen groep). */
function followsLayout(set: ExamSet, groups: GroupStanding[]): boolean {
  const titles = new Set(set.sections.map((section) => section.title));
  return groups.length > 0 && groups.every((group) => titles.has(group.title));
}

/** Het oefententamen waarin je deze groep het best verder kunt oefenen: een
 * sectie met dezelfde titel die je nog niet af hebt, in de opbouw van dit jaar
 * als dat kan; anders de nieuwste. */
function practiceFor(
  group: GroupStanding,
  sets: ExamSet[],
  groups: GroupStanding[],
): { set: ExamSet; number: number } | null {
  const ordered = [...sets.filter((set) => followsLayout(set, groups)), ...sets.filter((set) => !followsLayout(set, groups))];
  const matches = ordered.flatMap((set) =>
    set.sections.filter((section) => section.title === group.title).map((section) => ({ set, section })),
  );
  if (matches.length === 0) return null;
  const open = matches.find(({ section }) => section.answered < section.question_count);
  const chosen = open ?? matches[matches.length - 1];
  return { set: chosen.set, number: chosen.section.number };
}

export function Standings({ prep }: { prep: ExamPrep }) {
  const largest = Math.max(...prep.groups.map((group) => group.points));
  const practiced = prep.groups.some((group) => group.share !== null);
  return (
    <Block
      title="Waar liggen je punten"
      intro={
        practiced
          ? "Per groep: wat hij waard is, wat je bij je laatste pogingen haalde, en wat er dus nog te winnen valt. Het meeste bovenaan."
          : "Per groep wat hij waard is, het meeste bovenaan. Zodra je tentamenvragen maakt, zie je hier ook je score en wat er nog te winnen valt."
      }
    >
      <ol className="divide-y divide-ink-100 overflow-hidden rounded-lg border border-ink-100 bg-card">
        {prep.groups.map((group) => {
          const practice = practiceFor(group, prep.exam_sets, prep.groups);
          return (
            <li key={group.number} className="grid gap-2 px-4 py-3 sm:grid-cols-[1fr_auto] sm:items-center sm:gap-6">
              <div className="min-w-0">
                <p className="text-sm text-ink-800">
                  <span className="mr-1.5 text-ink-400">{group.number}.</span>
                  {group.title}
                </p>
                <div className="mt-1.5 h-1.5 w-full max-w-md rounded-full bg-ink-100" aria-hidden>
                  <div
                    className="relative h-full rounded-full bg-primary-200"
                    style={{ width: `${(group.points / largest) * 100}%` }}
                  >
                    {group.share !== null && (
                      <div
                        className="absolute inset-y-0 left-0 rounded-full bg-primary-600"
                        style={{ width: `${group.share * 100}%` }}
                      />
                    )}
                  </div>
                </div>
                <p className="mt-1 text-xs text-ink-500">
                  {group.mc} meerkeuze · {group.open} open
                  {group.share !== null
                    ? ` · je haalt ${Math.round(group.share * 100)}% (${group.answered} ${group.answered === 1 ? "vraag" : "vragen"})`
                    : " · nog niet geoefend"}
                </p>
              </div>
              <div className="flex items-baseline gap-4 text-sm sm:justify-end">
                <span className="tabular-nums text-ink-800">
                  <span className="font-semibold">{points(group.points)}</span>
                  <span className="text-ink-500"> punten</span>
                </span>
                {group.share !== null && (
                  <span className="tabular-nums text-accent-600">± {points(group.to_gain >= 10 ? Math.round(group.to_gain) : Math.round(group.to_gain * 10) / 10)} te winnen</span>
                )}
                {practice && (
                  <Link
                    href={examHref(prep.course_slug, practice.set.origin, practice.number)}
                    className="text-primary-600 underline underline-offset-2 hover:text-primary-500"
                  >
                    oefen
                  </Link>
                )}
              </div>
            </li>
          );
        })}
      </ol>
    </Block>
  );
}


// --- oefententamens -----------------------------------------------------------


export function ExamSets({ prep }: { prep: ExamPrep }) {
  return (
    <Block title="Oefententamens" intro="Maak ze op papier en op tijd; kijk daarna hier na.">
      <ul className="divide-y divide-ink-100 overflow-hidden rounded-lg border border-ink-100 bg-card">
        {prep.exam_sets.map((set) => (
          <li key={set.origin} className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 px-4 py-2.5 text-sm">
            <span className="flex items-baseline gap-2">
              <Link
                href={examHref(prep.course_slug, set.origin)}
                className="text-primary-600 underline underline-offset-2 hover:text-primary-500"
              >
                {set.title}
              </Link>
              {followsLayout(set, prep.groups) && (
                <span className="rounded-md bg-primary-50 px-1.5 py-0.5 text-[11px] font-medium text-primary-600">
                  opbouw van dit jaar
                </span>
              )}
            </span>
            <span className="text-xs tabular-nums text-ink-500">
              {set.answered > 0
                ? `${points(set.last_score)} van ${points(set.answered_points)} punten · ${set.answered} van ${set.question_count} vragen gemaakt`
                : `${set.question_count} vragen, ${points(set.points)} punten — nog niet gemaakt`}
            </span>
          </li>
        ))}
      </ul>
    </Block>
  );
}


// --- de analyse ---------------------------------------------------------------


export function Sources({ sources }: { sources: PrepSource[] }) {
  const missing = sources.filter((source) => !source.found).length;
  return (
    <details className="group mt-2 text-xs">
      <summary className="cursor-pointer select-none text-ink-400 hover:text-ink-600">
        {sources.length === 1 ? "bron" : `${sources.length} bronnen`}
        {missing > 0 && <span className="ml-1.5 text-accent-600">· {missing} niet teruggevonden</span>}
      </summary>
      <ul className="mt-1.5 space-y-1.5 border-l-2 border-ink-100 pl-3">
        {sources.map((source, index) => (
          <li key={index}>
            {source.href ? (
              <a href={source.href} target="_blank" rel="noreferrer" className="text-primary-600 underline underline-offset-2">
                {source.label} ↗
              </a>
            ) : (
              <span className="text-ink-600">{source.label}</span>
            )}
            <span className="block italic text-ink-500">“{source.quote}”</span>
            {!source.found && <span className="block text-accent-600">{source.reason ?? "niet teruggevonden"}</span>}
          </li>
        ))}
      </ul>
    </details>
  );
}

/**
 * De varianten van een patroon, met twee knoppen die er ook uitzien als knop:
 * oefenen, en de lijst openklappen. Eerst was het een regel "6 scenario's ›"
 * met een pijltje, en daar zag niemand een knop in.
 */
function Scenarios({
  courseSlug,
  scenarios,
  practice,
}: {
  courseSlug: string;
  scenarios: PrepScenario[];
  practice: { origin: string; section: number };
}) {
  const [open, setOpen] = useState(false);
  const listId = useId();
  const progress = scenarioProgress(scenarios);
  return (
    <div className="border-t border-ink-100 pt-3">
      <div className="flex flex-wrap items-center gap-2">
        <Link
          href={examHref(courseSlug, practice.origin, practice.section)}
          className="inline-flex h-8 items-center rounded-md bg-primary-500 px-3 text-sm font-medium text-on-fill hover:bg-primary-600"
        >
          Oefen {scenarios.length === 1 ? "dit scenario" : `alle ${scenarios.length}`}
        </Link>
        <Button
          variant="secondary"
          size="sm"
          aria-expanded={open}
          aria-controls={listId}
          onClick={() => setOpen((current) => !current)}
        >
          {open ? "Verberg" : "Bekijk"} de {scenarioCount(scenarios.length)}
          <span aria-hidden="true" className={`text-ink-400 transition-transform ${open ? "rotate-90" : ""}`}>›</span>
        </Button>
        {progress && <span className="text-xs text-ink-500">{progress}</span>}
      </div>
      {open && (
        <ol id={listId} className="mt-2 divide-y divide-ink-100">
          {scenarios.map((scenario) => (
            <li key={scenario.card_id} className="flex items-baseline justify-between gap-4 py-1.5 text-sm">
              <span className="text-ink-700">{scenario.topic || scenario.question_id}</span>
              <span
                className={`shrink-0 tabular-nums text-xs ${scenario.last_score === null ? "text-ink-400" : "text-ink-600"}`}
              >
                {scenarioResult(scenario)}
              </span>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

export function Patterns({
  courseSlug,
  patterns,
  titles,
}: {
  courseSlug: string;
  patterns: PrepPattern[];
  titles: Map<number, string>;
}) {
  return (
    <Block
      title="Wat zeker terugkomt"
      intro="Vraagtypes die steeds terugkeren in de oude tentamens en in wat de docent liet zien. Onder elk patroon oefen je de varianten die je op het tentamen kunt verwachten."
    >
      <div className="grid gap-3 md:grid-cols-2">
        {patterns.map((pattern) => (
          <article key={pattern.id} className="flex flex-col rounded-lg border border-ink-100 bg-card p-4">
            <div className="flex items-start justify-between gap-3">
              <h3 className="text-sm font-medium text-ink-900">{pattern.title}</h3>
              {pattern.seen !== null && pattern.of !== null && (
                <span
                  className={`shrink-0 rounded-md px-1.5 py-0.5 text-[11px] font-medium tabular-nums ${
                    pattern.seen === 0 ? "bg-accent-50 text-accent-600" : "bg-primary-50 text-primary-600"
                  }`}
                >
                  {pattern.seen === 0 ? "nieuw dit jaar" : `${pattern.seen} van ${pattern.of}`}
                </span>
              )}
            </div>
            {pattern.group !== null && titles.has(pattern.group) && (
              <p className="mt-0.5 text-[11px] text-ink-400">
                {pattern.group}. {titles.get(pattern.group)}
              </p>
            )}
            {pattern.detail && <p className="mt-1.5 text-sm text-ink-600">{pattern.detail}</p>}
            <Sources sources={pattern.sources} />
            {pattern.practice && pattern.scenarios.length > 0 && (
              <>
                {/* Duwt de scenario's naar de onderkant: kaarten naast elkaar eindigen gelijk. */}
                <div className="min-h-3 flex-1" aria-hidden="true" />
                <Scenarios courseSlug={courseSlug} scenarios={pattern.scenarios} practice={pattern.practice} />
              </>
            )}
          </article>
        ))}
      </div>
    </Block>
  );
}

export function Predictions({ predictions, groups }: { predictions: PrepPrediction[]; groups: GroupStanding[] }) {
  // Op volgorde van het tentamen, niet van wat er te winnen valt: zo lees je
  // ze zoals je ze woensdag tegenkomt.
  const ordered = [...groups].sort((a, b) => a.number - b.number);
  const sections = [
    ...ordered.map((group) => ({
      key: String(group.number),
      title: `${group.number}. ${group.title}`,
      items: predictions.filter((item) => item.group === group.number),
    })),
    {
      key: "rest",
      title: ordered.length > 0 ? "Overig" : "",
      items: predictions.filter((item) => item.group === null || !groups.some((group) => group.number === item.group)),
    },
  ].filter((section) => section.items.length > 0);

  return (
    <Block
      title="Voorspelde vragen"
      intro="Nieuwe vragen in de vorm van het tentamen, over wat de docent benadrukte. Schrijf je antwoord eerst op, kijk dan pas."
    >
      <div className="space-y-6">
        {sections.map((section) => (
          <div key={section.key}>
            {section.title && <h3 className="text-xs font-medium uppercase tracking-wide text-ink-500">{section.title}</h3>}
            <ol className="mt-2 space-y-3">
              {section.items.map((item) => (
                <PredictionCard key={item.id} item={item} />
              ))}
            </ol>
          </div>
        ))}
      </div>
    </Block>
  );
}

function PredictionCard({ item }: { item: PrepPrediction }) {
  const [shown, setShown] = useState(false);
  return (
    <li className="rounded-lg border border-ink-100 bg-card p-4">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0 space-y-2 text-sm text-ink-900">
          {questionBlocks(item.question).map((block, index) =>
            block.kind === "code" ? (
              <pre key={index} className="overflow-x-auto rounded-md bg-ink-50 px-3 py-2 font-mono text-xs leading-relaxed text-ink-800">
                {block.text}
              </pre>
            ) : (
              <p key={index} className="whitespace-pre-line">
                {block.text}
              </p>
            ),
          )}
        </div>
        {item.points !== null && (
          <span className="shrink-0 text-xs tabular-nums text-ink-400">
            {points(item.points)} {item.points > 1 ? "punten" : "punt"}
          </span>
        )}
      </div>
      {item.why && <p className="mt-2 text-xs text-ink-500">Waarom: {item.why}</p>}
      <div className="mt-3">
        <button
          type="button"
          onClick={() => setShown((current) => !current)}
          className="text-sm text-primary-600 underline underline-offset-2 hover:text-primary-500"
          aria-expanded={shown}
        >
          {shown ? "Verberg antwoord" : "Toon antwoord"}
        </button>
        {shown && (
          <p className="mt-2 whitespace-pre-line rounded-md bg-ink-50 px-3 py-2 text-sm text-ink-800">{item.answer}</p>
        )}
      </div>
      <Sources sources={item.sources} />
    </li>
  );
}

export function Tactics({ tactics }: { tactics: PrepTactic[] }) {
  return (
    <Block title="Zo haal je de punten" intro="Uit de uitwerkingen, de beoordelingsschema's en wat de docent erover zei.">
      <ol className="space-y-3">
        {tactics.map((tactic, index) => (
          <li key={tactic.id} className="flex gap-3 rounded-lg border border-ink-100 bg-card p-4">
            <span className="font-display text-lg font-semibold tabular-nums text-primary-600">{index + 1}</span>
            <div className="min-w-0">
              <h3 className="text-sm font-medium text-ink-900">{tactic.title}</h3>
              {tactic.detail && <p className="mt-1 text-sm text-ink-600">{tactic.detail}</p>}
              <Sources sources={tactic.sources} />
            </div>
          </li>
        ))}
      </ol>
    </Block>
  );
}
