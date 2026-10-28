"use client";

import type { ReactNode } from "react";

import { Sources } from "@/components/exam/exam-blocks";
import type { GroupStanding, PrepRule } from "@/lib/types";


function Part({ label, tone = "text-ink-700", children }: { label: string; tone?: string; children: ReactNode }) {
  return (
    <div className="grid gap-0.5 sm:grid-cols-[5.5rem_1fr] sm:gap-3">
      <dt className="text-xs font-medium uppercase tracking-wide text-ink-400 sm:pt-0.5">{label}</dt>
      <dd className={`text-sm ${tone}`}>{children}</dd>
    </div>
  );
}


/** Zo herken je de vraag: per situatie wat je ziet, wat je dan doet, waar de
 * punten zitten en wat de valkuil is. Op volgorde van het tentamen, zodat je
 * hem leest zoals je de vragen vrijdag tegenkomt. "Nieuw" is stof die nog nooit
 * op een oud tentamen stond; daar is het huiswerk de bron. */
export function Rules({ rules, groups }: { rules: PrepRule[]; groups: GroupStanding[] }) {
  const ordered = [...groups].sort((a, b) => a.number - b.number);
  const sections = [
    ...ordered.map((group) => ({
      key: String(group.number),
      title: `${group.number}. ${group.title}`,
      items: rules.filter((rule) => rule.group === group.number),
    })),
    {
      key: "rest",
      title: "Over het hele tentamen",
      items: rules.filter((rule) => rule.group === null || !groups.some((group) => group.number === rule.group)),
    },
  ].filter((section) => section.items.length > 0);

  return (
    <section>
      <h2 className="font-display text-base font-semibold text-ink-900">Zo herken je de vraag</h2>
      <p className="mt-0.5 max-w-3xl text-sm text-ink-500">
        Per type vraag: wat je ziet, wat je dan doet, waar de punten zitten volgens de uitwerkingen, en de valkuil.
        &ldquo;Nieuw&rdquo; stond nog nooit op een oud tentamen; daar is het huiswerk de bron.
      </p>
      <div className="mt-3 space-y-6">
        {sections.map((section) => (
          <div key={section.key}>
            <h3 className="text-xs font-medium uppercase tracking-wide text-ink-500">
              {section.title}
              <span className="ml-2 font-normal normal-case tracking-normal text-ink-400">{section.items.length}</span>
            </h3>
            <ul className="mt-2 space-y-3">
              {section.items.map((rule) => (
                <li key={rule.id} className="rounded-lg border border-ink-100 bg-card p-4">
                  {rule.new && (
                    <span className="mb-2 inline-block rounded-md bg-accent-50 px-1.5 py-0.5 text-[11px] font-medium text-accent-600">
                      nieuw dit jaar
                    </span>
                  )}
                  <dl className="space-y-2">
                    <Part label="Je ziet" tone="text-ink-900">
                      {rule.see}
                    </Part>
                    <Part label="Je doet">{rule.do}</Part>
                    {rule.points && <Part label="Punten">{rule.points}</Part>}
                    {rule.trap && (
                      <Part label="Valkuil" tone="text-accent-600">
                        {rule.trap}
                      </Part>
                    )}
                  </dl>
                  <Sources sources={rule.sources} />
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
    </section>
  );
}
