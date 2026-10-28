"use client";

import { useState, type FormEvent } from "react";

import { Button } from "@/components/ui/button";
import type { TaskInput } from "@/lib/api";
import type { AgendaCourse } from "@/lib/types";


export function TaskForm({
  courses,
  busy,
  onSubmit,
  onCancel,
}: {
  courses: AgendaCourse[];
  busy: boolean;
  onSubmit: (input: TaskInput) => Promise<void>;
  onCancel: () => void;
}) {
  const [title, setTitle] = useState("");
  const [dueOn, setDueOn] = useState("");
  const [courseSlug, setCourseSlug] = useState("");

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!title.trim()) return;
    await onSubmit({ title: title.trim(), due_on: dueOn || null, course_slug: courseSlug || null });
    setTitle("");
    setDueOn("");
  }

  const inputClass = "rounded-md border border-ink-200 bg-card px-2 py-1.5 text-sm text-ink-800";

  return (
    <form onSubmit={submit} className="flex flex-wrap items-end gap-2 rounded-lg border border-ink-100 bg-card p-3">
      <label className="flex min-w-[16rem] flex-1 flex-col gap-1 text-xs text-ink-500">
        Wat moet er gebeuren?
        <input
          autoFocus
          value={title}
          onChange={(event) => setTitle(event.target.value)}
          maxLength={200}
          placeholder="Sectie 3 van het proeftentamen maken"
          className={inputClass}
        />
      </label>
      <label className="flex flex-col gap-1 text-xs text-ink-500">
        Wanneer
        <input type="date" value={dueOn} onChange={(event) => setDueOn(event.target.value)} className={inputClass} />
      </label>
      <label className="flex flex-col gap-1 text-xs text-ink-500">
        Vak
        <select value={courseSlug} onChange={(event) => setCourseSlug(event.target.value)} className={inputClass}>
          <option value="">geen</option>
          {courses
            .filter((course) => course.course_slug)
            .map((course) => (
              <option key={course.course_slug ?? ""} value={course.course_slug ?? ""}>
                {course.name}
              </option>
            ))}
        </select>
      </label>
      <Button type="submit" size="sm" disabled={busy || !title.trim()}>
        Voeg toe
      </Button>
      <Button type="button" size="sm" variant="ghost" onClick={onCancel}>
        Annuleer
      </Button>
    </form>
  );
}
