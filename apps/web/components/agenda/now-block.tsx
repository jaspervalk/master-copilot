"use client";

import { EntryRows, entriesFor, type Entry, type EntryHandlers } from "@/components/agenda/entries";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { formatRelativeDays } from "@/lib/dates";
import { BUCKET_LABELS, type AgendaBucket, type AgendaItem, type AgendaTask } from "@/lib/types";


/** Wat nu telt. Ongeknipt: een "en nog 4" zou weer een verstopplek zijn. */
export const NOW_BUCKETS: AgendaBucket[] = ["overdue", "today", "tomorrow"];

const TONE: Record<string, string> = {
  overdue: "text-accent-700",
  today: "text-ink-900",
  tomorrow: "text-ink-700",
};


export function NowBlock({
  items,
  tasks,
  handlers,
  onNewTask,
}: {
  items: AgendaItem[];
  tasks: AgendaTask[];
  handlers: EntryHandlers;
  onNewTask: () => void;
}) {
  const groups = NOW_BUCKETS.map((bucket) => ({ bucket, entries: entriesFor(bucket, items, tasks, handlers.pinned) })).filter(
    (group) => group.entries.length > 0,
  );

  if (groups.length === 0) {
    // Het eerstvolgende dat er wél aankomt, zodat "niets" niet leeg voelt.
    const next = items.find((item) => item.bucket === "this_week" || item.bucket === "next_week" || item.bucket === "later");
    return (
      <EmptyState
        className="rounded-lg border border-dashed border-ink-200 px-4 py-10"
        title="Niets dat vandaag of morgen af moet."
        description={
          next && next.days_left !== null
            ? `Daarna: ${next.title} — ${formatRelativeDays(next.days_left)}.`
            : "Ververs uit Canvas, of zet er zelf een taak bij."
        }
        action={
          <Button size="sm" onClick={onNewTask}>
            Nieuwe taak
          </Button>
        }
      />
    );
  }

  return (
    <div className="overflow-hidden rounded-lg border border-ink-100 bg-card">
      {groups.map((group) => (
        <section key={group.bucket}>
          <div className="flex items-baseline gap-2 border-b border-ink-100 bg-ink-50 px-4 py-2">
            <h3 className={`text-sm font-semibold ${TONE[group.bucket] ?? "text-ink-700"}`}>{BUCKET_LABELS[group.bucket]}</h3>
            <span className="text-xs text-ink-400">{countLabel(group.entries)}</span>
          </div>
          <EntryRows entries={group.entries} handlers={handlers} />
        </section>
      ))}
    </div>
  );
}


/** Bij Verlopen staat ook wat je de afgelopen week afrondde, met vinkje. Een kaal
 *  getal zou die meetellen en de bak voller laten lijken dan hij is. */
function countLabel(entries: Entry[]): string {
  const done = entries.filter((entry) => (entry.task ? entry.task.done_at !== null : entry.item?.bucket === "done")).length;
  const open = entries.length - done;
  return done === 0 ? `${open}` : `${open} open · ${done} gedaan`;
}
