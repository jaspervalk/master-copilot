"use client";

import { useCallback, useEffect, useRef, useState } from "react";


export type UndoAction = {
  /** De rij waar dit over gaat, zodat de lijst hem kan laten staan. */
  key: string;
  message: string;
  run: () => Promise<unknown>;
};

/** Hoe lang je de tijd krijgt om je te bedenken. Lang genoeg om te zien dat er
 * iets gebeurde, kort genoeg om de rij niet te laten hangen. */
const WINDOW_MS = 10_000;


/** Eén aanbod tegelijk: een nieuwe handeling verdringt de vorige, want twee
 * balken onder elkaar is geen aanbod meer maar een logboek. */
export function useUndo() {
  const [action, setAction] = useState<UndoAction | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const clear = useCallback(() => {
    if (timer.current !== null) clearTimeout(timer.current);
    timer.current = null;
    setAction(null);
  }, []);

  const offer = useCallback(
    (next: UndoAction) => {
      if (timer.current !== null) clearTimeout(timer.current);
      setAction(next);
      timer.current = setTimeout(() => {
        timer.current = null;
        setAction(null);
      }, WINDOW_MS);
    },
    [],
  );

  const undo = useCallback(async () => {
    if (action === null) return;
    clear();
    await action.run();
  }, [action, clear]);

  useEffect(() => () => {
    if (timer.current !== null) clearTimeout(timer.current);
  }, []);

  return { action, offer, undo, clear };
}
