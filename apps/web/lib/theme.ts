/**
 * Licht of donker.
 *
 * Zonder eigen keuze volgt de app het systeem; de schakelaar in de kop legt een
 * afwijkende keuze vast in localStorage, en die wint daarna. Het thema is
 * alleen de klasse `dark` op <html>: de kleuren zelf zijn CSS-variabelen
 * (app/globals.css) die onder `.dark` een andere waarde krijgen, en
 * `color-scheme` draait daar mee.
 */

export type Theme = "light" | "dark";

export const THEME_STORAGE_KEY = "theme";


export function resolveTheme(stored: string | null, prefersDark: boolean): Theme {
  return stored === "light" || stored === "dark" ? stored : prefersDark ? "dark" : "light";
}


export function applyTheme(root: { classList: { toggle(name: string, on: boolean): unknown } }, theme: Theme) {
  root.classList.toggle("dark", theme === "dark");
}


/**
 * Draait in <head>, vóór de eerste verf: anders zie je bij elke laadbeurt eerst
 * een witte pagina die daarna donker wordt. Het script ís de twee functies
 * hierboven (`toString`), zodat de regel maar op één plek staat. Opslag kan
 * geblokkeerd zijn (privévenster); dan het systeem.
 */
export const THEME_SCRIPT = `(function () {
  var resolveTheme = ${resolveTheme.toString()};
  var applyTheme = ${applyTheme.toString()};
  var stored = null;
  try { stored = localStorage.getItem(${JSON.stringify(THEME_STORAGE_KEY)}); } catch (error) {}
  applyTheme(document.documentElement, resolveTheme(stored, matchMedia("(prefers-color-scheme: dark)").matches));
})();`;


/**
 * Wat er na een klik bewaard wordt. Is de keuze gelijk aan het systeem, dan
 * niets: anders zet één keer heen en terug klikken het volgen voorgoed uit, en
 * blijft de app 's avonds licht terwijl de rest van de computer donker wordt.
 */
export function choiceToStore(theme: Theme, prefersDark: boolean): Theme | null {
  return theme === (prefersDark ? "dark" : "light") ? null : theme;
}


/**
 * Wisselen zonder naloop. Knoppen en velden hebben een overgang van 140 ms op
 * kleur (globals.css); zonder deze klasse springt de pagina om en faden zij
 * erachteraan, en midden in die fade is de tekst van een knop onleesbaar.
 * De stijl wordt eerst doorgerekend met de overgang uit, pas dan mag hij terug.
 */
export function switchTheme(root: HTMLElement, theme: Theme) {
  root.classList.add("theme-switching");
  applyTheme(root, theme);
  getComputedStyle(root).color;
  requestAnimationFrame(() => root.classList.remove("theme-switching"));
}


export function readStoredTheme(): string | null {
  try {
    return localStorage.getItem(THEME_STORAGE_KEY);
  } catch {
    return null;
  }
}


export function storeTheme(theme: Theme | null) {
  try {
    if (theme === null) localStorage.removeItem(THEME_STORAGE_KEY);
    else localStorage.setItem(THEME_STORAGE_KEY, theme);
  } catch {
    // Niet te bewaren: dan geldt de keuze tot de volgende laadbeurt.
  }
}
