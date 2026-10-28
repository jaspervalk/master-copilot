"use client";

import Link from "next/link";
import { useState } from "react";

import { detailLines } from "@/components/agenda/format";
import { Badge } from "@/components/ui/badge";
import { LinkChips } from "@/components/ui/link-chips";
import { formatDateTime, formatDay, formatRelativeDays } from "@/lib/dates";
import { STATUS_LABELS, type AgendaItem, type AgendaStatus, type AgendaTask } from "@/lib/types";


type Tone = "neutral" | "success" | "warning" | "danger" | "accent";

const STATUS_TONE: Record<AgendaStatus, Tone> = {
  locked: "neutral",
  open: "warning",
  submitted: "success",
  late: "warning",
  graded: "success",
  missing: "danger",
  overdue: "danger",
  done: "neutral",
  closed: "neutral",
  upcoming: "neutral",
  past: "neutral",
};

// "Open" en "komt eraan" zijn de gewone gang van zaken; een badge die bij bijna
// elke rij staat zegt niets meer.
const UNREMARKABLE: AgendaStatus[] = ["open", "upcoming"];

// Smal stapelt alles onder het vinkje; vanaf sm staan datum, titel en acties
// naast elkaar. Anders knijpt de vaste datumkolom de titel tot "Assign...".
const rowClass =
  "grid grid-cols-[1.25rem_minmax(0,1fr)] gap-x-3 gap-y-1 px-4 py-2.5 sm:grid-cols-[1.25rem_6.5rem_minmax(0,1fr)_auto] sm:items-start sm:gap-3";
const dateCell = "col-start-2 sm:col-start-2 sm:row-start-1";
const bodyCell = "col-start-2 min-w-0 sm:col-start-3 sm:row-start-1";
const actionCell = "col-start-2 sm:col-start-4 sm:row-start-1";
const linkClass = "text-primary-600 underline underline-offset-2 hover:text-primary-500";
const moreClass = "text-[11px] text-ink-400 underline underline-offset-2 hover:text-ink-700";


