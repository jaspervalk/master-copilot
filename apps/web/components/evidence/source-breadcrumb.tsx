import { SECTION_SEPARATOR } from "@/lib/answer-format";


/** Het sectiepad als kruimelpad, met de diepste sectie als de leesbare kop.
 *
 * De paden uit de bladwijzers van een boek zijn lang ("Chapter 3. Data
 * Manipulation with Pandas › Aggregation and Grouping › GroupBy: Split, Apply,
 * Combine"). Op één grijze regel is dat onleesbaar, terwijl juist het laatste
 * stuk zegt waar je moet kijken.
 */
export function SourceBreadcrumb({ path }: { path: string | null }) {
  if (!path) return null;

  const parts = path
    .split(SECTION_SEPARATOR.trim())
    .map((part) => part.trim())
    .filter(Boolean);
  if (parts.length === 0) return null;

  const leaf = parts[parts.length - 1];
  const trail = parts.slice(0, -1);

  return (
    <div className="mt-2">
      {trail.length > 0 && (
        <ol className="flex flex-wrap items-center gap-x-1 gap-y-0.5 text-[11px] text-ink-400">
          {trail.map((part, index) => (
            <li key={`${part}-${index}`} className="flex items-center gap-1">
              <span className="max-w-[16rem] truncate">{part}</span>
              <span aria-hidden className="text-ink-300">
                ›
              </span>
            </li>
          ))}
        </ol>
      )}
      <p className="text-xs font-medium text-ink-700">{leaf}</p>
    </div>
  );
}
