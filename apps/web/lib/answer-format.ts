// Het antwoordmodel krijgt de instructie om $...$ te gebruiken, maar de
// gesprekken die er al staan bevatten \( \) en \[ \]. Beide vormen omzetten
// naar dollartekens is goedkoper dan remark-math een tweede notatie leren, en
// houdt oude antwoorden leesbaar.
const DISPLAY_MATH = /\\\[([\s\S]*?)\\\]/g;
const INLINE_MATH = /\\\(([\s\S]*?)\\\)/g;
// Elk $$…$$-paar, ook over meerdere regels heen, in documentvolgorde.
const DOLLAR_BLOCK = /\$\$([\s\S]+?)\$\$/g;

// De canonieke vorm die micromark als blokformule herkent: fences alleen op
// hun eigen regel, de formule ertussen. Alles wat daarvan afwijkt gaat mis:
//   - `$$x$$` op één regel is gewone inline-wiskunde, midden in de zin;
//   - `$$Var(X)=` met tekst achter de openingsfence is een fence met een
//     info-string — die eerste regel wordt als metadata weggegooid;
//   - `\end{cases}$$` sluit niets af, want een sluitfence moet alleen staan.
//     Het blok slokt dan de rest van het antwoord op en KaTeX faalt op de reus.
// Het model krijgt de instructie om het goed te doen, maar doet dat niet
// altijd; hier wordt het onvoorwaardelijk rechtgezet.
function asBlock(body: string): string {
  return `\n\n$$\n${body.trim()}\n$$\n\n`;
}

export function toDollarDelimiters(text: string): string {
  return (
    text
      // Eerst alleen de notatie gelijktrekken; de laatste pas zet élk
      // $$-paar in één keer in blokvorm, dus hier niet al omhullen.
      .replace(DISPLAY_MATH, (_match, body: string) => `$$${body}$$`)
      .replace(INLINE_MATH, (_match, body: string) => `$${body.trim()}$`)
      .replace(DOLLAR_BLOCK, (_match, body: string) => asBlock(body))
  );
}

// Hetzelfde scheidingsteken als de chunker in de backend gebruikt om een
// sectiepad op te bouwen.
export const SECTION_SEPARATOR = " › ";
