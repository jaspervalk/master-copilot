"use client";

import { useEffect, useRef, useState } from "react";

import { Composer } from "@/components/chat/composer";
import { CoursePicker } from "@/components/chat/course-picker";
import { Thread } from "@/components/chat/thread";
import { EvidencePanel } from "@/components/evidence/evidence-panel";
import { fetchCourses, fetchDocuments, streamChat } from "@/lib/api";
import type {
  AnswerCitation,
  AnswerLanguage,
  AnswerStyle,
  ChatTurn,
  CoachOptions,
  CourseSummary,
  DocumentRead,
  QueryFilters,
  RetrievalMode,
} from "@/lib/types";
import { useInitialParams } from "@/lib/use-initial-params";


export function ChatWorkspace() {
  const [courses, setCourses] = useState<CourseSummary[]>([]);
  const [courseSlug, setCourseSlug] = useState<string | null>(null);
  const [week, setWeek] = useState<number | null>(null);
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [selectedCitation, setSelectedCitation] = useState<AnswerCitation | null>(null);
  const [style, setStyle] = useState<AnswerStyle>("explain");
  const [mode, setMode] = useState<RetrievalMode>("hybrid");
  const [language, setLanguage] = useState<AnswerLanguage>("auto");
  const [coach, setCoach] = useState<CoachOptions | null>(null);
  const [coachChoices, setCoachChoices] = useState<DocumentRead[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // /?course=sso&coach=<document_id>, vanuit de agenda: het vak kiezen en de
  // coach op dat opgavenblad zetten zodra de lijst met keuzes er is.
  const initial = useInitialParams();
  const wantedCoach = useRef<string | null>(initial.get("coach"));

  useEffect(() => {
    fetchCourses()
      .then((list) => {
        setCourses(list);
        const wanted = initial.get("course");
        if (wanted && list.some((course) => course.slug === wanted)) selectCourse(wanted);
      })
      .catch((cause) => setError(cause instanceof Error ? cause.message : String(cause)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initial]);

  // Van vak wisselen begint een nieuw gesprek: de context van het vorige vak
  // zou de herschrijving van vervolgvragen de verkeerde kant op sturen.
  function selectCourse(slug: string | null) {
    setCourseSlug(slug);
    setWeek(null);
    setConversationId(null);
    setTurns([]);
    setSelectedCitation(null);
    setCoach(null);
    if (slug) {
      fetchDocuments({ courseSlug: slug, docKinds: ["assignment", "exercise"] })
        // Gesloten en ingeleverde opdrachten zijn niet te coachen; de server
        // weigert ze ook, maar ze horen niet eens in de lijst.
        .then((docs) => {
          const choices = docs.filter((doc) => doc.doc_kind === "exercise" || doc.assignment_status === "open");
          setCoachChoices(choices);
          const wanted = wantedCoach.current;
          wantedCoach.current = null;
          if (wanted && choices.some((doc) => doc.id === wanted)) setCoach({ document_id: wanted });
        })
        .catch(() => setCoachChoices([]));
    } else {
      setCoachChoices([]);
    }
  }

  async function ask(question: string, options: { reveal?: boolean } = {}) {
    setError(null);
    setIsStreaming(true);

    const filters: QueryFilters = { course_slug: courseSlug, week };
    const assistantId = `assistant-${Date.now()}`;

    setTurns((current) => [
      ...current,
      {
        id: `user-${Date.now()}`,
        role: "user",
        content: question,
        citations: [],
        retrievedChunks: [],
        confidence: null,
        confidenceReasons: [],
        abstained: null,
        rewrittenQuery: null,
      },
      {
        id: assistantId,
        role: "assistant",
        content: "",
        citations: [],
        retrievedChunks: [],
        confidence: null,
        confidenceReasons: [],
        abstained: null,
        rewrittenQuery: null,
        streaming: true,
      },
    ]);

    function patchAssistant(patch: Partial<ChatTurn>) {
      setTurns((current) =>
        current.map((turn) => (turn.id === assistantId ? { ...turn, ...patch } : turn)),
      );
    }

    await streamChat(
      {
        question,
        conversation_id: conversationId,
        filters,
        retrieval_mode: mode,
        answer_style: style,
        answer_language: language,
        // reveal geldt voor één beurt: de knop onder een hint-antwoord stelt
        // dezelfde vraag opnieuw, met de uitwerking vrijgegeven.
        coach: coach ? { ...coach, reveal: options.reveal ?? false } : null,
      },
      {
        onRetrieval: (payload) => {
          setConversationId(payload.conversation_id);
          patchAssistant({
            retrievedChunks: payload.chunks,
            rewrittenQuery: payload.rewritten_query,
          });
        },
        onDelta: (text) => {
          setTurns((current) =>
            current.map((turn) =>
              turn.id === assistantId ? { ...turn, content: turn.content + text } : turn,
            ),
          );
        },
        onComplete: (payload) => {
          patchAssistant({
            content: payload.answer,
            citations: payload.citations,
            retrievedChunks: payload.retrieved_chunks,
            confidence: payload.confidence,
            confidenceReasons: payload.confidence_reasons,
            abstained: payload.abstained,
            rewrittenQuery: payload.rewritten_query,
            coach: payload.coach ?? null,
            streaming: false,
          });
          setSelectedCitation(payload.citations[0] ?? null);
        },
        onError: (message) => {
          setError(message);
          patchAssistant({ streaming: false });
        },
      },
    );

    setIsStreaming(false);
  }

  const chunksForPanel = turns.flatMap((turn) => turn.retrievedChunks);
  // De nummers in het paneel moeten dezelfde zijn als de [1], [2] in het
  // antwoord, dus het gaat om de citaties van de beurt waar de selectie bij
  // hoort — niet om alles wat er ooit is opgehaald.
  const selectedCitationList =
    turns.find((turn) =>
      turn.citations.some((citation) => citation.chunk_id === selectedCitation?.chunk_id),
    )?.citations ?? [];

  return (
    <div className="flex h-full min-h-0">
      <CoursePicker
        courses={courses}
        selected={courseSlug}
        onSelect={selectCourse}
        week={week}
        onWeekChange={setWeek}
      />

      <section className="flex min-h-0 min-w-0 flex-1 flex-col">
        {error && (
          <div className="border-b border-rose-200 bg-rose-50 px-6 py-2 text-sm text-rose-800">
            {error}
          </div>
        )}
        <Thread
          turns={turns}
          activeCitationId={selectedCitation?.chunk_id ?? null}
          onSelectCitation={setSelectedCitation}
          onReveal={(question) => ask(question, { reveal: true })}
        />
        <Composer
          onSubmit={(question) => ask(question)}
          isStreaming={isStreaming}
          style={style}
          onStyleChange={setStyle}
          mode={mode}
          onModeChange={setMode}
          language={language}
          onLanguageChange={setLanguage}
          coach={coach}
          coachChoices={coachChoices}
          onCoachChange={setCoach}
        />
      </section>

      <EvidencePanel
        citation={selectedCitation}
        citations={selectedCitationList}
        chunks={chunksForPanel}
        onSelectCitation={setSelectedCitation}
      />
    </div>
  );
}
