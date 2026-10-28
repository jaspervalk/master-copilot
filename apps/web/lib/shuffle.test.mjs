// node --experimental-strip-types --test lib/*.test.mjs   (of: npm test)
// Een .mjs, zodat tsc hem niet meeneemt: de import van een .ts-bestand met
// extensie is voor Node nodig en voor de rest van het project niet toegestaan.
import assert from "node:assert/strict";
import { test } from "node:test";

import { shuffledOrder } from "./shuffle.ts";


/** Een vaste reeks "toevalsgetallen", zodat de uitkomst vastligt. */
function sequence(...values) {
  let index = 0;
  return () => values[index++ % values.length];
}

test("de volgorde is een herschikking van alle opties", () => {
  for (let length = 0; length <= 6; length++) {
    const order = shuffledOrder(length);
    assert.deepEqual([...order].sort((a, b) => a - b), Array.from({ length }, (_, index) => index));
  }
});

test("hetzelfde toeval geeft dezelfde volgorde (Fisher-Yates)", () => {
  // i=3: j=floor(0.1*4)=0 → [3,1,2,0]; i=2: j=floor(0.5*3)=1 → [3,2,1,0]; i=1: j=floor(0.9*2)=1 → ongewijzigd.
  assert.deepEqual(shuffledOrder(4, sequence(0.1, 0.5, 0.9)), [3, 2, 1, 0]);
});

test("nooit de oorspronkelijke volgorde: dan zou je het antwoord op zijn plek herkennen", () => {
  // 0.999 laat bij Fisher-Yates alles staan; dan schuift de volgorde één plek op.
  assert.deepEqual(shuffledOrder(4, () => 0.999), [1, 2, 3, 0]);
  assert.notDeepEqual(shuffledOrder(2, () => 0.999), [0, 1]);
});

test("nul of één optie valt niet te husselen", () => {
  assert.deepEqual(shuffledOrder(0), []);
  assert.deepEqual(shuffledOrder(1), [0]);
});
