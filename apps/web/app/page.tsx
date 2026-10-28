import { Suspense } from "react";

import { ChatWorkspace } from "@/components/chat/chat-workspace";

// Suspense: de console leest zoekparameters (useSearchParams), en zonder
// grens weigert Next de pagina te bouwen.
export default function Page() {
  return (
    <Suspense fallback={null}>
      <ChatWorkspace />
    </Suspense>
  );
}
