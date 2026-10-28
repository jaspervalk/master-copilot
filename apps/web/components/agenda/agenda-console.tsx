"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { CanvasSection, type CanvasActions } from "@/components/agenda/canvas-section";
import { INFO_DIFFS } from "@/components/agenda/course-panel";
import { DeadlineList } from "@/components/agenda/deadline-list";
import type { EntryHandlers } from "@/components/agenda/entries";
import { NowBlock } from "@/components/agenda/now-block";
import { ExamCards } from "@/components/agenda/exam-cards";
import { TaskForm } from "@/components/agenda/task-form";
import { Banner } from "@/components/ui/banner";
import { Button } from "@/components/ui/button";
import { keyFor, withItem, withMaterial, withPage, withTask, withoutTask } from "@/components/agenda/agenda-state";
import { UndoBar } from "@/components/agenda/undo-bar";
import { useUndo } from "@/components/agenda/use-undo";
import {
  createTask,
  restoreTask,
  deleteTask,
  fetchAgenda,
  fetchAssignmentText,
  fetchCanvasPage,
  fetchMaterial,
  ignoreCanvasPage,
  ignoreMaterial,
  setCourseHidden,
  setItemDone,
  syncCanvas,
  updateTask,
  type TaskInput,
} from "@/lib/api";
import { formatAgo, formatToday } from "@/lib/dates";
import type { Agenda, AgendaBucket, AgendaCourse, AgendaItem, AgendaMaterial, AgendaPage, AgendaTask, DocKind } from "@/lib/types";


