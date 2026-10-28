import { Suspense } from "react";

import { WeekConsole } from "@/components/weeks/week-console";

// Suspense: de console leest zoekparameters (useSearchParams), en zonder
// grens weigert Next de pagina te bouwen.
export default function Page() {
  return (
    <Suspense fallback={null}>
      <WeekConsole />
    </Suspense>
  );
}
