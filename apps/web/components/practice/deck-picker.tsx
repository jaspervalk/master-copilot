"use client";

import { useState } from "react";

import { SECTION_SEPARATOR } from "@/lib/answer-format";
import type { Deck } from "@/lib/types";


/** Het laatste stuk van het sectiepad is de leesbare naam; de rest is context. */
function split(path: string): { trail: string; leaf: string } {
  const parts = path.split(SECTION_SEPARATOR.trim()).map((part) => part.trim()).filter(Boolean);
  return { trail: parts.slice(0, -1).join(" › "), leaf: parts[parts.length - 1] ?? path };
}


export function DeckPicker({
  decks,
  selected,
  onSelect,
  dueTotal,
  reviewing,
  onReview,
}: {
  decks: Deck[];
  selected: Deck | null;
  onSelect: (deck: Deck) => void;
  dueTotal: number;
  reviewing: boolean;
  onReview: () => void;
}) {
  const [filter, setFilter] = useState("");

  // Een boek levert honderden secties; zonder filter is de lijst onbruikbaar.
  const needle = filter.trim().toLowerCase();
  const shown = needle
    ? decks.filter((deck) => deck.section_path.toLowerCase().includes(needle))
    : decks;

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="border-b border-ink-100 p-4">
        <input
          value={filter}
          onChange={(event) => setFilter(event.target.value)}
          placeholder="Filter op sectie…"
          className="block w-full rounded-md border border-ink-200 px-2 py-1.5 text-sm"
        />
        <p className="mt-1.5 text-[11px] text-ink-400">
          {shown.length} van {decks.length} secties
        </p>
      </div>

      {/* Bovenaan, vóór de secties: wat aan de beurt is gaat vóór wat nieuw is. */}
      <button
        type="button"
        onClick={onReview}
        disabled={dueTotal === 0}
        className={`flex items-center justify-between border-b border-ink-100 px-4 py-3 text-left transition ${
          reviewing ? "bg-primary-50" : dueTotal > 0 ? "hover:bg-ink-50" : "cursor-default"
        }`}
      >
        <span className="text-sm text-ink-800">Herhalen</span>
        <span
          className={`rounded-full px-2 py-0.5 text-[11px] tabular-nums ${
            dueTotal > 0 ? "bg-primary-500 text-on-fill" : "bg-ink-100 text-ink-400"
          }`}
        >
          {dueTotal}
        </span>
      </button>

      <ul className="min-h-0 flex-1 overflow-y-auto">
        {shown.map((deck) => {
          const { trail, leaf } = split(deck.section_path);
          const active = selected?.section_path === deck.section_path;
          return (
            <li key={deck.section_path}>
              <button
                type="button"
                onClick={() => onSelect(deck)}
                className={`block w-full border-b border-ink-50 px-4 py-2.5 text-left transition ${
                  active ? "bg-primary-50" : "hover:bg-ink-50"
                }`}
              >
                {trail && <span className="block truncate text-[11px] text-ink-400">{trail}</span>}
                <span className="block text-sm text-ink-800">{leaf}</span>
                <span className="mt-0.5 block text-[11px] text-ink-400">
                  p. {deck.page_start}-{deck.page_end}
                  {deck.card_count > 0 && (
                    <span className="ml-1.5 text-primary-600">{deck.card_count} kaarten</span>
                  )}
                  {deck.due_count > 0 && (
                    <span className="ml-1.5 text-accent-600">{deck.due_count} aan de beurt</span>
                  )}
                </span>
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
