export type DocKind =
  | "book"
  | "paper"
  | "slides"
  | "assignment"
  | "exercise"
  | "submission"
  | "solution"
  | "note"
  | "exam";

export const DOC_KINDS: DocKind[] = [
  "book",
  "paper",
  "slides",
  "assignment",
  "exercise",
  "submission",
  "solution",
  "note",
  "exam",
];

export const DOC_KIND_LABELS: Record<DocKind, string> = {
  book: "Boek",
  paper: "Paper",
  slides: "Slides",
  assignment: "Opdracht (beoordeeld)",
  exercise: "Oefenopgaven",
  submission: "Mijn uitwerking",
  solution: "Uitwerking (officieel)",
  note: "Aantekening",
  exam: "Tentamen (oud of proef)",
};

/** Boeken, papers en tentamens horen niet bij één week. */
export const KINDS_WITHOUT_WEEK: DocKind[] = ["book", "paper", "exam"];

export type RetrievalMode = "dense" | "hybrid";
export type AnswerStyle = "short" | "explain";
/** "auto" volgt de taal van de vraag; de andere twee pinnen hem vast. */
export type AnswerLanguage = "auto" | "nl" | "en";
export type Confidence = "low" | "medium" | "high";
export type AssignmentStatus = "open" | "submitted" | "closed";

export type CoachPolicy = "hints" | "reveal";

export type CoachOptions = {
  document_id: string;
  reveal?: boolean;
};

export type CoachEcho = {
  document_id: string;
  document_title: string;
  policy: CoachPolicy;
};

export type QueryFilters = {
  course_slug?: string | null;
  week?: number | null;
  doc_kinds?: DocKind[] | null;
  assignment_status?: AssignmentStatus | null;
};

export type QueryChunkResult = {
  chunk_id: string;
  document_id: string;
  document_title: string;
  source_path: string;
  course_slug: string;
  doc_kind: DocKind;
  week: number | null;
  assignment_status: AssignmentStatus | null;
  section_path: string | null;
  page_start: number;
  page_end: number;
  score: number;
  text: string;
  chunk_metadata: Record<string, unknown>;
};

export type AnswerCitation = {
  chunk_id: string;
  document_id: string;
  document_title: string;
  source_path: string;
  course_slug: string;
  doc_kind: DocKind;
  week: number | null;
  section_path: string | null;
  page_start: number;
  page_end: number;
  quote: string;
};

export type ChatResponse = {
  conversation_id: string;
  question: string;
  rewritten_query: string | null;
  answer: string;
  abstained: boolean;
  confidence: Confidence;
  confidence_reasons: string[];
  citations: AnswerCitation[];
  retrieved_chunks: QueryChunkResult[];
  embedding_provider: string;
  answer_model: string;
  answer_style: AnswerStyle;
  answer_language: AnswerLanguage;
  latency_ms: number | null;
  coach: CoachEcho | null;
};

export type CourseSummary = {
  slug: string;
  name: string;
  period: string | null;
  lecturer: string | null;
  document_count: number;
  weeks: number[];
  open_assignment_count: number;
};

export type DocumentRead = {
  id: string;
  title: string;
  source_path: string;
  course_slug: string;
  doc_kind: DocKind;
  week: number | null;
  assignment_status: AssignmentStatus | null;
  ingestion_status: string;
  page_count: number;
  chunk_count: number;
  parse_error: string | null;
  indexed_at: string | null;
  created_at: string;
};

export type ChatTurn = {
  id: string;
  role: "user" | "assistant";
  content: string;
  coach?: CoachEcho | null;
  citations: AnswerCitation[];
  retrievedChunks: QueryChunkResult[];
  confidence: Confidence | null;
  confidenceReasons: string[];
  abstained: boolean | null;
  rewrittenQuery: string | null;
  streaming?: boolean;
};

/** "slide 12" voor een deck, anders "p. 241-242". */
export function locationLabel(item: AnswerCitation | QueryChunkResult): string {
  if (item.doc_kind === "slides") {
    return item.page_start === item.page_end
      ? `slide ${item.page_start}`
      : `slides ${item.page_start}-${item.page_end}`;
  }
  return item.page_start === item.page_end
    ? `p. ${item.page_start}`
    : `p. ${item.page_start}-${item.page_end}`;
}

