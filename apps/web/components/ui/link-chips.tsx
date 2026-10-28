import Link from "next/link";


export type LinkChip = { label: string; href: string };

const chipClass =
  "inline-flex items-center gap-1 rounded-md border border-ink-200 bg-card px-2 py-0.5 text-xs text-primary-600 hover:border-primary-200 hover:bg-primary-50";


/** Knoppen naar wat je nodig hebt. Een link die er niet uitziet als een link,
 * bestaat niet: een titel die alleen bij hover onderstreepte, werd niet gezien.
 * Binnen de app via de router; Canvas en de collegeaantekeningen in een nieuw
 * tabblad, zodat de pagina blijft staan. */
export function LinkChips({ links, className = "mt-1.5" }: { links: LinkChip[]; className?: string }) {
  if (links.length === 0) return null;
  return (
    <div className={`flex flex-wrap gap-1.5 ${className}`}>
      {links.map((link, index) =>
        link.href.startsWith("/") ? (
          <Link key={index} href={link.href} className={chipClass}>
            {link.label}
          </Link>
        ) : (
          <a key={index} href={link.href} target="_blank" rel="noreferrer" className={chipClass}>
            {link.label}
            <span aria-hidden="true" className="text-ink-400">
              ↗
            </span>
          </a>
        ),
      )}
    </div>
  );
}
