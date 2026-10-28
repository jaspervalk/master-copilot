"use client";

import { useSearchParams } from "next/navigation";
import { useRef } from "react";


/** De zoekparameters zoals ze bij binnenkomst waren, één keer.
 *
 * Een console houdt zijn eigen state en schrijft nooit terug naar de URL;
 * de URL stuurt alleen de start — welk vak, welke week, welk tentamen, welke
 * opdracht in de coach — zodat de agenda ergens heen kan wijzen. De aanroeper
 * houdt zelf bij dat hij de parameters al gebruikt heeft. */
export function useInitialParams(): URLSearchParams {
  const params = useSearchParams();
  const initial = useRef<URLSearchParams | null>(null);
  if (initial.current === null) initial.current = new URLSearchParams(params.toString());
  return initial.current;
}