export type Deck = {
  section_path: string;
  document_title: string;
  page_start: number;
  page_end: number;
  chunk_count: number;
  card_count: number;
  /** Hoeveel van die kaarten nu weer aan de beurt zijn. */
  due_count: number;
};

/** Wat de generator maakt. "code": een NumPy- of pandas-uitdrukking.
 * "stats": een toets uitvoeren. "exam": meerkeuze en open vragen in de vorm
 * van het tentamen — de kaarten zelf zijn dan "mc" of "open". */
export type CardKind = "code" | "stats" | "exam" | "keuze" | "output";

export type PracticeCard = {
  id: string;
  course_slug: string;
  section_path: string | null;
  document_id: string;
  page_start: number;
  page_end: number;
  kind: string;
  setup: string;
  question: string;
  /** Punten op het tentamen; leeg bij code en stats. */
  points: number | null;
  /** Het (proef)tentamen waar de vraag uit komt, en de plek erin. */
  origin: string | null;
  position: number | null;
  week: number | null;
  options: string[];
  multi: boolean;
  /** Een figuur of stuk code bij de vraag, uitgeschreven naar tekst. */
  figure: string;
  exam_section: string | null;
  max_items: number | null;
};

export type AttemptResult = {
  correct: boolean;
  kind: string;
  reference_answer: string;
  /** De uitgewerkte oplossing van een toetskaart; leeg bij een codekaart. */
  explanation: string;
  expected_repr: string;
  given_repr: string;
  error: string | null;
  section_path: string | null;
  page_start: number;
  page_end: number;
  score: number | null;
  max_score: number | null;
  options: string[];
  selected: number[];
  correct_options: number[];
  criteria: CriterionResult[];
  feedback: string;
  /** Waar je dit nakijkt in je materiaal. */
  material: string;
};

export type CriterionResult = {
  criterion: string;
  points: number;
  awarded: number;
  evidence: string;
  comment: string;
  /** Het model gaf punten met een citaat dat niet in je antwoord staat. */
  withdrawn: boolean;
};

export type ExamSection = {
  number: number;
  title: string;
  question_count: number;
  points: number;
  answered: number;
  answered_points: number;
  last_score: number;
};

export type ExamSet = {
  origin: string;
  title: string;
  question_count: number;
  points: number;
  answered: number;
  answered_points: number;
  last_score: number;
  sections: ExamSection[];
};

export type GenerateExamSectionResult = {
  origin: string;
  title: string;
  section_number: number;
  section_title: string;
  created: number;
  points: number;
  planned_points: number;
  /** Plekken uit de opbouw die niet gevuld konden worden. */
  missing: string[];
  rejected: { label: string; reason: string }[];
  uncovered_topics: string[];
  source_note: string;
};

export type GenerateResult = {
  created: PracticeCard[];
  rejected: { label: string; reason: string }[];
};


export type WeekRead = {
  week: number;
  topics: string[];
  lectures: number[];
  chunk_count: number;
  has_summary: boolean;
  /** Leesregels uit course.yml die nergens op uitkwamen. */
  unresolved: string[];
};

/** Eén formule van het weekformuleblad, met wat elk symbool betekent. */
export type WeekFormula = {
  name: string;
  /** LaTeX zonder dollartekens; de pagina zet ze eromheen. */
  latex: string;
  when: string;
  symbols: { symbol: string; meaning: string }[];
};

export type WeekSummary = {
  course_slug: string;
  week: number;
  thread: string;
  topics: { label: string; covers: string; where: string }[];
  formulas: WeekFormula[];
  concepts: { term: string; meaning: string }[];
  skills: string[];
  /** Formules die zijn afgevallen, met de reden. */
  problems: string[];
  /** Het materiaal is veranderd sinds deze samenvatting is gemaakt. */
  stale: boolean;
  chunks_used: number;
  chunks_total: number;
  created_at: string;
};


// --- agenda ------------------------------------------------------------------

export type AgendaItemKind = "assignment" | "quiz" | "exam" | "event";

export type AgendaStatus =
  | "locked"
  | "open"
  | "submitted"
  | "late"
  | "graded"
  | "missing"
  | "overdue"
  | "done"
  | "closed"
  | "upcoming"
  | "past";

export type AgendaBucket =
  | "overdue"
  | "today"
  | "tomorrow"
  | "this_week"
  | "next_week"
  | "later"
  | "undated"
  | "done";

