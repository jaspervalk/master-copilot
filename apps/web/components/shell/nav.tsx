"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";

import { fetchAttention } from "@/lib/api";
import type { Attention } from "@/lib/types";


const items = [
  { href: "/agenda", label: "Agenda" },
  { href: "/", label: "Vragen" },
  { href: "/weken", label: "Weken" },
  { href: "/oefenen", label: "Oefenen" },
  { href: "/tentamen", label: "Tentamen" },
  { href: "/bronnen", label: "Bronnen" },
  { href: "/corpus", label: "Corpus" },
];


/**
 * De balk zegt niet alleen wáár je heen kunt, maar ook waar iets ligt.
 *
 * Twee tellers, allebei uit dezelfde bron als de pagina waar ze naartoe wijzen:
 * hoeveel er vandaag af moet (en wat al te laat is) bij Agenda, en hoeveel
 * kaarten er aan de beurt staan bij Oefenen. Ze worden bij elke paginawissel
 * opnieuw opgehaald — één klein verzoek dat alleen telt, geen Canvas.
 *
 * Geen hamburger op een groot scherm: zeven items passen ruim, en navigatie
 * achter een klik verstoppen kost bij elke wissel tijd zonder iets op te
 * leveren. Onder de `md`-grens past het niet meer, en dan klapt hij wél in.
 */
export function Nav() {
  const pathname = usePathname() || "/";
  const [attention, setAttention] = useState<Attention | null>(null);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    // Mislukt dit, dan staan er gewoon geen tellers; daar hoeft geen
    // foutmelding voor over de pagina.
    fetchAttention().then(setAttention).catch(() => setAttention(null));
  }, [pathname]);

  // Een menu dat open blijft staan na het navigeren is een menu dat in de weg zit.
  useEffect(() => setOpen(false), [pathname]);

  function badge(href: string) {
    if (!attention) return null;
    if (href === "/agenda") {
      const total = attention.today + attention.overdue;
      if (total === 0) return null;
      return <Badge value={total} tone={attention.overdue > 0 ? "accent" : "primary"} />;
    }
    if (href === "/oefenen" && attention.due_cards > 0) {
      return <Badge value={attention.due_cards} tone="primary" />;
    }
    return null;
  }

  function linkClass(href: string) {
    const active = href === "/" ? pathname === "/" : pathname.startsWith(href);
    return `flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium transition ${
      active ? "bg-ink-100 text-ink-900" : "text-ink-500 hover:bg-ink-50 hover:text-ink-800"
    }`;
  }

  function isActive(href: string) {
    return href === "/" ? pathname === "/" : pathname.startsWith(href);
  }

  return (
    <>
      <nav className="hidden items-center gap-1 md:flex">
        {items.map((item) => (
          <Link
            key={item.href}
            href={item.href}
            aria-current={isActive(item.href) ? "page" : undefined}
            className={linkClass(item.href)}
          >
            {item.label}
            {badge(item.href)}
          </Link>
        ))}
      </nav>

      {/* Alleen onder de md-grens: daar passen zes items niet meer naast elkaar. */}
      <div className="relative md:hidden">
        <button
          type="button"
          onClick={() => setOpen((current) => !current)}
          aria-expanded={open}
          aria-label="Menu"
          className="flex items-center gap-2 rounded-md px-2 py-1.5 text-sm font-medium text-ink-600 hover:bg-ink-50"
        >
          <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true">
            <path d="M2 4.5h14M2 9h14M2 13.5h14" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
          </svg>
          {items.find((item) => isActive(item.href))?.label ?? "Menu"}
          {attention && attention.today + attention.overdue + attention.due_cards > 0 && !open && (
            <span className="h-1.5 w-1.5 rounded-full bg-accent-500" aria-hidden="true" />
          )}
        </button>

        {open && (
          <div className="absolute left-0 top-full z-40 mt-1 w-56 rounded-md border border-ink-200 bg-card p-1 shadow-lift">
            {items.map((item) => (
              <Link
                key={item.href}
                href={item.href}
                aria-current={isActive(item.href) ? "page" : undefined}
                className={`flex items-center justify-between rounded px-3 py-2 text-sm ${
                  isActive(item.href) ? "bg-ink-100 text-ink-900" : "text-ink-600 hover:bg-ink-50"
                }`}
              >
                {item.label}
                {badge(item.href)}
              </Link>
            ))}
          </div>
        )}
      </div>
    </>
  );
}


/** Boven de honderd zegt het getal niets meer en wordt de balk rommelig. */
function Badge({ value, tone }: { value: number; tone: "primary" | "accent" }) {
  return (
    <span
      className={`min-w-[1.25rem] rounded-full px-1 text-center text-[11px] font-semibold tabular-nums ${
        tone === "accent" ? "bg-accent-500 text-on-fill" : "bg-primary-500 text-on-fill"
      }`}
    >
      {value > 99 ? "99+" : value}
    </span>
  );
}
