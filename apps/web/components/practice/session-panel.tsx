"use client";

import { Button } from "@/components/ui/button";
import type { Pace, StudyExam, StudySession } from "@/lib/types";


/** Wat je kunt kiezen. "Eigen tijd" bestaat niet: een getal typen kost meer
 *  aandacht dan het waard is, en deze drie dekken een dag. */
const MINUTES = [15, 25, 45];

function countdown(days: number): string {
  if (days === 0) return "vandaag";
  if (days === 1) return "morgen";
  return `over ${days} dagen`;
}


/**
 * Het blok "Vandaag": hoeveel tijd je hebt, wat er dan in past, en waarom.
 *
 * De samenstelling staat er expliciet bij. Niet als opsmuk: een ronde door
 * elkaar voelt zwaarder dan een ronde per college, en dat is precies de
 * bedoeling — wie dat niet weet, denkt dat het systeem stuk is en zet het uit.
 */
export function SessionPanel({
  session,
  exam,
  pace,
  minutes,
  onMinutes,
  onStart,
  busy,
}: {
  session: StudySession;
  exam: StudyExam | null;
  pace: Pace | null;
  minutes: number;
  onMinutes: (value: number) => void;
  onStart: () => void;
  busy: boolean;
}) {
  const procedures = new Set(
    session.cards.map((item) => item.procedure ?? item.topic ?? `week ${item.card.week ?? "?"}`),
  );
  const heeftKaarten = session.cards.length > 0;

  return (
    <section className="rounded-lg border border-ink-100 bg-card p-5">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h2 className="font-display text-base font-semibold text-ink-900">Vandaag</h2>
          <p className="mt-1 text-sm text-ink-500">
            {heeftKaarten
              ? `${session.cards.length} kaarten, ongeveer ${Math.round(session.estimated_minutes)} minuten.`
              : "Niets klaargezet."}
          </p>
        </div>

        <div className="flex rounded-md border border-ink-200 p-0.5" role="group" aria-label="Hoeveel tijd">
          {MINUTES.map((value) => (
            <button
              key={value}
              type="button"
              onClick={() => onMinutes(value)}
              className={`rounded px-3 py-1 text-xs transition ${
                minutes === value ? "bg-primary-500 text-on-fill" : "text-ink-600 hover:bg-ink-50"
              }`}
            >
              {value} min
            </button>
          ))}
        </div>
      </div>

      {heeftKaarten && (
        <dl className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
          <Teller label="vorige keer fout" value={session.counts.zwak} tone="accent" />
          <Teller label="herhalen" value={session.counts.herhalen} tone="primary" />
          <Teller label="nieuw" value={session.counts.nieuw} tone="ink" />
          <Teller label="onderwerpen door elkaar" value={procedures.size} tone="ink" />
        </dl>
      )}

      {pace && <PaceLine pace={pace} />}

      {session.notes.map((note) => (
        <p key={note} className="mt-3 text-sm text-ink-500">
          {note}
        </p>
      ))}

      <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
        <p className="max-w-lg text-xs text-ink-400">
          De kaarten staan door elkaar, niet per college. Dat voelt moeilijker en dat hoort: op het
          tentamen staat er ook niet bij welke toets je moet doen.
        </p>
        <div className="flex items-center gap-3">
          {exam && (
            <span className="text-xs text-ink-500">
              {exam.name} {countdown(exam.days_left)}
            </span>
          )}
          <Button onClick={onStart} disabled={!heeftKaarten || busy}>
            {busy ? "Bezig…" : "Begin"}
          </Button>
        </div>
      </div>
    </section>
  );
}


function Teller({ label, value, tone }: { label: string; value: number; tone: "accent" | "primary" | "ink" }) {
  const kleur = tone === "accent" ? "text-accent-600" : tone === "primary" ? "text-primary-600" : "text-ink-700";
  return (
    <div>
      <dd className={`font-display text-2xl font-semibold tabular-nums ${value === 0 ? "text-ink-300" : kleur}`}>
        {value}
      </dd>
      <dt className="text-[11px] uppercase tracking-wide text-ink-400">{label}</dt>
    </div>
  );
}


/**
 * Of dit tempo genoeg is, in één regel.
 *
 * Van alles wat er over leren te vinden is, weegt dit over vier weken het
 * zwaarst: niet hoe slim de planning is, maar of élke kaart vóór het tentamen
 * twee keer op afstand goed is gegaan. Dat is te rekenen, dus het staat er.
 *
 * De som rekent alsof je alles goed hebt, en dat zeggen we er ook bij — een
 * schatting die te rooskleurig is zonder dat je het weet, is erger dan geen.
 */
function PaceLine({ pace }: { pace: Pace }) {
  if (pace.reviews_needed === 0) {
    return (
      <p className="mt-3 rounded-md bg-primary-50 px-3 py-2 text-sm text-ink-700">
        Alles is minstens twee keer goed gegaan. Van nu af houdt herhalen het vast.
      </p>
    );
  }

  const dagen = pace.days_left === 1 ? "nog één dag" : `nog ${pace.days_left} dagen`;

  return (
    <p
      className={`mt-3 rounded-md px-3 py-2 text-sm ${
        pace.feasible ? "bg-primary-50 text-ink-700" : "bg-accent-50 text-ink-800"
      }`}
    >
      {pace.feasible ? (
        <>
          <strong className="font-medium">Dit tempo is genoeg.</strong> {dagen} tot {pace.exam_name}, en{" "}
          {pace.reviews_needed} beurten te gaan — bij {pace.minutes} minuten per dag haal je er ongeveer{" "}
          {pace.reviews_possible}.
        </>
      ) : (
        <>
          <strong className="font-medium">
            Bij {pace.minutes} minuten per dag red je het niet.
          </strong>{" "}
          {dagen} tot {pace.exam_name} en {pace.reviews_needed} beurten te gaan; in {pace.minutes} minuten
          per dag haal je er ongeveer {pace.reviews_possible}. Reken op{" "}
          <strong className="font-medium">{pace.minutes_per_day_needed} minuten per dag</strong>.
        </>
      )}{" "}
      <span className="text-ink-400">
        Gerekend alsof je alles goed hebt; een fout kost een extra beurt.
      </span>
    </p>
  );
}
