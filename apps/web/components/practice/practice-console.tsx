"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { DeckPicker } from "@/components/practice/deck-picker";
import { DrillRound } from "@/components/practice/drill-round";
import { ExamPicker } from "@/components/practice/exam-picker";
import { SessionPanel } from "@/components/practice/session-panel";
import { WeekProgress } from "@/components/practice/week-progress";
import { Banner } from "@/components/ui/banner";
import { Button } from "@/components/ui/button";
import {
  fetchCards,
  fetchCourses,
  fetchDecks,
  fetchDueCards,
  fetchDueCount,
  fetchExamCards,
  fetchExamPrep,
  fetchExams,
  fetchStudy,
  fillWeek,
  generateCards,
  generateExamSection,
  makeExamples,
} from "@/lib/api";
import { examSetNotice } from "@/lib/exam-plan";
import type { CardKind, CourseSummary, Deck, ExamSet, PracticeCard, Study } from "@/lib/types";
import { useInitialParams } from "@/lib/use-initial-params";


// Wat voor kaarten de generator maakt. De keuze zit bij het genereren, niet
// bij het oefenen: een deck kan alle soorten bevatten.
const KINDS: { value: CardKind; label: string; hint: string }[] = [
  {
    value: "keuze",
    label: "Welke toets",
    hint: "Een verhaal met vier plausibele procedures: welke hoort erbij, en wat moet je controleren? Dit is de vorm van een schriftelijk tentamen.",
  },
  {
    value: "output",
    label: "Wat print dit",
    hint: "Een codefragment uit de stof; jij voorspelt de uitvoer. Het goede antwoord komt van het echt uitvoeren van de code.",
  },
  {
    value: "stats",
    label: "Uitrekenen",
    hint: "Een toets uitvoeren op concrete getallen. Je typt het getal; de uitwerking komt erna.",
  },
  {
    value: "exam",
    label: "Tentamen",
    hint: "Meerkeuze en open vragen in de vorm van het proeftentamen. Open antwoorden worden nagekeken tegen een schema.",
  },
  { value: "code", label: "Code", hint: "Eén NumPy- of pandas-uitdrukking; wordt uitgevoerd en op waarde vergeleken." },
];

const GENERATE_LABEL: Record<CardKind, string> = {
  keuze: "Maak 8 keuzevragen",
  output: "Maak 8 codefragmenten",
  exam: "Maak 8 tentamenvragen",
  code: "Maak 8 kaarten",
  stats: "Maak 8 toetsopgaven",
};

/** Een ronde die niet bij één deck hoort: de ronde van vandaag, herhalen, of
 *  een (deel van een) tentamen. */
type SpecialRound = { key: string; cards: PracticeCard[] };


