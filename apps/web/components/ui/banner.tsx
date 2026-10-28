import type { ReactNode } from "react";


type Tone = "info" | "success" | "warning" | "danger";

const toneClasses: Record<Tone, string> = {
  info: "bg-ink-50 text-ink-700 border-ink-200",
  success: "bg-emerald-50 text-emerald-800 border-emerald-200",
  warning: "bg-amber-50 text-amber-800 border-amber-200",
  danger: "bg-rose-50 text-rose-800 border-rose-200",
};


export function Banner({
  tone = "info",
  children,
  className = "",
}: {
  tone?: Tone;
  children: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={`rounded-md border px-3 py-2 text-sm ${toneClasses[tone]} ${className}`}
      role="status"
    >
      {children}
    </div>
  );
}