export type AgendaItem = {
  id: string;
  kind: AgendaItemKind;
  course_id: number | null;
  course_slug: string | null;
  course_name: string;
  title: string;
  html_url: string | null;
  description: string;
  due_at: string | null;
  unlock_at: string | null;
  lock_at: string | null;
  /** Een tentamen uit course.yml heeft een dag, geen tijd. */
  due_on: string | null;
  deadline_at: string | null;
  days_left: number | null;
  points_possible: number | null;
  submission_types: string[];
  status: AgendaStatus;
  bucket: AgendaBucket;
  /** Waar de rij staat: een afgevinkte rij blijft op zijn dag tot die voorbij is. */
  place: AgendaBucket;
  score: number | null;
  grade: string | null;
  submitted_at: string | null;
  late: boolean;
  missing: boolean;
  marked_complete: boolean;
  done_at: string | null;
  /** Of het vinkje zin heeft; de server kent de regel, wij kopiëren hem niet. */
  tickable: boolean;
  quiz: { attempt: number | null; score: number | null; finished_at: string | null; answers_at: string | null } | null;
  /** De regel in course.yml die bij dit item hoort, op naam. */
  yaml: { name: string; week: number; due_date: string; same_day: boolean } | null;
  /** Het open opgavenblad in het corpus: de coach-link. */
  coach_document_id: string | null;
};

/** Een knop bij een taak: een pad binnen de app ("/weken?…") of een https-adres. */
export type TaskLink = {
  label: string;
  href: string;
};

export type AgendaTask = {
  id: string;
  title: string;
  notes: string;
  due_on: string | null;
  course_slug: string | null;
  link: string | null;
  links: TaskLink[];
  done_at: string | null;
  created_at: string;
  bucket: AgendaBucket;
  /** Waar de rij staat: een afgevinkte rij blijft op zijn dag tot die voorbij is. */
  place: AgendaBucket;
};

export type AgendaExam = {
  name: string;
  date: string | null;
  days_left: number | null;
  source: "yaml" | "canvas" | "both";
  canvas_item_id: string | null;
};

export type AgendaDiffKind =
  | "due_date_differs"
  | "yaml_only"
  | "canvas_only"
  | "exam_date_differs"
  | "exam_missing_in_yaml"
  | "canvas_id_missing"
  | "assignment_sheet_missing";

export type AgendaDiff = {
  kind: AgendaDiffKind;
  message: string;
  item_id: string | null;
  week: number | null;
  file_id: number | null;
  /** Geen pdf bij de opdracht, wel een beschrijving: die kan als tekst het corpus in. */
  can_fetch_text: boolean;
};

export type AgendaAnnouncement = {
  id: number;
  title: string;
  posted_at: string | null;
  body: string;
  html_url: string | null;
  unread: boolean;
};

export type AgendaCopilot = {
  due_count: number;
  exam_sets: ExamSet[];
  weeks_without_summary: number[];
  /** Weken waarvan de stof veranderde sinds de weekkaart gemaakt is. */
  stale_summaries: number[];
};

export type AgendaCourse = {
  canvas_id: number | null;
  course_slug: string | null;
  name: string;
  course_code: string | null;
  term: string | null;
  hidden: boolean;
  fetched_at: string | null;
  item_count: number;
  exams: AgendaExam[];
  /** Leeg voor een Canvas-vak zonder corpus. */
  copilot: AgendaCopilot | null;
  announcements: AgendaAnnouncement[];
  diffs: AgendaDiff[];
  /** Alleen voor een vak met een corpus. */
  materials: AgendaMaterial[];
  pages: AgendaPage[];
};

export type Agenda = {
  now: string;
  canvas: { configured: boolean; synced_at: string | null; stale: boolean };
  courses: AgendaCourse[];
  items: AgendaItem[];
  tasks: AgendaTask[];
  problems: string[];
};

export type CanvasSyncResult = {
  synced_at: string;
  courses: number;
  items: number;
  announcements: number;
  files_new: number;
  lines: string[];
  problems: string[];
};

export const BUCKET_ORDER: AgendaBucket[] = [
  "overdue",
  "today",
  "tomorrow",
  "this_week",
  "next_week",
  "later",
  "undated",
  "done",
];

export const BUCKET_LABELS: Record<AgendaBucket, string> = {
  overdue: "Verlopen",
  today: "Vandaag",
  tomorrow: "Morgen",
  this_week: "Deze week",
  next_week: "Volgende week",
  later: "Later",
  undated: "Zonder datum",
  done: "Afgerond",
};

