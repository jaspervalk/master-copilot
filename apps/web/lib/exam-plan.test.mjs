import assert from "node:assert/strict";
import { test } from "node:test";

import { examSetNotice, minutesLeft, planDays, stepDone, stepProgress } from "./exam-plan.ts";


const sets = [
  { origin: "oefententamen-4", question_count: 34, answered: 12 },
  { origin: "voorbeelden-college-13", question_count: 6, answered: 6 },
];
const steps = [
  { id: "a", day: "maandag", minutes: 40, exam: null },
  { id: "b", day: "maandag", minutes: 20, exam: "voorbeelden-college-13" },
  { id: "c", day: "dinsdag", minutes: 90, exam: "oefententamen-4" },
];

test("een oefententamen is af als elke vraag een poging heeft, de rest met een vinkje", () => {
  const none = new Set();
  assert.equal(stepDone(steps[0], sets, none), false);
  assert.equal(stepDone(steps[0], sets, new Set(["a"])), true);
  assert.equal(stepDone(steps[1], sets, none), true);
  assert.equal(stepDone(steps[2], sets, new Set(["c"])), false, "een vinkje maakt een tentamen niet af");
  assert.deepEqual(stepProgress(steps[2], sets), { answered: 12, total: 34 });
  assert.equal(stepProgress(steps[0], sets), null);
});

test("een tentamen dat er niet is, is niet af", () => {
  assert.equal(stepDone({ id: "x", day: "", minutes: 10, exam: "bestaat-niet" }, sets, new Set()), false);
});

test("stappen worden per dag gegroepeerd, in volgorde", () => {
  assert.deepEqual(planDays(steps).map((day) => [day.day, day.steps.map((step) => step.id)]), [
    ["maandag", ["a", "b"]],
    ["dinsdag", ["c"]],
  ]);
});

test("minuten die nog openstaan", () => {
  assert.equal(minutesLeft(steps, sets, new Set()), 130);
  assert.equal(minutesLeft(steps, sets, new Set(["a"])), 90);
});

test("de tijd voor een set volgt het tempo van het tentamen, niet altijd twee uur", () => {
  assert.equal(examSetNotice(19, 27, 1.2), "19 vragen, 27 punten: in het tempo van het tentamen ongeveer 30 minuten.");
  assert.equal(examSetNotice(34, 100, 1.2), "34 vragen, 100 punten: in het tempo van het tentamen ongeveer 120 minuten.");
  assert.equal(examSetNotice(14, 7.75, 120 / 9), "14 vragen, 7,75 punten: in het tempo van het tentamen ongeveer 105 minuten.");
  assert.equal(examSetNotice(6, 12, null), "6 vragen, 12 punten.");
});
