"use client";

import { useState } from "react";

import { keyFor } from "@/components/agenda/agenda-state";
import { RestList } from "@/components/agenda/rest-list";
import { Button } from "@/components/ui/button";
import { DOC_KIND_LABELS, KINDS_WITHOUT_WEEK, type AgendaMaterial, type DocKind, type MaterialState } from "@/lib/types";


// Wat je zelf kunt kiezen. Geen uitwerking of inzending: die zet je bewust
// zelf neer, want ze sturen de spoilerfilter.
const CHOOSABLE_KINDS: DocKind[] = ["slides", "exercise", "assignment", "book", "paper", "exam", "note"];
// Zonder week vallen slides buiten elke weekkaart, en heeft een opgavenblad
// geen status. De API weigert ze ook.
const WEEK_REQUIRED: DocKind[] = ["slides", "assignment"];

const REST_LABELS: Record<MaterialState, string> = {
  new: "",
  unplaced: "",
  in_corpus: "staat al in het corpus",
  downloaded: "opgehaald",
  ignored: "genegeerd",
  unsupported: "niet te indexeren",
};

// Leeg zolang je niet gekozen hebt: een vooringevuld soort bij een bestand
// zonder voorstel is precies het raden dat de API weigert.
type Choice = { kind: DocKind | ""; week: string };

function formatSize(bytes: number | null): string {
  if (bytes === null) return "";
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} kB`;
  return `${(bytes / 1024 / 1024).toFixed(1).replace(".", ",")} MB`;
}

function initialChoice(material: AgendaMaterial): Choice {
  if (material.placement) {
    return { kind: material.placement.doc_kind, week: material.placement.week ? String(material.placement.week) : "" };
  }
  return { kind: "", week: "" };
}


export function MaterialsList({
  materials,
  isPending,
  bulk,
  onFetch,
  onFetchAll,
  onIgnore,
}: {
  materials: AgendaMaterial[];
  isPending: (key: string) => boolean;
  bulk: boolean;
  onFetch: (material: AgendaMaterial, choice: { doc_kind: DocKind; week: number | null }) => void;
  /** Alle bestanden met een voorstel, elk op zijn voorgestelde plek. */
  onFetchAll: (materials: AgendaMaterial[]) => void;
  onIgnore: (material: AgendaMaterial, ignored: boolean) => void;
}) {
  const [choices, setChoices] = useState<Record<number, Choice>>({});
  if (materials.length === 0) return null;

  const todo = materials.filter((material) => material.state === "new" || material.state === "unplaced");
  const rest = materials.filter((material) => material.state !== "new" && material.state !== "unplaced");
  const proposed = materials.filter((material) => material.state === "new");
  const choiceFor = (material: AgendaMaterial): Choice => choices[material.id] ?? initialChoice(material);
  const inputClass = "rounded-md border border-ink-200 bg-card px-1.5 py-1 text-xs text-ink-800";

  return (
    <div className="mt-4">
      <div className="flex items-baseline justify-between gap-3">
        <h3 className="text-sm font-medium text-ink-600">
          Nieuw op Canvas
          {todo.length > 0 && <span className="ml-2 text-xs font-normal text-ink-400">{todo.length}</span>}
        </h3>
        {proposed.length > 1 && (
          <button
            type="button"
            disabled={bulk}
            onClick={() => onFetchAll(proposed)}
            className="text-xs text-primary-600 underline underline-offset-2 hover:text-primary-500 disabled:opacity-50"
          >
            Haal alle {proposed.length} voorstellen op
          </button>
        )}
      </div>
      {todo.length === 0 ? (
        <p className="mt-1 text-xs text-ink-400">Alles wat te plaatsen is, staat in het corpus.</p>
      ) : (
        <ul className="mt-2 divide-y divide-ink-50 overflow-hidden rounded-lg border border-ink-100 bg-card">
          {todo.map((material) => {
            const choice = choiceFor(material);
            const kind = choice.kind;
            const weekApplies = kind !== "" && !KINDS_WITHOUT_WEEK.includes(kind);
            const week = weekApplies && choice.week ? Number(choice.week) : null;
            const needsWeek = kind !== "" && WEEK_REQUIRED.includes(kind) && week === null;
            const missing = kind === "" ? "kies een soort" : needsWeek ? "kies een week" : null;
            const busy = isPending(keyFor.material(material.id));
            return (
              <li key={material.id} className="grid grid-cols-[minmax(0,1fr)_auto] items-start gap-4 px-4 py-3">
                <div className="min-w-0">
                  <div className="truncate text-sm text-ink-900">{material.display_name}</div>
                  <div className="text-[11px] text-ink-400">
                    {[material.module_name, material.folder, formatSize(material.size)].filter(Boolean).join(" — ")}
                  </div>
                  {material.placement ? (
                    <div className="mt-1 text-[11px] text-ink-500">
                      <code className="text-ink-700">{material.placement.relative_path}</code>
                      <span className="text-ink-400"> — {material.reason}</span>
                    </div>
                  ) : (
                    <div className="mt-1 text-[11px] text-accent-600">{material.reason}</div>
                  )}
                  <div className="mt-2 flex flex-wrap items-center gap-2 text-[11px] text-ink-500">
                    <select
                      value={kind}
                      onChange={(event) =>
                        setChoices((current) => ({ ...current, [material.id]: { ...choice, kind: event.target.value as DocKind | "" } }))
                      }
                      className={inputClass}
                      aria-label="Soort"
                    >
                      <option value="">soort…</option>
                      {CHOOSABLE_KINDS.map((option) => (
                        <option key={option} value={option}>
                          {DOC_KIND_LABELS[option]}
                        </option>
                      ))}
                    </select>
                    {weekApplies && (
                      <input
                        type="number"
                        min={1}
                        max={60}
                        value={choice.week}
                        placeholder="week"
                        onChange={(event) => setChoices((current) => ({ ...current, [material.id]: { ...choice, week: event.target.value } }))}
                        className={`${inputClass} w-16 ${needsWeek ? "border-accent-400" : ""}`}
                        aria-label="Week"
                        aria-invalid={needsWeek}
                      />
                    )}
                    {missing && <span className="text-accent-600">{missing}</span>}
                  </div>
                </div>
                <div className="flex flex-col items-end gap-1.5">
                  <Button
                    size="sm"
                    variant="secondary"
                    disabled={busy || missing !== null}
                    onClick={() => kind !== "" && onFetch(material, { doc_kind: kind, week })}
                  >
                    Haal op
                  </Button>
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => onIgnore(material, true)}
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
        one="ander bestand"
        many="andere bestanden"
        entries={rest.map((material) => ({
          key: String(material.id),
          label: material.display_name,
          stateLabel: REST_LABELS[material.state],
          note: material.state === "unsupported" ? material.reason : null,
          inCorpus: material.state === "downloaded" || material.state === "in_corpus",
          onRestore: material.state === "ignored" ? () => onIgnore(material, false) : undefined,
          restoreDisabled: isPending(keyFor.material(material.id)),
        }))}
      />
    </div>
  );
}
