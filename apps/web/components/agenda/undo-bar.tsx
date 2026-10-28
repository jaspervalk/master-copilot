"use client";

import type { UndoAction } from "@/components/agenda/use-undo";


/** De balk onderaan. Samen met de rij die even blijft staan is dit het hele
 * antwoord op "ik klikte klaar en nu is het weg". */
export function UndoBar({ action, onUndo, onDismiss }: { action: UndoAction | null; onUndo: () => void; onDismiss: () => void }) {
  if (action === null) return null;
  return (
    <div className="pointer-events-none fixed inset-x-0 bottom-6 z-20 flex justify-center px-6">
      <div
        role="status"
        className="pointer-events-auto flex items-center gap-4 rounded-full border border-ink-200 bg-card px-5 py-2.5 text-sm text-ink-700 shadow-lg"
      >
        <span className="truncate">{action.message}</span>
        <button type="button" onClick={onUndo} className="shrink-0 font-medium text-primary-600 underline underline-offset-2 hover:text-primary-500">
          ongedaan maken
        </button>
        <button type="button" onClick={onDismiss} aria-label="Melding sluiten" className="shrink-0 text-ink-300 hover:text-ink-600">
          ×
        </button>
      </div>
    </div>
  );
}