export function PracticeConsole() {
  const [courses, setCourses] = useState<CourseSummary[]>([]);
  const [courseSlug, setCourseSlug] = useState<string | null>(null);
  const [study, setStudy] = useState<Study | null>(null);
  const [minutes, setMinutes] = useState(25);
  const [decks, setDecks] = useState<Deck[]>([]);
  const [exams, setExams] = useState<ExamSet[]>([]);
  const [dueTotal, setDueTotal] = useState(0);
  const [deck, setDeck] = useState<Deck | null>(null);
  const [cards, setCards] = useState<PracticeCard[]>([]);
  const [kind, setKind] = useState<CardKind>("keuze");
  const [special, setSpecial] = useState<SpecialRound | null>(null);
  // Telt op bij elke speciale ronde. Zonder dat begint een ronde met precies
  // dezelfde kaarten — alles fout gehad — niet opnieuw.
  const [roundCounter, setRoundCounter] = useState(0);
  const [busy, setBusy] = useState(false);
  const [busyWeek, setBusyWeek] = useState<number | null>(null);
  const [generatingExam, setGeneratingExam] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  // /oefenen?course=sso&exam=mock-exam-1[&section=3] of &review=1, vanuit de
  // agenda. Eén keer, zodra het overzicht van dat vak er is.
  const initial = useInitialParams();
  const consumedInitial = useRef(false);

  function fail(cause: unknown) {
    setError(cause instanceof Error ? cause.message : String(cause));
  }

  useEffect(() => {
    fetchCourses()
      .then((list) => {
        setCourses(list);
        const wanted = initial.get("course");
        const start = wanted && list.some((course) => course.slug === wanted) ? wanted : list[0]?.slug;
        if (start) setCourseSlug((current) => current ?? start);
      })
      .catch(fail);
  }, [initial]);

  const loadStudy = useCallback(
    async (slug: string, wanted: number) => {
      try {
        setStudy(await fetchStudy(slug, wanted));
      } catch (cause) {
        fail(cause);
      }
    },
    [],
  );

  useEffect(() => {
    if (!courseSlug) return;
    setDeck(null);
    setCards([]);
    setSpecial(null);
    setStudy(null);
    void loadStudy(courseSlug, minutes);
    Promise.all([fetchDecks(courseSlug), fetchExams(courseSlug), fetchDueCount(courseSlug)])
      .then(([nieuweDecks, nieuweExams, total]) => {
        setDecks(nieuweDecks);
        setExams(nieuweExams);
        setDueTotal(total);
        if (!consumedInitial.current) {
          consumedInitial.current = true;
          if (initial.get("course") === courseSlug) {
            const exam = initial.get("exam");
            const section = initial.get("section");
            if (exam) void openExam(exam, section ? Number(section) : null);
            else if (initial.get("review")) void startReview();
          }
        }
      })
      .catch(fail);
    // openExam en startReview zijn functiedeclaraties hieronder; ze veranderen niet.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [courseSlug, loadStudy]);

  // Een andere tijd betekent een andere ronde; het overzicht eromheen blijft.
  useEffect(() => {
    if (courseSlug && study) void loadStudy(courseSlug, minutes);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [minutes]);

  function refreshOverview() {
    if (!courseSlug) return;
    void loadStudy(courseSlug, minutes);
    Promise.all([fetchDecks(courseSlug), fetchExams(courseSlug), fetchDueCount(courseSlug)])
      .then(([nieuweDecks, nieuweExams, total]) => {
        setDecks(nieuweDecks);
        setExams(nieuweExams);
        setDueTotal(total);
      })
      .catch(() => {
        // Alleen de tellers lopen dan achter; daar hoeft geen foutbalk voor open.
      });
  }

  function startSpecial(key: string, roundCards: PracticeCard[]) {
    setDeck(null);
    setSpecial({ key, cards: roundCards });
    setRoundCounter((current) => current + 1);
  }

  /** De ronde van vandaag: de kaarten staan al in het overzicht. */
  function startSession() {
    if (!study || study.session.cards.length === 0) return;
    setNotice(null);
    setError(null);
    startSpecial("vandaag", study.session.cards.map((item) => item.card));
  }

  async function practiseWeek(week: number) {
    if (!courseSlug) return;
    setNotice(null);
    setError(null);
    try {
      // Dezelfde regels als de ronde van vandaag, maar binnen één week.
      const ronde = await fetchStudy(courseSlug, Math.max(minutes, 45), week);
      if (ronde.session.cards.length === 0) {
        setNotice(ronde.session.notes[0] ?? `Geen kaarten voor week ${week}.`);
        return;
      }
      startSpecial(`week-${week}`, ronde.session.cards.map((item) => item.card));
    } catch (cause) {
      fail(cause);
    }
  }

  async function fillWeekCards(week: number) {
    if (!courseSlug || busyWeek !== null) return;
    setNotice(null);
    setError(null);
    setBusyWeek(week);
    try {
      const result = await fillWeek(courseSlug, week, kind === "exam" ? "keuze" : kind);
      const overgeslagen = result.skipped.map(([topic, reason]) => `${topic} (${reason})`);
      setNotice(
        `Week ${week}: ${result.created} kaarten erbij` +
          (result.topics_done.length > 0 ? ` over ${result.topics_done.join(", ")}` : "") +
          (overgeslagen.length > 0 ? `. Overgeslagen: ${overgeslagen.join("; ")}` : "") +
          (result.rejected.length > 0 ? `. ${result.rejected.length} afgekeurd (${result.rejected[0].reason})` : ""),
      );
      refreshOverview();
    } catch (cause) {
      fail(cause);
    } finally {
      setBusyWeek(null);
    }
  }

  async function makeWeekExamples(week: number) {
    if (!courseSlug || busyWeek !== null) return;
    setNotice(null);
    setError(null);
    setBusyWeek(week);
    try {
      const result = await makeExamples(courseSlug, week);
      const zonderFiguur = result.figure_problems.length;
      setNotice(
        `Week ${week}: ${result.created} voorbeelden erbij` +
          (result.topics_done.length > 0 ? ` over ${result.topics_done.join(", ")}` : "") +
          (zonderFiguur > 0 ? `. ${zonderFiguur} zonder figuur (${result.figure_problems[0][1]})` : "") +
          (result.skipped.length > 0 ? `. Overgeslagen: ${result.skipped.map(([t, r]) => `${t} (${r})`).join("; ")}` : ""),
      );
      refreshOverview();
    } catch (cause) {
      fail(cause);
    } finally {
      setBusyWeek(null);
    }
  }

  async function startReview() {
    if (!courseSlug) return;
    setNotice(null);
    setError(null);
    try {
      const [klaar, total] = await Promise.all([fetchDueCards(courseSlug), fetchDueCount(courseSlug)]);
      setDueTotal(total);
      startSpecial("review", klaar);
      if (klaar.length === 0) {
        setNotice("Niets aan de beurt. Kies een tentamen of een sectie.");
      } else if (total > klaar.length) {
        // Anders klopt de teller in de lijst niet met de lengte van de ronde.
        setNotice(`${klaar.length} van de ${total} — de rest komt in een volgende ronde.`);
      }
    } catch (cause) {
      fail(cause);
    }
  }

  async function openExam(origin: string, section: number | null) {
    if (!courseSlug) return;
    setNotice(null);
    setError(null);
    try {
      const examCards = await fetchExamCards(courseSlug, origin, section);
      startSpecial(section === null ? origin : `${origin}:${section}`, examCards);
      if (section === null) {
        const totaal = examCards.reduce((sum, card) => sum + (card.points ?? 0), 0);
        // Het tempo komt van de tab Tentamen; lukt dat niet, dan zonder tijd.
        const tempo = await fetchExamPrep(courseSlug)
          .then((prep) => prep.minutes_per_point)
          .catch(() => null);
        setNotice(examSetNotice(examCards.length, totaal, tempo));
      }
    } catch (cause) {
      fail(cause);
    }
  }

  async function openDeck(chosen: Deck) {
    if (!courseSlug) return;
    setDeck(chosen);
    setSpecial(null);
    setNotice(null);
    setError(null);
    try {
      setCards(await fetchCards(courseSlug, chosen.section_path));
    } catch (cause) {
      fail(cause);
    }
  }

  async function generate() {
    if (!courseSlug || !deck) return;
    setBusy(true);
    setNotice(null);
    setError(null);
    try {
      const result = await generateCards(courseSlug, deck.section_path, 8, kind);
      setCards(await fetchCards(courseSlug, deck.section_path));
      // Het afkeurrapport is geen ruis: het zegt of het model bruikbare
      // vragen maakt uit deze sectie.
      const afgekeurd = result.rejected.length;
      setNotice(
        `${result.created.length} kaarten erbij` +
          (afgekeurd > 0 ? ` — ${afgekeurd} afgekeurd (${result.rejected[0].reason})` : ""),
      );
      refreshOverview();
    } catch (cause) {
      fail(cause);
    } finally {
      setBusy(false);
    }
  }

  // Een oefententamen neemt de opbouw van het proeftentamen over. Sectie voor
  // sectie, zodat je ziet hoe ver het is en een fout niet alles kost.
  const blueprint = exams.find((exam) => !exam.origin.startsWith("oefententamen-")) ?? null;

  async function makePracticeExam() {
    if (!courseSlug || !blueprint || generatingExam) return;
    setNotice(null);
    setError(null);
    let origin: string | null = null;
    let title = "Oefententamen";
    let gevuld = 0;
    let gepland = 0;
    const kanttekeningen: string[] = [];
    try {
      for (const [index, section] of blueprint.sections.entries()) {
        setGeneratingExam(
          `Sectie ${index + 1} van ${blueprint.sections.length}: ${section.title}… (een halve tot een hele minuut per sectie)`,
        );
        const result = await generateExamSection(courseSlug, section.number, origin);
        origin = result.origin;
        title = result.title;
        gevuld += result.points;
        gepland += result.planned_points;
        if (result.created === 0 && result.source_note) {
          kanttekeningen.push(`sectie ${result.section_number} is leeg gebleven: nog geen stof in je corpus`);
        } else if (result.missing.length > 0) {
          kanttekeningen.push(`sectie ${result.section_number}: ${result.missing.length} vragen konden niet gemaakt worden`);
        }
        // Na elke sectie verversen: het tentamen groeit zichtbaar in de lijst.
        setExams(await fetchExams(courseSlug));
      }
      setNotice(
        `${title} klaar: ${gevuld} van ${gepland} punten.` +
          (kanttekeningen.length > 0 ? ` Let op: ${kanttekeningen.join("; ")}.` : ""),
      );
    } catch (cause) {
      fail(cause);
    } finally {
      setGeneratingExam(null);
      refreshOverview();
    }
  }

  async function makeMissingSection(origin: string, section: number) {
    if (!courseSlug || generatingExam) return;
    setNotice(null);
    setError(null);
    setGeneratingExam(`Sectie ${section} maken…`);
    try {
      const result = await generateExamSection(courseSlug, section, origin);
      setNotice(
        result.created > 0
          ? `${result.title}, sectie ${section}: ${result.created} vragen, ${result.points} van ${result.planned_points} punten.`
          : `Sectie ${section} lukt nog niet: ${result.source_note || "er kwamen geen bruikbare vragen uit"}.`,
      );
    } catch (cause) {
      fail(cause);
    } finally {
      setGeneratingExam(null);
      refreshOverview();
    }
  }

  function onDiscarded(cardId: string) {
    setCards((current) => current.filter((card) => card.id !== cardId));
    setSpecial((current) => current && { ...current, cards: current.cards.filter((card) => card.id !== cardId) });
  }

  function leaveRound() {
    setSpecial(null);
    setDeck(null);
    setCards([]);
    refreshOverview();
  }

  const activeExam = special && !["review", "vandaag"].includes(special.key) ? special.key : null;
  const inRound = (special !== null && special.cards.length > 0) || (deck !== null && cards.length > 0);

  // --- een ronde loopt: alleen de kaart, en een weg terug -------------------

  if (inRound) {
    return (
      <div className="flex h-full min-h-0 flex-col">
        <div className="flex items-center justify-between border-b border-ink-100 px-6 py-2">
          <button
            type="button"
            onClick={leaveRound}
            className="text-sm text-ink-500 underline underline-offset-2 hover:text-ink-800"
          >
            ← Terug naar het overzicht
          </button>
          {notice && <span className="text-xs text-ink-500">{notice}</span>}
        </div>
        {error && <div className="border-b border-rose-200 bg-rose-50 px-6 py-2 text-sm text-rose-800">{error}</div>}
        {special !== null ? (
          <DrillRound
            roundKey={`${special.key}-${roundCounter}`}
            cards={special.cards}
            onDiscarded={onDiscarded}
            onFinished={refreshOverview}
            busy={busy}
          />
        ) : (
          <DrillRound
            roundKey={deck!.section_path}
            cards={cards}
            onDiscarded={onDiscarded}
            onGenerate={generate}
            onFinished={refreshOverview}
            busy={busy}
          />
        )}
      </div>
    );
  }

  // --- overzicht ------------------------------------------------------------

  return (
    <div className="mx-auto max-w-4xl p-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="font-display text-lg font-semibold text-ink-900">Oefenen</h1>
          <p className="mt-0.5 text-sm text-ink-500">
            Wat je nu het beste kunt doen, samengesteld uit je eigen stof.
          </p>
        </div>
        <label className="block">
          <span className="sr-only">Vak</span>
          <select
            value={courseSlug ?? ""}
            onChange={(event) => setCourseSlug(event.target.value || null)}
            className="block rounded-md border border-ink-200 px-2 py-1.5 text-sm"
          >
            {courses.map((course) => (
              <option key={course.slug} value={course.slug}>
                {course.name}
              </option>
            ))}
          </select>
        </label>
      </header>

      <div className="mt-4 space-y-2">
        {error && <Banner tone="danger">{error}</Banner>}
        {notice && <Banner tone="success">{notice}</Banner>}
        {generatingExam && <Banner tone="info">{generatingExam}</Banner>}
      </div>

      {study === null ? (
        <p className="mt-6 text-sm text-ink-400">{error ? "" : "Laden…"}</p>
      ) : (
        <>
          <div className="mt-4">
            <SessionPanel
              session={study.session}
              exam={study.exam}
              pace={study.pace}
              minutes={minutes}
              onMinutes={setMinutes}
              onStart={startSession}
              busy={busy}
            />
          </div>

          {study.totals.cards > 0 && (
            <p className="mt-2 text-xs text-ink-400">
              {study.totals.cards} kaarten in totaal · {study.totals.mastered} beheerst ·{" "}
              {study.totals.new} nog nooit gedaan
              {dueTotal > 0 && (
                <>
                  {" · "}
                  <button
                    type="button"
                    onClick={startReview}
                    className="text-primary-600 underline underline-offset-2 hover:text-primary-500"
                  >
                    alles herhalen wat aan de beurt is ({dueTotal})
                  </button>
                </>
              )}
            </p>
          )}

          <WeekProgress
            weeks={study.weeks}
            courseSlug={study.course_slug}
            onPractise={practiseWeek}
            onFill={fillWeekCards}
            onExamples={makeWeekExamples}
            busyWeek={busyWeek}
          />
        </>
      )}

      {exams.length > 0 && (
        <section className="mt-8">
          <h2 className="font-display text-base font-semibold text-ink-900">Tentamens</h2>
          <div className="mt-2 rounded-lg border border-ink-100 bg-card">
            <ExamPicker
              exams={exams}
              active={activeExam}
              onOpen={openExam}
              onGenerate={blueprint ? makePracticeExam : undefined}
              onGenerateSection={makeMissingSection}
              generating={generatingExam}
            />
          </div>
        </section>
      )}

      <details className="mt-8 rounded-lg border border-ink-100 bg-card">
        <summary className="cursor-pointer px-4 py-3 text-sm font-medium text-ink-700">
          Zelf een sectie kiezen ({decks.length})
        </summary>
        <div className="border-t border-ink-100 px-4 py-3">
          <fieldset>
            <legend className="text-xs font-medium text-ink-600">Soort kaarten</legend>
            <div className="mt-1 flex flex-wrap rounded-md border border-ink-200 p-0.5">
              {KINDS.map((option) => (
                <button
                  key={option.value}
                  type="button"
                  title={option.hint}
                  onClick={() => setKind(option.value)}
                  className={`flex-1 rounded px-2 py-1 text-xs transition ${
                    kind === option.value ? "bg-primary-500 text-on-fill" : "text-ink-600 hover:bg-ink-50"
                  }`}
                >
                  {option.label}
                </button>
              ))}
            </div>
            <p className="mt-1 text-[11px] text-ink-400">{KINDS.find((option) => option.value === kind)?.hint}</p>
          </fieldset>

          <div className="mt-3 max-h-96 overflow-y-auto">
            <DeckPicker
              decks={decks}
              selected={deck}
              onSelect={openDeck}
              dueTotal={dueTotal}
              reviewing={special?.key === "review"}
              onReview={startReview}
            />
          </div>

          {deck && cards.length === 0 && (
            <div className="mt-3 rounded-md border border-dashed border-ink-200 p-4 text-center">
              <p className="text-sm text-ink-600">
                Nog geen kaarten voor {deck.section_path} · p. {deck.page_start}-{deck.page_end}
              </p>
              <Button className="mt-3" size="sm" onClick={generate} disabled={busy}>
                {busy ? "Bezig…" : GENERATE_LABEL[kind]}
              </Button>
            </div>
          )}
        </div>
      </details>
    </div>
  );
}
