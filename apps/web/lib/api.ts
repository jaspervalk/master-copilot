import type {
  Agenda,
  Attention,
  AgendaItem,
  AgendaMaterial,
  AgendaPage,
  AgendaTask,
  CanvasSyncResult,
  AnswerLanguage,
  AttemptResult,
  CardKind,
  Deck,
  ExamPrep,
  ExamSet,
  GenerateExamSectionResult,
  GenerateResult,
  PracticeCard,
  AnswerStyle,
  ChatResponse,
  CoachOptions,
  CourseSummary,
  DocumentRead,
  QueryChunkResult,
  QueryFilters,
  RetrievalMode,
  Study,
  FillWeekResult,
  Library,
  MakeExamplesResult,
  WeekRead,
  WeekSummary,
  WorkedExample,
} from "./types";

// `||`, niet `??`: een lege NEXT_PUBLIC_API_BASE_URL is niet nullish, en zou
// alle calls naar de Next-server op poort 3000 sturen in plaats van de API.
const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

async function handle<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const body = await response.json().catch(() => ({}) as { detail?: string });
    throw new Error(body.detail ?? `Verzoek mislukte (${response.status})`);
  }
  return (await response.json()) as T;
}

export async function fetchCourses(): Promise<CourseSummary[]> {
  return handle(await fetch(`${API_BASE}/api/courses`, { cache: "no-store" }));
}

export async function fetchDocuments(
  params: { courseSlug?: string; docKinds?: string[] } = {},
): Promise<DocumentRead[]> {
  const query = new URLSearchParams();
  if (params.courseSlug) query.set("course_slug", params.courseSlug);
  for (const kind of params.docKinds ?? []) query.append("doc_kind", kind);
  return handle(await fetch(`${API_BASE}/api/documents?${query.toString()}`, { cache: "no-store" }));
}

export async function uploadDocument(input: {
  file: File;
  courseSlug: string;
  docKind: string;
  week: number | null;
  overwrite?: boolean;
}): Promise<{ document: DocumentRead; chunk_count: number }> {
  const form = new FormData();
  form.append("file", input.file);
  form.append("course_slug", input.courseSlug);
  form.append("doc_kind", input.docKind);
  if (input.week !== null) form.append("week", String(input.week));
  if (input.overwrite) form.append("overwrite", "true");
  return handle(await fetch(`${API_BASE}/api/documents/upload`, { method: "POST", body: form }));
}

export async function reindexDocument(documentId: string) {
  return handle(await fetch(`${API_BASE}/api/documents/${documentId}/index`, { method: "POST" }));
}

export async function deleteDocument(documentId: string) {
  return handle(await fetch(`${API_BASE}/api/documents/${documentId}`, { method: "DELETE" }));
}

export type ChatRequestBody = {
  question: string;
  conversation_id?: string | null;
  filters?: QueryFilters | null;
  retrieval_mode?: RetrievalMode;
  answer_style?: AnswerStyle;
  answer_language?: AnswerLanguage;
  top_k?: number;
  coach?: CoachOptions | null;
};

