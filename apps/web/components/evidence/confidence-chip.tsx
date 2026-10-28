"use client";

import { useState } from "react";

import type { Confidence } from "@/lib/types";


const labels: Record<Confidence, string> = {
  low: "laag vertrouwen",
  medium: "redelijk vertrouwen",
  high: "hoog vertrouwen",
};

const tones: Record<Confidence, string> = {
  low: "border-rose-200 bg-rose-50 text-rose-800",
  medium: "border-amber-200 bg-amber-50 text-amber-800",
  high: "border-emerald-200 bg-emerald-50 text-emerald-800",
};


export function ConfidenceChip({
  confidence,
  reasons,
}: {
  confidence: Confidence;
  reasons: string[];
}) {
  const [open, setOpen] = useState(false);

  return (
    <span className="relative inline-block">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        className={`rounded-md border px-2 py-0.5 text-xs font-medium ${tones[confidence]}`}
      >
        {labels[confidence]}
      </button>
      {open && reasons.length > 0 && (
        <span className="absolute bottom-full left-0 z-20 mb-1 block w-72 rounded-md border border-ink-200 bg-card p-2 shadow-lift">
          <ul className="space-y-1 text-xs text-ink-600">
            {reasons.map((reason, index) => (
              <li key={index}>· {reason}</li>
            ))}
          </ul>
        </span>
      )}
    </span>
  );
}