export const STATUS_LABELS: Record<AgendaStatus, string> = {
  locked: "nog niet open",
  open: "open",
  submitted: "ingeleverd",
  late: "te laat ingeleverd",
  graded: "beoordeeld",
  missing: "ontbreekt",
  overdue: "verlopen",
  done: "afgevinkt",
  closed: "gesloten",
  upcoming: "komt eraan",
  past: "geweest",
};

export const KIND_LABELS: Record<AgendaItemKind, string> = {
  assignment: "Opdracht",
  quiz: "Quiz",
  exam: "Tentamen",
  event: "Afspraak",
};

export type MaterialState = "new" | "in_corpus" | "downloaded" | "ignored" | "unsupported" | "unplaced";

export type AgendaMaterial = {
  id: number;
  canvas_course_id: number;
  filename: string;
  display_name: string;
  size: number | null;
  content_type: string | null;
  folder: string | null;
  module_name: string | null;
  source: string;
  updated_at: string | null;
  state: MaterialState;
  /** Het voorstel; leeg als er niets zekers te zeggen valt. */
  placement: { doc_kind: DocKind; week: number | null; relative_path: string } | null;
  reason: string;
  document_id: string | null;
  corpus_path: string | null;
};

export type PageState = "new" | "in_corpus" | "downloaded" | "ignored";

/** Een pagina uit een module van Canvas: lab-instructies, een afleiding, het rooster. */
export type AgendaPage = {
  id: string;
  canvas_course_id: number;
  title: string;
  module_name: string | null;
  updated_at: string | null;
  state: PageState;
  placement: { doc_kind: DocKind; week: number | null; relative_path: string } | null;
  reason: string;
  document_id: string | null;
};

// --- studeren ---------------------------------------------------------------

export type StudyExam = {
  name: string;
  /** "JJJJ-MM-DD" */
  date: string;
  days_left: number;
  /** "course.yml" of "canvas" */
  source: string;
};

/** Waarom deze kaart in de ronde zit. */
export type SessionReason = "zwak" | "herhalen" | "nieuw";

export const REASON_LABELS: Record<SessionReason, string> = {
  zwak: "vorige keer fout",
  herhalen: "herhalen",
  nieuw: "nieuw",
};

export type SessionCard = {
  card: PracticeCard;
  reason: SessionReason;
  topic: string | null;
  /** De toets of het model waar de vraag om draait; hierop wisselt de ronde af. */
  procedure: string | null;
  minutes: number;
};

export type StudySession = {
  minutes: number;
  estimated_minutes: number;
  cards: SessionCard[];
  counts: Record<SessionReason, number>;
  notes: string[];
};

export type StudyWeek = {
  week: number;
  lectures: number[];
  topics: string[];
  material_chunks: number;
  cards: number;
  new: number;
  learning: number;
  mastered: number;
  weak: number;
  due: number;
  topics_without_cards: string[];
  has_summary: boolean;
  summary_stale: boolean;
  last_practised: string | null;
  examples: WorkedExample[];
};

export type Study = {
  course_slug: string;
  now: string;
  exam: StudyExam | null;
  pace: Pace | null;
  session: StudySession;
  weeks: StudyWeek[];
  totals: { cards: number; due: number; mastered: number; weak: number; new: number };
};

export type FillWeekResult = {
  week: number;
  created: number;
  topics_done: string[];
  /** [onderwerp, reden] — wat er niet gemaakt is. */
  skipped: [string, string][];
  rejected: { label: string; reason: string }[];
};

export type LibraryResource = {
  name: string;
  url: string;
  kind: string;
  license: string;
  note: string;
};

export type TopicResources = {
  week: number;
  topic: string;
  resources: LibraryResource[];
};

export type MethodClaim = {
  claim: string;
  source: string;
  title: string;
  url: string;
  /** Wat voor bewijs het is, en hoe sterk. */
  strength: string;
};

export type Library = {
  course_slug: string;
  topics: TopicResources[];
  method: MethodClaim[];
};

export type ExampleStep = { label: string; body: string };

export type WorkedExample = {
  id: string;
  week: number | null;
  topic: string;
  title: string;
  situation: string;
  steps: ExampleStep[];
  takeaway: string;
  /** De vraag die je jezelf stelt; met opzet niet nagekeken. */
  prompt: string;
  /** Klaar om in de pagina te zetten; leeg als er geen figuur is. */
  figure_svg: string;
  figure_caption: string;
  page_start: number;
  page_end: number;
};