export async function sendChat(body: ChatRequestBody): Promise<ChatResponse> {
  return handle(
    await fetch(`${API_BASE}/api/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  );
}

export type RetrievalFrame = {
  conversation_id: string;
  embedding_provider: string;
  rewritten_query: string | null;
  chunks: QueryChunkResult[];
};

export type StreamHandlers = {
  onRetrieval?: (payload: RetrievalFrame) => void;
  onDelta?: (text: string) => void;
  onComplete?: (payload: ChatResponse) => void;
  onError?: (message: string) => void;
};

export async function streamChat(body: ChatRequestBody, handlers: StreamHandlers): Promise<void> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}/api/chat/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  } catch (cause) {
    handlers.onError?.(cause instanceof Error ? cause.message : "Verbinding mislukt");
    return;
  }

  if (!response.ok || !response.body) {
    handlers.onError?.(`Streamen mislukte (${response.status})`);
    return;
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  // SSE-frames zijn gescheiden door een lege regel; het laatste stuk in de
  // buffer kan halfweg zijn en wacht op de volgende brok.
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    const frames = buffer.split("\n\n");
    buffer = frames.pop() ?? "";
    for (const frame of frames) {
      const line = frame.split("\n").find((part) => part.startsWith("data:"));
      if (!line) continue;
      let payload: Record<string, unknown>;
      try {
        payload = JSON.parse(line.slice(5).trim());
      } catch {
        continue;
      }
      if (payload.type === "retrieval") handlers.onRetrieval?.(payload as unknown as RetrievalFrame);
      else if (payload.type === "answer_delta") handlers.onDelta?.(String(payload.text ?? ""));
      else if (payload.type === "complete") handlers.onComplete?.(payload as unknown as ChatResponse);
      else if (payload.type === "error") handlers.onError?.(String(payload.message ?? "Onbekende fout"));
    }
  }
}


export async function fetchDecks(courseSlug: string): Promise<Deck[]> {
  const query = new URLSearchParams({ course_slug: courseSlug });
  return handle(await fetch(`${API_BASE}/api/practice/decks?${query}`, { cache: "no-store" }));
}

export async function fetchCards(courseSlug: string, sectionPath: string): Promise<PracticeCard[]> {
  const query = new URLSearchParams({ course_slug: courseSlug, section_path: sectionPath });
  return handle(await fetch(`${API_BASE}/api/practice/cards?${query}`, { cache: "no-store" }));
}

export async function fetchDueCount(courseSlug: string): Promise<number> {
  const query = new URLSearchParams({ course_slug: courseSlug });
  const body: { total: number } = await handle(
    await fetch(`${API_BASE}/api/practice/due/count?${query}`, { cache: "no-store" }),
  );
  return body.total;
}

export async function fetchExams(courseSlug: string): Promise<ExamSet[]> {
  const query = new URLSearchParams({ course_slug: courseSlug });
  return handle(await fetch(`${API_BASE}/api/practice/exams?${query}`, { cache: "no-store" }));
}

export async function fetchExamCards(
  courseSlug: string,
  origin: string,
  section: number | null = null,
): Promise<PracticeCard[]> {
  const query = new URLSearchParams({ course_slug: courseSlug });
  if (section !== null) query.set("section", String(section));
  return handle(
    await fetch(`${API_BASE}/api/practice/exams/${encodeURIComponent(origin)}/cards?${query}`, {
      cache: "no-store",
    }),
  );
}

/** Eén sectie van een oefententamen; zonder origin begint een nieuw tentamen. */
export async function generateExamSection(
  courseSlug: string,
  section: number,
  origin: string | null,
): Promise<GenerateExamSectionResult> {
  return handle(
    await fetch(`${API_BASE}/api/practice/exams/generate`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ course_slug: courseSlug, section, origin }),
    }),
  );
}

export async function fetchDueCards(courseSlug: string, limit = 20): Promise<PracticeCard[]> {
  const query = new URLSearchParams({ course_slug: courseSlug, limit: String(limit) });
  return handle(await fetch(`${API_BASE}/api/practice/due?${query}`, { cache: "no-store" }));
}

export async function generateCards(
  courseSlug: string,
  sectionPath: string,
  count = 8,
  kind: CardKind = "code",
): Promise<GenerateResult> {
  return handle(
    await fetch(`${API_BASE}/api/practice/decks/generate`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ course_slug: courseSlug, section_path: sectionPath, count, kind }),
    }),
  );
}

export async function submitAttempt(cardId: string, answer: string): Promise<AttemptResult> {
  return handle(
    await fetch(`${API_BASE}/api/practice/cards/${cardId}/attempt`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ answer }),
    }),
  );
}

export async function discardCard(cardId: string): Promise<PracticeCard> {
  return handle(await fetch(`${API_BASE}/api/practice/cards/${cardId}`, { method: "DELETE" }));
}


export async function fetchWeeks(courseSlug: string): Promise<WeekRead[]> {
  const query = new URLSearchParams({ course_slug: courseSlug });
  return handle(await fetch(`${API_BASE}/api/weeks?${query}`, { cache: "no-store" }));
}

export async function fetchWeekSummary(courseSlug: string, week: number): Promise<WeekSummary | null> {
  const query = new URLSearchParams({ course_slug: courseSlug, week: String(week) });
  const response = await fetch(`${API_BASE}/api/weeks/summary?${query}`, { cache: "no-store" });
  // Nog niet samengevat is geen fout; dan hoort de knop er te staan.
  if (response.status === 404) return null;
  return handle(response);
}

export async function buildWeekSummary(courseSlug: string, week: number): Promise<WeekSummary> {
  return handle(
    await fetch(`${API_BASE}/api/weeks/summary`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ course_slug: courseSlug, week }),
    }),
  );
}


// --- agenda ------------------------------------------------------------------

async function sendJson<T>(method: "POST" | "PATCH" | "DELETE", path: string, body?: unknown): Promise<T> {
  return handle(
    await fetch(`${API_BASE}${path}`, {
      method,
      headers: body === undefined ? undefined : { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    }),
  );
}

export async function fetchAgenda(): Promise<Agenda> {
  return handle(await fetch(`${API_BASE}/api/agenda`, { cache: "no-store" }));
}

export async function syncCanvas(): Promise<CanvasSyncResult> {
  return sendJson("POST", "/api/agenda/sync");
}

export async function setCourseHidden(canvasId: number, hidden: boolean): Promise<{ canvas_id: number; hidden: boolean }> {
  return sendJson("PATCH", `/api/agenda/courses/${canvasId}`, { hidden });
}

export async function setItemDone(itemId: string, done: boolean): Promise<AgendaItem> {
  return sendJson("PATCH", `/api/agenda/items/${encodeURIComponent(itemId)}`, { done });
}

export type TaskInput = {
  title: string;
  notes?: string;
  due_on?: string | null;
  course_slug?: string | null;
  link?: string | null;
};

export async function createTask(input: TaskInput): Promise<AgendaTask> {
  return sendJson("POST", "/api/agenda/tasks", input);
}

export async function updateTask(taskId: string, patch: Partial<TaskInput> & { done?: boolean }): Promise<AgendaTask> {
  return sendJson("PATCH", `/api/agenda/tasks/${taskId}`, patch);
}

export async function deleteTask(taskId: string): Promise<AgendaTask> {
  return sendJson("DELETE", `/api/agenda/tasks/${taskId}`);
}

/** Verwijderen is zacht, dus terughalen levert dezelfde taak op, niet een nieuwe. */
export async function restoreTask(taskId: string): Promise<AgendaTask> {
  return sendJson("POST", `/api/agenda/tasks/${taskId}/restore`);
}

export async function fetchMaterial(
  fileId: number,
  input: { doc_kind?: string | null; week?: number | null; overwrite?: boolean } = {},
): Promise<{ material: AgendaMaterial; document: DocumentRead; chunk_count: number }> {
  return sendJson("POST", `/api/agenda/materials/${fileId}/fetch`, input);
}

export async function ignoreMaterial(fileId: number, ignored: boolean): Promise<AgendaMaterial> {
  return sendJson("POST", `/api/agenda/materials/${fileId}/ignore`, { ignored });
}

export async function fetchAssignmentText(
  itemId: string,
  overwrite = false,
): Promise<{ document: DocumentRead; chunk_count: number }> {
  return sendJson("POST", `/api/agenda/items/${encodeURIComponent(itemId)}/sheet`, { overwrite });
}

export async function fetchCanvasPage(
  pageId: string,
  overwrite = false,
): Promise<{ page: AgendaPage; document: DocumentRead; chunk_count: number }> {
  return sendJson("POST", `/api/agenda/pages/${encodeURIComponent(pageId)}/fetch`, { overwrite });
}

export async function ignoreCanvasPage(pageId: string, ignored: boolean): Promise<AgendaPage> {
  return sendJson("POST", `/api/agenda/pages/${encodeURIComponent(pageId)}/ignore`, { ignored });
}

// --- studeren ---------------------------------------------------------------

export async function fetchStudy(courseSlug: string, minutes: number, week?: number): Promise<Study> {
  const query = new URLSearchParams({ course_slug: courseSlug, minutes: String(minutes) });
  if (week !== undefined) query.set("week", String(week));
  return handle(await fetch(`${API_BASE}/api/study?${query}`, { cache: "no-store" }));
}

export async function fillWeek(
  courseSlug: string,
  week: number,
  kind: CardKind,
  count = 4,
): Promise<FillWeekResult> {
  return sendJson("POST", `/api/study/weeks/${week}/cards`, { course_slug: courseSlug, kind, count });
}

export async function fetchLibrary(courseSlug: string): Promise<Library> {
  const query = new URLSearchParams({ course_slug: courseSlug });
  return handle(await fetch(`${API_BASE}/api/study/library?${query}`, { cache: "no-store" }));
}

export async function makeExamples(courseSlug: string, week: number): Promise<MakeExamplesResult> {
  return sendJson("POST", `/api/study/weeks/${week}/examples`, { course_slug: courseSlug, count: 1 });
}

export async function fetchAttention(): Promise<Attention> {
  return handle(await fetch(`${API_BASE}/api/attention`, { cache: "no-store" }));
}

export async function fetchWeekExamples(courseSlug: string, week: number): Promise<WorkedExample[]> {
  const query = new URLSearchParams({ course_slug: courseSlug, week: String(week) });
  return handle(await fetch(`${API_BASE}/api/weeks/examples?${query}`, { cache: "no-store" }));
}

export async function fetchExamPrep(courseSlug: string): Promise<ExamPrep> {
  const query = new URLSearchParams({ course_slug: courseSlug });
  return handle(await fetch(`${API_BASE}/api/exam-prep?${query}`, { cache: "no-store" }));
}
