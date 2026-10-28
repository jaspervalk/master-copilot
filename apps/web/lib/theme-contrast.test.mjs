// node --experimental-strip-types --test lib/*.test.mjs   (of: npm test)
//
// De kleuren staan als CSS-variabelen in app/globals.css: één set voor licht
// (`:root`) en één voor donker (`.dark`). Een donkere waarde kies je op het oog,
// en dan zie je pas op de pagina dat grijze tekst wegvalt. Daarom hier de paren
// die de app echt gebruikt, nagerekend volgens WCAG, in beide thema's.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

const css = readFileSync(new URL("../app/globals.css", import.meta.url), "utf8");


function block(selector) {
  const match = css.match(new RegExp(`${selector}\\s*\\{([^}]*)\\}`));
  assert.ok(match, `geen blok ${selector} in globals.css`);
  return match[1];
}

function variables(body) {
  return new Map([...body.matchAll(/--([\w-]+):\s*([^;]+);/g)].map((m) => [m[1], m[2].trim()]));
}

const themes = { licht: variables(block(":root")), donker: variables(block("\\.dark")) };


function rgb(theme, name) {
  const value = themes[theme].get(name);
  assert.ok(value, `--${name} ontbreekt in ${theme}`);
  const channels = value.split(/\s+/).map(Number);
  assert.equal(channels.length, 3, `--${name} is geen "r g b"-drietal: ${value}`);
  return channels;
}

function luminance([r, g, b]) {
  const linear = (c) => {
    const s = c / 255;
    return s <= 0.04045 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * linear(r) + 0.7152 * linear(g) + 0.0722 * linear(b);
}

function contrast(theme, fg, bg) {
  const [a, b] = [luminance(rgb(theme, fg)), luminance(rgb(theme, bg))].sort((x, y) => y - x);
  return (a + 0.05) / (b + 0.05);
}


// [voorgrond, achtergrond, minimum, waar het staat]
const PAIRS = [
  ["ink-900", "card", 4.5, "koppen"],
  ["ink-800", "surface", 4.5, "lopende tekst op de pagina"],
  ["ink-800", "card", 4.5, "lopende tekst op een kaart"],
  ["ink-700", "card", 4.5, "tekst op een kaart"],
  ["ink-600", "card", 4.5, "tekst op een kaart"],
  ["ink-500", "card", 4.5, "secundaire tekst"],
  ["ink-500", "surface", 4.5, "secundaire tekst en de navigatie"],
  // Bijschriften: licht haalt hier 3,7 en dat blijft zo; donker mag niet slechter.
  ["ink-400", "card", 3, "bijschriften"],
  ["ink-400", "surface", 3, "bijschriften"],
  ["ink-700", "ink-50", 4.5, "Banner info, codeblok"],
  ["ink-700", "ink-100", 4.5, "Badge neutraal"],
  ["ink-900", "ink-100", 4.5, "actief menu-item"],
  ["primary-600", "card", 4.5, "links en labels"],
  ["primary-500", "card", 4.5, "link onder de muis"],
  ["primary-600", "primary-50", 4.5, "gekozen stand"],
  ["on-fill", "primary-500", 4.5, "hoofdknop, tellers, eigen vraag"],
  ["on-fill", "primary-600", 4.5, "hoofdknop onder de muis"],
  ["on-fill", "accent-500", 4.5, "gevaarknop, teller te laat"],
  ["on-fill", "accent-600", 4.5, "gevaarknop onder de muis"],
  ["accent-600", "card", 4.5, "waarschuwingstekst"],
  ["accent-600", "accent-50", 4.5, "Badge accent"],
  ["rose-800", "rose-50", 4.5, "Banner en Badge fout"],
  ["rose-700", "card", 4.5, "foutmelding"],
  ["emerald-800", "emerald-50", 4.5, "Banner en Badge gelukt"],
  ["amber-800", "amber-50", 4.5, "Banner en Badge waarschuwing"],
];

for (const theme of Object.keys(themes)) {
  for (const [fg, bg, minimum, where] of PAIRS) {
    test(`${theme}: ${fg} op ${bg} (${where}) haalt ${minimum}:1`, () => {
      const ratio = contrast(theme, fg, bg);
      assert.ok(ratio >= minimum, `${ratio.toFixed(2)}:1`);
    });
  }
}


test("elk token heeft een donkere waarde", () => {
  // Een vergeten variabele valt in donker terug op de lichte waarde: een witte
  // kaart midden op een donkere pagina.
  const missing = [...themes.licht.keys()].filter((name) => !themes.donker.has(name));
  assert.deepEqual(missing, []);
});

test("in donker is de pagina donker en de kaart er net boven", () => {
  assert.ok(luminance(rgb("donker", "surface")) < 0.02);
  assert.ok(luminance(rgb("donker", "card")) > luminance(rgb("donker", "surface")));
});
