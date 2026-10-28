import type { ReactNode } from "react";

import { Nav } from "./nav";
import { ThemeToggle } from "./theme-toggle";


export function AppShell({ children }: { children: ReactNode }) {
  return (
    <div className="flex h-screen flex-col">
      <header className="sticky top-0 z-30 border-b border-ink-100 bg-surface/80 backdrop-blur">
        <div className="flex h-14 items-center justify-between gap-4 px-4 sm:px-6">
          <div className="flex min-w-0 items-center gap-3 lg:gap-6">
            {/* Tussen md en lg past het niet naast zeven items (het brak over twee
                regels); daar gaat het woordmerk weg, naast de hamburger mag hij. */}
            <span className="hidden whitespace-nowrap font-display text-base font-semibold tracking-tight text-ink-900 sm:block md:hidden lg:block">
              Master Copilot
            </span>
            <Nav />
          </div>
          <div className="flex items-center gap-3">
            {/* Verdwijnt als eerste: hij is een bijschrift, geen navigatie. Wie het
                is, staat in apps/web/.env.local, niet in de code: de repo is gedeeld. */}
            {process.env.NEXT_PUBLIC_APP_SUBTITLE ? (
              <span className="hidden text-xs font-medium text-ink-400 lg:block">
                {process.env.NEXT_PUBLIC_APP_SUBTITLE}
              </span>
            ) : null}
            <ThemeToggle />
          </div>
        </div>
      </header>
      <main className="min-h-0 flex-1">{children}</main>
    </div>
  );
}