export type MakeExamplesResult = {
  week: number;
  created: number;
  topics_done: string[];
  skipped: [string, string][];
  rejected: { label: string; reason: string }[];
  figure_problems: [string, string][];
};

/** De tellers in de navigatiebalk. */
export type Attention = {
  today: number;
  overdue: number;
  due_cards: number;
};

/** Haal je het in de tijd die er nog is? Optimistisch gerekend: alsof je alles
 *  goed hebt. Een fout kost een extra beurt. */
export type Pace = {
  exam_name: string;
  days_left: number;
  cards: number;
  reviews_needed: number;
  reviews_possible: number;
  minutes: number;
  minutes_per_day_needed: number;
  feasible: boolean;
};

// --- tentamen ---------------------------------------------------------------

export type ExamFacts = {
  duration_minutes: number | null;
  aids: string[];
  notes: string[];
};

/** Een groep van de opbouw van het tentamen, met hoe je ervoor staat. */
export type GroupStanding = {
  number: number;
  title: string;
  /** Wat de groep waard is op het tentamen. */
  points: number;
  mc: number;
  open: number;
  mc_points: number;
  open_points: number[];
  answered: number;
  answered_points: number;
  scored: number;
  /** null: nog niet geoefend. */
  share: number | null;
  /** Wat er nog te halen valt als je scoort zoals bij je laatste pogingen. */
  to_gain: number;
};

/** Een bron met letterlijk citaat, door de server teruggezocht in de index. */
export type PrepSource = {
  label: string;
  quote: string;
  found: boolean;
  reason: string | null;
  href: string | null;
};

/** Eén variant van een patroon om te oefenen, uit `exams/scenarios.yml`. */
export type PrepScenario = {
  card_id: string;
  question_id: string;
  /** Eén regel: wat dit scenario anders maakt dan de andere. */
  topic: string;
  points: number;
  /** Wat je bij je laatste poging haalde; null als je hem nog niet deed. */
  last_score: number | null;
};

export type PrepPattern = {
  id: string;
  title: string;
  detail: string;
  group: number | null;
  seen: number | null;
  of: number | null;
  sources: PrepSource[];
  scenarios: PrepScenario[];
  /** Waar je de scenario's oefent: /oefenen?exam=<origin>&section=<section>. */
  practice: { origin: string; section: number } | null;
};

export type PrepPrediction = {
  id: string;
  group: number | null;
  points: number | null;
  question: string;
  answer: string;
  why: string;
  sources: PrepSource[];
};

export type PrepTactic = {
  id: string;
  title: string;
  detail: string;
  sources: PrepSource[];
};

/** Zo herken je de vraag: wat je ziet, wat je doet, de punten en de valkuil. */
export type PrepRule = {
  id: string;
  group: number | null;
  /** Nooit op een oud tentamen: de bron is het huiswerk. */
  new: boolean;
  see: string;
  do: string;
  points: string;
  trap: string;
  sources: PrepSource[];
};

/** Een stap in "Tot het tentamen". Een stap met `exam` is af als elke vraag van
 * dat oefententamen een poging heeft; de andere vink je zelf af. */
export type PrepPlanStep = {
  id: string;
  title: string;
  /** Kop waaronder de stap staat, bijvoorbeeld "dinsdag 20 oktober". */
  day: string;
  detail: string;
  minutes: number | null;
  exam: string | null;
  links: TaskLink[];
  /** De slides bij deze stap, met de pagina's in de naam. */
  slides: TaskLink[];
};

export type ExamPrep = {
  course_slug: string;
  /** Of er een `exams/voorbereiding.yml` is; zonder alleen de berekende blokken. */
  has_file: boolean;
  exam: StudyExam | null;
  facts: ExamFacts | null;
  total_points: number | null;
  minutes_per_point: number | null;
  /** Gesorteerd op wat er te winnen valt, het meeste bovenaan. */
  groups: GroupStanding[];
  exam_sets: ExamSet[];
  patterns: PrepPattern[];
  predictions: PrepPrediction[];
  tactics: PrepTactic[];
  rules: PrepRule[];
  /** Wat je nog doet tot het tentamen, in volgorde. */
  plan: PrepPlanStep[];
  problems: string[];
};
