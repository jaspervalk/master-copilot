"use client";

import { useEffect, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Banner } from "@/components/ui/banner";
import { fetchCourses, fetchLibrary } from "@/lib/api";
import type { CourseSummary, Library, MethodClaim, TopicResources } from "@/lib/types";


/**
 * Twee dingen op één pagina, en ze horen bij elkaar.
 *
 * Boven: waarom het oefenen gaat zoals het gaat, met de studie ernaast. Een
 * programma dat je vertelt wat je moet doen, hoort te laten zien waarop dat
 * berust — en waar het bewijs dun is.
 *
 * Onder: gratis uitleg per onderwerp van jouw weken. Alleen links; het corpus
 * blijft je eigen materiaal, en van de meeste bronnen mag overnemen ook niet.
 */
export function LibraryConsole() {
  const [courses, setCourses] = useState<CourseSummary[]>([]);
  const [courseSlug, setCourseSlug] = useState<string | null>(null);
  const [library, setLibrary] = useState<Library | null>(null);
  const [error, setError] = useState<string | null>(null);

  function fail(cause: unknown) {
    setError(cause instanceof Error ? cause.message : String(cause));
  }

  useEffect(() => {
    fetchCourses()
      .then((list) => {
        setCourses(list);
        if (list[0]) setCourseSlug((current) => current ?? list[0].slug);
      })
      .catch(fail);
  }, []);

  useEffect(() => {
    if (!courseSlug) return;
    setLibrary(null);
    fetchLibrary(courseSlug).then(setLibrary).catch(fail);
  }, [courseSlug]);

  const metBronnen = (library?.topics ?? []).filter((row) => row.resources.length > 0);
  const zonderBronnen = (library?.topics ?? []).filter((row) => row.resources.length === 0);

  return (
    <div className="mx-auto max-w-4xl p-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="font-display text-lg font-semibold text-ink-900">Bronnen</h1>
          <p className="mt-0.5 text-sm text-ink-500">
            Waarom het oefenen zo werkt, en waar je uitleg vindt als de slides te kort zijn.
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

      {error && (
        <div className="mt-4">
          <Banner tone="danger">{error}</Banner>
        </div>
      )}

      <section className="mt-8">
        <h2 className="font-display text-base font-semibold text-ink-900">Hoe deze copilot je laat oefenen</h2>
        <div className="mt-2 space-y-3 text-sm text-ink-600">
          <p>
            De ronde van vandaag wordt niet door jou samengesteld en niet door een model, maar door
            vier regels. Ze staan hieronder met de studie waar ze op steunen, zodat je ze kunt
            nalezen — en kunt wantrouwen waar het bewijs dun is.
          </p>
          <ol className="list-decimal space-y-2 pl-5">
            <li>
              <strong className="font-medium text-ink-800">Je maakt vragen, je leest niet terug.</strong>{" "}
              Antwoord produceren met het boek dicht levert meer op dan herlezen, en het verschil
              groeit naarmate het tentamen verder weg is.
            </li>
            <li>
              <strong className="font-medium text-ink-800">Wat je kende komt later terug, wat je miste meteen.</strong>{" "}
              De afstand tussen twee keer dezelfde kaart groeit — maar nooit verder dan een vijfde van
              de tijd tot je tentamen, want daarna heb je er niets meer aan.
            </li>
            <li>
              <strong className="font-medium text-ink-800">De kaarten staan door elkaar.</strong> Geen twee
              vragen over dezelfde toets achter elkaar. Dat voelt zwaarder dan per college oefenen, en
              dat is precies waarom het werkt: op het tentamen staat er ook niet bij welke toets je
              moet doen.
            </li>
            <li>
              <strong className="font-medium text-ink-800">De voortgang telt wat je kunt, niet wat je deed.</strong>{" "}
              Geen tellertje met bestede minuten of gelezen bladzijden. Een kaart heet pas beheerst na
              drie goede antwoorden op verschillende dagen.
            </li>
          </ol>
        </div>

        {library && (
          <ul className="mt-5 space-y-3">
            {library.method.map((claim) => (
              <MethodRow key={claim.url} claim={claim} />
            ))}
          </ul>
        )}
      </section>

      <section className="mt-10">
        <h2 className="font-display text-base font-semibold text-ink-900">Uitleg per onderwerp</h2>
        <p className="mt-1 text-sm text-ink-500">
          De onderwerpen komen uit je eigen <code className="text-xs">course.yml</code>. Er wordt alleen
          gelinkt — niets hiervan komt in je corpus.
        </p>

        {library === null ? (
          <p className="mt-4 text-sm text-ink-400">{error ? "" : "Laden…"}</p>
        ) : metBronnen.length === 0 ? (
          <p className="mt-4 rounded-lg border border-dashed border-ink-200 px-4 py-8 text-center text-sm text-ink-500">
            Nog geen onderwerpen in de studiewijzer van dit vak.
          </p>
        ) : (
          <>
            <ul className="mt-4 space-y-3">
              {metBronnen.map((row) => (
                <TopicRow key={`${row.week}-${row.topic}`} row={row} />
              ))}
            </ul>
            {zonderBronnen.length > 0 && (
              <p className="mt-4 text-xs text-ink-400">
                Geen externe uitleg gevonden voor: {zonderBronnen.map((row) => row.topic).join(", ")}.
                Aanvullen kan in <code>resources/library.yml</code>.
              </p>
            )}
          </>
        )}
      </section>
    </div>
  );
}


function MethodRow({ claim }: { claim: MethodClaim }) {
  return (
    <li className="border-l-2 border-ink-100 pl-3">
      <p className="text-sm text-ink-800">{claim.claim}</p>
      <p className="mt-0.5 text-xs text-ink-500">
        <a
          href={claim.url}
          target="_blank"
          rel="noreferrer"
          className="text-primary-600 underline underline-offset-2 hover:text-primary-500"
        >
          {claim.source}
        </a>
        {" — "}
        {claim.title}
      </p>
      <p className="mt-0.5 text-[11px] text-ink-400">{claim.strength}</p>
    </li>
  );
}


function TopicRow({ row }: { row: TopicResources }) {
  return (
    <li className="rounded-lg border border-ink-100 bg-card p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="font-display text-sm font-semibold text-ink-900">{row.topic}</h3>
        <span className="text-xs text-ink-400">week {row.week}</span>
      </div>
      <ul className="mt-2 space-y-2">
        {row.resources.map((resource) => (
          <li key={resource.url} className="text-sm">
            <div className="flex flex-wrap items-center gap-2">
              <a
                href={resource.url}
                target="_blank"
                rel="noreferrer"
                className="text-primary-600 underline underline-offset-2 hover:text-primary-500"
              >
                {resource.name}
              </a>
              <Badge>{resource.kind}</Badge>
            </div>
            {resource.note && <p className="mt-0.5 text-xs text-ink-500">{resource.note}</p>}
            <p className="text-[11px] text-ink-400">{resource.license}</p>
          </li>
        ))}
      </ul>
    </li>
  );
}
