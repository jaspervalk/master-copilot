import { Suspense } from "react";

import { ExamConsole } from "@/components/exam/exam-console";

// Suspense: de console leest zoekparameters (useSearchParams), en zonder
// grens weigert Next de pagina te bouwen.
export default function Page() {
  return (
    <Suspense fallback={null}>
      <ExamConsole />
    </Suspense>
  );
}
