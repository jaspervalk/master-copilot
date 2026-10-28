"use client";

import { useEffect } from "react";

import { choiceToStore, readStoredTheme, resolveTheme, storeTheme, switchTheme } from "@/lib/theme";


const SYSTEM_DARK = "(prefers-color-scheme: dark)";


/**
 * Eén knop: licht ⇄ donker. Zonder eigen keuze volgt de app het systeem, ook
 * als dat 's avonds omslaat; een klik die afwijkt van het systeem wordt
 * bewaard, een klik terug naar het systeem wist hem weer.
 *
 * Wat er te zien is (maan of zon, en de naam voor een schermlezer) hangt aan de
 * klasse `dark` op <html>, via CSS en niet via React-state: die klasse zet het
 * script in <head> al vóór de eerste verf, en de server weet hem niet. Met
 * state zou de knop eerst het verkeerde icoon tonen, of niet hydrateren.
 */
export function ThemeToggle() {
  useEffect(() => {
    const media = matchMedia(SYSTEM_DARK);
    const follow = () => switchTheme(document.documentElement, resolveTheme(readStoredTheme(), media.matches));
    media.addEventListener("change", follow);
    return () => media.removeEventListener("change", follow);
  }, []);

  function toggle() {
    const next = document.documentElement.classList.contains("dark") ? "light" : "dark";
    switchTheme(document.documentElement, next);
    storeTheme(choiceToStore(next, matchMedia(SYSTEM_DARK).matches));
  }

  return (
    <button
      type="button"
      onClick={toggle}
      title="Licht of donker"
      className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md text-ink-500 hover:bg-ink-50 hover:text-ink-800"
    >
      <span className="sr-only dark:hidden">Zet donker thema aan</span>
      <span className="sr-only hidden dark:inline">Zet licht thema aan</span>
      <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true" className="dark:hidden">
        <path
          d="M15.2 10.9A6.4 6.4 0 0 1 7.1 2.8a6.4 6.4 0 1 0 8.1 8.1Z"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.6"
          strokeLinejoin="round"
        />
      </svg>
      <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true" className="hidden dark:block">
        <circle cx="9" cy="9" r="3.2" fill="none" stroke="currentColor" strokeWidth="1.6" />
        <path
          d="M9 1.6v1.7M9 14.7v1.7M1.6 9h1.7M14.7 9h1.7M3.8 3.8L5 5M13 13l1.2 1.2M3.8 14.2L5 13M13 5l1.2-1.2"
          stroke="currentColor"
          strokeWidth="1.6"
          strokeLinecap="round"
        />
      </svg>
    </button>
  );
}
