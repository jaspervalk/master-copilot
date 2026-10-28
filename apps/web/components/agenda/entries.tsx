"use client";

import { keyFor } from "@/components/agenda/agenda-state";
import { ItemRow, TaskRow } from "@/components/agenda/deadline-row";
import type { AgendaBucket, AgendaItem, AgendaTask } from "@/lib/types";


export type Entry = { key: string; sort: string; item?: AgendaItem; task?: AgendaTask };

/** Wat een lijst nodig heeft om zijn rijen te tekenen. Nu- en Binnenkort-blok
 * gebruiken dezelfde rijen; alleen de omlijsting verschilt. */
export type EntryHandlers = {
  isPending: (key: string) => boolean;
  /** Rij-sleutel → de bak waar hij stond voor je hem afvinkte. */
  pinned: Record<string, AgendaBucket>;
  onUndoPinned: () => void;
  onToggleItem: (item: AgendaItem, done: boolean) => void;
  onToggleTask: (task: AgendaTask, done: boolean) => void;
  onDeleteTask: (task: AgendaTask) => void;
};

/** Items en taken door elkaar, per plek op datum. De plek komt van de server
 * (`place`): een afgevinkte rij blijft op zijn dag staan tot die voorbij is.
 * `pinned` houdt een rij die van Verlopen naar Afgerond zou springen nog even
 * waar hij stond: hij mag niet stil verdwijnen. */
export function entriesFor(
  bucket: AgendaBucket,
  items: AgendaItem[],
  tasks: AgendaTask[],
  pinned: Record<string, AgendaBucket>,
): Entry[] {
  const entries: Entry[] = [
    ...items
      .filter((item) => (pinned[keyFor.item(item.id)] ?? item.place) === bucket)
      .map((item) => ({ key: item.id, sort: item.deadline_at ?? (item.due_on ? `${item.due_on}T12:00:00Z` : "9999"), item })),
    ...tasks
      .filter((task) => (pinned[keyFor.task(task.id)] ?? task.place) === bucket)
      .map((task) => ({ key: `task:${task.id}`, sort: task.due_on ? `${task.due_on}T12:00:00Z` : "9999", task })),
  ];
  return entries.sort((a, b) => a.sort.localeCompare(b.sort));
}

export function countFor(buckets: AgendaBucket[], items: AgendaItem[], tasks: AgendaTask[], pinned: Record<string, AgendaBucket>): number {
  return buckets.reduce((total, bucket) => total + entriesFor(bucket, items, tasks, pinned).length, 0);
}


export function EntryRows({ entries, handlers }: { entries: Entry[]; handlers: EntryHandlers }) {
  const { isPending, pinned, onUndoPinned, onToggleItem, onToggleTask, onDeleteTask } = handlers;
  return (
    <ul className="divide-y divide-ink-50">
      {entries.map((entry) =>
        entry.item ? (
          <ItemRow
            key={entry.key}
            item={entry.item}
            busy={isPending(keyFor.item(entry.item.id))}
            onUndo={keyFor.item(entry.item.id) in pinned ? onUndoPinned : undefined}
            onToggleDone={onToggleItem}
          />
        ) : entry.task ? (
          <TaskRow
            key={entry.key}
            task={entry.task}
            busy={isPending(keyFor.task(entry.task.id))}
            onUndo={keyFor.task(entry.task.id) in pinned ? onUndoPinned : undefined}
            onToggle={onToggleTask}
            onDelete={onDeleteTask}
          />
        ) : null,
      )}
    </ul>
  );
}
