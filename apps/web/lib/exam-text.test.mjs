import assert from "node:assert/strict";
import { test } from "node:test";

import { examPoints, optionLines, questionBlocks, scenarioCount, scenarioProgress, scenarioResult } from "./exam-text.ts";


test("elke optie komt op een eigen regel", () => {
  assert.equal(
    optionLines("Which is generative? a) Logistic regression  b) k-NN c) Naive Bayes d) Decision tree"),
    "Which is generative?\na) Logistic regression\nb) k-NN\nc) Naive Bayes\nd) Decision tree",
  );
});

test("zonder a) én b) blijft de tekst staan", () => {
  const open = "Give two examples (e.g. a) a tree) of interpretable models.";
  assert.equal(optionLines(open), open);
  assert.equal(optionLines("Explain k-fold cross-validation."), "Explain k-fold cross-validation.");
});

test("een ingesprongen alinea is code, met de inspringing binnen de code intact", () => {
  const vraag = "Fix the code.\n\n    for b in profit:\n        print(b)\n\n(a) Find the errors.";
  assert.deepEqual(questionBlocks(vraag), [
    { kind: "text", text: "Fix the code." },
    { kind: "code", text: "for b in profit:\n    print(b)" },
    { kind: "text", text: "(a) Find the errors." },
  ]);
});

test("een vraag zonder code is één tekstblok, met de opties onder elkaar", () => {
  assert.deepEqual(questionBlocks("Which? a) one b) two"), [{ kind: "text", text: "Which?\na) one\nb) two" }]);
});

test("punten houden hun kwarten", () => {
  assert.equal(examPoints(0.75), "0,75");
  assert.equal(examPoints(0.5), "0,5");
  assert.equal(examPoints(33), "33");
  assert.equal(examPoints(88.5), "88,5");
  assert.equal(examPoints(13.333333), "13,33");
});


test("een scenario zegt wat je bij je laatste poging haalde, of dat je hem nog niet deed", () => {
  assert.equal(scenarioResult({ points: 0.5, last_score: 0.3 }), "0,3 van 0,5");
  assert.equal(scenarioResult({ points: 4, last_score: 4 }), "4 van 4");
  assert.equal(scenarioResult({ points: 0.75, last_score: 0 }), "0 van 0,75");
  assert.equal(scenarioResult({ points: 0.5, last_score: null }), "nog niet geoefend");
});

test("hoeveel scenario's je al deed, alleen als dat er minstens één is", () => {
  const rij = (last_score) => ({ points: 0.5, last_score });
  assert.equal(scenarioProgress([rij(null), rij(null)]), "");
  assert.equal(scenarioProgress([rij(0.5), rij(null), rij(0)]), "2 van 3 geoefend");
  assert.equal(scenarioProgress([rij(0.5)]), "1 van 1 geoefend");
});

test("de knop noemt hoeveel scenario's hij openklapt", () => {
  assert.equal(scenarioCount(6), "6 scenario's");
  assert.equal(scenarioCount(1), "1 scenario");
});
