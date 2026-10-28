import type { Config } from "tailwindcss";


// Elke kleur is een CSS-variabele uit app/globals.css, met de waarden voor licht
// in `:root` en voor donker in `.dark`. Zo is `text-ink-900` in beide thema's
// dezelfde klasse en hoeft geen component `dark:` te kennen. `<alpha-value>`
// houdt `bg-surface/80` en dergelijke werkend.
const themed = (name: string) => `rgb(var(--${name}) / <alpha-value>)`;

const ramp = (name: string, shades: number[]) =>
  Object.fromEntries(shades.map((shade) => [shade, themed(`${name}-${shade}`)]));


const config: Config = {
  darkMode: "class",
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        ink: ramp("ink", [50, 100, 200, 300, 400, 500, 600, 700, 800, 900]),
        primary: ramp("primary", [50, 100, 200, 400, 500, 600]),
        accent: ramp("accent", [50, 100, 400, 500, 600]),
        // Alleen de tinten die Banner en Badge gebruiken; de rest van deze
        // reeksen blijft van Tailwind en draait dus niet mee in donker.
        rose: ramp("rose", [50, 200, 700, 800]),
        emerald: ramp("emerald", [50, 200, 800]),
        amber: ramp("amber", [50, 200, 800]),
        surface: themed("surface"),
        canvas: themed("canvas"),
        // De kaart: wit in licht. `bg-white` draait niet mee, en hoort dus
        // alleen nog waar het echt wit moet blijven (een figuur van matplotlib).
        card: themed("card"),
        "on-fill": themed("on-fill"),
        // Met eigen doorzichtigheid per thema: in donker moet hij zwaarder.
        scrim: "rgb(var(--scrim))",
      },
      borderRadius: {
        sm: "6px",
        DEFAULT: "10px",
        md: "12px",
        lg: "16px",
        xl: "20px",
      },
      boxShadow: {
        soft: "var(--shadow-soft)",
        lift: "var(--shadow-lift)",
      },
      fontFamily: {
        sans: ["var(--font-sans)", "ui-sans-serif", "system-ui", "sans-serif"],
        display: ["var(--font-display)", "ui-serif", "Georgia", "serif"],
      },
    },
  },
  plugins: [],
};

export default config;
