// node --experimental-strip-types --test lib/*.test.mjs   (of: npm test)
import assert from "node:assert/strict";
import { test } from "node:test";

import { applyTheme, choiceToStore, resolveTheme, THEME_SCRIPT, THEME_STORAGE_KEY } from "./theme.ts";


/** Net genoeg van `document` en `window` om het script in <head> te draaien. */
function fakeBrowser({ stored = null, prefersDark = false, storageThrows = false } = {}) {
  const classes = new Set();
  const root = {
    classList: {
      toggle: (name, on) => (on ? classes.add(name) : classes.delete(name)),
      contains: (name) => classes.has(name),
    },
  };
  const localStorage = {
    getItem: (key) => {
      if (storageThrows) throw new Error("SecurityError");
      return key === THEME_STORAGE_KEY ? stored : null;
    },
  };
  const matchMedia = (query) => ({ matches: query === "(prefers-color-scheme: dark)" && prefersDark });
  return { document: { documentElement: root }, localStorage, matchMedia, root, classes };
}

function runScript(browser) {
  new Function("document", "localStorage", "matchMedia", THEME_SCRIPT)(
    browser.document,
    browser.localStorage,
    browser.matchMedia,
  );
}


test("zonder eigen keuze volgt het thema het systeem", () => {
  assert.equal(resolveTheme(null, false), "light");
  assert.equal(resolveTheme(null, true), "dark");
});

test("een eigen keuze wint van het systeem", () => {
  assert.equal(resolveTheme("dark", false), "dark");
  assert.equal(resolveTheme("light", true), "light");
});

test("een onbekende opgeslagen waarde telt als geen keuze", () => {
  assert.equal(resolveTheme("sepia", true), "dark");
  assert.equal(resolveTheme("", false), "light");
});

test("een keuze gelijk aan het systeem wordt niet bewaard: dan volgt de app het systeem weer", () => {
  // Anders zet één keer heen en terug klikken het volgen voorgoed uit.
  assert.equal(choiceToStore("dark", true), null);
  assert.equal(choiceToStore("light", false), null);
  assert.equal(choiceToStore("dark", false), "dark");
  assert.equal(choiceToStore("light", true), "light");
});

test("applyTheme zet en haalt de klasse dark", () => {
  const browser = fakeBrowser();
  applyTheme(browser.root, "dark");
  assert.ok(browser.classes.has("dark"));
  applyTheme(browser.root, "light");
  assert.ok(!browser.classes.has("dark"));
});

test("het script in <head> past dezelfde regel toe vóór de eerste verf", () => {
  const systemDark = fakeBrowser({ prefersDark: true });
  runScript(systemDark);
  assert.ok(systemDark.classes.has("dark"));

  const chosenLight = fakeBrowser({ stored: "light", prefersDark: true });
  runScript(chosenLight);
  assert.ok(!chosenLight.classes.has("dark"));
});

test("geblokkeerde opslag (privévenster) laat het script niet vallen: dan het systeem", () => {
  const browser = fakeBrowser({ prefersDark: true, storageThrows: true });
  assert.doesNotThrow(() => runScript(browser));
  assert.ok(browser.classes.has("dark"));
});
