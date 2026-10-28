"use client";

import { useState } from "react";

import { EntryRows, entriesFor, type EntryHandlers } from "@/components/agenda/entries";
import { EmptyState } from "@/components/ui/empty-state";
import { BUCKET_LABELS, type AgendaBucket, type AgendaItem, type AgendaTask } from "@/lib/types";


/** Alles ná morgen; wat nu telt staat in het Nu-blok en mag niet dubbel staan. */
export const LATER_BUCKETS: AgendaBucket[] = ["this_week", "next_week", "later", "undated"];

// Verder dan volgende week hoef je niet te zien om te weten wat er speelt.
const COLLAPSED_BY_DEFAULT: AgendaBucket[] = ["later", "undated"];

// Genoeg om de afgelopen dagen terug te zien; de cijfers van september staan
// achter "toon alle".
const RECENT_DONE = 8;


export function DeadlineList({
  items,
  tasks,
  handlers,
}: {
  items: AgendaItem[];
  tasks: AgendaTask[];
  handlers: EntryHandlers;
}) {
  const [opened, setOpened] = useState<Partial<Record<AgendaBucket, boolean>>>({});
  const [showAllDone, setShowAllDone] = useState(false);

  const groups = LATER_BUCKETS.map((bucket) => ({ bucket, entries: entriesFor(bucket, items, tasks, handlers.pinned) })).filter(
    (group) => group.entries.length > 0,
  );
  // Nieuwste eerst: wat je deze week deed is wat je wil terugzien.
  const done = entriesFor("done", items, tasks, handlers.pinned).reverse();
  const shownDone = showAllDone ? done : done.slice(0, RECENT_DONE);

  if (groups.length === 0 && done.length === 0) {
    return (
      <EmptyState
        className="rounded-lg border border-dashed border-ink-200 px-4 py-8"
        title="Verder staat er niets."
        description="Ververs uit Canvas, of voeg een taak toe."
      />
    );
  }

  return (
    <div className="overflow-hidden rounded-lg border border-ink-100 bg-card">
      {groups.map((group) => {
        const collapsed = COLLAPSED_BY_DEFAULT.includes(group.bucket) && !opened[group.bucket];
        return (
          <section key={group.bucket}>
            <div className="flex items-baseline justify-between gap-3 border-b border-ink-100 bg-ink-50 px-4 py-2">
              <h3 className="text-sm font-medium text-ink-700">
                {BUCKET_LABELS[group.bucket]}
                <span className="ml-2 text-xs font-normal text-ink-400">{group.entries.length}</span>
              </h3>
              {COLLAPSED_BY_DEFAULT.includes(group.bucket) && (
                <button
                  type="button"
                  onClick={() => setOpened((current) => ({ ...current, [group.bucket]: collapsed }))}
                  className="text-xs text-primary-600 underline underline-offset-2"
                >
                  {collapsed ? "toon" : "verberg"}
                </button>
              )}
            </div>
            {!collapsed && <EntryRows entries={group.entries} handlers={handlers} />}
          </section>
        );
      })}

      {/* Afgerond is wat vóór vandaag af was; wat je vandaag of later afvinkt
          blijft op zijn dag staan. Open, want hier zie je terug wat je deed —
          ingeklapt was een afgevinkte rij voor wie hem afvinkte gewoon weg. */}
      {done.length > 0 && (
        <section className="border-t border-ink-100">
          <div className="flex items-baseline justify-between gap-3 border-b border-ink-100 bg-ink-50 px-4 py-2">
            <h3 className="text-sm font-medium text-ink-700">
              {BUCKET_LABELS.done}
              <span className="ml-2 text-xs font-normal text-ink-400">{done.length}</span>
            </h3>
            {done.length > RECENT_DONE && (
              <button
                type="button"
                onClick={() => setShowAllDone((current) => !current)}
                className="text-xs text-primary-600 underline underline-offset-2"
              >
                {showAllDone ? "alleen de laatste" : `toon alle ${done.length}`}
              </button>
            )}
          </div>
          <EntryRows entries={shownDone} handlers={handlers} />
        </section>
      )}
    </div>
  );
}
