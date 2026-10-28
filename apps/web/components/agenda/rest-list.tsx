"use client";

import Link from "next/link";
import { useState } from "react";


export type RestEntry = {
  key: string;
  label: string;
  /** "staat al in het corpus", "opgehaald", "genegeerd", … */
  stateLabel: string;
  /** Waarom het niet te indexeren is, als dat speelt. */
  note?: string | null;
  inCorpus: boolean;
  /** Gezet als dit teruggehaald kan worden uit de genegeerde hoek. */
  onRestore?: () => void;
  restoreDisabled?: boolean;
};

/** De staart onder "Nieuw op Canvas": wat er al staat, wat je ophaalde en wat
 * je negeerde. Bestanden en pagina's verschilden hier alleen in het woord
 * "bestand" of "pagina". */
export function RestList({ entries, one, many }: { entries: RestEntry[]; one: string; many: string }) {
  const [open, setOpen] = useState(false);
  if (entries.length === 0) return null;

  return (
    <div className="mt-2 text-xs text-ink-400">
      <button type="button" onClick={() => setOpen((current) => !current)} className="underline underline-offset-2">
        {open ? "verberg" : "toon"} {entries.length} {entries.length === 1 ? one : many}
      </button>
      {open && (
        <ul className="mt-2 space-y-1">
          {entries.map((entry) => (
            <li key={entry.key} className="flex flex-wrap items-baseline gap-x-2">
              <span className="text-ink-600">{entry.label}</span>
              <span>{entry.stateLabel}</span>
              {entry.note && <span>({entry.note})</span>}
              {entry.inCorpus && (
                <Link href="/corpus" className="text-primary-600 underline underline-offset-2">
                  corpus
                </Link>
              )}
              {entry.onRestore && (
                <button
                  type="button"
                  disabled={entry.restoreDisabled}
                  onClick={entry.onRestore}
                  className="underline underline-offset-2"
                >
                  toch tonen
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