export function ItemRow({
  item,
  busy,
  onUndo,
  onToggleDone,
}: {
  item: AgendaItem;
  busy: boolean;
  /** Gezet zolang de rij hier alleen nog staat om ongedaan te maken. */
  onUndo?: () => void;
  onToggleDone: (item: AgendaItem, done: boolean) => void;
}) {
  const [open, setOpen] = useState(false);
  const when = item.deadline_at ? formatDateTime(item.deadline_at) : item.due_on ? formatDay(item.due_on) : "geen datum";
  const finished = item.bucket === "done";
  const justDone = onUndo !== undefined;
  const coachHref =
    item.coach_document_id && item.course_slug
      ? `/?course=${encodeURIComponent(item.course_slug)}&coach=${encodeURIComponent(item.coach_document_id)}`
      : null;
  const details = detailLines(item);
  // Verder weg dan een week is "over 3 weken" ruis; de datum staat er al.
  const relative = item.days_left !== null && Math.abs(item.days_left) <= 7 ? formatRelativeDays(item.days_left) : null;

  return (
    <li className={`${rowClass} ${finished ? "text-ink-400" : ""}`}>
      <div className="pt-0.5">
        {item.tickable || item.status === "done" ? (
          <input
            type="checkbox"
            checked={item.status === "done"}
            disabled={busy}
            onChange={(event) => onToggleDone(item, event.target.checked)}
            aria-label={`Markeer ${item.title} als klaar`}
          />
        ) : null}
      </div>
      <div className={dateCell}>
        <div className={`text-sm tabular-nums ${finished ? "" : "text-ink-800"}`}>{when}</div>
        {!finished && relative && <div className="text-[11px] text-ink-400">{relative}</div>}
      </div>
      <div className={bodyCell}>
        <div className="text-[11px] font-medium text-primary-600">{item.course_name}</div>
        <div className={`truncate text-sm ${justDone || item.status === "done" ? "line-through" : ""} ${finished ? "" : "text-ink-900"}`}>
          {item.html_url ? (
            <a href={item.html_url} target="_blank" rel="noreferrer" className="hover:underline">
              {item.title}
            </a>
          ) : (
            item.title
          )}
        </div>
        {open && (
          <ul className="mt-1 space-y-0.5 text-[11px] text-ink-500">
            {details.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
        )}
      </div>
      <div className={`${actionCell} flex flex-wrap items-center gap-x-3 gap-y-1 sm:flex-col sm:items-end sm:gap-1`}>
        {!UNREMARKABLE.includes(item.status) && <Badge tone={STATUS_TONE[item.status]}>{STATUS_LABELS[item.status]}</Badge>}
        <div className="flex items-center gap-3 text-[11px]">
          {justDone && (
            <button type="button" onClick={onUndo} className={linkClass}>
              ongedaan maken
            </button>
          )}
          {coachHref ? (
            <Link href={coachHref} className={linkClass}>
              Coach
            </Link>
          ) : (
            item.kind === "exam" &&
            item.course_slug && (
              <Link href={`/oefenen?course=${encodeURIComponent(item.course_slug)}`} className={linkClass}>
                Oefenen
              </Link>
            )
          )}
          {details.length > 0 && (
            <button type="button" onClick={() => setOpen((current) => !current)} aria-expanded={open} className={moreClass}>
              {open ? "minder" : "meer"}
            </button>
          )}
        </div>
      </div>
    </li>
  );
}


export function TaskRow({
  task,
  busy,
  onUndo,
  onToggle,
  onDelete,
}: {
  task: AgendaTask;
  busy: boolean;
  onUndo?: () => void;
  onToggle: (task: AgendaTask, done: boolean) => void;
  onDelete: (task: AgendaTask) => void;
}) {
  const [open, setOpen] = useState(false);
  const finished = task.done_at !== null;
  const justDone = onUndo !== undefined;

  return (
    <li className={`${rowClass} ${finished ? "text-ink-400" : ""}`}>
      <div className="pt-0.5">
        <input
          type="checkbox"
          checked={finished}
          disabled={busy}
          onChange={(event) => onToggle(task, event.target.checked)}
          aria-label={`Markeer ${task.title} als klaar`}
        />
      </div>
      <div className={`${dateCell} text-sm tabular-nums ${finished ? "" : "text-ink-800"}`}>
        {task.due_on ? formatDay(task.due_on) : "geen datum"}
      </div>
      <div className={bodyCell}>
        <div className="text-[11px] font-medium text-primary-600">{task.course_slug ?? "eigen taak"}</div>
        <div className={`text-sm ${finished || justDone ? "line-through" : "text-ink-900"}`}>
          {task.link ? (
            <Link href={task.link} className="hover:underline">
              {task.title}
            </Link>
          ) : (
            task.title
          )}
        </div>
        <TaskLinks task={task} />
        {open && (
          <div className="mt-1 space-y-1 text-[11px] text-ink-500">
            {task.notes && <p>{task.notes}</p>}
            {/* Achter "meer", zodat verwijderen niet meer onder de muis ligt. */}
            <button type="button" onClick={() => onDelete(task)} disabled={busy} className="text-accent-600 underline underline-offset-2">
              Verwijder deze taak
            </button>
          </div>
        )}
      </div>
      <div className={`${actionCell} flex items-center gap-3 text-[11px] sm:justify-end`}>
        {justDone && (
          <button type="button" onClick={onUndo} className={linkClass}>
            ongedaan maken
          </button>
        )}
        <button type="button" onClick={() => setOpen((current) => !current)} aria-expanded={open} className={moreClass}>
          {open ? "minder" : "meer"}
        </button>
      </div>
    </li>
  );
}


/** De knoppen onder een taak. Een titel die alleen bij hover onderstreept was
 *  zag er niet uit als iets om op te klikken; elke knop zegt waar hij heen
 *  gaat. Een taak met alleen de oude enkele `link` krijgt één knop "Openen". */
function TaskLinks({ task }: { task: AgendaTask }) {
  const links = task.links.length > 0 ? task.links : task.link ? [{ label: "Openen", href: task.link }] : [];
  return <LinkChips links={links} />;
}
