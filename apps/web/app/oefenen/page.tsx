import { Suspense } from "react";

import { PracticeConsole } from "@/components/practice/practice-console";

// Suspense: de console leest zoekparameters (useSearchParams), en zonder
// grens weigert Next de pagina te bouwen.
export default function Page() {
  return (
    <Suspense fallback={null}>
      <PracticeConsole />
    </Suspense>
  );
}
