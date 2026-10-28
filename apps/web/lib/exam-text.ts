/** Zet elke optie van een meerkeuzevraag op een eigen regel. In
 * `voorbereiding.yml` staan ze als "a) ... b) ..." in doorlopende tekst (YAML
 * vouwt de regels samen), en op één regel lees je ze niet als vier keuzes.
 * Alleen als er een a) én een b) is: een losse "a)" midden in een zin blijft
 * staan. */
export function optionLines(question: string): string {
  if (!/(^|\s)a\)\s/.test(question) || !/\sb\)\s/.test(question)) return question;
  return question.replace(/\s+([a-f])\)\s+/g, "\n$1) ");
}

export type TextBlock = { kind: "text" | "code"; text: string };

/** Een vraag in alinea's, met code apart. Een alinea waarvan elke regel met
 * vier spaties begint is code (zoals in markdown): de PuLP-vragen van SSO
 * zetten zo een fragment in de vraag, en in de gewone tekstopmaak verdween de
 * inspringing — in Python de betekenis. */
export function questionBlocks(question: string): TextBlock[] {
  return question
    .split(/\n\s*\n/)
    .filter((paragraph) => paragraph.trim() !== "")
    .map((paragraph) => {
      const lines = paragraph.split("\n");
      if (lines.every((line) => line.startsWith("    "))) {
        return { kind: "code", text: lines.map((line) => line.slice(4)).join("\n") };
      }
      return { kind: "text", text: optionLines(paragraph.trim()) };
    });
}

/** Punten met hooguit twee decimalen en een komma: SSO telt in kwarten
 * (0,25 tot 0,75), en de opmaak van de agenda (één decimaal) maakte van 0,75
 * een "0,8". */
export function examPoints(value: number): string {
  return String(Math.round(value * 100) / 100).replace(".", ",");
}


type ScenarioScore = { points: number; last_score: number | null };

/** Wat je bij je laatste poging op een scenario haalde. Als tekst, niet als
 * gekleurd label: het getal zegt genoeg. */
export function scenarioResult(scenario: ScenarioScore): string {
  if (scenario.last_score === null) return "nog niet geoefend";
  return `${examPoints(scenario.last_score)} van ${examPoints(scenario.points)}`;
}

/** "6 scenario's", voor de knop die de lijst openklapt. */
export function scenarioCount(count: number): string {
  return `${count} ${count === 1 ? "scenario" : "scenario's"}`;
}

/** "2 van 6 geoefend" naast de knoppen; leeg zolang je er nog geen deed. */
export function scenarioProgress(scenarios: ScenarioScore[]): string {
  const done = scenarios.filter((scenario) => scenario.last_score !== null).length;
  return done > 0 ? `${done} van ${scenarios.length} geoefend` : "";
}
