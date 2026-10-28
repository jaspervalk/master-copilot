"use client";

import { keyFor } from "@/components/agenda/agenda-state";
import { RestList } from "@/components/agenda/rest-list";
import { Button } from "@/components/ui/button";
import { formatDay } from "@/lib/dates";
import { DOC_KIND_LABELS, type AgendaPage, type PageState } from "@/lib/types";


const REST_LABELS: Record<PageState, string> = {
  new: "",
  in_corpus: "staat al in het corpus",
  downloaded: "opgehaald",
  ignored: "genegeerd",
};


/** Pagina's uit de modules: lab-instructies, een afleiding bij een college, het
 * rooster met huiswerkopgaven. Een pagina heeft altijd een plek (een notitie
 * mag bij het hele vak horen), dus er valt niets te kiezen: ophalen of negeren. */
export function PagesList({
  pages,
  isPending,
  bulk,
  onFetch,
  onIgnore,
}: {
  pages: AgendaPage[];
  isPending: (key: string) => boolean;
  /** Ophalen van álle voorstellen blokkeert de hele sectie. */
  bulk: boolean;
  onFetch: (page: AgendaPage) => void;
  onIgnore: (page: AgendaPage, ignored: boolean) => void;
}) {
  if (pages.length === 0) return null;

  const todo = pages.filter((page) => page.state === "new");
  const rest = pages.filter((page) => page.state !== "new");

  return (
    <div className="mt-4">
      <h3 className="text-sm font-medium text-ink-600">
        Pagina&apos;s op Canvas
        {todo.length > 0 && <span className="ml-2 text-xs font-normal text-ink-400">{todo.length}</span>}
      </h3>
      {todo.length === 0 ? (
        <p className="mt-1 text-xs text-ink-400">Alle pagina&apos;s staan in het corpus of zijn genegeerd.</p>
      ) : (
        <ul className="mt-2 divide-y divide-ink-50 overflow-hidden rounded-lg border border-ink-100 bg-card">
          {todo.map((page) => {
            const busy = bulk || isPending(keyFor.page(page.id));
            return (
            <li key={page.id} className="grid grid-cols-[minmax(0,1fr)_auto] items-start gap-4 px-4 py-3">
              <div className="min-w-0">
                <div className="truncate text-sm text-ink-900">{page.title}</div>
                <div className="text-[11px] text-ink-400">
                  {[page.module_name, page.updated_at ? `bijgewerkt ${formatDay(page.updated_at)}` : null]
                    .filter(Boolean)
                    .join(" — ")}
                </div>
                {page.placement && (
                  <div className="mt-1 text-[11px] text-ink-500">
                    <span className="text-ink-600">{DOC_KIND_LABELS[page.placement.doc_kind]}</span>{" "}
                    <code className="text-ink-700">{page.placement.relative_path}</code>
                    <span className="text-ink-400"> — {page.reason}</span>
                  </div>
                )}
              </div>
              <div className="flex flex-col items-end gap-1.5">
                <Button size="sm" variant="secondary" disabled={busy} onClick={() => onFetch(page)}>
                  Haal op
                </Button>
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => onIgnore(page, true)}
                  className="text-[11px] text-ink-400 underline underline-offset-2 hover:text-ink-700"
                >
                  negeer
                </button>
              </div>
            </li>
            );
          })}
        </ul>
      )}
      <RestList
        one="andere pagina"
        many="andere pagina's"
        entries={rest.map((page) => ({
          key: page.id,
          label: page.title,
          stateLabel: REST_LABELS[page.state],
          inCorpus: page.state === "downloaded" || page.state === "in_corpus",
          onRestore: page.state === "ignored" ? () => onIgnore(page, false) : undefined,
          restoreDisabled: bulk || isPending(keyFor.page(page.id)),
        }))}
      />
    </div>
  );
}
