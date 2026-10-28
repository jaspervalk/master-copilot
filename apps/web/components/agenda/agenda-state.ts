/** Het agenda-object bijwerken met wat een route terugstuurde.
 *
 * De server rekent status en bucket uit — in Europe/Amsterdam, en bij een
 * tentamen met regels die hier niet thuishoren. Het antwoord van een PATCH is
 * dus compleet: we vervangen het hele object op zijn id en schrijven nooit
 * losse velden bij, want dan zou de client alsnog gaan rekenen.
 */
import type { Agenda, AgendaItem, AgendaMaterial, AgendaPage, AgendaTask } from "@/lib/types";


export function withItem(agenda: Agenda, item: AgendaItem): Agenda {
  return { ...agenda, items: agenda.items.map((current) => (current.id === item.id ? item : current)) };
}

export function withTask(agenda: Agenda, task: AgendaTask): Agenda {
  const known = agenda.tasks.some((current) => current.id === task.id);
  return {
    ...agenda,
    tasks: known ? agenda.tasks.map((current) => (current.id === task.id ? task : current)) : [...agenda.tasks, task],
  };
}

export function withoutTask(agenda: Agenda, taskId: string): Agenda {
  return { ...agenda, tasks: agenda.tasks.filter((current) => current.id !== taskId) };
}

/** Bestanden en pagina's hangen onder hun vak, niet in een platte lijst. */
export function withMaterial(agenda: Agenda, material: AgendaMaterial): Agenda {
  return {
    ...agenda,
    courses: agenda.courses.map((course) => ({
      ...course,
      materials: course.materials.map((current) => (current.id === material.id ? material : current)),
    })),
  };
}

export function withPage(agenda: Agenda, page: AgendaPage): Agenda {
  return {
    ...agenda,
    courses: agenda.courses.map((course) => ({
      ...course,
      pages: course.pages.map((current) => (current.id === page.id ? page : current)),
    })),
  };
}


/** De sleutels waarop "deze rij is bezig" hangt. Eén plek, zodat de console en
 * de lijsten dezelfde sleutel bouwen. */
export const keyFor = {
  item: (id: string) => `item:${id}`,
  task: (id: string) => `task:${id}`,
  material: (id: number) => `material:${id}`,
  page: (id: string) => `page:${id}`,
  course: (canvasId: number) => `course:${canvasId}`,
};
