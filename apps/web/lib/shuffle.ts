/** Een nieuwe volgorde voor de opties van een meerkeuzevraag: de oorspronkelijke
 *  indexen in de volgorde waarin ze getoond worden.
 *
 *  Een kaart die je fout had komt terug, en stond hij elke keer in dezelfde
 *  volgorde, dan onthield je de plek van het antwoord in plaats van het
 *  antwoord. Daarom ook nooit de oorspronkelijke volgorde.
 *
 *  `random` is in te voeren, zodat een test de uitkomst kan vastleggen. */
export function shuffledOrder(length: number, random: () => number = Math.random): number[] {
  const order = Array.from({ length }, (_, index) => index);
  // Fisher-Yates: elke volgorde even waarschijnlijk.
  for (let i = length - 1; i > 0; i--) {
    const j = Math.floor(random() * (i + 1));
    [order[i], order[j]] = [order[j], order[i]];
  }
  if (length > 1 && order.every((value, index) => value === index)) {
    order.push(order.shift() as number);
  }
  return order;
}
