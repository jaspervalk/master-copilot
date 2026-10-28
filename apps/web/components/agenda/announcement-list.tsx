"use client";

import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { formatDay } from "@/lib/dates";
import type { AgendaAnnouncement } from "@/lib/types";


// Canvas noemt alles "ongelezen" wat je daar nooit hebt aangeklikt, ook een
// bericht uit juli. Nieuw is: ongelezen én van de laatste drie weken.
const RECENT_DAYS = 21;

export function isNew(announcement: AgendaAnnouncement, now: number): boolean {
  if (!announcement.unread || !announcement.posted_at) return false;
  return now - new Date(announcement.posted_at).getTime() < RECENT_DAYS * 86_400_000;
}


export function AnnouncementList({ announcements }: { announcements: AgendaAnnouncement[] }) {
  const [openId, setOpenId] = useState<number | null>(null);
  if (announcements.length === 0) return null;
  const now = Date.now();

  return (
    <div className="mt-4">
      <h3 className="text-sm font-medium text-ink-600">Aankondigingen</h3>
      <ul className="mt-2 divide-y divide-ink-50 overflow-hidden rounded-lg border border-ink-100 bg-card">
        {announcements.map((announcement) => {
          const open = openId === announcement.id;
          return (
            <li key={announcement.id}>
              <button
                type="button"
                onClick={() => setOpenId(open ? null : announcement.id)}
                aria-expanded={open}
                className="flex w-full items-baseline justify-between gap-3 px-4 py-2 text-left transition hover:bg-ink-50"
              >
                <span className="flex min-w-0 items-baseline gap-2">
                  <span className="truncate text-sm text-ink-800">{announcement.title}</span>
                  {isNew(announcement, now) && <Badge tone="accent">nieuw</Badge>}
                </span>
                <span className="shrink-0 text-[11px] text-ink-400">
                  {announcement.posted_at ? formatDay(announcement.posted_at) : ""}
                </span>
              </button>
              {open && (
                <div className="px-4 pb-3">
                  <p className="whitespace-pre-line text-sm text-ink-600">{announcement.body}</p>
                  {announcement.html_url && (
                    <a
                      href={announcement.html_url}
                      target="_blank"
                      rel="noreferrer"
                      className="mt-2 inline-block text-xs text-primary-600 underline underline-offset-2"
                    >
                      Open in Canvas
                    </a>
                  )}
                </div>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