export function AgendaConsole() {
  const [agenda, setAgenda] = useState<Agenda | null>(null);
  const [syncing, setSyncing] = useState(false);
  // Per rij, niet één vlag voor de pagina: drie vinkjes achter elkaar zetten
  // moet kunnen zonder dat de tweede knop dood is terwijl de eerste loopt.
  const [pending, setPending] = useState<Record<string, boolean>>({});
  // Voor het handjevol handelingen dat wél de hele pagina raakt.
  const [bulk, setBulk] = useState(false);
  // De bak waar een rij stond vóór je hem afvinkte. Zolang die er staat blijft
  // de rij waar hij was, doorgestreept: afvinken mag niet stil zijn. Dit is
  // géén eigen bucketberekening — alleen uitstel van verplaatsen.
  //
  // Hoogstens één, net als het undo-aanbod: vink je een tweede rij af, dan is
  // het aanbod van de eerste vervallen en zou zijn "ongedaan maken" de
  // verkeerde rij terugdraaien.
  const [pinned, setPinned] = useState<Record<string, AgendaBucket>>({});
  const undo = useUndo();
  const [showTaskForm, setShowTaskForm] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  // Eén keer per bezoek vanzelf verversen als de momentopname oud is; daarna
  // alleen op de knop.
  const autoSynced = useRef(false);

  function fail(cause: unknown) {
    setError(cause instanceof Error ? cause.message : String(cause));
  }

  const load = useCallback(async () => {
    try {
      setAgenda(await fetchAgenda());
      setPinned({});
      setError(null);
    } catch (cause) {
      fail(cause);
    }
  }, []);

  const refresh = useCallback(async () => {
    setSyncing(true);
    setNotice(null);
    try {
      const result = await syncCanvas();
      const parts = [`${result.items} items`, `${result.announcements} aankondigingen`];
      if (result.files_new > 0) parts.push(`${result.files_new} nieuwe bestanden`);
      setNotice(`Bijgewerkt uit Canvas: ${parts.join(", ")}.`);
      await load();
    } catch (cause) {
      fail(cause);
    } finally {
      setSyncing(false);
    }
  }, [load]);

  useEffect(() => {
    void load();
  }, [load]);

  // Het aanbod verloopt na tien seconden in de hook; dan moet de rij ook
  // losgelaten worden, anders blijft hij op zijn oude plek hangen.
  useEffect(() => {
    if (undo.action === null) setPinned({});
  }, [undo.action]);

  useEffect(() => {
    if (!agenda || autoSynced.current) return;
    if (agenda.canvas.configured && agenda.canvas.stale) {
      autoSynced.current = true;
      void refresh();
    }
  }, [agenda, refresh]);

  const mark = (key: string, value: boolean) =>
    setPending((current) => {
      if (!value) {
        const { [key]: _gone, ...rest } = current;
        return rest;
      }
      return { ...current, [key]: true };
    });

  /** Met `apply` wordt het antwoord van de route lokaal ingevoegd; zonder
   * `apply` wordt de hele agenda opnieuw gehaald. Dat laatste is nodig zodra
   * het corpus verandert (diffs, verouderde weekkaarten, de staat van ándere
   * bestanden) of zodra een vak verschijnt of verdwijnt uit de lijst. */
  async function run<T>(key: string, action: () => Promise<T>, apply?: (agenda: Agenda, result: T) => Agenda) {
    mark(key, true);
    setError(null);
    try {
      const result = await action();
      if (apply) setAgenda((current) => (current ? apply(current, result) : current));
      else await load();
    } catch (cause) {
      fail(cause);
    } finally {
      mark(key, false);
    }
  }

  const isPending = (key: string) => bulk || pending[key] === true;

  const unpin = (key: string) => setPinned(({ [key]: _gone, ...rest }) => rest);

  // Deze vier geven het bijgewerkte object terug: lokaal invoegen, niet alles
  // opnieuw halen.
  async function toggleItem(item: AgendaItem, done: boolean) {
    const key = keyFor.item(item.id);
    // Vóór de handeling vastleggen waar de rij stond. Meestal blijft hij daar
    // toch (een afgevinkte rij houdt zijn dag), maar een verlopen rij springt
    // naar Afgerond, en die mag niet stil verdwijnen.
    if (done) setPinned({ [key]: item.place });
    else unpin(key);
    await run(key, () => setItemDone(item.id, done), withItem);
    if (done) {
      undo.offer({
        key,
        message: `${item.title} is afgevinkt.`,
        run: async () => {
          unpin(key);
          await run(key, () => setItemDone(item.id, false), withItem);
        },
      });
    }
  }

  async function toggleTask(task: AgendaTask, done: boolean) {
    const key = keyFor.task(task.id);
    if (done) setPinned({ [key]: task.place });
    else unpin(key);
    await run(key, () => updateTask(task.id, { done }), withTask);
    if (done) {
      undo.offer({
        key,
        message: `${task.title} is afgevinkt.`,
        run: async () => {
          unpin(key);
          await run(key, () => updateTask(task.id, { done: false }), withTask);
        },
      });
    }
  }

  async function removeTask(task: AgendaTask) {
    const key = keyFor.task(task.id);
    await run(key, () => deleteTask(task.id), (current) => withoutTask(current, task.id));
    // Verwijderen is zacht, dus terughalen geeft dezelfde taak terug — ook nog
    // na een herlaadbeurt, al is de balk dan weg.
    undo.offer({
      key,
      message: `${task.title} is verwijderd.`,
      run: () => run(key, () => restoreTask(task.id), withTask),
    });
  }

  async function ignoreMaterialAction(material: AgendaMaterial, ignored: boolean) {
    const key = keyFor.material(material.id);
    await run(key, () => ignoreMaterial(material.id, ignored), withMaterial);
    if (ignored) {
      undo.offer({
        key,
        message: `${material.display_name} wordt niet meer getoond.`,
        run: () => run(key, () => ignoreMaterial(material.id, false), withMaterial),
      });
    }
  }

  async function ignorePageAction(page: AgendaPage, ignored: boolean) {
    const key = keyFor.page(page.id);
    await run(key, () => ignoreCanvasPage(page.id, ignored), withPage);
    if (ignored) {
      undo.offer({
        key,
        message: `${page.title} wordt niet meer getoond.`,
        run: () => run(key, () => ignoreCanvasPage(page.id, false), withPage),
      });
    }
  }

  // Een vak verbergen verandert wélke items in de lijst horen; dat weet alleen
  // de server.
  async function hideCourse(course: AgendaCourse, hidden: boolean) {
    if (course.canvas_id === null) return;
    const canvasId = course.canvas_id;
    const key = keyFor.course(canvasId);
    await run(key, () => setCourseHidden(canvasId, hidden));
    if (hidden) {
      undo.offer({
        key,
        message: `${course.name} is verborgen; ${course.item_count} items staan niet meer in de lijst.`,
        run: () => run(key, () => setCourseHidden(canvasId, false)),
      });
    }
  }

  async function addTask(input: TaskInput) {
    await run("task:nieuw", () => createTask(input), withTask);
    setShowTaskForm(false);
  }

  // Ophalen verandert het corpus, en daarmee diffs, verouderde weekkaarten en
  // de staat van ándere bestanden: hier moet alles opnieuw.
  const fetchMaterialAction = (material: AgendaMaterial, choice: { doc_kind: DocKind; week: number | null }) =>
    run(keyFor.material(material.id), async () => {
      const result = await fetchMaterial(material.id, { doc_kind: choice.doc_kind, week: choice.week });
      setNotice(`${result.document.title} staat in het corpus (${result.chunk_count} stukken).`);
    });
  const fetchSheetFile = (fileId: number) =>
    run(keyFor.material(fileId), async () => {
      const result = await fetchMaterial(fileId);
      setNotice(`${result.document.title} staat in het corpus (${result.chunk_count} stukken).`);
    });
  const fetchPageAction = (page: AgendaPage) =>
    run(keyFor.page(page.id), async () => {
      const result = await fetchCanvasPage(page.id);
      setNotice(`${page.title} staat in het corpus als ${result.document.source_path} (${result.chunk_count} stukken).`);
    });
  const fetchSheetText = (itemId: string) =>
    run(keyFor.item(itemId), async () => {
      const result = await fetchAssignmentText(itemId);
      setNotice(`De opgave staat in het corpus als ${result.document.source_path} (${result.chunk_count} stukken). De coach kan er nu bij.`);
    });

  // Na elkaar, niet tegelijk: elk bestand wordt geïndexeerd, en de embedded
  // index verdraagt één schrijver. Een mislukt bestand stopt de rest niet.
  async function fetchAllMaterials(materials: AgendaMaterial[]) {
    setBulk(true);
    setError(null);
    const failed: string[] = [];
    let fetched = 0;
    for (const [index, material] of materials.entries()) {
      setNotice(`Ophalen ${index + 1} van ${materials.length}: ${material.display_name}`);
      try {
        await fetchMaterial(material.id);
        fetched += 1;
      } catch (cause) {
        failed.push(`${material.display_name}: ${cause instanceof Error ? cause.message : String(cause)}`);
      }
    }
    setNotice(`${fetched} van ${materials.length} bestanden staan in het corpus.`);
    if (failed.length > 0) setError(failed.join(" — "));
    await load();
    setBulk(false);
  }

  const handlers: EntryHandlers = {
    isPending,
    pinned,
    onUndoPinned: () => void undo.undo(),
    onToggleItem: (item, done) => void toggleItem(item, done),
    onToggleTask: (task, done) => void toggleTask(task, done),
    onDeleteTask: (task) => void removeTask(task),
  };

  const canvasActions: CanvasActions = {
    isPending,
    bulk,
    onHide: (course, hidden) => void hideCourse(course, hidden),
    onFetchMaterial: (material, choice) => void fetchMaterialAction(material, choice),
    onFetchAllMaterials: (materials) => void fetchAllMaterials(materials),
    onIgnoreMaterial: (material, ignored) => void ignoreMaterialAction(material, ignored),
    onFetchSheetFile: (fileId) => void fetchSheetFile(fileId),
    onFetchSheetText: (itemId) => void fetchSheetText(itemId),
    onFetchPage: (page) => void fetchPageAction(page),
    onIgnorePage: (page, ignored) => void ignorePageAction(page, ignored),
  };

  const courses = agenda?.courses ?? [];
  const visible = courses.filter((course) => !course.hidden);
  const hidden = courses.filter((course) => course.hidden);
  // Deze lopen uiteen met course.yml en sturen dus de spoilerfilter: ze horen
  // bovenaan, niet achter de dichte Canvas-sectie.
  const warnings = visible.flatMap((course) =>
    course.diffs.filter((diff) => !INFO_DIFFS.includes(diff.kind)).map((diff) => ({ course: course.name, diff })),
  );
  const configured = agenda?.canvas.configured ?? false;

  return (
    <div className="mx-auto max-w-6xl p-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="font-display text-lg font-semibold text-ink-900">Agenda</h1>
          <p className="mt-1 text-sm text-ink-500">
            {formatToday()}. Wat er wanneer af moet, en wat de copilot ervoor heeft.
          </p>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-xs text-ink-400">
            {agenda?.canvas.synced_at
              ? `Canvas bijgewerkt ${formatAgo(agenda.canvas.synced_at)}`
              : configured
                ? "Nog niet bijgewerkt uit Canvas"
                : ""}
          </span>
          <Button size="sm" variant="secondary" onClick={() => void refresh()} disabled={syncing || !configured}>
            {syncing ? "Bezig…" : "Ververs"}
          </Button>
          <Button size="sm" onClick={() => setShowTaskForm((current) => !current)}>
            Nieuwe taak
          </Button>
        </div>
      </header>

      <div className="mt-4 space-y-2">
        {error && <Banner tone="danger">{error}</Banner>}
        {notice && <Banner tone="success">{notice}</Banner>}
        {agenda && !configured && (
          <Banner tone="info">
            Canvas is niet gekoppeld. Zet <code>CANVAS_BASE_URL</code> en <code>CANVAS_ACCESS_TOKEN</code> in{" "}
            <code>.env</code> en start de API opnieuw; tot die tijd werkt de agenda met je eigen taken en course.yml.
          </Banner>
        )}
        {agenda?.problems.map((problem) => (
          <Banner key={problem} tone="warning">
            {problem}
          </Banner>
        ))}
        {warnings.map(({ course, diff }, index) => (
          <Banner key={`${course}:${diff.kind}:${index}`} tone="warning">
            <span className="font-medium">{course}</span> — {diff.message}
          </Banner>
        ))}
      </div>

      {showTaskForm && (
        <div className="mt-4">
          <TaskForm courses={visible} busy={isPending("task:nieuw")} onSubmit={addTask} onCancel={() => setShowTaskForm(false)} />
        </div>
      )}

      {agenda ? (
        <>
          <section className="mt-6">
            <h2 className="font-display text-base font-semibold text-ink-900">Nu</h2>
            <div className="mt-3">
              <NowBlock items={agenda.items} tasks={agenda.tasks} handlers={handlers} onNewTask={() => setShowTaskForm(true)} />
            </div>
          </section>

          <section className="mt-8">
            <h2 className="font-display text-base font-semibold text-ink-900">Binnenkort</h2>
            <div className="mt-3">
              <DeadlineList items={agenda.items} tasks={agenda.tasks} handlers={handlers} />
            </div>
          </section>

          <ExamCards courses={visible} />

          <CanvasSection courses={visible} actions={canvasActions} />
        </>
      ) : (
        <p className="mt-6 text-sm text-ink-400">{error ? "" : "Laden…"}</p>
      )}

      <UndoBar action={undo.action} onUndo={() => void undo.undo()} onDismiss={undo.clear} />

      {hidden.length > 0 && (
        <p className="mt-8 border-t border-ink-100 pt-4 text-xs text-ink-400">
          Verborgen:{" "}
          {hidden.map((course, index) => (
            <span key={course.canvas_id ?? course.name}>
              {index > 0 && ", "}
              {course.name} — {course.item_count === 1 ? "1 item staat" : `${course.item_count} items staan`} niet in de lijst{" "}
              <button
                type="button"
                disabled={course.canvas_id !== null && isPending(keyFor.course(course.canvas_id))}
                onClick={() => void hideCourse(course, false)}
                className="underline underline-offset-2 hover:text-ink-700"
              >
                toon
              </button>
            </span>
          ))}
        </p>
      )}
    </div>
  );
}
